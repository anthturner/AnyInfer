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
/// <remarks>
/// Each blocking call runs its asynchronous operation on the thread pool and waits for it, so failures
/// are thrown directly rather than wrapped in an <see cref="System.AggregateException"/>. Dispose the
/// client, for example with a <c>using</c> statement, to cancel outstanding calls, close open
/// <see cref="SyncStream"/> instances and dispose the provider adapters it owns. Observers, ledgers,
/// rate limiters, registries, resolvers and catalogs passed to it stay owned by the caller and are
/// never disposed by the client.
/// </remarks>
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

    /// <inheritdoc cref="AsyncClient.AsyncClient(IEnumerable{ProviderSettings}, ProviderRegistry, ResolverChain, Route, Repair, global::AnyInfer.Catalog.Catalog, PricingTable, IReadOnlyDictionary{string, IReadOnlyDictionary{string, ModelCapabilities}}, SchemaValidationOptions, IEnumerable{IObserver}, bool, bool, ITokenEstimator, SpendLedger, SpendPolicy, bool, IReadOnlyDictionary{string, RateLimiter}, CachePolicy, bool, IReadOnlyDictionary{InferenceOperation, Route})"/>
    /// <summary>
    /// Creates a synchronous client over provider settings and provider descriptor metadata.
    /// </summary>
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

    /// <inheritdoc cref="AsyncClient.FromAdapters"/>
    /// <summary>Creates a synchronous client over adapters the caller has already constructed.</summary>
    /// <returns>A synchronous client that owns the registered adapters.</returns>
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

    /// <inheritdoc cref="AsyncClient.FromConfig"/>
    /// <summary>
    /// Creates a synchronous client from parsed configuration without performing I/O or resolving
    /// credentials.
    /// </summary>
    /// <returns>A synchronous client configured from <paramref name="config"/>.</returns>
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

    /// <inheritdoc cref="AsyncClient.Resolve"/>
    /// <summary>
    /// Resolves a target without resolving credentials, building an adapter or doing network I/O.
    /// </summary>
    public ResolvedTarget Resolve(string target) => _inner.Resolve(target);

    /// <inheritdoc cref="AsyncClient.Capabilities"/>
    /// <summary>Gets assembled immutable capability facts without constructing an adapter.</summary>
    public ModelCapabilities Capabilities(string target) => _inner.Capabilities(target);

    /// <inheritdoc cref="AsyncClient.Spend"/>
    /// <summary>Gets completed spend recorded by this client's ledger.</summary>
    /// <exception cref="System.ObjectDisposedException">
    /// The client is being or has been disposed.
    /// </exception>
    public SpendTotals Spend()
    {
        ThrowIfClosing();
        return _inner.Spend();
    }

    /// <inheritdoc cref="AsyncClient.Budget(GenerationRequest, string, long?)"/>
    /// <summary>
    /// Builds a pure context budget for one explicit target without selecting or constructing an adapter.
    /// </summary>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="request"/> or <paramref name="target"/> is <see langword="null"/>, or
    /// <paramref name="outputReserveTokens"/> is negative.
    /// </exception>
    /// <exception cref="ConfigException">The target cannot be resolved.</exception>
    /// <exception cref="System.ObjectDisposedException">
    /// The client is being or has been disposed.
    /// </exception>
    public ContextBudget Budget(GenerationRequest request, string target, long? outputReserveTokens = null)
    {
        ThrowIfClosing();
        return _inner.Budget(request, target, outputReserveTokens);
    }

    /// <inheritdoc cref="AsyncClient.Budget(string, string, SchemaSpec, Sampling, long?, IEnumerable{ToolSpec}, string, CachePolicy)"/>
    /// <summary>Builds a pure context budget for one user prompt and an explicit target.</summary>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="prompt"/> or <paramref name="target"/> is <see langword="null"/>, or
    /// <paramref name="outputReserveTokens"/> is negative.
    /// </exception>
    /// <exception cref="ConfigException">The target cannot be resolved.</exception>
    /// <exception cref="System.ObjectDisposedException">
    /// The client is being or has been disposed.
    /// </exception>
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

    /// <inheritdoc cref="AsyncClient.Budget(IEnumerable{Message}, string, SchemaSpec, Sampling, long?, IEnumerable{ToolSpec}, string, CachePolicy)"/>
    /// <summary>Builds a pure context budget for caller messages and an explicit target.</summary>
    /// <exception cref="System.ArgumentException">
    /// <paramref name="messages"/> or <paramref name="target"/> is <see langword="null"/>, or
    /// <paramref name="outputReserveTokens"/> is negative.
    /// </exception>
    /// <exception cref="ConfigException">The target cannot be resolved.</exception>
    /// <exception cref="System.ObjectDisposedException">
    /// The client is being or has been disposed.
    /// </exception>
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

    /// <inheritdoc cref="AsyncClient.Subscribe"/>
    /// <summary>Subscribes an observer for synchronous telemetry notifications.</summary>
    public void Subscribe(IObserver observer, bool payloads = false) => _inner.Subscribe(observer, payloads);

    /// <inheritdoc cref="AsyncClient.Unsubscribe"/>
    /// <summary>Removes every reference-identical observer subscription.</summary>
    public void Unsubscribe(IObserver observer) => _inner.Unsubscribe(observer);

    /// <inheritdoc cref="AsyncClient.ModelsAsync"/>
    /// <summary>
    /// Lists models for one selected provider instance, blocking until the provider answers, and optionally
    /// filters by operation.
    /// </summary>
    /// <returns>A read-only snapshot of the listed models, filtered when an operation is given.</returns>
    public IReadOnlyList<DiscoveredModel> Models(
        string providerId,
        InferenceOperation? operation = null,
        CancellationToken cancellationToken = default) =>
        RunOperation(token => _inner.ModelsAsync(providerId, operation, token), cancellationToken);

    /// <inheritdoc cref="AsyncClient.HealthAsync"/>
    /// <summary>
    /// Gets a health observation for one selected provider instance, blocking until the provider answers.
    /// </summary>
    /// <returns>The provider's current health observation.</returns>
    public Health Health(string providerId, CancellationToken cancellationToken = default) =>
        RunOperation(token => _inner.HealthAsync(providerId, token), cancellationToken);

    /// <inheritdoc cref="AsyncClient.ProbeAsync"/>
    /// <summary>
    /// Runs ordered raw generation capability probes against one resolved target, blocking until they
    /// finish.
    /// </summary>
    /// <returns>
    /// A report of each probe's outcome, the measured capabilities merged with prior facts
    /// (<see langword="null"/> when no probe was conclusive), the number of requests sent and their
    /// reported usage.
    /// </returns>
    public ProbeReport Probe(
        string target,
        IEnumerable<Feature>? features = null,
        double timeoutS = 30,
        bool record = true,
        CancellationToken cancellationToken = default) =>
        RunOperation(token => _inner.ProbeAsync(target, features, timeoutS, record, token), cancellationToken);

    /// <inheritdoc cref="AsyncClient.EmbedAsync(EmbeddingRequest, string, Route, CancellationToken, bool?)"/>
    /// <summary>
    /// Embeds one immutable request through the selected retrieval route, blocking until it completes.
    /// </summary>
    /// <returns>
    /// One vector per input, in input order, with their shared embedding space, usage, timing, attempts,
    /// warnings and, when enabled, the raw payload and manifest.
    /// </returns>
    public EmbeddingResult Embed(
        EmbeddingRequest request,
        string? target = null,
        Route? route = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.EmbedAsync(request, target, route, token, manifest), cancellationToken);

    /// <inheritdoc cref="AsyncClient.EmbedAsync(string, string, Route, EmbeddingInputIntent?, int?, EmbeddingSpace, bool, BatchPolicy, double?, IReadOnlyDictionary{string, IReadOnlyDictionary{string, JsonValue}}, IReadOnlyDictionary{string, string}, int?, bool?, CancellationToken, bool?)"/>
    /// <summary>
    /// Embeds one text input through the selected retrieval route, blocking until it completes.
    /// </summary>
    /// <returns>
    /// The input's vector with its embedding space, usage, timing, attempts, warnings and, when enabled,
    /// the raw payload and manifest.
    /// </returns>
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

    /// <inheritdoc cref="AsyncClient.EmbedAsync(IEnumerable{string}, string, Route, EmbeddingInputIntent?, int?, EmbeddingSpace, bool, BatchPolicy, double?, IReadOnlyDictionary{string, IReadOnlyDictionary{string, JsonValue}}, IReadOnlyDictionary{string, string}, int?, bool?, CancellationToken, bool?)"/>
    /// <summary>
    /// Embeds ordered text inputs through the selected retrieval route, blocking until it completes.
    /// </summary>
    /// <returns>
    /// One vector per input, in input order, with their shared embedding space, usage, timing, attempts,
    /// warnings and, when enabled, the raw payload and manifest.
    /// </returns>
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

    /// <inheritdoc cref="AsyncClient.RerankAsync(RerankRequest, string, Route, CancellationToken, bool?)"/>
    /// <summary>
    /// Reranks one immutable request through the selected retrieval route, blocking until it completes.
    /// </summary>
    /// <returns>
    /// The ranked items in provider order, each with its score, document ID and original index, plus usage,
    /// timing, attempts, warnings and, when enabled, the raw payload and manifest.
    /// </returns>
    public RerankResult Rerank(
        RerankRequest request,
        string? target = null,
        Route? route = null,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.RerankAsync(request, target, route, token, manifest), cancellationToken);

    /// <inheritdoc cref="AsyncClient.RerankAsync(string, IEnumerable{string}, string, Route, int?, BatchPolicy, double?, IReadOnlyDictionary{string, IReadOnlyDictionary{string, JsonValue}}, IReadOnlyDictionary{string, string}, int?, bool, bool?, CancellationToken, bool?)"/>
    /// <summary>
    /// Reranks ordered document texts through the selected retrieval route, using each text's zero-based
    /// position, in invariant-culture digits, as its document ID, and blocks until it completes.
    /// </summary>
    /// <returns>
    /// The ranked items in provider order, each with its score, document ID and original index, plus usage,
    /// timing, attempts, warnings and, when enabled, the raw payload and manifest.
    /// </returns>
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

    /// <inheritdoc cref="AsyncClient.RerankAsync(string, IEnumerable{RerankDocument}, string, Route, int?, BatchPolicy, double?, IReadOnlyDictionary{string, IReadOnlyDictionary{string, JsonValue}}, IReadOnlyDictionary{string, string}, int?, bool, bool?, CancellationToken, bool?)"/>
    /// <summary>
    /// Reranks ordered documents through the selected retrieval route, blocking until it completes.
    /// </summary>
    /// <returns>
    /// The ranked items in provider order, each with its score, document ID and original index, plus usage,
    /// timing, attempts, warnings and, when enabled, the raw payload and manifest.
    /// </returns>
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
    /// <inheritdoc cref="AsyncClient.GenerateAsync(GenerationRequest, CancellationToken, bool?)"/>
    /// <summary>
    /// Generates a terminal result from an explicit request, blocking until it completes.
    /// </summary>
    /// <returns>
    /// The winning generation: its text, any structured value and tool calls, usage, timing, attempts and,
    /// when enabled, its manifest.
    /// </returns>
    public Generation Generate(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        RunOperation(token => _inner.GenerateAsync(request, token, manifest), cancellationToken);

    /// <inheritdoc cref="AsyncClient.RunToolsAsync(GenerationRequest, IEnumerable{Tool}, int, CancellationToken, bool?)"/>
    /// <summary>
    /// Generates and dispatches explicitly registered tools until the model stops calling them, blocking
    /// until the loop ends.
    /// </summary>
    /// <returns>
    /// The final round's generation, the first whose finish reason is not <c>tool_calls</c>. Its usage,
    /// attempts and manifest describe that round only.
    /// </returns>
    public Generation RunTools(
        GenerationRequest request,
        IEnumerable<Tool> tools,
        int maxRounds = 8,
        CancellationToken cancellationToken = default,
        bool? manifest = null) =>
        RunOperation(token => _inner.RunToolsAsync(request, tools, maxRounds, token, manifest), cancellationToken);

    /// <inheritdoc cref="AsyncClient.RunToolsAsync(string, IEnumerable{Tool}, string, Route, Sampling, Repair, SchemaSpec, string, double?, int?, string, CachePolicy, string, IReadOnlyDictionary{string, JsonObject}, IReadOnlyDictionary{string, string}, int?, bool, IEnumerable{ServerToolSpec}, int, int, int, CancellationToken, bool?)"/>
    /// <summary>
    /// Generates from one prompt while dispatching explicitly registered tools, blocking until the loop
    /// ends.
    /// </summary>
    /// <returns>
    /// The final round's generation, the first whose finish reason is not <c>tool_calls</c>. Its usage,
    /// attempts and manifest describe that round only.
    /// </returns>
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

    /// <inheritdoc cref="AsyncClient.RunToolsAsync(IEnumerable{Message}, IEnumerable{Tool}, string, Route, Sampling, Repair, SchemaSpec, string, double?, int?, string, CachePolicy, string, IReadOnlyDictionary{string, JsonObject}, IReadOnlyDictionary{string, string}, int?, bool, IEnumerable{ServerToolSpec}, int, int, int, CancellationToken, bool?)"/>
    /// <summary>
    /// Generates from caller messages while dispatching explicitly registered tools, blocking until the
    /// loop ends.
    /// </summary>
    /// <returns>
    /// The final round's generation, the first whose finish reason is not <c>tool_calls</c>. Its usage,
    /// attempts and manifest describe that round only.
    /// </returns>
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

    /// <inheritdoc cref="AsyncClient.GenerateAsync(string, string, Route, Sampling, Repair, SchemaSpec, string, double?, int?, CancellationToken, bool?, IEnumerable{ToolSpec}, string, CachePolicy, string, IReadOnlyDictionary{string, JsonObject}, IReadOnlyDictionary{string, string}, int?, bool, IEnumerable{ServerToolSpec}, int, int)"/>
    /// <summary>Generates a terminal result from one user prompt, blocking until it completes.</summary>
    /// <returns>
    /// The winning generation: its text, any structured value and tool calls, usage, timing, attempts and,
    /// when enabled, its manifest.
    /// </returns>
    public Generation Generate(string prompt, string? target = null, Route? route = null, Sampling? sampling = null,
        Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null, double? timeoutS = null,
        int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto", CachePolicy? cache = null,
        string? reasoning = null, IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null, int? logprobs = null, bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null, int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        RunOperation(token => _inner.GenerateAsync(prompt: prompt, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, cancellationToken: token, manifest: manifest, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes), cancellationToken);

    /// <inheritdoc cref="AsyncClient.GenerateAsync(IEnumerable{Message}, string, Route, Sampling, Repair, SchemaSpec, string, double?, int?, CancellationToken, bool?, IEnumerable{ToolSpec}, string, CachePolicy, string, IReadOnlyDictionary{string, JsonObject}, IReadOnlyDictionary{string, string}, int?, bool, IEnumerable{ServerToolSpec}, int, int)"/>
    /// <summary>Generates a terminal result from caller messages, blocking until it completes.</summary>
    /// <returns>
    /// The winning generation: its text, any structured value and tool calls, usage, timing, attempts and,
    /// when enabled, its manifest.
    /// </returns>
    public Generation Generate(IEnumerable<Message> messages, string? target = null, Route? route = null,
        Sampling? sampling = null, Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null,
        double? timeoutS = null, int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto", CachePolicy? cache = null,
        string? reasoning = null, IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null, int? logprobs = null, bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null, int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        RunOperation(token => _inner.GenerateAsync(messages: messages, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, cancellationToken: token, manifest: manifest, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes), cancellationToken);

    /// <inheritdoc cref="AsyncClient.StreamAsync(GenerationRequest, CancellationToken, bool?)"/>
    /// <summary>
    /// Starts a streaming generation from an explicit request and returns a synchronous view of its events.
    /// </summary>
    /// <returns>
    /// A synchronous stream of the operation's events. After a successful enumeration its
    /// <see cref="SyncStream.Result"/> holds the winning generation.
    /// </returns>
    /// <remarks>
    /// Unlike the asynchronous stream, this one does not wait to be enumerated: creating it starts a
    /// background pump that runs the generation and buffers up to 256 events ahead of the consumer, waiting
    /// while the buffer is full. Enumerate the stream once, or call <see cref="SyncStream.Collect"/>, and
    /// dispose it to stop the generation early; disposing the client also closes it. Events from every
    /// attempt arrive in order, including deltas from attempts that later fail. Generation failures and
    /// cancellation are thrown by the enumeration after the events buffered before them. The request's
    /// <see cref="GenerationRequest.Stream"/> flag is passed to the adapter as given.
    /// </remarks>
    public SyncStream Stream(GenerationRequest request, CancellationToken cancellationToken = default, bool? manifest = null) =>
        CreateStream(() => _inner.StreamAsync(request, cancellationToken, manifest));

    /// <inheritdoc cref="AsyncClient.StreamAsync(string, string, Route, Sampling, Repair, SchemaSpec, string, double?, int?, CancellationToken, bool?, IEnumerable{ToolSpec}, string, CachePolicy, string, IReadOnlyDictionary{string, JsonObject}, IReadOnlyDictionary{string, string}, int?, bool, IEnumerable{ServerToolSpec}, int, int)"/>
    /// <summary>
    /// Starts a streaming generation from one user prompt and returns a synchronous view of its events.
    /// </summary>
    /// <returns>
    /// A synchronous stream of the operation's events. After a successful enumeration its
    /// <see cref="SyncStream.Result"/> holds the winning generation.
    /// </returns>
    /// <remarks>
    /// Unlike the asynchronous stream, this one does not wait to be enumerated: creating it starts a
    /// background pump that runs the generation and buffers up to 256 events ahead of the consumer, waiting
    /// while the buffer is full. Enumerate the stream once, or call <see cref="SyncStream.Collect"/>, and
    /// dispose it to stop the generation early; disposing the client also closes it. Events from every
    /// attempt arrive in order, including deltas from attempts that later fail. Generation failures and
    /// cancellation are thrown by the enumeration after the events buffered before them.
    /// </remarks>
    public SyncStream Stream(string prompt, string? target = null, Route? route = null, Sampling? sampling = null,
        Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null, double? timeoutS = null,
        int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto", CachePolicy? cache = null,
        string? reasoning = null, IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null, int? logprobs = null, bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null, int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        CreateStream(() => _inner.StreamAsync(prompt: prompt, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, cancellationToken: cancellationToken, manifest: manifest, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes));

    /// <inheritdoc cref="AsyncClient.StreamAsync(IEnumerable{Message}, string, Route, Sampling, Repair, SchemaSpec, string, double?, int?, CancellationToken, bool?, IEnumerable{ToolSpec}, string, CachePolicy, string, IReadOnlyDictionary{string, JsonObject}, IReadOnlyDictionary{string, string}, int?, bool, IEnumerable{ServerToolSpec}, int, int)"/>
    /// <summary>
    /// Starts a streaming generation from caller messages and returns a synchronous view of its events.
    /// </summary>
    /// <returns>
    /// A synchronous stream of the operation's events. After a successful enumeration its
    /// <see cref="SyncStream.Result"/> holds the winning generation.
    /// </returns>
    /// <remarks>
    /// Unlike the asynchronous stream, this one does not wait to be enumerated: creating it starts a
    /// background pump that runs the generation and buffers up to 256 events ahead of the consumer, waiting
    /// while the buffer is full. Enumerate the stream once, or call <see cref="SyncStream.Collect"/>, and
    /// dispose it to stop the generation early; disposing the client also closes it. Events from every
    /// attempt arrive in order, including deltas from attempts that later fail. Generation failures and
    /// cancellation are thrown by the enumeration after the events buffered before them.
    /// </remarks>
    public SyncStream Stream(IEnumerable<Message> messages, string? target = null, Route? route = null,
        Sampling? sampling = null, Repair? repair = null, SchemaSpec? schema = null, string? schemaMechanism = null,
        double? timeoutS = null, int? maxResponseBytes = null, CancellationToken cancellationToken = default, bool? manifest = null,
        IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto", CachePolicy? cache = null,
        string? reasoning = null, IReadOnlyDictionary<string, JsonObject>? providerOptions = null,
        IReadOnlyDictionary<string, string>? metadata = null, int? logprobs = null, bool citeDocuments = false,
        IEnumerable<ServerToolSpec>? serverTools = null, int maxInputPartBytes = 20 * 1024 * 1024,
        int maxInputBytes = 50 * 1024 * 1024) =>
        CreateStream(() => _inner.StreamAsync(messages: messages, target: target, route: route, sampling: sampling, repair: repair, schema: schema, schemaMechanism: schemaMechanism, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, cancellationToken: cancellationToken, manifest: manifest, tools: tools, toolChoice: toolChoice, cache: cache, reasoning: reasoning, providerOptions: providerOptions, metadata: metadata, logprobs: logprobs, citeDocuments: citeDocuments, serverTools: serverTools, maxInputPartBytes: maxInputPartBytes, maxInputBytes: maxInputBytes));

    /// <summary>
    /// Cancels outstanding calls, closes open streams and disposes the adapters this client owns, blocking
    /// until that work finishes.
    /// </summary>
    /// <remarks>
    /// Calls made after disposal begins throw <see cref="System.ObjectDisposedException"/>. Disposal waits
    /// for blocking calls in progress to observe cancellation and return. Calling this method again waits
    /// for the same disposal. If closing a stream or disposing an adapter fails, the first failure is
    /// rethrown after the rest of the cleanup has run. Observers, ledgers, rate limiters, registries,
    /// resolvers and catalogs supplied by the caller are not disposed.
    /// </remarks>
    /// <exception cref="System.InvalidOperationException">
    /// Called from a callback this client is running, such as an observer notification or a tool handler.
    /// </exception>
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
