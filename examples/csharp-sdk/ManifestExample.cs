using AnyInfer.Manifest;

namespace AnyInfer.Examples;

/// <summary>Reads a partial manifest before stream consumption and its committed terminal counterpart.</summary>
public static class ManifestExample
{
    /// <summary>Streams one response with manifest capture enabled and returns both public snapshots.</summary>
    public static async Task<ManifestObservation> RunAsync(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);

        await using var client = new AsyncClient([settings], manifests: true, manifestPayloads: false);
        await using var stream = client.StreamAsync(
            "Say hello.",
            target: target,
            cancellationToken: cancellationToken);
        var partial = stream.Manifest
            ?? throw new InvalidOperationException("Manifest capture was not initialized for the stream.");
        var generation = await stream.CollectAsync(cancellationToken);
        var terminal = generation.Manifest
            ?? throw new InvalidOperationException("The completed generation has no manifest.");
        return new ManifestObservation(partial, terminal, generation);
    }
}

/// <summary>Contains the public partial and committed manifest snapshots for one stream.</summary>
public sealed record ManifestObservation(RunManifest Partial, RunManifest Terminal, Generation Generation);
