"""Best-effort live host utilization samples for local benchmark displays.

These readings are advisory. Missing platform facilities produce ``None`` rather than a
guessed zero, and collecting a sample never raises. The sampler keeps only the previous CPU
counter snapshot needed to turn cumulative operating-system counters into a percentage.
"""

from __future__ import annotations

import contextlib
import json
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ResourceSample", "StorageProfile", "SystemSampler", "storage_profile"]


@dataclass(frozen=True, slots=True)
class ResourceSample:
    """One instantaneous host-utilization observation.

    Percentages range from 0 to 100. ``None`` means the platform did not expose a safe,
    dependency-free reading.
    """

    cpu_percent: float | None = None
    ram_percent: float | None = None
    gpu_percent: float | None = None
    vram_percent: float | None = None
    ram_used_bytes: int | None = None
    vram_used_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class StorageProfile:
    """Capacity facts for the filesystem holding a path."""

    path: str
    total_bytes: int | None = None
    free_bytes: int | None = None


class SystemSampler:
    """Stateful sampler for CPU, RAM, GPU, and VRAM utilization."""

    def __init__(self) -> None:
        self._cpu_previous: tuple[int, int] | None = None

    def sample(self) -> ResourceSample:
        """Read one sample, leaving unsupported values unknown."""
        cpu = self._cpu()
        ram_percent, ram_used = _ram()
        gpu_percent, vram_percent, vram_used = _gpu()
        return ResourceSample(
            cpu_percent=cpu,
            ram_percent=ram_percent,
            gpu_percent=gpu_percent,
            vram_percent=vram_percent,
            ram_used_bytes=ram_used,
            vram_used_bytes=vram_used,
        )

    def _cpu(self) -> float | None:
        counters = _cpu_counters()
        if counters is None:
            return None
        previous = self._cpu_previous
        self._cpu_previous = counters
        if previous is None:
            return None
        total_delta = counters[0] - previous[0]
        idle_delta = counters[1] - previous[1]
        if total_delta <= 0:
            return None
        return _percent((total_delta - idle_delta) / total_delta * 100.0)


def storage_profile(path: Path | str) -> StorageProfile:
    """Return capacity/free-space facts for ``path`` without performing a speed test."""
    candidate = Path(path).expanduser()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    try:
        usage = shutil.disk_usage(candidate)
    except OSError:
        return StorageProfile(path=str(candidate))
    return StorageProfile(
        path=str(candidate), total_bytes=usage.total, free_bytes=usage.free
    )


def _cpu_counters() -> tuple[int, int] | None:
    if _platform_system() == "Linux":
        try:
            fields = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()[1:]
            values = [int(value) for value in fields]
        except (OSError, ValueError, IndexError):
            return None
        if len(values) < 4:
            return None
        return sum(values), values[3] + (values[4] if len(values) > 4 else 0)
    if _platform_system() == "Windows":
        with contextlib.suppress(Exception):
            import ctypes

            idle = ctypes.c_ulonglong()
            kernel = ctypes.c_ulonglong()
            user = ctypes.c_ulonglong()
            kernel32 = ctypes.__dict__["windll"].kernel32
            if kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            ):
                return int(kernel.value + user.value), int(idle.value)
    return None


def _ram() -> tuple[float | None, int | None]:
    if _platform_system() == "Linux":
        try:
            text = Path("/proc/meminfo").read_text(encoding="ascii")
        except OSError:
            return None, None
        values = {
            key: int(value) * 1024
            for key, value in re.findall(r"^(MemTotal|MemAvailable):\s+(\d+) kB", text, re.M)
        }
        total, available = values.get("MemTotal"), values.get("MemAvailable")
        if total and available is not None:
            used = max(0, total - available)
            return _percent(used / total * 100.0), used
    if _platform_system() == "Windows":
        with contextlib.suppress(Exception):
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong),
                    ("available", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong),
                    ("available_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended", ctypes.c_ulonglong),
                ]

            status = Status()
            status.length = ctypes.sizeof(Status)
            kernel32 = ctypes.__dict__["windll"].kernel32
            if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return float(status.load), int(status.total - status.available)
    return None, None


def _gpu() -> tuple[float | None, float | None, int | None]:
    """Prefer vendor readings that expose both compute and memory utilization."""
    nvidia = _nvidia()
    return nvidia if nvidia[0] is not None else _rocm()


def _nvidia() -> tuple[float | None, float | None, int | None]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None, None, None
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None, None
    if completed.returncode != 0:
        return None, None, None
    rows: list[tuple[float, float, float]] = []
    for line in completed.stdout.splitlines():
        try:
            gpu, used, total = (float(value.strip()) for value in line.split(",")[:3])
        except (TypeError, ValueError):
            continue
        rows.append((gpu, used, total))
    if not rows:
        return None, None, None
    gpu_percent = sum(row[0] for row in rows) / len(rows)
    used_mib = sum(row[1] for row in rows)
    total_mib = sum(row[2] for row in rows)
    vram_percent = used_mib / total_mib * 100.0 if total_mib > 0 else None
    normalized_vram = _percent(vram_percent) if vram_percent is not None else None
    return _percent(gpu_percent), normalized_vram, round(used_mib * 1024**2)


def _rocm() -> tuple[float | None, float | None, int | None]:
    executable = shutil.which("rocm-smi")
    if executable is None:
        return None, None, None
    try:
        completed = subprocess.run(
            [executable, "--showuse", "--showmemuse", "--json"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        payload = json.loads(completed.stdout) if completed.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None
    gpu_values: list[float] = []
    memory_values: list[float] = []
    for device in payload.values():
        if not isinstance(device, dict):
            continue
        for key, raw in device.items():
            match = re.search(r"-?\d+(?:\.\d+)?", str(raw))
            if match is None:
                continue
            value = float(match.group())
            lowered = str(key).casefold()
            if "gpu use" in lowered:
                gpu_values.append(value)
            elif "memory" in lowered and "%" in lowered:
                memory_values.append(value)
    gpu = sum(gpu_values) / len(gpu_values) if gpu_values else None
    memory = sum(memory_values) / len(memory_values) if memory_values else None
    return (
        _percent(gpu) if gpu is not None else None,
        _percent(memory) if memory is not None else None,
        None,
    )


def _percent(value: float) -> float:
    return max(0.0, min(100.0, value))


def _platform_system() -> str:
    """Keep platform branching runtime-driven for cross-platform type checking."""
    return platform.system()
