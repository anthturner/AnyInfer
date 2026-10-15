"""The unified catalog and installed inventories, annotated with fit and ownership."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anyinfer import CatalogView
from anyinfer.local.store import StoreEntry
from anyinfer.local.tuning import Posture
from anyinfer.types.capabilities import DiscoveredModel

from ...config import DemoConfig
from ...engine import Engine
from ..add_model_dialog import AddModelChoice, catalog_model_choice
from ..formatting import _bytes
from ..icons import brand_icon
from ..sdk_help import SdkHelpButton
from ._shared import _CATALOG_KEY, _REMOVE_KEY, _llama_cpp_enabled, _LlamaSetupPrompt

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
