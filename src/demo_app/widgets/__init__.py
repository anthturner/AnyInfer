"""Widgets for the AnyInfer demo, each demonstrating one part of the library."""

from .add_model_dialog import AddModelChoice, AddModelDialog
from .app_settings_dialog import AppSettingsDialog
from .chat_tabs import ChatPage, ConversationTabs
from .chat_view import (
    MessageBubble,
    MessageList,
    ReasoningFold,
    TypingIndicator,
    WelcomeView,
)
from .collapsible_section import CollapsibleSection
from .composer import Composer
from .embeddings_panel import EmbeddingsPanel
from .engine_bar import ContextWindowRow, EngineBar
from .help_dialogs import AboutDialog, LicensesDialog
from .metrics import StatusMetrics
from .models_dialog import ModelsDialog
from .schema_panel import EXAMPLE_SCHEMA, SchemaPanel
from .sdk_help import LibraryMapDialog, SdkHelpButton, SdkHelpDialog
from .settings_dialog import ProviderSettingsDialog
from .tab_widget import BorderedTabWidget
from .target_inspector import TargetInspector
from .telemetry_view import TelemetryView
from .tools_panel import ToolsPanel

__all__ = [
    "EXAMPLE_SCHEMA",
    "AboutDialog",
    "AddModelChoice",
    "AddModelDialog",
    "AppSettingsDialog",
    "BorderedTabWidget",
    "ChatPage",
    "CollapsibleSection",
    "Composer",
    "ContextWindowRow",
    "ConversationTabs",
    "EmbeddingsPanel",
    "EngineBar",
    "LibraryMapDialog",
    "LicensesDialog",
    "MessageBubble",
    "MessageList",
    "ModelsDialog",
    "ProviderSettingsDialog",
    "ReasoningFold",
    "SchemaPanel",
    "SdkHelpButton",
    "SdkHelpDialog",
    "StatusMetrics",
    "TargetInspector",
    "TelemetryView",
    "ToolsPanel",
    "TypingIndicator",
    "WelcomeView",
]
