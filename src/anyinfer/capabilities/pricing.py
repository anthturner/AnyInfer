"""Cost computation from capability-layer pricing.

**Cost is tri-state, and the states must stay distinguishable:**

- a **known** cost, computed from pricing whose provenance is trusted (``catalog``,
  ``discovered``, ``probed``, or an application ``override``);
- an **unknown** cost — ``None`` — when no trustworthy pricing exists;
- a genuine **zero**, for free local inference.

An unknown cost that renders as ``$0.00`` is the single most common accounting bug in
comparable gateways, so ``None`` is never coerced to zero anywhere in this module.

Arithmetic is `Decimal` throughout: per-token prices are fractions of a
cent, and float error accumulates fast across a long run.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from ..types.capabilities import ModelCapabilities, Pricing, Provenance, Sourced
from ..types.results import Usage
from .estimate import RequestEstimate

__all__ = ["TRUSTED_PROVENANCE", "CostEstimate", "compute_cost", "estimate_cost", "with_cost"]

TRUSTED_PROVENANCE: frozenset[Provenance] = frozenset(
    {"catalog", "discovered", "probed", "override"}
)
"""Provenance levels whose prices we will bill against.

``default`` is excluded on purpose: a descriptor-level fallback is a placeholder, not a
price, and computing money from it would manufacture authority the number does not have.
``override`` is included: an application's deliberate correction is the most trusted
number there is (D27).
"""

_PER_MILLION = Decimal(1_000_000)


def compute_cost(usage: Usage, capabilities: ModelCapabilities | None) -> Decimal | None:
    """Compute the cost of one generation.

    Args:
        usage: Token counts. Missing counts make the cost unknown rather than partial —
            billing for output while ignoring unknown input would understate the total.
        capabilities: Assembled capabilities, whose ``pricing`` field supplies the rates.

    Returns:
        The cost in the pricing currency, or ``None`` when it cannot be known.
    """
    if capabilities is None or capabilities.pricing is None:
        return None
    if capabilities.pricing.provenance not in TRUSTED_PROVENANCE:
        return None
    if usage.input_tokens is None or usage.output_tokens is None:
        return None

    pricing: Pricing = capabilities.pricing.value
    input_cost = (Decimal(usage.input_tokens) / _PER_MILLION) * pricing.input_per_1m
    output_cost = (Decimal(usage.output_tokens) / _PER_MILLION) * pricing.output_per_1m
    return input_cost + output_cost


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """A preflight cost range for one request.

    Deliberately a *range*, never one number: the input estimate is two-sided
    (`anyinfer.capabilities.estimate`) and the output spend is unknown until the
    model stops. Kept strictly separate from
    `cost_usd`, which is only ever computed from
    *reported* usage — estimated and actual money must never be indistinguishable.

    Attributes:
        low: Floor input tokens priced, with zero output — the least this can cost.
        high: Planning-estimate input plus the full output reserve priced — a spend
            ceiling under the budget's own assumptions.
        currency: The pricing currency.
    """

    low: Decimal
    high: Decimal
    currency: str = "USD"


def estimate_cost(
    estimate: RequestEstimate,
    output_reserve_tokens: int,
    pricing: Sourced[Pricing] | None,
) -> CostEstimate | None:
    """Estimate the cost range of a request before sending it.

    Args:
        estimate: The request's two-sided input-token estimate.
        output_reserve_tokens: Output tokens the budget reserves; prices the ceiling.
        pricing: The model's pricing with provenance.

    Returns:
        The cost range, or ``None`` when no trustworthy pricing exists — unknown is
        reported as unknown, exactly like `compute_cost()`.
    """
    if pricing is None or pricing.provenance not in TRUSTED_PROVENANCE:
        return None
    rates = pricing.value
    low = (Decimal(estimate.floor) / _PER_MILLION) * rates.input_per_1m
    high = (Decimal(estimate.tokens) / _PER_MILLION) * rates.input_per_1m + (
        Decimal(output_reserve_tokens) / _PER_MILLION
    ) * rates.output_per_1m
    return CostEstimate(low=low, high=high, currency=rates.currency)


def with_cost(usage: Usage, capabilities: ModelCapabilities | None) -> Usage:
    """Return ``usage`` with `cost_usd` filled in.

    A cost that is already set is preserved: providers that report their own cost
    (OpenRouter) are authoritative over anything computed here.
    """
    if usage.cost_usd is not None:
        return usage
    cost = compute_cost(usage, capabilities)
    if cost is None:
        return usage
    return replace(usage, cost_usd=cost)
