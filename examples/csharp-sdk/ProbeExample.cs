using AnyInfer.Capabilities;

namespace AnyInfer.Examples;

/// <summary>Runs explicit capability probes through configured public clients.</summary>
public static class ProbeExample
{
    /// <summary>Runs the ordered default probe selection and returns its immutable report.</summary>
    public static async Task<ProbeReport> RunAsync(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);

        await using var client = new AsyncClient([settings]);
        return await client.ProbeAsync(target, cancellationToken: cancellationToken);
    }

    /// <summary>Runs the ordered default probe selection through the synchronous facade.</summary>
    public static ProbeReport Run(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);

        using var client = new Client([settings]);
        return client.Probe(target, cancellationToken: cancellationToken);
    }
}
