using AnyInfer.Capabilities;
using AnyInfer.Config;
using AnyInfer.Events;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public retrieval routing and all-or-error batching controls.</summary>
public sealed class RetrievalRoutingBatchTests
{
    [Fact]
    public async Task Operation_route_precedes_generation_default_and_keeps_repeated_candidates()
    {
        var primary = new BatchAdapter();
        var operation = new BatchAdapter();
        var registry = Registry(("primary", primary), ("operation", operation));
        var routes = new Dictionary<InferenceOperation, Route>
        {
            [InferenceOperation.Embedding] = new(["operation:model", "operation:model"]),
        };
        await using var client = new AsyncClient(
            [ProviderSettings.Of("primary"), ProviderSettings.Of("operation")],
            registry,
            route: new Route(["primary:model"]),
            operationRoutes: routes);

        await client.EmbedAsync("one");

        Assert.Empty(primary.EmbeddingRequests);
        Assert.Single(operation.EmbeddingRequests);
    }

    [Fact]
    public async Task Per_call_target_wins_over_operation_route()
    {
        var primary = new BatchAdapter();
        var operation = new BatchAdapter();
        await using var client = new AsyncClient(
            [ProviderSettings.Of("primary"), ProviderSettings.Of("operation")],
            Registry(("primary", primary), ("operation", operation)),
            operationRoutes: new Dictionary<InferenceOperation, Route>
            {
                [InferenceOperation.Embedding] = new(["operation:model"]),
            });

        await client.EmbedAsync("one", target: "primary:model");

        Assert.Single(primary.EmbeddingRequests);
        Assert.Empty(operation.EmbeddingRequests);
    }

    [Fact]
    public async Task From_config_uses_its_operation_route_unless_an_explicit_factory_route_replaces_it()
    {
        var configured = new BatchAdapter();
        var explicitAdapter = new BatchAdapter();
        var registry = Registry(("configured", configured), ("explicit", explicitAdapter));
        var config = new AnyInferConfig(
            [ProviderSettings.Of("configured"), ProviderSettings.Of("explicit")],
            operationRoutes: new Dictionary<InferenceOperation, Route>
            {
                [InferenceOperation.Embedding] = new(["configured:model"]),
            });

        await using (var parsed = AsyncClient.FromConfig(config, registry))
        {
            await parsed.EmbedAsync("one");
        }

        await using (var overridden = AsyncClient.FromConfig(
            config,
            registry,
            operationRoutes: new Dictionary<InferenceOperation, Route>
            {
                [InferenceOperation.Embedding] = new(["explicit:model"]),
            }))
        {
            await overridden.EmbedAsync("two");
        }

        Assert.Single(configured.EmbeddingRequests);
        Assert.Single(explicitAdapter.EmbeddingRequests);
    }

    [Fact]
    public async Task From_adapters_forwards_the_embedding_operation_route_without_a_generation_adapter()
    {
        var adapter = new BatchAdapter();
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", adapter)],
            operationRoutes: new Dictionary<InferenceOperation, Route>
            {
                [InferenceOperation.Embedding] = new(["alpha:model", "alpha:model"]),
            });

        await client.EmbedAsync("one");

        Assert.Single(adapter.EmbeddingRequests);
        Assert.Equal("model", adapter.EmbeddingRequests.Single().Model);
    }

    [Fact]
    public async Task Embedding_batches_complete_out_of_order_but_return_input_order_and_mixed_raw_positions()
    {
        var firstStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseFirst = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new BatchAdapter
        {
            Embed = async (request, token) =>
            {
                if (request.Inputs[0] == "a")
                {
                    firstStarted.TrySetResult();
                    await releaseFirst.Task.WaitAsync(token);
                    return new EmbeddingWireResult([[1d], [2d]], request.Model, raw: new AnyInfer.Json.JsonString("first"));
                }

                await firstStarted.Task.WaitAsync(token);
                releaseFirst.TrySetResult();
                return new EmbeddingWireResult([[3d]], request.Model, raw: null);
            },
        };
        await using var client = Client(adapter, embeddingLimit: 2);

        var result = await client.EmbedAsync(
            ["a", "bb", "ccc"],
            target: "alpha:model",
            batch: new BatchPolicy(maxConcurrency: 2),
            retainRaw: true);

        Assert.Equal([1d, 2d, 3d], result.Vectors.Select(static vector => vector.Values.Single()));
        var raw = Assert.IsType<AnyInfer.Json.JsonArray>(result.Raw);
        Assert.IsType<AnyInfer.Json.JsonString>(raw.Items[0]);
        Assert.Same(AnyInfer.Json.JsonNull.Instance, raw.Items[1]);
    }

    [Fact]
    public async Task Provider_chunk_failure_joins_all_chunks_and_reports_ordered_batch_failures()
    {
        var adapter = new BatchAdapter
        {
            Embed = static (request, _) => request.Inputs[0] == "c"
                ? ValueTask.FromException<EmbeddingWireResult>(new ProviderUnavailableException("second chunk"))
                : ValueTask.FromResult(new EmbeddingWireResult(request.Inputs.Select(static _ => new[] { 1d }), request.Model)),
        };
        await using var client = Client(adapter, embeddingLimit: 2);

        var error = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.EmbedAsync(
            ["a", "b", "c"],
            target: "alpha:model",
            batch: new BatchPolicy(maxConcurrency: 2)));

        Assert.Collection(
            error.BatchFailures,
            first => { Assert.Equal(0, first.BatchIndex); Assert.Equal(2, first.ItemCount); Assert.True(first.Succeeded); Assert.Null(first.Error); },
            second => { Assert.Equal(1, second.BatchIndex); Assert.Equal(1, second.ItemCount); Assert.False(second.Succeeded); Assert.Null(second.Error); });
        Assert.Equal(["ok", "failed"], error.Attempts.Select(static attempt => attempt.Outcome));
        Assert.Null(error.Attempts.Last().Timing);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Split_provider_failure_is_route_terminal_and_never_replays_against_a_fallback(bool allChunksFail)
    {
        var primary = new BatchAdapter
        {
            Embed = (request, _) =>
            {
                var fails = allChunksFail || request.Inputs[0] == "c";
                return fails
                    ? ValueTask.FromException<EmbeddingWireResult>(new ProviderUnavailableException("primary failure"))
                    : ValueTask.FromResult(new EmbeddingWireResult(request.Inputs.Select(static _ => new[] { 1d }), request.Model));
            },
        };
        var fallback = new BatchAdapter();
        await using var client = new AsyncClient(
            [ProviderSettings.Of("primary"), ProviderSettings.Of("fallback")],
            Registry(("primary", primary), ("fallback", fallback), embeddingLimit: 2),
            route: new Route(["primary:model", "fallback:model"], retry: new Retry(MaxAttempts: 1), healthGate: false));

        var error = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.EmbedAsync(["a", "b", "c"]));

        Assert.Equal(2, primary.EmbeddingRequests.Count);
        Assert.Empty(fallback.EmbeddingRequests);
        Assert.Equal(
            allChunksFail ? [false, false] : [true, false],
            error.BatchFailures.Select(static failure => failure.Succeeded));
        Assert.Equal([0, 1], error.BatchFailures.Select(static failure => failure.BatchIndex));
        Assert.DoesNotContain(error.Attempts, static attempt => attempt.Outcome == "retried");
    }

    [Fact]
    public async Task Repeated_route_target_is_consumed_again_after_a_failure_when_health_gate_is_disabled()
    {
        var adapter = new BatchAdapter();
        var first = true;
        adapter.Embed = (request, _) =>
        {
            if (first)
            {
                first = false;
                return ValueTask.FromException<EmbeddingWireResult>(new ProviderUnavailableException("first occurrence"));
            }

            return ValueTask.FromResult(new EmbeddingWireResult([[1d]], request.Model));
        };
        var observer = new RecordingObserver();
        await using var client = new AsyncClient(
            [ProviderSettings.Of("alpha")],
            Registry(("alpha", adapter)),
            observers: [observer]);

        var result = await client.EmbedAsync(
            "one",
            route: new Route(["alpha:model", "alpha:model"], retry: new Retry(MaxAttempts: 1), healthGate: false));

        Assert.Single(result.Vectors);
        Assert.Equal(2, adapter.EmbeddingRequests.Count);
        Assert.Equal(2, observer.Events.OfType<TargetResolved>().Count());
        Assert.Single(observer.Events.OfType<FallbackTriggered>());
    }

    [Fact]
    public async Task Exhausted_unsplit_retry_keeps_only_the_final_failed_attempt_without_timing()
    {
        var terminal = new ProviderUnavailableException("terminal");
        var adapter = new BatchAdapter();
        adapter.Embed = (_, _) => ValueTask.FromException<EmbeddingWireResult>(
            adapter.EmbeddingRequests.Count == 2 ? terminal : new ProviderUnavailableException("retry"));
        await using var client = Client(adapter);

        var error = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.EmbedAsync(
            "one",
            route: new Route(["alpha:model"], retry: new Retry(MaxAttempts: 2, BackoffBaseS: 0))));

        var attempt = Assert.Single(error.Attempts);
        Assert.Equal("failed", attempt.Outcome);
        Assert.Null(attempt.Timing);
        Assert.Same(terminal, attempt.Error);
        Assert.Equal(2, adapter.EmbeddingRequests.Count);
    }

    [Fact]
    public async Task Non_provider_chunk_fault_rethrows_original_identity_after_all_work_has_joined()
    {
        var failure = new InvalidOperationException("sentinel");
        var secondEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new BatchAdapter
        {
            Embed = async (request, token) =>
            {
                if (request.Inputs[0] == "a")
                {
                    await secondEntered.Task.WaitAsync(token);
                    throw failure;
                }

                secondEntered.TrySetResult();
                return new EmbeddingWireResult([[2d]], request.Model);
            },
        };
        await using var client = Client(adapter, embeddingLimit: 1);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => client.EmbedAsync(
            ["a", "b"], target: "alpha:model", batch: new BatchPolicy(maxConcurrency: 2)));

        Assert.Same(failure, actual);
        Assert.Equal(2, adapter.EmbeddingRequests.Count);
    }

    [Fact]
    public async Task Rerank_split_requires_opt_in_for_cross_batch_and_keeps_each_chunk_top_n()
    {
        var adapter = new BatchAdapter();
        await using var client = Client(adapter, rerankLimit: 2);
        var documents = new[] { "a", "b", "c" };

        await Assert.ThrowsAsync<ConfigException>(() => client.RerankAsync("query", documents, target: "alpha:model", topN: 1));
        Assert.Empty(adapter.RerankRequests);

        var result = await client.RerankAsync(
            "query",
            documents,
            target: "alpha:model",
            topN: 1,
            batch: new BatchPolicy(rerankCrossBatch: true));

        Assert.Equal([1, 1], adapter.RerankRequests.Select(static request => request.TopN));
        Assert.Equal([0, 1, 2], result.Items.Select(static item => item.Index));
        Assert.Equal("rerank request was split into 2 batches of at most 2 documents for alpha:model; scores are comparable only within each batch — this result concatenates chunk-local rankings and is not a provider-certified global ordering; top_n=1 was applied within each batch, not globally", Assert.Single(result.Warnings));
    }

    [Theory]
    [InlineData("wrong-count")]
    [InlineData("ragged")]
    [InlineData("nonfinite")]
    public async Task Malformed_embedding_wire_shapes_are_core_config_failures_after_primary_entry(string shape)
    {
        var primary = new BatchAdapter
        {
            Embed = (request, _) => ValueTask.FromResult(shape switch
            {
                "wrong-count" => new EmbeddingWireResult([[1d]], request.Model),
                "ragged" => new EmbeddingWireResult([[1d], [1d, 2d]], request.Model),
                "nonfinite" => new EmbeddingWireResult([[double.NaN], [1d]], request.Model),
                _ => throw new InvalidOperationException(shape),
            }),
        };
        var fallback = new BatchAdapter();
        var observer = new RecordingObserver();
        await using var client = new AsyncClient(
            [ProviderSettings.Of("primary"), ProviderSettings.Of("fallback")],
            Registry(("primary", primary), ("fallback", fallback)),
            observers: [observer]);

        await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync(
            ["one", "two"],
            route: new Route(["primary:model", "fallback:model"], retry: new Retry(MaxAttempts: 2), healthGate: false)));

        Assert.Single(primary.EmbeddingRequests);
        Assert.Empty(fallback.EmbeddingRequests);
        Assert.Empty(observer.Events.OfType<RetryScheduled>());
        Assert.Empty(observer.Events.OfType<RequestCompleted>());
        Assert.Empty(observer.Events.OfType<RequestFailed>());
    }

    [Theory]
    [InlineData("out-of-range")]
    [InlineData("duplicate")]
    [InlineData("nonfinite")]
    [InlineData("out-of-chunk")]
    public async Task Malformed_rerank_wire_items_are_core_config_failures_after_primary_entry(string shape)
    {
        var primary = new BatchAdapter
        {
            Rerank = (request, _) => ValueTask.FromResult(shape switch
            {
                "out-of-range" => new RerankWireResult([new WireRankedItem(9, 1d)]),
                "duplicate" => new RerankWireResult([new WireRankedItem(request.Documents[0].Index, 1d), new WireRankedItem(request.Documents[0].Index, 0d)]),
                "nonfinite" => new RerankWireResult([new WireRankedItem(request.Documents[0].Index, double.PositiveInfinity)]),
                "out-of-chunk" => new RerankWireResult([new WireRankedItem(request.Documents[0].Index == 0 ? 1 : 0, 1d)]),
                _ => throw new InvalidOperationException(shape),
            }),
        };
        var fallback = new BatchAdapter();
        var observer = new RecordingObserver();
        await using var client = new AsyncClient(
            [ProviderSettings.Of("primary"), ProviderSettings.Of("fallback")],
            Registry(("primary", primary), ("fallback", fallback), rerankLimit: shape == "out-of-chunk" ? 1 : 2),
            observers: [observer]);

        await Assert.ThrowsAsync<ConfigException>(() => client.RerankAsync(
            "query",
            ["one", "two"],
            route: new Route(["primary:model", "fallback:model"], retry: new Retry(MaxAttempts: 2), healthGate: false),
            batch: shape == "out-of-chunk" ? new BatchPolicy(rerankCrossBatch: true) : null));

        Assert.NotEmpty(primary.RerankRequests);
        Assert.Empty(fallback.RerankRequests);
        Assert.Empty(observer.Events.OfType<RetryScheduled>());
        Assert.Empty(observer.Events.OfType<RequestCompleted>());
        Assert.Empty(observer.Events.OfType<RequestFailed>());
    }

    private static AsyncClient Client(BatchAdapter adapter, int? embeddingLimit = null, int? rerankLimit = null) =>
        new([ProviderSettings.Of("alpha")], Registry(("alpha", adapter), embeddingLimit: embeddingLimit, rerankLimit: rerankLimit));

    private static ProviderRegistry Registry(
        (string Id, BatchAdapter Adapter) first,
        (string Id, BatchAdapter Adapter)? second = null,
        int? embeddingLimit = null,
        int? rerankLimit = null)
    {
        var descriptors = new List<ProviderDescriptor> { Descriptor(first.Id, first.Adapter, embeddingLimit, rerankLimit) };
        if (second is { } value) descriptors.Add(Descriptor(value.Id, value.Adapter, embeddingLimit, rerankLimit));
        return new ProviderRegistry(descriptors);
    }

    private static ProviderDescriptor Descriptor(string id, BatchAdapter adapter, int? embeddingLimit, int? rerankLimit) =>
        new(
            id,
            id,
            (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            operations: [InferenceOperation.Embedding, InferenceOperation.Rerank],
            staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities> { ["model"] = new(maxBatchInputs: embeddingLimit) },
            staticRerankCapabilities: new Dictionary<string, RerankCapabilities> { ["model"] = new(maxDocuments: rerankLimit, nativeTopN: true) });

    private sealed class BatchAdapter : IEmbedsText, IReranksText, IAsyncDisposable
    {
        internal List<EmbeddingWireRequest> EmbeddingRequests { get; } = [];
        internal List<RerankWireRequest> RerankRequests { get; } = [];
        internal Func<EmbeddingWireRequest, CancellationToken, ValueTask<EmbeddingWireResult>>? Embed { get; set; }
        internal Func<RerankWireRequest, CancellationToken, ValueTask<RerankWireResult>>? Rerank { get; init; }

        public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
        {
            EmbeddingRequests.Add(request);
            return Embed?.Invoke(request, cancellationToken) ?? ValueTask.FromResult(
                new EmbeddingWireResult(request.Inputs.Select(static (_, index) => new[] { (double)(index + 1) }), request.Model));
        }

        public ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default)
        {
            RerankRequests.Add(request);
            return Rerank?.Invoke(request, cancellationToken) ?? ValueTask.FromResult(
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
