using System.Runtime.CompilerServices;
using System.Net;
using System.Net.Http;
using AnyInfer;
using AnyInfer.Capabilities;
using ModelCatalog = AnyInfer.Catalog.Catalog;
using AnyInfer.Core;
using AnyInfer.Events;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Routing;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Independent controls for PublicSdk entry clocks and own-transport pacing boundaries.</summary>
public sealed class EntryPacingTests
{
    [Fact]
    public async Task Virtual_entry_timer_starts_at_boundary_and_times_out_the_blocked_adapter_entry()
    {
        var clock = new VirtualTimeProvider();
        var capture = new OperationCapture();
        var operation = new OperationContext(capture, clock);
        var adapter = new ScriptedAdapter(static (_, token) => BlockUntilCancelled(token));
        var stream = AdapterInvocationBoundary.InvokeAsync(adapter, Request(timeoutS: 4), operation, EntryRole.Original);

        var pending = CollectAsync(stream);
        await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal([4d], clock.Armed);
        Assert.False(pending.IsCompleted);

        clock.Advance(TimeSpan.FromSeconds(4));
        var failure = await Assert.ThrowsAsync<ProviderException>(() => pending);

        Assert.Equal("transport", failure.Category);
        var entry = Assert.Single(capture.Entries);
        Assert.True(entry.Timeout.IsExpired);
        Assert.True(entry.Timeout.IsDisposed);
        Assert.Contains(capture.Lifecycle, item => item.Name == "entered");
    }

    [Fact]
    public async Task Entry_clock_is_per_operation_and_an_ordinary_source_failure_is_retained()
    {
        var firstClock = new VirtualTimeProvider();
        var secondClock = new VirtualTimeProvider();
        var first = new OperationContext(entryTimeProvider: firstClock);
        var second = new OperationContext(entryTimeProvider: secondClock);
        var source = new InvalidOperationException("source failure");

        var failure = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(
                new ScriptedAdapter((_, _) => Throw(source)), Request(timeoutS: 9), first, EntryRole.Original)));

        Assert.Same(source, failure);
        Assert.Equal([9d], firstClock.Armed);
        Assert.Empty(secondClock.Armed);
        Assert.Same(source, first.LastEntry!.TerminalFailure);
    }

    [Fact]
    public async Task Each_boundary_entry_gets_a_fresh_virtual_timer_and_disposes_it_after_clean_completion()
    {
        var clock = new VirtualTimeProvider();
        var capture = new OperationCapture();
        var operation = new OperationContext(capture, clock);

        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(
            new ScriptedAdapter(static (_, token) => Finish(token)), Request(timeoutS: 2), operation, EntryRole.Original));
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(
            new ScriptedAdapter(static (_, token) => Finish(token)), Request(timeoutS: 7), operation, EntryRole.Original));

        Assert.Equal([2d, 7d], clock.Armed);
        Assert.Equal([1, 2], capture.Entries.Select(static entry => entry.Ordinal));
        Assert.All(capture.Entries, static entry => Assert.True(entry.Timeout.IsDisposed));
    }

    [Fact]
    public async Task Owned_wait_does_not_rewrite_a_time_provider_source_exception_when_effective_token_is_live()
    {
        using var parent = new CancellationTokenSource();
        parent.Cancel();
        using var effective = new CancellationTokenSource();
        var source = new OperationCanceledException("timer source");
        var limiter = new RateLimiter(new RateLimits(minIntervalS: 1, respectHeaders: false), timeProvider: new ThrowingDelayTimeProvider(source));

        await using (await limiter.AcquireAsync()) { }
        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            limiter.AcquireAsync(effective.Token, () => parent.Token).AsTask());

        Assert.Same(source, failure);
        Assert.False(effective.IsCancellationRequested);
    }

    [Fact]
    public async Task Owned_semaphore_wait_uses_marker_only_close_parent_when_effective_token_is_cancelled()
    {
        using var rawClose = new CancellationTokenSource();
        using var effective = new CancellationTokenSource();
        var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false));
        await using var first = await limiter.AcquireAsync();

        var queued = limiter.AcquireAsync(effective.Token, () => rawClose.Token).AsTask();
        Assert.False(queued.IsCompleted);
        Assert.False(rawClose.IsCancellationRequested);
        effective.Cancel();

        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => queued);
        Assert.Equal(rawClose.Token, failure.CancellationToken);
        Assert.False(rawClose.IsCancellationRequested);
        Assert.True(effective.IsCancellationRequested);
    }

    [Fact]
    public async Task Injected_active_and_inactive_pacing_selection_is_per_instance_and_opaque_uses_only_an_outer_slot()
    {
        var active = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false));
        var inactive = new RateLimiter(new RateLimits(respectHeaders: false));
        var alpha = new ScriptedAdapter(static (_, token) => Finish(token));
        var beta = new ScriptedAdapter(static (_, token) => Finish(token));
        await using var pool = new ProviderPool(
            [new ProviderRegistration("alpha", alpha), new ProviderRegistration("beta", beta)],
            new Dictionary<string, RateLimiter>(StringComparer.Ordinal)
            {
                ["alpha"] = active,
                ["beta"] = inactive,
            });

        var selected = pool.GetPacing(pool.Materialize(pool.ResolveMetadata("alpha:model")));
        var suppressed = pool.GetPacing(pool.Materialize(pool.ResolveMetadata("beta:model")));

        Assert.Same(active, selected.Limiter);
        Assert.True(selected.UsesOuterSlot);
        Assert.Null(suppressed.Limiter);
        Assert.False(suppressed.UsesOuterSlot);
    }

    [Fact]
    public async Task Own_transport_queue_is_paid_before_the_virtual_entry_timer_is_armed_and_records_winning_queue_time()
    {
        var clock = new VirtualTimeProvider();
        var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false), timeProvider: clock);
        var held = await limiter.AcquireAsync();
        var adapter = new ScriptedAdapter(static (_, token) => Finish(token));
        var descriptor = new ProviderDescriptor("opaque", "Opaque", (_, _) => ValueTask.FromResult<IProviderAdapter>(adapter), governsOwnTransport: true);
        var descriptors = new ProviderRegistry([descriptor]);
        await using var owner = AsyncClient.FromAdapters([]);
        await using var pool = new ProviderPool(
            [ProviderSettings.Of("opaque")], descriptors, AnyInfer.Credentials.ResolverChain.CreateDefault(),
            new Dictionary<string, RateLimiter>(StringComparer.Ordinal) { ["opaque"] = limiter }, pacingTimeProvider: clock);
        var request = new GenerationRequest([Message.User("entry")], new Route(["opaque:model"]), stream: true, timeoutS: 4);
        var normalized = RequestNormalizer.Normalize(request, true, SchemaExecutionProfile.ModernSdk);
        var telemetry = new RequestTelemetry(normalized, request.Route, new EventDispatcher(), null, Guid.NewGuid().ToString("D"));
        var resolver = new TargetMetadataResolver(ModelCatalog.LoadDefault(), descriptors, () => pool.Bindings, pool, new CapabilityStore());
        var policy = new GenerationPolicyContext(request, null, null, new CachePrefixState(), clock);
        AsyncStream? stream = null;
        stream = new AsyncStream(owner, null, token => GenerationCore.ExecuteAsync(
            normalized, request.Route, pool, resolver, TargetResolutionProfile.PublicSdk,
            new RouteState(new SystemOperationClock()), new SystemOperationClock(), null, stream!, policy, token), default, telemetry: telemetry);

        var pending = stream.CollectAsync();
        try
        {
            Assert.False(pending.IsCompleted);
            Assert.Empty(adapter.Requests);
            clock.Advance(TimeSpan.FromSeconds(1));
            await held.DisposeAsync();
            await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));

            Assert.Equal([4d], clock.Armed);
            var result = await pending;
            Assert.NotNull(result.Timing);
            Assert.True(result.Timing!.Phases.TryGetValue("queued_ms", out var queued));
            Assert.Equal(1000d, queued);
        }
        finally
        {
            await held.DisposeAsync();
            await stream.DisposeAsync();
        }
    }

    [Fact]
    public async Task Normal_transport_arms_the_actual_entry_timer_while_its_governed_handler_is_queued()
    {
        var clock = new VirtualTimeProvider();
        var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false), timeProvider: clock);
        var rawHandler = new CountingHandler();
        var held = await limiter.AcquireAsync();
        var descriptors = new ProviderRegistry([
            new ProviderDescriptor(
                "normal-http",
                "Normal HTTP",
                (config, _) => ValueTask.FromResult<IProviderAdapter>(new HttpSendingAdapter(config.Transport!)))
        ]);
        await using var owner = AsyncClient.FromAdapters([]);
        await using var pool = new ProviderPool(
            [ProviderSettings.Of("normal-http", transport: rawHandler)],
            descriptors,
            AnyInfer.Credentials.ResolverChain.CreateDefault(),
            new Dictionary<string, RateLimiter>(StringComparer.Ordinal) { ["normal-http"] = limiter },
            pacingTimeProvider: clock);
        var request = new GenerationRequest([Message.User("entry")], new Route(["normal-http:model"], new Retry(1, 0, 0)), stream: true, timeoutS: 4);
        var normalized = RequestNormalizer.Normalize(request, true, SchemaExecutionProfile.ModernSdk);
        var telemetry = new RequestTelemetry(normalized, request.Route, new EventDispatcher(), null, Guid.NewGuid().ToString("D"));
        var resolver = new TargetMetadataResolver(ModelCatalog.LoadDefault(), descriptors, () => pool.Bindings, pool, new CapabilityStore());
        AsyncStream? stream = null;
        stream = new AsyncStream(owner, null, token => GenerationCore.ExecuteAsync(
            normalized, request.Route, pool, resolver, TargetResolutionProfile.PublicSdk,
            new RouteState(new SystemOperationClock()), new SystemOperationClock(), null, stream!,
            new GenerationPolicyContext(request, null, null, new CachePrefixState(), clock), token), default, telemetry: telemetry);

        var pending = stream.CollectAsync();
        try
        {
            await clock.WaitForArmedCountAsync(1).WaitAsync(TimeSpan.FromSeconds(5));
            Assert.Equal([4d], clock.Armed);
            Assert.Equal(0, rawHandler.SendCalls);

            clock.Advance(TimeSpan.FromSeconds(4));
            var failure = await Assert.ThrowsAsync<AllTargetsFailedException>(() => pending);
            var timeout = Assert.IsType<ProviderException>(Assert.Single(failure.Attempts).Error);
            Assert.Equal("transport", timeout.Category);
            Assert.True(timeout.Retryable);
            Assert.Equal(0, rawHandler.SendCalls);
        }
        finally
        {
            await held.DisposeAsync();
            await stream.DisposeAsync();
        }
    }

    [Fact]
    public async Task Normal_transport_selection_does_not_take_a_second_outer_slot_before_the_entry_timer()
    {
        var clock = new VirtualTimeProvider();
        var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false), timeProvider: clock);
        RateLimitLease? held = await limiter.AcquireAsync();
        var adapter = new ScriptedAdapter(static (_, token) => Finish(token));
        var descriptor = new ProviderDescriptor("normal", "Normal", (_, _) => ValueTask.FromResult<IProviderAdapter>(adapter));
        var descriptors = new ProviderRegistry([descriptor]);
        await using var owner = AsyncClient.FromAdapters([]);
        await using var pool = new ProviderPool(
            [ProviderSettings.Of("normal")], descriptors, AnyInfer.Credentials.ResolverChain.CreateDefault(),
            new Dictionary<string, RateLimiter>(StringComparer.Ordinal) { ["normal"] = limiter }, pacingTimeProvider: clock);
        var request = new GenerationRequest([Message.User("entry")], new Route(["normal:model"]), stream: true, timeoutS: 6);
        var normalized = RequestNormalizer.Normalize(request, true, SchemaExecutionProfile.ModernSdk);
        var telemetry = new RequestTelemetry(normalized, request.Route, new EventDispatcher(), null, Guid.NewGuid().ToString("D"));
        var resolver = new TargetMetadataResolver(ModelCatalog.LoadDefault(), descriptors, () => pool.Bindings, pool, new CapabilityStore());
        var context = new GenerationPolicyContext(request, null, null, new CachePrefixState(), clock);
        AsyncStream? stream = null;
        stream = new AsyncStream(owner, null, token => GenerationCore.ExecuteAsync(
            normalized, request.Route, pool, resolver, TargetResolutionProfile.PublicSdk,
            new RouteState(new SystemOperationClock()), new SystemOperationClock(), null, stream!, context, token), default, telemetry: telemetry);

        Task<Generation>? pending = null;
        Exception? primaryFailure = null;
        try
        {
            pending = stream.CollectAsync();
            var result = await pending.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.Equal("stop", result.FinishReason);
            Assert.Equal([6d], clock.Armed);
            Assert.Empty(result.Timing!.Phases);
        }
        catch (Exception exception)
        {
            primaryFailure = exception;
            throw;
        }
        finally
        {
            Exception? cleanupFailure = null;
            try
            {
                if (held is not null)
                {
                    await held.DisposeAsync();
                    held = null;
                }
            }
            catch (Exception exception)
            {
                cleanupFailure ??= exception;
            }

            try
            {
                if (pending is not null)
                {
                    await pending.WaitAsync(TimeSpan.FromSeconds(5));
                }
            }
            catch (Exception exception)
            {
                cleanupFailure ??= exception;
            }

            try
            {
                await stream.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5));
            }
            catch (Exception exception)
            {
                cleanupFailure ??= exception;
            }

            if (primaryFailure is null && cleanupFailure is not null)
            {
                System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(cleanupFailure).Throw();
            }
        }
    }

    [Fact]
    public async Task Retried_entry_gets_a_fresh_timer_and_only_its_distinct_queue_wait_wins()
    {
        var clock = new VirtualTimeProvider();
        var limiter = new RateLimiter(new RateLimits(minIntervalS: 1, respectHeaders: false), timeProvider: clock);
        await using var bootstrap = await limiter.AcquireAsync();
        await bootstrap.DisposeAsync();
        clock.Advance(TimeSpan.FromSeconds(.5));
        var retryClock = new GateOperationClock();
        var calls = 0;
        var adapter = new ScriptedAdapter((_, token) => Interlocked.Increment(ref calls) == 1
            ? Throw(new ProviderException("retry", "transport", true, "generate"))
            : Finish(token));
        var descriptor = new ProviderDescriptor("retry", "Retry", (_, _) => ValueTask.FromResult<IProviderAdapter>(adapter), governsOwnTransport: true);
        var descriptors = new ProviderRegistry([descriptor]);
        await using var owner = AsyncClient.FromAdapters([]);
        await using var pool = new ProviderPool([ProviderSettings.Of("retry")], descriptors,
            AnyInfer.Credentials.ResolverChain.CreateDefault(),
            new Dictionary<string, RateLimiter>(StringComparer.Ordinal) { ["retry"] = limiter }, pacingTimeProvider: clock);
        var request = new GenerationRequest([Message.User("retry")], new Route(["retry:model"], new Retry(2, 1, 1)), stream: true, timeoutS: 10);
        var normalized = RequestNormalizer.Normalize(request, true, SchemaExecutionProfile.ModernSdk);
        var telemetry = new RequestTelemetry(normalized, request.Route, new EventDispatcher(), null, Guid.NewGuid().ToString("D"));
        var resolver = new TargetMetadataResolver(ModelCatalog.LoadDefault(), descriptors, () => pool.Bindings, pool, new CapabilityStore());
        AsyncStream? stream = null;
        stream = new AsyncStream(owner, null, token => GenerationCore.ExecuteAsync(normalized, request.Route, pool, resolver,
            TargetResolutionProfile.PublicSdk, new RouteState(retryClock), retryClock, null, stream!,
            new GenerationPolicyContext(request, null, null, new CachePrefixState(), clock), token), default, telemetry: telemetry);

        var pending = stream.CollectAsync();
        try
        {
            await clock.WaitForArmedCountAsync(1).WaitAsync(TimeSpan.FromSeconds(5));
            clock.Advance(TimeSpan.FromSeconds(.5));
            await retryClock.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.Equal([.5d, 10d], clock.Armed);
            retryClock.Release.TrySetResult();
            await clock.WaitForArmedCountAsync(3).WaitAsync(TimeSpan.FromSeconds(5));
            clock.Advance(TimeSpan.FromSeconds(1));

            var result = await pending;
            Assert.Equal(2, calls);
            Assert.Equal([.5d, 10d, 1d, 10d], clock.Armed);
            Assert.True(result.Timing!.Phases.TryGetValue("queued_ms", out var queued));
            Assert.Equal(1000d, queued);
        }
        finally
        {
            retryClock.Release.TrySetResult();
            await stream.DisposeAsync();
        }
    }

    [Fact]
    public async Task Schema_correction_gets_a_fresh_timer_and_only_its_distinct_queue_wait_wins()
    {
        var clock = new VirtualTimeProvider();
        var limiter = new RateLimiter(new RateLimits(minIntervalS: 1, respectHeaders: false), timeProvider: clock);
        await using var bootstrap = await limiter.AcquireAsync();
        await bootstrap.DisposeAsync();
        clock.Advance(TimeSpan.FromSeconds(.5));
        var calls = 0;
        var adapter = new ScriptedAdapter((_, token) => Interlocked.Increment(ref calls) == 1
            ? Events(token, new AdapterTextDelta("\"wrong\""), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("\"correct\""), new AdapterFinal("stop")));
        var descriptor = new ProviderDescriptor("repair", "Repair", (_, _) => ValueTask.FromResult<IProviderAdapter>(adapter), governsOwnTransport: true);
        var descriptors = new ProviderRegistry([descriptor]);
        await using var owner = AsyncClient.FromAdapters([]);
        await using var pool = new ProviderPool([ProviderSettings.Of("repair")], descriptors,
            AnyInfer.Credentials.ResolverChain.CreateDefault(),
            new Dictionary<string, RateLimiter>(StringComparer.Ordinal) { ["repair"] = limiter }, pacingTimeProvider: clock);
        var request = new GenerationRequest([Message.User("repair")], new Route(["repair:model"]),
            schema: new SchemaSpec(JsonReader.Read("{\"const\":\"correct\"}")), repair: new Repair(1), stream: true, timeoutS: 10);
        var normalized = RequestNormalizer.Normalize(request, true, SchemaExecutionProfile.ModernSdk);
        var telemetry = new RequestTelemetry(normalized, request.Route, new EventDispatcher(), null, Guid.NewGuid().ToString("D"));
        var resolver = new TargetMetadataResolver(ModelCatalog.LoadDefault(), descriptors, () => pool.Bindings, pool, new CapabilityStore());
        AsyncStream? stream = null;
        stream = new AsyncStream(owner, null, token => GenerationCore.ExecuteAsync(normalized, request.Route, pool, resolver,
            TargetResolutionProfile.PublicSdk, new RouteState(new SystemOperationClock()), new SystemOperationClock(), null, stream!,
            new GenerationPolicyContext(request, null, null, new CachePrefixState(), clock), token), default, telemetry: telemetry);

        var pending = stream.CollectAsync();
        try
        {
            await clock.WaitForArmedCountAsync(1).WaitAsync(TimeSpan.FromSeconds(5));
            clock.Advance(TimeSpan.FromSeconds(.5));
            await clock.WaitForArmedCountAsync(3).WaitAsync(TimeSpan.FromSeconds(5));
            clock.Advance(TimeSpan.FromSeconds(1));

            var result = await pending;
            Assert.Equal(2, calls);
            Assert.Equal([.5d, 10d, 1d, 10d], clock.Armed);
            Assert.Equal(1, result.RepairAttempts);
            Assert.Equal("correct", Assert.IsType<JsonString>(result.Structured).Value);
            Assert.True(result.Timing!.Phases.TryGetValue("queued_ms", out var queued));
            Assert.Equal(1000d, queued);
        }
        finally
        {
            await stream.DisposeAsync();
        }
    }

    [Fact]
    public async Task Consumer_callbacks_at_attempt_start_first_adapter_event_and_finalization_do_not_inherit_attempt_pacing()
    {
        var adapter = new ScriptedAdapter(static (_, token) => Events(token,
            new AdapterTextDelta("first"), new AdapterFinal("stop")));
        var generationLimiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false));
        var descriptor = new ProviderDescriptor("reentry", "Reentry", (_, _) => ValueTask.FromResult<IProviderAdapter>(adapter), governsOwnTransport: true);
        var descriptors = new ProviderRegistry([descriptor]);
        await using var owner = AsyncClient.FromAdapters([]);
        await using var pool = new ProviderPool([ProviderSettings.Of("reentry")], descriptors,
            AnyInfer.Credentials.ResolverChain.CreateDefault(),
            new Dictionary<string, RateLimiter>(StringComparer.Ordinal) { ["reentry"] = generationLimiter });
        var request = new GenerationRequest([Message.User("reentry")], new Route(["reentry:model"]), stream: true, timeoutS: 10);
        var normalized = RequestNormalizer.Normalize(request, true, SchemaExecutionProfile.ModernSdk);
        var telemetry = new RequestTelemetry(normalized, request.Route, new EventDispatcher(), null, Guid.NewGuid().ToString("D"));
        var resolver = new TargetMetadataResolver(ModelCatalog.LoadDefault(), descriptors, () => pool.Bindings, pool, new CapabilityStore());
        AsyncStream? stream = null;
        stream = new AsyncStream(owner, null, token => GenerationCore.ExecuteAsync(normalized, request.Route, pool, resolver,
            TargetResolutionProfile.PublicSdk, new RouteState(new SystemOperationClock()), new SystemOperationClock(), null, stream!,
            new GenerationPolicyContext(request, null, null, new CachePrefixState()), token), default, telemetry: telemetry);

        try
        {
            await using var iterator = stream.GetAsyncEnumerator();
            Assert.True(await iterator.MoveNextAsync());
            Assert.IsType<TimingMark>(iterator.Current);
            await AssertConsumerPacingIsDetachedAsync();

            Assert.True(await iterator.MoveNextAsync());
            Assert.IsType<TimingMark>(iterator.Current);
            await AssertConsumerPacingIsDetachedAsync();

            while (await iterator.MoveNextAsync()) { }
            await AssertConsumerPacingIsDetachedAsync();
        }
        finally
        {
            await stream.DisposeAsync();
        }
    }

    [Theory]
    [InlineData("caller")]
    [InlineData("iterator")]
    [InlineData("close")]
    public async Task Public_outer_queue_refuses_cancelled_entry_and_releases_its_slot_for_a_fresh_request(string cancellationKind)
    {
        using var caller = new CancellationTokenSource();
        using var iteratorToken = new CancellationTokenSource();
        var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false));
        RateLimitLease? held = await limiter.AcquireAsync();
        var adapter = new ScriptedAdapter(static (_, token) => Finish(token));
        var attempts = new AttemptStartedObserver();
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("queue", adapter)],
            observers: [attempts],
            limiters: new Dictionary<string, RateLimiter>(StringComparer.Ordinal) { ["queue"] = limiter });
        var request = new GenerationRequest([Message.User("queue")], new Route(["queue:model"]), stream: true);
        AsyncStream? stream = null;
        IAsyncEnumerator<StreamEvent>? iterator = null;
        Task? pending = null;

        try
        {
            stream = client.StreamAsync(request, caller.Token);
            switch (cancellationKind)
            {
                case "caller":
                    pending = stream.CollectAsync();
                    break;
                case "iterator":
                    iterator = stream.GetAsyncEnumerator(iteratorToken.Token);
                    pending = iterator.MoveNextAsync().AsTask();
                    break;
                case "close":
                    pending = stream.CollectAsync();
                    break;
                default:
                    throw new ArgumentOutOfRangeException(nameof(cancellationKind));
            }

            var operation = pending ?? throw new InvalidOperationException("The queued operation did not start.");
            await attempts.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.False(operation.IsCompleted);
            Assert.Empty(adapter.Requests);

            if (cancellationKind == "caller")
            {
                caller.Cancel();
                var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => operation);
                Assert.Equal(caller.Token, cancelled.CancellationToken);
            }
            else if (cancellationKind == "iterator")
            {
                iteratorToken.Cancel();
                var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => operation);
                Assert.Equal(iteratorToken.Token, cancelled.CancellationToken);
            }
            else
            {
                await stream.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5));
                await Assert.ThrowsAnyAsync<OperationCanceledException>(() => operation);
            }

            Assert.Empty(adapter.Requests);
            await held.DisposeAsync();
            held = null;
            if (iterator is not null)
            {
                await iterator.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5));
                iterator = null;
            }

            if (cancellationKind != "close")
            {
                await stream.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5));
            }

            var recovered = await client.GenerateAsync(request);
            Assert.Equal("stop", recovered.FinishReason);
            Assert.Single(adapter.Requests);
        }
        finally
        {
            if (held is not null)
            {
                await held.DisposeAsync();
                held = null;
            }

            if (pending is not null)
            {
                try { await pending.WaitAsync(TimeSpan.FromSeconds(5)); }
                catch (Exception) { }
            }

            if (iterator is not null)
            {
                try { await iterator.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5)); }
                catch (OperationCanceledException) { }
            }

            if (stream is not null)
            {
                try { await stream.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5)); }
                catch (OperationCanceledException) { }
            }
        }
    }

    [Fact]
    public async Task Outer_permit_is_released_after_native_iterator_cleanup_failure_without_rewriting_the_source()
    {
        var clock = new VirtualTimeProvider();
        var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false), timeProvider: clock);
        var source = new InvalidOperationException("native cleanup");
        var adapter = new ScriptedAdapter((_, token) => FinalThenCleanupFailure(token, source));
        var descriptor = new ProviderDescriptor("cleanup", "Cleanup", (_, _) => ValueTask.FromResult<IProviderAdapter>(adapter), governsOwnTransport: true);
        var descriptors = new ProviderRegistry([descriptor]);
        await using var owner = AsyncClient.FromAdapters([]);
        await using var pool = new ProviderPool([ProviderSettings.Of("cleanup")], descriptors, AnyInfer.Credentials.ResolverChain.CreateDefault(),
            new Dictionary<string, RateLimiter>(StringComparer.Ordinal) { ["cleanup"] = limiter }, pacingTimeProvider: clock);
        var request = new GenerationRequest([Message.User("entry")], new Route(["cleanup:model"]), stream: true, timeoutS: 5);
        var normalized = RequestNormalizer.Normalize(request, true, SchemaExecutionProfile.ModernSdk);
        var resolver = new TargetMetadataResolver(ModelCatalog.LoadDefault(), descriptors, () => pool.Bindings, pool, new CapabilityStore());
        var telemetry = new RequestTelemetry(normalized, request.Route, new EventDispatcher(), null, Guid.NewGuid().ToString("D"));
        AsyncStream? stream = null;
        stream = new AsyncStream(owner, null, token => GenerationCore.ExecuteAsync(normalized, request.Route, pool, resolver,
            TargetResolutionProfile.PublicSdk, new RouteState(new SystemOperationClock()), new SystemOperationClock(), null, stream!,
            new GenerationPolicyContext(request, null, null, new CachePrefixState(), clock), token), default, telemetry: telemetry);

        var pending = stream.CollectAsync();
        RateLimitLease? recovered = null;
        Exception? primaryFailure = null;
        try
        {
            var failure = await Assert.ThrowsAsync<InvalidOperationException>(async () =>
                await pending.WaitAsync(TimeSpan.FromSeconds(5)));
            Assert.Same(source, failure);
            recovered = await limiter.AcquireAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5));
        }
        catch (Exception exception)
        {
            primaryFailure = exception;
            throw;
        }
        finally
        {
            Exception? cleanupFailure = null;
            try
            {
                if (recovered is not null)
                {
                    await recovered.DisposeAsync();
                    recovered = null;
                }
            }
            catch (Exception exception)
            {
                cleanupFailure ??= exception;
            }

            try
            {
                await pending.WaitAsync(TimeSpan.FromSeconds(5));
            }
            catch (Exception exception) when (ReferenceEquals(exception, source))
            {
            }
            catch (Exception exception)
            {
                cleanupFailure ??= exception;
            }

            try
            {
                await stream.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5));
            }
            catch (Exception exception)
            {
                cleanupFailure ??= exception;
            }

            if (primaryFailure is null && cleanupFailure is not null)
            {
                System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(cleanupFailure).Throw();
            }
        }
    }

    private static WireRequest Request(double timeoutS) =>
        new("fixture:model", [Message.User("entry pacing")], new Sampling(), timeoutS: timeoutS);

    private static async Task<List<AdapterEvent>> CollectAsync(IAsyncEnumerable<AdapterEvent> stream)
    {
        var result = new List<AdapterEvent>();
        await foreach (var item in stream)
        {
            result.Add(item);
        }

        return result;
    }

    private static async Task AssertConsumerPacingIsDetachedAsync()
    {
        var clock = new VirtualTimeProvider();
        var observations = new List<RateLimitWaited>();
        var limiter = new RateLimiter(
            new RateLimits(maxConcurrent: 1, respectHeaders: false),
            providerId: "consumer",
            events: item =>
            {
                if (item is RateLimitWaited waited)
                {
                    observations.Add(waited);
                }
            },
            timeProvider: clock);
        await using var held = await limiter.AcquireAsync();
        var queued = limiter.AcquireAsync().AsTask();
        clock.Advance(TimeSpan.FromSeconds(1));
        await held.DisposeAsync();
        await using var acquired = await queued;

        var observed = Assert.Single(observations);
        Assert.Equal(string.Empty, observed.RequestId);
        Assert.Null(observed.Target);
        Assert.Equal(1d, observed.WaitedS);
    }

    private static async IAsyncEnumerable<AdapterEvent> BlockUntilCancelled([EnumeratorCancellation] CancellationToken token)
    {
        await Task.Delay(Timeout.InfiniteTimeSpan, token);
        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> Finish([EnumeratorCancellation] CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        await Task.Yield();
        yield return new AdapterFinal("stop");
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

    private static async IAsyncEnumerable<AdapterEvent> FinalThenCleanupFailure(
        [EnumeratorCancellation] CancellationToken token,
        Exception source)
    {
        try
        {
            yield return new AdapterFinal("stop");
        }
        finally
        {
            await Task.Yield();
            throw source;
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Throw(Exception exception)
    {
        await Task.Yield();
        throw exception;
#pragma warning disable CS0162
        yield break;
#pragma warning restore CS0162
    }

    private sealed class ScriptedAdapter : IProviderAdapter
    {
        private readonly Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> _events;

        internal ScriptedAdapter(Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> events) => _events = events;
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal List<WireRequest> Requests { get; } = [];

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            Entered.TrySetResult();
            return _events(request, cancellationToken);
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class HttpSendingAdapter : IProviderAdapter
    {
        private readonly HttpClient _client;

        internal HttpSendingAdapter(HttpMessageHandler transport) => _client = new HttpClient(transport, disposeHandler: true);

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
            WireRequest request,
            [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            using var response = await _client.SendAsync(
                new HttpRequestMessage(HttpMethod.Post, "https://fixture.invalid/generate"), cancellationToken);
            response.EnsureSuccessStatusCode();
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync()
        {
            _client.Dispose();
            return ValueTask.CompletedTask;
        }
    }

    private sealed class CountingHandler : HttpMessageHandler
    {
        private int _sendCalls;

        internal int SendCalls => Volatile.Read(ref _sendCalls);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Interlocked.Increment(ref _sendCalls);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        }
    }

    private sealed class AttemptStartedObserver : IObserver
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public void OnEvent(TelemetryEvent telemetryEvent)
        {
            if (telemetryEvent is AttemptStarted)
            {
                Entered.TrySetResult();
            }
        }
    }

    private sealed class ThrowingDelayTimeProvider : TimeProvider
    {
        private readonly OperationCanceledException _source;
        internal ThrowingDelayTimeProvider(OperationCanceledException source) => _source = source;
        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period) => throw _source;
    }

    private sealed class GateOperationClock : IOperationClock
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public double NowSeconds { get; private set; }

        public async ValueTask DelayAsync(double seconds, CancellationToken cancellationToken = default)
        {
            Entered.TrySetResult();
            await Release.Task.WaitAsync(cancellationToken);
            NowSeconds += seconds;
        }
    }

    private sealed class VirtualTimeProvider : TimeProvider
    {
        private readonly object _gate = new();
        private readonly List<VirtualTimer> _timers = [];
        private readonly List<(int Count, TaskCompletionSource Completion)> _armingWaiters = [];
        private DateTimeOffset _now = new(2026, 1, 1, 0, 0, 0, TimeSpan.Zero);
        private long _timestamp;

        internal List<double> Armed { get; } = [];
        public override DateTimeOffset GetUtcNow() => _now;
        public override long GetTimestamp() => _timestamp;
        public override long TimestampFrequency => TimeSpan.TicksPerSecond;
        public override TimeZoneInfo LocalTimeZone => TimeZoneInfo.Utc;

        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        {
            var timer = new VirtualTimer(this, callback, state, dueTime, period);
            List<TaskCompletionSource>? completed = null;
            lock (_gate)
            {
                _timers.Add(timer);
                Armed.Add(dueTime.TotalSeconds);
                foreach (var waiter in _armingWaiters.Where(waiter => Armed.Count >= waiter.Count).ToArray())
                {
                    completed ??= [];
                    completed.Add(waiter.Completion);
                    _armingWaiters.Remove(waiter);
                }
            }

            foreach (var waiter in completed ?? [])
            {
                waiter.TrySetResult();
            }

            return timer;
        }

        internal Task WaitForArmedCountAsync(int count)
        {
            lock (_gate)
            {
                if (Armed.Count >= count)
                {
                    return Task.CompletedTask;
                }

                var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                _armingWaiters.Add((count, completion));
                return completion.Task;
            }
        }

        internal void Advance(TimeSpan amount)
        {
            var target = _now + amount;
            while (true)
            {
                VirtualTimer? next;
                lock (_gate)
                {
                    next = _timers.Where(timer => timer.Due <= target && !timer.Disposed).OrderBy(timer => timer.Due).FirstOrDefault();
                    if (next is null)
                    {
                        _timestamp += (target - _now).Ticks;
                        _now = target;
                        return;
                    }

                    _timestamp += (next.Due - _now).Ticks;
                    _now = next.Due;
                }

                next.Fire();
            }
        }

        private sealed class VirtualTimer : ITimer
        {
            private readonly VirtualTimeProvider _owner;
            private readonly TimerCallback _callback;
            private readonly object? _state;
            internal VirtualTimer(VirtualTimeProvider owner, TimerCallback callback, object? state, TimeSpan due, TimeSpan period)
            {
                _owner = owner;
                _callback = callback;
                _state = state;
                Due = owner._now + due;
            }

            internal DateTimeOffset Due { get; private set; }
            internal bool Disposed { get; private set; }
            public bool Change(TimeSpan dueTime, TimeSpan period)
            {
                if (Disposed) return false;
                Due = _owner._now + dueTime;
                return true;
            }

            public void Dispose() => Disposed = true;
            public ValueTask DisposeAsync() { Dispose(); return ValueTask.CompletedTask; }
            internal void Fire()
            {
                if (Disposed) return;
                Disposed = true;
                _callback(_state);
            }
        }
    }
}
