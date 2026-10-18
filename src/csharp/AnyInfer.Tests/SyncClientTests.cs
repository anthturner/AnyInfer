using System.Runtime.CompilerServices;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public synchronous-facade lifetime, delivery, and failure-preservation controls.</summary>
public sealed class SyncClientTests
{
    [Fact]
    public void Stream_validates_a_missing_route_before_publishing_a_sync_stream()
    {
        using var client = Client.FromAdapters([new ProviderRegistration("fake", new ScriptAdapter((_, token) => Events(token, new AdapterFinal("stop"))))]);
        Assert.Throws<ConfigException>(() => client.Stream("no route or target"));
    }

    [Fact]
    public void Convenience_generate_and_stream_preserve_their_wire_stream_mode_and_explicit_request_mode()
    {
        var adapter = new ScriptAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop")));
        using var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);

        client.Generate("prompt", target: "fake:model");
        Assert.False(adapter.LastRequest!.Stream);
        client.Generate([Message.User("messages")], target: "fake:model");
        Assert.False(adapter.LastRequest!.Stream);
        using (var stream = client.Stream("stream", target: "fake:model"))
        {
            stream.Collect();
            Assert.True(adapter.LastRequest!.Stream);
        }

        client.Generate(new GenerationRequest([Message.User("explicit")], new Route(["fake:model"]), stream: true));
        Assert.True(adapter.LastRequest!.Stream);
    }

    [Fact]
    public async Task Result_is_not_ready_before_terminal_commit_and_stream_is_single_consumer()
    {
        var terminalHeld = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseTerminal = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var client = Client.FromAdapters([new ProviderRegistration("fake", new ScriptAdapter((_, token) => HeldTerminalEvents(token, terminalHeld, releaseTerminal)))]);
        using var stream = client.Stream("hello", target: "fake:model");
        Assert.Throws<InvalidOperationException>(() => _ = stream.Result);

        using var enumerator = stream.GetEnumerator();
        MoveThroughTimingPrefix(enumerator);
        Assert.IsType<TextDelta>(enumerator.Current);
        await terminalHeld.Task.WaitAsync(TimeSpan.FromSeconds(5));
        try
        {
            Assert.Throws<InvalidOperationException>(() => _ = stream.Result);
            Assert.Throws<InvalidOperationException>(() => stream.GetEnumerator());
        }
        finally
        {
            releaseTerminal.TrySetResult();
        }

        while (enumerator.MoveNext()) { }

        Assert.Equal("ok", stream.Result.Text);
        stream.Dispose();
        Assert.False(enumerator.MoveNext());
        Assert.Equal("ok", stream.Result.Text);
    }

    [Fact]
    public void Queued_prefix_then_original_failure_and_original_cancellation_reach_the_sync_consumer_unchanged()
    {
        var failure = new InvalidOperationException("original failure");
        using (var client = Client.FromAdapters([new ProviderRegistration("fake", new ScriptAdapter((_, token) => PrefixThenThrow(token, failure)))]))
        using (var stream = client.Stream("hello", target: "fake:model"))
        using (var enumerator = stream.GetEnumerator())
        {
            MoveThroughTimingPrefix(enumerator);
            Assert.Equal("prefix", Assert.IsType<TextDelta>(enumerator.Current).Text);
            var actual = Assert.Throws<InvalidOperationException>(() => enumerator.MoveNext());
            Assert.Same(failure, actual);
        }

        var cancellation = new OperationCanceledException("caller cancellation");
        using var cancelledClient = Client.FromAdapters([new ProviderRegistration("fake", new ScriptAdapter((_, token) => PrefixThenThrow(token, cancellation)))]);
        using var cancelled = cancelledClient.Stream("hello", target: "fake:model");
        using var cancelledEnumerator = cancelled.GetEnumerator();
        MoveThroughTimingPrefix(cancelledEnumerator);
        Assert.Same(cancellation, Assert.ThrowsAny<OperationCanceledException>(() => cancelledEnumerator.MoveNext()));
    }

    [Fact]
    public async Task Early_foreach_close_joins_actual_adapter_cleanup_and_the_client_remains_reusable()
    {
        var adapter = new BlockingThenSuccessfulAdapter();
        using var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);

        foreach (var item in client.Stream("first", target: "fake:model"))
        {
            if (item is TextDelta delta)
            {
                Assert.Equal("first", delta.Text);
                break;
            }
        }

        await adapter.Cleanup.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.Equal("reused", client.Generate("second", target: "fake:model").Text);
        Assert.Equal(2, adapter.GenerateCalls);
    }

    [Fact]
    public async Task Unconsumed_bounded_queue_is_cancelled_before_join_and_all_adapter_instances_close_once()
    {
        var adapter = new QueueFillingAdapter();
        using var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);
        var stream = client.Stream("queue", target: "fake:model");
        await adapter.BeforeBoundedWrite.Task.WaitAsync(TimeSpan.FromSeconds(2));

        stream.Dispose();
        await adapter.Cleanup.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.Equal(0, adapter.DisposeCalls);
        client.Dispose();
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Concurrent_sync_calls_overlap_on_the_owned_async_client()
    {
        var adapter = new ConcurrentAdapter(8);
        using var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);

        var calls = Enumerable.Range(0, 8)
            .Select(index => Task.Run(() => client.Generate($"request-{index}", target: "fake:model")))
            .ToArray();
        await adapter.AllEntered.Task.WaitAsync(TimeSpan.FromSeconds(2));
        adapter.Release.TrySetResult();

        var results = await Task.WhenAll(calls).WaitAsync(TimeSpan.FromSeconds(2));
        Assert.All(results, static result => Assert.Equal("ok", result.Text));
        Assert.Equal(8, adapter.GenerateCalls);
    }

    [Fact]
    public async Task Client_close_broadcasts_cancellation_to_every_stream_before_waiting_for_cleanup()
    {
        var adapter = new OrderedCloseAdapter();
        var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);
        using var first = client.Stream("first", target: "fake:model");
        using var second = client.Stream("second", target: "fake:model");
        await adapter.BothEntered.Task.WaitAsync(TimeSpan.FromSeconds(2));

        var close = Task.Run(client.Dispose);
        await adapter.SecondCancelled.Task.WaitAsync(TimeSpan.FromSeconds(2));
        await close.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.True(adapter.FirstCleanupObservedSecondCancellation);
    }

    [Fact]
    public async Task Client_close_finishes_every_stream_cleanup_when_one_cancellation_callback_throws()
    {
        var sentinel = new InvalidOperationException("cancellation callback sentinel");
        var failing = new CallbackFailureAdapter(sentinel);
        var other = new CallbackFailureAdapter();
        var client = Client.FromAdapters([
            new ProviderRegistration("first", failing),
            new ProviderRegistration("second", other),
        ]);
        var first = client.Stream("first", target: "first:model");
        var second = client.Stream("second", target: "second:model");
        await Task.WhenAll(failing.Entered.Task, other.Entered.Task).WaitAsync(TimeSpan.FromSeconds(2));

        var close = Task.Run(() => Assert.ThrowsAny<Exception>(client.Dispose));
        await Task.WhenAll(failing.Cleanup.Task, other.Cleanup.Task).WaitAsync(TimeSpan.FromSeconds(2));
        var actual = await close.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.True(ContainsException(actual, sentinel));
        Assert.Equal(1, failing.DisposeCalls);
        Assert.Equal(1, other.DisposeCalls);
        first.Dispose();
        second.Dispose();
    }

    [Fact]
    public async Task Unsafe_registered_stream_callback_cannot_dispose_its_own_client_during_stream_close()
    {
        Client? client = null;
        var adapter = new UnsafeDisposeCallbackAdapter(() => client!);
        client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);
        try
        {
            using (var stream = client.Stream("first", target: "fake:model"))
            {
                await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(2));
                stream.Dispose();
            }

            Assert.IsType<InvalidOperationException>(await adapter.CallbackResult.Task.WaitAsync(TimeSpan.FromSeconds(2)));
            await adapter.Cleanup.Task.WaitAsync(TimeSpan.FromSeconds(2));
            Assert.Equal("reused", client.Generate("second", target: "fake:model").Text);
        }
        finally
        {
            client.Dispose();
        }

        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Unsafe_registered_buffered_callback_cannot_dispose_its_own_client_during_parent_close()
    {
        Client? client = null;
        var adapter = new UnsafeDisposeCallbackAdapter(() => client!);
        client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);
        var generate = Task.Run(() => Assert.ThrowsAny<OperationCanceledException>(() => client.Generate("blocked", target: "fake:model")));
        await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(2));

        var close = Task.Run(client.Dispose);
        Assert.IsType<InvalidOperationException>(await adapter.CallbackResult.Task.WaitAsync(TimeSpan.FromSeconds(2)));
        await adapter.Cleanup.Task.WaitAsync(TimeSpan.FromSeconds(2));
        await generate.WaitAsync(TimeSpan.FromSeconds(2));
        await close.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Client_close_cancels_existing_streams_while_waiting_for_a_blocked_late_creation()
    {
        var adapter = new BlockingThenSuccessfulAdapter();
        var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);
        using var established = client.Stream("established", target: "fake:model");
        await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(2));

        var messages = new BlockingMessages();
        var creation = Task.Run(() => client.Stream(messages, target: "fake:model"));
        await messages.Entered.Task.WaitAsync(TimeSpan.FromSeconds(2));
        var close = Task.Run(client.Dispose);

        await adapter.Cleanup.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.False(close.IsCompleted);
        messages.Release.TrySetResult();

        await Assert.ThrowsAsync<ObjectDisposedException>(async () => await creation.WaitAsync(TimeSpan.FromSeconds(2)));
        await close.WaitAsync(TimeSpan.FromSeconds(2));
    }

    [Fact]
    public async Task Collect_cancellation_interrupts_a_blocked_public_stream_and_joins_iterator_cleanup()
    {
        var adapter = new BlockingThenSuccessfulAdapter();
        using var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);
        using var stream = client.Stream("blocked", target: "fake:model");
        using var cancellation = new CancellationTokenSource();
        var collect = Task.Run(() => Assert.ThrowsAny<OperationCanceledException>(() => stream.Collect(cancellation.Token)));
        await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(2));
        cancellation.Cancel();
        await adapter.Cleanup.Task.WaitAsync(TimeSpan.FromSeconds(2));
        var actual = await collect.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.Equal(cancellation.Token, actual.CancellationToken);
    }

    [Fact]
    public async Task Caller_cancellation_unblocks_a_full_stream_queue_after_delivering_queued_prefix()
    {
        var adapter = new QueueFillingAdapter();
        using var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]);
        using var cancellation = new CancellationTokenSource();
        using var stream = client.Stream("queue", target: "fake:model", cancellationToken: cancellation.Token);
        await adapter.BeforeBoundedWrite.Task.WaitAsync(TimeSpan.FromSeconds(2));
        cancellation.Cancel();
        await adapter.Cleanup.Task.WaitAsync(TimeSpan.FromSeconds(2));

        using var enumerator = stream.GetEnumerator();
        MoveThroughTimingPrefix(enumerator);
        Assert.IsType<TextDelta>(enumerator.Current);
        var actual = Assert.ThrowsAny<OperationCanceledException>(() =>
        {
            while (enumerator.MoveNext()) { }
        });
        Assert.Equal(cancellation.Token, actual.CancellationToken);
    }

    [Fact]
    public void Hostile_synchronization_context_does_not_capture_sync_client_awaiters()
    {
        var prior = SynchronizationContext.Current;
        SynchronizationContext.SetSynchronizationContext(new ThrowingSynchronizationContext());
        try
        {
            using var client = Client.FromAdapters([new ProviderRegistration("fake", new ScriptAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop"))))]);
            Assert.Equal("ok", client.Generate("hello", target: "fake:model").Text);
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(prior);
        }
    }

    [Fact]
    public async Task Foreach_consumer_body_may_close_normally_but_owned_callbacks_cannot_self_dispose()
    {
        var adapter = new BlockingThenSuccessfulAdapter();
        using (var client = Client.FromAdapters([new ProviderRegistration("fake", adapter)]))
        {
            foreach (var _ in client.Stream("close normally", target: "fake:model"))
            {
                client.Dispose();
                break;
            }

            await adapter.Cleanup.Task.WaitAsync(TimeSpan.FromSeconds(2));
        }

        Client? reentrant = null;
        var messages = new DisposeDuringEnumeration(() => reentrant!.Dispose());
        reentrant = Client.FromAdapters([new ProviderRegistration("fake", new ScriptAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop"))))]);
        try
        {
            Assert.Throws<InvalidOperationException>(() => reentrant.Stream(messages, target: "fake:model"));
            Assert.Equal("ok", reentrant.Generate("still open", target: "fake:model").Text);
        }
        finally
        {
            reentrant.Dispose();
        }

        Client? callbackClient = null;
        var callbackCount = 0;
        var callbackAdapter = new ScriptAdapter((_, token) =>
        {
            if (Interlocked.Increment(ref callbackCount) == 1)
            {
                callbackClient!.Dispose();
            }

            return Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop"));
        });
        callbackClient = Client.FromAdapters([new ProviderRegistration("fake", callbackAdapter)]);
        try
        {
            Assert.Throws<InvalidOperationException>(() => callbackClient.Generate("callback", target: "fake:model"));
            Assert.Equal("ok", callbackClient.Generate("still open", target: "fake:model").Text);
        }
        finally
        {
            callbackClient.Dispose();
        }
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

    private static async IAsyncEnumerable<AdapterEvent> HeldTerminalEvents(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource terminalHeld,
        TaskCompletionSource releaseTerminal)
    {
        yield return new AdapterTextDelta("ok");
        terminalHeld.TrySetResult();
        await releaseTerminal.Task.WaitAsync(token);
        token.ThrowIfCancellationRequested();
        yield return new AdapterFinal("stop");
    }

    private static void MoveThroughTimingPrefix(IEnumerator<StreamEvent> enumerator)
    {
        Assert.True(enumerator.MoveNext());
        Assert.Equal("attempt_start", Assert.IsType<TimingMark>(enumerator.Current).Name);
        Assert.True(enumerator.MoveNext());
        Assert.Equal("first_token", Assert.IsType<TimingMark>(enumerator.Current).Name);
        Assert.True(enumerator.MoveNext());
    }

    private static bool ContainsException(Exception exception, Exception expected) =>
        ReferenceEquals(exception, expected) ||
        exception is AggregateException aggregate && aggregate.InnerExceptions.Any(inner => ContainsException(inner, expected)) ||
        exception.InnerException is not null && ContainsException(exception.InnerException, expected);

    private static async IAsyncEnumerable<AdapterEvent> PrefixThenThrow([EnumeratorCancellation] CancellationToken token, Exception failure)
    {
        yield return new AdapterTextDelta("prefix");
        await Task.Yield();
        token.ThrowIfCancellationRequested();
        System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        yield break;
    }

    private sealed class ScriptAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        private int _calls;
        internal WireRequest? LastRequest { get; private set; }
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            LastRequest = request;
            return script(Interlocked.Increment(ref _calls), cancellationToken);
        }
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class BlockingThenSuccessfulAdapter : IProviderAdapter
    {
        private int _calls;
        internal TaskCompletionSource Cleanup { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int GenerateCalls => _calls;

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => Events(cancellationToken);

        private async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token)
        {
            if (Interlocked.Increment(ref _calls) == 2)
            {
                yield return new AdapterTextDelta("reused");
                yield return new AdapterFinal("stop");
                yield break;
            }

            try
            {
                yield return new AdapterTextDelta("first");
                Entered.TrySetResult();
                await Task.Delay(Timeout.InfiniteTimeSpan, token);
            }
            finally
            {
                Cleanup.TrySetResult();
            }
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class QueueFillingAdapter : IProviderAdapter
    {
        internal TaskCompletionSource BeforeBoundedWrite { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Cleanup { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int DisposeCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => Events(cancellationToken);

        private async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token)
        {
            try
            {
                for (var index = 0; index <= 256; index++)
                {
                    // The core emits attempt_start and first_token before adapter text.
                    // Index 254 is therefore the 257th public event and blocks the bounded writer.
                    if (index == 254)
                    {
                        BeforeBoundedWrite.TrySetResult();
                    }

                    yield return new AdapterTextDelta(index.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    await Task.Yield();
                    token.ThrowIfCancellationRequested();
                }
            }
            finally
            {
                Cleanup.TrySetResult();
            }
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class ConcurrentAdapter(int expectedCalls) : IProviderAdapter
    {
        private int _calls;
        internal TaskCompletionSource AllEntered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int GenerateCalls => _calls;

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => Events(cancellationToken);

        private async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token)
        {
            if (Interlocked.Increment(ref _calls) == expectedCalls)
            {
                AllEntered.TrySetResult();
            }

            await Release.Task.WaitAsync(token);
            yield return new AdapterTextDelta("ok");
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class OrderedCloseAdapter : IProviderAdapter
    {
        private int _calls;
        internal TaskCompletionSource BothEntered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource SecondCancelled { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool FirstCleanupObservedSecondCancellation { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => Events(cancellationToken);

        private async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token)
        {
            var ordinal = Interlocked.Increment(ref _calls);
            if (ordinal == 2)
            {
                BothEntered.TrySetResult();
            }

            try
            {
                yield return new AdapterTextDelta(ordinal.ToString(System.Globalization.CultureInfo.InvariantCulture));
                await Task.Delay(Timeout.InfiniteTimeSpan, token);
            }
            finally
            {
                if (ordinal == 2)
                {
                    SecondCancelled.TrySetResult();
                }
                else
                {
                    await SecondCancelled.Task;
                    FirstCleanupObservedSecondCancellation = true;
                }
            }
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class CallbackFailureAdapter(Exception? cancellationFailure = null) : IProviderAdapter
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Cleanup { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int DisposeCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => Events(cancellationToken);

        private async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token)
        {
            var failure = cancellationFailure;
            using var registration = failure is null
                ? default(CancellationTokenRegistration)
                : token.Register(() => System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw());
            Entered.TrySetResult();
            try
            {
                yield return new AdapterTextDelta("pending");
                await Task.Delay(Timeout.InfiniteTimeSpan, token);
            }
            finally
            {
                Cleanup.TrySetResult();
            }
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class UnsafeDisposeCallbackAdapter(Func<Client> owner) : IProviderAdapter
    {
        private int _calls;
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Cleanup { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource<Exception?> CallbackResult { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int DisposeCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) => Events(cancellationToken);

        private async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token)
        {
            if (Interlocked.Increment(ref _calls) != 1)
            {
                yield return new AdapterTextDelta("reused");
                yield return new AdapterFinal("stop");
                yield break;
            }

            using var registration = token.UnsafeRegister(
                static state =>
                {
                    var callbackState = (UnsafeCallbackState)state!;
                    callbackState.Adapter.CallbackResult.TrySetResult(RecordDispose(callbackState.Owner));
                },
                new UnsafeCallbackState(this, owner));
            Entered.TrySetResult();
            try
            {
                yield return new AdapterTextDelta("pending");
                await Task.Delay(Timeout.InfiniteTimeSpan, token);
            }
            finally
            {
                Cleanup.TrySetResult();
            }
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }

        private static Exception? RecordDispose(Func<Client> callbackOwner)
        {
            try
            {
                callbackOwner().Dispose();
                return null;
            }
            catch (Exception exception)
            {
                return exception;
            }
        }

        private sealed record UnsafeCallbackState(UnsafeDisposeCallbackAdapter Adapter, Func<Client> Owner);
    }

    private sealed class ThrowingSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback d, object? state) => throw new Xunit.Sdk.XunitException("The sync facade captured the caller synchronization context.");
    }

    private sealed class DisposeDuringEnumeration(Action dispose) : IEnumerable<Message>
    {
        public IEnumerator<Message> GetEnumerator()
        {
            dispose();
            yield return Message.User("callback");
        }

        System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();
    }

    private sealed class BlockingMessages : IEnumerable<Message>
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public IEnumerator<Message> GetEnumerator()
        {
            Entered.TrySetResult();
            Release.Task.GetAwaiter().GetResult();
            yield return Message.User("late");
        }

        System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
