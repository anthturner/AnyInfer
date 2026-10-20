using System.Net;
using System.Runtime.CompilerServices;
using System.Text;
using AnyInfer.Capabilities;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Retrieval-only provider acquisition and ownership controls.</summary>
public sealed class RetrievalProviderOwnershipTests
{
    [Fact]
    public async Task Models_and_health_can_materialize_a_retrieval_only_lifecycle_without_generation()
    {
        var adapter = new RetrievalLifecycleAdapter();
        var registry = Registry((_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter), operations: [InferenceOperation.Embedding]);
        await using var client = new AsyncClient([ProviderSettings.Of("fixture")], registry);

        var models = await client.ModelsAsync("fixture");
        var health = await client.HealthAsync("fixture");

        Assert.Equal("embedding-model", Assert.Single(models).Id);
        Assert.True(health.Ok);
        Assert.Equal(1, adapter.ModelsCalls);
        Assert.Equal(1, adapter.HealthCalls);
        Assert.Equal(0, adapter.EmbedCalls);
    }

    [Fact]
    public async Task Declared_retrieval_protocol_is_checked_after_factory_and_invalid_new_return_is_disposed_once()
    {
        var invalid = new RetrievalLifecycleAdapter();
        var factoryCalls = 0;
        var registry = Registry((_, _) =>
        {
            factoryCalls++;
            return ValueTask.FromResult<IAsyncDisposable>(invalid);
        }, operations: [InferenceOperation.Embedding, InferenceOperation.Rerank]);
        await using var client = new AsyncClient([ProviderSettings.Of("fixture")], registry);

        await Assert.ThrowsAsync<ConfigException>(() => client.ModelsAsync("fixture"));

        Assert.Equal(1, factoryCalls);
        Assert.Equal(1, invalid.DisposeCalls);
        Assert.Equal(0, invalid.ModelsCalls);
    }

    [Fact]
    public async Task Invalid_factory_return_cleanup_failure_has_precedence_over_protocol_refusal()
    {
        var cleanupFailure = new InvalidOperationException("cleanup sentinel");
        var invalid = new LifecycleOnlyAdapter(cleanupFailure);
        var registry = Registry((_, _) => ValueTask.FromResult<IAsyncDisposable>(invalid), operations: [InferenceOperation.Rerank]);
        await using var client = new AsyncClient([ProviderSettings.Of("fixture")], registry);

        var actual = await Assert.ThrowsAnyAsync<Exception>(() => client.HealthAsync("fixture"));

        Assert.Same(cleanupFailure, actual);
        Assert.Equal(1, invalid.DisposeCalls);
    }

    [Fact]
    public async Task Factory_source_cancellation_and_exception_keep_their_identity()
    {
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        var cancellationRegistry = Registry((_, _) => ValueTask.FromException<IAsyncDisposable>(new OperationCanceledException(cancellation.Token)), operations: [InferenceOperation.Embedding]);
        await using var cancelledClient = new AsyncClient([ProviderSettings.Of("fixture")], cancellationRegistry);
        var cancellationFailure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => cancelledClient.ModelsAsync("fixture"));
        Assert.Equal(cancellation.Token, cancellationFailure.CancellationToken);

        var sourceFailure = new InvalidOperationException("factory sentinel");
        var failedRegistry = Registry((_, _) => ValueTask.FromException<IAsyncDisposable>(sourceFailure), operations: [InferenceOperation.Embedding]);
        await using var failedClient = new AsyncClient([ProviderSettings.Of("fixture")], failedRegistry);
        var actual = await Assert.ThrowsAnyAsync<Exception>(() => failedClient.ModelsAsync("fixture"));
        Assert.Same(sourceFailure, actual);
    }

    [Fact]
    public async Task Previously_adopted_object_is_not_disposed_by_a_later_invalid_descriptor_binding()
    {
        var shared = new RetrievalLifecycleAdapter();
        var registry = new ProviderRegistry([
            new ProviderDescriptor("valid", "Valid", (_, _) => ValueTask.FromResult<IAsyncDisposable>(shared), operations: [InferenceOperation.Embedding]),
            new ProviderDescriptor("invalid", "Invalid", (_, _) => ValueTask.FromResult<IAsyncDisposable>(shared), operations: [InferenceOperation.Rerank]),
        ]);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("valid"), ProviderSettings.Of("invalid")],
            registry);
        Assert.Equal("embedding-model", Assert.Single(await client.ModelsAsync("valid")).Id);

        await Assert.ThrowsAsync<ConfigException>(() => client.ModelsAsync("invalid"));

        Assert.Equal(0, shared.DisposeCalls);
        Assert.Equal("embedding-model", Assert.Single(await client.ModelsAsync("valid")).Id);
        await client.DisposeAsync();
        Assert.Equal(1, shared.DisposeCalls);
    }

    [Fact]
    public async Task Valid_second_binding_of_an_adopted_adapter_disposes_its_unused_governed_transport_only()
    {
        var firstRaw = new RecordingHandler();
        var secondRaw = new RecordingHandler();
        HttpMessageHandler? firstFactoryTransport = null;
        HttpMessageHandler? secondFactoryTransport = null;
        TransportOwningRetrievalAdapter? shared = null;
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                "first",
                "First",
                (config, _) =>
                {
                    firstFactoryTransport = config.Transport;
                    shared = new TransportOwningRetrievalAdapter(config.Transport!);
                    return ValueTask.FromResult<IAsyncDisposable>(shared);
                },
                operations: [InferenceOperation.Embedding]),
            new ProviderDescriptor(
                "second",
                "Second",
                (config, _) =>
                {
                    secondFactoryTransport = config.Transport;
                    return ValueTask.FromResult<IAsyncDisposable>(shared!);
                },
                operations: [InferenceOperation.Embedding]),
        ]);
        var client = new AsyncClient(
            [
                ProviderSettings.Of("first", transport: firstRaw, limits: new RateLimits(maxConcurrent: 1, respectHeaders: false)),
                ProviderSettings.Of("second", transport: secondRaw, limits: new RateLimits(maxConcurrent: 1, respectHeaders: false)),
            ],
            registry);
        try
        {
            Assert.Equal("embedding-model", Assert.Single(await client.ModelsAsync("first")).Id);
            Assert.Equal("embedding-model", Assert.Single(await client.ModelsAsync("second")).Id);

            Assert.NotNull(shared);
            Assert.NotSame(firstRaw, firstFactoryTransport);
            Assert.NotSame(secondRaw, secondFactoryTransport);
            Assert.NotSame(firstFactoryTransport, secondFactoryTransport);
            Assert.Equal(0, shared!.DisposeCalls);
            Assert.Equal(0, firstRaw.DisposeCalls);
            Assert.Equal(1, secondRaw.DisposeCalls);
        }
        finally
        {
            await client.DisposeAsync();
        }

        Assert.Equal(1, shared!.DisposeCalls);
        Assert.Equal(1, firstRaw.DisposeCalls);
        Assert.Equal(1, secondRaw.DisposeCalls);
    }

    [Fact]
    public async Task Cancelled_second_shared_binding_discards_its_wrapper_without_publishing_or_reusing_the_adapter()
    {
        var firstRaw = new RecordingHandler();
        using var cancellation = new CancellationTokenSource();
        var secondRaw = new RecordingHandler(cancellation.Cancel);
        HttpMessageHandler? firstFactoryTransport = null;
        HttpMessageHandler? secondFactoryTransport = null;
        TransportOwningRetrievalAdapter? shared = null;
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                "first",
                "First",
                (config, _) =>
                {
                    firstFactoryTransport = config.Transport;
                    shared = new TransportOwningRetrievalAdapter(config.Transport!);
                    return ValueTask.FromResult<IAsyncDisposable>(shared);
                },
                operations: [InferenceOperation.Embedding]),
            new ProviderDescriptor(
                "second",
                "Second",
                (config, _) =>
                {
                    secondFactoryTransport = config.Transport;
                    return ValueTask.FromResult<IAsyncDisposable>(shared!);
                },
                operations: [InferenceOperation.Embedding]),
        ]);
        var client = new AsyncClient(
            [
                ProviderSettings.Of("first", transport: firstRaw, limits: new RateLimits(maxConcurrent: 1, respectHeaders: false)),
                ProviderSettings.Of("second", transport: secondRaw, limits: new RateLimits(maxConcurrent: 1, respectHeaders: false)),
            ],
            registry);
        try
        {
            Assert.Equal("embedding-model", Assert.Single(await client.ModelsAsync("first")).Id);

            var actual = await Assert.ThrowsAnyAsync<OperationCanceledException>(
                () => client.ModelsAsync("second", cancellationToken: cancellation.Token));

            Assert.Equal(cancellation.Token, actual.CancellationToken);
            Assert.NotNull(shared);
            Assert.NotSame(firstRaw, firstFactoryTransport);
            Assert.NotSame(secondRaw, secondFactoryTransport);
            Assert.NotSame(firstFactoryTransport, secondFactoryTransport);
            Assert.Equal(1, shared!.ModelsCalls);
            Assert.Equal(0, shared.DisposeCalls);
            Assert.Equal(0, firstRaw.DisposeCalls);
            Assert.Equal(1, secondRaw.DisposeCalls);
        }
        finally
        {
            await client.DisposeAsync();
        }

        Assert.Equal(1, shared!.DisposeCalls);
        Assert.Equal(1, firstRaw.DisposeCalls);
        Assert.Equal(1, secondRaw.DisposeCalls);
    }

    [Fact]
    public async Task Generation_acquires_an_embedding_only_descriptor_before_refusing_without_invoking_generate()
    {
        var adapter = new MultiProtocolAdapter();
        var factories = 0;
        var registry = Registry((_, _) =>
        {
            factories++;
            return ValueTask.FromResult<IAsyncDisposable>(adapter);
        }, operations: [InferenceOperation.Embedding]);
        var client = new AsyncClient([ProviderSettings.Of("fixture")], registry, route: new Route(["fixture:model"]));
        try
        {
            await Assert.ThrowsAsync<ConfigException>(() => client.GenerateAsync("prompt", target: "fixture:model"));
            Assert.Equal(1, factories);
            Assert.Equal(0, adapter.GenerateCalls);
            Assert.Equal(0, adapter.DisposeCalls);
        }
        finally
        {
            await client.DisposeAsync();
        }

        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Model_filter_respects_descriptor_operation_declarations_without_losing_generation_rows()
    {
        var embeddingFact = new ModelCapabilities(
            operations: new Sourced<IReadOnlySet<InferenceOperation>>(
                new HashSet<InferenceOperation> { InferenceOperation.Generation, InferenceOperation.Embedding },
                Provenance.Discovered));
        var adapter = new MultiProtocolAdapter([
            new DiscoveredModel("model", embeddingFact),
            new DiscoveredModel("static-embedding"),
        ]);
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                "fixture",
                "Fixture",
                (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
                operations: [InferenceOperation.Generation],
                staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities>
                {
                    ["static-embedding"] = new(),
                }),
        ]);
        await using var client = new AsyncClient([ProviderSettings.Of("fixture")], registry);

        Assert.Empty(await client.ModelsAsync("fixture", InferenceOperation.Embedding));
        Assert.Equal(
            new[] { "model", "static-embedding" },
            (await client.ModelsAsync("fixture", InferenceOperation.Generation)).Select(static model => model.Id));
    }

    [Fact]
    public async Task Pool_owned_configured_transport_survives_invalid_wrapper_discard_and_second_factory_generates()
    {
        var handler = new RecordingHandler();
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var calls = 0;
        HttpMessageHandler? observedTransport = null;
        var descriptor = CooperativeOpenAiDescriptor(async (config, cancellationToken) =>
        {
            observedTransport = config.Transport;
            if (Interlocked.Increment(ref calls) == 1)
            {
                return new NonClosingInvalidAdapter(config.Transport);
            }

            return await builtin.Factory(config, cancellationToken);
        }, poolOwnsTransport: true);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "secret", transport: handler, limits: new RateLimits(maxConcurrent: 1, respectHeaders: false))],
            new ProviderRegistry([descriptor]),
            route: new Route(["openai-compat:model"]));

        await Assert.ThrowsAsync<ConfigException>(() => client.ModelsAsync("openai-compat"));
        Assert.Equal(0, handler.DisposeCalls);
        Assert.NotSame(handler, observedTransport);

        Assert.Equal("ok", (await client.GenerateAsync("fresh", target: "openai-compat:model")).Text);
        Assert.Equal(2, calls);
        Assert.Equal(1, handler.SendCalls);

        await client.DisposeAsync();
        Assert.Equal(1, handler.DisposeCalls);
    }

    [Fact]
    public async Task Transferred_configured_transport_is_consumed_by_invalid_wrapper_and_second_build_refuses_before_factory()
    {
        var handler = new RecordingHandler();
        var calls = 0;
        HttpMessageHandler? observedTransport = null;
        var descriptor = CooperativeOpenAiDescriptor(async (config, cancellationToken) =>
        {
            calls++;
            observedTransport = config.Transport;
            await Task.Yield();
            return new NonClosingInvalidAdapter(config.Transport);
        }, poolOwnsTransport: false);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "secret", transport: handler, limits: new RateLimits(maxConcurrent: 1, respectHeaders: false))],
            new ProviderRegistry([descriptor]));

        await Assert.ThrowsAsync<ConfigException>(() => client.ModelsAsync("openai-compat"));
        await Assert.ThrowsAsync<ConfigException>(() => client.ModelsAsync("openai-compat"));

        Assert.Equal(1, calls);
        Assert.Equal(0, handler.SendCalls);
        Assert.Equal(1, handler.DisposeCalls);
        Assert.NotSame(handler, observedTransport);
    }

    [Fact]
    public async Task Invalid_nonclosing_adapter_releases_temporary_governed_transport_and_disposal_failure_precedes_refusal()
    {
        var handler = new RecordingHandler();
        HttpMessageHandler? observedTransport = null;
        var cleanupFailure = new InvalidOperationException("adapter cleanup sentinel");
        var invalid = new NonClosingInvalidAdapter(null, cleanupFailure);
        var descriptor = new ProviderDescriptor(
            "fixture",
            "Fixture",
            (config, _) =>
            {
                observedTransport = config.Transport;
                return ValueTask.FromResult<IAsyncDisposable>(invalid);
            },
            operations: [InferenceOperation.Embedding]);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("fixture", transport: handler, limits: new RateLimits(maxConcurrent: 1, respectHeaders: false))],
            new ProviderRegistry([descriptor]));

        var actual = await Assert.ThrowsAnyAsync<Exception>(() => client.ModelsAsync("fixture"));

        Assert.Same(cleanupFailure, actual);
        Assert.NotNull(observedTransport);
        Assert.NotSame(handler, observedTransport);
        Assert.Equal(1, invalid.DisposeCalls);
        Assert.Equal(1, handler.DisposeCalls);
    }

    [Fact]
    public async Task Client_close_joins_a_late_factory_return_and_disposes_it_once()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var late = new RetrievalLifecycleAdapter();
        var registry = Registry(async (_, _) =>
        {
            entered.TrySetResult();
            await release.Task;
            return late;
        }, operations: [InferenceOperation.Embedding]);
        var client = new AsyncClient([ProviderSettings.Of("fixture")], registry);
        try
        {
            var pending = client.ModelsAsync("fixture");
            await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var closing = client.DisposeAsync().AsTask();
            release.TrySetResult();

            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            await closing.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.Equal(1, late.DisposeCalls);
        }
        finally
        {
            release.TrySetResult();
            await client.DisposeAsync();
        }
    }

    private static ProviderRegistry Registry(
        Func<ProviderConfig, CancellationToken, ValueTask<IAsyncDisposable>> factory,
        IEnumerable<InferenceOperation> operations) =>
        new([new ProviderDescriptor("fixture", "Fixture", factory, operations: operations)]);

    private static ProviderDescriptor CooperativeOpenAiDescriptor(
        Func<ProviderConfig, CancellationToken, ValueTask<IAsyncDisposable>> factory,
        bool poolOwnsTransport)
    {
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        return new ProviderDescriptor(
            builtin.Id,
            builtin.DisplayName,
            factory,
            builtin.Aliases,
            builtin.Setup,
            builtin.DefaultBaseUrl,
            builtin.RequiresBaseUrl)
        {
            PoolOwnsConfiguredTransport = poolOwnsTransport,
        };
    }

    private sealed class RetrievalLifecycleAdapter(Exception? disposeFailure = null) : IEmbedsText, IProviderLifecycle, IAsyncDisposable
    {
        internal int ModelsCalls { get; private set; }
        internal int HealthCalls { get; private set; }
        internal int EmbedCalls { get; private set; }
        internal int DisposeCalls { get; private set; }

        public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
        {
            EmbedCalls++;
            return ValueTask.FromResult(new EmbeddingWireResult([[1d]]));
        }

        public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default)
        {
            ModelsCalls++;
            return ValueTask.FromResult<IReadOnlyList<DiscoveredModel>>([new DiscoveredModel("embedding-model")]);
        }

        public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default)
        {
            HealthCalls++;
            return ValueTask.FromResult(new Health(true));
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return disposeFailure is null ? ValueTask.CompletedTask : ValueTask.FromException(disposeFailure);
        }
    }

    private sealed class LifecycleOnlyAdapter(Exception? disposeFailure = null) : IProviderLifecycle, IAsyncDisposable
    {
        internal int ModelsCalls { get; private set; }
        internal int DisposeCalls { get; private set; }

        public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default)
        {
            ModelsCalls++;
            return ValueTask.FromResult<IReadOnlyList<DiscoveredModel>>([new DiscoveredModel("wrong")]);
        }

        public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult(new Health(true));

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return disposeFailure is null ? ValueTask.CompletedTask : ValueTask.FromException(disposeFailure);
        }
    }

    private sealed class NonClosingInvalidAdapter(HttpMessageHandler? transport, Exception? disposeFailure = null) : IAsyncDisposable
    {
        internal HttpMessageHandler? Transport { get; } = transport;
        internal int DisposeCalls { get; private set; }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return disposeFailure is null ? ValueTask.CompletedTask : ValueTask.FromException(disposeFailure);
        }
    }

    private sealed class MultiProtocolAdapter : IProviderAdapter, IEmbedsText, IReranksText, IProviderLifecycle
    {
        private readonly IReadOnlyList<DiscoveredModel> _models;

        internal MultiProtocolAdapter(IReadOnlyList<DiscoveredModel>? models = null) =>
            _models = models ?? [new DiscoveredModel("embedding-model")];

        internal int GenerateCalls { get; private set; }
        internal int DisposeCalls { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
            WireRequest request,
            [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            await Task.Yield();
            yield break;
        }

        public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default) =>
            ValueTask.FromResult(new EmbeddingWireResult([[1d]]));

        public ValueTask<RerankWireResult> RerankAsync(RerankWireRequest request, CancellationToken cancellationToken = default) =>
            ValueTask.FromResult(new RerankWireResult([]));

        public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default) =>
            ValueTask.FromResult(_models);

        public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult(new Health(true));

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class TransportOwningRetrievalAdapter(HttpMessageHandler transport) : IEmbedsText, IProviderLifecycle, IAsyncDisposable
    {
        internal int DisposeCalls { get; private set; }
        internal int ModelsCalls { get; private set; }

        public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default) =>
            ValueTask.FromResult(new EmbeddingWireResult([[1d]]));

        public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default)
        {
            ModelsCalls++;
            return ValueTask.FromResult<IReadOnlyList<DiscoveredModel>>([new DiscoveredModel("embedding-model")]);
        }

        public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult(new Health(true));

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            transport.Dispose();
            return ValueTask.CompletedTask;
        }
    }

    private sealed class RecordingHandler(Action? onDispose = null) : HttpMessageHandler
    {
        internal int SendCalls { get; private set; }
        internal int DisposeCalls { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            SendCalls++;
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/v1/chat/completions", request.RequestUri!.AbsolutePath);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""",
                    Encoding.UTF8,
                    "application/json"),
            });
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                DisposeCalls++;
                onDispose?.Invoke();
            }

            base.Dispose(disposing);
        }
    }
}
