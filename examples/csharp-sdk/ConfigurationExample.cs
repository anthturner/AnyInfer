using AnyInfer.Config;
using AnyInfer.Providers;

namespace AnyInfer.Examples;

/// <summary>Loads inert JSON configuration before creating a configured client.</summary>
public static class ConfigurationExample
{
    /// <summary>Loads configuration, constructs a client, and uses its configured default route.</summary>
    public static async Task<Generation> RunAsync(
        string json,
        string prompt,
        ProviderRegistry? registry = null,
        CancellationToken cancellationToken = default)
    {
        var config = AnyInferConfig.Loads(json, registry);
        await using var client = AsyncClient.FromConfig(config, registry);
        return await client.GenerateAsync(prompt, cancellationToken: cancellationToken);
    }
}
