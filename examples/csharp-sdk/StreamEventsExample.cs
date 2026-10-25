namespace AnyInfer.Examples;

/// <summary>Reads the typed events of one generation stream the way a terminal or chat frontend would.</summary>
/// <remarks>
/// Each method consumes a stream returned by an <see cref="AsyncClient"/> <c>StreamAsync</c> call
/// once, the stream's single enumeration, and then reads its terminal result.
/// </remarks>
public static class StreamEventsExample
{
    // --8<-- [start:thinking]
    /// <summary>Writes reasoning and answer text to separate writers and returns the completed generation.</summary>
    public static async Task<Generation> ShowThinkingAsync(
        AsyncStream stream,
        TextWriter answer,
        TextWriter thinking,
        CancellationToken cancellationToken = default)
    {
        await foreach (var item in stream.WithCancellation(cancellationToken))
        {
            switch (item)
            {
                case ReasoningDelta reasoning:
                    thinking.Write(reasoning.Text);
                    break;
                case TextDelta delta:
                    answer.Write(delta.Text);
                    break;
            }
        }

        return stream.Result; // Result.Text holds the answer only, never the reasoning.
    }
    // --8<-- [end:thinking]

    // --8<-- [start:first-token]
    /// <summary>Prefixes the answer with the core-measured time to its first token.</summary>
    public static async Task<Generation> ShowFirstTokenAsync(
        AsyncStream stream,
        TextWriter output,
        CancellationToken cancellationToken = default)
    {
        await foreach (var item in stream.WithCancellation(cancellationToken))
        {
            switch (item)
            {
                case TimingMark { Name: "first_token" } mark:
                    output.Write($"[{mark.AtMs:F0} ms] ");
                    break;
                case TextDelta delta:
                    output.Write(delta.Text);
                    break;
            }
        }

        return stream.Result; // Result.Timing.FirstTokenMs repeats the winning attempt's measurement.
    }
    // --8<-- [end:first-token]

    // --8<-- [start:fallback]
    /// <summary>Announces each failed attempt as it happens while writing the answer.</summary>
    public static async Task<Generation> ShowFallbackAsync(
        AsyncStream stream,
        TextWriter output,
        CancellationToken cancellationToken = default)
    {
        await foreach (var item in stream.WithCancellation(cancellationToken))
        {
            switch (item)
            {
                case AttemptFailed failed:
                    output.WriteLine($"[{failed.Record.Target} failed: {failed.Record.Error?.GetType().Name}]");
                    break;
                case TextDelta delta:
                    output.Write(delta.Text);
                    break;
            }
        }

        return stream.Result;
    }
    // --8<-- [end:fallback]

    // --8<-- [start:describe]
    /// <summary>Returns a one-line description of any stream event.</summary>
    public static string Describe(StreamEvent item) => item switch
    {
        TimingMark mark => $"timing {mark.Name} at {mark.AtMs:F0} ms",
        TextDelta delta => $"text {delta.Text}",
        ReasoningDelta reasoning => $"reasoning {reasoning.Text}",
        CitationDelta citation => $"citation {citation.Citation.Title} <{citation.Citation.Uri}>",
        ToolCallDelta call => $"tool call #{call.Index} {call.Name} {call.ArgumentsFragment}",
        ServerToolDelta tool => $"server tool {tool.Kind} {tool.Status}",
        UsageUpdate usage => $"usage {usage.Usage.InputTokens} in, {usage.Usage.OutputTokens} out",
        AttemptFailed failed => $"attempt {failed.Record.Target} {failed.Record.Outcome}: {failed.Record.Error?.GetType().Name}",
        StreamEnded ended => $"ended {ended.Result.FinishReason} from {ended.Result.Target}",
        _ => item.GetType().Name,
    };

    /// <summary>Consumes a stream and returns one description per event, in arrival order.</summary>
    public static async Task<IReadOnlyList<string>> LogAsync(
        AsyncStream stream,
        CancellationToken cancellationToken = default)
    {
        var lines = new List<string>();
        await foreach (var item in stream.WithCancellation(cancellationToken))
        {
            lines.Add(Describe(item));
        }

        return lines;
    }
    // --8<-- [end:describe]

    // --8<-- [start:failure]
    /// <summary>Streams an answer and reports a route that ran out of targets instead of throwing.</summary>
    /// <returns>The completed generation, or <see langword="null"/> when every target failed.</returns>
    public static async Task<Generation?> TryStreamAsync(
        AsyncStream stream,
        TextWriter output,
        TextWriter errors,
        CancellationToken cancellationToken = default)
    {
        try
        {
            await foreach (var item in stream.WithCancellation(cancellationToken))
            {
                if (item is TextDelta delta)
                {
                    output.Write(delta.Text);
                }
            }

            return stream.Result;
        }
        catch (AllTargetsFailedException failure)
        {
            // Thrown by the enumeration after the last AttemptFailed event; stream.Result would throw here.
            foreach (var attempt in failure.Attempts)
            {
                errors.WriteLine($"{attempt.Target}: {attempt.Outcome} ({attempt.Error?.GetType().Name})");
            }

            return null;
        }
    }
    // --8<-- [end:failure]
}
