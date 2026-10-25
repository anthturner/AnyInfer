using AnyInfer.Capabilities;

namespace AnyInfer.Examples;

/// <summary>
/// Routes embedding and rerank calls through their own default routes and keeps query vectors in the
/// stored index's embedding space.
/// </summary>
public static class EmbeddingSpaceExample
{
    // --8<-- [start:client]
    /// <summary>Creates a client whose embedding and rerank calls need no target.</summary>
    /// <param name="providers">Provider instances, such as one TEI server per model.</param>
    /// <param name="embeddingTarget">The embedding <c>provider:model</c> target.</param>
    /// <param name="rerankTarget">The rerank <c>provider:model</c> target.</param>
    /// <returns>A client the caller owns and disposes.</returns>
    public static AsyncClient CreateClient(
        IEnumerable<ProviderSettings> providers,
        string embeddingTarget,
        string rerankTarget) =>
        new(
            providers,
            operationRoutes: new Dictionary<InferenceOperation, Route>
            {
                [InferenceOperation.Embedding] = new Route([embeddingTarget]),
                [InferenceOperation.Rerank] = new Route([rerankTarget]),
            });
    // --8<-- [end:client]

    // --8<-- [start:space]
    /// <summary>Embeds documents for an index through the client's embedding route.</summary>
    /// <param name="client">A client created by <see cref="CreateClient"/>.</param>
    /// <param name="documents">Texts to index, in order.</param>
    /// <param name="cancellationToken">Cancels the call.</param>
    /// <returns>The vectors and the <see cref="EmbeddingSpace"/> to store beside them.</returns>
    public static Task<EmbeddingResult> IndexAsync(
        AsyncClient client,
        IEnumerable<string> documents,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        return client.EmbedAsync(documents, cancellationToken: cancellationToken);
    }

    /// <summary>Embeds a query and fails unless its vector is comparable with the stored index.</summary>
    /// <param name="client">A client created by <see cref="CreateClient"/>.</param>
    /// <param name="query">The query text.</param>
    /// <param name="indexSpace">The space recorded when the index was built.</param>
    /// <param name="cancellationToken">Cancels the call.</param>
    /// <returns>The query vector, in a space compatible with <paramref name="indexSpace"/>.</returns>
    public static Task<EmbeddingResult> EmbedQueryAsync(
        AsyncClient client,
        string query,
        EmbeddingSpace indexSpace,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        return client.EmbedAsync(query, expectedSpace: indexSpace, cancellationToken: cancellationToken);
    }
    // --8<-- [end:space]

    // --8<-- [start:rerank]
    /// <summary>Reranks caller-identified candidates through the client's rerank route.</summary>
    /// <param name="client">A client created by <see cref="CreateClient"/>.</param>
    /// <param name="query">The query text.</param>
    /// <param name="candidates">Documents with application-owned identifiers.</param>
    /// <param name="cancellationToken">Cancels the call.</param>
    /// <returns>The candidate identifiers, best first.</returns>
    public static async Task<IReadOnlyList<string>> RankAsync(
        AsyncClient client,
        string query,
        IEnumerable<RerankDocument> candidates,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        var ranked = await client.RerankAsync(query, candidates, cancellationToken: cancellationToken);
        return ranked.Items
            .OrderByDescending(static item => item.Score)
            .Select(static item => item.DocumentId)
            .ToArray();
    }
    // --8<-- [end:rerank]
}
