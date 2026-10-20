using AnyInfer.Capabilities;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public embedding fallback compatibility-warning controls.</summary>
public sealed class RetrievalFallbackWarningTests
{
    [Fact]
    public async Task Cross_target_opt_in_fallback_warns_once_on_result_and_manifest()
    {
        var primary = new EmbeddingOnlyAdapter { Failure = new ProviderUnavailableException("primary") };
        var fallback = new EmbeddingOnlyAdapter();
        await using var client = Client(("primary", primary), ("fallback", fallback));
        var route = new Route(["primary:model", "fallback:alternate"], retry: new Retry(MaxAttempts: 1), healthGate: false);

        var result = await client.EmbedAsync(
            "one",
            route: route,
            allowIncompatibleFallback: true,
            manifest: true);

        const string warning = "embedding fallback served by fallback:alternate could not be proven compatible with the route's primary target primary:model; these vectors are not safely comparable with vectors from that target";
        Assert.Equal([warning], result.Warnings);
        Assert.NotNull(result.Manifest);
        Assert.Equal([warning], result.Manifest!.Notes);
        Assert.Equal(1, primary.Calls);
        Assert.Equal(1, fallback.Calls);
    }

    [Fact]
    public async Task Same_target_repeated_route_succeeds_without_incompatibility_warning()
    {
        var adapter = new EmbeddingOnlyAdapter { Failure = new ProviderUnavailableException("first occurrence") };
        await using var client = Client(("alpha", adapter));
        var route = new Route(["alpha:model", "alpha:model"], retry: new Retry(MaxAttempts: 1), healthGate: false);

        var result = await client.EmbedAsync("one", route: route, manifest: true);

        Assert.Empty(result.Warnings);
        Assert.NotNull(result.Manifest);
        Assert.Empty(result.Manifest!.Notes);
        Assert.Equal(2, adapter.Calls);
    }

    [Fact]
    public async Task Same_provider_different_model_opt_in_fallback_warns_once_on_result_and_manifest()
    {
        var adapter = new EmbeddingOnlyAdapter { Failure = new ProviderUnavailableException("primary") };
        await using var client = Client(("alpha", adapter));
        var route = new Route(["alpha:primary", "alpha:alternate"], retry: new Retry(MaxAttempts: 1), healthGate: false);

        var result = await client.EmbedAsync(
            "one",
            route: route,
            allowIncompatibleFallback: true,
            manifest: true);

        const string warning = "embedding fallback served by alpha:alternate could not be proven compatible with the route's primary target alpha:primary; these vectors are not safely comparable with vectors from that target";
        Assert.Equal([warning], result.Warnings);
        Assert.NotNull(result.Manifest);
        Assert.Equal([warning], result.Manifest!.Notes);
        Assert.Equal(2, adapter.Calls);
    }

    private static AsyncClient Client(
        (string Id, EmbeddingOnlyAdapter Adapter) first,
        (string Id, EmbeddingOnlyAdapter Adapter)? second = null)
    {
        var descriptors = new List<ProviderDescriptor> { Descriptor(first.Id, first.Adapter) };
        if (second is { } next) descriptors.Add(Descriptor(next.Id, next.Adapter));
        var settings = descriptors.Select(static descriptor => ProviderSettings.Of(descriptor.Id));
        return new AsyncClient(settings, new ProviderRegistry(descriptors));
    }

    private static ProviderDescriptor Descriptor(string id, EmbeddingOnlyAdapter adapter) =>
        new(
            id,
            id,
            (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            operations: [InferenceOperation.Embedding]);

    private sealed class EmbeddingOnlyAdapter : IEmbedsText, IAsyncDisposable
    {
        internal int Calls { get; private set; }
        internal ProviderException? Failure { get; set; }

        public ValueTask<EmbeddingWireResult> EmbedAsync(
            EmbeddingWireRequest request,
            CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Calls++;
            if (Failure is { } failure)
            {
                Failure = null;
                throw failure;
            }
            return ValueTask.FromResult(new EmbeddingWireResult([[1d]], request.Model));
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
