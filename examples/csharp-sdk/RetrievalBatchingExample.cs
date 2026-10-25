namespace AnyInfer.Examples;

/// <summary>Embeds and reranks under a batch ceiling the application has verified for its deployment.</summary>
public static class RetrievalBatchingExample
{
    // --8<-- [start:embed]
    /// <summary>Embeds documents in provider requests no larger than a verified per-request ceiling.</summary>
    /// <param name="client">A client the caller owns and disposes.</param>
    /// <param name="target">An embedding <c>provider:model</c> target.</param>
    /// <param name="documents">Texts to embed, in order.</param>
    /// <param name="verifiedMaxBatch">
    /// The deployment's per-request input ceiling, verified by the application, such as the
    /// <c>max_client_batch_size</c> a TEI server reports from <c>GET /info</c>.
    /// </param>
    /// <param name="cancellationToken">Cancels every batch, including pending retries.</param>
    /// <returns>One vector per document, in document order, whichever batch carried it.</returns>
    public static Task<EmbeddingResult> EmbedAsync(
        AsyncClient client,
        string target,
        IReadOnlyList<string> documents,
        int verifiedMaxBatch,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        return client.EmbedAsync(
            documents,
            target: target,
            batch: new BatchPolicy(maxConcurrency: 2, maxItemsOverride: verifiedMaxBatch),
            cancellationToken: cancellationToken);
    }
    // --8<-- [end:embed]

    // --8<-- [start:rerank]
    /// <summary>
    /// Reranks more documents than one request may carry, accepting rankings whose scores are comparable
    /// only within each batch.
    /// </summary>
    /// <param name="client">A client the caller owns and disposes.</param>
    /// <param name="target">A rerank <c>provider:model</c> target.</param>
    /// <param name="query">The query to rank against.</param>
    /// <param name="documents">Caller-identified documents, in order.</param>
    /// <param name="verifiedMaxBatch">The deployment's verified per-request document ceiling.</param>
    /// <param name="cancellationToken">Cancels every batch, including pending retries.</param>
    /// <returns>Chunk-local rankings, concatenated, with a warning that says so.</returns>
    public static Task<RerankResult> RerankAcrossBatchesAsync(
        AsyncClient client,
        string target,
        string query,
        IReadOnlyList<RerankDocument> documents,
        int verifiedMaxBatch,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        return client.RerankAsync(
            query,
            documents,
            target: target,
            batch: new BatchPolicy(maxItemsOverride: verifiedMaxBatch, rerankCrossBatch: true),
            cancellationToken: cancellationToken);
    }
    // --8<-- [end:rerank]
}
