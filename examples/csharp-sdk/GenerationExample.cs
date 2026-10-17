namespace AnyInfer.Examples;

/// <summary>Runs a buffered generation through configured public SDK APIs.</summary>
public static class GenerationExample
{
    /// <summary>Generates one response and disposes the client after completion.</summary>
    public static async Task<Generation> RunAsync(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([settings]);
        return await client.GenerateAsync("Say hello.", target: target, cancellationToken: cancellationToken);
    }
}
