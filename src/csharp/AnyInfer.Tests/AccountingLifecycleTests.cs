using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Winning-generation accounting projection controls.</summary>
public sealed class AccountingLifecycleTests
{
    [Fact]
    public async Task Correction_uses_only_the_winning_normalized_usage_for_result_completion_and_manifest_pricing()
    {
        var adapter = new ScriptedAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("not-json"), new AdapterUsage(new Usage(InputTokens: 90, OutputTokens: 90)), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("{\"answer\":\"ok\"}"), new AdapterUsage(new Usage(InputTokens: 2, OutputTokens: 3)), new AdapterFinal("stop")));
        var observer = new Collector();
        await using var client = Client(adapter, observer, TrustedPricing());

        var result = await client.GenerateAsync("repair", target: "alpha:model", schema: Schema(), repair: new Repair(1));

        Assert.Equal(2, adapter.Calls);
        Assert.Equal(2, result.Usage!.InputTokens);
        Assert.Equal(3, result.Usage.OutputTokens);
        Assert.Equal(5, result.Usage.TotalTokens);
        EqualDecimal(D("8"), result.Usage.CostUsd);
        var completed = Assert.IsType<RequestCompleted>(Assert.Single(observer.Events.OfType<RequestCompleted>()));
        EqualDecimal(D("8"), completed.Usage.CostUsd);
        Assert.Equal("8.000000", result.Manifest!.Usage.CostUsd);
        Assert.Equal(1, result.RepairAttempts);
    }

    [Fact]
    public async Task Provider_reported_cost_wins_while_default_unknown_and_free_pricing_remain_distinct()
    {
        var reportedAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterUsage(new Usage(InputTokens: 2, OutputTokens: 3, CostUsd: D("7.25"))), new AdapterFinal("stop")));
        await using var reportedClient = Client(reportedAdapter, null, TrustedPricing());
        EqualDecimal(D("7.25"), (await reportedClient.GenerateAsync("x", target: "alpha:model")).Usage!.CostUsd);

        var defaultAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterUsage(new Usage(InputTokens: 2, OutputTokens: 3)), new AdapterFinal("stop")));
        await using var defaultClient = Client(defaultAdapter, null, new Sourced<Pricing>(Rates(), Provenance.Default));
        Assert.Null((await defaultClient.GenerateAsync("x", target: "alpha:model")).Usage!.CostUsd);

        var freeAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterUsage(new Usage(InputTokens: 2, OutputTokens: 3)), new AdapterFinal("stop")));
        await using var freeClient = Client(freeAdapter, null, new Sourced<Pricing>(new Pricing(EDecimal.Zero, EDecimal.Zero), Provenance.Catalog));
        EqualDecimal(EDecimal.Zero, (await freeClient.GenerateAsync("x", target: "alpha:model")).Usage!.CostUsd);
    }

    [Fact]
    public async Task Retried_entry_does_not_contribute_usage_or_price_when_the_later_entry_wins()
    {
        var retry = new ProviderException("retry", "transport", true, "generate");
        var adapter = new ScriptedAdapter((call, token) => call == 1
            ? EventsThenThrow(token, retry, new AdapterUsage(new Usage(InputTokens: 90, OutputTokens: 90)))
            : Events(token, new AdapterTextDelta("ok"), new AdapterUsage(new Usage(InputTokens: 4, OutputTokens: 1)), new AdapterFinal("stop")));
        var observer = new Collector();
        await using var client = Client(adapter, observer, TrustedPricing());

        var result = await client.GenerateAsync(new GenerationRequest([Message.User("x")], new Route(["alpha:model"], new Retry(MaxAttempts: 2, BackoffBaseS: 0, BackoffMaxS: 0))));

        Assert.Equal(2, adapter.Calls);
        Assert.Equal(4, result.Usage!.InputTokens);
        Assert.Equal(1, result.Usage.OutputTokens);
        EqualDecimal(D("6"), result.Usage.CostUsd);
        Assert.Single(observer.Events.OfType<RetryScheduled>());
        EqualDecimal(D("6"), Assert.Single(observer.Events.OfType<RequestCompleted>()).Usage.CostUsd);
    }

    [Fact]
    public async Task Winning_usage_normalization_overflow_prevents_completion_charge_and_manifest_commit_but_explicit_total_short_circuits()
    {
        var overflowAdapter = new ScriptedAdapter((_, token) => Events(token,
            new AdapterTextDelta("ok"), new AdapterUsage(new Usage(InputTokens: long.MaxValue, OutputTokens: 1)), new AdapterFinal("stop")));
        var overflowObserver = new Collector();
        var overflowLedger = new SpendLedger();
        await using var overflowClient = Client(overflowAdapter, overflowObserver, TrustedPricing(), ledger: overflowLedger);
        var stream = overflowClient.StreamAsync("x", target: "alpha:model");

        await Assert.ThrowsAsync<OverflowException>(() => stream.CollectAsync());
        Assert.Empty(overflowObserver.Events.OfType<RequestCompleted>());
        Assert.False(stream.Manifest!.Complete);
        Assert.Equal(0, overflowLedger.Totals().Requests);
        EqualDecimal(EDecimal.Zero, overflowLedger.Totals().Cost);
        Assert.Empty(overflowLedger.ByTarget());

        var explicitAdapter = new ScriptedAdapter((_, token) => Events(token,
            new AdapterTextDelta("ok"), new AdapterUsage(new Usage(InputTokens: long.MaxValue, OutputTokens: 1, TotalTokens: 9)), new AdapterFinal("stop")));
        await using var explicitClient = Client(explicitAdapter, null, TrustedPricing());
        var result = await explicitClient.GenerateAsync("x", target: "alpha:model");
        Assert.Equal(9, result.Usage!.TotalTokens);
    }

    [Fact]
    public async Task Shared_caller_owned_ledger_observes_only_completed_generation_and_client_spend_reads_its_snapshot()
    {
        var ledger = new SpendLedger();
        var firstAdapter = new ScriptedAdapter((_, token) => Events(token,
            new AdapterTextDelta("ok"), new AdapterUsage(new Usage(InputTokens: 2, OutputTokens: 3)), new AdapterFinal("stop")));
        var secondAdapter = new ScriptedAdapter((_, token) => Events(token,
            new AdapterTextDelta("ok"), new AdapterUsage(new Usage(InputTokens: 1, OutputTokens: 1)), new AdapterFinal("stop")));
        var first = Client(firstAdapter, null, TrustedPricing(), ledger: ledger);
        await using var second = Client(secondAdapter, null, TrustedPricing(), ledger: ledger);

        var result = await first.GenerateAsync("x", target: "alpha:model");
        await first.DisposeAsync();
        await second.GenerateAsync("y", target: "alpha:model");

        EqualDecimal(D("8"), result.Usage!.CostUsd);
        Assert.Equal(2, second.Spend().Requests);
        EqualDecimal(D("11"), second.Spend().Cost);
        ledger.Record(new ResolvedTarget("other", "model"), new Usage(CostUsd: D("2")));
        EqualDecimal(D("13"), second.Spend().Cost);
    }

    [Fact]
    public async Task Unadvanced_close_releases_public_partial_manifest_reservation_without_starting_generation()
    {
        var ledger = new SpendLedger();
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("unused"), new AdapterFinal("stop")));
        var observer = new Collector();
        await using var client = Client(adapter, observer, TrustedPricing(), ledger: ledger);
        var stream = client.StreamAsync("x", target: "alpha:model");
        var requestId = stream.Manifest!.RequestId;
        Assert.True(ledger.Reserve(requestId, D("3"), D("3")).Accepted);

        await stream.DisposeAsync();

        EqualDecimal(EDecimal.Zero, ledger.Reserved());
        Assert.Empty(observer.Events);
        Assert.Equal(0, adapter.Calls);
    }

    [Fact]
    public async Task Raw_probe_does_not_publish_generation_telemetry_or_ledger_spend()
    {
        var ledger = new SpendLedger();
        var observer = new Collector();
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("{}"), new AdapterFinal("stop")));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer], ledger: ledger);

        await client.ProbeAsync("alpha:model", [Feature.JsonMode]);

        Assert.Empty(observer.Events);
        Assert.Equal(0, client.Spend().Requests);
        EqualDecimal(EDecimal.Zero, client.Spend().Cost);
    }

    [Fact]
    public async Task Async_budget_is_a_post_close_pure_query_that_uses_configured_estimator_without_adapter_work()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("unused"), new AdapterFinal("stop")));
        var estimator = new FixedEstimator(new TokenEstimate(7, 5));
        var client = Client(adapter, null, TrustedPricing(), estimator: estimator);
        await client.DisposeAsync();

        var budget = client.Budget("prompt", "alpha:model", outputReserveTokens: 4);

        Assert.Equal(4, budget.OutputReserveTokens);
        Assert.Equal(11, budget.Estimate.Tokens);
        Assert.Equal(5, budget.Estimate.Floor);
        Assert.Equal(1, estimator.Calls);
        Assert.Equal(0, adapter.Calls);
        Assert.Equal(0, client.Spend().Requests);
    }

    [Fact]
    public void Sync_budget_and_spend_refuse_after_close_before_estimator_or_adapter_work()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("unused"), new AdapterFinal("stop")));
        var estimator = new FixedEstimator(new TokenEstimate(7, 5));
        var descriptor = Descriptor(adapter, TrustedPricing());
        using var client = new Client([ProviderSettings.Of("alpha")], new ProviderRegistry([descriptor]), estimator: estimator);
        client.Dispose();

        Assert.Throws<ObjectDisposedException>(() => client.Spend());
        Assert.Throws<ObjectDisposedException>(() => client.Budget("prompt", "alpha:model"));
        Assert.Equal(0, estimator.Calls);
        Assert.Equal(0, adapter.Calls);
    }

    [Fact]
    public async Task All_budget_overloads_resolve_only_metadata_and_never_construct_an_adapter_or_emit_events()
    {
        var estimator = new FixedEstimator(new TokenEstimate(3, 2));
        var factoryCalls = 0;
        var observer = new Collector();
        var descriptor = new ProviderDescriptor(
            "alpha", "Alpha", (_, _) =>
            {
                factoryCalls++;
                throw new InvalidOperationException("Budget must not construct an adapter.");
            },
            staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal)
            {
                ["model"] = new ModelCapabilities(contextWindow: new Sourced<int>(100, Provenance.Catalog)),
            },
            tokenCalibration: new TokenCalibration(2, 1));
        var client = new AsyncClient([ProviderSettings.Of("alpha")], new ProviderRegistry([descriptor]), observers: [observer], estimator: estimator);

        var requestBudget = client.Budget(new GenerationRequest([Message.User("x")], new Route(["alpha:model"])), "alpha:model");
        var promptBudget = client.Budget("x", "alpha:model");
        var messagesBudget = client.Budget([Message.User("x")], "alpha:model");

        Assert.Equal(3, estimator.Calls);
        Assert.Equal(0, factoryCalls);
        Assert.Empty(observer.Events);
        Assert.Equal(15, requestBudget.Estimate.Tokens);
        Assert.Equal(15, promptBudget.Estimate.Tokens);
        Assert.Equal(15, messagesBudget.Estimate.Tokens);
        await client.DisposeAsync();
    }

    [Fact]
    public async Task Active_caller_cancellation_releases_reserved_partial_manifest_without_terminal_events_or_charge()
    {
        var ledger = new SpendLedger();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var caller = new CancellationTokenSource();
        var planted = new OperationCanceledException(caller.Token);
        var adapter = new ScriptedAdapter((_, token) => Blocking(token, planted, entered));
        var observer = new CallbackObserver(item =>
        {
            if (item is RequestStarted started)
            {
                Assert.True(ledger.Reserve(started.RequestId, D("3"), D("3")).Accepted);
            }
        });
        await using var client = Client(adapter, observer, TrustedPricing(), ledger: ledger);
        var stream = client.StreamAsync("x", target: "alpha:model", cancellationToken: caller.Token);
        var pending = stream.CollectAsync();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        EqualDecimal(D("3"), ledger.Reserved());
        caller.Cancel();

        var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(caller.Token, cancelled.CancellationToken);
        EqualDecimal(EDecimal.Zero, ledger.Reserved());
        Assert.Equal(0, ledger.Totals().Requests);
        Assert.Empty(ledger.ByTarget());
        Assert.False(stream.Manifest!.Complete);
    }

    private static AsyncClient Client(ScriptedAdapter adapter, IObserver? observer, Sourced<Pricing> pricing, ITokenEstimator? estimator = null, SpendLedger? ledger = null)
    {
        return new AsyncClient([ProviderSettings.Of("alpha")], new ProviderRegistry([Descriptor(adapter, pricing)]), observers: observer is null ? null : [observer], estimator: estimator, ledger: ledger);
    }

    private static ProviderDescriptor Descriptor(ScriptedAdapter adapter, Sourced<Pricing> pricing) =>
        new ProviderDescriptor(
            "alpha", "Alpha", (_, _) => ValueTask.FromResult<IProviderAdapter>(adapter),
            staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal)
            {
                ["model"] = new ModelCapabilities(pricing: pricing),
            });

    private static Sourced<Pricing> TrustedPricing() => new(Rates(), Provenance.Catalog);

    private static Pricing Rates() => new(D("1000000"), D("2000000"));

    private static SchemaSpec Schema() => new(new JsonObject([
        new JsonProperty("type", new JsonString("object")),
        new JsonProperty("required", new JsonArray([new JsonString("answer")])),
        new JsonProperty("properties", new JsonObject([new JsonProperty("answer", new JsonObject([new JsonProperty("type", new JsonString("string"))]))])),
    ]));

    private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token, params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            token.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Throw(Exception exception)
    {
        await Task.Yield();
        System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(exception).Throw();
        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> EventsThenThrow([EnumeratorCancellation] CancellationToken token, Exception exception, params AdapterEvent[] events)
    {
        await foreach (var item in Events(token, events)) yield return item;
        System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(exception).Throw();
        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> Blocking([EnumeratorCancellation] CancellationToken token, OperationCanceledException planted, TaskCompletionSource entered)
    {
        entered.TrySetResult();
        try
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, token);
        }
        catch (OperationCanceledException)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(planted).Throw();
        }
        yield break;
    }

    private static EDecimal D(string value) => EDecimal.FromString(value);

    private static void EqualDecimal(EDecimal expected, EDecimal? actual)
    {
        Assert.NotNull(actual);
        Assert.Equal(0, expected.CompareTo(actual!));
    }

    private sealed class ScriptedAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        public int Calls { get; private set; }
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => script(++Calls, cancellationToken);
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class Collector : IObserver
    {
        public List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }

    private sealed class CallbackObserver(Action<TelemetryEvent> callback) : IObserver
    {
        public void OnEvent(TelemetryEvent telemetryEvent) => callback(telemetryEvent);
    }

    private sealed class FixedEstimator(TokenEstimate estimate) : ITokenEstimator
    {
        public int Calls { get; private set; }
        public TokenEstimate Estimate(string text)
        {
            Calls++;
            return estimate;
        }
    }
}
