using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Config;

namespace AnyInfer.Examples;

/// <summary>Exercises the built-in native Jina retrieval provider without hosted traffic.</summary>
public static class JinaExample
{
    /// <summary>Creates settings for a caller-configured Jina instance.</summary>
    public static ProviderSettings Settings(HttpMessageHandler transport, string apiKey = "env://JINA_API_KEY") =>
        ProviderSettings.Of("jina", apiKey: apiKey, transport: transport, alias: "jina-retrieval");

    /// <summary>Runs embedding and reranking through the default registry with an asynchronous client.</summary>
    public static async Task<JinaObservation> RunAsync(ProviderSettings settings, CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([settings], manifests: true);
        var embeddings = await client.EmbedAsync(
            ["A quiet river bends through the valley.", "A lighthouse watches the harbor."],
            target: "jina-retrieval:jina-embeddings-v5-text-small",
            inputType: EmbeddingInputIntent.Document, retainRaw: true, cancellationToken: cancellationToken,
            manifest: true);
        var reranking = await client.RerankAsync(
            "Which text mentions water?",
            [new RerankDocument("river", "A quiet river bends through the valley."), new RerankDocument("lighthouse", "A lighthouse watches the harbor.")],
            target: "jina-retrieval:jina-reranker-v3", topN: 1, returnDocuments: true,
            retainRaw: true, cancellationToken: cancellationToken, manifest: true);
        return new JinaObservation(embeddings, reranking);
    }

    /// <summary>Runs embedding and reranking through the synchronous facade.</summary>
    public static JinaObservation Run(ProviderSettings settings, CancellationToken cancellationToken = default)
    {
        using var client = new Client([settings], manifests: true);
        var embeddings = client.Embed(["Which text mentions water?"], target: "jina-retrieval:jina-embeddings-v5-text-small",
            inputType: EmbeddingInputIntent.Query, retainRaw: true, cancellationToken: cancellationToken, manifest: true);
        var reranking = client.Rerank("Which text mentions water?",
            [new RerankDocument("river", "A quiet river bends through the valley."), new RerankDocument("lighthouse", "A lighthouse watches the harbor.")],
            target: "jina-retrieval:jina-reranker-v3", topN: 1, returnDocuments: true,
            retainRaw: true, cancellationToken: cancellationToken, manifest: true);
        return new JinaObservation(embeddings, reranking);
    }
}

/// <summary>Contains the public results from native Jina embedding and reranking calls.</summary>
public sealed record JinaObservation(EmbeddingResult Embeddings, RerankResult Reranking);

/// <summary>Scripted HTTP transport that validates the literal native Jina requests used by the example.</summary>
public sealed class JinaScriptedHandler : HttpMessageHandler
{
    /// <summary>Gets the number of requests received by this handler.</summary>
    public int RequestCount { get; private set; }
    /// <summary>Gets the number of times this handler was disposed by the client pool.</summary>
    public int DisposeCount { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
        using var json = JsonDocument.Parse(body);
        if (request.Method != HttpMethod.Post || request.Headers.Authorization?.Scheme != "Bearer"
            || request.Headers.Authorization.Parameter != "offline-jina-key"
            || request.Headers.Accept.Single().MediaType != "application/json"
            || request.Content?.Headers.ContentType?.MediaType != "application/json")
            throw new InvalidOperationException("Jina example used unexpected HTTP transport fields.");
        return request.RequestUri?.AbsolutePath switch
        {
            "/v1/embeddings" => Embeddings(json.RootElement),
            "/v1/rerank" => Rerank(json.RootElement),
            _ => throw new InvalidOperationException("Jina example used an unexpected request path."),
        };
    }

    protected override void Dispose(bool disposing) { if (disposing) DisposeCount++; base.Dispose(disposing); }

    private static HttpResponseMessage Embeddings(JsonElement request)
    {
        var input = request.GetProperty("input").EnumerateArray().Select(static item => item.GetString()).ToArray();
        var task = request.GetProperty("task").GetString();
        if (request.GetProperty("model").GetString() != "jina-embeddings-v5-text-small"
            || (task != "retrieval.passage" && task != "retrieval.query")
            || (task == "retrieval.passage" && !input.SequenceEqual(["A quiet river bends through the valley.", "A lighthouse watches the harbor."]))
            || (task == "retrieval.query" && !input.SequenceEqual(["Which text mentions water?"])))
            throw new InvalidOperationException("Jina embedding request lost caller values or task mapping.");
        return Json(task == "retrieval.passage"
            ? "{\"data\":[{\"index\":1,\"embedding\":[0.3,0.4]},{\"index\":0,\"embedding\":[0.1,0.2]}],\"model\":\"jina-embeddings-v5-text-small\",\"usage\":{\"total_tokens\":7,\"prompt_tokens\":7}}"
            : "{\"data\":[{\"index\":0,\"embedding\":[0.5,0.6]}],\"model\":\"jina-embeddings-v5-text-small\",\"usage\":{\"total_tokens\":7,\"prompt_tokens\":7}}");
    }

    private static HttpResponseMessage Rerank(JsonElement request)
    {
        if (request.GetProperty("model").GetString() != "jina-reranker-v3"
            || request.GetProperty("query").GetString() != "Which text mentions water?"
            || request.GetProperty("top_n").GetInt32() != 1
            || !request.GetProperty("documents").EnumerateArray().Select(static item => item.GetString()).SequenceEqual(["A quiet river bends through the valley.", "A lighthouse watches the harbor."]))
            throw new InvalidOperationException("Jina rerank request lost caller values or native top_n.");
        return Json("{\"results\":[{\"index\":1,\"relevance_score\":0.1}],\"model\":\"jina-reranker-v3\",\"usage\":{\"total_tokens\":7,\"prompt_tokens\":7}}");
    }

    private static HttpResponseMessage Json(string body) => new() { Content = new StringContent(body, Encoding.UTF8, "application/json") };
}
