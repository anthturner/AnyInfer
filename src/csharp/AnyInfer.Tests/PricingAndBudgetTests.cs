using AnyInfer.Capabilities;
using AnyInfer.Json;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Pure pricing, token-estimation, and context-budget contract controls.</summary>
public sealed class PricingAndBudgetTests
{
    [Fact]
    public void Generation_pricing_uses_trusted_rates_cache_boundaries_and_all_server_tool_uses()
    {
        var pricing = new Pricing(
            D("1000000"), D("2000000"), D("500000"), D("250000"),
            perServerToolUse: new Dictionary<string, EDecimal>(StringComparer.Ordinal)
            {
                ["search"] = D("1.25"),
                ["code"] = D("0.5"),
            });
        var trusted = Capabilities(pricing, Provenance.Catalog);

        var partialRead = new Usage(
            InputTokens: 10,
            OutputTokens: 3,
            CacheReadTokens: 3,
            CacheWriteTokens: 2,
            ServerToolUses: new Dictionary<string, long>(StringComparer.Ordinal) { ["search"] = 2, ["code"] = 1 });
        EqualDecimal(D("18"), PricingCalculator.ComputeCost(partialRead, trusted));

        var equalRead = partialRead with { CacheReadTokens = 10 };
        EqualDecimal(D("24.5"), PricingCalculator.ComputeCost(equalRead, trusted));
        var overRead = partialRead with { CacheReadTokens = 12 };
        EqualDecimal(D("25.5"), PricingCalculator.ComputeCost(overRead, trusted));

        var noWriteRate = new Pricing(D("1000000"), D("2000000"), D("500000"));
        EqualDecimal(D("14.5"), PricingCalculator.ComputeCost(partialRead with { ServerToolUses = new Dictionary<string, long>() }, Capabilities(noWriteRate, Provenance.Probed)));
        Assert.Null(PricingCalculator.ComputeCost(partialRead with { ServerToolUses = new Dictionary<string, long> { ["unknown"] = 0 } }, trusted));
        Assert.Null(PricingCalculator.ComputeCost(new Usage(OutputTokens: 3), trusted));
        Assert.Null(PricingCalculator.ComputeCost(partialRead, Capabilities(pricing, Provenance.Default)));

        var reported = partialRead with { CostUsd = D("99") };
        Assert.Same(reported, PricingCalculator.WithCost(reported, trusted));
        var derived = PricingCalculator.WithCost(partialRead, trusted);
        EqualDecimal(D("18"), derived.CostUsd);
    }

    [Fact]
    public void Operation_and_preflight_pricing_keep_trust_currency_precision_and_missing_values_explicit()
    {
        var pricing = new Pricing(D("1000000"), D("2000000"), currency: "EUR", perSearchUnit: D("2.5"));
        var capabilities = Capabilities(pricing, Provenance.Discovered);

        EqualDecimal(D("4"), PricingCalculator.ComputeOperationCost(new Usage(TotalTokens: 4), capabilities, InferenceOperation.Embedding));
        EqualDecimal(D("7.5"), PricingCalculator.ComputeOperationCost(new Usage(SearchUnits: 3), capabilities, InferenceOperation.Rerank));
        Assert.Null(PricingCalculator.ComputeOperationCost(new Usage(), capabilities, InferenceOperation.Embedding));
        Assert.Null(PricingCalculator.ComputeOperationCost(new Usage(InputTokens: 1), capabilities, InferenceOperation.Rerank));

        var estimate = new RequestEstimate(new TokenEstimate(5, 2), new TokenEstimate(0, 0), new TokenEstimate(0, 0));
        var cost = PricingCalculator.EstimateCost(estimate, 4, new Sourced<Pricing>(pricing, Provenance.Catalog));
        Assert.NotNull(cost);
        EqualDecimal(D("2"), cost!.Low);
        EqualDecimal(D("13"), cost.High);
        Assert.Equal("EUR", cost.Currency);
        Assert.Null(PricingCalculator.EstimateCost(estimate, 4, new Sourced<Pricing>(pricing, Provenance.Default)));
    }

    [Fact]
    public void Token_estimation_uses_utf8_heuristics_checked_addition_and_the_actual_representable_request_surface()
    {
        Assert.Equal(new TokenEstimate(1, 0), new HeuristicTokenEstimator().Estimate("é"));
        Assert.Equal(new TokenEstimate(2, 0), new HeuristicTokenEstimator(1.5).Estimate("abc"));
        Assert.Throws<ArgumentOutOfRangeException>(() => new HeuristicTokenEstimator(0));
        Assert.Throws<ArgumentOutOfRangeException>(() => new HeuristicTokenEstimator(double.NaN));
        Assert.Throws<OverflowException>(() => new TokenEstimate(long.MaxValue, 0) + new TokenEstimate(1, 0));

        var counter = new RecordingEstimator();
        var schema = new JsonObject([new JsonProperty("z", new JsonInteger(1)), new JsonProperty("a", new JsonString("x"))]);
        var request = Request(
            [new Message("user", [new Text("a"), new UnsupportedContentPart("opaque", JsonNull.Instance), new Text("b")])],
            schema: new SchemaSpec(schema));
        var estimate = TokenEstimation.EstimateRequest(request, counter, new TokenCalibration(1.5, 2));

        Assert.Equal(["ab", "{\"z\": 1, \"a\": \"x\"}"], counter.Inputs);
        Assert.Equal(new TokenEstimate(6, 2), estimate.Messages);
        Assert.Equal(new TokenEstimate(0, 0), estimate.Tools);
        Assert.Equal(new TokenEstimate(18, 18), estimate.Schema);
        Assert.Equal(new TokenEstimate(14, 0), estimate.Envelope);
        Assert.Equal(1, estimate.UnpricedParts);

        var booleanCounter = new RecordingEstimator();
        TokenEstimation.EstimateRequest(Request([Message.User("x")], schema: new SchemaSpec(new JsonBoolean(true))), booleanCounter);
        Assert.Equal(["x", "true"], booleanCounter.Inputs);
    }

    [Fact]
    public void Context_budget_applies_reserve_priority_planning_tri_state_and_explicit_range_guards()
    {
        Assert.Equal(820, ContextBudgeting.HeadroomFor(16_384));
        Assert.Equal(256, ContextBudgeting.HeadroomFor(1_000));
        Assert.Equal(8_192, ContextBudgeting.HeadroomFor(1_000_000));

        var request = Request([Message.User("x")], sampling: new Sampling(maxOutputTokens: 99));
        var capabilities = new ModelCapabilities(
            contextWindow: new Sourced<int>(1_000, Provenance.Catalog),
            maxOutputTokens: new Sourced<int>(20, Provenance.Catalog),
            pricing: new Sourced<Pricing>(new Pricing(D("1000000"), D("2000000")), Provenance.Catalog));
        var counter = new FixedEstimator(new TokenEstimate(10, 8));

        var sampled = ContextBudgeting.BuildContextBudget(request, capabilities, counter);
        Assert.Equal(99, sampled.OutputReserveTokens);
        Assert.Equal(256, sampled.HeadroomTokens);
        Assert.Equal(645, sampled.InputAllowanceTokens);
        Assert.Equal(631, sampled.RemainingTokens);
        Assert.True(sampled.Fits);
        Assert.NotNull(sampled.EstimatedCost);
        EqualDecimal(D("8"), sampled.EstimatedCost!.Low);
        EqualDecimal(D("212"), sampled.EstimatedCost.High);

        var explicitReserve = ContextBudgeting.BuildContextBudget(request, capabilities, counter, outputReserveTokens: 4, headroomTokens: 3);
        Assert.Equal(4, explicitReserve.OutputReserveTokens);
        Assert.Equal(3, explicitReserve.HeadroomTokens);
        Assert.Equal(993, explicitReserve.InputAllowanceTokens);
        Assert.Equal(979, explicitReserve.RemainingTokens);

        var noSampling = Request([Message.User("x")]);
        Assert.Equal(20, ContextBudgeting.BuildContextBudget(noSampling, capabilities, counter).OutputReserveTokens);
        Assert.Equal(ContextBudgeting.DefaultOutputReserveTokens, ContextBudgeting.BuildContextBudget(noSampling, null, counter).OutputReserveTokens);
        Assert.Throws<ArgumentOutOfRangeException>(() => ContextBudgeting.BuildContextBudget(request, capabilities, counter, outputReserveTokens: -1));
        Assert.Throws<ArgumentOutOfRangeException>(() => ContextBudgeting.BuildContextBudget(request, capabilities, counter, headroomTokens: -1));

        var unknown = new ContextBudget(null, new RequestEstimate(new TokenEstimate(9, 7), new TokenEstimate(0, 0), new TokenEstimate(0, 0), unpricedParts: 1), 4, 0);
        Assert.Null(unknown.InputAllowanceTokens);
        Assert.Null(unknown.RemainingTokens);
        Assert.Null(unknown.Fits);
        Assert.Null(unknown.EstimatedCost);

        var overCapacity = new ContextBudget(
            new Sourced<int>(10, Provenance.Catalog),
            new RequestEstimate(new TokenEstimate(9, 9), new TokenEstimate(0, 0), new TokenEstimate(0, 0)),
            outputReserveTokens: 4,
            headroomTokens: 2,
            pricing: new Sourced<Pricing>(new Pricing(D("1000000"), D("2000000")), Provenance.Catalog));
        Assert.Equal(-5, overCapacity.RemainingTokens);
        Assert.False(overCapacity.Fits);
        Assert.NotNull(overCapacity.EstimatedCost);
    }

    [Fact]
    public void Context_gate_uses_only_trusted_whole_window_lower_bound_not_planning_reserve_or_default_facts()
    {
        var estimate = new RequestEstimate(new TokenEstimate(100, 11), new TokenEstimate(0, 0), new TokenEstimate(0, 0));
        var trusted = new ContextBudget(new Sourced<int>(10, Provenance.Override), estimate, 9_999, 0);
        var error = ContextBudgeting.ContextGateError(trusted, "alpha", "model");
        Assert.NotNull(error);
        Assert.Equal("alpha", error!.Provider);
        Assert.Equal("context_length", error.Category);

        var atBoundary = new ContextBudget(new Sourced<int>(11, Provenance.Catalog), estimate, 99_999, 0);
        Assert.Null(ContextBudgeting.ContextGateError(atBoundary));
        var defaultWindow = new ContextBudget(new Sourced<int>(10, Provenance.Default), estimate, 0, 0);
        Assert.Null(ContextBudgeting.ContextGateError(defaultWindow));

        var unpriced = new ContextBudget(new Sourced<int>(10, Provenance.Catalog), new RequestEstimate(new TokenEstimate(100, 99), new TokenEstimate(0, 0), new TokenEstimate(0, 0), unpricedParts: 1), 0, 0);
        Assert.Null(ContextBudgeting.ContextGateError(unpriced));
    }

    private static EDecimal D(string value) => EDecimal.FromString(value);

    private static void EqualDecimal(EDecimal expected, EDecimal? actual)
    {
        Assert.NotNull(actual);
        Assert.Equal(0, expected.CompareTo(actual!));
    }

    private static ModelCapabilities Capabilities(Pricing pricing, Provenance provenance) =>
        new(pricing: new Sourced<Pricing>(pricing, provenance));

    private static GenerationRequest Request(IEnumerable<Message> messages, Sampling? sampling = null, SchemaSpec? schema = null) =>
        new(messages, new Route(["alpha:model"]), sampling: sampling, schema: schema);

    private sealed class RecordingEstimator : ITokenEstimator
    {
        public List<string> Inputs { get; } = [];

        public TokenEstimate Estimate(string text)
        {
            Inputs.Add(text);
            return new TokenEstimate(text.Length, text.Length);
        }
    }

    private sealed class FixedEstimator(TokenEstimate value) : ITokenEstimator
    {
        public TokenEstimate Estimate(string text) => value;
    }
}
