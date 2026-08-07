"""Turn a hardware profile into concrete llama-server launch flags.

The job is to pick the largest context that *actually fits* in the memory budget, given
the model's KV-cache cost per token, and to say so explicitly rather than letting the
server discover the shortfall by swapping or crashing.

Two subtleties that cause real failures elsewhere:

- **KV cache scales with concurrency.** llama.cpp allocates ``--ctx-size`` across
  ``--parallel`` slots, so the real KV footprint is ``context * parallel``. Budgeting for
  one slot and then serving two is how a "fits comfortably" plan runs out of VRAM.
- **A model must fit *alongside* its KV cache.** The weights are resident too, so the
  budget for KV is what remains after the artifact, not the whole device.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .hardware import HardwareProfile

__all__ = [
    "CONTEXT_LADDER",
    "Posture",
    "ServerPlan",
    "TuningInputs",
    "kv_bytes_per_token",
    "plan_server",
]

Posture = Literal["conservative", "balanced", "aggressive"]
"""How much of the machine the user is willing to spend on inference."""

CONTEXT_LADDER: tuple[int, ...] = (8192, 16384, 32768, 65536)
"""Context sizes to consider, smallest first. The largest that fits wins."""

_MEMORY_FRACTION: dict[Posture, float] = {
    "conservative": 0.50,
    "balanced": 0.65,
    "aggressive": 0.75,
}
"""Share of memory a posture will commit, leaving the rest to the rest of the system."""

_PARALLEL: dict[Posture, int] = {
    "conservative": 1,
    "balanced": 1,
    "aggressive": 2,
}

_BYTES_PER_GIB = 1024**3

_KV_BYTES_PER_TOKEN_F16: dict[str, int] = {
    "1B": 64 * 1024,
    "1.5B": 96 * 1024,
    "3B": 128 * 1024,
    "7B": 256 * 1024,
    "8B": 256 * 1024,
    "13B": 400 * 1024,
    "14B": 400 * 1024,
    "30B": 640 * 1024,
    "32B": 640 * 1024,
    "70B": 1280 * 1024,
}
"""Approximate f16 KV bytes per token by parameter class.

Deliberately a coarse table rather than a computation from GGUF metadata: the number only
needs to be right enough to choose a rung on the context ladder, and a table that is
obviously an estimate is harder to mistake for ground truth.
"""

_DEFAULT_KV_BYTES_PER_TOKEN = 256 * 1024


@dataclass(frozen=True, slots=True)
class TuningInputs:
    """What the tuner needs to know about the model being served.

    Attributes:
        artifact_size_bytes: On-disk size of the weights; they must be resident too.
        parameter_size: Parameter class (``"7B"``), keying the KV-cost table.
        max_context: Upper bound from the model itself, when known.
        requested_context: An explicit context the caller wants, overriding the ladder.
    """

    artifact_size_bytes: int | None = None
    parameter_size: str | None = None
    max_context: int | None = None
    requested_context: int | None = None


@dataclass(frozen=True, slots=True)
class ServerPlan:
    """A concrete, explainable llama-server configuration.

    Attributes:
        context_size: ``--ctx-size``, the total context across all slots.
        parallel: ``--parallel``, concurrent request slots.
        threads: ``--threads`` for CPU work.
        batch_size: ``--batch-size``.
        ubatch_size: ``--ubatch-size``.
        gpu_layers: ``--n-gpu-layers``; ``0`` means CPU-only.
        cache_type_k: ``--cache-type-k``.
        cache_type_v: ``--cache-type-v``.
        flash_attention: Whether to request flash attention.
        estimated_kv_bytes: Predicted KV-cache footprint, for admission control.
        estimated_total_bytes: Weights plus KV cache.
        posture: The posture this plan was derived under.
        rationale: Human-readable notes explaining the choices.
    """

    context_size: int
    parallel: int = 1
    threads: int = 4
    batch_size: int = 512
    ubatch_size: int = 128
    gpu_layers: int = 0
    cache_type_k: str = "f16"
    cache_type_v: str = "f16"
    flash_attention: bool = False
    estimated_kv_bytes: int = 0
    estimated_total_bytes: int = 0
    posture: Posture = "balanced"
    rationale: tuple[str, ...] = ()

    def server_arguments(self, model_path: str, *, host: str, port: int) -> list[str]:
        """Render the plan as llama-server CLI arguments.

        ``--jinja`` is always on: without it llama-server cannot apply a model's chat
        template, and tool calling silently does not work at all.
        """
        args = [
            "--model", model_path,
            "--host", host,
            "--port", str(port),
            "--ctx-size", str(self.context_size),
            "--parallel", str(self.parallel),
            "--threads", str(self.threads),
            "--batch-size", str(self.batch_size),
            "--ubatch-size", str(self.ubatch_size),
            "--n-gpu-layers", str(self.gpu_layers),
            "--cache-type-k", self.cache_type_k,
            "--cache-type-v", self.cache_type_v,
            "--jinja",
        ]
        if self.flash_attention:
            args.append("--flash-attn")
        return args

    @property
    def context_per_slot(self) -> int:
        """Usable context for a single request."""
        return self.context_size // max(1, self.parallel)


def kv_bytes_per_token(parameter_size: str | None, cache_type: str) -> int:
    """Estimate KV-cache bytes per token for a model class and cache precision."""
    base = _KV_BYTES_PER_TOKEN_F16.get(
        (parameter_size or "").upper().strip(), _DEFAULT_KV_BYTES_PER_TOKEN
    )
    return base // 2 if cache_type == "q8_0" else base


def plan_server(
    hardware: HardwareProfile,
    model: TuningInputs,
    *,
    posture: Posture = "balanced",
) -> ServerPlan:
    """Derive a server plan from hardware, model facts, and posture.

    Args:
        hardware: The detected profile. Unknown fields make the plan more conservative,
            never more optimistic.
        model: What is known about the model being served.
        posture: How much of the machine to commit.

    Returns:
        A plan whose memory estimate the caller can check before spawning.
    """
    rationale: list[str] = []
    parallel = _PARALLEL.get(posture, 1)
    fraction = _MEMORY_FRACTION.get(posture, 0.65)

    accelerated = hardware.has_accelerator
    gpu_layers = 999 if accelerated else 0
    if accelerated:
        primary = hardware.primary_accelerator
        assert primary is not None
        rationale.append(f"offloading all layers to the {primary.kind} device")
    else:
        rationale.append("no accelerator detected; running entirely on the CPU")

    budget, budget_note = _memory_budget(hardware, model, fraction)
    rationale.append(budget_note)

    candidates = _context_candidates(model)
    cache_types = ("f16", "q8_0") if posture == "aggressive" else ("f16",)

    chosen_context = candidates[0]
    chosen_cache = "f16"
    chosen_kv = 0
    for cache_type in cache_types:
        per_token = kv_bytes_per_token(model.parameter_size, cache_type)
        fitted = _largest_fitting_context(
            candidates, budget_bytes=budget, bytes_per_token=per_token * parallel
        )
        if fitted is not None and fitted >= chosen_context:
            chosen_context = fitted
            chosen_cache = cache_type
            chosen_kv = fitted * per_token * parallel

    if chosen_cache == "q8_0":
        rationale.append("using a q8_0 KV cache to fit a larger context (aggressive posture)")
    if chosen_kv == 0:
        chosen_kv = chosen_context * kv_bytes_per_token(model.parameter_size, chosen_cache)
        chosen_kv *= parallel
        rationale.append(
            "memory budget is unknown or too small for the ladder; using the smallest "
            "context and expecting the server to page or fail loudly"
        )

    if parallel > 1:
        rationale.append(
            f"reserving KV cache for {parallel} concurrent slots "
            f"({chosen_context // parallel} tokens each)"
        )

    threads = _thread_count(hardware, accelerated)
    rationale.append(f"using {threads} CPU threads")

    weights = model.artifact_size_bytes or 0
    return ServerPlan(
        context_size=chosen_context,
        parallel=parallel,
        threads=threads,
        batch_size=512,
        ubatch_size=128 if accelerated else 64,
        gpu_layers=gpu_layers,
        cache_type_k=chosen_cache,
        cache_type_v=chosen_cache,
        flash_attention=accelerated,
        estimated_kv_bytes=chosen_kv,
        estimated_total_bytes=weights + chosen_kv,
        posture=posture,
        rationale=tuple(rationale),
    )


def _context_candidates(model: TuningInputs) -> tuple[int, ...]:
    """The ladder rungs this model permits, smallest first."""
    if model.requested_context:
        return (model.requested_context,)
    ceiling = model.max_context or CONTEXT_LADDER[-1]
    rungs = tuple(c for c in CONTEXT_LADDER if c <= ceiling)
    return rungs or (min(CONTEXT_LADDER[0], ceiling),)


def _largest_fitting_context(
    candidates: tuple[int, ...], *, budget_bytes: int, bytes_per_token: int
) -> int | None:
    """The largest candidate whose KV cache fits the budget."""
    if budget_bytes <= 0 or bytes_per_token <= 0:
        return None
    fitting = [c for c in candidates if c * bytes_per_token <= budget_bytes]
    return max(fitting) if fitting else None


def _memory_budget(
    hardware: HardwareProfile, model: TuningInputs, fraction: float
) -> tuple[int, str]:
    """Bytes available for the KV cache, after the weights, and why."""
    weights = model.artifact_size_bytes or 0
    primary = hardware.primary_accelerator

    if primary is not None and primary.unified_memory:
        total = hardware.total_ram_bytes
        if total is None:
            return 0, "unified memory size is unknown; falling back to the smallest context"
        budget = int(total * fraction) - weights
        return max(0, budget), (
            f"unified memory: budgeting {_gib(budget)} for the KV cache after "
            f"{_gib(weights)} of weights"
        )

    if primary is not None and primary.total_vram_bytes:
        budget = int(primary.total_vram_bytes * fraction) - weights
        return max(0, budget), (
            f"{_gib(primary.total_vram_bytes)} of VRAM: budgeting {_gib(budget)} for the "
            f"KV cache after {_gib(weights)} of weights"
        )

    if hardware.total_ram_bytes:
        budget = int(hardware.total_ram_bytes * fraction) - weights
        return max(0, budget), (
            f"{_gib(hardware.total_ram_bytes)} of system RAM: budgeting {_gib(budget)} "
            f"for the KV cache after {_gib(weights)} of weights"
        )

    return 0, "memory size is unknown; falling back to the smallest context"


def _thread_count(hardware: HardwareProfile, accelerated: bool) -> int:
    """Pick a thread count, leaving the machine usable.

    With GPU offload the CPU mostly feeds the device, so fewer threads is fine; on CPU-only
    inference threads are the whole story, but taking every core makes the machine
    unresponsive.
    """
    cores = hardware.physical_cores or hardware.logical_cores or 4
    if accelerated:
        return max(1, min(8, cores // 2 or 1))
    return max(1, cores - 1)


def _gib(value: int) -> str:
    """Render bytes as a GiB string for rationale text."""
    return f"{value / _BYTES_PER_GIB:.1f} GiB"
