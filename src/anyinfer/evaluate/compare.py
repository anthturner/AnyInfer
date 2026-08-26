"""No-dispatch portability comparison for concrete generation requests.

Comparison assembles decisions the core already makes. It never ranks targets, constructs
an adapter, probes health, or generates text; caller order is preserved deliberately.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

from ..capabilities.budget import ContextBudget
from ..capabilities.cache import CacheMark, CachePlan
from ..capabilities.estimate import RequestEstimate, TokenEstimate
from ..capabilities.pricing import CostEstimate
from ..manifest import DroppedParameter
from ..schema.mechanism import MechanismRung
from ..types.capabilities import Pricing, Provenance, Sourced
from ..types.operations import EmbeddingInputIntent
from ..types.requests import ResolvedTarget
from ..types.results import Mechanism

__all__ = ["EmbeddingTargetComparison", "TargetComparison"]


@dataclass(frozen=True, slots=True)
class TargetComparison:
    """What one request would become on one target, without dispatching.

    Unresolvable targets are records rather than exceptions. Their target-dependent fields
    are ``None`` and `reason` says what configuration or identity was missing.
    """

    requested: str
    resolved: ResolvedTarget | None = None
    resolvable: bool = True
    reason: str = ""
    fits: bool | None = None
    budget: ContextBudget | None = None
    structured_mechanism: Mechanism | None = None
    mechanism_rungs: tuple[MechanismRung, ...] = ()
    dropped: tuple[DroppedParameter, ...] = ()
    cache: CachePlan | None = None
    cost: CostEstimate | None = None
    capability_provenance: Mapping[str, Provenance] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-safe representation."""
        return {
            "requested": self.requested,
            "resolved": str(self.resolved) if self.resolved is not None else None,
            "resolvable": self.resolvable,
            "reason": self.reason,
            "fits": self.fits,
            "budget": _budget_to_dict(self.budget),
            "structured_mechanism": self.structured_mechanism,
            "mechanism_rungs": [
                {
                    "mechanism": rung.mechanism,
                    "available": rung.available,
                    "reason": rung.reason,
                }
                for rung in self.mechanism_rungs
            ],
            "dropped": [
                {
                    "target": item.target,
                    "parameter": item.parameter,
                    "reason": item.reason,
                }
                for item in self.dropped
            ],
            "cache": _cache_to_dict(self.cache),
            "cost": (
                None
                if self.cost is None
                else {
                    "low": str(self.cost.low),
                    "high": str(self.cost.high),
                    "currency": self.cost.currency,
                }
            ),
            "capability_provenance": dict(sorted(self.capability_provenance.items())),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TargetComparison:
        """Rebuild a comparison produced by `to_dict`, ignoring unknown keys."""
        resolved_raw = data.get("resolved")
        resolved = _resolved_from_string(str(resolved_raw)) if resolved_raw else None
        cost_raw = data.get("cost")
        cost = None
        if isinstance(cost_raw, Mapping):
            cost = CostEstimate(
                Decimal(str(cost_raw.get("low", "0"))),
                Decimal(str(cost_raw.get("high", "0"))),
                str(cost_raw.get("currency", "USD")),
            )
        return cls(
            requested=str(data.get("requested", "")),
            resolved=resolved,
            resolvable=bool(data.get("resolvable", False)),
            reason=str(data.get("reason", "")),
            fits=data.get("fits") if isinstance(data.get("fits"), bool) else None,
            budget=_budget_from_dict(data.get("budget")),
            structured_mechanism=(
                cast("Mechanism", str(data["structured_mechanism"]))
                if data.get("structured_mechanism") is not None
                else None
            ),
            mechanism_rungs=tuple(
                MechanismRung(
                    str(item.get("mechanism", "")),
                    bool(item.get("available", False)),
                    str(item.get("reason", "")),
                )
                for item in data.get("mechanism_rungs", ())
                if isinstance(item, Mapping)
            ),
            dropped=tuple(
                DroppedParameter(
                    str(item.get("target", "")),
                    str(item.get("parameter", "")),
                    str(item.get("reason", "")),
                )
                for item in data.get("dropped", ())
                if isinstance(item, Mapping)
            ),
            cache=_cache_from_dict(data.get("cache")),
            cost=cost,
            capability_provenance={
                str(key): cast("Provenance", str(value))
                for key, value in (
                    data.get("capability_provenance", {}).items()
                    if isinstance(data.get("capability_provenance"), Mapping)
                    else ()
                )
            },
            notes=tuple(str(note) for note in data.get("notes", ())),
        )


@dataclass(frozen=True, slots=True)
class EmbeddingTargetComparison:
    """What one embedding request would become on one target, without dispatching.

    A separate type from `TargetComparison` rather than an optional section grafted onto
    it: generation's dimensions — mechanism rungs, cache planning, structured-output
    fallback — have no embedding counterpart at all, so folding both into one type would
    mean every embedding comparison carries a dozen fields that are always ``None``. The
    dimensions here (space capacity, batch limit, intents, pricing) are what an embedding
    call actually varies by.

    Unresolvable targets are records rather than exceptions, exactly as
    `TargetComparison` treats them: target-dependent fields are ``None``/empty and
    `reason` says what was missing.
    """

    requested: str
    resolved: ResolvedTarget | None = None
    resolvable: bool = True
    reason: str = ""
    fits: bool | None = None
    dimensions: int | None = None
    dimension_choices: tuple[int, ...] = ()
    max_batch_inputs: int | None = None
    max_input_tokens: int | None = None
    input_intents: tuple[EmbeddingInputIntent, ...] = ()
    normalized: bool | None = None
    cost: CostEstimate | None = None
    capability_provenance: Mapping[str, Provenance] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-safe representation."""
        return {
            "requested": self.requested,
            "resolved": str(self.resolved) if self.resolved is not None else None,
            "resolvable": self.resolvable,
            "reason": self.reason,
            "fits": self.fits,
            "dimensions": self.dimensions,
            "dimension_choices": list(self.dimension_choices),
            "max_batch_inputs": self.max_batch_inputs,
            "max_input_tokens": self.max_input_tokens,
            "input_intents": list(self.input_intents),
            "normalized": self.normalized,
            "cost": (
                None
                if self.cost is None
                else {
                    "low": str(self.cost.low),
                    "high": str(self.cost.high),
                    "currency": self.cost.currency,
                }
            ),
            "capability_provenance": dict(sorted(self.capability_provenance.items())),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EmbeddingTargetComparison:
        """Rebuild a comparison produced by `to_dict`, ignoring unknown keys."""
        resolved_raw = data.get("resolved")
        resolved = _resolved_from_string(str(resolved_raw)) if resolved_raw else None
        cost_raw = data.get("cost")
        cost = None
        if isinstance(cost_raw, Mapping):
            cost = CostEstimate(
                Decimal(str(cost_raw.get("low", "0"))),
                Decimal(str(cost_raw.get("high", "0"))),
                str(cost_raw.get("currency", "USD")),
            )
        return cls(
            requested=str(data.get("requested", "")),
            resolved=resolved,
            resolvable=bool(data.get("resolvable", False)),
            reason=str(data.get("reason", "")),
            fits=data.get("fits") if isinstance(data.get("fits"), bool) else None,
            dimensions=(
                int(data["dimensions"]) if data.get("dimensions") is not None else None
            ),
            dimension_choices=tuple(int(v) for v in data.get("dimension_choices", ())),
            max_batch_inputs=(
                int(data["max_batch_inputs"])
                if data.get("max_batch_inputs") is not None
                else None
            ),
            max_input_tokens=(
                int(data["max_input_tokens"])
                if data.get("max_input_tokens") is not None
                else None
            ),
            input_intents=tuple(
                cast("EmbeddingInputIntent", str(v)) for v in data.get("input_intents", ())
            ),
            normalized=(
                data.get("normalized") if isinstance(data.get("normalized"), bool) else None
            ),
            cost=cost,
            capability_provenance={
                str(key): cast("Provenance", str(value))
                for key, value in (
                    data.get("capability_provenance", {}).items()
                    if isinstance(data.get("capability_provenance"), Mapping)
                    else ()
                )
            },
            notes=tuple(str(note) for note in data.get("notes", ())),
        )


def _resolved_from_string(value: str) -> ResolvedTarget:
    provider, separator, model = value.partition(":")
    if not separator:
        return ResolvedTarget(provider, "")
    return ResolvedTarget(provider, model)


def _token_to_dict(value: TokenEstimate) -> dict[str, int]:
    return {"tokens": value.tokens, "floor": value.floor}


def _token_from_dict(value: Any) -> TokenEstimate:
    if not isinstance(value, Mapping):
        return TokenEstimate(0, 0)
    return TokenEstimate(int(value.get("tokens", 0)), int(value.get("floor", 0)))


def _budget_to_dict(value: ContextBudget | None) -> dict[str, Any] | None:
    if value is None:
        return None
    window = value.context_window
    pricing = value.pricing
    return {
        "context_window": (
            None if window is None else {"value": window.value, "provenance": window.provenance}
        ),
        "estimate": {
            "messages": _token_to_dict(value.estimate.messages),
            "tools": _token_to_dict(value.estimate.tools),
            "schema": _token_to_dict(value.estimate.schema),
            "envelope": _token_to_dict(value.estimate.envelope),
            "unpriced_parts": value.estimate.unpriced_parts,
        },
        "output_reserve_tokens": value.output_reserve_tokens,
        "headroom_tokens": value.headroom_tokens,
        "pricing": (
            None
            if pricing is None
            else {
                "value": {
                    "input_per_1m": str(pricing.value.input_per_1m),
                    "output_per_1m": str(pricing.value.output_per_1m),
                    "cache_read_per_1m": (
                        str(pricing.value.cache_read_per_1m)
                        if pricing.value.cache_read_per_1m is not None
                        else None
                    ),
                    "cache_write_per_1m": (
                        str(pricing.value.cache_write_per_1m)
                        if pricing.value.cache_write_per_1m is not None
                        else None
                    ),
                    "currency": pricing.value.currency,
                },
                "provenance": pricing.provenance,
            }
        ),
    }


def _budget_from_dict(value: Any) -> ContextBudget | None:
    if not isinstance(value, Mapping):
        return None
    estimate_raw = value.get("estimate")
    estimate_map = estimate_raw if isinstance(estimate_raw, Mapping) else {}
    window_raw = value.get("context_window")
    window = None
    if isinstance(window_raw, Mapping):
        window = Sourced(
            int(window_raw.get("value", 0)),
            str(window_raw.get("provenance", "default")),  # type: ignore[arg-type]
        )
    pricing_raw = value.get("pricing")
    pricing = None
    if isinstance(pricing_raw, Mapping) and isinstance(pricing_raw.get("value"), Mapping):
        rates = pricing_raw["value"]
        pricing = Sourced(
            Pricing(
                Decimal(str(rates.get("input_per_1m", "0"))),
                Decimal(str(rates.get("output_per_1m", "0"))),
                (
                    Decimal(str(rates["cache_read_per_1m"]))
                    if rates.get("cache_read_per_1m") is not None
                    else None
                ),
                (
                    Decimal(str(rates["cache_write_per_1m"]))
                    if rates.get("cache_write_per_1m") is not None
                    else None
                ),
                str(rates.get("currency", "USD")),
            ),
            str(pricing_raw.get("provenance", "default")),  # type: ignore[arg-type]
        )
    return ContextBudget(
        context_window=window,
        estimate=RequestEstimate(
            _token_from_dict(estimate_map.get("messages")),
            _token_from_dict(estimate_map.get("tools")),
            _token_from_dict(estimate_map.get("schema")),
            _token_from_dict(estimate_map.get("envelope")),
            int(estimate_map.get("unpriced_parts", 0)),
        ),
        output_reserve_tokens=int(value.get("output_reserve_tokens", 0)),
        headroom_tokens=int(value.get("headroom_tokens", 0)),
        pricing=pricing,
    )


def _cache_to_dict(value: CachePlan | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "mechanism": value.mechanism,
        "marks": [
            {"segment": mark.segment, "estimated_tokens": mark.estimated_tokens}
            for mark in value.marks
        ],
        "estimated_cacheable_tokens": value.estimated_cacheable_tokens,
        "reasons": list(value.reasons),
    }


def _cache_from_dict(value: Any) -> CachePlan | None:
    if not isinstance(value, Mapping):
        return None
    return CachePlan(
        mechanism=cast("Any", value.get("mechanism")),
        marks=tuple(
            CacheMark(int(mark.get("segment", 0)), int(mark.get("estimated_tokens", 0)))
            for mark in value.get("marks", ())
            if isinstance(mark, Mapping)
        ),
        estimated_cacheable_tokens=int(value.get("estimated_cacheable_tokens", 0)),
        reasons=tuple(str(reason) for reason in value.get("reasons", ())),
    )
