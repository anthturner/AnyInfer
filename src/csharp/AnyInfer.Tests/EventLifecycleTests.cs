using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Providers;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public async/sync manifest publication and telemetry lifetime controls.</summary>
public sealed class EventLifecycleTests
{
    [Fact]
    public async Task Async_stream_is_lazy_then_commits_one_shared_terminal_manifest_with_reported_usage()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token,
            new AdapterTextDelta("answer"),
            new AdapterUsage(new Usage(InputTokens: 2, OutputTokens: 3, CostUsd: EDecimal.FromString("1.25"), SearchUnits: 7)),
            new AdapterFinal("stop")));
        var observer = new Collector();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        var stream = client.StreamAsync("hello", target: "alpha:model");

        Assert.NotNull(stream.Manifest);
        Assert.False(stream.Manifest!.Complete);
        await using var enumerator = stream.GetAsyncEnumerator();
        Assert.Empty(observer.Events);
        Assert.Empty(adapter.Requests);

        Assert.True(await enumerator.MoveNextAsync());
        Assert.IsType<RequestStarted>(observer.Events.First());
        var publicEvents = new List<StreamEvent> { enumerator.Current };
        while (await enumerator.MoveNextAsync()) publicEvents.Add(enumerator.Current);

        var ended = Assert.IsType<StreamEnded>(publicEvents.Last());
        var manifest = ended.Result.Manifest;
        Assert.NotNull(manifest);
        Assert.Same(ended.Result, stream.Result);
        Assert.Same(manifest, stream.Manifest);
        Assert.False(manifest!.Usage.SearchUnits.HasValue);
        Assert.Equal("1.25", manifest.Usage.CostUsd);
        Assert.Equal(7, ended.Result.Usage!.SearchUnits);
        Assert.Equal(
            [typeof(RequestStarted), typeof(TargetResolved), typeof(AttemptStarted), typeof(UsageEstimated), typeof(FirstToken), typeof(AttemptCompleted), typeof(RequestCompleted)],
            observer.Events.Select(static item => item.GetType()));
        var estimate = Assert.Single(observer.Events.OfType<UsageEstimated>());
        Assert.Equal(Assert.IsType<RequestStarted>(observer.Events.First()).RequestId, estimate.RequestId);
        Assert.Equal(new ResolvedTarget("alpha", "model"), estimate.Target);
        Assert.Equal("input_tokens", estimate.FieldName);
        Assert.Equal("pre-dispatch context-gate estimate", estimate.Method);
        Assert.Single(adapter.Requests);
    }

    [Fact]
    public async Task Async_and_sync_manifest_switches_honor_client_defaults_and_per_call_overrides()
    {
        var asyncAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("a"), new AdapterFinal("stop")));
        await using (var disabled = AsyncClient.FromAdapters([new ProviderRegistration("alpha", asyncAdapter)], manifests: false))
        {
            Assert.Null((await disabled.GenerateAsync("a", target: "alpha:model")).Manifest);
            Assert.NotNull((await disabled.GenerateAsync("b", target: "alpha:model", manifest: true)).Manifest);
        }

        var syncAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("s"), new AdapterFinal("stop")));
        using var client = Client.FromAdapters([new ProviderRegistration("alpha", syncAdapter)], manifests: true);
        Assert.NotNull(client.Generate("s", target: "alpha:model").Manifest);
        Assert.Null(client.Generate("off", target: "alpha:model", manifest: false).Manifest);
        using var stream = client.Stream("inherit", target: "alpha:model");
        Assert.NotNull(stream.Manifest);
        var result = stream.Collect();
        Assert.Same(result.Manifest, stream.Manifest);
    }

    [Fact]
    public async Task Observer_payload_opt_in_is_independent_of_private_manifest_payload_capture()
    {
        var secret = "event-manifest-secret-" + Guid.NewGuid().ToString("N");
        Redaction.RegisterSecret(secret);
        var adapter = new ScriptedAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("not-json"), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("{\"answer\":\"ok\"}"), new AdapterFinal("stop")));
        var publicObserver = new Collector();
        var payloadObserver = new Collector();
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", adapter)],
            observers: [publicObserver],
            manifestPayloads: true);
        client.Subscribe(payloadObserver, payloads: true);
        var schema = new SchemaSpec(new JsonObject([
            new JsonProperty("type", new JsonString("object")),
            new JsonProperty("required", new JsonArray([new JsonString("answer")])),
            new JsonProperty("properties", new JsonObject([new JsonProperty("answer", new JsonObject([new JsonProperty("type", new JsonString("string"))]))])),
        ]));

        var result = await client.GenerateAsync($"prompt {secret}", target: "alpha:model", schema: schema, repair: new Repair(1));

        var publicStarted = Assert.IsType<RequestStarted>(publicObserver.Events.First());
        var payloadStarted = Assert.IsType<RequestStarted>(payloadObserver.Events.First());
        Assert.Null(publicStarted.PromptText);
        Assert.DoesNotContain(secret, Assert.IsType<string>(payloadStarted.PromptText), StringComparison.Ordinal);
        var publicRepair = Assert.IsType<RepairAttempted>(Assert.Single(publicObserver.Events.OfType<RepairAttempted>()));
        var payloadRepair = Assert.IsType<RepairAttempted>(Assert.Single(payloadObserver.Events.OfType<RepairAttempted>()));
        Assert.Null(publicRepair.RawText);
        Assert.Equal("not-json", payloadRepair.RawText);
        Assert.NotNull(result.Manifest?.Payloads);
        Assert.Equal(2, result.Manifest!.Payloads!.RepairTexts.Count);
        Assert.DoesNotContain(secret, Assert.IsType<string>(result.Manifest.Payloads.PromptText), StringComparison.Ordinal);
        Assert.Equal(2, adapter.Requests.Count);
    }

    [Theory]
    [InlineData(false, false, 0)]
    [InlineData(true, false, 1)]
    [InlineData(false, true, 0)]
    [InlineData(true, true, 2)]
    public async Task Repair_payload_capture_has_exact_manifest_and_observer_matrix(bool manifestPayloads, bool observerPayloads, int expectedRepairTexts)
    {
        var adapter = new ScriptedAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("not-json"), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("{\"answer\":\"ok\"}"), new AdapterFinal("stop")));
        var nonpayloadObserver = new Collector();
        var payloadObserver = new Collector();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], manifestPayloads: manifestPayloads);
        client.Subscribe(nonpayloadObserver, payloads: false);
        if (observerPayloads) client.Subscribe(payloadObserver, payloads: true);
        var schema = new SchemaSpec(new JsonObject([
            new JsonProperty("type", new JsonString("object")),
            new JsonProperty("required", new JsonArray([new JsonString("answer")])),
        ]));

        var result = await client.GenerateAsync("repair", target: "alpha:model", schema: schema, repair: new Repair(1));

        Assert.Equal(expectedRepairTexts, result.Manifest?.Payloads?.RepairTexts.Count ?? 0);
        var stripped = Assert.IsType<RepairAttempted>(Assert.Single(nonpayloadObserver.Events.OfType<RepairAttempted>()));
        Assert.Null(stripped.RawText);
        if (observerPayloads)
        {
            Assert.Equal("not-json", Assert.IsType<RepairAttempted>(Assert.Single(payloadObserver.Events.OfType<RepairAttempted>())).RawText);
        }
        else
        {
            Assert.Empty(payloadObserver.Events);
        }
    }

    [Fact]
    public async Task Manifests_disabled_ignores_manifest_payloads_even_when_observer_wants_payloads()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop")));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], manifests: false, manifestPayloads: true);

        Assert.Null((await client.GenerateAsync("no manifest", target: "alpha:model")).Manifest);
    }

    [Fact]
    public async Task Completion_observer_sees_committed_async_result_and_manifest_before_stream_ended_is_consumed()
    {
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ScriptedAdapter((_, token) => BlockingEvents(token, release));
        AsyncStream? stream = null;
        Generation? callbackResult = null;
        RunManifest? callbackManifest = null;
        var observer = new CallbackObserver(item =>
        {
            if (item is RequestCompleted)
            {
                callbackResult = stream!.Result;
                callbackManifest = stream.Manifest;
            }
        });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        stream = client.StreamAsync("hello", target: "alpha:model");
        await using var enumerator = stream.GetAsyncEnumerator();
        Assert.True(await enumerator.MoveNextAsync());
        release.TrySetResult();
        while (await enumerator.MoveNextAsync()) { }

        Assert.NotNull(callbackResult);
        Assert.Same(callbackResult, stream.Result);
        Assert.Same(callbackManifest, stream.Manifest);
        Assert.Same(stream.Result.Manifest, stream.Manifest);
    }

    [Fact]
    public async Task Completion_observer_sees_committed_sync_result_and_manifest_before_foreground_consumption()
    {
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ScriptedAdapter((_, token) => BlockingEvents(token, release));
        SyncStream? stream = null;
        Client? clientRef = null;
        Generation? callbackResult = null;
        RunManifest? callbackManifest = null;
        Exception? callbackRefusal = null;
        Exception? callbackClientRefusal = null;
        var callbackEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var observer = new CallbackObserver(item =>
        {
            if (item is RequestCompleted)
            {
                callbackResult = stream!.Result;
                callbackManifest = stream.Manifest;
                callbackRefusal = Assert.Throws<InvalidOperationException>(() => stream.Dispose());
                callbackClientRefusal = Assert.Throws<InvalidOperationException>(() => clientRef!.Dispose());
                callbackEntered.TrySetResult();
            }
        });
        using var client = Client.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        clientRef = client;
        stream = client.Stream("hello", target: "alpha:model");
        release.TrySetResult();
        await callbackEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.NotNull(callbackResult);
        Assert.NotNull(callbackManifest);
        Assert.IsType<InvalidOperationException>(callbackRefusal);
        Assert.IsType<InvalidOperationException>(callbackClientRefusal);
        var result = await Task.Run(() => stream.Collect());

        Assert.Same(result, callbackResult);
        Assert.Same(result.Manifest, callbackManifest);
        Assert.Same(result.Manifest, stream.Manifest);
    }

    [Fact]
    public async Task Fallback_is_emitted_for_the_next_raw_route_label_before_that_target_is_resolved()
    {
        var failure = new ProviderException("down", "transport", retryable: false, phase: "generate", detail: "down");
        var primary = new ScriptedAdapter((_, _) => Throw(failure));
        var secondary = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("recovered"), new AdapterFinal("stop")));
        var observer = new Collector();
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", primary), new ProviderRegistration("beta", secondary)], observers: [observer]);

        var result = await client.GenerateAsync("fallback", route: new Route(["alpha:model", "beta:model"]));

        Assert.Equal("recovered", result.Text);
        var events = observer.Events.ToArray();
        var fallbackIndex = Array.FindIndex(events, static item => item is FallbackTriggered);
        var betaResolvedIndex = Array.FindIndex(events, item => item is TargetResolved resolved && resolved.Target.ToString() == "beta:model");
        Assert.True(fallbackIndex >= 0);
        Assert.True(betaResolvedIndex >= 0);
        var fallback = Assert.IsType<FallbackTriggered>(events[fallbackIndex]);
        Assert.Equal("beta:model", fallback.ToTarget);
        Assert.True(fallbackIndex < betaResolvedIndex);
        Assert.Single(primary.Requests);
        Assert.Single(secondary.Requests);
    }

    [Fact]
    public async Task Duplicate_next_raw_target_receives_fallback_before_the_later_resolution_failure()
    {
        var transport = new ProviderException("down", "transport", retryable: false, phase: "generate", detail: "down");
        var alpha = new ScriptedAdapter((_, _) => Throw(transport));
        var observer = new Collector();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", alpha)], observers: [observer]);

        var failure = await Assert.ThrowsAsync<ProviderException>(() => client.GenerateAsync(
            "fallback", route: new Route(["alpha:model", "alpha:model", "missing:model"])));

        Assert.Equal("invalid_request", failure.Category);
        Assert.Equal("configure", failure.Phase);

        var fallback = Assert.Single(observer.Events.OfType<FallbackTriggered>());
        Assert.Equal("alpha:model", fallback.ToTarget);
        var fallbackPosition = observer.Events.IndexOf(fallback);
        var resolvedPosition = observer.Events.FindIndex(item => item is TargetResolved resolved && resolved.Target.ToString() == "alpha:model");
        Assert.True(fallbackPosition > resolvedPosition);
        Assert.Single(alpha.Requests);
    }

    [Fact]
    public async Task Target_resolved_precedes_unhealthy_skip_without_a_second_adapter_invocation()
    {
        var transport = new TransportException("unavailable", retryable: false, phase: "generate");
        var alpha = new ScriptedAdapter((_, _) => Throw(transport));
        var observer = new Collector();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", alpha)], observers: [observer]);
        var route = new Route(["alpha:model"], healthGate: true, healthTtlS: 30);

        await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("first", route: route));
        var secondStart = observer.Events.Count;
        await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("second", route: route));

        var secondEvents = observer.Events.Skip(secondStart).ToArray();
        var resolvedIndex = Array.FindIndex(secondEvents, static item => item is TargetResolved);
        var failureIndex = Array.FindIndex(secondEvents, static item => item is RequestFailed);
        Assert.True(resolvedIndex >= 0);
        Assert.True(failureIndex > resolvedIndex);
        Assert.Single(alpha.Requests);
    }

    [Fact]
    public async Task Inline_public_observer_cannot_dispose_its_own_async_stream_at_start_core_or_completion()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop")));
        AsyncStream? stream = null;
        AsyncClient? clientRef = null;
        var refusals = new List<Exception>();
        var observer = new CallbackObserver(item =>
        {
            if (item is RequestStarted or TargetResolved or RequestCompleted)
            {
                refusals.Add(Assert.Throws<InvalidOperationException>(() => stream!.DisposeAsync()));
                refusals.Add(Assert.Throws<InvalidOperationException>(() => clientRef!.DisposeAsync()));
            }
        });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        clientRef = client;
        stream = client.StreamAsync("self", target: "alpha:model");

        var result = await stream.CollectAsync();

        Assert.Equal(6, refusals.Count);
        Assert.All(refusals, static refusal => Assert.IsType<InvalidOperationException>(refusal));
        Assert.Same(result, stream.Result);
        Assert.NotNull(stream.Manifest);
    }

    [Fact]
    public async Task Inline_observer_cannot_dispose_its_own_active_enumerator_but_may_dispose_an_unrelated_stream()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop")));
        AsyncStream? active = null;
        IAsyncEnumerator<StreamEvent>? enumerator = null;
        AsyncStream? unrelated = null;
        Exception? ownRefusal = null;
        Task? unrelatedClose = null;
        var observer = new CallbackObserver(item =>
        {
            if (item is RequestStarted)
            {
                ownRefusal = Assert.Throws<InvalidOperationException>(() => enumerator!.DisposeAsync());
                unrelatedClose = unrelated!.DisposeAsync().AsTask();
            }
        });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        active = client.StreamAsync("active", target: "alpha:model");
        unrelated = client.StreamAsync("unrelated", target: "alpha:model");
        await using (enumerator = active.GetAsyncEnumerator())
        {
            while (await enumerator.MoveNextAsync()) { }
        }

        Assert.IsType<InvalidOperationException>(ownRefusal);
        Assert.NotNull(unrelatedClose);
        await unrelatedClose.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.False(unrelated.Manifest!.Complete);
        Assert.Equal("ok", active.Result.Text);
        Assert.NotNull(active.Manifest);
    }

    [Fact]
    public async Task Adapter_originated_cancellation_preserves_identity_and_leaves_an_incomplete_manifest_without_terminal_telemetry()
    {
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        var planted = new OperationCanceledException("adapter cancellation", innerException: null, cancellation.Token);
        var adapter = new ScriptedAdapter((_, _) => Throw(planted));
        var observer = new Collector();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        var stream = client.StreamAsync("cancel", target: "alpha:model");

        var escaped = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => stream.CollectAsync());

        Assert.Same(planted, escaped);
        Assert.Equal(cancellation.Token, escaped.CancellationToken);
        Assert.False(stream.Manifest!.Complete);
        Assert.DoesNotContain(observer.Events, static item => item is RequestCompleted or RequestFailed);
    }

    [Fact]
    public async Task External_close_joins_entered_inline_callback_and_token_ignoring_adapter_cleanup_without_publishing_completion()
    {
        using var callbackEntered = new ManualResetEventSlim();
        using var releaseCallback = new ManualResetEventSlim();
        var callbackFailure = new TaskCompletionSource<Exception>(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleanupEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseCleanup = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ScriptedAdapter((_, token) => FirstTokenThenBlockingCleanup(token, cleanupEntered, releaseCleanup));
        var observer = new Collector();
        var callback = new CallbackObserver(item =>
        {
            if (item is FirstToken)
            {
                callbackEntered.Set();
                try
                {
                    if (!releaseCallback.Wait(TimeSpan.FromSeconds(5)))
                    {
                        callbackFailure.TrySetResult(new TimeoutException("The test did not release the callback."));
                    }
                }
                catch (Exception exception)
                {
                    callbackFailure.TrySetResult(exception);
                }
            }
        });
        var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer, callback]);
        var stream = client.StreamAsync("late", target: "alpha:model");
        var pendingCollect = Task.Run(() => stream.CollectAsync());
        Assert.True(await Task.Run(() => callbackEntered.Wait(TimeSpan.FromSeconds(5))));

        var close = client.DisposeAsync().AsTask();
        Assert.False(close.IsCompleted);
        try
        {
            releaseCallback.Set();
            await cleanupEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.False(close.IsCompleted);
            releaseCleanup.TrySetResult();
            await close.WaitAsync(TimeSpan.FromSeconds(5));
        }
        finally
        {
            releaseCallback.Set();
            releaseCleanup.TrySetResult();
        }
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pendingCollect);
        Assert.False(callbackFailure.Task.IsCompleted);
        Assert.False(stream.Manifest!.Complete);
        Assert.DoesNotContain(observer.Events, static item => item is RequestCompleted);
    }

    [Fact]
    public async Task Routed_terminal_configuration_failure_emits_one_request_failed_and_no_completion()
    {
        var source = new ConfigException("configured failure", "alpha");
        var adapter = new ScriptedAdapter((_, _) => Throw(source));
        AsyncStream? stream = null;
        var refusals = new ConcurrentQueue<Exception>();
        var completions = 0;
        var observer = new CallbackObserver(item =>
        {
            if (item is RequestFailed)
            {
                refusals.Enqueue(Assert.Throws<InvalidOperationException>(() => stream!.DisposeAsync()));
            }
            else if (item is RequestCompleted)
            {
                Interlocked.Increment(ref completions);
            }
        });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        stream = client.StreamAsync("fail", target: "alpha:model");

        var escaped = await Assert.ThrowsAsync<ConfigException>(() => stream.CollectAsync());

        Assert.Same(source, escaped);
        var refusal = Assert.Single(refusals);
        Assert.IsType<InvalidOperationException>(refusal);
        Assert.False(stream.Manifest!.Complete);
        Assert.Equal(0, Volatile.Read(ref completions));
    }

    [Fact]
    public async Task Untyped_adapter_failure_preserves_its_exact_source_identity_without_terminal_telemetry()
    {
        var source = new InvalidOperationException("adapter sentinel");
        var adapter = new ScriptedAdapter((_, _) => Throw(source));
        var observer = new Collector();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        var stream = client.StreamAsync("fail", target: "alpha:model");

        var escaped = await Assert.ThrowsAsync<InvalidOperationException>(() => stream.CollectAsync());

        Assert.Same(source, escaped);
        Assert.False(stream.Manifest!.Complete);
        Assert.DoesNotContain(observer.Events, static item => item is RequestCompleted or RequestFailed);
    }

    [Fact]
    public async Task Caller_cancellation_proxy_preserves_original_token_and_refuses_same_stream_disposal_from_adapter_unsafe_register()
    {
        using var caller = new CancellationTokenSource();
        var registered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var iteratorFinally = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callback = new TaskCompletionSource<Exception>(TaskCreationOptions.RunContinuationsAsynchronously);
        var planted = new OperationCanceledException("adapter source cancellation", innerException: null, caller.Token);
        AsyncStream? stream = null;
        var adapter = new ScriptedAdapter((_, token) => UnsafeCancellationEvents(token, planted, registered, iteratorFinally, callback, () => stream!));
        var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)]);
        stream = client.StreamAsync("cancel", target: "alpha:model", cancellationToken: caller.Token);
        var pending = stream.CollectAsync();
        await registered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        caller.Cancel();

        var refusal = await callback.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var escaped = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.IsType<InvalidOperationException>(refusal);
        // A caller checkpoint may win before the prefetched native source OCE is read.
        // Exact source identity is covered by the non-racing adapter-originated controls.
        Assert.Equal(caller.Token, escaped.CancellationToken);
        Assert.False(stream.Manifest!.Complete);
        await iteratorFinally.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(0, adapter.DisposeCalls);
        await client.DisposeAsync();
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Captured_sync_stream_unsafe_register_refuses_own_disposal_and_preserves_the_original_caller_token()
    {
        using var caller = new CancellationTokenSource();
        var registered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callback = new TaskCompletionSource<Exception>(TaskCreationOptions.RunContinuationsAsynchronously);
        var planted = new OperationCanceledException("sync adapter source cancellation", innerException: null, caller.Token);
        SyncStream? stream = null;
        var adapter = new ScriptedAdapter((_, token) => UnsafeSyncCancellationEvents(token, planted, registered, callback, () => stream!));
        using var client = Client.FromAdapters([new ProviderRegistration("alpha", adapter)]);
        stream = client.Stream("cancel", target: "alpha:model", cancellationToken: caller.Token);
        var pending = Task.Run(() => stream.Collect());
        await registered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        caller.Cancel();

        Assert.IsType<InvalidOperationException>(await callback.Task.WaitAsync(TimeSpan.FromSeconds(5)));
        var escaped = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        // A caller checkpoint may win before the prefetched native source OCE is read.
        // Exact source identity is covered by the non-racing adapter-originated controls.
        Assert.Equal(caller.Token, escaped.CancellationToken);
        Assert.False(stream.Manifest!.Complete);
    }

    [Fact]
    public async Task Direct_sync_stream_close_replays_a_native_iterator_cleanup_failure_until_parent_ownership_finishes()
    {
        var source = new InvalidOperationException("native cleanup sentinel");
        using var callbackEntered = new ManualResetEventSlim();
        using var releaseCallback = new ManualResetEventSlim();
        var cancellationObserved = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ScriptedAdapter((_, token) => CleanupDisposalFailureEvents(token, source, cancellationObserved, cleaned));
        var observer = new CallbackObserver(item =>
        {
            if (item is FirstToken)
            {
                callbackEntered.Set();
                releaseCallback.Wait(TimeSpan.FromSeconds(5));
            }
        });
        var client = Client.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        var stream = client.Stream("close", target: "alpha:model");
        var pending = Task.Run(() => stream.Collect());
        Assert.True(await Task.Run(() => callbackEntered.Wait(TimeSpan.FromSeconds(5))));
        Exception first;
        try
        {
            var close = Task.Run(() => Assert.Throws<InvalidOperationException>(stream.Dispose));
            await cancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.False(close.IsCompleted);
            releaseCallback.Set();
            first = await close.WaitAsync(TimeSpan.FromSeconds(5));
        }
        finally
        {
            releaseCallback.Set();
        }
        var second = await Task.Run(() => Assert.Throws<InvalidOperationException>(stream.Dispose));

        Assert.Same(source, first);
        Assert.Same(source, second);
        await cleaned.Task.WaitAsync(TimeSpan.FromSeconds(5));
        _ = await Observe(pending);
        _ = await Task.Run(() => Record.Exception(client.Dispose));
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Client_owned_sync_close_reports_native_cleanup_failure_then_later_child_close_is_a_no_op()
    {
        var source = new InvalidOperationException("client cleanup sentinel");
        using var callbackEntered = new ManualResetEventSlim();
        using var releaseCallback = new ManualResetEventSlim();
        var cancellationObserved = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ScriptedAdapter((_, token) => CleanupDisposalFailureEvents(token, source, cancellationObserved, cleaned));
        var observer = new CallbackObserver(item =>
        {
            if (item is FirstToken)
            {
                callbackEntered.Set();
                releaseCallback.Wait(TimeSpan.FromSeconds(5));
            }
        });
        var client = Client.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);
        var stream = client.Stream("close", target: "alpha:model");
        var pending = Task.Run(() => stream.Collect());
        Assert.True(await Task.Run(() => callbackEntered.Wait(TimeSpan.FromSeconds(5))));
        Exception first;
        try
        {
            var close = Task.Run(() => Assert.Throws<InvalidOperationException>(client.Dispose));
            await cancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.False(close.IsCompleted);
            releaseCallback.Set();
            first = await close.WaitAsync(TimeSpan.FromSeconds(5));
        }
        finally
        {
            releaseCallback.Set();
        }

        Assert.Same(source, first);
        await cleaned.Task.WaitAsync(TimeSpan.FromSeconds(5));
        _ = await Observe(pending);
        await Task.Run(stream.Dispose);
        Assert.Equal(1, adapter.DisposeCalls);
        var repeated = await Task.Run(() => Assert.Throws<InvalidOperationException>(client.Dispose));
        Assert.Same(source, repeated);
    }

    [Fact]
    public async Task Client_close_marks_only_the_selected_cleanup_failure_as_parent_observed()
    {
        var firstSource = new InvalidOperationException("first cleanup sentinel");
        var secondSource = new InvalidOperationException("second cleanup sentinel");
        using var releaseCallbacks = new ManualResetEventSlim();
        var callbacksEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackCount = 0;
        var firstCancelled = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var secondCancelled = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var firstCleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var secondCleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var firstAdapter = new ScriptedAdapter((_, token) => CleanupDisposalFailureEvents(token, firstSource, firstCancelled, firstCleaned));
        var secondAdapter = new ScriptedAdapter((_, token) => CleanupDisposalFailureEvents(token, secondSource, secondCancelled, secondCleaned));
        var observer = new CallbackObserver(item =>
        {
            if (item is FirstToken)
            {
                if (Interlocked.Increment(ref callbackCount) == 2) callbacksEntered.TrySetResult();
                releaseCallbacks.Wait(TimeSpan.FromSeconds(5));
            }
        });
        var client = Client.FromAdapters([
            new ProviderRegistration("first", firstAdapter),
            new ProviderRegistration("second", secondAdapter),
        ], observers: [observer]);
        var first = client.Stream("first", target: "first:model");
        var second = client.Stream("second", target: "second:model");
        var firstPending = Task.Run(() => first.Collect());
        var secondPending = Task.Run(() => second.Collect());
        await callbacksEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        Exception parentFailure;
        try
        {
            var close = Task.Run(() => Assert.Throws<InvalidOperationException>(client.Dispose));
            await Task.WhenAll(firstCancelled.Task, secondCancelled.Task).WaitAsync(TimeSpan.FromSeconds(5));
            Assert.False(close.IsCompleted);
            releaseCallbacks.Set();
            parentFailure = await close.WaitAsync(TimeSpan.FromSeconds(5));
        }
        finally
        {
            releaseCallbacks.Set();
        }

        await Task.WhenAll(firstCleaned.Task, secondCleaned.Task).WaitAsync(TimeSpan.FromSeconds(5));
        _ = await Observe(firstPending);
        _ = await Observe(secondPending);
        Assert.True(ReferenceEquals(parentFailure, firstSource) || ReferenceEquals(parentFailure, secondSource));
        var selectedFirst = ReferenceEquals(parentFailure, firstSource);
        var firstLater = await Task.Run(() => Record.Exception(first.Dispose));
        var secondLater = await Task.Run(() => Record.Exception(second.Dispose));
        Assert.Null(selectedFirst ? firstLater : secondLater);
        Assert.Same(selectedFirst ? secondSource : firstSource, selectedFirst ? secondLater : firstLater);
        Assert.Equal(1, firstAdapter.DisposeCalls);
        Assert.Equal(1, secondAdapter.DisposeCalls);
        var repeated = await Task.Run(() => Assert.Throws<InvalidOperationException>(client.Dispose));
        Assert.Same(parentFailure, repeated);
    }

    [Fact]
    public async Task Raw_capability_probe_does_not_create_normal_generation_telemetry()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("{}"), new AdapterFinal("stop")));
        var observer = new Collector();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], observers: [observer]);

        await client.ProbeAsync("alpha:model", [AnyInfer.Capabilities.Feature.JsonMode]);

        Assert.Empty(observer.Events);
        Assert.Single(adapter.Requests);
    }

    [Fact]
    public async Task Boolean_schema_root_reads_and_assesses_the_real_response()
    {
        var booleanAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("{\"answer\":true}"), new AdapterFinal("stop")));
        await using (var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", booleanAdapter)]))
        {
            var result = await client.GenerateAsync("boolean", target: "alpha:model", schema: new SchemaSpec(new JsonBoolean(true)));
            Assert.Equal("{\"answer\":true}", result.Text);
            Assert.Single(booleanAdapter.Requests);
        }

    }

    private static async IAsyncEnumerable<AdapterEvent> Events(
        [EnumeratorCancellation] CancellationToken cancellationToken,
        params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> BlockingEvents(
        [EnumeratorCancellation] CancellationToken cancellationToken,
        TaskCompletionSource release)
    {
        yield return new AdapterTextDelta("answer");
        await release.Task.WaitAsync(cancellationToken);
        yield return new AdapterFinal("stop");
    }

    private static async IAsyncEnumerable<AdapterEvent> FirstTokenThenBlockingCleanup(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource cleanupEntered,
        TaskCompletionSource releaseCleanup)
    {
        try
        {
            yield return new AdapterTextDelta("late");
            await Task.Delay(Timeout.InfiniteTimeSpan, token).ConfigureAwait(false);
        }
        finally
        {
            cleanupEntered.TrySetResult();
            await releaseCleanup.Task.ConfigureAwait(false);
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> UnsafeCancellationEvents(
        [EnumeratorCancellation] CancellationToken token,
        OperationCanceledException planted,
        TaskCompletionSource registered,
        TaskCompletionSource iteratorFinally,
        TaskCompletionSource<Exception> callback,
        Func<AsyncStream> stream)
    {
        try
        {
            var cancellationDelay = Task.Delay(Timeout.InfiniteTimeSpan, token);
            using var registration = token.UnsafeRegister(static state =>
            {
                var pair = ((TaskCompletionSource<Exception> Callback, Func<AsyncStream> Stream))state!;
                try { pair.Callback.TrySetResult(Assert.Throws<InvalidOperationException>(() => pair.Stream().DisposeAsync())); }
                catch (Exception exception) { pair.Callback.TrySetResult(exception); }
            }, (callback, stream));
            registered.TrySetResult();
            try { await cancellationDelay; }
            catch (OperationCanceledException) { System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(planted).Throw(); throw; }
            yield break;
        }
        finally
        {
            iteratorFinally.TrySetResult();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> UnsafeSyncCancellationEvents(
        [EnumeratorCancellation] CancellationToken token,
        OperationCanceledException planted,
        TaskCompletionSource registered,
        TaskCompletionSource<Exception> callback,
        Func<SyncStream> stream)
    {
        var cancellationDelay = Task.Delay(Timeout.InfiniteTimeSpan, token);
        using var registration = token.UnsafeRegister(static state =>
        {
            var pair = ((TaskCompletionSource<Exception> Callback, Func<SyncStream> Stream))state!;
            try { pair.Callback.TrySetResult(Assert.Throws<InvalidOperationException>(() => pair.Stream().Dispose())); }
            catch (Exception exception) { pair.Callback.TrySetResult(exception); }
        }, (callback, stream));
        registered.TrySetResult();
        try { await cancellationDelay; }
        catch (OperationCanceledException) { System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(planted).Throw(); throw; }
        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> CleanupDisposalFailureEvents(
        [EnumeratorCancellation] CancellationToken token,
        Exception failure,
        TaskCompletionSource cancellationObserved,
        TaskCompletionSource cleaned)
    {
        using var registration = token.UnsafeRegister(static state => ((TaskCompletionSource)state!).TrySetResult(), cancellationObserved);
        try
        {
            yield return new AdapterTextDelta("pending");
            await Task.Delay(Timeout.InfiniteTimeSpan, token);
        }
        finally
        {
            cleaned.TrySetResult();
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private static async Task<Exception?> Observe(Task task)
    {
        try
        {
            await task.WaitAsync(TimeSpan.FromSeconds(5));
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Throw(Exception exception)
    {
        await Task.Yield();
        System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(exception).Throw();
        yield break;
    }

    private sealed class ScriptedAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        private readonly Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> _script = script;
        internal List<WireRequest> Requests { get; } = [];
        internal int DisposeCalls { get; private set; }
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return _script(Requests.Count, cancellationToken);
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class Collector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }

    private sealed class CallbackObserver(Action<TelemetryEvent> callback) : IObserver
    {
        public void OnEvent(TelemetryEvent telemetryEvent) => callback(telemetryEvent);
    }
}
