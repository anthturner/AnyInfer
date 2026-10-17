namespace AnyInfer.Examples;

/// <summary>Runs a buffered generation through the synchronous public SDK facade.</summary>
public static class SyncGenerationExample
{
    /// <summary>Generates one response and disposes the synchronous client after completion.</summary>
    public static Generation Run(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        using var client = new Client([settings]);
        return client.Generate("Say hello.", target: target, cancellationToken: cancellationToken);
    }
}
