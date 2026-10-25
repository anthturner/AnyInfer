using AnyInfer.Capabilities;

namespace AnyInfer.Examples;

/// <summary>
/// Configures the two local TEI server processes, discovers the model each one serves, and embeds and
/// reranks with the discovered identifiers.
/// </summary>
public static class TeiServersExample
{
    // --8<-- [start:servers]
    /// <summary>Creates settings for an embedding server on port 8080 and a reranking server on port 8081.</summary>
    /// <param name="apiKey">
    /// A credential reference such as <c>env://TEI_API_KEY</c>, only when the servers were started with an API
    /// key; <see langword="null"/> sends no Authorization header.
    /// </param>
    /// <returns>Two provider instances, <c>tei-embed</c> and <c>tei-rerank</c>.</returns>
    public static ProviderSettings[] LocalServers(string? apiKey = null) =>
    [
        ProviderSettings.Of("tei", "http://127.0.0.1:8080", apiKey: apiKey, alias: "tei-embed"),
        ProviderSettings.Of("tei", "http://127.0.0.1:8081", apiKey: apiKey, alias: "tei-rerank"),
    ];
    // --8<-- [end:servers]

    // --8<-- [start:discover]
    /// <summary>Discovers each server's model, then embeds documents and reranks them against a query.</summary>
    /// <param name="servers">Settings from <see cref="LocalServers"/>.</param>
    /// <param name="query">The query to rank against.</param>
    /// <param name="documents">Caller-identified documents.</param>
    /// <param name="cancellationToken">Cancels every call.</param>
    /// <returns>
    /// The discovered models and both results, or <see langword="null"/> results when a server does not serve
    /// the expected kind of model.
    /// </returns>
    public static async Task<TeiServersObservation> RunAsync(
        IEnumerable<ProviderSettings> servers,
        string query,
        IReadOnlyList<RerankDocument> documents,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient(servers);

        // GET /info reports the one model a TEI process serves and whether it embeds or reranks.
        var embedder = (await client.ModelsAsync("tei-embed", InferenceOperation.Embedding, cancellationToken)
            .ConfigureAwait(false)).FirstOrDefault()?.Id;
        var reranker = (await client.ModelsAsync("tei-rerank", InferenceOperation.Rerank, cancellationToken)
            .ConfigureAwait(false)).FirstOrDefault()?.Id;
        if (embedder is null || reranker is null)
        {
            return new TeiServersObservation(embedder, reranker, Embeddings: null, Ranking: null);
        }

        var embeddings = await client.EmbedAsync(
            documents.Select(static document => document.Text),
            target: $"tei-embed:{embedder}",
            cancellationToken: cancellationToken).ConfigureAwait(false);
        var ranking = await client.RerankAsync(
            query,
            documents,
            target: $"tei-rerank:{reranker}",
            topN: 2,
            cancellationToken: cancellationToken).ConfigureAwait(false);
        return new TeiServersObservation(embedder, reranker, embeddings, ranking);
    }
    // --8<-- [end:discover]
}

/// <summary>Contains the discovered TEI models and the results computed with them.</summary>
public sealed record TeiServersObservation(
    string? EmbeddingModel,
    string? RerankModel,
    EmbeddingResult? Embeddings,
    RerankResult? Ranking);
