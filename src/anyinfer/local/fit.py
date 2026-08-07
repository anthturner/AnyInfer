"""Will this model run on this machine?

The catalog says what exists; this says what *fits*. Each entry is classified against a
`HardwareProfile` into one of five levels, always with reasons — "why did it say tight?" has
to be answerable from the returned object alone, because a fit level with no explanation is
a number a user cannot argue with.

Advisory, never raising, and never optimistic about an unknown: a `None` field in the
profile produces ``unknown``, not a guess. That is the same contract
`anyinfer.local.hardware` keeps, and the reason the two compose.

The catalog is consumed *structurally* (a `SizedEntry` protocol) rather than imported, for
the same reason `anyinfer.local.recommend` does it: the catalog depends on this package, so
a reverse import would be a cycle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

from .backends import Backend
from .hardware import HardwareProfile
from .tuning import Posture

__all__ = [
    "FitLevel",
    "ModelFit",
    "SizedEntry",
    "classify_fit",
    "memory_budget",
    "sort_by_fit",
]

FitLevel = Literal["gpu", "cpu", "tight", "no", "unknown"]
"""How well a model fits: fully offloaded, CPU-resident, marginal, impossible, or unknown."""

_MEMORY_FRACTION: dict[Posture, float] = {
    "conservative": 0.50,
    "balanced": 0.65,
    "aggressive": 0.75,
}
"""Mirrors the tuner's postures — the fit engine must budget the way the server will."""

_TIGHT_MARGIN = 0.10
"""Within this fraction of the budget counts as tight rather than comfortable."""

_SLOW_ON_CPU_FROM = 14
"""Parameter count (in billions) at and above which CPU inference needs a speed caveat."""

_ESTIMATE_CONTEXT = 8192
"""The context the catalog's stored estimates assume, restated when explaining a shortfall."""

_BYTES_PER_GIB = 1024**3


class SizedEntry(Protocol):
    """The subset of a catalog model this module needs."""

    @property
    def id(self) -> str:
        """Catalog model id."""
        ...

    @property
    def parameter_size(self) -> str | None:
        """Parameter class (``"7B"``), when stated."""
        ...

    @property
    def est_ram_bytes(self) -> int | None:
        """Memory needed on the CPU-only path."""
        ...

    @property
    def est_vram_bytes(self) -> int | None:
        """Memory needed when fully offloaded."""
        ...


@dataclass(frozen=True, slots=True)
class ModelFit:
    """How a model relates to a machine's memory.

    Attributes:
        level: The classification.
        reasons: Human-readable notes, mirroring `ServerPlan.rationale`. Always non-empty.
        headroom_bytes: Budget minus requirement for the level that was chosen; negative
            when nothing fit, ``None`` when the numbers were unknown.
    """

    level: FitLevel
    reasons: tuple[str, ...] = ()
    headroom_bytes: int | None = None

    @property
    def runnable(self) -> bool:
        """Whether this machine can plausibly run the model at all."""
        return self.level in ("gpu", "cpu", "tight")

    @property
    def rank(self) -> int:
        """Sort key for best-fit-first ordering; higher is better."""
        return {"gpu": 4, "cpu": 3, "tight": 2, "unknown": 1, "no": 0}[self.level]


def memory_budget(
    hardware: HardwareProfile, *, posture: Posture = "balanced"
) -> tuple[int | None, int | None]:
    """Return ``(vram_budget, ram_budget)`` in bytes for a posture.

    ``None`` means "not determinable". Free memory is preferred over total when the platform
    reported it, because a device already hosting a desktop compositor does not have its
    nameplate VRAM available. Unified memory reports no separate VRAM budget: it *is* the
    RAM budget, and counting it twice is how a plan overcommits an Apple Silicon machine.
    """
    fraction = _MEMORY_FRACTION.get(posture, 0.65)

    ram: int | None = None
    if hardware.total_ram_bytes:
        usable = hardware.available_ram_bytes or hardware.total_ram_bytes
        ram = int(usable * fraction)

    primary = hardware.primary_accelerator
    if primary is None or primary.kind == "cpu" or primary.unified_memory:
        return None, ram

    device = primary.free_vram_bytes or primary.total_vram_bytes
    vram = int(device * fraction) if device else None
    return vram, ram


def classify_fit(
    entry: SizedEntry,
    hardware: HardwareProfile | None,
    *,
    posture: Posture = "balanced",
    backend: Backend | None = None,
) -> ModelFit:
    """Classify one catalog entry against a machine.

    Args:
        entry: The catalog model, with its stored memory estimates.
        hardware: The profile to budget against. ``None`` — the remote-host case — always
            yields ``unknown``, because guessing someone else's machine is not advice.
        posture: How much of the machine to commit; matches the tuner's postures.
        backend: The runtime variant that would actually drive this. Used only to surface
            the upgrade path when a faster one is available but not installed.

    Returns:
        A fit level with reasons. Never raises.
    """
    if hardware is None:
        return ModelFit(
            "unknown",
            ("no hardware profile was supplied, so this model's fit cannot be judged",),
        )

    vram_budget, ram_budget = memory_budget(hardware, posture=posture)
    need_vram = entry.est_vram_bytes
    need_ram = entry.est_ram_bytes

    if need_vram is None and need_ram is None:
        return ModelFit(
            "unknown",
            (f"catalog entry {entry.id!r} records no memory estimates",),
        )
    if vram_budget is None and ram_budget is None:
        return ModelFit(
            "unknown",
            ("this machine's memory could not be determined, so fit is unknown",),
        )

    reasons: list[str] = []
    primary = hardware.primary_accelerator
    unified = primary is not None and primary.unified_memory

    # --- the accelerated path -----------------------------------------------------------
    if need_vram is not None:
        device_budget = ram_budget if unified else vram_budget
        if device_budget is not None and hardware.has_accelerator:
            headroom = device_budget - need_vram
            label = "unified memory" if unified else "VRAM"
            if headroom >= int(device_budget * _TIGHT_MARGIN):
                reasons.append(
                    f"needs {_gib(need_vram)} of {label}; {_gib(device_budget)} is budgeted "
                    f"at the {posture} posture"
                )
                reasons.extend(_backend_reasons(hardware, backend))
                return ModelFit("gpu", tuple(reasons), headroom)
            if headroom >= 0:
                reasons.append(
                    f"needs {_gib(need_vram)} of {label} against a {_gib(device_budget)} "
                    f"budget — it fits, but with little room for a longer context"
                )
                reasons.extend(_backend_reasons(hardware, backend))
                return ModelFit("tight", tuple(reasons), headroom)
            reasons.append(
                f"needs {_gib(need_vram)} of {label} but only {_gib(device_budget)} is "
                f"budgeted; layers would spill to the CPU"
            )

    # --- the CPU path -------------------------------------------------------------------
    if need_ram is not None and ram_budget is not None:
        headroom = ram_budget - need_ram
        if headroom >= int(ram_budget * _TIGHT_MARGIN):
            reasons.append(
                f"needs {_gib(need_ram)} of system RAM; {_gib(ram_budget)} is budgeted"
            )
            reasons.extend(_cpu_speed_reasons(entry))
            return ModelFit("cpu", tuple(reasons), headroom)
        if headroom >= 0:
            reasons.append(
                f"needs {_gib(need_ram)} of system RAM against a {_gib(ram_budget)} "
                f"budget — it fits, but the machine will have little left"
            )
            reasons.extend(_cpu_speed_reasons(entry))
            return ModelFit("tight", tuple(reasons), headroom)

    # --- the total-memory backstop ------------------------------------------------------
    total = hardware.total_ram_bytes
    if total is not None and need_ram is not None and need_ram <= total:
        reasons.append(
            f"needs {_gib(need_ram)} — more than the {posture} posture budgets, but within "
            f"this machine's {_gib(total)} of RAM; expect swapping"
        )
        return ModelFit("tight", tuple(reasons), (ram_budget or 0) - need_ram)

    requirement = need_ram or need_vram or 0
    reasons.append(
        f"needs {_gib(requirement)} at a {_ESTIMATE_CONTEXT}-token context, which exceeds "
        f"this machine's memory"
    )
    reasons.append("choose a smaller parameter class, or a lower quantization")
    return ModelFit("no", tuple(reasons), (ram_budget or 0) - requirement)


_EntryT = TypeVar("_EntryT", bound=SizedEntry)


def sort_by_fit(pairs: Sequence[tuple[_EntryT, ModelFit]]) -> list[tuple[_EntryT, ModelFit]]:
    """Order entries best-fit-first, then by descending headroom, then by id.

    Ties broken deterministically so the same catalog and the same machine always produce
    the same listing — a browsing UI that reshuffles between calls is unusable. Generic in
    the entry type so a caller keeps whatever it put in, rather than having its rows
    widened to the protocol.
    """
    return sorted(
        pairs,
        key=lambda pair: (-pair[1].rank, -(pair[1].headroom_bytes or 0), pair[0].id),
    )


def _backend_reasons(hardware: HardwareProfile, backend: Backend | None) -> tuple[str, ...]:
    """Surface the CUDA add-on upgrade path, and only where it applies."""
    if backend is None:
        return ()
    nvidia = any(a.kind == "cuda" for a in hardware.accelerators)
    if nvidia and backend.kind != "cuda":
        return (
            f"planning for the {backend.kind} runtime; installing the CUDA runtime would "
            "give better throughput on this NVIDIA device",
        )
    return ()


def _cpu_speed_reasons(entry: SizedEntry) -> tuple[str, ...]:
    """Warn that a large model on the CPU runs, but slowly."""
    billions = _billions(entry.parameter_size)
    if billions is not None and billions >= _SLOW_ON_CPU_FROM:
        return (
            f"a {entry.parameter_size} model on the CPU will run, slowly — expect a few "
            "tokens per second",
        )
    return ()


def _billions(parameter_size: str | None) -> float | None:
    """Parse ``"14B"`` into ``14.0``."""
    if not parameter_size:
        return None
    text = parameter_size.strip().upper().removesuffix("B")
    try:
        return float(text)
    except ValueError:
        return None


def _gib(value: int) -> str:
    """Render bytes as a GiB string for reason text."""
    return f"{value / _BYTES_PER_GIB:.1f} GiB"
