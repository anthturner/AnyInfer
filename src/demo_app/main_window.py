"""The demo's main window: composition, not logic.

Every behaviour on display belongs to AnyInfer; this file only wires widgets to
`Engine` signals. In particular there is no retry loop, no fallback
logic, no schema validation and no timing measurement here — those are the library's job,
and duplicating any of them in an application is the mistake this demo is meant to prevent.

Conversations are tabs. Each tab owns its transcript and state
(`ChatPage`), and the engine's keyed signals route every stream
event to the tab whose conversation started it — several tabs can stream at once without
their transcripts bleeding into each other.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anyinfer import CachePolicy, CostEstimate, HistoryPolicy, Retry, Route
from anyinfer.errors import AnyInferError
from anyinfer.types.capabilities import Health, Sourced
from anyinfer.types.messages import Message, Text, system, user
from anyinfer.types.requests import Repair, Sampling
from anyinfer.types.results import AttemptRecord, Generation

from . import config as config_module
from . import strings, theme
from .config import DemoConfig, ProviderConfig
from .conversation import Conversation, conversations_dir, gist_title
from .engine import Engine, GenerationSpec
from .widgets import (
    AboutDialog,
    AppSettingsDialog,
    CollapsibleSection,
    Composer,
    EngineBar,
    LibraryMapDialog,
    LicensesDialog,
    ModelsDialog,
    ProviderSettingsDialog,
    SchemaPanel,
    SdkHelpButton,
    StatusMetrics,
    TargetInspector,
    TelemetryView,
    ToolsPanel,
    WelcomeView,
)
from .widgets.chat_tabs import ChatPage, ConversationTabs
from .widgets.chat_view import MessageList
from .widgets.collapsible_section import HEADER_HEIGHT
from .widgets.icons import themed_icon
from .widgets.sdk_help import DOCS_URL

__all__ = ["MainWindow"]

_RIGHT_SNAP_WIDTH = 220

#: The width the inspector sidebar reopens to after it is hidden or snapped shut.
_RIGHT_OPEN_WIDTH = 380

_SECTION_ICONS: dict[str, str] = {
    "telemetry": "activity",
    "structured": "braces",
    "providers": "server",
    "target": "target",
    "tools": "tool",
}
"""Inspector section key → Tabler icon used by its header."""

_UNREPORTED_DEFAULT_NOTE = (
    " (Provider default: decided by the provider itself — the value is not reported "
    "to AnyInfer, so it is not invented here.)"
)


def _cost_hint(cost: CostEstimate | None) -> str:
    """Render a preflight cost range, or nothing when there is no pricing to render.

    A *range* rather than a figure, because that is what the library returns: the output
    length is not known before the request, so the low end assumes none of the reserve is
    spent and the high end assumes all of it is. Collapsing that to one number would
    present a bound as a prediction.
    """
    if cost is None:
        return ""
    if cost.low == cost.high:
        return f"~{cost.low:.4f} {cost.currency}"
    return f"~{cost.low:.4f}-{cost.high:.4f} {cost.currency}"


def _make_system_prompt_dialog(parent: QWidget, current: str) -> QInputDialog:
    """Build the wider, edge-wrapping editor used for the configured system prompt."""
    dialog = QInputDialog(parent)
    dialog.setWindowTitle("System prompt")
    dialog.setLabelText("Sent as the first system message in new chats:")
    dialog.setInputMode(QInputDialog.InputMode.TextInput)
    dialog.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput)
    dialog.setTextValue(current)

    editor = dialog.findChild(QPlainTextEdit)
    if editor is not None:
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    dialog.ensurePolished()
    natural = dialog.sizeHint()
    dialog.resize(round(natural.width() * 1.5), natural.height())
    return dialog


class MainWindow(QMainWindow):
    """The demo window."""

    def __init__(self, config: DemoConfig, config_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("AnyInfer Demo")
        self.resize(1280, 860)
        self.setMinimumSize(960, 640)

        self._engine = Engine(config)
        self._models_dialog: ModelsDialog | None = None
        self._theme = config.theme
        # Saves must go back to the file the app was started with (`--config PATH`),
        # not unconditionally to the default location.
        self._config_path = config_path or config_module.CONFIG_PATH
        self._conversations_dir = conversations_dir(self._config_path.parent)

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
        self._open_page(Conversation.new())

    # ---- compatibility views over the active tab ---------------------------------------

    @property
    def _conversation(self) -> list[Message]:
        """The active tab's message list (the same mutable list the tab owns)."""
        page = self._tabs.current_page()
        return page.messages if page is not None else []

    @property
    def _current_conversation(self) -> Conversation:
        """The active tab's conversation record."""
        page = self._tabs.current_page()
        return page.conversation if page is not None else Conversation.new()

    @property
    def _chat(self) -> MessageList:
        """The active tab's transcript view."""
        page = self._tabs.current_page()
        if page is None:
            raise RuntimeError("the window must keep at least one conversation tab")
        return page.view

    # ---- construction ----------------------------------------------------------------

    def _build_ui(self, config: DemoConfig) -> None:
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setHandleWidth(4)
        self._main_splitter.addWidget(self._build_center_pane(config))
        self._main_splitter.addWidget(self._build_inspector())
        self._main_splitter.setStretchFactor(0, 3)
        self._main_splitter.setStretchFactor(1, 2)
        self._main_splitter.setCollapsible(0, False)

        # Dragging the inspector below a usable width snaps it shut. `splitterMoved`
        # fires on user drags only, so programmatic setSizes cannot recurse through here.
        self._main_splitter.splitterMoved.connect(self._on_main_splitter_moved)

        self.setCentralWidget(self._main_splitter)
        self.setStatusBar(QStatusBar())
        self._status_metrics = StatusMetrics()
        self.statusBar().addPermanentWidget(self._status_metrics)
        self.statusBar().showMessage("Ready — offline fake provider, no credentials needed.")

        self._right_sidebar_width_before_hide = _RIGHT_OPEN_WIDTH

    def _build_center_pane(self, config: DemoConfig) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._engine_bar = EngineBar(self._engine.registry, config)
        self._engine_bar.refresh_requested.connect(self._engine.list_models)
        layout.addWidget(self._engine_bar)

        self._tabs = ConversationTabs()
        self._tabs.new_requested.connect(self._on_new_chat)
        self._tabs.open_saved_requested.connect(self._on_open_saved)
        self._tabs.rename_requested.connect(self._on_tab_rename)
        self._tabs.save_requested.connect(self._on_tab_save)
        self._tabs.delete_requested.connect(self._on_tab_delete)
        self._tabs.close_requested.connect(self._on_tab_close)
        self._tabs.close_all_requested.connect(self._on_tab_close_all)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self._tabs, 1)

        self._composer = Composer()
        self._composer.send_requested.connect(self._on_send)
        self._composer.cancel_requested.connect(self._on_cancel_current)
        self._composer.text_changed.connect(self._schedule_token_hint)
        layout.addWidget(self._composer)

        layout.addWidget(self._build_controls())
        return pane

    def _make_welcome(self) -> WelcomeView:
        """A welcome view for one new tab; every empty tab gets its own."""
        welcome = WelcomeView()
        welcome.quick_question_requested.connect(self._on_welcome_quick_question)
        welcome.structured_output_requested.connect(self._on_welcome_structured)
        welcome.fallback_demo_requested.connect(self._on_welcome_fallback)
        welcome.tool_loop_requested.connect(self._on_welcome_tools)
        return welcome

    def _build_controls(self) -> CollapsibleSection:
        content = QWidget()
        grid = QGridLayout(content)
        self._request_options_grid = grid
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        for column in range(3):
            grid.setColumnStretch(column, 1)

        def add_cell(
            row: int,
            column: int,
            label: str,
            control: QWidget,
            *,
            help_topic: str | None = None,
        ) -> None:
            """Add one consistently aligned label/control cell to the three-column grid."""
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(3)

            header = QWidget()
            # Help chips are taller than labels. Giving every header the same height keeps
            # the controls below them on one baseline, including the Session checkbox.
            header.setFixedHeight(22)
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(4)
            header_layout.addWidget(QLabel(label))
            if help_topic is not None:
                header_layout.addWidget(SdkHelpButton(help_topic))
            header_layout.addStretch(1)
            cell_layout.addWidget(header)
            cell_layout.addWidget(control)
            grid.addWidget(cell, row, column)

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setSpecialValueText("provider default")
        self._temperature.setValue(0.0)
        self._temperature.setMinimumWidth(132)
        self._temperature.setAccessibleName("Temperature")
        self._temperature.setToolTip(
            "Sampling temperature. At the minimum the field reads 'provider default' and "
            "is omitted from the wire request entirely — AnyInfer never invents a "
            "temperature." + _UNREPORTED_DEFAULT_NOTE
        )
        self._top_p = QDoubleSpinBox()
        self._top_p.setRange(0.0, 1.0)
        self._top_p.setSingleStep(0.05)
        self._top_p.setSpecialValueText("provider default")
        self._top_p.setValue(0.0)
        self._top_p.setMinimumWidth(132)
        self._top_p.setAccessibleName("Top-p")
        self._top_p.setToolTip(
            "Nucleus-sampling cutoff. At the minimum the value is omitted from the wire "
            "request, so the provider's default is used." + _UNREPORTED_DEFAULT_NOTE
        )
        self._max_output_tokens = QSpinBox()
        self._max_output_tokens.setRange(0, 65_536)
        self._max_output_tokens.setSingleStep(1)
        self._max_output_tokens.setSpecialValueText("provider default")
        self._max_output_tokens.setValue(0)
        self._max_output_tokens.setMinimumWidth(132)
        self._max_output_tokens.setAccessibleName("Max output tokens")
        self._reasoning = QComboBox()
        # The blank entry is "say nothing", not "minimal": a request that omits the field
        # lets each provider apply its own default, and the normalized levels below are
        # translated per provider by its descriptor rather than sent verbatim.
        self._reasoning.addItem("provider default", "")
        for level in ("minimal", "low", "medium", "high"):
            self._reasoning.addItem(level, level)
        self._reasoning.setAccessibleName("Reasoning effort")
        self._reasoning.setToolTip(
            "Normalized reasoning effort. Each provider's descriptor translates it into "
            "that provider's own spelling; a provider without the control drops it and "
            "reports the drop as telemetry rather than failing." + _UNREPORTED_DEFAULT_NOTE
        )
        self._max_attempts = QSpinBox()
        self._max_attempts.setRange(1, 5)
        self._max_attempts.setValue(2)
        self._max_attempts.setMinimumWidth(96)
        self._max_attempts.setAccessibleName("Max attempts per target")
        self._max_attempts.setToolTip("Retry budget per target, before falling back.")
        self._fallback = QComboBox()
        self._fallback.addItem("Nothing (no fallback)", "")
        self._fallback.setAccessibleName("Fallback target")
        self._fallback.setToolTip(
            "Optional fallback target the router moves to once the retry budget is spent. "
            "Pick the flaky demo model above with 1 attempt to watch it happen."
        )
        self._history = QComboBox()
        self._history.addItem("Send everything (default)", "")
        self._history.addItem("Trim only when it will not fit", "last_resort")
        self._history.addItem("Trim proactively", "proactive")
        self._history.setAccessibleName("History policy")
        self._history.setToolTip(
            "Opt-in conversation compaction, applied by the client on the request path. "
            "Off by default — with no policy the full transcript is sent untouched. "
            "Trimming is never silent: it emits a ContextReduced telemetry event."
        )
        self._cache = QComboBox()
        self._cache.addItem("Off (default)", "")
        self._cache.addItem("Auto placement", "auto")
        self._cache.addItem("Explicit marks", "explicit")
        self._cache.setAccessibleName("Prompt cache policy")
        self._cache.setToolTip(
            "Opt-in prompt-cache placement. Caching changes what a provider bills and how "
            "long it retains the prompt, so no policy means cached exactly as before: not "
            "at all. The plan — mechanism and marks — arrives as a CachePlanned event."
        )
        self._reuse_session = QCheckBox("Reuse session")
        self._reuse_session.setAccessibleName("Reuse provider session")
        self._reuse_session.setToolTip(
            "Thread turns through one provider-side session, so a provider that keeps "
            "conversations can resume instead of re-reading the whole transcript. The "
            "status line reports what actually happened: resumed, fresh, or unsupported "
            "— the provider decides, never the client."
        )
        self._sync_request_control_heights()
        add_cell(0, 0, "Temperature", self._temperature)
        add_cell(0, 1, "Top-p", self._top_p)
        add_cell(0, 2, "Max tokens", self._max_output_tokens)
        add_cell(1, 0, "Reasoning", self._reasoning)
        add_cell(1, 1, "Attempts", self._max_attempts)
        add_cell(1, 2, "Fallback", self._fallback, help_topic="routing")
        add_cell(2, 0, "History", self._history, help_topic="history")
        add_cell(2, 1, "Prompt cache", self._cache, help_topic="prompt-cache")
        add_cell(2, 2, "Session", self._reuse_session)

        saved = self._engine.config.targets
        if len(saved) > 1:
            self._fallback.addItem(saved[1], saved[1])
            self._fallback.setCurrentIndex(1)
        self._engine_bar.changed.connect(self._update_fallback_choices)
        self._engine_bar.changed.connect(self._refresh_token_hint)
        self._engine_bar.changed.connect(self._refresh_default_hints)
        self._engine_bar.changed.connect(self._update_send_availability)
        self._refresh_default_hints()
        self._update_send_availability()

        section = CollapsibleSection(
            "Request options — sampling & routing",
            content,
        )
        section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        section.set_minimized(True)
        self._request_options_section = section
        return section

    def _sync_request_control_heights(self) -> None:
        """Keep the checkbox cell level with adjacent controls after style changes."""
        self._reuse_session.setMinimumHeight(
            max(self._history.sizeHint().height(), self._cache.sizeHint().height())
        )

    def _build_inspector(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("InspectorPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._inspector_splitter = QSplitter(Qt.Orientation.Vertical)
        self._inspector_splitter.setHandleWidth(4)

        self._telemetry = TelemetryView()
        self._telemetry_section = CollapsibleSection(
            strings.TELEMETRY_TITLE,
            self._telemetry,
            help_topic="telemetry",
            icon=_SECTION_ICONS["telemetry"],
        )
        self._inspector_splitter.addWidget(self._telemetry_section)

        self._schema = SchemaPanel()
        self._schema_section = CollapsibleSection(
            strings.STRUCTURED_TITLE,
            self._schema,
            help_topic="structured",
            icon=_SECTION_ICONS["structured"],
        )
        self._inspector_splitter.addWidget(self._schema_section)

        self._providers_section = CollapsibleSection(
            strings.PROVIDERS_TITLE,
            self._build_providers_tab(),
            help_topic="providers",
            icon=_SECTION_ICONS["providers"],
        )
        self._inspector_splitter.addWidget(self._providers_section)

        self._target_inspector = TargetInspector(self._engine)
        self._target_section = CollapsibleSection(
            strings.TARGET_TITLE,
            self._target_inspector,
            help_topic="target-inspection",
            icon=_SECTION_ICONS["target"],
        )
        self._target_section.set_minimized(True)
        self._inspector_splitter.addWidget(self._target_section)

        self._tools = ToolsPanel(self._engine)
        self._tools_section = CollapsibleSection(
            strings.TOOLS_TITLE,
            self._tools,
            help_topic="tools",
            icon=_SECTION_ICONS["tools"],
        )
        self._tools_section.set_minimized(True)
        self._inspector_splitter.addWidget(self._tools_section)

        self._inspector_sections: dict[str, CollapsibleSection] = {
            "telemetry": self._telemetry_section,
            "structured": self._schema_section,
            "providers": self._providers_section,
            "target": self._target_section,
            "tools": self._tools_section,
        }
        # A splitter distributes surplus height between its handles when every visible
        # child is fixed at its collapsed height. This invisible final child absorbs that
        # surplus instead, keeping a stack of collapsed headers anchored to the top.
        self._inspector_bottom_spacer = QWidget()
        self._inspector_bottom_spacer.setObjectName("InspectorBottomSpacer")
        self._inspector_bottom_spacer.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self._inspector_splitter.addWidget(self._inspector_bottom_spacer)
        self._inspector_splitter.setStretchFactor(len(self._inspector_sections), 1)
        self._inspector_bottom_spacer.hide()
        for section in self._inspector_sections.values():
            section.minimized_changed.connect(self._sync_inspector_bottom_spacer)

        self._inspector_splitter.setSizes([280, 280, 220, HEADER_HEIGHT, HEADER_HEIGHT, 0])
        layout.addWidget(self._inspector_splitter, 1)

        # Both panels act on whatever engine/model the bar currently points at.
        self._engine_bar.changed.connect(self._sync_inspector_targets)
        self._sync_inspector_targets()
        return pane

    def _sync_inspector_targets(self) -> None:
        """Point the target inspector and tools panel at the bar's current selection."""
        target = self._engine_bar.target()
        self._target_inspector.set_target(target)
        self._tools.set_target(target)

    def _sync_inspector_bottom_spacer(self, *_args: object) -> None:
        """Put surplus splitter height below an entirely collapsed visible stack."""
        visible_sections = [
            section for section in self._inspector_sections.values() if not section.isHidden()
        ]
        anchor_to_top = bool(visible_sections) and all(
            section.minimized for section in visible_sections
        )
        self._inspector_bottom_spacer.setVisible(anchor_to_top)
        if not anchor_to_top:
            return

        handle_count = len(visible_sections)
        used_height = len(visible_sections) * HEADER_HEIGHT
        remaining = max(
            0,
            self._inspector_splitter.height()
            - used_height
            - handle_count * self._inspector_splitter.handleWidth(),
        )
        sizes = [
            HEADER_HEIGHT if section in visible_sections else 0
            for section in self._inspector_sections.values()
        ]
        self._inspector_splitter.setSizes([*sizes, remaining])

    def _build_providers_tab(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        caption = QLabel(
            "Discovery and health probes go through the same adapter contract for every "
            "provider: <code>list_models()</code> and <code>health()</code>."
        )
        caption.setObjectName("Caption")
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
        self._provider_table.setHorizontalHeaderLabels(["Alias", "Engine", "Health", "Models"])
        self._provider_table.setAccessibleName("Provider report")
        self._provider_table.horizontalHeader().setStretchLastSection(True)
        self._provider_table.verticalHeader().setVisible(False)
        self._provider_table.setEditTriggers(self._provider_table.EditTrigger.NoEditTriggers)
        layout.addWidget(self._provider_table, 1)
        self._provider_rows: dict[str, int] = {}
        return pane

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        app_settings_action = QAction("App &settings…", self)
        app_settings_action.setShortcut(QKeySequence("Ctrl+,"))
        app_settings_action.triggered.connect(self._on_app_settings)
        file_menu.addAction(app_settings_action)

        settings_action = QAction("Provider &settings…", self)
        settings_action.triggered.connect(self._on_configure)
        file_menu.addAction(settings_action)

        new_chat_action = QAction("&New chat", self)
        new_chat_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        new_chat_action.triggered.connect(self._on_new_chat)
        file_menu.addAction(new_chat_action)

        open_saved_action = QAction(strings.OPEN_SAVED, self)
        open_saved_action.setShortcut(QKeySequence.StandardKey.Open)
        open_saved_action.triggered.connect(self._on_open_saved)
        file_menu.addAction(open_saved_action)

        system_prompt_action = QAction("System &prompt…", self)
        system_prompt_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        system_prompt_action.triggered.connect(self._on_system_prompt)
        file_menu.addAction(system_prompt_action)

        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        tools_menu = self.menuBar().addMenu("&Tools")
        models_action = QAction(strings.LOCAL_INFERENCE, self)
        models_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
        models_action.triggered.connect(self._on_local_models)
        tools_menu.addAction(models_action)

        self._build_sidebar_menu()

        self._build_help_menu()

        send_action = QAction("Send", self)
        send_action.setShortcut(QKeySequence("Ctrl+Return"))
        send_action.triggered.connect(self._on_send)
        self.addAction(send_action)

    def _build_help_menu(self) -> None:
        help_menu = self.menuBar().addMenu("&Help")

        map_action = QAction("&Library map — what this demo exercises…", self)
        map_action.setShortcut(QKeySequence.StandardKey.HelpContents)
        map_action.setIcon(themed_icon(self, "map", size=16))
        map_action.triggered.connect(self._on_library_map)
        help_menu.addAction(map_action)

        docs_action = QAction("&Documentation", self)
        docs_action.setIcon(themed_icon(self, "book", size=16))
        docs_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(DOCS_URL)))
        help_menu.addAction(docs_action)

        reference_action = QAction("SDK &Reference", self)
        reference_action.setIcon(themed_icon(self, "book", size=16))
        reference_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(f"{DOCS_URL}reference/"))
        )
        help_menu.addAction(reference_action)

        help_menu.addSeparator()
        licenses_action = QAction("&Third-party licenses…", self)
        licenses_action.setIcon(themed_icon(self, "license", size=16))
        licenses_action.triggered.connect(self._on_licenses)
        help_menu.addAction(licenses_action)

        help_menu.addSeparator()
        about_action = QAction("&About…", self)
        about_action.setIcon(themed_icon(self, "info", size=16))
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

        # Kept so a theme change can re-tint the menu icons.
        self._help_menu_actions = {
            "map": map_action,
            "book": docs_action,
            "book2": reference_action,
            "license": licenses_action,
            "info": about_action,
        }

    def _build_sidebar_menu(self) -> None:
        """Build the top-level Sidebar menu and its visibility checkboxes."""
        self._sidebar_menu = self.menuBar().addMenu(f"&{strings.SIDEBAR}")

        self._right_sidebar_action = QAction(strings.SHOW_SIDEBAR, self, checkable=True)
        self._right_sidebar_action.setChecked(True)
        self._right_sidebar_action.triggered.connect(self._set_right_sidebar_visible)
        self._sidebar_menu.addAction(self._right_sidebar_action)
        self._sidebar_menu.addSeparator()

        self._section_actions: dict[str, QAction] = {}
        section_labels = (
            ("telemetry", strings.SHOW_TELEMETRY),
            ("structured", strings.SHOW_STRUCTURED),
            ("providers", strings.SHOW_PROVIDERS),
            ("target", strings.SHOW_TARGET),
            ("tools", strings.SHOW_TOOLS),
        )
        for key, label in section_labels:
            action = QAction(label, self, checkable=True)
            action.setChecked(True)
            action.triggered.connect(
                lambda checked, k=key: self._set_inspector_section_visible(k, checked)
            )
            self._sidebar_menu.addAction(action)
            self._section_actions[key] = action

    def _build_shortcuts(self) -> None:
        cancel_action = QAction("Cancel generation", self)
        cancel_action.setShortcut(QKeySequence("Esc"))
        cancel_action.triggered.connect(self._on_cancel_current)
        self.addAction(cancel_action)

        settings_action = QAction("Open settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        settings_action.triggered.connect(self._on_configure)
        self.addAction(settings_action)

        toggle_action = QAction("Toggle sidebar", self)
        toggle_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        toggle_action.triggered.connect(self._toggle_right_sidebar)
        self.addAction(toggle_action)

        self.setTabOrder(self._engine_bar, self._tabs)
        self.setTabOrder(self._tabs, self._composer)

    def _connect_engine(self) -> None:
        # Generation events arrive keyed by conversation id and are routed to the tab
        # that started them — the unkeyed signals still exist for single-stream callers.
        self._engine.gen_text_delta.connect(self._on_gen_text_delta)
        self._engine.gen_reasoning_delta.connect(self._on_gen_reasoning_delta)
        self._engine.gen_first_token.connect(self._on_gen_first_token)
        self._engine.gen_usage_update.connect(self._on_gen_usage_update)
        self._engine.gen_attempt_failed.connect(self._on_gen_attempt_failed)
        self._engine.gen_finished.connect(self._on_gen_finished)
        self._engine.gen_failed.connect(self._on_gen_failed)
        self._engine.gen_cancelled.connect(self._on_gen_cancelled)
        self._engine.gen_busy_changed.connect(self._on_gen_busy_changed)
        self._engine.telemetry.connect(self._telemetry.add_event)
        self._engine.models_listed.connect(self._on_models_listed)
        self._engine.models_listed.connect(self._engine_bar.on_models_listed)
        self._engine.health_checked.connect(self._on_health_checked)
        self._engine.discovery_failed.connect(self._on_discovery_failed)

    # ---- tabs --------------------------------------------------------------------------

    def _open_page(self, conversation: Conversation, *, focus: bool = True) -> ChatPage:
        """Open a conversation in a new tab, replaying any saved transcript."""
        page = ChatPage(conversation)
        welcome = self._make_welcome()
        page.view.set_empty_state(welcome)
        for message in conversation.messages:
            if message.role == "user":
                page.view.add_user_message(message.text)
            elif message.role == "assistant":
                bubble = page.view.begin_assistant_message("")
                bubble.append_delta(message.text)
                page.view.end_assistant_message()
        index = self._tabs.add_page(page, conversation.title)
        if focus:
            self._tabs.setCurrentIndex(index)
        return page

    def _page_for(self, key: str) -> ChatPage | None:
        index = self._tabs.index_of_key(key)
        return self._tabs.page_at(index) if index >= 0 else None

    def _on_tab_changed(self, _index: int) -> None:
        """Follow the active tab: the composer mirrors *its* busy state, not a global."""
        page = self._tabs.current_page()
        if page is None:
            return
        self._composer.set_busy(self._engine.busy_for(page.key))
        self._refresh_token_hint()

    def _on_cancel_current(self) -> None:
        page = self._tabs.current_page()
        if page is not None:
            self._engine.cancel(page.key)

    def _on_tab_rename(self, index: int) -> None:
        page = self._tabs.page_at(index)
        if page is None:
            return
        title, ok = QInputDialog.getText(
            self, strings.RENAME, "Title:", text=page.conversation.title
        )
        if ok and title.strip():
            self._rename_page(page, title.strip())

    def _rename_page(self, page: ChatPage, title: str) -> None:
        page.conversation = page.conversation.renamed(title)
        index = self._tabs.indexOf(page)
        if index >= 0:
            self._tabs.set_title(index, title)
        self._save_page(page)

    def _on_tab_save(self, index: int, fmt: str) -> None:
        page = self._tabs.page_at(index)
        if page is None:
            return
        self._save_page(page)
        self._save_page_as(page, fmt)

    def _on_tab_delete(self, index: int) -> None:
        page = self._tabs.page_at(index)
        if page is None:
            return
        self._engine.cancel(page.key)
        page.messages.clear()  # closing this page must not recreate the deleted save
        self._tabs.removeTab(index)
        page.deleteLater()
        (self._conversations_dir / f"{page.conversation.id}.json").unlink(missing_ok=True)
        if self._tabs.count() == 0:
            self._open_page(Conversation.new())

    def _on_tab_close(self, index: int) -> None:
        """Close one tab, keeping its conversation on disk for Open Saved."""
        page = self._tabs.page_at(index)
        if page is None:
            return
        self._engine.cancel(page.key)
        self._save_page(page)
        self._tabs.removeTab(index)
        page.deleteLater()
        if self._tabs.count() == 0:
            self._open_page(Conversation.new())

    def _on_tab_close_all(self) -> None:
        """Close every tab (conversations stay saved) and start one fresh."""
        for page in self._tabs.pages():
            self._engine.cancel(page.key)
            self._save_page(page)
        while self._tabs.count():
            widget = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        self._open_page(Conversation.new())

    # ---- actions ---------------------------------------------------------------------

    def _on_send(self) -> None:
        """Collect the UI state into a request and hand it to the engine."""
        page = self._tabs.current_page()
        if page is None or self._engine.busy_for(page.key):
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

        if not page.messages and self._engine.config.system_prompt:
            page.messages.append(system(self._engine.config.system_prompt))
        first_user_turn = not any(m.role == "user" for m in page.messages)
        page.messages.append(user(prompt))
        if first_user_turn and page.conversation.title == "New chat":
            # Title at send time so the tab immediately reads as the topic.
            title = gist_title(prompt)
            page.conversation = page.conversation.renamed(title)
            index = self._tabs.indexOf(page)
            if index >= 0:
                self._tabs.set_title(index, title)

        self._composer.clear()
        page.view.add_user_message(prompt)
        page.view.show_typing()
        self._status_metrics.reset()
        page.pending_target = targets[0]
        page.streaming_started = False

        spec = GenerationSpec(
            messages=tuple(page.messages),
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
            reasoning=self._reasoning.currentData() or None,
            use_session=self._reuse_session.isChecked(),
            history=self._history_policy(),
            cache=self._cache_policy(),
        )
        self._engine.generate(spec, page.key)

    def _history_policy(self) -> HistoryPolicy | None:
        """The selected compaction policy, or ``None`` for the untouched default."""
        mode = self._history.currentData()
        if mode not in ("last_resort", "proactive"):
            return None
        return HistoryPolicy(mode=mode)

    def _cache_policy(self) -> CachePolicy | None:
        """The selected prompt-cache policy, or ``None`` to cache nothing."""
        mode = self._cache.currentData()
        if mode not in ("auto", "explicit"):
            return None
        return CachePolicy(mode=mode)

    def _build_sampling(self) -> Sampling:
        """Read sampling knobs, leaving unset ones genuinely unset."""
        temperature = self._temperature.value()
        top_p = self._top_p.value()
        max_output_tokens = self._max_output_tokens.value()
        return Sampling(
            temperature=None if temperature == 0.0 else temperature,
            top_p=None if top_p == 0.0 else top_p,
            max_output_tokens=max_output_tokens if max_output_tokens > 0 else None,
        )

    def _route_targets(self) -> tuple[str, ...]:
        """The routing chain: the picked engine/model, then the optional fallback."""
        primary = self._engine_bar.target()
        if not primary:
            return ()
        fallback = self._fallback.currentData()
        if isinstance(fallback, str) and fallback and fallback != primary:
            return (primary, fallback)
        return (primary,)

    def _update_send_availability(self) -> None:
        """Keep Send unavailable until both an engine and a model are selected."""
        self._composer.set_send_enabled(bool(self._engine_bar.target()))

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

    def _refresh_default_hints(self) -> None:
        """Show the values the SDK actually has on file for 'provider default' fields.

        Three fields, one rule: show the number when the library has one on file, and say
        plainly that it does not when it does not. Sampling defaults are known only for a
        provider whose own documentation states them, so most selections still land on the
        unreported note, which is the point, not a shortfall.
        """
        detected = self._engine_bar.max_output_tokens_detected()
        base = (
            "Upper bound on tokens the model may generate. Zero omits the field from "
            "the wire request."
        )
        if detected is None:
            self._max_output_tokens.setSpecialValueText("provider default")
            self._max_output_tokens.setToolTip(base + _UNREPORTED_DEFAULT_NOTE)
        else:
            self._max_output_tokens.setSpecialValueText(f"provider default ({detected.value:,})")
            self._max_output_tokens.setToolTip(
                f"{base} (Provider default: {detected.value:,} tokens — {detected.provenance}.)"
            )

        self._apply_sampling_hint(
            self._temperature,
            self._engine_bar.default_temperature_detected(),
            "Sampling temperature. At the minimum the field reads 'provider default' and "
            "is omitted from the wire request entirely — AnyInfer never invents a "
            "temperature.",
        )
        self._apply_sampling_hint(
            self._top_p,
            self._engine_bar.default_top_p_detected(),
            "Nucleus-sampling cutoff. At the minimum the value is omitted from the wire "
            "request, so the provider's default is used.",
        )

    @staticmethod
    def _apply_sampling_hint(
        spin: QDoubleSpinBox, detected: Sourced[float] | None, base: str
    ) -> None:
        """Name the provider's documented default, or say it was never reported."""
        if detected is None:
            spin.setSpecialValueText("provider default")
            spin.setToolTip(base + _UNREPORTED_DEFAULT_NOTE)
            return
        spin.setSpecialValueText(f"provider default ({detected.value:g})")
        spin.setToolTip(f"{base} (Provider default: {detected.value:g} — {detected.provenance}.)")

    def _on_configure(self) -> None:
        if self._engine.busy:
            # Applying settings tears down the client, which would kill every in-flight
            # stream mid-answer; make the user settle the generations first.
            self.statusBar().showMessage("Finish or cancel the running generations first.")
            return
        dialog = ProviderSettingsDialog(self._engine.registry, self._engine.config, self)
        if dialog.exec() != ProviderSettingsDialog.DialogCode.Accepted:
            return
        self._apply_provider_config(
            dialog.result_config(),
            "Settings saved; the client will rebuild on next use.",
        )

    def _on_app_settings(self) -> None:
        """Edit and persist preferences that apply beyond one provider instance."""
        dialog = AppSettingsDialog(self._engine.config, self)
        if dialog.exec() != AppSettingsDialog.DialogCode.Accepted:
            return
        self._apply_app_settings(dialog.result_config())

    def _apply_app_settings(self, edited: DemoConfig) -> None:
        """Apply and persist the result of the application-settings dialog."""
        self._apply_theme(edited.theme)
        config = self._with_ui_state(edited)
        self._engine.update_preferences(config)
        if self._models_dialog is not None:
            self._models_dialog.set_providers(config)
        try:
            config.save(self._config_path)
        except OSError as error:
            self.statusBar().showMessage(f"App settings applied but not saved: {error}")
            return
        self.statusBar().showMessage("App settings saved.")

    def _apply_provider_config(self, config: DemoConfig, success_message: str) -> None:
        """Apply and persist provider settings from either configuration surface."""
        config = self._with_ui_state(config)
        self._engine.apply_config(config)
        self._engine_bar.set_providers(config)
        if self._models_dialog is not None:
            # Catalog acquisition and engine pull both depend on the configured engines;
            # a settings change can add or remove one while the dialog is open.
            self._models_dialog.set_providers(config)
        self._discover_enabled_providers()
        try:
            config.save(self._config_path)
        except OSError as error:
            message = f"Settings applied but not saved: {error}"
            self.statusBar().showMessage(message)
            if self._models_dialog is not None:
                self._models_dialog.show_status(message)
            return
        self.statusBar().showMessage(success_message)
        if self._models_dialog is not None:
            self._models_dialog.show_status(success_message)

    def _on_quick_add_llama_cpp(self) -> None:
        """Enable a default llama.cpp instance from the Local Inference catalog."""
        if self._engine.busy:
            message = "Finish or cancel the running generations before adding llama.cpp."
            self.statusBar().showMessage(message)
            if self._models_dialog is not None:
                self._models_dialog.show_status(message)
            return
        config = self._engine.config.with_provider(
            ProviderConfig(provider_id="llama-cpp", enabled=True)
        )
        self._apply_provider_config(config, "llama.cpp added with default settings.")

    def _on_system_prompt(self) -> None:
        """Edit the system prompt stored in the demo config."""
        dialog = _make_system_prompt_dialog(self, self._engine.config.system_prompt)
        if dialog.exec() != QInputDialog.DialogCode.Accepted:
            return
        config = replace(self._engine.config, system_prompt=dialog.textValue())
        self._engine.update_preferences(config)
        with contextlib.suppress(OSError):
            config.save(self._config_path)
        self.statusBar().showMessage("System prompt updated.")

    def _on_library_map(self) -> None:
        """Open the live map of which public SDK symbols this demo exercises."""
        dialog = LibraryMapDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def _on_licenses(self) -> None:
        dialog = LicensesDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def _on_about(self) -> None:
        AboutDialog(self).exec()

    def _on_local_models(self) -> None:
        """Open (or focus) the local-inference manager."""
        if self._models_dialog is not None and self._models_dialog.isVisible():
            self._models_dialog.raise_()
            self._models_dialog.activateWindow()
            return
        self._models_dialog = ModelsDialog(
            self._engine,
            self._engine.config,
            self,
            initial_target=self._engine_bar.target(),
        )
        self._models_dialog.quick_llama_setup_requested.connect(self._on_quick_add_llama_cpp)
        self._models_dialog.runtime_selection_requested.connect(self._on_runtime_selected)
        self._models_dialog.show()

    def _on_runtime_selected(self, runtime: str) -> None:
        """Persist one default runtime across the demo's llama.cpp instances."""
        providers = []
        changed = False
        for provider in self._engine.config.providers:
            if provider.provider_id != "llama-cpp":
                providers.append(provider)
                continue
            options = dict(provider.options)
            options["runtime"] = runtime
            providers.append(replace(provider, options=options))
            changed = True
        if not changed:
            return
        self._apply_provider_config(
            self._engine.config.with_providers(providers),
            f"llama.cpp will use {runtime} for future server starts.",
        )

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

    # ---- sidebar: visibility and snapping ----------------------------------------------

    def _on_main_splitter_moved(self, _pos: int, _index: int) -> None:
        """Snap the inspector shut below a usable width."""
        sizes = self._main_splitter.sizes()
        if len(sizes) < 2:
            return
        width = sizes[1]
        if 0 < width < _RIGHT_SNAP_WIDTH:
            total = sum(sizes)
            self._main_splitter.setSizes([total, 0])
            self._right_sidebar_action.setChecked(False)
        elif width >= _RIGHT_SNAP_WIDTH:
            self._right_sidebar_width_before_hide = width
            self._right_sidebar_action.setChecked(True)

    def _set_right_sidebar_visible(self, visible: bool) -> None:
        """Collapse or restore the inspector pane while keeping it resizable."""
        splitter = self._main_splitter
        sizes = splitter.sizes()
        if visible:
            total = sum(sizes) if sizes else 1
            restored = max(self._right_sidebar_width_before_hide, _RIGHT_SNAP_WIDTH)
            left = max(total - restored, int(total * 0.55))
            splitter.setSizes([left, total - left])
        else:
            if len(sizes) >= 2 and sizes[1] > 0:
                self._right_sidebar_width_before_hide = max(sizes[1], _RIGHT_SNAP_WIDTH)
            total = sum(sizes) if sizes else 1
            splitter.setSizes([total, 0])
        self._right_sidebar_action.setChecked(visible)

    def _toggle_right_sidebar(self) -> None:
        sizes = self._main_splitter.sizes()
        collapsed = len(sizes) < 2 or sizes[1] == 0
        self._set_right_sidebar_visible(collapsed)

    def _set_inspector_section_visible(self, key: str, visible: bool) -> None:
        """Show or fully hide one inspector section (distinct from minimize)."""
        self._inspector_sections[key].setVisible(visible)
        self._sync_inspector_bottom_spacer()

    # ---- welcome / quick actions -------------------------------------------------------

    def _on_welcome_quick_question(self, question: str) -> None:
        """Pre-fill and immediately send a random trivia question."""
        self._composer.set_text(question)
        self._on_send()

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

    def _on_welcome_tools(self) -> None:
        """Aim the tool-loop panel at the offline tools model and bring it into view."""
        self._engine_bar.set_target("demo-fake:tools")
        self._sync_inspector_targets()
        self._set_right_sidebar_visible(True)
        self._set_inspector_section_visible("tools", True)
        self._tools_section.set_minimized(False)
        self.statusBar().showMessage(
            "Tool loop ready — press 'Run tool loop' in the right sidebar."
        )

    # ---- conversation persistence ------------------------------------------------------

    def _on_new_chat(self) -> None:
        """Open a fresh conversation in a new tab; nothing else is interrupted."""
        self._open_page(Conversation.new())
        self.statusBar().showMessage("New chat.")

    def _on_open_saved(self) -> None:
        """Choose a saved conversation JSON file and open it as a tab."""
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            strings.OPEN_SAVED,
            str(self._conversations_dir),
            "AnyInfer conversations (*.json)",
        )
        if not path_str:
            return
        loaded = Conversation.load(Path(path_str))
        if loaded is None:
            self._warn("Open failed", "That file is not a valid saved conversation.")
            return
        existing = self._tabs.index_of_key(loaded.id)
        if existing >= 0:
            self._tabs.setCurrentIndex(existing)
        else:
            self._open_page(loaded)
        self.statusBar().showMessage(f"Opened '{loaded.title}'.")

    def _save_page_as(self, page: ChatPage, fmt: str) -> None:
        """Save one tab as a portable Markdown or JSON file chosen by the user."""
        conversation = page.conversation.with_messages(page.messages)

        if fmt == "markdown":
            destination, _ = QFileDialog.getSaveFileName(
                self, "Save as Markdown", f"{conversation.title}.md", "Markdown (*.md)"
            )
            if destination:
                Path(destination).write_text(conversation.to_markdown(), encoding="utf-8")
        else:
            destination, _ = QFileDialog.getSaveFileName(
                self, "Save as JSON", f"{conversation.title}.json", "JSON (*.json)"
            )
            if destination:
                Path(destination).write_text(
                    json.dumps(conversation.to_json(), indent=2), encoding="utf-8"
                )

    def _save_page(self, page: ChatPage) -> None:
        if not page.messages:
            return
        page.conversation = page.conversation.with_messages(page.messages)
        with contextlib.suppress(OSError):
            page.conversation.save(self._conversations_dir)

    def _save_all_pages(self) -> None:
        for page in self._tabs.pages():
            self._save_page(page)

    # ---- theme and persistence -------------------------------------------------------

    def _apply_theme(self, preference: str) -> None:
        """Restyle the whole application and re-render the themed icons."""
        self._theme = preference
        theme.apply_theme(QApplication.instance(), preference)
        self._sync_request_control_heights()
        self._engine_bar.reapply_theme()
        self._tabs.reapply_theme()
        for page in self._tabs.pages():
            page.view.reapply_theme()
            empty = page.view.empty_state()
            if isinstance(empty, WelcomeView):
                empty.reapply_theme()
        self._composer.reapply_theme()
        self._telemetry.reapply_theme()
        self._provider_refresh_button.setIcon(
            themed_icon(self._provider_refresh_button, "refresh")
        )
        for section in self._inspector_sections.values():
            section.reapply_theme()
        for name, action in self._help_menu_actions.items():
            icon_name = {
                "map": "map",
                "book": "book",
                "book2": "book",
                "license": "license",
                "info": "info",
            }[name]
            action.setIcon(themed_icon(self, icon_name, size=16))

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
        page = self._tabs.current_page()
        if not target or page is None:
            self._composer.clear_token_hint()
            return
        try:
            budget = self._engine.budget(
                [*page.messages, user(self._composer.text() or " ")], target
            )
        except AnyInferError:
            self._composer.clear_token_hint()
            return
        window = budget.context_window
        self._composer.set_token_hint(
            budget.estimate.tokens,
            budget.remaining_tokens,
            budget.fits if window is not None else None,
            _cost_hint(budget.estimated_cost),
        )

    # ---- engine callbacks ------------------------------------------------------------

    def _on_gen_text_delta(self, key: str, text: str) -> None:
        page = self._page_for(key)
        if page is None:
            return
        if not page.streaming_started:
            page.streaming_started = True
            page.view.begin_assistant_message(page.pending_target)
        page.view.append_delta(text)

    def _on_gen_reasoning_delta(self, key: str, text: str) -> None:
        page = self._page_for(key)
        if page is None:
            return
        if not page.streaming_started:
            page.streaming_started = True
            page.view.begin_assistant_message(page.pending_target)
        page.view.append_reasoning(text)

    def _on_gen_first_token(self, key: str, at_ms: float) -> None:
        if self._is_current(key):
            self._status_metrics.set_first_token(at_ms)

    def _on_gen_usage_update(self, key: str, usage: object) -> None:
        if self._is_current(key):
            self._status_metrics.set_usage(usage)

    def _is_current(self, key: str) -> bool:
        page = self._tabs.current_page()
        return page is not None and page.key == key

    def _on_gen_attempt_failed(self, key: str, record: object) -> None:
        """Report a failed attempt inline, so fallback is visible as it happens."""
        page = self._page_for(key)
        if page is None or not isinstance(record, AttemptRecord):
            return
        detail = (
            f"{record.error.type_name}: {record.error.detail}" if record.error else "no detail"
        )
        page.view.add_notice(f"[{record.outcome}] {record.target} — {detail}", severity="warn")

    def _on_gen_finished(self, key: str, result: object) -> None:
        """Render a completed generation across the transcript, metrics, and schema panel."""
        page = self._page_for(key)
        if page is None or not isinstance(result, Generation):
            return
        # The bubble opened under the route's primary target; the result knows which
        # target actually answered — after a fallback, they differ.
        page.view.set_active_target(str(result.target))
        page.view.end_assistant_message()
        if self._is_current(key):
            self._status_metrics.set_result(result)
        self._schema.report(result)
        for warning in result.warnings:
            page.view.add_notice(f"warning: {warning}", severity="warn")
        page.messages.append(Message(role="assistant", content=(Text(result.text),)))
        page.conversation = page.conversation.with_result(result)
        self._save_page(page)
        # What the provider actually did with the session — resumed, fresh, or
        # unsupported — is the library's answer, and the honest thing is to show it.
        reuse = self._engine.session_reuse if self._reuse_session.isChecked() else ""
        session_note = f" — session {reuse}" if reuse else ""
        self.statusBar().showMessage(
            f"Completed via {result.target} — "
            f"{self._telemetry.event_count} telemetry events{session_note}."
        )

    def _on_gen_failed(self, key: str, message: str, error: object) -> None:
        """Surface a failure with the library's own hint, which is the actionable part."""
        page = self._page_for(key)
        if page is None:
            return
        page.view.end_assistant_message()
        hint = error.hint if isinstance(error, AnyInferError) else ""
        text = f"Request failed: {message}"
        if hint:
            text += f"\nHint: {hint}"
        page.view.add_notice(text, severity="error")
        # Drop the user turn that produced no answer, so a retry does not double it up.
        if page.messages and page.messages[-1].role == "user":
            page.messages.pop()
        self.statusBar().showMessage("Request failed — see the transcript and telemetry.")

    def _on_gen_cancelled(self, key: str) -> None:
        """Settle the transcript after a cancelled generation."""
        page = self._page_for(key)
        if page is None:
            return
        page.view.end_assistant_message()  # renders any partial text; drops an empty turn
        page.view.add_notice("Generation cancelled.", severity="warn")
        # Drop the user turn that got no (complete) answer, so a resend does not double it.
        if page.messages and page.messages[-1].role == "user":
            page.messages.pop()
        self.statusBar().showMessage("Generation cancelled.")

    def _on_gen_busy_changed(self, key: str, busy: bool) -> None:
        """The composer mirrors the *active tab's* state; other tabs stream in peace."""
        if self._is_current(key):
            self._composer.set_busy(busy)
        page = self._page_for(key)
        if busy and page is not None:
            self.statusBar().showMessage(f"Streaming from {page.pending_target}…")

    def _on_discovery_failed(self, provider_id: str, message: str, error: object) -> None:
        """Report a background discovery/health failure in the providers panel.

        Deliberately not the transcript: a failed ``models()`` probe is not a failed
        chat request, and must not read as one.
        """
        hint = error.hint if isinstance(error, AnyInferError) else ""
        detail = f"{message}\nHint: {hint}" if hint else message
        self._set_provider_row(provider_id, health="fail", detail=detail)
        self.statusBar().showMessage(f"{provider_id}: discovery failed — {message}")

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
        self._save_all_pages()
        if self._models_dialog is not None:
            # Closed first: its panels listen to engine signals, and a straggling
            # download callback into a dead dialog is a crash on exit.
            self._models_dialog.close()
        self._engine.cancel()
        with contextlib.suppress(AnyInferError):
            self._engine.close()
        super().closeEvent(event)  # type: ignore[arg-type]
