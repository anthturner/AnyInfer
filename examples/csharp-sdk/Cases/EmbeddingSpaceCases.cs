using AnyInfer.Capabilities;
using AnyInfer.Providers;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts the operation-route and embedding-space recipe against two TEI instances.</summary>
internal static class EmbeddingSpaceCases
{
    private const string EmbedTarget = "tei-embed:BAAI/bge-small-en-v1.5";
    private const string RerankTarget = "tei-rerank:BAAI/bge-reranker-base";

    /// <summary>Embedding and rerank calls without a target use their operation routes; a matching query space is accepted.</summary>
    [ExampleCase("embedding-space.operation-routes")]
    internal static async Task OperationRoutes()
    {
        var embed = new RecipeTeiHandler();
        var rerank = new RecipeTeiHandler();
        await using (var client = EmbeddingSpaceExample.CreateClient([Embedder(embed), Reranker(rerank)], EmbedTarget, RerankTarget))
        {
            var index = await EmbeddingSpaceExample.IndexAsync(client, ["A river carries water.", "A road crosses the plain."]);
            var query = await EmbeddingSpaceExample.EmbedQueryAsync(client, "Where is water?", index.Space);
            var ranked = await EmbeddingSpaceExample.RankAsync(
                client,
                "Where is water?",
                [new RerankDocument("road", "A road crosses the plain."), new RerankDocument("river", "A river carries water.")]);
            ExampleSupport.Require(
                index.Target is { ProviderId: "tei-embed", Model: "BAAI/bge-small-en-v1.5" }
                && index.Space.CompatibleWith(query.Space)
                && query.Vectors.Single().Values.SequenceEqual([15.0, 63])
                && ranked.SequenceEqual(["river", "road"]),
                "Operation routes did not serve embedding and rerank calls, or the query space did not match the index.");
            var generation = await RecipeSupport.CaptureAsync(() => client.GenerateAsync("Say hello."));
            ExampleSupport.Require(
                generation is ConfigException,
                "A generation call without a target or default route used a retrieval operation route.");
        }

        ExampleSupport.Require(
            embed.Paths.SequenceEqual(["/embed", "/embed"])
            && rerank.Paths.SequenceEqual(["/rerank"])
            && embed.Disposals == 1
            && rerank.Disposals == 1,
            "The embedding and rerank routes did not reach their own TEI instances.");
    }

    /// <summary>A query whose result is not in the stored index's space fails instead of returning incomparable vectors.</summary>
    [ExampleCase("embedding-space.incompatible-space")]
    internal static async Task IncompatibleSpace()
    {
        var embed = new RecipeTeiHandler();
        await using (var client = EmbeddingSpaceExample.CreateClient([Embedder(embed)], EmbedTarget, RerankTarget))
        {
            var otherIndex = new EmbeddingSpace("hosted-index", "another-embedding-model", dimensions: 2);
            var failure = await RecipeSupport.CaptureAsync(() =>
                EmbeddingSpaceExample.EmbedQueryAsync(client, "Where is water?", otherIndex));
            ExampleSupport.Require(
                failure is ConfigException && embed.Requests == 1,
                "Vectors returned in an incompatible space were not refused with ConfigException after the request.");
            ExampleSupport.Require(
                new EmbeddingSpace("a", "m", compatibilityId: "corpus-v1").CompatibleWith(new EmbeddingSpace("b", "n", compatibilityId: "corpus-v1"))
                && !new EmbeddingSpace("a", "m", modelRevision: "r1").CompatibleWith(new EmbeddingSpace("a", "m", modelRevision: "r2")),
                "EmbeddingSpace compatibility did not follow the asserted identity or the revision rule.");
        }

        ExampleSupport.Require(embed.Disposals == 1, "The client did not dispose its TEI transport once.");
        var rejected = RecipeSupport.Capture(() => _ = new AsyncClient(
            operationRoutes: new Dictionary<InferenceOperation, Route> { [InferenceOperation.Generation] = new Route(["tei-embed:x"]) }));
        ExampleSupport.Require(rejected is ArgumentException, "A generation operation route was accepted.");
    }

    /// <summary>Fallback to another instance is refused unless incompatible fallback is allowed, which then warns.</summary>
    [ExampleCase("embedding-space.incompatible-fallback")]
    internal static async Task IncompatibleFallback()
    {
        var failing = new RecipeTeiHandler(failText: "A river carries water.");
        var other = new RecipeTeiHandler();
        await using (var client = new AsyncClient(
        [
            Embedder(failing),
            ProviderSettings.Of("tei", "http://127.0.0.1:8090", transport: other, alias: "tei-other"),
        ]))
        {
            var route = new Route(["tei-embed:m", "tei-other:m"]);
            var refused = await RecipeSupport.CaptureAsync(() => client.EmbedAsync("A river carries water.", route: route));
            ExampleSupport.Require(
                refused is ConfigException && failing.Requests == 1 && other.Requests == 0,
                "Fallback to a different embedding instance was not refused before its request.");

            var allowed = await client.EmbedAsync("A river carries water.", route: route, allowIncompatibleFallback: true);
            ExampleSupport.Require(
                allowed.Target.ProviderId == "tei-other" && allowed.Warnings.Count == 1 && other.Requests == 1,
                "Allowed incompatible fallback did not serve the second instance with a warning.");
        }
    }

    private static ProviderSettings Embedder(HttpMessageHandler transport) =>
        ProviderSettings.Of("tei", "http://127.0.0.1:8080", transport: transport, alias: "tei-embed");

    private static ProviderSettings Reranker(HttpMessageHandler transport) =>
        ProviderSettings.Of("tei", "http://127.0.0.1:8081", transport: transport, alias: "tei-rerank");
}
