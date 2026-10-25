namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts the local TEI servers recipe with scripted GET /info, embed, and rerank responses.</summary>
internal static class TeiServersCases
{
    private const string EmbedInfo = """
        {"model_id":"BAAI/bge-small-en-v1.5","model_sha":"5c38ec7c405ec4b44b94cc5a9bb96e735b38267a","model_dtype":"float32",
         "model_type":{"embedding":{"pooling":"cls"}},"max_concurrent_requests":512,"max_input_length":512,
         "max_batch_tokens":16384,"max_client_batch_size":2,"version":"1.9.4"}
        """;

    private const string RerankInfo = """
        {"model_id":"BAAI/bge-reranker-base","model_sha":"2cfc18c9415c912f9d8155881c133215df768a70","model_dtype":"float32",
         "model_type":{"reranker":{"id2label":{"0":"LABEL_0"},"label2id":{"LABEL_0":0}}},"max_concurrent_requests":512,
         "max_input_length":512,"max_batch_tokens":16384,"max_client_batch_size":2,"version":"1.9.4"}
        """;

    private static readonly RerankDocument[] Documents =
    [
        new("road", "A road crosses the plain."),
        new("river", "A river carries water to the sea."),
        new("harbor", "A lighthouse watches the harbor water."),
    ];

    /// <summary>Discovery names each server's model; calls use it, unknown usage stays unknown, and /info limits are not hydrated.</summary>
    [ExampleCase("tei-servers.discover-and-call")]
    internal static async Task DiscoverAndCall()
    {
        var embed = new RecipeTeiHandler(info: EmbedInfo);
        var rerank = new RecipeTeiHandler(info: RerankInfo);
        var servers = TeiServersExample.LocalServers();
        var observation = await TeiServersExample.RunAsync(
            [ExampleSupport.WithTransport(servers[0], embed), ExampleSupport.WithTransport(servers[1], rerank)],
            "Which text mentions water?",
            Documents);
        ExampleSupport.Require(
            observation.EmbeddingModel == "BAAI/bge-small-en-v1.5"
            && observation.RerankModel == "BAAI/bge-reranker-base"
            && observation.Embeddings is { Vectors.Count: 3, Target.Model: "BAAI/bge-small-en-v1.5" } embeddings
            && embeddings.Space is { ProviderId: "tei-embed", Normalized: true, Dimensions: 2 }
            && embeddings.Usage is { InputTokens: null, OutputTokens: null, TotalTokens: null, CostUsd: null }
            && observation.Ranking is { Items.Count: 2 } ranking
            && ranking.Items.Select(static item => item.DocumentId).SequenceEqual(["river", "harbor"])
            && ranking.Items.Select(static item => item.Index).SequenceEqual([1, 2])
            && ranking.Usage is { InputTokens: null, CostUsd: null },
            "Discovered TEI models were not used, or usage, space, caller IDs, or client-side top_n were wrong.");
        ExampleSupport.Require(
            embed.Paths.SequenceEqual(["/info", "/embed"])
            && rerank.Paths.SequenceEqual(["/info", "/rerank"])
            && embed.Batches.Single().Length == 3
            && embed.Disposals == 1
            && rerank.Disposals == 1,
            "The recipe did not send one discovery request and one unsplit operation request to each server.");
        ExampleSupport.Require(
            servers.All(static settings => settings.ApiKey is null)
            && TeiServersExample.LocalServers("env://TEI_API_KEY").All(static settings => settings.ApiKey == "env://TEI_API_KEY"),
            "The local server settings did not keep the optional key reference unresolved.");
    }

    /// <summary>A server started with the other kind of model is filtered out of discovery, and nothing else is sent.</summary>
    [ExampleCase("tei-servers.wrong-model-kind")]
    internal static async Task WrongModelKind()
    {
        var embed = new RecipeTeiHandler(info: RerankInfo);
        var rerank = new RecipeTeiHandler(info: RerankInfo);
        var servers = TeiServersExample.LocalServers();
        var observation = await TeiServersExample.RunAsync(
            [ExampleSupport.WithTransport(servers[0], embed), ExampleSupport.WithTransport(servers[1], rerank)],
            "Which text mentions water?",
            Documents);
        ExampleSupport.Require(
            observation is { EmbeddingModel: null, RerankModel: "BAAI/bge-reranker-base", Embeddings: null, Ranking: null }
            && embed.Paths.SequenceEqual(["/info"])
            && rerank.Paths.SequenceEqual(["/info"]),
            "A reranker on the embedding port was not filtered out before any operation request.");
    }
}
