"""The conversation transcript: a scrolling list of message bubbles.

Streaming is the library's primitive, so each assistant bubble is written incrementally
from `TextDelta` events rather than assembled at the end. Markdown is
expensive to re-render on every delta, so deltas accumulate in a plain-text buffer and the
bubble re-renders Markdown only when the turn completes — the buffer is shown verbatim while
streaming.

Reasoning deltas are kept in a per-message collapsible fold because they are explicitly *not*
part of the answer text.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import strings, theme
from ..assets import asset_path
from .icons import themed_icon
from .markdown_renderer import render_markdown

__all__ = [
    "MessageBubble",
    "MessageList",
    "ReasoningFold",
    "TypingIndicator",
    "WelcomeView",
]


class ReasoningFold(QWidget):
    """A per-message collapsible area for reasoning text, hidden until first used."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)

        self._toggle = QToolButton()
        self._toggle.setText("Reasoning (excluded from answer text)")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(False)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._toggle.setAccessibleName("Toggle reasoning")
        self._toggle.setAccessibleDescription(
            "Shows or hides the model's reasoning text, which is excluded from the answer."
        )
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        self._body = QTextEdit()
        self._body.setReadOnly(True)
        self._body.setFont(QFont("Consolas", 9))
        self._body.setVisible(False)
        self._body.setMaximumHeight(160)
        layout.addWidget(self._body)

        self._buffer = ""
        self.setVisible(False)

    def append(self, text: str) -> None:
        """Append a reasoning fragment, revealing the fold on first use."""
        if not self.isVisible():
            self.setVisible(True)
        self._buffer += text
        self._body.setPlainText(self._buffer)

    def _on_toggled(self, checked: bool) -> None:
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self._body.setVisible(checked)


class TypingIndicator(QFrame):
    """A temporary assistant bubble shown between request start and the first delta."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MessageBubbleAssistant")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        label = QLabel("● ● ●")
        label.setObjectName("Muted")
        label.setAccessibleName("Assistant is responding")
        layout.addWidget(label)
        layout.addStretch(1)


class MessageBubble(QFrame):
    """One turn in the transcript: rounded container, Markdown body, optional extras."""

    def __init__(self, role: str, target: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self.setObjectName(
            "MessageBubbleUser" if role == "user" else "MessageBubbleAssistant"
        )
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAccessibleName(f"{'Your' if role == 'user' else 'Assistant'} message")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(4)

        header = QHBoxLayout()
        label = "You" if role == "user" else (f"Assistant ({target})" if target else "Assistant")
        self.header_label = label
        self._header_label = QLabel(f"<b>{html.escape(label)}</b>")
        self._header_label.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(self._header_label)
        header.addStretch(1)

        self._copy_button = QPushButton()
        self._copy_button.setObjectName("IconButton")
        self._copy_button.setFixedSize(24, 24)
        self._copy_button.setToolTip("Copy this message")
        self._copy_button.setAccessibleName("Copy message text")
        self._copy_button.clicked.connect(self._copy)
        header.addWidget(self._copy_button)
        outer.addLayout(header)

        self._body = QTextEdit()
        self._body.setReadOnly(True)
        self._body.setFrameShape(QFrame.Shape.NoFrame)
        self._body.setFont(QFont("Segoe UI", 10))
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._body.document().documentLayout().documentSizeChanged.connect(
            self._resize_to_content
        )
        outer.addWidget(self._body)

        self._reasoning = ReasoningFold()
        outer.addWidget(self._reasoning)

        self._buffer = ""
        self._plain_only = role == "user"
        self._reapply_icon()
        self._resize_to_content()

    # ---- content -----------------------------------------------------------------

    def set_target(self, target: str) -> None:
        """Rename the header to the target that actually produced this turn.

        The bubble opens under the route's primary target; once the result arrives, the
        resolved target may differ — a fallback answered — and the header must say so.
        """
        if self.role != "assistant":
            return
        label = f"Assistant ({target})" if target else "Assistant"
        self.header_label = label
        self._header_label.setText(f"<b>{html.escape(label)}</b>")

    def set_plain_text(self, text: str) -> None:
        """Set the body verbatim (user turns; never Markdown-rendered)."""
        self._buffer = text
        self._body.setPlainText(text)

    def append_delta(self, text: str) -> None:
        """Append a streamed fragment, shown as plain text until the turn completes."""
        self._buffer += text
        self._body.setPlainText(self._buffer)
        cursor = self._body.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._body.setTextCursor(cursor)

    def render_final(self) -> None:
        """Re-render the accumulated buffer as sanitized Markdown, once the turn ends."""
        if self._plain_only:
            return
        self._body.setHtml(render_markdown(self._buffer))

    def append_reasoning(self, text: str) -> None:
        """Forward a reasoning fragment to this bubble's fold."""
        self._reasoning.append(text)

    def text(self) -> str:
        """The raw text this bubble was built from (pre-Markdown for assistant turns)."""
        return self._buffer

    # ---- internals -----------------------------------------------------------------

    def _resize_to_content(self) -> None:
        height = self._body.document().size().height()
        self._body.setFixedHeight(max(24, int(height) + 8))

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._buffer)

    def _reapply_icon(self) -> None:
        self._copy_button.setIcon(themed_icon(self._copy_button, "copy", size=14))

    def reapply_theme(self) -> None:
        """Re-render themed icons after a theme change."""
        self._reapply_icon()


class MessageList(QScrollArea):
    """A scrollable, vertical list of `MessageBubble` widgets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setAccessibleName("Conversation transcript")

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(10)
        self._layout.addStretch(1)
        self.setWidget(container)

        self._rows: list[tuple[QWidget, QWidget]] = []  # (container, content widget)
        self._active: MessageBubble | None = None
        self._typing: TypingIndicator | None = None
        self._empty_state: QWidget | None = None

    # ---- empty state -----------------------------------------------------------------

    def set_empty_state(self, widget: QWidget | None) -> None:
        """Show ``widget`` centered when there are no messages, or clear it with ``None``."""
        if self._empty_state is not None:
            self._layout.removeWidget(self._empty_state)
            self._empty_state.setParent(None)
        self._empty_state = widget
        if widget is not None and not self._rows:
            self._layout.insertWidget(0, widget, 0, Qt.AlignmentFlag.AlignCenter)
            widget.setVisible(True)
        elif widget is not None:
            widget.setVisible(False)

    def _refresh_empty_state(self) -> None:
        if self._empty_state is None:
            return
        self._empty_state.setVisible(not self._rows)

    # ---- transcript --------------------------------------------------------------

    def clear(self) -> None:
        """Remove every bubble and notice from the list."""
        for container, _content in self._rows:
            self._layout.removeWidget(container)
            container.setParent(None)
        self._rows.clear()
        self._active = None
        self._typing = None
        self._refresh_empty_state()

    def add_user_message(self, text: str) -> MessageBubble:
        """Append a right-aligned user bubble."""
        bubble = MessageBubble("user")
        bubble.set_plain_text(text)
        self._add_row(bubble, align_right=True)
        return bubble

    def show_typing(self) -> None:
        """Show the animated typing indicator, replacing any previous one."""
        self.hide_typing()
        self._typing = TypingIndicator()
        self._add_row(self._typing, align_right=False)

    def hide_typing(self) -> None:
        """Remove the typing indicator, if shown."""
        if self._typing is None:
            return
        self._remove_row(self._typing)
        self._typing = None

    def begin_assistant_message(self, target: str) -> MessageBubble:
        """Open an assistant turn, replacing the typing indicator if present."""
        self.hide_typing()
        bubble = MessageBubble("assistant", target)
        self._add_row(bubble, align_right=False)
        self._active = bubble
        return bubble

    def set_active_target(self, target: str) -> None:
        """Retitle the open assistant bubble with the target that actually answered."""
        if self._active is not None:
            self._active.set_target(target)

    def append_delta(self, text: str) -> None:
        """Append a streamed fragment to the open assistant bubble."""
        if self._active is None:
            self._active = self.begin_assistant_message("")
        self._active.append_delta(text)
        self._scroll_to_bottom()

    def append_reasoning(self, text: str) -> None:
        """Forward a reasoning fragment to the open assistant bubble."""
        if self._active is not None:
            self._active.append_reasoning(text)

    def end_assistant_message(self) -> None:
        """Close the streaming turn and render its Markdown; drop it if it stayed empty."""
        self.hide_typing()
        if self._active is None:
            return
        if not self._active.text().strip():
            self._remove_row(self._active)
        else:
            self._active.render_final()
        self._active = None

    def add_notice(self, text: str, *, severity: str = "info") -> None:
        """Append a narrow, full-width notice bar — a failed attempt, a fallback, an error."""
        token = {"error": "danger", "warn": "warn"}.get(severity, "muted")
        label = QLabel(f"<span style='color:{theme.color(token)}'>{html.escape(text)}</span>")
        label.setObjectName("NoticeBar")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setAccessibleName("Notice")
        label.setProperty("_plain_text", text)
        self._add_row(label, align_right=False, stretch=False)
        if self._active is not None:
            # A notice mid-turn (a retry, a fallback) must read as happening *before* the
            # answer that follows it, so the bubble that opened earlier moves after it.
            self._move_row_to_end(self._active)

    def _move_row_to_end(self, widget: QWidget) -> None:
        for container, content in self._rows:
            if content is widget:
                self._layout.removeWidget(container)
                self._layout.insertWidget(self._layout.count() - 1, container)
                self._rows.remove((container, content))
                self._rows.append((container, content))
                break

    def transcript_text(self) -> str:
        """The transcript as plain text, for copying out or asserting on in tests."""
        lines: list[str] = []
        for _container, widget in self._rows:
            if isinstance(widget, MessageBubble):
                lines.append(widget.header_label)
                lines.append(widget.text())
            elif isinstance(widget, QLabel):
                lines.append(str(widget.property("_plain_text") or widget.text()))
        return "\n".join(lines)

    def reapply_theme(self) -> None:
        """Re-render themed icons on every bubble after a theme change."""
        for _container, widget in self._rows:
            if isinstance(widget, MessageBubble):
                widget.reapply_theme()

    # ---- internals -----------------------------------------------------------------

    def _add_row(self, widget: QWidget, *, align_right: bool, stretch: bool = True) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if align_right:
            row.addStretch(1)
            widget.setMaximumWidth(560)
            row.addWidget(widget)
        else:
            widget.setMaximumWidth(720 if stretch else 16_777_215)
            row.addWidget(widget)
            row.addStretch(1)
        container = QWidget()
        container.setLayout(row)
        self._layout.insertWidget(self._layout.count() - 1, container)
        self._rows.append((container, widget))
        self._refresh_empty_state()
        self._scroll_to_bottom()

    def _remove_row(self, widget: QWidget) -> None:
        for container, content in list(self._rows):
            if content is widget:
                self._layout.removeWidget(container)
                container.setParent(None)
                self._rows.remove((container, content))
                break
        self._refresh_empty_state()

    def _scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class WelcomeView(QWidget):
    """The centered empty state shown when a conversation has no messages yet."""

    new_chat_requested = Signal()
    structured_output_requested = Signal()
    fallback_demo_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        self._logo = QSvgWidget()
        self._logo.setFixedSize(300, 65)
        self._logo.setAccessibleName("AnyInfer")
        layout.addWidget(self._logo, 0, Qt.AlignmentFlag.AlignCenter)
        self._reapply_logo()

        tagline = QLabel(strings.WELCOME_TAGLINE)
        tagline.setObjectName("Muted")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        new_chat = QPushButton(strings.WELCOME_NEW_CHAT)
        new_chat.setAccessibleName(strings.WELCOME_NEW_CHAT)
        new_chat.clicked.connect(self.new_chat_requested)
        buttons.addWidget(new_chat)

        structured = QPushButton(strings.WELCOME_STRUCTURED)
        structured.setAccessibleName(strings.WELCOME_STRUCTURED)
        structured.clicked.connect(self.structured_output_requested)
        buttons.addWidget(structured)

        fallback = QPushButton(strings.WELCOME_FALLBACK)
        fallback.setAccessibleName(strings.WELCOME_FALLBACK)
        fallback.clicked.connect(self.fallback_demo_requested)
        buttons.addWidget(fallback)

        button_row = QWidget()
        button_row.setLayout(buttons)
        layout.addWidget(button_row, 0, Qt.AlignmentFlag.AlignCenter)

    def reapply_theme(self) -> None:
        """Swap the wordmark for the light/dark variant matching the active theme."""
        self._reapply_logo()

    def _reapply_logo(self) -> None:
        variant = "dark" if theme.is_dark_active() else "light"
        self._logo.load(str(asset_path(f"anyinfer-horizontal-{variant}.svg")))


