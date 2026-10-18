using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Config;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

using Catalog = global::AnyInfer.Catalog.Catalog;

/// <summary>Public CAT.3 descriptor metadata and pure client capability-query controls.</summary>
public sealed class ProviderCapabilityTests
{
    [Fact]
    public void Descriptor_validates_locality_and_snapshots_metadata_collections()
    {
        var staticFacts = new Dictionary<string, ModelCapabilities>
        {
            ["model"] = new ModelCapabilities(contextWindow: new Sourced<int>(4096, Provenance.Catalog)),
        };
        var operations = new List<InferenceOperation> { InferenceOperation.Generation, InferenceOperation.Embedding };
        var descriptor = Descriptor(
            locality: ProviderLocality.Local,
            staticCapabilities: staticFacts,
            operations: operations,
            staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities> { ["model"] = new(dimensions: 384) },
            staticRerankCapabilities: new Dictionary<string, RerankCapabilities> { ["model"] = new(maxDocuments: 4, nativeTopN: true) },
            tokenCalibration: new TokenCalibration(1.25, 3, TokenizerKind.Tiktoken, Provenance.Catalog),
            rateLimitHeaders: new RateLimitHeaders("remain", "reset", "tokens", "tokens-reset"));
        staticFacts.Clear();
        operations.Clear();

        Assert.Equal(ProviderLocality.Local, descriptor.Locality);
        Assert.Equal(4096, descriptor.StaticCapabilities["model"].ContextWindow!.Value);
        Assert.Contains(InferenceOperation.Embedding, descriptor.Operations);
        Assert.Equal(384, descriptor.StaticEmbeddingCapabilities["model"].Dimensions);
        Assert.True(descriptor.StaticRerankCapabilities["model"].NativeTopN);
        Assert.Equal(1.25, descriptor.TokenCalibration!.Multiplier);
        Assert.True(descriptor.RateLimitHeaders!.Declared);
        Assert.Throws<ArgumentOutOfRangeException>(() => Descriptor(locality: (ProviderLocality)99));
        Assert.Throws<ArgumentOutOfRangeException>(() => Descriptor(operations: [(InferenceOperation)99]));

        var defaults = Descriptor();
        Assert.NotNull(defaults.TokenCalibration);
        Assert.True(defaults.TokenCalibration!.IsIdentity);
        Assert.NotNull(defaults.RateLimitHeaders);
        Assert.False(defaults.RateLimitHeaders!.Declared);
    }

    [Fact]
    public async Task Pure_queries_use_configured_instance_pricing_and_overrides_without_factory_or_network_work_and_survive_close()
    {
        var factoryCalls = 0;
        var catalog = CatalogWithAliases(("alias-a", "primary", "model"), ("alias-b", "primary", "model"));
        var table = new PricingTable(new Dictionary<string, IReadOnlyList<PricingEntry>>
        {
            ["primary"] = [new PricingEntry("model", new Pricing(2m, 3m), "2026-01-01", "https://example.invalid/primary")],
            ["engine"] = [new PricingEntry("model", new Pricing(99m, 99m), "2026-01-01", "https://example.invalid/engine")],
        });
        var overrides = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>
        {
            ["primary"] = new Dictionary<string, ModelCapabilities>
            {
                ["model"] = new ModelCapabilities(
                    contextWindow: new Sourced<int>(0, Provenance.Default),
                    features: new Sourced<Feature>(Feature.None, Provenance.Default)),
            },
        };
        var registry = new ProviderRegistry([
            Descriptor(
                factory: (_, _) =>
                {
                    factoryCalls++;
                    return ValueTask.FromException<IProviderAdapter>(new InvalidOperationException("Pure metadata queries must not construct adapters."));
                },
                locality: ProviderLocality.Local,
                defaultCapabilities: new ModelCapabilities(features: new Sourced<Feature>(Feature.JsonSchema, Provenance.Catalog)),
                staticCapabilities: new Dictionary<string, ModelCapabilities>
                {
                    ["model"] = new ModelCapabilities(contextWindow: new Sourced<int>(4096, Provenance.Catalog)),
                })
        ]);
        var settings = ProviderSettings.Of("engine", alias: "primary");
        var client = new AsyncClient([settings], registry, catalog: catalog, pricingTable: table, capabilityOverrides: overrides);
        try
        {
            var first = client.Resolve("alias-a");
            var second = client.Resolve("alias-b");
            var capabilities = client.Capabilities("alias-a");

            Assert.Equal("primary", first.ProviderId);
            Assert.Equal("model", first.Model);
            Assert.Equal("alias-a", first.ViaAlias);
            Assert.Equal(first.ProviderId, second.ProviderId);
            Assert.Equal(0, capabilities.ContextWindow!.Value);
            Assert.Equal(Provenance.Override, capabilities.ContextWindow.Provenance);
            Assert.Equal(Feature.JsonSchema, capabilities.Features.Value);
            Assert.Equal(2m, capabilities.Pricing!.Value.InputPer1M);
            Assert.Equal(Provenance.Catalog, capabilities.Pricing.Provenance);
            Assert.Equal(0, factoryCalls);

            await client.DisposeAsync();
            Assert.Equal(first, client.Resolve("alias-a"));
            Assert.Equal(capabilities, client.Capabilities("alias-a"));
            Assert.Equal(0, factoryCalls);
        }
        finally
        {
            await client.DisposeAsync();
        }
    }

    [Fact]
    public async Task Effective_locality_adds_zero_price_only_for_local_absent_pricing_and_prebuilt_clients_keep_unknown_facts()
    {
        var catalog = CatalogWithAliases(("tier", "primary", "model"));
        var registry = new ProviderRegistry([Descriptor(locality: ProviderLocality.Local)]);

        await using var local = new AsyncClient([ProviderSettings.Of("engine", alias: "primary")], registry, catalog: catalog, pricingTable: new PricingTable(new Dictionary<string, IReadOnlyList<PricingEntry>>()));
        var localFacts = local.Capabilities("tier");
        Assert.Equal(0m, localFacts.Pricing!.Value.InputPer1M);
        Assert.Equal(0m, localFacts.Pricing.Value.OutputPer1M);
        Assert.Equal(Provenance.Catalog, localFacts.Pricing.Provenance);

        await using var remote = new AsyncClient([ProviderSettings.Of("engine", baseUrl: "https://remote.example/v1", alias: "primary")], registry, catalog: catalog, pricingTable: new PricingTable(new Dictionary<string, IReadOnlyList<PricingEntry>>()));
        Assert.Null(remote.Capabilities("tier").Pricing);

        var adapter = new NoopAdapter();
        await using var prebuilt = AsyncClient.FromAdapters([new ProviderRegistration("raw", adapter)]);
        var unknown = prebuilt.Capabilities("raw:model");
        Assert.Null(unknown.ContextWindow);
        Assert.Null(unknown.Pricing);
        Assert.Equal(Feature.None, unknown.Features.Value);
        Assert.Equal(0, adapter.GenerateCalls);
    }

    [Fact]
    public void Constructor_rejects_normalized_override_collisions_and_sync_client_mirrors_pure_queries()
    {
        var catalog = CatalogWithAliases(("tier", "primary", "model"));
        var registry = new ProviderRegistry([Descriptor()]);
        var duplicate = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>
        {
            ["Primary"] = new Dictionary<string, ModelCapabilities>(),
            ["primary"] = new Dictionary<string, ModelCapabilities>(),
        };
        Assert.Throws<ArgumentException>(() => new AsyncClient([ProviderSettings.Of("engine", alias: "primary")], registry, catalog: catalog, capabilityOverrides: duplicate));

        using var client = new Client([ProviderSettings.Of("engine", alias: "primary")], registry, catalog: catalog);
        Assert.Equal("primary", client.Resolve("tier").ProviderId);
        Assert.Equal(Feature.None, client.Capabilities("tier").Features.Value);

        var config = new AnyInferConfig([ProviderSettings.Of("engine", alias: "primary")]);
        using var fromConfig = Client.FromConfig(config, registry, catalog: catalog);
        Assert.Equal("primary", fromConfig.Resolve("tier").ProviderId);
        Assert.Equal(Feature.None, fromConfig.Capabilities("tier").Features.Value);
    }

    [Fact]
    public async Task Reached_aliases_are_lazy_deduplicated_and_share_concrete_health_state()
    {
        var factoryCalls = 0;
        var adapter = new ScriptedAdapter((call, token) => call == 1
            ? Fail(new TransportException("unavailable", retryable: false, phase: "generate"))
            : Events(token, new AdapterTextDelta("unexpected"), new AdapterFinal("stop")));
        var registry = new ProviderRegistry([
            Descriptor(factory: (_, _) =>
            {
                factoryCalls++;
                return ValueTask.FromResult<IProviderAdapter>(adapter);
            })
        ]);
        var catalog = CatalogWithAliases(
            ("alias-a", "primary", "model"),
            ("alias-b", "primary", "model"));
        await using var client = new AsyncClient(
            [ProviderSettings.Of("engine", alias: "primary")],
            registry,
            route: new Route(["alias-a", "alias-b"], new Retry(1, 0, 0), healthGate: true, healthTtlS: 30),
            catalog: catalog);

        var first = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("first", target: "alias-a"));
        Assert.Single(first.Attempts);
        Assert.Equal("alias-a", Assert.IsType<ResolvedTarget>(first.Attempts[0].Target).ViaAlias);
        Assert.Equal(1, adapter.GenerateCalls);

        var second = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("second", target: "alias-b"));
        Assert.Single(second.Attempts);
        Assert.Equal("skipped_unhealthy", second.Attempts[0].Outcome);
        Assert.Equal("alias-b", Assert.IsType<ResolvedTarget>(second.Attempts[0].Target).ViaAlias);
        Assert.Equal(1, adapter.GenerateCalls);
        Assert.Equal(1, factoryCalls);
    }

    [Fact]
    public async Task Unused_invalid_fallback_does_not_materialize_and_reached_invalid_alias_fails_before_factory()
    {
        var factoryCalls = 0;
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop")));
        var registry = new ProviderRegistry([
            Descriptor(factory: (_, _) =>
            {
                factoryCalls++;
                return ValueTask.FromResult<IProviderAdapter>(adapter);
            })
        ]);
        var catalog = CatalogWithAliases(("usable", "primary", "model"));
        await using var client = new AsyncClient([ProviderSettings.Of("engine", alias: "primary")], registry, catalog: catalog);

        var result = await client.GenerateAsync("success", route: new Route(["usable", "missing"], new Retry(1, 0, 0), healthGate: false));
        Assert.Equal("ok", result.Text);
        Assert.Equal(1, factoryCalls);
        Assert.Equal(1, adapter.GenerateCalls);

        await Assert.ThrowsAsync<ConfigException>(() => client.GenerateAsync("missing", route: new Route(["missing"])));
        Assert.Equal(1, factoryCalls);
        Assert.Equal(1, adapter.GenerateCalls);
    }

    private static Catalog CatalogWithAliases(params (string Alias, string Provider, string Model)[] aliases) =>
        new(new Dictionary<string, AliasEntry>(aliases.ToDictionary(
            static item => item.Alias,
            static item => new AliasEntry(item.Alias, targets: new Dictionary<string, TargetEntry> { [item.Provider] = new TargetEntry(item.Provider, item.Model) }),
            StringComparer.Ordinal)));

    private static ProviderDescriptor Descriptor(
        Func<ProviderConfig, CancellationToken, ValueTask<IProviderAdapter>>? factory = null,
        ProviderLocality locality = ProviderLocality.Hosted,
        ModelCapabilities? defaultCapabilities = null,
        IReadOnlyDictionary<string, ModelCapabilities>? staticCapabilities = null,
        IEnumerable<InferenceOperation>? operations = null,
        IReadOnlyDictionary<string, EmbeddingCapabilities>? staticEmbeddingCapabilities = null,
        IReadOnlyDictionary<string, RerankCapabilities>? staticRerankCapabilities = null,
        TokenCalibration? tokenCalibration = null,
        RateLimitHeaders? rateLimitHeaders = null) =>
        new("engine", "Engine", factory ?? (static (_, _) => ValueTask.FromResult<IProviderAdapter>(new NoopAdapter())),
            locality: locality, defaultCapabilities: defaultCapabilities, staticCapabilities: staticCapabilities,
            operations: operations, staticEmbeddingCapabilities: staticEmbeddingCapabilities,
            staticRerankCapabilities: staticRerankCapabilities, tokenCalibration: tokenCalibration,
            rateLimitHeaders: rateLimitHeaders);

    private sealed class NoopAdapter : IProviderAdapter
    {
        internal int GenerateCalls { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            await Task.Yield();
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class ScriptedAdapter : IProviderAdapter
    {
        private readonly Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> _script;

        internal ScriptedAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) => _script = script;
        internal int GenerateCalls { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            var call = ++GenerateCalls;
            await foreach (var item in _script(call, cancellationToken).WithCancellation(cancellationToken))
            {
                yield return item;
            }
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken cancellationToken, params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Fail(AnyInferException failure)
    {
        if (failure is null)
        {
            yield break;
        }

        await Task.Yield();
        throw failure;
    }
}
