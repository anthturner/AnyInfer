"""Layered capability assembly with provenance and pricing.

Layers, weakest to strongest: descriptor defaults → static catalog (including the bundled
pricing table) → live discovery → opt-in probes → application overrides. Later layers
override earlier ones field by field, and every value keeps its provenance so a consumer
can tell a measured context window from a guessed one, and a deliberate user correction
from both.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Literal

from ..registry import ProviderDescriptor
from ..types.capabilities import (
    DiscoveredModel,
    ModelCapabilities,
    Pricing,
    Sourced,
    conjunction,
)
from .pricing_table import PricingTable, load_default_pricing

__all__ = ["AUTO_SENTINELS", "CapabilityStore", "capabilities_for"]

AUTO_SENTINELS = frozenset({"auto"})
"""Model ids that mean "the provider chooses" and therefore need conjunction bounds (R7)."""

_LOCAL_ZERO_PRICING = Sourced(Pricing(Decimal(0), Decimal(0)), "catalog")
"""Local inference has a genuine per-token cost of zero — a real 0, not an unknown."""


def capabilities_for(
    descriptor: ProviderDescriptor,
    model: str,
    *,
    discovered: Mapping[str, ModelCapabilities] | None = None,
    probed: Mapping[str, ModelCapabilities] | None = None,
    pricing: PricingTable | None = None,
    overrides: Mapping[str, ModelCapabilities] | None = None,
    locality: Literal["hosted", "local", "remote"] | None = None,
) -> ModelCapabilities:
    """Assemble what is known about one model.

    Args:
        descriptor: The provider descriptor, supplying defaults and the static catalog.
        model: The concrete model id, or a delegating sentinel such as ``"auto"``.
        discovered: Capabilities read from a live model listing.
        probed: Capabilities measured by opt-in probes.
        pricing: The pricing table supplying the ``catalog`` pricing layer.
        overrides: Application-supplied corrections by model id; every value is re-tagged
            ``override`` provenance, so it outranks every collected layer.
        locality: Overrides the descriptor's own locality for this instance. A client
            passes ``"remote"`` for a normally-local engine reached over a network, so the
            genuine-zero local pricing is *not* applied to someone else's metered endpoint;
            cost then stays unknown, which is the honest answer.

    Returns:
        The assembled capabilities. Unknown fields stay ``None`` rather than being guessed.
    """
    if model.lower() in AUTO_SENTINELS:
        return _delegating_capabilities(descriptor, discovered, probed, pricing, overrides)

    result = descriptor.default_capabilities
    static = descriptor.static_capabilities.get(model)
    if static is not None:
        result = result.overlay(static)
    if pricing is not None:
        # The table contributes exactly one field; a full overlay would drag empty
        # defaults along and clobber same-provenance fields on the tie-break.
        table_pricing = pricing.lookup(descriptor.id, model)
        if table_pricing is not None and table_pricing.outranks(result.pricing):
            result = replace(result, pricing=table_pricing)
    if discovered and model in discovered:
        result = result.overlay(discovered[model])
    if probed and model in probed:
        result = result.overlay(probed[model])
    effective_locality = locality or descriptor.locality
    if effective_locality == "local" and result.pricing is None:
        result = replace(result, pricing=_LOCAL_ZERO_PRICING)
    if overrides and model in overrides:
        result = _apply_override(result, overrides[model])
    return result


def _apply_override(result: ModelCapabilities, caps: ModelCapabilities) -> ModelCapabilities:
    """Apply an application's corrections, each field at ``override`` provenance.

    Callers write plain values; the fact that they supplied them deliberately *is* the
    provenance, so they are not asked to spell it out per field. Fields the caller left
    unset are untouched — an override corrects, it does not reset.
    """
    if caps.context_window is not None:
        result = replace(result, context_window=Sourced(caps.context_window.value, "override"))
    if caps.max_output_tokens is not None:
        result = replace(
            result, max_output_tokens=Sourced(caps.max_output_tokens.value, "override")
        )
    if caps.features.value:
        result = replace(result, features=Sourced(caps.features.value, "override"))
    if caps.pricing is not None:
        result = replace(result, pricing=Sourced(caps.pricing.value, "override"))
    if caps.local is not None:
        result = replace(result, local=caps.local)
    return result


def _delegating_capabilities(
    descriptor: ProviderDescriptor,
    discovered: Mapping[str, ModelCapabilities] | None,
    probed: Mapping[str, ModelCapabilities] | None,
    pricing: PricingTable | None,
    overrides: Mapping[str, ModelCapabilities] | None,
) -> ModelCapabilities:
    """Conjunction over every model the provider might pick.

    Promising more than the weakest candidate would be a lie the caller cannot detect until
    a request fails, so the bound is the intersection.
    """
    candidates: list[ModelCapabilities] = []
    names = set(descriptor.static_capabilities) | set(discovered or {}) | set(probed or {})
    for name in sorted(names):
        if name.lower() in AUTO_SENTINELS:
            continue
        candidates.append(
            capabilities_for(
                descriptor,
                name,
                discovered=discovered,
                probed=probed,
                pricing=pricing,
                overrides=overrides,
            )
        )
    if not candidates:
        return descriptor.default_capabilities
    return conjunction(candidates)


class CapabilityStore:
    """Caches discovery and probe layers per provider, plus the client's pricing/overrides.

    Discovery costs a network round trip, so the assembled view is memoized until something
    explicitly invalidates it. Probe results are stored separately because they are expensive
    enough that a caller opts into them deliberately. The pricing table and application
    overrides are fixed for the store's lifetime — they are configuration, not cache.
    """

    def __init__(
        self,
        *,
        pricing: PricingTable | None = None,
        overrides: Mapping[str, Mapping[str, ModelCapabilities]] | None = None,
    ) -> None:
        self._discovered: dict[str, dict[str, ModelCapabilities]] = {}
        self._probed: dict[str, dict[str, ModelCapabilities]] = {}
        self._pricing = pricing if pricing is not None else load_default_pricing()
        self._overrides = {k: dict(v) for k, v in (overrides or {}).items()}

    def record_discovery(self, provider_id: str, models: Sequence[DiscoveredModel]) -> None:
        """Store the capability fields a model listing reported."""
        layer = self._discovered.setdefault(provider_id, {})
        for model in models:
            if model.capabilities is not None:
                layer[model.id] = model.capabilities

    def record_probe(self, provider_id: str, model: str, caps: ModelCapabilities) -> None:
        """Store measured capabilities for one model."""
        self._probed.setdefault(provider_id, {})[model] = caps

    def has_discovery(self, provider_id: str) -> bool:
        """Whether a discovery layer has been recorded for this provider."""
        return provider_id in self._discovered

    def discovered_has_model(self, provider_id: str, model: str) -> bool | None:
        """Whether a completed discovery listed ``model``; ``None`` means not discovered."""
        layer = self._discovered.get(provider_id)
        if layer is None:
            return None
        return model in layer

    def invalidate(self, provider_id: str | None = None) -> None:
        """Drop cached layers for one provider, or all of them."""
        if provider_id is None:
            self._discovered.clear()
            self._probed.clear()
            return
        self._discovered.pop(provider_id, None)
        self._probed.pop(provider_id, None)

    def capabilities_for(
        self,
        descriptor: ProviderDescriptor,
        model: str,
        *,
        locality: Literal["hosted", "local", "remote"] | None = None,
    ) -> ModelCapabilities:
        """Assemble capabilities for a model using this store's cached layers."""
        return capabilities_for(
            descriptor,
            model,
            discovered=self._discovered.get(descriptor.id),
            probed=self._probed.get(descriptor.id),
            pricing=self._pricing,
            overrides=self._overrides.get(descriptor.id),
            locality=locality,
        )
