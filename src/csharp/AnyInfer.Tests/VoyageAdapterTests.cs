using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Contract-derived buffered controls for the native Voyage retrieval dialect.</summary>
public sealed class VoyageAdapterTests
{
    [Fact]
    public async Task Embedding_fixture_restores_wire_indexes_and_projects_exact_native_request()
    {
        var fixture = Fixture("embedding-indexed");
        Assert.Equal("embedding", fixture.GetProperty("operation").GetString());
        var stimulus = fixture.GetProperty("request");
        var inputs = stimulus.GetProperty("inputs").EnumerateArray().Select(static input => input.GetString()!).ToArray();
        var inputType = Enum.Parse<EmbeddingInputIntent>(stimulus.GetProperty("input_type").GetString()!, ignoreCase: true);
        var dimensions = stimulus.GetProperty("dimensions").GetInt32();
        var target = fixture.GetProperty("target").GetString()!;
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, fixture.GetProperty("response").GetRawText()));
        await using var client = Client(handler, apiKey: "fixture-secret");

        var result = await client.EmbedAsync(inputs, target: target, inputType: inputType, dimensions: dimensions);

        var request = Assert.Single(handler.Requests);
        Assert.Equal(HttpMethod.Post, request.Method);
        Assert.Equal("/base/v1/embeddings", request.Path);
        Assert.Equal("Bearer fixture-secret", request.Headers["authorization"]);
        Assert.Equal("application/json", request.ContentHeaders["content-type"]);
        Assert.Equal("voyage-3.5", request.Body.RootElement.GetProperty("model").GetString());
        Assert.Equal(["alpha", "beta"], request.Body.RootElement.GetProperty("input").EnumerateArray().Select(static item => item.GetString()));
        Assert.Equal("query", request.Body.RootElement.GetProperty("input_type").GetString());
        Assert.Equal(2, request.Body.RootElement.GetProperty("output_dimension").GetInt32());
        Assert.Equal([0.1d, 0.2d], result.Vectors[0].Values);
        Assert.Equal([0.3d, 0.4d], result.Vectors[1].Values);
        Assert.Null(result.Usage!.InputTokens);
        Assert.Null(result.Usage.OutputTokens);
        Assert.Equal(7, result.Usage.TotalTokens);
    }

    [Fact]
    public async Task Rerank_fixture_maps_original_ids_and_forwards_native_top_n()
    {
        var fixture = Fixture("rerank-positional");
        Assert.Equal("rerank", fixture.GetProperty("operation").GetString());
        var stimulus = fixture.GetProperty("request");
        var query = stimulus.GetProperty("query").GetString()!;
        var documents = stimulus.GetProperty("documents").EnumerateArray().Select(static item => new RerankDocument(item.GetProperty("id").GetString()!, item.GetProperty("text").GetString()!)).ToArray();
        var topN = stimulus.GetProperty("top_n").GetInt32();
        var target = fixture.GetProperty("target").GetString()!;
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, fixture.GetProperty("response").GetRawText()));
        await using var client = Client(handler);

        var result = await client.RerankAsync(query, documents, target: target, topN: topN, retainRaw: true);

        var request = Assert.Single(handler.Requests);
        Assert.Equal("/base/v1/rerank", request.Path);
        Assert.Equal("question", request.Body.RootElement.GetProperty("query").GetString());
        Assert.Equal(["first", "second"], request.Body.RootElement.GetProperty("documents").EnumerateArray().Select(static item => item.GetString()));
        Assert.Equal(1, request.Body.RootElement.GetProperty("top_k").GetInt32());
        var item = Assert.Single(result.Items);
        Assert.Equal(1, item.Index);
        Assert.Equal("doc-a", item.DocumentId);
        Assert.Equal(0.9d, item.Score);
        Assert.Null(result.Usage!.InputTokens);
        Assert.Null(result.Usage.OutputTokens);
        Assert.Equal(11, result.Usage.TotalTokens);
        Assert.NotNull(result.Raw);
    }

    [Fact]
    public async Task Rerank_adapter_preserves_provider_response_order_while_mapping_original_indexes()
    {
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"relevance_score":0.1},{"index":1,"relevance_score":0.9}]}"""));
        await using var adapter = Adapter(handler);

        var result = await adapter.RerankAsync(new RerankWireRequest("model", "question", [new RerankWireDocument(7, "first"), new RerankWireDocument(4, "second")]));

        Assert.Equal([7, 4], result.Items.Select(static item => item.Index));
        Assert.Equal([0.1d, 0.9d], result.Items.Select(static item => item.Score));
    }

    [Fact]
    public async Task Custom_headers_override_default_bearer_and_options_overlay_payload_last()
    {
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, """{"object":"list","data":[{"index":0,"embedding":[1]}]}"""));
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["Authorization"] = "Custom fixture" };
        var options = new Dictionary<string, JsonValue> { ["model"] = new JsonString("overlaid"), ["input"] = new JsonArray([new JsonString("changed")]), ["extra"] = new JsonBoolean(true) };
        await using var adapter = Adapter(handler, headers: headers);

        await adapter.EmbedAsync(new EmbeddingWireRequest("original", ["input"], extraOptions: options));

        var request = Assert.Single(handler.Requests);
        Assert.Equal("Custom fixture", request.Headers["authorization"]);
        Assert.Equal("overlaid", request.Body.RootElement.GetProperty("model").GetString());
        Assert.Equal("changed", request.Body.RootElement.GetProperty("input")[0].GetString());
        Assert.True(request.Body.RootElement.GetProperty("extra").GetBoolean());
        Assert.False(request.Query.Contains("api-version", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public async Task Raw_usage_is_total_only_and_invalid_indexes_are_rejected()
    {
        var rawHandler = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":[true,"2.5"]}],"usage":{"total_tokens":7}}"""));
        await using var rawAdapter = Adapter(rawHandler);
        var raw = await rawAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"]));
        Assert.Equal([1d, 2.5d], Assert.Single(raw.Vectors));
        Assert.Null(raw.Usage!.InputTokens);
        Assert.Null(raw.Usage.OutputTokens);
        Assert.Equal(7, raw.Usage.TotalTokens);

        var malformed = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":true,"embedding":[1]}]}"""));
        await using var malformedAdapter = Adapter(malformed);
        await Assert.ThrowsAsync<ProviderException>(() => malformedAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());

        var malformedUsage = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":[1]}],"usage":{"total_tokens":true}}"""));
        await using var malformedUsageAdapter = Adapter(malformedUsage);
        var unknownUsage = await malformedUsageAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"]));
        Assert.Null(unknownUsage.Usage);

        var overflowingUsage = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":[1]}],"usage":{"total_tokens":9223372036854775808}}"""));
        await using var overflowingUsageAdapter = Adapter(overflowingUsage);
        var overflow = await Assert.ThrowsAsync<ProviderException>(() => overflowingUsageAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());
        Assert.Equal("validate", overflow.Phase);
    }

    [Theory]
    [InlineData("true", "0.1")]
    [InlineData("\"0\"", "0.1")]
    [InlineData("2", "0.1")]
    [InlineData("0", "true")]
    [InlineData("0", "\"0.1\"")]
    public async Task Rerank_rejects_boolean_string_and_out_of_range_indexes_and_non_numeric_scores(string index, string score)
    {
        var body = $$"""{"data":[{"index":{{index}},"relevance_score":{{score}}}]}""";
        using var parsed = JsonDocument.Parse(body);
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, body));
        await using var adapter = Adapter(handler);
        await Assert.ThrowsAsync<ProviderException>(() => adapter.RerankAsync(new RerankWireRequest("model", "query", [new RerankWireDocument(0, "doc"), new RerankWireDocument(1, "doc")])).AsTask());
    }

    [Fact]
    public async Task Public_core_refuses_nonfinite_components_and_ragged_vectors()
    {
        var nonfinite = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":["NaN"]}]}"""));
        await using var nonfiniteClient = Client(nonfinite);
        var nonfiniteFailure = await Assert.ThrowsAsync<ConfigException>(() => nonfiniteClient.EmbedAsync("input", target: "voyage:model"));
        Assert.Single(nonfinite.Requests);
        Assert.Contains("malformed embedding vector", nonfiniteFailure.Message, StringComparison.OrdinalIgnoreCase);

        var ragged = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":[1]},{"index":1,"embedding":[1,2]}]}"""));
        await using var raggedClient = Client(ragged);
        var raggedFailure = await Assert.ThrowsAsync<ConfigException>(() => raggedClient.EmbedAsync(["one", "two"], target: "voyage:model"));
        Assert.Single(ragged.Requests);
        Assert.Contains("inconsistent dimensions", raggedFailure.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Status_classification_retains_numeric_retry_after_and_runs_before_cap()
    {
        var handler = new ScriptHandler(Response((HttpStatusCode)429, """{"detail":"slow down"}""", retryAfter: "0.5"));
        await using var adapter = Adapter(handler);
        var failure = await Assert.ThrowsAsync<RateLimitException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());
        Assert.Equal(0.5, failure.RetryAfterS);

        var statusFirst = new ScriptHandler(Response(HttpStatusCode.Unauthorized, $$"""{"detail":"{{new string('x', 2048)}}"}"""));
        await using var statusAdapter = Adapter(statusFirst);
        var auth = await Assert.ThrowsAsync<AuthException>(() => statusAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask());
        Assert.Equal(401, auth.HttpStatus);
    }

    [Fact]
    public async Task Large_valid_429_body_is_classified_before_the_success_cap()
    {
        var detail = new string('x', 70_000);
        var body = JsonSerializer.Serialize(new { detail });
        using var parsed = JsonDocument.Parse(body);
        var handler = new ScriptHandler(Response((HttpStatusCode)429, body));
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<RateLimitException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask());

        Assert.Equal(429, failure.HttpStatus);
        Assert.Equal("generate", failure.Phase);
    }

    [Theory]
    [InlineData("""{"error":{"message":"message-value","detail":"ignored","type":"ignored"}}""", "message-value")]
    [InlineData("""{"error":{"detail":"detail-value","type":"ignored"}}""", "detail-value")]
    [InlineData("""{"error":{"type":"type-value"}}""", "type-value")]
    public async Task Nested_error_detail_prefers_message_then_detail_then_type(string body, string expected)
    {
        var handler = new ScriptHandler(Response((HttpStatusCode)429, body));
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<RateLimitException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());

        Assert.Equal(429, failure.HttpStatus);
        Assert.Equal("generate", failure.Phase);
        Assert.Equal(expected, failure.Detail);
    }

    [Fact]
    public async Task Error_detail_is_bounded_to_400_and_redacts_the_registered_secret()
    {
        Redaction.RegisterSecret("fixture-secret");
        var detail = "fixture-secret " + new string('x', 500);
        var body = JsonSerializer.Serialize(new { error = new { message = detail } });
        using var parsed = JsonDocument.Parse(body);
        var handler = new ScriptHandler(Response((HttpStatusCode)429, body));
        await using var adapter = Adapter(handler);

        var failure = await Assert.ThrowsAsync<RateLimitException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());

        Assert.NotEmpty(failure.Detail!);
        Assert.True(failure.Detail!.Length <= 400);
        Assert.DoesNotContain("fixture-secret", failure.Detail, StringComparison.Ordinal);
        Assert.Contains("[redacted]", failure.Detail, StringComparison.Ordinal);
    }

    [Fact]
    public void Default_registry_exposes_retrieval_only_voyage_descriptor()
    {
        var registry = ProviderRegistry.CreateDefault();
        var descriptor = registry.Get("voyageai");
        Assert.Equal("voyage", descriptor.Id);
        Assert.Equal("https://api.voyageai.com/v1", descriptor.DefaultBaseUrl);
        Assert.Contains(InferenceOperation.Embedding, descriptor.Operations);
        Assert.Contains(InferenceOperation.Rerank, descriptor.Operations);
        Assert.DoesNotContain(InferenceOperation.Generation, descriptor.Operations);
        Assert.Equal("VOYAGE_API_KEY", Assert.Single(descriptor.Setup.Fields, static field => field.Key == "api_key").EnvVar);
        Assert.True(Assert.Single(descriptor.Setup.Fields, static field => field.Key == "api_key").Required);
        Assert.Equal(["voyage-3-large", "voyage-3.5", "voyage-3.5-lite", "voyage-4", "voyage-4-large", "voyage-4-lite", "voyage-code-3", "voyage-finance-2", "voyage-law-2"], descriptor.StaticEmbeddingCapabilities.Keys.OrderBy(static key => key, StringComparer.Ordinal));
        Assert.Equal(["rerank-2", "rerank-2-lite", "rerank-2.5", "rerank-2.5-lite"], descriptor.StaticRerankCapabilities.Keys.OrderBy(static key => key, StringComparer.Ordinal));
        Assert.All(descriptor.StaticEmbeddingCapabilities.Values, static capability => { Assert.Equal(1000, capability.MaxBatchInputs); Assert.Equal([EmbeddingInputIntent.Query, EmbeddingInputIntent.Document], capability.InputIntents); Assert.Empty(capability.DimensionChoices); Assert.Null(capability.Dimensions); Assert.Null(capability.MaxInputTokens); Assert.Null(capability.MaxInputBytes); Assert.Null(capability.Normalized); });
        Assert.All(descriptor.StaticRerankCapabilities.Values, static capability => { Assert.Equal(1000, capability.MaxDocuments); Assert.Null(capability.MaxTokensPerDocument); Assert.Null(capability.MaxBytesPerDocument); Assert.True(capability.NativeTopN); });
        Assert.Equal("manual-only", descriptor.Setup.ModelSelection);
    }

    private static AsyncClient Client(HttpMessageHandler handler, string? apiKey = "fixture-secret") =>
        new([ProviderSettings.Of("voyage", "http://voyage.test/base/v1", apiKey, transport: handler)], ProviderRegistry.CreateDefault(), retainRaw: true);

    private static VoyageAdapter Adapter(HttpMessageHandler handler, IReadOnlyDictionary<string, string>? headers = null) =>
        Assert.IsType<VoyageAdapter>(VoyageAdapter.Create(new ProviderConfig(ProviderSettings.Of("voyage", "http://voyage.test/base/v1", "fixture-secret", headers: headers, transport: handler), "voyage", "fixture-secret"), CancellationToken.None));

    private static JsonElement Fixture(string id)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "voyage-wire", "inputs.json")));
        return document.RootElement.GetProperty("cases").EnumerateArray().Single(item => item.GetProperty("id").GetString() == id).Clone();
    }

    private static HttpResponseMessage Response(HttpStatusCode status, string body, string? retryAfter = null)
    {
        var response = new HttpResponseMessage(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        if (retryAfter is not null) response.Headers.TryAddWithoutValidation("Retry-After", retryAfter);
        return response;
    }

    private sealed record CapturedRequest(HttpMethod Method, string Path, string Query, IReadOnlyDictionary<string, string> Headers, IReadOnlyDictionary<string, string> ContentHeaders, JsonDocument Body);
    private sealed class ScriptHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);
        internal List<CapturedRequest> Requests { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Assert.NotEmpty(_responses);
            var bytes = await request.Content!.ReadAsByteArrayAsync(cancellationToken);
            Requests.Add(new(request.Method, request.RequestUri!.AbsolutePath, request.RequestUri.Query, Headers(request.Headers), Headers(request.Content.Headers), JsonDocument.Parse(bytes)));
            return _responses.Dequeue();
        }
        private static IReadOnlyDictionary<string, string> Headers(HttpHeaders headers) => headers.ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(",", item.Value), StringComparer.Ordinal);
    }
}
