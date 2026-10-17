using System.Net;
using System.Text;
using AnyInfer;
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

    var bufferedHandler = new CountingHandler();
    var buffered = await GenerationExample.RunAsync(WithTransport(displayedSettings, bufferedHandler), target);
    Require(buffered.Text == "hello", "Buffered example returned unexpected text.");
    Require(bufferedHandler.RequestCount == 1 && bufferedHandler.DisposeCount == 1, "Buffered example did not close its transport once.");

    var streamingHandler = new CountingHandler();
    var streamed = await StreamingExample.RunAsync(WithTransport(displayedSettings, streamingHandler), target);
    Require(streamed.Text == "hello", "Streaming example returned unexpected text.");
    Require(streamingHandler.RequestCount == 1 && streamingHandler.DisposeCount == 1, "Streaming example did not close its transport once.");

    var structuredHandler = new CountingHandler(structured: true);
    var structured = await StructuredOutputExample.RunAsync(WithTransport(displayedSettings, structuredHandler), target);
    Require(structured.Text.Contains("answer", StringComparison.Ordinal), "Structured-output example returned unexpected text.");
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
        builtin.ModelCapabilities,
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

sealed class CountingHandler(HttpStatusCode statusCode = HttpStatusCode.OK, bool structured = false) : HttpMessageHandler
{
    public int RequestCount { get; private set; }
    public int DisposeCount { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        var stream = request.Content is not null && (await request.Content.ReadAsStringAsync(cancellationToken)).Contains("\"stream\":true", StringComparison.Ordinal);
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

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            DisposeCount++;
        }

        base.Dispose(disposing);
    }
}
