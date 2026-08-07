"""Hardware detection for local inference.

**Advisory only.** Detection *proposes*; callers decide. Every probe is best-effort: a
missing tool, a permission error, or an unparseable output produces a warning and a ``None``
field, never an exception. A wrong number here would silently mis-tune a server, so unknown
is always preferred to guessed — the same discipline as the capability model's provenance.

Results are disk-cached, keyed by a signature of the probe executables themselves, so
installing a GPU driver invalidates the cache without the user knowing they had to.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "CACHE_BYPASS_ENV",
    "CACHE_REFRESH_ENV",
    "Accelerator",
    "AcceleratorKind",
    "HardwareProfile",
    "cache_path",
    "detect",
    "probe_signature",
]

CACHE_BYPASS_ENV = "ANYINFER_HARDWARE_CACHE_BYPASS"
"""Set to skip the cache entirely (read *and* write)."""

CACHE_REFRESH_ENV = "ANYINFER_HARDWARE_CACHE_REFRESH"
"""Set to ignore a cached result and re-probe, then rewrite the cache."""

_IS_WINDOWS = sys.platform == "win32"
_PROBE_TIMEOUT_S = 6.0
_PROBE_EXECUTABLES = ("nvidia-smi", "rocm-smi", "vulkaninfo", "lspci", "system_profiler")

AcceleratorKind = Literal["cuda", "rocm", "metal", "vulkan", "cpu"]
"""Accelerator families we can detect and target."""


@dataclass(frozen=True, slots=True)
class Accelerator:
    """One detected accelerator.

    Attributes:
        kind: Which runtime family can drive it.
        name: Human-readable device name, when reported.
        total_vram_bytes: Total device memory, or ``None`` when unknown.
        free_vram_bytes: Free device memory at probe time, or ``None``.
        unified_memory: True when device memory is shared with system RAM (Apple Silicon),
            which makes VRAM budgeting a different calculation entirely.
        compute_capability: NVIDIA compute capability as reported by the driver
            (``"8.9"``), or ``None``. Quantized kernels gate on this — FP8 needs 8.9, the
            Marlin GPTQ kernel needs 8.0 — and an unknown capability must *exclude* a gated
            variant rather than optimistically permit it.
        driver_version: Vendor driver version string, when reported. Used to check that a
            downloadable CUDA runtime's toolkit version is supported before installing it.
    """

    kind: AcceleratorKind
    name: str | None = None
    total_vram_bytes: int | None = None
    free_vram_bytes: int | None = None
    unified_memory: bool = False
    compute_capability: str | None = None
    driver_version: str | None = None

    @property
    def compute_capability_value(self) -> float | None:
        """`compute_capability` as a comparable number, or ``None`` when unparseable."""
        return _parse_float(self.compute_capability)

    @property
    def driver_major(self) -> int | None:
        """The major component of `driver_version`, or ``None``."""
        if not self.driver_version:
            return None
        match = re.match(r"\s*(\d+)", self.driver_version)
        return int(match.group(1)) if match else None


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    """What we could learn about this machine.

    Every field may be ``None``: absence means "not determined", never "zero".

    Attributes:
        os_name: ``"windows"``, ``"linux"``, ``"darwin"``, or the raw platform string.
        arch: Machine architecture as reported by `platform.machine()`.
        total_ram_bytes: Physical RAM.
        available_ram_bytes: RAM currently free, when the platform reports it.
        cpu_name: Processor model string.
        physical_cores: Physical core count, preferred for thread tuning.
        logical_cores: Logical processor count.
        accelerators: Detected accelerators, strongest first.
        warnings: Everything that could not be determined, and why.
        detected_at: Unix timestamp of the probe, for cache display.
    """

    os_name: str
    arch: str
    total_ram_bytes: int | None = None
    available_ram_bytes: int | None = None
    cpu_name: str | None = None
    physical_cores: int | None = None
    logical_cores: int | None = None
    accelerators: tuple[Accelerator, ...] = ()
    warnings: tuple[str, ...] = ()
    detected_at: float = 0.0

    @property
    def primary_accelerator(self) -> Accelerator | None:
        """The accelerator a server should target, or ``None`` for CPU-only."""
        return self.accelerators[0] if self.accelerators else None

    @property
    def has_accelerator(self) -> bool:
        """Whether any non-CPU accelerator was detected."""
        return any(a.kind != "cpu" for a in self.accelerators)

    @property
    def total_vram_bytes(self) -> int | None:
        """Total memory of the primary accelerator, when known."""
        primary = self.primary_accelerator
        return primary.total_vram_bytes if primary else None

    @classmethod
    def from_user_input(
        cls,
        *,
        ram_gb: float | None = None,
        vram_gb: float | None = None,
        accelerator: AcceleratorKind | None = None,
        accelerator_name: str | None = None,
        compute_capability: str | None = None,
        os_name: str = "",
        arch: str = "",
    ) -> HardwareProfile:
        """Build a profile from specs a person supplied, in familiar units.

        The remote-Ollama case: local probing describes the wrong machine, and no Ollama
        API reports its host's specs, so asking the user is the only honest source. Values
        arrive in gigabytes because that is what a user reads off a spec sheet; anything
        left out stays ``None`` and keeps its "not determined" meaning.

        The profile is marked as self-reported in `warnings`, so any advice derived from it
        can say so.
        """
        accelerators: tuple[Accelerator, ...] = ()
        if accelerator is not None and accelerator != "cpu":
            accelerators = (
                Accelerator(
                    kind=accelerator,
                    name=accelerator_name,
                    total_vram_bytes=_gb_to_bytes(vram_gb),
                    unified_memory=accelerator == "metal",
                    compute_capability=compute_capability,
                ),
            )
        return cls(
            os_name=os_name,
            arch=arch,
            total_ram_bytes=_gb_to_bytes(ram_gb),
            accelerators=accelerators,
            warnings=("these specs were supplied by the user, not measured",),
        )

    @property
    def user_supplied(self) -> bool:
        """Whether this profile came from `from_user_input` rather than a probe."""
        return any("supplied by the user" in warning for warning in self.warnings)

    def to_json(self) -> dict[str, Any]:
        """Serialize for the disk cache."""
        return {
            "os_name": self.os_name,
            "arch": self.arch,
            "total_ram_bytes": self.total_ram_bytes,
            "available_ram_bytes": self.available_ram_bytes,
            "cpu_name": self.cpu_name,
            "physical_cores": self.physical_cores,
            "logical_cores": self.logical_cores,
            "accelerators": [
                {
                    "kind": a.kind,
                    "name": a.name,
                    "total_vram_bytes": a.total_vram_bytes,
                    "free_vram_bytes": a.free_vram_bytes,
                    "unified_memory": a.unified_memory,
                    "compute_capability": a.compute_capability,
                    "driver_version": a.driver_version,
                }
                for a in self.accelerators
            ],
            "warnings": list(self.warnings),
            "detected_at": self.detected_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> HardwareProfile:
        """Deserialize from the disk cache."""
        return cls(
            os_name=str(data.get("os_name", "")),
            arch=str(data.get("arch", "")),
            total_ram_bytes=_opt_int(data.get("total_ram_bytes")),
            available_ram_bytes=_opt_int(data.get("available_ram_bytes")),
            cpu_name=data.get("cpu_name"),
            physical_cores=_opt_int(data.get("physical_cores")),
            logical_cores=_opt_int(data.get("logical_cores")),
            accelerators=tuple(
                Accelerator(
                    kind=entry.get("kind", "cpu"),
                    name=entry.get("name"),
                    total_vram_bytes=_opt_int(entry.get("total_vram_bytes")),
                    free_vram_bytes=_opt_int(entry.get("free_vram_bytes")),
                    unified_memory=bool(entry.get("unified_memory")),
                    compute_capability=entry.get("compute_capability"),
                    driver_version=entry.get("driver_version"),
                )
                for entry in data.get("accelerators", [])
                if isinstance(entry, dict)
            ),
            warnings=tuple(str(w) for w in data.get("warnings", [])),
            detected_at=float(data.get("detected_at", 0.0)),
        )


# ---- probe plumbing ------------------------------------------------------------------


def _run(command: list[str]) -> str | None:
    """Run a probe command, returning stdout or ``None`` on any failure.

    Never raises: a detector that can crash the caller is worse than no detector.
    """
    executable = shutil.which(command[0])
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
            **_hidden_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return str(completed.stdout)


def _hidden_window_kwargs() -> dict[str, Any]:
    """Keep probe subprocesses from flashing a console window on Windows.

    Attributes are looked up dynamically because they exist only on Windows, and this
    module must typecheck identically on every platform.
    """
    if not _IS_WINDOWS:
        return {}
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", None)
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", None)
    if startupinfo_cls is None or show_window is None or no_window is None:
        return {}
    startupinfo = startupinfo_cls()
    startupinfo.dwFlags |= show_window
    return {"startupinfo": startupinfo, "creationflags": no_window}


def probe_signature() -> str:
    """Fingerprint the probe tooling, so the cache invalidates when it changes.

    Keyed on the resolved path and mtime of each probe executable plus the interpreter's
    platform: installing a GPU driver, or moving to different hardware, changes this.
    """
    parts = [platform.platform(), platform.machine(), sys.platform]
    for name in _PROBE_EXECUTABLES:
        resolved = shutil.which(name)
        if resolved is None:
            parts.append(f"{name}:absent")
            continue
        try:
            stat = Path(resolved).stat()
            parts.append(f"{name}:{resolved}:{int(stat.st_mtime)}:{stat.st_size}")
        except OSError:
            parts.append(f"{name}:{resolved}:unstattable")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


# ---- RAM -----------------------------------------------------------------------------


def _detect_ram() -> tuple[int | None, int | None, str | None]:
    """Return ``(total, available, warning)`` bytes of system RAM."""
    if _IS_WINDOWS:
        return _detect_ram_windows()

    # ``os.sysconf`` is POSIX-only; look it up dynamically so this module typechecks
    # identically on Windows.
    sysconf = getattr(os, "sysconf", None)
    if sysconf is not None:
        with contextlib.suppress(AttributeError, ValueError, OSError):
            page_size = int(sysconf("SC_PAGE_SIZE"))
            total = page_size * int(sysconf("SC_PHYS_PAGES"))
            available: int | None = None
            with contextlib.suppress(AttributeError, ValueError, OSError):
                available = page_size * int(sysconf("SC_AVPHYS_PAGES"))
            return total, available, None

    if sys.platform == "darwin":
        output = _run(["sysctl", "-n", "hw.memsize"])
        if output and output.strip().isdigit():
            return int(output.strip()), None, None

    return None, None, "could not determine system RAM on this platform"


def _detect_ram_windows() -> tuple[int | None, int | None, str | None]:
    """Read total and available RAM via ``GlobalMemoryStatusEx``."""
    import ctypes

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, None, "GlobalMemoryStatusEx reported failure"
    except (AttributeError, OSError) as exc:
        return None, None, f"could not query Windows memory status: {exc}"
    return int(status.ullTotalPhys), int(status.ullAvailPhys), None


# ---- CPU -----------------------------------------------------------------------------


def _detect_cpu() -> tuple[str | None, int | None, int | None, str | None]:
    """Return ``(name, physical_cores, logical_cores, warning)``."""
    logical = os.cpu_count()
    name: str | None = None
    physical: int | None = None

    if _IS_WINDOWS:
        output = _run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Processor | "
                "Select-Object -Property Name,NumberOfCores | ConvertTo-Json -Compress",
            ]
        )
        parsed = _parse_json(output)
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else None
        if isinstance(parsed, dict):
            name = _clean(parsed.get("Name"))
            physical = _opt_int(parsed.get("NumberOfCores"))
    elif sys.platform == "darwin":
        name = _clean(_run(["sysctl", "-n", "machdep.cpu.brand_string"]))
        cores = _run(["sysctl", "-n", "hw.physicalcpu"])
        if cores and cores.strip().isdigit():
            physical = int(cores.strip())
    else:
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            with contextlib.suppress(OSError):
                text = cpuinfo.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"^model name\s*:\s*(.+)$", text, re.MULTILINE)
                if match:
                    name = match.group(1).strip()
                ids = set(re.findall(r"^core id\s*:\s*(\d+)$", text, re.MULTILINE))
                physical = len(ids) or None

    warning = None if name else "could not determine the CPU model"
    return name, physical, logical, warning


# ---- accelerators --------------------------------------------------------------------


def _detect_accelerators() -> tuple[list[Accelerator], list[str]]:
    """Detect accelerators, strongest family first."""
    warnings: list[str] = []
    found: list[Accelerator] = []

    nvidia = _detect_nvidia()
    if nvidia:
        found.extend(nvidia)

    if not found:
        rocm = _detect_rocm()
        if rocm:
            found.extend(rocm)

    if not found and sys.platform == "darwin":
        metal = _detect_metal()
        if metal:
            found.append(metal)

    if not found:
        vulkan = _detect_vulkan()
        if vulkan:
            found.append(vulkan)
            warnings.append(
                "only a Vulkan-capable device was detected; VRAM is unknown, so tuning "
                "will be conservative"
            )

    if not found:
        warnings.append("no accelerator detected; local inference will run on the CPU")

    return found, warnings


def _detect_nvidia() -> list[Accelerator]:
    """Query ``nvidia-smi`` for device names, memory, compute capability, and driver.

    ``compute_cap`` is not present on older drivers, so the query is retried without it
    rather than losing the whole probe: a missing capability must read as ``None``, which
    excludes capability-gated variants, not as a failure to detect the GPU at all.
    """
    fields = "name,memory.total,memory.free,compute_cap,driver_version"
    output = _run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"])
    if not output:
        fields = "name,memory.total,memory.free"
        output = _run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"])
    if not output:
        return []

    devices: list[Accelerator] = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        devices.append(
            Accelerator(
                kind="cuda",
                name=parts[0] or None,
                total_vram_bytes=_mib_to_bytes(parts[1]),
                free_vram_bytes=_mib_to_bytes(parts[2]),
                compute_capability=_clean(parts[3]) if len(parts) > 3 else None,
                driver_version=_clean(parts[4]) if len(parts) > 4 else None,
            )
        )
    return devices


def _detect_rocm() -> list[Accelerator]:
    """Query ``rocm-smi`` for AMD device memory."""
    output = _run(["rocm-smi", "--showmeminfo", "vram", "--json"])
    parsed = _parse_json(output)
    if not isinstance(parsed, dict):
        return []
    devices: list[Accelerator] = []
    for key, value in parsed.items():
        if not key.lower().startswith("card") or not isinstance(value, dict):
            continue
        total = None
        used = None
        for field_name, raw in value.items():
            lowered = field_name.lower()
            number = _opt_int(raw) if not isinstance(raw, str) else _digits(raw)
            if number is None:
                continue
            if "total" in lowered:
                total = number
            elif "used" in lowered:
                used = number
        free = total - used if total is not None and used is not None else None
        devices.append(Accelerator(kind="rocm", total_vram_bytes=total, free_vram_bytes=free))
    return devices


def _detect_metal() -> Accelerator | None:
    """Detect Apple Silicon, whose GPU memory is unified with system RAM."""
    if platform.machine().lower() not in ("arm64", "aarch64"):
        return None
    output = _run(["system_profiler", "SPDisplaysDataType"])
    name = None
    if output:
        match = re.search(r"Chipset Model:\s*(.+)", output)
        if match:
            name = match.group(1).strip()
    return Accelerator(kind="metal", name=name, unified_memory=True)


def _detect_vulkan() -> Accelerator | None:
    """Detect any Vulkan-capable device as a last-resort accelerator."""
    output = _run(["vulkaninfo", "--summary"])
    if not output:
        return None
    match = re.search(r"deviceName\s*=\s*(.+)", output)
    return Accelerator(kind="vulkan", name=match.group(1).strip() if match else None)


# ---- assembly ------------------------------------------------------------------------


def _probe() -> HardwareProfile:
    """Run every probe and assemble a profile."""
    warnings: list[str] = []

    total_ram, available_ram, ram_warning = _detect_ram()
    if ram_warning:
        warnings.append(ram_warning)

    cpu_name, physical, logical, cpu_warning = _detect_cpu()
    if cpu_warning:
        warnings.append(cpu_warning)

    accelerators, accel_warnings = _detect_accelerators()
    warnings.extend(accel_warnings)

    return HardwareProfile(
        os_name=sys.platform,
        arch=platform.machine(),
        total_ram_bytes=total_ram,
        available_ram_bytes=available_ram,
        cpu_name=cpu_name,
        physical_cores=physical,
        logical_cores=logical,
        accelerators=tuple(accelerators),
        warnings=tuple(warnings),
        detected_at=time.time(),
    )


def cache_path() -> Path:
    """Where the detection cache lives."""
    if _IS_WINDOWS:
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "anyinfer" / "hardware.json"


def detect(*, use_cache: bool = True) -> HardwareProfile:
    """Detect this machine's hardware.

    Never raises: anything that could not be determined becomes a warning and a ``None``
    field. Callers treat the result as advice, not as fact.

    Args:
        use_cache: Read and write the disk cache. Overridden by
            `CACHE_BYPASS_ENV` and `CACHE_REFRESH_ENV`.

    Returns:
        The detected profile.
    """
    bypass = bool(os.environ.get(CACHE_BYPASS_ENV))
    refresh = bool(os.environ.get(CACHE_REFRESH_ENV))
    caching = use_cache and not bypass
    signature = probe_signature()

    if caching and not refresh:
        cached = _read_cache(signature)
        if cached is not None:
            return cached

    profile = _probe()
    if caching:
        _write_cache(signature, profile)
    return profile


def _read_cache(signature: str) -> HardwareProfile | None:
    """Read a cached profile, ignoring it if the probe signature changed."""
    path = cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("signature") != signature:
        return None
    payload = data.get("profile")
    if not isinstance(payload, dict):
        return None
    try:
        return HardwareProfile.from_json(payload)
    except (TypeError, ValueError):
        return None


def _write_cache(signature: str, profile: HardwareProfile) -> None:
    """Write the cache atomically, ignoring any failure."""
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"signature": signature, "profile": profile.to_json()}, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        # A read-only or full cache directory must not break detection.
        return


# ---- small helpers -------------------------------------------------------------------


def _parse_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _digits(text: str) -> int | None:
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def _parse_float(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.strip())
    except ValueError:
        return None


def _gb_to_bytes(value: float | None) -> int | None:
    """Convert a user-facing gigabyte figure to bytes, treating 0 as "not stated"."""
    if value is None or value <= 0:
        return None
    return int(value * 1024**3)


def _mib_to_bytes(text: str) -> int | None:
    value = _digits(text)
    return value * 1024 * 1024 if value is not None else None


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip()
    return cleaned or None
