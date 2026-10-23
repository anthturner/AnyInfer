using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Controls for descriptive provider model-inventory metadata.</summary>
public sealed class ModelInventoryTests
{
    [Fact]
    public void Descriptor_defaults_to_served_and_retains_all_closed_categories()
    {
        var defaultDescriptor = Descriptor();
        Assert.Equal(ModelInventoryKind.Served, defaultDescriptor.ModelInventory);

        foreach (var category in new[] { ModelInventoryKind.Served, ModelInventoryKind.Available, ModelInventoryKind.Installed })
        {
            var descriptor = Descriptor(category);
            Assert.Equal(category, descriptor.ModelInventory);
            Assert.Equal([InferenceOperation.Generation], descriptor.Operations);
            Assert.Empty(descriptor.Aliases);
        }

        Assert.Throws<ArgumentOutOfRangeException>(() => Descriptor((ModelInventoryKind)99));
    }

    [Fact]
    public async Task Configured_lifecycle_keeps_discovered_ids_identical_for_every_category()
    {
        foreach (var category in new[] { ModelInventoryKind.Served, ModelInventoryKind.Available, ModelInventoryKind.Installed })
        {
            var adapter = new LifecycleAdapter([new DiscoveredModel("model-a"), new DiscoveredModel("model-b")]);
            var factoryCalls = 0;
            var client = new AsyncClient([ProviderSettings.Of("fixture")], new ProviderRegistry([
                Descriptor(category, (_, _) =>
                {
                    factoryCalls++;
                    return ValueTask.FromResult<IAsyncDisposable>(adapter);
                })]));
            try
            {
                Assert.Equal(["model-a", "model-b"], (await client.ModelsAsync("fixture")).Select(static model => model.Id));
                Assert.Equal(new Health(true, "ready"), await client.HealthAsync("fixture"));
            }
            finally
            {
                await client.DisposeAsync();
            }
            Assert.Equal(1, factoryCalls);
            Assert.Equal(1, adapter.ListCalls);
            Assert.Equal(1, adapter.HealthCalls);
            Assert.Equal(1, adapter.DisposeCalls);
        }
    }

    private static ProviderDescriptor Descriptor(
        ModelInventoryKind category = ModelInventoryKind.Served,
        Func<ProviderConfig, CancellationToken, ValueTask<IAsyncDisposable>>? factory = null) =>
        new("fixture", "Fixture", factory ?? ((_, _) => ValueTask.FromResult<IAsyncDisposable>(new LifecycleAdapter([]))),
            operations: [InferenceOperation.Generation], modelInventory: category);

    private sealed class LifecycleAdapter(IReadOnlyList<DiscoveredModel> models) : IProviderAdapter, IProviderLifecycle
    {
        internal int ListCalls { get; private set; }
        internal int HealthCalls { get; private set; }
        internal int DisposeCalls { get; private set; }

        public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default)
        {
            ListCalls++;
            return ValueTask.FromResult(models);
        }

        public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default)
        {
            HealthCalls++;
            return ValueTask.FromResult(new Health(true, "ready"));
        }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            yield return new AdapterTextDelta("ok");
            await Task.CompletedTask;
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }
}
