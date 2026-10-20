using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Credentials;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public lifecycle-query behavior over lazy provider instances.</summary>
public sealed class ProviderLifecycleTests
{
    [Fact]
    public async Task Models_selects_the_exact_configured_instance_and_snapshots_the_adapter_list()
    {
        var primary = new LifecycleAdapter(models: [new DiscoveredModel("primary-model")]);
        var secondaryModels = new List<DiscoveredModel> { new("secondary-model"), new("id-only") };
        var secondary = new LifecycleAdapter(models: secondaryModels);
        var factories = new List<string>();
        var registry = Registry((config, _) =>
        {
            factories.Add(config.ProviderId);
            return ValueTask.FromResult<IAsyncDisposable>(config.ProviderId == "primary" ? primary : secondary);
        });

        await using var client = new AsyncClient(
            [ProviderSettings.Of("fake", alias: "primary"), ProviderSettings.Of("fake", alias: "secondary")],
            registry);

        var result = await client.ModelsAsync(" secondary ");
        secondaryModels.Clear();

        Assert.Equal(["secondary-model", "id-only"], result.Select(static model => model.Id));
        Assert.Equal(["secondary"], factories);
        Assert.Equal(0, primary.ListCalls);
        Assert.Equal(1, secondary.ListCalls);
    }

    [Fact]
    public async Task Lifecycle_selector_uses_exact_instance_or_a_distinct_engine_default_and_unknown_work_is_rejected_before_factory()
    {
        var tenant = new LifecycleAdapter(models: [new DiscoveredModel("tenant-model")]);
        var defaultInstance = new LifecycleAdapter(models: [new DiscoveredModel("default-model")]);
        var factories = new List<string>();
        var registry = Registry((config, _) =>
        {
            factories.Add(config.ProviderId);
            return ValueTask.FromResult<IAsyncDisposable>(config.ProviderId == "tenant" ? tenant : defaultInstance);
        });
        await using var client = new AsyncClient([ProviderSettings.Of("fake", alias: "tenant")], registry);

        Assert.Equal("tenant-model", Assert.Single(await client.ModelsAsync("tenant")).Id);
        Assert.Equal("default-model", Assert.Single(await client.ModelsAsync("fake")).Id);
        await Assert.ThrowsAsync<ConfigException>(() => client.ModelsAsync("unknown"));

        Assert.Equal(["tenant", "fake"], factories);
        Assert.Equal(1, tenant.ListCalls);
        Assert.Equal(1, defaultInstance.ListCalls);
    }

    [Fact]
    public async Task Models_filter_uses_known_operations_then_static_embedding_facts_without_replacing_discovery()
    {
        var models = new[] { new DiscoveredModel("static-embedding"), new DiscoveredModel("id-only") };
        var adapter = new EmbeddingLifecycleAdapter(new LifecycleAdapter(models: models));
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                "fake",
                "Fake",
                (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
                operations: [InferenceOperation.Generation, InferenceOperation.Embedding],
                staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities>
                {
                    ["static-embedding"] = new(),
                })]);
        await using var client = new AsyncClient([ProviderSettings.Of("fake", alias: "tenant")], registry);

        var filtered = await client.ModelsAsync("tenant", InferenceOperation.Embedding);
        var complete = await client.ModelsAsync("tenant");

        Assert.Equal(["static-embedding"], filtered.Select(static model => model.Id));
        Assert.Equal(["static-embedding", "id-only"], complete.Select(static model => model.Id));
        Assert.Equal(2, adapter.ListCalls);
    }

    [Fact]
    public async Task Known_empty_operations_are_authoritative_while_unknown_models_use_static_and_generation_fallbacks()
    {
        var knownEmpty = new ModelCapabilities(operations: new Sourced<IReadOnlySet<InferenceOperation>>(
            new HashSet<InferenceOperation>(), Provenance.Discovered));
        var adapter = new EmbeddingLifecycleAdapter(new LifecycleAdapter(models: [
            new DiscoveredModel("known-empty", knownEmpty),
            new DiscoveredModel("static-embedding"),
            new DiscoveredModel("unknown"),
        ]));
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
                operations: [InferenceOperation.Generation, InferenceOperation.Embedding],
                staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities> { ["static-embedding"] = new() })]);
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], registry);

        Assert.Equal(["static-embedding"], (await client.ModelsAsync("fake", InferenceOperation.Embedding)).Select(static model => model.Id));
        Assert.Equal(["static-embedding", "unknown"], (await client.ModelsAsync("fake", InferenceOperation.Generation)).Select(static model => model.Id));
    }

    [Fact]
    public void Synchronous_models_and_health_mirror_the_public_async_lifecycle_surface()
    {
        var adapter = new LifecycleAdapter(models: [new DiscoveredModel("sync-model")]);
        using var client = Client.FromAdapters([new ProviderRegistration("sync", adapter)]);

        Assert.Equal("sync-model", Assert.Single(client.Models("sync")).Id);
        Assert.True(client.Health("sync").Ok);
        Assert.Equal(1, adapter.ListCalls);
        Assert.Equal(1, adapter.HealthCalls);
    }

    [Fact]
    public async Task Lifecycle_unsupported_generation_only_adapter_refuses_without_fabricating_results()
    {
        var adapter = new GenerationOnlyAdapter();
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("plain", adapter)]);

        var models = await Assert.ThrowsAsync<UnsupportedInputException>(() => client.ModelsAsync("plain"));
        var health = await Assert.ThrowsAsync<UnsupportedInputException>(() => client.HealthAsync("plain"));

        Assert.Equal("plain", models.Provider);
        Assert.Equal("discover", models.Phase);
        Assert.Equal("plain", health.Provider);
        Assert.Equal("discover", health.Phase);
        Assert.Equal(0, adapter.GenerateCalls);
    }

    [Fact]
    public async Task Undefined_operation_refuses_before_factory_or_lifecycle_dispatch_and_client_remains_usable()
    {
        var adapter = new LifecycleAdapter(models: [new DiscoveredModel("model")]);
        var factoryCalls = 0;
        var registry = Registry((_, _) =>
        {
            factoryCalls++;
            return ValueTask.FromResult<IAsyncDisposable>(adapter);
        });
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], registry);

        var failure = await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() =>
            client.ModelsAsync("fake", (InferenceOperation)999));

        Assert.Equal("operation", failure.ParamName);
        Assert.Equal(0, factoryCalls);
        Assert.Equal(0, adapter.ListCalls);
        Assert.Equal(["model"], (await client.ModelsAsync("fake")).Select(static model => model.Id));
    }

    [Fact]
    public async Task Prebuilt_lifecycle_adapter_records_discovery_facts_without_a_descriptor_and_keeps_id_only_facts_unknown()
    {
        var known = new ModelCapabilities(contextWindow: new Sourced<int>(4096, Provenance.Discovered));
        var adapter = new LifecycleAdapter(models: [new DiscoveredModel("known", known), new DiscoveredModel("id-only")]);
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("direct", adapter)]);

        Assert.Equal(["known", "id-only"], (await client.ModelsAsync("direct")).Select(static model => model.Id));

        Assert.Equal(4096, client.Capabilities("direct:known").ContextWindow!.Value);
        Assert.Null(client.Capabilities("direct:id-only").ContextWindow);
        Assert.Equal(1, adapter.ListCalls);
    }

    [Fact]
    public async Task Concurrent_models_health_and_generation_share_the_lazy_adapter_without_serializing_adapter_io()
    {
        var modelsEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var healthEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var generationEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new LifecycleAdapter(
            models: [new DiscoveredModel("model")],
            list: async token =>
            {
                modelsEntered.TrySetResult();
                await release.Task.WaitAsync(token);
                return [new DiscoveredModel("model")];
            },
            health: async token =>
            {
                healthEntered.TrySetResult();
                await release.Task.WaitAsync(token);
                return new Health(true, "ready");
            },
            generateEntered: generationEntered,
            generateRelease: release);
        var registry = Registry((_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter));
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], registry, route: new Route(["fake:model"]));

        var listing = client.ModelsAsync("fake");
        var health = client.HealthAsync("fake");
        var generation = client.GenerateAsync("hello");
        await Task.WhenAll(modelsEntered.Task, healthEntered.Task, generationEntered.Task).WaitAsync(TimeSpan.FromSeconds(5));
        release.TrySetResult();

        Assert.Equal("model", Assert.Single(await listing).Id);
        Assert.True((await health).Ok);
        Assert.Equal("ok", (await generation).Text);
        Assert.Equal(1, adapter.ListCalls);
        Assert.Equal(1, adapter.HealthCalls);
        Assert.Equal(1, adapter.GenerateCalls);
    }

    [Fact]
    public async Task Caller_cancelled_listing_that_ignores_its_token_is_discarded_before_discovery_publication()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var listed = new ModelCapabilities(contextWindow: new Sourced<int>(8192, Provenance.Discovered));
        var adapter = new LifecycleAdapter(
            models: [],
            list: async _ =>
            {
                entered.TrySetResult();
                await release.Task;
                return [new DiscoveredModel("late", listed)];
            });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("direct", adapter)]);
        using var cancellation = new CancellationTokenSource();
        var pending = client.ModelsAsync("direct", cancellationToken: cancellation.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        cancellation.Cancel();
        release.TrySetResult();

        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(cancellation.Token, failure.CancellationToken);
        Assert.Null(client.Capabilities("direct:late").ContextWindow);
    }

    [Fact]
    public async Task Cancelled_waiter_leaves_the_owner_factory_and_later_listing_usable()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new LifecycleAdapter(models: [new DiscoveredModel("model")]);
        var factories = 0;
        var registry = Registry(async (_, token) =>
        {
            factories++;
            entered.TrySetResult();
            await release.Task.WaitAsync(token);
            return adapter;
        });
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], registry);

        var owner = client.ModelsAsync("fake");
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        var waiter = client.ModelsAsync("fake", cancellationToken: cancelled.Token);

        var waiterFailure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => waiter);
        Assert.Equal(cancelled.Token, waiterFailure.CancellationToken);
        release.TrySetResult();
        Assert.Equal("model", Assert.Single(await owner).Id);
        Assert.Equal(1, factories);
        Assert.Equal(1, adapter.ListCalls);
    }

    [Fact]
    public async Task Late_factory_return_after_caller_cancellation_is_disposed_and_not_adopted()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var discarded = new LifecycleAdapter(models: [new DiscoveredModel("discarded")]);
        var retained = new LifecycleAdapter(models: [new DiscoveredModel("retained")]);
        var factoryCalls = 0;
        var registry = Registry(async (_, _) =>
        {
            if (Interlocked.Increment(ref factoryCalls) == 1)
            {
                entered.TrySetResult();
                await release.Task;
                return discarded;
            }

            return retained;
        });
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], registry);
        using var cancellation = new CancellationTokenSource();
        var pending = client.ModelsAsync("fake", cancellationToken: cancellation.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        cancellation.Cancel();
        release.TrySetResult();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(1, discarded.DisposeCalls);
        Assert.Equal(0, discarded.ListCalls);
        Assert.Equal("retained", Assert.Single(await client.ModelsAsync("fake")).Id);
        Assert.Equal(2, factoryCalls);
    }

    [Fact]
    public async Task Factory_and_lifecycle_source_failures_preserve_the_original_exception_object()
    {
        var factoryFailure = new InvalidOperationException("factory sentinel");
        var factoryRegistry = Registry((_, _) => ValueTask.FromException<IAsyncDisposable>(factoryFailure));
        await using var factoryClient = new AsyncClient([ProviderSettings.Of("fake")], factoryRegistry);
        var observedFactory = await Assert.ThrowsAnyAsync<Exception>(() => factoryClient.ModelsAsync("fake"));
        Assert.Same(factoryFailure, observedFactory);

        var lifecycleFailure = new OperationCanceledException("adapter sentinel");
        var adapter = new LifecycleAdapter(models: [], list: _ => ValueTask.FromException<IReadOnlyList<DiscoveredModel>>(lifecycleFailure));
        await using var lifecycleClient = AsyncClient.FromAdapters([new ProviderRegistration("plain", adapter)]);
        var observedLifecycle = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => lifecycleClient.ModelsAsync("plain"));
        Assert.Same(lifecycleFailure, observedLifecycle);
    }

    [Fact]
    public async Task Async_client_owned_factory_and_unsafe_cancellation_callbacks_refuse_self_dispose_without_closing_the_client()
    {
        AsyncClient? client = null;
        var adapter = new LifecycleAdapter(models: [new DiscoveredModel("model")]);
        var registry = Registry((_, _) =>
        {
            Assert.Throws<InvalidOperationException>(() => client!.DisposeAsync());
            return ValueTask.FromResult<IAsyncDisposable>(adapter);
        });
        client = new AsyncClient([ProviderSettings.Of("fake")], registry);
        Assert.Equal("model", Assert.Single(await client.ModelsAsync("fake")).Id);

        var cancellationEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var unsafeRegistered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        Exception? callbackFailure = null;
        var callbackAdapter = new LifecycleAdapter(
            models: [],
            list: async token =>
            {
                using var registration = token.UnsafeRegister(_ =>
                {
                    callbackFailure = Record.Exception(() => client.DisposeAsync());
                    cancellationEntered.TrySetResult();
                }, null);
                unsafeRegistered.TrySetResult();
                await Task.Delay(Timeout.InfiniteTimeSpan, token);
                return [];
            });
        await client.DisposeAsync();
        client = AsyncClient.FromAdapters([new ProviderRegistration("callback", callbackAdapter)]);
        var pending = client.ModelsAsync("callback");
        await unsafeRegistered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var closing = client.DisposeAsync().AsTask();
        await cancellationEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        await closing;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.IsType<InvalidOperationException>(callbackFailure);
    }

    [Fact]
    public async Task Resolver_callback_refuses_async_self_dispose_before_pool_adoption_and_external_disposal_still_closes_once()
    {
        AsyncClient? client = null;
        var adapter = new LifecycleAdapter(models: [new DiscoveredModel("model")]);
        var resolver = new SelfDisposingResolver("custom://lifecycle", () => client!.DisposeAsync());
        var registry = Registry((_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter));
        client = new AsyncClient([ProviderSettings.Of("fake", apiKey: "custom://lifecycle")], registry, new ResolverChain([resolver]));

        Assert.Equal("model", Assert.Single(await client.ModelsAsync("fake")).Id);
        Assert.Equal(1, resolver.ResolveCalls);
        Assert.Equal(1, adapter.ListCalls);
        await client.DisposeAsync();
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public void Captured_sync_client_refuses_self_dispose_from_factory_models_and_health_callbacks_before_external_close()
    {
        Client? client = null;
        var callbackFailures = new ConcurrentQueue<Exception?>();
        var adapter = new LifecycleAdapter(
            models: [new DiscoveredModel("model")],
            list: _ =>
            {
                callbackFailures.Enqueue(Record.Exception(() => client!.Dispose()));
                return ValueTask.FromResult<IReadOnlyList<DiscoveredModel>>([new DiscoveredModel("model")]);
            },
            health: _ =>
            {
                callbackFailures.Enqueue(Record.Exception(() => client!.Dispose()));
                return ValueTask.FromResult(new Health(true));
            });
        var registry = Registry((_, _) =>
        {
            callbackFailures.Enqueue(Record.Exception(() => client!.Dispose()));
            return ValueTask.FromResult<IAsyncDisposable>(adapter);
        });
        client = new Client([ProviderSettings.Of("fake")], registry);

        Assert.Equal("model", Assert.Single(client.Models("fake")).Id);
        Assert.True(client.Health("fake").Ok);
        Assert.Equal(3, callbackFailures.Count);
        Assert.All(callbackFailures, static failure => Assert.IsType<InvalidOperationException>(failure));
        Assert.Equal(1, adapter.ListCalls);
        Assert.Equal(1, adapter.HealthCalls);
        client.Dispose();
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Secret_option_resolver_success_followed_by_caller_cancellation_uses_the_original_token_before_factory_dispatch()
    {
        using var cancellation = new CancellationTokenSource();
        var resolver = new CallbackResolver("vault://option", _ =>
        {
            cancellation.Cancel();
            return ValueTask.FromResult("resolved-option");
        });
        var factoryCalls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) =>
            {
                factoryCalls++;
                return ValueTask.FromResult<IAsyncDisposable>(new LifecycleAdapter(models: []));
            }, setup: new ProviderSetupSpec([new SetupField("token", "Token", "secret")]))]);
        var options = new JsonObject([new JsonProperty("token", new JsonString("vault://option"))]);
        await using var client = new AsyncClient([ProviderSettings.Of("fake", options: options)], registry, new ResolverChain([resolver]));

        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => client.ModelsAsync("fake", cancellationToken: cancellation.Token));

        Assert.Equal(cancellation.Token, failure.CancellationToken);
        Assert.Equal(1, resolver.ResolveCalls);
        Assert.Equal(0, factoryCalls);
    }

    [Fact]
    public async Task Resolver_thrown_operation_cancellation_preserves_its_original_object_even_when_the_caller_is_cancelled()
    {
        using var cancellation = new CancellationTokenSource();
        var sentinel = new OperationCanceledException("resolver sentinel");
        var resolver = new CallbackResolver("vault://throws", _ =>
        {
            cancellation.Cancel();
            return ValueTask.FromException<string>(sentinel);
        });
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", static (_, _) => ValueTask.FromResult<IAsyncDisposable>(new LifecycleAdapter(models: [])),
                setup: new ProviderSetupSpec([new SetupField("token", "Token", "secret")]))]);
        var options = new JsonObject([new JsonProperty("token", new JsonString("vault://throws"))]);
        await using var client = new AsyncClient([ProviderSettings.Of("fake", options: options)], registry, new ResolverChain([resolver]));

        var actual = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => client.ModelsAsync("fake", cancellationToken: cancellation.Token));

        Assert.Same(sentinel, actual);
    }

    [Fact]
    public async Task Captured_sync_client_unsafe_cancellation_callbacks_refuse_self_dispose_and_external_close_joins_both_lifecycle_calls()
    {
        Client? client = null;
        var registrations = 0;
        var callbackFailures = new ConcurrentQueue<Exception?>();
        var unsafeRegistered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        void Register(CancellationToken token)
        {
            token.UnsafeRegister(_ =>
            {
                callbackFailures.Enqueue(Record.Exception(() => client!.Dispose()));
            }, null);
            if (Interlocked.Increment(ref registrations) == 2) unsafeRegistered.TrySetResult();
        }

        var adapter = new LifecycleAdapter(
            models: [],
            list: async token =>
            {
                Register(token);
                await Task.Delay(Timeout.InfiniteTimeSpan, token);
                return [];
            },
            health: async token =>
            {
                Register(token);
                await Task.Delay(Timeout.InfiniteTimeSpan, token);
                return new Health(true);
            });
        client = Client.FromAdapters([new ProviderRegistration("sync", adapter)]);
        var models = Task.Run(() => client.Models("sync"));
        var health = Task.Run(() => client.Health("sync"));
        await unsafeRegistered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        await Task.Run(client.Dispose);

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => models);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => health);
        Assert.Equal(2, callbackFailures.Count);
        Assert.All(callbackFailures, static failure => Assert.IsType<InvalidOperationException>(failure));
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Client_close_signals_lifecycle_and_generation_before_joining_and_disposes_the_adopted_adapter_once()
    {
        var entered = 0;
        var allEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new LifecycleAdapter(
            models: [],
            list: token => BlockLifecycle(token, () => Signal()),
            health: token => BlockHealth(token, () => Signal()),
            generateEntered: null,
            generateRelease: null,
            generateBlock: token => BlockGeneration(token, () => Signal()));
        var registry = Registry((_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter));
        var client = new AsyncClient([ProviderSettings.Of("fake")], registry, route: new Route(["fake:model"]));

        var listing = client.ModelsAsync("fake");
        var health = client.HealthAsync("fake");
        var generation = client.GenerateAsync("hello");
        await allEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        await client.DisposeAsync();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => listing);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => health);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => generation);
        Assert.Equal(1, adapter.DisposeCalls);

        void Signal()
        {
            if (Interlocked.Increment(ref entered) == 3)
            {
                allEntered.TrySetResult();
            }
        }
    }

    [Fact]
    public async Task Throwing_lifecycle_cancellation_callback_does_not_prevent_close_from_signalling_every_operation()
    {
        var entered = 0;
        var allEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var sentinel = new InvalidOperationException("callback sentinel");
        var adapter = new LifecycleAdapter(
            models: [],
            list: async token =>
            {
                var delay = Task.Delay(Timeout.InfiniteTimeSpan, token);
                using var registration = token.Register(() => throw sentinel);
                Signal();
                await delay;
                return [];
            },
            health: token => BlockHealth(token, Signal),
            generateBlock: token => BlockGeneration(token, Signal));
        var registry = Registry((_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter));
        var client = new AsyncClient([ProviderSettings.Of("fake")], registry, route: new Route(["fake:model"]));
        var listing = client.ModelsAsync("fake");
        var health = client.HealthAsync("fake");
        var generation = client.GenerateAsync("hello");
        await allEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        var closeFailure = await Assert.ThrowsAnyAsync<Exception>(() => client.DisposeAsync().AsTask());

        Assert.True(ContainsReference(closeFailure, sentinel));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => listing);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => health);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => generation);
        Assert.Equal(1, adapter.DisposeCalls);

        void Signal()
        {
            if (Interlocked.Increment(ref entered) == 3) allEntered.TrySetResult();
        }
    }

    [Fact]
    public async Task Client_close_discards_a_token_ignoring_late_factory_return_before_it_can_be_adopted()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var late = new LifecycleAdapter(models: [new DiscoveredModel("late")]);
        var registry = Registry(async (_, _) =>
        {
            entered.TrySetResult();
            await release.Task;
            return late;
        });
        var client = new AsyncClient([ProviderSettings.Of("fake")], registry);
        var listing = client.ModelsAsync("fake");
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        var close = client.DisposeAsync().AsTask();
        release.TrySetResult();
        await close;

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => listing);
        Assert.Equal(1, late.DisposeCalls);
        Assert.Equal(0, late.ListCalls);
    }

    private static ProviderRegistry Registry(Func<ProviderConfig, CancellationToken, ValueTask<IAsyncDisposable>> factory) =>
        new([new ProviderDescriptor("fake", "Fake", factory)]);

    private sealed class LifecycleAdapter : IProviderAdapter, IProviderLifecycle
    {
        private readonly IReadOnlyList<DiscoveredModel> _models;
        private readonly Func<CancellationToken, ValueTask<IReadOnlyList<DiscoveredModel>>>? _list;
        private readonly Func<CancellationToken, ValueTask<Health>>? _health;
        private readonly TaskCompletionSource? _generateEntered;
        private readonly TaskCompletionSource? _generateRelease;
        private readonly Func<CancellationToken, IAsyncEnumerable<AdapterEvent>>? _generateBlock;

        internal LifecycleAdapter(
            IReadOnlyList<DiscoveredModel> models,
            Func<CancellationToken, ValueTask<IReadOnlyList<DiscoveredModel>>>? list = null,
            Func<CancellationToken, ValueTask<Health>>? health = null,
            TaskCompletionSource? generateEntered = null,
            TaskCompletionSource? generateRelease = null,
            Func<CancellationToken, IAsyncEnumerable<AdapterEvent>>? generateBlock = null)
        {
            _models = models;
            _list = list;
            _health = health;
            _generateEntered = generateEntered;
            _generateRelease = generateRelease;
            _generateBlock = generateBlock;
        }

        internal int ListCalls { get; private set; }
        internal int HealthCalls { get; private set; }
        internal int GenerateCalls { get; private set; }
        internal int DisposeCalls { get; private set; }

        public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default)
        {
            ListCalls++;
            return _list is null ? ValueTask.FromResult(_models) : _list(cancellationToken);
        }

        public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default)
        {
            HealthCalls++;
            return _health is null ? ValueTask.FromResult(new Health(true, "ready")) : _health(cancellationToken);
        }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            if (_generateBlock is not null)
            {
                await foreach (var item in _generateBlock(cancellationToken).WithCancellation(cancellationToken))
                {
                    yield return item;
                }
                yield break;
            }
            _generateEntered?.TrySetResult();
            if (_generateRelease is not null)
            {
                await _generateRelease.Task.WaitAsync(cancellationToken);
            }

            yield return new AdapterTextDelta("ok");
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class EmbeddingLifecycleAdapter(LifecycleAdapter inner) : IProviderAdapter, IProviderLifecycle, IEmbedsText
    {
        internal int ListCalls => inner.ListCalls;

        public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default) =>
            inner.ListModelsAsync(cancellationToken);

        public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default) =>
            inner.HealthAsync(cancellationToken);

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            inner.GenerateAsync(request, cancellationToken);

        public ValueTask<EmbeddingWireResult> EmbedAsync(EmbeddingWireRequest request, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return ValueTask.FromResult(new EmbeddingWireResult(request.Inputs.Select(static _ => new[] { 0d }), request.Model));
        }

        public ValueTask DisposeAsync() => inner.DisposeAsync();
    }

    private static async ValueTask<IReadOnlyList<DiscoveredModel>> BlockLifecycle(CancellationToken token, Action entered)
    {
        entered();
        await Task.Delay(Timeout.InfiniteTimeSpan, token);
        return [];
    }

    private static async ValueTask<Health> BlockHealth(CancellationToken token, Action entered)
    {
        entered();
        await Task.Delay(Timeout.InfiniteTimeSpan, token);
        return new Health(true);
    }

    private static async IAsyncEnumerable<AdapterEvent> BlockGeneration([EnumeratorCancellation] CancellationToken token, Action entered)
    {
        entered();
        await Task.Delay(Timeout.InfiniteTimeSpan, token);
        yield break;
    }

    private static bool ContainsReference(Exception actual, Exception expected) =>
        ReferenceEquals(actual, expected) ||
        actual is AggregateException aggregate && aggregate.InnerExceptions.Any(item => ContainsReference(item, expected)) ||
        actual.InnerException is { } inner && ContainsReference(inner, expected);

    private sealed class GenerationOnlyAdapter : IProviderAdapter
    {
        internal int GenerateCalls { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterTextDelta("ok");
            await Task.Yield();
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class SelfDisposingResolver(string reference, Func<ValueTask> dispose) : ICredentialResolver
    {
        internal int ResolveCalls { get; private set; }
        public bool Handles(string candidate) => candidate == reference;
        public ValueTask<string> ResolveAsync(string candidate, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Assert.Equal(reference, candidate);
            Assert.IsType<InvalidOperationException>(Record.Exception(() => dispose()));
            ResolveCalls++;
            return ValueTask.FromResult("resolver-secret");
        }
    }

    private sealed class CallbackResolver(string reference, Func<CancellationToken, ValueTask<string>> callback) : ICredentialResolver
    {
        internal int ResolveCalls { get; private set; }
        public bool Handles(string candidate) => candidate == reference;
        public ValueTask<string> ResolveAsync(string candidate, CancellationToken cancellationToken = default)
        {
            Assert.Equal(reference, candidate);
            ResolveCalls++;
            return callback(cancellationToken);
        }
    }
}
