"""Tabbed conversations: several chats in flight at once, none of them confused.

Each tab owns a `ChatPage` — its own transcript view plus the per-conversation state a
single-chat window used to keep as window fields. The window routes the engine's *keyed*
generation signals to the page whose conversation started them, which is the whole
demonstration: two tabs can stream from two providers simultaneously and every delta
lands in the transcript it belongs to.

The tab bar adds the affordances a chat app is expected to have: elided titles, a close
button that appears on the hovered or active tab (and turns red under the pointer), and
a context menu for opening, saving, renaming, deleting, and closing tabs.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from anyinfer.types.messages import Message

from .. import theme
from ..conversation import Conversation
from .chat_view import MessageList
from .icons import themed_icon
from .tab_widget import BorderedTabWidget

__all__ = ["ChatPage", "ConversationTabs"]

_CLOSE_ICON_SIZE = 12
_STRIP_BUTTON_SIZE = 28


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


class _CornerBox(QWidget):
    """A fixed-size corner-widget container with a `sizeHint()` that is right immediately.

    `QTabWidget` reads a corner widget's `sizeHint()` synchronously, at the moment it is
    installed, to place it — a plain `QWidget` with a freshly attached layout can't answer
    that yet (a layout's size hint isn't valid until the event loop has run once), which
    left this container pinned at (0, 0) instead of at the tab strip's right edge.
    """

    def __init__(self, size: QSize, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size)

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt's spelling
        return self._size


class ConversationTabs(BorderedTabWidget):
    """The tabbed chat area. Emits intents; the window owns what they mean."""

    new_requested = Signal()
    open_saved_requested = Signal()
    rename_requested = Signal(int)
    save_requested = Signal(int, str)  # (index, "markdown" | "json")
    delete_requested = Signal(int)
    close_requested = Signal(int)
    close_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConversationTabs")
        self._bar = _TabBar()
        self.setTabBar(self._bar)
        self.setMovable(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        # Qt's own scroll buttons still do the scrolling (there is no public API for tab
        # bar scroll offset), but they render huddled together off to one side. The
        # corner-widget pair below stands in for them visually, at the strip's true ends,
        # driven by clicking the real (now invisible) buttons underneath.
        self.setUsesScrollButtons(True)
        self._bar.hovered_changed.connect(lambda _i: self._refresh_close_buttons())
        self.currentChanged.connect(lambda _i: self._refresh_close_buttons())
        self._bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bar.customContextMenuRequested.connect(self._on_context_menu)
        self._bar.tabMoved.connect(lambda *_: self._schedule_scroll_refresh())

        self._new_tab_button = QToolButton()
        self._new_tab_button.setObjectName("NewTabButton")
        self._new_tab_button.setAccessibleName("New chat")
        self._new_tab_button.setToolTip("New chat")
        self._new_tab_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_tab_button.setAutoRaise(True)
        self._new_tab_button.setFixedSize(_STRIP_BUTTON_SIZE, _STRIP_BUTTON_SIZE)
        self._new_tab_button.setIconSize(QSize(_CLOSE_ICON_SIZE, _CLOSE_ICON_SIZE))
        self._new_tab_button.clicked.connect(self.new_requested)

        self._scroll_left = QToolButton()
        self._scroll_left.setObjectName("TabScrollButton")
        self._scroll_left.setAccessibleName("Scroll tabs left")
        self._scroll_left.setToolTip("Scroll tabs left")
        self._scroll_left.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scroll_left.setAutoRaise(True)
        self._scroll_left.setFixedSize(_STRIP_BUTTON_SIZE, _STRIP_BUTTON_SIZE)
        self._scroll_left.setIconSize(QSize(_CLOSE_ICON_SIZE, _CLOSE_ICON_SIZE))
        self._scroll_left.clicked.connect(lambda: self._click_native_scroll_button(-1))

        self._scroll_right = QToolButton()
        self._scroll_right.setObjectName("TabScrollButton")
        self._scroll_right.setAccessibleName("Scroll tabs right")
        self._scroll_right.setToolTip("Scroll tabs right")
        self._scroll_right.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scroll_right.setAutoRaise(True)
        self._scroll_right.setFixedSize(_STRIP_BUTTON_SIZE, _STRIP_BUTTON_SIZE)
        self._scroll_right.setIconSize(QSize(_CLOSE_ICON_SIZE, _CLOSE_ICON_SIZE))
        self._scroll_right.clicked.connect(lambda: self._click_native_scroll_button(1))

        right_corner = _CornerBox(QSize(_STRIP_BUTTON_SIZE * 2, _STRIP_BUTTON_SIZE))
        right_layout = QHBoxLayout(right_corner)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._new_tab_button)
        right_layout.addWidget(self._scroll_right)
        self.setCornerWidget(self._scroll_left, Qt.Corner.TopLeftCorner)
        self.setCornerWidget(right_corner, Qt.Corner.TopRightCorner)

        self._scroll_refresh_timer = QTimer(self)
        self._scroll_refresh_timer.setSingleShot(True)
        self._scroll_refresh_timer.setInterval(0)
        self._scroll_refresh_timer.timeout.connect(self._refresh_scroll_buttons)
        self._bar.tabMoved.connect(lambda *_: self.update_tab_outline())
        self._schedule_scroll_refresh()
        self.reapply_theme()

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
        button.setFixedSize(20, 20)
        button.setIconSize(QSize(_CLOSE_ICON_SIZE, _CLOSE_ICON_SIZE))
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
        """Re-render the themed close, new-tab, and scroll icons after a theme change."""
        icon = self._close_icon()
        for i in range(self.count()):
            button = self._bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if isinstance(button, QToolButton):
                button.setIcon(icon)
        self._new_tab_button.setIcon(themed_icon(self, "plus", size=_CLOSE_ICON_SIZE))
        self._scroll_left.setIcon(themed_icon(self, "chevron-left", size=_CLOSE_ICON_SIZE))
        self._scroll_right.setIcon(themed_icon(self, "chevron-right", size=_CLOSE_ICON_SIZE))
        self.update_tab_outline()

    # ---- tab strip scrolling ------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — Qt's spelling
        """Refresh tab scrolling after the widget is resized."""
        super().resizeEvent(event)
        self._schedule_scroll_refresh()

    def tabInserted(self, index: int) -> None:  # noqa: N802 — Qt's spelling
        """Refresh tab scrolling after a tab is inserted."""
        super().tabInserted(index)
        self._schedule_scroll_refresh()

    def tabRemoved(self, index: int) -> None:  # noqa: N802 — Qt's spelling
        """Refresh tab scrolling after a tab is removed."""
        super().tabRemoved(index)
        self._schedule_scroll_refresh()

    def _native_scroll_buttons(self) -> tuple[QToolButton | None, QToolButton | None]:
        """Qt's own (undocumented, but stable) scroll buttons, left-to-right.

        `setUsesScrollButtons` gives the tab bar a real pair of scroll buttons with no
        public accessor and no public way to trigger a scroll otherwise; the corner-widget
        buttons above stand in for them visually and click these underneath, so the
        scrolling itself stays exactly what Qt does natively.
        """
        left = self._bar.findChild(QToolButton, "ScrollLeftButton")
        right = self._bar.findChild(QToolButton, "ScrollRightButton")
        return left, right

    def _click_native_scroll_button(self, direction: int) -> None:
        left, right = self._native_scroll_buttons()
        button = left if direction < 0 else right
        if button is not None and button.isEnabled():
            button.click()
        self.update_tab_outline()
        self._schedule_scroll_refresh()

    def _schedule_scroll_refresh(self) -> None:
        self._scroll_refresh_timer.start()

    def _refresh_scroll_buttons(self) -> None:
        """Show each custom scroll button only while its native counterpart can act.

        Mirroring `isVisible()` hides both when every tab already fits; mirroring
        `isEnabled()` hides one at a time once scrolled to that end, rather than merely
        graying it out.
        """
        left, right = self._native_scroll_buttons()
        self._scroll_left.setVisible(bool(left and left.isVisible() and left.isEnabled()))
        self._scroll_right.setVisible(bool(right and right.isVisible() and right.isEnabled()))

    # ---- internals ---------------------------------------------------------------

    def _close_icon(self) -> QIcon:
        """An ``x`` that turns the theme's danger color while the pointer is on it.

        ``QIcon.Mode.Active`` is what a hovered ``QToolButton`` renders, so the red
        variant rides along in the same icon instead of needing hover event handling.
        """
        normal = themed_icon(self, "x", size=_CLOSE_ICON_SIZE)
        active = themed_icon(self, "x", size=_CLOSE_ICON_SIZE, color=theme.color("danger"))
        icon = QIcon()
        icon.addPixmap(normal.pixmap(_CLOSE_ICON_SIZE, _CLOSE_ICON_SIZE), QIcon.Mode.Normal)
        icon.addPixmap(active.pixmap(_CLOSE_ICON_SIZE, _CLOSE_ICON_SIZE), QIcon.Mode.Active)
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
        menu, actions = self._make_context_menu(index)
        chosen = menu.exec(self._bar.mapToGlobal(pos))
        if chosen is actions["new"]:
            self.new_requested.emit()
        elif chosen is actions["open"]:
            self.open_saved_requested.emit()
        elif chosen is actions["rename"]:
            self.rename_requested.emit(index)
        elif chosen is actions["save_md"]:
            self.save_requested.emit(index, "markdown")
        elif chosen is actions["save_json"]:
            self.save_requested.emit(index, "json")
        elif chosen is actions["delete"]:
            self.delete_requested.emit(index)
        elif chosen is actions["close"]:
            self.close_requested.emit(index)
        elif chosen is actions["close_all"]:
            self.close_all_requested.emit()

    def _make_context_menu(self, index: int) -> tuple[QMenu, dict[str, QAction]]:
        """Build the tab menu for ``index``; split out so its availability is testable."""
        menu = QMenu(self)
        new_action = menu.addAction("New")
        open_saved_action = menu.addAction("Open Saved…")
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
        return menu, {
            "new": new_action,
            "open": open_saved_action,
            "rename": rename_action,
            "save_md": save_md,
            "save_json": save_json,
            "delete": delete_action,
            "close": close_action,
            "close_all": close_all_action,
        }
