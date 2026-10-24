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

/// <summary>Offline public-factory controls for the reviewed Nscale compatibility-preset admission.</summary>
public sealed class NscaleRegistrationTests
{
    [Fact]
    public void Default_registry_admits_only_the_reviewed_generated_nscale_descriptor()
    {
        var registry = ProviderRegistry.CreateDefault();
        var descriptor = registry.Get("nscale");
        var generated = CompatPresetTable.Rows.Single(row => row.Source.Id == "nscale");

        Assert.Same(generated.Generation.Descriptor, descriptor);
        Assert.Equal(["cerebras", "hyperbolic", "jina", "nscale", "openai-compat", "tei", "voyage"], registry.Descriptors.Select(static item => item.Id));
        Assert.Equal(10, registry.Descriptors.Sum(static item => item.Operations.Count));
        Assert.Empty(descriptor.Aliases);
        Assert.Equal("Nscale", descriptor.DisplayName);
        Assert.Equal("https://inference.api.nscale.com/v1", descriptor.DefaultBaseUrl);
        Assert.False(descriptor.RequiresBaseUrl);
        Assert.True(descriptor.PoolOwnsConfiguredTransport);
        Assert.Equal([InferenceOperation.Generation], descriptor.Operations);
        Assert.Equal(["generation"], generated.Source.SourceOperations);
        Assert.Equal(["contracts/openai-compat-presets.md", "contracts/openai-compat-presets.md#nscale", "contracts/openai-compat.md"], generated.Source.ContractDependencies);
        Assert.Empty(generated.PendingNativeParity);
        Assert.Equal("NSCALE_API_KEY", descriptor.Setup.Fields.Single(field => field.Key == "api_key").EnvVar);
        Assert.Equal("bearer", generated.Generation.Dialect.AuthHeader);
        Assert.True(generated.Generation.Dialect.ModelsListing);
        Assert.Equal("max_tokens", generated.Generation.Dialect.OutputTokensField);
        Assert.Equal(CompatPresetReasoningStyle.Effort, generated.Generation.ReasoningStyle);
        Assert.Equal(Feature.Reasoning | Feature.Streaming | Feature.SystemPrompt | Feature.Tools, descriptor.DefaultCapabilities.Features!.Value);
        Assert.Equal(Provenance.Default, descriptor.DefaultCapabilities.Features.Provenance);

        foreach (var row in CompatPresetTable.Rows.Where(static row => row.Source.Id is not "cerebras" and not "hyperbolic" and not "nscale"))
        {
            Assert.False(registry.Has(row.Source.Id));
            Assert.All(row.Generation.Descriptor.Aliases, alias => Assert.False(registry.Has(alias)));
        }
    }

    [Fact]
    public async Task Default_factory_lists_health_checks_and_keeps_unsupported_retrieval_local()
    {
        var handler = new ScriptedHandler(
            JsonResponse("""{"object":"list","data":[{"id":"meta-llama/Llama-3.1-8B-Instruct"}]}"""),
            JsonResponse("""{"object":"list","data":[{"id":"meta-llama/Llama-3.1-8B-Instruct"}]}"""));
        await using var client = Client(handler);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        Assert.Equal("meta-llama/Llama-3.1-8B-Instruct", (await client.ModelsAsync("nscale", cancellationToken: deadline.Token)).Single().Id);
        Assert.True((await client.HealthAsync("nscale", deadline.Token)).Ok);
        Assert.All(handler.Requests, request =>
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Equal("https", request.Uri.Scheme);
            Assert.Equal("inference.api.nscale.com", request.Uri.Host);
            Assert.Equal("/v1/models", request.Uri.AbsolutePath);
            Assert.Equal("Bearer fixture-key", request.Headers["authorization"]);
            Assert.Null(request.Body);
        });
        await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync("unsupported", target: "nscale:model", cancellationToken: deadline.Token));
        Assert.Equal(2, handler.Requests.Count);
    }

    [Fact]
    public async Task Default_factory_projects_buffered_and_clean_eof_streams_with_usage_semantics()
    {
        var handler = new ScriptedHandler(
            JsonResponse("""{"choices":[{"message":{"content":"buffered"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}"""),
            SseResponse("""{"choices":[{"delta":{"content":"stream"}}]}""", """{"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":5,"total_tokens":9}}""", """{"choices":[{"delta":{},"finish_reason":"stop"}]}"""),
            SseResponse("""{"choices":[{"delta":{"content":"unknown"},"finish_reason":"stop"}]}"""));
        await using var client = Client(handler);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var tool = new ToolSpec("lookup", "Look up a value", Assert.IsType<JsonObject>(JsonReader.ReadModern("""{"type":"object","properties":{"query":{"type":"string"}}}""")));

        var buffered = await client.GenerateAsync("hello", target: "nscale:model", sampling: new Sampling(maxOutputTokens: 7), reasoning: "medium", tools: [tool], cancellationToken: deadline.Token);
        var streamed = await client.GenerateAsync(new GenerationRequest([Message.User("hello")], new Route(["nscale:model"]), stream: true), deadline.Token);
        var absentUsage = await client.GenerateAsync(new GenerationRequest([Message.User("hello")], new Route(["nscale:model"]), stream: true), deadline.Token);

        Assert.Equal("buffered", buffered.Text);
        Assert.Equal(5, buffered.Usage!.TotalTokens);
        Assert.Equal("stream", streamed.Text);
        Assert.Equal(9, streamed.Usage!.TotalTokens);
        Assert.Equal("unknown", absentUsage.Text);
        Assert.Null(absentUsage.Usage);
        Assert.Equal(3, handler.Requests.Count);
        var first = handler.Requests[0].Body!.RootElement;
        Assert.Equal("model", first.GetProperty("model").GetString());
        Assert.Equal(7, first.GetProperty("max_tokens").GetInt32());
        Assert.False(first.TryGetProperty("max_completion_tokens", out _));
        Assert.Equal("medium", first.GetProperty("reasoning_effort").GetString());
        Assert.Equal("auto", first.GetProperty("tool_choice").GetString());
        Assert.Equal("lookup", first.GetProperty("tools")[0].GetProperty("function").GetProperty("name").GetString());
        foreach (var request in handler.Requests.Skip(1))
        {
            Assert.True(request.Body!.RootElement.GetProperty("stream").GetBoolean());
            Assert.True(request.Body.RootElement.GetProperty("stream_options").GetProperty("include_usage").GetBoolean());
        }
    }

    [Fact]
    public async Task Default_factory_classifies_auth_size_and_lifetime_controls()
    {
        var handler = new ScriptedHandler(
            JsonResponse("""{"error":{"message":"bad key"}}""", HttpStatusCode.Unauthorized),
            JsonResponse(new string('x', 512)));
        var resolver = new RecordingResolver("env://NSCALE_TEST_KEY", "resolved-fixture-key");
        var client = Client(handler, "env://NSCALE_TEST_KEY", new ResolverChain([resolver]));
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        try
        {
            Assert.Equal(0, resolver.ResolveCalls);
            var auth = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("bad", target: "nscale:model", cancellationToken: deadline.Token));
            Assert.Equal(1, resolver.ResolveCalls);
            var authAttempt = Assert.Single(auth.Attempts);
            Assert.Equal("auth", authAttempt.Error!.Category);
            Assert.Equal(401, authAttempt.Error.HttpStatus);
            var oversize = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("large", target: "nscale:model", maxResponseBytes: 32, cancellationToken: deadline.Token));
            Assert.Equal("stream_protocol", Assert.Single(oversize.Attempts).Error!.Category);
        }
        finally { await client.DisposeAsync().AsTask().WaitAsync(deadline.Token); }
        Assert.Equal(1, handler.DisposeCalls);
    }

    [Fact]
    public async Task Default_factory_preserves_caller_cancellation_and_borrowed_handler_ownership()
    {
        var handler = new BlockingHandler();
        var resolver = new RecordingResolver("env://NSCALE_TEST_KEY", "resolved-fixture-key");
        var client = Client(handler, "env://NSCALE_TEST_KEY", new ResolverChain([resolver]));
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        using var caller = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token);
        try
        {
            Assert.Equal(0, resolver.ResolveCalls);
            var pending = client.GenerateAsync("wait", target: "nscale:model", cancellationToken: caller.Token);
            await handler.Entered.Task.WaitAsync(deadline.Token);
            Assert.Equal(1, resolver.ResolveCalls);
            caller.Cancel();
            Assert.Equal(caller.Token, (await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending)).CancellationToken);
        }
        finally
        {
            handler.Release.TrySetResult();
            await client.DisposeAsync().AsTask().WaitAsync(deadline.Token);
        }
        Assert.Equal(1, handler.DisposeCalls);
    }

    private static AsyncClient Client(HttpMessageHandler handler, string key = "fixture-key", ResolverChain? resolver = null) => new(
        [ProviderSettings.Of("nscale", apiKey: key, transport: handler)], ProviderRegistry.CreateDefault(), resolver, contextGate: false);

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
        internal int DisposeCalls { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var contentHeaders = request.Content is null ? Enumerable.Empty<KeyValuePair<string, IEnumerable<string>>>() : request.Content.Headers;
            var headers = request.Headers.Concat(contentHeaders).ToDictionary(static pair => pair.Key.ToLowerInvariant(), static pair => string.Join(",", pair.Value), StringComparer.Ordinal);
            var bytes = request.Content is null ? Array.Empty<byte>() : await request.Content.ReadAsByteArrayAsync(cancellationToken);
            Requests.Add(new CapturedRequest(request.Method, request.RequestUri!, headers, bytes.Length == 0 ? null : JsonDocument.Parse(bytes)));
            return _responses.Dequeue();
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
}
