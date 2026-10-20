using AnyInfer.Internal;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Independent controls for operation-neutral buffered deadline ownership.</summary>
public sealed class BufferedOperationDeadlineTests
{
    [Fact]
    public async Task Deadline_cancels_the_owned_token_and_joins_its_timer_before_sources_are_disposed()
    {
        var clock = new ControlledTimeProvider();
        using var lifecycle = new CancellationTokenSource();
        using var caller = new CancellationTokenSource();
        var scope = new BufferedOperationDeadlineScope(2, lifecycle.Token, caller.Token, clock);
        var observed = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var registration = scope.Token.Register(static state => ((TaskCompletionSource)state!).TrySetResult(), observed);

        clock.Fire();
        await observed.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(scope.IsExpired);
        Assert.True(scope.Token.IsCancellationRequested);

        await scope.DisposeAsync();

        Assert.True(clock.TimerDisposed);
    }

    [Fact]
    public void Arming_failure_preserves_the_original_exception_identity()
    {
        var failure = new InvalidOperationException("timer arming failure");
        using var lifecycle = new CancellationTokenSource();
        using var caller = new CancellationTokenSource();

        var observed = Assert.Throws<InvalidOperationException>(() =>
            _ = new BufferedOperationDeadlineScope(1, lifecycle.Token, caller.Token, new ThrowingTimeProvider(failure)));

        Assert.Same(failure, observed);
    }

    [Fact]
    public async Task Lifecycle_cancellation_is_not_reported_as_deadline_expiry()
    {
        var clock = new ControlledTimeProvider();
        using var lifecycle = new CancellationTokenSource();
        using var caller = new CancellationTokenSource();
        await using var scope = new BufferedOperationDeadlineScope(2, lifecycle.Token, caller.Token, clock);

        lifecycle.Cancel();

        Assert.True(scope.Token.IsCancellationRequested);
        Assert.False(scope.IsExpired);
        Assert.Null(scope.DeferredFailure);
    }

    [Fact]
    public async Task First_callback_failure_is_retained_while_disposal_still_releases_every_owned_resource()
    {
        var clock = new ControlledTimeProvider();
        using var lifecycle = new CancellationTokenSource();
        using var caller = new CancellationTokenSource();
        await using var scope = new BufferedOperationDeadlineScope(2, lifecycle.Token, caller.Token, clock);
        var first = new InvalidOperationException("first callback failure");
        using var firstRegistration = scope.Token.Register(static state => throw (Exception)state!, first);

        clock.Fire();

        Assert.NotNull(scope.DeferredFailure);
        await scope.DisposeAsync();
        Assert.True(clock.TimerDisposed);
    }

    [Fact]
    public async Task Dispose_waits_for_an_overlapping_timer_callback_before_releasing_its_linked_token()
    {
        var clock = new ControlledTimeProvider();
        using var lifecycle = new CancellationTokenSource();
        using var caller = new CancellationTokenSource();
        await using var scope = new BufferedOperationDeadlineScope(2, lifecycle.Token, caller.Token, clock);
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var readAfterRelease = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackEntries = new CallbackCounter();
        using var registration = scope.Token.UnsafeRegister(static state =>
        {
            var callback = ((TaskCompletionSource Entered, TaskCompletionSource Release, BufferedOperationDeadlineScope Scope,
                CallbackCounter Entries,
                TaskCompletionSource<Exception?> ReadAfterRelease))state!;
            Interlocked.Increment(ref callback.Entries.Value);
            callback.Entered.TrySetResult();
            callback.Release.Task.GetAwaiter().GetResult();
            callback.ReadAfterRelease.TrySetResult(Record.Exception(() => _ = callback.Scope.Token.IsCancellationRequested));
        }, (entered, release, scope, callbackEntries, readAfterRelease));

        var firing = clock.FireAsync();
        Task? disposing = null;
        try
        {
            await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            disposing = scope.DisposeAsync().AsTask();
            await Task.Yield();
            Assert.False(disposing.IsCompleted);

            release.TrySetResult();
            await Task.WhenAll(firing, disposing).WaitAsync(TimeSpan.FromSeconds(5));
            Assert.Null(await readAfterRelease.Task.WaitAsync(TimeSpan.FromSeconds(5)));
            clock.Fire();
            Assert.Equal(1, callbackEntries.Value);
        }
        finally
        {
            release.TrySetResult();
            await firing;
            if (disposing is not null)
            {
                await disposing;
            }
        }
    }

    [Fact]
    public async Task First_timer_callback_failure_wins_over_later_timer_disposal_failure()
    {
        var callbackFailure = new InvalidOperationException("callback failure");
        var disposalFailure = new InvalidOperationException("timer disposal failure");
        var clock = new ControlledTimeProvider(disposalFailure);
        using var lifecycle = new CancellationTokenSource();
        using var caller = new CancellationTokenSource();
        await using var scope = new BufferedOperationDeadlineScope(2, lifecycle.Token, caller.Token, clock);
        using var registration = scope.Token.UnsafeRegister(static state => throw (Exception)state!, callbackFailure);

        await clock.FireAsync().WaitAsync(TimeSpan.FromSeconds(5));

        var retained = Assert.IsType<AggregateException>(scope.DeferredFailure);
        Assert.Same(callbackFailure, Assert.Single(retained.Flatten().InnerExceptions));
        await scope.DisposeAsync();

        Assert.Same(retained, scope.DeferredFailure);
        Assert.Equal(1, clock.DisposeCalls);
        await scope.DisposeAsync();
        Assert.Equal(1, clock.DisposeCalls);
    }

    [Fact]
    public async Task Timer_callback_restores_captured_owner_and_original_caller_identity_without_flowing_ambient_context()
    {
        var clock = new ControlledTimeProvider();
        using var lifecycle = new CancellationTokenSource();
        using var caller = new CancellationTokenSource();
        await using var capturedAsyncOwner = new AsyncClient();
        using var capturedSyncOwner = new Client();
        await using var unrelatedAsyncOwner = new AsyncClient();
        using var unrelatedSyncOwner = new Client();
        BufferedOperationDeadlineScope scope;
        using (AsyncExecutionContext.Push(capturedAsyncOwner, capturedSyncOwner))
        using (SyncExecutionContext.Push(capturedSyncOwner))
        using (CancellationIdentityContext.Push(caller.Token, caller.Token))
        {
            scope = new BufferedOperationDeadlineScope(2, lifecycle.Token, caller.Token, clock);
        }

        var observed = new TaskCompletionSource<(AsyncClient? AsyncOwner, Client? SyncOwner, CancellationToken Caller)>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var guardFailures = new TaskCompletionSource<(Exception? AsyncFailure, Exception? SyncFailure)>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        using var registration = scope.Token.UnsafeRegister(static state =>
        {
            var callback = ((BufferedOperationDeadlineScope Scope,
                AsyncClient AsyncOwner,
                Client SyncOwner,
                TaskCompletionSource<(AsyncClient? AsyncOwner, Client? SyncOwner, CancellationToken Caller)> Observed,
                TaskCompletionSource<(Exception? AsyncFailure, Exception? SyncFailure)> GuardFailures))state!;
            callback.Observed.TrySetResult((
                AsyncExecutionContext.CurrentAsyncClient,
                SyncExecutionContext.CurrentClient,
                CancellationIdentityContext.Resolve(callback.Scope.Token)));
            callback.GuardFailures.TrySetResult((
                Record.Exception(() => callback.AsyncOwner.DisposeAsync().AsTask().GetAwaiter().GetResult()),
                Record.Exception(callback.SyncOwner.Dispose)));
        }, (scope, capturedAsyncOwner, capturedSyncOwner, observed, guardFailures));

        using (AsyncExecutionContext.Push(unrelatedAsyncOwner, unrelatedSyncOwner))
        using (SyncExecutionContext.Push(unrelatedSyncOwner))
        {
            Task firing;
            using (ExecutionContext.SuppressFlow())
            {
                firing = clock.FireAsync();
            }

            await firing.WaitAsync(TimeSpan.FromSeconds(5));
            var callback = await observed.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.Same(capturedAsyncOwner, callback.AsyncOwner);
            Assert.Same(capturedSyncOwner, callback.SyncOwner);
            Assert.Equal(caller.Token, callback.Caller);
            Assert.Same(unrelatedAsyncOwner, AsyncExecutionContext.CurrentAsyncClient);
            Assert.Same(unrelatedSyncOwner, SyncExecutionContext.CurrentClient);
            var guard = await guardFailures.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.IsType<InvalidOperationException>(guard.AsyncFailure);
            Assert.IsType<InvalidOperationException>(guard.SyncFailure);
        }

        await scope.DisposeAsync();
    }

    private sealed class ThrowingTimeProvider(Exception failure) : TimeProvider
    {
        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period) => throw failure;
    }

    private sealed class CallbackCounter
    {
        internal int Value;
    }

    private sealed class ControlledTimeProvider(Exception? disposeFailure = null) : TimeProvider
    {
        private readonly Exception? _disposeFailure = disposeFailure;
        private TimerCallback? _callback;
        private object? _state;

        internal bool TimerDisposed { get; private set; }

        internal int DisposeCalls { get; private set; }

        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        {
            _callback = callback;
            _state = state;
            return new ControlledTimer(this);
        }

        internal void Fire() => (_callback ?? throw new InvalidOperationException("Timer was not armed."))(_state);

        internal Task FireAsync() => Task.Run(Fire);

        private sealed class ControlledTimer(ControlledTimeProvider owner) : ITimer
        {
            public bool Change(TimeSpan dueTime, TimeSpan period) => true;
            public void Dispose()
            {
                owner.TimerDisposed = true;
                owner.DisposeCalls++;
                if (owner._disposeFailure is not null)
                {
                    throw owner._disposeFailure;
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
