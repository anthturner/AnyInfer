namespace AnyInfer.Examples;

/// <summary>Streams text through the synchronous public SDK facade.</summary>
public static class SyncStreamingExample
{
    /// <summary>Writes text deltas and returns the observed terminal generation.</summary>
    public static Generation Run(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        using var client = new Client([settings]);
        using var stream = client.Stream("Say hello.", target: target, cancellationToken: cancellationToken);
        foreach (var item in stream)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (item is TextDelta delta)
            {
                Console.Write(delta.Text);
            }
        }

        return stream.Result;
    }
}
