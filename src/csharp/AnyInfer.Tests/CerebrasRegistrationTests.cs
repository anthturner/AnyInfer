using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Credentials;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Routing;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Offline controls for the one reviewed native compatibility-preset admission.</summary>
public sealed class CerebrasRegistrationTests
{
    [Fact]
    public void Default_registry_admits_only_the_reviewed_generated_cerebras_descriptor()
    {
        var registry = ProviderRegistry.CreateDefault();
        var descriptor = registry.Get("cerebras");
        var generated = CompatPresetTable.Rows.Single(row => row.Source.Id == "cerebras");

        Assert.Same(generated.Generation.Descriptor, descriptor);
        Assert.Equal(["cerebras", "jina", "openai-compat", "tei", "voyage"], registry.Descriptors.Select(static item => item.Id));
        Assert.Equal(8, registry.Descriptors.Sum(static item => item.Operations.Count));
        Assert.Empty(descriptor.Aliases);
        Assert.Equal("Cerebras Inference", descriptor.DisplayName);
        Assert.Equal("https://api.cerebras.ai/v1", descriptor.DefaultBaseUrl);
        Assert.False(descriptor.RequiresBaseUrl);
        Assert.True(descriptor.PoolOwnsConfiguredTransport);
        Assert.Equal([InferenceOperation.Generation], descriptor.Operations);
        Assert.Equal(["generation"], generated.Source.SourceOperations);
        Assert.Empty(generated.PendingNativeParity);
        Assert.Equal("CEREBRAS_API_KEY", descriptor.Setup.Fields.Single(field => field.Key == "api_key").EnvVar);
        Assert.Equal("bearer", generated.Generation.Dialect.AuthHeader);
        Assert.Equal("max_tokens", generated.Generation.Dialect.OutputTokensField);
        Assert.Equal(CompatPresetReasoningStyle.EffortMinLow, generated.Generation.ReasoningStyle);

        foreach (var row in CompatPresetTable.Rows.Where(static row => row.Source.Id != "cerebras"))
        {
            Assert.False(registry.Has(row.Source.Id));
            Assert.All(row.Generation.Descriptor.Aliases, alias => Assert.False(registry.Has(alias)));
        }
        Assert.Throws<ConfigException>(() => registry.ResolveId("reka"));
    }

    [Fact]
    public async Task Default_public_factory_projects_buffered_streaming_reasoning_tools_and_schema()
    {
        var handler = new ScriptedHandler(
            JsonResponse("""{"choices":[{"message":{"content":"{\"answer\":\"ok\"}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}"""),
            SseResponse("""{"choices":[{"delta":{"content":"stream"}}]}""", """{"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":5,"total_tokens":9}}""", """{"choices":[{"delta":{},"finish_reason":"stop"}]}""", "[DONE]"));
        await using var client = Client(handler);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var schema = SchemaSpec.FromJson("""{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}""");
        var tool = new ToolSpec("lookup", "Look up a value", Assert.IsType<JsonObject>(JsonReader.ReadModern("""{"type":"object","properties":{"query":{"type":"string"}}}""")));

        var buffered = await client.GenerateAsync("hello", target: "cerebras:model", sampling: new Sampling(maxOutputTokens: 7), schema: schema, tools: [tool], reasoning: "minimal", cancellationToken: deadline.Token);
        Assert.Equal("{\"answer\":\"ok\"}", buffered.Text);
        Assert.Equal(2, buffered.Usage!.InputTokens);
        Assert.Equal(3, buffered.Usage.OutputTokens);

        var streaming = await client.GenerateAsync(new GenerationRequest(
            [Message.User("hello")],
            new Route(["cerebras:model"]),
            reasoning: "none",
            stream: true), cancellationToken: deadline.Token);
        Assert.Equal("stream", streaming.Text);
        Assert.Equal(9, streaming.Usage!.TotalTokens);

        Assert.Equal(2, handler.Requests.Count);
        var first = handler.Requests[0].Body!.RootElement;
        Assert.Equal("Bearer fixture-key", handler.Requests[0].Headers["authorization"]);
        Assert.Equal("model", first.GetProperty("model").GetString());
        Assert.Equal("low", first.GetProperty("reasoning_effort").GetString());
        Assert.False(first.TryGetProperty("response_format", out _));
        Assert.Contains(first.GetProperty("messages").EnumerateArray(), message =>
            message.GetProperty("content").GetString()!.Contains("JSON Schema", StringComparison.Ordinal));
        Assert.Equal("lookup", first.GetProperty("tools")[0].GetProperty("function").GetProperty("name").GetString());
        Assert.Equal(7, first.GetProperty("max_tokens").GetInt32());
        Assert.False(first.TryGetProperty("max_completion_tokens", out _));
        var second = handler.Requests[1].Body!.RootElement;
        Assert.True(second.GetProperty("stream").GetBoolean());
        Assert.True(second.GetProperty("stream_options").GetProperty("include_usage").GetBoolean());
        Assert.False(second.TryGetProperty("reasoning_effort", out _));
    }

    [Fact]
    public async Task Default_factory_lists_health_checks_and_classifies_errors_and_size_limits()
    {
        var handler = new ScriptedHandler(
            JsonResponse("""{"object":"list","data":[{"id":"model-a"}]}"""),
            JsonResponse("""{"object":"list","data":[{"id":"model-a"}]}"""),
            JsonResponse("""{"error":{"message":"bad key"}}""", HttpStatusCode.Unauthorized),
            JsonResponse(new string('x', 512)));
        await using var client = Client(handler);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        Assert.Equal("model-a", (await client.ModelsAsync("cerebras", cancellationToken: deadline.Token)).Single().Id);
        Assert.True((await client.HealthAsync("cerebras", deadline.Token)).Ok);
        Assert.Equal(2, handler.Requests.Count);
        Assert.All(handler.Requests, request =>
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Equal("api.cerebras.ai", request.Uri.Host);
            Assert.Equal("/v1/models", request.Uri.AbsolutePath);
            Assert.Equal("Bearer fixture-key", request.Headers["authorization"]);
            Assert.Null(request.Body);
        });
        await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync("not-supported", target: "cerebras:model", cancellationToken: deadline.Token));
        Assert.Equal(2, handler.Requests.Count);
        var auth = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("bad", target: "cerebras:model", cancellationToken: deadline.Token));
        var authAttempt = Assert.Single(auth.Attempts);
        Assert.Equal("auth", authAttempt.Error!.Category);
        Assert.Equal(401, authAttempt.Error.HttpStatus);
        var oversize = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("large", target: "cerebras:model", maxResponseBytes: 32, cancellationToken: deadline.Token));
        Assert.Equal("stream_protocol", Assert.Single(oversize.Attempts).Error!.Category);
    }

    [Fact]
    public async Task Default_factory_is_lazy_cancellable_and_disposes_borrowed_handler_once()
    {
        var handler = new BlockingHandler();
        var resolver = new RecordingResolver("env://CEREBRAS_TEST_KEY", "resolved-fixture-key");
        var client = Client(handler, "env://CEREBRAS_TEST_KEY", new ResolverChain([resolver]));
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        using var caller = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token);
        try
        {
            Assert.Equal(0, resolver.ResolveCalls);
            var pending = client.GenerateAsync("wait", target: "cerebras:model", cancellationToken: caller.Token);
            await handler.Entered.Task.WaitAsync(deadline.Token);
            Assert.Equal(1, resolver.ResolveCalls);
            caller.Cancel();
            var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            Assert.Equal(caller.Token, cancelled.CancellationToken);
        }
        finally
        {
            handler.Release.TrySetResult();
            await client.DisposeAsync().AsTask().WaitAsync(deadline.Token);
        }
        Assert.Equal(1, handler.DisposeCalls);
    }

    private static AsyncClient Client(HttpMessageHandler handler, string apiKey = "fixture-key", ResolverChain? resolver = null) => new(
        [ProviderSettings.Of("cerebras", apiKey: apiKey, transport: handler)], ProviderRegistry.CreateDefault(), resolver, contextGate: false);

    private static HttpResponseMessage JsonResponse(string value, HttpStatusCode status = HttpStatusCode.OK) => new(status)
    {
        Content = new StringContent(value, Encoding.UTF8, "application/json"),
    };

    private static HttpResponseMessage SseResponse(params string[] frames) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(string.Concat(frames.Select(static frame => "data: " + frame + "\n\n")), Encoding.UTF8, "text/event-stream"),
    };

    private sealed record CapturedRequest(HttpMethod Method, Uri Uri, IReadOnlyDictionary<string, string> Headers, JsonDocument? Body);

    private sealed class ScriptedHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);
        internal List<CapturedRequest> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var contentHeaders = request.Content is null
                ? Enumerable.Empty<KeyValuePair<string, IEnumerable<string>>>()
                : request.Content.Headers;
            var headers = request.Headers.Concat(contentHeaders).ToDictionary(static pair => pair.Key.ToLowerInvariant(), static pair => string.Join(",", pair.Value), StringComparer.Ordinal);
            var bytes = request.Content is null
                ? Array.Empty<byte>()
                : await request.Content.ReadAsByteArrayAsync(cancellationToken);
            Requests.Add(new CapturedRequest(request.Method, request.RequestUri!, headers,
                bytes.Length == 0 ? null : JsonDocument.Parse(bytes)));
            return _responses.Dequeue();
        }
    }

    private sealed class BlockingHandler : HttpMessageHandler
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int DisposeCalls { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Entered.TrySetResult();
            await Release.Task.WaitAsync(cancellationToken);
            return JsonResponse("""{"choices":[{"message":{"content":"late"},"finish_reason":"stop"}]}""");
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) DisposeCalls++;
            base.Dispose(disposing);
        }
    }

    private sealed class RecordingResolver(string reference, string value) : ICredentialResolver
    {
        internal int ResolveCalls { get; private set; }

        public bool Handles(string candidate) => string.Equals(reference, candidate, StringComparison.Ordinal);

        public ValueTask<string> ResolveAsync(string candidate, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Assert.Equal(reference, candidate);
            ResolveCalls++;
            return ValueTask.FromResult(value);
        }
    }
}
