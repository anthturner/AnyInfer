"""Small themed line icons for the demo's controls.

The artwork is a set of MIT-licensed `Tabler <https://tabler.io/icons>`_ icons, embedded
as SVG source so the demo ships no asset files. They are drawn with
``stroke="currentColor"``; `themed_icon()` substitutes the widget's palette text color at
render time, which keeps the glyphs legible in both the light and dark theme.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

__all__ = ["themed_icon"]

_SVG_HEADER = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">'
)

_ICONS: dict[str, str] = {
    # tabler:wand — auto-detect is on.
    "wand": (
        '<path d="M6 21l15 -15l-3 -3l-15 15l3 3" />'
        '<path d="M15 6l3 3" />'
        '<path d="M9 3a2 2 0 0 0 2 2a2 2 0 0 0 -2 2a2 2 0 0 0 -2 -2a2 2 0 0 0 2 -2" />'
        '<path d="M19 13a2 2 0 0 0 2 2a2 2 0 0 0 -2 2a2 2 0 0 0 -2 -2a2 2 0 0 0 2 -2" />'
    ),
    # tabler:wand-off — manual override.
    "wand-off": (
        '<path d="M10.5 10.5l-7.5 7.5l3 3l7.5 -7.5m2 -2l5.5 -5.5l-3 -3l-5.5 5.5" />'
        '<path d="M15 6l3 3" />'
        '<path d="M8.433 4.395c.35 -.36 .567 -.852 .567 -1.395a2 2 0 0 0 2 2'
        'c-.554 0 -1.055 .225 -1.417 .589" />'
        '<path d="M18.418 14.41c.36 -.36 .582 -.86 .582 -1.41a2 2 0 0 0 2 2'
        'c-.555 0 -1.056 .226 -1.419 .59" />'
        '<path d="M3 3l18 18" />'
    ),
    # tabler:refresh — reload the model list.
    "refresh": (
        '<path d="M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4" />'
        '<path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4" />'
    ),
    # tabler:send-2 — submit the composer.
    "send": (
        '<path d="M10 14l11 -11" />'
        '<path d="M21 3l-6.5 18a0.55 .55 0 0 1 -1 0l-3.5 -7l-7 -3.5a0.55 .55 0 0 1 0 -1l18 -6.5" />'
    ),
    # tabler:player-stop — cancel a running generation.
    "cancel": (
        '<path d="M5 5m0 2a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v10a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2z" />'
    ),
    # tabler:copy — copy a bubble or code block to the clipboard.
    "copy": (
        '<path d="M7 7m0 2.667a2.667 2.667 0 0 1 2.667 -2.667h8.666a2.667 2.667 0 0 1 2.667 2.667v8.666a2.667 2.667 0 0 1 -2.667 2.667h-8.666a2.667 2.667 0 0 1 -2.667 -2.667z" />'
        '<path d="M4.012 16.737a2.005 2.005 0 0 1 -1.012 -1.737v-10c0 -1.1 .9 -2 2 -2h10c.75 0 1.158 .385 1.5 1" />'
    ),
    # tabler:download — export a conversation.
    "download": (
        '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2" />'
        '<path d="M7 11l5 5l5 -5" />'
        '<path d="M12 4l0 12" />'
    ),
    # tabler:upload — import a conversation.
    "upload": (
        '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2" />'
        '<path d="M7 9l5 -5l5 5" />'
        '<path d="M12 4l0 12" />'
    ),
    # tabler:chevron-up — points at the header; shown when the section is expanded
    # (click to minimize it upward, out of the way).
    "chevron-up": '<path d="M6 15l6 -6l6 6" />',
    # tabler:chevron-down — shown when the section is minimized (click to restore it).
    "chevron-down": '<path d="M6 9l6 6l6 -6" />',
    # tabler:chevron-right — a collapsed row in the configured-engine list.
    "chevron-right": '<path d="M9 6l6 6l-6 6" />',
    # tabler:trash — remove a configured engine from the list.
    "trash": (
        '<path d="M4 7l16 0" />'
        '<path d="M10 11l0 6" />'
        '<path d="M14 11l0 6" />'
        '<path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12" />'
        '<path d="M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3" />'
    ),
}


def themed_icon(widget: QWidget, name: str, *, size: int = 18) -> QIcon:
    """Render one named icon tinted with ``widget``'s current text color.

    Re-call after a theme change — the returned icon is a fixed rendering, not live.
    """
    tint = widget.palette().windowText().color().name()
    svg = f"{_SVG_HEADER}{_ICONS[name]}</svg>".replace("currentColor", tint)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))

    scale = widget.devicePixelRatioF() or 1.0
    pixels = max(1, round(size * scale))
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, pixels, pixels))
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)
