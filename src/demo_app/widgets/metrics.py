"""A compact, status-bar-hosted readout of the last request's measured metrics.

Everything here is either measured centrally by the core or reported by the provider; a
number AnyInfer was not given is shown as ``—``, never as zero or an estimate presented as
fact.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

__all__ = ["StatusMetrics"]

_FIELDS = (
    ("target", "Target"),
    ("ttft", "TTFT"),
    ("total", "Total"),
    ("throughput", "Rate"),
    ("tokens", "Tokens"),
    ("cost", "Cost"),
    ("attempts", "Attempts"),
)


class StatusMetrics(QWidget):
    """A single-row metrics readout meant to be embedded in ``QMainWindow.statusBar()``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)

        self._values: dict[str, QLabel] = {}
        for key, label in _FIELDS:
            caption = QLabel(f"{label}:")
            caption.setObjectName("Muted")
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setAccessibleName(f"{label} metric")
            layout.addWidget(caption)
            layout.addWidget(value)
            self._values[key] = value

    def reset(self) -> None:
        """Blank every field back to 'not reported'."""
        for label in self._values.values():
            label.setText("—")

    def set_first_token(self, at_ms: float) -> None:
        """Show the centrally-measured TTFT as soon as the mark arrives."""
        self._values["ttft"].setText(f"{at_ms:.0f} ms")

    def set_usage(self, usage: Any) -> None:
        """Show token counts and cost, mid-stream if the provider reports them early."""
        if usage.total_tokens is not None:
            self._values["tokens"].setText(str(usage.total_tokens))
        if usage.cost_usd is not None:
            self._values["cost"].setText(f"${usage.cost_usd:.6f}")

    def set_result(self, result: Any) -> None:
        """Fill the readout from a completed generation."""
        self._values["target"].setText(str(result.target))
        self._values["total"].setText(f"{result.timing.total_ms:.0f} ms")

        if result.timing.first_token_ms is not None:
            self._values["ttft"].setText(f"{result.timing.first_token_ms:.0f} ms")
        if result.timing.output_tokens_per_s is not None:
            self._values["throughput"].setText(f"{result.timing.output_tokens_per_s:.1f} tok/s")

        self.set_usage(result.usage)

        ok = sum(1 for a in result.attempts if a.outcome == "ok")
        self._values["attempts"].setText(f"{len(result.attempts)} ({ok} ok)")
