using AnyInfer.Capabilities;
using AnyInfer.Providers;
using Xunit;
using PeterO.Numbers;

namespace AnyInfer.Tests;

/// <summary>Friend-boundary CAT.3 capability-store layer and invalidation controls.</summary>
public sealed class CapabilityAssemblyTests
{
    [Fact]
    public void Discovery_layers_are_instance_scoped_atomic_and_invalidation_restores_unknown()
    {
        var descriptor = Descriptor();
        var store = new CapabilityStore();

        Assert.Null(store.DiscoveredHasModel("primary", "model"));
        Assert.Null(store.DiscoveredHasModel("backup", "model"));

        store.RecordDiscovery("primary", []);
        Assert.False(store.DiscoveredHasModel("primary", "model"));
        Assert.False(store.DiscoveredHasModel("primary", "another-model"));
        Assert.Null(store.DiscoveredHasModel("backup", "model"));

        store.RecordDiscovery("primary", [new DiscoveredModel("model", new ModelCapabilities(contextWindow: new Sourced<int>(8192, Provenance.Discovered)))]);
        store.RecordDiscovery("backup", [new DiscoveredModel("model")]);
        store.RecordProbe("primary", "model", new ModelCapabilities(contextWindow: new Sourced<int>(12288, Provenance.Probed)));
        store.RecordProbe("primary", "model", new ModelCapabilities(contextWindow: new Sourced<int>(16384, Provenance.Probed)));
        var primary = store.CapabilitiesFor(descriptor, "primary", "model", ProviderLocality.Hosted);
        var backup = store.CapabilitiesFor(descriptor, "backup", "model", ProviderLocality.Hosted);
        Assert.Equal(16384, primary.ContextWindow!.Value);
        Assert.Equal(Provenance.Probed, primary.ContextWindow.Provenance);
        Assert.Equal(4096, backup.ContextWindow!.Value);
        Assert.True(store.DiscoveredHasModel("primary", "model"));
        Assert.False(store.DiscoveredHasModel("backup", "model"));

        store.Invalidate("primary");
        Assert.Null(store.DiscoveredHasModel("primary", "model"));
        Assert.False(store.DiscoveredHasModel("backup", "model"));
        store.Invalidate();
        Assert.Null(store.DiscoveredHasModel("backup", "model"));
    }

    [Fact]
    public void Assembly_orders_default_static_pricing_local_zero_and_override_without_erasing_default_features()
    {
        var pricing = new PricingTable(new Dictionary<string, IReadOnlyList<PricingEntry>>
        {
            ["primary"] = [new PricingEntry("model", new Pricing(EDecimal.FromString("1"), EDecimal.FromString("2")), "2026-01-01", "https://example.invalid")],
        });
        var overrides = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>
        {
            ["primary"] = new Dictionary<string, ModelCapabilities>
            {
                ["model"] = new ModelCapabilities(
                    contextWindow: new Sourced<int>(0, Provenance.Default),
                    features: new Sourced<Feature>(Feature.None, Provenance.Default),
                    embedding: new EmbeddingCapabilities(dimensions: 1)),
            },
        };
        var descriptor = Descriptor(staticCapabilities: new Dictionary<string, ModelCapabilities>
        {
            ["model"] = new ModelCapabilities(
                contextWindow: new Sourced<int>(4096, Provenance.Catalog),
                features: new Sourced<Feature>(Feature.JsonSchema, Provenance.Default)),
        });
        var store = new CapabilityStore(pricing, overrides);

        var assembled = store.CapabilitiesFor(descriptor, "primary", "model", ProviderLocality.Local);
        Assert.Equal(0, assembled.ContextWindow!.Value);
        Assert.Equal(Provenance.Override, assembled.ContextWindow.Provenance);
        Assert.Equal(Feature.JsonSchema, assembled.Features.Value);
        Assert.Equal(EDecimal.FromString("1"), assembled.Pricing!.Value.InputPer1M);
        Assert.Equal(Provenance.Catalog, assembled.Pricing.Provenance);
        Assert.Null(assembled.Embedding);

        var unknownLocal = new CapabilityStore(new PricingTable(new Dictionary<string, IReadOnlyList<PricingEntry>>()))
            .CapabilitiesFor(descriptor, "local", "unknown", ProviderLocality.Local);
        Assert.Equal(EDecimal.FromString("0"), unknownLocal.Pricing!.Value.InputPer1M);
        Assert.Equal(Provenance.Catalog, unknownLocal.Pricing.Provenance);
        Assert.Equal(Feature.JsonSchema, unknownLocal.Features.Value);
        Assert.Equal(Provenance.Default, unknownLocal.Features.Provenance);
    }

    [Fact]
    public async Task Concurrent_probe_replacement_exposes_one_complete_latest_fact_record()
    {
        var store = new CapabilityStore();
        var descriptor = Descriptor();
        var begin = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var writerActive = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var concurrentWriterActive = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var readerObservedActiveWriter = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var writersDone = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var observed = 0;
        var observedDuringConcurrentWriterWindow = 0;
        var writerLoopProgress = 0;
        var reader = Task.Run(async () =>
        {
            await begin.Task;
            await writerActive.Task;
            while (!writersDone.Task.IsCompleted)
            {
                AssertWholeProbeRecord(store.CapabilitiesFor(descriptor, "primary", "model", ProviderLocality.Hosted));
                Interlocked.Increment(ref observed);
                if (writerActive.Task.IsCompleted)
                {
                    readerObservedActiveWriter.TrySetResult();
                }
                if (concurrentWriterActive.Task.IsCompleted && Volatile.Read(ref writerLoopProgress) > 0)
                {
                    Interlocked.Increment(ref observedDuringConcurrentWriterWindow);
                }

                await Task.Yield();
            }
        });
        var first = Task.Run(async () =>
        {
            await begin.Task;
            store.RecordProbe("primary", "model", Probe(100, Feature.JsonSchema));
            writerActive.TrySetResult();
            await readerObservedActiveWriter.Task;
            for (var index = 0; index < 64; index++)
            {
                store.RecordProbe("primary", "model", Probe(100, Feature.JsonSchema));
                Interlocked.Increment(ref writerLoopProgress);
                await Task.Yield();
            }
        });
        var second = Task.Run(async () =>
        {
            await begin.Task;
            await writerActive.Task;
            concurrentWriterActive.TrySetResult();
            await readerObservedActiveWriter.Task;
            for (var index = 0; index < 64; index++)
            {
                store.RecordProbe("primary", "model", Probe(200, Feature.Tools));
                Interlocked.Increment(ref writerLoopProgress);
                await Task.Yield();
            }
        });

        begin.TrySetResult();
        await Task.WhenAll(first, second);
        writersDone.TrySetResult();
        await reader;

        var result = store.CapabilitiesFor(descriptor, "primary", "model", ProviderLocality.Hosted);
        Assert.True(observed > 0);
        Assert.True(observedDuringConcurrentWriterWindow > 0);
        AssertWholeProbeRecord(result);
    }

    private static ModelCapabilities Probe(int contextWindow, Feature features) => new(
        contextWindow: new Sourced<int>(contextWindow, Provenance.Probed),
        features: new Sourced<Feature>(features, Provenance.Probed));

    private static void AssertWholeProbeRecord(ModelCapabilities result)
    {
        Assert.NotNull(result.ContextWindow);
        Assert.Equal(Provenance.Probed, result.ContextWindow!.Provenance);
        Assert.True(
            result.ContextWindow.Value == 100 && result.Features.Value == Feature.JsonSchema ||
            result.ContextWindow.Value == 200 && result.Features.Value == Feature.Tools,
            "A probe replacement must publish one whole supplied capability record, never a mixed layer.");
    }

    private static ProviderDescriptor Descriptor(IReadOnlyDictionary<string, ModelCapabilities>? staticCapabilities = null) =>
        new("engine", "Engine", static (_, _) => ValueTask.FromException<IProviderAdapter>(new InvalidOperationException()),
            defaultCapabilities: new ModelCapabilities(
                contextWindow: new Sourced<int>(4096, Provenance.Default),
                features: new Sourced<Feature>(Feature.JsonSchema, Provenance.Default)),
            staticCapabilities: staticCapabilities);
}
