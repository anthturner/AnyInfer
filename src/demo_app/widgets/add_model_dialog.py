"""Unified model search over AnyInfer's verified local-engine catalog channels."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anyinfer import CatalogEntryFit, CatalogView
from anyinfer.local.downloads import default_model_dir
from anyinfer.local.server import is_loopback
from anyinfer.registry import ProviderRegistry

from ..config import DemoConfig, ProviderConfig

__all__ = ["AddModelChoice", "AddModelDialog", "catalog_model_choice"]


@dataclass(frozen=True, slots=True)
class AddModelChoice:
    """One selected model and the SDK operation that can make it available."""

    operation: Literal["acquire", "pull"]
    instance_id: str
    provider_id: str
    model_id: str
    model_ref: str
    acquisition_engine: str | None = None


def _normalized_engine(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _acquisition_engine(entry: CatalogEntryFit, provider_id: str) -> str | None:
    """Match a provider channel to a variant engine without maintaining an engine list."""
    engines = sorted({variant.engine for variant in entry.model.variants})
    wanted = _normalized_engine(provider_id)
    exact = [engine for engine in engines if _normalized_engine(engine) == wanted]
    if len(exact) == 1:
        return exact[0]
    return engines[0] if len(engines) == 1 else None


def _pull_reference(entry: CatalogEntryFit, provider_id: str) -> str:
    """Read a provider channel's catalog reference, such as an Ollama registry tag."""
    channel = getattr(entry.model, provider_id.replace("-", "_"), None)
    tag = getattr(channel, "tag", "")
    return tag if isinstance(tag, str) else ""


def catalog_model_choice(
    entry: CatalogEntryFit,
    provider: ProviderConfig,
    registry: ProviderRegistry,
) -> AddModelChoice | None:
    """Resolve a catalog row to the operation declared by one provider instance."""
    if not registry.has(provider.provider_id):
        return None
    descriptor = registry.get(provider.provider_id)
    pulling = descriptor.model_puller is not None
    model_ref = _pull_reference(entry, provider.provider_id) if pulling else entry.id
    engine = None if pulling else _acquisition_engine(entry, provider.provider_id)
    if not model_ref or (not pulling and engine is None):
        return None
    return AddModelChoice(
        operation="pull" if pulling else "acquire",
        instance_id=provider.instance_id,
        provider_id=provider.provider_id,
        model_id=entry.id,
        model_ref=model_ref,
        acquisition_engine=engine,
    )


def _nearest_existing(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


class AddModelDialog(QDialog):
    """Search compatible catalog channels and choose the correct install operation."""

    def __init__(
        self,
        view: CatalogView,
        config: DemoConfig,
        registry: ProviderRegistry,
        parent: QWidget | None = None,
        *,
        benchmark_context: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add local model")
        self.setMinimumSize(980, 600)
        self._view = view
        self._registry = registry
        self._providers: dict[str, ProviderConfig] = {}
        self._choice: AddModelChoice | None = None
        self._free_disk_bytes: int | None
        try:
            self._free_disk_bytes = shutil.disk_usage(_nearest_existing(default_model_dir())).free
        except OSError:
            self._free_disk_bytes = None

        outer = QVBoxLayout(self)
        intro = QLabel(
            "Search AnyInfer's verified model catalog. llama.cpp and vLLM downloads use "
            "pinned Hugging Face revisions; engines with their own store use their own "
            "catalog tag and downloader."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        if benchmark_context:
            benchmark = QLabel(benchmark_context)
            benchmark.setWordWrap(True)
            benchmark.setTextFormat(Qt.TextFormat.RichText)
            benchmark.setObjectName("HintText")
            outer.addWidget(benchmark)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Engine:"))
        self._engine = QComboBox()
        self._engine.setMinimumWidth(260)
        self._engine.setMaximumWidth(340)
        self._engine.setAccessibleName("Local engine for new model")
        for provider in config.enabled_providers():
            if not registry.has(provider.provider_id):
                continue
            descriptor = registry.get(provider.provider_id)
            if descriptor.locality != "local":
                continue
            self._providers[provider.instance_id] = provider
            self._engine.addItem(
                f"{provider.instance_id} — {descriptor.display_name}", provider.instance_id
            )
        self._engine.currentIndexChanged.connect(self._repopulate)
        controls.addWidget(self._engine)

        controls.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setMinimumWidth(210)
        self._search.setPlaceholderText("name, family, capability, or model id")
        self._search.setAccessibleName("Search verified local models")
        self._search.textChanged.connect(self._repopulate)
        controls.addWidget(self._search, 1)

        self._show_unreasonable = QCheckBox("Show models that should not be used")
        self._show_unreasonable.setChecked(True)
        self._show_unreasonable.toggled.connect(self._repopulate)
        controls.addWidget(self._show_unreasonable)
        outer.addLayout(controls)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Model", "Source", "Size", "Recommendation", "Why"])
        self._table.setAccessibleName("Models available to add")
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self._table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemDoubleClicked.connect(lambda *_: self._accept())
        outer.addWidget(self._table, 1)

        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setObjectName("HintText")
        outer.addWidget(self._detail)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._add = QPushButton("Add")
        self._add.setEnabled(False)
        self._add.clicked.connect(self._accept)
        buttons.addButton(self._add, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._empty = QLabel()
        self._empty.setWordWrap(True)
        self._empty.setObjectName("HintText")
        outer.insertWidget(2, self._empty)
        self._repopulate()

    def choice(self) -> AddModelChoice | None:
        """Return the operation selected by the accepted dialog."""
        return self._choice

    def focus_search(self) -> None:
        """Put the cursor in the model search field."""
        self._search.setFocus()
        self._search.selectAll()

    def _current_provider(self) -> ProviderConfig | None:
        instance = self._engine.currentData()
        return self._providers.get(instance) if isinstance(instance, str) else None

    def _entries(self) -> list[CatalogEntryFit]:
        provider = self._current_provider()
        if provider is None:
            return []
        query = self._search.text().strip().casefold()
        entries = [entry for entry in self._view.entries if provider.provider_id in entry.channels]
        if query:
            entries = [
                entry
                for entry in entries
                if query
                in " ".join(
                    (
                        entry.id,
                        entry.name,
                        entry.model.family,
                        entry.model.description,
                        " ".join(entry.model.best_at),
                    )
                ).casefold()
            ]
        if not self._show_unreasonable.isChecked():
            entries = [entry for entry in entries if self._recommendation(entry)[1]]
        return entries

    def _repopulate(self, *_args: object) -> None:
        self._table.setRowCount(0)
        entries = self._entries()
        query = self._search.text().strip()
        best_id = next(
            (entry.id for entry in entries if self._recommendation(entry)[1]),
            "",
        )
        provider = self._current_provider()
        for entry in entries:
            row = self._table.rowCount()
            self._table.insertRow(row)
            name = QTableWidgetItem(entry.name)
            name.setData(Qt.ItemDataRole.UserRole, entry)
            self._table.setItem(row, 0, name)
            self._table.setItem(row, 1, QTableWidgetItem(self._source(entry, provider)))
            self._table.setItem(row, 2, QTableWidgetItem(self._bytes(entry.model.est_file_bytes)))
            recommendation, _reasonable, why = self._recommendation(entry)
            if entry.id == best_id:
                recommendation = f"★ Best match · {recommendation}"
            self._table.setItem(row, 3, QTableWidgetItem(recommendation))
            why_item = QTableWidgetItem(why)
            why_item.setToolTip("\n".join(entry.fit.reasons))
            self._table.setItem(row, 4, why_item)
        provider = self._current_provider()
        has_channel = bool(
            provider
            and any(provider.provider_id in entry.channels for entry in self._view.entries)
        )
        if entries:
            empty_text = ""
        elif not self._providers:
            empty_text = (
                "No enabled local engine is configured. Enable llama.cpp, Ollama, vLLM, "
                "or another local provider under Provider settings."
            )
        elif provider is not None and not has_channel:
            display = self._registry.get(provider.provider_id).display_name
            empty_text = f"The bundled verified catalog currently has no {display} artifacts."
            if self._registry.get(provider.provider_id).model_puller is not None:
                empty_text += " Enter an exact model id above to ask that engine to pull it."
        else:
            descriptor = self._registry.get(provider.provider_id) if provider is not None else None
            if descriptor is not None and descriptor.model_puller is not None and query:
                empty_text = (
                    "No shipped catalog model matches. Choose Pull to ask "
                    f"{descriptor.display_name} "
                    f"to fetch “{query}” from its own model index."
                )
            else:
                empty_text = "No catalog models match this search."
        self._empty.setText(empty_text)
        if entries:
            self._table.selectRow(0)
        else:
            self._on_selection_changed()

    def _source(self, entry: CatalogEntryFit, provider: ProviderConfig | None) -> str:
        if provider is None or not self._registry.has(provider.provider_id):
            return "Catalog"
        descriptor = self._registry.get(provider.provider_id)
        if descriptor.model_puller is not None:
            return f"{descriptor.display_name} index"
        engine = _acquisition_engine(entry, provider.provider_id)
        variants = entry.model.variants_for(engine)
        if any(variant.source.resolver == "huggingface" for variant in variants):
            return "Hugging Face (pinned)"
        return "AnyInfer catalog"

    def _recommendation(self, entry: CatalogEntryFit) -> tuple[str, bool, str]:
        provider = self._current_provider()
        if provider is not None and self._registry.has(provider.provider_id):
            descriptor = self._registry.get(provider.provider_id)
            endpoint = provider.base_url or descriptor.default_base_url
            if endpoint is not None and not is_loopback(endpoint):
                return (
                    "Remote fit unknown",
                    True,
                    "This engine runs on another host, so this machine's RAM, accelerator, "
                    "disk, and benchmark results do not describe it.",
                )
        puller = bool(
            provider
            and self._registry.has(provider.provider_id)
            and self._registry.get(provider.provider_id).model_puller is not None
        )
        size = entry.model.est_file_bytes
        first_reason = entry.fit.reasons[0] if entry.fit.reasons else "No fit reason reported."
        if (
            not puller
            and size is not None
            and self._free_disk_bytes is not None
            and size * 1.1 > self._free_disk_bytes
        ):
            return (
                "Do not use — disk",
                False,
                f"Needs about {self._bytes(round(size * 1.1))}; only "
                f"{self._bytes(self._free_disk_bytes)} is free.",
            )
        labels = {
            "gpu": ("Recommended", True),
            "cpu": ("Works on CPU", True),
            "tight": ("Caution — tight fit", True),
            "unknown": ("Fit unknown", True),
            "no": ("Do not use — too large", False),
        }
        label, reasonable = labels.get(entry.fit.level, (entry.fit.level, False))
        return label, reasonable, first_reason

    def _selected_entry(self) -> CatalogEntryFit | None:
        items = self._table.selectedItems()
        if not items:
            return None
        item = self._table.item(items[0].row(), 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return value if isinstance(value, CatalogEntryFit) else None

    def _on_selection_changed(self) -> None:
        entry = self._selected_entry()
        provider = self._current_provider()
        if provider is None:
            self._add.setEnabled(False)
            self._detail.clear()
            return
        descriptor = self._registry.get(provider.provider_id)
        pulling = descriptor.model_puller is not None
        manual_ref = self._search.text().strip() if pulling and entry is None else ""
        if entry is None:
            self._add.setEnabled(bool(manual_ref))
            self._add.setText("Pull")
            self._detail.setText(
                f"Ask {descriptor.display_name} to pull {manual_ref} from its own model index."
                if manual_ref
                else ""
            )
            return
        choice = catalog_model_choice(entry, provider, self._registry)
        self._add.setEnabled(choice is not None)
        self._add.setText("Pull" if pulling else "Download")
        recommendation, _reasonable, why = self._recommendation(entry)
        self._detail.setText(f"<b>{recommendation}.</b> {why}")

    def _accept(self) -> None:
        entry = self._selected_entry()
        provider = self._current_provider()
        if provider is None:
            return
        descriptor = self._registry.get(provider.provider_id)
        pulling = descriptor.model_puller is not None
        if entry is None:
            model_ref = self._search.text().strip()
            if not pulling or not model_ref:
                return
            self._choice = AddModelChoice(
                operation="pull",
                instance_id=provider.instance_id,
                provider_id=provider.provider_id,
                model_id=model_ref,
                model_ref=model_ref,
            )
            self.accept()
            return
        choice = catalog_model_choice(entry, provider, self._registry)
        if choice is None:
            return
        recommendation, reasonable, why = self._recommendation(entry)
        if not reasonable:
            confirmed = QMessageBox.question(
                self,
                "Add a model that should not be used?",
                f"{entry.name}: {recommendation}.\n\n{why}\n\nContinue anyway?",
            )
            if confirmed != QMessageBox.StandardButton.Yes:
                return
        self._choice = choice
        self.accept()

    @staticmethod
    def _bytes(count: int | None) -> str:
        if count is None:
            return "—"
        size = float(count)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if size < 1024 or unit == "GiB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GiB"
