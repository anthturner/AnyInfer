# Capabilities

Provenance-tagged model metadata: every value knows whether it was catalogued,
discovered, probed, or defaulted. The reasoning is in
[capabilities and provenance](../../concepts/capabilities.md); token estimation and the
budget calculator are explained in
[token estimation and context budgets](../../concepts/budgeting.md).

<div class="anyinfer-api-block" markdown>

::: anyinfer.ModelCapabilities

::: anyinfer.Pricing

::: anyinfer.Feature

::: anyinfer.Mechanism

::: anyinfer.Sourced

::: anyinfer.Provenance

::: anyinfer.Health

::: anyinfer.DiscoveredModel

::: anyinfer.LocalModelInfo

::: anyinfer.ContextBudget

::: anyinfer.TokenEstimate

::: anyinfer.TokenEstimator

::: anyinfer.HeuristicTokenEstimator

::: anyinfer.RequestEstimate

::: anyinfer.TokenCalibration

::: anyinfer.build_context_budget

::: anyinfer.estimate_request

::: anyinfer.check_context_fit

::: anyinfer.ProbeReport

::: anyinfer.FeatureProbe

::: anyinfer.ProbeOutcome

::: anyinfer.PROBEABLE_FEATURES

::: anyinfer.DEFAULT_PROBE_FEATURES

::: anyinfer.CostEstimate

::: anyinfer.PricingTable

::: anyinfer.load_default_pricing

::: anyinfer.fetch_pricing

</div>

## Spend accounting

An in-process rollup of what a client spent, and an optional ceiling checked before
dispatch. Concepts: [cost and spending](../../concepts/cost.md).

<div class="anyinfer-api-block" markdown>

::: anyinfer.SpendLedger

::: anyinfer.SpendTotals

::: anyinfer.SpendStore

::: anyinfer.SpendPolicy

</div>

## Rate governance

Client-side pacing for one provider instance, and the header dialect a provider reports its
window in. Both are inert until configured. Concepts:
[rate limits](../../concepts/rate-limits.md).

<div class="anyinfer-api-block" markdown>

::: anyinfer.RateLimits

::: anyinfer.RateLimitHeaders

</div>
