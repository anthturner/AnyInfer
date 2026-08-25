"""Helpers shared by two or more of the Models dialog's panels."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ...config import DemoConfig
from ..formatting import _bytes

__all__ = [
    "_ACQUIRE_KEY",
    "_BENCHMARK_KEY",
    "_CATALOG_KEY",
    "_INSTALLED_KEY",
    "_INSTALL_RUNTIME_KEY",
    "_PLAN_KEY",
    "_PULL_KEY",
    "_REMOVE_KEY",
    "_RUNTIMES_KEY",
    "_LlamaSetupPrompt",
    "_bytes",
    "_llama_cpp_enabled",
]

_CATALOG_KEY = "models.catalog"
_INSTALLED_KEY = "models.installed"
_ACQUIRE_KEY = "models.acquire"
_PLAN_KEY = "models.plan"
_REMOVE_KEY = "models.remove"
_PULL_KEY = "models.pull"
_RUNTIMES_KEY = "models.runtimes"
_INSTALL_RUNTIME_KEY = "models.install-runtime"
_BENCHMARK_KEY = "models.benchmark"
"""Keys tagging each background call, so an answer lands in the panel that asked for it.

The engine runs local work on a pool of its own, so two of these can be outstanding at
once — a catalog refresh while a download runs is the ordinary case, not an edge one.
"""


class _LlamaSetupPrompt(QWidget):
    """One shared prerequisite notice for llama.cpp-owned surfaces."""

    setup_requested = Signal()

    def __init__(self, purpose: str) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        message = QLabel(f"<b>llama.cpp provider required.</b> Add it before {purpose}.")
        message.setTextFormat(Qt.TextFormat.RichText)
        message.setWordWrap(True)
        layout.addWidget(message, 1)
        self.button = QPushButton("Add llama.cpp with defaults")
        self.button.setAccessibleName("Add llama.cpp provider with defaults")
        self.button.setToolTip(
            "Enable one llama.cpp provider using its built-in paths, balanced resource "
            "posture, and per-user model store."
        )
        self.button.clicked.connect(self.setup_requested)
        layout.addWidget(self.button)

    def set_ready(self, ready: bool) -> None:
        """Hide the prerequisite once an enabled llama.cpp instance exists."""
        self.setVisible(not ready)


def _llama_cpp_enabled(config: DemoConfig) -> bool:
    """Whether configuration contains at least one enabled llama.cpp instance."""
    return any(
        provider.enabled and provider.provider_id == "llama-cpp" for provider in config.providers
    )
