using System.Net;

namespace AnyInfer.Examples.Cases;

/// <summary>Runs the console answer renderer offline through completion, restart, cancellation and breakage.</summary>
internal static class CookbookStreamingCases
{
    private static readonly Route FastRoute = new(["primary:chat", "backup:chat"], retry: new Retry(MaxAttempts: 2, BackoffBaseS: 0.01));

    [ExampleCase("cookbook.streaming.restart-after-midstream-failure")]
    internal static async Task RestartAfterMidstreamFailure()
    {
        var (broken, brokenReply) = CookbookBody.Sse(CookbookReplies.Delta("The deploy "), CookbookBody.Break);
        var primary = new CookbookScriptedHandler(
            brokenReply,
            CookbookReplies.Sse(CookbookReplies.Delta("The deploy "), CookbookReplies.Delta("is safe."), CookbookReplies.Finish(12, 4), "[DONE]"));
        var backup = new CookbookScriptedHandler();
        var output = new StringWriter();

        var outcome = await CookbookStreamingExample.RunConsoleAsync(
            Providers(primary, backup), FastRoute, "Is the deploy safe?", output, TimeSpan.FromSeconds(30));

        ExampleSupport.Require(outcome is { Status: CookbookStreamStatus.Completed, Shown: "The deploy is safe.", DiscardedAttempts: 1, Error: null }
            && outcome.Generation is { Text: "The deploy is safe.", FinishReason: "stop", Usage.TotalTokens: 16 } generation
            && generation.Attempts.Select(static attempt => attempt.Outcome).SequenceEqual(["retried", "ok"])
            && generation.Attempts[0].Error is TransportException
            && broken.Disposed,
            "The renderer did not restart after the mid-stream transport failure, or the result kept the failed attempt's text.");
        ExampleSupport.Require(primary.Requests.Count == 2
            && primary.Requests.All(static request => request.Json().GetProperty("stream").GetBoolean())
            && backup.Requests.Count == 0
            && primary.DisposeCount == 1
            && backup.DisposeCount == 1
            && output.ToString().Contains("[primary:chat retried: TransportException]", StringComparison.Ordinal),
            "The retry did not stay on the primary, or the client did not release every transport it was given.");
    }

    [ExampleCase("cookbook.streaming.fallback-before-content")]
    internal static async Task FallbackBeforeContent()
    {
        var primary = new CookbookScriptedHandler(
            CookbookReplies.Status(HttpStatusCode.Unauthorized, "bad key"));
        var backup = new CookbookScriptedHandler(
            CookbookReplies.Sse(CookbookReplies.Delta("Yes."), CookbookReplies.Finish(), "[DONE]"));
        var output = new StringWriter();

        var outcome = await CookbookStreamingExample.RunConsoleAsync(
            Providers(primary, backup), FastRoute, "Is the deploy safe?", output, TimeSpan.FromSeconds(30));

        // An authentication failure is never retried on the same target; the route falls back.
        ExampleSupport.Require(outcome is { Status: CookbookStreamStatus.Completed, Shown: "Yes.", DiscardedAttempts: 0 }
            && outcome.Generation!.Target!.ToString() == "backup:chat"
            && outcome.Generation.Attempts.Select(static attempt => attempt.Outcome).SequenceEqual(["failed", "ok"])
            && outcome.Generation.Attempts[0].Error is AuthException
            && primary.Requests.Count == 1
            && backup.Requests.Count == 1
            && output.ToString().StartsWith("[primary:chat failed: AuthException]", StringComparison.Ordinal),
            "A failure before any content did not fall back to the next target.");
    }

    [ExampleCase("cookbook.streaming.deadline-cancels")]
    internal static async Task DeadlineCancels()
    {
        var (stalled, stalledReply) = CookbookBody.Sse(CookbookReplies.Delta("Thinking"), CookbookBody.Stall);
        var primary = new CookbookScriptedHandler(stalledReply);
        var backup = new CookbookScriptedHandler();
        var output = new StringWriter();

        var outcome = await CookbookStreamingExample.RunConsoleAsync(
            Providers(primary, backup), FastRoute, "Is the deploy safe?", output, TimeSpan.FromMilliseconds(300));

        ExampleSupport.Require(outcome is { Status: CookbookStreamStatus.Cancelled, Shown: "Thinking", Generation: null, Error: null }
            && stalled.StallCancelled
            && stalled.Disposed
            && primary.Requests.Count == 1
            && backup.Requests.Count == 0
            && primary.DisposeCount == 1
            && output.ToString().EndsWith("[cancelled]" + Environment.NewLine, StringComparison.Ordinal),
            "The deadline did not cancel the provider call in progress without falling back.");
    }

    [ExampleCase("cookbook.streaming.protocol-break")]
    internal static async Task ProtocolBreak()
    {
        var primary = new CookbookScriptedHandler(
            CookbookReplies.Sse(CookbookReplies.Delta("The deploy "), "{not json"));
        var backup = new CookbookScriptedHandler();
        var output = new StringWriter();

        var outcome = await CookbookStreamingExample.RunConsoleAsync(
            Providers(primary, backup), FastRoute, "Is the deploy safe?", output, TimeSpan.FromSeconds(30));

        // A corrupted stream after visible content is reported, not retried or sent to the backup.
        ExampleSupport.Require(outcome is { Status: CookbookStreamStatus.Broken, Generation: null, Error: StreamProtocolException }
            && outcome.Shown == "The deploy "
            && outcome.DiscardedAttempts == 0
            && primary.Requests.Count == 1
            && backup.Requests.Count == 0
            && output.ToString().Contains("[answer incomplete: stream_protocol]", StringComparison.Ordinal),
            "A protocol break after content was retried or fell back.");
    }

    [ExampleCase("cookbook.streaming.no-target-answers")]
    internal static async Task NoTargetAnswers()
    {
        var primary = new CookbookScriptedHandler(
            CookbookReplies.Status(HttpStatusCode.ServiceUnavailable),
            CookbookReplies.Status(HttpStatusCode.ServiceUnavailable));
        var backup = new CookbookScriptedHandler(
            CookbookReplies.Status(HttpStatusCode.BadGateway),
            CookbookReplies.Status(HttpStatusCode.BadGateway));
        var output = new StringWriter();

        var outcome = await CookbookStreamingExample.RunConsoleAsync(
            Providers(primary, backup), FastRoute, "Is the deploy safe?", output, TimeSpan.FromSeconds(30));

        ExampleSupport.Require(outcome is { Status: CookbookStreamStatus.Failed, Shown: "", Generation: null, Error: AllTargetsFailedException { Attempts.Count: 4 } }
            && primary.Requests.Count == 2
            && backup.Requests.Count == 2
            && output.ToString().EndsWith("[no target answered: 4 attempt(s)]" + Environment.NewLine, StringComparison.Ordinal),
            "An exhausted route was not reported after every retry and fallback.");
    }

    [ExampleCase("cookbook.streaming.synchronous")]
    internal static void Synchronous()
    {
        var primary = new CookbookScriptedHandler(
            CookbookReplies.Sse(CookbookReplies.Delta("Yes, "), CookbookReplies.Delta("ship it."), CookbookReplies.Finish(8, 3), "[DONE]"));
        var backup = new CookbookScriptedHandler();
        var output = new StringWriter();
        CookbookStreamOutcome outcome;
        using (var client = new Client(Providers(primary, backup), route: FastRoute))
        {
            outcome = CookbookStreamingExample.StreamAnswer(client, "Is the deploy safe?", output, CancellationToken.None);
        }

        ExampleSupport.Require(outcome is { Status: CookbookStreamStatus.Completed, Shown: "Yes, ship it." }
            && outcome.Generation is { Text: "Yes, ship it.", Usage.TotalTokens: 11 }
            && output.ToString() == "Yes, ship it." + Environment.NewLine
            && primary.Requests.Count == 1
            && primary.DisposeCount == 1,
            "The synchronous renderer did not stream the answer or release its transport.");

        var stalledPrimary = new CookbookScriptedHandler(CookbookBody.Sse(CookbookReplies.Delta("Thinking"), CookbookBody.Stall).Reply);
        using var deadline = new CancellationTokenSource(TimeSpan.FromMilliseconds(300));
        CookbookStreamOutcome cancelled;
        using (var client = new Client(Providers(stalledPrimary, new CookbookScriptedHandler()), route: FastRoute))
        {
            cancelled = CookbookStreamingExample.StreamAnswer(client, "Is the deploy safe?", new StringWriter(), deadline.Token);
        }

        ExampleSupport.Require(cancelled is { Status: CookbookStreamStatus.Cancelled, Shown: "Thinking" }
            && stalledPrimary.DisposeCount == 1,
            "The synchronous renderer did not stop when its token was cancelled.");
    }

    private static ProviderSettings[] Providers(HttpMessageHandler primary, HttpMessageHandler backup) =>
    [
        ProviderSettings.Of("openai-compat", "https://primary.offline/v1", transport: primary, alias: "primary"),
        ProviderSettings.Of("openai-compat", "https://backup.offline/v1", transport: backup, alias: "backup"),
    ];
}
