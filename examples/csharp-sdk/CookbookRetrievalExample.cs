using AnyInfer.Capabilities;

namespace AnyInfer.Examples;

/// <summary>
/// A help-center search: embed a corpus under caller-owned document IDs, shortlist candidates for a
/// query by cosine similarity in the application's own index, then rerank the shortlist.
/// </summary>
public static class CookbookRetrievalExample
{
    /// <summary>Two local Text Embeddings Inference servers, one per model, as TEI serves one model per process.</summary>
    public static CookbookRetrievalDeployment Tei { get; } = new(
        [
            ProviderSettings.Of("tei", "http://127.0.0.1:8080", alias: "tei-embed"),
            ProviderSettings.Of("tei", "http://127.0.0.1:8081", alias: "tei-rerank"),
        ],
        "tei-embed:BAAI/bge-small-en-v1.5",
        "tei-rerank:BAAI/bge-reranker-base");

    /// <summary>Hosted Voyage AI for both operations; the key stays an environment reference.</summary>
    public static CookbookRetrievalDeployment Voyage { get; } = new(
        [ProviderSettings.Of("voyage", apiKey: "env://VOYAGE_API_KEY")],
        "voyage:voyage-3.5-lite",
        "voyage:rerank-2.5");

    /// <summary>Hosted Jina AI for both operations; the key stays an environment reference.</summary>
    public static CookbookRetrievalDeployment Jina { get; } = new(
        [ProviderSettings.Of("jina", apiKey: "env://JINA_API_KEY")],
        "jina:jina-embeddings-v5-text-small",
        "jina:jina-reranker-v3");

    /// <summary>Indexes a corpus and answers one query against it with a single client.</summary>
    /// <param name="deployment">The provider instances and the embedding and rerank targets.</param>
    /// <param name="corpus">Passages to index; their IDs are the application's own.</param>
    /// <param name="query">The search query.</param>
    /// <param name="maxBatchInputs">A per-request input ceiling the application has verified for its deployment.</param>
    /// <param name="output">Where the results are written, such as <see cref="Console.Out"/>.</param>
    /// <param name="cancellationToken">Cancels indexing and search, including internal batches.</param>
    /// <returns>The index that was built and the reranked results.</returns>
    public static async Task<(CookbookPassageIndex Index, CookbookSearchResult Result)> RunAsync(
        CookbookRetrievalDeployment deployment,
        IReadOnlyList<CookbookPassage> corpus,
        string query,
        int maxBatchInputs,
        TextWriter output,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(deployment);
        ArgumentNullException.ThrowIfNull(output);
        await using var client = new AsyncClient(deployment.Providers);
        var index = await BuildIndexAsync(client, deployment.EmbeddingTarget, corpus, maxBatchInputs, cancellationToken).ConfigureAwait(false);
        var result = await SearchAsync(client, index, deployment.EmbeddingTarget, deployment.RerankTarget, query, candidates: 3, topN: 2, cancellationToken).ConfigureAwait(false);
        await output.WriteLineAsync($"indexed {index.Entries.Count} passages in {index.Requests} request(s), space {index.Space.ProviderId}/{index.Space.Model} ({index.Space.Dimensions} dims)").ConfigureAwait(false);
        foreach (var warning in index.Warnings)
        {
            await output.WriteLineAsync($"warning: {warning}").ConfigureAwait(false);
        }

        foreach (var hit in result.Hits)
        {
            await output.WriteLineAsync($"{hit.PassageId}  rerank {hit.RerankScore:F2}  cosine {hit.Cosine:F2}").ConfigureAwait(false);
        }

        return (index, result);
    }

    /// <summary>Embeds every passage as a document and keeps each vector under its passage's own ID.</summary>
    /// <param name="client">The client that owns the provider instances.</param>
    /// <param name="embeddingTarget">The <c>provider:model</c> embedding target.</param>
    /// <param name="corpus">Passages to index.</param>
    /// <param name="maxBatchInputs">The verified per-request input ceiling; larger inputs are split by the SDK.</param>
    /// <param name="cancellationToken">Cancels the operation, including pending batches.</param>
    /// <returns>An in-memory index that records the embedding space its vectors belong to.</returns>
    public static async Task<CookbookPassageIndex> BuildIndexAsync(
        AsyncClient client,
        string embeddingTarget,
        IReadOnlyList<CookbookPassage> corpus,
        int maxBatchInputs,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        ArgumentNullException.ThrowIfNull(corpus);
        var embedded = await client.EmbedAsync(
            corpus.Select(static passage => passage.Text),
            target: embeddingTarget,
            inputType: EmbeddingInputIntent.Document,
            batch: new BatchPolicy(maxConcurrency: 2, maxItemsOverride: maxBatchInputs),
            cancellationToken: cancellationToken).ConfigureAwait(false);

        // Vectors come back in input order across every internal batch, so IDs pair by position.
        var entries = corpus.Zip(embedded.Vectors, static (passage, vector) => new CookbookIndexEntry(passage, vector.Values)).ToArray();
        return new CookbookPassageIndex(embedded.Space, entries, embedded.Attempts.Count, embedded.Usage, embedded.Warnings);
    }

    /// <summary>Embeds the query in the index's space, shortlists by cosine similarity, and reranks the shortlist.</summary>
    /// <param name="client">The client that owns the provider instances.</param>
    /// <param name="index">The index to search.</param>
    /// <param name="embeddingTarget">The embedding target; its space must be compatible with the index's.</param>
    /// <param name="rerankTarget">The <c>provider:model</c> rerank target.</param>
    /// <param name="query">The search query.</param>
    /// <param name="candidates">How many nearest passages to send to the reranker.</param>
    /// <param name="topN">How many reranked passages to return.</param>
    /// <param name="cancellationToken">Cancels both calls.</param>
    /// <returns>The reranked passages, best first, under their own IDs.</returns>
    /// <exception cref="ConfigException">The query embedding's space is not compatible with the index's.</exception>
    public static async Task<CookbookSearchResult> SearchAsync(
        AsyncClient client,
        CookbookPassageIndex index,
        string embeddingTarget,
        string rerankTarget,
        string query,
        int candidates,
        int topN,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        ArgumentNullException.ThrowIfNull(index);
        var probe = await client.EmbedAsync(
            query,
            target: embeddingTarget,
            inputType: EmbeddingInputIntent.Query,
            expectedSpace: index.Space,
            cancellationToken: cancellationToken).ConfigureAwait(false);
        var shortlist = index.Entries
            .Select(entry => (entry.Passage, Cosine: Cosine(probe.Vectors[0].Values, entry.Vector)))
            .OrderByDescending(static candidate => candidate.Cosine)
            .Take(candidates)
            .ToDictionary(static candidate => candidate.Passage.Id, static candidate => candidate.Cosine, StringComparer.Ordinal);

        var ranked = await client.RerankAsync(
            query,
            index.Entries.Where(entry => shortlist.ContainsKey(entry.Passage.Id))
                .Select(static entry => new RerankDocument(entry.Passage.Id, entry.Passage.Text)),
            target: rerankTarget,
            topN: topN,
            cancellationToken: cancellationToken).ConfigureAwait(false);
        var hits = ranked.Items.Select(item => new CookbookSearchHit(item.DocumentId, item.Score, shortlist[item.DocumentId])).ToArray();
        return new CookbookSearchResult(hits, probe.Usage, ranked.Usage);
    }

    private static double Cosine(IReadOnlyList<double> left, IReadOnlyList<double> right)
    {
        double dot = 0, leftNorm = 0, rightNorm = 0;
        for (var i = 0; i < left.Count; i++)
        {
            dot += left[i] * right[i];
            leftNorm += left[i] * left[i];
            rightNorm += right[i] * right[i];
        }

        return dot / (Math.Sqrt(leftNorm) * Math.Sqrt(rightNorm));
    }
}

/// <summary>The provider instances and targets one retrieval deployment uses.</summary>
/// <param name="Providers">The configured provider instances.</param>
/// <param name="EmbeddingTarget">The <c>provider:model</c> embedding target.</param>
/// <param name="RerankTarget">The <c>provider:model</c> rerank target.</param>
public sealed record CookbookRetrievalDeployment(
    IReadOnlyList<ProviderSettings> Providers,
    string EmbeddingTarget,
    string RerankTarget);

/// <summary>One passage under the application's own identifier.</summary>
/// <param name="Id">The application's passage ID.</param>
/// <param name="Text">The passage text.</param>
public sealed record CookbookPassage(string Id, string Text);

/// <summary>One indexed passage and its vector.</summary>
/// <param name="Passage">The passage.</param>
/// <param name="Vector">Its embedding, in the index's space.</param>
public sealed record CookbookIndexEntry(CookbookPassage Passage, IReadOnlyList<double> Vector);

/// <summary>An application-owned in-memory vector index.</summary>
/// <param name="Space">The embedding space every vector in the index belongs to.</param>
/// <param name="Entries">The indexed passages, in corpus order.</param>
/// <param name="Requests">How many provider requests indexing took.</param>
/// <param name="Usage">Reported usage summed over those requests; unreported counts stay unknown.</param>
/// <param name="Warnings">Nonfatal warnings the SDK reported while indexing.</param>
public sealed record CookbookPassageIndex(
    EmbeddingSpace Space,
    IReadOnlyList<CookbookIndexEntry> Entries,
    int Requests,
    Usage Usage,
    IReadOnlyList<string> Warnings);

/// <summary>One search hit.</summary>
/// <param name="PassageId">The application's passage ID.</param>
/// <param name="RerankScore">The reranker's relevance score.</param>
/// <param name="Cosine">The shortlist cosine similarity.</param>
public sealed record CookbookSearchHit(string PassageId, double RerankScore, double Cosine);

/// <summary>The reranked results for one query.</summary>
/// <param name="Hits">Reranked passages, best first.</param>
/// <param name="QueryUsage">Reported usage of the query embedding.</param>
/// <param name="RerankUsage">Reported usage of the rerank call.</param>
public sealed record CookbookSearchResult(IReadOnlyList<CookbookSearchHit> Hits, Usage QueryUsage, Usage RerankUsage);
