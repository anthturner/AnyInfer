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

This package splits what was once one file into one module per panel — `system_panel.py`,
`benchmark_panel.py`, `catalog_panel.py`, `runtime_panel.py` — plus `_shared.py` for the
handful of helpers more than one panel needs. This module keeps only `ModelsDialog`, the
composition class that wires the four panels to one `Engine` and one status line.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from anyinfer import BenchmarkSample, CatalogView, Measurement
from anyinfer.local.acquire import AcquisitionProgress, AcquisitionReport
from anyinfer.local.runtimes import InstallReport
from anyinfer.local.store import RemovalReport, StoreEntry
from anyinfer.types.capabilities import DiscoveredModel

from ...config import DemoConfig
from ...engine import Engine
from ...fake_provider import DEMO_PROVIDER_ID
from ..add_model_dialog import AddModelChoice, AddModelDialog
from ..formatting import _bytes
from ..tab_widget import BorderedTabWidget
from ._shared import (
    _ACQUIRE_KEY,
    _BENCHMARK_KEY,
    _CATALOG_KEY,
    _INSTALL_RUNTIME_KEY,
    _INSTALLED_KEY,
    _PLAN_KEY,
    _PULL_KEY,
    _REMOVE_KEY,
    _RUNTIMES_KEY,
)
from .benchmark_panel import _BenchmarkPanel
from .catalog_panel import _CatalogPanel
from .runtime_panel import _RuntimePanel, _RuntimeReport
from .system_panel import _contrasting_text_color, _SystemPanel

__all__ = [
    "_CATALOG_KEY",
    "ModelsDialog",
    "_BenchmarkPanel",
    "_CatalogPanel",
    "_RuntimePanel",
    "_RuntimeReport",
    "_SystemPanel",
    "_bytes",
    "_contrasting_text_color",
    "_scrollable",
]


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
