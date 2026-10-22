using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Contract-derived buffered controls for the native Jina retrieval dialect.</summary>
public sealed class JinaAdapterTests
{
    private static readonly HashSet<string> V5ModelsWithLiteralClustering = new(StringComparer.Ordinal)
    {
        "jina-embeddings-v5-text-small",
        "jina-embeddings-v5-text-nano",
        "jina-embeddings-v5-omni-small",
        "jina-embeddings-v5-omni-nano",
    };

    [Fact]
    public async Task Embedding_fixture_restores_wire_indexes_and_projects_exact_native_request()
    {
        var fixture = Fixture("embedding-v3-indexed");
        Assert.Equal("embedding", fixture.GetProperty("operation").GetString());
        var stimulus = fixture.GetProperty("request");
        var inputs = stimulus.GetProperty("inputs").EnumerateArray().Select(static value => value.GetString()!).ToArray();
        var inputType = Enum.Parse<EmbeddingInputIntent>(stimulus.GetProperty("input_type").GetString()!, ignoreCase: true);
        var dimensions = stimulus.GetProperty("dimensions").GetInt32();
        var target = fixture.GetProperty("target").GetString()!;
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, fixture.GetProperty("response").GetRawText()));
        await using var client = Client(handler);

        var result = await client.EmbedAsync(inputs, target: target, inputType: inputType, dimensions: dimensions);

        var request = Assert.Single(handler.Requests);
        Assert.Equal(HttpMethod.Post, request.Method);
        Assert.Equal("/base/v1/embeddings", request.Path);
        Assert.Equal("Bearer fixture-secret", request.Headers["authorization"]);
        Assert.Equal("application/json", request.ContentHeaders["content-type"]);
        Assert.Equal(target.Split(':', 2)[1], request.Body.RootElement.GetProperty("model").GetString());
        Assert.Equal(inputs, request.Body.RootElement.GetProperty("input").EnumerateArray().Select(static value => value.GetString()));
        Assert.Equal("retrieval.query", request.Body.RootElement.GetProperty("task").GetString());
        Assert.Equal(dimensions, request.Body.RootElement.GetProperty("dimensions").GetInt32());
        Assert.Equal([0.1d, 0.2d], result.Vectors[0].Values);
        Assert.Equal([0.3d, 0.4d], result.Vectors[1].Values);
        Assert.Equal(7, result.Usage!.TotalTokens);
        Assert.Null(result.Usage.InputTokens);
        Assert.Null(result.Usage.OutputTokens);
    }

    [Fact]
    public async Task V5_fixture_preserves_prompt_usage_raw_while_normalizing_total_only()
    {
        var fixture = Fixture("embedding-v5-clustering");
        Assert.Equal("embedding", fixture.GetProperty("operation").GetString());
        var stimulus = fixture.GetProperty("request");
        var inputs = stimulus.GetProperty("inputs").EnumerateArray().Select(static value => value.GetString()!).ToArray();
        var inputType = Enum.Parse<EmbeddingInputIntent>(stimulus.GetProperty("input_type").GetString()!, ignoreCase: true);
        var target = fixture.GetProperty("target").GetString()!;
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, fixture.GetProperty("response").GetRawText()));
        await using var client = Client(handler);

        var result = await client.EmbedAsync(inputs, target: target, inputType: inputType);

        Assert.Equal("clustering", Assert.Single(handler.Requests).Body.RootElement.GetProperty("task").GetString());
        Assert.Contains("\"prompt_tokens\":8", JsonWriter.Write(result.Raw!));
        Assert.Equal(9, result.Usage!.TotalTokens);
        Assert.Null(result.Usage.InputTokens);
        Assert.Null(result.Usage.OutputTokens);
        Assert.Null(result.Usage.CacheReadTokens);
        Assert.Null(result.Usage.CacheWriteTokens);
        Assert.Null(result.Usage.ReasoningTokens);
        Assert.Null(result.Usage.CostUsd);
        Assert.Null(result.Usage.SearchUnits);
        Assert.Empty(result.Usage.ServerToolUses);
    }

    [Fact]
    public async Task Embedding_task_matrix_covers_all_normalized_intents_and_model_specific_Jina_spellings()
    {
        foreach (var (intent, model, task) in TaskCases())
        {
            var handler = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":[1]}]}"""));
            await using var adapter = Adapter(handler);

            await adapter.EmbedAsync(new EmbeddingWireRequest(model, ["input"], inputType: intent));

            var body = Assert.Single(handler.Requests).Body.RootElement;
            if (task is null)
            {
                Assert.False(body.TryGetProperty("task", out _));
            }
            else
            {
                Assert.Equal(task, body.GetProperty("task").GetString());
            }
        }
    }

    [Theory]
    [InlineData(EmbeddingInputIntent.Classification)]
    [InlineData(EmbeddingInputIntent.Clustering)]
    public async Task Public_v4_unsupported_intents_warn_while_retaining_the_adapter_omission_rule(EmbeddingInputIntent intent)
    {
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":[1]}]}"""));
        await using var client = Client(handler);

        var result = await client.EmbedAsync("input", target: "jina:jina-embeddings-v4", inputType: intent);

        Assert.Contains(result.Warnings, warning => warning.Contains($"does not support input_type='{intent.ToString().ToLowerInvariant()}'", StringComparison.Ordinal));
        Assert.False(Assert.Single(handler.Requests).Body.RootElement.TryGetProperty("task", out _));
    }

    [Fact]
    public async Task Rerank_fixture_preserves_wire_order_and_maps_original_ids_without_local_truncation()
    {
        var fixture = Fixture("rerank-positional-results");
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
        Assert.Equal(topN, request.Body.RootElement.GetProperty("top_n").GetInt32());
        Assert.Equal(documents.Select(static document => document.Text), request.Body.RootElement.GetProperty("documents").EnumerateArray().Select(static item => item.GetString()));
        var item = Assert.Single(result.Items);
        Assert.Equal(1, item.Index);
        Assert.Equal("doc-a", item.DocumentId);
        Assert.Equal(0.9d, item.Score);
        Assert.NotNull(result.Raw);
    }

    [Fact]
    public async Task Rerank_adapter_preserves_provider_order_and_does_not_locally_apply_top_n()
    {
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, """{"results":[{"index":1,"relevance_score":0.1},{"index":0,"relevance_score":0.9}]}"""));
        await using var adapter = Adapter(handler);

        var result = await adapter.RerankAsync(new RerankWireRequest("model", "question", [new RerankWireDocument(7, "first"), new RerankWireDocument(4, "second")], topN: 1));

        Assert.Equal([4, 7], result.Items.Select(static item => item.Index));
        Assert.Equal([0.1d, 0.9d], result.Items.Select(static item => item.Score));
    }

    [Fact]
    public async Task Custom_headers_override_bearer_options_overlay_last_and_api_version_is_not_sent()
    {
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":[1]}]}"""));
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["Authorization"] = "Custom fixture", ["Content-Type"] = "application/vnd.jina+json" };
        var options = new Dictionary<string, JsonValue> { ["model"] = new JsonString("overlaid"), ["input"] = new JsonArray([new JsonString("changed")]), ["task"] = new JsonString("caller-task"), ["extra"] = new JsonBoolean(true) };
        await using var adapter = Adapter(handler, headers);

        await adapter.EmbedAsync(new EmbeddingWireRequest("original", ["input"], inputType: EmbeddingInputIntent.Clustering, extraOptions: options));

        var request = Assert.Single(handler.Requests);
        Assert.Equal("Custom fixture", request.Headers["authorization"]);
        Assert.Equal("application/vnd.jina+json", request.ContentHeaders["content-type"]);
        Assert.Equal("overlaid", request.Body.RootElement.GetProperty("model").GetString());
        Assert.Equal("changed", request.Body.RootElement.GetProperty("input")[0].GetString());
        Assert.Equal("caller-task", request.Body.RootElement.GetProperty("task").GetString());
        Assert.True(request.Body.RootElement.GetProperty("extra").GetBoolean());
        Assert.False(request.Query.Contains("api-version", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public async Task Raw_usage_is_total_only_bool_and_string_float_components_are_preserved_and_invalid_indexes_are_rejected()
    {
        var valid = new ScriptHandler(Response(HttpStatusCode.OK, """{"model":"returned","data":[{"index":0,"embedding":[true,"2.5"]}],"usage":{"total_tokens":7,"prompt_tokens":3,"image_tokens":1}}"""));
        await using var validAdapter = Adapter(valid);
        var raw = await validAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"]));
        Assert.Equal([1d, 2.5d], Assert.Single(raw.Vectors));
        Assert.Equal("returned", raw.Model);
        Assert.Equal(7, raw.Usage!.TotalTokens);
        Assert.Null(raw.Usage.InputTokens);
        Assert.Null(raw.Usage.OutputTokens);
        Assert.Null(raw.Usage.CacheReadTokens);
        Assert.Null(raw.Usage.CacheWriteTokens);
        Assert.Null(raw.Usage.ReasoningTokens);
        Assert.Null(raw.Usage.CostUsd);
        Assert.Null(raw.Usage.SearchUnits);
        Assert.Empty(raw.Usage.ServerToolUses);
        Assert.Contains("\"prompt_tokens\":3", JsonWriter.Write(raw.Raw!));

        var malformed = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":true,"embedding":[1]}]}"""));
        await using var malformedAdapter = Adapter(malformed);
        await Assert.ThrowsAsync<ProviderException>(() => malformedAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask());

        var overflow = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":[1]}],"usage":{"total_tokens":9223372036854775808}}"""));
        await using var overflowAdapter = Adapter(overflow);
        Assert.Equal("validate", (await Assert.ThrowsAsync<ProviderException>(() => overflowAdapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"])).AsTask())).Phase);
    }

    [Fact]
    public async Task Public_core_refuses_nonfinite_and_ragged_vectors()
    {
        var nonfinite = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":["NaN"]}]}"""));
        await using var nonfiniteClient = Client(nonfinite);
        await Assert.ThrowsAsync<ConfigException>(() => nonfiniteClient.EmbedAsync("input", target: "jina:model"));

        var ragged = new ScriptHandler(Response(HttpStatusCode.OK, """{"data":[{"index":0,"embedding":[1]},{"index":1,"embedding":[1,2]}]}"""));
        await using var raggedClient = Client(ragged);
        await Assert.ThrowsAsync<ConfigException>(() => raggedClient.EmbedAsync(["one", "two"], target: "jina:model"));
    }

    [Theory]
    [InlineData("true", "0.1")]
    [InlineData("\"0\"", "0.1")]
    [InlineData("2", "0.1")]
    [InlineData("0", "true")]
    [InlineData("0", "\"0.1\"")]
    public async Task Rerank_rejects_invalid_positions_and_scores(string index, string score)
    {
        var handler = new ScriptHandler(Response(HttpStatusCode.OK, $$"""{"results":[{"index":{{index}},"relevance_score":{{score}}}]}"""));
        await using var adapter = Adapter(handler);
        await Assert.ThrowsAsync<ProviderException>(() => adapter.RerankAsync(new RerankWireRequest("model", "query", [new RerankWireDocument(0, "one"), new RerankWireDocument(1, "two")])).AsTask());
    }

    [Fact]
    public async Task Status_is_classified_before_success_cap_and_error_detail_is_bounded_and_redacted()
    {
        Redaction.RegisterSecret("fixture-secret");
        var body = JsonSerializer.Serialize(new { detail = "fixture-secret " + new string('x', 600) });
        var handler = new ScriptHandler(Response((HttpStatusCode)429, body, "0.5"));
        await using var adapter = Adapter(handler);
        var failure = await Assert.ThrowsAsync<RateLimitException>(() => adapter.EmbedAsync(new EmbeddingWireRequest("model", ["input"], maxResponseBytes: 1)).AsTask());
        Assert.Equal(0.5, failure.RetryAfterS);
        Assert.True(failure.Detail!.Length <= 400);
        Assert.DoesNotContain("fixture-secret", failure.Detail, StringComparison.Ordinal);
    }

    [Fact]
    public void Default_registry_exposes_manual_retrieval_only_Jina_metadata()
    {
        var descriptor = ProviderRegistry.CreateDefault().Get("jinaai");
        Assert.Equal("jina", descriptor.Id);
        Assert.Equal("https://api.jina.ai/v1", descriptor.DefaultBaseUrl);
        Assert.Equal("manual-only", descriptor.Setup.ModelSelection);
        Assert.Equal("JINA_API_KEY", Assert.Single(descriptor.Setup.Fields, static field => field.Key == "api_key").EnvVar);
        Assert.True(Assert.Single(descriptor.Setup.Fields, static field => field.Key == "api_key").Required);
        Assert.Contains(InferenceOperation.Embedding, descriptor.Operations);
        Assert.Contains(InferenceOperation.Rerank, descriptor.Operations);
        Assert.DoesNotContain(InferenceOperation.Generation, descriptor.Operations);
        Assert.Equal(["jina-embeddings-v3", "jina-embeddings-v4", "jina-embeddings-v5-omni-nano", "jina-embeddings-v5-omni-small", "jina-embeddings-v5-text-nano", "jina-embeddings-v5-text-small"], descriptor.StaticEmbeddingCapabilities.Keys.OrderBy(static key => key, StringComparer.Ordinal));
        Assert.Equal(["jina-reranker-m0", "jina-reranker-v2-base-multilingual", "jina-reranker-v3", "jina-reranker-v3.5"], descriptor.StaticRerankCapabilities.Keys.OrderBy(static key => key, StringComparer.Ordinal));
        Assert.Equal([EmbeddingInputIntent.Query, EmbeddingInputIntent.Document], descriptor.StaticEmbeddingCapabilities["jina-embeddings-v4"].InputIntents);
        Assert.Equal([EmbeddingInputIntent.Query, EmbeddingInputIntent.Document, EmbeddingInputIntent.Classification, EmbeddingInputIntent.Clustering], descriptor.StaticEmbeddingCapabilities["jina-embeddings-v3"].InputIntents);
        Assert.All(descriptor.StaticEmbeddingCapabilities.Where(static item => item.Key != "jina-embeddings-v4").Select(static item => item.Value), static capability => Assert.Equal([EmbeddingInputIntent.Query, EmbeddingInputIntent.Document, EmbeddingInputIntent.Classification, EmbeddingInputIntent.Clustering], capability.InputIntents));
        Assert.All(descriptor.StaticRerankCapabilities.Values, static capability => Assert.True(capability.NativeTopN));
    }

    private static AsyncClient Client(HttpMessageHandler handler) => new([ProviderSettings.Of("jina", "http://jina.test/base/v1", "fixture-secret", transport: handler)], ProviderRegistry.CreateDefault(), retainRaw: true);
    private static JinaAdapter Adapter(HttpMessageHandler handler, IReadOnlyDictionary<string, string>? headers = null) => Assert.IsType<JinaAdapter>(JinaAdapter.Create(new ProviderConfig(ProviderSettings.Of("jina", "http://jina.test/base/v1", "fixture-secret", headers: headers, transport: handler), "jina", "fixture-secret"), CancellationToken.None));
    private static IEnumerable<(EmbeddingInputIntent Intent, string Model, string? Task)> TaskCases()
    {
        foreach (var model in new[] { "jina-embeddings-v3", "jina-embeddings-v5-text-small", "jina-embeddings-v5-text-nano", "jina-embeddings-v5-omni-small", "jina-embeddings-v5-omni-nano", "unknown-future-model", "jina-embeddings-v5-future" })
        {
            yield return (EmbeddingInputIntent.Query, model, "retrieval.query");
            yield return (EmbeddingInputIntent.Document, model, "retrieval.passage");
            yield return (EmbeddingInputIntent.Classification, model, "classification");
            yield return (EmbeddingInputIntent.Clustering, model, V5ModelsWithLiteralClustering.Contains(model) ? "clustering" : "separation");
        }

        yield return (EmbeddingInputIntent.Query, "jina-embeddings-v4", "retrieval.query");
        yield return (EmbeddingInputIntent.Document, "jina-embeddings-v4", "retrieval.passage");
        yield return (EmbeddingInputIntent.Classification, "jina-embeddings-v4", null);
        yield return (EmbeddingInputIntent.Clustering, "jina-embeddings-v4", null);
    }
    private static JsonElement Fixture(string id) { using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "jina-wire", "inputs.json"))); return document.RootElement.GetProperty("cases").EnumerateArray().Single(item => item.GetProperty("id").GetString() == id).Clone(); }
    private static HttpResponseMessage Response(HttpStatusCode status, string body, string? retryAfter = null) { var response = new HttpResponseMessage(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") }; if (retryAfter is not null) response.Headers.TryAddWithoutValidation("Retry-After", retryAfter); return response; }
    private sealed record CapturedRequest(HttpMethod Method, string Path, string Query, IReadOnlyDictionary<string, string> Headers, IReadOnlyDictionary<string, string> ContentHeaders, JsonDocument Body);
    private sealed class ScriptHandler(params HttpResponseMessage[] responses) : HttpMessageHandler { private readonly Queue<HttpResponseMessage> _responses = new(responses); internal List<CapturedRequest> Requests { get; } = []; protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) { var bytes = await request.Content!.ReadAsByteArrayAsync(cancellationToken); Requests.Add(new(request.Method, request.RequestUri!.AbsolutePath, request.RequestUri.Query, Headers(request.Headers), Headers(request.Content.Headers), JsonDocument.Parse(bytes))); return _responses.Dequeue(); } private static IReadOnlyDictionary<string, string> Headers(HttpHeaders headers) => headers.ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(",", item.Value), StringComparer.Ordinal); }
}
