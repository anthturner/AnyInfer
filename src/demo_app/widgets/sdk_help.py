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

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QPaintEvent,
    QPainter,
    QResizeEvent,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..sdk_help import TOPICS, HelpTopic, covered_symbols, uncovered_symbols
from .icons import themed_icon

__all__ = ["LibraryMapDialog", "SdkHelpButton", "SdkHelpDialog", "open_topic"]

DOCS_URL = "https://anyinfer.dev/"


def _monospace() -> QFont:
    """The platform's fixed-pitch font, for API names and snippets."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(9)
    return font


def _stripe_color() -> QColor:
    """A zebra-stripe tint derived from the active theme, not a hardcoded color.

    Blended from the live `surface`/`border` tokens rather than a fixed palette entry, so
    every custom theme gets a stripe that reads as "this theme, slightly recessed" instead
    of a mismatched gray.
    """
    surface = QColor(theme.color("surface"))
    border = QColor(theme.color("border"))
    mix = 0.35
    return QColor(
        round(surface.red() + (border.red() - surface.red()) * mix),
        round(surface.green() + (border.green() - surface.green()) * mix),
        round(surface.blue() + (border.blue() - surface.blue()) * mix),
    )


def _inset_separator() -> QFrame:
    """A hairline with side margins, separating prose from the reference material."""
    line = QFrame()
    line.setObjectName("InsetSeparator")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


class _LineNumberArea(QWidget):
    """The gutter a `_CodeView` paints its line numbers into."""

    def __init__(self, view: _CodeView) -> None:
        super().__init__(view)
        self._view = view

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt's spelling
        return QSize(self._view.gutter_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt's spelling
        self._view.paint_gutter(event)


class _CodeView(QPlainTextEdit):
    """A read-only snippet viewer with a line-number gutter and a hover copy button.

    The numbers live in a painted margin, not in the document, so selecting and copying
    the code never picks them up. The copy button sits over the top-right corner and
    only appears while the pointer is inside the viewer — reference chrome, not a
    standing control.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("CodeView")
        self.setReadOnly(True)
        self.setFont(_monospace())
        self.setAccessibleName("Code snippet")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._gutter = _LineNumberArea(self)
        self.blockCountChanged.connect(lambda _n: self._update_gutter_width())
        self.updateRequest.connect(self._on_update_request)
        self._update_gutter_width()

        self._copy_button = QPushButton(self)
        self._copy_button.setObjectName("IconButton")
        self._copy_button.setFixedSize(28, 28)
        self._copy_button.setToolTip("Copy snippet")
        self._copy_button.setAccessibleName("Copy snippet")
        self._copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_button.clicked.connect(self._copy)
        self._copy_button.setVisible(False)
        self._apply_stripes()
        self.reapply_theme()

    def reapply_theme(self) -> None:
        """Re-render the themed copy icon and zebra stripes after a theme change."""
        self._copy_button.setIcon(themed_icon(self._copy_button, "copy", size=16))
        self._apply_stripes()
        self._gutter.update()

    # ---- zebra striping ------------------------------------------------------------

    def _apply_stripes(self) -> None:
        """Tint every other line so a long snippet is easier to track by eye.

        `QTextEdit.ExtraSelection` with `FullWidthSelection` paints the highlight across
        the whole line regardless of its text length — the built-in mechanism for a
        current-line highlight, reused here for every odd line instead of just one. The
        gutter is a separate sibling widget with no selections of its own, so `paint_gutter`
        below fills the matching rects by hand to keep the stripes continuous under it.
        """
        stripe = _stripe_color()
        selections = []
        block = self.document().firstBlock()
        while block.isValid():
            if block.blockNumber() % 2 == 1:
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(stripe)
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                selection.cursor = QTextCursor(block)
                selections.append(selection)
            block = block.next()
        self.setExtraSelections(selections)

    # ---- gutter --------------------------------------------------------------------

    def gutter_width(self) -> int:
        """Width for the widest line number currently needed."""
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def paint_gutter(self, event: QPaintEvent) -> None:
        """Paint the zebra stripes and visible block numbers, muted, right-aligned."""
        painter = QPainter(self._gutter)
        painter.setFont(self.font())
        stripe = _stripe_color()
        block = self.firstVisibleBlock()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if block.blockNumber() % 2 == 1:
                    painter.fillRect(0, top, self._gutter.width(), bottom - top, stripe)
                painter.setPen(theme.color("muted"))
                painter.drawText(
                    0,
                    top,
                    self._gutter.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block.blockNumber() + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
        painter.end()

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    # ---- copy-on-hover ---------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — Qt's spelling
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._gutter.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))
        self._copy_button.move(rect.right() - self._copy_button.width() - 6, rect.top() + 6)

    def enterEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt's spelling
        self._copy_button.setVisible(True)
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt's spelling
        self._copy_button.setVisible(False)
        super().leaveEvent(event)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.toPlainText())


class SdkHelpDialog(QDialog):
    """One topic, rendered: summary, the SDK calls involved, and a copyable snippet."""

    def __init__(self, topic: HelpTopic, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"How is this built? — {topic.title}")
        self.setMinimumSize(560, 480)
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

        layout.addWidget(_inset_separator())

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

        layout.addSpacing(8)  # the API list and the snippet are different artifacts

        snippet_caption = QLabel("<b>The same thing in plain Python</b>")
        snippet_caption.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(snippet_caption)

        self._snippet = _CodeView(topic.snippet)
        layout.addWidget(self._snippet, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        source = QLabel(f"Wired up in <code>{html.escape(topic.demo_source)}</code>")
        source.setTextFormat(Qt.TextFormat.RichText)
        source.setWordWrap(True)
        source.setObjectName("Muted")
        footer.addWidget(source, 1)

        docs_button = QPushButton("More Documentation")
        docs_button.setAccessibleName("More Documentation")
        docs_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOCS_URL)))
        footer.addWidget(docs_button)

        close_button = QPushButton("Close")
        close_button.setAccessibleName("Close")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

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
