using System.Collections.Concurrent;
using System.Runtime.ExceptionServices;
using AnyInfer;
using AnyInfer.Core;
using AnyInfer.Events;
using AnyInfer.Internal;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Independent controls for entry-timer arming, callback ownership, and failure precedence.</summary>
public sealed class EntryTimerFailureTests
{
    [Fact]
    public async Task Timer_arm_failure_escapes_unchanged_before_the_adapter_and_disposes_staged_sources()
    {
        var sentinel = new InvalidOperationException("arm");
        var clock = new ThrowingArmTimeProvider(sentinel);
        var capture = new OperationCapture();
        var operation = new OperationContext(capture, clock);
        var adapter = new RecordingAdapter(static _ => Empty());

        var failure = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original)));

        Assert.Same(sentinel, failure);
        Assert.Equal(0, adapter.GenerateCalls);
        var entry = Assert.Single(capture.Entries);
        Assert.True(entry.Timeout.IsDisposed);
        Assert.Throws<ObjectDisposedException>(() => entry.Timeout.TimeoutSource.Cancel());
        Assert.Throws<ObjectDisposedException>(() => entry.Timeout.LinkedSource.Cancel());
    }

    [Fact]
    public async Task Timer_dispose_failure_waits_for_a_published_callback_before_disposing_sources()
    {
        var sentinel = new InvalidOperationException("timer dispose");
        var clock = new ControlledTimeProvider(throwOnDispose: sentinel);
        var (_, scope) = CreateScope(clock);
        var callbackEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var registration = scope.TimeoutToken.UnsafeRegister(static state =>
        {
            var pair = ((TaskCompletionSource Entered, TaskCompletionSource Release))state!;
            pair.Entered.TrySetResult();
            pair.Release.Task.GetAwaiter().GetResult();
        }, (callbackEntered, callbackRelease));

        Task? firing = null;
        Task? disposing = null;
        Exception? primary = null;
        Exception? cleanup = null;
        try
        {
            firing = clock.FireAsync();
            await callbackEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            disposing = scope.DisposeAsync().AsTask();
            Assert.False(disposing.IsCompleted);
            Assert.False(scope.IsDisposed);

            callbackRelease.TrySetResult();
            await firing.WaitAsync(TimeSpan.FromSeconds(5));
            await disposing.WaitAsync(TimeSpan.FromSeconds(5));

            Assert.True(scope.IsDisposed);
            Assert.Same(sentinel, scope.DeferredFailure);
            Assert.Throws<ObjectDisposedException>(() => scope.TimeoutSource.Cancel());
            Assert.Throws<ObjectDisposedException>(() => scope.LinkedSource.Cancel());
        }
        catch (Exception exception)
        {
            primary = exception;
        }
        finally
        {
            callbackRelease.TrySetResult();
            cleanup = await ObservePendingAsync(firing, cleanup);
            cleanup = await ObservePendingAsync(disposing, cleanup);
            if (!scope.IsDisposed)
            {
                cleanup = await ObservePendingAsync(scope.DisposeAsync().AsTask(), cleanup);
            }
        }

        Rethrow(primary, cleanup);
    }

    [Fact]
    public async Task Timer_callback_restores_real_owner_contexts_without_capturing_the_registration_context()
    {
        var clock = new ControlledTimeProvider();
        using var caller = new CancellationTokenSource();
        await using var asyncClient = AsyncClient.FromAdapters([]);
        using var syncClient = new Client();
        var request = new GenerationRequest(
            [Message.User("timer")],
            new Route(["timer:model"]),
            stream: true,
            timeoutS: 1);
        var normalized = RequestNormalizer.Normalize(request, true, SchemaExecutionProfile.ModernSdk);
        var telemetry = new RequestTelemetry(
            normalized,
            request.Route,
            new EventDispatcher(),
            null,
            Guid.NewGuid().ToString("D"));
        await using var stream = new AsyncStream(
            asyncClient,
            syncClient,
            static _ => EmptyStream(),
            caller.Token,
            telemetry: telemetry);
        var observations = new ConcurrentQueue<Exception?>();
        var deferredDisposals = new ConcurrentQueue<Task<Exception?>>();
        var completed = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        EntryTimeoutScope scope;

        using (AsyncExecutionContext.Push(asyncClient, syncClient))
        using (SyncExecutionContext.Push(syncClient))
        using (StreamExecutionContext.Push(stream))
        using (CancellationIdentityContext.Push(caller.Token, caller.Token))
        {
            (_, scope) = CreateScope(clock, caller.Token);
        }

        using var registration = scope.TimeoutToken.UnsafeRegister(static state =>
        {
            var values = ((AsyncClient AsyncClient, Client SyncClient, AsyncStream Stream,
                EntryTimeoutScope Scope, CancellationToken Caller, ConcurrentQueue<Exception?> Observations,
                ConcurrentQueue<Task<Exception?>> DeferredDisposals, TaskCompletionSource Completed))state!;
            values.Observations.Enqueue(AsyncExecutionContext.CurrentAsyncClient == values.AsyncClient ? null : new InvalidOperationException("async owner missing"));
            values.Observations.Enqueue(SyncExecutionContext.CurrentClient == values.SyncClient ? null : new InvalidOperationException("sync owner missing"));
            values.Observations.Enqueue(StreamExecutionContext.Current == values.Stream ? null : new InvalidOperationException("stream owner missing"));
            values.Observations.Enqueue(CancellationIdentityContext.Resolve(values.Scope.Token) == values.Caller ? null : new InvalidOperationException("caller identity missing"));
            values.Observations.Enqueue(RecordSelfDispose(values.AsyncClient.DisposeAsync, values.DeferredDisposals));
            values.Observations.Enqueue(RecordSelfDispose(values.SyncClient.Dispose));
            values.Observations.Enqueue(RecordSelfDispose(values.Stream.DisposeAsync, values.DeferredDisposals));
            values.Completed.TrySetResult();
        }, (asyncClient, syncClient, stream, scope, caller.Token, observations, deferredDisposals, completed));

        Task? firing = null;
        Exception? primary = null;
        Exception? cleanup = null;
        try
        {
            firing = clock.FireAsync();
            await completed.Task.WaitAsync(TimeSpan.FromSeconds(5));
            await firing.WaitAsync(TimeSpan.FromSeconds(5));
            await scope.DisposeAsync();
            while (deferredDisposals.TryDequeue(out var deferred))
            {
                observations.Enqueue(await deferred.WaitAsync(TimeSpan.FromSeconds(5)));
            }

            var observed = observations.ToArray();
            Assert.All(observed[..4], static observation => Assert.Null(observation));
            Assert.All(observed[4..], static observation => Assert.IsType<InvalidOperationException>(observation));
            Assert.Equal(7, observed.Length);
        }
        catch (Exception exception)
        {
            primary = exception;
        }
        finally
        {
            cleanup = await ObservePendingAsync(firing, cleanup);
            if (!scope.IsDisposed)
            {
                cleanup = await ObservePendingAsync(scope.DisposeAsync().AsTask(), cleanup);
            }
            while (deferredDisposals.TryDequeue(out var deferred))
            {
                cleanup = await ObservePendingAsync(deferred, cleanup);
            }
        }

        Rethrow(primary, cleanup);
    }

    [Fact]
    public async Task Timer_callback_failure_is_deferred_and_rethrown_by_the_boundary_when_no_native_failure_precedes_it()
    {
        var callback = new InvalidOperationException("callback");
        var clock = new ControlledTimeProvider();
        var capture = new OperationCapture();
        var operation = new OperationContext(capture, clock);
        var adapter = new GateAdapter();
        var pending = CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original));
        Task? firing = null;
        Exception? primary = null;
        Exception? cleanup = null;
        try
        {
            await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var timeout = Assert.Single(capture.Entries).Timeout;
            using var registration = timeout.TimeoutToken.UnsafeRegister(static state => throw (Exception)state!, callback);

            firing = clock.FireAsync();
            await firing.WaitAsync(TimeSpan.FromSeconds(5));
            adapter.Release.TrySetResult();
            var failure = await Assert.ThrowsAsync<AggregateException>(() => pending);

            Assert.Same(timeout.DeferredFailure, failure);
            Assert.Contains(callback, failure.InnerExceptions);
            Assert.True(timeout.IsDisposed);
        }
        catch (Exception exception)
        {
            primary = exception;
        }
        finally
        {
            adapter.Release.TrySetResult();
            cleanup = await ObservePendingAsync(firing, cleanup);
            if (!pending.IsCompleted)
            {
                cleanup = await ObservePendingAsync(pending, cleanup);
            }
        }

        Rethrow(primary, cleanup);
    }

    [Fact]
    public async Task Native_failure_wins_over_a_timer_callback_failure_and_cleanup_still_completes()
    {
        var callback = new InvalidOperationException("callback");
        var native = new InvalidOperationException("native");
        var clock = new ControlledTimeProvider();
        var capture = new OperationCapture();
        var operation = new OperationContext(capture, clock);
        var adapter = new GateAdapter(native);
        var pending = CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original));
        Task? firing = null;
        Exception? primary = null;
        Exception? cleanup = null;
        try
        {
            await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var timeout = Assert.Single(capture.Entries).Timeout;
            using var registration = timeout.TimeoutToken.UnsafeRegister(static state => throw (Exception)state!, callback);

            firing = clock.FireAsync();
            await firing.WaitAsync(TimeSpan.FromSeconds(5));
            adapter.Release.TrySetResult();
            var failure = await Assert.ThrowsAsync<InvalidOperationException>(() => pending);

            Assert.Same(native, failure);
            Assert.IsType<AggregateException>(timeout.DeferredFailure);
            Assert.True(timeout.IsDisposed);
        }
        catch (Exception exception)
        {
            primary = exception;
        }
        finally
        {
            adapter.Release.TrySetResult();
            cleanup = await ObservePendingAsync(firing, cleanup);
            if (!pending.IsCompleted)
            {
                cleanup = await ObservePendingAsync(pending, cleanup);
            }
        }

        Rethrow(primary, cleanup);
    }

    [Fact]
    public async Task Iterator_dispose_failure_wins_over_a_timer_callback_failure_and_cleanup_still_completes()
    {
        var callback = new InvalidOperationException("callback");
        var disposal = new InvalidOperationException("iterator dispose");
        var clock = new ControlledTimeProvider();
        var capture = new OperationCapture();
        var operation = new OperationContext(capture, clock);
        var adapter = new DisposeFaultAdapter(disposal);
        await using var enumerator = AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original)
            .GetAsyncEnumerator();

        Assert.True(await enumerator.MoveNextAsync());
        var timeout = Assert.Single(capture.Entries).Timeout;
        using var registration = timeout.TimeoutToken.UnsafeRegister(static state => throw (Exception)state!, callback);

        await clock.FireAsync().WaitAsync(TimeSpan.FromSeconds(5));
        var failure = await Assert.ThrowsAsync<InvalidOperationException>(() => enumerator.DisposeAsync().AsTask());

        Assert.Same(disposal, failure);
        Assert.IsType<AggregateException>(timeout.DeferredFailure);
        Assert.True(timeout.IsDisposed);
    }

    private static (EntryContext Entry, EntryTimeoutScope Scope) CreateScope(
        TimeProvider clock,
        CancellationToken callerToken = default)
    {
        var operation = new OperationContext(entryTimeProvider: clock);
        var entry = operation.BeginEntry(Request(), EntryRole.Original, null);
        return (entry, new EntryTimeoutScope(entry, callerToken, clock));
    }

    private static WireRequest Request() =>
        new("timer:model", [Message.User("timer")], new Sampling(), timeoutS: 1);

    private static Exception? RecordSelfDispose(
        Func<ValueTask> dispose,
        ConcurrentQueue<Task<Exception?>> deferredDisposals)
    {
        try
        {
            var result = dispose();
            if (result.IsCompleted)
            {
                result.GetAwaiter().GetResult();
                return null;
            }

            deferredDisposals.Enqueue(ObserveValueTaskAsync(result));
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }

    private static Exception? RecordSelfDispose(Action dispose)
    {
        try
        {
            dispose();
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }

    private static async Task<List<AdapterEvent>> CollectAsync(IAsyncEnumerable<AdapterEvent> events)
    {
        var values = new List<AdapterEvent>();
        await foreach (var item in events)
        {
            values.Add(item);
        }
        return values;
    }

    private static async IAsyncEnumerable<AdapterEvent> Empty()
    {
        await Task.Yield();
        yield break;
    }

    private static async IAsyncEnumerable<StreamEvent> EmptyStream()
    {
        await Task.Yield();
        yield break;
    }

    private static async Task<Exception?> ObservePendingAsync(Task? task, Exception? previous = null)
    {
        if (task is null)
        {
            return previous;
        }

        try
        {
            await task.WaitAsync(TimeSpan.FromSeconds(5));
            return previous;
        }
        catch (Exception exception)
        {
            return previous ?? exception;
        }
    }

    private static async Task<Exception?> ObservePendingAsync(Task<Exception?> task, Exception? previous = null)
    {
        var failure = await ObservePendingAsync((Task)task, previous);
        return failure ?? (task.IsCompletedSuccessfully ? task.Result : null);
    }

    private static async Task<Exception?> ObserveValueTaskAsync(ValueTask task)
    {
        try
        {
            await task;
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }

    private static void Rethrow(Exception? primary, Exception? cleanup)
    {
        if (primary is not null)
        {
            ExceptionDispatchInfo.Capture(primary).Throw();
        }

        if (cleanup is not null)
        {
            ExceptionDispatchInfo.Capture(cleanup).Throw();
        }
    }

    private sealed class RecordingAdapter : IProviderAdapter
    {
        private readonly Func<CancellationToken, IAsyncEnumerable<AdapterEvent>> _events;

        internal RecordingAdapter(Func<CancellationToken, IAsyncEnumerable<AdapterEvent>> events) => _events = events;
        internal int GenerateCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            return _events(cancellationToken);
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class GateAdapter : IProviderAdapter
    {
        private readonly Exception? _failure;

        internal GateAdapter(Exception? failure = null) => _failure = failure;
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => Events();

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;

        private async IAsyncEnumerable<AdapterEvent> Events()
        {
            Entered.TrySetResult();
            await Release.Task.ConfigureAwait(false);
            if (_failure is not null)
            {
                throw _failure;
            }
            yield return new AdapterFinal("stop");
        }
    }

    private sealed class DisposeFaultAdapter : IProviderAdapter
    {
        private readonly Exception _failure;

        internal DisposeFaultAdapter(Exception failure) => _failure = failure;

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => Events();

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;

        private async IAsyncEnumerable<AdapterEvent> Events()
        {
            try
            {
                yield return new AdapterTextDelta("partial");
            }
            finally
            {
                await Task.Yield();
                throw _failure;
            }
        }
    }

    private sealed class ThrowingArmTimeProvider(Exception failure) : TimeProvider
    {
        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period) =>
            throw failure;
    }

    private sealed class ControlledTimeProvider : TimeProvider
    {
        private readonly Exception? _throwOnDispose;
        private TimerCallback? _callback;
        private object? _state;

        internal ControlledTimeProvider(Exception? throwOnDispose = null) => _throwOnDispose = throwOnDispose;

        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        {
            _callback = callback;
            _state = state;
            return new ControlledTimer(_throwOnDispose);
        }

        internal Task FireAsync()
        {
            var callback = _callback ?? throw new InvalidOperationException("Timer was not armed.");
            var state = _state;
            return Task.Run(() => callback(state));
        }

        private sealed class ControlledTimer : ITimer
        {
            private readonly Exception? _throwOnDispose;

            internal ControlledTimer(Exception? throwOnDispose) => _throwOnDispose = throwOnDispose;

            public bool Change(TimeSpan dueTime, TimeSpan period) => true;

            public void Dispose()
            {
                if (_throwOnDispose is not null)
                {
                    throw _throwOnDispose;
                }
            }

            public ValueTask DisposeAsync()
            {
                Dispose();
                return ValueTask.CompletedTask;
            }
        }
    }
}
