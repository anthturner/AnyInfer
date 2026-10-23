using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;
using JsonProperty = AnyInfer.Json.JsonProperty;

namespace AnyInfer.Tests;

/// <summary>Controls for private OpenAI-compatible dialect spellings and no-listing lifecycle behavior.</summary>
public sealed class CompatDialectTests
{
    [Theory]
    [InlineData("Bearer fixture-token", "bearer")]
    [InlineData("fixture-token", "x-api-key")]
    public async Task Selected_auth_spelling_reaches_models_and_chat(string expected, string spelling)
    {
        var handler = new RecordingHandler(Models(), Chat());
        await using var client = ConfiguredClient(handler, new OpenAICompatDialectOptions(spelling));

        await client.ModelsAsync("dialect");
        await client.GenerateAsync(PublicRequest());

        Assert.Equal(expected, handler.Requests[0].Headers[spelling == "bearer" ? "authorization" : "x-api-key"]);
        Assert.Equal(expected, handler.Requests[1].Headers[spelling == "bearer" ? "authorization" : "x-api-key"]);
    }

    [Fact]
    public async Task Caller_auth_overrides_are_case_insensitive_and_other_auth_header_coexists()
    {
        var handler = new RecordingHandler(Models(), Chat());
        await using var client = ConfiguredClient(handler, new OpenAICompatDialectOptions("bearer"),
            headers: new Dictionary<string, string> { ["AUTHORIZATION"] = "Custom caller", ["x-api-key"] = "other" });

        await client.ModelsAsync("dialect");
        await client.GenerateAsync(PublicRequest());

        foreach (var captured in handler.Requests)
        {
            Assert.Equal("Custom caller", captured.Headers["authorization"]);
            Assert.Equal("other", captured.Headers["x-api-key"]);
        }
    }

    [Fact]
    public async Task X_api_key_override_is_case_insensitive_and_authorization_coexists()
    {
        var handler = new RecordingHandler(Models(), Chat());
        await using var client = ConfiguredClient(handler, new OpenAICompatDialectOptions("x-api-key"),
            headers: new Dictionary<string, string> { ["X-API-KEY"] = "Custom caller", ["authorization"] = "other" });

        await client.ModelsAsync("dialect");
        await client.GenerateAsync(PublicRequest());
        foreach (var captured in handler.Requests)
        {
            Assert.Equal("Custom caller", captured.Headers["x-api-key"]);
            Assert.Equal("other", captured.Headers["authorization"]);
        }
    }

    [Theory]
    [InlineData("bearer")]
    [InlineData("x-api-key")]
    public async Task Keyless_adapter_invents_no_auth_headers_on_get_or_post(string spelling)
    {
        var handler = new RecordingHandler(Models(), Chat());
        await using var client = ConfiguredClient(handler, new OpenAICompatDialectOptions(spelling), apiKey: null);
        await client.ModelsAsync("dialect");
        await client.GenerateAsync(PublicRequest());
        foreach (var captured in handler.Requests)
        {
            Assert.DoesNotContain("authorization", captured.Headers.Keys);
            Assert.DoesNotContain("x-api-key", captured.Headers.Keys);
        }
    }

    [Fact]
    public void Invalid_private_spellings_fail_before_transport()
    {
        Assert.Throws<ArgumentException>(() => new OpenAICompatDialectOptions(authHeader: "Bearer"));
        Assert.Throws<ArgumentException>(() => new OpenAICompatDialectOptions(authHeader: "X-API-KEY"));
        Assert.Throws<ArgumentException>(() => new OpenAICompatDialectOptions(outputTokensField: "completion_tokens"));
    }

    [Fact]
    public void Null_private_fields_fail_and_default_constructor_preserves_generic_defaults()
    {
        Assert.Throws<ArgumentException>(() => new OpenAICompatDialectOptions(authHeader: null!));
        Assert.Throws<ArgumentException>(() => new OpenAICompatDialectOptions(outputTokensField: null!));
        var defaults = new OpenAICompatDialectOptions();
        Assert.Equal("bearer", defaults.AuthHeader);
        Assert.True(defaults.ModelsListing);
        Assert.Equal("max_tokens", defaults.OutputTokensField);
    }

    [Fact]
    public async Task Factory_rejects_explicit_null_dialect_while_constructor_null_uses_defaults()
    {
        var factoryHandler = new RecordingHandler();
        var config = new ProviderConfig(
            ProviderSettings.Of("dialect", "https://dialect.invalid/v1", "fixture-token", transport: factoryHandler),
            "dialect", "fixture-token");
        Assert.Throws<ArgumentNullException>(() => OpenAIChatAdapter.Create(config, null!, CancellationToken.None));
        Assert.Empty(factoryHandler.Requests);

        var constructorHandler = new RecordingHandler(Chat());
        await using var adapter = new OpenAIChatAdapter(new Uri("https://dialect.invalid/v1"), "fixture-token", handler: constructorHandler, dialect: null);
        await Collect(adapter.GenerateAsync(Request()));
        Assert.Equal("Bearer fixture-token", constructorHandler.Requests.Single().Headers["authorization"]);
        Assert.Equal(3, constructorHandler.Requests.Single().Body.RootElement.GetProperty("max_tokens").GetInt32());
    }

    [Fact]
    public async Task Omitted_direct_constructor_and_factory_keep_generic_bearer_and_max_tokens()
    {
        var directHandler = new RecordingHandler(Chat());
        await using (var direct = new OpenAIChatAdapter(new Uri("https://dialect.invalid/v1"), "fixture-token", handler: directHandler))
        {
            await Collect(direct.GenerateAsync(Request()));
        }
        Assert.Equal("Bearer fixture-token", directHandler.Requests.Single().Headers["authorization"]);
        Assert.Equal(3, directHandler.Requests.Single().Body.RootElement.GetProperty("max_tokens").GetInt32());

        var factoryHandler = new RecordingHandler(Chat());
        await using var client = ConfiguredClient(factoryHandler, dialect: null);
        Assert.Equal("ok", (await client.GenerateAsync(new GenerationRequest(
            [new Message("user", [new Text("hello")])], new Route(["dialect:dialect-model"], healthGate: false),
            new Sampling(maxOutputTokens: 3)))).Text);
        Assert.Equal("Bearer fixture-token", factoryHandler.Requests.Single().Headers["authorization"]);
        Assert.Equal(3, factoryHandler.Requests.Single().Body.RootElement.GetProperty("max_tokens").GetInt32());
    }

    [Fact]
    public async Task No_listing_returns_without_http_and_preserves_resolved_caller_identity()
    {
        var handler = new RecordingHandler();
        await using var adapter = Adapter(handler, new OpenAICompatDialectOptions(modelsListing: false));
        Assert.Empty(await adapter.ListModelsAsync());
        Assert.Equal("no cheap readiness probe; failures surface on use", (await adapter.HealthAsync()).Detail);
        Assert.Empty(handler.Requests);

        using var caller = new CancellationTokenSource();
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(caller.Token);
        caller.Cancel();
        using var scope = CancellationIdentityContext.Push(linked.Token, caller.Token);
        var error = await Assert.ThrowsAsync<OperationCanceledException>(() => adapter.ListModelsAsync(linked.Token).AsTask());
        Assert.Equal(caller.Token, error.CancellationToken);
        var healthError = await Assert.ThrowsAsync<OperationCanceledException>(() => adapter.HealthAsync(linked.Token).AsTask());
        Assert.Equal(caller.Token, healthError.CancellationToken);
        Assert.Empty(handler.Requests);
    }

    [Fact]
    public async Task Configured_client_uses_private_factory_for_models_chat_and_owned_transport_cleanup()
    {
        var handler = new RecordingHandler(Models(), Chat());
        var dialect = new OpenAICompatDialectOptions("x-api-key");
        var client = ConfiguredClient(handler, dialect);
        try
        {
            Assert.Empty(await client.ModelsAsync("dialect"));
            var result = await client.GenerateAsync(new GenerationRequest(
                [new Message("user", [new Text("hello")])], new Route(["dialect:dialect-model"], healthGate: false),
                new Sampling(maxOutputTokens: 7)));
            Assert.Equal("ok", result.Text);
            Assert.Equal("fixture-token", handler.Requests[0].Headers["x-api-key"]);
            Assert.Equal("fixture-token", handler.Requests[1].Headers["x-api-key"]);
        }
        finally
        {
            await client.DisposeAsync();
        }
        Assert.Equal(1, handler.DisposeCalls);
    }

    [Fact]
    public async Task Configured_no_listing_success_returns_models_and_health_without_http_then_disposes_once()
    {
        var handler = new RecordingHandler();
        var client = ConfiguredClient(handler, new OpenAICompatDialectOptions(modelsListing: false));
        try
        {
            Assert.Empty(await client.ModelsAsync("dialect"));
            var health = await client.HealthAsync("dialect");
            Assert.True(health.Ok);
            Assert.Equal("no cheap readiness probe; failures surface on use", health.Detail);
            Assert.Empty(handler.Requests);
        }
        finally
        {
            await client.DisposeAsync();
        }
        Assert.Equal(1, handler.DisposeCalls);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Configured_no_listing_cancellation_at_adapter_entry_preserves_original_caller_token(bool health)
    {
        using var caller = new CancellationTokenSource();
        var handler = new RecordingHandler();
        var client = ConfiguredClient(handler, new OpenAICompatDialectOptions(modelsListing: false),
            config => new CancelAtLifecycleEntry((OpenAIChatAdapter)OpenAIChatAdapter.Create(config, new OpenAICompatDialectOptions(modelsListing: false), CancellationToken.None), caller));
        try
        {
            OperationCanceledException exception;
            if (health)
            {
                exception = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => client.HealthAsync("dialect", caller.Token));
            }
            else
            {
                exception = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => client.ModelsAsync("dialect", cancellationToken: caller.Token));
            }
            Assert.Equal(caller.Token, exception.CancellationToken);
            Assert.Empty(handler.Requests);
        }
        finally
        {
            await client.DisposeAsync();
        }
    }

    [Fact]
    public async Task No_listing_refuses_after_disposal_before_constructing_lifecycle_answers()
    {
        var handler = new RecordingHandler();
        var adapter = Adapter(handler, new OpenAICompatDialectOptions(modelsListing: false));
        await adapter.DisposeAsync();
        await Assert.ThrowsAsync<ObjectDisposedException>(() => adapter.ListModelsAsync().AsTask());
        await Assert.ThrowsAsync<ObjectDisposedException>(() => adapter.HealthAsync().AsTask());
        Assert.Empty(handler.Requests);
        Assert.Equal(1, handler.DisposeCalls);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Alternate_output_key_renames_final_overlay_without_mutating_wire_input(bool stream)
    {
        var options = new JsonObject([
            new JsonProperty("max_completion_tokens", new JsonInteger(1)),
            new JsonProperty("max_tokens", new JsonInteger(9)),
        ]);
        var handler = new RecordingHandler(stream ? SseChat() : Chat());
        await using var client = ConfiguredClient(handler, new OpenAICompatDialectOptions(outputTokensField: "max_completion_tokens"));
        var request = PublicRequest(stream, options);

        await client.GenerateAsync(request);

        var body = handler.Requests.Single().Body.RootElement;
        Assert.False(body.TryGetProperty("max_tokens", out _));
        Assert.Equal(9, body.GetProperty("max_completion_tokens").GetInt32());
        Assert.True(request.ProviderOptions["dialect"].TryGetValue("max_tokens", out var original));
        Assert.Equal(new JsonInteger(9), original);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Alternate_output_key_observes_each_final_overlay_case(bool stream)
    {
        var cases = new (JsonObject? Options, int? Sampling, string? ExpectedName, JsonValue? ExpectedValue)[]
        {
            (null, 3, "max_completion_tokens", new JsonInteger(3)),
            (new JsonObject([new JsonProperty("max_tokens", new JsonInteger(9))]), 3, "max_completion_tokens", new JsonInteger(9)),
            (new JsonObject([new JsonProperty("max_completion_tokens", new JsonInteger(1)), new JsonProperty("max_tokens", new JsonInteger(9))]), 3, "max_completion_tokens", new JsonInteger(9)),
            (new JsonObject([new JsonProperty("max_completion_tokens", new JsonInteger(1))]), null, "max_completion_tokens", new JsonInteger(1)),
            (null, null, null, null),
            (new JsonObject([new JsonProperty("max_tokens", JsonNull.Instance)]), null, "max_completion_tokens", JsonNull.Instance),
            (new JsonObject([new JsonProperty("max_tokens", new JsonString("tagged"))]), null, "max_completion_tokens", new JsonString("tagged")),
        };
        foreach (var item in cases)
        {
            var handler = new RecordingHandler(stream ? SseChat() : Chat());
            await using var client = ConfiguredClient(handler, new OpenAICompatDialectOptions(outputTokensField: "max_completion_tokens"));
            await client.GenerateAsync(PublicRequest(stream, item.Options, item.Sampling));
            var body = handler.Requests.Single().Body.RootElement;
            Assert.False(body.TryGetProperty("max_tokens", out _));
            if (item.ExpectedName is null)
            {
                Assert.False(body.TryGetProperty("max_completion_tokens", out _));
                continue;
            }
            Assert.True(body.TryGetProperty(item.ExpectedName, out var observed));
            Assert.Equal(JsonWriter.Write(item.ExpectedValue!), observed.GetRawText());
        }
    }

    private static OpenAIChatAdapter Adapter(RecordingHandler handler, OpenAICompatDialectOptions dialect) =>
        new(new Uri("https://dialect.invalid/v1"), "fixture-token", handler: handler, dialect: dialect);

    private static WireRequest Request(bool stream = false, JsonObject? options = null, int? maxTokens = 3) =>
        new("dialect-model", [new Message("user", [new Text("hello")])], new Sampling(maxOutputTokens: maxTokens), stream: stream,
            extraOptions: options);

    private static GenerationRequest PublicRequest(bool stream = false, JsonObject? options = null, int? maxTokens = 3) =>
        new([new Message("user", [new Text("hello")])], new Route(["dialect:dialect-model"], healthGate: false),
            new Sampling(maxOutputTokens: maxTokens), stream: stream,
            providerOptions: options is null ? null : new Dictionary<string, JsonObject> { ["dialect"] = options });

    private static AsyncClient ConfiguredClient(
        RecordingHandler handler,
        OpenAICompatDialectOptions? dialect,
        Func<ProviderConfig, IAsyncDisposable>? factory = null,
        IReadOnlyDictionary<string, string>? headers = null,
        string? apiKey = "fixture-token")
    {
        var descriptor = new ProviderDescriptor("dialect", "Dialect", (config, token) =>
            ValueTask.FromResult(factory?.Invoke(config) ?? (IAsyncDisposable)(dialect is null
                ? OpenAIChatAdapter.Create(config, token)
                : OpenAIChatAdapter.Create(config, dialect, token))));
        return new AsyncClient(
            [ProviderSettings.Of("dialect", "https://dialect.invalid/v1", apiKey, headers: headers, transport: handler)],
            new ProviderRegistry([descriptor]));
    }

    private static HttpResponseMessage Models() => new(HttpStatusCode.OK) { Content = new StringContent("{\"data\":[]}", Encoding.UTF8, "application/json") };
    private static HttpResponseMessage Chat() => new(HttpStatusCode.OK) { Content = new StringContent("{\"choices\":[{\"message\":{\"content\":\"ok\"},\"finish_reason\":\"stop\"}]}", Encoding.UTF8, "application/json") };
    private static HttpResponseMessage SseChat() => new(HttpStatusCode.OK) { Content = new StringContent("data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\ndata: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n", Encoding.UTF8, "text/event-stream") };

    private static async Task Collect(IAsyncEnumerable<AdapterEvent> events)
    {
        await foreach (var _ in events) { }
    }

    private sealed class RecordingHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);
        internal List<CapturedRequest> Requests { get; } = [];
        internal int DisposeCalls { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var headers = request.Headers.Concat(request.Content!.Headers)
                .ToDictionary(static pair => pair.Key.ToLowerInvariant(), static pair => string.Join(",", pair.Value), StringComparer.Ordinal);
            var content = await request.Content.ReadAsStringAsync(cancellationToken);
            var body = JsonDocument.Parse(string.IsNullOrWhiteSpace(content) ? "{}" : content);
            Requests.Add(new CapturedRequest(headers, body));
            return _responses.Dequeue();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) DisposeCalls++;
            base.Dispose(disposing);
        }
    }

    private sealed class CancelAtLifecycleEntry(OpenAIChatAdapter inner, CancellationTokenSource caller) : IProviderAdapter, IProviderLifecycle
    {
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => inner.GenerateAsync(request, cancellationToken);
        public ValueTask DisposeAsync() => inner.DisposeAsync();
        public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default)
        {
            caller.Cancel();
            return inner.ListModelsAsync(cancellationToken);
        }
        public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default)
        {
            caller.Cancel();
            return inner.HealthAsync(cancellationToken);
        }
    }

    private sealed record CapturedRequest(IReadOnlyDictionary<string, string> Headers, JsonDocument Body);
}
