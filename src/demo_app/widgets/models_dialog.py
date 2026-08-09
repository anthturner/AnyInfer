"""Local model management: the catalog, the store, and the runtimes behind them.

The chat window shows what a *configured* engine can already do. This dialog shows the
step before that, which for a local engine is most of the work: choosing weights that fit
the machine, fetching them, and having a llama.cpp build to run them with.

Everything here is one library call per button. `Client.local_catalog()`
already annotates every entry with how it fits *this* computer, `acquire_model()`
already plans, downloads, verifies, and indexes, and `install_runtime()` already
picks the right build for the detected accelerator. None of that is re-implemented here —
the panels below are tables over those return values, which is the point: an application
integrating AnyInfer does not write a downloader.

Three surfaces, because they answer three different questions:

===========  ==========================================================================
Panel        Question it answers
===========  ==========================================================================
Catalog      What could I run here, and would it fit?
Installed    What have I already fetched, and what is it costing me on disk?
Runtimes     What can actually execute it, and is the right accelerator build present?
===========  ==========================================================================

The fourth surface, **Engine pull**, is deliberately separate from the first three. Ollama
and its kin keep their own model store, so "make this available" is a request to *them*
rather than a download AnyInfer performs — the weights land under the engine's name, in the
engine's directory, and AnyInfer's store neither indexes them nor can remove them. Presenting
that as another row in the Installed table would be a lie about who owns the file.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from anyinfer import CatalogView
from anyinfer.local.acquire import AcquisitionProgress, AcquisitionReport
from anyinfer.local.hardware import HardwareProfile
from anyinfer.local.runtimes import InstallReport
from anyinfer.local.store import RemovalReport, StoreEntry
from anyinfer.local.tuning import Posture

from ..config import DemoConfig
from ..engine import Engine
from .sdk_help import SdkHelpButton

__all__ = ["ModelsDialog"]

_CATALOG_KEY = "models.catalog"
_INSTALLED_KEY = "models.installed"
_ACQUIRE_KEY = "models.acquire"
_PLAN_KEY = "models.plan"
_REMOVE_KEY = "models.remove"
_PULL_KEY = "models.pull"
_RUNTIMES_KEY = "models.runtimes"
_INSTALL_RUNTIME_KEY = "models.install-runtime"
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


def _hardware_summary(hardware: HardwareProfile | None, source: str) -> str:
    """One line describing the machine every fit verdict below was computed against.

    Shown because the verdicts are otherwise unfalsifiable. "Will not fit" is a claim about
    a specific amount of memory, and a user who disagrees with it deserves to see which
    machine AnyInfer thinks it is looking at.
    """
    if hardware is None:
        return "<i>Hardware not detected — fit estimates are unavailable.</i>"
    parts = [f"{hardware.os_name}/{hardware.arch}"]
    if hardware.cpu_name:
        parts.append(hardware.cpu_name)
    if hardware.total_ram_bytes:
        parts.append(f"{_bytes(hardware.total_ram_bytes)} RAM")
    for accelerator in hardware.accelerators:
        name = accelerator.name or accelerator.kind
        vram = _bytes(accelerator.total_vram_bytes) if accelerator.total_vram_bytes else "?"
        parts.append(f"{name} ({vram} VRAM)")
    return f"<b>This machine</b> ({source}): " + " · ".join(parts)


class _CatalogPanel(QWidget):
    """The catalog, annotated with how each entry fits this machine.

    Sorted by the library, filtered here. The filter is the only logic in this panel:
    deciding *whether* something fits is `ModelFit`'s job, and re-deriving it
    from sizes would be the demo quietly growing a second opinion.
    """

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._view: CatalogView | None = None

        layout = QVBoxLayout(self)

        self._hardware = QLabel("<i>Loading…</i>")
        self._hardware.setTextFormat(Qt.TextFormat.RichText)
        self._hardware.setWordWrap(True)
        layout.addWidget(self._hardware)

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

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Model", "Size", "Context", "Fit", "Engines", "License"]
        )
        self._table.setAccessibleName("Model catalog")
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, 1)

        self._why = QLabel()
        self._why.setWordWrap(True)
        self._why.setObjectName("HintText")
        layout.addWidget(self._why)

        buttons = QHBoxLayout()
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
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def refresh(self) -> None:
        """Re-read the catalog at the selected posture."""
        self._hardware.setText("<i>Reading the catalog…</i>")
        chosen = self._posture.currentText()
        posture: Posture = chosen if chosen in _POSTURES else "balanced"
        self._engine.local_catalog(_CATALOG_KEY, None, posture=posture)

    def on_catalog(self, view: CatalogView) -> None:
        """Adopt a freshly read catalog."""
        self._view = view
        self._hardware.setText(_hardware_summary(view.hardware, view.hardware_source))
        self._notes.setText("<br>".join(f"• {note}" for note in view.notes) if view.notes else "")
        self._notes.setVisible(bool(view.notes))

        chosen = self._engine_filter.currentData()
        channels = sorted({channel for entry in view.entries for channel in entry.channels})
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
        """The engine filter's current value, or ``None`` when unfiltered.

        Passed through to acquisition so a model offered by both llama.cpp and Ollama is
        fetched for the one the user was looking at.
        """
        data = self._engine_filter.currentData()
        return data if isinstance(data, str) and data else None

    def _repopulate(self) -> None:
        view = self._view
        self._table.setRowCount(0)
        if view is None:
            return
        wanted = self._engine_filter.currentData()
        entries = view.runnable if self._runnable_only.isChecked() else view.entries
        for entry in entries:
            if isinstance(wanted, str) and wanted and wanted not in entry.channels:
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            name = QTableWidgetItem(entry.name)
            name.setData(Qt.ItemDataRole.UserRole, entry.id)
            name.setToolTip(entry.model.description or entry.id)
            self._table.setItem(row, 0, name)
            self._table.setItem(row, 1, QTableWidgetItem(_bytes(entry.model.est_file_bytes)))
            context = entry.model.context_window
            self._table.setItem(row, 2, QTableWidgetItem(f"{context:,}" if context else "—"))
            fit = QTableWidgetItem(_FIT_LABELS.get(entry.fit.level, entry.fit.level))
            fit.setToolTip("\n".join(entry.fit.reasons) or entry.fit.level)
            self._table.setItem(row, 3, fit)
            self._table.setItem(row, 4, QTableWidgetItem(", ".join(entry.channels)))
            self._table.setItem(row, 5, QTableWidgetItem(entry.model.license))
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        model_id = self.selected_model()
        self._plan.setEnabled(bool(model_id))
        self._download.setEnabled(bool(model_id))
        entry = self._entry(model_id)
        # The reasons are the library's own words for its verdict, and they carry the
        # numbers ("needs 6.4 GiB of VRAM; 12.7 GiB is budgeted") that make it checkable.
        self._why.setText(" ".join(entry.fit.reasons) if entry is not None else "")

    def _entry(self, model_id: str) -> Any:
        if self._view is None or not model_id:
            return None
        return next((e for e in self._view.entries if e.id == model_id), None)

    def _on_plan(self) -> None:
        model_id = self.selected_model()
        if model_id:
            self._engine.acquire_model(
                _PLAN_KEY, model_id, engine=self.selected_engine(), dry_run=True
            )

    def _on_download(self) -> None:
        model_id = self.selected_model()
        if model_id:
            self._engine.acquire_model(_ACQUIRE_KEY, model_id, engine=self.selected_engine())


class _InstalledPanel(QWidget):
    """What is already on disk, and what removing it would free."""

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine

        layout = QVBoxLayout(self)
        caption = QLabel(
            "Models acquired into AnyInfer's own store. Weights an engine downloaded for "
            "itself are not listed here — they belong to that engine, not to this store."
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Model", "Variant", "Engine", "Quantization", "Size", "License"]
        )
        self._table.setAccessibleName("Installed models")
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, 1)

        self._empty = QLabel("<i>Nothing acquired yet — pick something from the Catalog.</i>")
        self._empty.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._empty)

        buttons = QHBoxLayout()
        self._remove = QPushButton("Remove")
        self._remove.setEnabled(False)
        self._remove.setToolTip("Delete these weights and drop them from the store index.")
        self._remove.clicked.connect(self._on_remove)
        buttons.addWidget(self._remove)
        buttons.addStretch(1)
        buttons.addWidget(SdkHelpButton("acquisition"))
        layout.addLayout(buttons)

    def refresh(self) -> None:
        """Re-read the store index."""
        self._engine.installed_models(_INSTALLED_KEY)

    def on_installed(self, entries: Sequence[StoreEntry]) -> None:
        """Adopt a freshly read store listing."""
        self._table.setRowCount(0)
        for entry in entries:
            row = self._table.rowCount()
            self._table.insertRow(row)
            name = QTableWidgetItem(entry.model_id)
            name.setData(Qt.ItemDataRole.UserRole, entry.id)
            name.setToolTip(entry.directory)
            self._table.setItem(row, 0, name)
            self._table.setItem(row, 1, QTableWidgetItem(entry.variant_id))
            self._table.setItem(row, 2, QTableWidgetItem(entry.engine))
            self._table.setItem(row, 3, QTableWidgetItem(entry.quantization or "—"))
            total = sum(f.size_bytes for f in entry.files) if entry.files else None
            self._table.setItem(row, 4, QTableWidgetItem(_bytes(total)))
            self._table.setItem(row, 5, QTableWidgetItem(entry.license or "—"))
        self._empty.setVisible(not entries)
        self._on_selection_changed()

    def _selected_entry_id(self) -> str:
        items = self._table.selectedItems()
        if not items:
            return ""
        cell = self._table.item(items[0].row(), 0)
        value = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        return value if isinstance(value, str) else ""

    def _on_selection_changed(self) -> None:
        self._remove.setEnabled(bool(self._selected_entry_id()))

    def _on_remove(self) -> None:
        entry_id = self._selected_entry_id()
        if not entry_id:
            return
        confirmed = QMessageBox.question(
            self,
            "Remove model",
            f"Delete the weights for {entry_id}?\n\nThey can be downloaded again later.",
        )
        if confirmed == QMessageBox.StandardButton.Yes:
            self._engine.remove_model(_REMOVE_KEY, entry_id)


class _RuntimePanel(QWidget):
    """The llama.cpp builds present, and the accelerator backends they can drive.

    Runtimes are fetched rather than bundled — a wheel carrying every accelerator build of
    llama.cpp would be enormous and mostly wrong for any given machine — so "which build
    do I have" is a real question with a real answer, and this is where it is asked.
    """

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine

        layout = QVBoxLayout(self)
        caption = QLabel(
            "llama.cpp runtimes are downloaded on demand for the accelerator this machine "
            "actually has. Nothing is bundled into the package."
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Backend", "Build", "Architecture", "Path"])
        self._table.setAccessibleName("Installed runtimes")
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        self._backends = QLabel()
        self._backends.setWordWrap(True)
        self._backends.setObjectName("HintText")
        layout.addWidget(self._backends)

        buttons = QHBoxLayout()
        buttons.addWidget(QLabel("Install:"))
        self._kind = QComboBox()
        self._kind.addItem("Best for this machine", "")
        for kind in ("cuda", "vulkan", "metal", "rocm", "cpu"):
            self._kind.addItem(kind, kind)
        self._kind.setAccessibleName("Runtime backend to install")
        buttons.addWidget(self._kind)

        self._install = QPushButton("Install runtime")
        self._install.setToolTip(
            "Fetch the pinned llama.cpp build for this backend into the per-user runtime "
            "directory."
        )
        self._install.clicked.connect(self._on_install)
        buttons.addWidget(self._install)
        buttons.addStretch(1)
        buttons.addWidget(SdkHelpButton("runtimes"))
        layout.addLayout(buttons)

    def refresh(self) -> None:
        """Re-read installed runtimes and the backends this machine can drive."""
        self._engine.run_task(_RUNTIMES_KEY, _read_runtimes)

    def on_runtimes(self, report: _RuntimeReport) -> None:
        """Adopt a freshly read runtime inventory."""
        self._table.setRowCount(0)
        for manifest in report.installed:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(manifest.backend))
            self._table.setItem(row, 1, QTableWidgetItem(manifest.build))
            self._table.setItem(row, 2, QTableWidgetItem(manifest.architecture))
            self._table.setItem(row, 3, QTableWidgetItem(str(manifest.executable)))
        available = ", ".join(f"{b.kind}" for b in report.backends) or "none detected"
        self._table.setToolTip("")
        self._backends.setText(
            f"Usable backends on this machine: {available}."
            if report.installed
            else f"No runtime installed yet. Usable backends: {available}."
        )

    def _on_install(self) -> None:
        kind = self._kind.currentData()
        wanted = kind if isinstance(kind, str) and kind else None
        self._engine.run_task(_INSTALL_RUNTIME_KEY, lambda: _install_runtime(wanted))


class _PullPanel(QWidget):
    """Ask an engine that owns its own store to make a model available.

    A different operation from acquisition, with a different owner for the result, so it
    gets its own panel rather than a second button on the catalog. Only engines whose
    descriptor declares a model puller are offered — which is the registry answering
    "who can do this", instead of this file keeping a list of engine names.
    """

    def __init__(self, engine: Engine, config: DemoConfig) -> None:
        super().__init__()
        self._engine = engine

        layout = QVBoxLayout(self)
        caption = QLabel(
            "Engines with their own model store — Ollama and its kin — download weights "
            "themselves, under their own name and into their own directory. AnyInfer asks; "
            "it does not fetch, index, or remove them."
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)

        row = QHBoxLayout()
        row.addWidget(QLabel("Engine:"))
        self._instances = QComboBox()
        self._instances.setAccessibleName("Engine to pull with")
        row.addWidget(self._instances)

        row.addWidget(QLabel("Model:"))
        self._model = QLineEdit()
        self._model.setPlaceholderText("qwen3:8b")
        self._model.setAccessibleName("Model to pull")
        self._model.returnPressed.connect(self._on_pull)
        row.addWidget(self._model, 1)

        self._pull = QPushButton("Pull")
        self._pull.clicked.connect(self._on_pull)
        row.addWidget(self._pull)
        row.addWidget(SdkHelpButton("engine-pull"))
        layout.addLayout(row)

        self._empty = QLabel()
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)
        layout.addStretch(1)

        self.set_providers(config)

    def set_providers(self, config: DemoConfig) -> None:
        """Offer the configured instances whose engine can pull."""
        registry = self._engine.registry
        self._instances.clear()
        for provider in config.enabled_providers():
            if not registry.has(provider.provider_id):
                continue
            if registry.get(provider.provider_id).model_puller is None:
                continue
            self._instances.addItem(provider.instance_id, provider.instance_id)
        usable = self._instances.count() > 0
        self._pull.setEnabled(usable)
        self._model.setEnabled(usable)
        self._empty.setText(
            ""
            if usable
            else "<i>No configured engine manages its own model store. Add Ollama under "
            "Provider settings to use this.</i>"
        )
        self._empty.setTextFormat(Qt.TextFormat.RichText)

    def _on_pull(self) -> None:
        instance = self._instances.currentData()
        model = self._model.text().strip()
        if isinstance(instance, str) and instance and model:
            self._engine.pull_model(_PULL_KEY, instance, model)


class _RuntimeReport:
    """What one runtime inventory read found.

    A tiny value rather than a tuple, so the two lists cannot be swapped at the call site
    and so the worker returns one object through the engine's single ``task_done`` channel.
    """

    __slots__ = ("backends", "installed")

    def __init__(self, installed: Sequence[Any], backends: Sequence[Any]) -> None:
        self.installed = installed
        self.backends = backends


def _read_runtimes() -> _RuntimeReport:
    """Read the runtime inventory. Runs on a worker thread — it touches the filesystem."""
    from anyinfer.local.backends import available_backends
    from anyinfer.local.runtimes import installed_runtimes

    return _RuntimeReport(installed_runtimes(), available_backends())


def _install_runtime(kind: str | None) -> Any:
    """Install one llama.cpp runtime build. Runs on a worker thread — it downloads."""
    from anyinfer.local.runtimes import install_runtime

    return install_runtime(kind)  # type: ignore[arg-type]


class ModelsDialog(QDialog):
    """The local-model manager: catalog, store, runtimes, and engine-managed pulls."""

    def __init__(self, engine: Engine, config: DemoConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Local models")
        self.setMinimumSize(880, 620)
        self._engine = engine

        outer = QVBoxLayout(self)

        self._tabs = QTabWidget()
        self._catalog = _CatalogPanel(engine)
        self._installed = _InstalledPanel(engine)
        self._runtimes = _RuntimePanel(engine)
        self._pull = _PullPanel(engine, config)
        self._tabs.addTab(self._catalog, "Catalog")
        self._tabs.addTab(self._installed, "Installed")
        self._tabs.addTab(self._runtimes, "Runtimes")
        self._tabs.addTab(self._pull, "Engine pull")
        outer.addWidget(self._tabs, 1)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setAccessibleName("Download progress")
        outer.addWidget(self._progress)

        self._status = QLabel("Ready.")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

        engine.task_done.connect(self._on_task_done)
        engine.task_failed.connect(self._on_task_failed)
        engine.acquisition_progress.connect(self._on_progress)

        self._catalog.refresh()
        self._installed.refresh()
        self._runtimes.refresh()

    # ---- engine callbacks --------------------------------------------------------------

    def _on_task_done(self, key: str, result: object) -> None:
        """Route one completed background call to the panel that asked for it."""
        if key == _CATALOG_KEY and isinstance(result, CatalogView):
            self._catalog.on_catalog(result)
            self._status.setText(f"Catalog: {len(result.entries)} entries.")
        elif key == _INSTALLED_KEY and isinstance(result, Sequence):
            self._installed.on_installed(result)
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
            self._installed.refresh()
        elif key == _INSTALL_RUNTIME_KEY and isinstance(result, InstallReport):
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
        self._installed.refresh()

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
        self._status.setText(f"{message}\nHint: {hint}" if hint else message)

    def set_providers(self, config: DemoConfig) -> None:
        """Adopt new provider configuration, for the pull panel's engine list."""
        self._pull.set_providers(config)
