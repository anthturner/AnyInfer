"""Tabbed conversations: several chats in flight at once, none of them confused.

Each tab owns a `ChatPage` — its own transcript view plus the per-conversation state a
single-chat window used to keep as window fields. The window routes the engine's *keyed*
generation signals to the page whose conversation started them, which is the whole
demonstration: two tabs can stream from two providers simultaneously and every delta
lands in the transcript it belongs to.

The tab bar adds the affordances a chat app is expected to have: elided titles, a close
button that appears on the hovered or active tab (and turns red under the pointer), and
a context menu mirroring the conversation sidebar's actions.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMenu,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from anyinfer.types.messages import Message

from .. import theme
from ..conversation import Conversation
from .chat_view import MessageList
from .icons import themed_icon

__all__ = ["ChatPage", "ConversationTabs"]

_CLOSE_ICON_SIZE = 12


class ChatPage(QWidget):
    """One conversation's view and in-flight state.

    Plain attributes rather than accessors: this is window-internal state that moved
    out of `MainWindow` when one conversation became many, not a public surface.
    """

    def __init__(self, conversation: Conversation, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.conversation = conversation
        self.messages: list[Message] = list(conversation.messages)
        self.pending_target = ""
        self.streaming_started = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.view = MessageList()
        layout.addWidget(self.view)

    @property
    def key(self) -> str:
        """The routing key for this page's generations: its conversation id."""
        return self.conversation.id


class _TabBar(QTabBar):
    """A tab bar that knows which tab the pointer is over."""

    hovered_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self._hovered = -1

    @property
    def hovered(self) -> int:
        """Index under the pointer, or -1."""
        return self._hovered

    def event(self, event: QEvent) -> bool:
        """Track hover so close buttons can appear only where they are useful."""
        if event.type() in (QEvent.Type.HoverMove, QEvent.Type.HoverEnter):
            index = self.tabAt(event.position().toPoint())  # type: ignore[attr-defined]
            if index != self._hovered:
                self._hovered = index
                self.hovered_changed.emit(index)
        elif event.type() in (QEvent.Type.HoverLeave, QEvent.Type.Leave):
            if self._hovered != -1:
                self._hovered = -1
                self.hovered_changed.emit(-1)
        return super().event(event)


class ConversationTabs(QTabWidget):
    """The tabbed chat area. Emits intents; the window owns what they mean."""

    new_requested = Signal()
    rename_requested = Signal(int)
    save_requested = Signal(int, str)  # (index, "markdown" | "json")
    delete_requested = Signal(int)
    close_requested = Signal(int)
    close_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bar = _TabBar()
        self.setTabBar(self._bar)
        self.setDocumentMode(True)
        self.setMovable(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(True)
        self._bar.hovered_changed.connect(lambda _i: self._refresh_close_buttons())
        self.currentChanged.connect(lambda _i: self._refresh_close_buttons())
        self._bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bar.customContextMenuRequested.connect(self._on_context_menu)

    # ---- pages -------------------------------------------------------------------

    def add_page(self, page: ChatPage, title: str) -> int:
        """Append a page with its own hover-revealed close button."""
        index = self.addTab(page, title)
        self.setTabToolTip(index, title)
        button = QToolButton()
        button.setObjectName("TabClose")
        button.setAccessibleName("Close tab")
        button.setToolTip("Close tab")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoRaise(True)
        button.setIcon(self._close_icon())
        button.clicked.connect(lambda _checked=False, b=button: self._on_close_clicked(b))
        self._bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)
        self._refresh_close_buttons()
        return index

    def page_at(self, index: int) -> ChatPage | None:
        """The `ChatPage` at ``index``, or ``None`` for anything else."""
        widget = self.widget(index)
        return widget if isinstance(widget, ChatPage) else None

    def pages(self) -> list[ChatPage]:
        """Every page, in tab order."""
        return [p for i in range(self.count()) if (p := self.page_at(i)) is not None]

    def current_page(self) -> ChatPage | None:
        """The active page, or ``None`` when there are no tabs."""
        widget = self.currentWidget()
        return widget if isinstance(widget, ChatPage) else None

    def index_of_key(self, key: str) -> int:
        """The tab index holding the conversation ``key``, or -1."""
        for i in range(self.count()):
            page = self.page_at(i)
            if page is not None and page.key == key:
                return i
        return -1

    def set_title(self, index: int, title: str) -> None:
        """Retitle one tab (the bar elides; the tooltip keeps the whole thing)."""
        self.setTabText(index, title)
        self.setTabToolTip(index, title)

    def reapply_theme(self) -> None:
        """Re-render the themed close icons after a theme change."""
        icon = self._close_icon()
        for i in range(self.count()):
            button = self._bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if isinstance(button, QToolButton):
                button.setIcon(icon)

    # ---- internals ---------------------------------------------------------------

    def _close_icon(self) -> QIcon:
        """An ``x`` that turns the theme's danger color while the pointer is on it.

        ``QIcon.Mode.Active`` is what a hovered ``QToolButton`` renders, so the red
        variant rides along in the same icon instead of needing hover event handling.
        """
        normal = themed_icon(self, "x", size=_CLOSE_ICON_SIZE)
        active = themed_icon(self, "x", size=_CLOSE_ICON_SIZE, color=theme.color("danger"))
        icon = QIcon()
        icon.addPixmap(
            normal.pixmap(_CLOSE_ICON_SIZE, _CLOSE_ICON_SIZE), QIcon.Mode.Normal
        )
        icon.addPixmap(
            active.pixmap(_CLOSE_ICON_SIZE, _CLOSE_ICON_SIZE), QIcon.Mode.Active
        )
        return icon

    def _refresh_close_buttons(self) -> None:
        """Show a close button only on the hovered and the active tab."""
        for i in range(self.count()):
            button = self._bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if button is not None:
                button.setVisible(i == self.currentIndex() or i == self._bar.hovered)

    def _on_close_clicked(self, button: QToolButton) -> None:
        for i in range(self.count()):
            if self._bar.tabButton(i, QTabBar.ButtonPosition.RightSide) is button:
                self.close_requested.emit(i)
                return

    def _on_context_menu(self, pos: QPoint) -> None:
        index = self._bar.tabAt(pos)
        menu = QMenu(self)
        new_action = menu.addAction("New")
        menu.addSeparator()
        rename_action = menu.addAction("Rename")
        save_menu = menu.addMenu("Save As")
        save_md = save_menu.addAction("Markdown")
        save_json = save_menu.addAction("JSON")
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        close_action = menu.addAction("Close")
        close_all_action = menu.addAction("Close All")

        for action in (rename_action, delete_action, close_action):
            action.setEnabled(index >= 0)
        save_menu.setEnabled(index >= 0)

        chosen = menu.exec(self._bar.mapToGlobal(pos))
        if chosen is new_action:
            self.new_requested.emit()
        elif chosen is rename_action:
            self.rename_requested.emit(index)
        elif chosen is save_md:
            self.save_requested.emit(index, "markdown")
        elif chosen is save_json:
            self.save_requested.emit(index, "json")
        elif chosen is delete_action:
            self.delete_requested.emit(index)
        elif chosen is close_action:
            self.close_requested.emit(index)
        elif chosen is close_all_action:
            self.close_all_requested.emit()
