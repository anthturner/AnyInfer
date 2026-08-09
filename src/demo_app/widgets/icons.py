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
    # tabler:x — close a tab or dismiss something.
    "x": '<path d="M18 6l-12 12" /><path d="M6 6l12 12" />',
    # tabler:player-stop-filled — cancel a running generation (filled square reads as
    # "stop", where the outline version rendered as a broken-looking empty box).
    "stop": (
        '<path d="M17 4h-10a3 3 0 0 0 -3 3v10a3 3 0 0 0 3 3h10a3 3 0 0 0 3 -3v-10'
        'a3 3 0 0 0 -3 -3z" fill="currentColor" stroke="none" />'
    ),
    # tabler:eraser — clear the telemetry timeline.
    "eraser": (
        '<path d="M19 20h-10.5l-4.21 -4.3a1 1 0 0 1 0 -1.41l10 -10a1 1 0 0 1 1.41 0l5 5'
        'a1 1 0 0 1 0 1.41l-9.2 9.3" />'
        '<path d="M18 13.3l-6.3 -6.3" />'
    ),
    # tabler:book-2 — documentation links.
    "book": (
        '<path d="M19 4v16h-12a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2h12z" />'
        '<path d="M19 16h-12a2 2 0 0 0 -2 2" />'
        '<path d="M9 8h6" />'
    ),
    # tabler:info-circle — the About dialog.
    "info": (
        '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0" />'
        '<path d="M12 9h.01" />'
        '<path d="M11 12h1v4h1" />'
    ),
    # tabler:license — third-party licenses.
    "license": (
        '<path d="M15 21h-9a3 3 0 0 1 -3 -3v-1h10v2a2 2 0 0 0 4 0v-14a2 2 0 1 1 2 2h-2'
        'm2 -4h-11a3 3 0 0 0 -3 3v11" />'
        '<path d="M9 7l4 0" />'
        '<path d="M9 11l4 0" />'
    ),
    # tabler:activity — the telemetry section.
    "activity": '<path d="M3 12h4l3 8l4 -16l3 8h4" />',
    # tabler:braces — the structured-output section.
    "braces": (
        '<path d="M7 4a2 2 0 0 0 -2 2v3a2 3 0 0 1 -2 3a2 3 0 0 1 2 3v3a2 2 0 0 0 2 2" />'
        '<path d="M17 4a2 2 0 0 1 2 2v3a2 3 0 0 0 2 3a2 3 0 0 0 -2 3v3a2 2 0 0 1 -2 2" />'
    ),
    # tabler:server-2 — the providers section.
    "server": (
        '<path d="M3 4m0 3a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v2a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3z" />'
        '<path d="M3 12m0 3a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v2a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3z" />'
        '<path d="M7 8l0 .01" /><path d="M7 16l0 .01" />'
    ),
    # tabler:focus-2 — the target-inspector section.
    "target": (
        '<path d="M12 12m-.5 0a.5 .5 0 1 0 1 0a.5 .5 0 1 0 -1 0" />'
        '<path d="M12 12m-7 0a7 7 0 1 0 14 0a7 7 0 1 0 -14 0" />'
        '<path d="M12 3v2" /><path d="M3 12h2" /><path d="M12 19v2" /><path d="M19 12h2" />'
    ),
    # tabler:tool — the tool-loop section.
    "tool": (
        '<path d="M7 10h3v-3l-3.5 -3.5a6 6 0 0 1 8 8l6 6a2 2 0 0 1 -3 3l-6 -6'
        'a6 6 0 0 1 -8 -8l3.5 3.5" />'
    ),
    # tabler:map-2 — the library map.
    "map": (
        '<path d="M12 18.5l-3 -1.5l-6 3v-13l6 -3l6 3l6 -3v7.5" />'
        '<path d="M9 4v13" /><path d="M15 7v5.5" />'
        '<path d="M21.121 20.121a3 3 0 1 0 -4.242 0c.418 .419 1.125 1.045 2.121 1.879'
        'c1.051 -.89 1.759 -1.516 2.121 -1.879z" />'
        '<path d="M19 18v.01" />'
    ),
    # tabler:trash — remove a configured engine from the list.
    "trash": (
        '<path d="M4 7l16 0" />'
        '<path d="M10 11l0 6" />'
        '<path d="M14 11l0 6" />'
        '<path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12" />'
        '<path d="M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3" />'
    ),
}


def themed_icon(widget: QWidget, name: str, *, size: int = 18, color: str | None = None) -> QIcon:
    """Render one named icon tinted with ``widget``'s current text color.

    ``color`` overrides the palette lookup — a filled accent button needs its icon in the
    on-accent color, which is not any widget's windowText.

    Re-call after a theme change — the returned icon is a fixed rendering, not live.
    """
    tint = color or widget.palette().windowText().color().name()
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
