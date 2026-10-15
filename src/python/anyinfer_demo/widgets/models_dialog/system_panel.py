"""The detected hardware profile and the model-fit overview derived from it."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from anyinfer import CatalogView, Measurement
from anyinfer.local.downloads import default_model_dir
from anyinfer.local.metrics import storage_profile

from ...engine import Engine
from ..formatting import _bytes


def _vendor_mark(name: str | None, kind: str, *, cpu: bool = False) -> tuple[str, str]:
    """Return a compact, non-logo vendor mark and its familiar accent color."""
    lowered = (name or "").casefold()
    if "nvidia" in lowered or "geforce" in lowered or "quadro" in lowered:
        return "NVIDIA", "#76b900"
    if any(token in lowered for token in ("amd", "ryzen", "radeon")):
        return ("AMD RYZEN" if cpu and "ryzen" in lowered else "AMD"), "#ed1c24"
    if "intel" in lowered:
        return "INTEL", "#0071c5"
    if "apple" in lowered or kind == "metal":
        return "APPLE SILICON", "#666666"
    return ("CPU" if cpu else kind.upper()), "#2c7a6f"


class _HardwareCard(QFrame):
    """A graphical hardware summary card with a vendor mark and optional memory gauge."""

    def __init__(self, heading: str) -> None:
        super().__init__()
        self.setObjectName("HardwareCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        header = QHBoxLayout()
        self._mark = QLabel("—")
        self._mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mark.setMinimumWidth(72)
        self._mark.setFixedHeight(28)
        self._mark.setAccessibleName(f"{heading} vendor")
        header.addWidget(self._mark)
        self._heading = QLabel(heading)
        self._heading.setObjectName("HardwareCardHeading")
        header.addWidget(self._heading, 1)
        layout.addLayout(header)

        self._name = QLabel("Detecting…")
        self._name.setWordWrap(True)
        self._name.setObjectName("HardwareCardName")
        layout.addWidget(self._name)
        self._details = QLabel()
        self._details.setWordWrap(True)
        self._details.setObjectName("Muted")
        layout.addWidget(self._details)

        self._gauge = QProgressBar()
        self._gauge.setAccessibleName(f"{heading} available memory")
        self._gauge.setRange(0, 1000)
        self._gauge.setVisible(False)
        layout.addWidget(self._gauge)
        layout.addStretch(1)

    def set_data(
        self,
        *,
        name: str,
        mark: str,
        accent: str,
        details: Sequence[str],
        available: int | None = None,
        total: int | None = None,
    ) -> None:
        """Replace the card contents with one detected component."""
        self._mark.setText(mark)
        mark_text = _contrasting_text_color(accent)
        self._mark.setStyleSheet(
            f"background: {accent}; color: {mark_text}; border-radius: 7px; "
            "font-size: 8pt; font-weight: 700; padding: 2px 7px;"
        )
        self._name.setText(name)
        self._details.setText("<br>".join(details))
        show_gauge = total is not None and total > 0 and available is not None
        self._gauge.setVisible(show_gauge)
        if total is not None and total > 0 and available is not None:
            fraction = max(0.0, min(1.0, available / total))
            self._gauge.setValue(round(fraction * 1000))
            self._gauge.setFormat(f"{_bytes(available)} available of {_bytes(total)}")


def _contrasting_text_color(background: str) -> str:
    """Choose black or white according to WCAG relative contrast with ``background``."""
    color = QColor(background)
    if not color.isValid():
        return "#ffffff"

    def luminance(candidate: QColor) -> float:
        channels = (candidate.redF(), candidate.greenF(), candidate.blueF())
        linear = tuple(
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        )
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    background_luminance = luminance(color)
    white_contrast = 1.05 / (background_luminance + 0.05)
    black_contrast = (background_luminance + 0.05) / 0.05
    return "#ffffff" if white_contrast >= black_contrast else "#000000"


class _SystemPanel(QWidget):
    """Detected hardware and the model-fit overview derived from it."""

    benchmark_requested = Signal()

    def __init__(
        self,
        engine: Engine,
    ) -> None:
        super().__init__()
        self._engine = engine

        layout = QVBoxLayout(self)
        intro = QLabel(
            "A detected hardware profile drives the fit verdicts in Catalog. Memory fit "
            "answers <i>what can run</i>; the Benchmark tab measures <i>how it runs</i>."
        )
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        cards = QGridLayout()
        cards.setSpacing(10)
        self._cpu = _HardwareCard("Processor")
        self._memory = _HardwareCard("System memory")
        self._gpu = _HardwareCard("Accelerator")
        self._storage = _HardwareCard("Model storage")
        self._platform = _HardwareCard("Platform & runtime")
        cards.addWidget(self._cpu, 0, 0)
        cards.addWidget(self._memory, 0, 1)
        cards.addWidget(self._gpu, 1, 0)
        cards.addWidget(self._storage, 1, 1)
        cards.addWidget(self._platform, 2, 0, 1, 2)
        cards.setColumnStretch(0, 1)
        cards.setColumnStretch(1, 1)
        layout.addLayout(cards)

        self._recommendations = QLabel("<i>Reading model-fit recommendations…</i>")
        self._recommendations.setWordWrap(True)
        self._recommendations.setTextFormat(Qt.TextFormat.RichText)
        self._recommendations.setObjectName("SystemRecommendation")
        layout.addWidget(self._recommendations)

        self._warnings = QLabel()
        self._warnings.setWordWrap(True)
        self._warnings.setObjectName("HintText")
        self._warnings.setVisible(False)
        layout.addWidget(self._warnings)

        score = QGroupBox("Measured capability")
        score_layout = QHBoxLayout(score)
        self._capability = QLabel(
            "No benchmark yet. A single universal score would hide the model, runtime, "
            "context size, and workload that produced it, so AnyInfer reports those "
            "measurements directly."
        )
        self._capability.setWordWrap(True)
        score_layout.addWidget(self._capability, 1)
        self._benchmark_button = QPushButton("Benchmark this system…")
        self._benchmark_button.clicked.connect(self.benchmark_requested)
        score_layout.addWidget(self._benchmark_button)
        layout.addWidget(score)
        layout.addStretch(1)

    def on_catalog(self, view: CatalogView) -> None:
        """Render the same hardware profile and fit results the catalog uses."""
        hardware = view.hardware
        if hardware is None:
            for card, heading in (
                (self._cpu, "CPU"),
                (self._memory, "RAM"),
                (self._gpu, "GPU"),
                (self._platform, "SYSTEM"),
            ):
                card.set_data(
                    name="Not detected",
                    mark=heading,
                    accent="#666666",
                    details=("Hardware-based guidance is unavailable.",),
                )
            self._recommendations.setText(
                "<b>Model guidance unavailable.</b> Open Catalog for the reason and "
                "supply the remote host profile when applicable."
            )
            return

        cpu_mark, cpu_color = _vendor_mark(hardware.cpu_name, "cpu", cpu=True)
        core_parts = []
        if hardware.physical_cores is not None:
            core_parts.append(f"{hardware.physical_cores} physical cores")
        if hardware.logical_cores is not None:
            core_parts.append(f"{hardware.logical_cores} logical processors")
        self._cpu.set_data(
            name=hardware.cpu_name or "Processor name unavailable",
            mark=cpu_mark,
            accent=cpu_color,
            details=(
                " · ".join(core_parts) or "Core counts unavailable",
                hardware.arch or "Unknown architecture",
            ),
        )

        memory_details = [f"{_bytes(hardware.total_ram_bytes)} installed"]
        if hardware.available_ram_bytes is not None:
            memory_details.append(f"{_bytes(hardware.available_ram_bytes)} available at detection")
        self._memory.set_data(
            name="Physical RAM",
            mark="RAM",
            accent="#e8963c",
            details=memory_details,
            available=hardware.available_ram_bytes,
            total=hardware.total_ram_bytes,
        )

        storage = storage_profile(default_model_dir())
        storage_details = [f"Model store: {storage.path}"]
        if storage.total_bytes is not None:
            storage_details.insert(0, f"{_bytes(storage.total_bytes)} filesystem capacity")
        if storage.free_bytes is not None:
            storage_details.append(f"{_bytes(storage.free_bytes)} free now")
        self._storage.set_data(
            name="Filesystem containing model weights",
            mark="DISK",
            accent="#596780",
            details=storage_details,
            available=storage.free_bytes,
            total=storage.total_bytes,
        )

        accelerator = hardware.primary_accelerator
        if accelerator is None:
            self._gpu.set_data(
                name="No discrete accelerator detected",
                mark="CPU",
                accent="#666666",
                details=("Models can still run with the CPU backend.",),
            )
        else:
            gpu_mark, gpu_color = _vendor_mark(accelerator.name, accelerator.kind)
            memory_line = f"{accelerator.kind.upper()} backend"
            if accelerator.total_vram_bytes is not None:
                memory_line += f" · {_bytes(accelerator.total_vram_bytes)} VRAM"
            gpu_details = [memory_line]
            compute_line = []
            if accelerator.compute_capability:
                compute_line.append(f"Compute capability {accelerator.compute_capability}")
            if accelerator.driver_version:
                compute_line.append(f"Driver {accelerator.driver_version}")
            if compute_line:
                gpu_details.append(" · ".join(compute_line))
            if accelerator.unified_memory:
                gpu_details.append("Unified system/device memory")
            if len(hardware.accelerators) > 1:
                gpu_details.append(f"{len(hardware.accelerators)} accelerators detected")
            self._gpu.set_data(
                name=accelerator.name or accelerator.kind.upper(),
                mark=gpu_mark,
                accent=gpu_color,
                details=gpu_details,
                available=accelerator.free_vram_bytes,
                total=accelerator.total_vram_bytes,
            )

        detected = (
            datetime.fromtimestamp(hardware.detected_at).astimezone().strftime("%b %d, %Y %H:%M")
            if hardware.detected_at
            else "time unavailable"
        )
        backend = view.backend
        platform_details = [f"Profile: {view.hardware_source} · {detected}"]
        if backend is not None:
            platform_details.append(f"Selected runtime: {backend.kind.upper()}")
        else:
            platform_details.append("No llama.cpp runtime selected")
        self._platform.set_data(
            name=f"{hardware.os_name or 'Unknown OS'} · {hardware.arch or 'unknown architecture'}",
            mark=(backend.kind.upper() if backend is not None else "OS"),
            accent="#2c7a6f",
            details=platform_details,
        )
        if backend is not None and backend.detail:
            self._platform.setToolTip(backend.detail)

        runnable = [entry for entry in view.entries if entry.fit.runnable]
        accelerated = sum(entry.fit.level == "gpu" for entry in runnable)
        cpu_only = sum(entry.fit.level == "cpu" for entry in runnable)
        tight = sum(entry.fit.level == "tight" for entry in runnable)
        examples = ", ".join(entry.name for entry in runnable[:3]) or "none"
        self._recommendations.setText(
            f"<b>{len(runnable)} of {len(view.entries)} catalog models are reasonable "
            f"memory fits:</b> {accelerated} accelerated, {cpu_only} CPU, {tight} tight. "
            f"Best-fit examples: {examples}. See Catalog for model-by-model reasons."
        )
        self._warnings.setText("<br>".join(f"• {warning}" for warning in hardware.warnings))
        self._warnings.setVisible(bool(hardware.warnings))

    def on_benchmark(self, measurement: Measurement) -> None:
        """Show the last warm measurement without turning it into a synthetic score."""
        target = f"{measurement.identity.provider_id}:{measurement.identity.model}"
        decode = (
            f"{measurement.decode_tokens_per_s:.1f} tok/s decode"
            if measurement.decode_tokens_per_s is not None
            else "decode rate unavailable"
        )
        ttft = (
            f"{measurement.ttft_ms:.0f} ms first token"
            if measurement.ttft_ms is not None
            else "first-token time unavailable"
        )
        self._capability.setText(
            f"<b>{target}</b>: {decode} · {ttft}. This is a workload-specific measured "
            "profile, not a universal hardware score."
        )
