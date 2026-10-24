using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Config;
using AnyInfer.Examples;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Providers;
using PeterO.Numbers;

await VerifyAsync();

static async Task VerifyAsync()
{
    const string baseUrl = "https://offline.example/v1";
    const string target = "openai-compat:demo";

    var displayedSettings = SettingsExample.Create(baseUrl);
    Require(displayedSettings.ProviderId == "openai-compat", "Settings example did not produce the expected provider.");
    Require(ConnectionExample.VerifyRoundTrip(), "Connection settings example did not round-trip its inert values.");

    var cerebrasHandler = new CerebrasScriptedHandler();
    var cerebras = await CerebrasExample.RunAsync(
        CerebrasExample.Settings(cerebrasHandler, "offline-cerebras-key"));
    Require(cerebras.Text == "hello from Cerebras"
        && cerebras.Usage is { InputTokens: 1, OutputTokens: 1, TotalTokens: 2 }
        && cerebrasHandler.RequestCount == 1
        && cerebrasHandler.DisposeCount == 1,
        "Cerebras example did not use the default registration or preserve the scripted result.");

    var hyperbolicHandler = new HyperbolicScriptedHandler();
    var hyperbolic = await HyperbolicExample.RunAsync(
        HyperbolicExample.Settings(hyperbolicHandler, "offline-hyperbolic-key"));
    Require(hyperbolic.Text == "hello from Hyperbolic"
        && hyperbolic.Usage is { InputTokens: 1, OutputTokens: 1, TotalTokens: 2 }
        && hyperbolicHandler.RequestCount == 1
        && hyperbolicHandler.DisposeCount == 1,
        "Hyperbolic example did not use the default registration or preserve the scripted result.");

    var nscaleHandler = new NscaleScriptedHandler();
    var nscale = await NscaleExample.RunAsync(
        NscaleExample.Settings(nscaleHandler, "offline-nscale-key"));
    Require(nscale.Text == "hello from Nscale"
        && nscale.Usage is { InputTokens: 1, OutputTokens: 1, TotalTokens: 2 }
        && nscaleHandler.RequestCount == 1
        && nscaleHandler.DisposeCount == 1,
        "Nscale example did not use the default registration or preserve the scripted result.");

    var pureFactoryCalls = 0;
    var pureRegistry = new ProviderRegistry(
    [
        new ProviderDescriptor(
            "demo",
            "Demo",
            (_, _) =>
            {
                pureFactoryCalls++;
                throw new InvalidOperationException("Pure catalog queries must not construct an adapter.");
            }),
    ]);
    var catalog = new global::AnyInfer.Catalog.Catalog(
        aliases: new Dictionary<string, AliasEntry>
        {
            ["tier"] = new AliasEntry("tier", targets: new Dictionary<string, TargetEntry>
            {
                ["demo-instance"] = new TargetEntry("demo-instance", Model: "demo-model"),
            }),
        });
    var pricing = new PricingTable(new Dictionary<string, IReadOnlyList<PricingEntry>>
    {
        ["demo-instance"] =
        [
            new PricingEntry("demo-model", new Pricing(EDecimal.FromString("3.25"), EDecimal.FromString("4.5")), "2026-10-17", "offline example"),
        ],
    });
    var catalogObservation = CatalogExample.Inspect(
        catalog,
        pricing,
        ProviderSettings.Of("demo", alias: "demo-instance"),
        pureRegistry);
    Require(catalogObservation.Target.ProviderId == "demo-instance"
        && catalogObservation.Target.Model == "demo-model"
        && catalogObservation.Target.ViaAlias == "tier"
        && catalogObservation.Pricing is { Provenance: Provenance.Catalog }
        && catalogObservation.Pricing.Value.InputPer1M.CompareTo(EDecimal.FromString("3.25")) == 0,
        "Catalog example did not expose the expected public facts.");
    Require(pureFactoryCalls == 0, "Catalog example constructed an adapter for a pure query.");

    var asyncLifecycleHandler = new CountingHandler();
    var asyncLifecycle = await LifecycleExample.RunAsync(
        WithTransport(displayedSettings, asyncLifecycleHandler),
        "openai-compat");
    Require(asyncLifecycle.Models.Count == 1
        && asyncLifecycle.Models[0].Id == "demo"
        && asyncLifecycle.Health.Ok
        && asyncLifecycleHandler.ModelRequestCount == 2
        && asyncLifecycleHandler.EmptyModelBodies == 2
        && asyncLifecycleHandler.DisposeCount == 1,
        "Asynchronous lifecycle example did not preserve discovery facts or transport ownership.");

    var syncLifecycleHandler = new CountingHandler();
    var syncLifecycle = LifecycleExample.Run(
        WithTransport(displayedSettings, syncLifecycleHandler),
        "openai-compat");
    Require(syncLifecycle.Models.Count == 1
        && syncLifecycle.Models[0].Id == "demo"
        && syncLifecycle.Health.Ok
        && syncLifecycleHandler.ModelRequestCount == 2
        && syncLifecycleHandler.EmptyModelBodies == 2
        && syncLifecycleHandler.DisposeCount == 1,
        "Synchronous lifecycle example did not preserve discovery facts or transport ownership.");

    var setup = SetupExample.Create();
    Require(setup.HostShorthand?.Expand("offline.example") == "https://offline.example:443"
        && setup.AnyOf.Count == 1
        && setup.RequirementNote.Length != 0,
        "Setup example did not retain declarative metadata.");

    var asyncProbeHandler = new CountingHandler(probes: true);
    var asyncProbe = await ProbeExample.RunAsync(WithTransport(displayedSettings, asyncProbeHandler), target);
    Require(asyncProbe.Requests == 4
        && asyncProbe.Probes.All(static item => item.Outcome == ProbeOutcome.Supported)
        && asyncProbe.Capabilities?.Features?.Provenance == Provenance.Probed
        && asyncProbeHandler.ProbeRequestCount == 4
        && asyncProbeHandler.DisposeCount == 1,
        "Asynchronous probe example did not retain ordered measured facts or transport ownership.");

    var syncProbeHandler = new CountingHandler(probes: true);
    var syncProbe = ProbeExample.Run(WithTransport(displayedSettings, syncProbeHandler), target);
    Require(syncProbe.Requests == 4
        && syncProbe.Probes.All(static item => item.Outcome == ProbeOutcome.Supported)
        && syncProbe.Capabilities?.Features?.Provenance == Provenance.Probed
        && syncProbeHandler.ProbeRequestCount == 4
        && syncProbeHandler.DisposeCount == 1,
        "Synchronous probe example did not retain ordered measured facts or transport ownership.");

    var bufferedHandler = new CountingHandler();
    var buffered = await GenerationExample.RunAsync(WithTransport(displayedSettings, bufferedHandler), target);
    Require(buffered.Text == "hello", "Buffered example returned unexpected text.");
    Require(bufferedHandler.RequestCount == 1 && bufferedHandler.DisposeCount == 1, "Buffered example did not close its transport once.");

    var streamingHandler = new CountingHandler();
    var streamed = await StreamingExample.RunAsync(WithTransport(displayedSettings, streamingHandler), target);
    Require(streamed.Text == "hello", "Streaming example returned unexpected text.");
    Require(streamingHandler.RequestCount == 1 && streamingHandler.DisposeCount == 1, "Streaming example did not close its transport once.");

    var syncBufferedHandler = new CountingHandler();
    var syncBuffered = SyncGenerationExample.Run(WithTransport(displayedSettings, syncBufferedHandler), target);
    Require(syncBuffered.Text == "hello", "Synchronous buffered example returned unexpected text.");
    Require(syncBufferedHandler.RequestCount == 1 && syncBufferedHandler.DisposeCount == 1, "Synchronous buffered example did not close its transport once.");

    var syncStreamingHandler = new CountingHandler();
    var syncStreamed = SyncStreamingExample.Run(WithTransport(displayedSettings, syncStreamingHandler), target);
    Require(syncStreamed.Text == "hello", "Synchronous streaming example returned unexpected text.");
    Require(syncStreamingHandler.RequestCount == 1 && syncStreamingHandler.DisposeCount == 1, "Synchronous streaming example did not close its transport once.");

    var asyncRetriever = new RecordingRetriever();
    var asyncRetrieval = await RetrievalExample.RunAsync(
        ProviderSettings.Of("offline-retrieval"),
        RetrievalRegistry(asyncRetriever),
        "offline-retrieval:demo");
    Require(asyncRetrieval.Embeddings.Vectors.Count == 2
        && asyncRetrieval.Embeddings.Vectors[0].Values.SequenceEqual([0.1, 0.2])
        && asyncRetrieval.Embeddings.Space is { ProviderId: "offline-retrieval", Model: "demo", Dimensions: 2 }
        && asyncRetrieval.Embeddings.Raw is null
        && asyncRetrieval.Embeddings.Manifest is { Operation: "embedding", Payloads: null }
        && asyncRetrieval.Reranking.Items.Count == 2
        && asyncRetrieval.Reranking.Items[0] is { Index: 0, DocumentId: "river", Text: "A quiet river bends through the valley.", Score: 0.9 }
        && asyncRetrieval.Reranking.Items[1] is { Index: 1, DocumentId: "lighthouse", Text: "A lighthouse watches the harbor.", Score: 0.1 }
        && asyncRetrieval.Reranking.Raw is null
        && asyncRetrieval.Reranking.Manifest is { Operation: "rerank", Payloads: null }
        && asyncRetriever.EmbedCalls == 1
        && asyncRetriever.RerankCalls == 1
        && asyncRetriever.DisposeCount == 1,
        "Asynchronous retrieval example did not preserve operation, identity, manifest, or disposal facts.");

    var syncRetriever = new RecordingRetriever();
    var syncRetrieval = RetrievalExample.Run(
        ProviderSettings.Of("offline-retrieval"),
        RetrievalRegistry(syncRetriever),
        "offline-retrieval:demo");
    Require(syncRetrieval.Embeddings.Vectors.Count == 2
        && syncRetrieval.Embeddings.Vectors[0].Values.SequenceEqual([0.1, 0.2])
        && syncRetrieval.Reranking.Items.Count == 2
        && syncRetrieval.Reranking.Items[0] is { Index: 0, DocumentId: "river", Text: "A quiet river bends through the valley.", Score: 0.9 }
        && syncRetrieval.Reranking.Items[1] is { Index: 1, DocumentId: "lighthouse", Text: "A lighthouse watches the harbor.", Score: 0.1 }
        && syncRetrieval.Embeddings.Raw is null
        && syncRetrieval.Embeddings.Manifest is { Operation: "embedding", Payloads: null }
        && syncRetrieval.Reranking.Raw is null
        && syncRetrieval.Reranking.Manifest is { Operation: "rerank", Payloads: null }
        && syncRetriever.EmbedCalls == 1
        && syncRetriever.RerankCalls == 1
        && syncRetriever.DisposeCount == 1,
        "Synchronous retrieval example did not preserve operation, identity, or disposal facts.");

    var asyncTeiEmbedHandler = new TeiScriptedHandler(reranker: false);
    var asyncTeiRerankHandler = new TeiScriptedHandler(reranker: true);
    var asyncTei = await TeiExample.RunAsync(
        TeiExample.EmbeddingSettings(asyncTeiEmbedHandler),
        TeiExample.RerankSettings(asyncTeiRerankHandler));
    RequireTeiObservation(asyncTei, "Asynchronous");
    Require(asyncTeiEmbedHandler.RequestCount == 1
        && asyncTeiRerankHandler.RequestCount == 1
        && asyncTeiEmbedHandler.DisposeCount == 1
        && asyncTeiRerankHandler.DisposeCount == 1,
        "Asynchronous TEI example did not retain transport ownership.");

    var syncTeiEmbedHandler = new TeiScriptedHandler(reranker: false);
    var syncTeiRerankHandler = new TeiScriptedHandler(reranker: true);
    var syncTei = TeiExample.Run(
        TeiExample.EmbeddingSettings(syncTeiEmbedHandler),
        TeiExample.RerankSettings(syncTeiRerankHandler));
    RequireTeiObservation(syncTei, "Synchronous");
    Require(syncTeiEmbedHandler.RequestCount == 1
        && syncTeiRerankHandler.RequestCount == 1
        && syncTeiEmbedHandler.DisposeCount == 1
        && syncTeiRerankHandler.DisposeCount == 1,
        "Synchronous TEI example did not retain transport ownership.");

    var asyncVoyageHandler = new VoyageScriptedHandler();
    var asyncVoyage = await VoyageExample.RunAsync(
        VoyageExample.Settings(asyncVoyageHandler, "offline-voyage-key"));
    RequireVoyageObservation(asyncVoyage, "Asynchronous", expectedInputCount: 2);
    Require(asyncVoyageHandler.RequestCount == 2 && asyncVoyageHandler.DisposeCount == 1,
        "Asynchronous Voyage example did not retain transport ownership.");

    var syncVoyageHandler = new VoyageScriptedHandler();
    var syncVoyage = VoyageExample.Run(
        VoyageExample.Settings(syncVoyageHandler, "offline-voyage-key"));
    RequireVoyageObservation(syncVoyage, "Synchronous", expectedInputCount: 1);
    Require(syncVoyageHandler.RequestCount == 2 && syncVoyageHandler.DisposeCount == 1,
        "Synchronous Voyage example did not retain transport ownership.");

    var asyncJinaHandler = new JinaScriptedHandler();
    var asyncJina = await JinaExample.RunAsync(JinaExample.Settings(asyncJinaHandler, "offline-jina-key"));
    RequireJinaObservation(asyncJina, "Asynchronous", expectedInputCount: 2);
    Require(asyncJinaHandler.RequestCount == 2 && asyncJinaHandler.DisposeCount == 1,
        "Asynchronous Jina example did not retain transport ownership.");

    var syncJinaHandler = new JinaScriptedHandler();
    var syncJina = JinaExample.Run(JinaExample.Settings(syncJinaHandler, "offline-jina-key"));
    RequireJinaObservation(syncJina, "Synchronous", expectedInputCount: 1);
    Require(syncJinaHandler.RequestCount == 2 && syncJinaHandler.DisposeCount == 1,
        "Synchronous Jina example did not retain transport ownership.");

    var telemetryHandler = new CountingHandler();
    var telemetry = await TelemetryExample.RunAsync(WithTransport(displayedSettings, telemetryHandler), target);
    Require(telemetry.Generation.Text == "hello"
        && telemetry.Events.OfType<RequestStarted>().Single().PromptText is null
        && telemetry.Events.OfType<RequestCompleted>().Single().ResponseText is null
        && telemetryHandler.RequestCount == 1
        && telemetryHandler.DisposeCount == 1,
        "Telemetry example did not retain payload-free public event facts or transport ownership.");

    var manifestHandler = new CountingHandler();
    var manifest = await ManifestExample.RunAsync(WithTransport(displayedSettings, manifestHandler), target);
    var schema = ManifestUtilities.JsonSchema();
    Require(!manifest.Partial.Complete
        && manifest.Terminal.Complete
        && manifest.Generation.Manifest == manifest.Terminal
        && ManifestUtilities.SchemaDigest(schema).StartsWith("sha256:", StringComparison.Ordinal)
        && ManifestUtilities.Render(manifest.Terminal).Length != 0
        && manifestHandler.RequestCount == 1
        && manifestHandler.DisposeCount == 1,
        "Manifest example did not preserve partial, terminal, or embedded-schema facts.");

    var accountingDirectory = Path.Combine(Path.GetTempPath(), $"anyinfer-accounting-{Guid.NewGuid():N}");
    Directory.CreateDirectory(accountingDirectory);
    try
    {
        var accountingHandler = new CountingHandler();
        var accounting = await AccountingExample.RunAsync(
            WithTransport(displayedSettings, accountingHandler),
            target,
            Path.Combine(accountingDirectory, "spend.json"));
        Require(accounting.PricedUsage.CostUsd?.CompareTo(EDecimal.FromString("0.004")) == 0
            && accounting.UnknownCost is null
            && accounting.FreeUsage.CostUsd?.CompareTo(EDecimal.Zero) == 0
            && accounting.RequestEstimate.UnpricedParts == 1
            && accounting.Generation.Text == "hello"
            && accounting.Totals.Requests == 1
            && accounting.Totals.UnknownRequests == 1
            && accounting.StoreWasAbsent
            && accounting.StoreWritten
            && accounting.Persisted["total"] == accounting.Totals
            && accountingHandler.RequestCount == 1
            && accountingHandler.DisposeCount == 1,
            "Accounting example did not preserve explicit pricing, storage, or caller ownership facts.");
    }
    finally
    {
        Directory.Delete(accountingDirectory, recursive: true);
    }

    var policyHandler = new CountingHandler(policy: true);
    var policy = await RequestPolicyExample.RunAsync(WithTransport(displayedSettings, policyHandler), target);
    Require(policy.Generation.Text == ""
        && policy.Generation.FinishReason == "tool_calls"
        && policy.Totals.Requests == 1
        && policy.Route.ContextWindowTargets.SequenceEqual([target])
        && policy.RequestCache.Mode == CacheMode.Off
        && policy.Tool.Name == "lookup_weather"
        && policy.RawCall.Name == "lookup_weather"
        && policy.RawResult.Content == "clear"
        && policy.Generation.ToolCalls.Single() is { Id: "inbound-call", Name: "lookup_weather" } inboundCall
        && IsBoston(inboundCall.Arguments)
        && policy.ToolDeltas.Single() is
        {
            Index: 0,
            CallId: "inbound-call",
            Name: "lookup_weather",
            ArgumentsFragment: "{\"city\":\"Boston\"}",
        }
        && policyHandler.RequestCount == 1
        && policyHandler.DisposeCount == 1,
        "Request-policy example did not preserve public policy, raw-tool, or ownership facts.");

    var structuredHandler = new CountingHandler(structured: true);
    var structured = await StructuredOutputExample.RunAsync(WithTransport(displayedSettings, structuredHandler), target);
    Require(structured.Answer == "ok", "Structured-output example returned unexpected text.");
    Require(structuredHandler.RequestCount == 1 && structuredHandler.DisposeCount == 1, "Structured-output example did not close its transport once.");

    var richHandler = new RichGenerationHandler();
    byte[] fixtureImage = [0x89, 0x50];
    byte[] fixtureDocument = [0x5A];
    byte[] fixtureAudio = [0x52, 0x49, 0x46, 0x46];
    var rich = await RichGenerationExample.RunAsync(
        WithTransport(displayedSettings, richHandler),
        target,
        fixtureImage,
        fixtureDocument,
        fixtureAudio);
    Require(rich.Generation.Text == "rich answer"
        && rich.Generation.Logprobs.Single() is { Token: "rich", Logprob: -0.25, Bytes: [114, 105, 99, 104] }
        && rich.Generation.Logprobs[0].Top.Single() is { Token: "rich", Logprob: -0.25 }
        && richHandler.RequestCount == 1
        && richHandler.DisposeCount == 1,
        "Rich-generation example did not retain typed inputs, logprobs, or transport ownership.");

    var toolHandler = new ToolLoopHandler();
    var toolResult = await ToolLoopExample.RunAsync(WithTransport(displayedSettings, toolHandler), target);
    Require(toolResult.Generation.Text == "Boston is clear."
        && toolResult.Generation.FinishReason == "stop"
        && toolResult.HandlerCalls == 1
        && toolHandler.RequestCount == 2
        && toolHandler.DisposeCount == 1,
        "Tool-loop example did not retain two-round history, final result, or transport ownership.");

    var configurationHandler = new CountingHandler();
    var configurationRegistry = BuiltinRegistry(configurationHandler);
    const string configJson = """
        {"format_version":1,"providers":[{"id":"openai-compat","base_url":"https://offline.example/v1"}],"default_route":["openai-compat:demo"]}
        """;
    var configured = await ConfigurationExample.RunAsync(configJson, "Say hello.", configurationRegistry);
    Require(configured.Text == "hello", "Configuration example returned unexpected text.");
    Require(configurationHandler.RequestCount == 1 && configurationHandler.DisposeCount == 1, "Configuration example did not close its transport once.");

    var primary = new CountingHandler(statusCode: HttpStatusCode.ServiceUnavailable);
    var backup = new CountingHandler();
    var routed = await RoutingExample.RunAsync(
        [
            ProviderSettings.Of("openai-compat", baseUrl, transport: primary, alias: "primary"),
            ProviderSettings.Of("openai-compat", baseUrl, transport: backup, alias: "backup"),
        ],
        new Route(["primary:demo", "backup:demo"], retry: new Retry(1)));
    Require(routed.Text == "hello" && routed.Attempts.Count == 2, "Routing example did not retain fallback attempts.");
    Require(primary.RequestCount == 1 && backup.RequestCount == 1, "Routing example did not use both targets in order.");
    Require(primary.DisposeCount == 1 && backup.DisposeCount == 1, "Routing example did not close each transport once.");
}

static ProviderSettings WithTransport(ProviderSettings source, HttpMessageHandler transport) =>
    ProviderSettings.Of(
        source.ProviderId,
        source.BaseUrl,
        source.ApiKey,
        source.ApiVersion,
        source.Headers,
        source.Options,
        source.TimeoutS,
        transport,
        source.Alias,
        source.Limits,
        source.Proxy,
        source.Verify,
        source.ClientCertificate);

static ProviderRegistry BuiltinRegistry(HttpMessageHandler transport)
{
    var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
    var wrapped = new ProviderDescriptor(
        builtin.Id,
        builtin.DisplayName,
        (config, cancellationToken) =>
        {
            var settings = ProviderSettings.Of(
                builtin.Id,
                config.BaseUrl,
                config.ApiKey,
                config.ApiVersion,
                config.Headers,
                config.Options,
                config.TimeoutS,
                transport,
                config.ProviderId == builtin.Id ? null : config.ProviderId);
            return builtin.Factory(new ProviderConfig(settings, config.EngineId, config.ApiKey, config.Options), cancellationToken);
        },
        builtin.Aliases,
        builtin.Setup,
        builtin.DefaultBaseUrl,
        builtin.RequiresBaseUrl,
        builtin.StructuredOutputProfiles,
        builtin.MaxRepairAttempts);
    return new ProviderRegistry([wrapped]);
}

static ProviderRegistry RetrievalRegistry(RecordingRetriever retriever) =>
    new([
        new ProviderDescriptor(
            "offline-retrieval",
            "Offline retrieval",
            (_, _) => new ValueTask<IAsyncDisposable>(retriever),
            operations: [InferenceOperation.Embedding, InferenceOperation.Rerank]),
    ]);

static void Require(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static bool IsBoston(JsonObject value) =>
    value.TryGetValue("city", out var city) && city is JsonString { Value: "Boston" };

static void RequireTeiObservation(TeiObservation observation, string lane)
{
    Require(observation.Embeddings.Target.ProviderId == "tei-embed"
        && observation.Embeddings.Target.Model == "embed-model"
        && observation.Embeddings.Vectors.Count == 2
        && observation.Embeddings.Vectors[0].Values.SequenceEqual([0.1, 0.2])
        && observation.Embeddings.Usage.InputTokens is null
        && observation.Embeddings.Usage.OutputTokens is null
        && observation.Embeddings.Raw is not null
        && observation.Embeddings.Manifest is { Complete: true, Operation: "embedding", Payloads: null }
        && observation.Reranking.Target.ProviderId == "tei-rerank"
        && observation.Reranking.Target.Model == "rerank-model"
        && observation.Reranking.Items.Count == 2
        && observation.Reranking.Items[0] is { Index: 0, DocumentId: "river", Score: 0.9 }
        && observation.Reranking.Items[1] is { Index: 1, DocumentId: "lighthouse", Score: 0.1 }
        && observation.Reranking.Usage.InputTokens is null
        && observation.Reranking.Usage.OutputTokens is null
        && observation.Reranking.Raw is not null
        && observation.Reranking.Manifest is { Complete: true, Operation: "rerank", Payloads: null },
        $"{lane} TEI example did not preserve public result, caller identity, manifest, or unknown usage facts.");
}

static void RequireVoyageObservation(VoyageObservation observation, string lane, int expectedInputCount)
{
    Require(observation.Embeddings.Target.ProviderId == "voyage-retrieval"
        && observation.Embeddings.Target.Model == "voyage-3.5-lite"
        && observation.Embeddings.Vectors.Count == expectedInputCount
        && observation.Embeddings.Vectors[0].Values.SequenceEqual(expectedInputCount == 2 ? [0.1, 0.2] : [0.5, 0.6])
        && observation.Embeddings.Usage.InputTokens is null
        && observation.Embeddings.Usage.OutputTokens is null
        && observation.Embeddings.Usage.TotalTokens == 7
        && observation.Embeddings.Raw is not null
        && observation.Embeddings.Manifest is { Complete: true, Operation: "embedding", Payloads: null }
        && observation.Reranking.Target.ProviderId == "voyage-retrieval"
        && observation.Reranking.Target.Model == "rerank-2.5"
        && observation.Reranking.Items.Count == 1
        && observation.Reranking.Items[0] is { Index: 1, DocumentId: "lighthouse", Score: 0.1 }
        && observation.Reranking.Usage.InputTokens is null
        && observation.Reranking.Usage.OutputTokens is null
        && observation.Reranking.Usage.TotalTokens == 7
        && observation.Reranking.Raw is not null
        && observation.Reranking.Manifest is { Complete: true, Operation: "rerank", Payloads: null },
        $"{lane} Voyage example did not preserve public result, total-only usage, provider order, or manifest privacy.");
}

static void RequireJinaObservation(JinaObservation observation, string lane, int expectedInputCount)
{
    Require(observation.Embeddings.Target.ProviderId == "jina-retrieval"
        && observation.Embeddings.Target.Model == "jina-embeddings-v5-text-small"
        && observation.Embeddings.Vectors.Count == expectedInputCount
        && observation.Embeddings.Vectors[0].Values.SequenceEqual(expectedInputCount == 2 ? [0.1, 0.2] : [0.5, 0.6])
        && observation.Embeddings.Usage.InputTokens is null
        && observation.Embeddings.Usage.OutputTokens is null
        && observation.Embeddings.Usage.TotalTokens == 7
        && observation.Embeddings.Raw is not null
        && HasPromptTokens(observation.Embeddings.Raw)
        && observation.Embeddings.Manifest is { Complete: true, Operation: "embedding", Payloads: null }
        && observation.Reranking.Target.ProviderId == "jina-retrieval"
        && observation.Reranking.Target.Model == "jina-reranker-v3"
        && observation.Reranking.Items.Count == 1
        && observation.Reranking.Items[0] is { Index: 1, DocumentId: "lighthouse", Score: 0.1 }
        && observation.Reranking.Usage.InputTokens is null
        && observation.Reranking.Usage.OutputTokens is null
        && observation.Reranking.Usage.TotalTokens == 7
        && observation.Reranking.Raw is not null
        && HasPromptTokens(observation.Reranking.Raw)
        && observation.Reranking.Manifest is { Complete: true, Operation: "rerank", Payloads: null },
        $"{lane} Jina example did not preserve public result, total-only usage, provider order, or manifest privacy.");
}

static bool HasPromptTokens(JsonValue? raw) => raw is JsonObject payload
    && payload.TryGetValue("usage", out var usageValue)
    && usageValue is JsonObject usage
    && usage.TryGetValue("prompt_tokens", out var promptTokens)
    && promptTokens is JsonInteger integer
    && integer.Value == 7;

sealed class RichGenerationHandler : HttpMessageHandler
{
    public int RequestCount { get; private set; }
    public int DisposeCount { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        var body = await request.Content!.ReadAsStringAsync(cancellationToken);
        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        var content = root.GetProperty("messages")[0].GetProperty("content").EnumerateArray().ToArray();
        if (request.RequestUri?.AbsolutePath != "/v1/chat/completions"
            || !root.GetProperty("logprobs").GetBoolean()
            || root.GetProperty("top_logprobs").GetInt32() != 2
            || content.Length != 4
            || content[0].GetProperty("type").GetString() != "text"
            || content[1].GetProperty("image_url").GetProperty("url").GetString() != "data:image/png;base64,iVA="
            || content[1].GetProperty("image_url").GetProperty("detail").GetString() != "low"
            || content[2].GetProperty("file").GetProperty("filename").GetString() != "brief.pdf"
            || content[2].GetProperty("file").GetProperty("file_data").GetString() != "data:application/pdf;base64,Wg=="
            || content[3].GetProperty("input_audio").GetProperty("format").GetString() != "wav"
            || content[3].GetProperty("input_audio").GetProperty("data").GetString() != "UklGRg==")
        {
            throw new InvalidOperationException("Rich-generation example did not project its typed request.");
        }
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("""{"choices":[{"message":{"content":"rich answer"},"finish_reason":"stop","logprobs":{"content":[{"token":"rich","logprob":-0.25,"bytes":[114,105,99,104],"top_logprobs":[{"token":"rich","logprob":-0.25}]}]}}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""", Encoding.UTF8, "application/json"),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }
}

sealed class ToolLoopHandler : HttpMessageHandler
{
    public int RequestCount { get; private set; }
    public int DisposeCount { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        var body = await request.Content!.ReadAsStringAsync(cancellationToken);
        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        if (request.RequestUri?.AbsolutePath != "/v1/chat/completions"
            || root.GetProperty("tools")[0].GetProperty("function").GetProperty("name").GetString() != "read_weather")
        {
            throw new InvalidOperationException("Tool-loop example did not project its registered tool.");
        }
        if (RequestCount == 1)
        {
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"choices":[{"message":{"tool_calls":[{"id":"weather-1","type":"function","function":{"name":"read_weather","arguments":"{\"city\":\"Boston\"}"}}]},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""", Encoding.UTF8, "application/json"),
            };
        }
        var messages = root.GetProperty("messages").EnumerateArray().ToArray();
        if (RequestCount != 2
            || messages[^2].GetProperty("tool_calls")[0].GetProperty("id").GetString() != "weather-1"
            || messages[^1].GetProperty("tool_call_id").GetString() != "weather-1"
            || messages[^1].GetProperty("content").GetString() != "clear")
        {
            throw new InvalidOperationException("Tool-loop example did not preserve tool history.");
        }
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("""{"choices":[{"message":{"content":"Boston is clear."},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":2,"total_tokens":4}}""", Encoding.UTF8, "application/json"),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }
}

sealed class CountingHandler(
    HttpStatusCode statusCode = HttpStatusCode.OK,
    bool structured = false,
    bool probes = false,
    bool policy = false) : HttpMessageHandler
{
    public int RequestCount { get; private set; }
    public int ModelRequestCount { get; private set; }
    public int EmptyModelBodies { get; private set; }
    public int ProbeRequestCount { get; private set; }
    public int DisposeCount { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        if (request.Method == HttpMethod.Get && request.RequestUri?.AbsolutePath == "/v1/models")
        {
            ModelRequestCount++;
            byte[] bytes = request.Content is null
                ? []
                : await request.Content.ReadAsByteArrayAsync(cancellationToken);
            if (bytes.Length == 0
                && request.Content?.Headers.ContentType?.MediaType == "application/json"
                && request.Headers.Authorization is null)
            {
                EmptyModelBodies++;
            }

            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("{\"data\":[{\"id\":\"demo\"}]}", Encoding.UTF8, "application/json"),
            };
        }

        var requestBody = request.Content is null
            ? ""
            : await request.Content.ReadAsStringAsync(cancellationToken);
        if (request.Method != HttpMethod.Post
            || request.RequestUri?.AbsolutePath != "/v1/chat/completions"
            || !string.IsNullOrEmpty(request.RequestUri?.Query)
            || request.Content?.Headers.ContentType?.MediaType != "application/json"
            || request.Headers.Authorization is not null)
        {
            throw new InvalidOperationException("Generation request used unexpected HTTP transport fields.");
        }

        if (probes)
        {
            if (request.Method != HttpMethod.Post
                || request.RequestUri?.AbsolutePath != "/v1/chat/completions"
                || !string.IsNullOrEmpty(request.RequestUri?.Query)
                || request.Content?.Headers.ContentType?.MediaType != "application/json"
                || request.Headers.Authorization is not null)
            {
                throw new InvalidOperationException("Probe request used unexpected HTTP transport fields.");
            }

            return ProbeResponse(requestBody);
        }

        if (policy)
        {
            return PolicyResponse(requestBody);
        }

        var stream = requestBody.Contains("\"stream\":true", StringComparison.Ordinal);
        using var document = JsonDocument.Parse(requestBody);
        if (document.RootElement.GetProperty("model").GetString() != "demo")
        {
            throw new InvalidOperationException("Generation request did not retain the selected model.");
        }

        if (structured
            && (document.RootElement.TryGetProperty("response_format", out _)
                || !document.RootElement.GetProperty("messages")
                    .EnumerateArray()
                    .Any(static message => message.GetProperty("role").GetString() == "system"
                        && message.GetProperty("content").GetString()?.StartsWith(
                            "Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n",
                            StringComparison.Ordinal) == true)))
        {
            throw new InvalidOperationException("Structured example did not use prompt-based schema enforcement.");
        }
        if (statusCode != HttpStatusCode.OK)
        {
            return new HttpResponseMessage(statusCode)
            {
                Content = new StringContent("{\"error\":\"offline failure\"}", Encoding.UTF8, "application/json"),
            };
        }

        var text = structured ? "{\\\"answer\\\":\\\"ok\\\"}" : "hello";
        if (stream)
        {
            var payload = $"data: {{\"choices\":[{{\"delta\":{{\"content\":\"hello\"}}}}]}}\n\n" +
                "data: {\"choices\":[{\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}\n\n" +
                "data: [DONE]\n\n";
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(payload, Encoding.UTF8, "text/event-stream"),
            };
        }

        var body = $"{{\"choices\":[{{\"message\":{{\"content\":\"{text}\"}},\"finish_reason\":\"stop\"}}],\"usage\":{{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}}}";
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
    }

    private HttpResponseMessage ProbeResponse(string requestBody)
    {
        using var document = JsonDocument.Parse(requestBody);
        var root = document.RootElement;
        if (root.GetProperty("model").GetString() != "demo"
            || root.GetProperty("max_tokens").GetInt32() != 64
            || root.GetProperty("temperature").GetDouble() != 0)
        {
            throw new InvalidOperationException("Probe request lost its forced sampling controls.");
        }

        ProbeRequestCount++;
        return ProbeRequestCount switch
        {
            1 => JsonProbeResponse(root, "json_schema"),
            2 => JsonProbeResponse(root, "json_object"),
            3 => ToolProbeResponse(root),
            4 => StreamingProbeResponse(root),
            _ => throw new InvalidOperationException("Probe example made an unexpected request."),
        };
    }

    private static HttpResponseMessage PolicyResponse(string requestBody)
    {
        using var document = JsonDocument.Parse(requestBody);
        var root = document.RootElement;
        var messages = root.GetProperty("messages").EnumerateArray().ToArray();
        var function = root.GetProperty("tools")[0].GetProperty("function");
        var parameters = function.GetProperty("parameters");
        var assistant = messages.Single(static message => message.GetProperty("role").GetString() == "assistant");
        var outboundCall = assistant.GetProperty("tool_calls")[0];
        var outboundFunction = outboundCall.GetProperty("function");
        using var outboundArguments = JsonDocument.Parse(outboundFunction.GetProperty("arguments").GetString()!);
        var tool = messages.Single(static message => message.GetProperty("role").GetString() == "tool");
        if (!root.GetProperty("stream").GetBoolean()
            || function.GetProperty("name").GetString() != "lookup_weather"
            || parameters.GetProperty("type").GetString() != "object"
            || parameters.GetProperty("properties").GetProperty("city").GetProperty("type").GetString() != "string"
            || assistant.GetProperty("content").ValueKind != JsonValueKind.Null
            || outboundCall.GetProperty("id").GetString() != "call-1"
            || outboundFunction.GetProperty("name").GetString() != "lookup_weather"
            || outboundArguments.RootElement.GetProperty("city").GetString() != "Boston"
            || tool.GetProperty("tool_call_id").GetString() != "call-1"
            || tool.GetProperty("content").GetString() != "clear"
            || tool.TryGetProperty("is_error", out _))
        {
            throw new InvalidOperationException("Request-policy example did not project raw tool feedback.");
        }

        const string payload = "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"inbound-call\",\"function\":{\"name\":\"lookup_weather\",\"arguments\":\"{\\\"city\\\":\\\"Boston\\\"}\"}}]}}]}\n\n" +
            "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\"}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}\n\n" +
            "data: [DONE]\n\n";
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(payload, Encoding.UTF8, "text/event-stream"),
        };
    }

    private static HttpResponseMessage JsonProbeResponse(JsonElement request, string format)
    {
        var responseFormat = request.GetProperty("response_format");
        if (responseFormat.GetProperty("type").GetString() != format)
        {
            throw new InvalidOperationException("Probe response format did not match its selected feature.");
        }

        if (format == "json_schema"
            && responseFormat.GetProperty("json_schema").GetProperty("name").GetString()
                != "capability_probe")
        {
            throw new InvalidOperationException("Schema probe did not retain its named probe schema.");
        }

        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("""{"choices":[{"message":{"content":"{\"colour\":\"blue\"}"},"finish_reason":"stop"}]}""", Encoding.UTF8, "application/json"),
        };
    }

    private static HttpResponseMessage ToolProbeResponse(JsonElement request)
    {
        if (request.GetProperty("tool_choice").GetString() != "required"
            || request.GetProperty("tools")[0].GetProperty("function").GetProperty("name").GetString()
                != "record_colour")
        {
            throw new InvalidOperationException("Tool probe did not retain its forced raw tool declaration.");
        }

        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("""{"choices":[{"message":{"tool_calls":[{"id":"probe-call","type":"function","function":{"name":"record_colour","arguments":"{\"colour\":\"blue\"}"}}]},"finish_reason":"tool_calls"}]}""", Encoding.UTF8, "application/json"),
        };
    }

    private static HttpResponseMessage StreamingProbeResponse(JsonElement request)
    {
        if (!request.GetProperty("stream").GetBoolean()
            || !request.GetProperty("stream_options").GetProperty("include_usage").GetBoolean())
        {
            throw new InvalidOperationException("Streaming probe did not retain stream controls.");
        }

        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(
                "data: {\"choices\":[{\"delta\":{\"content\":\"one, \"}}]}\n\n"
                + "data: {\"choices\":[{\"delta\":{\"content\":\"two\"},\"finish_reason\":\"stop\"}]}\n\n"
                + "data: [DONE]\n\n",
                Encoding.UTF8,
                "text/event-stream"),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            DisposeCount++;
        }

        base.Dispose(disposing);
    }
}

sealed class RecordingRetriever : IEmbedsText, IReranksText, IAsyncDisposable
{
    public int EmbedCalls { get; private set; }
    public int RerankCalls { get; private set; }
    public int DisposeCount { get; private set; }

    public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
    {
        EmbedCalls++;
        if (EmbedCalls != 1
            || RerankCalls != 0
            || request.Model != "demo"
            || !request.Inputs.SequenceEqual(["A quiet river bends through the valley.", "A lighthouse watches the harbor."]))
        {
            throw new InvalidOperationException("Retrieval embedding example did not preserve its literal request or call order.");
        }

        return ValueTask.FromResult(new EmbeddingWireResult(
            [[0.1, 0.2], [0.3, 0.4]],
            model: "demo",
            dimensions: 2,
            normalized: true));
    }

    public ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default)
    {
        RerankCalls++;
        if (EmbedCalls != 1
            || RerankCalls != 1
            || request.Model != "demo"
            || request.Query != "Which text mentions water?"
            || !request.Documents.Select(static document => document.Index).SequenceEqual([0, 1])
            || !request.Documents.Select(static document => document.Text).SequenceEqual(
                ["A quiet river bends through the valley.", "A lighthouse watches the harbor."]))
        {
            throw new InvalidOperationException("Retrieval reranking example did not preserve caller document order.");
        }

        return ValueTask.FromResult(new RerankWireResult([new WireRankedItem(0, 0.9), new WireRankedItem(1, 0.1)], model: "demo"));
    }

    public ValueTask DisposeAsync()
    {
        DisposeCount++;
        return ValueTask.CompletedTask;
    }
}
