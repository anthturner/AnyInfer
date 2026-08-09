"""The message input area: auto-growing text box, token estimate, and quick-action chips.

The token estimate is read straight from `budget()`, the same public
preflight calculator an application would use to decide how much more context to pack — this
widget performs no estimation of its own.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import strings, theme
from .icons import themed_icon
from .sdk_help import SdkHelpButton

__all__ = ["QUICK_ACTIONS", "Composer"]

_MAX_LINES = 8


class QuickAction:
    """One quick-action chip: a label and the prompt it prefills."""

    __slots__ = ("label", "prompt")

    def __init__(self, label: str, prompt: str) -> None:
        self.label = label
        self.prompt = prompt


QUICK_ACTIONS: tuple[QuickAction, ...] = (
    QuickAction(
        "Summarize JSON",
        "Summarize the following JSON in one sentence: "
        '{"library": "AnyInfer", "interface": "typed events", "providers": 7}',
    ),
    QuickAction(
        "Run flaky→fallback demo",
        "Try the flaky target and show the retry and fallback trail.",
    ),
    QuickAction("Structured output", "Analyze this product review: 'Fast shipping, great value.'"),
)


class _AutoGrowingTextEdit(QPlainTextEdit):
    """A ``QPlainTextEdit`` that grows with its content, up to `_MAX_LINES`."""

    send_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(strings.COMPOSER_PLACEHOLDER)
        self.setAccessibleName("Message")
        self.setAccessibleDescription(strings.COMPOSER_PLACEHOLDER)
        self.textChanged.connect(self._adjust_height)
        self._adjust_height()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt's spelling
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if is_enter and event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            self.send_requested.emit()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            return
        super().keyPressEvent(event)

    def _adjust_height(self) -> None:
        metrics = self.fontMetrics()
        lines = min(_MAX_LINES, max(1, self.document().blockCount()))
        height = metrics.lineSpacing() * lines + 16
        self.setFixedHeight(height)


class Composer(QWidget):
    """The full input area: text box, token hint, send/cancel buttons, and quick chips."""

    send_requested = Signal()
    cancel_requested = Signal()
    quick_action_chosen = Signal(str)
    text_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        for action in QUICK_ACTIONS:
            button = QPushButton(action.label)
            button.setObjectName("ChipButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"Quick action: {action.label}")
            button.clicked.connect(
                lambda _checked=False, p=action.prompt: self.quick_action_chosen.emit(p)
            )
            chips.addWidget(button)
        chips.addStretch(1)
        layout.addLayout(chips)

        row = QHBoxLayout()
        self._text = _AutoGrowingTextEdit()
        self._text.send_requested.connect(self.send_requested)
        self._text.cancel_requested.connect(self.cancel_requested)
        self._text.textChanged.connect(self.text_changed)
        row.addWidget(self._text, 1)

        buttons = QVBoxLayout()
        self._send_button = QPushButton()
        self._send_button.setObjectName("PrimaryButton")
        self._send_button.setFixedSize(34, 34)
        self._send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_button.setToolTip(f"{strings.SEND} (Ctrl+Enter)")
        self._send_button.setAccessibleName(strings.SEND)
        self._send_button.clicked.connect(self.send_requested)
        buttons.addWidget(self._send_button)

        self._cancel_button = QPushButton()
        self._cancel_button.setObjectName("IconButton")
        self._cancel_button.setToolTip(f"{strings.CANCEL} (Esc)")
        self._cancel_button.setAccessibleName(strings.CANCEL)
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self.cancel_requested)
        buttons.addWidget(self._cancel_button)
        row.addLayout(buttons)
        layout.addLayout(row)

        hint_row = QHBoxLayout()
        self._hint = QLabel("—")
        self._hint.setObjectName("Muted")
        self._hint.setAccessibleName("Token estimate")
        hint_row.addWidget(self._hint)
        hint_row.addStretch(1)
        hint_row.addWidget(SdkHelpButton("budget"))
        layout.addLayout(hint_row)

        self._reapply_icons()

    # ---- text ----------------------------------------------------------------------

    def text(self) -> str:
        """The current composer text."""
        return self._text.toPlainText()

    def set_text(self, text: str) -> None:
        """Replace the composer text, e.g. from a quick-action chip."""
        self._text.setPlainText(text)
        cursor = self._text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._text.setTextCursor(cursor)
        self._text.setFocus()

    def clear(self) -> None:
        """Empty the composer."""
        self._text.clear()

    def set_busy(self, busy: bool) -> None:
        """Toggle send/cancel availability while a request is in flight."""
        self._send_button.setEnabled(not busy)
        self._cancel_button.setEnabled(busy)
        self._text.setReadOnly(busy)

    # ---- token hint ------------------------------------------------------------------

    def set_token_hint(
        self,
        estimate_tokens: int,
        remaining_tokens: int | None,
        fits: bool | None,
        cost: str = "",
    ) -> None:
        """Show the token estimate, in the same tri-state shape as `ContextBudget`.

        ``cost`` is appended only when the library had pricing on file for the target.
        An absent price is shown as nothing at all rather than as ``$0.00``: a local model
        genuinely costs nothing, and a hosted model with no pricing entry costs *something
        unknown*, and the two must not read the same.
        """
        suffix = f" · {cost}" if cost else ""
        if remaining_tokens is None:
            self._hint.setText(f"~{estimate_tokens:,} tokens{suffix}")
            self._hint.setStyleSheet("")
            return
        text = f"~{estimate_tokens:,} tokens / {remaining_tokens:,} remaining{suffix}"
        self._hint.setText(text)
        if fits is False:
            self._hint.setStyleSheet(f"color: {theme.color('warn')};")
        else:
            self._hint.setStyleSheet("")

    def clear_token_hint(self) -> None:
        """Reset the hint to its unknown state."""
        self._hint.setText("—")
        self._hint.setStyleSheet("")

    def reapply_theme(self) -> None:
        """Re-render themed icons after a theme change."""
        self._reapply_icons()

    def _reapply_icons(self) -> None:
        self._send_button.setIcon(
            themed_icon(self._send_button, "send", color=theme.color("on_accent"))
        )
        self._cancel_button.setIcon(themed_icon(self._cancel_button, "cancel"))
