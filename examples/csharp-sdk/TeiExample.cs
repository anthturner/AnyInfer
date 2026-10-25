using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer.Config;

namespace AnyInfer.Examples;

/// <summary>Exercises the built-in native Text Embeddings Inference retrieval provider.</summary>
public static class TeiExample
{
    /// <summary>Creates settings for the embedding TEI instance used by this offline example.</summary>
    public static ProviderSettings EmbeddingSettings(HttpMessageHandler transport) =>
        ProviderSettings.Of("tei", "https://tei-embed.offline/v1", transport: transport, alias: "tei-embed");

    /// <summary>Creates settings for the reranking TEI instance used by this offline example.</summary>
    public static ProviderSettings RerankSettings(HttpMessageHandler transport) =>
        ProviderSettings.Of("tei", "https://tei-rerank.offline/v1", transport: transport, alias: "tei-rerank");

    /// <summary>Runs embedding and reranking through the default registry with an asynchronous client.</summary>
    public static async Task<TeiObservation> RunAsync(
        ProviderSettings embeddingSettings,
        ProviderSettings rerankSettings,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([embeddingSettings, rerankSettings], manifests: true);
        return await RunAsync(client, cancellationToken);
    }

    /// <summary>Runs embedding and reranking through the default registry with the synchronous facade.</summary>
    public static TeiObservation Run(
        ProviderSettings embeddingSettings,
        ProviderSettings rerankSettings,
        CancellationToken cancellationToken = default)
    {
        using var client = new Client([embeddingSettings, rerankSettings], manifests: true);
        return Run(client, cancellationToken);
    }

    private static async Task<TeiObservation> RunAsync(AsyncClient client, CancellationToken cancellationToken)
    {
        var embeddings = await client.EmbedAsync(
            ["A quiet river bends through the valley.", "A lighthouse watches the harbor."],
            target: "tei-embed:embed-model",
            retainRaw: true,
            cancellationToken: cancellationToken,
            manifest: true);
        var reranking = await client.RerankAsync(
            "Which text mentions water?",
            [
                new RerankDocument("river", "A quiet river bends through the valley."),
                new RerankDocument("lighthouse", "A lighthouse watches the harbor."),
            ],
            target: "tei-rerank:rerank-model",
            returnDocuments: true,
            retainRaw: true,
            cancellationToken: cancellationToken,
            manifest: true);
        return new TeiObservation(embeddings, reranking);
    }

    private static TeiObservation Run(Client client, CancellationToken cancellationToken)
    {
        var embeddings = client.Embed(
            ["A quiet river bends through the valley.", "A lighthouse watches the harbor."],
            target: "tei-embed:embed-model",
            retainRaw: true,
            cancellationToken: cancellationToken,
            manifest: true);
        var reranking = client.Rerank(
            "Which text mentions water?",
            [
                new RerankDocument("river", "A quiet river bends through the valley."),
                new RerankDocument("lighthouse", "A lighthouse watches the harbor."),
            ],
            target: "tei-rerank:rerank-model",
            returnDocuments: true,
            retainRaw: true,
            cancellationToken: cancellationToken,
            manifest: true);
        return new TeiObservation(embeddings, reranking);
    }
}

/// <summary>Contains the public results from the native TEI embedding and reranking calls.</summary>
public sealed record TeiObservation(EmbeddingResult Embeddings, RerankResult Reranking);

/// <summary>Scripted HTTP transport that validates the literal native TEI requests used by the example.</summary>
public sealed class TeiScriptedHandler(bool reranker) : HttpMessageHandler
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
            || request.RequestUri?.AbsolutePath != (reranker ? "/v1/rerank" : "/v1/embed")
            || request.Headers.Accept.Single().MediaType != "application/json"
            || request.Content?.Headers.ContentType?.MediaType != "application/json")
        {
            throw new InvalidOperationException("TEI example used unexpected HTTP transport fields.");
        }

        if (!reranker)
        {
            var inputs = json.RootElement.GetProperty("inputs").EnumerateArray().Select(static item => item.GetString()).ToArray();
            if (!inputs.SequenceEqual(["A quiet river bends through the valley.", "A lighthouse watches the harbor."]))
                throw new InvalidOperationException("TEI embedding request lost caller input order.");
            return Json("[[0.1,0.2],[0.3,0.4]]");
        }

        var texts = json.RootElement.GetProperty("texts").EnumerateArray().Select(static item => item.GetString()).ToArray();
        if (json.RootElement.GetProperty("query").GetString() != "Which text mentions water?"
            || !texts.SequenceEqual(["A quiet river bends through the valley.", "A lighthouse watches the harbor."])
            || json.RootElement.GetProperty("return_text").GetBoolean())
        {
            throw new InvalidOperationException("TEI rerank request lost caller values.");
        }
        return Json("[{\"index\":1,\"score\":0.1},{\"index\":0,\"score\":0.9}]");
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }

    private static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };
}
