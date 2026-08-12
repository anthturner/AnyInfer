"""Tier 3 confidential-execution detection.

Does this box actually have the hardware to back an attested-local-execution guarantee,
and does it, right now. **Advisory only**, mirroring `hardware.py`'s own discipline
exactly: detection *proposes*, `ConfidentialExecutionAdapter` (in `providers` — the one
thing that actually enforces anything) decides, and every probe here is best-effort. A
missing device node or an
unparseable `nvidia-smi` line produces "not detected," never a guess dressed up as a fact
— see `plans/TIERED_ENCRYPTED_PLANS.md` §4d for the full design this module implements.

This is a hardware-capability question in the same category as `hardware.py`/`backends.py`
already answer ("what does this box actually have"), so it stays in core, in `local/`, not
in the `anyinfer-confidential` add-on — it never touches prompt content, so the library's
"no prompt templating in core" boundary does not apply to it.

**What `end_to_end=True` actually means:** the CPU package this process runs in is inside
an attestable trusted execution environment (AMD SEV-SNP or Intel TDX; see `CpuTeeKind`
for why Nitro and SGX are detected but not part of this claim), and if the selected model
offloads any layers to a GPU, that GPU is itself confidential-computing-capable *and* has
CC mode enabled — closing the PCIe bridge, not just the CPU leg. Every other field exists
so a caller can render *why*, not just whether.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .hardware import _run as _hardware_run

if TYPE_CHECKING:
    from .backends import Backend
    from .provenance import ModelManifest
    from .store import ResolvedModel

__all__ = [
    "ATTESTATION_CACHE_BYPASS_ENV",
    "ATTESTATION_CACHE_REFRESH_ENV",
    "ConfidentialExecutionStatus",
    "CpuTeeKind",
    "cache_path",
    "confidential_execution_status",
]

ATTESTATION_CACHE_BYPASS_ENV = "ANYINFER_ATTESTATION_CACHE_BYPASS"
"""Set to skip the cache entirely (read *and* write)."""

ATTESTATION_CACHE_REFRESH_ENV = "ANYINFER_ATTESTATION_CACHE_REFRESH"
"""Set to ignore a cached result and re-probe, then rewrite the cache."""

CpuTeeKind = Literal["sev-snp", "tdx", "nitro", "sgx"]
"""CPU TEE families this module can detect.

``sgx`` and ``nitro`` are detected and reported for completeness — a caller asking "what
did you find" deserves the whole answer — but neither is part of the v1 `end_to_end`
claim: SGX's enclave-shaped programming model is not the lift-and-shift story SEV-SNP/TDX
give, and Nitro Enclaves have no persistent storage or general networking, so serving a
model inside one needs real integration work this module does not attempt to paper over
(see the research findings in `plans/TIERED_ENCRYPTED_PLANS.md` §4c).
"""

_IS_LINUX = sys.platform.startswith("linux")

# The device-node checks below are the whole of v1 CPU TEE detection: Windows/macOS
# confidential-guest detection is not attempted (unknown is preferred to guessed, exactly
# `hardware.py`'s own rule), and every check here is a plain existence probe — no
# privileged access or attestation-report generation happens in detection, only in the
# separate, `attest`-extra-gated verification step this module does not implement.
_DEV_ROOT = Path("/dev")
"""Where to look for TEE guest device nodes — a module global so tests can monkeypatch it
to a fixture directory rather than the real ``/dev``, mirroring `hardware.py`'s own
injectable-seam convention (see `tests/test_local_hardware.py`)."""

_TSM_REPORT_DIR = Path("/sys/kernel/config/tsm/report")
"""The generic in-kernel TSM report interface, present on newer kernels for both TDX and
SEV-SNP guests. Used only to *corroborate* a device-node finding — raising confidence, not
as a second independent source of truth, since both paths describe the same fact."""


@dataclass(frozen=True, slots=True)
class ConfidentialExecutionStatus:
    """What this box can actually guarantee for confidential local execution right now.

    Attributes:
        cpu_tee: Detected CPU TEE, or ``None``.
        gpu_cc_capable: The primary detected GPU supports CC mode at all (a hardware
            fact); ``False`` when no GPU was detected.
        gpu_cc_enabled: CC mode is actually active in the current driver/runtime
            configuration, when `gpu_cc_capable` is ``True``.
        gpu_offload_required: Whether the selected model's launch plan offloads to GPU at
            all; when ``False``, `gpu_cc_capable`/`gpu_cc_enabled` do not gate
            `end_to_end` — a CPU-only backend has no PCIe bridge to worry about.
        end_to_end: The one field most callers branch on — see the module docstring for
            the exact definition.
        detail: Human-readable why, the same role `Backend.detail` already plays.
        model_verified: Tier 4 — whether `confidential_execution_status`'s optional
            `manifest`/`vendor_public_key` arguments were supplied and verified against
            the running model's weights on disk. ``None`` means "not evaluated" (no
            manifest was supplied), never "failed." **This field alone is not a Tier 4
            claim** — a hash-and-signature check on an unattested host is a real but
            weaker guarantee; only `model_verified is True and end_to_end is True`
            together is the full Tier 4 claim (see `provenance.py`'s module docstring).
    """

    cpu_tee: CpuTeeKind | None
    gpu_cc_capable: bool
    gpu_cc_enabled: bool
    gpu_offload_required: bool
    end_to_end: bool
    detail: str
    model_verified: bool | None = None


def cache_path() -> Path:
    """Where the detection cache lives — the same directory `hardware.py` uses."""
    from .hardware import cache_path as _hardware_cache_path

    return _hardware_cache_path().with_name("attestation.json")


def confidential_execution_status(
    *,
    backend: Backend,
    model: ResolvedModel | None = None,
    use_cache: bool = True,
    manifest: ModelManifest | None = None,
    vendor_public_key: bytes | None = None,
) -> ConfidentialExecutionStatus:
    """Detect what this box can guarantee for confidential local execution.

    Never raises: anything that cannot be determined becomes "not detected," never a
    guess. Callers — including `ConfidentialExecutionAdapter`'s own fail-closed check —
    treat the result as advice about a hardware fact, not as a decision.

    Args:
        backend: The selected local backend (used only to know whether this run targets
            a GPU-accelerated build at all, alongside `model`).
        model: The selected model, when known. Its `launch_hints["n_gpu_layers"]`
            determines `gpu_offload_required`. When `None` (a caller checking capability
            before choosing a model), `gpu_offload_required` is conservatively `True`
            unless `backend` itself is a CPU-only build — a capability check must never
            over-promise before a model is even chosen.
        use_cache: Read and write the disk cache for the hardware-detection portion of
            the result. Overridden by `ATTESTATION_CACHE_BYPASS_ENV` and
            `ATTESTATION_CACHE_REFRESH_ENV`. **Tier 4 verification is never cached**,
            regardless of this flag — a swapped model file must be caught on the very
            next call, not masked by a stale cache entry.
        manifest: Tier 4 — a vendor-signed `provenance.ModelManifest` to verify `model`'s
            weights against. Requires `model` and `vendor_public_key` too; ignored
            otherwise.
        vendor_public_key: The vendor's Ed25519 public key for `manifest`'s signature.

    Returns:
        The detected status.

    Raises:
        anyinfer.errors.ConfigError: `manifest` was supplied but the `attest` extra
            (``pip install anyinfer[attest]``) is not installed.
    """
    bypass = bool(os.environ.get(ATTESTATION_CACHE_BYPASS_ENV))
    refresh = bool(os.environ.get(ATTESTATION_CACHE_REFRESH_ENV))
    caching = use_cache and not bypass
    signature = _probe_signature()

    status: ConfidentialExecutionStatus | None = None
    if caching and not refresh:
        status = _read_cache(signature)

    if status is None:
        status = _probe(backend=backend, model=model)
        if caching:
            _write_cache(signature, status)

    if manifest is not None and vendor_public_key is not None and model is not None:
        from .provenance import verify_model_manifest

        verified = verify_model_manifest(
            manifest, weights_path=model.path, vendor_public_key=vendor_public_key
        )
        status = replace(status, model_verified=verified)

    return status


def _probe(*, backend: Backend, model: ResolvedModel | None) -> ConfidentialExecutionStatus:
    cpu_tee = _detect_cpu_tee()
    gpu_offload_required = _gpu_offload_required(backend=backend, model=model)

    gpu_cc_capable = False
    gpu_cc_enabled = False
    if gpu_offload_required:
        gpu_cc_capable, gpu_cc_enabled = _detect_gpu_cc()

    if cpu_tee not in ("sev-snp", "tdx"):
        end_to_end = False
        if cpu_tee is None:
            detail = "no attestable CPU TEE detected (SEV-SNP/TDX guest device not present)"
        else:
            detail = (
                f"detected {cpu_tee} but it is not part of the v1 attested-execution "
                "claim (see the module docstring on CpuTeeKind)"
            )
    elif not gpu_offload_required:
        end_to_end = True
        detail = f"CPU-only execution inside an attested {cpu_tee.upper()} guest"
    elif gpu_cc_capable and gpu_cc_enabled:
        end_to_end = True
        detail = f"{cpu_tee.upper()} CPU TEE with a CC-enabled GPU closing the PCIe bridge"
    elif gpu_cc_capable and not gpu_cc_enabled:
        end_to_end = False
        detail = "GPU supports confidential computing but CC mode is not enabled"
    else:
        end_to_end = False
        detail = (
            f"{cpu_tee.upper()} CPU TEE detected, but the model offloads to a GPU that "
            "is not confidential-computing-capable — the PCIe bridge is unprotected"
        )

    return ConfidentialExecutionStatus(
        cpu_tee=cpu_tee,
        gpu_cc_capable=gpu_cc_capable,
        gpu_cc_enabled=gpu_cc_enabled,
        gpu_offload_required=gpu_offload_required,
        end_to_end=end_to_end,
        detail=detail,
    )


def _gpu_offload_required(*, backend: Backend, model: ResolvedModel | None) -> bool:
    if model is not None:
        hints = getattr(model, "launch_hints", None) or {}
        return int(hints.get("n_gpu_layers", 0) or 0) > 0
    # No model chosen yet: conservative unless the backend itself is unambiguously CPU-only.
    return getattr(backend, "kind", None) != "cpu"


def _detect_cpu_tee() -> CpuTeeKind | None:
    """Detect a CPU TEE guest, Linux only for v1 (see the module docstring)."""
    if not _IS_LINUX:
        return None
    if (_DEV_ROOT / "sev-guest").exists():
        return "sev-snp"
    if (_DEV_ROOT / "tdx_guest").exists():
        return "tdx"
    if (_DEV_ROOT / "nsm").exists():
        return "nitro"
    if (_DEV_ROOT / "sgx_enclave").exists():
        return "sgx"
    return None


def _detect_gpu_cc() -> tuple[bool, bool]:
    """Detect NVIDIA confidential-computing GPU capability and enablement.

    Returns:
        ``(capable, enabled)``. Both ``False`` when `nvidia-smi` is absent, the
        ``conf-compute`` subcommand is unsupported, or its output does not parse — this
        surface is newer and less stable than the flags `hardware.py` already depends on,
        so an unparseable result is treated as "not detected," never a guess.
    """
    output = _run(["nvidia-smi", "conf-compute", "-f"])
    if output is None:
        return False, False
    capable = bool(re.search(r"CC\s+capable\s*:\s*TRUE", output, re.IGNORECASE))
    enabled = bool(re.search(r"CC\s+status\s*:\s*ON", output, re.IGNORECASE))
    return capable, enabled


def _run(command: list[str]) -> str | None:
    """Run a probe command — delegates to `hardware.py`'s own subprocess helper.

    A separate module-level name so tests can monkeypatch attestation probing without
    also stubbing every `hardware.py` probe, while still sharing one implementation of
    "how do we safely shell out" (timeout, hidden window on Windows, never raises).
    """
    return _hardware_run(command)


def _probe_signature() -> str:
    """Fingerprint what this module's probes depend on, for cache invalidation."""
    parts = [sys.platform]
    for name in ("sev-guest", "tdx_guest", "nsm", "sgx_enclave"):
        parts.append(f"{name}:{(_DEV_ROOT / name).exists()}")
    parts.append(f"tsm:{_TSM_REPORT_DIR.exists()}")
    import shutil

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is not None:
        try:
            stat = Path(nvidia_smi).stat()
            parts.append(f"nvidia-smi:{nvidia_smi}:{int(stat.st_mtime)}:{stat.st_size}")
        except OSError:
            parts.append("nvidia-smi:unstattable")
    else:
        parts.append("nvidia-smi:absent")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _read_cache(signature: str) -> ConfidentialExecutionStatus | None:
    """Read a cached status, ignoring it if the probe signature changed."""
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("signature") != signature:
        return None
    payload = data.get("status")
    if not isinstance(payload, dict):
        return None
    try:
        return ConfidentialExecutionStatus(
            cpu_tee=payload.get("cpu_tee"),
            gpu_cc_capable=bool(payload["gpu_cc_capable"]),
            gpu_cc_enabled=bool(payload["gpu_cc_enabled"]),
            gpu_offload_required=bool(payload["gpu_offload_required"]),
            end_to_end=bool(payload["end_to_end"]),
            detail=str(payload["detail"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _write_cache(signature: str, status: ConfidentialExecutionStatus) -> None:
    """Write the cache atomically, ignoring any failure."""
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "signature": signature,
                    "status": {
                        "cpu_tee": status.cpu_tee,
                        "gpu_cc_capable": status.gpu_cc_capable,
                        "gpu_cc_enabled": status.gpu_cc_enabled,
                        "gpu_offload_required": status.gpu_offload_required,
                        "end_to_end": status.end_to_end,
                        "detail": status.detail,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        return
