using System.Runtime.CompilerServices;
using AnyInfer.Core;
using AnyInfer.Credentials;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Late factory-return cancellation and pool-adoption controls.</summary>
public sealed class LateFactoryCancellationTests
{
    [Fact]
    public async Task Cancelled_parent_supplier_discards_a_late_factory_result_before_pool_adoption()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var discarded = new RecordingAdapter();
        var retained = new RecordingAdapter();
        var calls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", async (_, _) =>
            {
                if (Interlocked.Increment(ref calls) == 1)
                {
                    entered.TrySetResult();
                    await release.Task;
                    return discarded;
                }

                return retained;
            })]);
        await using var pool = new ProviderPool([ProviderSettings.Of("fake")], registry, ResolverChain.CreateDefault());
        var resolved = pool.Materialize(pool.ResolveMetadata("fake:model"));
        using var parent = new CancellationTokenSource();
        using var effective = new CancellationTokenSource();

        var pending = pool.GetAdapterAsync(resolved, effective.Token, () => parent.IsCancellationRequested ? parent.Token : null).AsTask();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        parent.Cancel();
        Assert.False(effective.IsCancellationRequested);
        release.TrySetResult();

        var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(parent.Token, cancelled.CancellationToken);
        Assert.Equal(1, discarded.DisposeCalls);
        Assert.Equal(0, discarded.GenerateCalls);

        var fresh = await pool.GetAdapterAsync(resolved, CancellationToken.None);
        Assert.Same(retained, fresh);
        Assert.Equal(2, calls);
    }

    [Fact]
    public async Task Already_cancelled_raw_parent_stops_before_factory_while_effective_child_is_uncancelled()
    {
        var factoryCalls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) =>
            {
                Interlocked.Increment(ref factoryCalls);
                return ValueTask.FromResult<IProviderAdapter>(new RecordingAdapter());
            })]);
        await using var pool = new ProviderPool([ProviderSettings.Of("fake")], registry, ResolverChain.CreateDefault());
        var resolved = pool.Materialize(pool.ResolveMetadata("fake:model"));
        using var parent = new CancellationTokenSource();
        using var effective = new CancellationTokenSource();
        parent.Cancel();

        var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            pool.GetAdapterAsync(
                resolved,
                effective.Token,
                () => parent.Token,
                parent.Token).AsTask());

        Assert.Equal(parent.Token, cancelled.CancellationToken);
        Assert.False(effective.IsCancellationRequested);
        Assert.Equal(0, factoryCalls);
    }

    [Fact]
    public async Task Gate_wait_cancellation_uses_original_parent_without_disturbing_the_active_shared_build()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var shared = new RecordingAdapter();
        var calls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", async (_, _) =>
            {
                Interlocked.Increment(ref calls);
                entered.TrySetResult();
                await release.Task;
                return shared;
            })]);
        await using var pool = new ProviderPool([ProviderSettings.Of("fake")], registry, ResolverChain.CreateDefault());
        var resolved = pool.Materialize(pool.ResolveMetadata("fake:model"));

        var active = pool.GetAdapterAsync(resolved, CancellationToken.None).AsTask();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        using var originalParent = new CancellationTokenSource();
        using var queuedEffectiveChild = new CancellationTokenSource();
        var queued = pool.GetAdapterAsync(
            resolved,
            queuedEffectiveChild.Token,
            () => originalParent.IsCancellationRequested ? originalParent.Token : null,
            originalParent.Token).AsTask();
        originalParent.Cancel();
        Assert.False(queuedEffectiveChild.IsCancellationRequested);
        queuedEffectiveChild.Cancel();

        try
        {
            var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => queued);
            Assert.Equal(originalParent.Token, cancelled.CancellationToken);
            Assert.False(active.IsCompleted);
            Assert.Equal(1, calls);
        }
        finally
        {
            release.TrySetResult();
        }

        Assert.Same(shared, await active.WaitAsync(TimeSpan.FromSeconds(5)));
        Assert.Equal(1, calls);
    }

    [Fact]
    public async Task Iterator_cancellation_discards_held_factory_return_without_caching_it()
    {
        var fixture = new HeldFactory();
        await using var client = fixture.CreateClient();
        using var iterator = new CancellationTokenSource();
        var stream = client.StreamAsync("x", target: "fake:model");
        var pending = stream.CollectAsync(iterator.Token);
        await fixture.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        iterator.Cancel();
        fixture.Release.TrySetResult();

        var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(iterator.Token, cancelled.CancellationToken);
        Assert.Equal(1, fixture.Discarded.DisposeCalls);
        Assert.Equal(0, fixture.Discarded.GenerateCalls);
        Assert.Equal("ok", (await client.StreamAsync("fresh", target: "fake:model").CollectAsync()).Text);
        Assert.Equal(2, fixture.FactoryCalls);
    }

    [Fact]
    public async Task Active_enumerator_close_discards_held_factory_return_without_caching_it()
    {
        var fixture = new HeldFactory();
        await using var client = fixture.CreateClient();
        var stream = client.StreamAsync("x", target: "fake:model");
        var enumerator = stream.GetAsyncEnumerator();
        var moving = enumerator.MoveNextAsync().AsTask();
        await fixture.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        try
        {
            var closing = enumerator.DisposeAsync().AsTask();
            Assert.False(closing.IsCompleted);
            fixture.Release.TrySetResult();
            await closing.WaitAsync(TimeSpan.FromSeconds(5));
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => moving);
        }
        finally
        {
            fixture.Release.TrySetResult();
        }

        Assert.Equal(1, fixture.Discarded.DisposeCalls);
        Assert.Equal(0, fixture.Discarded.GenerateCalls);
        Assert.Equal("ok", (await client.StreamAsync("fresh", target: "fake:model").CollectAsync()).Text);
        Assert.Equal(2, fixture.FactoryCalls);
    }

    [Fact]
    public async Task Direct_stream_close_discards_held_factory_return_without_caching_it()
    {
        var fixture = new HeldFactory();
        await using var client = fixture.CreateClient();
        var stream = client.StreamAsync("x", target: "fake:model");
        var pending = stream.CollectAsync();
        await fixture.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var closing = stream.DisposeAsync().AsTask();
        fixture.Release.TrySetResult();

        await closing.WaitAsync(TimeSpan.FromSeconds(5));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(1, fixture.Discarded.DisposeCalls);
        Assert.Equal(0, fixture.Discarded.GenerateCalls);
        Assert.Equal("ok", (await client.StreamAsync("fresh", target: "fake:model").CollectAsync()).Text);
        Assert.Equal(2, fixture.FactoryCalls);
    }

    [Fact]
    public async Task Lease_close_request_is_selected_before_tokens_and_remains_an_owned_cancellation_after_caller_wins()
    {
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", new RecordingAdapter())]);
        using var caller = new CancellationTokenSource();
        using var iterator = new CancellationTokenSource();
        using var close = new CancellationTokenSource();
        using var unrelated = new CancellationTokenSource();
        var closeRequested = false;
        await using var stream = new AsyncStream(client, null, EmptyEvents, caller.Token);
        await using var lease = new AnyInfer.Internal.StreamOperationLease(
            stream,
            client,
            null,
            caller.Token,
            iterator.Token,
            close.Token,
            () => closeRequested);

        closeRequested = true;
        Assert.False(close.IsCancellationRequested);
        Assert.False(lease.Token.IsCancellationRequested);
        Assert.Equal(close.Token, lease.CancelledParentToken);
        var closeCancellation = new OperationCanceledException(close.Token);
        Assert.True(lease.IsOwnedParentCancellation(closeCancellation));
        Assert.False(lease.IsOwnedParentCancellation(new OperationCanceledException(unrelated.Token)));

        iterator.Cancel();
        Assert.Equal(iterator.Token, lease.CancelledParentToken);
        caller.Cancel();
        Assert.Equal(caller.Token, lease.CancelledParentToken);
        Assert.True(lease.IsOwnedParentCancellation(closeCancellation));
    }

    [Fact]
    public async Task Factory_originated_cancellation_preserves_its_exact_source_object_when_no_parent_won()
    {
        using var source = new CancellationTokenSource();
        var planted = new OperationCanceledException(source.Token);
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) => ValueTask.FromException<IProviderAdapter>(planted))]);
        await using var pool = new ProviderPool([ProviderSettings.Of("fake")], registry, ResolverChain.CreateDefault());
        var resolved = pool.Materialize(pool.ResolveMetadata("fake:model"));

        var escaped = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pool.GetAdapterAsync(resolved, CancellationToken.None).AsTask());
        Assert.Same(planted, escaped);
        Assert.Equal(source.Token, escaped.CancellationToken);
    }

    private sealed class HeldFactory
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal RecordingAdapter Discarded { get; } = new();
        private readonly RecordingAdapter _retained = new();
        internal int FactoryCalls;

        internal AsyncClient CreateClient()
        {
            var registry = new ProviderRegistry([
                new ProviderDescriptor("fake", "Fake", async (_, _) =>
                {
                    if (Interlocked.Increment(ref FactoryCalls) == 1)
                    {
                        Entered.TrySetResult();
                        await Release.Task;
                        return Discarded;
                    }

                    return _retained;
                })]);
            return new AsyncClient([ProviderSettings.Of("fake")], registry, route: new Route(["fake:model"]));
        }
    }

    private sealed class RecordingAdapter : IProviderAdapter
    {
        internal int GenerateCalls { get; private set; }
        internal int DisposeCalls { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            yield return new AdapterTextDelta("ok");
            await Task.Yield();
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private static async IAsyncEnumerable<StreamEvent> EmptyEvents([EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        await Task.CompletedTask;
        yield break;
    }
}
