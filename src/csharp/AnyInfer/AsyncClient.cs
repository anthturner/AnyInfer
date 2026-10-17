using AnyInfer.Core;
using AnyInfer.Internal;
using System.Runtime.ExceptionServices;
using AnyInfer.Providers;

namespace AnyInfer;

/// <summary>Owns provider adapters and creates lazy generation operations.</summary>
public sealed class AsyncClient : IAsyncDisposable
{
    private readonly ProviderPool _pool;
    private readonly IOperationClock _clock;
    private readonly RouteState _health;
    private readonly Route? _defaultRoute;
    private readonly Repair? _defaultRepair;
    private readonly object _gate = new();
    private readonly HashSet<AsyncStream> _activeStreams = [];
    private bool _disposed;
    private Task? _disposeTask;

    /// <summary>Creates a client over immutable provider settings and descriptor metadata.</summary>
    public AsyncClient(
        IEnumerable<ProviderSettings>? providers = null,
        Providers.ProviderRegistry? registry = null,
        Credentials.ResolverChain? resolver = null,
        Route? route = null,
        Repair? repair = null)
    {
        _pool = new ProviderPool(providers, registry ?? Providers.ProviderRegistry.CreateDefault(), resolver ?? Credentials.ResolverChain.CreateDefault());
        _clock = new SystemOperationClock();
        _health = new RouteState(_clock);
        _defaultRoute = route;
        _defaultRepair = repair;
    }

    /// <summary>Creates a client over externally constructed adapters.</summary>
    public static AsyncClient FromAdapters(IEnumerable<ProviderRegistration> providers) => new(providers, new SystemOperationClock());

    /// <summary>Creates a client from inert parsed configuration without performing I/O or credential resolution.</summary>
    public static AsyncClient FromConfig(
        Config.AnyInferConfig config,
        Providers.ProviderRegistry? registry = null,
        Credentials.ResolverChain? resolver = null)
    {
        ArgumentNullException.ThrowIfNull(config);
        return new AsyncClient(config.Providers, registry, resolver, config.Route, config.Repair);
    }

    internal AsyncClient(IEnumerable<ProviderRegistration> providers, IOperationClock clock)
    {
        _pool = new ProviderPool(providers);
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        _health = new RouteState(_clock);
    }

    internal RouteState Health => _health;

    /// <summary>Consumes this client's single streaming execution path to its terminal result.</summary>
    public Task<Generation> GenerateAsync(GenerationRequest request, CancellationToken cancellationToken = default) =>
        GenerateAsync(request, capture: null, cancellationToken: cancellationToken);

    /// <summary>Generates from one user prompt through the normal request path.</summary>
    public Task<Generation> GenerateAsync(
        string prompt,
        string? target = null,
        Route? route = null,
        Sampling? sampling = null,
        Repair? repair = null,
        Json.JsonValue? schema = null,
        string? schemaMechanism = null,
        double? timeoutS = null,
        int? maxResponseBytes = null,
        CancellationToken cancellationToken = default) =>
        GenerateAsync(
            CreateConvenienceRequest([Message.User(prompt)], target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, stream: false),
            cancellationToken);

    /// <summary>Generates from immutable caller messages through the normal request path.</summary>
    public Task<Generation> GenerateAsync(
        IEnumerable<Message> messages,
        string? target = null,
        Route? route = null,
        Sampling? sampling = null,
        Repair? repair = null,
        Json.JsonValue? schema = null,
        string? schemaMechanism = null,
        double? timeoutS = null,
        int? maxResponseBytes = null,
        CancellationToken cancellationToken = default) =>
        GenerateAsync(
            CreateConvenienceRequest(messages, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, stream: false),
            cancellationToken);

    internal async Task<Generation> GenerateAsync(
        GenerationRequest request,
        OperationCapture? capture,
        CancellationToken cancellationToken = default)
    {
        await using var stream = StreamAsync(request, capture, cancellationToken);
        await foreach (var _ in stream.WithCancellation(cancellationToken).ConfigureAwait(false))
        {
        }

        return stream.Result;
    }

    /// <summary>Creates a lazy single-consumer generation stream.</summary>
    public AsyncStream StreamAsync(GenerationRequest request, CancellationToken cancellationToken = default) =>
        StreamAsync(request, capture: null, cancellationToken: cancellationToken);

    /// <summary>Creates a streaming generation operation from one user prompt.</summary>
    public AsyncStream StreamAsync(
        string prompt,
        string? target = null,
        Route? route = null,
        Sampling? sampling = null,
        Repair? repair = null,
        Json.JsonValue? schema = null,
        string? schemaMechanism = null,
        double? timeoutS = null,
        int? maxResponseBytes = null,
        CancellationToken cancellationToken = default) =>
        StreamAsync(
            CreateConvenienceRequest([Message.User(prompt)], target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, stream: true),
            cancellationToken);

    /// <summary>Creates a streaming generation operation from immutable caller messages.</summary>
    public AsyncStream StreamAsync(
        IEnumerable<Message> messages,
        string? target = null,
        Route? route = null,
        Sampling? sampling = null,
        Repair? repair = null,
        Json.JsonValue? schema = null,
        string? schemaMechanism = null,
        double? timeoutS = null,
        int? maxResponseBytes = null,
        CancellationToken cancellationToken = default) =>
        StreamAsync(
            CreateConvenienceRequest(messages, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, stream: true),
            cancellationToken);

    internal AsyncStream StreamAsync(
        GenerationRequest request,
        OperationCapture? capture,
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(request);
        var effectiveRequest = request.Repair is null && _defaultRepair is not null
            ? new GenerationRequest(
                request.Messages,
                request.Route,
                request.Sampling,
                _defaultRepair,
                request.Schema,
                request.SchemaMechanism,
                request.TimeoutS,
                request.MaxResponseBytes,
                request.Stream)
            : request;
        var normalized = RequestNormalizer.Normalize(effectiveRequest);
        AsyncStream? stream = null;
        stream = new AsyncStream(
            token => RunStreamAsync(normalized, effectiveRequest.Route, capture, stream!, token),
            cancellationToken,
            RemoveActiveStream);
        lock (_gate)
        {
            ThrowIfDisposed();
            _activeStreams.Add(stream);
        }

        return stream;
    }

    /// <inheritdoc />
    public ValueTask DisposeAsync()
    {
        lock (_gate)
        {
            if (_disposeTask is null)
            {
                _disposed = true;
                _disposeTask = DisposeCoreAsync(_activeStreams.ToArray());
                _activeStreams.Clear();
            }

            return new ValueTask(_disposeTask);
        }
    }

    private async Task DisposeCoreAsync(AsyncStream[] streams)
    {
        await Task.Yield();
        Exception? failure = null;
        foreach (var stream in streams)
        {
            try
            {
                await stream.DisposeAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }
        }

        try
        {
            await _pool.DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }

        if (failure is not null)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }
    private async IAsyncEnumerable<StreamEvent> RunStreamAsync(
        NormalizedRequest normalized,
        Route route,
        OperationCapture? capture,
        AsyncStream stream,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
    {
        try
        {
            await foreach (var generationEvent in GenerationCore.ExecuteAsync(
                normalized,
                route,
                _pool,
                _health,
                _clock,
                capture,
                stream,
                cancellationToken).WithCancellation(cancellationToken).ConfigureAwait(false))
            {
                yield return generationEvent;
            }
        }
        finally
        {
            RemoveActiveStream(stream);
        }
    }

    private void RemoveActiveStream(AsyncStream stream)
    {
        lock (_gate)
        {
            _activeStreams.Remove(stream);
        }
    }
    private void ThrowIfDisposed()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                throw new ObjectDisposedException(nameof(AsyncClient));
            }
        }
    }

    private GenerationRequest CreateConvenienceRequest(
        IEnumerable<Message> messages,
        string? target,
        Route? route,
        Sampling? sampling,
        Repair? repair,
        Json.JsonValue? schema,
        string? schemaMechanism,
        double? timeoutS,
        int? maxResponseBytes,
        bool stream)
    {
        ArgumentNullException.ThrowIfNull(messages);
        var selectedRoute = route;
        if (selectedRoute is null && target is not null)
        {
            selectedRoute = _defaultRoute is null
                ? new Route([target])
                : new Route([target], _defaultRoute.Retry, _defaultRoute.HealthGate, _defaultRoute.HealthTtlS);
        }

        selectedRoute ??= _defaultRoute ?? throw new ArgumentException("Specify a target, route, or client default route.");

        return new GenerationRequest(
            messages,
            selectedRoute,
            sampling,
            repair ?? _defaultRepair,
            schema,
            schemaMechanism,
            timeoutS,
            maxResponseBytes,
            stream);
    }
}
