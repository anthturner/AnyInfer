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
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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

from anyinfer import CachePolicy, CostEstimate, HistoryPolicy, Retry, Route
from anyinfer.errors import AnyInferError
from anyinfer.types.capabilities import Health
from anyinfer.types.messages import Message, Text, system, user
from anyinfer.types.requests import Repair, Sampling
from anyinfer.types.results import AttemptRecord, Generation

from . import config as config_module
from . import strings, theme
from .config import DemoConfig
from .conversation import Conversation, conversations_dir, gist_title
from .engine import Engine, GenerationSpec
from .widgets import (
    AboutDialog,
    CollapsibleSection,
    Composer,
    ConversationSidebar,
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
from .widgets.icons import themed_icon
from .widgets.sdk_help import DOCS_URL

__all__ = ["MainWindow"]

#: Below these drag widths a sidebar snaps shut — a 60-px conversation list is noise.
_LEFT_SNAP_WIDTH = 140
_RIGHT_SNAP_WIDTH = 220

#: The width a sidebar reopens to when dragged out of its snapped-shut state.
_LEFT_OPEN_WIDTH = 220
_RIGHT_OPEN_WIDTH = 380

_SECTION_ICONS: dict[str, str] = {
    "telemetry": "activity",
    "structured": "braces",
    "providers": "server",
    "target": "target",
    "tools": "tool",
}
"""Inspector section key → Tabler icon, shared by the headers and the View menu."""

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


class MainWindow(QMainWindow):
    """The demo window."""

    def __init__(self, config: DemoConfig, config_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("AnyInfer Demo")
        self.resize(1280, 860)

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
        self._reload_sidebar()

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
        assert page is not None, "the window always keeps at least one tab"
        return page.view

    # ---- construction ----------------------------------------------------------------

    def _build_ui(self, config: DemoConfig) -> None:
        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.setHandleWidth(4)

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
        self._main_splitter.setHandleWidth(4)
        self._main_splitter.addWidget(self._build_center_pane(config))
        self._main_splitter.addWidget(self._build_inspector())
        self._main_splitter.setStretchFactor(0, 3)
        self._main_splitter.setStretchFactor(1, 2)
        self._main_splitter.setCollapsible(0, False)
        outer.addWidget(self._main_splitter)

        outer.setStretchFactor(0, 0)
        outer.setStretchFactor(1, 1)
        outer.setSizes([_LEFT_OPEN_WIDTH, 1000])

        # Dragging a sidebar below a usable width snaps it shut; dragging it back out
        # of the snap reopens it at a sane size. `splitterMoved` fires on user drags
        # only, so programmatic setSizes cannot recurse through here.
        outer.splitterMoved.connect(self._on_outer_splitter_moved)
        self._main_splitter.splitterMoved.connect(self._on_main_splitter_moved)

        self.setCentralWidget(outer)
        self.setStatusBar(QStatusBar())
        self._status_metrics = StatusMetrics()
        self.statusBar().addPermanentWidget(self._status_metrics)
        self.statusBar().showMessage("Ready — offline fake provider, no credentials needed.")

        self._outer_splitter = outer
        self._sidebar_width_before_hide = _LEFT_OPEN_WIDTH
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
        welcome.new_chat_requested.connect(self._on_new_chat)
        welcome.structured_output_requested.connect(self._on_welcome_structured)
        welcome.fallback_demo_requested.connect(self._on_welcome_fallback)
        welcome.tool_loop_requested.connect(self._on_welcome_tools)
        return welcome

    def _build_controls(self) -> QGroupBox:
        # "&&": QGroupBox treats a lone ampersand as a mnemonic marker and eats it.
        group = QGroupBox("Request options — sampling && routing")
        # Two rows: sampling knobs above, routing/state below. One row held them all
        # until reasoning, history, and caching arrived; ten controls in a line is a
        # ribbon, not a form.
        outer = QVBoxLayout(group)
        outer.setSpacing(6)
        controls = QHBoxLayout()
        controls.setSpacing(12)
        routing = QHBoxLayout()
        routing.setSpacing(12)
        outer.addLayout(controls)
        outer.addLayout(routing)

        controls.addWidget(QLabel("Temperature:"))
        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setSpecialValueText("provider default")
        self._temperature.setValue(0.0)
        self._temperature.setAccessibleName("Temperature")
        self._temperature.setToolTip(
            "Sampling temperature. At the minimum the field reads 'provider default' and "
            "is omitted from the wire request entirely — AnyInfer never invents a "
            "temperature." + _UNREPORTED_DEFAULT_NOTE
        )
        controls.addWidget(self._temperature)

        controls.addWidget(QLabel("Top-p:"))
        self._top_p = QDoubleSpinBox()
        self._top_p.setRange(0.0, 1.0)
        self._top_p.setSingleStep(0.05)
        self._top_p.setSpecialValueText("provider default")
        self._top_p.setValue(0.0)
        self._top_p.setAccessibleName("Top-p")
        self._top_p.setToolTip(
            "Nucleus-sampling cutoff. At the minimum the value is omitted from the wire "
            "request, so the provider's default is used." + _UNREPORTED_DEFAULT_NOTE
        )
        controls.addWidget(self._top_p)

        controls.addWidget(QLabel("Max tokens:"))
        self._max_output_tokens = QSpinBox()
        self._max_output_tokens.setRange(0, 65_536)
        self._max_output_tokens.setSingleStep(1)
        self._max_output_tokens.setSpecialValueText("provider default")
        self._max_output_tokens.setValue(0)
        self._max_output_tokens.setAccessibleName("Max output tokens")
        controls.addWidget(self._max_output_tokens)

        controls.addWidget(QLabel("Reasoning:"))
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
        controls.addWidget(self._reasoning)

        routing.addWidget(QLabel("Attempts:"))
        self._max_attempts = QSpinBox()
        self._max_attempts.setRange(1, 5)
        self._max_attempts.setValue(2)
        self._max_attempts.setAccessibleName("Max attempts per target")
        self._max_attempts.setToolTip("Retry budget per target, before falling back.")
        routing.addWidget(self._max_attempts)

        routing.addWidget(QLabel("Fallback:"))
        self._fallback = QComboBox()
        self._fallback.addItem("Nothing (no fallback)", "")
        self._fallback.setAccessibleName("Fallback target")
        self._fallback.setToolTip(
            "Optional fallback target the router moves to once the retry budget is spent. "
            "Pick the flaky demo model above with 1 attempt to watch it happen."
        )
        routing.addWidget(self._fallback)

        routing.addWidget(QLabel("History:"))
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
        routing.addWidget(self._history)
        routing.addWidget(SdkHelpButton("history"))

        routing.addWidget(QLabel("Prompt cache:"))
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
        routing.addWidget(self._cache)
        routing.addWidget(SdkHelpButton("prompt-cache"))

        self._reuse_session = QCheckBox("Reuse session")
        self._reuse_session.setAccessibleName("Reuse provider session")
        self._reuse_session.setToolTip(
            "Thread turns through one provider-side session, so a provider that keeps "
            "conversations can resume instead of re-reading the whole transcript. The "
            "status line reports what actually happened: resumed, fresh, or unsupported "
            "— the provider decides, never the client."
        )
        routing.addWidget(self._reuse_session)

        self._controls_help = SdkHelpButton("routing")

        saved = self._engine.config.targets
        if len(saved) > 1:
            self._fallback.addItem(saved[1], saved[1])
            self._fallback.setCurrentIndex(1)
        self._engine_bar.changed.connect(self._update_fallback_choices)
        self._engine_bar.changed.connect(self._refresh_token_hint)
        self._engine_bar.changed.connect(self._refresh_default_hints)
        self._refresh_default_hints()

        controls.addStretch(1)
        routing.addStretch(1)
        routing.addWidget(self._controls_help)
        return group

    def _build_inspector(self) -> QWidget:
        pane = QWidget()
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

        self._inspector_splitter.setSizes([280, 280, 220, 40, 40])
        layout.addWidget(self._inspector_splitter, 1)

        self._inspector_sections: dict[str, CollapsibleSection] = {
            "telemetry": self._telemetry_section,
            "structured": self._schema_section,
            "providers": self._providers_section,
            "target": self._target_section,
            "tools": self._tools_section,
        }
        # Both panels act on whatever engine/model the bar currently points at.
        self._engine_bar.changed.connect(self._sync_inspector_targets)
        self._sync_inspector_targets()
        return pane

    def _sync_inspector_targets(self) -> None:
        """Point the target inspector and tools panel at the bar's current selection."""
        target = self._engine_bar.target()
        self._target_inspector.set_target(target)
        self._tools.set_target(target)

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
        models_action = QAction(strings.LOCAL_MODELS, self)
        models_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
        models_action.triggered.connect(self._on_local_models)
        tools_menu.addAction(models_action)

        view_menu = self.menuBar().addMenu("&View")
        self._build_sidebar_menu(view_menu)
        view_menu.addSeparator()
        self._build_theme_menu(view_menu)

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

    def _build_sidebar_menu(self, view_menu: QMenu) -> None:
        """Whole-sidebar and per-section visibility entries.

        A visible section shows the ordinary checkmark; a hidden one shows the section's
        own icon instead — the menu doubles as a legend for the header icons on the
        right-hand dock.
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
        self._conversations_action = conversations_action

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
            action.toggled.connect(lambda _checked, k=key: self._sync_section_action_icon(k))
            view_menu.addAction(action)
            self._section_actions[key] = action
            self._sync_section_action_icon(key)

    def _sync_section_action_icon(self, key: str) -> None:
        """Hidden sections wear their icon in the menu; visible ones wear the checkmark."""
        action = self._section_actions[key]
        if action.isChecked():
            action.setIcon(QIcon())
        else:
            action.setIcon(themed_icon(self, _SECTION_ICONS[key], size=16))

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
        cancel_action.triggered.connect(self._on_cancel_current)
        self.addAction(cancel_action)

        settings_action = QAction("Open settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        settings_action.triggered.connect(self._on_configure)
        self.addAction(settings_action)

        toggle_action = QAction("Toggle right sidebar", self)
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
        self._reload_sidebar()

    def _on_tab_save(self, index: int, fmt: str) -> None:
        page = self._tabs.page_at(index)
        if page is None:
            return
        self._save_page(page)
        self._on_export_conversation(page.conversation.id, fmt)

    def _on_tab_delete(self, index: int) -> None:
        page = self._tabs.page_at(index)
        if page is not None:
            self._on_delete_conversation(page.conversation.id)

    def _on_tab_close(self, index: int) -> None:
        """Close one tab, keeping its conversation on disk and in the sidebar."""
        page = self._tabs.page_at(index)
        if page is None:
            return
        self._engine.cancel(page.key)
        self._save_page(page)
        self._tabs.removeTab(index)
        page.deleteLater()
        if self._tabs.count() == 0:
            self._open_page(Conversation.new())
        self._reload_sidebar()

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
        self._reload_sidebar()

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
            # Titled at send time, so the tab and sidebar read as the topic rather than
            # as "New chat" for the length of the first answer.
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

        Only the max-output-tokens capability is knowable here; sampling defaults are
        provider-side and unreported, and their tooltips say so instead of showing an
        invented number.
        """
        detected = self._engine_bar.max_output_tokens_detected()
        base = (
            "Upper bound on tokens the model may generate. Zero omits the field from "
            "the wire request."
        )
        if detected is None:
            self._max_output_tokens.setSpecialValueText("provider default")
            self._max_output_tokens.setToolTip(base + _UNREPORTED_DEFAULT_NOTE)
            return
        self._max_output_tokens.setSpecialValueText(
            f"provider default ({detected.value:,})"
        )
        self._max_output_tokens.setToolTip(
            f"{base} (Provider default: {detected.value:,} tokens — "
            f"{detected.provenance}.)"
        )

    def _on_configure(self) -> None:
        if self._engine.busy:
            # Applying settings tears down the client, which would kill every in-flight
            # stream mid-answer; make the user settle the generations first.
            self.statusBar().showMessage("Finish or cancel the running generations first.")
            return
        dialog = ProviderSettingsDialog(self._engine.registry, self._engine.config, self)
        if dialog.exec() != ProviderSettingsDialog.DialogCode.Accepted:
            return
        config = self._with_ui_state(dialog.result_config())
        self._engine.apply_config(config)
        self._engine_bar.set_providers(config)
        if self._models_dialog is not None:
            # The pull panel offers configured engines; a settings change can add or
            # remove one while the dialog is open.
            self._models_dialog.set_providers(config)
        self._discover_enabled_providers()
        try:
            config.save(self._config_path)
        except OSError as error:
            self.statusBar().showMessage(f"Settings applied but not saved: {error}")
            return
        self.statusBar().showMessage("Settings saved; the client will rebuild on next use.")

    def _on_system_prompt(self) -> None:
        """Edit the system prompt stored in the demo config."""
        current = self._engine.config.system_prompt
        text, ok = QInputDialog.getMultiLineText(
            self, "System prompt", "Sent as the first system message in new chats:", current
        )
        if not ok:
            return
        config = replace(self._engine.config, system_prompt=text)
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
        """Open (or focus) the local-model manager."""
        if self._models_dialog is not None and self._models_dialog.isVisible():
            self._models_dialog.raise_()
            self._models_dialog.activateWindow()
            return
        self._models_dialog = ModelsDialog(self._engine, self._engine.config, self)
        self._models_dialog.show()

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

    # ---- sidebars: visibility and snapping ---------------------------------------------

    def _on_outer_splitter_moved(self, _pos: int, _index: int) -> None:
        """Snap the conversation list shut below a usable width."""
        sizes = self._outer_splitter.sizes()
        if len(sizes) < 2:
            return
        width = sizes[0]
        if 0 < width < _LEFT_SNAP_WIDTH:
            total = sum(sizes)
            self._outer_splitter.setSizes([0, total])
            self._sync_left_actions(False)
        elif width >= _LEFT_SNAP_WIDTH:
            self._sidebar_width_before_hide = width
            self._sync_left_actions(True)

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

    def _sync_left_actions(self, visible: bool) -> None:
        self._left_sidebar_action.setChecked(visible)
        self._conversations_action.setChecked(visible)

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

    def _set_left_sidebar_visible(self, visible: bool) -> None:
        """Collapse or restore the conversation history sidebar while keeping it resizable."""
        splitter = self._outer_splitter
        sizes = splitter.sizes()
        if visible:
            total = sum(sizes) if sizes else 1
            restored = max(self._sidebar_width_before_hide, _LEFT_SNAP_WIDTH)
            right = max(total - restored, int(total * 0.6))
            splitter.setSizes([total - right, right])
        else:
            if len(sizes) >= 2 and sizes[0] > 0:
                self._sidebar_width_before_hide = max(sizes[0], _LEFT_SNAP_WIDTH)
            total = sum(sizes) if sizes else 1
            splitter.setSizes([0, total])
        self._sync_left_actions(visible)
        self._sidebar.setVisible(visible)

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

    def _on_welcome_tools(self) -> None:
        """Aim the tool-loop panel at the offline tools model and bring it into view."""
        self._engine_bar.set_target("demo-fake:tools")
        self._sync_inspector_targets()
        self._set_right_sidebar_visible(True)
        self._tools_section.setVisible(True)
        self._tools_section.set_minimized(False)
        self.statusBar().showMessage(
            "Tool loop ready — press 'Run tool loop' in the right sidebar."
        )

    # ---- conversation persistence ------------------------------------------------------

    def _on_new_chat(self) -> None:
        """Open a fresh conversation in a new tab; nothing else is interrupted."""
        self._open_page(Conversation.new())
        self.statusBar().showMessage("New chat.")

    def _on_conversation_selected(self, conversation_id: str) -> None:
        existing = self._tabs.index_of_key(conversation_id)
        if existing >= 0:
            self._tabs.setCurrentIndex(existing)
            return
        path = self._conversations_dir / f"{conversation_id}.json"
        loaded = Conversation.load(path)
        if loaded is None:
            return
        self._open_page(loaded)
        self.statusBar().showMessage(f"Loaded '{loaded.title}'.")

    def _on_rename_conversation(self, conversation_id: str, title: str) -> None:
        page = self._page_for(conversation_id)
        if page is not None:
            self._rename_page(page, title)
            return
        path = self._conversations_dir / f"{conversation_id}.json"
        loaded = Conversation.load(path)
        if loaded is not None:
            loaded.renamed(title).save(self._conversations_dir)
        self._reload_sidebar()

    def _on_delete_conversation(self, conversation_id: str) -> None:
        """Delete a conversation's file, closing its tab if it has one."""
        index = self._tabs.index_of_key(conversation_id)
        if index >= 0:
            page = self._tabs.page_at(index)
            if page is not None:
                self._engine.cancel(page.key)
                page.messages.clear()  # a close must not re-save what delete removes
            self._tabs.removeTab(index)
            if page is not None:
                page.deleteLater()
        (self._conversations_dir / f"{conversation_id}.json").unlink(missing_ok=True)
        if self._tabs.count() == 0:
            self._open_page(Conversation.new())
        self._reload_sidebar()

    def _on_export_conversation(self, conversation_id: str, fmt: str) -> None:
        page = self._page_for(conversation_id)
        if page is not None:
            conversation = page.conversation.with_messages(page.messages)
        else:
            loaded = Conversation.load(self._conversations_dir / f"{conversation_id}.json")
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
        self._save_all_pages()
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

    def _save_page(self, page: ChatPage) -> None:
        if not page.messages:
            return
        page.conversation = page.conversation.with_messages(page.messages)
        with contextlib.suppress(OSError):
            page.conversation.save(self._conversations_dir)

    def _save_current_conversation(self) -> None:
        page = self._tabs.current_page()
        if page is not None:
            self._save_page(page)

    def _save_all_pages(self) -> None:
        for page in self._tabs.pages():
            self._save_page(page)

    def _reload_sidebar(self) -> None:
        conversations = Conversation.load_all(self._conversations_dir)
        page = self._tabs.current_page()
        active_id = page.conversation.id if page is not None else ""
        self._sidebar.set_conversations(conversations, active_id=active_id)

    # ---- theme and persistence -------------------------------------------------------

    def _apply_theme(self, preference: str) -> None:
        """Restyle the whole application and re-render the themed icons."""
        self._theme = preference
        theme.apply_theme(QApplication.instance(), preference)
        self._engine_bar.reapply_theme()
        self._tabs.reapply_theme()
        for page in self._tabs.pages():
            page.view.reapply_theme()
            empty = page.view.empty_state()
            if isinstance(empty, WelcomeView):
                empty.reapply_theme()
        self._composer.reapply_theme()
        self._sidebar.reapply_theme()
        self._telemetry.reapply_theme()
        self._provider_refresh_button.setIcon(
            themed_icon(self._provider_refresh_button, "refresh")
        )
        for section in self._inspector_sections.values():
            section.reapply_theme()
        for key in self._section_actions:
            self._sync_section_action_icon(key)
        for name, action in self._help_menu_actions.items():
            icon_name = {"map": "map", "book": "book", "book2": "book",
                         "license": "license", "info": "info"}[name]
            action.setIcon(themed_icon(self, icon_name, size=16))

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
        self._reload_sidebar()
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
