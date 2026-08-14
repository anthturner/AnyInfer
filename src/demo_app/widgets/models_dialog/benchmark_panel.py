"""Live cold/warm benchmark charts over installed local targets."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from anyinfer import BenchmarkSample, Measurement
from anyinfer.errors import AnyInferError
from anyinfer.local.server import is_loopback
from anyinfer.local.store import StoreEntry
from anyinfer.types.capabilities import DiscoveredModel

from ...config import DemoConfig
from ...engine import Engine
from ...fake_provider import DEMO_PROVIDER_ID
from ..sdk_help import SdkHelpButton
from ._shared import _BENCHMARK_KEY


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
