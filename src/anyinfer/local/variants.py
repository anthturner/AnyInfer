"""Which quantization to acquire for *this* machine.

The catalog lists a ladder; this picks a rung. The rule is the highest quality tier whose
weights **and KV cache** fit the tuned memory budget; never the biggest file that happens
to fit, because a model that exactly fills VRAM leaves nothing for the cache and the server
will not serve.

One policy is stated outright and is the reason the default ladder stops where it does:

> **Below Q4, prefer a smaller model at a good quant over a bigger model at a bad one.**

So when nothing at Q4_K_M or better fits, selection returns ``None`` with reasons and lets
the fit engine suggest a smaller parameter class. A caller who genuinely wants IQ2 asks for
it. Selection never quietly walks off the quality cliff.

Every rejection carries a string. "Why did it pick Q4 on my 24 GB card?" must be answerable
from the returned object alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from .backends import Backend
from .fit import ModelFit, classify_fit, memory_budget
from .hardware import HardwareProfile
from .tuning import Posture, kv_bytes_per_token

__all__ = [
    "LLAMA_CPP_LADDER",
    "LOW_QUALITY_LADDER",
    "VLLM_GATES",
    "SelectableVariant",
    "VariantChoice",
    "VariantPrefs",
    "evaluate_variants",
    "select_variant",
]

LLAMA_CPP_LADDER: tuple[str, ...] = ("Q8_0", "Q6_K", "Q5_K_M", "MXFP4", "Q4_K_M")
"""Curated llama.cpp quantizations, best quality first.

``MXFP4`` is here because for the gpt-oss family it is the format the model was *trained*
in, not a lossy quantization of something larger — treating it as sub-Q4 would refuse the
only build those models publish.
"""

LOW_QUALITY_LADDER: tuple[str, ...] = ("Q4_0", "IQ4_XS", "IQ3_M", "IQ2_M")
"""Rungs below the quality floor, offered only under ``allow_low_quality``."""

VLLM_GATES: dict[str, float] = {
    "fp8": 8.9,
    "w8a8": 8.9,
    "gptq": 8.0,
    "marlin": 8.0,
    "awq": 7.5,
    "bf16": 0.0,
    "fp16": 0.0,
}
"""Minimum NVIDIA compute capability each vLLM quantization's kernels require."""

_WEIGHT_BYTES_PER_PARAM: dict[str, float] = {
    "bf16": 2.0,
    "fp16": 2.0,
    "fp8": 1.0,
    "w8a8": 1.0,
    "awq": 0.55,
    "gptq": 0.55,
}
"""Coarse weight-size multipliers, used only when a variant records no file size."""

_DEFAULT_CONTEXT = 8192
_BYTES_PER_GIB = 1024**3


class SelectableVariant(Protocol):
    """The subset of a catalog variant selection needs."""

    @property
    def id(self) -> str:
        """Variant id."""
        ...

    @property
    def engine(self) -> str:
        """``"llama.cpp"`` or ``"vllm"``."""
        ...

    @property
    def quantization(self) -> str:
        """The quantization this rung ships."""
        ...

    @property
    def quality_rank(self) -> int:
        """Ladder position; higher is better."""
        ...

    @property
    def est_file_bytes(self) -> int | None:
        """Download size."""
        ...

    @property
    def est_ram_bytes(self) -> int | None:
        """CPU-path memory requirement."""
        ...

    @property
    def est_vram_bytes(self) -> int | None:
        """Offloaded memory requirement."""
        ...

    @property
    def min_compute_capability(self) -> str | None:
        """Capability gate, when the variant declares one."""
        ...


@dataclass(frozen=True, slots=True)
class VariantPrefs:
    """How aggressively to choose.

    Attributes:
        posture: Memory posture, matching the tuner's.
        context: Context length to budget the KV cache for.
        allow_low_quality: Permit rungs below Q4_K_M.
        allow_multi_gpu: Let vLLM sum VRAM across **identical** devices, and emit a
            ``tensor_parallel_size`` hint. llama.cpp never sums by default, because its
            split is layer-wise and much easier to get wrong.
        gpu_memory_utilization: vLLM's fraction of device memory to plan against.
        max_download_bytes: Refuse variants larger than this, whatever fits in memory.
    """

    posture: Posture = "balanced"
    context: int = _DEFAULT_CONTEXT
    allow_low_quality: bool = False
    allow_multi_gpu: bool = False
    gpu_memory_utilization: float = 0.9
    max_download_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class VariantChoice:
    """The chosen rung, and why the others were not.

    Attributes:
        variant_id: The chosen variant.
        quantization: What it ships.
        fit: How it fits this machine.
        engine: Which engine it targets.
        est_file_bytes: What it will cost to download.
        reasons: Why this rung, and why not the next one up.
        rejected: ``(variant_id, why not)`` for every rung that was passed over.
        tensor_parallel_size: How many devices a vLLM launch should span.
        gpu_memory_utilization: The utilization the budget assumed.
    """

    variant_id: str
    quantization: str
    fit: ModelFit
    engine: str = "llama.cpp"
    est_file_bytes: int | None = None
    reasons: tuple[str, ...] = ()
    rejected: tuple[tuple[str, str], ...] = ()
    tensor_parallel_size: int = 1
    gpu_memory_utilization: float | None = None


@dataclass(frozen=True, slots=True)
class _Rejection:
    """One rung that did not make it, with its reason."""

    variant_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class _Budget:
    """The memory a variant is measured against, and how it was derived."""

    bytes_available: int | None
    label: str
    devices: int = 1
    notes: tuple[str, ...] = field(default_factory=tuple)


def evaluate_variants(
    variants: Sequence[SelectableVariant],
    hardware: HardwareProfile | None,
    *,
    engine: str | None = None,
    parameter_size: str | None = None,
    backend: Backend | None = None,
    prefs: VariantPrefs | None = None,
) -> tuple[VariantChoice | None, tuple[tuple[str, str], ...]]:
    """Choose a rung *and* return why every other rung was passed over.

    The rejections matter even — especially, when nothing was chosen: "no quantization
    fits" is only useful advice if it comes with the numbers behind it. `select_variant`
    is the convenience wrapper for callers that only need the choice.

    Returns:
        ``(choice, rejections)``. ``choice`` is ``None`` when nothing acceptable fits,
        which is a real answer, not a failure — the caller should then offer a smaller
        model.
    """
    options = VariantPrefs() if prefs is None else prefs
    candidates = [v for v in variants if engine is None or v.engine == engine]
    if not candidates or hardware is None:
        return None, ()

    ordered = sorted(candidates, key=lambda v: (-v.quality_rank, v.id))

    # Two passes, because a rung that fits the accelerator beats a better rung that would
    # only fit in system RAM: Q4_K_M resident on a GPU is dramatically faster than Q8_0
    # paging through the CPU, and quality-per-second is what a user actually experiences.
    accelerated = hardware.has_accelerator
    for cpu_fallback in (False, True) if accelerated else (True,):
        rejections: list[_Rejection] = []
        for variant in ordered:
            verdict = _consider(
                variant,
                hardware,
                parameter_size=parameter_size,
                prefs=options,
                backend=backend,
                cpu_fallback=cpu_fallback,
            )
            if isinstance(verdict, _Rejection):
                rejections.append(verdict)
                continue
            choice = VariantChoice(
                variant_id=variant.id,
                quantization=variant.quantization,
                fit=verdict.fit,
                engine=variant.engine,
                est_file_bytes=variant.est_file_bytes,
                reasons=(*verdict.reasons, *_upgrade_note(rejections)),
                rejected=tuple((r.variant_id, r.reason) for r in rejections),
                tensor_parallel_size=verdict.devices,
                gpu_memory_utilization=verdict.utilization,
            )
            return choice, choice.rejected
        last = tuple((r.variant_id, r.reason) for r in rejections)

    return None, last


def select_variant(
    variants: Sequence[SelectableVariant],
    hardware: HardwareProfile | None,
    *,
    engine: str | None = None,
    parameter_size: str | None = None,
    backend: Backend | None = None,
    prefs: VariantPrefs | None = None,
) -> VariantChoice | None:
    """Choose the best quantization this machine can actually run.

    Args:
        variants: The model's ladder, in any order.
        hardware: The machine to budget against. ``None`` yields ``None``: guessing a
            quantization for an unknown machine is exactly the kind of confident wrong
            answer this module exists to avoid.
        engine: Restrict to one engine's variants.
        parameter_size: Parameter class, for the KV-cache cost.
        backend: The runtime that would drive this, used to surface an upgrade path.
        prefs: Selection preferences.

    Returns:
        The chosen rung, or ``None`` when nothing acceptable fits. Use
        `evaluate_variants` when the rejection reasons matter too.
    """
    choice, _ = evaluate_variants(
        variants,
        hardware,
        engine=engine,
        parameter_size=parameter_size,
        backend=backend,
        prefs=prefs,
    )
    return choice


@dataclass(frozen=True, slots=True)
class _Accepted:
    """A rung that passed every gate."""

    fit: ModelFit
    reasons: tuple[str, ...]
    devices: int = 1
    utilization: float | None = None


def _consider(
    variant: SelectableVariant,
    hardware: HardwareProfile,
    *,
    parameter_size: str | None,
    prefs: VariantPrefs,
    backend: Backend | None,
    cpu_fallback: bool,
) -> _Accepted | _Rejection:
    """Apply every gate to one rung, in the order that fails fastest."""
    quant = variant.quantization.upper()

    if variant.engine == "llama.cpp":
        if quant not in LLAMA_CPP_LADDER and not prefs.allow_low_quality:
            return _Rejection(
                variant.id,
                f"{variant.quantization} is below the Q4_K_M quality floor; a smaller model "
                "at a good quantization beats a bigger one at a bad quantization "
                "(pass allow_low_quality=True to override)",
            )
    elif variant.engine == "vllm":
        gate = _capability_gate(variant, hardware)
        if gate is not None:
            return _Rejection(variant.id, gate)

    if prefs.max_download_bytes and (variant.est_file_bytes or 0) > prefs.max_download_bytes:
        return _Rejection(
            variant.id,
            f"its {_gib(variant.est_file_bytes or 0)} download exceeds the "
            f"{_gib(prefs.max_download_bytes)} limit you set",
        )

    need = _requirement(variant, parameter_size, prefs)
    budget = _budget_for(variant, hardware, prefs, need=need, cpu_fallback=cpu_fallback)
    if budget.bytes_available is None:
        return _Rejection(
            variant.id,
            "this machine's memory could not be determined, so nothing can be promised",
        )

    if need > budget.bytes_available:
        return _Rejection(
            variant.id,
            f"needs about {_gib(need)} ({variant.quantization} weights plus a "
            f"{prefs.context}-token KV cache) but only {_gib(budget.bytes_available)} of "
            f"{budget.label} is budgeted",
        )

    fit = classify_fit(
        _FitView(variant, parameter_size),
        hardware,
        posture=prefs.posture,
        backend=backend,
    )
    reasons = [
        f"{variant.quantization} is the highest curated quantization that fits: about "
        f"{_gib(need)} against {_gib(budget.bytes_available)} of {budget.label}",
        *budget.notes,
        *fit.reasons,
    ]
    return _Accepted(
        fit=fit,
        reasons=tuple(reasons),
        devices=budget.devices,
        utilization=prefs.gpu_memory_utilization if variant.engine == "vllm" else None,
    )


def _capability_gate(variant: SelectableVariant, hardware: HardwareProfile) -> str | None:
    """Reject a vLLM variant this GPU's kernels cannot run. Returns the reason, or ``None``."""
    devices = [a for a in hardware.accelerators if a.kind in ("cuda", "rocm")]
    if not devices:
        return (
            "vLLM needs a CUDA or ROCm device and none was detected; use the llama.cpp "
            "channel on this machine"
        )

    declared = variant.min_compute_capability
    required = float(declared) if declared else VLLM_GATES.get(variant.quantization.lower())
    if required is None or required <= 0:
        return None

    best = max((d.compute_capability_value or 0.0) for d in devices)
    if best <= 0:
        # An unknown capability must exclude a gated variant, never permit it: guessing
        # here produces a download that fails at model load with a kernel error.
        return (
            f"{variant.quantization} needs compute capability {required} and this driver "
            "did not report one"
        )
    if best < required:
        return (
            f"{variant.quantization} needs compute capability {required}; this machine's "
            f"best device reports {best}"
        )
    return None


def _budget_for(
    variant: SelectableVariant,
    hardware: HardwareProfile,
    prefs: VariantPrefs,
    *,
    need: int | None = None,
    cpu_fallback: bool = True,
) -> _Budget:
    """How much memory this variant may use, and what that memory is.

    ``need`` lets the llama.cpp path prefer VRAM when the rung actually fits on the device.
    ``cpu_fallback`` decides whether system RAM may stand in when it does not — the second
    pass of `evaluate_variants`, run only after no rung fit the accelerator at all.
    """
    vram, ram = memory_budget(hardware, posture=prefs.posture)
    primary = hardware.primary_accelerator
    unified = primary is not None and primary.unified_memory

    if variant.engine == "vllm":
        devices = [a for a in hardware.accelerators if a.kind in ("cuda", "rocm")]
        if not devices or vram is None:
            return _Budget(None, "VRAM")
        count = 1
        notes = [
            f"budgeting against {prefs.gpu_memory_utilization:.0%} of device memory, which "
            "is what vLLM reserves by default"
        ]
        if prefs.allow_multi_gpu and len(devices) > 1:
            identical = {(d.name, d.total_vram_bytes) for d in devices}
            if len(identical) == 1:
                count = len(devices)
                notes.append(
                    f"summing VRAM across {count} identical devices; the launch hint carries "
                    f"tensor_parallel_size={count}"
                )
            else:
                notes.append(
                    "the installed GPUs are not identical, so their memory was not summed"
                )
        return _Budget(
            int(vram * prefs.gpu_memory_utilization) * count,
            "VRAM",
            devices=count,
            notes=tuple(notes),
        )

    if unified and ram is not None:
        return _Budget(ram, "unified memory")

    if hardware.has_accelerator and vram is not None:
        if need is not None and need <= vram:
            return _Budget(vram, "VRAM")
        # llama.cpp is not all-or-nothing: a model too large for a small GPU still runs,
        # more slowly, out of system RAM. Budgeting against VRAM alone would reject a rung
        # this machine can genuinely serve.
        if cpu_fallback and ram is not None and ram > vram:
            return _Budget(
                ram,
                "system RAM",
                notes=(
                    f"it does not fit the {_gib(vram)} VRAM budget, so it is planned for "
                    "the CPU path and will run more slowly",
                ),
            )
        return _Budget(vram, "VRAM")
    return _Budget(ram, "system RAM")


def _requirement(
    variant: SelectableVariant, parameter_size: str | None, prefs: VariantPrefs
) -> int:
    """Bytes this variant needs: weights, KV cache at the planned context, and overhead."""
    weights = variant.est_file_bytes or _estimated_weights(variant, parameter_size)
    kv = kv_bytes_per_token(parameter_size, "f16") * max(1, prefs.context)
    recorded = variant.est_vram_bytes or variant.est_ram_bytes
    if recorded:
        # Catalog estimates already include an 8k KV cache and overhead; scale the cache
        # portion rather than double-counting it.
        base_kv = kv_bytes_per_token(parameter_size, "f16") * _DEFAULT_CONTEXT
        return max(recorded, recorded - base_kv + kv)
    return weights + kv


def _estimated_weights(variant: SelectableVariant, parameter_size: str | None) -> int:
    """Fall back to a multiplier when a variant records no file size."""
    billions = _billions(parameter_size)
    if billions is None:
        return 0
    factor = _WEIGHT_BYTES_PER_PARAM.get(variant.quantization.lower(), 0.6)
    return int(billions * 1e9 * factor)


class _FitView:
    """Adapts a variant to the fit engine's `SizedEntry` protocol."""

    __slots__ = ("_parameter_size", "_variant")

    def __init__(self, variant: SelectableVariant, parameter_size: str | None) -> None:
        self._variant = variant
        self._parameter_size = parameter_size

    @property
    def id(self) -> str:
        """The variant id."""
        return self._variant.id

    @property
    def parameter_size(self) -> str | None:
        """The model's parameter class."""
        return self._parameter_size

    @property
    def est_ram_bytes(self) -> int | None:
        """CPU-path requirement."""
        return self._variant.est_ram_bytes

    @property
    def est_vram_bytes(self) -> int | None:
        """Offloaded requirement."""
        return self._variant.est_vram_bytes


def _upgrade_note(rejections: Sequence[_Rejection]) -> tuple[str, ...]:
    """Name the rung immediately above the chosen one, so "why not better?" is answered."""
    if not rejections:
        return ()
    return (f"the next rung up was rejected: {rejections[-1].reason}",)


def _billions(parameter_size: str | None) -> float | None:
    if not parameter_size:
        return None
    text = parameter_size.strip().upper().removesuffix("B")
    try:
        return float(text)
    except ValueError:
        return None


def _gib(value: int) -> str:
    return f"{value / _BYTES_PER_GIB:.1f} GiB"
