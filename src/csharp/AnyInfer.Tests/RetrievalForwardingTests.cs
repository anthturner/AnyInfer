using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public retrieval response-cap forwarding and timing-projection controls.</summary>
public sealed class RetrievalForwardingTests
{
    [Fact]
    public async Task Async_and_sync_defaults_forward_public_response_caps_to_retrieval_wires()
    {
        var asynchronous = new RecordingRetrievalAdapter();
        await using (var client = CreateAsyncClient(asynchronous))
        {
            await client.EmbedAsync("embedding", target: "alpha:model");
            await client.RerankAsync("query", ["document"], target: "alpha:model");
        }

        var synchronous = new RecordingRetrievalAdapter();
        using (var client = CreateClient(synchronous))
        {
            _ = client.Embed("embedding", target: "alpha:model");
            _ = client.Rerank("query", ["document"], target: "alpha:model");
        }

        Assert.Equal(64 * 1024 * 1024, asynchronous.EmbeddingRequests.Single().MaxResponseBytes);
        Assert.Equal(8 * 1024 * 1024, asynchronous.RerankRequests.Single().MaxResponseBytes);
        Assert.Equal(64 * 1024 * 1024, synchronous.EmbeddingRequests.Single().MaxResponseBytes);
        Assert.Equal(8 * 1024 * 1024, synchronous.RerankRequests.Single().MaxResponseBytes);
    }

    [Fact]
    public async Task Supplied_requests_and_convenience_overrides_forward_caps_above_the_wire_default_exactly()
    {
        const int suppliedEmbeddingCap = 2 * 1024 * 1024 + 17;
        const int suppliedRerankCap = 3 * 1024 * 1024 + 19;
        const int asyncConvenienceEmbeddingCap = 4 * 1024 * 1024 + 23;
        const int asyncConvenienceRerankCap = 5 * 1024 * 1024 + 29;
        const int syncSuppliedEmbeddingCap = 6 * 1024 * 1024 + 31;
        const int syncSuppliedRerankCap = 7 * 1024 * 1024 + 37;
        const int syncConvenienceEmbeddingCap = 8 * 1024 * 1024 + 41;
        const int syncConvenienceRerankCap = 9 * 1024 * 1024 + 43;
        var asynchronous = new RecordingRetrievalAdapter();
        await using (var client = CreateAsyncClient(asynchronous))
        {
            await client.EmbedAsync(
                new EmbeddingRequest(["supplied"], maxResponseBytes: suppliedEmbeddingCap),
                target: "alpha:model");
            await client.RerankAsync(
                new RerankRequest("query", [new RerankDocument("0", "supplied")], maxResponseBytes: suppliedRerankCap),
                target: "alpha:model");
        }

        var asyncConvenience = new RecordingRetrievalAdapter();
        await using (var client = CreateAsyncClient(asyncConvenience))
        {
            await client.EmbedAsync("convenience", target: "alpha:model", maxResponseBytes: asyncConvenienceEmbeddingCap);
            await client.RerankAsync("query", ["convenience"], target: "alpha:model", maxResponseBytes: asyncConvenienceRerankCap);
        }

        var syncSupplied = new RecordingRetrievalAdapter();
        using (var client = CreateClient(syncSupplied))
        {
            _ = client.Embed(
                new EmbeddingRequest(["supplied"], maxResponseBytes: syncSuppliedEmbeddingCap),
                target: "alpha:model");
            _ = client.Rerank(
                new RerankRequest("query", [new RerankDocument("0", "supplied")], maxResponseBytes: syncSuppliedRerankCap),
                target: "alpha:model");
        }

        var syncConvenience = new RecordingRetrievalAdapter();
        using (var client = CreateClient(syncConvenience))
        {
            _ = client.Embed("convenience", target: "alpha:model", maxResponseBytes: syncConvenienceEmbeddingCap);
            _ = client.Rerank("query", ["convenience"], target: "alpha:model", maxResponseBytes: syncConvenienceRerankCap);
        }

        Assert.Equal(suppliedEmbeddingCap, asynchronous.EmbeddingRequests.Single().MaxResponseBytes);
        Assert.Equal(suppliedRerankCap, asynchronous.RerankRequests.Single().MaxResponseBytes);
        Assert.Equal(asyncConvenienceEmbeddingCap, asyncConvenience.EmbeddingRequests.Single().MaxResponseBytes);
        Assert.Equal(asyncConvenienceRerankCap, asyncConvenience.RerankRequests.Single().MaxResponseBytes);
        Assert.Equal(syncSuppliedEmbeddingCap, syncSupplied.EmbeddingRequests.Single().MaxResponseBytes);
        Assert.Equal(syncSuppliedRerankCap, syncSupplied.RerankRequests.Single().MaxResponseBytes);
        Assert.Equal(syncConvenienceEmbeddingCap, syncConvenience.EmbeddingRequests.Single().MaxResponseBytes);
        Assert.Equal(syncConvenienceRerankCap, syncConvenience.RerankRequests.Single().MaxResponseBytes);
    }

    [Fact]
    public async Task Embedding_wire_phases_flow_to_success_attempt_events_result_and_manifest()
    {
        var phases = new Dictionary<string, double> { ["load"] = 12.5, ["fwd"] = 3d };
        var adapter = new RecordingRetrievalAdapter
        {
            Embed = request => new EmbeddingWireResult([[1d]], request.Model, phases: phases),
        };
        var observer = new RecordingObserver();
        await using var client = CreateAsyncClient(adapter, observer);

        var result = await client.EmbedAsync("phase", target: "alpha:model", manifest: true);

        AssertPhases(phases, result.Attempts.Single().Timing!.Phases);
        AssertPhases(phases, result.Timing.Phases);
        AssertPhases(phases, Assert.Single(observer.Events.OfType<AttemptCompleted>()).Timing.Phases);
        AssertPhases(phases, Assert.Single(observer.Events.OfType<RequestCompleted>()).Timing.Phases);
        AssertPhases(phases, Assert.IsType<AnyInfer.Manifest.RunManifest>(result.Manifest).Timing.Phases);
    }

    [Fact]
    public async Task Split_embedding_retains_per_chunk_phases_but_keeps_aggregate_and_manifest_phases_empty()
    {
        var adapter = new RecordingRetrievalAdapter
        {
            Embed = request => new EmbeddingWireResult(
                request.Inputs.Select(static _ => new[] { 1d }),
                request.Model,
                phases: new Dictionary<string, double> { [request.Inputs.Single()] = 1d }),
        };
        var observer = new RecordingObserver();
        await using var client = CreateAsyncClient(adapter, observer, embeddingLimit: 1);

        var result = await client.EmbedAsync(
            ["first", "second"],
            target: "alpha:model",
            batch: new BatchPolicy(maxConcurrency: 1),
            manifest: true);

        Assert.Equal(2, result.Attempts.Count);
        Assert.Equal("first", Assert.Single(result.Attempts[0].Timing!.Phases).Key);
        Assert.Equal("second", Assert.Single(result.Attempts[1].Timing!.Phases).Key);
        Assert.Empty(result.Timing.Phases);
        Assert.Empty(Assert.IsType<AnyInfer.Manifest.RunManifest>(result.Manifest).Timing.Phases);
        Assert.All(observer.Events.OfType<AttemptCompleted>(), static item => Assert.Single(item.Timing.Phases));
        Assert.Empty(Assert.Single(observer.Events.OfType<RequestCompleted>()).Timing.Phases);
    }

    [Fact]
    public async Task Rerank_has_no_provider_phase_input_and_keeps_all_retrieval_timings_empty()
    {
        var adapter = new RecordingRetrievalAdapter();
        var observer = new RecordingObserver();
        await using var client = CreateAsyncClient(adapter, observer);

        var result = await client.RerankAsync("query", ["document"], target: "alpha:model", manifest: true);

        Assert.Empty(result.Attempts.Single().Timing!.Phases);
        Assert.Empty(result.Timing.Phases);
        Assert.Empty(Assert.Single(observer.Events.OfType<AttemptCompleted>()).Timing.Phases);
        Assert.Empty(Assert.Single(observer.Events.OfType<RequestCompleted>()).Timing.Phases);
        Assert.Empty(Assert.IsType<AnyInfer.Manifest.RunManifest>(result.Manifest).Timing.Phases);
    }

    [Fact]
    public async Task Retry_manifest_preserves_the_bounded_attempt_snapshot_detail()
    {
        var calls = 0;
        var adapter = new RecordingRetrievalAdapter
        {
            Embed = request => ++calls == 1
                ? throw new ProviderUnavailableException("literal failure", provider: "alpha")
                : new EmbeddingWireResult([[1d]], request.Model),
        };
        await using var client = CreateAsyncClient(adapter);

        var result = await client.EmbedAsync(
            "retry",
            route: new Route(["alpha:model"], retry: new Retry(MaxAttempts: 2, BackoffBaseS: 0)),
            manifest: true);

        var failure = result.Attempts.First(static attempt => attempt.Outcome == "retried").Error;
        var detail = Assert.IsType<ProviderUnavailableException>(failure).Snapshot().Detail;
        var manifest = Assert.IsType<AnyInfer.Manifest.RunManifest>(result.Manifest);
        var failedRoute = Assert.Single(manifest.Route.Considered, static item => item.Outcome == "retried");
        var failedAttempt = Assert.Single(manifest.Attempts, static item => item.Outcome == "retried");

        Assert.Equal("literal failure", detail);
        Assert.Equal(detail, failedRoute.Reason);
        Assert.NotNull(failedAttempt.Error);
        Assert.Equal(detail, failedAttempt.Error!.Detail);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Unsplit_terminal_retrieval_failure_keeps_aggregate_provider_empty_and_emits_provider_snapshot(bool embedding)
    {
        var providerFailure = new ProviderUnavailableException(
            "literal failure",
            provider: "alpha",
            detail: "literal detail");
        var adapter = new RecordingRetrievalAdapter
        {
            Embed = _ => throw providerFailure,
            Rerank = _ => throw providerFailure,
        };
        var observer = new RecordingObserver();
        await using var client = CreateAsyncClient(adapter, observer);
        var route = new Route(["alpha:model"], retry: new Retry(MaxAttempts: 1, BackoffBaseS: 0));

        var failure = embedding
            ? await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.EmbedAsync("input", route: route))
            : await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.RerankAsync("query", ["document"], route: route));

        Assert.Null(failure.Provider);
        Assert.Empty(failure.BatchFailures);
        var attempt = Assert.Single(failure.Attempts);
        Assert.Equal("failed", attempt.Outcome);
        Assert.Same(providerFailure, attempt.Error);
        var requestFailure = Assert.Single(observer.Events.OfType<RequestFailed>());
        Assert.Equal("alpha", requestFailure.Error.Provider);
        Assert.Equal("literal detail", requestFailure.Error.Detail);
        Assert.Empty(observer.Events.OfType<RequestCompleted>());
    }
    private static void AssertPhases(
        IReadOnlyDictionary<string, double> expected,
        IReadOnlyDictionary<string, double> actual)
    {
        Assert.Equal(expected.Count, actual.Count);
        foreach (var (name, value) in expected)
        {
            Assert.True(actual.TryGetValue(name, out var observed));
            Assert.Equal(value, observed);
        }
    }

    private static AsyncClient CreateAsyncClient(
        RecordingRetrievalAdapter adapter,
        RecordingObserver? observer = null,
        int? embeddingLimit = null) =>
        new(
            [ProviderSettings.Of("alpha")],
            Registry(adapter, embeddingLimit),
            observers: observer is null ? null : [observer]);

    private static Client CreateClient(RecordingRetrievalAdapter adapter) =>
        new([ProviderSettings.Of("alpha")], Registry(adapter));

    private static ProviderRegistry Registry(RecordingRetrievalAdapter adapter, int? embeddingLimit = null) =>
        new([
            new ProviderDescriptor(
                "alpha",
                "Alpha",
                (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
                operations: [InferenceOperation.Embedding, InferenceOperation.Rerank],
                staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities>
                {
                    ["model"] = new(dimensions: 1, maxBatchInputs: embeddingLimit),
                },
                staticRerankCapabilities: new Dictionary<string, RerankCapabilities>
                {
                    ["model"] = new(nativeTopN: true),
                }),
        ]);

    private sealed class RecordingRetrievalAdapter : IEmbedsText, IReranksText, IAsyncDisposable
    {
        internal List<EmbeddingWireRequest> EmbeddingRequests { get; } = [];
        internal List<RerankWireRequest> RerankRequests { get; } = [];
        internal Func<EmbeddingWireRequest, EmbeddingWireResult>? Embed { get; init; }
        internal Func<RerankWireRequest, RerankWireResult>? Rerank { get; init; }

        public ValueTask<EmbeddingWireResult> EmbedAsync(
            EmbeddingWireRequest request,
            CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            EmbeddingRequests.Add(request);
            return ValueTask.FromResult(Embed?.Invoke(request) ?? new EmbeddingWireResult(
                request.Inputs.Select(static _ => new[] { 1d }), request.Model));
        }

        public ValueTask<RerankWireResult> RerankAsync(
            RerankWireRequest request,
            CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            RerankRequests.Add(request);
            return ValueTask.FromResult(Rerank?.Invoke(request) ?? new RerankWireResult(
                request.Documents.Select(static item => new WireRankedItem(item.Index, 1d)), request.Model));
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class RecordingObserver : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent value) => Events.Add(value);
    }
}
