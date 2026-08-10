"""An accordion-style dock section: a header bar with a title and a minimize/restore button.

Used to stack several panels (Telemetry, Structured output, Providers) in one
`QSplitter` where minimizing one gives the others more room, without
fully hiding it the way the View menu's show/hide checkboxes do — collapsing here always
leaves the header visible so the section can be restored with one click.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .icons import themed_icon

__all__ = ["CollapsibleSection"]

HEADER_HEIGHT = 32
"""Fixed header height; also the collapsed height of a minimized section."""


class CollapsibleSection(QFrame):
    """A titled section that collapses to its header bar and restores to its prior size.

    Minimizing pins the section's height to just the header via ``setFixedHeight`` — a
    ``QSplitter`` then hands the freed space to the remaining expanded siblings on its own,
    which is the accordion behaviour: one collapse grows the others, nothing is torn down.
    """

    minimized_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        content: QWidget,
        parent: QWidget | None = None,
        *,
        help_topic: str | None = None,
        icon: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CollapsibleSection")
        self._content = content
        self._minimized = False
        self._icon_name = icon

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("CollapsibleSectionHeader")
        header.setFixedHeight(HEADER_HEIGHT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 8, 0)

        self._icon_label: QLabel | None = None
        if icon is not None:
            self._icon_label = QLabel()
            self._icon_label.setFixedSize(16, 16)
            header_layout.addWidget(self._icon_label)
            self._render_icon()

        self._title_label = QLabel(title)
        self._title_label.setObjectName("CollapsibleSectionTitle")
        header_layout.addWidget(self._title_label)
        header_layout.addStretch(1)

        self.help_button = None
        if help_topic is not None:
            # Imported here so the section stays usable without the help registry in
            # minimal harnesses and tests.
            from .sdk_help import SdkHelpButton

            self.help_button = SdkHelpButton(help_topic)
            header_layout.addWidget(self.help_button)

        self._toggle = QPushButton()
        self._toggle.setObjectName("IconButton")
        self._toggle.setFixedSize(26, 26)
        self._toggle.clicked.connect(self.toggle_minimized)
        header_layout.addWidget(self._toggle)

        outer.addWidget(header)
        outer.addWidget(content, 1)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._update_toggle()

    # ---- state -------------------------------------------------------------------

    @property
    def minimized(self) -> bool:
        """Whether the section is currently collapsed to its header."""
        return self._minimized

    @property
    def title(self) -> str:
        """The section's header title."""
        return self._title_label.text()

    def toggle_minimized(self) -> None:
        """Flip between minimized (header only) and restored."""
        self.set_minimized(not self._minimized)

    def set_minimized(self, minimized: bool) -> None:
        """Collapse to the header bar, or restore the content below it."""
        if minimized == self._minimized:
            return
        self._minimized = minimized
        self._content.setVisible(not minimized)
        if minimized:
            self.setFixedHeight(HEADER_HEIGHT)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16_777_215)  # QWIDGETSIZE_MAX — undo setFixedHeight's cap
        self._update_toggle()
        self.minimized_changed.emit(minimized)

    def reapply_theme(self) -> None:
        """Re-render the themed icons after a theme change."""
        self._update_toggle()
        self._render_icon()

    def _render_icon(self) -> None:
        if self._icon_label is not None and self._icon_name is not None:
            self._icon_label.setPixmap(themed_icon(self, self._icon_name, size=16).pixmap(16, 16))

    def _update_toggle(self) -> None:
        """Sync the toggle's icon, tooltip, and accessible name to the current state.

        Called from ``__init__`` too, so the button is labelled before the first toggle.
        """
        minimized = self._minimized
        self._toggle.setToolTip("Restore" if minimized else "Minimize")
        self._toggle.setAccessibleName(
            f"Restore {self.title}" if minimized else f"Minimize {self.title}"
        )
        icon_name = "chevron-down" if minimized else "chevron-up"
        self._toggle.setIcon(themed_icon(self._toggle, icon_name))
