using System.Text;

namespace AnyInfer.Examples;

/// <summary>
/// A console answer renderer: streams text as it arrives, cancels on Ctrl+C or an overall deadline,
/// discards text from an attempt that failed mid-answer, and reports the terminal generation.
/// </summary>
public static class CookbookStreamingExample
{
    /// <summary>
    /// Streams one answer with the cancellation a console entry point wires up: Ctrl+C and an overall
    /// deadline both cancel the same token.
    /// </summary>
    /// <param name="providers">The provider instances the route's targets name.</param>
    /// <param name="route">The ordered targets with their retry policy.</param>
    /// <param name="question">The user's question.</param>
    /// <param name="output">Where the answer is rendered, such as <see cref="Console.Out"/>.</param>
    /// <param name="deadline">How long the whole answer may take, retries and fallback included.</param>
    /// <returns>How the answer ended and what was shown.</returns>
    public static async Task<CookbookStreamOutcome> RunConsoleAsync(
        IEnumerable<ProviderSettings> providers,
        Route route,
        string question,
        TextWriter output,
        TimeSpan deadline)
    {
        using var cancellation = new CancellationTokenSource(deadline);
        ConsoleCancelEventHandler onCancel = (_, args) =>
        {
            args.Cancel = true;
            cancellation.Cancel();
        };
        Console.CancelKeyPress += onCancel;
        try
        {
            await using var client = new AsyncClient(providers, route: route);
            return await StreamAnswerAsync(client, question, output, cancellation.Token).ConfigureAwait(false);
        }
        finally
        {
            Console.CancelKeyPress -= onCancel;
        }
    }

    /// <summary>Renders one streamed answer and returns its terminal generation when it completes.</summary>
    /// <param name="client">The client whose default route serves the question.</param>
    /// <param name="question">The user's question.</param>
    /// <param name="output">Where the answer is rendered.</param>
    /// <param name="cancellationToken">Cancels the stream, including a provider call in progress.</param>
    /// <returns>How the answer ended and what was shown.</returns>
    public static async Task<CookbookStreamOutcome> StreamAnswerAsync(
        AsyncClient client,
        string question,
        TextWriter output,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(client);
        ArgumentNullException.ThrowIfNull(output);
        var shown = new StringBuilder();
        var discarded = 0;
        var restart = false;
        await using var stream = client.StreamAsync(question, cancellationToken: cancellationToken);
        try
        {
            await foreach (var item in stream.WithCancellation(cancellationToken).ConfigureAwait(false))
            {
                switch (item)
                {
                    case TextDelta delta:
                        if (restart)
                        {
                            // The text on screen belonged to an attempt that failed; this is a new answer.
                            discarded++;
                            shown.Clear();
                            restart = false;
                        }

                        shown.Append(delta.Text);
                        await output.WriteAsync(delta.Text).ConfigureAwait(false);
                        break;
                    case AttemptFailed failed:
                        // A retry or the next target may follow; any text it streams replaces what is shown.
                        if (shown.Length > 0)
                        {
                            restart = true;
                            await output.WriteLineAsync().ConfigureAwait(false);
                        }

                        await output.WriteLineAsync($"[{failed.Record.Target} {failed.Record.Outcome}: {failed.Record.Error?.GetType().Name}]").ConfigureAwait(false);
                        break;
                }
            }

            var result = stream.Result;
            await output.WriteLineAsync().ConfigureAwait(false);
            await output.WriteLineAsync($"[{result.Target} in {result.Timing?.TotalMs:F0} ms, {result.Usage?.TotalTokens?.ToString() ?? "unknown"} tokens]").ConfigureAwait(false);
            return new CookbookStreamOutcome(CookbookStreamStatus.Completed, shown.ToString(), discarded, result, null);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            await output.WriteLineAsync().ConfigureAwait(false);
            await output.WriteLineAsync("[cancelled]").ConfigureAwait(false);
            return new CookbookStreamOutcome(CookbookStreamStatus.Cancelled, shown.ToString(), discarded, null, null);
        }
        catch (StreamProtocolException error)
        {
            // A stream that broke after visible content is not retried: the shown text is incomplete.
            await output.WriteLineAsync().ConfigureAwait(false);
            await output.WriteLineAsync($"[answer incomplete: {error.Category}]").ConfigureAwait(false);
            return new CookbookStreamOutcome(CookbookStreamStatus.Broken, shown.ToString(), discarded, null, error);
        }
        catch (AllTargetsFailedException error)
        {
            await output.WriteLineAsync($"[no target answered: {error.Attempts.Count} attempt(s)]").ConfigureAwait(false);
            return new CookbookStreamOutcome(CookbookStreamStatus.Failed, shown.ToString(), discarded, null, error);
        }
    }

    /// <summary>Renders one streamed answer through the synchronous client, for a synchronous caller.</summary>
    /// <param name="client">The synchronous client whose default route serves the question.</param>
    /// <param name="question">The user's question.</param>
    /// <param name="output">Where the answer is rendered.</param>
    /// <param name="cancellationToken">Cancels the stream; the next event wait then throws.</param>
    /// <returns>How the answer ended and what was shown.</returns>
    public static CookbookStreamOutcome StreamAnswer(
        Client client,
        string question,
        TextWriter output,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(client);
        ArgumentNullException.ThrowIfNull(output);
        var shown = new StringBuilder();
        var discarded = 0;
        var restart = false;
        try
        {
            using var stream = client.Stream(question, cancellationToken: cancellationToken);
            foreach (var item in stream)
            {
                if (item is TextDelta delta)
                {
                    if (restart)
                    {
                        discarded++;
                        shown.Clear();
                        restart = false;
                    }

                    shown.Append(delta.Text);
                    output.Write(delta.Text);
                }
                else if (item is AttemptFailed && shown.Length > 0)
                {
                    restart = true;
                    output.WriteLine();
                }
            }

            output.WriteLine();
            return new CookbookStreamOutcome(CookbookStreamStatus.Completed, shown.ToString(), discarded, stream.Result, null);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            output.WriteLine();
            output.WriteLine("[cancelled]");
            return new CookbookStreamOutcome(CookbookStreamStatus.Cancelled, shown.ToString(), discarded, null, null);
        }
    }
}

/// <summary>How a streamed answer ended.</summary>
public enum CookbookStreamStatus
{
    /// <summary>The stream completed and its terminal generation is available.</summary>
    Completed,

    /// <summary>The caller cancelled, by Ctrl+C or the deadline.</summary>
    Cancelled,

    /// <summary>The stream broke after visible content and was not retried.</summary>
    Broken,

    /// <summary>Every target failed before an answer completed.</summary>
    Failed,
}

/// <summary>The renderer's record of one streamed answer.</summary>
/// <param name="Status">How the stream ended.</param>
/// <param name="Shown">The text of the attempt being shown when the stream ended.</param>
/// <param name="DiscardedAttempts">How many attempts failed after their text had been shown.</param>
/// <param name="Generation">The terminal generation of a completed stream, otherwise <see langword="null"/>.</param>
/// <param name="Error">The failure that ended a broken or failed stream, otherwise <see langword="null"/>.</param>
public sealed record CookbookStreamOutcome(
    CookbookStreamStatus Status,
    string Shown,
    int DiscardedAttempts,
    Generation? Generation,
    AnyInferException? Error);
