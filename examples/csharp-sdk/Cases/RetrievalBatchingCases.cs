namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts the retrieval batching recipe against the built-in TEI descriptor.</summary>
internal static class RetrievalBatchingCases
{
    private const string EmbedTarget = "tei-embed:BAAI/bge-small-en-v1.5";
    private const string RerankTarget = "tei-rerank:BAAI/bge-reranker-base";
    private static readonly string[] Documents = ["doc-a", "doc-bb", "doc-ccc", "doc-dddd", "doc-eeeee"];

    /// <summary>TEI hydrates no batch ceiling, so the default policy sends every input in one request.</summary>
    [ExampleCase("retrieval-batching.unknown-ceiling-is-one-request")]
    internal static async Task UnknownCeilingIsOneRequest()
    {
        var transport = new RecipeTeiHandler();
        await using (var client = new AsyncClient([TeiExample.EmbeddingSettings(transport)]))
        {
            var result = await client.EmbedAsync(Documents, target: "tei-embed:embed-model");
            ExampleSupport.Require(
                result.Vectors.Count == 5 && result.Warnings.Count == 0 && result.Attempts.Count == 1,
                "An embedding request with an unknown ceiling did not stay one bounded request.");
        }

        ExampleSupport.Require(
            transport.Requests == 1 && transport.Batches.Single().SequenceEqual(Documents) && transport.Disposals == 1,
            "An unknown provider ceiling caused guessed splitting.");
    }

    /// <summary>A verified ceiling splits the inputs into ordered batches and returns vectors in input order.</summary>
    [ExampleCase("retrieval-batching.verified-ceiling-splits")]
    internal static async Task VerifiedCeilingSplits()
    {
        var transport = new RecipeTeiHandler();
        await using (var client = new AsyncClient([Embedder(transport)]))
        {
            var result = await RetrievalBatchingExample.EmbedAsync(client, EmbedTarget, Documents, verifiedMaxBatch: 2);
            ExampleSupport.Require(
                result.Vectors.Select(static vector => vector.Values[0]).SequenceEqual([5.0, 6, 7, 8, 9])
                && result.Space is { ProviderId: "tei-embed", Model: "BAAI/bge-small-en-v1.5", Dimensions: 2 }
                && result.Usage.InputTokens is null,
                "Batched vectors were not returned in input order with one space and unknown usage.");
        }

        ExampleSupport.Require(
            transport.Requests == 3
            && transport.Batches.Select(static batch => batch.Length).Order().SequenceEqual([1, 2, 2])
            && transport.Batches.SelectMany(static batch => batch).Order(StringComparer.Ordinal).SequenceEqual(Documents)
            && transport.Disposals == 1,
            "A verified ceiling of two did not split five inputs into three requests.");
    }

    /// <summary>A failed batch fails the whole operation and records every batch's outcome.</summary>
    [ExampleCase("retrieval-batching.batch-failure")]
    internal static async Task BatchFailure()
    {
        var transport = new RecipeTeiHandler(failText: "doc-ccc");
        await using (var client = new AsyncClient([Embedder(transport)]))
        {
            var failure = await RecipeSupport.CaptureAsync(() =>
                RetrievalBatchingExample.EmbedAsync(client, EmbedTarget, Documents, verifiedMaxBatch: 2));
            ExampleSupport.Require(
                failure is AllTargetsFailedException { BatchFailures.Count: 3 } exhausted
                && exhausted.BatchFailures.Single(static batch => !batch.Succeeded) is { BatchIndex: 1, ItemCount: 2, Error: not null }
                && exhausted.BatchFailures.Sum(static batch => batch.ItemCount) == 5
                && exhausted.Attempts.Count(static attempt => attempt.Error is ProviderException { HttpStatus: 413 }) == 1
                && transport.Requests == 3,
                "A failed batch did not surface as AllTargetsFailedException with every batch outcome.");
        }

        ExampleSupport.Require(transport.Disposals == 1, "The failed batch client did not dispose its transport once.");
    }

    /// <summary>Splitting is refused when the policy forbids it, before any request is sent.</summary>
    [ExampleCase("retrieval-batching.split-refused")]
    internal static async Task SplitRefused()
    {
        var transport = new RecipeTeiHandler();
        await using (var client = new AsyncClient([Embedder(transport)]))
        {
            var failure = await RecipeSupport.CaptureAsync(() => client.EmbedAsync(
                Documents,
                target: EmbedTarget,
                batch: new BatchPolicy(maxItemsOverride: 2, allowSplit: false)));
            ExampleSupport.Require(
                failure is ConfigException && transport.Requests == 0,
                "A forbidden split was not refused with ConfigException before dispatch.");
        }

        var invalid = RecipeSupport.Capture(() => _ = new BatchPolicy(maxItemsOverride: 0));
        ExampleSupport.Require(invalid is ArgumentOutOfRangeException, "A zero batch ceiling was accepted.");
    }

    /// <summary>Reranking splits only with cross-batch opt-in, which keeps original indices and warns about scores.</summary>
    [ExampleCase("retrieval-batching.rerank-cross-batch")]
    internal static async Task RerankCrossBatch()
    {
        RerankDocument[] documents =
        [
            new("harbor", "A lighthouse watches the harbor."),
            new("river", "A river carries water to the sea."),
            new("road", "A road crosses the plain."),
        ];
        var transport = new RecipeTeiHandler();
        await using (var client = new AsyncClient([Reranker(transport)]))
        {
            var refused = await RecipeSupport.CaptureAsync(() => client.RerankAsync(
                "Which text mentions water?",
                documents,
                target: RerankTarget,
                batch: new BatchPolicy(maxItemsOverride: 2)));
            ExampleSupport.Require(
                refused is ConfigException && transport.Requests == 0,
                "A rerank split without cross-batch opt-in was not refused before dispatch.");

            var ranked = await RetrievalBatchingExample.RerankAcrossBatchesAsync(
                client, RerankTarget, "Which text mentions water?", documents, verifiedMaxBatch: 2);
            ExampleSupport.Require(
                ranked.Items.Count == 3
                && ranked.Items.Single(static item => item.DocumentId == "river") is { Index: 1, Score: 0.9 }
                && ranked.Items.Single(static item => item.DocumentId == "road") is { Index: 2, Score: 0.1 }
                && ranked.Warnings.Single().Contains("chunk-local", StringComparison.Ordinal),
                "Cross-batch reranking lost caller IDs or original indices, or did not warn about chunk-local scores.");
        }

        ExampleSupport.Require(
            transport.Requests == 2 && transport.Disposals == 1,
            "Cross-batch reranking of three documents did not send two batches.");
    }

    /// <summary>
    /// Voyage's declared 1,000-input ceiling splits without an override and refuses a larger rerank;
    /// Jina's unknown ceiling refuses more than 2,048 inputs locally.
    /// </summary>
    [ExampleCase("retrieval-batching.declared-and-unknown-ceilings")]
    internal static async Task DeclaredAndUnknownCeilings()
    {
        var inputs = Enumerable.Range(0, 1_001).Select(static index => $"text {index}").ToArray();
        var voyage = new RecipeHostedRetrievalHandler();
        await using (var client = new AsyncClient([VoyageExample.Settings(voyage, "offline-voyage-key")]))
        {
            var result = await client.EmbedAsync(inputs, target: "voyage-retrieval:voyage-3.5-lite");
            ExampleSupport.Require(
                result.Vectors.Count == 1_001
                && result.Vectors[1_000].Values[0] == 0
                && result.Vectors[999].Values[0] == 999
                && result.Usage.TotalTokens == 1_001
                && voyage.BatchSizes.Order().SequenceEqual([1, 1_000]),
                "Voyage's declared ceiling did not split 1,001 inputs into ordered batches of 1,000 and 1.");

            var rerank = await RecipeSupport.CaptureAsync(() => client.RerankAsync(
                "query",
                inputs.Select(static (text, index) => new RerankDocument($"d{index}", text)),
                target: "voyage-retrieval:rerank-2.5"));
            ExampleSupport.Require(
                rerank is ConfigException && voyage.Requests == 2,
                "A Voyage rerank over its declared 1,000-document ceiling was not refused before dispatch.");
        }

        var jina = new RecipeHostedRetrievalHandler();
        await using (var client = new AsyncClient([JinaExample.Settings(jina, "offline-jina-key")]))
        {
            var many = Enumerable.Range(0, 2_049).Select(static index => $"text {index}").ToArray();
            var refused = await RecipeSupport.CaptureAsync(() =>
                client.EmbedAsync(many, target: "jina-retrieval:jina-embeddings-v5-text-small"));
            var accepted = await client.EmbedAsync(many[..2_048], target: "jina-retrieval:jina-embeddings-v5-text-small");
            var rerank = await RecipeSupport.CaptureAsync(() => client.RerankAsync(
                "query",
                many[..1_001].Select(static (text, index) => new RerankDocument($"d{index}", text)),
                target: "jina-retrieval:jina-reranker-v3"));
            ExampleSupport.Require(
                refused is ConfigException
                && rerank is ConfigException
                && accepted.Vectors.Count == 2_048
                && jina.BatchSizes.SequenceEqual([2_048]),
                "Jina's unknown ceiling was guessed, or more than 2,048 inputs or 1,000 documents were not refused locally.");
        }
    }

    private static ProviderSettings Embedder(HttpMessageHandler transport) =>
        ProviderSettings.Of("tei", "http://127.0.0.1:8080", transport: transport, alias: "tei-embed");

    private static ProviderSettings Reranker(HttpMessageHandler transport) =>
        ProviderSettings.Of("tei", "http://127.0.0.1:8081", transport: transport, alias: "tei-rerank");
}
