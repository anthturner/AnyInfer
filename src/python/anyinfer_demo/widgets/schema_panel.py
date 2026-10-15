"""Structured-output controls: a schema editor on the left, the result on the right.

The interesting part to demonstrate is that the *mechanism* is chosen by AnyInfer, not by
the caller. The same schema becomes a decoding grammar on llama.cpp, a ``json_schema``
response format on OpenAI, plain JSON mode elsewhere, and a prompt instruction as a last
resort, and the result reports which one was used
(`structured_mechanism`).

Validation is always against the canonical schema regardless of mechanism, and a violation
is repaired within a bounded budget rather than retried forever.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..strings import STRUCTURED_TITLE

__all__ = ["EXAMPLE_SCHEMA", "SchemaPanel"]

EXAMPLE_SCHEMA = {
    "type": "object",
    "title": "Analysis",
    "properties": {
        "summary": {"type": "string", "description": "One-sentence summary."},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["summary", "sentiment", "keywords", "confidence"],
    "additionalProperties": False,
}
"""A schema small enough to read and strict enough to actually reject bad output."""


class SchemaPanel(QWidget):
    """Edits the structured-output contract and reports the outcome of the last one."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        caption = QLabel(
            f"<b>{STRUCTURED_TITLE}</b> — responses are validated against this JSON "
            "Schema; AnyInfer picks the strongest mechanism the target supports."
        )
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        caption.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(caption)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self._enabled = QCheckBox("Enforce schema")
        self._enabled.setAccessibleName("Enforce schema")
        controls.addWidget(self._enabled)

        repair_label = QLabel("Repair attempts:")
        controls.addWidget(repair_label)
        self._repair = QSpinBox()
        self._repair.setRange(0, 3)
        self._repair.setValue(1)
        self._repair.setAccessibleName("Repair attempts")
        repair_label.setBuddy(self._repair)
        self._repair.setToolTip(
            "Bounded budget for re-prompting the model with its own validation errors. "
            "0 disables repair, so a violation raises SchemaViolationError."
        )
        controls.addWidget(self._repair)

        self._mechanism_pill = QLabel()
        self._mechanism_pill.setVisible(False)
        controls.addWidget(self._mechanism_pill)
        controls.addStretch(1)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._editor = QPlainTextEdit(json.dumps(EXAMPLE_SCHEMA, indent=2))
        self._editor.setEnabled(False)
        self._editor.setAccessibleName("Schema editor")
        self._enabled.toggled.connect(self._editor.setEnabled)
        splitter.addWidget(self._editor)

        result_side = QWidget()
        result_layout = QVBoxLayout(result_side)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(8)

        self._result_tree = QTreeWidget()
        self._result_tree.setHeaderLabels(["Field", "Value"])
        self._result_tree.setAccessibleName("Structured result")
        result_layout.addWidget(self._result_tree, 1)

        self._repair_log = QLabel("No structured request yet.")
        self._repair_log.setWordWrap(True)
        self._repair_log.setTextFormat(Qt.TextFormat.RichText)
        result_layout.addWidget(self._repair_log)

        splitter.addWidget(result_side)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self._status = QLabel()
        self._status.setObjectName("ErrorText")
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        layout.addWidget(self._status)

    @property
    def enabled(self) -> bool:
        """Whether the next request should carry a schema."""
        return self._enabled.isChecked()

    def set_enabled(self, enabled: bool) -> None:
        """Set whether the next request should carry a schema."""
        self._enabled.setChecked(enabled)

    def schema(self) -> dict[str, Any] | None:
        """The edited schema, or ``None`` when schema enforcement is disabled.

        Raises:
            ValueError: If schema enforcement is on but the text is not a valid JSON
                object.
        """
        if not self.enabled:
            return None
        try:
            parsed = json.loads(self._editor.toPlainText())
        except json.JSONDecodeError as error:
            raise ValueError(f"the schema is not valid JSON: {error}") from error
        if not isinstance(parsed, dict):
            raise ValueError("the schema must be a JSON object")
        return parsed

    def repair_attempts(self) -> int:
        """The configured repair budget."""
        return int(self._repair.value())

    def report(self, result: Any) -> None:
        """Show what the core did with the schema on the last successful request."""
        self._status.setVisible(False)
        if result.structured_mechanism is None:
            self._mechanism_pill.setVisible(False)
            self._result_tree.clear()
            self._repair_log.setText("Last request carried no schema.")
            return

        self._set_mechanism_pill(result.structured_mechanism)
        self._result_tree.clear()
        if isinstance(result.structured, dict):
            for key, value in result.structured.items():
                _add_tree_row(self._result_tree.invisibleRootItem(), key, value)
        self._result_tree.expandAll()

        repairs = (
            f"{result.repair_attempts} repair attempt(s)"
            if result.repair_attempts
            else "validated on the first try"
        )
        self._repair_log.setText(f"{repairs}.")

    def report_error(self, message: str) -> None:
        """Show a validation or configuration failure."""
        self._status.setText(_escape(message))
        self._status.setVisible(True)

    def _set_mechanism_pill(self, mechanism: str) -> None:
        self._mechanism_pill.setText(
            f"<span style='background:{theme.color('accent_bg')}; color:{theme.color('accent')}; "
            f"border-radius:8px; padding:2px 8px;'><b>{_escape(mechanism)}</b></span>"
        )
        self._mechanism_pill.setTextFormat(Qt.TextFormat.RichText)
        self._mechanism_pill.setVisible(True)


def _add_tree_row(parent: QTreeWidgetItem, key: str, value: Any) -> None:
    if isinstance(value, dict):
        item = QTreeWidgetItem(parent, [str(key), ""])
        for sub_key, sub_value in value.items():
            _add_tree_row(item, sub_key, sub_value)
    elif isinstance(value, list):
        item = QTreeWidgetItem(parent, [str(key), f"[{len(value)} items]"])
        for index, sub_value in enumerate(value):
            _add_tree_row(item, str(index), sub_value)
    else:
        QTreeWidgetItem(parent, [str(key), json.dumps(value)])


def _escape(text: str) -> str:
    """Minimal HTML escaping for text placed into a rich-text label."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
