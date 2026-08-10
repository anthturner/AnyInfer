"""One reliable pane-border implementation for every tabbed demo surface.

Qt's stylesheet renderer drops one-pixel rounded-border arcs on several platform styles.
The tab bar itself still styles correctly, so this widget leaves tab chrome to Qt and paints
only the pane outline as one continuous, topmost path with a gap under the selected tab.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import QTabWidget, QWidget

from .. import theme

__all__ = ["BorderedTabWidget"]


class _TabbedPaneOutline(QWidget):
    """Paint a tab pane outline above its pages so no edge or corner can be erased."""

    _RADIUS = 8.0

    def __init__(self, tabs: BorderedTabWidget) -> None:
        super().__init__(tabs)
        self._tabs = tabs
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt's spelling
        del event
        if self.width() < 3 or self.height() < 3:
            return

        left = 0.5
        right = self.width() - 0.5
        bottom = self.height() - 0.5
        top = max(0.5, min(self._tabs.tabBar().geometry().bottom() + 0.5, bottom - 1.0))
        radius = max(0.0, min(self._RADIUS, (bottom - top) / 2.0))

        path = QPainterPath()
        path.moveTo(left, top)
        current = self._tabs.currentIndex()
        if current >= 0:
            bar = self._tabs.tabBar()
            tab = bar.tabRect(current)
            gap_left = float(bar.x() + tab.left())
            gap_right = float(bar.x() + tab.right() + 1)
            path.lineTo(gap_left, top)
            path.moveTo(gap_right, top)
        path.lineTo(right, top)
        path.lineTo(right, bottom - radius)
        path.quadTo(right, bottom, right - radius, bottom)
        path.lineTo(left + radius, bottom)
        path.quadTo(left, bottom, left, bottom - radius)
        path.lineTo(left, top)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(theme.color("border")), 1.0))
        painter.drawPath(path)


class BorderedTabWidget(QTabWidget):
    """A top-tab widget with the demo's continuous file-folder pane outline."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDocumentMode(False)
        self.setTabPosition(QTabWidget.TabPosition.North)

        self._pane_outline = _TabbedPaneOutline(self)
        self._pane_outline.setGeometry(self.rect())
        self._pane_outline.raise_()
        self._outline_timer = QTimer(self)
        self._outline_timer.setSingleShot(True)
        self._outline_timer.setInterval(0)
        self._outline_timer.timeout.connect(self._sync_tab_outline)
        self.currentChanged.connect(lambda _index: self.update_tab_outline())
        self.tabBar().tabMoved.connect(lambda *_args: self.update_tab_outline())

    def update_tab_outline(self) -> None:
        """Repaint now and once more after Qt settles tab geometry for this event turn."""
        self._sync_tab_outline()
        self._outline_timer.start()

    def _sync_tab_outline(self) -> None:
        """Fit, raise, and repaint the outline against the latest tab-bar geometry."""
        self._pane_outline.setGeometry(self.rect())
        self._pane_outline.raise_()
        self._pane_outline.update()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — Qt's spelling
        """Keep the topmost outline fitted to the whole tab widget."""
        super().resizeEvent(event)
        if hasattr(self, "_pane_outline"):
            self._pane_outline.setGeometry(self.rect())
            self.update_tab_outline()

    def tabInserted(self, index: int) -> None:  # noqa: N802 — Qt's spelling
        """Repaint after inserting a tab changes the selected-gap geometry."""
        super().tabInserted(index)
        if hasattr(self, "_pane_outline"):
            self.update_tab_outline()

    def tabRemoved(self, index: int) -> None:  # noqa: N802 — Qt's spelling
        """Repaint after removing a tab changes the selected-gap geometry."""
        super().tabRemoved(index)
        if hasattr(self, "_pane_outline"):
            self.update_tab_outline()
