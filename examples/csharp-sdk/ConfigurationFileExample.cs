using AnyInfer.Config;

namespace AnyInfer.Examples;

/// <summary>
/// Loads a version 1 configuration document with generation, embedding, and rerank defaults, then answers
/// from the best-ranked passage without naming a target in code.
/// </summary>
public static class ConfigurationFileExample
{
    // --8<-- [start:document]
    /// <summary>A version 1 document that uses every block the native reader accepts.</summary>
    public const string Document = """
        {
          "format_version": 1,
          "providers": [
            {"id": "local-chat", "adapter": "openai-compat", "base_url": "http://127.0.0.1:11434/v1"},
            {"id": "tei-embed", "adapter": "tei", "base_url": "http://127.0.0.1:8080"},
            {"id": "tei-rerank", "adapter": "tei", "base_url": "http://127.0.0.1:8081"}
          ],
          "default_route": ["local-chat:qwen3:8b"],
          "operation_routes": {
            "embedding": ["tei-embed:BAAI/bge-small-en-v1.5"],
            "rerank": ["tei-rerank:BAAI/bge-reranker-base"]
          },
          "repair": {"max_attempts": 1},
          "cache": {"mode": "auto"}
        }
        """;
    // --8<-- [end:document]

    // --8<-- [start:use]
    /// <summary>Validates configuration text; nothing is resolved, constructed, or sent.</summary>
    /// <param name="json">A version 1 configuration document.</param>
    /// <returns>The validated, inert configuration.</returns>
    public static AnyInferConfig Load(string json) => AnyInferConfig.Loads(json, source: "anyinfer.json");

    /// <summary>Ranks passages with the configured rerank route and answers with the default route.</summary>
    /// <param name="config">Configuration from <see cref="Load"/>.</param>
    /// <param name="question">The user's question.</param>
    /// <param name="passages">Candidate passages with application-owned identifiers.</param>
    /// <param name="cancellationToken">Cancels both calls.</param>
    /// <returns>The identifier of the passage used and the answer.</returns>
    public static async Task<ConfiguredAnswer> AnswerAsync(
        AnyInferConfig config,
        string question,
        IReadOnlyList<RerankDocument> passages,
        CancellationToken cancellationToken = default)
    {
        await using var client = AsyncClient.FromConfig(config);
        var ranked = await client.RerankAsync(question, passages, topN: 1, cancellationToken: cancellationToken);
        var best = passages[ranked.Items[0].Index];
        var answer = await client.GenerateAsync(
            $"Answer from this passage only.\n\n{best.Text}\n\nQuestion: {question}",
            cancellationToken: cancellationToken);
        return new ConfiguredAnswer(best.Id, answer);
    }
    // --8<-- [end:use]
}

/// <summary>Contains the passage identifier a configured answer used and the answer itself.</summary>
public sealed record ConfiguredAnswer(string PassageId, Generation Answer);
