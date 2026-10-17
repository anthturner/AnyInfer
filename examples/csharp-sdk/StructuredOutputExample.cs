using AnyInfer.Json;

namespace AnyInfer.Examples;

/// <summary>Requests a small JSON object and lets the core validate it.</summary>
public static class StructuredOutputExample
{
    /// <summary>Generates an object with a required string answer property.</summary>
    public static async Task<Generation> RunAsync(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        var schema = JsonReader.Read("""
            {"type":"object","required":["answer"],"properties":{"answer":{"type":"string"}}}
            """);
        await using var client = new AsyncClient([settings]);
        return await client.GenerateAsync(
            "Return an answer object.",
            target: target,
            schema: schema,
            repair: new Repair(1),
            cancellationToken: cancellationToken);
    }
}
