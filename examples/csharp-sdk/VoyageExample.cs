using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Config;

namespace AnyInfer.Examples;

/// <summary>Exercises the built-in native Voyage retrieval provider without hosted traffic.</summary>
public static class VoyageExample
{
    /// <summary>Creates settings for a caller-configured Voyage instance.</summary>
    public static ProviderSettings Settings(HttpMessageHandler transport, string apiKey = "env://VOYAGE_API_KEY") =>
        ProviderSettings.Of("voyage", apiKey: apiKey, transport: transport, alias: "voyage-retrieval");

    /// <summary>Runs embedding and reranking through the default registry with an asynchronous client.</summary>
    public static async Task<VoyageObservation> RunAsync(
        ProviderSettings settings,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([settings], manifests: true);
        return await RunAsync(client, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>Runs embedding and reranking through the default registry with the synchronous facade.</summary>
    public static VoyageObservation Run(
        ProviderSettings settings,
        CancellationToken cancellationToken = default)
    {
        using var client = new Client([settings], manifests: true);
        return Run(client, cancellationToken);
    }

    private static async Task<VoyageObservation> RunAsync(AsyncClient client, CancellationToken cancellationToken)
    {
        var embeddings = await client.EmbedAsync(
            ["A quiet river bends through the valley.", "A lighthouse watches the harbor."],
            target: "voyage-retrieval:voyage-3.5-lite",
            inputType: EmbeddingInputIntent.Document,
            retainRaw: true,
            cancellationToken: cancellationToken,
            manifest: true).ConfigureAwait(false);
        var reranking = await client.RerankAsync(
            "Which text mentions water?",
            [
                new RerankDocument("river", "A quiet river bends through the valley."),
                new RerankDocument("lighthouse", "A lighthouse watches the harbor."),
            ],
            target: "voyage-retrieval:rerank-2.5",
            topN: 1,
            returnDocuments: true,
            retainRaw: true,
            cancellationToken: cancellationToken,
            manifest: true).ConfigureAwait(false);
        return new VoyageObservation(embeddings, reranking);
    }

    private static VoyageObservation Run(Client client, CancellationToken cancellationToken)
    {
        var embeddings = client.Embed(
            ["Which text mentions water?"],
            target: "voyage-retrieval:voyage-3.5-lite",
            inputType: EmbeddingInputIntent.Query,
            retainRaw: true,
            cancellationToken: cancellationToken,
            manifest: true);
        var reranking = client.Rerank(
            "Which text mentions water?",
            [
                new RerankDocument("river", "A quiet river bends through the valley."),
                new RerankDocument("lighthouse", "A lighthouse watches the harbor."),
            ],
            target: "voyage-retrieval:rerank-2.5",
            topN: 1,
            returnDocuments: true,
            retainRaw: true,
            cancellationToken: cancellationToken,
            manifest: true);
        return new VoyageObservation(embeddings, reranking);
    }
}

/// <summary>Contains the public results from native Voyage embedding and reranking calls.</summary>
public sealed record VoyageObservation(EmbeddingResult Embeddings, RerankResult Reranking);

/// <summary>Scripted HTTP transport that validates the literal native Voyage requests used by the example.</summary>
public sealed class VoyageScriptedHandler : HttpMessageHandler
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
        if (request.Method != HttpMethod.Post
            || request.Headers.Authorization?.Scheme != "Bearer"
            || request.Headers.Authorization.Parameter != "offline-voyage-key"
            || request.Headers.Accept.Single().MediaType != "application/json"
            || request.Content?.Headers.ContentType?.MediaType != "application/json")
        {
            throw new InvalidOperationException("Voyage example used unexpected HTTP transport fields.");
        }

        return request.RequestUri?.AbsolutePath switch
        {
            "/v1/embeddings" => Embeddings(json.RootElement),
            "/v1/rerank" => Rerank(json.RootElement),
            _ => throw new InvalidOperationException("Voyage example used an unexpected request path."),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }

    private static HttpResponseMessage Embeddings(JsonElement request)
    {
        var input = request.GetProperty("input").EnumerateArray().Select(static item => item.GetString()).ToArray();
        var inputType = request.GetProperty("input_type").GetString();
        if (request.GetProperty("model").GetString() != "voyage-3.5-lite"
            || (inputType != "document" && inputType != "query")
            || (inputType == "document" && !input.SequenceEqual(["A quiet river bends through the valley.", "A lighthouse watches the harbor."]))
            || (inputType == "query" && !input.SequenceEqual(["Which text mentions water?"])))
        {
            throw new InvalidOperationException("Voyage embedding request lost caller values or array shape.");
        }

        var response = inputType == "document"
            ? "{\"data\":[{\"index\":1,\"embedding\":[0.3,0.4]},{\"index\":0,\"embedding\":[0.1,0.2]}],\"usage\":{\"total_tokens\":7}}"
            : "{\"data\":[{\"index\":0,\"embedding\":[0.5,0.6]}],\"usage\":{\"total_tokens\":7}}";
        return Json(response);
    }

    private static HttpResponseMessage Rerank(JsonElement request)
    {
        var documents = request.GetProperty("documents").EnumerateArray().Select(static item => item.GetString()).ToArray();
        if (request.GetProperty("model").GetString() != "rerank-2.5"
            || request.GetProperty("query").GetString() != "Which text mentions water?"
            || request.GetProperty("top_k").GetInt32() != 1
            || !documents.SequenceEqual(["A quiet river bends through the valley.", "A lighthouse watches the harbor."]))
        {
            throw new InvalidOperationException("Voyage rerank request lost caller values or native top_k.");
        }

        return Json("{\"data\":[{\"index\":1,\"relevance_score\":0.1}],\"usage\":{\"total_tokens\":7}}");
    }

    private static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };
}
