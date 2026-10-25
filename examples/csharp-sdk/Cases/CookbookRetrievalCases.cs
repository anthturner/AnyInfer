using System.Collections.Concurrent;
using System.Net;
using System.Text;
using System.Text.Json;

namespace AnyInfer.Examples.Cases;

/// <summary>Runs the help-center search against offline TEI-, Voyage- and Jina-shaped servers.</summary>
internal static class CookbookRetrievalCases
{
    private const string Query = "My delivery was late, can I get a refund?";

    private static readonly CookbookPassage[] Corpus =
    [
        new("kb-refunds", "Refunds are issued to the original payment method within five business days."),
        new("kb-late", "If a delivery arrives late, request a refund for the shipping charge from the order page."),
        new("kb-courier", "Our courier partners deliver Monday to Saturday; tracking updates hourly."),
        new("kb-password", "Reset your password from the login page; the link expires after one hour."),
        new("kb-invoices", "Invoices and receipts are available under Billing for twelve months."),
    ];

    [ExampleCase("cookbook.retrieval.tei-batched-index-and-rerank")]
    internal static async Task TeiBatchedIndexAndRerank()
    {
        var embedServer = new CookbookRetrievalServer();
        var rerankServer = new CookbookRetrievalServer();
        var deployment = Offline(CookbookRetrievalExample.Tei, ("tei-embed", embedServer), ("tei-rerank", rerankServer));
        var output = new StringWriter();

        var (index, result) = await CookbookRetrievalExample.RunAsync(deployment, Corpus, Query, maxBatchInputs: 2, output);

        RequireRanking(index, result, "tei-embed", "BAAI/bge-small-en-v1.5");
        // TEI publishes no batch ceiling, so only the caller's verified limit split the corpus: 2 + 2 + 1.
        // The shortlist reaches the reranker in corpus order; the caller's IDs map the scores back.
        ExampleSupport.Require(index.Requests == 3
            && embedServer.EmbedBatches.OrderBy(static size => size).SequenceEqual([1, 1, 2, 2])
            && embedServer.Paths.All(static path => path == "/embed")
            && rerankServer.Paths.SequenceEqual(["/rerank"])
            && rerankServer.RerankDocuments.Single().SequenceEqual(Corpus.Take(3).Select(static passage => passage.Text))
            && index.Usage.TotalTokens is null
            && result.RerankUsage.TotalTokens is null
            && index.Warnings.Count == 0
            && embedServer.DisposeCount == 1
            && rerankServer.DisposeCount == 1
            && output.ToString().StartsWith("indexed 5 passages in 3 request(s), space tei-embed/BAAI/bge-small-en-v1.5 (4 dims)", StringComparison.Ordinal),
            "TEI indexing did not batch by the caller's ceiling, send the shortlist, or keep unreported usage unknown.");
    }

    [ExampleCase("cookbook.retrieval.voyage-and-jina")]
    internal static async Task VoyageAndJina()
    {
        var voyage = new CookbookRetrievalServer();
        var jina = new CookbookRetrievalServer();
        (CookbookPassageIndex Index, CookbookSearchResult Result) voyageRun, jinaRun;
        using (new CookbookEnvironment(("VOYAGE_API_KEY", "offline-voyage-key"), ("JINA_API_KEY", "offline-jina-key")))
        {
            voyageRun = await CookbookRetrievalExample.RunAsync(
                Offline(CookbookRetrievalExample.Voyage, ("voyage", voyage)), Corpus, Query, maxBatchInputs: 2, new StringWriter());
            jinaRun = await CookbookRetrievalExample.RunAsync(
                Offline(CookbookRetrievalExample.Jina, ("jina", jina)), Corpus, Query, maxBatchInputs: 2, new StringWriter());
        }

        RequireRanking(voyageRun.Index, voyageRun.Result, "voyage", "voyage-3.5-lite");
        RequireRanking(jinaRun.Index, jinaRun.Result, "jina", "jina-embeddings-v5-text-small");
        ExampleSupport.Require(voyage.Authorizations.All(static value => value == "Bearer offline-voyage-key")
            && voyage.InputTypes.Order(StringComparer.Ordinal).SequenceEqual(["document", "document", "document", "query"])
            && voyage.TopN.SequenceEqual([2])
            && voyageRun.Index.Warnings.Count == 0
            && voyageRun.Index.Usage.TotalTokens == 3 * 7
            && voyageRun.Result.RerankUsage.TotalTokens == 7
            && jina.Authorizations.All(static value => value == "Bearer offline-jina-key")
            && jina.InputTypes.Order(StringComparer.Ordinal).SequenceEqual(["retrieval.passage", "retrieval.passage", "retrieval.passage", "retrieval.query"])
            && jina.TopN.SequenceEqual([2])
            && voyage.DisposeCount == 1
            && jina.DisposeCount == 1,
            "The hosted-shaped deployments did not send their native intents, top-N and credentials, or lost reported usage.");
    }

    [ExampleCase("cookbook.retrieval.incompatible-space")]
    internal static async Task IncompatibleSpace()
    {
        var embedServer = new CookbookRetrievalServer();
        var rerankServer = new CookbookRetrievalServer();
        var deployment = Offline(CookbookRetrievalExample.Tei, ("tei-embed", embedServer), ("tei-rerank", rerankServer));
        await using var client = new AsyncClient(deployment.Providers);
        var index = await CookbookRetrievalExample.BuildIndexAsync(client, deployment.EmbeddingTarget, Corpus, maxBatchInputs: 8);

        // The embedding server was redeployed with another model, but the stored index was not rebuilt.
        ConfigException? refused = null;
        try
        {
            await CookbookRetrievalExample.SearchAsync(
                client, index, "tei-embed:BAAI/bge-base-en-v1.5", deployment.RerankTarget, Query, candidates: 3, topN: 2);
        }
        catch (ConfigException exception)
        {
            refused = exception;
        }

        ExampleSupport.Require(refused is not null
            && index.Requests == 1
            && embedServer.EmbedBatches.SequenceEqual([5, 1])
            && rerankServer.Paths.Count == 0
            && new EmbeddingSpace("tei-embed", "BAAI/bge-base-en-v1.5").CompatibleWith(index.Space) is false
            && index.Space.CompatibleWith(new EmbeddingSpace("tei-embed", "BAAI/bge-small-en-v1.5", dimensions: 4)),
            "A query embedding from another model was compared with the stored index.");
    }

    private static void RequireRanking(CookbookPassageIndex index, CookbookSearchResult result, string provider, string model)
    {
        ExampleSupport.Require(index.Space is { Dimensions: 4 } space
            && space.ProviderId == provider
            && space.Model == model
            && index.Entries.Select(static entry => entry.Passage.Id).SequenceEqual(Corpus.Select(static passage => passage.Id))
            && index.Entries.All(static entry => entry.Vector.SequenceEqual(CookbookRetrievalServer.Embed(entry.Passage.Text)))
            && result.Hits.Select(static hit => hit.PassageId).SequenceEqual(["kb-late", "kb-refunds"])
            && result.Hits[0].RerankScore == 0.9
            && result.Hits[1].RerankScore == 0.6
            && result.Hits[0].Cosine > 0.98
            && result.Hits[1].Cosine < result.Hits[0].Cosine,
            $"The {provider} search lost caller IDs, vector order or the reranked order.");
    }

    private static CookbookRetrievalDeployment Offline(
        CookbookRetrievalDeployment deployment,
        params (string Instance, HttpMessageHandler Transport)[] transports)
    {
        var byInstance = transports.ToDictionary(static item => item.Instance, static item => item.Transport, StringComparer.Ordinal);
        return deployment with
        {
            Providers = deployment.Providers.Select(provider => ExampleSupport.WithTransport(provider, byInstance[provider.InstanceId])).ToArray(),
        };
    }
}

/// <summary>
/// A thread-safe offline retrieval server that answers TEI, Voyage and Jina request shapes with
/// deterministic concept-count vectors and concept-overlap relevance scores.
/// </summary>
internal sealed class CookbookRetrievalServer : HttpMessageHandler
{
    private static readonly string[][] Concepts =
    [
        ["refund", "refunds"],
        ["delivery", "deliver", "late", "courier", "shipping", "tracking"],
        ["password", "login", "account"],
        ["invoices", "receipts", "billing"],
    ];

    private static readonly int[] Weights = [6, 3, 1, 1];

    private readonly ConcurrentQueue<string> _paths = new();
    private readonly ConcurrentQueue<int> _embedBatches = new();
    private readonly ConcurrentQueue<string> _inputTypes = new();
    private readonly ConcurrentQueue<string?> _authorizations = new();
    private readonly ConcurrentQueue<int> _topN = new();
    private readonly ConcurrentQueue<string[]> _rerankDocuments = new();

    internal IReadOnlyList<string> Paths => _paths.ToArray();
    internal IReadOnlyList<int> EmbedBatches => _embedBatches.ToArray();
    internal IReadOnlyList<string> InputTypes => _inputTypes.ToArray();
    internal IReadOnlyList<string?> Authorizations => _authorizations.ToArray();
    internal IReadOnlyList<int> TopN => _topN.ToArray();
    internal IReadOnlyList<string[]> RerankDocuments => _rerankDocuments.ToArray();
    internal int DisposeCount { get; private set; }

    internal static double[] Embed(string text) => Counts(text).Select(static count => count + 0.05).ToArray();

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var path = request.RequestUri!.AbsolutePath;
        _paths.Enqueue(path);
        _authorizations.Enqueue(request.Headers.Authorization?.ToString());
        using var document = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(cancellationToken));
        var body = document.RootElement;
        return path switch
        {
            "/embed" => Json(JsonSerializer.Serialize(EmbedAll(Strings(body.GetProperty("inputs"))))),
            "/rerank" => TeiRerank(body),
            "/v1/embeddings" => HostedEmbeddings(body),
            "/v1/rerank" => HostedRerank(body),
            _ => new HttpResponseMessage(HttpStatusCode.NotFound),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }

    private HttpResponseMessage TeiRerank(JsonElement body)
    {
        var texts = Strings(body.GetProperty("texts"));
        _rerankDocuments.Enqueue(texts);
        // TEI returns every rank; the adapter orders them and applies top-N itself.
        return Json(JsonSerializer.Serialize(Rank(body.GetProperty("query").GetString()!, texts)
            .Select(static rank => new { index = rank.Index, score = rank.Score })));
    }

    private HttpResponseMessage HostedEmbeddings(JsonElement body)
    {
        var inputs = Strings(body.GetProperty("input"));
        _inputTypes.Enqueue(body.TryGetProperty("input_type", out var inputType) ? inputType.GetString()! : body.GetProperty("task").GetString()!);
        var vectors = EmbedAll(inputs);
        // Hosted APIs return indexed items; reverse them to prove the SDK restores input order.
        var data = vectors.Select(static (vector, index) => new { index, embedding = vector }).Reverse().ToArray();
        return Json(JsonSerializer.Serialize(new { data, model = body.GetProperty("model").GetString(), usage = new { total_tokens = 7 } }));
    }

    private HttpResponseMessage HostedRerank(JsonElement body)
    {
        var documents = Strings(body.GetProperty("documents"));
        _rerankDocuments.Enqueue(documents);
        var topN = body.TryGetProperty("top_k", out var topK) ? topK.GetInt32() : body.GetProperty("top_n").GetInt32();
        _topN.Enqueue(topN);
        var ranks = Rank(body.GetProperty("query").GetString()!, documents)
            .OrderByDescending(static rank => rank.Score)
            .Take(topN)
            .Select(static rank => new { index = rank.Index, relevance_score = rank.Score })
            .ToArray();
        var payload = body.TryGetProperty("top_k", out _)
            ? JsonSerializer.Serialize(new { data = ranks, usage = new { total_tokens = 7 } })
            : JsonSerializer.Serialize(new { results = ranks, model = body.GetProperty("model").GetString(), usage = new { total_tokens = 7 } });
        return Json(payload);
    }

    private double[][] EmbedAll(string[] inputs)
    {
        _embedBatches.Enqueue(inputs.Length);
        return inputs.Select(Embed).ToArray();
    }

    private static IEnumerable<(int Index, double Score)> Rank(string query, string[] documents)
    {
        var wanted = Counts(query);
        return documents.Select((document, index) =>
        {
            var present = Counts(document);
            var score = Enumerable.Range(0, Concepts.Length).Sum(concept => wanted[concept] > 0 && present[concept] > 0 ? Weights[concept] : 0);
            return (index, score / 10.0);
        });
    }

    private static int[] Counts(string text)
    {
        var words = text.ToLowerInvariant().Split([' ', ',', '.', ';', '?'], StringSplitOptions.RemoveEmptyEntries);
        return Concepts.Select(concept => words.Count(word => concept.Contains(word, StringComparer.Ordinal))).ToArray();
    }

    private static string[] Strings(JsonElement array) => array.EnumerateArray().Select(static item => item.GetString()!).ToArray();

    private static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };
}
