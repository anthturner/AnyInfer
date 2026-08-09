"""Theming: the AnyInfer brand palette, plus a handful of named custom palettes.

The tokens for ``"light"``/``"dark"`` are a Qt translation of
``docs/assets/anyinfer-palette.css`` — the same deep-teal-and-amber palette the project uses
on the web. The user preference is one of ``"system"``, ``"light"``, ``"dark"``, or one of the
`CUSTOM_THEMES` keys; ``"system"`` resolves through Qt's color scheme hint and follows
the OS live via ``QStyleHints.colorSchemeChanged``. A custom theme is a single, self-contained
palette (not a light/dark pair) — picking one is a deliberate departure from OS-following.

Widgets that insert colored rich text at runtime (the transcript's notices) read the active
tokens through `color()`; everything else is styled by the application-wide stylesheet
and palette, so a theme switch restyles the whole window in one call to
`apply_theme()`.
"""

from __future__ import annotations

from string import Template
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

__all__ = [
    "CUSTOM_THEMES",
    "CUSTOM_THEMES_MENU",
    "CUSTOM_THEME_LABELS",
    "DEFAULT_THEME_CHOICES",
    "THEME_CHOICES",
    "apply_theme",
    "color",
    "is_dark_active",
    "palette_colors",
    "resolve_dark",
    "resolve_theme",
    "stylesheet",
]

DEFAULT_THEME_CHOICES: tuple[tuple[str, str], ...] = (
    ("system", "System default"),
    ("light", "Light"),
    ("dark", "Dark"),
)
"""``(preference value, menu label)`` pairs for the OS-following defaults, in menu order."""

# docs/assets/anyinfer-palette.css — brand constants shared by the light and dark themes.
_TEAL = "#2C7A6F"
_TEAL_DEEP = "#0B3B3C"
_TEAL_BRIGHT = "#4FBFA8"
_AMBER = "#E8963C"
_GOLD = "#F0C86A"

_LIGHT: dict[str, str] = {
    "bg": "#ffffff",
    "surface": "#f6f8fa",
    "border": "#d1d9e0",
    "text": _TEAL_DEEP,
    "muted": "#59636e",
    "accent": _TEAL,
    "accent_hover": "#1f6f63",
    "accent_bg": "#eaf4f1",
    "accent_border": "#a8cfc6",
    "on_accent": "#ffffff",
    "link": "#1f6f63",
    "amber": _AMBER,
    "gold": _GOLD,
    "on_amber": _TEAL_DEEP,
    "ok": "#157347",
    "warn": "#9a6700",
    "danger": "#b42318",
}

_DARK: dict[str, str] = {
    "bg": "#0d1117",
    "surface": "#151b23",
    "border": "#3d444d",
    "text": "#f0f6fc",
    "muted": "#9198a1",
    "accent": _TEAL_BRIGHT,
    "accent_hover": "#7fd8c4",
    "accent_bg": "#0f2b28",
    "accent_border": "#275d54",
    "on_accent": _TEAL_DEEP,
    "link": _TEAL_BRIGHT,
    "amber": _AMBER,
    "gold": _GOLD,
    "on_amber": _TEAL_DEEP,
    "ok": "#4cc38a",
    "warn": "#d9a23d",
    "danger": "#ef7f78",
}

# Named custom palettes: each is a complete, self-contained token set (not a light/dark
# pair) — choosing one is an explicit departure from the OS-following defaults above.
# Every palette keeps the full token surface so the shared stylesheet renders identically;
# only the actual color values differ.
CUSTOM_THEMES: dict[str, dict[str, str]] = {
    "slate": {
        "bg": "#1a1d24",
        "surface": "#22262f",
        "border": "#383d4a",
        "text": "#e8eaf0",
        "muted": "#9198a8",
        "accent": "#7c93f0",
        "accent_hover": "#9cadf5",
        "accent_bg": "#262c42",
        "accent_border": "#4a5480",
        "on_accent": "#0f1117",
        "link": "#7c93f0",
        "amber": "#e8963c",
        "gold": "#f0c86a",
        "on_amber": "#1a1d24",
        "ok": "#5fd08a",
        "warn": "#e0b04a",
        "danger": "#f0776e",
    },
    "rose": {
        "bg": "#fff7f8",
        "surface": "#fdeef0",
        "border": "#f0d2d8",
        "text": "#5c1a2b",
        "muted": "#8a5c68",
        "accent": "#c2385a",
        "accent_hover": "#a12c49",
        "accent_bg": "#fbe2e7",
        "accent_border": "#e8a8ba",
        "on_accent": "#ffffff",
        "link": "#a12c49",
        "amber": "#d9762f",
        "gold": "#e8a94f",
        "on_amber": "#3a1208",
        "ok": "#2f8f5b",
        "warn": "#a16a1f",
        "danger": "#b8203f",
    },
    "forest": {
        "bg": "#0f1a12",
        "surface": "#16241a",
        "border": "#2c3f31",
        "text": "#e3f0e6",
        "muted": "#8fa896",
        "accent": "#5fbf7a",
        "accent_hover": "#7dd696",
        "accent_bg": "#1a2f20",
        "accent_border": "#3a6047",
        "on_accent": "#0a140c",
        "link": "#5fbf7a",
        "amber": "#e0a23c",
        "gold": "#f0ca6e",
        "on_amber": "#0f1a12",
        "ok": "#6bd68a",
        "warn": "#e0b04a",
        "danger": "#e87d70",
    },
    "ocean": {
        "bg": "#f2f9fc",
        "surface": "#e4f2f8",
        "border": "#bfdde9",
        "text": "#0b3b52",
        "muted": "#4d7085",
        "accent": "#1a7fa8",
        "accent_hover": "#136181",
        "accent_bg": "#d6ecf4",
        "accent_border": "#8fc4da",
        "on_accent": "#ffffff",
        "link": "#136181",
        "amber": "#d9822f",
        "gold": "#eab35a",
        "on_amber": "#0b3b52",
        "ok": "#1f8f6b",
        "warn": "#9a6d1a",
        "danger": "#c23b2f",
    },
    "sunset": {
        "bg": "#1c1410",
        "surface": "#261c16",
        "border": "#423024",
        "text": "#f5e6d8",
        "muted": "#b8977f",
        "accent": "#e8703c",
        "accent_hover": "#f28a5a",
        "accent_bg": "#3a271a",
        "accent_border": "#7a4d33",
        "on_accent": "#1c1410",
        "link": "#f0a15c",
        "amber": "#e8963c",
        "gold": "#f0c86a",
        "on_amber": "#1c1410",
        "ok": "#7ac97a",
        "warn": "#e8b054",
        "danger": "#e8654f",
    },
}
"""Custom palette key -> full token table. Order here is the menu's display order."""

CUSTOM_THEME_LABELS: dict[str, str] = {
    "slate": "Slate",
    "rose": "Rose",
    "forest": "Forest",
    "ocean": "Ocean",
    "sunset": "Sunset",
}
"""Custom palette key -> menu label, kept separate so `CUSTOM_THEMES` stays pure data."""

CUSTOM_THEMES_MENU: tuple[tuple[str, str], ...] = tuple(
    (key, CUSTOM_THEME_LABELS[key]) for key in CUSTOM_THEMES
)
"""``(preference value, menu label)`` pairs for the custom palettes, in menu order."""

THEME_CHOICES: tuple[tuple[str, str], ...] = (*DEFAULT_THEME_CHOICES, *CUSTOM_THEMES_MENU)
"""Every ``(preference value, menu label)`` pair, defaults first, for callers that want a
flat list; `_build_menu()` renders the two groups —
custom themes first, defaults after a separator — instead of using this directly."""

_active: dict[str, str] = dict(_LIGHT)
_active_is_dark: bool = False

# QSS braces clash with str.format, so tokens are $-substituted instead.
_STYLESHEET = Template("""
QWidget {
    background: $bg;
    color: $text;
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
}
QMenuBar, QMenu { background: $surface; }
QMenuBar { border-bottom: 1px solid $border; }
QMenu { border: 1px solid $border; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 20px; border-radius: 6px; }
QMenu::item:selected, QMenuBar::item:selected { background: $accent_bg; color: $accent; }
QMenu::separator { height: 1px; background: $border; margin: 6px 12px; }

QLabel { background: transparent; }
QLabel#Muted { color: $muted; }
QLabel#ErrorText { color: $danger; }
QLabel#Caption { color: $muted; padding: 6px 0; }

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QTreeWidget, QListWidget {
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 4px 8px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QListWidget:focus, QTreeWidget:focus {
    border: 1px solid $accent;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QPlainTextEdit:disabled {
    color: $muted;
    background: $bg;
}
QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    selection-background-color: $accent_bg;
    selection-color: $text;
    padding: 4px;
}

QPushButton {
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    min-height: 30px;
    padding: 6px 16px;
}
QPushButton:hover { border-color: $accent; background: $accent_bg; }
QPushButton:pressed { background: $accent_border; }
QPushButton:disabled { color: $muted; background: $bg; }
QPushButton:default {
    background: $amber;
    border-color: $amber;
    color: $on_amber;
    font-weight: 600;
}
QPushButton:default:hover { background: $gold; border-color: $gold; }
QPushButton:default:disabled { background: $surface; border-color: $border; color: $muted; }
QPushButton#IconButton { padding: 4px; border-radius: 6px; border: none; background: transparent; }
QPushButton#IconButton:hover { background: $accent_bg; border: 1px solid $accent_border; }
/* A disclosure reads as a label you can click, not as a command: chrome here would give
   "Advanced" the same weight as the fields it is there to keep out of the way. */
QPushButton#DisclosureButton {
    border: none;
    background: transparent;
    color: $muted;
    padding: 4px 6px;
    text-align: left;
}
QPushButton#DisclosureButton:hover { color: $text; background: transparent; }

QGroupBox {
    border: 1px solid $border;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 8px;
    background: $bg;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: $accent;
}

QHeaderView::section {
    background: $surface;
    color: $muted;
    border: none;
    border-bottom: 1px solid $border;
    padding: 6px 8px;
}
QTreeWidget::item:selected { background: $accent_bg; color: $text; }

QSplitter::handle { background: $border; }
QSplitter::handle:horizontal { width: 2px; }
QSplitter::handle:vertical { height: 2px; }
QStatusBar {
    background: $surface;
    border-top: 1px solid $border;
    color: $muted;
    padding: 4px 10px;
}
QScrollArea { border: none; background: transparent; }
QScrollArea#TelemetryScroll {
    border: 1px solid $border;
    border-radius: 8px;
    background: $surface;
}
QToolTip {
    background: $surface;
    color: $text;
    border: 1px solid $accent_border;
    border-radius: 6px;
    padding: 6px;
}

/* The message body is the bubble's content, not a field inside it. */
QTextEdit#MessageBody {
    background: transparent;
    border: none;
    padding: 0;
}

QFrame#MessageBubbleUser {
    background: $accent_bg;
    border: 1px solid $accent_border;
    border-radius: 16px;
}
QFrame#MessageBubbleAssistant {
    background: $surface;
    border: 1px solid $border;
    border-radius: 16px;
}
QFrame#TelemetryCard {
    background: $surface;
    border: 1px solid $border;
    border-radius: 10px;
}
QFrame#TelemetryCard:hover { border-color: $accent_border; }
QLabel#NoticeBar { color: $muted; font-style: italic; }
QListWidget#ConversationList {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget#ConversationList::item {
    border-radius: 8px;
    padding: 8px;
    margin: 3px 0;
}
QListWidget#ConversationList::item:selected {
    background: $accent_bg;
    color: $text;
}

QFrame#CollapsibleSection {
    border: 1px solid $border;
    border-radius: 10px;
    background: $bg;
}
QFrame#CollapsibleSectionHeader {
    background: $surface;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
    border-bottom: 1px solid $border;
}
QLabel#CollapsibleSectionTitle {
    color: $accent;
    font-weight: 600;
}

/* Generic surfaced cards used by the demo's newer layouts. */
QFrame#SectionCard {
    background: $surface;
    border: 1px solid $border;
    border-radius: 10px;
}
QFrame#ProviderCard {
    background: $surface;
    border: 1px solid $border;
    border-radius: 10px;
}

/* Slim, rounded scrollbars that match the palette instead of the platform default. */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle {
    background: $border;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::handle:hover { background: $accent_border; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* Tabs (the Local models dialog). */
QTabWidget::pane {
    border: 1px solid $border;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: $muted;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 16px;
    margin-right: 2px;
}
QTabBar::tab:hover { color: $text; background: $accent_bg; }
QTabBar::tab:selected {
    background: $surface;
    color: $accent;
    border-color: $border;
    font-weight: 600;
}

QProgressBar {
    background: $surface;
    border: 1px solid $border;
    border-radius: 7px;
    height: 14px;
    text-align: center;
    color: $text;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: 6px;
}

QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid $border;
    border-radius: 5px;
    background: $surface;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked {
    background: $accent;
    border-color: $accent;
}

QToolButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 3px 6px;
    color: $muted;
}
QToolButton:hover { background: $accent_bg; color: $text; }

/* Quick-action chips under the composer: pill-shaped invitations, not commands. */
QPushButton#ChipButton {
    background: $surface;
    border: 1px solid $border;
    border-radius: 14px;
    padding: 4px 14px;
    min-height: 0;
    color: $muted;
}
QPushButton#ChipButton:hover {
    border-color: $accent;
    color: $accent;
    background: $accent_bg;
}

/* The send button: the one filled, unmistakable action on the screen. */
QPushButton#PrimaryButton {
    background: $accent;
    border: 1px solid $accent;
    border-radius: 17px;
    color: $on_accent;
    padding: 4px;
}
QPushButton#PrimaryButton:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#PrimaryButton:disabled { background: $surface; border-color: $border; }

/* "How is this built?" chips: quiet until you look for them. */
QPushButton#HelpChip {
    background: transparent;
    border: 1px solid $accent_border;
    border-radius: 10px;
    color: $accent;
    padding: 0 8px;
    min-height: 0;
    font-size: 8pt;
}
QPushButton#HelpChip:hover { background: $accent_bg; border-color: $accent; }
QLabel#ApiList {
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 8px;
}

/* Welcome feature cards. */
QFrame#WelcomeCard {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#WelcomeCard:hover { border-color: $accent; background: $accent_bg; }
QLabel#WelcomeCardTitle { font-weight: 600; color: $accent; }
QLabel#BubbleHeader { color: $muted; font-size: 8.5pt; }
""")


def palette_colors(dark: bool) -> dict[str, str]:
    """The token table for one resolved appearance."""
    return dict(_DARK if dark else _LIGHT)


def color(token: str) -> str:
    """The active theme's value for one token, for runtime-inserted rich text."""
    return _active[token]


def resolve_dark(app: Any, preference: str) -> bool:
    """Resolve an OS-following preference to a concrete appearance.

    Only meaningful for ``"system"``/``"light"``/``"dark"``; custom themes are a fixed
    palette regardless of the OS, so callers resolving one of those never reach here via
    `resolve_theme()`.
    """
    if preference == "dark":
        return True
    if preference == "light":
        return False
    hints = app.styleHints() if app is not None else None
    if hints is not None:
        scheme = hints.colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    # No scheme hint: infer from whichever palette the platform gave us.
    palette = app.palette() if app is not None else None
    if palette is None:
        return False
    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    return bool(window.lightnessF() < text.lightnessF())


def resolve_theme(app: Any, preference: str) -> dict[str, str]:
    """Resolve any theme preference — OS-following or a named custom palette — to tokens."""
    custom = CUSTOM_THEMES.get(preference)
    if custom is not None:
        return dict(custom)
    return palette_colors(resolve_dark(app, preference))


def is_dark_active() -> bool:
    """Whether the currently active theme reads as a dark surface.

    Custom palettes are not OS-tracked, so this reflects the palette actually installed by
    the last `apply_theme()` call, not a live OS query — it is what asset selection
    (e.g. picking a light/dark logo variant) should read.
    """
    return _active_is_dark


def stylesheet(colors: dict[str, str]) -> str:
    """Render the application stylesheet for one token table."""
    return _STYLESHEET.substitute(colors)


def _qt_palette(colors: dict[str, str]) -> QPalette:
    """A QPalette matching the tokens, so native pieces (scrollbars, views) follow too."""
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: colors["bg"],
        QPalette.ColorRole.WindowText: colors["text"],
        QPalette.ColorRole.Base: colors["surface"],
        QPalette.ColorRole.AlternateBase: colors["bg"],
        QPalette.ColorRole.Text: colors["text"],
        QPalette.ColorRole.Button: colors["surface"],
        QPalette.ColorRole.ButtonText: colors["text"],
        QPalette.ColorRole.Highlight: colors["accent"],
        QPalette.ColorRole.HighlightedText: colors["on_accent"],
        QPalette.ColorRole.Link: colors["link"],
        QPalette.ColorRole.PlaceholderText: colors["muted"],
        QPalette.ColorRole.ToolTipBase: colors["surface"],
        QPalette.ColorRole.ToolTipText: colors["text"],
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["muted"]))
    return palette


def apply_theme(app: Any, preference: str) -> dict[str, str]:
    """Apply a theme preference application-wide and return the active tokens.

    ``preference`` is ``"system"``/``"light"``/``"dark"`` or one of the `CUSTOM_THEMES`
    keys. Sets the Fusion style once (the platform-native style ignores palettes for several
    controls, which makes a real dark mode impossible), then installs the matching palette
    and stylesheet.
    """
    global _active, _active_is_dark
    colors = resolve_theme(app, preference)
    _active = colors
    _active_is_dark = QColor(colors["bg"]).lightnessF() < QColor(colors["text"]).lightnessF()
    if app is not None:
        if app.style().objectName() != "fusion":
            app.setStyle("Fusion")
        app.setPalette(_qt_palette(colors))
        app.setStyleSheet(stylesheet(colors))
    return colors
