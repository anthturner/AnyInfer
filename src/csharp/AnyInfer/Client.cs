using AnyInfer.Config;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Credentials;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using AnyInfer.Events;
using System.Runtime.ExceptionServices;

namespace AnyInfer;

/// <summary>Provides a synchronous facade over one lifetime-owned asynchronous client.</summary>
public sealed class Client : IDisposable
{
    private readonly AsyncClient _inner;
    private readonly CancellationTokenSource _lifetime = new();
    private readonly object _gate = new();
    private readonly HashSet<SyncStream> _streams = [];
    private readonly HashSet<TaskCompletionSource> _operations = [];
    private bool _closing;
    private Task? _disposeTask;
    private TaskCompletionSource<Exception?>? _lifetimeSignalCompletion;

    /// <summary>Creates a synchronous client over immutable provider settings and descriptor metadata.</summary>
    public Client(
        IEnumerable<ProviderSettings>? providers = null,
        ProviderRegistry? registry = null,
        ResolverChain? resolver = null,
        Route? route = null,
        Repair? repair = null,
        global::AnyInfer.Catalog.Catalog? catalog = null,
        PricingTable? pricingTable = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>? capabilityOverrides = null,
        SchemaValidationOptions? schemaValidation = null,
        IEnumerable<IObserver>? observers = null,
        bool manifests = true,
        bool manifestPayloads = false)
        : this(new AsyncClient(providers, registry, resolver, route, repair, catalog, pricingTable, capabilityOverrides, schemaValidation, observers, manifests, manifestPayloads))
    {
    }

    private Client(AsyncClient inner) => _inner = inner ?? throw new ArgumentNullException(nameof(inner));

    /// <summary>Creates a synchronous client over externally constructed adapters.</summary>
    public static Client FromAdapters(
        IEnumerable<ProviderRegistration> providers,
        SchemaValidationOptions? schemaValidation = null,
        IEnumerable<IObserver>? observers = null,
        bool manifests = true,
        bool manifestPayloads = false) =>
        new(AsyncClient.FromAdapters(providers, schemaValidation, observers, manifests, manifestPayloads));

    /// <summary>Creates a synchronous client from inert parsed configuration.</summary>
    public static Client FromConfig(
        AnyInferConfig config,
        ProviderRegistry? registry = null,
        ResolverChain? resolver = null,
        global::AnyInfer.Catalog.Catalog? catalog = null,
        PricingTable? pricingTable = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>? capabilityOverrides = null,
        SchemaValidationOptions? schemaValidation = null,
        IEnumerable<IObserver>? observers = null,
        bool manifests = true,
        bool manifestPayloads = false) =>
        new(AsyncClient.FromConfig(config, registry, resolver, catalog, pricingTable, capabilityOverrides, schemaValidation, observers, manifests, manifestPayloads));

    /// <summary>Gets the immutable catalog used by pure target resolution.</summary>
    public global::AnyInfer.Catalog.Catalog Catalog => _inner.Catalog;

    /// <summary>Resolves a target without credentials, factories, or network work.</summary>
    public ResolvedTarget Resolve(string target) => _inner.Resolve(target);

    /// <summary>Gets assembled immutable capability facts without constructing an adapter.</summary>
    public ModelCapabilities Capabilities(string target) => _inner.Capabilities(target);

    /// <summary>Subscribes an observer for synchronous telemetry notifications.</summary>
    public void Subscribe(IObserver observer, bool payloads = false) => _inner.Subscribe(observer, payloads);

    /// <summary>Removes every reference-identical observer subscription.</summary>
    public void Unsubscribe(IObserver observer) => _inner.Unsubscribe(observer);

    /// <summary>Lists models for one selected provider instance and optionally filters by operation.</summary>
    public IReadOnlyList<DiscoveredModel> Models(
        string providerId,
        InferenceOperation? operation = null,
        CancellationToken cancellationToken = default) =>
        RunOperation(token => _inner.ModelsAsync(providerId, operation, token), cancellationToken);

    /// <summary>Gets a health observation for one selected provider instance.</summary>
    public Health Health(string providerId, CancellationToken cancellationToken = default) =>
        RunOperation(token => _inner.HealthAsync(providerId, token), cancellationToken);

    /// <summary>Runs ordered raw generation capability probes against one resolved target.</summary>
    public ProbeReport Probe(
        string target,
        IEnumerable<Feature>? features = null,
        double timeoutS = 30,
        bool record = true,
        CancellationToken cancellationToken = default) =>
        RunOperation(token => _inner.ProbeAsync(target, features, timeoutS, record, token), cancellationToken);
    /// <summary>Generates a terminal result from an explicit request.</summary>
    public Generation Generate(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        RunOperation(token => _inner.GenerateAsync(request, token, manifest), cancellationToken);

    /// <summary>Generates a terminal result from one user prompt.</summary>
    public Generation Generate(string prompt, string? target = null, Route? route = null, Sampling? sampling = null,
        Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null, double? timeoutS = null,
        int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null) =>
        RunOperation(token => _inner.GenerateAsync(prompt, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, token, manifest), cancellationToken);

    /// <summary>Generates a terminal result from caller messages.</summary>
    public Generation Generate(IEnumerable<Message> messages, string? target = null, Route? route = null,
        Sampling? sampling = null, Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null,
        double? timeoutS = null, int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null) =>
        RunOperation(token => _inner.GenerateAsync(messages, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, token, manifest), cancellationToken);

    /// <summary>Creates an eager-pump synchronous stream from an explicit request.</summary>
    public SyncStream Stream(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        CreateStream(() => _inner.StreamAsync(request, cancellationToken, manifest));

    /// <summary>Creates an eager-pump synchronous stream from one user prompt.</summary>
    public SyncStream Stream(string prompt, string? target = null, Route? route = null, Sampling? sampling = null,
        Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null, double? timeoutS = null,
        int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null) =>
        CreateStream(() => _inner.StreamAsync(prompt, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, cancellationToken, manifest));

    /// <summary>Creates an eager-pump synchronous stream from caller messages.</summary>
    public SyncStream Stream(IEnumerable<Message> messages, string? target = null, Route? route = null,
        Sampling? sampling = null, Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null,
        double? timeoutS = null, int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null) =>
        CreateStream(() => _inner.StreamAsync(messages, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, cancellationToken, manifest));

    /// <inheritdoc />
    public void Dispose()
    {
        if (ReferenceEquals(SyncExecutionContext.CurrentClient, this))
        {
            throw new InvalidOperationException("A Client cannot be disposed from an active client-owned callback.");
        }

        Task disposal;
        lock (_gate)
        {
            if (_disposeTask is null)
            {
                _closing = true;
                disposal = _disposeTask = Task.Run(DisposeCoreAsync);
            }
            else
            {
                disposal = _disposeTask;
            }
        }

        disposal.GetAwaiter().GetResult();
    }

    private T RunOperation<T>(Func<CancellationToken, Task<T>> operation, CancellationToken callerCancellation)
    {
        ArgumentNullException.ThrowIfNull(operation);
        var reservation = ReserveOperation();
        try
        {
            return Task.Run(async () =>
            {
                using var context = SyncExecutionContext.Push(this);
                using var linked = CancellationTokenSource.CreateLinkedTokenSource(callerCancellation, _lifetime.Token);
                using var identity = CancellationIdentityContext.Push(linked.Token, callerCancellation);
                return await operation(linked.Token).ConfigureAwait(false);
            }).GetAwaiter().GetResult();
        }
        finally
        {
            CompleteOperation(reservation);
        }
    }

    private SyncStream CreateStream(Func<AsyncStream> create)
    {
        ArgumentNullException.ThrowIfNull(create);
        var reservation = ReserveOperation();
        AsyncStream? inner = null;
        SyncStream? stream = null;
        try
        {
            using (SyncExecutionContext.Push(this))
            {
                inner = create();
            }

            lock (_gate)
            {
                ThrowIfClosing();
            }

            stream = new SyncStream(this, inner, _lifetime.Token, RemoveStream);
            lock (_gate)
            {
                ThrowIfClosing();
                _streams.Add(stream);
                var published = stream;
                stream = null;
                return published;
            }
        }
        catch
        {
            if (stream is not null)
            {
                _ = stream.SignalCloseAsync();
                stream.CloseAsync().GetAwaiter().GetResult();
            }
            else if (inner is not null)
            {
                DisposeInner(inner);
            }

            throw;
        }
        finally
        {
            CompleteOperation(reservation);
        }
    }

    private TaskCompletionSource ReserveOperation()
    {
        var reservation = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (_gate)
        {
            ThrowIfClosing();
            _operations.Add(reservation);
        }

        return reservation;
    }

    private void CompleteOperation(TaskCompletionSource reservation)
    {
        lock (_gate)
        {
            _operations.Remove(reservation);
        }

        reservation.TrySetResult();
    }

    private async Task DisposeCoreAsync()
    {
        SyncStream[] streams;
        Task[] operations;
        lock (_gate)
        {
            streams = _streams.ToArray();
            _streams.Clear();
            operations = _operations.Select(static reservation => reservation.Task).ToArray();
        }

        var lifetimeSignal = SignalLifetimeAsync();
        var signals = new Task<Exception?>[streams.Length];
        for (var index = 0; index < streams.Length; index++)
        {
            signals[index] = streams[index].SignalCloseAsync();
        }

        Exception? failure = await lifetimeSignal.ConfigureAwait(false);
        var signalFailures = await Task.WhenAll(signals).ConfigureAwait(false);
        foreach (var signalFailure in signalFailures)
        {
            failure ??= signalFailure;
        }

        foreach (var stream in streams)
        {
            try
            {
                await stream.CloseAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                if (failure is null)
                {
                    failure = exception;
                    stream.MarkParentCloseFailureObserved();
                }
            }
        }

        try
        {
            await Task.WhenAll(operations).ConfigureAwait(false);
            await _inner.DisposeAsync().ConfigureAwait(false);
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
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private Task<Exception?> SignalLifetimeAsync()
    {
        TaskCompletionSource<Exception?> completion;
        lock (_gate)
        {
            if (_lifetimeSignalCompletion is not null)
            {
                return _lifetimeSignalCompletion.Task;
            }

            completion = _lifetimeSignalCompletion = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        _ = Task.Run(() => SignalLifetimeCore(completion));
        return completion.Task;
    }

    private void SignalLifetimeCore(TaskCompletionSource<Exception?> completion)
    {
        Exception? failure = null;
        try
        {
            using var context = SyncExecutionContext.Push(this);
            _lifetime.Cancel();
        }
        catch (Exception exception)
        {
            failure = exception;
        }

        completion.TrySetResult(failure);
    }

    private void RemoveStream(SyncStream stream)
    {
        lock (_gate)
        {
            _streams.Remove(stream);
        }
    }

    private static void DisposeInner(AsyncStream inner) =>
        Task.Run(async () => await inner.DisposeAsync().ConfigureAwait(false)).GetAwaiter().GetResult();

    private void ThrowIfClosing()
    {
        if (_closing)
        {
            throw new ObjectDisposedException(nameof(Client));
        }
    }
}
