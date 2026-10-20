using AnyInfer.Core;
using AnyInfer.Internal;
using System.Runtime.ExceptionServices;
using AnyInfer.Providers;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Schema;
using AnyInfer.Events;
using AnyInfer.Manifest;
using AnyInfer.Routing;
using AnyInfer.Json;

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
    private readonly EventDispatcher _dispatcher;
    private readonly bool _manifests;
    private readonly bool _manifestPayloads;
    private readonly ITokenEstimator? _estimator;
    private readonly SpendLedger? _ledger;
    private readonly SpendPolicy? _spendPolicy;
    private readonly bool _contextGate;
    private readonly CachePolicy? _cachePolicy;
    private readonly bool _retainRaw;
    private readonly IReadOnlyDictionary<InferenceOperation, Route> _operationRoutes;
    private readonly CachePrefixState _cachePrefixes = new();
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
    {
        _dispatcher = new EventDispatcher(observers);
        var copiedLimiters = CopyLimiters(limiters);
        var descriptors = registry ?? Providers.ProviderRegistry.CreateDefault();
        _pool = new ProviderPool(
            providers,
            descriptors,
            resolver ?? Credentials.ResolverChain.CreateDefault(),
            copiedLimiters,
            _dispatcher.Emit,
            TimeProvider.System);
        _clock = new SystemOperationClock();
        _health = new RouteState(_clock);
        _defaultRoute = route;
        _defaultRepair = repair;
        _catalog = catalog ?? AnyInfer.Catalog.Catalog.LoadDefault();
        _capabilities = new CapabilityStore(pricingTable, capabilityOverrides);
        _targetResolver = new TargetMetadataResolver(_catalog, _pool.DescriptorSnapshot, () => _pool.Bindings, _pool, _capabilities);
        _resolutionProfile = TargetResolutionProfile.PublicSdk;
        _schemaValidation = schemaValidation;
        _manifests = manifests;
        _manifestPayloads = manifestPayloads;
        _estimator = estimator;
        _ledger = ledger ?? (spendPolicy is null ? null : new SpendLedger());
        _spendPolicy = spendPolicy;
        _contextGate = contextGate;
        _cachePolicy = cachePolicy;
        _retainRaw = retainRaw;
        _operationRoutes = CopyOperationRoutes(operationRoutes);
        if (_ledger is not null) _dispatcher.Subscribe(_ledger);
    }

    /// <summary>Creates a client over externally constructed adapters.</summary>
    public static AsyncClient FromAdapters(
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
        new(providers, new SystemOperationClock(), publicSdk: true, schemaValidation, observers, manifests, manifestPayloads, estimator, ledger, spendPolicy, contextGate, limiters, cachePolicy, retainRaw, operationRoutes);

    /// <summary>Creates a client from inert parsed configuration without performing I/O or credential resolution.</summary>
    public static AsyncClient FromConfig(
        Config.AnyInferConfig config,
        Providers.ProviderRegistry? registry = null,
        Credentials.ResolverChain? resolver = null,
        AnyInfer.Catalog.Catalog? catalog = null,
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
    {
        ArgumentNullException.ThrowIfNull(config);
        return new AsyncClient(config.Providers, registry, resolver, config.Route, config.Repair, catalog, pricingTable, capabilityOverrides, schemaValidation, observers, manifests, manifestPayloads, estimator, ledger, spendPolicy, contextGate, limiters, cachePolicy ?? config.Cache, retainRaw, operationRoutes ?? config.OperationRoutes);
    }

    internal AsyncClient(IEnumerable<ProviderRegistration> providers, IOperationClock clock)
        : this(providers, clock, publicSdk: false, schemaValidation: null, observers: null, manifests: false, manifestPayloads: false, estimator: null, ledger: null, spendPolicy: null, contextGate: false, limiters: null, cachePolicy: null, retainRaw: false, operationRoutes: null)
    {
    }

    private AsyncClient(
        IEnumerable<ProviderRegistration> providers,
        IOperationClock clock,
        bool publicSdk,
        SchemaValidationOptions? schemaValidation,
        IEnumerable<IObserver>? observers,
        bool manifests,
        bool manifestPayloads,
        ITokenEstimator? estimator,
        SpendLedger? ledger,
        SpendPolicy? spendPolicy,
        bool contextGate,
        IReadOnlyDictionary<string, RateLimiter>? limiters,
        CachePolicy? cachePolicy,
        bool retainRaw,
        IReadOnlyDictionary<InferenceOperation, Route>? operationRoutes)
    {
        _dispatcher = new EventDispatcher(observers);
        var copiedLimiters = CopyLimiters(limiters);
        _pool = new ProviderPool(providers, copiedLimiters, _dispatcher.Emit, TimeProvider.System);
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        _health = new RouteState(_clock);
        _catalog = AnyInfer.Catalog.Catalog.LoadDefault();
        _capabilities = new CapabilityStore();
        _targetResolver = new TargetMetadataResolver(
            _catalog,
            publicSdk ? new Providers.ProviderRegistry([]) : null,
            () => _pool.Bindings,
            _pool,
            _capabilities);
        _resolutionProfile = publicSdk ? TargetResolutionProfile.PublicSdk : TargetResolutionProfile.FrozenV0;
        _schemaValidation = schemaValidation;
        _manifests = manifests;
        _manifestPayloads = manifestPayloads;
        _estimator = estimator;
        _ledger = ledger ?? (publicSdk && spendPolicy is not null ? new SpendLedger() : null);
        _spendPolicy = publicSdk ? spendPolicy : null;
        _contextGate = publicSdk && contextGate;
        _cachePolicy = publicSdk ? cachePolicy : null;
        _retainRaw = publicSdk && retainRaw;
        _operationRoutes = publicSdk ? CopyOperationRoutes(operationRoutes) : EmptyOperationRoutes;
        if (_ledger is not null) _dispatcher.Subscribe(_ledger);
    }

    private static IReadOnlyDictionary<string, RateLimiter>? CopyLimiters(
        IReadOnlyDictionary<string, RateLimiter>? limiters)
    {
        if (limiters is null)
        {
            return null;
        }

        var copy = new Dictionary<string, RateLimiter>(StringComparer.Ordinal);
        foreach (var pair in limiters)
        {
            var instanceId = ProviderSettings.NormalizeId(pair.Key, nameof(limiters));
            ArgumentNullException.ThrowIfNull(pair.Value);
            if (!copy.TryAdd(instanceId, pair.Value))
            {
                throw new ArgumentException("Limiter instance IDs must be unique after normalization.", nameof(limiters));
            }
        }

        return new System.Collections.ObjectModel.ReadOnlyDictionary<string, RateLimiter>(copy);
    }

    private static readonly IReadOnlyDictionary<InferenceOperation, Route> EmptyOperationRoutes =
        new System.Collections.ObjectModel.ReadOnlyDictionary<InferenceOperation, Route>(
            new Dictionary<InferenceOperation, Route>());

    private static IReadOnlyDictionary<InferenceOperation, Route> CopyOperationRoutes(
        IReadOnlyDictionary<InferenceOperation, Route>? operationRoutes)
    {
        if (operationRoutes is null || operationRoutes.Count == 0)
        {
            return EmptyOperationRoutes;
        }

        var copy = new Dictionary<InferenceOperation, Route>();
        foreach (var pair in operationRoutes)
        {
            if (pair.Key is not InferenceOperation.Embedding and not InferenceOperation.Rerank)
            {
                throw new ArgumentException("Operation routes support only embedding and rerank.", nameof(operationRoutes));
            }

            copy.Add(pair.Key, pair.Value ?? throw new ArgumentException("Operation routes cannot contain null routes.", nameof(operationRoutes)));
        }

        return new System.Collections.ObjectModel.ReadOnlyDictionary<InferenceOperation, Route>(copy);
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

    /// <summary>Gets completed spend recorded by this client's optional caller-owned ledger.</summary>
    public SpendTotals Spend() => _ledger?.Totals() ?? new SpendTotals();

    /// <summary>Builds a pure context budget for one explicit target without selecting or constructing an adapter.</summary>
    public ContextBudget Budget(GenerationRequest request, string target, long? outputReserveTokens = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(target);
        var metadata = _targetResolver.Resolve(target, _resolutionProfile);
        var capabilities = metadata.ResolvedCapabilities ?? _capabilities.CapabilitiesFor(
            metadata.Descriptor,
            metadata.Target.ProviderId,
            metadata.Target.Model,
            _pool.EffectiveLocality(metadata));
        return ContextBudgeting.BuildContextBudget(
            request,
            capabilities,
            _estimator,
            metadata.Descriptor?.TokenCalibration,
            outputReserveTokens);
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
        CachePolicy? cache = null) =>
        Budget(new GenerationRequest([Message.User(prompt)], new Route([target]), sampling, schema: schema, tools: tools, toolChoice: toolChoice, cache: cache), target, outputReserveTokens);

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
        ArgumentNullException.ThrowIfNull(messages);
        return Budget(new GenerationRequest(messages, new Route([target]), sampling, schema: schema, tools: tools, toolChoice: toolChoice, cache: cache), target, outputReserveTokens);
    }

    /// <summary>Subscribes an observer for synchronous telemetry notifications.</summary>
    public void Subscribe(IObserver observer, bool payloads = false) => _dispatcher.Subscribe(observer, payloads);

    /// <summary>Removes every reference-identical observer subscription.</summary>
    public void Unsubscribe(IObserver observer) => _dispatcher.Unsubscribe(observer);

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

    /// <summary>Runs ordered raw generation capability probes against one resolved target.</summary>
    public Task<ProbeReport> ProbeAsync(
        string target,
        IEnumerable<Feature>? features = null,
        double timeoutS = 30,
        bool record = true,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(target);
        return ProbeCoreAsync(target, features, timeoutS, record, cancellationToken, CancellationIdentityContext.Resolve(cancellationToken));
    }

    /// <summary>Embeds one immutable request through the selected retrieval route.</summary>
    public Task<EmbeddingResult> EmbedAsync(
        EmbeddingRequest request,
        string? target = null,
        Route? route = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        return EmbedCoreAsync(request, target, route, cancellationToken, CancellationIdentityContext.Resolve(cancellationToken), manifest);
    }

    /// <summary>Embeds one text input through the selected retrieval route.</summary>
    public Task<EmbeddingResult> EmbedAsync(
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
        EmbedAsync(new EmbeddingRequest([input], inputType, dimensions, expectedSpace, timeoutS,
            maxResponseBytes ?? 64 * 1024 * 1024, metadata, providerOptions, batch,
            retainRaw ?? _retainRaw, allowIncompatibleFallback), target, route, cancellationToken, manifest);

    /// <summary>Embeds ordered text inputs through the selected retrieval route.</summary>
    public Task<EmbeddingResult> EmbedAsync(
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
        EmbedAsync(new EmbeddingRequest(inputs, inputType, dimensions, expectedSpace, timeoutS,
            maxResponseBytes ?? 64 * 1024 * 1024, metadata, providerOptions, batch,
            retainRaw ?? _retainRaw, allowIncompatibleFallback), target, route, cancellationToken, manifest);

    /// <summary>Reranks one immutable request through the selected retrieval route.</summary>
    public Task<RerankResult> RerankAsync(
        RerankRequest request,
        string? target = null,
        Route? route = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        return RerankCoreAsync(request, target, route, cancellationToken, CancellationIdentityContext.Resolve(cancellationToken), manifest);
    }

    /// <summary>Reranks ordered document texts through the selected retrieval route.</summary>
    public Task<RerankResult> RerankAsync(
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
        RerankAsync(new RerankRequest(query, documents.Select((text, index) => new RerankDocument(index.ToString(System.Globalization.CultureInfo.InvariantCulture), text)), topN, timeoutS,
            maxResponseBytes ?? 8 * 1024 * 1024, metadata, providerOptions, batch, returnDocuments, retainRaw ?? _retainRaw), target, route, cancellationToken, manifest);

    /// <summary>Reranks ordered documents through the selected retrieval route.</summary>
    public Task<RerankResult> RerankAsync(
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
        RerankAsync(new RerankRequest(query, documents, topN, timeoutS,
            maxResponseBytes ?? 8 * 1024 * 1024, metadata, providerOptions, batch, returnDocuments, retainRaw ?? _retainRaw), target, route, cancellationToken, manifest);
    /// <summary>Consumes this client's single streaming execution path to its terminal result.</summary>
    public Task<Generation> GenerateAsync(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        GenerateAsync(request, capture: null, cancellationToken: cancellationToken, manifest: manifest);

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
        CancellationToken cancellationToken = default,
        bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null,
        string toolChoice = "auto",
        CachePolicy? cache = null) =>
        GenerateAsync(
            CreateConvenienceRequest([Message.User(prompt)], target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, stream: false, tools, toolChoice, cache),
            cancellationToken,
            manifest);

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
        CancellationToken cancellationToken = default,
        bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null,
        string toolChoice = "auto",
        CachePolicy? cache = null) =>
        GenerateAsync(
            CreateConvenienceRequest(messages, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, stream: false, tools, toolChoice, cache),
            cancellationToken,
            manifest);

    internal async Task<Generation> GenerateAsync(
        GenerationRequest request,
        OperationCapture? capture,
        CancellationToken cancellationToken = default,
        bool? manifest = null)
    {
        await using var stream = StreamAsync(request, capture, cancellationToken, manifest);
        return await stream.CollectAsync(cancellationToken).ConfigureAwait(false);
    }

    /// <summary>Creates a lazy single-consumer generation stream.</summary>
    public AsyncStream StreamAsync(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        StreamAsync(request, capture: null, cancellationToken: cancellationToken, manifest: manifest);

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
        CancellationToken cancellationToken = default,
        bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null,
        string toolChoice = "auto",
        CachePolicy? cache = null) =>
        StreamAsync(
            CreateConvenienceRequest([Message.User(prompt)], target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, stream: true, tools, toolChoice, cache),
            cancellationToken,
            manifest);

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
        CancellationToken cancellationToken = default,
        bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null,
        string toolChoice = "auto",
        CachePolicy? cache = null) =>
        StreamAsync(
            CreateConvenienceRequest(messages, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, stream: true, tools, toolChoice, cache),
            cancellationToken,
            manifest);

    internal AsyncStream StreamAsync(
        GenerationRequest request,
        OperationCapture? capture,
        CancellationToken cancellationToken = default,
        bool? manifest = null)
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
                request.Stream,
                request.Tools,
                request.ToolChoice,
                request.Cache)
            : request;
        var normalized = RequestNormalizer.Normalize(
            effectiveRequest,
            _resolutionProfile == TargetResolutionProfile.PublicSdk,
            _resolutionProfile == TargetResolutionProfile.PublicSdk ? SchemaExecutionProfile.ModernSdk : SchemaExecutionProfile.FrozenV0,
            _schemaValidation);
        var enableManifest = _resolutionProfile == TargetResolutionProfile.PublicSdk && (manifest ?? _manifests);
        var requestId = Guid.NewGuid().ToString("D");
        ManifestBuilder? builder = enableManifest
            ? new ManifestBuilder(
                requestId,
                normalized,
                effectiveRequest.Route,
                metadata => _capabilities.CapabilitiesFor(metadata.Descriptor, metadata.Target.ProviderId, metadata.Target.Model, _pool.EffectiveLocality(metadata)),
                _manifestPayloads,
                AnyInferVersion.Value,
                effectiveRequest.Cache ?? _cachePolicy)
            : null;
        RequestTelemetry? telemetry = _resolutionProfile == TargetResolutionProfile.PublicSdk
            ? new RequestTelemetry(normalized, effectiveRequest.Route, _dispatcher, builder, requestId)
            : null;
        AsyncStream? stream = null;
        stream = new AsyncStream(
            this,
            SyncExecutionContext.CurrentClient,
            token => RunStreamAsync(normalized, effectiveRequest.Route, capture, stream!, _resolutionProfile == TargetResolutionProfile.PublicSdk ? new GenerationPolicyContext(effectiveRequest, effectiveRequest.Cache ?? _cachePolicy, _estimator, _cachePrefixes, _spendPolicy, _ledger, _contextGate) : null, token, _retainRaw),
            cancellationToken,
            OnStreamClosed,
            telemetry);
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
            foreach (var operation in operations)
            {
                failure ??= operation.ChildSignalFailure;
            }
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
        GenerationPolicyContext? policyContext,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken,
        bool retainRaw)
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
                policyContext,
                cancellationToken,
                retainRaw).WithCancellation(cancellationToken).ConfigureAwait(false))
            {
                yield return generationEvent;
            }
        }
        finally
        {
            RemoveActiveStream(stream);
        }
    }

    private async Task<EmbeddingResult> EmbedCoreAsync(
        EmbeddingRequest request,
        string? target,
        Route? route,
        CancellationToken cancellationToken,
        CancellationToken callerIdentity,
        bool? manifest)
    {
        var reservation = ReserveLifecycle(cancellationToken, callerIdentity);
        using var context = AsyncExecutionContext.Push(this, reservation.SyncOwner);
        using var identity = CancellationIdentityContext.Push(reservation.Token, reservation.CallerIdentity);
        var requestId = Guid.NewGuid().ToString("D");
        var committed = false;
        try
        {
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            var effectiveRoute = ResolveOperationRoute(InferenceOperation.Embedding, target, route);
            var admission = _targetResolver.Resolve(effectiveRoute.Targets[0], _resolutionProfile);
            RetrievalCore.EnforceEmbeddingSpend(request, admission.ResolvedCapabilities, admission.Target, requestId, _spendPolicy, _ledger, _estimator);
            _dispatcher.Emit(new RequestStarted(requestId, effectiveRoute.Targets, request.Metadata, operation: "embedding"));
            var outcome = await RetrievalCore.EmbedAsync(request, effectiveRoute, _pool, _targetResolver, _health, _clock,
                _capabilities, reservation.Token, reservation.CallerIdentity, _dispatcher.Emit, requestId, TimeProvider.System).ConfigureAwait(false);
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            var timing = outcome.Timing;
            var result = new EmbeddingResult(outcome.Vectors, outcome.Target, outcome.Space, outcome.Usage, timing,
                outcome.Attempts, outcome.Warnings, outcome.Raw,
                _resolutionProfile == TargetResolutionProfile.PublicSdk && (manifest ?? _manifests)
                    ? OperationManifestBuilder.Build(requestId, "embedding", effectiveRoute, outcome.Target, outcome.Usage, timing, outcome.Attempts, outcome.Warnings, outcome.Space)
                    : null);
            bool closed;
            lock (_gate)
            {
                closed = _disposed;
                if (!closed)
                {
                    reservation.ThrowIfCallerCancelled();
                    committed = true;
                }
            }
            if (closed)
            {
                await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            }
            _dispatcher.Emit(new RequestCompleted(requestId, outcome.Target, outcome.Usage, timing));
            return result;
        }
        catch (RetrievalCore.OwnedCallerDeadlineCancellationException)
        {
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            throw;
        }
        finally
        {
            if (!committed)
            {
                _ledger?.Abandon(requestId);
            }

            await CompleteLifecycleAsync(reservation).ConfigureAwait(false);
        }
    }

    private async Task<RerankResult> RerankCoreAsync(
        RerankRequest request,
        string? target,
        Route? route,
        CancellationToken cancellationToken,
        CancellationToken callerIdentity,
        bool? manifest)
    {
        var reservation = ReserveLifecycle(cancellationToken, callerIdentity);
        using var context = AsyncExecutionContext.Push(this, reservation.SyncOwner);
        using var identity = CancellationIdentityContext.Push(reservation.Token, reservation.CallerIdentity);
        var requestId = Guid.NewGuid().ToString("D");
        var committed = false;
        try
        {
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            var effectiveRoute = ResolveOperationRoute(InferenceOperation.Rerank, target, route);
            var admission = _targetResolver.Resolve(effectiveRoute.Targets[0], _resolutionProfile);
            RetrievalCore.EnforceUnknownSpend(admission.Target, requestId, _spendPolicy, _ledger);
            _dispatcher.Emit(new RequestStarted(requestId, effectiveRoute.Targets, request.Metadata, operation: "rerank"));
            var outcome = await RetrievalCore.RerankAsync(request, effectiveRoute, _pool, _targetResolver, _health, _clock,
                _capabilities, reservation.Token, reservation.CallerIdentity, _dispatcher.Emit, requestId, TimeProvider.System).ConfigureAwait(false);
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            var timing = outcome.Timing;
            var result = new RerankResult(outcome.Items, outcome.Target, outcome.Usage, timing,
                outcome.Attempts, outcome.Warnings, outcome.Raw,
                _resolutionProfile == TargetResolutionProfile.PublicSdk && (manifest ?? _manifests)
                    ? OperationManifestBuilder.Build(requestId, "rerank", effectiveRoute, outcome.Target, outcome.Usage, timing, outcome.Attempts, outcome.Warnings)
                    : null);
            bool closed;
            lock (_gate)
            {
                closed = _disposed;
                if (!closed)
                {
                    reservation.ThrowIfCallerCancelled();
                    committed = true;
                }
            }
            if (closed)
            {
                await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            }
            _dispatcher.Emit(new RequestCompleted(requestId, outcome.Target, outcome.Usage, timing));
            return result;
        }
        catch (RetrievalCore.OwnedCallerDeadlineCancellationException)
        {
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            throw;
        }
        finally
        {
            if (!committed)
            {
                _ledger?.Abandon(requestId);
            }

            await CompleteLifecycleAsync(reservation).ConfigureAwait(false);
        }
    }

    private Route ResolveOperationRoute(InferenceOperation operation, string? target, Route? route)
    {
        if (target is not null && route is null)
        {
            return _defaultRoute is null
                ? new Route([target])
                : new Route([target], _defaultRoute.Retry, _defaultRoute.HealthGate, _defaultRoute.HealthTtlS);
        }

        return route
            ?? (target is null && _operationRoutes.TryGetValue(operation, out var operationRoute) ? operationRoute : null)
            ?? _defaultRoute
            ?? throw new ConfigException("Specify a target, route, operation route, or client default route.");
    }

    private void OnStreamClosed(AsyncStream stream)
    {
        RemoveActiveStream(stream);
        var requestId = stream.Telemetry?.RequestId;
        if (requestId is not null)
        {
            _ledger?.Release(requestId);
        }
    }

    private async Task<ProbeReport> ProbeCoreAsync(
        string target,
        IEnumerable<Feature>? suppliedFeatures,
        double timeoutS,
        bool record,
        CancellationToken cancellationToken,
        CancellationToken callerIdentity)
    {
        var reservation = ReserveLifecycle(cancellationToken, callerIdentity);
        using var context = AsyncExecutionContext.Push(this, reservation.SyncOwner);
        using var identity = CancellationIdentityContext.Push(reservation.Token, reservation.CallerIdentity);
        try
        {
            var metadata = _targetResolver.Resolve(target, _resolutionProfile);
            var features = (suppliedFeatures ?? CapabilityProbes.DefaultProbeFeatures).ToArray();
            ProbeFeatureLease.ValidateTimeout(timeoutS);
            foreach (var feature in features)
            {
                if (!CapabilityProbes.ProbeableFeatures.Contains(feature))
                {
                    throw new ConfigException(
                        $"Feature '{feature}' cannot be probed.",
                        metadata.Target.ProviderId,
                        detail: $"'{feature}' is not a generation probe feature.",
                        hint: "Choose JsonSchema, JsonMode, Grammar, Tools, or Streaming.");
                }
            }

            if (metadata.Descriptor is { } descriptor && !descriptor.Operations.Contains(InferenceOperation.Generation))
            {
                throw new ConfigException(
                    "The selected provider does not declare generation support.",
                    metadata.Target.ProviderId,
                    hint: "Configure a provider descriptor that declares generation support.");
            }

            var resolved = _pool.Materialize(metadata);
            var adapter = await _pool.GetAdapterAsync(resolved.State, reservation.Token, reservation.CallerIdentity).ConfigureAwait(false);
            if (adapter is not IGeneratesText generationAdapter)
            {
                throw new ConfigException(
                    "The selected provider does not implement generation support.",
                    resolved.Target.ProviderId,
                    hint: "Configure a provider adapter that implements IGeneratesText.");
            }
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();

            var probes = new List<FeatureProbe>(features.Length);
            Usage? usage = null;
            foreach (var feature in features)
            {
                await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
                var result = await CapabilityProbeRunner.RunAsync(
                    generationAdapter,
                    resolved,
                    feature,
                    timeoutS,
                    this,
                    reservation.SyncOwner,
                    reservation.Token,
                    reservation.CallerIdentity,
                    reservation.RecordChildSignalFailure).ConfigureAwait(false);
                reservation.ThrowIfCallerCancelled();
                probes.Add(result.Probe);
                usage = OverlayProbeUsage(usage, result.Usage);
            }

            usage = NormalizeProbeUsage(usage);
            ModelCapabilities? measured;
            var closed = false;
            lock (_gate)
            {
                closed = _disposed;
                if (!closed)
                {
                    reservation.ThrowIfCallerCancelled();
                    measured = _capabilities.MergeProbe(
                        metadata.Descriptor,
                        resolved.Target.ProviderId,
                        resolved.Target.Model,
                        _pool.EffectiveLocality(metadata),
                        metadata.Capabilities,
                        probes,
                        record);
                }
                else
                {
                    measured = null!;
                }
            }

            if (closed)
            {
                await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            }

            return new ProbeReport(resolved.Target, probes, measured, features.Length, usage);
        }
        finally
        {
            await CompleteLifecycleAsync(reservation).ConfigureAwait(false);
        }
    }

    private static Usage? OverlayProbeUsage(Usage? existing, Usage? overlay)
    {
        if (overlay is null)
        {
            return existing;
        }

        return new Usage(
            overlay.InputTokens ?? existing?.InputTokens,
            overlay.OutputTokens ?? existing?.OutputTokens,
            overlay.TotalTokens ?? existing?.TotalTokens,
            overlay.CacheReadTokens ?? existing?.CacheReadTokens,
            overlay.CacheWriteTokens ?? existing?.CacheWriteTokens,
            overlay.ReasoningTokens ?? existing?.ReasoningTokens);
    }

    private static Usage? NormalizeProbeUsage(Usage? usage)
    {
        if (usage is null || usage.TotalTokens is not null || usage.InputTokens is null || usage.OutputTokens is null)
        {
            return usage;
        }

        return new Usage(
            usage.InputTokens,
            usage.OutputTokens,
            checked(usage.InputTokens.Value + usage.OutputTokens.Value),
            usage.CacheReadTokens,
            usage.CacheWriteTokens,
            usage.ReasoningTokens);
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
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            if (adapter is not IProviderLifecycle lifecycle)
            {
                throw new UnsupportedInputException("Model discovery is not supported by this provider.", state.InstanceId, "discover");
            }

            var listed = await lifecycle.ListModelsAsync(reservation.Token).ConfigureAwait(false);
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            var snapshot = Array.AsReadOnly((listed ?? throw new InvalidOperationException("A provider returned no model listing.")).ToArray());
            lock (_gate)
            {
                if (!_disposed)
                {
                    reservation.ThrowIfCallerCancelled();
                    _capabilities.RecordDiscovery(state.InstanceId, snapshot);
                    return Array.AsReadOnly(FilterModels(snapshot, state, operation, adapter).ToArray());
                }
            }

            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
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
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            if (adapter is not IProviderLifecycle lifecycle)
            {
                throw new UnsupportedInputException("Health discovery is not supported by this provider.", state.InstanceId, "discover");
            }

            var health = await lifecycle.HealthAsync(reservation.Token).ConfigureAwait(false);
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            lock (_gate)
            {
                if (!_disposed)
                {
                    reservation.ThrowIfCallerCancelled();
                    return health ?? throw new InvalidOperationException("A provider returned no health observation.");
                }
            }

            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
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
        IAsyncDisposable adapter)
    {
        if (operation is null) return models;
        return models.Where(model => SupportsOperation(state, model, operation.Value, adapter));
    }

    private static bool SupportsOperation(
        ProviderPool.InstanceState state,
        DiscoveredModel model,
        InferenceOperation operation,
        IAsyncDisposable adapter)
    {
        if (state.Descriptor is { } descriptor && !descriptor.Operations.Contains(operation))
        {
            return false;
        }

        if (model.Capabilities?.Operations is { } operations)
        {
            return operations.Value.Contains(operation);
        }

        if (state.Descriptor is { } declared)
        {
            return operation switch
            {
                InferenceOperation.Embedding => declared.StaticEmbeddingCapabilities.ContainsKey(model.Id),
                InferenceOperation.Rerank => declared.StaticRerankCapabilities.ContainsKey(model.Id),
                _ => declared.Operations.Contains(operation),
            };
        }

        return operation switch
        {
            InferenceOperation.Generation => adapter is IGeneratesText,
            InferenceOperation.Embedding => adapter is IEmbedsText,
            InferenceOperation.Rerank => adapter is IReranksText,
            _ => false,
        };
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
        private Exception? _childSignalFailure;
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
        internal Exception? ChildSignalFailure
        {
            get
            {
                lock (_gate)
                {
                    return _childSignalFailure;
                }
            }
        }

        internal void RecordChildSignalFailure(Exception failure)
        {
            ArgumentNullException.ThrowIfNull(failure);
            lock (_gate)
            {
                _childSignalFailure ??= failure;
            }
        }

        internal void ThrowIfCallerCancelled()
        {
            CallerIdentity.ThrowIfCancellationRequested();
            Token.ThrowIfCancellationRequested();
        }

        internal async Task ThrowIfClientCloseWonAsync()
        {
            bool closed;
            lock (_owner._gate)
            {
                closed = _owner._disposed;
            }

            if (!closed)
            {
                return;
            }

            await SignalCancelAsync().ConfigureAwait(false);
            ThrowIfCallerCancelled();
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
        bool stream,
        IEnumerable<ToolSpec>? tools,
        string toolChoice,
        CachePolicy? cache)
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
            stream,
            tools,
            toolChoice,
            cache);
    }
}
