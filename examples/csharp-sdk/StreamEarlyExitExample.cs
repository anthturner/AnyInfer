using System.Text;

namespace AnyInfer.Examples;

/// <summary>Stops reading a stream early, which cancels the generation still in flight.</summary>
public static class StreamEarlyExitExample
{
    // --8<-- [start:async]
    /// <summary>Contains the text read before the stream stopped and, when it finished, its terminal result.</summary>
    /// <param name="Text">The answer text received before reading stopped.</param>
    /// <param name="Result">The terminal generation, or <see langword="null"/> when reading stopped early.</param>
    public sealed record Excerpt(string Text, Generation? Result);

    /// <summary>Reads answer text until it reaches <paramref name="maxCharacters"/>, then stops the generation.</summary>
    public static async Task<Excerpt> ReadAsync(
        ProviderSettings settings,
        string target,
        int maxCharacters,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([settings]);
        await using var stream = client.StreamAsync(
            "Explain TCP slow start.",
            target: target,
            cancellationToken: cancellationToken);
        var text = new StringBuilder();
        await foreach (var item in stream.WithCancellation(cancellationToken))
        {
            if (item is not TextDelta delta)
            {
                continue;
            }

            text.Append(delta.Text);
            if (text.Length >= maxCharacters)
            {
                // Leaving the loop disposes its enumerator, which cancels the in-flight request.
                // The stream has no terminal result now: stream.Result would throw.
                return new Excerpt(text.ToString(), Result: null);
            }
        }

        return new Excerpt(text.ToString(), stream.Result);
    }
    // --8<-- [end:async]

    // --8<-- [start:sync]
    /// <summary>Reads answer text through the synchronous facade and stops at <paramref name="maxCharacters"/>.</summary>
    public static Excerpt Read(
        ProviderSettings settings,
        string target,
        int maxCharacters,
        CancellationToken cancellationToken = default)
    {
        using var client = new Client([settings]);
        // A synchronous stream starts generating as soon as it is created.
        using var stream = client.Stream(
            "Explain TCP slow start.",
            target: target,
            cancellationToken: cancellationToken);
        var text = new StringBuilder();
        foreach (var item in stream)
        {
            if (item is not TextDelta delta)
            {
                continue;
            }

            text.Append(delta.Text);
            if (text.Length >= maxCharacters)
            {
                // Leaving the loop disposes the stream, which cancels the generation and waits for it to stop.
                return new Excerpt(text.ToString(), Result: null);
            }
        }

        // Finishing the loop also disposed the stream; its observed terminal result stays readable.
        return new Excerpt(text.ToString(), stream.Result);
    }
    // --8<-- [end:sync]
}
