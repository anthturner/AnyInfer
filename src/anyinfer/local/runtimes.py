"""Acquiring and validating ``llama-server`` runtime variants.

AnyInfer ships no llama.cpp binaries. A CUDA build with its cuBLAS and cudart libraries runs
to hundreds of megabytes; CPU and Vulkan builds are tens. Packing the large one into a wheel
to spare some users a download would make *every* user pay for it, so runtimes are fetched —
and CUDA specifically is an opt-in add-on that AnyInfer recommends but never installs by
itself.

An installed variant is a directory under the runtime root holding the build plus a
``runtime.json`` manifest. The manifest is what makes "are the CUDA extensions installed?"
answerable without guessing from a directory name: it records the architecture, the backend,
the pinned build id, and the executable, and a manifest that fails any of those checks means
the variant simply does not exist. Advisory, never raising, exactly like hardware detection.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import sys
import tarfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import httpx2

from ..errors import LocalRuntimeError
from .artifacts import GgufArtifact, GgufFile
from .downloads import ProgressCallback, download_artifact
from .hardware import AcceleratorKind, HardwareProfile

__all__ = [
    "MANIFEST_NAME",
    "InstallReport",
    "RuntimeArtifact",
    "RuntimeManifest",
    "RuntimeTable",
    "check_cuda_preconditions",
    "default_runtime_kind",
    "install_hint",
    "install_runtime",
    "installed_runtimes",
    "load_runtime_table",
    "platform_key",
    "read_manifest",
    "remove_runtime",
    "runtime_root",
]

MANIFEST_NAME = "runtime.json"
"""The file that makes a directory a recognized runtime variant."""

_MANIFEST_VERSION = 1
_BINARY_NAMES = ("llama-server", "llama-server.exe")
_ARCH_ALIASES: Mapping[str, str] = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
}


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    """One downloadable runtime archive.

    Attributes:
        platform: Platform key this build targets (``"win32-amd64"``).
        backend: Acceleration family the build was compiled for.
        filename: Archive file name.
        url: Where to fetch it.
        sha256: Expected digest of the archive.
        size_bytes: Expected archive size.
        companions: Extra archives unpacked into the same directory — the CUDA runtime
            libraries ship separately from the llama.cpp build.
    """

    platform: str
    backend: AcceleratorKind
    filename: str
    url: str
    sha256: str
    size_bytes: int | None = None
    companions: tuple[RuntimeArtifact, ...] = ()

    @property
    def total_bytes(self) -> int:
        """Bytes to transfer including companions."""
        return (self.size_bytes or 0) + sum(c.size_bytes or 0 for c in self.companions)


@dataclass(frozen=True, slots=True)
class RuntimeTable:
    """The pinned set of fetchable runtime builds.

    Attributes:
        build: The llama.cpp release tag every variant here comes from.
        generated: When the table was pinned.
        release_url: The upstream release page.
        cuda_toolkit: CUDA version the pinned CUDA build links against.
        min_cuda_driver_major: Driver major version that toolkit requires.
        min_compute_capability: Lowest GPU compute capability the build supports.
        warn_below_vram_bytes: Below this, CUDA works but is not worth the download.
        artifacts: Every pinned variant.
    """

    build: str
    generated: str = ""
    release_url: str = ""
    cuda_toolkit: str = ""
    min_cuda_driver_major: int = 0
    min_compute_capability: float = 0.0
    warn_below_vram_bytes: int = 0
    artifacts: tuple[RuntimeArtifact, ...] = ()

    def for_platform(self, key: str | None = None) -> tuple[RuntimeArtifact, ...]:
        """Variants available for one platform, best backend first."""
        target = key or platform_key()
        chosen = [a for a in self.artifacts if a.platform == target]
        from .backends import BACKEND_RANK

        return tuple(sorted(chosen, key=lambda a: BACKEND_RANK.get(a.backend, 0), reverse=True))

    def artifact(self, backend: str, *, key: str | None = None) -> RuntimeArtifact | None:
        """One variant by backend, for this platform."""
        for candidate in self.for_platform(key):
            if candidate.backend == backend:
                return candidate
        return None


@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    """A validated ``runtime.json`` describing an installed variant.

    Attributes:
        backend: The acceleration family this build targets.
        build: The llama.cpp build id it was cut from.
        architecture: The machine architecture it runs on.
        executable: Absolute path to ``llama-server``.
        directory: The variant directory.
    """

    backend: AcceleratorKind
    build: str
    architecture: str
    executable: Path
    directory: Path


# ---- locations ---------------------------------------------------------------------------


def runtime_root() -> Path:
    """Where runtime variants are installed.

    Follows the same per-OS data-dir convention as the model directory, so a user who knows
    where one lives can find the other. Overridable with ``ANYINFER_RUNTIME_DIR``.
    """
    override = os.environ.get("ANYINFER_RUNTIME_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "anyinfer" / "runtimes"


def platform_key(*, os_name: str | None = None, arch: str | None = None) -> str:
    """This machine's ``"<platform>-<arch>"`` key, matching the pinned table."""
    system = os_name or sys.platform
    machine = (arch or platform.machine()).lower()
    return f"{system}-{_ARCH_ALIASES.get(machine, machine)}"


# ---- the pinned table ----------------------------------------------------------------------


def load_runtime_table(path: Path | None = None) -> RuntimeTable:
    """Load the pinned runtime table.

    Raises:
        LocalRuntimeError: If the bundled table is unreadable or malformed. Unlike the
            probes, this is real data shipped with the package: a broken table is a build
            defect, not a property of the user's machine.
    """
    try:
        if path is None:
            resource = files("anyinfer.local").joinpath("runtimes.json")
            with resource.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LocalRuntimeError(
            f"the pinned runtime table could not be read: {exc}",
            hint="reinstall anyinfer; this file ships with the package",
        ) from exc

    requirements = data.get("cuda_requirements", {})
    artifacts = tuple(_parse_artifact(entry) for entry in data.get("variants", []))
    return RuntimeTable(
        build=str(data.get("build", "")),
        generated=str(data.get("generated", "")),
        release_url=str(data.get("release_url", "")),
        cuda_toolkit=str(requirements.get("toolkit", "")),
        min_cuda_driver_major=int(requirements.get("min_driver_major", 0)),
        min_compute_capability=float(requirements.get("min_compute_capability", 0.0)),
        warn_below_vram_bytes=int(requirements.get("warn_below_vram_bytes", 0)),
        artifacts=artifacts,
    )


def _parse_artifact(entry: Mapping[str, Any]) -> RuntimeArtifact:
    """Parse one pinned variant, including its companion archives."""
    companions = tuple(
        RuntimeArtifact(
            platform=str(entry.get("platform", "")),
            backend=cast("AcceleratorKind", str(entry.get("backend", "cpu"))),
            filename=str(c["filename"]),
            url=str(c["url"]),
            sha256=str(c["sha256"]),
            size_bytes=c.get("size_bytes"),
        )
        for c in entry.get("companions", [])
    )
    return RuntimeArtifact(
        platform=str(entry.get("platform", "")),
        backend=cast("AcceleratorKind", str(entry.get("backend", "cpu"))),
        filename=str(entry["filename"]),
        url=str(entry["url"]),
        sha256=str(entry["sha256"]),
        size_bytes=entry.get("size_bytes"),
        companions=companions,
    )


# ---- manifests ------------------------------------------------------------------------------


def read_manifest(directory: Path, *, build: str | None = None) -> RuntimeManifest | None:
    """Validate an installed variant, or return ``None``.

    Every check is a reason the variant does not exist: a manifest naming an unknown
    backend, a different build than this AnyInfer pins, a foreign architecture, or an
    executable that resolves outside its own directory. Returning ``None`` rather than
    raising keeps a tampered or stale install from breaking discovery for the others.
    """
    manifest_path = directory / MANIFEST_NAME
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    from .backends import BACKEND_RANK

    backend = str(data.get("backend", ""))
    if backend not in BACKEND_RANK:
        return None

    architecture = str(data.get("architecture", ""))
    if architecture and _ARCH_ALIASES.get(architecture.lower(), architecture.lower()) != (
        _ARCH_ALIASES.get(platform.machine().lower(), platform.machine().lower())
    ):
        return None

    manifest_build = str(data.get("build", ""))
    if build is not None and manifest_build != build:
        return None

    executable = str(data.get("executable", ""))
    if not executable:
        return None
    resolved = (directory / executable).resolve()
    # Containment is checked *after* resolution, so a symlink cannot point the manifest at
    # an executable elsewhere on the machine.
    try:
        resolved.relative_to(directory.resolve())
    except ValueError:
        return None
    if not resolved.exists():
        return None

    return RuntimeManifest(
        backend=backend,
        build=manifest_build,
        architecture=architecture,
        executable=resolved,
        directory=directory,
    )


def installed_runtimes(
    root: Path | None = None, *, build: str | None = None
) -> list[RuntimeManifest]:
    """Every validated runtime variant under the runtime root."""
    base = root or runtime_root()
    if not base.is_dir():
        return []
    found: list[RuntimeManifest] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        manifest = read_manifest(entry, build=build)
        if manifest is not None:
            found.append(manifest)
    return found


def _write_manifest(directory: Path, *, backend: str, build: str, executable: Path) -> None:
    """Record a variant as installed, atomically."""
    payload = {
        "format_version": _MANIFEST_VERSION,
        "backend": backend,
        "build": build,
        "architecture": _ARCH_ALIASES.get(platform.machine().lower(), platform.machine().lower()),
        "executable": executable.relative_to(directory).as_posix(),
    }
    temporary = directory / f"{MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(directory / MANIFEST_NAME)


# ---- selection --------------------------------------------------------------------------------


def default_runtime_kind(hardware: HardwareProfile | None) -> AcceleratorKind:
    """Which variant to install when the caller expresses no preference.

    Never CUDA. The vendor-neutral small builds cover every GPU well enough to be useful
    immediately, and a several-hundred-megabyte download is a decision a user makes, not one
    a library makes on their behalf:

    - Apple Silicon → Metal, which needs no vendor runtime and is the native path.
    - Intel Mac → CPU; llama.cpp's Metal backend targets Apple Silicon.
    - Windows or Linux with any GPU → Vulkan, which drives NVIDIA, AMD, and Intel alike.
    - Anything else → CPU.
    """
    # `platform.system()` rather than `sys.platform`: mypy narrows the latter to whichever
    # host the type check runs on, which makes everything past this branch read as dead
    # code under `warn_unreachable` on a macOS checkout. Same test, no narrowing.
    if platform.system() == "Darwin":
        return "metal" if platform.machine().lower() in ("arm64", "aarch64") else "cpu"
    if hardware is not None and hardware.has_accelerator:
        return "vulkan"
    return "cpu"


def check_cuda_preconditions(
    hardware: HardwareProfile, table: RuntimeTable
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(blocking_reasons, warnings)`` for installing the CUDA add-on.

    The pinned build implies a CUDA toolkit version, which implies a minimum driver and a
    minimum compute capability. Checking them up front turns "your GPU is too old" into a
    clear refusal before a 400 MB download instead of an incomprehensible crash at load.
    """
    blocking: list[str] = []
    warnings: list[str] = []

    devices = [a for a in hardware.accelerators if a.kind == "cuda"]
    if not devices:
        blocking.append(
            "no NVIDIA device was detected (nvidia-smi reported nothing); the CUDA runtime "
            "would have nothing to drive"
        )
        return tuple(blocking), tuple(warnings)

    best = max(devices, key=lambda d: d.compute_capability_value or 0.0)

    capability = best.compute_capability_value
    if capability is None:
        blocking.append(
            "this driver did not report a compute capability, so CUDA support cannot be "
            f"confirmed (the pinned build needs {table.min_compute_capability} or newer)"
        )
    elif capability < table.min_compute_capability:
        blocking.append(
            f"{best.name or 'this GPU'} reports compute capability {capability}, below the "
            f"{table.min_compute_capability} the pinned CUDA {table.cuda_toolkit} build needs"
        )

    driver = best.driver_major
    if driver is None:
        warnings.append("the NVIDIA driver version could not be read; install may fail at load")
    elif driver < table.min_cuda_driver_major:
        blocking.append(
            f"NVIDIA driver {best.driver_version} is below {table.min_cuda_driver_major}, the "
            f"minimum for CUDA {table.cuda_toolkit}"
        )

    vram = best.total_vram_bytes
    if vram is not None and table.warn_below_vram_bytes and vram < table.warn_below_vram_bytes:
        warnings.append(
            f"{best.name or 'this GPU'} has {vram / 1024**3:.1f} GiB of VRAM; CUDA will work "
            "but only small models will fit"
        )

    return tuple(blocking), tuple(warnings)


# ---- installation ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstallReport:
    """The outcome of installing a runtime variant.

    Attributes:
        backend: Which variant was installed.
        build: The build id it came from.
        directory: Where it landed.
        executable: The ``llama-server`` inside it.
        downloaded_bytes: Bytes actually transferred (zero when everything was cached).
        reused: Whether an already-valid install was kept.
        warnings: Non-blocking notes, including CUDA precondition warnings.
    """

    backend: AcceleratorKind
    build: str
    directory: Path
    executable: Path
    downloaded_bytes: int = 0
    reused: bool = False
    warnings: tuple[str, ...] = ()


def install_runtime(
    kind: AcceleratorKind | None = None,
    *,
    hardware: HardwareProfile | None = None,
    root: Path | None = None,
    table: RuntimeTable | None = None,
    progress: ProgressCallback | None = None,
    client: httpx2.Client | None = None,
    force: bool = False,
) -> InstallReport:
    """Fetch, verify, and unpack a llama-server runtime variant.

    Args:
        kind: Which backend to install. ``None`` picks `default_runtime_kind`, which is
            never CUDA.
        hardware: Detected hardware, needed for the default choice and the CUDA gate.
        root: Runtime root; defaults to `runtime_root()`.
        table: Pinned artifact table; defaults to the bundled one.
        progress: Download progress callback.
        client: An ``httpx2.Client``, for tests or custom transports.
        force: Install CUDA even when the precondition checks object. Never skips digest
            verification — only the hardware gate.

    Returns:
        A report naming the executable to launch.

    Raises:
        LocalRuntimeError: If no build exists for this platform and backend, if a CUDA
            precondition fails without ``force``, or if the archive fails verification or
            cannot be unpacked.
    """
    pinned = table or load_runtime_table()
    backend = kind or default_runtime_kind(hardware)
    warnings: list[str] = []

    if backend == "cuda":
        if hardware is None:
            raise LocalRuntimeError(
                "installing the CUDA runtime needs a hardware profile to check against",
                hint="pass hardware=anyinfer.local.detect(), or use force=True",
            )
        blocking, cuda_warnings = check_cuda_preconditions(hardware, pinned)
        warnings.extend(cuda_warnings)
        if blocking and not force:
            raise LocalRuntimeError(
                "this machine does not meet the CUDA runtime's requirements: "
                + "; ".join(blocking),
                hint=(
                    "install the Vulkan runtime instead — it drives NVIDIA GPUs too, or "
                    "pass force=True if you are certain"
                ),
            )
        warnings.extend(f"installed despite: {reason}" for reason in blocking)

    artifact = pinned.artifact(backend)
    if artifact is None:
        available = ", ".join(sorted({a.backend for a in pinned.for_platform()})) or "(none)"
        raise LocalRuntimeError(
            f"no pinned {backend} llama-server build exists for {platform_key()}",
            hint=f"available for this platform: {available}",
        )

    base = root or runtime_root()
    directory = base / backend
    existing = read_manifest(directory, build=pinned.build)
    if existing is not None and not force:
        return InstallReport(
            backend=backend,
            build=pinned.build,
            directory=directory,
            executable=existing.executable,
            reused=True,
            warnings=tuple(warnings),
        )

    staging = base / ".staging" / backend
    _clear(staging)
    staging.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    for member in (artifact, *artifact.companions):
        report = download_artifact(
            GgufArtifact(
                id=f"runtime-{backend}-{member.filename}",
                files=(
                    GgufFile(
                        filename=member.filename,
                        url=member.url,
                        sha256=member.sha256,
                        size_bytes=member.size_bytes,
                    ),
                ),
            ),
            model_dir=staging,
            progress=progress,
            client=client,
        )
        downloaded += report.downloaded_bytes
        _unpack(report.primary_path, staging)

    executable = _find_executable(staging)
    if executable is None:
        _clear(staging)
        raise LocalRuntimeError(
            f"the {backend} runtime archive contained no llama-server executable",
            hint="the pinned artifact table may be stale; re-run scripts/pin_runtimes.py",
        )

    _write_manifest(staging, backend=backend, build=pinned.build, executable=executable)
    _swap(staging, directory)

    installed = read_manifest(directory, build=pinned.build)
    if installed is None:
        raise LocalRuntimeError(
            f"the {backend} runtime failed validation after installation",
            hint=f"inspect {directory / MANIFEST_NAME}",
        )
    return InstallReport(
        backend=backend,
        build=pinned.build,
        directory=directory,
        executable=installed.executable,
        downloaded_bytes=downloaded,
        warnings=tuple(warnings),
    )


def remove_runtime(kind: AcceleratorKind, *, root: Path | None = None) -> bool:
    """Delete an installed runtime variant. Returns whether anything was removed."""
    directory = (root or runtime_root()) / kind
    if not directory.is_dir():
        return False
    shutil.rmtree(directory, ignore_errors=True)
    return not directory.exists()


# ---- archive handling ---------------------------------------------------------------------------


def _unpack(archive: Path, destination: Path) -> None:
    """Extract an archive, rejecting any member that would escape ``destination``.

    Archive members are remote input, so the containment check is not optional; a
    ``../`` member in a tarball is the oldest write-anywhere trick there is.

    Raises:
        LocalRuntimeError: On an unreadable archive or an escaping member.
    """
    root = destination.resolve()
    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as bundle:
                for name in bundle.namelist():
                    _assert_contained(root, name)
                bundle.extractall(destination)
        else:
            with tarfile.open(archive) as bundle:
                for member in bundle.getmembers():
                    _assert_contained(root, member.name)
                    if member.issym() or member.islnk():
                        _assert_contained(root, member.linkname)
                bundle.extractall(destination, filter="data")
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise LocalRuntimeError(
            f"could not unpack {archive.name}: {exc}",
            hint="the download may be corrupt; delete it and retry",
        ) from exc
    with contextlib.suppress(OSError):
        archive.unlink()


def _assert_contained(root: Path, name: str) -> None:
    """Reject an archive member whose path leaves the destination."""
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise LocalRuntimeError(
            f"archive member {name!r} would be written outside the runtime directory",
            hint="this archive is not trustworthy; report it upstream",
        ) from None


def _find_executable(directory: Path) -> Path | None:
    """Locate ``llama-server`` in an unpacked archive, whatever depth it landed at."""
    for name in _BINARY_NAMES:
        direct = directory / name
        if direct.is_file():
            return direct
    for name in _BINARY_NAMES:
        for found in sorted(directory.rglob(name)):
            if found.is_file():
                return found
    return None


def _swap(staging: Path, target: Path) -> None:
    """Move a staged install into place, replacing any previous one.

    Staged then swapped rather than written in place, so an interrupted install never
    leaves a half-unpacked directory that a manifest check would have to catch later.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        retired = target.with_name(f"{target.name}.old")
        _clear(retired)
        target.replace(retired)
        try:
            staging.replace(target)
        finally:
            _clear(retired)
    else:
        staging.replace(target)


def _clear(path: Path) -> None:
    """Remove a directory tree if it exists, ignoring failures."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def install_hint(hardware: HardwareProfile | None, table: RuntimeTable | None = None) -> str:
    """A one-line suggestion of which runtime this machine should install."""
    pinned = table or load_runtime_table()
    kind = default_runtime_kind(hardware)
    artifact = pinned.artifact(kind)
    size = f" (~{artifact.total_bytes / 1024**2:.0f} MiB)" if artifact else ""
    if hardware is not None and any(a.kind == "cuda" for a in hardware.accelerators):
        return (
            f"install the {kind} runtime{size} to get started; on this NVIDIA device the "
            "CUDA runtime gives better throughput and can be installed explicitly"
        )
    return f"install the {kind} runtime{size}"
