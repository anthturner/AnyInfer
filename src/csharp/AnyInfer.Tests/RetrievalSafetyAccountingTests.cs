using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public safety, accounting, and privacy controls for buffered retrieval operations.</summary>
public sealed class RetrievalSafetyAccountingTests
{
    [Fact]
    public async Task Unknown_limits_are_single_request_ceilings()
    {
        var adapter = new RetrievalAdapter();
        await using var client = CreateClient(adapter);

        await client.EmbedAsync(Enumerable.Repeat("x", 2048), target: "alpha:model");
        await client.RerankAsync("q", Enumerable.Repeat("d", 1000), target: "alpha:model");

        Assert.Single(adapter.EmbeddingRequests);
        Assert.Equal(2048, adapter.EmbeddingRequests[0].Inputs.Count);
        Assert.Single(adapter.RerankRequests);
        Assert.Equal(1000, adapter.RerankRequests[0].Documents.Count);

        await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync(
            Enumerable.Repeat("x", 2049), target: "alpha:model"));
        await Assert.ThrowsAsync<ConfigException>(() => client.RerankAsync(
            "q", Enumerable.Repeat("d", 1001), target: "alpha:model",
            batch: new BatchPolicy(rerankCrossBatch: true)));
        Assert.Single(adapter.EmbeddingRequests);
        Assert.Single(adapter.RerankRequests);
    }

    [Fact]
    public async Task Discovered_embedding_batch_limit_overlays_static_facts_after_models_listing()
    {
        var adapter = new RetrievalAdapter
        {
            ListedModels = [new DiscoveredModel("model", new ModelCapabilities(
                embedding: new EmbeddingCapabilities(maxBatchInputs: 1)))],
        };
        await using var client = CreateClient(adapter, embeddingLimit: 2);

        var listed = await client.ModelsAsync("alpha", InferenceOperation.Embedding);
        await client.EmbedAsync(["first", "second"], target: "alpha:model", batch: new BatchPolicy(maxConcurrency: 1));

        Assert.Single(listed);
        Assert.Equal([1, 1], adapter.EmbeddingRequests.Select(static request => request.Inputs.Count));
    }

    [Fact]
    public async Task Overrides_take_precedence_and_input_intent_warnings_follow_declared_facts()
    {
        var adapter = new RetrievalAdapter();
        var observer = new EventCollector();
        var descriptor = Descriptor(
            adapter,
            embeddingLimit: 1,
            intents: [EmbeddingInputIntent.Document]);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("alpha")], new ProviderRegistry([descriptor]), observers: [observer]);

        var result = await client.EmbedAsync(
            ["a", "b"],
            target: "alpha:model",
            inputType: EmbeddingInputIntent.Query,
            batch: new BatchPolicy(maxItemsOverride: 2));

        Assert.Single(adapter.EmbeddingRequests);
        Assert.Equal(EmbeddingInputIntent.Query, adapter.EmbeddingRequests[0].InputType);
        var warning = Assert.Single(result.Warnings);
        Assert.Equal("alpha:model does not support input_type='query' (supported: document); the provider's own handling applies", warning);
        Assert.Empty(observer.Events.OfType<RequestFailed>());
    }

    [Fact]
    public async Task Chunk_local_vector_count_and_space_agreement_are_checked_after_actual_calls()
    {
        var adapter = new RetrievalAdapter
        {
            Embed = request => request.Inputs[0] == "a"
                ? new EmbeddingWireResult([[1d], [2d], [3d]], model: "one", dimensions: 1)
                : new EmbeddingWireResult([[4d]], model: "two", dimensions: 1),
        };
        await using var client = CreateClient(adapter, embeddingLimit: 2);

        var failure = await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync(
            ["a", "b", "c", "d"],
            target: "alpha:model",
            batch: new BatchPolicy(maxConcurrency: 1)));

        Assert.Equal("alpha", failure.Provider);
        Assert.Equal([2, 2], adapter.EmbeddingRequests.Select(static request => request.Inputs.Count));
    }

    [Fact]
    public async Task Cross_chunk_reported_space_disagreement_is_a_provider_config_failure()
    {
        var adapter = new RetrievalAdapter
        {
            Embed = request => request.Inputs[0] == "a"
                ? new EmbeddingWireResult([[1d], [2d]], model: "first", dimensions: 1)
                : new EmbeddingWireResult([[3d], [4d]], model: "second", dimensions: 1),
        };
        await using var client = CreateClient(adapter, embeddingLimit: 2);

        var failure = await Assert.ThrowsAsync<ConfigException>(() => client.EmbedAsync(
            ["a", "b", "c", "d"], target: "alpha:model", batch: new BatchPolicy(maxConcurrency: 1)));

        Assert.Equal("alpha", failure.Provider);
        Assert.Equal(2, adapter.EmbeddingRequests.Count);
    }

    [Fact]
    public async Task Null_input_intent_is_silent_and_declared_empty_facts_emit_the_source_warning()
    {
        var silent = new RetrievalAdapter();
        await using var silentClient = CreateClient(silent, embeddingLimit: null);
        var nullIntent = await silentClient.EmbedAsync("input", target: "alpha:model");
        var emptyFacts = await silentClient.EmbedAsync(
            "input", target: "alpha:model", inputType: EmbeddingInputIntent.Query);

        Assert.Empty(nullIntent.Warnings);
        Assert.Equal("alpha:model does not distinguish embedding input intents; input_type='query' has no effect on this target", Assert.Single(emptyFacts.Warnings));
    }
    [Fact]
    public async Task Produced_space_is_post_result_only_and_does_not_hydrate_expected_space()
    {
        var adapter = new RetrievalAdapter
        {
            Embed = request => new EmbeddingWireResult([[1d, 2d]], model: request.Model, dimensions: 2),
        };
        await using var client = CreateClient(adapter);
        var expected = new EmbeddingSpace("alpha", "model", dimensions: 2);

        var result = await client.EmbedAsync("input", target: "alpha:model", expectedSpace: expected);

        Assert.Null(result.Space.ModelRevision);
        Assert.False(result.Space.InputIntentAware);
        Assert.Null(result.Space.CompatibilityId);
        Assert.Equal(2, result.Space.Dimensions);
    }

    [Fact]
    public async Task Operation_costs_use_reported_usage_and_commit_one_logical_ledger_result()
    {
        var adapter = new RetrievalAdapter
        {
            Embed = request => new EmbeddingWireResult(
                request.Inputs.Select(static _ => new[] { 1d }), request.Model,
                usage: new Usage(InputTokens: 1)),
            Rerank = request => new RerankWireResult(
                request.Documents.Select(static item => new WireRankedItem(item.Index, 1d)), request.Model,
                usage: new Usage(SearchUnits: 2)),
        };
        var ledger = new SpendLedger();
        var observer = new EventCollector();
        var pricing = new Pricing(D("1000000"), EDecimal.Zero, perSearchUnit: D("3"));
        var capabilities = new ModelCapabilities(pricing: new Sourced<Pricing>(pricing, Provenance.Catalog));
        await using var client = CreateClient(adapter, capabilities: capabilities, observer: observer, ledger: ledger);

        var embeddings = await client.EmbedAsync(["a", "b"], target: "alpha:model", batch: new BatchPolicy(maxItemsOverride: 1));
        var rerank = await client.RerankAsync("q", ["a"], target: "alpha:model");

        EqualDecimal(D("2"), embeddings.Usage.CostUsd);
        EqualDecimal(D("6"), rerank.Usage.CostUsd);
        Assert.Equal(2, ledger.Totals().Requests);
        Assert.Equal(2, observer.Events.OfType<RequestCompleted>().Count());
    }

    [Fact]
    public async Task Provider_reported_operation_cost_wins_and_a_failed_split_does_not_commit_partial_usage()
    {
        var adapter = new RetrievalAdapter
        {
            Embed = request => request.Inputs[0] == "failed"
                ? throw new ProviderUnavailableException("chunk failure")
                : new EmbeddingWireResult(
                    request.Inputs.Select(static _ => new[] { 1d }), request.Model,
                    usage: new Usage(InputTokens: 1, CostUsd: D("9"))),
        };
        var ledger = new SpendLedger();
        var capabilities = new ModelCapabilities(pricing: new Sourced<Pricing>(
            new Pricing(D("1000000"), EDecimal.Zero), Provenance.Catalog));
        await using var client = CreateClient(adapter, embeddingLimit: 1, capabilities: capabilities, ledger: ledger);

        var error = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.EmbedAsync(
            ["ok", "failed"], target: "alpha:model", batch: new BatchPolicy(maxConcurrency: 1)));

        Assert.Collection(
            error.BatchFailures,
            first => { Assert.True(first.Succeeded); Assert.Equal(0, first.BatchIndex); Assert.Equal(1, first.ItemCount); },
            second => { Assert.False(second.Succeeded); Assert.Equal(1, second.BatchIndex); Assert.Equal(1, second.ItemCount); });
        EqualDecimal(EDecimal.Zero, ledger.Totals().Cost);
        Assert.Equal(0, ledger.Totals().Requests);
    }

    [Fact]
    public async Task Rerank_cross_batch_requires_opt_in_even_when_an_explicit_override_is_selected()
    {
        var adapter = new RetrievalAdapter();
        await using var client = CreateClient(adapter, embeddingLimit: null);
        var request = new RerankRequest(
            "query",
            [new RerankDocument("0", "first"), new RerankDocument("1", "second")],
            batch: new BatchPolicy(maxItemsOverride: 1));

        await Assert.ThrowsAsync<ConfigException>(() => client.RerankAsync(request, target: "alpha:model"));

        Assert.Empty(adapter.RerankRequests);
    }
    [Fact]
    public async Task Unknown_refused_spend_never_constructs_or_invokes_the_provider()
    {
        var adapter = new RetrievalAdapter();
        var factoryCalls = 0;
        var descriptor = new ProviderDescriptor(
            "alpha", "Alpha", (_, _) =>
            {
                factoryCalls++;
                return ValueTask.FromResult<IAsyncDisposable>(adapter);
            },
            operations: [InferenceOperation.Embedding],
            staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities> { ["model"] = new() });
        await using var client = new AsyncClient(
            [ProviderSettings.Of("alpha")],
            new ProviderRegistry([descriptor]),
            estimator: new FixedEstimator(),
            spendPolicy: new SpendPolicy(onUnknown: "refuse"));

        var failure = await Assert.ThrowsAsync<SpendLimitException>(() => client.EmbedAsync("input", target: "alpha:model"));

        Assert.Equal("spend_limit", failure.Category);
        Assert.Equal("generate", failure.Phase);
        Assert.Equal(0, factoryCalls);
        Assert.Empty(adapter.EmbeddingRequests);
    }

    [Fact]
    public async Task Split_terminal_failure_preserves_successful_retry_trail_and_emits_the_first_provider_failure()
    {
        var calls = new Dictionary<string, int>(StringComparer.Ordinal);
        var adapter = new RetrievalAdapter
        {
            Embed = request =>
            {
                var input = request.Inputs.Single();
                calls[input] = calls.TryGetValue(input, out var count) ? count + 1 : 1;
                return input switch
                {
                    "zero" when calls[input] == 1 => throw new ProviderUnavailableException("transient", provider: "provider-a", detail: "retry-detail"),
                    "zero" => new EmbeddingWireResult([[1d]], request.Model, usage: new Usage(InputTokens: 1)),
                    "one" => throw new ProviderUnavailableException("first failure", provider: "provider-a", detail: "a-detail"),
                    _ => throw new ProviderUnavailableException("second failure", provider: "provider-b", detail: "b-detail"),
                };
            },
        };
        var ledger = new SpendLedger();
        var observer = new EventCollector();
        await using var client = CreateClient(adapter, embeddingLimit: 1, observer: observer, ledger: ledger);

        var error = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.EmbedAsync(
            ["zero", "one", "two"],
            target: "alpha:model",
            route: new Route(["alpha:model"], retry: new Retry(MaxAttempts: 2, BackoffBaseS: 0)),
            batch: new BatchPolicy(maxConcurrency: 1)));

        Assert.Equal(["retried", "ok", "failed", "failed"], error.Attempts.Select(static attempt => attempt.Outcome));
        Assert.NotNull(error.Attempts[0].Timing);
        Assert.NotNull(error.Attempts[1].Timing);
        Assert.Null(error.Attempts[2].Timing);
        Assert.Null(error.Attempts[3].Timing);
        Assert.Collection(
            error.BatchFailures,
            first => { Assert.Equal(0, first.BatchIndex); Assert.True(first.Succeeded); Assert.Equal(1, first.ItemCount); },
            second => { Assert.Equal(1, second.BatchIndex); Assert.False(second.Succeeded); Assert.Equal(1, second.ItemCount); Assert.Equal("a-detail", second.Error); },
            third => { Assert.Equal(2, third.BatchIndex); Assert.False(third.Succeeded); Assert.Equal(1, third.ItemCount); Assert.Equal("b-detail", third.Error); });
        Assert.Null(error.Provider);
        Assert.Null(error.Detail);
        Assert.Null(error.InnerException);
        var terminal = Assert.IsType<RequestFailed>(Assert.Single(observer.Events.OfType<RequestFailed>()));
        Assert.Equal("provider-a", terminal.Error.Provider);
        Assert.Equal("a-detail", terminal.Error.Detail);
        Assert.Empty(observer.Events.OfType<RequestCompleted>());
        Assert.Equal(0, ledger.Totals().Requests);
    }

    [Fact]
    public async Task Successful_retry_projects_attempt_trail_warning_and_public_manifest_without_payloads()
    {
        var calls = 0;
        var adapter = new RetrievalAdapter
        {
            Embed = request => ++calls == 1
                ? throw new ProviderUnavailableException("retry", provider: "alpha", detail: "retry-detail")
                : new EmbeddingWireResult([[1d]], request.Model, usage: new Usage(InputTokens: 1)),
        };
        var observer = new EventCollector();
        var descriptor = Descriptor(adapter, intents: [EmbeddingInputIntent.Document]);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("alpha")], new ProviderRegistry([descriptor]), observers: [observer]);

        var result = await client.EmbedAsync(
            "input",
            target: "alpha:model",
            route: new Route(["alpha:model"], retry: new Retry(MaxAttempts: 2, BackoffBaseS: 0)),
            inputType: EmbeddingInputIntent.Query,
            manifest: true);

        var manifest = Assert.IsType<AnyInfer.Manifest.RunManifest>(result.Manifest);
        var completed = Assert.IsType<RequestCompleted>(Assert.Single(observer.Events.OfType<RequestCompleted>()));
        Assert.Equal(completed.RequestId, manifest.RequestId);
        Assert.Equal("embedding", manifest.Operation);
        Assert.Equal("alpha:model", manifest.Route.Resolved);
        Assert.Equal(["retried", "ok"], manifest.Route.Considered.Select(static item => item.Outcome));
        Assert.Equal(["retry-detail", ""], manifest.Route.Considered.Select(static item => item.Reason));
        Assert.All(manifest.Attempts, static attempt => Assert.Equal(1, attempt.AttemptNumber));
        Assert.Equal(["retried", "ok"], manifest.Attempts.Select(static item => item.Outcome));
        Assert.NotNull(manifest.Attempts[0].Error);
        Assert.Equal("retry-detail", manifest.Attempts[0].Error!.Detail);
        Assert.NotNull(manifest.Attempts[0].TotalMs);
        Assert.NotNull(manifest.Attempts[1].TotalMs);
        Assert.Equal(result.Usage.InputTokens, manifest.Usage.InputTokens);
        Assert.Equal(result.Usage.CostUsd?.ToString(), manifest.Usage.CostUsd);
        Assert.Contains(Assert.Single(result.Warnings), manifest.Notes);
        Assert.Null(manifest.Payloads);
        Assert.IsType<JsonObject>(manifest.ToDictionary());
    }
    [Fact]
    public async Task Retained_raw_is_identity_preserving_while_default_manifest_and_telemetry_remain_payload_free()
    {
        var raw = new JsonObject([new JsonProperty("provider", new JsonString("raw"))]);
        var adapter = new RetrievalAdapter
        {
            Embed = request => new EmbeddingWireResult([[1d]], request.Model, raw: raw),
        };
        var observer = new EventCollector();
        await using var client = CreateClient(adapter, observer: observer);

        var withoutRaw = await client.EmbedAsync("one", target: "alpha:model");
        var retained = await client.EmbedAsync("two", target: "alpha:model", retainRaw: true, manifest: true);

        Assert.Null(withoutRaw.Raw);
        Assert.Same(raw, retained.Raw);
        Assert.NotNull(retained.Manifest);
        Assert.True(retained.Manifest!.Complete);
        Assert.Null(retained.Manifest.Payloads);
        Assert.Equal("embedding", retained.Manifest.Operation);
        Assert.Equal("alpha:model", retained.Manifest.Route.Resolved);
        Assert.Equal(retained.Usage.InputTokens, retained.Manifest.Usage.InputTokens);
        Assert.Equal(retained.Usage.CostUsd?.ToString(), retained.Manifest.Usage.CostUsd);
        Assert.DoesNotContain(observer.Events, static item => item.ToString()!.Contains("raw", StringComparison.OrdinalIgnoreCase));
    }

    private static AsyncClient CreateClient(
        RetrievalAdapter adapter,
        int? embeddingLimit = null,
        ModelCapabilities? capabilities = null,
        EventCollector? observer = null,
        SpendLedger? ledger = null)
    {
        var descriptor = Descriptor(adapter, embeddingLimit, capabilities: capabilities);
        return new AsyncClient(
            [ProviderSettings.Of("alpha")],
            new ProviderRegistry([descriptor]),
            observers: observer is null ? null : [observer],
            ledger: ledger);
    }

    private static ProviderDescriptor Descriptor(
        RetrievalAdapter adapter,
        int? embeddingLimit = null,
        IEnumerable<EmbeddingInputIntent>? intents = null,
        ModelCapabilities? capabilities = null) =>
        new(
            "alpha",
            "Alpha",
            (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            operations: [InferenceOperation.Embedding, InferenceOperation.Rerank],
            staticCapabilities: capabilities is null
                ? null
                : new Dictionary<string, ModelCapabilities> { ["model"] = capabilities },
            staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities>
            {
                ["model"] = new(maxBatchInputs: embeddingLimit, inputIntents: intents),
            },
            staticRerankCapabilities: new Dictionary<string, RerankCapabilities>
            {
                ["model"] = new(nativeTopN: true),
            });

    private static EDecimal D(string value) => EDecimal.FromString(value);

    private static void EqualDecimal(EDecimal expected, EDecimal? actual)
    {
        Assert.NotNull(actual);
        Assert.Equal(0, expected.CompareTo(actual!));
    }

    private sealed class RetrievalAdapter : IEmbedsText, IReranksText, IProviderLifecycle, IAsyncDisposable
    {
        private readonly object _gate = new();

        internal List<EmbeddingWireRequest> EmbeddingRequests { get; } = [];
        internal List<RerankWireRequest> RerankRequests { get; } = [];
        internal IReadOnlyList<DiscoveredModel> ListedModels { get; init; } = [];
        internal Func<EmbeddingWireRequest, EmbeddingWireResult>? Embed { get; init; }
        internal Func<RerankWireRequest, RerankWireResult>? Rerank { get; init; }

        public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
        {
            lock (_gate) EmbeddingRequests.Add(request);
            return ValueTask.FromResult(Embed?.Invoke(request) ?? new EmbeddingWireResult(
                request.Inputs.Select(static _ => new[] { 1d }), request.Model));
        }

        public ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default)
        {
            lock (_gate) RerankRequests.Add(request);
            return ValueTask.FromResult(Rerank?.Invoke(request) ?? new RerankWireResult(
                request.Documents.Select(static item => new WireRankedItem(item.Index, 1d)), request.Model));
        }

        public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default) =>
            ValueTask.FromResult(ListedModels);

        public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default) =>
            ValueTask.FromResult(new Health(true));

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class EventCollector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }

    private sealed class FixedEstimator : ITokenEstimator
    {
        public TokenEstimate Estimate(string text) => new(1, 1);
    }
}
