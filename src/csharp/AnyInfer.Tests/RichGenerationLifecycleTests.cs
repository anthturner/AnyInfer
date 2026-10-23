using System.Runtime.CompilerServices;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public close and cancellation barriers after rich nonterminal events.</summary>
public sealed class RichGenerationLifecycleTests
{
    [Fact]
    public async Task Early_close_after_reasoning_closes_adapter_iterator_and_never_publishes_terminal_result()
    {
        var adapter = new BarrierAdapter();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("rich", adapter)]);
        var stream = client.StreamAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"])));
        await using var enumerator = stream.GetAsyncEnumerator();

        Assert.True(await enumerator.MoveNextAsync());
        Assert.Equal("attempt_start", Assert.IsType<TimingMark>(enumerator.Current).Name);
        Assert.True(await enumerator.MoveNextAsync());
        Assert.Equal("first_token", Assert.IsType<TimingMark>(enumerator.Current).Name);
        Assert.True(await enumerator.MoveNextAsync());
        Assert.Equal("thinking", Assert.IsType<ReasoningDelta>(enumerator.Current).Text);
        var enteredAdvance = enumerator.MoveNextAsync().AsTask();
        await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(1));

        await stream.DisposeAsync();
        try { await enteredAdvance; } catch (OperationCanceledException) { }
        await adapter.Finally.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.Throws<InvalidOperationException>(() => _ = stream.Result);
        Assert.False(adapter.TerminalPublished);
    }

    [Fact]
    public async Task Caller_cancellation_after_citation_preserves_original_identity_and_closes_iterator()
    {
        var adapter = new BarrierAdapter(citationFirst: true);
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("rich", adapter)]);
        using var caller = new CancellationTokenSource();
        var stream = client.StreamAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"])), caller.Token);
        await using var enumerator = stream.GetAsyncEnumerator(caller.Token);

        Assert.True(await enumerator.MoveNextAsync());
        Assert.Equal("attempt_start", Assert.IsType<TimingMark>(enumerator.Current).Name);
        Assert.True(await enumerator.MoveNextAsync());
        Assert.IsType<CitationDelta>(enumerator.Current);
        var pending = enumerator.MoveNextAsync().AsTask();
        await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        caller.Cancel();
        var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);

        Assert.Equal(caller.Token, cancelled.CancellationToken);
        Assert.NotNull(adapter.ObservedCancellation);
        Assert.Same(adapter.ObservedCancellation, cancelled.InnerException);
        await adapter.Finally.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.False(adapter.TerminalPublished);
    }

    [Fact]
    public async Task Iterator_cancellation_token_is_the_parent_identity_when_stream_has_no_call_token()
    {
        var adapter = new BarrierAdapter(citationFirst: true);
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("rich", adapter)]);
        using var iteratorParent = new CancellationTokenSource();
        var stream = client.StreamAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"])));
        await using var enumerator = stream.GetAsyncEnumerator(iteratorParent.Token);

        Assert.True(await enumerator.MoveNextAsync());
        Assert.Equal("attempt_start", Assert.IsType<TimingMark>(enumerator.Current).Name);
        Assert.True(await enumerator.MoveNextAsync());
        Assert.IsType<CitationDelta>(enumerator.Current);
        var pending = enumerator.MoveNextAsync().AsTask();
        await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        iteratorParent.Cancel();

        var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(iteratorParent.Token, cancelled.CancellationToken);
        Assert.NotNull(adapter.ObservedCancellation);
        Assert.Same(adapter.ObservedCancellation, cancelled.InnerException);
        await adapter.Finally.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.False(adapter.TerminalPublished);
    }

    [Fact]
    public async Task Foreign_cancellation_exception_is_not_rewritten_after_parent_cancellation()
    {
        var adapter = new ForeignCancellationAdapter();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("rich", adapter)]);
        using var caller = new CancellationTokenSource();
        var stream = client.StreamAsync(new GenerationRequest([Message.User("question")], new Route(["rich:model"])), caller.Token);
        await using var enumerator = stream.GetAsyncEnumerator(caller.Token);

        Assert.True(await enumerator.MoveNextAsync());
        Assert.Equal("attempt_start", Assert.IsType<TimingMark>(enumerator.Current).Name);
        Assert.True(await enumerator.MoveNextAsync());
        Assert.IsType<CitationDelta>(enumerator.Current);
        var pending = enumerator.MoveNextAsync().AsTask();
        await adapter.Entered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        caller.Cancel();
        adapter.Release.TrySetResult();

        var escaped = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Same(adapter.Planted, escaped);
        Assert.Equal(adapter.ForeignToken, escaped.CancellationToken);
        await adapter.Finally.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.False(adapter.TerminalPublished);
    }

    private sealed class BarrierAdapter(bool citationFirst = false) : IProviderAdapter
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Finally { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal OperationCanceledException? ObservedCancellation { get; private set; }
        internal bool TerminalPublished { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            Generate(cancellationToken);

        private async IAsyncEnumerable<AdapterEvent> Generate([EnumeratorCancellation] CancellationToken token)
        {
            try
            {
                if (citationFirst)
                {
                    yield return new AdapterCitationDelta(new Citation(0, 1, "source"));
                }
                else
                {
                    yield return new AdapterReasoningDelta("thinking");
                }
                Entered.TrySetResult();
                try
                {
                    await Task.Delay(Timeout.InfiniteTimeSpan, token);
                }
                catch (OperationCanceledException exception)
                {
                    ObservedCancellation = exception;
                    throw;
                }
                TerminalPublished = true;
                yield return new AdapterFinal("stop");
            }
            finally
            {
                Finally.TrySetResult();
            }
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class ForeignCancellationAdapter : IProviderAdapter
    {
        private readonly CancellationTokenSource _foreign = new();
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Finally { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal OperationCanceledException Planted { get; }
        internal CancellationToken ForeignToken => _foreign.Token;
        internal bool TerminalPublished { get; private set; }

        internal ForeignCancellationAdapter() => Planted = new OperationCanceledException(_foreign.Token);

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            Generate();

        private async IAsyncEnumerable<AdapterEvent> Generate()
        {
            try
            {
                yield return new AdapterCitationDelta(new Citation(0, 1, "source"));
                Entered.TrySetResult();
                await Release.Task;
                throw Planted;
            }
            finally
            {
                Finally.TrySetResult();
            }
        }

        public ValueTask DisposeAsync()
        {
            _foreign.Dispose();
            return ValueTask.CompletedTask;
        }
    }
}
