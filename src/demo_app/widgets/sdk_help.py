"""The "How is this built?" chip, its dialog, and the library map.

The chip is the demo's teaching device: a small ``</>`` button that sits next to a
surface and opens the `HelpTopic` explaining which public AnyInfer calls implement what
that surface shows, with a copyable plain-Python snippet doing the same thing. The prose
lives in `demo_app.sdk_help`, not here — this module only renders it.

The library map answers the wider question: of everything ``anyinfer`` exports, which
parts does this demo actually exercise, and which does it not? The uncovered list is
computed live from ``anyinfer.__all__`` rather than maintained by hand, so it cannot
quietly go stale as the library grows.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..sdk_help import TOPICS, HelpTopic, covered_symbols, uncovered_symbols

__all__ = ["LibraryMapDialog", "SdkHelpButton", "SdkHelpDialog", "open_topic"]

DOCS_URL = "https://anyinfer.dev/"


def _monospace() -> QFont:
    """The platform's fixed-pitch font, for API names and snippets."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(9)
    return font


class SdkHelpDialog(QDialog):
    """One topic, rendered: summary, the SDK calls involved, and a copyable snippet."""

    def __init__(self, topic: HelpTopic, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"How is this built? — {topic.title}")
        self.setMinimumSize(560, 460)
        self._topic = topic

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(f"<h3>{html.escape(topic.title)}</h3>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        summary = QLabel(topic.summary)
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(summary)

        api_caption = QLabel("<b>The SDK surface behind it</b>")
        api_caption.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(api_caption)

        api_list = QLabel(
            "<br>".join(f"<code>anyinfer.{html.escape(entry)}</code>" for entry in topic.api)
        )
        api_list.setTextFormat(Qt.TextFormat.RichText)
        api_list.setFont(_monospace())
        api_list.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        api_list.setObjectName("ApiList")
        layout.addWidget(api_list)

        snippet_row = QHBoxLayout()
        snippet_caption = QLabel("<b>The same thing in plain Python</b>")
        snippet_caption.setTextFormat(Qt.TextFormat.RichText)
        snippet_row.addWidget(snippet_caption)
        snippet_row.addStretch(1)
        copy_button = QPushButton("Copy")
        copy_button.setAccessibleName("Copy snippet")
        copy_button.clicked.connect(self._copy_snippet)
        snippet_row.addWidget(copy_button)
        layout.addLayout(snippet_row)

        self._snippet = QPlainTextEdit(topic.snippet)
        self._snippet.setReadOnly(True)
        self._snippet.setFont(_monospace())
        self._snippet.setAccessibleName("Code snippet")
        layout.addWidget(self._snippet, 1)

        source = QLabel(
            f"Wired up in <code>{html.escape(topic.demo_source)}</code> — "
            f"<a href='{DOCS_URL}'>full documentation</a>"
        )
        source.setTextFormat(Qt.TextFormat.RichText)
        source.setOpenExternalLinks(True)
        source.setObjectName("Muted")
        layout.addWidget(source)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _copy_snippet(self) -> None:
        QApplication.clipboard().setText(self._topic.snippet)


def open_topic(key: str, parent: QWidget | None = None) -> SdkHelpDialog:
    """Open the help dialog for one topic key. Raises ``KeyError`` for an unknown key."""
    dialog = SdkHelpDialog(TOPICS[key], parent)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show()
    return dialog


class SdkHelpButton(QPushButton):
    """The ``</>`` chip: click to see which AnyInfer calls implement this surface.

    Constructing one for an unknown topic key raises immediately — a chip that opens
    nothing is worse than no chip, and the failure should happen at build time in tests
    rather than on the user's click.
    """

    def __init__(self, topic_key: str, parent: QWidget | None = None) -> None:
        super().__init__("</>", parent)
        topic = TOPICS[topic_key]  # KeyError here is deliberate
        self._topic_key = topic_key
        self.setObjectName("HelpChip")
        self.setFont(_monospace())
        self.setFixedHeight(22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"How is this built? {topic.title} — the AnyInfer calls behind it.")
        self.setAccessibleName(f"How is this built: {topic.title}")
        self.clicked.connect(self._open)

    @property
    def topic_key(self) -> str:
        """The topic this chip opens."""
        return self._topic_key

    def _open(self) -> None:
        open_topic(self._topic_key, self.window())


class LibraryMapDialog(QDialog):
    """Every public ``anyinfer`` symbol, mapped to where this demo demonstrates it.

    Derived live from ``anyinfer.__all__`` and the topic registry. Double-clicking a
    topic opens its help dialog; the "not demonstrated" branch is the demo's honest gaps
    list, not a promise of coverage.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import anyinfer

        self.setWindowTitle("Library map — what this demo exercises")
        self.setMinimumSize(640, 560)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        covered = covered_symbols()
        uncovered = uncovered_symbols()
        total = len(anyinfer.__all__)
        header = QLabel(
            f"<b>This demo exercises {len(covered)} of {total} public "
            f"<code>anyinfer</code> symbols</b>, across {len(TOPICS)} surfaces. "
            "Double-click a surface for the full story; the last branch lists what is "
            "<i>not</i> shown here, honestly."
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setWordWrap(True)
        layout.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Surface", "SDK calls"])
        self._tree.setAccessibleName("Library map")
        self._tree.setColumnWidth(0, 260)
        for topic in TOPICS.values():
            item = QTreeWidgetItem(self._tree, [topic.title, ", ".join(topic.api)])
            item.setData(0, Qt.ItemDataRole.UserRole, topic.key)
            item.setToolTip(1, "\n".join(f"anyinfer.{entry}" for entry in topic.api))
        gaps = QTreeWidgetItem(
            self._tree,
            [f"Not demonstrated here ({len(uncovered)})", ""],
        )
        gaps.setToolTip(
            0,
            "Public symbols no surface of this demo references. Computed live from "
            "anyinfer.__all__ — this list shrinks as the demo grows, and never lies.",
        )
        for name in uncovered:
            QTreeWidgetItem(gaps, [name, ""])
        self._tree.itemDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self._tree, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        docs_button = buttons.addButton(
            "Open documentation", QDialogButtonBox.ButtonRole.ActionRole
        )
        docs_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOCS_URL)))
        layout.addWidget(buttons)

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(key, str) and key:
            open_topic(key, self)
