"""User-visible strings shared by the demo's widgets.

This module does not implement translation — every constant is still plain English — but
centralizing the recurring labels gives a future translation layer one place to hook.
Not every literal routes through here: one-off notices and captions still live at their
call sites.
"""

from __future__ import annotations

__all__ = [
    "CANCEL",
    "COMPOSER_PLACEHOLDER",
    "CONVERSATIONS_TITLE",
    "DELETE",
    "EXPORT_ALL",
    "EXPORT_JSON",
    "EXPORT_MARKDOWN",
    "IMPORT",
    "NEW_CHAT",
    "PROVIDERS_TITLE",
    "REFRESH",
    "RENAME",
    "SEND",
    "SETTINGS",
    "LOCAL_MODELS",
    "SHOW_CONVERSATIONS",
    "SHOW_LEFT_SIDEBAR",
    "SHOW_PROVIDERS",
    "SHOW_RIGHT_SIDEBAR",
    "SHOW_STRUCTURED",
    "SHOW_TARGET",
    "SHOW_TELEMETRY",
    "SHOW_TOOLS",
    "STRUCTURED_TITLE",
    "TARGET_TITLE",
    "TELEMETRY_TITLE",
    "TOOLS_TITLE",
    "WELCOME_FALLBACK",
    "WELCOME_QUICK_QUESTION",
    "WELCOME_STRUCTURED",
    "WELCOME_TAGLINE",
    "WELCOME_TOOLS",
]

COMPOSER_PLACEHOLDER = "Ask something… (Ctrl+Enter to send, Shift+Enter for a new line)"
NEW_CHAT = "New chat"
SEND = "Send"
CANCEL = "Cancel"
EXPORT_ALL = "Export all"
IMPORT = "Import"
RENAME = "Rename"
DELETE = "Delete"
EXPORT_JSON = "Export as JSON"
EXPORT_MARKDOWN = "Export as Markdown"

WELCOME_TAGLINE = "A faithful, offline worked example of AnyInfer integration."
WELCOME_QUICK_QUESTION = "Ask a quick question"
WELCOME_STRUCTURED = "Try structured output"
WELCOME_FALLBACK = "See fallback demo"
WELCOME_TOOLS = "Run the tool loop"

TELEMETRY_TITLE = "Telemetry"
STRUCTURED_TITLE = "Structured output"
PROVIDERS_TITLE = "Providers"
TARGET_TITLE = "Target inspector"
TOOLS_TITLE = "Tool loop"
LOCAL_MODELS = "Local models…"
REFRESH = "Refresh"
SETTINGS = "Provider settings…"
CONVERSATIONS_TITLE = "Conversations"

SHOW_LEFT_SIDEBAR = "Show Left Sidebar"
SHOW_RIGHT_SIDEBAR = "Show Right Sidebar"
SHOW_CONVERSATIONS = "Conversation History"
SHOW_TELEMETRY = "Telemetry"
SHOW_STRUCTURED = "Structured Output"
SHOW_PROVIDERS = "Providers"
SHOW_TARGET = "Target Inspector"
SHOW_TOOLS = "Tool Loop"
