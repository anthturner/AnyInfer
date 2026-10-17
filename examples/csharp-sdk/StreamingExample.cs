namespace AnyInfer.Examples;

/// <summary>Streams text deltas and retrieves the same operation's terminal result.</summary>
public static class StreamingExample
{
    /// <summary>Writes each text delta to standard output and returns the completed generation.</summary>
    public static async Task<Generation> RunAsync(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([settings]);
        await using var stream = client.StreamAsync("Say hello.", target: target, cancellationToken: cancellationToken);
        await foreach (var item in stream.WithCancellation(cancellationToken))
        {
            if (item is TextDelta delta)
            {
                Console.Write(delta.Text);
            }
        }

        return stream.Result;
    }
}
