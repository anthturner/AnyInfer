"""Which llama.cpp runtime variants are available, and which to prefer.

A llama.cpp build is compiled against one acceleration backend, so choosing the right
variant is a prerequisite to any local inference. The ranking reflects real throughput on
the hardware each backend targets.

AnyInfer never bundles these binaries: they are runtime-fetched or operator-installed, and
this module only reports what it finds.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ..errors import LocalRuntimeError
from .hardware import Accelerator, AcceleratorKind, HardwareProfile

__all__ = ["BACKEND_RANK", "Backend", "available_backends", "select_backend"]

BACKEND_RANK: dict[AcceleratorKind, int] = {
    "cuda": 30,
    "metal": 25,
    "rocm": 22,
    "vulkan": 20,
    "cpu": 10,
}
"""Preference order across runtime variants; higher wins."""

_MANIFEST_BONUS = 1
"""A manifest-validated variant outranks an identically-classed guess, and only that.

Deliberately smaller than the gap between any two backends: a verified CPU build must not
beat an unverified CUDA one, because the ranking is about capability first and confidence
second.
"""

_BINARY_NAMES = ("llama-server", "llama-server.exe")


@dataclass(frozen=True, slots=True)
class Backend:
    """One usable llama.cpp runtime variant.

    Attributes:
        kind: The acceleration family this build targets.
        binary: Path to its ``llama-server`` executable.
        rank: Preference score from `BACKEND_RANK`.
        detail: Why this backend was or was not selected.
    """

    kind: AcceleratorKind
    binary: Path
    rank: int = 0
    detail: str = ""


def available_backends(
    *,
    search_paths: list[Path] | None = None,
    hardware: HardwareProfile | None = None,
    runtime_root: Path | None = None,
    include_runtime_root: bool = True,
) -> list[Backend]:
    """Find installed llama-server binaries, best first.

    Three sources, in descending order of how much they can be trusted:

    1. **Manifest-validated variants** under the well-known runtime root. The manifest
       states the backend, so nothing is inferred.
    2. **Caller-supplied directories**, where the backend is guessed from the directory
       name — a convention, not a fact.
    3. **``PATH``**, where the backend is guessed from the hardware, because a binary on
       ``PATH`` says nothing at all about what it was compiled against.

    The distinction is recorded in `Backend.detail` rather than hidden, so a surprising
    selection can be explained.

    Args:
        search_paths: Extra directories to search, each expected to hold a runtime variant
            named after its backend (``.../cuda/llama-server``).
        hardware: Detected hardware, used to label what a found binary can actually drive.
        runtime_root: Override the well-known runtime root.
        include_runtime_root: Search the well-known runtime root at all.

    Returns:
        Usable backends, ranked. Empty when no binary is found at all.
    """
    found: list[Backend] = []
    seen: set[Path] = set()

    if include_runtime_root:
        from .runtimes import installed_runtimes, load_runtime_table

        try:
            pinned_build: str | None = load_runtime_table().build
        except LocalRuntimeError:
            pinned_build = None
        for manifest in installed_runtimes(runtime_root):
            stale = pinned_build is not None and manifest.build != pinned_build
            detail = f"installed runtime variant (build {manifest.build})"
            if stale:
                detail += (
                    f"; this AnyInfer pins build {pinned_build}, so the variant is stale — "
                    "reinstall it to keep using it"
                )
            found.append(
                Backend(
                    kind=manifest.backend,
                    binary=manifest.executable,
                    rank=BACKEND_RANK.get(manifest.backend, 0) + (0 if stale else _MANIFEST_BONUS),
                    detail=detail,
                )
            )
            seen.add(manifest.executable)

    for directory in search_paths or []:
        for name in _BINARY_NAMES:
            candidate = directory / name
            if candidate.exists() and candidate not in seen:
                kind = _kind_from_path(directory)
                found.append(
                    Backend(
                        kind=kind,
                        binary=candidate,
                        rank=BACKEND_RANK.get(kind, 0),
                        detail=(
                            f"found in {directory}; its backend is inferred from the "
                            "directory name, not verified"
                        ),
                    )
                )
                seen.add(candidate)
                break

    on_path = shutil.which("llama-server")
    if on_path is not None and Path(on_path) not in seen:
        kind = _kind_for_hardware(hardware)
        found.append(
            Backend(
                kind=kind,
                binary=Path(on_path),
                rank=BACKEND_RANK.get(kind, 0),
                detail="found on PATH; its acceleration support is assumed, not verified",
            )
        )

    return sorted(found, key=lambda b: b.rank, reverse=True)


def select_backend(
    hardware: HardwareProfile,
    *,
    preferred: AcceleratorKind | None = None,
    search_paths: list[Path] | None = None,
    runtime_root: Path | None = None,
    include_runtime_root: bool = True,
) -> Backend | None:
    """Pick the requested, or best, backend this machine can actually use.

    A CUDA build on a machine with no NVIDIA device is useless, so the selection is the
    intersection of what is installed and what the hardware can drive. When the best
    *drivable* variant is not the best variant the hardware could theoretically use — a
    Vulkan build on an NVIDIA card because the CUDA add-on is not installed — the returned
    `Backend.detail` says so, which is what turns a silent degradation into a
    discoverable recommendation.
    """
    installed = available_backends(
        search_paths=search_paths,
        hardware=hardware,
        runtime_root=runtime_root,
        include_runtime_root=include_runtime_root,
    )
    if not installed:
        return None

    drivable: set[AcceleratorKind] = {"cpu"}
    for accelerator in hardware.accelerators:
        drivable.add(accelerator.kind)
        if accelerator.kind != "cpu":
            # Vulkan is vendor-neutral: it drives NVIDIA, AMD, and Intel devices alike,
            # which is exactly why it is the fallback the default install path chooses.
            # Treating it as undrivable on an NVIDIA box would degrade to CPU for no
            # reason.
            drivable.add("vulkan")

    if preferred is not None:
        chosen = next((backend for backend in installed if backend.kind == preferred), None)
        if chosen is None:
            raise LocalRuntimeError(
                f"the requested {preferred} llama.cpp runtime is not installed",
                provider="llama-cpp",
                hint=f"install it with 'anyinfer runtime install {preferred}', or select auto",
            )
        if preferred not in drivable:
            raise LocalRuntimeError(
                f"the installed {preferred} llama.cpp runtime cannot drive this machine",
                provider="llama-cpp",
                hint="select auto or choose a runtime matching the detected accelerator",
            )
        return chosen

    for backend in installed:
        if backend.kind in drivable:
            return _explain_choice(backend, hardware, installed)

    fallback = installed[-1]
    return Backend(
        kind=fallback.kind,
        binary=fallback.binary,
        rank=fallback.rank,
        detail=(
            f"{fallback.detail}; no installed variant matches this machine's hardware "
            f"({', '.join(sorted(drivable))}), so this is a last resort"
        ),
    )


def _explain_choice(
    chosen: Backend, hardware: HardwareProfile, installed: list[Backend]
) -> Backend:
    """Annotate the selected backend when a better one was possible but absent."""
    best_possible = max(
        (BACKEND_RANK.get(a.kind, 0) for a in hardware.accelerators),
        default=BACKEND_RANK["cpu"],
    )
    if BACKEND_RANK.get(chosen.kind, 0) >= best_possible:
        return chosen

    preferred = max(hardware.accelerators, key=lambda a: BACKEND_RANK.get(a.kind, 0)).kind
    if any(b.kind == preferred for b in installed):
        return chosen
    return Backend(
        kind=chosen.kind,
        binary=chosen.binary,
        rank=chosen.rank,
        detail=(
            f"{chosen.detail}; selected because no {preferred} runtime is installed — "
            f"installing it would use this machine's {preferred} device directly"
        ),
    )


_PATH_KINDS: tuple[AcceleratorKind, ...] = ("cuda", "rocm", "metal", "vulkan")


def _kind_from_path(directory: Path) -> AcceleratorKind:
    """Infer a backend family from a runtime directory's name."""
    name = directory.name.lower()
    for kind in _PATH_KINDS:
        if kind in name:
            return kind
    return "cpu"


def _kind_for_hardware(hardware: HardwareProfile | None) -> AcceleratorKind:
    """The family a generic binary most likely targets on this machine."""
    if hardware is None:
        return "cpu"
    primary: Accelerator | None = hardware.primary_accelerator
    return primary.kind if primary is not None else "cpu"
