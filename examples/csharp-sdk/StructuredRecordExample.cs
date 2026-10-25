using System.Text.Json.Serialization;

namespace AnyInfer.Examples;

/// <summary>Validates a review analysis against a JSON Schema and reads it as an application record.</summary>
public static class StructuredRecordExample
{
    // --8<-- [start:record]
    /// <summary>The application's typed view of a validated review analysis.</summary>
    public sealed record ReviewAnalysis(
        [property: JsonPropertyName("sentiment")] string Sentiment,
        [property: JsonPropertyName("score")] int Score,
        [property: JsonPropertyName("themes")] IReadOnlyList<string> Themes);

    /// <summary>The schema every analysis satisfies before the application sees it.</summary>
    public static readonly SchemaSpec Review = SchemaSpec.FromJson("""
        {
          "$schema": "https://json-schema.org/draft/2020-12/schema",
          "title": "review",
          "type": "object",
          "properties": {
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
            "themes": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["sentiment", "score", "themes"],
          "additionalProperties": false
        }
        """);

    /// <summary>Generates an analysis, allowing one repair round trip, and deserializes the validated value.</summary>
    public static async Task<ReviewAnalysis> AnalyzeAsync(
        AsyncClient client,
        string target,
        string review,
        CancellationToken cancellationToken = default)
    {
        var generation = await client.GenerateAsync(
            "Analyze this review:\n" + review,
            target: target,
            schema: Review,
            repair: new Repair(MaxAttempts: 1),
            cancellationToken: cancellationToken);

        // Structured is the value already validated against Review, whichever mechanism produced it.
        return generation.DeserializeStructured<ReviewAnalysis>()
            ?? throw new InvalidOperationException("The validated analysis was JSON null.");
    }
    // --8<-- [end:record]

    // --8<-- [start:failure]
    /// <summary>Returns the analysis, or <see langword="null"/> after logging why the answer never fit the schema.</summary>
    public static async Task<ReviewAnalysis?> TryAnalyzeAsync(
        AsyncClient client,
        string target,
        string review,
        TextWriter log,
        CancellationToken cancellationToken = default)
    {
        try
        {
            return await AnalyzeAsync(client, target, review, cancellationToken);
        }
        catch (SchemaViolationException error)
        {
            // The repair budget is spent; the route does not move on to another target.
            log.WriteLine($"{error.Message} Failed rules: {string.Join(", ", error.Issues.Select(static issue => issue.Rule))}");
            return null;
        }
    }
    // --8<-- [end:failure]

    // --8<-- [start:mechanism]
    /// <summary>Reports how the target produced structured output and how many repairs it needed.</summary>
    public static string Explain(Generation generation) =>
        $"{generation.StructuredMechanism} after {generation.RepairAttempts} repair round trip(s)";
    // --8<-- [end:mechanism]
}
