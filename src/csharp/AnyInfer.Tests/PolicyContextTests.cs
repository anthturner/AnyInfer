using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Config;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public-client controls for spend admission and context-window route replacement.</summary>
public sealed class PolicyContextTests
{
    [Fact]
    public async Task Unknown_refuse_is_a_direct_spend_limit_after_factory_acquisition_without_adapter_dispatch()
    {
        var adapter = new RecordingAdapter(static token => Success(token));
        var factoryCalls = 0;
        await using var client = CreateClient(
            "alpha",
            adapter,
            new ModelCapabilities(),
            spendPolicy: new SpendPolicy(D("7"), EDecimal.Zero, "refuse"),
            onFactory: () => factoryCalls++);

        var error = await Assert.ThrowsAsync<SpendLimitException>(() =>
            client.GenerateAsync("request", target: "alpha:model"));

        EqualDecimal(D("7"), error.LimitUsd);
        EqualDecimal(EDecimal.Zero, error.SpentUsd);
        Assert.Null(error.EstimatedUsd);
        Assert.Equal("spend_limit", error.Category);
        Assert.Equal("generate", error.Phase);
        Assert.False(error.Retryable);
        Assert.Null(error.Provider);
        Assert.Equal(1, factoryCalls);
        Assert.Equal(0, adapter.GenerateCalls);
        Assert.Equal(0, client.Spend().Requests);
        EqualDecimal(EDecimal.Zero, client.Spend().Cost);

        var zeroTotalAdapter = new RecordingAdapter(static token => Success(token));
        await using var zeroTotal = CreateClient(
            "zero-total",
            zeroTotalAdapter,
            new ModelCapabilities(),
            spendPolicy: new SpendPolicy(EDecimal.Zero, EDecimal.Zero, "refuse"));
        var zeroTotalError = await Assert.ThrowsAsync<SpendLimitException>(() =>
            zeroTotal.GenerateAsync("request", target: "zero-total:model"));
        EqualDecimal(EDecimal.Zero, zeroTotalError.LimitUsd);
        Assert.Equal(0, zeroTotalAdapter.GenerateCalls);

        var unboundedAdapter = new RecordingAdapter(static token => Success(token));
        await using var unbounded = CreateClient(
            "unbounded",
            unboundedAdapter,
            new ModelCapabilities(),
            spendPolicy: new SpendPolicy(maxRequestUsd: EDecimal.Zero, onUnknown: "refuse"));
        var unboundedError = await Assert.ThrowsAsync<SpendLimitException>(() =>
            unbounded.GenerateAsync("request", target: "unbounded:model"));
        Assert.Null(unboundedError.LimitUsd);
        Assert.Equal(0, unboundedAdapter.GenerateCalls);
    }

    [Fact]
    public async Task Supplied_inactive_policy_still_installs_one_ledger_and_known_zero_or_positive_estimates_follow_the_request_ceiling()
    {
        var freeAdapter = new RecordingAdapter(static token => Success(token));
        var suppliedLedger = new SpendLedger();
        await using var freeClient = CreateClient(
            "free",
            freeAdapter,
            Capabilities(pricing: new Pricing(EDecimal.Zero, EDecimal.Zero)),
            spendPolicy: new SpendPolicy(),
            ledger: suppliedLedger);

        var free = await freeClient.GenerateAsync("request", target: "free:model");

        Assert.Equal(1, freeAdapter.GenerateCalls);
        EqualDecimal(EDecimal.Zero, free.Usage!.CostUsd);
        Assert.Equal(1, freeClient.Spend().Requests);
        EqualDecimal(EDecimal.Zero, freeClient.Spend().Cost);
        Assert.Equal(1, suppliedLedger.Totals().Requests);

        var autoAdapter = new RecordingAdapter(static token => Success(token));
        await using var autoClient = CreateClient(
            "auto",
            autoAdapter,
            Capabilities(pricing: new Pricing(EDecimal.Zero, EDecimal.Zero)),
            spendPolicy: new SpendPolicy());
        await autoClient.GenerateAsync("request", target: "auto:model");
        Assert.Equal(1, autoClient.Spend().Requests);

        var pricedAdapter = new RecordingAdapter(static token => Success(token));
        var pricedFactoryCalls = 0;
        await using var pricedClient = CreateClient(
            "priced",
            pricedAdapter,
            Capabilities(pricing: new Pricing(D("1000000"), EDecimal.Zero)),
            estimator: new FixedEstimator(new TokenEstimate(1, 1)),
            spendPolicy: new SpendPolicy(maxRequestUsd: EDecimal.Zero),
            onFactory: () => pricedFactoryCalls++);

        var error = await Assert.ThrowsAsync<SpendLimitException>(() =>
            pricedClient.GenerateAsync("request", target: "priced:model"));

        EqualDecimal(EDecimal.Zero, error.LimitUsd);
        Assert.NotNull(error.EstimatedUsd);
        Assert.True(error.EstimatedUsd!.CompareTo(EDecimal.Zero) > 0);
        Assert.Equal(1, pricedFactoryCalls);
        Assert.Equal(0, pricedAdapter.GenerateCalls);
        Assert.Equal(0, pricedClient.Spend().Requests);
    }

    [Fact]
    public async Task Context_gate_replaces_the_ordinary_route_with_the_specialized_chain_before_adapter_dispatch()
    {
        var small = new RecordingAdapter(static token => Success(token));
        var large = new RecordingAdapter(static token => Success(token));
        var smallFactoryCalls = 0;
        var observer = new Collector();
        var smallDescriptor = Descriptor(
            "small",
            small,
            Capabilities(contextWindow: 3),
            onFactory: () => smallFactoryCalls++);
        var largeDescriptor = Descriptor("large", large, Capabilities(contextWindow: 100));
        await using var client = new AsyncClient(
            [ProviderSettings.Of("small"), ProviderSettings.Of("large")],
            new ProviderRegistry([smallDescriptor, largeDescriptor]),
            observers: [observer],
            estimator: new FixedEstimator(new TokenEstimate(4, 4)));
        var route = new Route(["small:model"], contextWindowTargets: ["large:model"]);

        var result = await client.GenerateAsync(new GenerationRequest([Message.User("request")], route));

        Assert.Equal("large", result.Target!.ProviderId);
        Assert.Equal(1, smallFactoryCalls);
        Assert.Equal(0, small.GenerateCalls);
        Assert.Equal(1, large.GenerateCalls);
        Assert.Contains(result.Attempts, static attempt => attempt.Target?.ProviderId == "small" && attempt.Error is ContextLengthException);
        Assert.Contains(observer.Events, static item => item is FallbackTriggered fallback && fallback.ToTarget == "large:model");
    }

    [Fact]
    public async Task Provider_context_failure_uses_the_specialized_chain_and_an_empty_chain_preserves_the_ordinary_fallback()
    {
        var overflowing = new RecordingAdapter(token => ThrowAfterYield(token, new ContextLengthException("overflow")));
        var specialized = new RecordingAdapter(static token => Success(token));
        var ordinary = new RecordingAdapter(static token => Success(token));
        var descriptors = new ProviderRegistry([
            Descriptor("first", overflowing, Capabilities()),
            Descriptor("special", specialized, Capabilities()),
            Descriptor("ordinary", ordinary, Capabilities()),
        ]);
        await using var redirected = new AsyncClient(
            [ProviderSettings.Of("first"), ProviderSettings.Of("special"), ProviderSettings.Of("ordinary")],
            descriptors);

        var specializedResult = await redirected.GenerateAsync(new GenerationRequest(
            [Message.User("request")],
            new Route(["first:model", "ordinary:model"], contextWindowTargets: ["special:model", "special:model"])));

        Assert.Equal("special", specializedResult.Target!.ProviderId);
        Assert.Equal(1, overflowing.GenerateCalls);
        Assert.Equal(1, specialized.GenerateCalls);
        Assert.Equal(0, ordinary.GenerateCalls);

        var emptyOverflow = new RecordingAdapter(token => ThrowAfterYield(token, new ContextLengthException("overflow")));
        var fallback = new RecordingAdapter(static token => Success(token));
        await using var ordinaryFallback = new AsyncClient(
            [ProviderSettings.Of("first"), ProviderSettings.Of("ordinary")],
            new ProviderRegistry([
                Descriptor("first", emptyOverflow, Capabilities()),
                Descriptor("ordinary", fallback, Capabilities()),
            ]));

        var ordinaryResult = await ordinaryFallback.GenerateAsync(new GenerationRequest(
            [Message.User("request")],
            new Route(["first:model", "ordinary:model"])));

        Assert.Equal("ordinary", ordinaryResult.Target!.ProviderId);
        Assert.Equal(1, emptyOverflow.GenerateCalls);
        Assert.Equal(1, fallback.GenerateCalls);

        var unrelated = new RecordingAdapter(token => ThrowAfterYield(
            token,
            new ProviderException("unrelated", "transport", false, "generate")));
        var unrelatedOrdinary = new RecordingAdapter(static token => Success(token));
        var shouldNotRun = new RecordingAdapter(static token => Success(token));
        await using var unrelatedFallback = new AsyncClient(
            [ProviderSettings.Of("first"), ProviderSettings.Of("ordinary"), ProviderSettings.Of("special")],
            new ProviderRegistry([
                Descriptor("first", unrelated, Capabilities()),
                Descriptor("ordinary", unrelatedOrdinary, Capabilities()),
                Descriptor("special", shouldNotRun, Capabilities()),
            ]));

        var unrelatedResult = await unrelatedFallback.GenerateAsync(new GenerationRequest(
            [Message.User("request")],
            new Route(["first:model", "ordinary:model"], contextWindowTargets: ["special:model"])));

        Assert.Equal("ordinary", unrelatedResult.Target!.ProviderId);
        Assert.Equal(1, unrelated.GenerateCalls);
        Assert.Equal(1, unrelatedOrdinary.GenerateCalls);
        Assert.Equal(0, shouldNotRun.GenerateCalls);

        var filteredOverflow = new RecordingAdapter(token => ThrowAfterYield(token, new ContextLengthException("overflow")));
        var filteredOrdinary = new RecordingAdapter(static token => Success(token));
        await using var filtered = new AsyncClient(
            [ProviderSettings.Of("first"), ProviderSettings.Of("ordinary")],
            new ProviderRegistry([
                Descriptor("first", filteredOverflow, Capabilities()),
                Descriptor("ordinary", filteredOrdinary, Capabilities()),
            ]));

        await Assert.ThrowsAsync<AllTargetsFailedException>(() => filtered.GenerateAsync(new GenerationRequest(
            [Message.User("request")],
            new Route(["first:model", "ordinary:model"], contextWindowTargets: ["first:model"]))));
        Assert.Equal(1, filteredOverflow.GenerateCalls);
        Assert.Equal(0, filteredOrdinary.GenerateCalls);
    }

    [Fact]
    public void Sync_client_uses_the_same_direct_spend_refusal_before_adapter_generate()
    {
        var adapter = new RecordingAdapter(static token => Success(token));
        var factoryCalls = 0;
        var descriptor = Descriptor(
            "sync",
            adapter,
            Capabilities(pricing: new Pricing(D("1000000"), EDecimal.Zero)),
            onFactory: () => factoryCalls++);
        using var client = new Client(
            [ProviderSettings.Of("sync")],
            new ProviderRegistry([descriptor]),
            estimator: new FixedEstimator(new TokenEstimate(1, 1)),
            spendPolicy: new SpendPolicy(maxRequestUsd: EDecimal.Zero));

        var error = Assert.Throws<SpendLimitException>(() => client.Generate("request", target: "sync:model"));

        EqualDecimal(EDecimal.Zero, error.LimitUsd);
        Assert.NotNull(error.EstimatedUsd);
        Assert.Equal(1, factoryCalls);
        Assert.Equal(0, adapter.GenerateCalls);
        Assert.Equal(0, client.Spend().Requests);
    }

    [Fact]
    public async Task Route_specialized_targets_are_snapshotted_and_bare_convenience_requests_do_not_inherit_them()
    {
        var specialized = new[] { "large:model" };
        var route = new Route(["small:model"], contextWindowTargets: specialized);
        specialized[0] = "mutated:model";
        Assert.Equal(["large:model"], route.ContextWindowTargets);

        var small = new RecordingAdapter(static token => Success(token));
        var descriptor = Descriptor("small", small, Capabilities(contextWindow: 3));
        await using var client = new AsyncClient(
            [ProviderSettings.Of("small")],
            new ProviderRegistry([descriptor]),
            route: route,
            estimator: new FixedEstimator(new TokenEstimate(4, 4)));

        var failure = await Assert.ThrowsAsync<AllTargetsFailedException>(() =>
            client.GenerateAsync("request", target: "small:model"));

        Assert.Contains(failure.Attempts, static attempt => attempt.Error is ContextLengthException);
        Assert.Equal(0, small.GenerateCalls);
    }

    [Fact]
    public async Task From_config_uses_its_cache_default_until_an_explicit_off_override_and_forwards_policy_inputs()
    {
        var adapter = new RecordingAdapter(static token => Success(token));
        var descriptor = Descriptor("configured", adapter, Capabilities(contextWindow: 1));
        var config = new AnyInferConfig([ProviderSettings.Of("configured")], cache: new CachePolicy());
        var configuredObserver = new Collector();
        await using var configured = AsyncClient.FromConfig(
            config,
            new ProviderRegistry([descriptor]),
            observers: [configuredObserver],
            estimator: new FixedEstimator(new TokenEstimate(4, 4)),
            spendPolicy: new SpendPolicy(onUnknown: "allow"),
            contextGate: false);

        await configured.GenerateAsync("request", target: "configured:model");

        Assert.Equal(1, adapter.GenerateCalls);
        Assert.Contains(
            configuredObserver.Events,
            static item => item is ParameterDropped { Parameter: "cache.mode" });

        var overrideAdapter = new RecordingAdapter(static token => Success(token));
        var overrideDescriptor = Descriptor("configured", overrideAdapter, Capabilities());
        var overrideObserver = new Collector();
        await using var overridden = AsyncClient.FromConfig(
            config,
            new ProviderRegistry([overrideDescriptor]),
            observers: [overrideObserver],
            cachePolicy: new CachePolicy(CacheMode.Off));

        await overridden.GenerateAsync("request", target: "configured:model");

        Assert.Equal(1, overrideAdapter.GenerateCalls);
        Assert.DoesNotContain(
            overrideObserver.Events,
            static item => item is ParameterDropped { Parameter: "cache.mode" });

        var refusingAdapter = new RecordingAdapter(static token => Success(token));
        var refusingDescriptor = Descriptor("configured", refusingAdapter, Capabilities());
        await using var refusing = AsyncClient.FromConfig(
            config,
            new ProviderRegistry([refusingDescriptor]),
            spendPolicy: new SpendPolicy(onUnknown: "refuse"));

        await Assert.ThrowsAsync<SpendLimitException>(() =>
            refusing.GenerateAsync("request", target: "configured:model"));
        Assert.Equal(0, refusingAdapter.GenerateCalls);
    }

    [Fact]
    public async Task Shared_total_reservation_refuses_a_second_dispatch_and_cancellation_releases_it_for_a_later_winner()
    {
        var adapter = new BlockingThenSuccessAdapter();
        using var cancellation = new CancellationTokenSource();
        var ledger = new SpendLedger();
        await using var client = CreateClient(
            "reserved",
            adapter,
            Capabilities(pricing: new Pricing(D("1000000"), EDecimal.Zero)),
            estimator: new FixedEstimator(new TokenEstimate(1, 1)),
            spendPolicy: new SpendPolicy(maxTotalUsd: D("5")),
            ledger: ledger);
        Task<Generation>? first = null;
        Task<OperationCanceledException>? cancellationAssertion = null;
        var firstObserved = false;
        Exception? primary = null;
        Exception? cleanup = null;
        try
        {
            first = client.GenerateAsync("first", target: "reserved:model", cancellationToken: cancellation.Token);
            await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(10));
            EqualDecimal(D("5"), ledger.Reserved());

            var refused = await Assert.ThrowsAsync<SpendLimitException>(() =>
                client.GenerateAsync("second", target: "reserved:model"));
            EqualDecimal(D("5"), refused.LimitUsd);
            Assert.Equal(1, adapter.GenerateCalls);

            cancellation.Cancel();
            var pendingCancellationAssertion = Assert.ThrowsAnyAsync<OperationCanceledException>(() => first!);
            cancellationAssertion = pendingCancellationAssertion;
            var cancelled = await pendingCancellationAssertion.WaitAsync(TimeSpan.FromSeconds(10));
            Assert.True(cancellation.IsCancellationRequested);
            Assert.True(cancelled.CancellationToken.IsCancellationRequested);
            firstObserved = true;
            EqualDecimal(EDecimal.Zero, ledger.Reserved());
            Assert.Equal(0, ledger.Totals().Requests);

            var winner = await client.GenerateAsync("third", target: "reserved:model");
            Assert.Equal("ok", winner.Text);
            Assert.Equal(2, adapter.GenerateCalls);
            Assert.Equal(1, ledger.Totals().Requests);
            EqualDecimal(D("1"), ledger.Totals().Cost);
        }
        catch (Exception exception)
        {
            primary = exception;
        }
        finally
        {
            cancellation.Cancel();
            adapter.Release.TrySetResult();
            if (!firstObserved)
            {
                cleanup = await ObserveAsync(first, cleanup);
            }

            cleanup = await ObserveAsync(cancellationAssertion, cleanup);
        }

        Rethrow(primary, cleanup);
    }

    [Fact]
    public async Task Retry_and_schema_repair_keep_one_request_reservation_and_charge_only_the_winning_completion()
    {
        var retryable = new ProviderException("retry", "transport", true, "generate");
        var retryAdapter = new ScriptedAdapter((call, token) => call == 1
            ? ThrowAfterYield(token, retryable)
            : Success(token));
        var retryLedger = new SpendLedger();
        var retryObserver = new Collector();
        await using var retryClient = CreateClient(
            "retry",
            retryAdapter,
            Capabilities(pricing: new Pricing(D("1000000"), EDecimal.Zero)),
            estimator: new FixedEstimator(new TokenEstimate(1, 1)),
            spendPolicy: new SpendPolicy(maxTotalUsd: D("5")),
            ledger: retryLedger,
            observer: retryObserver);

        var retried = await retryClient.GenerateAsync(new GenerationRequest(
            [Message.User("request")],
            new Route(["retry:model"], new Retry(MaxAttempts: 2, BackoffBaseS: 0, BackoffMaxS: 0))));

        Assert.Equal("ok", retried.Text);
        Assert.Equal(2, retryAdapter.GenerateCalls);
        Assert.Single(retryObserver.Events.OfType<RetryScheduled>());
        var retryCompleted = Assert.Single(retryObserver.Events.OfType<RequestCompleted>());
        EqualDecimal(D("1"), retried.Usage!.CostUsd);
        EqualDecimal(D("1"), retryCompleted.Usage.CostUsd);
        Assert.Equal("1.000000", retried.Manifest!.Usage.CostUsd);
        Assert.Equal(1, retryLedger.Totals().Requests);
        EqualDecimal(D("1"), retryLedger.Totals().Cost);
        EqualDecimal(EDecimal.Zero, retryLedger.Reserved());

        var repairEstimator = new FixedEstimator(new TokenEstimate(1, 1));
        var repairAdapter = new ScriptedAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("not-json"), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("{\"answer\":\"ok\"}"), new AdapterUsage(new Usage(InputTokens: 1, OutputTokens: 0)), new AdapterFinal("stop")));
        var repairLedger = new SpendLedger();
        await using var repairClient = CreateClient(
            "repair",
            repairAdapter,
            Capabilities(pricing: new Pricing(D("1000000"), EDecimal.Zero)),
            estimator: repairEstimator,
            spendPolicy: new SpendPolicy(maxTotalUsd: D("6")),
            ledger: repairLedger,
            contextGate: false);

        var repaired = await repairClient.GenerateAsync(
            "request",
            target: "repair:model",
            schema: AnswerSchema(),
            repair: new Repair(1));

        Assert.Equal(1, repaired.RepairAttempts);
        Assert.Equal(2, repairAdapter.GenerateCalls);
        Assert.Equal(2, repairEstimator.Calls);
        Assert.Equal(1, repairLedger.Totals().Requests);
        EqualDecimal(D("1"), repaired.Usage!.CostUsd);
        Assert.Equal("1.000000", repaired.Manifest!.Usage.CostUsd);
        EqualDecimal(D("1"), repairLedger.Totals().Cost);
        EqualDecimal(EDecimal.Zero, repairLedger.Reserved());
    }

    [Fact]
    public async Task Known_priced_fallback_replaces_its_reservation_for_the_same_request_id_and_charges_only_the_winner()
    {
        var source = new RecordingAdapter(token => ThrowAfterYield(
            token,
            new ProviderException("fallback", "transport", false, "generate")));
        var winner = new RecordingAdapter(static token => Success(token));
        var ledger = new SpendLedger();
        var observer = new Collector();
        var pricing = new Pricing(D("1000000"), EDecimal.Zero);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("source"), ProviderSettings.Of("winner")],
            new ProviderRegistry([
                Descriptor("source", source, Capabilities(pricing: pricing)),
                Descriptor("winner", winner, Capabilities(pricing: pricing)),
            ]),
            observers: [observer],
            estimator: new FixedEstimator(new TokenEstimate(1, 1)),
            spendPolicy: new SpendPolicy(maxTotalUsd: D("5")),
            ledger: ledger);

        var result = await client.GenerateAsync(new GenerationRequest(
            [Message.User("request")],
            new Route(["source:model", "winner:model"])));

        Assert.Equal("winner", result.Target!.ProviderId);
        Assert.Equal(1, source.GenerateCalls);
        Assert.Equal(1, winner.GenerateCalls);
        var starts = observer.Events.OfType<AttemptStarted>().ToArray();
        Assert.Equal(2, starts.Length);
        Assert.Equal(starts[0].RequestId, starts[1].RequestId);
        Assert.Equal(["source", "winner"], starts.Select(static item => item.Target.ProviderId));
        Assert.Single(observer.Events.OfType<RequestCompleted>());
        Assert.Equal(1, ledger.Totals().Requests);
        EqualDecimal(D("1"), result.Usage!.CostUsd);
        EqualDecimal(D("1"), ledger.Totals().Cost);
        EqualDecimal(EDecimal.Zero, ledger.Reserved());
    }

    [Fact]
    public async Task Known_context_refusal_to_unknown_allow_retains_its_reservation_until_terminal_cleanup()
    {
        var known = new RecordingAdapter(token => ThrowAfterYield(token, new ContextLengthException("overflow")));
        var unknown = new BlockingThenSuccessAdapter();
        var ledger = new SpendLedger();
        await using var client = new AsyncClient(
            [ProviderSettings.Of("known"), ProviderSettings.Of("unknown")],
            new ProviderRegistry([
                Descriptor(
                    "known",
                    known,
                    Capabilities(pricing: new Pricing(D("1000000"), EDecimal.Zero))),
                Descriptor("unknown", unknown, new ModelCapabilities()),
            ]),
            estimator: new FixedEstimator(new TokenEstimate(1, 1)),
            spendPolicy: new SpendPolicy(maxTotalUsd: D("5"), onUnknown: "allow"),
            ledger: ledger);
        var stream = client.StreamAsync(new GenerationRequest(
            [Message.User("request")],
            new Route(["known:model"], contextWindowTargets: ["unknown:model"])));
        Task<Generation>? pending = null;
        Task? disposal = null;
        Task<OperationCanceledException>? cancellationAssertion = null;
        var pendingObserved = false;
        Exception? primary = null;
        Exception? cleanup = null;
        try
        {
            pending = stream.CollectAsync();
            await unknown.Entered.Task.WaitAsync(TimeSpan.FromSeconds(10));

            Assert.Equal(1, known.GenerateCalls);
            Assert.Equal(1, unknown.GenerateCalls);
            EqualDecimal(D("5"), ledger.Reserved());

            disposal = stream.DisposeAsync().AsTask();
            await disposal.WaitAsync(TimeSpan.FromSeconds(10));
            var pendingCancellationAssertion = Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending!);
            cancellationAssertion = pendingCancellationAssertion;
            await pendingCancellationAssertion.WaitAsync(TimeSpan.FromSeconds(10));
            pendingObserved = true;
            EqualDecimal(EDecimal.Zero, ledger.Reserved());
            Assert.Equal(0, ledger.Totals().Requests);

            var later = await client.GenerateAsync("later", target: "unknown:model");
            Assert.Equal("ok", later.Text);
            EqualDecimal(EDecimal.Zero, ledger.Reserved());
        }
        catch (Exception exception)
        {
            primary = exception;
        }
        finally
        {
            unknown.Release.TrySetResult();
            if (!pendingObserved)
            {
                cleanup = await ObserveAsync(pending, cleanup);
            }

            cleanup = await ObserveAsync(disposal, cleanup);
            cleanup = await ObserveAsync(cancellationAssertion, cleanup);
            cleanup = await ObserveAsync(stream.DisposeAsync().AsTask(), cleanup);
        }

        Rethrow(primary, cleanup);
    }

    [Fact]
    public async Task Early_stream_disposal_releases_the_actual_policy_reservation_before_a_later_admission()
    {
        var adapter = new BlockingThenSuccessAdapter();
        var ledger = new SpendLedger();
        await using var client = CreateClient(
            "early",
            adapter,
            Capabilities(pricing: new Pricing(D("1000000"), EDecimal.Zero)),
            estimator: new FixedEstimator(new TokenEstimate(1, 1)),
            spendPolicy: new SpendPolicy(maxTotalUsd: D("5")),
            ledger: ledger);
        var unadvanced = client.StreamAsync("unused", target: "early:model");
        await unadvanced.DisposeAsync();
        Assert.Equal(0, adapter.GenerateCalls);
        EqualDecimal(EDecimal.Zero, ledger.Reserved());

        var stream = client.StreamAsync("request", target: "early:model");
        Task<Generation>? pending = null;
        Task? disposal = null;
        Task<OperationCanceledException>? cancellationAssertion = null;
        var pendingObserved = false;
        Exception? primary = null;
        Exception? cleanup = null;
        try
        {
            pending = stream.CollectAsync();
            await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(10));
            EqualDecimal(D("5"), ledger.Reserved());

            disposal = stream.DisposeAsync().AsTask();
            await disposal.WaitAsync(TimeSpan.FromSeconds(10));
            var pendingCancellationAssertion = Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending!);
            cancellationAssertion = pendingCancellationAssertion;
            await pendingCancellationAssertion.WaitAsync(TimeSpan.FromSeconds(10));
            pendingObserved = true;
            EqualDecimal(EDecimal.Zero, ledger.Reserved());
            Assert.Equal(0, ledger.Totals().Requests);

            var later = await client.GenerateAsync("later", target: "early:model");
            Assert.Equal("ok", later.Text);
            Assert.Equal(1, ledger.Totals().Requests);
        }
        catch (Exception exception)
        {
            primary = exception;
        }
        finally
        {
            adapter.Release.TrySetResult();
            if (!pendingObserved)
            {
                cleanup = await ObserveAsync(pending, cleanup);
            }

            cleanup = await ObserveAsync(disposal, cleanup);
            cleanup = await ObserveAsync(cancellationAssertion, cleanup);
            cleanup = await ObserveAsync(stream.DisposeAsync().AsTask(), cleanup);
        }

        Rethrow(primary, cleanup);
    }

    [Fact]
    public async Task Automatic_spend_uses_identity_calibration_while_budget_uses_the_descriptor_calibration_and_estimator_faults_escape()
    {
        var adapter = new RecordingAdapter(static token => Success(token));
        var estimator = new FixedEstimator(new TokenEstimate(2, 2));
        var descriptor = Descriptor(
            "calibrated",
            adapter,
            Capabilities(pricing: new Pricing(D("1000000"), EDecimal.Zero)),
            tokenCalibration: new TokenCalibration(2, 0));
        await using var client = new AsyncClient(
            [ProviderSettings.Of("calibrated")],
            new ProviderRegistry([descriptor]),
            estimator: estimator,
            spendPolicy: new SpendPolicy(maxRequestUsd: D("6")));

        var budget = client.Budget("request", "calibrated:model", outputReserveTokens: 0);
        Assert.Equal(12, budget.Estimate.Tokens);

        var generation = await client.GenerateAsync("request", target: "calibrated:model");
        Assert.Equal("ok", generation.Text);
        Assert.Equal(1, adapter.GenerateCalls);

        var sentinel = new InvalidOperationException("estimator");
        var failingAdapter = new RecordingAdapter(static token => Success(token));
        await using var failingClient = CreateClient(
            "failing",
            failingAdapter,
            Capabilities(pricing: new Pricing(D("1000000"), EDecimal.Zero)),
            estimator: new ThrowingEstimator(sentinel),
            spendPolicy: new SpendPolicy(maxTotalUsd: D("1")));

        var failure = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            failingClient.GenerateAsync("request", target: "failing:model"));
        Assert.Same(sentinel, failure);
        Assert.Equal(0, failingAdapter.GenerateCalls);
        Assert.Equal(0, failingClient.Spend().Requests);
    }

    [Fact]
    public async Task Context_gate_uses_only_trusted_whole_window_floor_and_can_be_explicitly_disabled()
    {
        var exactAdapter = new RecordingAdapter(static token => Success(token));
        await using var exact = CreateClient(
            "exact",
            exactAdapter,
            Capabilities(contextWindow: 4),
            estimator: new FixedEstimator(new TokenEstimate(4, 4)));
        await exact.GenerateAsync("request", target: "exact:model");
        Assert.Equal(1, exactAdapter.GenerateCalls);

        var defaultAdapter = new RecordingAdapter(static token => Success(token));
        await using var defaultWindow = CreateClient(
            "default",
            defaultAdapter,
            new ModelCapabilities(new Sourced<int>(3, Provenance.Default)),
            estimator: new FixedEstimator(new TokenEstimate(4, 4)));
        await defaultWindow.GenerateAsync("request", target: "default:model");
        Assert.Equal(1, defaultAdapter.GenerateCalls);

        var unsupportedAdapter = new RecordingAdapter(static token => Success(token));
        await using var unsupported = CreateClient(
            "unsupported",
            unsupportedAdapter,
            Capabilities(contextWindow: 3),
            estimator: new FixedEstimator(new TokenEstimate(4, 4)));
        var admission = await Assert.ThrowsAsync<ProviderException>(() => unsupported.GenerateAsync(new GenerationRequest(
            [new Message("user", [new UnsupportedContentPart("image", new JsonObject([]))])],
            new Route(["unsupported:model"]))));
        Assert.Equal("unsupported_input", admission.Category);
        Assert.Equal("generate", admission.Phase);
        Assert.Equal(0, unsupportedAdapter.GenerateCalls);

        var disabledAdapter = new RecordingAdapter(static token => Success(token));
        var disabledDescriptor = Descriptor("disabled", disabledAdapter, Capabilities(contextWindow: 3));
        await using var disabled = new AsyncClient(
            [ProviderSettings.Of("disabled")],
            new ProviderRegistry([disabledDescriptor]),
            estimator: new FixedEstimator(new TokenEstimate(4, 4)),
            contextGate: false);
        await disabled.GenerateAsync("request", target: "disabled:model");
        Assert.Equal(1, disabledAdapter.GenerateCalls);
    }

    private static AsyncClient CreateClient(
        string id,
        IProviderAdapter adapter,
        ModelCapabilities capabilities,
        ITokenEstimator? estimator = null,
        SpendPolicy? spendPolicy = null,
        Action? onFactory = null,
        SpendLedger? ledger = null,
        IObserver? observer = null,
        bool contextGate = true)
    {
        var descriptor = Descriptor(id, adapter, capabilities, onFactory: onFactory);
        return new AsyncClient(
            [ProviderSettings.Of(id)],
            new ProviderRegistry([descriptor]),
            observers: observer is null ? null : [observer],
            estimator: estimator,
            ledger: ledger,
            spendPolicy: spendPolicy,
            contextGate: contextGate);
    }

    private static ProviderDescriptor Descriptor(
        string id,
        IProviderAdapter adapter,
        ModelCapabilities capabilities,
        Action? onFactory = null,
        TokenCalibration? tokenCalibration = null) =>
        new(
            id,
            id,
            (_, _) =>
            {
                onFactory?.Invoke();
                return ValueTask.FromResult<IProviderAdapter>(adapter);
            },
            staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal)
            {
                ["model"] = capabilities,
            },
            tokenCalibration: tokenCalibration);

    private static ModelCapabilities Capabilities(
        int? contextWindow = null,
        Pricing? pricing = null) =>
        new(
            contextWindow is null ? null : new Sourced<int>(contextWindow.Value, Provenance.Catalog),
            pricing: pricing is null ? null : new Sourced<Pricing>(pricing, Provenance.Catalog));

    private static EDecimal D(string value) => EDecimal.FromString(value);

    private static SchemaSpec AnswerSchema() => new(new JsonObject([
        new JsonProperty("type", new JsonString("object")),
        new JsonProperty("required", new JsonArray([new JsonString("answer")])),
        new JsonProperty("properties", new JsonObject([
            new JsonProperty("answer", new JsonObject([
                new JsonProperty("type", new JsonString("string")),
            ])),
        ])),
    ]));

    private static void EqualDecimal(EDecimal expected, EDecimal? actual)
    {
        Assert.NotNull(actual);
        Assert.Equal(0, expected.CompareTo(actual!));
    }

    private static async IAsyncEnumerable<AdapterEvent> Success([EnumeratorCancellation] CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        yield return new AdapterTextDelta("ok");
        yield return new AdapterUsage(new Usage(InputTokens: 1, OutputTokens: 0));
        yield return new AdapterFinal("stop");
        await Task.Yield();
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

    private static async IAsyncEnumerable<AdapterEvent> ThrowAfterYield(
        [EnumeratorCancellation] CancellationToken token,
        Exception error)
    {
        token.ThrowIfCancellationRequested();
        await Task.Yield();
        System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error).Throw();
        yield break;
    }

    private sealed class RecordingAdapter(Func<CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        public int GenerateCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            return script(cancellationToken);
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class ScriptedAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        public int GenerateCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            script(++GenerateCalls, cancellationToken);

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class BlockingThenSuccessAdapter : IProviderAdapter
    {
        public TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public int GenerateCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            return GenerateCalls == 1 ? Block(cancellationToken) : Success(cancellationToken);
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;

        private async IAsyncEnumerable<AdapterEvent> Block([EnumeratorCancellation] CancellationToken token)
        {
            Entered.TrySetResult();
            await Release.Task.WaitAsync(token);
            yield return new AdapterTextDelta("released");
            yield return new AdapterFinal("stop");
        }
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

    private sealed class ThrowingEstimator(Exception failure) : ITokenEstimator
    {
        public TokenEstimate Estimate(string text) => throw failure;
    }

    private sealed class Collector : IObserver
    {
        public List<TelemetryEvent> Events { get; } = [];

        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }

    private static async Task<Exception?> ObserveAsync(Task? task, Exception? previous = null)
    {
        if (task is null)
        {
            return previous;
        }

        try
        {
            await task.WaitAsync(TimeSpan.FromSeconds(10));
        }
        catch (Exception exception)
        {
            return previous ?? exception;
        }

        return previous;
    }

    private static void Rethrow(Exception? primary, Exception? cleanup)
    {
        if (primary is not null)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(primary).Throw();
        }

        if (cleanup is not null)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(cleanup).Throw();
        }
    }
}
