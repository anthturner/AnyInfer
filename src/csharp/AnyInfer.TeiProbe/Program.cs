using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Providers;
using System.Net.Http;
using System.Reflection;
using System.Text.Json;

var arguments = ProbeArguments.Parse(args);
var stamp = SourceStamp.Read();
var deployment = await DeploymentWitnessAsync(arguments, stamp);
var sdk = await SdkWitnessAsync(arguments, stamp);
var witness = new { source = stamp, deployment, sdk };
await File.WriteAllTextAsync(arguments.Output, JsonSerializer.Serialize(witness, new JsonSerializerOptions { WriteIndented = true }) + "\n");

static async Task<object> DeploymentWitnessAsync(ProbeArguments arguments, SourceStamp stamp)
{
    using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
    var embedding = await ReadInfoAsync(client, arguments.EmbeddingUrl, arguments.ExpectedVersion, arguments.EmbeddingModel);
    var rerank = await ReadInfoAsync(client, arguments.RerankUrl, arguments.ExpectedVersion, arguments.RerankModel);
    return new { kind = "raw-deployment-info", source = stamp, embedding, rerank };
}

static async Task<object> ReadInfoAsync(HttpClient client, string baseUrl, string version, string model)
{
    using var response = await client.GetAsync(Append(baseUrl, "info"), HttpCompletionOption.ResponseHeadersRead);
    response.EnsureSuccessStatusCode();
    using var document = JsonDocument.Parse(await response.Content.ReadAsStreamAsync());
    var root = document.RootElement;
    if (root.GetProperty("version").GetString() != version || root.GetProperty("model_id").GetString() != model)
        throw new InvalidOperationException("The deployment identity does not match the expected TEI version and model.");
    return new
    {
        model_id = root.GetProperty("model_id").GetString(),
        model_type = root.TryGetProperty("model_type", out var type) ? type.GetRawText() : null,
        version = root.GetProperty("version").GetString(),
        limits = new
        {
            max_input_length = OptionalNumber(root, "max_input_length"),
            max_batch_tokens = OptionalNumber(root, "max_batch_tokens"),
            max_client_batch_size = OptionalNumber(root, "max_client_batch_size"),
        },
    };
}

static async Task<object> SdkWitnessAsync(ProbeArguments arguments, SourceStamp stamp)
{
    var ledger = new SpendLedger();
    var settings = new[]
    {
        ProviderSettings.Of("tei", arguments.EmbeddingUrl, alias: "tei-embed"),
        ProviderSettings.Of("tei", arguments.RerankUrl, alias: "tei-rerank"),
    };
    await using var client = new AsyncClient(settings, ProviderRegistry.CreateDefault(), ledger: ledger, retainRaw: true);
    var embeddingModels = await client.ModelsAsync("tei-embed", InferenceOperation.Embedding);
    var rerankModels = await client.ModelsAsync("tei-rerank", InferenceOperation.Rerank);
    var embeddingHealth = await client.HealthAsync("tei-embed");
    var rerankHealth = await client.HealthAsync("tei-rerank");
    if (!embeddingHealth.Ok || !rerankHealth.Ok || !embeddingModels.Any(model => model.Id == arguments.EmbeddingModel) || !rerankModels.Any(model => model.Id == arguments.RerankModel))
        throw new InvalidOperationException("The public SDK could not discover a ready expected TEI model and operation.");
    var embedding = await client.EmbedAsync(new[] { "AnyInfer TEI probe" }, target: "tei-embed:probe", dimensions: 384, retainRaw: true);
    var rerank = await client.RerankAsync("TEI probe", new[] { new RerankDocument("document-a", "TEI retrieval probe"), new RerankDocument("document-b", "unrelated text") }, target: "tei-rerank:probe", topN: 1, retainRaw: true);
    if (embedding.Vectors.Count != 1 || embedding.Space.Normalized is not true || embedding.Raw is null || !UsageIsUnknown(embedding.Usage) || embedding.Manifest?.Payloads is not null || rerank.Items.Count != 1 || rerank.Items[0].DocumentId != "document-a" || rerank.Raw is null || !UsageIsUnknown(rerank.Usage) || rerank.Manifest?.Payloads is not null)
        throw new InvalidOperationException("The public SDK TEI witness returned an unexpected retrieval result.");
    using var sync = new Client(settings, ProviderRegistry.CreateDefault(), retainRaw: true);
    var syncEmbedding = sync.Embed("AnyInfer TEI probe", target: "tei-embed:probe", dimensions: 384, retainRaw: true);
    if (syncEmbedding.Vectors.Count != 1 || syncEmbedding.Space.Normalized is not true || syncEmbedding.Raw is null || !UsageIsUnknown(syncEmbedding.Usage) || syncEmbedding.Manifest?.Payloads is not null)
        throw new InvalidOperationException("The synchronous public SDK witness returned an unexpected embedding result.");
    var totals = ledger.Totals();
    if (totals.Complete || totals.UnknownRequests != 2)
        throw new InvalidOperationException("The public SDK TEI witness expected unknown ledger cost for both async retrieval operations.");
    return new { kind = "public-sdk", source = stamp, embedding_models = embeddingModels.Select(model => model.Id), rerank_models = rerankModels.Select(model => model.Id), embedding_health = embeddingHealth.Ok, rerank_health = rerankHealth.Ok, embedding_dimensions = embedding.Vectors[0].Values.Count, embedding_normalized = embedding.Space.Normalized, rerank_document_id = rerank.Items[0].DocumentId, ledger_cost_known = totals.Complete, ledger_unknown_requests = totals.UnknownRequests };
}

static long? OptionalNumber(JsonElement root, string name) => root.TryGetProperty(name, out var value) && value.TryGetInt64(out var number) ? number : null;
static string Append(string baseUrl, string path) => baseUrl.TrimEnd('/') + "/" + path;
static bool UsageIsUnknown(Usage usage) => usage.InputTokens is null && usage.OutputTokens is null && usage.TotalTokens is null && usage.CacheReadTokens is null && usage.CacheWriteTokens is null && usage.ReasoningTokens is null && usage.CostUsd is null && usage.SearchUnits is null && usage.ServerToolUses.Count == 0;

internal sealed record ProbeArguments(string EmbeddingUrl, string RerankUrl, string ExpectedVersion, string EmbeddingModel, string RerankModel, string Output)
{
    internal static ProbeArguments Parse(string[] args)
    {
        if (args.Length != 12) throw new ArgumentException("Expected --embedding-url --rerank-url --expected-version --embedding-model --rerank-model --output.");
        var values = args.Chunk(2).ToDictionary(pair => pair[0], pair => pair[1], StringComparer.Ordinal);
        return new ProbeArguments(values["--embedding-url"], values["--rerank-url"], values["--expected-version"], values["--embedding-model"], values["--rerank-model"], values["--output"]);
    }
}

internal sealed record SourceStamp(string Commit, bool Dirty)
{
    internal static SourceStamp Read()
    {
        var metadata = Assembly.GetExecutingAssembly().GetCustomAttributes<AssemblyMetadataAttribute>().ToDictionary(item => item.Key, item => item.Value, StringComparer.Ordinal);
        if (!metadata.TryGetValue("TeiProbeSourceCommit", out var commit) || commit is null || !System.Text.RegularExpressions.Regex.IsMatch(commit, "^[0-9a-f]{40}$") || !metadata.TryGetValue("TeiProbeSourceDirty", out var dirty) || !string.Equals(dirty, "true", StringComparison.Ordinal) && !string.Equals(dirty, "false", StringComparison.Ordinal) || !bool.TryParse(dirty, out var isDirty)) throw new InvalidOperationException("Build source metadata is absent or invalid.");
        return new SourceStamp(commit, isDirty);
    }
}
