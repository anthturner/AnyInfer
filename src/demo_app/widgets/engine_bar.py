"""The friendly engine/model/context-window picker row.

This replaces typing raw ``provider:model`` target strings: the engines the user has
enabled appear in a dropdown, the models an engine reports appear next to it (with their
size, when the engine says — Ollama reports parameter count and quantization), and the
context window sits at the end with an auto-detect toggle, matching Frisket's
``ContextWindowOverrideRow``: while auto-detect is on the field is disabled and shows the
actual token count on file for the current engine/model, so the user can see the budget
that will really apply; toggling it off frees the field for a manual value.

The bar still *produces* a target string — ``provider:model`` is exactly what
`Route` consumes — it just stops making humans write one.
No provider-specific code lives here: engines come from the registry, models and
sizes from ``list_models()`` discovery, and context windows from provenance-tagged
capabilities, never invented.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from anyinfer.errors import AnyInferError
from anyinfer.registry import ProviderRegistry
from anyinfer.types.capabilities import DiscoveredModel, Sourced

from ..config import DemoConfig
from .icons import themed_icon

__all__ = ["ContextWindowRow", "EngineBar"]

_BASE_TOOLTIP = (
    "Maximum tokens this engine accepts in one request. Leave automatic unless "
    "the engine reports the wrong size."
)

_PROVENANCE_NOTE = {
    "discovered": "reported by the engine",
    "probed": "measured by a probe",
    "catalog": "from the bundled catalog",
    "default": "the provider's default assumption",
}


class ContextWindowRow(QWidget):
    """Auto-detect/manual context-window control, as in Frisket.

    In auto-detect mode the field is disabled and shows the token count actually on file
    for the current engine/model rather than a generic "Auto-detected" label; the tooltip
    names where that number came from, because capability values carry provenance
    and an estimate must never look authoritative.
    """

    changed = Signal()

    def __init__(
        self, parent: QWidget | None = None, *, initial_tokens: int | None = None
    ) -> None:
        super().__init__(parent)
        self._auto = initial_tokens is None
        self._manual_tokens = "" if initial_tokens is None else str(initial_tokens)
        self._detected: Sourced[int] | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._input = QLineEdit(self)
        self._input.setAccessibleDescription(_BASE_TOOLTIP)
        self._toggle = QPushButton(self)
        self._toggle.setObjectName("IconButton")
        self._toggle.setFixedSize(32, 32)
        self._toggle.setIconSize(QSize(18, 18))
        self._toggle.setAccessibleName("Automatic context window")
        layout.addWidget(self._input, 1)
        layout.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignVCenter)

        self._input.textChanged.connect(lambda *_: self.changed.emit())
        self._toggle.clicked.connect(self._toggle_auto)
        self._update_controls()

    @property
    def auto_detect(self) -> bool:
        """Whether the row is in auto-detect mode."""
        return self._auto

    def tokens(self) -> int | None:
        """The manual override in tokens, or ``None`` in auto-detect mode or when blank."""
        if self._auto:
            return None
        text = self._input.text().strip()
        if not text.isdigit():
            return None
        value = int(text)
        return value if value > 0 else None

    def set_detected(self, detected: Sourced[int] | None) -> None:
        """Point the auto-detect display at what is known for the current engine/model."""
        self._detected = detected
        if self._auto:
            self._update_controls()

    def reapply_theme(self) -> None:
        """Re-render the toggle icon after a theme change.

        Only the icon: a full ``_update_controls`` would reset the line edit's text from
        the stored manual value, clobbering whatever the user is actively typing.
        """
        self._toggle.setIcon(themed_icon(self._toggle, "wand" if self._auto else "wand-off"))

    def _toggle_auto(self, _checked: bool = False) -> None:
        self._auto = not self._auto
        self._update_controls()
        self.changed.emit()

    def _update_controls(self) -> None:
        self._toggle.setIcon(themed_icon(self._toggle, "wand" if self._auto else "wand-off"))
        self._toggle.setToolTip(
            "Disable automatic context-window detection."
            if self._auto
            else "Enable automatic context-window detection."
        )
        self._input.setEnabled(not self._auto)
        if self._auto:
            self._manual_tokens = self._input.text().strip() or self._manual_tokens
            self._input.clear()
            self._input.setPlaceholderText(self._auto_placeholder())
            self._input.setToolTip(self._auto_tooltip())
        else:
            self._input.setPlaceholderText("Tokens (minimum 1024)")
            self._input.setText(self._manual_tokens)
            self._input.setToolTip(_BASE_TOOLTIP)

    def _auto_placeholder(self) -> str:
        if self._detected is None:
            return "Auto-detected"
        return f"Auto-detected — {self._detected.value:,} tokens"

    def _auto_tooltip(self) -> str:
        if self._detected is None:
            return f"{_BASE_TOOLTIP} Not yet detected; refresh the model list to detect it."
        note = _PROVENANCE_NOTE.get(self._detected.provenance, self._detected.provenance)
        return (
            f"{_BASE_TOOLTIP} Detected a {self._detected.value:,}-token context window "
            f"for this engine and model ({note})."
        )


class EngineBar(QWidget):
    """One row: engine dropdown, model-and-size dropdown, context window with auto-detect."""

    changed = Signal()
    refresh_requested = Signal(str)
    """Asks the owner to run model discovery for a provider id."""

    def __init__(
        self,
        registry: ProviderRegistry,
        config: DemoConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry = registry
        self._discovered: dict[str, list[DiscoveredModel]] = {}
        self._model_drafts: dict[str, str] = {}
        # instance id → the engine it is an instance of, for looking up display names and
        # capability defaults that belong to the engine rather than the instance.
        self._engine_of: dict[str, str] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Engine:"))
        self._engine = QComboBox()
        self._engine.setToolTip("Every engine enabled under File → Provider settings…")
        layout.addWidget(self._engine, 2)

        layout.addWidget(QLabel("Model:"))
        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setToolTip(
            "Models this engine reports, with their size when the engine says. "
            "Type a name to use a model that is not listed."
        )
        layout.addWidget(self._model, 3)

        self._refresh = QPushButton()
        self._refresh.setObjectName("IconButton")
        self._refresh.setFixedSize(32, 32)
        self._refresh.setIconSize(QSize(18, 18))
        self._refresh.setAccessibleName("Refresh available models")
        self._refresh.setToolTip("Reload this engine's model list.")
        layout.addWidget(self._refresh, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(QLabel("Context window:"))
        self._context = ContextWindowRow(self, initial_tokens=config.context_window_tokens)
        layout.addWidget(self._context, 2)

        self.set_providers(config)
        if config.targets:
            self.set_target(config.targets[0])

        self._engine.currentIndexChanged.connect(self._on_engine_changed)
        self._model.currentTextChanged.connect(self._on_model_changed)
        self._model.activated.connect(self._on_model_activated)
        self._context.changed.connect(self.changed)
        self._refresh.clicked.connect(self._request_refresh)
        self.reapply_theme()

    # ---- selection -------------------------------------------------------------------

    def provider_id(self) -> str:
        """The selected engine instance's id — its alias, when it has one."""
        data = self._engine.currentData()
        return str(data) if isinstance(data, str) else ""

    def model(self) -> str:
        """The selected model id, undecorated."""
        text = self._model.currentText().strip()
        index = self._model.findText(text)
        if index >= 0 and isinstance(self._model.itemData(index), str):
            return str(self._model.itemData(index))
        return text

    def target(self) -> str:
        """The selection as the ``provider:model`` string a Route consumes."""
        provider, model = self.provider_id(), self.model()
        return f"{provider}:{model}" if provider and model else ""

    def set_target(self, target: str) -> None:
        """Select a saved target by instance id, keeping it verbatim if that id is gone.

        An instance that is no longer enabled is inserted as a plain entry rather than
        dropped, so a saved selection survives a settings round-trip visibly instead of
        silently changing.
        """
        provider, _, model = target.partition(":")
        index = self._engine.findData(provider)
        if index < 0:
            label = self._instance_label(self._engine_for(provider), provider)
            self._engine.addItem(label, provider)
            index = self._engine.count() - 1
        self._engine.setCurrentIndex(index)
        self._populate_models(provider)
        self._model.setCurrentText(model)
        self._model_drafts[provider] = model
        self._refresh_context_hint()

    def context_window_tokens(self) -> int | None:
        """The manual context-window override, or ``None`` when auto-detect is on."""
        return self._context.tokens()

    def known_targets(self) -> tuple[str, ...]:
        """Every discovered ``provider:model``, for building fallback choices."""
        return tuple(
            f"{provider}:{model.id}"
            for provider, models in sorted(self._discovered.items())
            for model in models
        )

    # ---- wiring ----------------------------------------------------------------------

    def set_providers(self, config: DemoConfig) -> None:
        """Rebuild the engine dropdown from the enabled instances.

        Items are keyed by *instance* id, so two instances of one engine are two
        separately selectable entries rather than one that silently wins.
        """
        selected = self.provider_id()
        self._engine.blockSignals(True)
        self._engine.clear()
        self._engine_of.clear()
        for provider in config.enabled_providers():
            instance_id = provider.instance_id
            self._engine_of[instance_id] = provider.provider_id
            self._engine.addItem(
                self._instance_label(provider.provider_id, instance_id), instance_id
            )
        index = self._engine.findData(selected)
        self._engine.setCurrentIndex(max(0, index))
        self._engine.blockSignals(False)
        self._populate_models(self.provider_id())
        self._refresh_context_hint()

    def _instance_label(self, provider_id: str, instance_id: str) -> str:
        """Label one instance: the engine's name, plus the alias when it has one.

        Showing both matters when an engine is configured twice — "OpenAI" alone would
        name two different endpoints identically.
        """
        display = self._display_name(provider_id)
        return display if instance_id == provider_id else f"{display} ({instance_id})"

    def on_models_listed(self, provider_id: str, models: Sequence[DiscoveredModel]) -> None:
        """Adopt one provider's discovery results."""
        self._discovered[provider_id] = [m for m in models if isinstance(m, DiscoveredModel)]
        if provider_id == self.provider_id():
            self._populate_models(provider_id)
            self._refresh_context_hint()
        self.changed.emit()

    def reapply_theme(self) -> None:
        """Re-render the themed icons after a theme change."""
        self._refresh.setIcon(themed_icon(self._refresh, "refresh"))
        self._context.reapply_theme()

    # ---- internals -------------------------------------------------------------------

    def _request_refresh(self) -> None:
        provider = self.provider_id()
        if provider:
            self.refresh_requested.emit(provider)

    def _engine_for(self, instance_id: str) -> str:
        """The engine behind an instance id, falling back to the id itself.

        A saved target may name an instance that is no longer configured; the registry
        still knows the engine when a previous client derived a descriptor for it.
        """
        known = self._engine_of.get(instance_id)
        if known:
            return known
        try:
            descriptor = self._registry.get(instance_id)
        except AnyInferError:
            return instance_id
        return descriptor.derived_from or descriptor.id

    def _display_name(self, provider_id: str) -> str:
        try:
            return self._registry.get(provider_id).display_name
        except AnyInferError:
            return provider_id

    def _on_engine_changed(self, _index: int) -> None:
        provider = self.provider_id()
        self._populate_models(provider)
        if provider and provider not in self._discovered:
            self.refresh_requested.emit(provider)
        self._refresh_context_hint()
        self.changed.emit()

    def _on_model_changed(self, model: str) -> None:
        provider = self.provider_id()
        if provider:
            self._model_drafts[provider] = model
        self._refresh_context_hint()
        self.changed.emit()

    def _on_model_activated(self, index: int) -> None:
        """Collapse a decorated "model — size" choice back to the plain model id."""
        data = self._model.itemData(index)
        if isinstance(data, str) and data:
            self._model.setCurrentText(data)

    def _populate_models(self, provider_id: str) -> None:
        draft = self._model_drafts.get(provider_id, self._model.currentText().strip())
        self._model.blockSignals(True)
        self._model.clear()
        for discovered in self._discovered.get(provider_id, []):
            self._model.addItem(_model_label(discovered), discovered.id)
        self._model.setCurrentText(draft)
        self._model.blockSignals(False)

    def _refresh_context_hint(self) -> None:
        self._context.set_detected(self._context_window())

    def _context_window(self) -> Sourced[int] | None:
        """What is known about the current selection's context window, if anything.

        Discovery outranks the descriptor's defaults, mirroring the library's provenance
        ordering — and when nothing is known the answer is honestly ``None``.
        """
        provider, model = self.provider_id(), self.model()
        for discovered in self._discovered.get(provider, []):
            if (
                discovered.id == model
                and discovered.capabilities is not None
                and discovered.capabilities.context_window is not None
            ):
                return discovered.capabilities.context_window
        try:
            defaults = self._registry.get(self._engine_for(provider)).default_capabilities
        except AnyInferError:
            return None
        return defaults.context_window if defaults is not None else None


def _model_label(discovered: DiscoveredModel) -> str:
    """A dropdown label: the model id, plus its size when the engine reported one."""
    capabilities = discovered.capabilities
    local = capabilities.local if capabilities is not None else None
    details: list[str] = []
    if local is not None:
        if local.parameter_size:
            details.append(str(local.parameter_size))
        if local.quantization:
            details.append(str(local.quantization))
        if not details and local.artifact_size_bytes:
            details.append(f"{local.artifact_size_bytes / 1_073_741_824:.1f} GiB")
    return f"{discovered.id} — {' · '.join(details)}" if details else discovered.id
