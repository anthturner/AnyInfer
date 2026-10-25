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

/// <summary>
/// Asynchronous AnyInfer client that routes generation, streaming, tool-loop, embedding and reranking
/// calls to the provider adapters it owns.
/// </summary>
/// <remarks>
/// Provider adapters are built lazily, when an operation first needs a provider instance, and belong to
/// the client from then on; adapters supplied to <see cref="FromAdapters"/> belong to it from
/// construction. Dispose the client with <see cref="DisposeAsync"/>, for example with
/// <c>await using</c>, to cancel outstanding operations and streams and to dispose those adapters.
/// Observers, ledgers, rate limiters, registries, resolvers and catalogs passed to it stay owned by the
/// caller and are never disposed by the client.
/// </remarks>
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

    /// <summary>Creates a client over provider settings and provider descriptor metadata.</summary>
    /// <param name="providers">
    /// Provider instances to configure, or <see langword="null"/> for none. Each instance is identified by
    /// its alias, or by its canonical provider ID when it has none, and identities must be unique. A
    /// <c>provider:model</c> target that names a registered provider without a configured instance uses
    /// that provider's default settings.
    /// </param>
    /// <param name="registry">
    /// Provider descriptors that map provider IDs and aliases to adapter factories and metadata. The client
    /// copies the descriptors registered at construction, so later registrations do not affect it.
    /// <see langword="null"/> uses <see cref="Providers.ProviderRegistry.CreateDefault"/>.
    /// </param>
    /// <param name="resolver">
    /// Resolves credential references in provider settings, such as <c>env://NAME</c>, when an adapter is
    /// first built. <see langword="null"/> uses <see cref="Credentials.ResolverChain.CreateDefault"/>.
    /// </param>
    /// <param name="route">
    /// Default route for calls that name neither a target nor a route; embedding and rerank calls use a
    /// matching <paramref name="operationRoutes"/> entry first. A call that names only a target runs it
    /// with this route's retry and health-gate settings. <see langword="null"/> means each call must name a
    /// target or route.
    /// </param>
    /// <param name="repair">
    /// Default structured-output repair budget for requests that set none, or <see langword="null"/> for no
    /// default repair.
    /// </param>
    /// <param name="catalog">
    /// Catalog that resolves alias targets (targets without a <c>provider:</c> prefix) against the
    /// configured provider instances. <see langword="null"/> uses
    /// <see cref="AnyInfer.Catalog.Catalog.LoadDefault"/>.
    /// </param>
    /// <param name="pricingTable">
    /// Price facts used for model capabilities, cost estimates and spend admission. <see langword="null"/>
    /// uses <see cref="PricingTable.LoadDefault"/>.
    /// </param>
    /// <param name="capabilityOverrides">
    /// Caller-asserted model capabilities keyed by provider instance ID and then by exact model name.
    /// Supplied values take precedence over descriptor, pricing, discovered and probed facts. Instance keys
    /// are normalized and must stay unique; <see langword="null"/> for none.
    /// </param>
    /// <param name="schemaValidation">
    /// Resources and limits for validating structured output against modern JSON Schema;
    /// <see langword="null"/> uses the validator defaults.
    /// </param>
    /// <param name="observers">
    /// Observers subscribed at construction with payloads removed from their events, or
    /// <see langword="null"/> for none. They stay owned by the caller.
    /// </param>
    /// <param name="manifests">
    /// Whether results carry a <see cref="RunManifest"/> by default; a call's <c>manifest</c> argument
    /// overrides it.
    /// </param>
    /// <param name="manifestPayloads">
    /// Whether generation manifests also capture redacted prompt text, response text, schema body,
    /// tool-call arguments and repair texts. Embedding and rerank manifests carry no payloads.
    /// </param>
    /// <param name="estimator">
    /// Token estimator for context budgets, the context gate, spend estimates and cache planning;
    /// <see langword="null"/> uses the built-in <see cref="HeuristicTokenEstimator"/>.
    /// </param>
    /// <param name="ledger">
    /// Caller-owned ledger that records this client's completed spend from its telemetry and holds
    /// spend-policy reservations; <c>Spend()</c> reads it. <see langword="null"/> uses a private ledger
    /// when <paramref name="spendPolicy"/> is set, and none otherwise.
    /// </param>
    /// <param name="spendPolicy">
    /// Spend ceilings checked before each request is dispatched; a refused request fails with
    /// <see cref="SpendLimitException"/>. <see langword="null"/> applies no ceiling.
    /// </param>
    /// <param name="contextGate">
    /// Whether a generation attempt is refused before dispatch when its estimated input provably exceeds
    /// the target's trusted context window. The refused attempt fails with
    /// <see cref="ContextLengthException"/> and the route falls back to its context-window targets when it
    /// has any, otherwise to its next target.
    /// </param>
    /// <param name="limiters">
    /// Caller-supplied rate limiters keyed by provider instance ID. A supplied limiter replaces the one the
    /// instance's settings would create, and when its limits are inactive that instance is not paced. Keys
    /// are normalized and must stay unique. They stay owned by the caller; <see langword="null"/> for none.
    /// </param>
    /// <param name="cachePolicy">
    /// Default prompt-cache planning policy for requests that set none; <see langword="null"/> plans no
    /// cache placement for them.
    /// </param>
    /// <param name="retainRaw">
    /// Whether generation results keep the raw terminal provider payload in <see cref="Generation.Raw"/>.
    /// It is also the default for embedding and rerank calls that pass no <c>retainRaw</c> value.
    /// </param>
    /// <param name="operationRoutes">
    /// Default routes for embedding and rerank calls that name neither a target nor a route. Only
    /// <see cref="InferenceOperation.Embedding"/> and <see cref="InferenceOperation.Rerank"/> keys are
    /// accepted; generation uses <paramref name="route"/>.
    /// </param>
    /// <remarks>
    /// Construction builds no adapter, resolves no credential and sends nothing. The first operation that
    /// needs a provider instance resolves that instance's credentials and builds its adapter, which the
    /// client then owns and disposes when it is disposed.
    /// </remarks>
    /// <exception cref="System.ArgumentException">
    /// A provider, observer or limiter entry is <see langword="null"/>; limiter or capability-override keys
    /// are blank or collide after normalization; or <paramref name="operationRoutes"/> has a key other than
    /// embedding or rerank, or a <see langword="null"/> route.
    /// </exception>
    /// <exception cref="ConfigException">
    /// A provider ID is not registered, two instances share an identity, an instance alias shadows a
    /// registered provider ID or alias, or one transport handler is shared by several instances.
    /// </exception>
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

    /// <summary>Creates a client over adapters the caller has already constructed.</summary>
    /// <param name="providers">
    /// Registrations pairing a provider ID with an adapter and its structured-output profiles. Targets name
    /// these IDs, directly as <c>provider:model</c> or through a catalog alias; no provider descriptors are
    /// used. IDs are normalized and must be unique.
    /// </param>
    /// <param name="schemaValidation">
    /// Resources and limits for validating structured output against modern JSON Schema;
    /// <see langword="null"/> uses the validator defaults.
    /// </param>
    /// <param name="observers">
    /// Observers subscribed at construction with payloads removed from their events, or
    /// <see langword="null"/> for none. They stay owned by the caller.
    /// </param>
    /// <param name="manifests">
    /// Whether results carry a <see cref="RunManifest"/> by default; a call's <c>manifest</c> argument
    /// overrides it.
    /// </param>
    /// <param name="manifestPayloads">
    /// Whether generation manifests also capture redacted prompt text, response text, schema body,
    /// tool-call arguments and repair texts. Embedding and rerank manifests carry no payloads.
    /// </param>
    /// <param name="estimator">
    /// Token estimator for context budgets, the context gate, spend estimates and cache planning;
    /// <see langword="null"/> uses the built-in <see cref="HeuristicTokenEstimator"/>.
    /// </param>
    /// <param name="ledger">
    /// Caller-owned ledger that records this client's completed spend from its telemetry and holds
    /// spend-policy reservations; <c>Spend()</c> reads it. <see langword="null"/> uses a private ledger
    /// when <paramref name="spendPolicy"/> is set, and none otherwise.
    /// </param>
    /// <param name="spendPolicy">
    /// Spend ceilings checked before each request is dispatched; a refused request fails with
    /// <see cref="SpendLimitException"/>. <see langword="null"/> applies no ceiling.
    /// </param>
    /// <param name="contextGate">
    /// Whether a generation attempt is refused before dispatch when its estimated input provably exceeds
    /// the target's trusted context window. The refused attempt fails with
    /// <see cref="ContextLengthException"/> and the route falls back to its context-window targets when it
    /// has any, otherwise to its next target.
    /// </param>
    /// <param name="limiters">
    /// Caller-supplied rate limiters keyed by registration provider ID. A limiter with active limits takes
    /// a pacing slot before each call to that adapter. Keys are normalized and must stay unique. They stay
    /// owned by the caller; <see langword="null"/> for none.
    /// </param>
    /// <param name="cachePolicy">
    /// Default prompt-cache planning policy for requests that set none; <see langword="null"/> plans no
    /// cache placement for them.
    /// </param>
    /// <param name="retainRaw">
    /// Whether generation results keep the raw terminal provider payload in <see cref="Generation.Raw"/>.
    /// It is also the default for embedding and rerank calls that pass no <c>retainRaw</c> value.
    /// </param>
    /// <param name="operationRoutes">
    /// Default routes for embedding and rerank calls that name neither a target nor a route. Only
    /// <see cref="InferenceOperation.Embedding"/> and <see cref="InferenceOperation.Rerank"/> keys are
    /// accepted.
    /// </param>
    /// <returns>A client that owns the registered adapters.</returns>
    /// <remarks>
    /// The client takes ownership of every registered adapter and disposes each one when it is disposed; if
    /// this method throws, ownership has not passed. The client has no default route, so each generation
    /// call names a target or route, and embedding and rerank calls can rely on
    /// <paramref name="operationRoutes"/>. Alias targets resolve through the bundled catalog. Registered
    /// adapters have no descriptor or pricing-table facts, so their capabilities come only from model
    /// discovery and recorded probes; without those, spend estimates and the context gate treat cost and
    /// context window as unknown.
    /// </remarks>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="providers"/> is <see langword="null"/> or contains <see langword="null"/>; two
    /// registrations share a provider ID after normalization; an observer or limiter entry is
    /// <see langword="null"/>, or limiter keys are blank or collide; or <paramref name="operationRoutes"/>
    /// has a key other than embedding or rerank, or a <see langword="null"/> route.
    /// </exception>
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

    /// <summary>
    /// Creates a client from parsed configuration without performing I/O or resolving credentials.
    /// </summary>
    /// <param name="config">
    /// Parsed configuration that supplies the provider instances, the default route, the default repair
    /// budget, the cache policy and the operation routes.
    /// </param>
    /// <param name="registry">
    /// Provider descriptors that map provider IDs and aliases to adapter factories and metadata. The client
    /// copies the descriptors registered at construction, so later registrations do not affect it.
    /// <see langword="null"/> uses <see cref="Providers.ProviderRegistry.CreateDefault"/>.
    /// </param>
    /// <param name="resolver">
    /// Resolves credential references in provider settings, such as <c>env://NAME</c>, when an adapter is
    /// first built. <see langword="null"/> uses <see cref="Credentials.ResolverChain.CreateDefault"/>.
    /// </param>
    /// <param name="catalog">
    /// Catalog that resolves alias targets (targets without a <c>provider:</c> prefix) against the
    /// configured provider instances. <see langword="null"/> uses
    /// <see cref="AnyInfer.Catalog.Catalog.LoadDefault"/>.
    /// </param>
    /// <param name="pricingTable">
    /// Price facts used for model capabilities, cost estimates and spend admission. <see langword="null"/>
    /// uses <see cref="PricingTable.LoadDefault"/>.
    /// </param>
    /// <param name="capabilityOverrides">
    /// Caller-asserted model capabilities keyed by provider instance ID and then by exact model name.
    /// Supplied values take precedence over descriptor, pricing, discovered and probed facts. Instance keys
    /// are normalized and must stay unique; <see langword="null"/> for none.
    /// </param>
    /// <param name="schemaValidation">
    /// Resources and limits for validating structured output against modern JSON Schema;
    /// <see langword="null"/> uses the validator defaults.
    /// </param>
    /// <param name="observers">
    /// Observers subscribed at construction with payloads removed from their events, or
    /// <see langword="null"/> for none. They stay owned by the caller.
    /// </param>
    /// <param name="manifests">
    /// Whether results carry a <see cref="RunManifest"/> by default; a call's <c>manifest</c> argument
    /// overrides it.
    /// </param>
    /// <param name="manifestPayloads">
    /// Whether generation manifests also capture redacted prompt text, response text, schema body,
    /// tool-call arguments and repair texts. Embedding and rerank manifests carry no payloads.
    /// </param>
    /// <param name="estimator">
    /// Token estimator for context budgets, the context gate, spend estimates and cache planning;
    /// <see langword="null"/> uses the built-in <see cref="HeuristicTokenEstimator"/>.
    /// </param>
    /// <param name="ledger">
    /// Caller-owned ledger that records this client's completed spend from its telemetry and holds
    /// spend-policy reservations; <c>Spend()</c> reads it. <see langword="null"/> uses a private ledger
    /// when <paramref name="spendPolicy"/> is set, and none otherwise.
    /// </param>
    /// <param name="spendPolicy">
    /// Spend ceilings checked before each request is dispatched; a refused request fails with
    /// <see cref="SpendLimitException"/>. <see langword="null"/> applies no ceiling.
    /// </param>
    /// <param name="contextGate">
    /// Whether a generation attempt is refused before dispatch when its estimated input provably exceeds
    /// the target's trusted context window. The refused attempt fails with
    /// <see cref="ContextLengthException"/> and the route falls back to its context-window targets when it
    /// has any, otherwise to its next target.
    /// </param>
    /// <param name="limiters">
    /// Caller-supplied rate limiters keyed by provider instance ID. A supplied limiter replaces the one the
    /// instance's settings would create, and when its limits are inactive that instance is not paced. Keys
    /// are normalized and must stay unique. They stay owned by the caller; <see langword="null"/> for none.
    /// </param>
    /// <param name="cachePolicy">
    /// Prompt-cache planning policy that replaces the configuration's
    /// <see cref="Config.AnyInferConfig.Cache"/> when not <see langword="null"/>; requests that set no
    /// cache policy use the effective one.
    /// </param>
    /// <param name="retainRaw">
    /// Whether generation results keep the raw terminal provider payload in <see cref="Generation.Raw"/>.
    /// It is also the default for embedding and rerank calls that pass no <c>retainRaw</c> value.
    /// </param>
    /// <param name="operationRoutes">
    /// Embedding and rerank default routes that replace the configuration's
    /// <see cref="Config.AnyInferConfig.OperationRoutes"/> when not <see langword="null"/>. Only
    /// <see cref="InferenceOperation.Embedding"/> and <see cref="InferenceOperation.Rerank"/> keys are
    /// accepted.
    /// </param>
    /// <returns>A client configured from <paramref name="config"/>.</returns>
    /// <remarks>
    /// The configuration's providers, route and repair budget are used as given. As with the constructor,
    /// adapters are built and credentials resolved only when an operation first needs a provider instance.
    /// </remarks>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="config"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="System.ArgumentException">
    /// An observer or limiter entry is <see langword="null"/>; limiter or capability-override keys are
    /// blank or collide after normalization; or <paramref name="operationRoutes"/> has a key other than
    /// embedding or rerank, or a <see langword="null"/> route.
    /// </exception>
    /// <exception cref="ConfigException">
    /// A configured provider ID is not registered, two instances share an identity, an instance alias
    /// shadows a registered provider ID or alias, or one transport handler is shared by several instances.
    /// </exception>
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

    /// <summary>
    /// Resolves a target without resolving credentials, building an adapter or doing network I/O.
    /// </summary>
    /// <param name="target">
    /// The target to resolve: <c>provider:model</c>, where provider is a configured instance ID or a
    /// registered provider ID or alias, or a catalog alias.
    /// </param>
    /// <returns>
    /// The provider instance ID and model the target names; <see cref="ResolvedTarget.ViaAlias"/> holds the
    /// catalog alias when one was used.
    /// </returns>
    /// <exception cref="ConfigException">
    /// The target is empty, names no model, names a provider that is neither configured nor registered, or
    /// is a catalog alias with no target among the configured provider instances.
    /// </exception>
    public ResolvedTarget Resolve(string target) => _targetResolver.Resolve(target, TargetResolutionProfile.PublicSdk).Target;

    /// <summary>Gets assembled immutable capability facts without constructing an adapter.</summary>
    /// <param name="target">
    /// The target to describe: <c>provider:model</c>, where provider is a configured instance ID or a
    /// registered provider ID or alias, or a catalog alias.
    /// </param>
    /// <returns>
    /// Capability facts with their provenance, assembled from the provider descriptor, the pricing table,
    /// recorded discovery and probe results, and capability overrides. Unknown values stay unknown.
    /// </returns>
    /// <exception cref="ConfigException">The target cannot be resolved.</exception>
    public ModelCapabilities Capabilities(string target)
    {
        var resolved = _targetResolver.Resolve(target, TargetResolutionProfile.PublicSdk);
        return _capabilities.CapabilitiesFor(resolved.Descriptor, resolved.Target.ProviderId, resolved.Target.Model, _pool.EffectiveLocality(resolved));
    }

    /// <summary>Gets completed spend recorded by this client's ledger.</summary>
    /// <returns>
    /// A snapshot of completed spend from the caller's ledger or the client's private ledger, or empty
    /// totals when the client has neither.
    /// </returns>
    public SpendTotals Spend() => _ledger?.Totals() ?? new SpendTotals();

    /// <summary>
    /// Builds a pure context budget for one explicit target without selecting or constructing an adapter.
    /// </summary>
    /// <param name="request">
    /// Request whose messages, tool declarations and schema are sized; its route is not consulted.
    /// </param>
    /// <param name="target">
    /// Target whose capabilities supply the context window, output limit and pricing:
    /// <c>provider:model</c>, where provider is a configured instance ID or a registered provider ID or
    /// alias, or a catalog alias.
    /// </param>
    /// <param name="outputReserveTokens">
    /// Tokens to reserve for the response. <see langword="null"/> uses the request's maximum output tokens
    /// when set, otherwise the smaller of <see cref="ContextBudgeting.DefaultOutputReserveTokens"/> (4,096)
    /// and the model's known output limit. Must not be negative.
    /// </param>
    /// <returns>
    /// The input estimate, response reserve, safety headroom and pricing evidence for the target. Unknown
    /// capacity or cost stays unknown.
    /// </returns>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="request"/> or <paramref name="target"/> is <see langword="null"/>, or
    /// <paramref name="outputReserveTokens"/> is negative.
    /// </exception>
    /// <exception cref="ConfigException">The target cannot be resolved.</exception>
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

    /// <summary>Builds a pure context budget for one user prompt and an explicit target.</summary>
    /// <param name="prompt">Text sized as the single user message.</param>
    /// <param name="target">
    /// Target whose capabilities supply the context window, output limit and pricing:
    /// <c>provider:model</c>, where provider is a configured instance ID or a registered provider ID or
    /// alias, or a catalog alias.
    /// </param>
    /// <param name="schema">
    /// Response schema whose JSON text is counted toward the input, or <see langword="null"/>.
    /// </param>
    /// <param name="sampling">
    /// Sampling controls, or <see langword="null"/>; only the maximum output tokens affects the budget, as
    /// the default response reserve.
    /// </param>
    /// <param name="outputReserveTokens">
    /// Tokens to reserve for the response. <see langword="null"/> uses <paramref name="sampling"/>'s
    /// maximum output tokens when set, otherwise the smaller of
    /// <see cref="ContextBudgeting.DefaultOutputReserveTokens"/> (4,096) and the model's known output
    /// limit. Must not be negative.
    /// </param>
    /// <param name="tools">Tool declarations counted toward the input, or <see langword="null"/>.</param>
    /// <param name="toolChoice">
    /// Tool-selection mode stored on the planning request; it does not change the estimate.
    /// </param>
    /// <param name="cache">
    /// Prompt-cache policy stored on the planning request; it does not change the estimate.
    /// </param>
    /// <returns>
    /// The input estimate, response reserve, safety headroom and pricing evidence for the target. Unknown
    /// capacity or cost stays unknown.
    /// </returns>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="prompt"/> or <paramref name="target"/> is <see langword="null"/>, or
    /// <paramref name="outputReserveTokens"/> is negative.
    /// </exception>
    /// <exception cref="ConfigException">The target cannot be resolved.</exception>
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
    /// <param name="messages">Conversation messages to size, in order.</param>
    /// <param name="target">
    /// Target whose capabilities supply the context window, output limit and pricing:
    /// <c>provider:model</c>, where provider is a configured instance ID or a registered provider ID or
    /// alias, or a catalog alias.
    /// </param>
    /// <param name="schema">
    /// Response schema whose JSON text is counted toward the input, or <see langword="null"/>.
    /// </param>
    /// <param name="sampling">
    /// Sampling controls, or <see langword="null"/>; only the maximum output tokens affects the budget, as
    /// the default response reserve.
    /// </param>
    /// <param name="outputReserveTokens">
    /// Tokens to reserve for the response. <see langword="null"/> uses <paramref name="sampling"/>'s
    /// maximum output tokens when set, otherwise the smaller of
    /// <see cref="ContextBudgeting.DefaultOutputReserveTokens"/> (4,096) and the model's known output
    /// limit. Must not be negative.
    /// </param>
    /// <param name="tools">Tool declarations counted toward the input, or <see langword="null"/>.</param>
    /// <param name="toolChoice">
    /// Tool-selection mode stored on the planning request; it does not change the estimate.
    /// </param>
    /// <param name="cache">
    /// Prompt-cache policy stored on the planning request; it does not change the estimate.
    /// </param>
    /// <returns>
    /// The input estimate, response reserve, safety headroom and pricing evidence for the target. Unknown
    /// capacity or cost stays unknown.
    /// </returns>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="messages"/> or <paramref name="target"/> is <see langword="null"/>, or
    /// <paramref name="outputReserveTokens"/> is negative.
    /// </exception>
    /// <exception cref="ConfigException">The target cannot be resolved.</exception>
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
    /// <param name="observer">
    /// Observer to notify of every telemetry event this client emits. It is called synchronously on the
    /// thread that emits the event; an exception it throws is suppressed, and the first one per
    /// subscription is traced as a warning on the <c>AnyInfer.Events</c> trace source. It stays owned by
    /// the caller.
    /// </param>
    /// <param name="payloads">
    /// Whether events keep their payload text: the prompt text of <see cref="RequestStarted"/>, the
    /// rejected response text of <see cref="RepairAttempted"/> and the response text of
    /// <see cref="RequestCompleted"/>. With <see langword="false"/> the observer receives copies without
    /// that text.
    /// </param>
    /// <remarks>Subscribing the same observer twice delivers each event to it twice.</remarks>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="observer"/> is <see langword="null"/>.
    /// </exception>
    public void Subscribe(IObserver observer, bool payloads = false) => _dispatcher.Subscribe(observer, payloads);

    /// <summary>Removes every reference-identical observer subscription.</summary>
    /// <param name="observer">
    /// Observer to remove, compared by reference; removing one that is not subscribed does nothing.
    /// </param>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="observer"/> is <see langword="null"/>.
    /// </exception>
    public void Unsubscribe(IObserver observer) => _dispatcher.Unsubscribe(observer);

    /// <summary>
    /// Lists models for one selected provider instance and optionally filters by operation.
    /// </summary>
    /// <param name="providerId">
    /// Provider instance to query: a configured instance ID or, for a client built from provider settings,
    /// a registered provider ID or alias, which then uses that provider's default settings. It is
    /// normalized like provider settings IDs.
    /// </param>
    /// <param name="operation">
    /// Keep only models that support this operation, judged from the provider's declared operations, each
    /// model's discovered operations, the descriptor's static embedding and rerank model facts, or else the
    /// adapter's implemented protocols. <see langword="null"/> returns every listed model.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the discovery call. Cancellation surfaces as
    /// <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <returns>
    /// A task whose result is a read-only snapshot of the listed models, filtered when an operation is
    /// given.
    /// </returns>
    /// <remarks>
    /// The provider's adapter is built first if this client has not built it yet, which resolves its
    /// credentials. Failures raised by the adapter's own call propagate unchanged. The adapter must
    /// implement <see cref="IProviderLifecycle"/>. Model capabilities in the listing are recorded on this
    /// client and feed later capability lookups.
    /// </remarks>
    /// <exception cref="System.ArgumentOutOfRangeException">
    /// <paramref name="operation"/> is not a defined <see cref="InferenceOperation"/> value.
    /// </exception>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="providerId"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ConfigException">
    /// The provider is neither configured nor registered, or its instance cannot be configured.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="UnsupportedInputException">
    /// The provider's adapter does not implement <see cref="IProviderLifecycle"/>.
    /// </exception>
    /// <exception cref="System.InvalidOperationException">
    /// The adapter returned <see langword="null"/> instead of a model listing.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
    /// <param name="providerId">
    /// Provider instance to query: a configured instance ID or, for a client built from provider settings,
    /// a registered provider ID or alias, which then uses that provider's default settings. It is
    /// normalized like provider settings IDs.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the health call. Cancellation surfaces as <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <returns>A task whose result is the provider's current health observation.</returns>
    /// <remarks>
    /// The provider's adapter is built first if this client has not built it yet, which resolves its
    /// credentials. Failures raised by the adapter's own call propagate unchanged. The adapter must
    /// implement <see cref="IProviderLifecycle"/>.
    /// </remarks>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="providerId"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ConfigException">
    /// The provider is neither configured nor registered, or its instance cannot be configured.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="UnsupportedInputException">
    /// The provider's adapter does not implement <see cref="IProviderLifecycle"/>.
    /// </exception>
    /// <exception cref="System.InvalidOperationException">
    /// The adapter returned <see langword="null"/> instead of a health observation.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
    public Task<Health> HealthAsync(string providerId, CancellationToken cancellationToken = default) =>
        HealthCoreAsync(providerId, cancellationToken, CancellationIdentityContext.Resolve(cancellationToken));

    /// <summary>Runs ordered raw generation capability probes against one resolved target.</summary>
    /// <param name="target">
    /// The target to probe: <c>provider:model</c>, where provider is a configured instance ID or a
    /// registered provider ID or alias, or a catalog alias.
    /// </param>
    /// <param name="features">
    /// Features to probe, in order, with one generation request each. Only JSON schema, JSON mode, grammar,
    /// tools and streaming can be probed. <see langword="null"/> uses
    /// <see cref="CapabilityProbes.DefaultProbeFeatures"/>: JSON schema, JSON mode, tools and streaming.
    /// </param>
    /// <param name="timeoutS">
    /// Deadline in seconds for each probe request; 30 by default. It must be positive, finite and at most
    /// 4,294,967.294 seconds.
    /// </param>
    /// <param name="record">
    /// Whether to store the measured features on this client, so later capability lookups and
    /// structured-output mechanism choices use them. With <see langword="false"/> they are only reported.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the remaining probes. Cancellation surfaces as
    /// <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <returns>
    /// A task whose result reports each probe's outcome, the measured capabilities merged with prior facts
    /// (<see langword="null"/> when no probe was conclusive), the number of requests sent and their
    /// reported usage.
    /// </returns>
    /// <remarks>
    /// Each feature is sent directly to the target's adapter, at temperature 0 with at most
    /// <see cref="CapabilityProbes.ProbeMaxOutputTokens"/> output tokens, without routing, retries, repair
    /// or spend-policy admission. A provider rejection records the feature as unsupported and a timeout
    /// records it as inconclusive; neither is thrown.
    /// </remarks>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="target"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="System.ArgumentOutOfRangeException">
    /// <paramref name="timeoutS"/> is outside its documented range.
    /// </exception>
    /// <exception cref="ConfigException">
    /// The target cannot be resolved, a requested feature cannot be probed, or the provider does not
    /// support generation.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
    /// <param name="request">
    /// The embedding request, including its inputs, intent, dimensions, batching policy, timeout and
    /// response limit.
    /// </param>
    /// <param name="target">
    /// One target to embed with when <paramref name="route"/> is <see langword="null"/>:
    /// <c>provider:model</c>, where provider is a configured instance ID or a registered provider ID or
    /// alias, or a catalog alias. It uses the retry and health-gate settings of the client's default route
    /// when one exists. When both are <see langword="null"/>, the client's embedding operation route, then
    /// its default route, is used.
    /// </param>
    /// <param name="route">
    /// Ordered targets with retry and health-gate settings; when supplied it takes precedence over
    /// <paramref name="target"/>. Unless the request allows incompatible fallback, every fallback target
    /// must keep the first target's provider instance and model.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the operation, including pending retries and internal batches. Cancellation surfaces as
    /// <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether the result carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this call, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <returns>
    /// A task whose result holds one vector per input, in input order, with their shared embedding space,
    /// usage, timing, attempts, warnings and, when enabled, the raw payload and manifest.
    /// </returns>
    /// <remarks>
    /// Spend admission estimates the cost on the route's first target. Inputs over the provider's batch
    /// limit are split into internal batches when the batch policy allows it; the operation is
    /// all-or-error, and when any batch fails <see cref="AllTargetsFailedException.BatchFailures"/> records
    /// every batch's outcome.
    /// </remarks>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="request"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ConfigException">
    /// No target, route, operation route or default route is available; a target cannot be resolved or its
    /// provider does not support embedding; a fallback target would change provider instance or model
    /// without allowing incompatible fallback; the inputs exceed a batch limit that may not be split; or
    /// the provider's vectors are malformed or incompatible with the expected space.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">The client's spend policy refuses the request.</exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed, or an internal batch failed.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
    /// <param name="input">Text to embed.</param>
    /// <param name="target">
    /// One target to embed with when <paramref name="route"/> is <see langword="null"/>:
    /// <c>provider:model</c>, where provider is a configured instance ID or a registered provider ID or
    /// alias, or a catalog alias. It uses the retry and health-gate settings of the client's default route
    /// when one exists. When both are <see langword="null"/>, the client's embedding operation route, then
    /// its default route, is used.
    /// </param>
    /// <param name="route">
    /// Ordered targets with retry and health-gate settings; when supplied it takes precedence over
    /// <paramref name="target"/>. Unless <paramref name="allowIncompatibleFallback"/> is
    /// <see langword="true"/>, every fallback target must keep the first target's provider instance and
    /// model.
    /// </param>
    /// <param name="inputType">
    /// Intent of the input, such as query or document, for providers whose embeddings depend on it;
    /// <see langword="null"/> sends none. A target that does not support the intent adds a warning to the
    /// result.
    /// </param>
    /// <param name="dimensions">
    /// Output dimensionality to request from the provider; <see langword="null"/> uses the model's default.
    /// </param>
    /// <param name="expectedSpace">
    /// Embedding space the vectors must be compatible with, for example the space of vectors already
    /// stored; an incompatible result fails with <see cref="ConfigException"/>. <see langword="null"/>
    /// skips the check.
    /// </param>
    /// <param name="allowIncompatibleFallback">
    /// Whether route fallback may move to a different provider instance or model, whose vectors are not
    /// proven comparable; such a result carries a warning. With <see langword="false"/> that fallback fails
    /// with <see cref="ConfigException"/>.
    /// </param>
    /// <param name="batch">
    /// Batching policy for inputs over the provider's batch limit; <see langword="null"/> uses the default
    /// <see cref="BatchPolicy"/>, which splits into up to four concurrent batches.
    /// </param>
    /// <param name="timeoutS">
    /// Deadline in seconds for each provider call; <see langword="null"/> uses 120 seconds. A call that
    /// runs out of time fails as a retryable provider timeout.
    /// </param>
    /// <param name="providerOptions">
    /// Extra provider options keyed by provider instance ID, as it appears in resolved targets; only the
    /// selected instance's map is passed to its adapter. <see langword="null"/> for none.
    /// </param>
    /// <param name="metadata">
    /// Opaque caller labels reported on the <see cref="RequestStarted"/> event and usable for
    /// <see cref="SpendLedger"/> grouping; they are not sent to the provider. <see langword="null"/> for
    /// none.
    /// </param>
    /// <param name="maxResponseBytes">
    /// Upper bound in bytes on each provider response; <see langword="null"/> uses 64 MiB.
    /// </param>
    /// <param name="retainRaw">
    /// Whether the result keeps the raw provider payload, combined across internal batches;
    /// <see langword="null"/> uses the client's <c>retainRaw</c> setting.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the operation, including pending retries and internal batches. Cancellation surfaces as
    /// <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether the result carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this call, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <returns>
    /// A task whose result holds the input's vector with its embedding space, usage, timing, attempts,
    /// warnings and, when enabled, the raw payload and manifest.
    /// </returns>
    /// <remarks>Spend admission estimates the cost on the route's first target.</remarks>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="input"/> is <see langword="null"/>, or another argument is invalid.
    /// </exception>
    /// <exception cref="ConfigException">
    /// No target, route, operation route or default route is available; a target cannot be resolved or its
    /// provider does not support embedding; a fallback target would change provider instance or model
    /// without allowing incompatible fallback; the inputs exceed a batch limit that may not be split; or
    /// the provider's vectors are malformed or incompatible with the expected space.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">The client's spend policy refuses the request.</exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed, or an internal batch failed.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
    /// <param name="inputs">
    /// Texts to embed, in order. There must be at least one, and none may be <see langword="null"/>.
    /// </param>
    /// <param name="target">
    /// One target to embed with when <paramref name="route"/> is <see langword="null"/>:
    /// <c>provider:model</c>, where provider is a configured instance ID or a registered provider ID or
    /// alias, or a catalog alias. It uses the retry and health-gate settings of the client's default route
    /// when one exists. When both are <see langword="null"/>, the client's embedding operation route, then
    /// its default route, is used.
    /// </param>
    /// <param name="route">
    /// Ordered targets with retry and health-gate settings; when supplied it takes precedence over
    /// <paramref name="target"/>. Unless <paramref name="allowIncompatibleFallback"/> is
    /// <see langword="true"/>, every fallback target must keep the first target's provider instance and
    /// model.
    /// </param>
    /// <param name="inputType">
    /// Intent of the input, such as query or document, for providers whose embeddings depend on it;
    /// <see langword="null"/> sends none. A target that does not support the intent adds a warning to the
    /// result.
    /// </param>
    /// <param name="dimensions">
    /// Output dimensionality to request from the provider; <see langword="null"/> uses the model's default.
    /// </param>
    /// <param name="expectedSpace">
    /// Embedding space the vectors must be compatible with, for example the space of vectors already
    /// stored; an incompatible result fails with <see cref="ConfigException"/>. <see langword="null"/>
    /// skips the check.
    /// </param>
    /// <param name="allowIncompatibleFallback">
    /// Whether route fallback may move to a different provider instance or model, whose vectors are not
    /// proven comparable; such a result carries a warning. With <see langword="false"/> that fallback fails
    /// with <see cref="ConfigException"/>.
    /// </param>
    /// <param name="batch">
    /// Batching policy for inputs over the provider's batch limit; <see langword="null"/> uses the default
    /// <see cref="BatchPolicy"/>, which splits into up to four concurrent batches.
    /// </param>
    /// <param name="timeoutS">
    /// Deadline in seconds for each provider call; <see langword="null"/> uses 120 seconds. A call that
    /// runs out of time fails as a retryable provider timeout.
    /// </param>
    /// <param name="providerOptions">
    /// Extra provider options keyed by provider instance ID, as it appears in resolved targets; only the
    /// selected instance's map is passed to its adapter. <see langword="null"/> for none.
    /// </param>
    /// <param name="metadata">
    /// Opaque caller labels reported on the <see cref="RequestStarted"/> event and usable for
    /// <see cref="SpendLedger"/> grouping; they are not sent to the provider. <see langword="null"/> for
    /// none.
    /// </param>
    /// <param name="maxResponseBytes">
    /// Upper bound in bytes on each provider response; <see langword="null"/> uses 64 MiB.
    /// </param>
    /// <param name="retainRaw">
    /// Whether the result keeps the raw provider payload, combined across internal batches;
    /// <see langword="null"/> uses the client's <c>retainRaw</c> setting.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the operation, including pending retries and internal batches. Cancellation surfaces as
    /// <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether the result carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this call, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <returns>
    /// A task whose result holds one vector per input, in input order, with their shared embedding space,
    /// usage, timing, attempts, warnings and, when enabled, the raw payload and manifest.
    /// </returns>
    /// <remarks>
    /// Spend admission estimates the cost on the route's first target. Inputs over the provider's batch
    /// limit are split into internal batches when the batch policy allows it; the operation is
    /// all-or-error, and when any batch fails <see cref="AllTargetsFailedException.BatchFailures"/> records
    /// every batch's outcome.
    /// </remarks>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="inputs"/> is <see langword="null"/>, is empty or contains <see langword="null"/>, or
    /// another argument is invalid.
    /// </exception>
    /// <exception cref="ConfigException">
    /// No target, route, operation route or default route is available; a target cannot be resolved or its
    /// provider does not support embedding; a fallback target would change provider instance or model
    /// without allowing incompatible fallback; the inputs exceed a batch limit that may not be split; or
    /// the provider's vectors are malformed or incompatible with the expected space.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">The client's spend policy refuses the request.</exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed, or an internal batch failed.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
    /// <param name="request">
    /// The rerank request, including its query, documents, top-N limit, batching policy, timeout and
    /// response limit.
    /// </param>
    /// <param name="target">
    /// One target to rank with when <paramref name="route"/> is <see langword="null"/>:
    /// <c>provider:model</c>, where provider is a configured instance ID or a registered provider ID or
    /// alias, or a catalog alias. It uses the retry and health-gate settings of the client's default route
    /// when one exists. When both are <see langword="null"/>, the client's rerank operation route, then its
    /// default route, is used.
    /// </param>
    /// <param name="route">
    /// Ordered targets with retry and health-gate settings; when supplied it takes precedence over
    /// <paramref name="target"/>.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the operation, including pending retries and internal batches. Cancellation surfaces as
    /// <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether the result carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this call, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <returns>
    /// A task whose result holds the ranked items in provider order, each with its score, document ID and
    /// original index, plus usage, timing, attempts, warnings and, when enabled, the raw payload and
    /// manifest.
    /// </returns>
    /// <remarks>
    /// Rerank cost is not estimated before dispatch, so a spend policy that refuses unknown costs refuses
    /// the request. A split request reports chunk-local rankings with a warning; the operation is
    /// all-or-error, and when any batch fails <see cref="AllTargetsFailedException.BatchFailures"/> records
    /// every batch's outcome.
    /// </remarks>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="request"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ConfigException">
    /// No target, route, operation route or default route is available; a target cannot be resolved or its
    /// provider does not support reranking; the documents exceed a batch limit that may not be split; or
    /// the provider returned an invalid ranked item.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">
    /// The client's spend policy refuses requests of unknown cost.
    /// </exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed, or an internal batch failed.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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

    /// <inheritdoc cref="RerankAsync(string, IEnumerable{RerankDocument}, string, Route, int?, BatchPolicy, double?, IReadOnlyDictionary{string, IReadOnlyDictionary{string, JsonValue}}, IReadOnlyDictionary{string, string}, int?, bool, bool?, CancellationToken, bool?)"/>
    /// <summary>
    /// Reranks ordered document texts through the selected retrieval route, using each text's zero-based
    /// position, in invariant-culture digits, as its document ID.
    /// </summary>
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
    /// <param name="query">Query text to rank the documents against; it must not be empty.</param>
    /// <param name="documents">
    /// Documents to rank, in order; there must be at least one. Ranked items report each document's ID and
    /// its original zero-based position.
    /// </param>
    /// <param name="target">
    /// One target to rank with when <paramref name="route"/> is <see langword="null"/>:
    /// <c>provider:model</c>, where provider is a configured instance ID or a registered provider ID or
    /// alias, or a catalog alias. It uses the retry and health-gate settings of the client's default route
    /// when one exists. When both are <see langword="null"/>, the client's rerank operation route, then its
    /// default route, is used.
    /// </param>
    /// <param name="route">
    /// Ordered targets with retry and health-gate settings; when supplied it takes precedence over
    /// <paramref name="target"/>.
    /// </param>
    /// <param name="topN">
    /// Maximum number of ranked items to return, at least 1; <see langword="null"/> returns every document.
    /// When the request is split into internal batches it applies within each batch.
    /// </param>
    /// <param name="batch">
    /// Batching policy for documents over the provider's limit; <see langword="null"/> uses the default
    /// <see cref="BatchPolicy"/>, which does not allow cross-batch reranking, so such a request fails
    /// instead of being split.
    /// </param>
    /// <param name="timeoutS">
    /// Deadline in seconds for each provider call; <see langword="null"/> uses 120 seconds. A call that
    /// runs out of time fails as a retryable provider timeout.
    /// </param>
    /// <param name="providerOptions">
    /// Extra provider options keyed by provider instance ID, as it appears in resolved targets; only the
    /// selected instance's map is passed to its adapter. <see langword="null"/> for none.
    /// </param>
    /// <param name="metadata">
    /// Opaque caller labels reported on the <see cref="RequestStarted"/> event and usable for
    /// <see cref="SpendLedger"/> grouping; they are not sent to the provider. <see langword="null"/> for
    /// none.
    /// </param>
    /// <param name="maxResponseBytes">
    /// Upper bound in bytes on each provider response; <see langword="null"/> uses 8 MiB.
    /// </param>
    /// <param name="returnDocuments">Whether ranked items echo each document's text.</param>
    /// <param name="retainRaw">
    /// Whether the result keeps the raw provider payload, combined across internal batches;
    /// <see langword="null"/> uses the client's <c>retainRaw</c> setting.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the operation, including pending retries and internal batches. Cancellation surfaces as
    /// <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether the result carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this call, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <returns>
    /// A task whose result holds the ranked items in provider order, each with its score, document ID and
    /// original index, plus usage, timing, attempts, warnings and, when enabled, the raw payload and
    /// manifest.
    /// </returns>
    /// <remarks>
    /// Rerank cost is not estimated before dispatch, so a spend policy that refuses unknown costs refuses
    /// the request. A split request reports chunk-local rankings with a warning; the operation is
    /// all-or-error, and when any batch fails <see cref="AllTargetsFailedException.BatchFailures"/> records
    /// every batch's outcome.
    /// </remarks>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="query"/> or <paramref name="documents"/> is <see langword="null"/>; the query is
    /// empty; the documents are empty, contain <see langword="null"/> or repeat an ID; or
    /// <paramref name="topN"/> is less than 1.
    /// </exception>
    /// <exception cref="ConfigException">
    /// No target, route, operation route or default route is available; a target cannot be resolved or its
    /// provider does not support reranking; the documents exceed a batch limit that may not be split; or
    /// the provider returned an invalid ranked item.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">
    /// The client's spend policy refuses requests of unknown cost.
    /// </exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed, or an internal batch failed.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
    /// <summary>Generates a buffered result from a complete request.</summary>
    /// <param name="request">
    /// The request to run. Its route selects the targets; a request without a repair budget uses the
    /// client's default repair, and one without a cache policy uses the client's default cache policy.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the operation, including pending retries, fallbacks and repair round trips. Cancellation
    /// surfaces as <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether the result carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this call, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <returns>
    /// A task whose result is the winning generation: its text, any structured value and tool calls, usage,
    /// timing, attempts and, when enabled, its manifest.
    /// </returns>
    /// <remarks>
    /// Generation runs the same execution path as streaming and collects it to its terminal result. The
    /// request's <see cref="GenerationRequest.Stream"/> flag is passed to the adapter as given.
    /// </remarks>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="request"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ProviderException">
    /// The messages use a role or content type outside the supported request profile, or the sampling seed
    /// is negative or a penalty is not finite.
    /// </exception>
    /// <exception cref="ConfigException">
    /// A target cannot be resolved, a provider instance cannot be configured, or the selected provider does
    /// not support generation.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">The client's spend policy refuses the request.</exception>
    /// <exception cref="SchemaViolationException">
    /// The response still fails the schema after the repair budget is spent.
    /// </exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed; <see cref="AllTargetsFailedException.Attempts"/> lists each
    /// attempt.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
    public Task<Generation> GenerateAsync(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        GenerateAsync(request, capture: null, cancellationToken: cancellationToken, manifest: manifest);

    /// <summary>
    /// Generates and dispatches explicitly registered tools until the model stops calling them.
    /// </summary>
    /// <param name="request">
    /// The starting request. Its messages begin the conversation and its other settings apply to every
    /// round; its tool declarations are replaced by the registered tools' declarations.
    /// </param>
    /// <param name="tools">
    /// Handlers to register, in order. A later tool with the same name replaces the earlier one in its
    /// position, and only registered tools are dispatched.
    /// </param>
    /// <param name="maxRounds">
    /// Maximum number of generation rounds; 8 by default. The loop fails if the model is still calling
    /// tools after this many rounds.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the loop, including a running generation and the token passed to a running tool handler.
    /// Cancellation surfaces as <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether each round's generation carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this loop, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <returns>
    /// A task whose result is the final round's generation, the first whose finish reason is not
    /// <c>tool_calls</c>. Its usage, attempts and manifest describe that round only.
    /// </returns>
    /// <remarks>
    /// Each round generates from the conversation so far. When a round finishes with tool calls, the calls
    /// are dispatched to their handlers one at a time, in order, and the assistant's calls and each
    /// handler's output are appended to the conversation before the next round. A handler exception other
    /// than <see cref="System.OperationCanceledException"/> is returned to the model as an error tool
    /// result instead of being thrown.
    /// </remarks>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="request"/> or <paramref name="tools"/> is <see langword="null"/>, or
    /// <paramref name="tools"/> contains <see langword="null"/>.
    /// </exception>
    /// <exception cref="ProviderException">
    /// The messages use a role or content type outside the supported request profile, or the sampling seed
    /// is negative or a penalty is not finite.
    /// </exception>
    /// <exception cref="ConfigException">
    /// A target cannot be resolved, a provider instance cannot be configured, or the selected provider does
    /// not support generation.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">The client's spend policy refuses the request.</exception>
    /// <exception cref="SchemaViolationException">
    /// The response still fails the schema after the repair budget is spent.
    /// </exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed; <see cref="AllTargetsFailedException.Attempts"/> lists each
    /// attempt.
    /// </exception>
    /// <exception cref="ToolLoopException">
    /// The model called a tool that is not registered, or <paramref name="maxRounds"/> rounds ended with
    /// tool calls still pending; with a <paramref name="maxRounds"/> below 1 this happens before any
    /// generation.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
    public Task<Generation> RunToolsAsync(
        GenerationRequest request,
        IEnumerable<Tool> tools,
        int maxRounds = 8,
        CancellationToken cancellationToken = default,
        bool? manifest = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(tools);
        return RunToolsCoreAsync(
            request,
            new ToolRegistry(tools),
            maxRounds,
            cancellationToken,
            CancellationIdentityContext.Resolve(cancellationToken),
            manifest);
    }

    /// <summary>Generates from one prompt while dispatching explicitly registered tools.</summary>
    /// <param name="prompt">Text sent as the single user message.</param>
    /// <param name="tools">
    /// Handlers to register, in order. A later tool with the same name replaces the earlier one in its
    /// position, and only registered tools are dispatched.
    /// </param>
    /// <param name="target">
    /// One target to run when <paramref name="route"/> is <see langword="null"/>: <c>provider:model</c>,
    /// where provider is a configured instance ID or a registered provider ID or alias, or a catalog alias.
    /// It uses the retry and health-gate settings of the client's default route when one exists. When both
    /// are <see langword="null"/>, the client's default route is used.
    /// </param>
    /// <param name="route">
    /// Ordered targets with retry, health-gate and context-window fallback settings. When supplied it takes
    /// precedence, and <paramref name="target"/> is ignored.
    /// </param>
    /// <param name="sampling">
    /// Sampling controls such as temperature, top-p, maximum output tokens, stop sequences, seed and
    /// penalties; <see langword="null"/> leaves every value to the provider. A value the provider's
    /// descriptor declares it ignores is reported with a <see cref="ParameterDropped"/> event.
    /// </param>
    /// <param name="repair">
    /// Structured-output repair budget, used only with <paramref name="schema"/>; <see langword="null"/>
    /// uses the client's default repair, and with neither no repair round trip is made. A provider's
    /// declared repair ceiling can lower it, reported with a <see cref="ParameterDropped"/> event.
    /// </param>
    /// <param name="schema">
    /// Schema the response text must satisfy, or <see langword="null"/> for free text. The core uses the
    /// strongest mechanism the target supports (grammar, JSON schema, JSON mode, then prompt instructions),
    /// validates the response and spends the repair budget on corrections; the parsed value is returned in
    /// <see cref="Generation.Structured"/>.
    /// </param>
    /// <param name="schemaMechanism">
    /// A structured-output mechanism name stored on the request as
    /// <see cref="GenerationRequest.SchemaMechanism"/>. Generation chooses the mechanism from the target's
    /// capabilities and does not act on this value.
    /// </param>
    /// <param name="timeoutS">
    /// Deadline in seconds for each provider call, applied separately to every attempt and repair round
    /// trip; <see langword="null"/> uses the provider instance's <see cref="ProviderSettings.TimeoutS"/>,
    /// 120 seconds unless configured.
    /// </param>
    /// <param name="maxResponseBytes">
    /// Upper bound in bytes on each provider response the adapter reads; <see langword="null"/> uses 1 MiB
    /// (1,048,576 bytes).
    /// </param>
    /// <param name="toolChoice">
    /// How the model may use the registered tools: <c>auto</c> (the default), <c>none</c>, <c>required</c>,
    /// or the name of one registered tool to force it. Must not be <see langword="null"/>.
    /// </param>
    /// <param name="cache">
    /// Prompt-cache planning policy for this request; <see langword="null"/> uses the client's default
    /// cache policy, and with neither no cache placement is planned.
    /// </param>
    /// <param name="reasoning">
    /// Reasoning effort to request, such as <c>none</c>, <c>minimal</c>, <c>low</c>, <c>medium</c> or
    /// <c>high</c>; <see langword="null"/> keeps the provider default. The provider descriptor translates
    /// it to its wire form, and it is not sent, with a <see cref="ParameterDropped"/> event, when the
    /// model's trusted capabilities exclude reasoning.
    /// </param>
    /// <param name="providerOptions">
    /// Extra provider request options keyed by provider instance ID, or by <c>*</c> for every provider. For
    /// the selected target the <c>*</c> properties apply first and that instance's own properties override
    /// them; the merged object reaches the adapter as <see cref="WireRequest.ExtraOptions"/>, which the
    /// built-in OpenAI-compatible adapter overlays onto its request body. <see langword="null"/> for none.
    /// </param>
    /// <param name="metadata">
    /// Opaque caller labels copied onto the request and not sent to the provider. They are reported on the
    /// <see cref="RequestStarted"/> event, their keys are recorded in the manifest, and a
    /// <see cref="SpendLedger"/> can group spend by them. <see langword="null"/> for none.
    /// </param>
    /// <param name="logprobs">
    /// Number of alternative tokens, from 0 to 20, to report with each generated token's log-probability,
    /// or <see langword="null"/> for no log-probabilities. It is not requested, with a
    /// <see cref="ParameterDropped"/> event, when the model's trusted capabilities exclude
    /// log-probabilities.
    /// </param>
    /// <param name="citeDocuments">
    /// Whether to ask the provider to cite supplied documents; citations are returned in
    /// <see cref="Generation.Citations"/>. It is not requested, with a <see cref="ParameterDropped"/>
    /// event, when the model's trusted capabilities exclude citations.
    /// </param>
    /// <param name="serverTools">
    /// Provider-run tools, such as web search or code execution, to enable for this request, or
    /// <see langword="null"/> for none. An attempt on a target whose provider or model cannot run a
    /// requested kind fails with <see cref="UnsupportedInputException"/>.
    /// </param>
    /// <param name="maxInputPartBytes">
    /// Largest inline media payload, in bytes, allowed in any one message part; 20 MiB by default. Must be
    /// at least 1.
    /// </param>
    /// <param name="maxInputBytes">
    /// Largest total of inline media payload bytes across all messages; 50 MiB by default. Must be at least
    /// 1.
    /// </param>
    /// <param name="maxRounds">
    /// Maximum number of generation rounds; 8 by default. The loop fails if the model is still calling
    /// tools after this many rounds.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the loop, including a running generation and the token passed to a running tool handler.
    /// Cancellation surfaces as <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether each round's generation carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this loop, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <returns>
    /// A task whose result is the final round's generation, the first whose finish reason is not
    /// <c>tool_calls</c>. Its usage, attempts and manifest describe that round only.
    /// </returns>
    /// <remarks>
    /// Each round generates from the conversation so far. When a round finishes with tool calls, the calls
    /// are dispatched to their handlers one at a time, in order, and the assistant's calls and each
    /// handler's output are appended to the conversation before the next round. A handler exception other
    /// than <see cref="System.OperationCanceledException"/> is returned to the model as an error tool
    /// result instead of being thrown.
    /// </remarks>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="prompt"/>, <paramref name="tools"/> or another required argument is
    /// <see langword="null"/>, <paramref name="tools"/> contains <see langword="null"/>, or a value is
    /// outside its documented range, such as <c>logprobs</c> outside 0 to 20 or inline media over its byte
    /// limits.
    /// </exception>
    /// <exception cref="ProviderException">
    /// The sampling seed is negative or a penalty is not finite.
    /// </exception>
    /// <exception cref="ConfigException">
    /// No target, route or client default route is available, a target cannot be resolved, a provider
    /// instance cannot be configured, or the selected provider does not support generation.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">The client's spend policy refuses the request.</exception>
    /// <exception cref="SchemaViolationException">
    /// The response still fails the schema after the repair budget is spent.
    /// </exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed; <see cref="AllTargetsFailedException.Attempts"/> lists each
    /// attempt.
    /// </exception>
    /// <exception cref="ToolLoopException">
    /// The model called a tool that is not registered, or <paramref name="maxRounds"/> rounds ended with
    /// tool calls still pending; with a <paramref name="maxRounds"/> below 1 this happens before any
    /// generation.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
    public Task<Generation> RunToolsAsync(
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
        RunToolsAsync(
            CreateConvenienceRequest([Message.User(prompt)], target, route, sampling, repair, schema,
                schemaMechanism, timeoutS, maxResponseBytes, false, null, toolChoice, cache,
                reasoning, providerOptions, metadata, logprobs, citeDocuments, serverTools,
                maxInputPartBytes, maxInputBytes),
            tools, maxRounds, cancellationToken, manifest);

    /// <summary>Generates from caller messages while dispatching explicitly registered tools.</summary>
    /// <param name="messages">
    /// Conversation messages in order, using the <c>system</c>, <c>user</c>, <c>assistant</c> and
    /// <c>tool</c> roles. They are copied, and a <see langword="null"/> element is rejected.
    /// </param>
    /// <param name="tools">
    /// Handlers to register, in order. A later tool with the same name replaces the earlier one in its
    /// position, and only registered tools are dispatched.
    /// </param>
    /// <param name="target">
    /// One target to run when <paramref name="route"/> is <see langword="null"/>: <c>provider:model</c>,
    /// where provider is a configured instance ID or a registered provider ID or alias, or a catalog alias.
    /// It uses the retry and health-gate settings of the client's default route when one exists. When both
    /// are <see langword="null"/>, the client's default route is used.
    /// </param>
    /// <param name="route">
    /// Ordered targets with retry, health-gate and context-window fallback settings. When supplied it takes
    /// precedence, and <paramref name="target"/> is ignored.
    /// </param>
    /// <param name="sampling">
    /// Sampling controls such as temperature, top-p, maximum output tokens, stop sequences, seed and
    /// penalties; <see langword="null"/> leaves every value to the provider. A value the provider's
    /// descriptor declares it ignores is reported with a <see cref="ParameterDropped"/> event.
    /// </param>
    /// <param name="repair">
    /// Structured-output repair budget, used only with <paramref name="schema"/>; <see langword="null"/>
    /// uses the client's default repair, and with neither no repair round trip is made. A provider's
    /// declared repair ceiling can lower it, reported with a <see cref="ParameterDropped"/> event.
    /// </param>
    /// <param name="schema">
    /// Schema the response text must satisfy, or <see langword="null"/> for free text. The core uses the
    /// strongest mechanism the target supports (grammar, JSON schema, JSON mode, then prompt instructions),
    /// validates the response and spends the repair budget on corrections; the parsed value is returned in
    /// <see cref="Generation.Structured"/>.
    /// </param>
    /// <param name="schemaMechanism">
    /// A structured-output mechanism name stored on the request as
    /// <see cref="GenerationRequest.SchemaMechanism"/>. Generation chooses the mechanism from the target's
    /// capabilities and does not act on this value.
    /// </param>
    /// <param name="timeoutS">
    /// Deadline in seconds for each provider call, applied separately to every attempt and repair round
    /// trip; <see langword="null"/> uses the provider instance's <see cref="ProviderSettings.TimeoutS"/>,
    /// 120 seconds unless configured.
    /// </param>
    /// <param name="maxResponseBytes">
    /// Upper bound in bytes on each provider response the adapter reads; <see langword="null"/> uses 1 MiB
    /// (1,048,576 bytes).
    /// </param>
    /// <param name="toolChoice">
    /// How the model may use the registered tools: <c>auto</c> (the default), <c>none</c>, <c>required</c>,
    /// or the name of one registered tool to force it. Must not be <see langword="null"/>.
    /// </param>
    /// <param name="cache">
    /// Prompt-cache planning policy for this request; <see langword="null"/> uses the client's default
    /// cache policy, and with neither no cache placement is planned.
    /// </param>
    /// <param name="reasoning">
    /// Reasoning effort to request, such as <c>none</c>, <c>minimal</c>, <c>low</c>, <c>medium</c> or
    /// <c>high</c>; <see langword="null"/> keeps the provider default. The provider descriptor translates
    /// it to its wire form, and it is not sent, with a <see cref="ParameterDropped"/> event, when the
    /// model's trusted capabilities exclude reasoning.
    /// </param>
    /// <param name="providerOptions">
    /// Extra provider request options keyed by provider instance ID, or by <c>*</c> for every provider. For
    /// the selected target the <c>*</c> properties apply first and that instance's own properties override
    /// them; the merged object reaches the adapter as <see cref="WireRequest.ExtraOptions"/>, which the
    /// built-in OpenAI-compatible adapter overlays onto its request body. <see langword="null"/> for none.
    /// </param>
    /// <param name="metadata">
    /// Opaque caller labels copied onto the request and not sent to the provider. They are reported on the
    /// <see cref="RequestStarted"/> event, their keys are recorded in the manifest, and a
    /// <see cref="SpendLedger"/> can group spend by them. <see langword="null"/> for none.
    /// </param>
    /// <param name="logprobs">
    /// Number of alternative tokens, from 0 to 20, to report with each generated token's log-probability,
    /// or <see langword="null"/> for no log-probabilities. It is not requested, with a
    /// <see cref="ParameterDropped"/> event, when the model's trusted capabilities exclude
    /// log-probabilities.
    /// </param>
    /// <param name="citeDocuments">
    /// Whether to ask the provider to cite supplied documents; citations are returned in
    /// <see cref="Generation.Citations"/>. It is not requested, with a <see cref="ParameterDropped"/>
    /// event, when the model's trusted capabilities exclude citations.
    /// </param>
    /// <param name="serverTools">
    /// Provider-run tools, such as web search or code execution, to enable for this request, or
    /// <see langword="null"/> for none. An attempt on a target whose provider or model cannot run a
    /// requested kind fails with <see cref="UnsupportedInputException"/>.
    /// </param>
    /// <param name="maxInputPartBytes">
    /// Largest inline media payload, in bytes, allowed in any one message part; 20 MiB by default. Must be
    /// at least 1.
    /// </param>
    /// <param name="maxInputBytes">
    /// Largest total of inline media payload bytes across all messages; 50 MiB by default. Must be at least
    /// 1.
    /// </param>
    /// <param name="maxRounds">
    /// Maximum number of generation rounds; 8 by default. The loop fails if the model is still calling
    /// tools after this many rounds.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the loop, including a running generation and the token passed to a running tool handler.
    /// Cancellation surfaces as <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether each round's generation carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this loop, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <returns>
    /// A task whose result is the final round's generation, the first whose finish reason is not
    /// <c>tool_calls</c>. Its usage, attempts and manifest describe that round only.
    /// </returns>
    /// <remarks>
    /// Each round generates from the conversation so far. When a round finishes with tool calls, the calls
    /// are dispatched to their handlers one at a time, in order, and the assistant's calls and each
    /// handler's output are appended to the conversation before the next round. A handler exception other
    /// than <see cref="System.OperationCanceledException"/> is returned to the model as an error tool
    /// result instead of being thrown.
    /// </remarks>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="messages"/>, <paramref name="tools"/> or another required argument is
    /// <see langword="null"/>, <paramref name="tools"/> contains <see langword="null"/>, or a value is
    /// outside its documented range, such as <c>logprobs</c> outside 0 to 20 or inline media over its byte
    /// limits.
    /// </exception>
    /// <exception cref="ProviderException">
    /// The messages use a role or content type outside the supported request profile, or the sampling seed
    /// is negative or a penalty is not finite.
    /// </exception>
    /// <exception cref="ConfigException">
    /// No target, route or client default route is available, a target cannot be resolved, a provider
    /// instance cannot be configured, or the selected provider does not support generation.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">The client's spend policy refuses the request.</exception>
    /// <exception cref="SchemaViolationException">
    /// The response still fails the schema after the repair budget is spent.
    /// </exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed; <see cref="AllTargetsFailedException.Attempts"/> lists each
    /// attempt.
    /// </exception>
    /// <exception cref="ToolLoopException">
    /// The model called a tool that is not registered, or <paramref name="maxRounds"/> rounds ended with
    /// tool calls still pending; with a <paramref name="maxRounds"/> below 1 this happens before any
    /// generation.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
    public Task<Generation> RunToolsAsync(
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
        RunToolsAsync(
            CreateConvenienceRequest(messages, target, route, sampling, repair, schema, schemaMechanism,
                timeoutS, maxResponseBytes, false, null, toolChoice, cache, reasoning,
                providerOptions, metadata, logprobs, citeDocuments, serverTools, maxInputPartBytes,
                maxInputBytes),
            tools, maxRounds, cancellationToken, manifest);

    /// <summary>Generates a buffered result from one user prompt.</summary>
    /// <param name="prompt">Text sent as the single user message.</param>
    /// <param name="target">
    /// One target to run when <paramref name="route"/> is <see langword="null"/>: <c>provider:model</c>,
    /// where provider is a configured instance ID or a registered provider ID or alias, or a catalog alias.
    /// It uses the retry and health-gate settings of the client's default route when one exists. When both
    /// are <see langword="null"/>, the client's default route is used.
    /// </param>
    /// <param name="route">
    /// Ordered targets with retry, health-gate and context-window fallback settings. When supplied it takes
    /// precedence, and <paramref name="target"/> is ignored.
    /// </param>
    /// <param name="sampling">
    /// Sampling controls such as temperature, top-p, maximum output tokens, stop sequences, seed and
    /// penalties; <see langword="null"/> leaves every value to the provider. A value the provider's
    /// descriptor declares it ignores is reported with a <see cref="ParameterDropped"/> event.
    /// </param>
    /// <param name="repair">
    /// Structured-output repair budget, used only with <paramref name="schema"/>; <see langword="null"/>
    /// uses the client's default repair, and with neither no repair round trip is made. A provider's
    /// declared repair ceiling can lower it, reported with a <see cref="ParameterDropped"/> event.
    /// </param>
    /// <param name="schema">
    /// Schema the response text must satisfy, or <see langword="null"/> for free text. The core uses the
    /// strongest mechanism the target supports (grammar, JSON schema, JSON mode, then prompt instructions),
    /// validates the response and spends the repair budget on corrections; the parsed value is returned in
    /// <see cref="Generation.Structured"/>.
    /// </param>
    /// <param name="schemaMechanism">
    /// A structured-output mechanism name stored on the request as
    /// <see cref="GenerationRequest.SchemaMechanism"/>. Generation chooses the mechanism from the target's
    /// capabilities and does not act on this value.
    /// </param>
    /// <param name="timeoutS">
    /// Deadline in seconds for each provider call, applied separately to every attempt and repair round
    /// trip; <see langword="null"/> uses the provider instance's <see cref="ProviderSettings.TimeoutS"/>,
    /// 120 seconds unless configured.
    /// </param>
    /// <param name="maxResponseBytes">
    /// Upper bound in bytes on each provider response the adapter reads; <see langword="null"/> uses 1 MiB
    /// (1,048,576 bytes).
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the operation, including pending retries, fallbacks and repair round trips. Cancellation
    /// surfaces as <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether the result carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this call, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <param name="tools">
    /// Tool declarations advertised to the model, or <see langword="null"/> for none. They are not
    /// executed: calls the model requests are returned in <see cref="Generation.ToolCalls"/>.
    /// </param>
    /// <param name="toolChoice">
    /// How the model may use the declared tools: <c>auto</c> (the default), <c>none</c>, <c>required</c>,
    /// or the name of one declared tool to force it. Must not be <see langword="null"/>.
    /// </param>
    /// <param name="cache">
    /// Prompt-cache planning policy for this request; <see langword="null"/> uses the client's default
    /// cache policy, and with neither no cache placement is planned.
    /// </param>
    /// <param name="reasoning">
    /// Reasoning effort to request, such as <c>none</c>, <c>minimal</c>, <c>low</c>, <c>medium</c> or
    /// <c>high</c>; <see langword="null"/> keeps the provider default. The provider descriptor translates
    /// it to its wire form, and it is not sent, with a <see cref="ParameterDropped"/> event, when the
    /// model's trusted capabilities exclude reasoning.
    /// </param>
    /// <param name="providerOptions">
    /// Extra provider request options keyed by provider instance ID, or by <c>*</c> for every provider. For
    /// the selected target the <c>*</c> properties apply first and that instance's own properties override
    /// them; the merged object reaches the adapter as <see cref="WireRequest.ExtraOptions"/>, which the
    /// built-in OpenAI-compatible adapter overlays onto its request body. <see langword="null"/> for none.
    /// </param>
    /// <param name="metadata">
    /// Opaque caller labels copied onto the request and not sent to the provider. They are reported on the
    /// <see cref="RequestStarted"/> event, their keys are recorded in the manifest, and a
    /// <see cref="SpendLedger"/> can group spend by them. <see langword="null"/> for none.
    /// </param>
    /// <param name="logprobs">
    /// Number of alternative tokens, from 0 to 20, to report with each generated token's log-probability,
    /// or <see langword="null"/> for no log-probabilities. It is not requested, with a
    /// <see cref="ParameterDropped"/> event, when the model's trusted capabilities exclude
    /// log-probabilities.
    /// </param>
    /// <param name="citeDocuments">
    /// Whether to ask the provider to cite supplied documents; citations are returned in
    /// <see cref="Generation.Citations"/>. It is not requested, with a <see cref="ParameterDropped"/>
    /// event, when the model's trusted capabilities exclude citations.
    /// </param>
    /// <param name="serverTools">
    /// Provider-run tools, such as web search or code execution, to enable for this request, or
    /// <see langword="null"/> for none. An attempt on a target whose provider or model cannot run a
    /// requested kind fails with <see cref="UnsupportedInputException"/>.
    /// </param>
    /// <param name="maxInputPartBytes">
    /// Largest inline media payload, in bytes, allowed in any one message part; 20 MiB by default. Must be
    /// at least 1.
    /// </param>
    /// <param name="maxInputBytes">
    /// Largest total of inline media payload bytes across all messages; 50 MiB by default. Must be at least
    /// 1.
    /// </param>
    /// <returns>
    /// A task whose result is the winning generation: its text, any structured value and tool calls, usage,
    /// timing, attempts and, when enabled, its manifest.
    /// </returns>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="prompt"/> or another required argument is <see langword="null"/>, or a value is
    /// outside its documented range, such as <c>logprobs</c> outside 0 to 20 or inline media over its byte
    /// limits.
    /// </exception>
    /// <exception cref="ProviderException">
    /// The sampling seed is negative or a penalty is not finite.
    /// </exception>
    /// <exception cref="ConfigException">
    /// No target, route or client default route is available, a target cannot be resolved, a provider
    /// instance cannot be configured, or the selected provider does not support generation.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">The client's spend policy refuses the request.</exception>
    /// <exception cref="SchemaViolationException">
    /// The response still fails the schema after the repair budget is spent.
    /// </exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed; <see cref="AllTargetsFailedException.Attempts"/> lists each
    /// attempt.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
        CachePolicy? cache = null,
        string? reasoning = null,
        IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? logprobs = null,
        bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null,
        int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        GenerateAsync(
            CreateConvenienceRequest(messages: [Message.User(prompt)], target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, stream: false, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes),
            cancellationToken,
            manifest);

    /// <summary>Generates a buffered result from caller messages.</summary>
    /// <param name="messages">
    /// Conversation messages in order, using the <c>system</c>, <c>user</c>, <c>assistant</c> and
    /// <c>tool</c> roles. They are copied, and a <see langword="null"/> element is rejected.
    /// </param>
    /// <param name="target">
    /// One target to run when <paramref name="route"/> is <see langword="null"/>: <c>provider:model</c>,
    /// where provider is a configured instance ID or a registered provider ID or alias, or a catalog alias.
    /// It uses the retry and health-gate settings of the client's default route when one exists. When both
    /// are <see langword="null"/>, the client's default route is used.
    /// </param>
    /// <param name="route">
    /// Ordered targets with retry, health-gate and context-window fallback settings. When supplied it takes
    /// precedence, and <paramref name="target"/> is ignored.
    /// </param>
    /// <param name="sampling">
    /// Sampling controls such as temperature, top-p, maximum output tokens, stop sequences, seed and
    /// penalties; <see langword="null"/> leaves every value to the provider. A value the provider's
    /// descriptor declares it ignores is reported with a <see cref="ParameterDropped"/> event.
    /// </param>
    /// <param name="repair">
    /// Structured-output repair budget, used only with <paramref name="schema"/>; <see langword="null"/>
    /// uses the client's default repair, and with neither no repair round trip is made. A provider's
    /// declared repair ceiling can lower it, reported with a <see cref="ParameterDropped"/> event.
    /// </param>
    /// <param name="schema">
    /// Schema the response text must satisfy, or <see langword="null"/> for free text. The core uses the
    /// strongest mechanism the target supports (grammar, JSON schema, JSON mode, then prompt instructions),
    /// validates the response and spends the repair budget on corrections; the parsed value is returned in
    /// <see cref="Generation.Structured"/>.
    /// </param>
    /// <param name="schemaMechanism">
    /// A structured-output mechanism name stored on the request as
    /// <see cref="GenerationRequest.SchemaMechanism"/>. Generation chooses the mechanism from the target's
    /// capabilities and does not act on this value.
    /// </param>
    /// <param name="timeoutS">
    /// Deadline in seconds for each provider call, applied separately to every attempt and repair round
    /// trip; <see langword="null"/> uses the provider instance's <see cref="ProviderSettings.TimeoutS"/>,
    /// 120 seconds unless configured.
    /// </param>
    /// <param name="maxResponseBytes">
    /// Upper bound in bytes on each provider response the adapter reads; <see langword="null"/> uses 1 MiB
    /// (1,048,576 bytes).
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels the operation, including pending retries, fallbacks and repair round trips. Cancellation
    /// surfaces as <see cref="System.OperationCanceledException"/>.
    /// </param>
    /// <param name="manifest">
    /// Whether the result carries a <see cref="RunManifest"/>: <see langword="true"/> or
    /// <see langword="false"/> overrides the client's <c>manifests</c> setting for this call, and
    /// <see langword="null"/> uses it.
    /// </param>
    /// <param name="tools">
    /// Tool declarations advertised to the model, or <see langword="null"/> for none. They are not
    /// executed: calls the model requests are returned in <see cref="Generation.ToolCalls"/>.
    /// </param>
    /// <param name="toolChoice">
    /// How the model may use the declared tools: <c>auto</c> (the default), <c>none</c>, <c>required</c>,
    /// or the name of one declared tool to force it. Must not be <see langword="null"/>.
    /// </param>
    /// <param name="cache">
    /// Prompt-cache planning policy for this request; <see langword="null"/> uses the client's default
    /// cache policy, and with neither no cache placement is planned.
    /// </param>
    /// <param name="reasoning">
    /// Reasoning effort to request, such as <c>none</c>, <c>minimal</c>, <c>low</c>, <c>medium</c> or
    /// <c>high</c>; <see langword="null"/> keeps the provider default. The provider descriptor translates
    /// it to its wire form, and it is not sent, with a <see cref="ParameterDropped"/> event, when the
    /// model's trusted capabilities exclude reasoning.
    /// </param>
    /// <param name="providerOptions">
    /// Extra provider request options keyed by provider instance ID, or by <c>*</c> for every provider. For
    /// the selected target the <c>*</c> properties apply first and that instance's own properties override
    /// them; the merged object reaches the adapter as <see cref="WireRequest.ExtraOptions"/>, which the
    /// built-in OpenAI-compatible adapter overlays onto its request body. <see langword="null"/> for none.
    /// </param>
    /// <param name="metadata">
    /// Opaque caller labels copied onto the request and not sent to the provider. They are reported on the
    /// <see cref="RequestStarted"/> event, their keys are recorded in the manifest, and a
    /// <see cref="SpendLedger"/> can group spend by them. <see langword="null"/> for none.
    /// </param>
    /// <param name="logprobs">
    /// Number of alternative tokens, from 0 to 20, to report with each generated token's log-probability,
    /// or <see langword="null"/> for no log-probabilities. It is not requested, with a
    /// <see cref="ParameterDropped"/> event, when the model's trusted capabilities exclude
    /// log-probabilities.
    /// </param>
    /// <param name="citeDocuments">
    /// Whether to ask the provider to cite supplied documents; citations are returned in
    /// <see cref="Generation.Citations"/>. It is not requested, with a <see cref="ParameterDropped"/>
    /// event, when the model's trusted capabilities exclude citations.
    /// </param>
    /// <param name="serverTools">
    /// Provider-run tools, such as web search or code execution, to enable for this request, or
    /// <see langword="null"/> for none. An attempt on a target whose provider or model cannot run a
    /// requested kind fails with <see cref="UnsupportedInputException"/>.
    /// </param>
    /// <param name="maxInputPartBytes">
    /// Largest inline media payload, in bytes, allowed in any one message part; 20 MiB by default. Must be
    /// at least 1.
    /// </param>
    /// <param name="maxInputBytes">
    /// Largest total of inline media payload bytes across all messages; 50 MiB by default. Must be at least
    /// 1.
    /// </param>
    /// <returns>
    /// A task whose result is the winning generation: its text, any structured value and tool calls, usage,
    /// timing, attempts and, when enabled, its manifest.
    /// </returns>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="messages"/> or another required argument is <see langword="null"/>, or a value is
    /// outside its documented range, such as <c>logprobs</c> outside 0 to 20 or inline media over its byte
    /// limits.
    /// </exception>
    /// <exception cref="ProviderException">
    /// The messages use a role or content type outside the supported request profile, or the sampling seed
    /// is negative or a penalty is not finite.
    /// </exception>
    /// <exception cref="ConfigException">
    /// No target, route or client default route is available, a target cannot be resolved, a provider
    /// instance cannot be configured, or the selected provider does not support generation.
    /// </exception>
    /// <exception cref="CredentialException">
    /// A provider credential reference cannot be resolved.
    /// </exception>
    /// <exception cref="SpendLimitException">The client's spend policy refuses the request.</exception>
    /// <exception cref="SchemaViolationException">
    /// The response still fails the schema after the repair budget is spent.
    /// </exception>
    /// <exception cref="AllTargetsFailedException">
    /// Every target in the route failed; <see cref="AllTargetsFailedException.Attempts"/> lists each
    /// attempt.
    /// </exception>
    /// <exception cref="System.OperationCanceledException">
    /// The operation was cancelled, or the client was disposed while it ran.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
        CachePolicy? cache = null,
        string? reasoning = null,
        IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? logprobs = null,
        bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null,
        int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        GenerateAsync(
            CreateConvenienceRequest(messages: messages, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, stream: false, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes),
            cancellationToken,
            manifest);

    private async Task<Generation> RunToolsCoreAsync(
        GenerationRequest request,
        ToolRegistry registry,
        int maxRounds,
        CancellationToken cancellationToken,
        CancellationToken callerIdentity,
        bool? manifest)
    {
        var reservation = ReserveLifecycle(cancellationToken, callerIdentity);
        using var context = AsyncExecutionContext.Push(this, reservation.SyncOwner);
        using var identity = CancellationIdentityContext.Push(reservation.Token, reservation.CallerIdentity);
        try
        {
            await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
            reservation.ThrowIfCallerCancelled();
            return await ToolLoop.RunAsync(
                request,
                registry,
                maxRounds,
                (next, token) => GenerateAsync(next, token, manifest),
                async token =>
                {
                    await reservation.ThrowIfClientCloseWonAsync().ConfigureAwait(false);
                    reservation.ThrowIfCallerCancelled();
                    token.ThrowIfCancellationRequested();
                },
                reservation.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException exception)
            when (exception.CancellationToken == reservation.Token && reservation.CallerIdentity.IsCancellationRequested)
        {
            throw new OperationCanceledException(exception.Message, exception, reservation.CallerIdentity);
        }
        finally
        {
            await CompleteLifecycleAsync(reservation).ConfigureAwait(false);
        }
    }

    internal async Task<Generation> GenerateAsync(
        GenerationRequest request,
        OperationCapture? capture,
        CancellationToken cancellationToken = default,
        bool? manifest = null)
    {
        await using var stream = StreamAsync(request, capture, cancellationToken, manifest);
        return await stream.CollectAsync(cancellationToken).ConfigureAwait(false);
    }

    /// <inheritdoc cref="GenerateAsync(GenerationRequest, CancellationToken, bool?)"/>
    /// <summary>
    /// Creates a lazy, single-consumer stream that runs a complete request when it is enumerated.
    /// </summary>
    /// <returns>
    /// A stream of the operation's events. After a successful enumeration its
    /// <see cref="AsyncStream.Result"/> holds the winning generation.
    /// </returns>
    /// <remarks>
    /// Nothing is sent until the stream is enumerated, and it can be enumerated once. Events from every
    /// attempt arrive in order, including deltas from attempts that later fail; each failed attempt is
    /// marked by an <see cref="AttemptFailed"/> event, and <see cref="StreamEnded"/> carries the winning
    /// generation. Generation failures such as <see cref="AllTargetsFailedException"/>,
    /// <see cref="SchemaViolationException"/> or <see cref="SpendLimitException"/> are thrown while
    /// enumerating. The <paramref name="cancellationToken"/> is kept with the stream and observed for its
    /// whole enumeration. Dispose the stream, for example with <c>await using</c>, to end it early;
    /// disposing the stream or the client cancels a running generation. The request's
    /// <see cref="GenerationRequest.Stream"/> flag is passed to the adapter as given.
    /// </remarks>
    /// <exception cref="System.ArgumentNullException">
    /// <paramref name="request"/> is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ProviderException">
    /// The messages use a role or content type outside the supported request profile, or the sampling seed
    /// is negative or a penalty is not finite.
    /// </exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
    public AsyncStream StreamAsync(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        StreamAsync(request, capture: null, cancellationToken: cancellationToken, manifest: manifest);

    /// <inheritdoc cref="GenerateAsync(string, string, Route, Sampling, Repair, SchemaSpec, string, double?, int?, CancellationToken, bool?, IEnumerable{ToolSpec}, string, CachePolicy, string, IReadOnlyDictionary{string, JsonObject}, IReadOnlyDictionary{string, string}, int?, bool, IEnumerable{ServerToolSpec}, int, int)"/>
    /// <summary>Creates a lazy, single-consumer streaming generation from one user prompt.</summary>
    /// <returns>
    /// A stream of the operation's events. After a successful enumeration its
    /// <see cref="AsyncStream.Result"/> holds the winning generation.
    /// </returns>
    /// <remarks>
    /// Nothing is sent until the stream is enumerated, and it can be enumerated once. Events from every
    /// attempt arrive in order, including deltas from attempts that later fail; each failed attempt is
    /// marked by an <see cref="AttemptFailed"/> event, and <see cref="StreamEnded"/> carries the winning
    /// generation. Generation failures such as <see cref="AllTargetsFailedException"/>,
    /// <see cref="SchemaViolationException"/> or <see cref="SpendLimitException"/> are thrown while
    /// enumerating. The <paramref name="cancellationToken"/> is kept with the stream and observed for its
    /// whole enumeration. Dispose the stream, for example with <c>await using</c>, to end it early;
    /// disposing the stream or the client cancels a running generation.
    /// </remarks>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="prompt"/> or another required argument is <see langword="null"/>, or a value is
    /// outside its documented range.
    /// </exception>
    /// <exception cref="ProviderException">
    /// The sampling seed is negative or a penalty is not finite.
    /// </exception>
    /// <exception cref="ConfigException">No target, route or client default route is available.</exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
        CachePolicy? cache = null,
        string? reasoning = null,
        IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? logprobs = null,
        bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null,
        int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        StreamAsync(
            CreateConvenienceRequest(messages: [Message.User(prompt)], target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, stream: true, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes),
            cancellationToken,
            manifest);

    /// <inheritdoc cref="GenerateAsync(IEnumerable{Message}, string, Route, Sampling, Repair, SchemaSpec, string, double?, int?, CancellationToken, bool?, IEnumerable{ToolSpec}, string, CachePolicy, string, IReadOnlyDictionary{string, JsonObject}, IReadOnlyDictionary{string, string}, int?, bool, IEnumerable{ServerToolSpec}, int, int)"/>
    /// <summary>Creates a lazy, single-consumer streaming generation from caller messages.</summary>
    /// <returns>
    /// A stream of the operation's events. After a successful enumeration its
    /// <see cref="AsyncStream.Result"/> holds the winning generation.
    /// </returns>
    /// <remarks>
    /// Nothing is sent until the stream is enumerated, and it can be enumerated once. Events from every
    /// attempt arrive in order, including deltas from attempts that later fail; each failed attempt is
    /// marked by an <see cref="AttemptFailed"/> event, and <see cref="StreamEnded"/> carries the winning
    /// generation. Generation failures such as <see cref="AllTargetsFailedException"/>,
    /// <see cref="SchemaViolationException"/> or <see cref="SpendLimitException"/> are thrown while
    /// enumerating. The <paramref name="cancellationToken"/> is kept with the stream and observed for its
    /// whole enumeration. Dispose the stream, for example with <c>await using</c>, to end it early;
    /// disposing the stream or the client cancels a running generation.
    /// </remarks>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="messages"/> or another required argument is <see langword="null"/>, or a value is
    /// outside its documented range.
    /// </exception>
    /// <exception cref="ProviderException">
    /// The messages use a role or content type outside the supported request profile, or the sampling seed
    /// is negative or a penalty is not finite.
    /// </exception>
    /// <exception cref="ConfigException">No target, route or client default route is available.</exception>
    /// <exception cref="System.ObjectDisposedException">The client has been disposed.</exception>
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
        CachePolicy? cache = null,
        string? reasoning = null,
        IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null,
        int? logprobs = null,
        bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null,
        int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        StreamAsync(
            CreateConvenienceRequest(messages: messages, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, stream: true, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes),
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
                messages: request.Messages,
                route: request.Route,
                sampling: request.Sampling,
                repair: _defaultRepair,
                schema: request.Schema,
                schemaMechanism: request.SchemaMechanism,
                timeoutS: request.TimeoutS,
                maxResponseBytes: request.MaxResponseBytes,
                stream: request.Stream,
                tools: request.Tools,
                toolChoice: request.ToolChoice,
                cache: request.Cache,
                reasoning: request.Reasoning,
                providerOptions: request.ProviderOptions,
                metadata: request.Metadata,
                logprobs: request.Logprobs,
                citeDocuments: request.CiteDocuments,
                serverTools: request.ServerTools,
                maxInputPartBytes: request.MaxInputPartBytes,
                maxInputBytes: request.MaxInputBytes)
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

    /// <summary>
    /// Cancels outstanding operations and streams, then disposes the adapters this client owns.
    /// </summary>
    /// <remarks>
    /// Operations started after disposal begins throw <see cref="System.ObjectDisposedException"/>. The
    /// returned task completes once running operations and open streams have observed cancellation and
    /// every owned adapter has been disposed; calling this method again returns the same task. If closing a
    /// stream or disposing an adapter fails, the first failure is rethrown from the task after the rest of
    /// the cleanup has run. Observers, ledgers, rate limiters, registries, resolvers and catalogs supplied
    /// by the caller are not disposed.
    /// </remarks>
    /// <exception cref="System.InvalidOperationException">
    /// Called from a callback this client is running, such as an observer notification or a tool handler.
    /// </exception>
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
        CachePolicy? cache,
        string? reasoning,
        IReadOnlyDictionary<string, JsonObject>? providerOptions,
        IReadOnlyDictionary<string, string>? metadata,
        int? logprobs,
        bool citeDocuments,
        IEnumerable<ServerToolSpec>? serverTools,
        int maxInputPartBytes,
        int maxInputBytes)
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
            messages: messages,
            route: selectedRoute,
            sampling: sampling,
            repair: repair ?? _defaultRepair,
            schema: schema,
            schemaMechanism: schemaMechanism,
            timeoutS: timeoutS,
            maxResponseBytes: maxResponseBytes,
            stream: stream,
            tools: tools,
            toolChoice: toolChoice,
            cache: cache,
            reasoning: reasoning,
            providerOptions: providerOptions,
            metadata: metadata,
            logprobs: logprobs,
            citeDocuments: citeDocuments,
            serverTools: serverTools,
            maxInputPartBytes: maxInputPartBytes,
            maxInputBytes: maxInputBytes);
    }
}
