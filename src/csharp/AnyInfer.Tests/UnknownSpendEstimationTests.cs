using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Providers;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public controls for unknown-price automatic spend admission.</summary>
public sealed class UnknownSpendEstimationTests
{
    [Fact]
    public async Task Missing_pricing_allow_with_context_gate_off_dispatches_without_estimating()
    {
        var estimator = new CountingEstimator();
        var adapter = new SuccessAdapter();
        await using var client = CreateClient(
            "allow",
            adapter,
            new ModelCapabilities(),
            estimator,
            new SpendPolicy(maxTotalUsd: EDecimal.One, onUnknown: "allow"),
            contextGate: false);

        var result = await client.GenerateAsync("request", target: "allow:model");

        Assert.Equal("ok", result.Text);
        Assert.Equal(1, adapter.GenerateCalls);
        Assert.Equal(0, estimator.Calls);
    }

    [Fact]
    public async Task Missing_pricing_refuse_with_context_gate_off_is_direct_and_does_not_estimate_or_dispatch()
    {
        var estimator = new CountingEstimator();
        var adapter = new SuccessAdapter();
        await using var client = CreateClient(
            "refuse",
            adapter,
            new ModelCapabilities(),
            estimator,
            new SpendPolicy(onUnknown: "refuse"),
            contextGate: false);

        var error = await Assert.ThrowsAsync<SpendLimitException>(() =>
            client.GenerateAsync("request", target: "refuse:model"));

        Assert.Null(error.LimitUsd);
        Assert.Null(error.EstimatedUsd);
        Assert.Equal(0, adapter.GenerateCalls);
        Assert.Equal(0, estimator.Calls);
    }

    [Fact]
    public async Task Missing_pricing_still_uses_the_estimator_for_the_later_enabled_context_gate()
    {
        var estimator = new CountingEstimator();
        var adapter = new SuccessAdapter();
        await using var client = CreateClient(
            "context",
            adapter,
            new ModelCapabilities(contextWindow: new Sourced<int>(100, Provenance.Catalog)),
            estimator,
            new SpendPolicy(maxTotalUsd: EDecimal.One, onUnknown: "allow"),
            contextGate: true);

        await client.GenerateAsync("request", target: "context:model");

        Assert.Equal(1, adapter.GenerateCalls);
        Assert.True(estimator.Calls > 0);
    }

    [Fact]
    public async Task Priced_automatic_spend_preserves_the_injected_estimator_exception_identity()
    {
        var sentinel = new InvalidOperationException("estimator sentinel");
        var adapter = new SuccessAdapter();
        await using var client = CreateClient(
            "priced",
            adapter,
            new ModelCapabilities(pricing: new Sourced<Pricing>(new Pricing(EDecimal.Zero, EDecimal.Zero), Provenance.Catalog)),
            new ThrowingEstimator(sentinel),
            new SpendPolicy(maxRequestUsd: EDecimal.Zero),
            contextGate: false);

        var error = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            client.GenerateAsync("request", target: "priced:model"));

        Assert.Same(sentinel, error);
        Assert.Equal(0, adapter.GenerateCalls);
    }

    private static AsyncClient CreateClient(
        string id,
        IProviderAdapter adapter,
        ModelCapabilities capabilities,
        ITokenEstimator estimator,
        SpendPolicy spendPolicy,
        bool contextGate)
    {
        var descriptor = new ProviderDescriptor(
            id,
            id,
            (_, _) => ValueTask.FromResult(adapter),
            staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal)
            {
                ["model"] = capabilities,
            });
        return new AsyncClient(
            [ProviderSettings.Of(id)],
            new ProviderRegistry([descriptor]),
            estimator: estimator,
            spendPolicy: spendPolicy,
            contextGate: contextGate);
    }

    private sealed class CountingEstimator : ITokenEstimator
    {
        public int Calls { get; private set; }

        public TokenEstimate Estimate(string text)
        {
            Calls++;
            return new TokenEstimate(1, 1);
        }
    }

    private sealed class ThrowingEstimator(Exception exception) : ITokenEstimator
    {
        public TokenEstimate Estimate(string text) => throw exception;
    }

    private sealed class SuccessAdapter : IProviderAdapter
    {
        public int GenerateCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            return Events(cancellationToken);
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;

        private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterTextDelta("ok");
            yield return new AdapterFinal("stop", new Usage(InputTokens: 1, OutputTokens: 0));
            await Task.Yield();
        }
    }
}
