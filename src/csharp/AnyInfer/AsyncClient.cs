using AnyInfer.Core;
using AnyInfer.Internal;
using System.Runtime.ExceptionServices;
using AnyInfer.Providers;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Schema;

namespace AnyInfer;

/// <summary>Owns provider adapters and creates lazy generation operations.</summary>
public sealed class AsyncClient : IAsyncDisposable
{
    private readonly ProviderPool _pool;
    private readonly IOperationClock _clock;
    private readonly RouteState _health;
    private readonly Route? _defaultRoute;
    private readonly Repair? _defaultRepair;
    private readonly AnyInfer.Catalog.Catalog _catalog;
    private readonly CapabilityStore _capabilities;
    private readonly TargetMetadataResolver _targetResolver;
    private readonly TargetResolutionProfile _resolutionProfile;
    private readonly SchemaValidationOptions? _schemaValidation;
    private readonly object _gate = new();
    private readonly HashSet<AsyncStream> _activeStreams = [];
    private readonly HashSet<LifecycleReservation> _lifecycleOperations = [];
    private readonly CancellationTokenSource _lifetime = new();
    private Task<Exception?>? _lifetimeSignal;
    private bool _disposed;
    private Task? _disposeTask;

    /// <summary>Creates a client over immutable provider settings and descriptor metadata.</summary>
    public AsyncClient(
        IEnumerable<ProviderSettings>? providers = null,
        Providers.ProviderRegistry? registry = null,
        Credentials.ResolverChain? resolver = null,
        Route? route = null,
        Repair? repair = null,
        AnyInfer.Catalog.Catalog? catalog = null,
        PricingTable? pricingTable = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>? capabilityOverrides = null,
        SchemaValidationOptions? schemaValidation = null)
    {
        var descriptors = registry ?? Providers.ProviderRegistry.CreateDefault();
        _pool = new ProviderPool(providers, descriptors, resolver ?? Credentials.ResolverChain.CreateDefault());
        _clock = new SystemOperationClock();
        _health = new RouteState(_clock);
        _defaultRoute = route;
        _defaultRepair = repair;
        _catalog = catalog ?? AnyInfer.Catalog.Catalog.LoadDefault();
        _capabilities = new CapabilityStore(pricingTable, capabilityOverrides);
        _targetResolver = new TargetMetadataResolver(_catalog, _pool.DescriptorSnapshot, () => _pool.Bindings, _pool);
        _resolutionProfile = TargetResolutionProfile.PublicSdk;
        _schemaValidation = schemaValidation;
    }

    /// <summary>Creates a client over externally constructed adapters.</summary>
    public static AsyncClient FromAdapters(IEnumerable<ProviderRegistration> providers, SchemaValidationOptions? schemaValidation = null) =>
        new(providers, new SystemOperationClock(), publicSdk: true, schemaValidation);

    /// <summary>Creates a client from inert parsed configuration without performing I/O or credential resolution.</summary>
    public static AsyncClient FromConfig(
        Config.AnyInferConfig config,
        Providers.ProviderRegistry? registry = null,
        Credentials.ResolverChain? resolver = null,
        AnyInfer.Catalog.Catalog? catalog = null,
        PricingTable? pricingTable = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>? capabilityOverrides = null,
        SchemaValidationOptions? schemaValidation = null)
    {
        ArgumentNullException.ThrowIfNull(config);
        return new AsyncClient(config.Providers, registry, resolver, config.Route, config.Repair, catalog, pricingTable, capabilityOverrides, schemaValidation);
    }

    internal AsyncClient(IEnumerable<ProviderRegistration> providers, IOperationClock clock)
        : this(providers, clock, publicSdk: false, schemaValidation: null)
    {
    }

    private AsyncClient(IEnumerable<ProviderRegistration> providers, IOperationClock clock, bool publicSdk, SchemaValidationOptions? schemaValidation)
    {
        _pool = new ProviderPool(providers);
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        _health = new RouteState(_clock);
        _catalog = AnyInfer.Catalog.Catalog.LoadDefault();
        _capabilities = new CapabilityStore();
        _targetResolver = new TargetMetadataResolver(
            _catalog,
            publicSdk ? new Providers.ProviderRegistry([]) : null,
            () => _pool.Bindings,
            _pool);
        _resolutionProfile = publicSdk ? TargetResolutionProfile.PublicSdk : TargetResolutionProfile.FrozenV0;
        _schemaValidation = schemaValidation;
    }

    internal RouteState Health => _health;

    /// <summary>Gets the immutable catalog used by pure target resolution.</summary>
    public AnyInfer.Catalog.Catalog Catalog => _catalog;

    /// <summary>Resolves a target without credentials, factories, or network work.</summary>
    public ResolvedTarget Resolve(string target) => _targetResolver.Resolve(target, TargetResolutionProfile.PublicSdk).Target;

    /// <summary>Gets assembled immutable capability facts without constructing an adapter.</summary>
    public ModelCapabilities Capabilities(string target)
    {
        var resolved = _targetResolver.Resolve(target, TargetResolutionProfile.PublicSdk);
        return _capabilities.CapabilitiesFor(resolved.Descriptor, resolved.Target.ProviderId, resolved.Target.Model, _pool.EffectiveLocality(resolved));
    }

    /// <summary>Lists models for one selected provider instance and optionally filters by operation.</summary>
    public Task<IReadOnlyList<DiscoveredModel>> ModelsAsync(
        string providerId,
        InferenceOperation? operation = null,
        CancellationToken cancellationToken = default)
    {
        if (operation is { } requested && !Enum.IsDefined(requested))
        {
            throw new ArgumentOutOfRangeException(nameof(operation));
        }

        return ModelsCoreAsync(providerId, operation, cancellationToken, CancellationIdentityContext.Resolve(cancellationToken));
    }

    /// <summary>Gets a health observation for one selected provider instance.</summary>
    public Task<Health> HealthAsync(string providerId, CancellationToken cancellationToken = default) =>
        HealthCoreAsync(providerId, cancellationToken, CancellationIdentityContext.Resolve(cancellationToken));

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
        SchemaSpec? schema = null,
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
        SchemaSpec? schema = null,
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
        SchemaSpec? schema = null,
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
        SchemaSpec? schema = null,
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
        var normalized = RequestNormalizer.Normalize(
            effectiveRequest,
            _resolutionProfile == TargetResolutionProfile.PublicSdk,
            _resolutionProfile == TargetResolutionProfile.PublicSdk ? SchemaExecutionProfile.ModernSdk : SchemaExecutionProfile.FrozenV0,
            _schemaValidation);
        AsyncStream? stream = null;
        stream = new AsyncStream(
            this,
            SyncExecutionContext.CurrentClient,
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
        if (ReferenceEquals(AsyncExecutionContext.CurrentAsyncClient, this))
        {
            throw new InvalidOperationException("An AsyncClient cannot be disposed from an active client-owned callback.");
        }

        AsyncStream[] streams;
        LifecycleReservation[] operations;
        lock (_gate)
        {
            if (_disposeTask is null)
            {
                _disposed = true;
                streams = _activeStreams.ToArray();
                operations = _lifecycleOperations.ToArray();
                _activeStreams.Clear();
                _disposeTask = DisposeCoreAsync(streams, operations);
            }

            return new ValueTask(_disposeTask);
        }
    }

    private async Task DisposeCoreAsync(AsyncStream[] streams, LifecycleReservation[] operations)
    {
        Exception? failure = null;
        var lifetimeSignal = SignalLifetimeAsync();
        var streamSignals = streams.Select(static stream => stream.BeginCloseAsync()).ToArray();
        var operationSignals = operations.Select(static operation => operation.SignalCancelAsync()).ToArray();
        var signalFailures = await Task.WhenAll(streamSignals.Concat(operationSignals).Append(lifetimeSignal)).ConfigureAwait(false);
        foreach (var signalFailure in signalFailures) failure ??= signalFailure;
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
            await Task.WhenAll(operations.Select(static operation => operation.Completion)).ConfigureAwait(false);
            await _pool.DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }
        finally
        {
            _lifetime.Dispose();
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
                _targetResolver,
                _resolutionProfile,
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

    private async Task<IReadOnlyList<DiscoveredModel>> ModelsCoreAsync(
        string providerId,
        InferenceOperation? operation,
        CancellationToken cancellationToken,
        CancellationToken callerIdentity)
    {
        var reservation = ReserveLifecycle(cancellationToken, callerIdentity);
        using var context = AsyncExecutionContext.Push(this, reservation.SyncOwner);
        using var identity = CancellationIdentityContext.Push(reservation.Token, reservation.CallerIdentity);
        try
        {
            var state = _pool.ResolveLifecycleInstance(providerId);
            var adapter = await _pool.GetAdapterAsync(state, reservation.Token, reservation.CallerIdentity).ConfigureAwait(false);
            if (adapter is not IProviderLifecycle lifecycle)
            {
                throw new UnsupportedInputException("Model discovery is not supported by this provider.", state.InstanceId, "discover");
            }

            var listed = await lifecycle.ListModelsAsync(reservation.Token).ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            var snapshot = Array.AsReadOnly((listed ?? throw new InvalidOperationException("A provider returned no model listing.")).ToArray());
            _capabilities.RecordDiscovery(state.InstanceId, snapshot);
            reservation.ThrowIfCallerCancelled();
            return Array.AsReadOnly(FilterModels(snapshot, state, operation, adapter).ToArray());
        }
        finally
        {
            await CompleteLifecycleAsync(reservation).ConfigureAwait(false);
        }
    }

    private async Task<Health> HealthCoreAsync(
        string providerId,
        CancellationToken cancellationToken,
        CancellationToken callerIdentity)
    {
        var reservation = ReserveLifecycle(cancellationToken, callerIdentity);
        using var context = AsyncExecutionContext.Push(this, reservation.SyncOwner);
        using var identity = CancellationIdentityContext.Push(reservation.Token, reservation.CallerIdentity);
        try
        {
            var state = _pool.ResolveLifecycleInstance(providerId);
            var adapter = await _pool.GetAdapterAsync(state, reservation.Token, reservation.CallerIdentity).ConfigureAwait(false);
            if (adapter is not IProviderLifecycle lifecycle)
            {
                throw new UnsupportedInputException("Health discovery is not supported by this provider.", state.InstanceId, "discover");
            }

            var health = await lifecycle.HealthAsync(reservation.Token).ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            return health ?? throw new InvalidOperationException("A provider returned no health observation.");
        }
        finally
        {
            await CompleteLifecycleAsync(reservation).ConfigureAwait(false);
        }
    }

    private IEnumerable<DiscoveredModel> FilterModels(
        IReadOnlyList<DiscoveredModel> models,
        ProviderPool.InstanceState state,
        InferenceOperation? operation,
        IProviderAdapter adapter)
    {
        if (operation is null) return models;
        return models.Where(model => SupportsOperation(state, model, operation.Value, adapter));
    }

    private static bool SupportsOperation(
        ProviderPool.InstanceState state,
        DiscoveredModel model,
        InferenceOperation operation,
        IProviderAdapter adapter)
    {
        if (model.Capabilities?.Operations is { } operations)
        {
            return operations.Value.Contains(operation);
        }

        if (state.Descriptor is { } descriptor)
        {
            return operation switch
            {
                InferenceOperation.Embedding => descriptor.StaticEmbeddingCapabilities.ContainsKey(model.Id),
                InferenceOperation.Rerank => descriptor.StaticRerankCapabilities.ContainsKey(model.Id),
                _ => descriptor.Operations.Contains(operation),
            };
        }

        return operation == InferenceOperation.Generation && adapter is IProviderAdapter;
    }

    private LifecycleReservation ReserveLifecycle(CancellationToken callerCancellation, CancellationToken callerIdentity)
    {
        LifecycleReservation reservation;
        lock (_gate)
        {
            ThrowIfDisposed();
            reservation = new LifecycleReservation(this, callerCancellation, callerIdentity, _lifetime.Token, SyncExecutionContext.CurrentClient);
            _lifecycleOperations.Add(reservation);
        }
        return reservation;
    }

    private async Task CompleteLifecycleAsync(LifecycleReservation reservation)
    {
        lock (_gate)
        {
            _lifecycleOperations.Remove(reservation);
        }
        await reservation.CompleteAsync().ConfigureAwait(false);
    }

    private Task<Exception?> SignalLifetimeAsync()
    {
        lock (_gate)
        {
            return _lifetimeSignal ??= LifecycleReservation.Signal(_lifetime, this, SyncExecutionContext.CurrentClient);
        }
    }

    private void RemoveActiveStream(AsyncStream stream)
    {
        lock (_gate)
        {
            _activeStreams.Remove(stream);
        }
    }

    private sealed class LifecycleReservation
    {
        private readonly AsyncClient _owner;
        private readonly CancellationToken _callerCancellation;
        private readonly CancellationTokenSource _linked;
        private readonly object _gate = new();
        private readonly TaskCompletionSource _completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private Task<Exception?>? _signal;
        private bool _completed;

        internal LifecycleReservation(
            AsyncClient owner,
            CancellationToken callerCancellation,
            CancellationToken callerIdentity,
            CancellationToken lifetime,
            Client? syncOwner)
        {
            _owner = owner;
            _callerCancellation = callerCancellation;
            CallerIdentity = callerIdentity;
            _linked = CancellationTokenSource.CreateLinkedTokenSource(callerCancellation, lifetime);
            SyncOwner = syncOwner;
        }

        internal Client? SyncOwner { get; }
        internal CancellationToken CallerIdentity { get; }
        internal CancellationToken Token => _linked.Token;
        internal Task Completion => _completion.Task;

        internal void ThrowIfCallerCancelled()
        {
            CallerIdentity.ThrowIfCancellationRequested();
            Token.ThrowIfCancellationRequested();
        }

        internal Task<Exception?> SignalCancelAsync()
        {
            lock (_gate)
            {
                if (_completed)
                {
                    return Task.FromResult<Exception?>(null);
                }
                return _signal ??= Task.Run(() => SignalCore(_linked, _owner, SyncOwner));
            }
        }

        internal async Task CompleteAsync()
        {
            Task<Exception?>? signal;
            lock (_gate)
            {
                signal = _signal;
                _completed = true;
            }
            if (signal is not null)
            {
                await signal.ConfigureAwait(false);
            }
            _completion.TrySetResult();
            _linked.Dispose();
        }

        internal static Task<Exception?> Signal(CancellationTokenSource source, AsyncClient owner, Client? syncOwner) =>
            Task.Run(() => SignalCore(source, owner, syncOwner));

        private static Exception? SignalCore(CancellationTokenSource source, AsyncClient owner, Client? syncOwner)
        {
            try
            {
                using var asyncContext = AsyncExecutionContext.Push(owner, syncOwner);
                using var syncContext = syncOwner is null ? null : SyncExecutionContext.Push(syncOwner);
                source.Cancel();
                return null;
            }
            catch (Exception exception)
            {
                return exception;
            }
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
        SchemaSpec? schema,
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

        selectedRoute ??= _defaultRoute ?? throw new ConfigException("Specify a target, route, or client default route.");

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
