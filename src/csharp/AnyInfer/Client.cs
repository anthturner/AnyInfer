using AnyInfer.Config;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Credentials;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using AnyInfer.Events;
using AnyInfer.Routing;
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
        bool manifestPayloads = false,
        ITokenEstimator? estimator = null,
        SpendLedger? ledger = null,
        SpendPolicy? spendPolicy = null,
        bool contextGate = true,
        IReadOnlyDictionary<string, RateLimiter>? limiters = null,
        CachePolicy? cachePolicy = null,
        bool retainRaw = false,
        IReadOnlyDictionary<InferenceOperation, Route>? operationRoutes = null)
        : this(new AsyncClient(providers, registry, resolver, route, repair, catalog, pricingTable, capabilityOverrides, schemaValidation, observers, manifests, manifestPayloads, estimator, ledger, spendPolicy, contextGate, limiters, cachePolicy, retainRaw, operationRoutes))
    {
    }

    private Client(AsyncClient inner) => _inner = inner ?? throw new ArgumentNullException(nameof(inner));

    /// <summary>Creates a synchronous client over externally constructed adapters.</summary>
    public static Client FromAdapters(
        IEnumerable<ProviderRegistration> providers,
        SchemaValidationOptions? schemaValidation = null,
        IEnumerable<IObserver>? observers = null,
        bool manifests = true,
        bool manifestPayloads = false,
        ITokenEstimator? estimator = null,
        SpendLedger? ledger = null,
        SpendPolicy? spendPolicy = null,
        bool contextGate = true,
        IReadOnlyDictionary<string, RateLimiter>? limiters = null,
        CachePolicy? cachePolicy = null,
        bool retainRaw = false,
        IReadOnlyDictionary<InferenceOperation, Route>? operationRoutes = null) =>
        new(AsyncClient.FromAdapters(providers, schemaValidation, observers, manifests, manifestPayloads, estimator, ledger, spendPolicy, contextGate, limiters, cachePolicy, retainRaw, operationRoutes));

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
        bool manifestPayloads = false,
        ITokenEstimator? estimator = null,
        SpendLedger? ledger = null,
        SpendPolicy? spendPolicy = null,
        bool contextGate = true,
        IReadOnlyDictionary<string, RateLimiter>? limiters = null,
        CachePolicy? cachePolicy = null,
        bool retainRaw = false,
        IReadOnlyDictionary<InferenceOperation, Route>? operationRoutes = null) =>
        new(AsyncClient.FromConfig(config, registry, resolver, catalog, pricingTable, capabilityOverrides, schemaValidation, observers, manifests, manifestPayloads, estimator, ledger, spendPolicy, contextGate, limiters, cachePolicy, retainRaw, operationRoutes));

    /// <summary>Gets the immutable catalog used by pure target resolution.</summary>
    public global::AnyInfer.Catalog.Catalog Catalog => _inner.Catalog;

    /// <summary>Resolves a target without credentials, factories, or network work.</summary>
    public ResolvedTarget Resolve(string target) => _inner.Resolve(target);

    /// <summary>Gets assembled immutable capability facts without constructing an adapter.</summary>
    public ModelCapabilities Capabilities(string target) => _inner.Capabilities(target);

    /// <summary>Gets completed spend recorded by this client's optional caller-owned ledger.</summary>
    public SpendTotals Spend()
    {
        ThrowIfClosing();
        return _inner.Spend();
    }

    /// <summary>Builds a pure context budget for one explicit target without selecting or constructing an adapter.</summary>
    public ContextBudget Budget(GenerationRequest request, string target, long? outputReserveTokens = null)
    {
        ThrowIfClosing();
        return _inner.Budget(request, target, outputReserveTokens);
    }

    /// <summary>Builds a pure context budget for one prompt and explicit target.</summary>
    public ContextBudget Budget(
        string prompt,
        string target,
        SchemaSpec? schema = null,
        Sampling? sampling = null,
        long? outputReserveTokens = null,
        IEnumerable<ToolSpec>? tools = null,
        string toolChoice = "auto",
        CachePolicy? cache = null)
    {
        ThrowIfClosing();
        return _inner.Budget(prompt, target, schema, sampling, outputReserveTokens, tools, toolChoice, cache);
    }

    /// <summary>Builds a pure context budget for caller messages and an explicit target.</summary>
    public ContextBudget Budget(
        IEnumerable<Message> messages,
        string target,
        SchemaSpec? schema = null,
        Sampling? sampling = null,
        long? outputReserveTokens = null,
        IEnumerable<ToolSpec>? tools = null,
        string toolChoice = "auto",
        CachePolicy? cache = null)
    {
        ThrowIfClosing();
        return _inner.Budget(messages, target, schema, sampling, outputReserveTokens, tools, toolChoice, cache);
    }

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

    /// <summary>Embeds one immutable request through the selected retrieval route.</summary>
    public EmbeddingResult Embed(
        EmbeddingRequest request,
        string? target = null,
        Route? route = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.EmbedAsync(request, target, route, token, manifest), cancellationToken);

    /// <summary>Embeds one text input through the selected retrieval route.</summary>
    public EmbeddingResult Embed(
        string input,
        string? target = null,
        Route? route = null,
        EmbeddingInputIntent? inputType = null,
        int? dimensions = null,
        EmbeddingSpace? expectedSpace = null,
        bool allowIncompatibleFallback = false,
        BatchPolicy? batch = null,
        double? timeoutS = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? maxResponseBytes = null,
        bool? retainRaw = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.EmbedAsync(input, target, route, inputType, dimensions, expectedSpace, allowIncompatibleFallback, batch, timeoutS, providerOptions, metadata, maxResponseBytes, retainRaw, token, manifest), cancellationToken);

    /// <summary>Embeds ordered text inputs through the selected retrieval route.</summary>
    public EmbeddingResult Embed(
        IEnumerable<string> inputs,
        string? target = null,
        Route? route = null,
        EmbeddingInputIntent? inputType = null,
        int? dimensions = null,
        EmbeddingSpace? expectedSpace = null,
        bool allowIncompatibleFallback = false,
        BatchPolicy? batch = null,
        double? timeoutS = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? maxResponseBytes = null,
        bool? retainRaw = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.EmbedAsync(inputs, target, route, inputType, dimensions, expectedSpace, allowIncompatibleFallback, batch, timeoutS, providerOptions, metadata, maxResponseBytes, retainRaw, token, manifest), cancellationToken);

    /// <summary>Reranks one immutable request through the selected retrieval route.</summary>
    public RerankResult Rerank(
        RerankRequest request,
        string? target = null,
        Route? route = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.RerankAsync(request, target, route, token, manifest), cancellationToken);

    /// <summary>Reranks ordered document texts through the selected retrieval route.</summary>
    public RerankResult Rerank(
        string query,
        IEnumerable<string> documents,
        string? target = null,
        Route? route = null,
        int? topN = null,
        BatchPolicy? batch = null,
        double? timeoutS = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? maxResponseBytes = null,
        bool returnDocuments = false,
        bool? retainRaw = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.RerankAsync(query, documents, target, route, topN, batch, timeoutS, providerOptions, metadata, maxResponseBytes, returnDocuments, retainRaw, token, manifest), cancellationToken);

    /// <summary>Reranks ordered documents through the selected retrieval route.</summary>
    public RerankResult Rerank(
        string query,
        IEnumerable<RerankDocument> documents,
        string? target = null,
        Route? route = null,
        int? topN = null,
        BatchPolicy? batch = null,
        double? timeoutS = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? maxResponseBytes = null,
        bool returnDocuments = false,
        bool? retainRaw = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.RerankAsync(query, documents, target, route, topN, batch, timeoutS, providerOptions, metadata, maxResponseBytes, returnDocuments, retainRaw, token, manifest), cancellationToken);
    /// <summary>Generates a terminal result from an explicit request.</summary>
    public Generation Generate(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        RunOperation(token => _inner.GenerateAsync(request, token, manifest), cancellationToken);

    /// <summary>Generates and dispatches explicitly registered tools until the model stops calling them.</summary>
    public Generation RunTools(
        GenerationRequest request,
        IEnumerable<Tool> tools,
        int maxRounds = 8,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.RunToolsAsync(request, tools, maxRounds, token, manifest), cancellationToken);

    /// <summary>Generates from one prompt while dispatching explicitly registered tools.</summary>
    public Generation RunTools(
        string prompt,
        IEnumerable<Tool> tools,
        string? target = null,
        Route? route = null,
        Sampling? sampling = null,
        Repair? repair = null,
        SchemaSpec? schema = null,
        string? schemaMechanism = null,
        double? timeoutS = null,
        int? maxResponseBytes = null,
        string toolChoice = "auto",
        CachePolicy? cache = null,
        string? reasoning = null,
        IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? logprobs = null,
        bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null,
        int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024,
        int maxRounds = 8,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.RunToolsAsync(prompt, tools, target, route, sampling, repair, schema,
            schemaMechanism, timeoutS, maxResponseBytes, toolChoice, cache, reasoning,
            providerOptions, metadata, logprobs, citeDocuments, serverTools, maxInputPartBytes,
            maxInputBytes, maxRounds, token, manifest), cancellationToken);

    /// <summary>Generates from caller messages while dispatching explicitly registered tools.</summary>
    public Generation RunTools(
        IEnumerable<Message> messages,
        IEnumerable<Tool> tools,
        string? target = null,
        Route? route = null,
        Sampling? sampling = null,
        Repair? repair = null,
        SchemaSpec? schema = null,
        string? schemaMechanism = null,
        double? timeoutS = null,
        int? maxResponseBytes = null,
        string toolChoice = "auto",
        CachePolicy? cache = null,
        string? reasoning = null,
        IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? logprobs = null,
        bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null,
        int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024,
        int maxRounds = 8,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.RunToolsAsync(messages, tools, target, route, sampling, repair, schema,
            schemaMechanism, timeoutS, maxResponseBytes, toolChoice, cache, reasoning,
            providerOptions, metadata, logprobs, citeDocuments, serverTools, maxInputPartBytes,
            maxInputBytes, maxRounds, token, manifest), cancellationToken);

    /// <summary>Generates a terminal result from one user prompt.</summary>
    public Generation Generate(string prompt, string? target = null, Route? route = null, Sampling? sampling = null,
        Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null, double? timeoutS = null,
        int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto", CachePolicy? cache = null,
        string? reasoning = null, IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null, int? logprobs = null, bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null, int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        RunOperation(token => _inner.GenerateAsync(prompt: prompt, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, cancellationToken: token, manifest: manifest, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes), cancellationToken);

    /// <summary>Generates a terminal result from caller messages.</summary>
    public Generation Generate(IEnumerable<Message> messages, string? target = null, Route? route = null,
        Sampling? sampling = null, Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null,
        double? timeoutS = null, int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto", CachePolicy? cache = null,
        string? reasoning = null, IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null, int? logprobs = null, bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null, int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        RunOperation(token => _inner.GenerateAsync(messages: messages, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, cancellationToken: token, manifest: manifest, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes), cancellationToken);

    /// <summary>Creates an eager-pump synchronous stream from an explicit request.</summary>
    public SyncStream Stream(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        CreateStream(() => _inner.StreamAsync(request, cancellationToken, manifest));

    /// <summary>Creates an eager-pump synchronous stream from one user prompt.</summary>
    public SyncStream Stream(string prompt, string? target = null, Route? route = null, Sampling? sampling = null,
        Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null, double? timeoutS = null,
        int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto", CachePolicy? cache = null,
        string? reasoning = null, IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null, int? logprobs = null, bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null, int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        CreateStream(() => _inner.StreamAsync(prompt: prompt, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, cancellationToken: cancellationToken, manifest: manifest, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes));

    /// <summary>Creates an eager-pump synchronous stream from caller messages.</summary>
    public SyncStream Stream(IEnumerable<Message> messages, string? target = null, Route? route = null,
        Sampling? sampling = null, Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null,
        double? timeoutS = null, int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto", CachePolicy? cache = null,
        string? reasoning = null, IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null, int? logprobs = null, bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null, int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        CreateStream(() => _inner.StreamAsync(messages: messages, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, cancellationToken: cancellationToken, manifest: manifest, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes));

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
