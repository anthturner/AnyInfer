using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Contract-derived buffered controls for the native TEI retrieval dialect.</summary>
public sealed class TeiAdapterTests
{
    [Fact]
    public async Task Embed_projects_native_path_headers_payload_and_unknown_usage()
    {
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, "[[1.0,2.0]]"));
        await using var client = Client(handler, apiKey: "fixture-secret");

        var result = await client.EmbedAsync("input", target: "tei:any-advisory-model", retainRaw: true);

        var request = Assert.Single(handler.Requests);
        Assert.Equal(HttpMethod.Post, request.Method);
        Assert.Equal("/base/embed", request.Path);
        Assert.Equal("Bearer fixture-secret", request.Headers["authorization"]);
        Assert.Equal("application/json", request.ContentHeaders["content-type"]);
        Assert.Equal("input", request.Body.RootElement.GetProperty("inputs")[0].GetString());
        Assert.False(request.Body.RootElement.TryGetProperty("model", out _));
        AssertUnknownUsage(result.Usage);
        Assert.NotNull(result.Raw);
        Assert.NotNull(result.Manifest);
        Assert.Null(result.Manifest!.Payloads);
        Assert.Null(result.Manifest.Usage.CostUsd);
    }

    [Fact]
    public async Task Rerank_keeps_wire_order_for_request_and_stably_sorts_then_applies_top_n()
    {
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, """[{"index":2,"score":0.4},{"index":1,"score":0.9},{"index":0,"score":0.9}]"""));
        await using var client = Client(handler);

        var result = await client.RerankAsync("query", ["zero", "one", "two"], target: "tei:any", topN: 2, retainRaw: true);

        var request = Assert.Single(handler.Requests);
        Assert.Equal("/base/rerank", request.Path);
        Assert.Equal("query", request.Body.RootElement.GetProperty("query").GetString());
        Assert.False(request.Body.RootElement.GetProperty("return_text").GetBoolean());
        Assert.Equal(["zero", "one", "two"], request.Body.RootElement.GetProperty("texts").EnumerateArray().Select(static value => value.GetString()));
        Assert.Equal([1, 0], result.Items.Select(static item => item.Index));
        AssertUnknownUsage(result.Usage);
        Assert.NotNull(result.Raw);
    }

    [Fact]
    public async Task Discovery_maps_known_type_and_preserves_unknown_recognized_type_as_empty_operations()
    {
        var handler = new ScriptHandler(
            Response(HttpStatusCode.OK, """{"model_id":"embed","model_type":{"embedding":{}}}"""),
            Response(HttpStatusCode.OK, """{"model_id":"other","model_type":{"classifier":{}}}"""));
        await using var client = Client(handler);

        var known = await client.ModelsAsync("tei");
        var unknown = await client.ModelsAsync("tei");

        Assert.Equal("embed", Assert.Single(known).Id);
        Assert.Contains(InferenceOperation.Embedding, Assert.Single(known).Capabilities!.Operations!.Value);
        Assert.Empty(Assert.Single(unknown).Capabilities!.Operations!.Value);
        Assert.All(handler.Requests, static request => Assert.Equal("/base/info", request.Path));
    }

    [Fact]
    public async Task Status_classification_retains_numeric_retry_after_and_ignores_http_dates()
    {
        var numeric = new ScriptHandler(Response((HttpStatusCode)429, """{"error":"slow down"}""", retryAfter: "0.5"));
        await using var numericAdapter = Adapter(numeric);
        var numericFailure = await Assert.ThrowsAsync<RateLimitException>(() => numericAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());
        Assert.Equal(0.5, numericFailure.RetryAfterS);

        var date = new ScriptHandler(Response((HttpStatusCode)429, """{"error":"slow down"}""", retryAfter: "Wed, 21 Oct 2015 07:28:00 GMT"));
        await using var dateAdapter = Adapter(date);
        var dateFailure = await Assert.ThrowsAsync<RateLimitException>(() => dateAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());
        Assert.Null(dateFailure.RetryAfterS);
    }

    [Fact]
    public async Task Adapter_coerces_embedding_components_but_rejects_invalid_rank_shapes_and_count_mismatch()
    {
        var components = new ScriptHandler(Response(HttpStatusCode.OK, """[[true,"2.5"]]"""));
        await using var componentAdapter = Adapter(components);
        var vectors = await componentAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"]));
        Assert.Equal([1d, 2.5d], Assert.Single(vectors.Vectors));

        var mismatch = new ScriptHandler(Response(HttpStatusCode.OK, """[[1]]"""));
        await using var mismatchAdapter = Adapter(mismatch);
        await Assert.ThrowsAsync<ProviderException>(() => mismatchAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["one", "two"])).AsTask());

        var invalidScore = new ScriptHandler(Response(HttpStatusCode.OK, """[{"index":0,"score":"0.4"}]"""));
        await using var rankAdapter = Adapter(invalidScore);
        await Assert.ThrowsAsync<ProviderException>(() => rankAdapter.RerankAsync(new RerankWireRequest("model", "query", [new RerankWireDocument(0, "doc")])).AsTask());
    }

    [Fact]
    public async Task Status_is_classified_before_a_success_response_cap()
    {
        var error = new string('x', 2048);
        var handler = new ScriptHandler(Response(HttpStatusCode.Unauthorized, $$"""{"error":"{{error}}"}"""));
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<AuthException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask());

        Assert.Equal(401, failure.HttpStatus);
        Assert.Equal("generate", failure.Phase);
    }

    [Fact]
    public async Task Per_operation_options_overlay_native_payload_last_without_sending_model()
    {
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, """[[1]]"""));
        await using var adapter = Adapter(handler);
        var options = new Dictionary<string, JsonValue> { ["normalize"] = new JsonBoolean(false), ["inputs"] = new JsonArray([new JsonString("overlaid")]) };

        await adapter.EmbedAsync(new EmbeddingWireRequest("advisory", ["original"], extraOptions: options));

        var body = Assert.Single(handler.Requests).Body.RootElement;
        Assert.Equal("overlaid", body.GetProperty("inputs")[0].GetString());
        Assert.False(body.GetProperty("normalize").GetBoolean());
        Assert.False(body.TryGetProperty("model", out _));
    }

    [Fact]
    public async Task Public_operation_route_and_sync_facade_use_the_builtin_retrieval_path()
    {
        var routedHandler = new ScriptHandler(Response(HttpStatusCode.OK, """[[1]]"""));
        await using var routed = new AsyncClient(
            [ProviderSettings.Of("tei", "http://tei.test", transport: routedHandler)],
            ProviderRegistry.CreateDefault(),
            operationRoutes: new Dictionary<InferenceOperation, Route> { [InferenceOperation.Embedding] = new Route(["tei:routed-model"]) });

        var routedResult = await routed.EmbedAsync("input");
        Assert.Equal("routed-model", routedResult.Target.Model);
        Assert.Single(routedHandler.Requests);

        var syncHandler = new ScriptHandler(Response(HttpStatusCode.OK, """[[1]]"""));
        using var sync = new Client([ProviderSettings.Of("tei", "http://tei.test", transport: syncHandler)], ProviderRegistry.CreateDefault());
        var syncResult = sync.Embed("input", target: "tei:sync-model");
        Assert.Single(syncResult.Vectors);
        Assert.Single(syncHandler.Requests);
    }

    private static AsyncClient Client(HttpMessageHandler handler, string? apiKey = null) =>
        new([ProviderSettings.Of("tei", "http://tei.test/base", apiKey, transport: handler)], ProviderRegistry.CreateDefault(), retainRaw: true);

    private static TeiAdapter Adapter(HttpMessageHandler handler) => Assert.IsType<TeiAdapter>(TeiAdapter.Create(new ProviderConfig(ProviderSettings.Of("tei", "http://tei.test/base", transport: handler), "tei", null), CancellationToken.None));

    private static void AssertUnknownUsage(Usage? usage)
    {
        Assert.NotNull(usage);
        Assert.Null(usage!.InputTokens); Assert.Null(usage.OutputTokens); Assert.Null(usage.TotalTokens);
        Assert.Null(usage.CacheReadTokens); Assert.Null(usage.CacheWriteTokens); Assert.Null(usage.ReasoningTokens);
        Assert.Null(usage.CostUsd); Assert.Null(usage.SearchUnits); Assert.Empty(usage.ServerToolUses);
    }

    private static HttpResponseMessage Response(HttpStatusCode status, string body, string? retryAfter = null)
    {
        var response = new HttpResponseMessage(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        if (retryAfter is not null) response.Headers.TryAddWithoutValidation("Retry-After", retryAfter);
        return response;
    }

    private sealed record CapturedRequest(HttpMethod Method, string Path, IReadOnlyDictionary<string, string> Headers, IReadOnlyDictionary<string, string> ContentHeaders, JsonDocument Body);

    private sealed class ScriptHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);
        internal List<CapturedRequest> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Assert.NotEmpty(_responses);
            var bytes = await request.Content!.ReadAsByteArrayAsync(cancellationToken);
            var body = JsonDocument.Parse(bytes.Length == 0 ? "{}" : Encoding.UTF8.GetString(bytes));
            Requests.Add(new(request.Method, request.RequestUri!.AbsolutePath, Headers(request.Headers), Headers(request.Content.Headers), body));
            return _responses.Dequeue();
        }

        private static IReadOnlyDictionary<string, string> Headers(HttpHeaders headers) => headers.ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(",", item.Value), StringComparer.Ordinal);
    }
}
