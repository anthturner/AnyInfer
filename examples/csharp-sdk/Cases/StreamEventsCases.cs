using System.Net;
using System.Text.RegularExpressions;
using AnyInfer.Providers;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes the stream-event recipes published in the streaming guide.</summary>
internal static class StreamEventsCases
{
    private static readonly Route ScriptedRoute = new(["broken:demo", "scripted:demo"], retry: new Retry(1));

    [ExampleCase("stream-events.describe-every-event")]
    internal static async Task DescribeEveryEvent()
    {
        var broken = new GuideScripts.FailingAdapter(new ProviderUnavailableException("offline outage", provider: "broken"));
        var scripted = RichAdapter();
        await using var client = AsyncClient.FromAdapters(
        [
            new ProviderRegistration("broken", broken),
            new ProviderRegistration("scripted", scripted),
        ]);
        await using var stream = client.StreamAsync("What is the capital of France?", route: ScriptedRoute);
        ExampleSupport.Require(broken.Calls == 0 && scripted.Calls == 0, "An asynchronous stream sent a request before it was enumerated.");
        GuideScripts.ExpectThrows<InvalidOperationException>(() => _ = stream.Result, "Result was readable before the stream completed.");

        var lines = await StreamEventsExample.LogAsync(stream);
        string[] expected =
        [
            "timing attempt_start at 0 ms",
            "attempt broken:demo failed: ProviderUnavailableException",
            "timing attempt_start at 0 ms",
            "timing first_token at * ms",
            "reasoning Recall the capital.",
            "text Paris",
            "citation Atlas <https://atlas.example/france>",
            "tool call #0 lookup_population {\"city\":\"Paris\"}",
            "server tool web_search completed",
            "usage 3 in, 5 out",
            "ended tool_calls from scripted:demo",
        ];
        ExampleSupport.Require(lines.Count == expected.Length
            && lines.Zip(expected).All(static pair => Matches(pair.First, pair.Second)),
            $"Stream events arrived as [{string.Join(" | ", lines)}].");

        var result = stream.Result;
        ExampleSupport.Require(result.Text == "Paris"
            && result.Citations.Single().Uri == "https://atlas.example/france"
            && result.ToolCalls.Single().Name == "lookup_population"
            && result.Attempts.Select(static attempt => attempt.Outcome).SequenceEqual(["failed", "ok"])
            && broken.Calls == 1
            && scripted.Calls == 1,
            "The terminal generation did not keep the streamed facts.");
        await GuideScripts.ExpectThrowsAsync<InvalidOperationException>(
            async () => await StreamEventsExample.LogAsync(stream),
            "A stream accepted a second consumer.");
    }

    [ExampleCase("stream-events.stream-ended-is-result")]
    internal static async Task StreamEndedIsResult()
    {
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("scripted", RichAdapter())]);
        await using var stream = client.StreamAsync("What is the capital of France?", target: "scripted:demo");
        Generation? ended = null;
        await foreach (var item in stream)
        {
            if (item is StreamEnded end)
            {
                ended = end.Result;
            }
        }

        ExampleSupport.Require(ended is not null && ReferenceEquals(ended, stream.Result) && ended.Manifest is { Complete: true },
            "StreamEnded did not carry the same terminal generation that Result returns.");

        await using var collected = client.StreamAsync("What is the capital of France?", target: "scripted:demo");
        var result = await collected.CollectAsync();
        ExampleSupport.Require(ReferenceEquals(result, collected.Result) && result.Text == "Paris",
            "CollectAsync did not return the stream's terminal result.");
    }

    [ExampleCase("stream-events.show-thinking")]
    internal static async Task ShowThinking()
    {
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("scripted", RichAdapter())]);
        await using var stream = client.StreamAsync("What is the capital of France?", target: "scripted:demo");
        var answer = new StringWriter();
        var thinking = new StringWriter();
        var result = await StreamEventsExample.ShowThinkingAsync(stream, answer, thinking);
        ExampleSupport.Require(answer.ToString() == "Paris"
            && thinking.ToString() == "Recall the capital."
            && result.Text == "Paris",
            "Reasoning was not kept separate from the answer.");
    }

    [ExampleCase("stream-events.first-token")]
    internal static async Task FirstToken()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        await using var client = new AsyncClient([GuideScripts.Instance(handler)]);
        await using var stream = client.StreamAsync("Say hello.", target: ExampleSupport.Target);
        var output = new StringWriter();
        var result = await StreamEventsExample.ShowFirstTokenAsync(stream, output);
        ExampleSupport.Require(Regex.IsMatch(output.ToString(), @"^\[\d+ ms\] hello$")
            && result.Timing?.FirstTokenMs is >= 0
            && result.Text == "hello"
            && handler.RequestCount == 1,
            $"Time to first token was rendered as '{output}'.");
    }

    [ExampleCase("stream-events.show-fallback")]
    internal static async Task ShowFallback()
    {
        var primary = new GuideScripts.ChatHandler(GuideScripts.Status(HttpStatusCode.ServiceUnavailable));
        var backup = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        await using var client = new AsyncClient([GuideScripts.Instance(primary, "primary"), GuideScripts.Instance(backup, "backup")]);
        await using var stream = client.StreamAsync("Say hello.", route: new Route(["primary:demo", "backup:demo"], retry: new Retry(1)));
        var output = new StringWriter();
        var result = await StreamEventsExample.ShowFallbackAsync(stream, output);
        ExampleSupport.Require(output.ToString() == $"[primary:demo failed: ProviderUnavailableException]{Environment.NewLine}hello"
            && result.Target?.ToString() == "backup:demo"
            && primary.RequestCount == 1
            && backup.RequestCount == 1,
            $"The fallback was rendered as '{output}'.");
    }

    [ExampleCase("stream-events.all-targets-failed")]
    internal static async Task AllTargetsFailed()
    {
        var primary = new GuideScripts.ChatHandler(GuideScripts.Status(HttpStatusCode.ServiceUnavailable));
        var backup = new GuideScripts.ChatHandler(GuideScripts.Status(HttpStatusCode.BadGateway));
        await using var client = new AsyncClient([GuideScripts.Instance(primary, "primary"), GuideScripts.Instance(backup, "backup")]);
        await using var stream = client.StreamAsync("Say hello.", route: new Route(["primary:demo", "backup:demo"], retry: new Retry(1)));
        var output = new StringWriter();
        var errors = new StringWriter();
        var result = await StreamEventsExample.TryStreamAsync(stream, output, errors);
        var nl = Environment.NewLine;
        ExampleSupport.Require(result is null
            && output.ToString().Length == 0
            && errors.ToString() == $"primary:demo: failed (ProviderUnavailableException){nl}backup:demo: failed (ProviderUnavailableException){nl}",
            $"Exhausted targets were reported as '{errors}'.");
        GuideScripts.ExpectThrows<InvalidOperationException>(() => _ = stream.Result, "A failed stream exposed a terminal result.");
    }

    [ExampleCase("stream-events.protocol-failure-after-content")]
    internal static async Task ProtocolFailureAfterContent()
    {
        var primary = new GuideScripts.ChatHandler(GuideScripts.Events(
            "{\"choices\":[{\"delta\":{\"content\":\"hel\"}}]}",
            "{not json"));
        var backup = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        await using var client = new AsyncClient([GuideScripts.Instance(primary, "primary"), GuideScripts.Instance(backup, "backup")]);
        await using var stream = client.StreamAsync("Say hello.", route: new Route(["primary:demo", "backup:demo"], retry: new Retry(1)));
        var output = new StringWriter();
        await GuideScripts.ExpectThrowsAsync<StreamProtocolException>(
            async () => await StreamEventsExample.TryStreamAsync(stream, output, TextWriter.Null),
            "A stream that broke after emitting content was not reported as a protocol failure.");
        ExampleSupport.Require(output.ToString() == "hel" && backup.RequestCount == 0,
            "A stream that broke after emitting content fell back to another target.");
    }

    [ExampleCase("stream-events.missing-route")]
    internal static async Task MissingRoute()
    {
        var handler = new GuideScripts.ChatHandler();
        await using var client = new AsyncClient([GuideScripts.Instance(handler)]);
        GuideScripts.ExpectThrows<ConfigException>(() => client.StreamAsync("Say hello."), "A stream without a target or route was created.");
        ExampleSupport.Require(handler.RequestCount == 0, "A stream without a target sent a request.");
    }

    private static GuideScripts.EventAdapter RichAdapter() => new(
        new AdapterReasoningDelta("Recall the capital."),
        new AdapterTextDelta("Paris"),
        new AdapterCitationDelta(new Citation(title: "Atlas", uri: "https://atlas.example/france")),
        new AdapterToolCallDelta(0, "call-1", "lookup_population", "{\"city\":\"Paris\"}"),
        new AdapterServerToolDelta("web_search", "completed"),
        new AdapterUsage(new Usage(InputTokens: 3, OutputTokens: 5)),
        new AdapterFinal("stop"));

    private static bool Matches(string actual, string pattern) =>
        Regex.IsMatch(actual, "^" + Regex.Escape(pattern).Replace(@"\*", @"\d+") + "$");
}
