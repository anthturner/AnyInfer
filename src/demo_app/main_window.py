"""The demo's main window: composition, not logic.

Every behaviour on display belongs to AnyInfer; this file only wires widgets to
`Engine` signals. In particular there is no retry loop, no fallback
logic, no schema validation and no timing measurement here — those are the library's job,
and duplicating any of them in an application is the mistake this demo is meant to prevent.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anyinfer import Retry, Route
from anyinfer.errors import AnyInferError
from anyinfer.types.capabilities import Health
from anyinfer.types.messages import Message, Text, system, user
from anyinfer.types.requests import Repair, Sampling
from anyinfer.types.results import AttemptRecord, Generation

from . import config as config_module
from . import strings, theme
from .config import DemoConfig
from .conversation import Conversation, conversations_dir
from .engine import Engine, GenerationSpec
from .widgets import (
    CollapsibleSection,
    Composer,
    ConversationSidebar,
    EngineBar,
    ProviderSettingsDialog,
    SchemaPanel,
    StatusMetrics,
    TelemetryView,
    WelcomeView,
)
from .widgets.chat_view import MessageList
from .widgets.icons import themed_icon

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    """The demo window."""

    def __init__(self, config: DemoConfig, config_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("AnyInfer Demo")
        self.resize(1280, 860)

        self._engine = Engine(config)
        self._conversation: list[Message] = []
        self._pending_target = ""
        self._streaming_started = False
        self._theme = config.theme
        # Saves must go back to the file the app was started with (`--config PATH`),
        # not unconditionally to the default location.
        self._config_path = config_path or config_module.CONFIG_PATH
        self._conversations_dir = conversations_dir(self._config_path.parent)
        self._current_conversation = Conversation.new()

        # Coalesces per-keystroke budget refreshes into one call per typing pause;
        # `budget()` is pure and cheap, but re-running it on every keystroke is waste.
        self._token_hint_timer = QTimer(self)
        self._token_hint_timer.setSingleShot(True)
        self._token_hint_timer.setInterval(250)
        self._token_hint_timer.timeout.connect(self._refresh_token_hint)

        self._build_ui(config)
        self._connect_engine()
        self._build_menu()
        self._build_shortcuts()
        self._apply_theme(config.theme)
        self._follow_system_scheme()
        self._discover_enabled_providers()
        self._reload_sidebar()

    # ---- construction ----------------------------------------------------------------

    def _build_ui(self, config: DemoConfig) -> None:
        outer = QSplitter(Qt.Orientation.Horizontal)

        self._sidebar = ConversationSidebar()
        self._sidebar.new_chat_requested.connect(self._on_new_chat)
        self._sidebar.conversation_selected.connect(self._on_conversation_selected)
        self._sidebar.rename_requested.connect(self._on_rename_conversation)
        self._sidebar.delete_requested.connect(self._on_delete_conversation)
        self._sidebar.export_requested.connect(self._on_export_conversation)
        self._sidebar.export_all_requested.connect(self._on_export_all)
        self._sidebar.import_requested.connect(self._on_import_conversation)
        outer.addWidget(self._sidebar)

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.addWidget(self._build_center_pane(config))
        self._main_splitter.addWidget(self._build_inspector())
        self._main_splitter.setStretchFactor(0, 3)
        self._main_splitter.setStretchFactor(1, 2)
        outer.addWidget(self._main_splitter)

        outer.setStretchFactor(0, 0)
        outer.setStretchFactor(1, 1)
        outer.setSizes([220, 1000])

        self.setCentralWidget(outer)
        self.setStatusBar(QStatusBar())
        self._status_metrics = StatusMetrics()
        self.statusBar().addPermanentWidget(self._status_metrics)
        self.statusBar().showMessage("Ready — offline fake provider, no credentials needed.")

    def _build_center_pane(self, config: DemoConfig) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)

        self._engine_bar = EngineBar(self._engine.registry, config)
        self._engine_bar.refresh_requested.connect(self._engine.list_models)
        layout.addWidget(self._engine_bar)

        self._chat = MessageList()
        self._welcome = WelcomeView()
        self._welcome.new_chat_requested.connect(self._on_new_chat)
        self._welcome.structured_output_requested.connect(self._on_welcome_structured)
        self._welcome.fallback_demo_requested.connect(self._on_welcome_fallback)
        self._chat.set_empty_state(self._welcome)
        layout.addWidget(self._chat, 1)

        self._composer = Composer()
        self._composer.send_requested.connect(self._on_send)
        self._composer.cancel_requested.connect(self._engine.cancel)
        self._composer.quick_action_chosen.connect(self._composer.set_text)
        self._composer.text_changed.connect(self._schedule_token_hint)
        layout.addWidget(self._composer)

        layout.addLayout(self._build_controls())
        return pane

    def _build_controls(self) -> QHBoxLayout:
        controls = QHBoxLayout()

        controls.addWidget(QLabel("Temperature:"))
        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setSpecialValueText("provider default")
        self._temperature.setValue(0.0)
        self._temperature.setAccessibleName("Temperature")
        self._temperature.setToolTip(
            "At the minimum the field reads 'provider default' and is omitted from the wire "
            "request entirely — AnyInfer never invents a temperature."
        )
        controls.addWidget(self._temperature)

        controls.addWidget(QLabel("Max attempts/target:"))
        self._max_attempts = QSpinBox()
        self._max_attempts.setRange(1, 5)
        self._max_attempts.setValue(2)
        self._max_attempts.setAccessibleName("Max attempts per target")
        self._max_attempts.setToolTip("Retry budget per target, before falling back.")
        controls.addWidget(self._max_attempts)

        controls.addWidget(QLabel("If it fails, try:"))
        self._fallback = QComboBox()
        self._fallback.addItem("Nothing (no fallback)", "")
        self._fallback.setAccessibleName("Fallback target")
        self._fallback.setToolTip(
            "Optional fallback target the router moves to once the retry budget is spent. "
            "Pick the flaky demo model above with 1 attempt to watch it happen."
        )
        controls.addWidget(self._fallback)
        saved = self._engine.config.targets
        if len(saved) > 1:
            self._fallback.addItem(saved[1], saved[1])
            self._fallback.setCurrentIndex(1)
        self._engine_bar.changed.connect(self._update_fallback_choices)
        self._engine_bar.changed.connect(self._refresh_token_hint)

        controls.addStretch(1)
        return controls

    def _build_inspector(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)

        self._inspector_splitter = QSplitter(Qt.Orientation.Vertical)

        self._telemetry = TelemetryView()
        self._telemetry_section = CollapsibleSection(strings.TELEMETRY_TITLE, self._telemetry)
        self._inspector_splitter.addWidget(self._telemetry_section)

        self._schema = SchemaPanel()
        self._schema_section = CollapsibleSection(strings.STRUCTURED_TITLE, self._schema)
        self._inspector_splitter.addWidget(self._schema_section)

        self._providers_section = CollapsibleSection(
            strings.PROVIDERS_TITLE, self._build_providers_tab()
        )
        self._inspector_splitter.addWidget(self._providers_section)
        self._inspector_splitter.setSizes([300, 300, 260])
        layout.addWidget(self._inspector_splitter, 1)

        self._inspector_sections: dict[str, CollapsibleSection] = {
            "telemetry": self._telemetry_section,
            "structured": self._schema_section,
            "providers": self._providers_section,
        }
        return pane

    def _build_providers_tab(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)

        caption = QLabel(
            "Discovery and health probes go through the same adapter contract for every "
            "provider: <code>list_models()</code> and <code>health()</code>."
        )
        caption.setWordWrap(True)
        caption.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(caption)

        buttons = QHBoxLayout()
        configure = QPushButton(strings.SETTINGS)
        configure.setAccessibleName(strings.SETTINGS)
        configure.clicked.connect(self._on_configure)
        buttons.addWidget(configure)

        refresh = QPushButton()
        refresh.setObjectName("IconButton")
        refresh.setFixedSize(32, 32)
        refresh.setIconSize(QSize(18, 18))
        refresh.setIcon(themed_icon(refresh, "refresh"))
        refresh.setToolTip(strings.REFRESH)
        refresh.setAccessibleName(strings.REFRESH)
        refresh.clicked.connect(self._on_refresh_providers)
        buttons.addWidget(refresh)
        self._provider_refresh_button = refresh
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._provider_table = QTableWidget(0, 4)
        # Rows are keyed by instance, so the engine is named alongside it: two instances
        # of one engine are two rows that would otherwise be indistinguishable.
        self._provider_table.setHorizontalHeaderLabels(
            ["Alias", "Engine", "Health", "Models"]
        )
        self._provider_table.setAccessibleName("Provider report")
        self._provider_table.horizontalHeader().setStretchLastSection(True)
        self._provider_table.verticalHeader().setVisible(False)
        self._provider_table.setEditTriggers(self._provider_table.EditTrigger.NoEditTriggers)
        layout.addWidget(self._provider_table, 1)
        self._provider_rows: dict[str, int] = {}
        return pane

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        settings_action = QAction("Provider &settings…", self)
        settings_action.triggered.connect(self._on_configure)
        file_menu.addAction(settings_action)

        new_chat_action = QAction("&New chat", self)
        new_chat_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        new_chat_action.triggered.connect(self._on_new_chat)
        file_menu.addAction(new_chat_action)

        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        self._build_sidebar_menu(view_menu)
        view_menu.addSeparator()
        self._build_theme_menu(view_menu)

        send_action = QAction("Send", self)
        send_action.setShortcut(QKeySequence("Ctrl+Return"))
        send_action.triggered.connect(self._on_send)
        self.addAction(send_action)

    def _build_sidebar_menu(self, view_menu: QMenu) -> None:
        """Whole-sidebar and per-section visibility checkboxes.

        Grouped together (rather than split across menus) so "hide the whole right
        sidebar" and "hide just Telemetry" read as the same kind of choice, one coarser
        than the other.
        """
        self._left_sidebar_action = QAction(strings.SHOW_LEFT_SIDEBAR, self, checkable=True)
        self._left_sidebar_action.setChecked(True)
        self._left_sidebar_action.triggered.connect(self._set_left_sidebar_visible)
        view_menu.addAction(self._left_sidebar_action)

        self._right_sidebar_action = QAction(strings.SHOW_RIGHT_SIDEBAR, self, checkable=True)
        self._right_sidebar_action.setChecked(True)
        self._right_sidebar_action.triggered.connect(self._set_right_sidebar_visible)
        view_menu.addAction(self._right_sidebar_action)

        view_menu.addSeparator()

        conversations_action = QAction(strings.SHOW_CONVERSATIONS, self, checkable=True)
        conversations_action.setChecked(True)
        conversations_action.triggered.connect(self._set_left_sidebar_visible)
        view_menu.addAction(conversations_action)
        # The sidebar has one panel, so its own checkbox and the left-sidebar checkbox are
        # the same switch — keep both in sync rather than modeling a second state.
        self._left_sidebar_action.triggered.connect(conversations_action.setChecked)
        conversations_action.triggered.connect(self._left_sidebar_action.setChecked)

        self._section_actions: dict[str, QAction] = {}
        section_labels = (
            ("telemetry", strings.SHOW_TELEMETRY),
            ("structured", strings.SHOW_STRUCTURED),
            ("providers", strings.SHOW_PROVIDERS),
        )
        for key, label in section_labels:
            action = QAction(label, self, checkable=True)
            action.setChecked(True)
            action.triggered.connect(
                lambda checked, k=key: self._set_inspector_section_visible(k, checked)
            )
            view_menu.addAction(action)
            self._section_actions[key] = action

    def _build_theme_menu(self, view_menu: QMenu) -> None:
        """Build the Theme submenu.

        Custom palettes first, then a separator, then the OS-following defaults — custom
        themes are the more deliberate, less "default" choice, so they lead.

        The menu, action group, and per-theme actions are kept as instance attributes
        rather than locals: PySide6 does not keep a Python wrapper alive just because its
        underlying Qt object is still parented, so an unreferenced local here can be
        garbage-collected out from under the menu it was wired into.
        """
        self._theme_menu = view_menu.addMenu("&Theme")
        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}

        for key, label in theme.CUSTOM_THEMES_MENU:
            self._add_theme_action(key, label)

        self._theme_menu.addSeparator()

        for key, label in theme.DEFAULT_THEME_CHOICES:
            self._add_theme_action(key, label)

    def _add_theme_action(self, key: str, label: str) -> None:
        action = QAction(label, self, checkable=True)
        action.setChecked(key == self._theme)
        action.triggered.connect(lambda _checked=False, p=key: self._set_theme(p))
        self._theme_action_group.addAction(action)
        self._theme_menu.addAction(action)
        self._theme_actions[key] = action

    def _build_shortcuts(self) -> None:
        cancel_action = QAction("Cancel generation", self)
        cancel_action.setShortcut(QKeySequence("Esc"))
        cancel_action.triggered.connect(self._engine.cancel)
        self.addAction(cancel_action)

        settings_action = QAction("Open settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        settings_action.triggered.connect(self._on_configure)
        self.addAction(settings_action)

        toggle_action = QAction("Toggle right sidebar", self)
        toggle_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        toggle_action.triggered.connect(self._toggle_right_sidebar)
        self.addAction(toggle_action)

        self.setTabOrder(self._engine_bar, self._chat)
        self.setTabOrder(self._chat, self._composer)

    def _connect_engine(self) -> None:
        self._engine.text_delta.connect(self._on_first_text_delta)
        self._engine.text_delta.connect(self._chat.append_delta)
        self._engine.reasoning_delta.connect(self._on_first_text_delta)
        self._engine.reasoning_delta.connect(self._chat.append_reasoning)
        self._engine.first_token.connect(self._status_metrics.set_first_token)
        self._engine.usage_update.connect(self._status_metrics.set_usage)
        self._engine.attempt_failed.connect(self._on_attempt_failed)
        self._engine.finished.connect(self._on_finished)
        self._engine.failed.connect(self._on_failed)
        self._engine.cancelled.connect(self._on_cancelled)
        self._engine.telemetry.connect(self._telemetry.add_event)
        self._engine.busy_changed.connect(self._on_busy_changed)
        self._engine.models_listed.connect(self._on_models_listed)
        self._engine.models_listed.connect(self._engine_bar.on_models_listed)
        self._engine.health_checked.connect(self._on_health_checked)
        self._engine.discovery_failed.connect(self._on_discovery_failed)

    # ---- actions ---------------------------------------------------------------------

    def _on_send(self) -> None:
        """Collect the UI state into a request and hand it to the engine."""
        if self._engine.busy:
            return
        prompt = self._composer.text().strip()
        if not prompt:
            return

        targets = self._route_targets()
        if not targets:
            self._warn("No model selected", "Choose an engine and a model first.")
            return

        try:
            schema = self._schema.schema()
        except ValueError as error:
            self._schema.report_error(str(error))
            self._warn("Invalid schema", str(error))
            return

        if not self._conversation and self._engine.config.system_prompt:
            self._conversation.append(system(self._engine.config.system_prompt))
        self._conversation.append(user(prompt))

        self._composer.clear()
        self._chat.add_user_message(prompt)
        self._chat.show_typing()
        self._status_metrics.reset()
        self._pending_target = targets[0]
        self._streaming_started = False

        spec = GenerationSpec(
            messages=tuple(self._conversation),
            route=Route(
                targets=targets,
                retry=Retry(max_attempts=self._max_attempts.value()),
                # Health gating would skip the flaky demo model after its scripted failure,
                # which would hide the retry behaviour this demo exists to show.
                health_gate=False,
            ),
            sampling=self._build_sampling(),
            schema=schema,
            repair=Repair(max_attempts=self._schema.repair_attempts()) if schema else None,
        )
        self._engine.generate(spec)

    def _on_first_text_delta(self, _text: str) -> None:
        """Open the real assistant bubble on first content, replacing the typing indicator."""
        if not self._streaming_started:
            self._streaming_started = True
            self._chat.begin_assistant_message(self._pending_target)

    def _build_sampling(self) -> Sampling:
        """Read sampling knobs, leaving unset ones genuinely unset."""
        temperature = self._temperature.value()
        return Sampling(temperature=None if temperature == 0.0 else temperature)

    def _route_targets(self) -> tuple[str, ...]:
        """The routing chain: the picked engine/model, then the optional fallback."""
        primary = self._engine_bar.target()
        if not primary:
            return ()
        fallback = self._fallback.currentData()
        if isinstance(fallback, str) and fallback and fallback != primary:
            return (primary, fallback)
        return (primary,)

    def _update_fallback_choices(self) -> None:
        """Refresh the fallback dropdown from everything discovery has reported."""
        selected = self._fallback.currentData()
        self._fallback.blockSignals(True)
        self._fallback.clear()
        self._fallback.addItem("Nothing (no fallback)", "")
        for target in self._engine_bar.known_targets():
            self._fallback.addItem(target, target)
        if isinstance(selected, str) and selected:
            index = self._fallback.findData(selected)
            if index < 0:  # keep a saved choice discovery has not (re)confirmed
                self._fallback.addItem(selected, selected)
                index = self._fallback.count() - 1
            self._fallback.setCurrentIndex(index)
        self._fallback.blockSignals(False)
        self._refresh_token_hint()

    def _on_configure(self) -> None:
        if self._engine.busy:
            # Applying settings tears down the client, which would kill the in-flight
            # stream mid-answer; make the user settle the generation first.
            self.statusBar().showMessage("Finish or cancel the current generation first.")
            return
        dialog = ProviderSettingsDialog(self._engine.registry, self._engine.config, self)
        if dialog.exec() != ProviderSettingsDialog.DialogCode.Accepted:
            return
        config = self._with_ui_state(dialog.result_config())
        self._engine.apply_config(config)
        self._engine_bar.set_providers(config)
        self._discover_enabled_providers()
        try:
            config.save(self._config_path)
        except OSError as error:
            self.statusBar().showMessage(f"Settings applied but not saved: {error}")
            return
        self.statusBar().showMessage("Settings saved; the client will rebuild on next use.")

    def _on_refresh_providers(self) -> None:
        self._provider_table.setRowCount(0)
        self._provider_rows.clear()
        enabled = list(self._engine.config.enabled_providers())
        if not enabled:
            self.statusBar().showMessage(
                "No providers are enabled. Use 'Configure providers…' to enable one."
            )
            return
        for provider in enabled:
            # Probing by instance id, not engine: two instances of one engine have
            # different endpoints and credentials, so each needs its own probe.
            self._engine.check_health(provider.instance_id)
            self._engine.list_models(provider.instance_id)

    def _set_right_sidebar_visible(self, visible: bool) -> None:
        """Show or fully hide the inspector pane (Telemetry/Structured output/Providers)."""
        sizes = self._main_splitter.sizes()
        if visible:
            if len(sizes) >= 2 and sizes[1] == 0:
                self._main_splitter.setSizes([3, 2])
        else:
            self._main_splitter.setSizes([sum(sizes) if sizes else 1, 0])
        self._right_sidebar_action.setChecked(visible)

    def _toggle_right_sidebar(self) -> None:
        sizes = self._main_splitter.sizes()
        collapsed = len(sizes) < 2 or sizes[1] == 0
        self._set_right_sidebar_visible(collapsed)

    def _set_left_sidebar_visible(self, visible: bool) -> None:
        """Show or fully hide the conversation history sidebar."""
        self._sidebar.setVisible(visible)
        self._left_sidebar_action.setChecked(visible)

    def _set_inspector_section_visible(self, key: str, visible: bool) -> None:
        """Show or fully hide one inspector section (distinct from minimize)."""
        self._inspector_sections[key].setVisible(visible)

    # ---- welcome / quick actions -------------------------------------------------------

    def _on_welcome_structured(self) -> None:
        self._schema.set_enabled(True)
        self._composer.set_text("Analyze this product review: 'Fast shipping, great value.'")

    def _on_welcome_fallback(self) -> None:
        index = self._fallback.findData("demo-fake:reliable")
        if index >= 0:
            self._fallback.setCurrentIndex(index)
        self._engine_bar.set_target("demo-fake:flaky")
        self._max_attempts.setValue(1)
        self._composer.set_text("Try the flaky target and show the retry and fallback trail.")

    # ---- conversation persistence ------------------------------------------------------

    def _on_new_chat(self) -> None:
        if self._engine.busy:
            # Clearing the transcript mid-stream would strand the in-flight answer.
            self.statusBar().showMessage("Finish or cancel the current generation first.")
            return
        self._save_current_conversation()
        self._current_conversation = Conversation.new()
        self._conversation.clear()
        self._chat.clear()
        self._status_metrics.reset()
        self._telemetry.clear()
        self.statusBar().showMessage("New chat.")
        self._reload_sidebar()

    def _on_conversation_selected(self, conversation_id: str) -> None:
        if conversation_id == self._current_conversation.id:
            return
        if self._engine.busy:
            # Switching would replay a different transcript under the active stream.
            self.statusBar().showMessage("Finish or cancel the current generation first.")
            self._reload_sidebar()  # restore the highlight to the active conversation
            return
        self._save_current_conversation()
        path = self._conversations_dir / f"{conversation_id}.json"
        loaded = Conversation.load(path)
        if loaded is None:
            return
        self._current_conversation = loaded
        self._conversation = list(loaded.messages)
        self._chat.clear()
        for message in loaded.messages:
            if message.role == "user":
                self._chat.add_user_message(message.text)
            elif message.role == "assistant":
                bubble = self._chat.begin_assistant_message("")
                bubble.append_delta(message.text)
                self._chat.end_assistant_message()
        self.statusBar().showMessage(f"Loaded '{loaded.title}'.")

    def _on_rename_conversation(self, conversation_id: str, title: str) -> None:
        if conversation_id == self._current_conversation.id:
            self._current_conversation = self._current_conversation.renamed(title)
            self._save_current_conversation()
        else:
            path = self._conversations_dir / f"{conversation_id}.json"
            loaded = Conversation.load(path)
            if loaded is not None:
                loaded.renamed(title).save(self._conversations_dir)
        self._reload_sidebar()

    def _on_delete_conversation(self, conversation_id: str) -> None:
        if conversation_id == self._current_conversation.id:
            # Drop the in-memory transcript first so `_on_new_chat`'s save-on-exit does
            # not immediately recreate the file this call is meant to remove.
            self._conversation.clear()
            path = self._conversations_dir / f"{conversation_id}.json"
            path.unlink(missing_ok=True)
            self._on_new_chat()
        else:
            path = self._conversations_dir / f"{conversation_id}.json"
            path.unlink(missing_ok=True)
            self._reload_sidebar()

    def _on_export_conversation(self, conversation_id: str, fmt: str) -> None:
        conversation = self._current_conversation
        if conversation.id != conversation_id:
            path = self._conversations_dir / f"{conversation_id}.json"
            loaded = Conversation.load(path)
            if loaded is None:
                return
            conversation = loaded

        if fmt == "markdown":
            destination, _ = QFileDialog.getSaveFileName(
                self, "Export as Markdown", f"{conversation.title}.md", "Markdown (*.md)"
            )
            if destination:
                Path(destination).write_text(conversation.to_markdown(), encoding="utf-8")
        else:
            destination, _ = QFileDialog.getSaveFileName(
                self, "Export as JSON", f"{conversation.title}.json", "JSON (*.json)"
            )
            if destination:
                Path(destination).write_text(
                    json.dumps(conversation.to_json(), indent=2), encoding="utf-8"
                )

    def _on_export_all(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, strings.EXPORT_ALL)
        if not directory:
            return
        self._save_current_conversation()
        for conversation in Conversation.load_all(self._conversations_dir):
            destination = Path(directory) / f"{conversation.id}.json"
            destination.write_text(json.dumps(conversation.to_json(), indent=2), encoding="utf-8")
        self.statusBar().showMessage(f"Exported conversations to {directory}.")

    def _on_import_conversation(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, strings.IMPORT, "", "JSON (*.json)")
        if not path_str:
            return
        loaded = Conversation.load(Path(path_str))
        if loaded is None:
            self._warn("Import failed", "That file is not a valid conversation export.")
            return
        loaded.save(self._conversations_dir)
        self._reload_sidebar()

    def _save_current_conversation(self) -> None:
        if not self._conversation:
            return
        self._current_conversation = self._current_conversation.with_messages(self._conversation)
        with contextlib.suppress(OSError):
            self._current_conversation.save(self._conversations_dir)

    def _reload_sidebar(self) -> None:
        conversations = Conversation.load_all(self._conversations_dir)
        self._sidebar.set_conversations(conversations, active_id=self._current_conversation.id)

    # ---- theme and persistence -------------------------------------------------------

    def _apply_theme(self, preference: str) -> None:
        """Restyle the whole application and re-render the themed icons."""
        self._theme = preference
        theme.apply_theme(QApplication.instance(), preference)
        self._engine_bar.reapply_theme()
        self._chat.reapply_theme()
        self._welcome.reapply_theme()
        self._composer.reapply_theme()
        self._sidebar.reapply_theme()
        self._provider_refresh_button.setIcon(
            themed_icon(self._provider_refresh_button, "refresh")
        )
        for section in self._inspector_sections.values():
            section.reapply_theme()

    def _set_theme(self, preference: str) -> None:
        """Adopt a theme chosen from the menu (or set programmatically), and remember it."""
        self._apply_theme(preference)
        action = self._theme_actions.get(preference)
        if action is not None:
            action.setChecked(True)
        config = self._with_ui_state(self._engine.config)
        self._engine.update_preferences(config)
        with contextlib.suppress(OSError):
            config.save(self._config_path)

    def _follow_system_scheme(self) -> None:
        """Track the OS appearance live while the preference is 'system'."""
        # instance() is typed as returning the QCoreApplication base (which lacks
        # styleHints), and colorSchemeChanged only exists on Qt 6.5+ — narrow and
        # guard rather than crash at startup.
        app = QApplication.instance()
        hints = app.styleHints() if isinstance(app, QApplication) else None
        if hints is not None and hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)

    def _on_system_scheme_changed(self, _scheme: object) -> None:
        if self._theme == "system":
            self._apply_theme("system")

    def _with_ui_state(self, config: DemoConfig) -> DemoConfig:
        """Fold the bar's selection and the appearance preferences into ``config``."""
        return replace(
            config,
            targets=self._route_targets() or config.targets,
            theme=self._theme,
            context_window_tokens=self._engine_bar.context_window_tokens(),
        )

    def _discover_enabled_providers(self) -> None:
        """Run background model discovery so the dropdowns fill without a manual step."""
        for provider in self._engine.config.enabled_providers():
            self._engine.list_models(provider.instance_id)

    def _schedule_token_hint(self) -> None:
        """(Re)start the debounce timer; the hint refreshes once typing pauses."""
        self._token_hint_timer.start()

    def _refresh_token_hint(self) -> None:
        """Read the composer's token estimate from the public budget calculator."""
        target = self._engine_bar.target()
        if not target:
            self._composer.clear_token_hint()
            return
        try:
            budget = self._engine.budget(
                [*self._conversation, user(self._composer.text() or " ")], target
            )
        except AnyInferError:
            self._composer.clear_token_hint()
            return
        window = budget.context_window
        self._composer.set_token_hint(
            budget.estimate.tokens,
            budget.remaining_tokens,
            budget.fits if window is not None else None,
        )

    # ---- engine callbacks ------------------------------------------------------------

    def _on_attempt_failed(self, record: object) -> None:
        """Report a failed attempt inline, so fallback is visible as it happens."""
        if not isinstance(record, AttemptRecord):
            return
        detail = (
            f"{record.error.type_name}: {record.error.detail}" if record.error else "no detail"
        )
        self._chat.add_notice(f"[{record.outcome}] {record.target} — {detail}", severity="warn")

    def _on_finished(self, result: object) -> None:
        """Render a completed generation across the transcript, metrics, and schema panel."""
        if not isinstance(result, Generation):
            return
        # The bubble opened under the route's primary target; the result knows which
        # target actually answered — after a fallback, they differ.
        self._chat.set_active_target(str(result.target))
        self._chat.end_assistant_message()
        self._status_metrics.set_result(result)
        self._schema.report(result)
        for warning in result.warnings:
            self._chat.add_notice(f"warning: {warning}", severity="warn")
        self._conversation.append(Message(role="assistant", content=(Text(result.text),)))
        self._current_conversation = self._current_conversation.with_result(result)
        self._save_current_conversation()
        self._reload_sidebar()
        self.statusBar().showMessage(
            f"Completed via {result.target} — {self._telemetry.event_count} telemetry events."
        )

    def _on_failed(self, message: str, error: object) -> None:
        """Surface a failure with the library's own hint, which is the actionable part."""
        self._chat.end_assistant_message()
        hint = error.hint if isinstance(error, AnyInferError) else ""
        text = f"Request failed: {message}"
        if hint:
            text += f"\nHint: {hint}"
        self._chat.add_notice(text, severity="error")
        # Drop the user turn that produced no answer, so a retry does not double it up.
        if self._conversation and self._conversation[-1].role == "user":
            self._conversation.pop()
        self.statusBar().showMessage("Request failed — see the transcript and telemetry.")

    def _on_cancelled(self) -> None:
        """Settle the transcript after a cancelled generation."""
        self._chat.end_assistant_message()  # renders any partial text; drops an empty turn
        self._chat.add_notice("Generation cancelled.", severity="warn")
        # Drop the user turn that got no (complete) answer, so a resend does not double it.
        if self._conversation and self._conversation[-1].role == "user":
            self._conversation.pop()
        self.statusBar().showMessage("Generation cancelled.")

    def _on_discovery_failed(self, provider_id: str, message: str, error: object) -> None:
        """Report a background discovery/health failure in the providers panel.

        Deliberately not the transcript: a failed ``models()`` probe is not a failed
        chat request, and must not read as one.
        """
        hint = error.hint if isinstance(error, AnyInferError) else ""
        detail = f"{message}\nHint: {hint}" if hint else message
        self._set_provider_row(provider_id, health="fail", detail=detail)
        self.statusBar().showMessage(f"{provider_id}: discovery failed — {message}")

    def _on_busy_changed(self, busy: bool) -> None:
        """Disable input while a request is in flight."""
        self._composer.set_busy(busy)
        # Switching conversations mid-stream would corrupt the transcript, so the
        # sidebar rests while a request is in flight.
        self._sidebar.setEnabled(not busy)
        if busy:
            self.statusBar().showMessage(f"Streaming from {self._pending_target}…")

    def _on_models_listed(self, provider_id: str, models: object) -> None:
        """Report a provider's discovered models."""
        if not isinstance(models, Sequence):
            return
        ids = ", ".join(m.id for m in models) or "(none reported)"
        self._set_provider_row(provider_id, models=ids)

    def _on_health_checked(self, provider_id: str, health: object) -> None:
        """Report a provider's health probe."""
        if not isinstance(health, Health):
            return
        state = "ok" if health.ok else "fail"
        self._set_provider_row(provider_id, health=state, detail=health.detail)

    def _set_provider_row(
        self, instance_id: str, *, health: str = "", models: str = "", detail: str = ""
    ) -> None:
        row = self._provider_rows.get(instance_id)
        if row is None:
            row = self._provider_table.rowCount()
            self._provider_table.insertRow(row)
            self._provider_table.setItem(row, 0, QTableWidgetItem(instance_id))
            self._provider_table.setItem(row, 1, QTableWidgetItem(self._engine_of(instance_id)))
            self._provider_table.setItem(row, 2, QTableWidgetItem("unknown"))
            self._provider_table.setItem(row, 3, QTableWidgetItem(""))
            self._provider_rows[instance_id] = row
        if health:
            item = QTableWidgetItem({"ok": "✓ ok", "fail": "✕ fail"}.get(health, health))
            if detail:
                item.setToolTip(detail)
            self._provider_table.setItem(row, 2, item)
        if models:
            self._provider_table.setItem(row, 3, QTableWidgetItem(models))

    def _engine_of(self, instance_id: str) -> str:
        """The engine an instance was configured from, for the report's Engine column."""
        for provider in self._engine.config.providers:
            if provider.instance_id == instance_id:
                return provider.provider_id
        return instance_id

    def _warn(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    # ---- shutdown --------------------------------------------------------------------

    def closeEvent(self, event: object) -> None:  # noqa: N802 — Qt's spelling
        """Close the AnyInfer client before the window goes away."""
        self._save_current_conversation()
        self._engine.cancel()
        with contextlib.suppress(AnyInferError):
            self._engine.close()
        super().closeEvent(event)  # type: ignore[arg-type]
