using System.Runtime.CompilerServices;
using System.Runtime.ExceptionServices;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public lifecycle barriers for the bounded tool-loop operation.</summary>
public sealed class ToolLoopLifecycleTests
{
    [Fact]
    public async Task Caller_cancellation_inside_handler_preserves_parent_identity_and_stops_before_next_round()
    {
        var adapter = new ToolCallThenStopAdapter();
        var entered = Gate();
        var observed = new TaskCompletionSource<OperationCanceledException>(TaskCreationOptions.RunContinuationsAsynchronously);
        var tool = new Tool(Spec(), async (_, token) =>
        {
            entered.TrySetResult();
            try { await Task.Delay(Timeout.InfiniteTimeSpan, token); }
            catch (OperationCanceledException exception) { observed.TrySetResult(exception); throw; }
            return null;
        });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", adapter)]);
        using var caller = new CancellationTokenSource();
        var pending = client.RunToolsAsync(Request(), [tool], cancellationToken: caller.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(2));
        caller.Cancel();

        var escaped = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        var owned = await observed.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.Equal(caller.Token, escaped.CancellationToken);
        Assert.Same(owned, escaped.InnerException);
        Assert.Equal(1, adapter.Calls);
    }

    [Fact]
    public async Task Foreign_handler_cancellation_escapes_unchanged_after_caller_cancels()
    {
        var adapter = new ToolCallThenStopAdapter();
        var entered = Gate();
        var release = Gate();
        using var foreignSource = new CancellationTokenSource();
        var foreign = new OperationCanceledException("foreign", foreignSource.Token);
        var tool = new Tool(Spec(), async (_, _) =>
        {
            entered.TrySetResult();
            await release.Task;
            ExceptionDispatchInfo.Capture(foreign).Throw();
            return null;
        });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", adapter)]);
        using var caller = new CancellationTokenSource();
        var pending = client.RunToolsAsync(Request(), [tool], cancellationToken: caller.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(2));
        caller.Cancel();
        release.TrySetResult();

        var escaped = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Same(foreign, escaped);
        Assert.Equal(foreignSource.Token, escaped.CancellationToken);
        Assert.Equal(1, adapter.Calls);
    }

    [Fact]
    public async Task Dispose_async_cancels_handler_and_waits_for_whole_tool_operation()
    {
        var adapter = new ToolCallThenStopAdapter();
        var entered = Gate();
        var observed = Gate();
        var tool = new Tool(Spec(), async (_, token) =>
        {
            entered.TrySetResult();
            try { await Task.Delay(Timeout.InfiniteTimeSpan, token); }
            catch (OperationCanceledException) { observed.TrySetResult(); throw; }
            return null;
        });
        var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", adapter)]);
        var pending = client.RunToolsAsync(Request(), [tool]);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(2));

        var dispose = client.DisposeAsync().AsTask();
        await observed.Task.WaitAsync(TimeSpan.FromSeconds(2));
        await dispose.WaitAsync(TimeSpan.FromSeconds(2));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(1, adapter.Calls);
    }

    [Fact]
    public async Task Noncooperative_handler_holds_dispose_until_explicit_release_after_owned_cancellation()
    {
        var adapter = new ToolCallThenStopAdapter();
        var entered = Gate();
        var cancellationObserved = Gate();
        var release = Gate();
        var tool = new Tool(Spec(), async (_, token) =>
        {
            using var registration = token.Register(static state => ((TaskCompletionSource)state!).TrySetResult(), cancellationObserved);
            entered.TrySetResult();
            await release.Task;
            token.ThrowIfCancellationRequested();
            return null;
        });
        var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", adapter)]);
        var pending = client.RunToolsAsync(Request(), [tool]);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(2));

        var dispose = client.DisposeAsync().AsTask();
        await cancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.False(dispose.IsCompleted);
        release.TrySetResult();
        await dispose.WaitAsync(TimeSpan.FromSeconds(2));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(1, adapter.Calls);
    }

    [Fact]
    public async Task Async_and_sync_callback_self_disposal_become_tool_errors_and_external_disposal_remains_safe()
    {
        var asyncAdapter = new ToolCallThenStopAdapter();
        AsyncClient? asyncClient = null;
        var asyncTool = new Tool(Spec(), (_, _) =>
        {
            asyncClient!.DisposeAsync().AsTask().GetAwaiter().GetResult();
            return ValueTask.FromResult<object?>("unreachable");
        });
        asyncClient = AsyncClient.FromAdapters([new ProviderRegistration("fake", asyncAdapter)]);
        try
        {
            var asyncResult = await asyncClient.RunToolsAsync(Request(), [asyncTool]);
            Assert.Equal("done", asyncResult.Text);
            Assert.Equal(2, asyncAdapter.Calls);
            Assert.Contains(asyncAdapter.Requests[1].Messages.SelectMany(static message => message.Content), static part => part is ToolResult { IsError: true });
        }
        finally { await asyncClient.DisposeAsync(); }

        var syncAdapter = new ToolCallThenStopAdapter();
        Client? syncClient = null;
        var syncTool = new Tool(Spec(), (_, _) =>
        {
            syncClient!.Dispose();
            return ValueTask.FromResult<object?>("unreachable");
        });
        syncClient = Client.FromAdapters([new ProviderRegistration("fake", syncAdapter)]);
        try
        {
            var syncResult = syncClient.RunTools(Request(), [syncTool]);
            Assert.Equal("done", syncResult.Text);
            Assert.Equal(2, syncAdapter.Calls);
            Assert.Contains(syncAdapter.Requests[1].Messages.SelectMany(static message => message.Content), static part => part is ToolResult { IsError: true });
        }
        finally { syncClient.Dispose(); }
    }

    private static GenerationRequest Request() => new([Message.User("question")], new Route(["fake:model"]));
    private static ToolSpec Spec() => new("lookup", "", new AnyInfer.Json.JsonObject([]));
    private static TaskCompletionSource Gate() => new(TaskCreationOptions.RunContinuationsAsynchronously);

    private sealed class ToolCallThenStopAdapter : IProviderAdapter
    {
        private int _calls;
        internal int Calls => Volatile.Read(ref _calls);
        internal List<WireRequest> Requests { get; } = [];

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return Generate(Interlocked.Increment(ref _calls), cancellationToken);
        }

        private static async IAsyncEnumerable<AdapterEvent> Generate(int call, [EnumeratorCancellation] CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            if (call == 1)
            {
                yield return new AdapterToolCallDelta(0, "call-1", "lookup", "{}");
                yield return new AdapterFinal("tool_calls");
            }
            else
            {
                yield return new AdapterTextDelta("done");
                yield return new AdapterFinal("stop");
            }
            await Task.Yield();
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
