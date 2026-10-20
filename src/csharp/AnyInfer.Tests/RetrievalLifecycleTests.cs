using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Providers;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public lifecycle controls for buffered embedding and reranking calls.</summary>
public sealed class RetrievalLifecycleTests
{
    [Fact]
    public async Task Client_close_joins_a_held_embedding_body_before_disposing_the_adapter_once()
    {
        var adapter = new HeldRetrievalAdapter();
        var events = new CapturingObserver();
        await using var client = CreateClient(adapter, events);

        var pending = client.EmbedAsync("input", target: "retrieval:model");
        await adapter.EmbeddingEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var closing = client.DisposeAsync().AsTask();
        Assert.False(closing.IsCompleted);
        try
        {
            adapter.Release.TrySetResult();
            await adapter.CleanupEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.False(closing.IsCompleted);
            Assert.Equal(0, adapter.DisposeCalls);
            Assert.Contains(events.Events, static item => item is RequestStarted);
            adapter.CleanupRelease.TrySetResult();
            await closing.WaitAsync(TimeSpan.FromSeconds(5));
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            Assert.Equal(1, adapter.DisposeCalls);
            Assert.DoesNotContain(events.Events, static item => item is RequestCompleted or RequestFailed);
        }
        finally
        {
            adapter.Release.TrySetResult();
            adapter.CleanupRelease.TrySetResult();
            await ObserveAsync(pending);
            await ObserveAsync(closing);
        }
    }

    [Fact]
    public async Task Original_caller_cancellation_wins_over_a_held_rerank_body_without_success_publication()
    {
        var adapter = new HeldRetrievalAdapter();
        var events = new CapturingObserver();
        await using var client = CreateClient(adapter, events);
        using var caller = new CancellationTokenSource();

        var pending = client.RerankAsync("query", ["document"], target: "retrieval:model", cancellationToken: caller.Token);
        await adapter.RerankEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        try
        {
            caller.Cancel();
            await adapter.CleanupEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.Equal(0, adapter.DisposeCalls);
            adapter.CleanupRelease.TrySetResult();
            var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            Assert.Equal(caller.Token, failure.CancellationToken);
            Assert.DoesNotContain(events.Events, static item => item is RequestCompleted or RequestFailed);
        }
        finally
        {
            adapter.Release.TrySetResult();
            adapter.CleanupRelease.TrySetResult();
            await ObserveAsync(pending);
        }
    }

    [Fact]
    public void Sync_embedding_uses_the_same_declared_retrieval_adapter_path()
    {
        var adapter = new HeldRetrievalAdapter();
        adapter.Release.TrySetResult();
        adapter.CleanupRelease.TrySetResult();
        using var client = new Client(
            [ProviderSettings.Of("retrieval")],
            new ProviderRegistry([new ProviderDescriptor(
                "retrieval",
                "Retrieval",
                (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
                operations: [InferenceOperation.Embedding, InferenceOperation.Rerank],
                staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities> { ["model"] = new() })]));

        var result = client.Embed("input", target: "retrieval:model");

        Assert.Single(result.Vectors);
        Assert.Equal(1d, result.Vectors[0].Values.Single());
    }

    [Fact]
    public async Task Close_joins_a_held_factory_and_discards_its_late_retrieval_object_once()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cancellationObserved = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var late = new HeldRetrievalAdapter();
        var descriptor = new ProviderDescriptor("factory", "Factory", async (_, cancellationToken) =>
        {
            using var registration = cancellationToken.Register(() => cancellationObserved.TrySetResult());
            entered.TrySetResult();
            await release.Task;
            return late;
        }, operations: [InferenceOperation.Embedding, InferenceOperation.Rerank]);
        await using var client = new AsyncClient([ProviderSettings.Of("factory")], new ProviderRegistry([descriptor]));
        var pending = client.EmbedAsync("input", target: "factory:model");
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var closing = client.DisposeAsync().AsTask();
        try
        {
            Assert.False(closing.IsCompleted);
            await cancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.False(closing.IsCompleted);
            release.TrySetResult();
            await closing.WaitAsync(TimeSpan.FromSeconds(5));
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            Assert.Equal(1, late.DisposeCalls);
            Assert.False(late.EmbeddingEntered.Task.IsCompleted);
        }
        finally
        {
            late.Release.TrySetResult();
            late.CleanupRelease.TrySetResult();
            release.TrySetResult();
            await ObserveAsync(pending);
            await ObserveAsync(closing);
        }
    }

    [Fact]
    public async Task Unrelated_provider_cancellation_escapes_by_exact_identity_without_terminal_telemetry()
    {
        using var unrelated = new CancellationTokenSource();
        var planted = new OperationCanceledException(unrelated.Token);
        var adapter = new HeldRetrievalAdapter { EmbeddingFailure = planted };
        adapter.Release.TrySetResult();
        adapter.CleanupRelease.TrySetResult();
        var events = new CapturingObserver();
        await using var client = CreateClient(adapter, events);

        var observed = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => client.EmbedAsync("input", target: "retrieval:model"));

        Assert.Same(planted, observed);
        Assert.DoesNotContain(events.Events, static item => item is RequestCompleted or RequestFailed);
    }

    [Fact]
    public async Task Priced_held_embedding_cancellation_silently_abandons_ledger_reservation_and_metadata()
    {
        var adapter = new HeldRetrievalAdapter();
        var events = new CapturingObserver();
        var ledger = new SpendLedger();
        await using var client = CreatePricedEmbeddingClient(adapter, ledger, events);
        using var caller = new CancellationTokenSource();
        var request = new EmbeddingRequest(["input"], metadata: new Dictionary<string, string> { ["label"] = "cancelled" });
        var pending = client.EmbedAsync(request, target: "priced:model", cancellationToken: caller.Token);

        await adapter.EmbeddingEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var started = events.SingleStarted();
        try
        {
            Assert.True(ledger.Reserved().CompareTo(EDecimal.Zero) > 0);
            caller.Cancel();
            await adapter.CleanupEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            adapter.CleanupRelease.TrySetResult();
            var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            Assert.Equal(caller.Token, failure.CancellationToken);
            Assert.Equal(0, ledger.Reserved().CompareTo(EDecimal.Zero));
            Assert.Equal(0, ledger.Totals().Cost.CompareTo(EDecimal.Zero));
            Assert.DoesNotContain(events.Events, static item => item is RequestCompleted or RequestFailed);
            ledger.Record(new ResolvedTarget("priced", "model"), new Usage(InputTokens: 1), started.RequestId);
            Assert.Empty(ledger.ByLabel("label"));
        }
        finally
        {
            adapter.Release.TrySetResult();
            adapter.CleanupRelease.TrySetResult();
            await ObserveAsync(pending);
        }
    }

    [Fact]
    public async Task Post_acquire_embedding_operation_refusal_silently_abandons_ledger_reservation_and_metadata()
    {
        var adapter = new RerankOnlyAdapter();
        var events = new CapturingObserver();
        var ledger = new SpendLedger();
        await using var client = CreatePostAcquireConfigClient(adapter, ledger, events);
        var request = new EmbeddingRequest(["input"], metadata: new Dictionary<string, string> { ["label"] = "config" });
        var pending = client.EmbedAsync(request, target: "config:model");

        await adapter.FactoryEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var started = events.SingleStarted();
        Exception? primary = null;
        try
        {
            Assert.True(ledger.Reserved().CompareTo(EDecimal.Zero) > 0);
            adapter.FactoryRelease.TrySetResult();
            await Assert.ThrowsAsync<ConfigException>(() => pending);
            Assert.Equal(0, adapter.RerankCalls);
            Assert.Equal(0, ledger.Reserved().CompareTo(EDecimal.Zero));
            Assert.Equal(0, ledger.Totals().Cost.CompareTo(EDecimal.Zero));
            Assert.DoesNotContain(events.Events, static item => item is RequestCompleted or RequestFailed);
            ledger.Record(new ResolvedTarget("config", "model"), new Usage(InputTokens: 1), started.RequestId);
            Assert.Empty(ledger.ByLabel("label"));
        }
        catch (Exception exception)
        {
            primary = exception;
            throw;
        }
        finally
        {
            adapter.FactoryRelease.TrySetResult();
            try
            {
                await pending.WaitAsync(TimeSpan.FromSeconds(5));
            }
            catch (ConfigException) { }
            catch (OperationCanceledException) { }
            catch (Exception) when (primary is not null) { }
        }
    }

    private static AsyncClient CreateClient(HeldRetrievalAdapter adapter, IObserver? observer = null)
    {
        var descriptor = new ProviderDescriptor(
            "retrieval",
            "Retrieval",
            (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            operations: [InferenceOperation.Embedding, InferenceOperation.Rerank],
            staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities> { ["model"] = new() });
        return new AsyncClient([ProviderSettings.Of("retrieval")], new ProviderRegistry([descriptor]), observers: observer is null ? null : [observer]);
    }

    private static AsyncClient CreatePricedEmbeddingClient(HeldRetrievalAdapter adapter, SpendLedger ledger, IObserver observer)
    {
        var capabilities = PricedEmbeddingCapabilities();
        var descriptor = new ProviderDescriptor(
            "priced",
            "Priced",
            (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            operations: [InferenceOperation.Embedding],
            staticCapabilities: new Dictionary<string, ModelCapabilities> { ["model"] = capabilities },
            staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities> { ["model"] = new() });
        return new AsyncClient(
            [ProviderSettings.Of("priced")],
            new ProviderRegistry([descriptor]),
            estimator: new FixedEstimator(),
            ledger: ledger,
            spendPolicy: new SpendPolicy(maxTotalUsd: EDecimal.One, onUnknown: "allow"),
            observers: [observer]);
    }

    private static AsyncClient CreatePostAcquireConfigClient(RerankOnlyAdapter adapter, SpendLedger ledger, IObserver observer)
    {
        var descriptor = new ProviderDescriptor(
            "config",
            "Config",
            async (_, _) =>
            {
                adapter.FactoryEntered.TrySetResult();
                await adapter.FactoryRelease.Task.ConfigureAwait(false);
                return adapter;
            },
            operations: [InferenceOperation.Rerank],
            staticCapabilities: new Dictionary<string, ModelCapabilities> { ["model"] = PricedEmbeddingCapabilities() },
            staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities> { ["model"] = new() });
        return new AsyncClient(
            [ProviderSettings.Of("config")],
            new ProviderRegistry([descriptor]),
            estimator: new FixedEstimator(),
            ledger: ledger,
            spendPolicy: new SpendPolicy(maxTotalUsd: EDecimal.One, onUnknown: "allow"),
            observers: [observer]);
    }

    private static ModelCapabilities PricedEmbeddingCapabilities() => new(
        pricing: new Sourced<Pricing>(new Pricing(EDecimal.One, EDecimal.Zero), Provenance.Catalog),
        embedding: new EmbeddingCapabilities());

    private sealed class HeldRetrievalAdapter : IEmbedsText, IReranksText, IAsyncDisposable
    {
        internal TaskCompletionSource EmbeddingEntered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource RerankEntered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource CleanupEntered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource CleanupRelease { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int DisposeCalls { get; private set; }
        internal Exception? EmbeddingFailure { get; init; }

        public async ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
        {
            EmbeddingEntered.TrySetResult();
            try
            {
                await Release.Task.WaitAsync(cancellationToken);
                cancellationToken.ThrowIfCancellationRequested();
                if (EmbeddingFailure is not null) throw EmbeddingFailure;
                return new EmbeddingWireResult(request.Inputs.Select(static _ => new[] { 1d }), request.Model);
            }
            finally
            {
                CleanupEntered.TrySetResult();
                await CleanupRelease.Task.ConfigureAwait(false);
            }
        }

        public async ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default)
        {
            RerankEntered.TrySetResult();
            try
            {
                await Release.Task.WaitAsync(cancellationToken);
                cancellationToken.ThrowIfCancellationRequested();
                return new RerankWireResult(request.Documents.Select(static document => new WireRankedItem(document.Index, 1d)), request.Model);
            }
            finally
            {
                CleanupEntered.TrySetResult();
                await CleanupRelease.Task.ConfigureAwait(false);
            }
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class RerankOnlyAdapter : IReranksText, IAsyncDisposable
    {
        internal TaskCompletionSource FactoryEntered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource FactoryRelease { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int RerankCalls { get; private set; }

        public ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default)
        {
            RerankCalls++;
            return ValueTask.FromResult(new RerankWireResult(request.Documents.Select(static document => new WireRankedItem(document.Index, 1d)), request.Model));
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class FixedEstimator : ITokenEstimator
    {
        public TokenEstimate Estimate(string text) => new(1, 1);
    }

    private sealed class CapturingObserver : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);

        internal RequestStarted SingleStarted() => Assert.IsType<RequestStarted>(Assert.Single(Events.OfType<RequestStarted>()));
    }

    private static async Task ObserveAsync(Task task)
    {
        try { await task.WaitAsync(TimeSpan.FromSeconds(5)); }
        catch (OperationCanceledException) { }
    }
}
