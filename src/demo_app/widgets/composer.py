"""The message input area: token estimate, auto-growing text box, and one action button.

The token estimate sits immediately above the input because they are one instrument: the
estimate is `budget()` run over exactly what the box holds. The single action button is
Send until a request is in flight, then becomes Stop — there is never a dead button on
screen, and the keyboard follows the same state (Ctrl+Enter sends only when idle, Esc
cancels only when busy).
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

__all__ = ["Composer"]

_MAX_LINES = 8


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
    """The full input area: token hint, text box, and the morphing Send/Stop button."""

    send_requested = Signal()
    cancel_requested = Signal()
    text_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)  # the hint hugs the input — they are one instrument

        self._hint = QLabel("—")
        self._hint.setObjectName("Muted")
        self._hint.setAccessibleName("Token estimate")
        layout.addWidget(self._hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._text = _AutoGrowingTextEdit()
        self._text.send_requested.connect(self._on_send_key)
        self._text.cancel_requested.connect(self._on_cancel_key)
        self._text.textChanged.connect(self.text_changed)
        row.addWidget(self._text, 1)

        # One button that is Send when idle and Stop when busy. Never both, never a
        # disabled ghost: the visible action is always the one that works right now.
        self._action_button = QPushButton()
        self._action_button.setObjectName("PrimaryButton")
        self._action_button.setFixedSize(34, 34)
        self._action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action_button.clicked.connect(self._on_action_clicked)
        row.addWidget(self._action_button, 0, Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(SdkHelpButton("budget"), 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

        self._apply_state()

    # ---- text ----------------------------------------------------------------------

    def text(self) -> str:
        """The current composer text."""
        return self._text.toPlainText()

    def set_text(self, text: str) -> None:
        """Replace the composer text, e.g. from a welcome card."""
        self._text.setPlainText(text)
        cursor = self._text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._text.setTextCursor(cursor)
        self._text.setFocus()

    def clear(self) -> None:
        """Empty the composer."""
        self._text.clear()

    # ---- send / cancel state -----------------------------------------------------

    @property
    def busy(self) -> bool:
        """Whether the composer is in its Stop state."""
        return self._busy

    def set_busy(self, busy: bool) -> None:
        """Morph between Send (idle) and Stop (a request is in flight)."""
        if busy == self._busy:
            return
        self._busy = busy
        self._apply_state()

    def _on_action_clicked(self) -> None:
        if self._busy:
            self.cancel_requested.emit()
        else:
            self.send_requested.emit()

    def _on_send_key(self) -> None:
        """Ctrl+Enter sends only while idle; while busy the keystroke is inert."""
        if not self._busy:
            self.send_requested.emit()

    def _on_cancel_key(self) -> None:
        """Esc cancels only while busy; an idle Esc means nothing here."""
        if self._busy:
            self.cancel_requested.emit()

    def _apply_state(self) -> None:
        self._text.setReadOnly(self._busy)
        if self._busy:
            self._action_button.setIcon(
                themed_icon(self._action_button, "stop", color=theme.color("on_accent"))
            )
            self._action_button.setToolTip(f"{strings.CANCEL} (Esc)")
            self._action_button.setAccessibleName(strings.CANCEL)
        else:
            self._action_button.setIcon(
                themed_icon(self._action_button, "send", color=theme.color("on_accent"))
            )
            self._action_button.setToolTip(f"{strings.SEND} (Ctrl+Enter)")
            self._action_button.setAccessibleName(strings.SEND)

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
        """Re-render the themed action icon after a theme change."""
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        # `_apply_state` short-circuits on unchanged state, so the icon refresh is
        # spelled out for theme changes.
        name = "stop" if self._busy else "send"
        self._action_button.setIcon(
            themed_icon(self._action_button, name, color=theme.color("on_accent"))
        )
