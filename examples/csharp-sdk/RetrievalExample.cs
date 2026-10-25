using AnyInfer.Providers;

namespace AnyInfer.Examples;

/// <summary>Runs buffered text embedding and reranking through an application-owned retrieval adapter.</summary>
public static class RetrievalExample
{
    /// <summary>Embeds two texts and reranks two caller-identified documents with an asynchronous client.</summary>
    public static async Task<RetrievalObservation> RunAsync(
        ProviderSettings settings,
        ProviderRegistry registry,
        string target,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentNullException.ThrowIfNull(registry);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);

        await using var client = new AsyncClient([settings], registry: registry, manifests: true);
        var embeddings = await client.EmbedAsync(
            ["A quiet river bends through the valley.", "A lighthouse watches the harbor."],
            target: target,
            cancellationToken: cancellationToken,
            manifest: true);
        var reranking = await client.RerankAsync(
            "Which text mentions water?",
            [
                new RerankDocument("river", "A quiet river bends through the valley."),
                new RerankDocument("lighthouse", "A lighthouse watches the harbor."),
            ],
            target: target,
            returnDocuments: true,
            cancellationToken: cancellationToken,
            manifest: true);
        return new RetrievalObservation(embeddings, reranking);
    }

    /// <summary>Embeds two texts and reranks two caller-identified documents with a synchronous client.</summary>
    public static RetrievalObservation Run(
        ProviderSettings settings,
        ProviderRegistry registry,
        string target,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentNullException.ThrowIfNull(registry);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);

        using var client = new Client([settings], registry: registry, manifests: true);
        var embeddings = client.Embed(
            ["A quiet river bends through the valley.", "A lighthouse watches the harbor."],
            target: target,
            cancellationToken: cancellationToken,
            manifest: true);
        var reranking = client.Rerank(
            "Which text mentions water?",
            [
                new RerankDocument("river", "A quiet river bends through the valley."),
                new RerankDocument("lighthouse", "A lighthouse watches the harbor."),
            ],
            target: target,
            returnDocuments: true,
            cancellationToken: cancellationToken,
            manifest: true);
        return new RetrievalObservation(embeddings, reranking);
    }
}

/// <summary>Contains the public results of one embedding and reranking sequence.</summary>
public sealed record RetrievalObservation(EmbeddingResult Embeddings, RerankResult Reranking);
