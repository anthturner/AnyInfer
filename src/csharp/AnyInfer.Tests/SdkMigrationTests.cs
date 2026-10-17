using System.Runtime.CompilerServices;
using System.Diagnostics;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public SDK migration behavior, independent of conformance capture internals.</summary>
public sealed class SdkMigrationTests
{
    [Fact]
    public void Public_vocabulary_preserves_python_message_target_and_timing_contracts()
    {
        var user = Message.User("user");
        var system = Message.System("system");
        var assistant = Message.Assistant("assistant");

        Assert.Equal(["user", "system", "assistant"], [user.Role, system.Role, assistant.Role]);
        Assert.Equal("user", Assert.IsType<Text>(Assert.Single(user.Content)).Value);
        Assert.Throws<ArgumentNullException>(() => new Text(null!));

        var target = new ResolvedTarget("instance", "models/name:revision", "catalog-alias");
        Assert.Equal("instance:models/name:revision", target.ToString());
        Assert.Equal("catalog-alias", target.ViaAlias);
        Assert.Null(new ResolvedTarget("instance", "model").ViaAlias);

        var inputPhases = new Dictionary<string, double>(StringComparer.Ordinal)
        {
            ["model_load_ms"] = 0,
            ["first_token"] = 1.5,
        };
        var timing = new Timing(4, 1.5, 3, null, inputPhases);
        inputPhases["model_load_ms"] = 99;
        inputPhases["after-construction"] = 2;
        Assert.Equal(2, timing.Phases.Count);
        Assert.Equal(0, timing.Phases["model_load_ms"]);
        Assert.False(timing.Phases.ContainsKey("after-construction"));
        var immutablePhases = Assert.IsAssignableFrom<IDictionary<string, double>>(timing.Phases);
        Assert.Throws<NotSupportedException>(() => immutablePhases.Add("must-not-mutate", 1));
        Assert.All(timing.Phases, phase => Assert.True(double.IsFinite(phase.Value) && phase.Value >= 0));
    }

    [Fact]
    public async Task Prompt_and_message_conveniences_use_the_same_real_path_and_snapshot_caller_input()
    {
        var adapter = new ObservableAdapter((_, token) => Events(token,
            new AdapterTextDelta("ok"),
            new AdapterFinal("stop", new Usage(InputTokens: 2, OutputTokens: 1))));
        await using var client = new AsyncClient([new ProviderRegistration("alpha", adapter)]);

        List<Message> messages = [Message.System("keep"), Message.User("original")];
        var streamed = client.StreamAsync(messages, target: "alpha:model", sampling: new Sampling(stop: ["END"]));
        messages[1] = Message.User("mutated-after-call");
        var events = await Collect(streamed);
        var generated = await client.GenerateAsync("prompt", target: "alpha:model");

        Assert.Equal("ok", streamed.Result.Text);
        Assert.Equal("ok", generated.Text);
        Assert.Equal(2, adapter.Requests.Count);
        Assert.True(adapter.Requests[0].Stream);
        Assert.False(adapter.Requests[1].Stream);
        Assert.Equal(["keep", "original"], adapter.Requests[0].Messages.Select(Render));
        Assert.Equal("prompt", Render(Assert.Single(adapter.Requests[1].Messages)));
        Assert.Contains(events, static item => item is StreamEnded);
    }

    [Fact]
    public async Task Convenience_rejects_both_or_neither_target_and_route()
    {
        var adapter = new ObservableAdapter((_, token) => Events(token, new AdapterFinal("stop")));
        await using var client = new AsyncClient([new ProviderRegistration("alpha", adapter)]);

        Assert.Throws<ArgumentException>(() => client.StreamAsync("prompt"));
        Assert.Throws<ArgumentException>(() => client.StreamAsync("prompt", "alpha:model", new Route(["alpha:model"])));
        Assert.Empty(adapter.Requests);
    }

    [Fact]
    public async Task Stream_timing_uses_monotonic_seconds_and_single_captured_elapsed_values()
    {
        var adapter = new ObservableAdapter((_, token) => Events(token,
            new AdapterTextDelta("timed"),
            new AdapterFinal("stop", new Usage(OutputTokens: 4))));
        await using var client = new AsyncClient([new ProviderRegistration("alpha", adapter)]);

        var beforeIteration = Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
        var stream = client.StreamAsync("prompt", target: "alpha:model");
        var events = await Collect(stream);
        var afterTerminal = Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
        var result = stream.Result;
        var timing = Assert.IsType<Timing>(result.Timing);
        var firstToken = Assert.IsType<TimingMark>(Assert.Single(events, static item => item is TimingMark { Name: "first_token" }));

        Assert.InRange(timing.StartedAt, beforeIteration, afterTerminal);
        Assert.Equal(firstToken.AtMs, timing.FirstTokenMs!.Value);
        if (timing.TotalMs > timing.FirstTokenMs.Value)
        {
            Assert.Equal(
                4d / ((timing.TotalMs - timing.FirstTokenMs.Value) / 1000d),
                timing.OutputTokensPerS!.Value);
        }
    }

    [Fact]
    public async Task Stream_timing_keeps_throughput_unknown_for_zero_output_tokens_after_real_decode()
    {
        var adapter = new ObservableAdapter((_, token) => Events(token,
            new AdapterTextDelta("zero-token-usage"),
            new AdapterFinal("stop", new Usage(OutputTokens: 0))));
        await using var client = new AsyncClient([new ProviderRegistration("alpha", adapter)]);

        var stream = client.StreamAsync("prompt", target: "alpha:model");
        await Collect(stream);
        var result = stream.Result;
        var timing = Assert.IsType<Timing>(result.Timing);

        Assert.Equal(0L, Assert.IsType<Usage>(result.Usage).OutputTokens!.Value);
        Assert.NotNull(timing.FirstTokenMs);
        Assert.True(timing.TotalMs > timing.FirstTokenMs.Value);
        Assert.Null(timing.OutputTokensPerS);
    }

    [Fact]
    public async Task Stream_events_expose_real_attempt_scopes_for_fallback_and_repair()
    {
        var fallbackFailure = new ProviderException("first failed", "transport", false, "generate");
        var failed = new ObservableAdapter((_, _) => Throw(fallbackFailure));
        var succeeded = new ObservableAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("{\"age\":\"wrong\"}"), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("{\"age\":7}"), new AdapterFinal("stop")));
        var schema = JsonReader.Read("{\"type\":\"object\",\"required\":[\"age\"],\"properties\":{\"age\":{\"type\":\"integer\"}}}");
        await using var client = new AsyncClient(
        [
            new ProviderRegistration("first", failed),
            new ProviderRegistration("second", succeeded, maxRepairAttempts: 1),
        ]);

        var stream = client.StreamAsync("schema", route: new Route(["first:model", "second:model"]), repair: new Repair(1), schema: schema);
        var events = await Collect(stream);
        var result = stream.Result;
        var starts = events.OfType<TimingMark>().Where(mark => mark.Name == "attempt_start").ToArray();
        var firstTokens = events.OfType<TimingMark>().Where(mark => mark.Name == "first_token").ToArray();

        Assert.Equal("{\"age\":7}", result.Text);
        Assert.Equal(1, result.RepairAttempts);
        Assert.Contains(events, item => item is AttemptFailed { Record.Error: var error } && ReferenceEquals(error, fallbackFailure));
        Assert.Equal(3, starts.Length);
        Assert.Equal(2, firstTokens.Length);
        Assert.Equal(
            ["attempt_start", "attempt_start", "first_token", "attempt_start", "first_token"],
            events.OfType<TimingMark>().Select(mark => mark.Name));
        AssertTimingMarksAreScopedToFirstText(events);
        Assert.All(starts.Concat(firstTokens), mark => Assert.True(double.IsFinite(mark.AtMs) && mark.AtMs >= 0));
        Assert.All(events.OfType<StreamEnded>(), ended => Assert.Same(result, ended.Result));
        Assert.NotNull(result.Timing);
        Assert.True(double.IsFinite(result.Timing!.TotalMs) && result.Timing.TotalMs >= 0);
        Assert.All(result.Timing.Phases, phase => Assert.True(double.IsFinite(phase.Value) && phase.Value >= 0));
    }

    [Fact]
    public async Task Result_collect_single_consumer_and_early_close_follow_one_lazy_execution()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ObservableAdapter((_, token) => BlockAfterText(token, entered, cleaned));
        await using var client = new AsyncClient([new ProviderRegistration("alpha", adapter)]);
        var stream = client.StreamAsync("prompt", target: "alpha:model");

        Assert.Throws<InvalidOperationException>(() => _ = stream.Result);
        await using var enumerator = stream.GetAsyncEnumerator();
        Assert.Throws<InvalidOperationException>(() => stream.GetAsyncEnumerator());
        Assert.True(await enumerator.MoveNextAsync());
        Assert.IsType<TimingMark>(enumerator.Current);
        Assert.True(await enumerator.MoveNextAsync());
        Assert.IsType<TimingMark>(enumerator.Current);
        Assert.True(await enumerator.MoveNextAsync());
        Assert.IsType<TextDelta>(enumerator.Current);
        var pendingMove = enumerator.MoveNextAsync().AsTask();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        await stream.DisposeAsync();
        await cleaned.Task.WaitAsync(TimeSpan.FromSeconds(5));
        try
        {
            await pendingMove;
        }
        catch (OperationCanceledException)
        {
            // Closing the real blocked read may complete this pending pull through cancellation.
        }

        Assert.Equal(0, adapter.DisposeCalls);
        Assert.Throws<InvalidOperationException>(() => _ = stream.Result);
        await Assert.ThrowsAsync<InvalidOperationException>(() => stream.CollectAsync());

        await client.DisposeAsync();
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Collect_async_returns_terminal_generation_from_the_same_single_consumer_stream()
    {
        var adapter = new ObservableAdapter((_, token) => Events(token, new AdapterTextDelta("collected"), new AdapterFinal("stop")));
        await using var client = new AsyncClient([new ProviderRegistration("alpha", adapter)]);
        var stream = client.StreamAsync("prompt", target: "alpha:model");

        var result = await stream.CollectAsync();

        Assert.Equal("collected", result.Text);
        Assert.Same(result, stream.Result);
        Assert.Null(result.Timing!.OutputTokensPerS);
        Assert.Single(adapter.Requests);
        Assert.Throws<InvalidOperationException>(() => stream.GetAsyncEnumerator());
    }

    private static async Task<List<StreamEvent>> Collect(AsyncStream stream)
    {
        var events = new List<StreamEvent>();
        await foreach (var item in stream)
        {
            events.Add(item);
        }

        return events;
    }

    private static string Render(Message message) => string.Concat(message.Content.OfType<Text>().Select(static part => part.Value));

    private static void AssertTimingMarksAreScopedToFirstText(IEnumerable<StreamEvent> events)
    {
        var hasAttempt = false;
        var hasFirstToken = false;
        var hasText = false;
        StreamEvent? previous = null;

        foreach (var item in events)
        {
            switch (item)
            {
                case TimingMark { Name: "attempt_start" }:
                    if (hasAttempt)
                    {
                        Assert.True(
                            (!hasFirstToken && !hasText) || (hasFirstToken && hasText),
                            "Each completed content-bearing attempt must emit first_token immediately before its first text delta.");
                    }

                    hasAttempt = true;
                    hasFirstToken = false;
                    hasText = false;
                    break;
                case TimingMark { Name: "first_token" }:
                    Assert.True(hasAttempt, "first_token must follow an attempt_start.");
                    Assert.False(hasFirstToken, "An attempt may emit only one first_token mark.");
                    Assert.False(hasText, "first_token must precede the entry's first text delta.");
                    hasFirstToken = true;
                    break;
                case TextDelta:
                    Assert.True(hasAttempt, "Text must belong to an active attempt.");
                    if (!hasText)
                    {
                        Assert.True(hasFirstToken, "The entry's first text delta must follow first_token.");
                        Assert.IsType<TimingMark>(previous);
                        Assert.Equal("first_token", ((TimingMark)previous!).Name);
                    }

                    hasText = true;
                    break;
            }

            previous = item;
        }

        Assert.True(hasAttempt);
        Assert.True(
            (!hasFirstToken && !hasText) || (hasFirstToken && hasText),
            "The final content-bearing attempt must emit first_token immediately before its first text delta.");
    }

    private static async IAsyncEnumerable<AdapterEvent> Events(
        [EnumeratorCancellation] CancellationToken token,
        params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            token.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Throw(Exception failure)
    {
        if (failure is null)
        {
            yield break;
        }

        await Task.Yield();
        throw failure;
    }

    private static async IAsyncEnumerable<AdapterEvent> BlockAfterText(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource entered,
        TaskCompletionSource cleaned)
    {
        try
        {
            yield return new AdapterTextDelta("partial");
            entered.TrySetResult();
            await Task.Delay(Timeout.InfiniteTimeSpan, token);
        }
        finally
        {
            cleaned.TrySetResult();
        }
    }

    private sealed class ObservableAdapter : IProviderAdapter
    {
        private readonly Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> _script;
        private int _calls;

        internal ObservableAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) => _script = script;

        internal List<WireRequest> Requests { get; } = [];

        internal int DisposeCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return _script(Interlocked.Increment(ref _calls), cancellationToken);
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }
}
