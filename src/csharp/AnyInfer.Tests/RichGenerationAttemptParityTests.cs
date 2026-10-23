using System.Runtime.CompilerServices;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public controls for attempt-local timing and terminal usage projection.</summary>
public sealed class RichGenerationAttemptParityTests
{
    [Fact]
    public async Task Winning_modern_attempt_reuses_the_generation_timing_including_first_content_and_phases()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token,
            new AdapterTextDelta("ok"),
            new AdapterFinal("stop", new Usage(InputTokens: 1, OutputTokens: 2), phases: [new("decode_ms", 3d)])));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)]);

        var result = await client.GenerateAsync("prompt", target: "alpha:model");

        var attempt = Assert.Single(result.Attempts);
        Assert.Equal("ok", attempt.Outcome);
        Assert.Equal(result.Timing, attempt.Timing);
        Assert.NotNull(attempt.Timing!.FirstTokenMs);
        Assert.Equal(3d, attempt.Timing.Phases["decode_ms"]);
    }

    [Fact]
    public async Task Failed_and_fallback_entries_have_isolated_measured_timing()
    {
        var failed = new ScriptedAdapter((_, _) => Throw(new ProviderException("offline", "transport", false, "generate")));
        var succeeded = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop")));
        await using var client = AsyncClient.FromAdapters(
        [
            new ProviderRegistration("first", failed),
            new ProviderRegistration("second", succeeded),
        ]);

        var result = await client.GenerateAsync("prompt", route: new Route(["first:model", "second:model"]));

        Assert.Equal(["failed", "ok"], result.Attempts.Select(static attempt => attempt.Outcome));
        Assert.All(result.Attempts, static attempt =>
        {
            Assert.NotNull(attempt.Timing);
            Assert.True(attempt.Timing!.TotalMs >= 0);
        });
        Assert.Null(result.Attempts[0].Timing!.FirstTokenMs);
        Assert.Equal(result.Timing, result.Attempts[1].Timing);
    }

    [Fact]
    public async Task Predispatch_refusal_has_a_measured_scope_but_no_first_token()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterFinal("unreachable")));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)]);
        var request = new GenerationRequest(
            [Message.User("prompt")],
            new Route(["alpha:model"]),
            serverTools: [new ServerToolSpec("web_search")]);

        var failure = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync(request));

        var attempt = Assert.Single(failure.Attempts);
        Assert.Equal("failed", attempt.Outcome);
        Assert.NotNull(attempt.Timing);
        Assert.Null(attempt.Timing!.FirstTokenMs);
        Assert.True(attempt.Timing.TotalMs >= 0);
    }

    [Fact]
    public async Task Server_tool_counts_without_terminal_usage_do_not_synthesize_a_usage_update()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token,
            new AdapterTextDelta("ok"),
            new AdapterFinal("stop", serverToolUses: [new ServerToolUse("web_search", 1), new ServerToolUse("web_search", 2)])));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)]);

        var stream = client.StreamAsync("prompt", target: "alpha:model");
        var events = await Collect(stream);

        Assert.Empty(events.OfType<UsageUpdate>());
        Assert.Equal([new ServerToolUse("web_search", 1), new ServerToolUse("web_search", 2)], stream.Result.ServerToolUses);
        Assert.Equal(2L, stream.Result.Usage!.ServerToolUses["web_search"]);
    }

    [Fact]
    public async Task Terminal_usage_still_projects_once_when_no_incremental_usage_event_exists()
    {
        var terminalUsage = new Usage(InputTokens: 3, OutputTokens: 5);
        var adapter = new ScriptedAdapter((_, token) => Events(token,
            new AdapterTextDelta("ok"), new AdapterFinal("stop", terminalUsage)));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)]);

        var stream = client.StreamAsync("prompt", target: "alpha:model");
        var events = await Collect(stream);

        Assert.Equal([terminalUsage], events.OfType<UsageUpdate>().Select(static update => update.Usage));
    }

    private static async Task<List<StreamEvent>> Collect(AsyncStream stream)
    {
        var events = new List<StreamEvent>();
        await foreach (var item in stream) events.Add(item);
        return events;
    }

    private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token, params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            token.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Throw(Exception error)
    {
        if (error is null)
        {
            yield return new AdapterFinal("unreachable");
            yield break;
        }

        await Task.Yield();
        throw error;
    }

    private sealed class ScriptedAdapter : IProviderAdapter
    {
        private readonly Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> _script;
        private int _calls;

        internal ScriptedAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) => _script = script;

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            _script(Interlocked.Increment(ref _calls), cancellationToken);

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
