using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public single-operation retrieval dispatch controls.</summary>
public sealed class RetrievalDispatchTests
{
    [Fact]
    public async Task Embed_convenience_overloads_preserve_scalar_sequence_and_duplicate_input_order()
    {
        var adapter = new RecordingRetrievalAdapter();
        await using var client = Client(adapter, operations: [InferenceOperation.Embedding]);

        var scalar = await client.EmbedAsync("one", target: "alpha:model");
        var sequence = await client.EmbedAsync(["dup", "dup", "three"], target: "alpha:model");

        Assert.Single(scalar.Vectors);
        Assert.Equal(["one"], adapter.EmbeddingRequests[0].Inputs);
        Assert.Equal(["dup", "dup", "three"], adapter.EmbeddingRequests[1].Inputs);
        Assert.Equal(3, sequence.Vectors.Count);
        Assert.Equal(sequence.Vectors[0].Values, sequence.Vectors[1].Values);
    }

    [Fact]
    public async Task Supplied_embedding_request_keeps_its_raw_choice_and_response_cap()
    {
        var raw = new AnyInfer.Json.JsonObject([new("source", new AnyInfer.Json.JsonString("adapter"))]);
        var adapter = new RecordingRetrievalAdapter { EmbeddingRaw = raw };
        await using var client = Client(adapter, operations: [InferenceOperation.Embedding], retainRaw: true);
        var request = new EmbeddingRequest(["one"], maxResponseBytes: 17, retainRaw: false);

        var result = await client.EmbedAsync(request, target: "alpha:model");

        Assert.Equal(17, adapter.EmbeddingRequests.Single().MaxResponseBytes);
        Assert.Null(result.Raw);
    }

    [Fact]
    public async Task Descriptor_declaration_and_runtime_protocol_are_checked_after_the_factory_enters()
    {
        var entered = 0;
        var adapter = new DisposeOnlyAdapter();
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                "alpha",
                "Alpha",
                (_, _) =>
                {
                    entered++;
                    return ValueTask.FromResult<IAsyncDisposable>(adapter);
                },
                operations: [InferenceOperation.Embedding]),
        ]);
        await using var client = new AsyncClient([ProviderSettings.Of("alpha")], registry);

        await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync("one", target: "alpha:model"));

        Assert.Equal(1, entered);
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Same_target_retry_records_retried_then_final_success_with_actual_timing()
    {
        var adapter = new RecordingRetrievalAdapter();
        adapter.EmbeddingFailures.Enqueue(new ProviderUnavailableException("temporary"));
        await using var client = Client(adapter, operations: [InferenceOperation.Embedding]);
        var route = new Route(["alpha:model"], retry: new Retry(MaxAttempts: 2, BackoffBaseS: 0));

        var result = await client.EmbedAsync("one", route: route);

        Assert.Equal(["retried", "ok"], result.Attempts.Select(static attempt => attempt.Outcome));
        Assert.All(result.Attempts, static attempt => Assert.NotNull(attempt.Timing));
        Assert.Equal(2, adapter.EmbeddingRequests.Count);
    }

    [Fact]
    public async Task Embedding_post_result_checks_reject_invalid_vectors_and_mismatched_expected_space_after_the_call()
    {
        var adapter = new RecordingRetrievalAdapter
        {
            EmbeddingResultFactory = static request => new EmbeddingWireResult([[double.NaN]], model: request.Model),
        };
        await using var client = Client(adapter, operations: [InferenceOperation.Embedding]);

        await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync("one", target: "alpha:model"));
        Assert.Single(adapter.EmbeddingRequests);

        adapter.EmbeddingResultFactory = static request => new EmbeddingWireResult([[1d]], model: request.Model);
        var expected = new EmbeddingSpace("other", "model");
        await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync("one", target: "alpha:model", expectedSpace: expected));
        Assert.Equal(2, adapter.EmbeddingRequests.Count);
    }

    [Fact]
    public async Task Rerank_string_documents_keep_original_ids_provider_order_and_optional_document_echo()
    {
        var adapter = new RecordingRetrievalAdapter
        {
            RerankResultFactory = static _ => new RerankWireResult([
                new WireRankedItem(2, 0.2),
                new WireRankedItem(0, 0.9),
            ]),
        };
        await using var client = Client(adapter, operations: [InferenceOperation.Rerank]);

        var result = await client.RerankAsync("query", ["zero", "one", "two"], target: "alpha:model", returnDocuments: true);

        Assert.Equal([2, 0], result.Items.Select(static item => item.Index));
        Assert.Equal(["2", "0"], result.Items.Select(static item => item.DocumentId));
        Assert.Equal(["two", "zero"], result.Items.Select(static item => item.Text));
        Assert.Equal([0, 1, 2], adapter.RerankRequests.Single().Documents.Select(static document => document.Index));
    }

    [Fact]
    public async Task Retrieval_manifest_override_and_telemetry_share_the_actual_operation_identifier()
    {
        var adapter = new RecordingRetrievalAdapter();
        var observer = new RecordingObserver();
        await using var client = new AsyncClient(
            [ProviderSettings.Of("alpha")],
            Registry(adapter, [InferenceOperation.Embedding]),
            observers: [observer],
            manifests: false);

        var noManifest = await client.EmbedAsync("one", target: "alpha:model");
        var withManifest = await client.EmbedAsync("two", target: "alpha:model", manifest: true);

        Assert.Null(noManifest.Manifest);
        Assert.NotNull(withManifest.Manifest);
        var started = observer.Events.OfType<RequestStarted>().ToArray();
        var completed = observer.Events.OfType<RequestCompleted>().ToArray();
        Assert.Equal(2, started.Length);
        Assert.Equal(started.Select(static item => item.RequestId), completed.Select(static item => item.RequestId));
        Assert.Contains(completed, item => item.RequestId == withManifest.Manifest!.RequestId);
    }

    [Fact]
    public void Sync_facade_uses_the_same_public_embedding_and_rerank_overloads()
    {
        var adapter = new RecordingRetrievalAdapter();
        using var client = new Client(
            [ProviderSettings.Of("alpha")],
            Registry(adapter, [InferenceOperation.Embedding, InferenceOperation.Rerank]));

        var embedding = client.Embed("one", target: "alpha:model");
        var rerank = client.Rerank("query", ["one", "two"], target: "alpha:model");

        Assert.Single(embedding.Vectors);
        Assert.Equal(["0", "1"], rerank.Items.Select(static item => item.DocumentId));
    }

    private static AsyncClient Client(
        RecordingRetrievalAdapter adapter,
        IEnumerable<InferenceOperation> operations,
        bool retainRaw = false) =>
        new([ProviderSettings.Of("alpha")], Registry(adapter, operations), retainRaw: retainRaw);

    private static ProviderRegistry Registry(IAsyncDisposable adapter, IEnumerable<InferenceOperation> operations) =>
        new([
            new ProviderDescriptor(
                "alpha",
                "Alpha",
                (_, _) => ValueTask.FromResult(adapter),
                operations: operations,
                staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities>
                {
                    ["model"] = new(dimensions: 1),
                },
                staticRerankCapabilities: new Dictionary<string, RerankCapabilities>
                {
                    ["model"] = new(nativeTopN: true),
                }),
        ]);

    private sealed class DisposeOnlyAdapter : IAsyncDisposable
    {
        internal int DisposeCalls { get; private set; }
        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class RecordingRetrievalAdapter : IEmbedsText, IReranksText, IAsyncDisposable
    {
        internal List<EmbeddingWireRequest> EmbeddingRequests { get; } = [];
        internal List<RerankWireRequest> RerankRequests { get; } = [];
        internal Queue<ProviderException> EmbeddingFailures { get; } = [];
        internal Func<EmbeddingWireRequest, EmbeddingWireResult>? EmbeddingResultFactory { get; set; }
        internal Func<RerankWireRequest, RerankWireResult>? RerankResultFactory { get; set; }
        internal AnyInfer.Json.JsonValue? EmbeddingRaw { get; set; }

        public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            EmbeddingRequests.Add(request);
            if (EmbeddingFailures.TryDequeue(out var failure)) throw failure;
            return ValueTask.FromResult(EmbeddingResultFactory?.Invoke(request) ??
                new EmbeddingWireResult(request.Inputs.Select(static text => new[] { (double)text.Length }), request.Model, raw: EmbeddingRaw));
        }

        public ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            RerankRequests.Add(request);
            return ValueTask.FromResult(RerankResultFactory?.Invoke(request) ??
                new RerankWireResult(request.Documents.Select(static document => new WireRankedItem(document.Index, document.Index))));
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class RecordingObserver : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent value) => Events.Add(value);
    }
}
