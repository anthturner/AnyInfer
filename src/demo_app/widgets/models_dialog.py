"""Local inference: system hardware, the model catalog, store, and runtimes.

The chat window shows what a *configured* engine can already do. This dialog shows the
step before that, which for a local engine is most of the work: choosing weights that fit
the machine, fetching them, and having a llama.cpp build to run them with.

Everything here is one library call per button. `Client.local_catalog()`
already annotates every entry with how it fits *this* computer, `acquire_model()`
already plans, downloads, verifies, and indexes, and `install_runtime()` already
picks the right build for the detected accelerator. None of that is re-implemented here —
the panels below are tables over those return values, which is the point: an application
integrating AnyInfer does not write a downloader.

Four tabs, each answering a separate operator question:

===========  ==========================================================================
Panel        Question it answers
===========  ==========================================================================
System       What hardware and storage can local inference use?
Benchmark    How does one installed target perform under this workload?
Catalog      What could I run here, would it fit, and where is it installed?
Runtimes     What can actually execute it, and is the right accelerator build present?
===========  ==========================================================================

Catalog is the unified model inventory. It preserves ownership explicitly: AnyInfer-managed
weights and models reported by engine-owned stores appear together, while the ``Installed
For`` column records who owns each installation and therefore which removal operation is safe.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anyinfer import BenchmarkSample, CatalogView, Measurement
from anyinfer.errors import AnyInferError
from anyinfer.local.acquire import AcquisitionProgress, AcquisitionReport
from anyinfer.local.downloads import default_model_dir
from anyinfer.local.hardware import HardwareProfile
from anyinfer.local.metrics import storage_profile
from anyinfer.local.runtimes import InstallReport
from anyinfer.local.server import is_loopback
from anyinfer.local.store import RemovalReport, StoreEntry
from anyinfer.local.tuning import Posture
from anyinfer.types.capabilities import DiscoveredModel

from ..config import DemoConfig
from ..engine import Engine, RuntimeInstallProgress
from ..fake_provider import DEMO_PROVIDER_ID
from .add_model_dialog import AddModelChoice, AddModelDialog, catalog_model_choice
from .icons import brand_icon
from .sdk_help import SdkHelpButton
from .tab_widget import BorderedTabWidget

__all__ = ["ModelsDialog"]

_CATALOG_KEY = "models.catalog"
_INSTALLED_KEY = "models.installed"
_ACQUIRE_KEY = "models.acquire"
_PLAN_KEY = "models.plan"
_REMOVE_KEY = "models.remove"
_PULL_KEY = "models.pull"
_RUNTIMES_KEY = "models.runtimes"
_INSTALL_RUNTIME_KEY = "models.install-runtime"
_BENCHMARK_KEY = "models.benchmark"
"""Keys tagging each background call, so an answer lands in the panel that asked for it.

The engine runs local work on a pool of its own, so two of these can be outstanding at
once — a catalog refresh while a download runs is the ordinary case, not an edge one.
"""

_POSTURES: tuple[Posture, ...] = ("conservative", "balanced", "aggressive")
"""The tuning postures a fit verdict can be computed at.

Named here rather than typed inline so the combo box and the value handed back to the
library cannot drift apart, and so a posture the planner has no rule for cannot be
selected at all.
"""

_FIT_LABELS = {
    "gpu": "✓ GPU",
    "cpu": "◐ CPU only",
    "tight": "▲ Tight",
    "no": "✕ Will not fit",
}
"""Plain-language rendering of `FitLevel`.

Worth spelling out rather than printing the enum: "cpu" is not a failure and "tight" is not
a refusal, and a bare lowercase word next to a green tick reads like one or the other.
"""

_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("deepseek", "DeepSeek"),
    ("devstral", "Mistral"),
    ("ministral", "Mistral"),
    ("mixtral", "Mistral"),
    ("mistral", "Mistral"),
    ("qwen", "Qwen"),
    ("qwq", "Qwen"),
    ("llama", "Llama"),
    ("phi", "Phi"),
    ("gemma", "Gemma"),
    ("granite", "Granite"),
    ("falcon", "Falcon"),
    ("glm", "GLM"),
    ("gpt-oss", "GPT-OSS"),
    ("hermes", "Hermes"),
    ("olmo", "OLMo"),
    ("smollm", "SmolLM"),
    ("starcoder", "StarCoder"),
)
"""Stable broad-family labels used to group catalog and engine-owned model ids."""


def _family_label(family_or_model_id: str) -> str:
    """Return a broad display family from catalog metadata or an external model id."""
    candidate = family_or_model_id.rsplit("/", 1)[-1].casefold()
    for prefix, label in _FAMILY_PREFIXES:
        if candidate.startswith(prefix) or f"-{prefix}" in candidate:
            return label
    return "Other"


class _PlainSortTableWidgetItem(QTableWidgetItem):
    """A table item that sorts by plain code-point order, not the host's locale.

    `QTableWidgetItem`'s default comparison collates through the OS's locale — on
    Windows and macOS that is typically case-insensitive-ish, on a minimal Linux
    container with no locale configured it is plain byte order — so a user's model list
    would resort itself differently depending on what machine they run the app on.
    """

    def __lt__(self, other: object) -> bool:
        if isinstance(other, QTableWidgetItem):
            return self.text() < other.text()
        return NotImplemented


def _bytes(count: int | None) -> str:
    """Format a byte count for a table cell, or an em dash when it is unknown.

    An em dash rather than ``0``: the catalog genuinely does not know the size of every
    entry, and a zero there would read as a free download.
    """
    if count is None:
        return "—"
    size = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


class _LlamaSetupPrompt(QWidget):
    """One shared prerequisite notice for llama.cpp-owned surfaces."""

    setup_requested = Signal()

    def __init__(self, purpose: str) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        message = QLabel(f"<b>llama.cpp provider required.</b> Add it before {purpose}.")
        message.setTextFormat(Qt.TextFormat.RichText)
        message.setWordWrap(True)
        layout.addWidget(message, 1)
        self.button = QPushButton("Add llama.cpp with defaults")
        self.button.setAccessibleName("Add llama.cpp provider with defaults")
        self.button.setToolTip(
            "Enable one llama.cpp provider using its built-in paths, balanced resource "
            "posture, and per-user model store."
        )
        self.button.clicked.connect(self.setup_requested)
        layout.addWidget(self.button)

    def set_ready(self, ready: bool) -> None:
        """Hide the prerequisite once an enabled llama.cpp instance exists."""
        self.setVisible(not ready)


def _llama_cpp_enabled(config: DemoConfig) -> bool:
    """Whether configuration contains at least one enabled llama.cpp instance."""
    return any(
        provider.enabled and provider.provider_id == "llama-cpp" for provider in config.providers
    )


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


class _LineChart(QWidget):
    """Small dependency-free line chart for benchmark telemetry."""

    _COLORS = ("#2c7a6f", "#d97706", "#4f46e5", "#c026d3", "#dc2626")

    def __init__(self, title: str, unit: str, *, fixed_max: float | None = None) -> None:
        super().__init__()
        self._title = title
        self._unit = unit
        self._fixed_max = fixed_max
        self._series: dict[str, list[QPointF]] = {}
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def clear(self) -> None:
        """Drop every plotted point."""
        self._series.clear()
        self.update()

    def add_point(self, series: str, elapsed_ms: float, value: float | None) -> None:
        """Append one known value; unknown readings leave a visible gap."""
        if value is None:
            return
        self._series.setdefault(series, []).append(QPointF(elapsed_ms / 1000.0, value))
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 — Qt virtual name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        foreground = self.palette().color(self.foregroundRole())
        muted = QColor(foreground)
        muted.setAlpha(90)
        painter.setPen(foreground)
        painter.drawText(10, 20, self._title)

        plot = QRectF(44, 34, max(20, self.width() - 58), max(30, self.height() - 64))
        painter.setPen(QPen(muted, 1))
        painter.drawRect(plot)
        points = [point for values in self._series.values() for point in values]
        maximum_x = max((point.x() for point in points), default=1.0)
        maximum_y = self._fixed_max or max((point.y() for point in points), default=1.0)
        maximum_x = max(maximum_x, 1.0)
        maximum_y = max(maximum_y, 1.0)
        painter.drawText(4, round(plot.top() + 5), f"{maximum_y:.0f}{self._unit}")
        painter.drawText(round(plot.right() - 30), self.height() - 8, f"{maximum_x:.1f}s")

        legend_x = round(plot.left())
        for index, (name, values) in enumerate(self._series.items()):
            color = QColor(self._COLORS[index % len(self._COLORS)])
            painter.setPen(QPen(color, 2))
            mapped = [
                QPointF(
                    plot.left() + point.x() / maximum_x * plot.width(),
                    plot.bottom() - point.y() / maximum_y * plot.height(),
                )
                for point in values
            ]
            for start, end in pairwise(mapped):
                painter.drawLine(start, end)
            painter.setPen(color)
            painter.drawText(legend_x, self.height() - 8, name)
            legend_x += painter.fontMetrics().horizontalAdvance(name) + 18


def _is_local_target(engine: Engine, config: DemoConfig, target: str) -> bool:
    """Whether a concrete target executes on the machine this dialog can observe."""
    provider_id, separator, model = target.partition(":")
    if not separator or not provider_id or not model:
        return False
    provider = config.for_provider(provider_id)
    if not provider.enabled:
        return False
    try:
        descriptor = engine.registry.get(provider.provider_id)
    except AnyInferError:
        return False
    if descriptor.id == DEMO_PROVIDER_ID or descriptor.locality != "local":
        return False
    endpoint = provider.base_url or descriptor.default_base_url
    return endpoint is None or is_loopback(endpoint)


class _BenchmarkPanel(QWidget):
    """Live cold/warm benchmark charts over installed local targets."""

    def __init__(self, engine: Engine, config: DemoConfig, initial_target: str = "") -> None:
        super().__init__()
        self._engine = engine
        self._config = config
        self._initial_target = initial_target
        self._installed: tuple[StoreEntry, ...] = ()
        self._provider_models: dict[str, tuple[DiscoveredModel, ...]] = {}

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Runs the same deterministic request twice. The first series includes model "
            "load and warmup; the second is the immediately-following warm run. Live host "
            "utilization is best-effort and unknown values are omitted, never shown as zero."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(QLabel("Installed local target:"))
        self._benchmark_target = QComboBox()
        self._benchmark_target.setAccessibleName("Installed local target to benchmark")
        self._benchmark_target.currentTextChanged.connect(self._update_benchmark_button)
        row.addWidget(self._benchmark_target, 1)
        self._benchmark_button = QPushButton("Run cold + warm benchmark")
        self._benchmark_button.clicked.connect(self.start)
        row.addWidget(self._benchmark_button)
        row.addWidget(SdkHelpButton("local-system"))
        layout.addLayout(row)

        self._empty = QLabel(
            "<i>No installed local model is available. Download one in Catalog, or pull "
            "one into a configured local engine.</i>"
        )
        self._empty.setWordWrap(True)
        self._empty.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._empty)

        self._benchmark_progress = QProgressBar()
        self._benchmark_progress.setRange(0, 0)
        self._benchmark_progress.setFormat("Waiting to benchmark…")
        self._benchmark_progress.setAccessibleName("Benchmark progress")
        self._benchmark_progress.setVisible(False)
        layout.addWidget(self._benchmark_progress)

        charts = QGridLayout()
        self._tokens_chart = _LineChart("Decode throughput over time", " tok/s")
        self._resources_chart = _LineChart("Host utilization over time", "%", fixed_max=100)
        charts.addWidget(self._tokens_chart, 0, 0)
        charts.addWidget(self._resources_chart, 0, 1)
        charts.setColumnStretch(0, 1)
        charts.setColumnStretch(1, 1)
        layout.addLayout(charts)

        results = QGridLayout()
        results.addWidget(QLabel(""), 0, 0)
        results.addWidget(QLabel("First run"), 0, 1)
        results.addWidget(QLabel("Warm run"), 0, 2)
        self._result_values: dict[tuple[int, int], QLabel] = {}
        for result_row, title in enumerate(
            ("Time to first token", "Prefill", "Decode", "Model load", "Total"), 1
        ):
            results.addWidget(QLabel(title), result_row, 0)
            for column in (1, 2):
                value = QLabel("—")
                value.setObjectName("BenchmarkValue")
                results.addWidget(value, result_row, column)
                self._result_values[(result_row, column)] = value
        results.setColumnStretch(1, 1)
        results.setColumnStretch(2, 1)
        layout.addLayout(results)

        self._benchmark_note = QLabel(
            "No measurement yet. Results are specific to the selected model, runtime, "
            "context size, and current machine load."
        )
        self._benchmark_note.setWordWrap(True)
        self._benchmark_note.setObjectName("HintText")
        layout.addWidget(self._benchmark_note)
        self._repopulate_targets()

    def set_providers(self, config: DemoConfig) -> None:
        """Adopt provider changes and discard inventories for removed instances."""
        self._config = config
        valid = set(config.instance_ids())
        self._provider_models = {
            key: models for key, models in self._provider_models.items() if key in valid
        }
        self._repopulate_targets()

    def on_installed(self, entries: Sequence[StoreEntry]) -> None:
        """Adopt the AnyInfer-owned model inventory."""
        self._installed = tuple(entries)
        self._repopulate_targets()

    def on_provider_models(self, instance_id: str, models: Sequence[DiscoveredModel]) -> None:
        """Adopt an engine-owned installed/served inventory."""
        self._provider_models[instance_id] = tuple(models)
        self._repopulate_targets()

    def _repopulate_targets(self) -> None:
        selected = (
            self._benchmark_target.currentText() if hasattr(self, "_benchmark_target") else ""
        )
        targets: list[str] = []

        llama_instances = [
            provider.instance_id
            for provider in self._config.enabled_providers()
            if provider.provider_id == "llama-cpp"
        ]
        installed = sorted(
            self._installed,
            key=lambda entry: (entry.total_bytes <= 0, entry.total_bytes, entry.model_id),
        )
        for entry in installed:
            if entry.engine not in ("llama.cpp", "llama-cpp") or not entry.variant_id:
                continue
            targets.extend(f"{instance}:{entry.variant_id}" for instance in llama_instances)

        for instance, models in self._provider_models.items():
            provider = self._config.for_provider(instance)
            try:
                descriptor = self._engine.registry.get(provider.provider_id)
            except AnyInferError:
                continue
            if descriptor.model_inventory == "available":
                continue
            targets.extend(f"{instance}:{model.id}" for model in models)

        for target in (*self._config.targets, self._initial_target):
            if _is_local_target(self._engine, self._config, target):
                targets.append(target)

        unique = list(dict.fromkeys(targets))
        self._benchmark_target.blockSignals(True)
        self._benchmark_target.clear()
        self._benchmark_target.addItems(unique)
        preferred = selected or self._initial_target
        index = self._benchmark_target.findText(preferred)
        if index >= 0:
            self._benchmark_target.setCurrentIndex(index)
        self._benchmark_target.blockSignals(False)
        self._empty.setVisible(not unique)
        self._update_benchmark_button()

    def _update_benchmark_button(self, *_args: object) -> None:
        self._benchmark_button.setEnabled(
            _is_local_target(
                self._engine, self._config, self._benchmark_target.currentText().strip()
            )
            and not self._benchmark_progress.isVisible()
        )

    def start(self) -> None:
        """Start the two-run measurement when an installed target is selected."""
        target = self._benchmark_target.currentText().strip()
        if not _is_local_target(self._engine, self._config, target):
            self._benchmark_note.setText(
                "Install a local model first; the benchmark will not silently download "
                "weights or choose a workload for you."
            )
            return
        self._tokens_chart.clear()
        self._resources_chart.clear()
        self._benchmark_progress.setVisible(True)
        self._benchmark_progress.setFormat("First run: loading and warmup…")
        self._benchmark_button.setEnabled(False)
        self._benchmark_note.setText(
            f"Running two deterministic requests against <code>{target}</code>…"
        )
        self._engine.benchmark_pair(_BENCHMARK_KEY, target)

    def on_progress(self, run: int, sample: BenchmarkSample) -> None:
        """Append one live point to the cold or warm chart series."""
        prefix = "First" if run == 1 else "Warm"
        if run == 2:
            self._benchmark_progress.setFormat("Warm run: measuring steady-state…")
        self._tokens_chart.add_point(prefix, sample.elapsed_ms, sample.output_tokens_per_s)
        resources = sample.resources
        for label, value in (
            (f"{prefix} CPU", resources.cpu_percent),
            (f"{prefix} GPU", resources.gpu_percent),
            (f"{prefix} RAM", resources.ram_percent),
            (f"{prefix} VRAM", resources.vram_percent),
        ):
            self._resources_chart.add_point(label, sample.elapsed_ms, value)

    def on_benchmark(self, first: Measurement, second: Measurement) -> None:
        """Show cold and warm terminal measurements."""
        self._benchmark_progress.setVisible(False)
        self._update_benchmark_button()

        def milliseconds(value: float | None) -> str:
            return f"{value:.0f} ms" if value is not None else "—"

        def rate(value: float | None) -> str:
            return f"{value:.1f} tok/s" if value is not None else "—"

        for column, measurement in ((1, first), (2, second)):
            values = (
                milliseconds(measurement.ttft_ms),
                rate(measurement.prefill_tokens_per_s),
                rate(measurement.decode_tokens_per_s),
                milliseconds(measurement.model_load_ms),
                milliseconds(measurement.total_ms),
            )
            for result_row, value in enumerate(values, 1):
                self._result_values[(result_row, column)].setText(value)
        target = f"{second.identity.provider_id}:{second.identity.model}"
        self._benchmark_note.setText(
            f"<b>Measured {target}.</b> The warm series is the steady-state comparison; "
            "the first series exposes load and warmup cost."
        )

    def on_benchmark_failed(self, message: str) -> None:
        """Restore controls after a failed request."""
        self._benchmark_progress.setVisible(False)
        self._update_benchmark_button()
        self._benchmark_note.setText(message)

    def benchmark_context(self) -> str:
        """Return the measured-target note when a benchmark has completed."""
        text = self._benchmark_note.text()
        return text if text.startswith("<b>Measured ") else ""


class _CatalogPanel(QWidget):
    """The catalog and installed inventories, annotated with fit and ownership.

    Sorted by the library, filtered here. The filter is the only logic in this panel:
    deciding *whether* something fits is `ModelFit`'s job, and re-deriving it
    from sizes would be the demo quietly growing a second opinion.
    """

    quick_llama_setup_requested = Signal()
    """Emitted when the user asks the host application to enable llama.cpp defaults."""
    add_requested = Signal()
    """Emitted when the user wants to search or name a model to install."""
    action_requested = Signal(object, bool)
    """Emitted with a resolved model operation and whether it is only a dry run."""

    def __init__(self, engine: Engine, config: DemoConfig) -> None:
        super().__init__()
        self._engine = engine
        self._view: CatalogView | None = None
        self._store_entries: tuple[StoreEntry, ...] = ()
        self._provider_models: dict[str, tuple[DiscoveredModel, ...]] = {}
        self._provider_engines: dict[str, str] = {}
        self._config = config
        self._llama_cpp_ready = False

        layout = QVBoxLayout(self)

        self._provider_notice = _LlamaSetupPrompt(
            "downloading catalog models so the demo can run the weights you acquire"
        )
        self._quick_setup = self._provider_notice.button
        self._provider_notice.setup_requested.connect(self.quick_llama_setup_requested)
        layout.addWidget(self._provider_notice)

        self._notes = QLabel()
        self._notes.setTextFormat(Qt.TextFormat.RichText)
        self._notes.setWordWrap(True)
        self._notes.setObjectName("HintText")
        layout.addWidget(self._notes)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Engine:"))
        self._engine_filter = QComboBox()
        self._engine_filter.addItem("Any", "")
        self._engine_filter.setAccessibleName("Filter catalog by engine")
        self._engine_filter.currentIndexChanged.connect(self._repopulate)
        controls.addWidget(self._engine_filter)

        self._runnable_only = QCheckBox("Only what fits")
        self._runnable_only.setToolTip(
            "Hide entries this machine cannot run. The verdict is the library's, from "
            "detected RAM and VRAM at the selected posture."
        )
        self._runnable_only.stateChanged.connect(self._repopulate)
        controls.addWidget(self._runnable_only)

        controls.addWidget(QLabel("Posture:"))
        self._posture = QComboBox()
        self._posture.addItems(_POSTURES)
        self._posture.setCurrentText("balanced")
        self._posture.setToolTip(
            "How much of this machine a model may claim. It changes the fit verdicts "
            "below, so it is a property of the question rather than of the answer."
        )
        self._posture.currentTextChanged.connect(lambda *_: self.refresh())
        controls.addWidget(self._posture)

        controls.addStretch(1)
        controls.addWidget(SdkHelpButton("catalog"))
        layout.addLayout(controls)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            [
                "Model",
                "Family",
                "Size",
                "Context",
                "Fit",
                "Engines",
                "Installed For",
                "License",
            ]
        )
        self._table.setAccessibleName("Model catalog")
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4, 5, 6, 7):
            self._table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, 1)

        self._why = QLabel()
        self._why.setWordWrap(True)
        self._why.setObjectName("HintText")
        layout.addWidget(self._why)

        buttons = QHBoxLayout()
        self._add = QPushButton("Add…")
        self._add.setToolTip(
            "Search verified catalog models, or name a model for an engine-owned store."
        )
        self._add.clicked.connect(self.add_requested)
        buttons.addWidget(self._add)

        self._plan = QPushButton("What would this download?")
        self._plan.setToolTip(
            "A dry run: resolve the artifact and report its files and byte count without "
            "fetching anything."
        )
        self._plan.setEnabled(False)
        self._plan.clicked.connect(self._on_plan)
        buttons.addWidget(self._plan)

        self._download = QPushButton("Download")
        self._download.setEnabled(False)
        self._download.clicked.connect(self._on_download)
        buttons.addWidget(self._download)

        self._remove = QPushButton("Remove")
        self._remove.setEnabled(False)
        self._remove.setToolTip("Delete the selected AnyInfer-managed weights.")
        self._remove.clicked.connect(self._on_remove)
        buttons.addWidget(self._remove)
        buttons.addStretch(1)
        buttons.addWidget(SdkHelpButton("acquisition"))
        layout.addLayout(buttons)

        self.set_providers(config)

    def set_providers(self, config: DemoConfig) -> None:
        """Gate catalog acquisition on an enabled llama.cpp provider instance."""
        self._config = config
        self._llama_cpp_ready = _llama_cpp_enabled(config)
        self._provider_notice.set_ready(self._llama_cpp_ready)
        self._on_selection_changed()

    def set_provider_instances(self, instances: dict[str, str]) -> None:
        """Track local provider instances and discard discoveries for removed ones."""
        self._provider_engines = dict(instances)
        self._provider_models = {
            instance: models
            for instance, models in self._provider_models.items()
            if instance in instances
        }
        self._repopulate()

    def on_installed(self, entries: Sequence[StoreEntry]) -> None:
        """Adopt AnyInfer-managed models from the local store index."""
        self._store_entries = tuple(entries)
        self._repopulate()

    def on_provider_models(self, instance_id: str, models: Sequence[DiscoveredModel]) -> None:
        """Adopt models reported by an engine-owned local service."""
        if instance_id not in self._provider_engines:
            return
        self._provider_models[instance_id] = tuple(models)
        self._repopulate()

    def refresh(self) -> None:
        """Re-read the catalog at the selected posture."""
        chosen = self._posture.currentText()
        posture: Posture = chosen if chosen in _POSTURES else "balanced"
        self._engine.local_catalog(_CATALOG_KEY, None, posture=posture)

    def on_catalog(self, view: CatalogView) -> None:
        """Adopt a freshly read catalog."""
        self._view = view
        self._notes.setText("<br>".join(f"• {note}" for note in view.notes) if view.notes else "")
        self._notes.setVisible(bool(view.notes))

        chosen = self._engine_filter.currentData()
        channels = sorted(
            {
                *(channel for entry in view.entries for channel in entry.channels),
                *self._provider_engines.values(),
                *(
                    "llama-cpp" if entry.engine in ("llama.cpp", "llama-cpp") else entry.engine
                    for entry in self._store_entries
                ),
            }
        )
        self._engine_filter.blockSignals(True)
        self._engine_filter.clear()
        self._engine_filter.addItem("Any", "")
        for channel in channels:
            self._engine_filter.addItem(channel, channel)
        index = self._engine_filter.findData(chosen)
        self._engine_filter.setCurrentIndex(max(index, 0))
        self._engine_filter.blockSignals(False)

        self._repopulate()

    def selected_model(self) -> str:
        """The catalog id of the highlighted row, or an empty string."""
        items = self._table.selectedItems()
        if not items:
            return ""
        data = self._table.item(items[0].row(), 0)
        value = data.data(Qt.ItemDataRole.UserRole) if data else None
        return value if isinstance(value, str) else ""

    def selected_engine(self) -> str | None:
        """The provider filter's current value, or ``None`` when unfiltered."""
        data = self._engine_filter.currentData()
        return data if isinstance(data, str) and data else None

    def _repopulate(self) -> None:
        view = self._view
        sort_column = self._table.horizontalHeader().sortIndicatorSection()
        sort_order = self._table.horizontalHeader().sortIndicatorOrder()
        sorting_enabled = self._table.isSortingEnabled()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        if view is None:
            self._table.setSortingEnabled(sorting_enabled)
            return
        wanted = self._engine_filter.currentData()
        entries = view.runnable if self._runnable_only.isChecked() else view.entries
        catalog_ids: set[str] = set()
        for entry in entries:
            if isinstance(wanted, str) and wanted and wanted not in entry.channels:
                continue
            catalog_ids.add(entry.id)
            row = self._table.rowCount()
            self._table.insertRow(row)
            name = QTableWidgetItem(entry.name)
            name.setData(Qt.ItemDataRole.UserRole, entry.id)
            name.setData(
                Qt.ItemDataRole.UserRole + 1,
                tuple(item.id for item in self._store_entries if item.model_id == entry.id),
            )
            name.setToolTip(entry.model.description or entry.id)
            self._table.setItem(row, 0, name)
            self._table.setItem(
                row, 1, _PlainSortTableWidgetItem(_family_label(entry.model.family))
            )
            self._table.setItem(row, 2, QTableWidgetItem(_bytes(entry.model.est_file_bytes)))
            context = entry.model.context_window
            self._table.setItem(row, 3, QTableWidgetItem(f"{context:,}" if context else "—"))
            fit = QTableWidgetItem(_FIT_LABELS.get(entry.fit.level, entry.fit.level))
            fit.setToolTip("\n".join(entry.fit.reasons) or entry.fit.level)
            self._table.setItem(row, 4, fit)
            self._set_engine_marks(row, 5, entry.channels)
            self._set_engine_marks(row, 6, self._installed_for(entry.id, entry))
            self._table.setItem(row, 7, QTableWidgetItem(entry.model.license))

        external_rows: dict[tuple[str, str], DiscoveredModel | StoreEntry] = {}
        for item in self._store_entries:
            if item.model_id not in catalog_ids:
                provider_id = (
                    "llama-cpp" if item.engine in ("llama.cpp", "llama-cpp") else item.engine
                )
                external_rows[(item.model_id, provider_id)] = item
        for instance_id, models in self._provider_models.items():
            provider_id = self._provider_engines.get(instance_id, instance_id)
            for model in models:
                if self._catalog_entry_for_provider_model(provider_id, model.id) is None:
                    external_rows[(model.id, provider_id)] = model

        for (model_id, provider_id), source in sorted(external_rows.items()):
            if isinstance(wanted, str) and wanted and wanted != provider_id:
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            name = QTableWidgetItem(model_id)
            name.setData(Qt.ItemDataRole.UserRole, model_id)
            store_ids = tuple(
                item.id
                for item in self._store_entries
                if item.model_id == model_id
                and ("llama-cpp" if item.engine in ("llama.cpp", "llama-cpp") else item.engine)
                == provider_id
            )
            name.setData(Qt.ItemDataRole.UserRole + 1, store_ids)
            name.setToolTip("Installed model not present in AnyInfer's shipped catalog.")
            self._table.setItem(row, 0, name)
            self._table.setItem(row, 1, _PlainSortTableWidgetItem(_family_label(model_id)))
            local = (
                source.capabilities.local
                if isinstance(source, DiscoveredModel) and source.capabilities is not None
                else None
            )
            size = (
                local.artifact_size_bytes
                if local is not None
                else source.total_bytes
                if isinstance(source, StoreEntry)
                else None
            )
            self._table.setItem(row, 2, QTableWidgetItem(_bytes(size)))
            discovered_context = (
                source.capabilities.context_window
                if isinstance(source, DiscoveredModel) and source.capabilities is not None
                else None
            )
            context_value = discovered_context.value if discovered_context is not None else None
            self._table.setItem(
                row, 3, QTableWidgetItem(f"{context_value:,}" if context_value else "—")
            )
            self._table.setItem(row, 4, QTableWidgetItem("Installed · fit not cataloged"))
            self._set_engine_marks(row, 5, (provider_id,))
            self._set_engine_marks(row, 6, (provider_id,))
            license_text = (
                source.license if isinstance(source, StoreEntry) else "Managed by engine"
            )
            self._table.setItem(row, 7, QTableWidgetItem(license_text or "—"))
        self._table.setSortingEnabled(sorting_enabled)
        if sorting_enabled:
            self._table.sortItems(sort_column, sort_order)
        self._on_selection_changed()

    def _catalog_entry_for_provider_model(self, provider_id: str, model_id: str) -> Any:
        """Match a discovered engine model to a shipped catalog row when possible."""
        if self._view is None:
            return None
        for entry in self._view.entries:
            if entry.id == model_id:
                return entry
            channel = getattr(entry.model, provider_id.replace("-", "_"), None)
            if getattr(channel, "tag", None) == model_id:
                return entry
        return None

    def _installed_for(self, model_id: str, entry: Any) -> tuple[str, ...]:
        """Return engine ids that currently report or own this catalog model."""
        engines = [item.engine for item in self._store_entries if item.model_id == model_id]
        for instance_id, models in self._provider_models.items():
            provider_id = self._provider_engines.get(instance_id, instance_id)
            channel = getattr(entry.model, provider_id.replace("-", "_"), None)
            references = {model_id, getattr(channel, "tag", None)}
            if any(model.id in references for model in models):
                engines.append(provider_id)
        return tuple(dict.fromkeys(engines))

    def _set_engine_marks(self, row: int, column: int, engines: Sequence[str]) -> None:
        """Render branded local-engine marks while preserving hover and accessibility names."""
        self._table.setItem(row, column, QTableWidgetItem(", ".join(engines) or "—"))
        holder = QWidget()
        marks = QHBoxLayout(holder)
        marks.setContentsMargins(4, 0, 4, 0)
        marks.setSpacing(5)
        for engine in engines:
            normalized = "llama-cpp" if engine in ("llama.cpp", "llama-cpp") else engine
            icon = brand_icon(normalized)
            label = QLabel()
            if icon.isNull():
                label.setText(engine)
            else:
                label.setPixmap(icon.pixmap(42, 22))
                if normalized == "ollama":
                    label.setStyleSheet("background: white; border-radius: 3px; padding: 2px;")
            display = "llama.cpp" if normalized == "llama-cpp" else engine
            label.setToolTip(display)
            label.setAccessibleName(display)
            marks.addWidget(label)
        if not engines:
            marks.addWidget(QLabel("—"))
        marks.addStretch(1)
        self._table.setCellWidget(row, column, holder)

    def _on_selection_changed(self) -> None:
        model_id = self.selected_model()
        entry = self._entry(model_id)
        choice = self._selected_add_choice()
        can_execute = choice is not None and (bool(choice.instance_id) or self._llama_cpp_ready)
        pulling = choice is not None and choice.operation == "pull"
        self._plan.setEnabled(can_execute and not pulling)
        self._download.setEnabled(can_execute)
        self._download.setText("Pull" if pulling else "Download")
        self._remove.setEnabled(bool(self._selected_store_entry_ids()))
        # The reasons are the library's own words for its verdict, and they carry the
        # numbers ("needs 6.4 GiB of VRAM; 12.7 GiB is budgeted") that make it checkable.
        self._why.setText(" ".join(entry.fit.reasons) if entry is not None else "")

    def _entry(self, model_id: str) -> Any:
        if self._view is None or not model_id:
            return None
        return next((e for e in self._view.entries if e.id == model_id), None)

    def _selected_add_choice(self) -> AddModelChoice | None:
        """Resolve the selected provider channel to its declared model operation."""
        entry = self._entry(self.selected_model())
        if entry is None:
            return None
        provider_id = self.selected_engine()
        if provider_id is None:
            if not entry.model.variants:
                return None
            return AddModelChoice("acquire", "", "", entry.id, entry.id)
        provider = next(
            (
                candidate
                for candidate in self._config.enabled_providers()
                if candidate.provider_id == provider_id
            ),
            None,
        )
        if provider is None:
            return None
        return catalog_model_choice(entry, provider, self._engine.registry)

    def _on_plan(self) -> None:
        choice = self._selected_add_choice()
        if choice is not None and choice.operation == "acquire":
            self.action_requested.emit(choice, True)

    def _on_download(self) -> None:
        choice = self._selected_add_choice()
        if choice is not None:
            self.action_requested.emit(choice, False)

    def _selected_store_entry_ids(self) -> tuple[str, ...]:
        items = self._table.selectedItems()
        if not items:
            return ()
        item = self._table.item(items[0].row(), 0)
        value = item.data(Qt.ItemDataRole.UserRole + 1) if item is not None else None
        if not isinstance(value, tuple):
            return ()
        return tuple(item for item in value if isinstance(item, str))

    def _on_remove(self) -> None:
        entry_ids = self._selected_store_entry_ids()
        if not entry_ids:
            return
        entry_id = entry_ids[0]
        confirmed = QMessageBox.question(
            self,
            "Remove model",
            f"Delete the weights for {entry_id}?\n\nThey can be downloaded again later.",
        )
        if confirmed == QMessageBox.StandardButton.Yes:
            self._engine.remove_model(_REMOVE_KEY, entry_id)


def _default_runtime_kind(hardware: HardwareProfile | None) -> str:
    """Return the SDK's default backend spelling without duplicating its policy."""
    from anyinfer.local.runtimes import default_runtime_kind

    return default_runtime_kind(hardware)


def _runtime_backend_usable(kind: str, hardware: HardwareProfile | None) -> tuple[bool, str]:
    """Explain whether detected hardware can drive one llama.cpp runtime family."""
    if kind == "cpu":
        return True, "CPU runtimes work on every supported machine."
    if hardware is None:
        return False, "Hardware was not detected, so this accelerator cannot be confirmed."

    detected = {accelerator.kind for accelerator in hardware.accelerators}
    if kind == "cuda":
        usable = "cuda" in detected
        return usable, (
            "An NVIDIA CUDA device was detected."
            if usable
            else "No NVIDIA CUDA device was detected."
        )
    if kind == "metal":
        apple_silicon = (
            hardware.os_name.lower() in ("darwin", "macos")
            and hardware.arch.lower() in ("arm64", "aarch64")
            and "metal" in detected
        )
        return apple_silicon, (
            "Apple Silicon with Metal was detected."
            if apple_silicon
            else "Metal runtimes require detected Apple Silicon."
        )
    if kind == "rocm":
        usable = "rocm" in detected
        return usable, (
            "A ROCm-capable device was detected."
            if usable
            else "No ROCm-capable device was detected."
        )
    if kind == "vulkan":
        usable = hardware.has_accelerator
        return usable, (
            "A hardware accelerator was detected; Vulkan is the vendor-neutral fallback."
            if usable
            else "No GPU or other hardware accelerator was detected for Vulkan."
        )
    return False, f"{kind} is not a recognized llama.cpp runtime backend."


class _RuntimePanel(QWidget):
    """The llama.cpp builds present, and the accelerator backends they can drive.

    Runtimes are fetched rather than bundled — a wheel carrying every accelerator build of
    llama.cpp would be enormous and mostly wrong for any given machine, so "which build
    do I have" is a real question with a real answer, and this is where it is asked.
    """

    quick_llama_setup_requested = Signal()
    runtime_selected = Signal(str)

    def __init__(self, engine: Engine, config: DemoConfig) -> None:
        super().__init__()
        self._engine = engine
        self._config = config
        self._report: _RuntimeReport | None = None
        self._ignore_hardware_constraints = False
        self._llama_cpp_ready = False

        outer = QVBoxLayout(self)
        self._setup_prompt = _LlamaSetupPrompt("installing or inspecting its runtimes")
        self._setup_prompt.setup_requested.connect(self.quick_llama_setup_requested)
        outer.addWidget(self._setup_prompt)

        self._content = QWidget()
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(
            "llama.cpp runtimes are downloaded on demand for the accelerator this machine "
            "actually has. Nothing is bundled into the package. vLLM and Ollama manage "
            "their own runtime environments, so they do not appear here."
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Selected", "Backend", "Build", "Architecture", "Path"]
        )
        self._table.setAccessibleName("Installed runtimes")
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        self._backends = QLabel()
        self._backends.setWordWrap(True)
        self._backends.setObjectName("HintText")
        layout.addWidget(self._backends)

        selection = QHBoxLayout()
        selection.addWidget(QLabel("Runtime:"))
        self._runtime_choice = QComboBox()
        for kind in ("cuda", "vulkan", "metal", "rocm", "cpu"):
            self._runtime_choice.addItem(kind.upper(), kind)
        self._runtime_choice.setAccessibleName("llama.cpp runtime to install")
        self._runtime_choice.currentIndexChanged.connect(self._update_install_button)
        selection.addWidget(self._runtime_choice)
        self._install = QPushButton("Install Runtime")
        self._install.setToolTip(
            "Fetch the pinned llama.cpp build for this backend into the per-user runtime "
            "directory, then make it the default for llama.cpp."
        )
        self._install.clicked.connect(self._on_install)
        selection.addWidget(self._install)
        selection.addStretch(1)
        selection.addWidget(SdkHelpButton("runtimes"))
        layout.addLayout(selection)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setAccessibleName("Runtime installation progress")
        layout.addWidget(self._progress)
        outer.addWidget(self._content, 1)

        self.set_providers(config)

    def refresh(self) -> None:
        """Re-read installed runtimes and the backends this machine can drive."""
        self._engine.run_task(_RUNTIMES_KEY, _read_runtimes)

    def on_runtimes(self, report: _RuntimeReport) -> None:
        """Adopt a freshly read runtime inventory."""
        self._report = report
        self._configure_backend_choices()
        self._select_configured_or_recommended_runtime()
        self._render_runtime_table()

    def _render_runtime_table(self) -> None:
        """Render the installed variants and mark the backend llama.cpp will select."""
        report = self._report
        self._table.setRowCount(0)
        if report is None:
            return
        selected_kind = self._selected_runtime_kind()
        for manifest in report.installed:
            row = self._table.rowCount()
            self._table.insertRow(row)
            selected = QTableWidgetItem("✓" if manifest.backend == selected_kind else "")
            selected.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            selected.setToolTip(
                "Selected for llama.cpp"
                if manifest.backend == selected_kind
                else "Installed but not selected"
            )
            self._table.setItem(row, 0, selected)
            self._table.setItem(row, 1, QTableWidgetItem(manifest.backend))
            self._table.setItem(row, 2, QTableWidgetItem(manifest.build))
            self._table.setItem(row, 3, QTableWidgetItem(manifest.architecture))
            self._table.setItem(row, 4, QTableWidgetItem(str(manifest.executable)))
        available = ", ".join(f"{b.kind}" for b in report.backends) or "none detected"
        self._table.setToolTip("")
        self._backends.setText(
            f"Usable installed backends on this machine: {available}."
            if report.installed
            else f"No runtime installed yet. Usable installed backends: {available}."
        )

    def set_providers(self, config: DemoConfig) -> None:
        """Apply the llama.cpp prerequisite and runtime hardware preference."""
        self._config = config
        self._llama_cpp_ready = _llama_cpp_enabled(config)
        self._ignore_hardware_constraints = config.ignore_runtime_hardware_constraints
        self._setup_prompt.set_ready(self._llama_cpp_ready)
        self._content.setVisible(self._llama_cpp_ready)
        self._configure_backend_choices()
        self._select_configured_or_recommended_runtime()
        self._render_runtime_table()

    def _configured_runtime(self) -> str:
        """Return the first enabled llama.cpp instance's configured backend."""
        for provider in self._config.instances_of("llama-cpp"):
            if provider.enabled:
                return str(provider.options.get("runtime", "auto"))
        return "auto"

    def _selected_runtime_kind(self) -> str | None:
        """Resolve ``auto`` to the installed backend that this machine would use."""
        configured = self._configured_runtime()
        if configured != "auto":
            return configured
        if self._report is None:
            return None
        selected = next(
            (
                backend.kind
                for backend in self._report.backends
                if _runtime_backend_usable(backend.kind, self._report.hardware)[0]
            ),
            None,
        )
        if selected is not None:
            return str(selected)
        fallback = next(
            (
                manifest.backend
                for manifest in self._report.installed
                if _runtime_backend_usable(manifest.backend, self._report.hardware)[0]
            ),
            None,
        )
        return str(fallback) if fallback is not None else None

    def _select_configured_or_recommended_runtime(self) -> None:
        """Prefer an explicit setting, otherwise show the SDK's machine recommendation."""
        if self._report is None:
            return
        configured = self._configured_runtime()
        wanted = (
            configured if configured != "auto" else _default_runtime_kind(self._report.hardware)
        )
        index = self._runtime_choice.findData(wanted)
        model = self._runtime_choice.model()
        if isinstance(model, QStandardItemModel) and index >= 0 and model.item(index).isEnabled():
            self._runtime_choice.setCurrentIndex(index)

    def _configure_backend_choices(self) -> None:
        """Enable only published variants the detected machine can plausibly drive."""
        report = self._report
        model = self._runtime_choice.model()
        if not isinstance(model, QStandardItemModel):
            return

        if report is None:
            for index in range(self._runtime_choice.count()):
                model.item(index).setEnabled(False)
            self._install.setEnabled(False)
            return

        default_kind = _default_runtime_kind(report.hardware)
        published = set(report.installable)
        for index in range(self._runtime_choice.count()):
            value = self._runtime_choice.itemData(index)
            kind = str(value)
            available = kind in published
            usable, reason = _runtime_backend_usable(kind, report.hardware)
            enabled = available and (usable or self._ignore_hardware_constraints)
            item = model.item(index)
            item.setEnabled(enabled)
            if not available:
                tooltip = f"No pinned {kind} build is published for this platform."
            elif usable:
                tooltip = reason
            elif self._ignore_hardware_constraints:
                tooltip = f"Hardware constraint ignored: {reason}"
            else:
                tooltip = reason
            label = kind.upper()
            if kind == default_kind:
                label += " — recommended for this machine"
            self._runtime_choice.setItemText(index, label)
            self._runtime_choice.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)

        current = model.item(self._runtime_choice.currentIndex())
        if current is None or not current.isEnabled():
            first = next(
                (
                    index
                    for index in range(self._runtime_choice.count())
                    if model.item(index).isEnabled()
                ),
                -1,
            )
            self._runtime_choice.setCurrentIndex(first)
        self._update_install_button()

    def _update_install_button(self, *_args: object) -> None:
        model = self._runtime_choice.model()
        index = self._runtime_choice.currentIndex()
        choice_enabled = (
            isinstance(model, QStandardItemModel) and index >= 0 and model.item(index).isEnabled()
        )
        self._install.setEnabled(
            self._llama_cpp_ready and choice_enabled and not self._progress.isVisible()
        )

    def _on_install(self) -> None:
        kind = self._runtime_choice.currentData()
        wanted = kind if isinstance(kind, str) and kind else None
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setFormat("Preparing runtime download…")
        self._update_install_button()
        self._engine.install_runtime(
            _INSTALL_RUNTIME_KEY,
            wanted,
            force=self._ignore_hardware_constraints,
        )

    def on_install_progress(self, progress: object) -> None:
        """Render archive download progress emitted by the runtime installer."""
        if not isinstance(progress, RuntimeInstallProgress):
            return
        self._progress.setVisible(True)
        if progress.total_bytes:
            self._progress.setRange(0, 1000)
            fraction = min(1.0, progress.downloaded_bytes / progress.total_bytes)
            self._progress.setValue(round(fraction * 1000))
            self._progress.setFormat(
                f"{progress.artifact_id}: {_bytes(progress.downloaded_bytes)} of "
                f"{_bytes(progress.total_bytes)}"
            )
        else:
            self._progress.setRange(0, 0)
            self._progress.setFormat(
                f"{progress.artifact_id}: {_bytes(progress.downloaded_bytes)}"
            )

    def on_install_finished(self, report: InstallReport) -> None:
        """Restore controls and select the successfully installed backend."""
        self._progress.setVisible(False)
        self._update_install_button()
        self.runtime_selected.emit(report.backend)

    def on_install_failed(self) -> None:
        """Restore controls after a runtime install fails."""
        self._progress.setVisible(False)
        self._update_install_button()


class _RuntimeReport:
    """What one runtime inventory read found.

    A tiny value rather than a tuple, so the two lists cannot be swapped at the call site
    and so the worker returns one object through the engine's single ``task_done`` channel.
    """

    __slots__ = ("backends", "hardware", "installable", "installed")

    def __init__(
        self,
        installed: Sequence[Any],
        backends: Sequence[Any],
        hardware: HardwareProfile,
        installable: Sequence[str],
    ) -> None:
        self.installed = installed
        self.backends = backends
        self.hardware = hardware
        self.installable = tuple(installable)


def _read_runtimes() -> _RuntimeReport:
    """Read the runtime inventory. Runs on a worker thread — it touches the filesystem."""
    from anyinfer.local.backends import available_backends
    from anyinfer.local.hardware import detect
    from anyinfer.local.runtimes import installed_runtimes, load_runtime_table

    hardware = detect()
    installable = tuple(artifact.backend for artifact in load_runtime_table().for_platform())
    return _RuntimeReport(
        installed_runtimes(),
        available_backends(hardware=hardware),
        hardware,
        installable,
    )


def _scrollable(widget: QWidget) -> QScrollArea:
    """Wrap a content-sized tab so small screens scroll instead of clipping groups."""
    scroll = QScrollArea()
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(widget)
    return scroll


class ModelsDialog(QDialog):
    """Local inference: system profile, unified model catalog, and runtimes."""

    quick_llama_setup_requested = Signal()
    """Ask the owning application to add an enabled default llama.cpp provider."""
    runtime_selection_requested = Signal(str)
    """Ask the owning application to persist the default llama.cpp runtime."""

    def __init__(
        self,
        engine: Engine,
        config: DemoConfig,
        parent: QWidget | None = None,
        *,
        initial_target: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Local Inference")
        self.setMinimumSize(960, 720)
        self._engine = engine
        self._local_provider_instances: dict[str, str] = {}

        outer = QVBoxLayout(self)

        self._tabs = BorderedTabWidget()
        self._system = _SystemPanel(engine)
        self._benchmark = _BenchmarkPanel(engine, config, initial_target)
        self._system.benchmark_requested.connect(self._start_system_benchmark)
        self._catalog = _CatalogPanel(engine, config)
        self._catalog.quick_llama_setup_requested.connect(self.quick_llama_setup_requested)
        self._catalog.add_requested.connect(self._on_add_model)
        self._catalog.action_requested.connect(self._dispatch_model_choice)
        self._runtimes = _RuntimePanel(engine, config)
        self._runtimes.quick_llama_setup_requested.connect(self.quick_llama_setup_requested)
        self._runtimes.runtime_selected.connect(self.runtime_selection_requested)
        self._tabs.addTab(_scrollable(self._system), "System")
        self._tabs.addTab(_scrollable(self._benchmark), "Benchmark")
        self._tabs.addTab(self._catalog, "Catalog")
        self._tabs.addTab(self._runtimes, "Runtimes")
        outer.addWidget(self._tabs, 1)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setAccessibleName("Download progress")
        outer.addWidget(self._progress)

        self._status = QLabel("Ready.")
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._buttons.rejected.connect(self.reject)
        self._buttons.accepted.connect(self.accept)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        footer.addWidget(self._status, 1, Qt.AlignmentFlag.AlignVCenter)
        footer.addWidget(self._buttons, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(footer)

        engine.task_done.connect(self._on_task_done)
        engine.task_failed.connect(self._on_task_failed)
        engine.acquisition_progress.connect(self._on_progress)
        engine.runtime_install_progress.connect(self._runtimes.on_install_progress)
        engine.benchmark_progress.connect(self._on_benchmark_progress)
        engine.models_listed.connect(self._on_provider_models_listed)

        self._sync_local_provider_models(config)
        self._catalog.refresh()
        self._engine.installed_models(_INSTALLED_KEY)
        self._runtimes.refresh()

    def _on_add_model(self) -> None:
        """Open one engine-aware search surface and dispatch the selected operation."""
        view = self._catalog._view
        if view is None:
            self._status.setText("The catalog is still loading; try Add again in a moment.")
            return
        dialog = AddModelDialog(
            view,
            self._engine.config,
            self._engine.registry,
            self,
            benchmark_context=self._benchmark.benchmark_context(),
        )
        dialog.focus_search()
        if dialog.exec() != AddModelDialog.DialogCode.Accepted:
            return
        choice = dialog.choice()
        if choice is None:
            return
        self._dispatch_model_choice(choice)

    def _dispatch_model_choice(self, choice: object, dry_run: bool = False) -> None:
        """Send a resolved catalog action through the matching SDK operation."""
        if not isinstance(choice, AddModelChoice):
            return
        if choice.operation == "pull":
            self._engine.pull_model(_PULL_KEY, choice.instance_id, choice.model_ref)
            self._status.setText(f"Asking {choice.instance_id} to pull {choice.model_ref}…")
            return
        key = _PLAN_KEY if dry_run else _ACQUIRE_KEY
        self._engine.acquire_model(
            key,
            choice.model_id,
            engine=choice.acquisition_engine,
            dry_run=dry_run,
        )
        if dry_run:
            self._status.setText(f"Planning the download for {choice.model_id}…")
        else:
            self._status.setText(
                f"Downloading {choice.model_id} for {choice.acquisition_engine or 'the best fit'} "
                "from its verified catalog source…"
            )

    # ---- engine callbacks --------------------------------------------------------------

    def _on_task_done(self, key: str, result: object) -> None:
        """Route one completed background call to the panel that asked for it."""
        if key == _CATALOG_KEY and isinstance(result, CatalogView):
            self._system.on_catalog(result)
            self._catalog.on_catalog(result)
            self._status.setText(f"Catalog: {len(result.entries)} entries.")
        elif key == _INSTALLED_KEY and isinstance(result, Sequence):
            installed = tuple(entry for entry in result if isinstance(entry, StoreEntry))
            self._catalog.on_installed(installed)
            self._benchmark.on_installed(installed)
            self._status.setText(f"{len(result)} model(s) in the store.")
        elif key == _RUNTIMES_KEY and isinstance(result, _RuntimeReport):
            self._runtimes.on_runtimes(result)
        elif key in (_ACQUIRE_KEY, _PLAN_KEY) and isinstance(result, AcquisitionReport):
            self._on_acquired(result)
        elif key == _REMOVE_KEY and isinstance(result, RemovalReport):
            self._status.setText(
                f"Removed {result.entry_id} — {_bytes(result.freed_bytes)} freed."
                if result.removed
                else f"{result.entry_id} was not removed."
            )
            self._engine.installed_models(_INSTALLED_KEY)
            self._refresh_local_provider_models()
        elif key == _INSTALL_RUNTIME_KEY and isinstance(result, InstallReport):
            self._runtimes.on_install_finished(result)
            verb = "Already installed" if result.reused else "Installed"
            self._status.setText(
                f"{verb}: {result.backend} runtime {result.build} "
                f"({_bytes(result.downloaded_bytes)} fetched) → {result.executable}"
            )
            self._runtimes.refresh()
        elif key == _PULL_KEY:
            # PullReport's shape is the engine's to define, so it is reported as the
            # library spells it rather than reformatted into fields this file assumes.
            self._status.setText(f"Pull finished: {result}")
            self._refresh_local_provider_models()
        elif (
            key == _BENCHMARK_KEY
            and isinstance(result, tuple)
            and len(result) == 2
            and all(isinstance(measurement, Measurement) for measurement in result)
        ):
            first, second = result
            self._benchmark.on_benchmark(first, second)
            self._system.on_benchmark(second)
            self._status.setText(f"Benchmark complete: {second.summary}")

    def _on_acquired(self, report: AcquisitionReport) -> None:
        """Report an acquisition, which for a dry run is a plan rather than a download."""
        self._progress.setVisible(False)
        plan = report.plan
        if report.dry_run:
            already = f", {_bytes(plan.already_have_bytes)} already on disk"
            self._status.setText(
                f"{plan.model_id} ({plan.variant_id}): {len(plan.files)} file(s), "
                f"{_bytes(plan.total_bytes)} total{already}. "
                + ("Nothing to do — already satisfied." if plan.satisfied else "")
            )
            return
        if report.cancelled:
            self._status.setText(f"{plan.model_id}: cancelled.")
            return
        verb = "Already present" if report.reused else "Downloaded"
        warnings = f" ⚠ {'; '.join(report.warnings)}" if report.warnings else ""
        self._status.setText(
            f"{verb}: {plan.model_id} ({plan.variant_id}), "
            f"{_bytes(report.downloaded_bytes)} fetched.{warnings}"
        )
        self._engine.installed_models(_INSTALLED_KEY)
        # llama.cpp discovery is intentionally the installed inventory. Refreshing it
        # here updates both this dialog and the main model picker immediately after the
        # store changes, without making either UI reconstruct catalog semantics.
        self._refresh_local_provider_models()

    def _on_progress(self, progress: object) -> None:
        """Drive the progress bar from the library's own acquisition snapshots."""
        if not isinstance(progress, AcquisitionProgress):
            return
        total = progress.total_bytes
        self._progress.setVisible(True)
        if total:
            self._progress.setRange(0, 1000)
            self._progress.setValue(min(1000, int(1000 * progress.total_downloaded_bytes / total)))
        else:
            # An unknown total is a real state, not a zero: a busy indicator is honest
            # where a 0% bar would imply a measurement nobody made.
            self._progress.setRange(0, 0)
        speed = progress.bytes_per_second
        rate = f" · {_bytes(int(speed))}/s" if speed else ""
        estimate = " (estimated)" if progress.total_is_estimate else ""
        self._status.setText(
            f"{progress.phase}: {progress.filename} "
            f"[{progress.file_index + 1}/{progress.file_count}] "
            f"{_bytes(progress.total_downloaded_bytes)} of {_bytes(total)}{estimate}{rate}"
        )

    def _on_task_failed(self, key: str, message: str, error: object) -> None:
        """Surface a failed background call with the library's own hint."""
        if not key.startswith("models."):
            return
        self._progress.setVisible(False)
        hint = getattr(error, "hint", "")
        detail = f"{message}\nHint: {hint}" if hint else message
        if key == _BENCHMARK_KEY:
            self._benchmark.on_benchmark_failed(detail)
        elif key == _INSTALL_RUNTIME_KEY:
            self._runtimes.on_install_failed()
        self._status.setText(detail)

    def set_providers(self, config: DemoConfig) -> None:
        """Adopt new provider configuration across provider-dependent panels."""
        self._benchmark.set_providers(config)
        self._catalog.set_providers(config)
        self._runtimes.set_providers(config)
        self._sync_local_provider_models(config)

    def _sync_local_provider_models(self, config: DemoConfig) -> None:
        """Refresh inventories for configured engines whose inference is local."""
        instances: dict[str, str] = {}
        for provider in config.enabled_providers():
            if not self._engine.registry.has(provider.provider_id):
                continue
            descriptor = self._engine.registry.get(provider.provider_id)
            if (
                descriptor.id == DEMO_PROVIDER_ID
                or descriptor.locality != "local"
                or descriptor.model_inventory == "available"
            ):
                continue
            instances[provider.instance_id] = provider.provider_id
        self._local_provider_instances = instances
        self._catalog.set_provider_instances(instances)
        self._refresh_local_provider_models()

    def _refresh_local_provider_models(self) -> None:
        for instance_id in self._local_provider_instances:
            self._engine.list_models(instance_id)

    def _on_provider_models_listed(self, instance_id: str, models: object) -> None:
        """Merge one local engine's discovered inventory into Catalog and Benchmark."""
        if instance_id not in self._local_provider_instances or not isinstance(models, Sequence):
            return
        discovered = tuple(model for model in models if isinstance(model, DiscoveredModel))
        self._catalog.on_provider_models(instance_id, discovered)
        self._benchmark.on_provider_models(instance_id, discovered)

    def _on_benchmark_progress(self, key: str, run: int, sample: object) -> None:
        """Route live benchmark telemetry to its dedicated tab."""
        if key == _BENCHMARK_KEY and isinstance(sample, BenchmarkSample):
            self._benchmark.on_progress(run, sample)

    def _start_system_benchmark(self) -> None:
        """Move from the System callout to Benchmark and start when a model is ready."""
        self._tabs.setCurrentIndex(1)
        self._benchmark.start()

    def show_status(self, message: str) -> None:
        """Surface a host-level setup result in the dialog's existing status line."""
        self._status.setText(message)
