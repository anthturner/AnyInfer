using AnyInfer.Capabilities;
using AnyInfer.Events;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Caller-owned in-process spend ledger controls.</summary>
public sealed class SpendLedgerTests
{
    [Fact]
    public void Ledger_records_completed_events_with_labels_unknowns_and_independent_ordinal_snapshots()
    {
        var ledger = new SpendLedger();
        var target = new ResolvedTarget("alpha", "model");
        ledger.OnEvent(new RequestStarted("one", ["alpha:model"], [new KeyValuePair<string, string>("team", "A")]));
        ledger.OnEvent(new RequestCompleted("one", target, new Usage(InputTokens: 2, OutputTokens: 3, CostUsd: EDecimal.FromString("1.0")), new Timing()));
        ledger.Record(target, new Usage(InputTokens: 0, CostUsd: EDecimal.Zero));
        ledger.Record(new ResolvedTarget("beta", "model"), new Usage(OutputTokens: 4));

        var totals = ledger.Totals();
        Assert.Equal(3, totals.Requests);
        Assert.Equal(1, totals.UnknownRequests);
        Assert.Equal(2, totals.InputTokens);
        Assert.Equal(7, totals.OutputTokens);
        Assert.False(totals.Complete);
        Assert.Equal(0, totals.Cost.CompareTo(EDecimal.One));
        var targets = ledger.ByTarget();
        Assert.Equal(["alpha:model", "beta:model"], targets.Keys);
        Assert.Equal(1, ledger.ByLabel("team")["A"].Requests);
        ledger.Record(target, new Usage(CostUsd: EDecimal.One));
        Assert.Equal(2, targets["alpha:model"].Requests);
    }

    [Fact]
    public void Ledger_reserve_uses_sum_all_minus_previous_and_rejections_preserve_the_prior_reservation()
    {
        var ledger = new SpendLedger();
        Assert.True(ledger.Reserve("a", EDecimal.FromInt32(3), EDecimal.FromInt32(10)).Accepted);
        Assert.True(ledger.Reserve("b", EDecimal.FromInt32(4), EDecimal.FromInt32(10)).Accepted);
        var rejected = ledger.Reserve("a", EDecimal.FromInt32(8), EDecimal.FromInt32(10));

        Assert.False(rejected.Accepted);
        Assert.Equal(0, rejected.Reserved.CompareTo(EDecimal.FromInt32(4)));
        Assert.Equal(0, ledger.Reserved().CompareTo(EDecimal.FromInt32(7)));
        Assert.True(ledger.Reserve("a", EDecimal.FromInt32(5), EDecimal.FromInt32(10)).Accepted);
        Assert.Equal(0, ledger.Reserved().CompareTo(EDecimal.FromInt32(9)));
        ledger.Release("a");
        Assert.Equal(0, ledger.Reserved().CompareTo(EDecimal.FromInt32(4)));
        ledger.Reset();
        Assert.Equal(0, ledger.Reserved().CompareTo(EDecimal.Zero));
        Assert.Equal(0, ledger.Totals().Requests);
    }

    [Fact]
    public async Task Ledger_serializes_reservation_record_release_state_under_its_own_lock()
    {
        var ledger = new SpendLedger();
        var target = new ResolvedTarget("alpha", "model");
        var ready = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var first = Task.Run(async () =>
        {
            Assert.True(ledger.Reserve("one", EDecimal.One, EDecimal.FromInt32(2)).Accepted);
            ready.TrySetResult();
            await release.Task;
            ledger.Record(target, new Usage(CostUsd: EDecimal.One), "one");
        });
        await ready.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var second = Task.Run(() => ledger.Reserve("two", EDecimal.FromInt32(2), EDecimal.FromInt32(2)));
        var rejected = await second.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.False(rejected.Accepted);
        release.TrySetResult();
        await first.WaitAsync(TimeSpan.FromSeconds(5));
        ledger.Release("two");
        Assert.Equal(0, ledger.Reserved().CompareTo(EDecimal.Zero));
        Assert.Equal(1, ledger.Totals().Requests);
    }
}
