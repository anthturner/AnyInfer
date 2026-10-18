using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Config;
using AnyInfer.Examples;
using AnyInfer.Providers;

await VerifyAsync();

static async Task VerifyAsync()
{
    const string baseUrl = "https://offline.example/v1";
    const string target = "openai-compat:demo";

    var displayedSettings = SettingsExample.Create(baseUrl);
    Require(displayedSettings.ProviderId == "openai-compat", "Settings example did not produce the expected provider.");

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
            new PricingEntry("demo-model", new Pricing(3.25m, 4.5m), "2026-10-17", "offline example"),
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
        && catalogObservation.Pricing is { Value.InputPer1M: 3.25m, Provenance: Provenance.Catalog },
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

    var structuredHandler = new CountingHandler(structured: true);
    var structured = await StructuredOutputExample.RunAsync(WithTransport(displayedSettings, structuredHandler), target);
    Require(structured.Answer == "ok", "Structured-output example returned unexpected text.");
    Require(structuredHandler.RequestCount == 1 && structuredHandler.DisposeCount == 1, "Structured-output example did not close its transport once.");

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
        source.Alias);

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

static void Require(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

sealed class CountingHandler(
    HttpStatusCode statusCode = HttpStatusCode.OK,
    bool structured = false,
    bool probes = false) : HttpMessageHandler
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

        var stream = requestBody.Contains("\"stream\":true", StringComparison.Ordinal);
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
