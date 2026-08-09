"""Layered, provenance-tagged capability assembly, cost, and context budgeting."""

from .assemble import AUTO_SENTINELS, CapabilityStore, capabilities_for
from .budget import (
    DEFAULT_OUTPUT_RESERVE_TOKENS,
    ContextBudget,
    build_context_budget,
    headroom_for,
)
from .estimate import (
    HeuristicTokenEstimator,
    RequestEstimate,
    TokenEstimate,
    TokenEstimator,
    estimate_request,
)
from .gating import check_context_fit, context_gate_error
from .pricing import TRUSTED_PROVENANCE, CostEstimate, compute_cost, estimate_cost, with_cost
from .pricing_table import (
    DEFAULT_PRICING_URL,
    PricingEntry,
    PricingTable,
    fetch_pricing,
    load_default_pricing,
)
from .probes import (
    DEFAULT_PROBE_FEATURES,
    PROBEABLE_FEATURES,
    FeatureProbe,
    ProbeOutcome,
    ProbeReport,
)

__all__ = [
    "AUTO_SENTINELS",
    "DEFAULT_OUTPUT_RESERVE_TOKENS",
    "DEFAULT_PRICING_URL",
    "DEFAULT_PROBE_FEATURES",
    "PROBEABLE_FEATURES",
    "TRUSTED_PROVENANCE",
    "CapabilityStore",
    "ContextBudget",
    "CostEstimate",
    "FeatureProbe",
    "HeuristicTokenEstimator",
    "PricingEntry",
    "PricingTable",
    "ProbeOutcome",
    "ProbeReport",
    "RequestEstimate",
    "TokenEstimate",
    "TokenEstimator",
    "build_context_budget",
    "capabilities_for",
    "check_context_fit",
    "compute_cost",
    "context_gate_error",
    "estimate_cost",
    "estimate_request",
    "fetch_pricing",
    "headroom_for",
    "load_default_pricing",
    "with_cost",
]
