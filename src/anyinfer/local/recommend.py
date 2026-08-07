"""Hardware → tier recommendation.

Generalizes mote's ``get_recommended_model_key``: instead of hardcoded thresholds, the
requirements live in the alias catalog (``min_ram_bytes`` / ``min_vram_bytes``), so
updating the recommendation is a data change rather than a code change.

Advisory, like everything else in this subsystem: it proposes a tier and explains why, and
the caller is free to ignore it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .hardware import HardwareProfile

__all__ = ["Recommendation", "Tier", "TierSource", "recommend_alias"]


class Tier(Protocol):
    """The subset of a catalog alias this module needs.

    Structural rather than nominal so the local subsystem does not import the catalog:
    artifacts (local data) are depended on by the catalog, and a reverse dependency here
    would make that a cycle.
    """

    @property
    def name(self) -> str:
        """The alias name."""
        ...

    @property
    def min_ram_bytes(self) -> int | None:
        """System RAM this tier needs, when stated."""
        ...

    @property
    def min_vram_bytes(self) -> int | None:
        """Accelerator memory this tier needs, when stated."""
        ...


class TierSource(Protocol):
    """The subset of a catalog needed to recommend a tier."""

    def alias_names(self) -> tuple[str, ...]:
        """Every alias name."""
        ...

    def alias(self, name: str) -> Tier:
        """Look up one alias."""
        ...


@dataclass(frozen=True, slots=True)
class Recommendation:
    """A recommended tier and the reasoning behind it.

    Attributes:
        alias: The recommended alias, or ``None`` when nothing fits.
        reason: Why this tier was chosen, for display to a user.
        confident: ``False`` when the machine's memory could not be determined, so the
            recommendation is a floor rather than a fit.
    """

    alias: str | None
    reason: str
    confident: bool = True


def recommend_alias(
    hardware: HardwareProfile,
    catalog: TierSource,
    *,
    prefer_accelerated: bool = True,
) -> Recommendation:
    """Recommend the largest catalog tier this machine can comfortably run.

    Args:
        hardware: The detected profile.
        catalog: The catalog whose aliases carry ``min_ram_bytes``/``min_vram_bytes``.
        prefer_accelerated: Budget against VRAM when an accelerator is present. With
            unified memory, system RAM is the budget regardless.

    Returns:
        A recommendation. When memory is unknown, the smallest tier is proposed with
        ``confident=False`` rather than guessing upward.
    """
    tiers = _ordered_tiers(catalog)
    if not tiers:
        return Recommendation(None, "the catalog defines no aliases", confident=False)

    ram = hardware.total_ram_bytes
    vram = _accelerator_budget(hardware) if prefer_accelerated else None

    if ram is None and vram is None:
        smallest = tiers[0]
        return Recommendation(
            smallest.name,
            "could not determine this machine's memory, so the smallest tier is the only "
            "safe suggestion",
            confident=False,
        )

    best: Tier | None = None
    for tier in tiers:
        if _fits(tier, ram=ram, vram=vram):
            best = tier

    if best is None:
        smallest = tiers[0]
        return Recommendation(
            smallest.name,
            f"this machine is below the requirements of every tier; {smallest.name} is "
            "the smallest available and may still be slow",
            confident=False,
        )

    return Recommendation(best.name, _explain(best, ram=ram, vram=vram))


def _ordered_tiers(catalog: TierSource) -> list[Tier]:
    """Aliases ordered smallest to largest by their stated requirements."""
    entries = [catalog.alias(name) for name in catalog.alias_names()]
    return sorted(entries, key=lambda e: (e.min_vram_bytes or 0, e.min_ram_bytes or 0))


def _accelerator_budget(hardware: HardwareProfile) -> int | None:
    """Usable accelerator memory, or ``None`` when there is none to speak of."""
    primary = hardware.primary_accelerator
    if primary is None:
        return None
    if primary.unified_memory:
        # Unified memory is the system RAM already accounted for; treating it as separate
        # VRAM would double-count it.
        return None
    return primary.total_vram_bytes


def _fits(tier: Tier, *, ram: int | None, vram: int | None) -> bool:
    """Whether a tier's stated requirements are satisfied.

    An unstated requirement is treated as satisfied; an unmeasurable resource is treated as
    *not* satisfying a stated requirement, so unknowns never inflate the recommendation.
    """
    if tier.min_vram_bytes:
        # A machine without a discrete GPU can still satisfy a VRAM requirement out of
        # system RAM (unified memory, or CPU inference), so both are consulted.
        best_available = max(vram or 0, ram or 0)
        if best_available < tier.min_vram_bytes:
            return False
    return not (tier.min_ram_bytes and (ram is None or ram < tier.min_ram_bytes))


def _explain(tier: Tier, *, ram: int | None, vram: int | None) -> str:
    """Describe why a tier was chosen."""
    if vram:
        return f"{_gib(vram)} of VRAM comfortably fits the {tier.name} tier"
    if ram:
        return f"{_gib(ram)} of system RAM fits the {tier.name} tier"
    return f"{tier.name} is the best fit for this machine"


def _gib(value: int) -> str:
    return f"{value / 1024**3:.0f} GiB"
