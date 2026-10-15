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
    "EMBEDDINGS_TITLE",
    "LOCAL_INFERENCE",
    "OPEN_SAVED",
    "PROVIDERS_TITLE",
    "REFRESH",
    "RENAME",
    "SEND",
    "SETTINGS",
    "SHOW_PROVIDERS",
    "SHOW_SIDEBAR",
    "SHOW_STRUCTURED",
    "SHOW_TARGET",
    "SHOW_TELEMETRY",
    "SHOW_TOOLS",
    "SIDEBAR",
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
SEND = "Send"
CANCEL = "Cancel"
RENAME = "Rename"
OPEN_SAVED = "Open Saved…"

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
EMBEDDINGS_TITLE = "Embeddings and rerank"
LOCAL_INFERENCE = "Local Inference…"
REFRESH = "Refresh"
SETTINGS = "Provider settings…"
SIDEBAR = "Sidebar"
SHOW_SIDEBAR = "Show Sidebar"
SHOW_TELEMETRY = "Telemetry"
SHOW_STRUCTURED = "Structured Output"
SHOW_PROVIDERS = "Providers"
SHOW_TARGET = "Target Inspector"
SHOW_TOOLS = "Tool Loop"
