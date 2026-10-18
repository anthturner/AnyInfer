using System.Text.Json.Serialization;

namespace AnyInfer.Examples;

/// <summary>Requests a small JSON object and lets the core validate it.</summary>
public static class StructuredOutputExample
{
    /// <summary>Represents the validated response object used by this example.</summary>
    public sealed record AnswerResult([property: JsonPropertyName("answer")] string Answer);

    /// <summary>Generates an object with a required string answer property.</summary>
    public static async Task<AnswerResult> RunAsync(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        var schema = SchemaSpec.FromJson("""
            {"$schema":"https://json-schema.org/draft/2020-12/schema","title":"answer","type":"object","required":["answer"],"properties":{"answer":{"type":"string"}}}
            """);
        await using var client = new AsyncClient([settings]);
        var generation = await client.GenerateAsync(
            "Return an answer object.",
            target: target,
            schema: schema,
            repair: new Repair(1),
            cancellationToken: cancellationToken);
        return generation.DeserializeStructured<AnswerResult>()
            ?? throw new InvalidOperationException("The validated response could not be deserialized.");
    }
}
