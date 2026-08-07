"""The conversation list: new/export/import, and per-item rename/delete/export.

Purely a view over `Conversation` objects the owner supplies —
this widget never touches disk itself; `MainWindow` owns
persistence and passes conversations in.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import strings
from ..conversation import Conversation
from .icons import themed_icon

__all__ = ["ConversationSidebar"]


class ConversationSidebar(QWidget):
    """A collapsible list of saved conversations with new/rename/delete/export actions."""

    new_chat_requested = Signal()
    conversation_selected = Signal(str)
    rename_requested = Signal(str, str)
    delete_requested = Signal(str)
    export_requested = Signal(str, str)  # (conversation_id, "json" | "markdown")
    export_all_requested = Signal()
    import_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(strings.CONVERSATIONS_TITLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        top = QHBoxLayout()
        self._new_button = QPushButton(strings.NEW_CHAT)
        self._new_button.setAccessibleName(strings.NEW_CHAT)
        self._new_button.clicked.connect(self.new_chat_requested)
        top.addWidget(self._new_button, 1)

        self._export_all = QPushButton()
        self._export_all.setObjectName("IconButton")
        self._export_all.setToolTip(strings.EXPORT_ALL)
        self._export_all.setAccessibleName(strings.EXPORT_ALL)
        self._export_all.clicked.connect(self.export_all_requested)
        top.addWidget(self._export_all)

        self._import_button = QPushButton()
        self._import_button.setObjectName("IconButton")
        self._import_button.setToolTip(strings.IMPORT)
        self._import_button.setAccessibleName(strings.IMPORT)
        self._import_button.clicked.connect(self.import_requested)
        top.addWidget(self._import_button)
        layout.addLayout(top)

        self._list = QListWidget()
        self._list.setObjectName("ConversationList")
        self._list.setAccessibleName(strings.CONVERSATIONS_TITLE)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list, 1)

        self._reapply_icons()

    # ---- population ----------------------------------------------------------------

    def set_conversations(self, conversations: list[Conversation], *, active_id: str = "") -> None:
        """Replace the list contents, preserving the active selection when possible."""
        self._list.blockSignals(True)
        self._list.clear()
        for conversation in conversations:
            item = QListWidgetItem(_item_label(conversation))
            item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            item.setToolTip(conversation.updated_at.strftime("%Y-%m-%d %H:%M"))
            self._list.addItem(item)
            if conversation.id == active_id:
                item.setSelected(True)
        self._list.blockSignals(False)

    def reapply_theme(self) -> None:
        """Re-render themed icons after a theme change."""
        self._reapply_icons()

    def _reapply_icons(self) -> None:
        self._export_all.setIcon(themed_icon(self._export_all, "download", size=16))
        self._import_button.setIcon(themed_icon(self._import_button, "upload", size=16))

    # ---- interaction -----------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        items = self._list.selectedItems()
        if items:
            self.conversation_selected.emit(str(items[0].data(Qt.ItemDataRole.UserRole)))

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        conversation_id = str(item.data(Qt.ItemDataRole.UserRole))

        menu = QMenu(self)
        rename_action = menu.addAction(strings.RENAME)
        delete_action = menu.addAction(strings.DELETE)
        menu.addSeparator()
        export_json_action = menu.addAction(strings.EXPORT_JSON)
        export_md_action = menu.addAction(strings.EXPORT_MARKDOWN)

        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen is rename_action:
            self._prompt_rename(conversation_id, item.text())
        elif chosen is delete_action:
            self.delete_requested.emit(conversation_id)
        elif chosen is export_json_action:
            self.export_requested.emit(conversation_id, "json")
        elif chosen is export_md_action:
            self.export_requested.emit(conversation_id, "markdown")

    def _prompt_rename(self, conversation_id: str, current_title: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        title, ok = QInputDialog.getText(self, strings.RENAME, "Title:", text=current_title)
        if ok and title.strip():
            self.rename_requested.emit(conversation_id, title.strip())


def _item_label(conversation: Conversation) -> str:
    stamp = conversation.updated_at.strftime("%b %d, %H:%M")
    return f"{conversation.title}\n{stamp}"
