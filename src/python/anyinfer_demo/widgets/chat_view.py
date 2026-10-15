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
import math
import random

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent, QMouseEvent, QResizeEvent, QTextOption
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

#: How wide a bubble may grow before its text wraps, per role.
USER_BUBBLE_MAX_WIDTH = 560
ASSISTANT_BUBBLE_MAX_WIDTH = 720

#: Horizontal space a bubble spends on its own border and padding.
_BUBBLE_CHROME = 26


class _MessageBody(QTextEdit):
    """A read-only text view that is exactly as tall as the text it holds.

    A body that scrolls hides the answer behind scrollbars even when the transcript has
    room to spare, so this view never scrolls: it wraps at whatever width it is given and
    reports the resulting document height as its own fixed height. Its width hint is the
    text's unwrapped width, capped at ``maximum_width``, so short turns stay narrow and
    long ones use the full bubble.
    """

    def __init__(self, maximum_width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._maximum_width = maximum_width
        self._measuring = False
        self._width_cache: int | None = None
        self._width_revision = -1
        self.setObjectName("MessageBody")
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The transcript owns vertical scrolling; an individual message must never grow
        # a second horizontal navigation axis. Code is explicitly wrapped below, and the
        # word-wrap mode breaks any remaining long token at the bubble edge.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.document().setDefaultStyleSheet("pre, code { white-space: pre-wrap; }")
        self.document().setDocumentMargin(0)
        self.document().documentLayout().documentSizeChanged.connect(self._on_document_resized)
        self.sync_size()

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt's spelling
        return QSize(self._natural_width(), self._content_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 — Qt's spelling
        return QSize(0, self._content_height())

    def sync_size(self) -> None:
        """Pin the height to the wrapped document and re-ask the layout for a width."""
        height = self._content_height()
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)
        self.updateGeometry()

    # ---- internals -----------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — Qt's spelling
        """Re-fit the height whenever a new width changes how the text wraps."""
        super().resizeEvent(event)
        if not self._measuring:
            self.sync_size()

    def _on_document_resized(self, *_: object) -> None:
        if not self._measuring:
            self.sync_size()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt's spelling
        """Drop the cached width when the font or style changes its text metrics."""
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._width_revision = -1  # metrics moved; the cached width no longer holds
        super().changeEvent(event)

    def _content_height(self) -> int:
        height = max(1, math.ceil(self.document().size().height()))
        scrollbar = self.horizontalScrollBar()
        if scrollbar.isVisible():
            height += scrollbar.sizeHint().height()  # room for the bar, not under it
        return height

    def _natural_width(self) -> int:
        """The width this text would need unwrapped, clamped to the bubble maximum.

         Measuring lays the document out unwrapped and then back again — two extra layouts
        , so the result is cached per document revision: streaming appends measure once per
         delta no matter how often the layout asks for a size hint.
        """
        document = self.document()
        if self._width_cache is not None and self._width_revision == document.revision():
            return self._width_cache
        self._width_revision = document.revision()
        wrapped_width = document.textWidth()
        # The unwrapped relayout re-emits documentSizeChanged; `_measuring` keeps that from
        # being mistaken for real content growth before the wrapped width is restored.
        self._measuring = True
        try:
            document.setTextWidth(-1)
            ideal = document.idealWidth()
        finally:
            document.setTextWidth(wrapped_width)
            self._measuring = False
        self._width_cache = min(self._maximum_width, math.ceil(ideal) + 1)
        return self._width_cache


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
        self._body.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Reasoning is an aside, not the answer: it stays a bounded, scrolling box.
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
        self.setObjectName("MessageBubbleUser" if role == "user" else "MessageBubbleAssistant")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAccessibleName(f"{'Your' if role == 'user' else 'Assistant'} message")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 10)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(4)
        label = "You" if role == "user" else (f"Assistant ({target})" if target else "Assistant")
        self.header_label = label
        self._target = target
        self._header_label = QLabel()
        self._header_label.setObjectName("BubbleHeader")
        self._header_label.setTextFormat(Qt.TextFormat.RichText)
        # Hovering the speaker reveals which target actually answered; resting state
        # stays quiet so a transcript is not a wall of provider ids.
        self._header_label.installEventFilter(self)
        self._render_header(hovered=False)
        header.addWidget(self._header_label)
        header.addStretch(1)

        self._copy_button = QPushButton()
        self._copy_button.setObjectName("IconButton")
        self._copy_button.setFixedSize(22, 22)
        self._copy_button.setToolTip("Copy this message")
        self._copy_button.setAccessibleName("Copy message text")
        self._copy_button.clicked.connect(self._copy)
        header.addWidget(self._copy_button)
        outer.addLayout(header)

        max_width = USER_BUBBLE_MAX_WIDTH if role == "user" else ASSISTANT_BUBBLE_MAX_WIDTH
        self._body = _MessageBody(max_width - _BUBBLE_CHROME)
        outer.addWidget(self._body)

        self._reasoning = ReasoningFold()
        outer.addWidget(self._reasoning)

        self._buffer = ""
        self._plain_only = role == "user"
        self._reapply_icon()

    # ---- content -----------------------------------------------------------------

    def set_target(self, target: str) -> None:
        """Adopt the target that actually produced this turn.

        The bubble opens under the route's primary target; once the result arrives, the
        resolved target may differ — a fallback answered, and the hover reveal must say
        so.
        """
        if self.role != "assistant":
            return
        self._target = target
        self.header_label = f"Assistant ({target})" if target else "Assistant"
        self._render_header(hovered=self._header_label.underMouse())

    def _render_header(self, *, hovered: bool) -> None:
        if self.role == "user":
            self._header_label.setText("<b>You</b>")
            return
        if hovered and self._target:
            self._header_label.setText(f"<b>Assistant</b> — {html.escape(self._target)}")
        else:
            self._header_label.setText("<b>Assistant</b>")
        if self._target:
            self._header_label.setToolTip(f"Answered by {self._target}")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 — Qt's spelling
        """Show the answering target while the pointer rests on the speaker label."""
        if watched is self._header_label:
            if event.type() == QEvent.Type.Enter:
                self._render_header(hovered=True)
            elif event.type() == QEvent.Type.Leave:
                self._render_header(hovered=False)
        return super().eventFilter(watched, event)

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
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName("Conversation transcript")
        self.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(12)
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

    def empty_state(self) -> QWidget | None:
        """The widget shown when the transcript is empty, if one was set."""
        return self._empty_state

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
            widget.setMaximumWidth(USER_BUBBLE_MAX_WIDTH)
            row.addWidget(widget)
        else:
            widget.setMaximumWidth(ASSISTANT_BUBBLE_MAX_WIDTH if stretch else 16_777_215)
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


class _WelcomeCard(QFrame):
    """One clickable feature card on the welcome screen."""

    clicked = Signal()

    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WelcomeCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(190)
        self.setMinimumHeight(132)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.MinimumExpanding)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("WelcomeCardTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        body = QLabel(description)
        body.setObjectName("Muted")
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addStretch(1)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — Qt's spelling
        """Treat a click anywhere on the card as choosing it."""
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt's spelling
        """Activate with Enter/Space, so the card works from the keyboard too."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


_QUICK_QUESTIONS = (
    "Explain E=mc^2 as if I were a child.",
    "What are the five most populated cities in the United States?",
    "Why is the sky blue?",
    "What's the difference between a crocodile and an alligator?",
    "Give me a fun fact about octopuses.",
    "How many moons does Jupiter have?",
    "What year did the Berlin Wall fall?",
    "What's the tallest mountain in the world?",
)


class WelcomeView(QWidget):
    """The centered empty state: wordmark, tagline, and four guided-tour cards."""

    quick_question_requested = Signal(str)
    structured_output_requested = Signal()
    fallback_demo_requested = Signal()
    tool_loop_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(18)
        layout.setContentsMargins(24, 24, 24, 24)

        self._logo = QSvgWidget()
        self._logo.setFixedSize(300, 65)
        self._logo.setAccessibleName("AnyInfer")
        layout.addWidget(self._logo, 0, Qt.AlignmentFlag.AlignCenter)
        self._reapply_logo()

        tagline = QLabel(strings.WELCOME_TAGLINE)
        tagline.setObjectName("Muted")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)

        cards = QHBoxLayout()
        cards.setSpacing(10)

        quick_question_card = _WelcomeCard(
            strings.WELCOME_QUICK_QUESTION,
            "Send a random trivia question to the selected engine and watch it answer.",
        )
        quick_question_card.clicked.connect(
            lambda: self.quick_question_requested.emit(random.choice(_QUICK_QUESTIONS))
        )
        cards.addWidget(quick_question_card)

        for title, description, signal in (
            (
                strings.WELCOME_STRUCTURED,
                "Enforce a JSON Schema and watch the mechanism and repairs report in.",
                self.structured_output_requested,
            ),
            (
                strings.WELCOME_FALLBACK,
                "Point at the flaky model and watch retry, fallback, and the attempt trail.",
                self.fallback_demo_requested,
            ),
            (
                strings.WELCOME_TOOLS,
                "Hand the model two Python functions and let run_tools() drive the loop.",
                self.tool_loop_requested,
            ),
        ):
            card = _WelcomeCard(title, description)
            card.clicked.connect(signal)
            cards.addWidget(card)

        card_row = QWidget()
        card_row.setLayout(cards)
        layout.addWidget(card_row, 0, Qt.AlignmentFlag.AlignCenter)

        hint = QLabel(
            "Every surface here carries a  </>  chip — click one to see the SDK call behind it."
        )
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

    def reapply_theme(self) -> None:
        """Swap the wordmark for the light/dark variant matching the active theme."""
        self._reapply_logo()

    def _reapply_logo(self) -> None:
        variant = "dark" if theme.is_dark_active() else "light"
        self._logo.load(str(asset_path(f"anyinfer-horizontal-{variant}.svg")))
