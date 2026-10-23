using System.Runtime.CompilerServices;
using AnyInfer.Core;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Compatibility controls for FrozenV0 winning-result timing.</summary>
public sealed class FrozenTimingCompatibilityTests
{
    [Fact]
    public async Task Frozen_winning_result_retains_the_entry_timing_that_its_marks_observe()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token,
            new AdapterTextDelta("done"),
            new AdapterFinal("stop")));
        await using var client = new AsyncClient([new ProviderRegistration("frozen", adapter)], new SystemOperationClock());
        var stream = client.StreamAsync(new GenerationRequest([Message.User("prompt")], new Route(["frozen:model"])));
        var events = new List<StreamEvent>();

        await foreach (var item in stream)
        {
            events.Add(item);
        }

        var result = stream.Result;
        Assert.Contains(events, static item => item is TimingMark { Name: "attempt_start" });
        Assert.Contains(events, static item => item is TimingMark { Name: "first_token" });
        Assert.NotNull(result.Timing);
        Assert.NotNull(result.Timing!.FirstTokenMs);
        Assert.True(result.Timing.TotalMs >= result.Timing.FirstTokenMs);
        Assert.Null(Assert.Single(result.Attempts).Timing);
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

    private sealed class ScriptedAdapter(Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            script(request, cancellationToken);

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
