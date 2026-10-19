using System.Net;
using System.Text;
using AnyInfer.Capabilities;
using AnyInfer.Config;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Routing;
using AnyInfer.Schema;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public builtin HTTP controls for request-admission policy boundaries.</summary>
public sealed class PolicyAdmissionHttpTests
{
    [Fact]
    public async Task Unknown_refuse_is_a_direct_pre_dispatch_spend_error_with_no_generation_send()
    {
        var handler = new RecordingHandler();
        await using var client = CreateClient(handler, spendPolicy: new SpendPolicy(onUnknown: "refuse"));

        var failure = await Assert.ThrowsAsync<SpendLimitException>(() =>
            client.GenerateAsync("unknown", target: "alpha:model"));

        Assert.Null(failure.Provider);
        Assert.Equal("generate", failure.Phase);
        Assert.False(failure.Retryable);
        Assert.Null(failure.LimitUsd);
        Assert.Equal(EDecimal.Zero, failure.SpentUsd);
        Assert.Null(failure.EstimatedUsd);
        Assert.Equal(0, handler.SendCalls);
    }

    [Fact]
    public async Task Trusted_context_window_refuses_before_http_and_context_gate_false_dispatches()
    {
        var capabilities = new ModelCapabilities(
            contextWindow: new Sourced<int>(128, Provenance.Catalog));
        var overrides = Capabilities(capabilities);
        var handler = new RecordingHandler();
        var prompt = new string('x', 4_000);

        await using (var gated = CreateClient(handler, capabilityOverrides: overrides))
        {
            var failure = await Assert.ThrowsAsync<AllTargetsFailedException>(() =>
                gated.GenerateAsync(prompt, target: "alpha:model"));
            var error = Assert.IsType<ContextLengthException>(Assert.Single(failure.Attempts).Error);
            Assert.Equal("alpha", error.Provider);
            Assert.False(error.Retryable);
            Assert.Equal("generate", error.Phase);
        }

        Assert.Equal(0, handler.SendCalls);

        await using (var ungated = CreateClient(handler, capabilityOverrides: overrides, contextGate: false))
        {
            Assert.Equal("ok", (await ungated.GenerateAsync(prompt, target: "alpha:model")).Text);
        }

        Assert.Equal(1, handler.SendCalls);
    }

    [Fact]
    public async Task From_config_applies_provider_limits_and_cache_default_without_eager_transport_work()
    {
        var first = new BlockingContentHandler();
        var settings = ProviderSettings.Of(
            "openai-compat",
            "https://policy.invalid/v1",
            "secret",
            transport: first,
            alias: "alpha",
            limits: new RateLimits(maxConcurrent: 1));
        var config = new AnyInferConfig([settings], cache: new CachePolicy(CacheMode.Off));
        var client = AsyncClient.FromConfig(config);
        try
        {
            var initial = client.GenerateAsync("one", target: "alpha:model");
            await first.Started.Task.WaitAsync(TimeSpan.FromSeconds(1));
            var queued = client.GenerateAsync("two", target: "alpha:model");
            Assert.Equal(1, first.SendCalls);

            first.Release.TrySetResult();
            await initial;
            await first.SecondStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            await queued;

            Assert.Equal(2, first.SendCalls);
            Assert.All(first.Contents, static content => Assert.True(content.Disposed));
        }
        finally
        {
            first.Release.TrySetResult();
            await client.DisposeAsync();
        }
    }

    [Theory]
    [InlineData(413, "{\"error\":{\"message\":\"maximum context length is 16 tokens\"}}", "maximum context length is 16 tokens")]
    [InlineData(422, "{\"error\":{\"detail\":\"too many tokens for this model\"}}", "too many tokens for this model")]
    [InlineData(413, "{\"error\":{\"type\":\"context_length exceeded\"}}", "context_length exceeded")]
    [InlineData(422, "{\"error\":\"request exceeds maximum context\"}", "request exceeds maximum context")]
    [InlineData(413, "{\"error\":{\"message\":false,\"detail\":\"maximum context is 16 tokens\"}}", "maximum context is 16 tokens")]
    [InlineData(422, "{\"error\":{\"message\":true,\"detail\":\"maximum context is 16 tokens\"}}", "{\"error\":{\"message\":true,\"detail\":\"maximum context is 16 tokens\"}}")]
    [InlineData(413, "context length was exceeded", "context length was exceeded")]
    public async Task Modern_413_and_422_context_details_use_the_specialized_context_route(
        int status,
        string body,
        string expectedDetail)
    {
        var first = new ScriptHandler(new ResponseScript((HttpStatusCode)status, body, TimeSpan.FromSeconds(7)));
        var alternate = new ScriptHandler(ResponseScript.Success("alternate"));
        var ordinary = new ScriptHandler(ResponseScript.Success("ordinary"));
        var observer = new Collector();
        await using var client = CreateContextRouteClient(first, alternate, ordinary, observer);
        var route = ContextRoute();

        var result = await client.GenerateAsync(
            "schema request",
            route: route,
            schema: Schema());

        Assert.Equal(StructuredResponseText("alternate"), result.Text);
        Assert.Equal("alternate", Assert.IsType<JsonString>(Assert.IsType<JsonObject>(result.Structured).Properties.Single().Value).Value);
        Assert.Equal("beta", result.Target!.ProviderId);
        Assert.Equal(1, first.SendCalls);
        Assert.Equal(1, alternate.SendCalls);
        Assert.Equal(0, ordinary.SendCalls);
        AssertModernSchema(first.Requests.Single());
        AssertModernSchema(alternate.Requests.Single());

        var context = Assert.IsType<ContextLengthException>(
            Assert.Single(result.Attempts, static attempt => attempt.Error is not null).Error);
        Assert.Equal(status, context.HttpStatus);
        Assert.Equal("alpha", context.Provider);
        Assert.Equal("generate", context.Phase);
        Assert.False(context.Retryable);
        Assert.Null(context.RetryAfterS);
        Assert.Equal(expectedDetail, context.Message);
        Assert.Equal(expectedDetail, context.Detail);
        var fallback = Assert.Single(observer.Events.OfType<FallbackTriggered>());
        Assert.Equal("alpha:model", fallback.FromTarget.ToString());
        Assert.Equal("beta:model", fallback.ToTarget);
        Assert.NotNull(fallback.Error);
        Assert.Equal(nameof(ContextLengthException), fallback.Error!.TypeName);
        Assert.Equal(status, fallback.Error.HttpStatus);
        Assert.Equal("alpha", fallback.Error.Provider);
        Assert.Equal("generate", fallback.Error.Phase);
        Assert.False(fallback.Error.Retryable);
        Assert.Equal(expectedDetail, fallback.Error.Detail);
        AssertDisposed(first, alternate, ordinary);
    }

    [Theory]
    [InlineData(400, "{\"error\":{\"code\":\"context_length_exceeded\",\"message\":\"request rejected\"}}")]
    [InlineData(413, "{\"error\":{\"detail\":\"unsupported request form\"}}")]
    [InlineData(422, "{\"error\":{\"type\":\"unprocessable payload\"}}")]
    public async Task Nonqualifying_context_like_http_errors_stay_on_the_ordinary_route(int status, string body)
    {
        var first = new ScriptHandler(new ResponseScript((HttpStatusCode)status, body, TimeSpan.FromSeconds(7)));
        var alternate = new ScriptHandler(ResponseScript.Success("alternate"));
        var ordinary = new ScriptHandler(ResponseScript.Success("ordinary"));
        var observer = new Collector();
        await using var client = CreateContextRouteClient(first, alternate, ordinary, observer);

        var result = await client.GenerateAsync(
            "schema request",
            route: ContextRoute(),
            schema: Schema());

        Assert.Equal(StructuredResponseText("ordinary"), result.Text);
        Assert.Equal("ordinary", Assert.IsType<JsonString>(Assert.IsType<JsonObject>(result.Structured).Properties.Single().Value).Value);
        Assert.Equal("ordinary", result.Target!.ProviderId);
        Assert.Equal(1, first.SendCalls);
        Assert.Equal(0, alternate.SendCalls);
        Assert.Equal(1, ordinary.SendCalls);
        var invalid = Assert.IsType<ProviderException>(
            Assert.Single(result.Attempts, static attempt => attempt.Error is not null).Error);
        Assert.IsNotType<ContextLengthException>(invalid);
        Assert.Equal("invalid_request", invalid.Category);
        Assert.Equal(status, invalid.HttpStatus);
        Assert.Equal("alpha", invalid.Provider);
        Assert.Equal("generate", invalid.Phase);
        Assert.False(invalid.Retryable);
        Assert.Equal(7d, invalid.RetryAfterS);
        var fallback = Assert.Single(observer.Events.OfType<FallbackTriggered>());
        Assert.Equal("ordinary:model", fallback.ToTarget);
        Assert.Equal(nameof(ProviderException), fallback.Error!.TypeName);
        AssertDisposed(first, alternate, ordinary);
    }

    [Fact]
    public async Task Truthy_nonstring_error_value_uses_bounded_raw_detail_before_later_context_marker()
    {
        var body = "{\"error\":{\"message\":{\"padding\":\"" + new string('x', 450) + "\"},\"detail\":\"maximum context is 16 tokens\"}}";
        var first = new ScriptHandler(new ResponseScript(HttpStatusCode.RequestEntityTooLarge, body));
        var alternate = new ScriptHandler(ResponseScript.Success("alternate"));
        var ordinary = new ScriptHandler(ResponseScript.Success("ordinary"));
        var observer = new Collector();
        await using var client = CreateContextRouteClient(first, alternate, ordinary, observer);

        var result = await client.GenerateAsync("schema request", route: ContextRoute(), schema: Schema());

        Assert.Equal(StructuredResponseText("ordinary"), result.Text);
        Assert.Equal("ordinary", Assert.IsType<JsonString>(Assert.IsType<JsonObject>(result.Structured).Properties.Single().Value).Value);
        Assert.Equal(1, first.SendCalls);
        Assert.Equal(0, alternate.SendCalls);
        Assert.Equal(1, ordinary.SendCalls);
        var invalid = Assert.IsType<ProviderException>(
            Assert.Single(result.Attempts, static attempt => attempt.Error is not null).Error);
        Assert.IsNotType<ContextLengthException>(invalid);
        Assert.Equal("invalid_request", invalid.Category);
        Assert.Equal("ordinary:model", Assert.Single(observer.Events.OfType<FallbackTriggered>()).ToTarget);
        AssertDisposed(first, alternate, ordinary);
    }

    [Fact]
    public async Task Frozen_wire_request_keeps_a_context_marked_413_as_the_legacy_invalid_request_error()
    {
        var handler = new ScriptHandler(new ResponseScript(
            HttpStatusCode.RequestEntityTooLarge,
            "{\"error\":{\"message\":\"maximum context length is 16 tokens\"}}",
            TimeSpan.FromSeconds(7)));
        await using var adapter = new OpenAIChatAdapter(
            new Uri("https://policy.invalid/v1"),
            "secret",
            handler: handler);
        var request = new WireRequest(
            "model",
            [Message.User("legacy")],
            new Sampling(),
            schema: Schema().JsonSchema);

        var failure = await Assert.ThrowsAsync<ProviderException>(() => Collect(adapter.GenerateAsync(request)));

        Assert.IsNotType<ContextLengthException>(failure);
        Assert.Equal("invalid_request", failure.Category);
        Assert.Equal(413, failure.HttpStatus);
        Assert.Equal("generate", failure.Phase);
        Assert.False(failure.Retryable);
        Assert.Equal(7d, failure.RetryAfterS);
        Assert.Equal(1, handler.SendCalls);
        AssertDisposed(handler);
    }

    private static AsyncClient CreateClient(
        HttpMessageHandler handler,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>? capabilityOverrides = null,
        SpendPolicy? spendPolicy = null,
        bool contextGate = true) =>
        new(
            [ProviderSettings.Of("openai-compat", "https://policy.invalid/v1", "secret", transport: handler, alias: "alpha")],
            capabilityOverrides: capabilityOverrides,
            spendPolicy: spendPolicy,
            contextGate: contextGate);

    private static AsyncClient CreateContextRouteClient(
        HttpMessageHandler first,
        HttpMessageHandler alternate,
        HttpMessageHandler ordinary,
        IObserver observer) =>
        new(
            [
                ProviderSettings.Of("openai-compat", "https://policy.invalid/v1", "secret", transport: first, alias: "alpha"),
                ProviderSettings.Of("openai-compat", "https://policy.invalid/v1", "secret", transport: alternate, alias: "beta"),
                ProviderSettings.Of("openai-compat", "https://policy.invalid/v1", "secret", transport: ordinary, alias: "ordinary"),
            ],
            capabilityOverrides: new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>(StringComparer.Ordinal)
            {
                ["alpha"] = new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = JsonSchemaCapabilities() },
                ["beta"] = new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = JsonSchemaCapabilities() },
                ["ordinary"] = new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = JsonSchemaCapabilities() },
            },
            observers: [observer]);

    private static ModelCapabilities JsonSchemaCapabilities() =>
        new(features: new Sourced<Feature>(Feature.JsonSchema, Provenance.Override));

    private static Route ContextRoute() =>
        new(
            ["alpha:model", "ordinary:model"],
            retry: new Retry(MaxAttempts: 1, BackoffBaseS: 0, BackoffMaxS: 0),
            healthGate: false,
            contextWindowTargets: ["beta:model"]);

    private static SchemaSpec Schema() => SchemaSpec.FromJson("{\"type\":\"object\"}");

    private static void AssertModernSchema(byte[] request)
    {
        using var document = System.Text.Json.JsonDocument.Parse(request);
        Assert.Equal("json_schema", document.RootElement.GetProperty("response_format").GetProperty("type").GetString());
    }

    private static async Task<List<AdapterEvent>> Collect(IAsyncEnumerable<AdapterEvent> source)
    {
        var events = new List<AdapterEvent>();
        await foreach (var item in source) events.Add(item);
        return events;
    }

    private static void AssertDisposed(params ScriptHandler[] handlers)
    {
        foreach (var handler in handlers)
        {
            Assert.All(handler.Responses, static response => Assert.True(response.Disposed));
            Assert.All(handler.Contents, static content => Assert.True(content.Disposed));
        }
    }

    private static IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>> Capabilities(ModelCapabilities capabilities) =>
        new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>(StringComparer.Ordinal)
        {
            ["alpha"] = new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = capabilities },
        };

    private sealed class RecordingHandler : HttpMessageHandler
    {
        private int _sends;
        internal int SendCalls => Volatile.Read(ref _sends);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Interlocked.Increment(ref _sends);
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/v1/chat/completions", request.RequestUri!.AbsolutePath);
            return Task.FromResult(Response());
        }
    }

    private static string StructuredResponseText(string answer) =>
        System.Text.Json.JsonSerializer.Serialize(new Dictionary<string, string> { ["answer"] = answer });

    private sealed record ResponseScript(HttpStatusCode Status, string Body, TimeSpan? RetryAfter = null)
    {
        internal static ResponseScript Success(string answer) => new(
            HttpStatusCode.OK,
            System.Text.Json.JsonSerializer.Serialize(new Dictionary<string, object?>
            {
                ["choices"] = new[]
                {
                    new Dictionary<string, object?>
                    {
                        ["message"] = new Dictionary<string, string> { ["content"] = StructuredResponseText(answer) },
                        ["finish_reason"] = "stop",
                    },
                },
                ["usage"] = new Dictionary<string, int>
                {
                    ["prompt_tokens"] = 1,
                    ["completion_tokens"] = 1,
                    ["total_tokens"] = 2,
                },
            }));
    }

    private sealed class ScriptHandler(params ResponseScript[] scripts) : HttpMessageHandler
    {
        private readonly Queue<ResponseScript> _scripts = new(scripts);
        private int _sends;

        internal int SendCalls => Volatile.Read(ref _sends);
        internal List<byte[]> Requests { get; } = [];
        internal List<TrackingResponse> Responses { get; } = [];
        internal List<RecordedContent> Contents { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/v1/chat/completions", request.RequestUri!.AbsolutePath);
            Assert.Equal(string.Empty, request.RequestUri.Query);
            Assert.NotNull(request.Content);
            Requests.Add(await request.Content.ReadAsByteArrayAsync(cancellationToken));
            var script = _scripts.Count == 0
                ? throw new Xunit.Sdk.XunitException("Policy HTTP script exhausted.")
                : _scripts.Dequeue();
            var content = new RecordedContent(Encoding.UTF8.GetBytes(script.Body));
            content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/json");
            var response = new TrackingResponse(script.Status) { Content = content };
            if (script.RetryAfter is { } retryAfter)
            {
                response.Headers.RetryAfter = new System.Net.Http.Headers.RetryConditionHeaderValue(retryAfter);
            }
            Contents.Add(content);
            Responses.Add(response);
            Interlocked.Increment(ref _sends);
            return response;
        }
    }

    private sealed class TrackingResponse(HttpStatusCode status) : HttpResponseMessage(status)
    {
        internal bool Disposed { get; private set; }

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class RecordedContent(byte[] bytes) : HttpContent
    {
        internal bool Disposed { get; private set; }

        protected override bool TryComputeLength(out long length)
        {
            length = bytes.Length;
            return true;
        }

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) =>
            stream.WriteAsync(bytes).AsTask();

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class Collector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent value) => Events.Add(value);
    }

    private sealed class BlockingContentHandler : HttpMessageHandler
    {
        private int _sends;
        internal TaskCompletionSource Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource SecondStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal List<TrackingContent> Contents { get; } = [];
        internal int SendCalls => Volatile.Read(ref _sends);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var call = Interlocked.Increment(ref _sends);
            if (call == 1) Started.TrySetResult(); else SecondStarted.TrySetResult();
            var content = new TrackingContent(Release);
            Contents.Add(content);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content });
        }
    }

    private sealed class TrackingContent : HttpContent
    {
        private readonly TaskCompletionSource _release;
        internal bool Disposed { get; private set; }

        internal TrackingContent(TaskCompletionSource release)
        {
            _release = release;
            Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/json");
        }

        protected override async Task SerializeToStreamAsync(Stream stream, TransportContext? context)
        {
            await _release.Task;
            await stream.WriteAsync(Encoding.UTF8.GetBytes("""{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}"""));
        }

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return false;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }

    private static HttpResponseMessage Response() => new(HttpStatusCode.OK)
    {
        Content = new StringContent(
            """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""",
            Encoding.UTF8,
            "application/json"),
    };
}
