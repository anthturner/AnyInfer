using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Credentials;
using AnyInfer.Providers;
using AnyInfer.Routing;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Offline public-factory controls for the reviewed Hyperbolic registration.</summary>
public sealed class HyperbolicRegistrationTests
{
    [Fact]
    public void Default_registry_admits_only_the_reviewed_generated_hyperbolic_descriptor()
    {
        var registry = ProviderRegistry.CreateDefault();
        var descriptor = registry.Get("hyperbolic");
        var generated = CompatPresetTable.Rows.Single(row => row.Source.Id == "hyperbolic");

        Assert.Same(generated.Generation.Descriptor, descriptor);
        Assert.Equal(["cerebras", "hyperbolic", "jina", "openai-compat", "tei", "voyage"], registry.Descriptors.Select(static item => item.Id));
        Assert.Equal(9, registry.Descriptors.Sum(static item => item.Operations.Count));
        Assert.Empty(descriptor.Aliases);
        Assert.Equal("Hyperbolic", descriptor.DisplayName);
        Assert.Equal("https://api.hyperbolic.ai/inference/v1", descriptor.DefaultBaseUrl);
        Assert.False(descriptor.RequiresBaseUrl);
        Assert.Equal([InferenceOperation.Generation], descriptor.Operations);
        Assert.Equal(["generation"], generated.Source.SourceOperations);
        Assert.Empty(generated.PendingNativeParity);
        Assert.Equal("HYPERBOLIC_API_KEY", descriptor.Setup.Fields.Single(field => field.Key == "api_key").EnvVar);
        Assert.Equal("bearer", generated.Generation.Dialect.AuthHeader);
        Assert.Equal("max_tokens", generated.Generation.Dialect.OutputTokensField);

        foreach (var row in CompatPresetTable.Rows.Where(static row => row.Source.Id is not "cerebras" and not "hyperbolic"))
        {
            Assert.False(registry.Has(row.Source.Id));
            Assert.All(row.Generation.Descriptor.Aliases, alias => Assert.False(registry.Has(alias)));
        }
    }

    [Fact]
    public async Task Default_factory_projects_buffered_and_streamed_chat_with_reported_usage()
    {
        var handler = new ScriptedHandler(
            Json("""{"choices":[{"message":{"content":"buffered"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}"""),
            Sse("""{"choices":[{"delta":{"content":"stream"}}]}""", """{"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":5,"total_tokens":9}}""", """{"choices":[{"delta":{},"finish_reason":"stop"}]}""", "[DONE]"));
        await using var client = Client(handler);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        var buffered = await client.GenerateAsync("hello", target: "hyperbolic:glm-5.3-flash", sampling: new Sampling(maxOutputTokens: 7), reasoning: "low", cancellationToken: deadline.Token);
        var streamed = await client.GenerateAsync(new GenerationRequest([Message.User("hello")], new Route(["hyperbolic:glm-5.3-flash"]), new Sampling(maxOutputTokens: 7), reasoning: "low", stream: true), deadline.Token);

        Assert.Equal("buffered", buffered.Text);
        Assert.Equal(5, buffered.Usage!.TotalTokens);
        Assert.Equal("stream", streamed.Text);
        Assert.Equal(9, streamed.Usage!.TotalTokens);
        Assert.Equal(2, handler.Requests.Count);
        foreach (var request in handler.Requests)
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("api.hyperbolic.ai", request.Uri.Host);
            Assert.Equal("/inference/v1/chat/completions", request.Uri.AbsolutePath);
            Assert.Equal("Bearer fixture-key", request.Headers["authorization"]);
            Assert.Equal(7, request.Body!.RootElement.GetProperty("max_tokens").GetInt32());
            Assert.False(request.Body.RootElement.TryGetProperty("max_completion_tokens", out _));
            Assert.False(request.Body.RootElement.TryGetProperty("reasoning_effort", out _));
        }
        Assert.True(handler.Requests[1].Body!.RootElement.GetProperty("stream_options").GetProperty("include_usage").GetBoolean());
    }

    [Fact]
    public async Task Default_factory_lists_and_health_checks_without_body_then_keeps_retrieval_and_errors_local()
    {
        var handler = new ScriptedHandler(Json("""{"object":"list","data":[{"id":"glm-5.3-flash"}]}"""), Json("""{"object":"list","data":[{"id":"glm-5.3-flash"}]}"""), Json("""{"error":{"message":"bad key"}}""", HttpStatusCode.Unauthorized), Json(new string('x', 512)));
        await using var client = Client(handler);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        Assert.Equal("glm-5.3-flash", (await client.ModelsAsync("hyperbolic", cancellationToken: deadline.Token)).Single().Id);
        Assert.True((await client.HealthAsync("hyperbolic", deadline.Token)).Ok);
        Assert.Equal(2, handler.Requests.Count);
        Assert.All(handler.Requests, request =>
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Equal("https", request.Uri.Scheme);
            Assert.Equal("api.hyperbolic.ai", request.Uri.Host);
            Assert.Equal("/inference/v1/models", request.Uri.AbsolutePath);
            Assert.Equal("Bearer fixture-key", request.Headers["authorization"]);
            Assert.Null(request.Body);
        });
        await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync("unsupported", target: "hyperbolic:glm-5.3-flash", cancellationToken: deadline.Token));
        Assert.Equal(2, handler.Requests.Count);
        var auth = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("bad", target: "hyperbolic:glm-5.3-flash", cancellationToken: deadline.Token));
        Assert.Equal("auth", Assert.Single(auth.Attempts).Error!.Category);
        var oversize = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("large", target: "hyperbolic:glm-5.3-flash", maxResponseBytes: 32, cancellationToken: deadline.Token));
        Assert.Equal("stream_protocol", Assert.Single(oversize.Attempts).Error!.Category);
    }

    [Fact]
    public async Task Default_factory_resolves_lazily_and_preserves_caller_cancellation_and_handler_ownership()
    {
        var handler = new BlockingHandler();
        var resolver = new Resolver("env://HYPERBOLIC_TEST_KEY", "resolved-key");
        var client = Client(handler, "env://HYPERBOLIC_TEST_KEY", new ResolverChain([resolver]));
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        using var caller = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token);
        try
        {
            Assert.Equal(0, resolver.Calls);
            var pending = client.GenerateAsync("wait", target: "hyperbolic:glm-5.3-flash", cancellationToken: caller.Token);
            await handler.Entered.Task.WaitAsync(deadline.Token);
            Assert.Equal(1, resolver.Calls);
            caller.Cancel();
            Assert.Equal(caller.Token, (await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending)).CancellationToken);
        }
        finally { handler.Release.TrySetResult(); await client.DisposeAsync().AsTask().WaitAsync(deadline.Token); }
        Assert.Equal(1, handler.DisposeCalls);
    }

    private static AsyncClient Client(HttpMessageHandler handler, string key = "fixture-key", ResolverChain? resolver = null) => new([ProviderSettings.Of("hyperbolic", apiKey: key, transport: handler)], ProviderRegistry.CreateDefault(), resolver, contextGate: false);
    private static HttpResponseMessage Json(string value, HttpStatusCode status = HttpStatusCode.OK) => new(status) { Content = new StringContent(value, Encoding.UTF8, "application/json") };
    private static HttpResponseMessage Sse(params string[] values) => new(HttpStatusCode.OK) { Content = new StringContent(string.Concat(values.Select(static value => "data: " + value + "\n\n")), Encoding.UTF8, "text/event-stream") };
    private sealed record Request(HttpMethod Method, Uri Uri, IReadOnlyDictionary<string, string> Headers, JsonDocument? Body);
    private sealed class ScriptedHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);
        internal List<Request> Requests { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            var contentHeaders = request.Content is null ? Enumerable.Empty<KeyValuePair<string, IEnumerable<string>>>() : request.Content.Headers;
            var headers = request.Headers.Concat(contentHeaders).ToDictionary(static pair => pair.Key.ToLowerInvariant(), static pair => string.Join(",", pair.Value), StringComparer.Ordinal);
            var bytes = request.Content is null ? Array.Empty<byte>() : await request.Content.ReadAsByteArrayAsync(token);
            Requests.Add(new(request.Method, request.RequestUri!, headers, bytes.Length == 0 ? null : JsonDocument.Parse(bytes)));
            return _responses.Dequeue();
        }
    }
    private sealed class BlockingHandler : HttpMessageHandler
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously); internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously); internal int DisposeCalls { get; private set; }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) { Entered.TrySetResult(); await Release.Task.WaitAsync(token); return Json("""{"choices":[{"message":{"content":"late"},"finish_reason":"stop"}]}"""); }
        protected override void Dispose(bool disposing) { if (disposing) DisposeCalls++; base.Dispose(disposing); }
    }
    private sealed class Resolver(string reference, string value) : ICredentialResolver
    { internal int Calls { get; private set; } public bool Handles(string candidate) => candidate == reference; public ValueTask<string> ResolveAsync(string candidate, CancellationToken token = default) { token.ThrowIfCancellationRequested(); Assert.Equal(reference, candidate); Calls++; return ValueTask.FromResult(value); } }
}
