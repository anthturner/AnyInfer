"""Help-menu dialogs: third-party licenses and About.

The license list is built from what the demo actually ships or links, with versions read
from the installed distributions at runtime — a hardcoded version string would be wrong
by the second release. Full license text is embedded where we redistribute the material
(the Tabler icon shapes live in this repository), and named-plus-linked where we only
link against it (Qt/PySide6 under LGPLv3, obtained from the system's installed copy).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata

from PySide6.QtCore import Qt
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..assets import asset_path
from .sdk_help import _monospace

__all__ = ["THIRD_PARTY_COMPONENTS", "AboutDialog", "LicensesDialog"]

_MIT_TABLER = """MIT License

Copyright (c) 2020-2024 Paweł Kuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

_LGPL_NOTICE = """This demo application links against {name}, which is made available
under the GNU Lesser General Public License v3 (LGPLv3).

The library is used unmodified, via its published Python bindings; nothing from it is
statically bundled into this repository. The complete license text is available at:

    https://www.gnu.org/licenses/lgpl-3.0.html

Source code for the library is available from its publisher:

    {source}"""


@dataclass(frozen=True, slots=True)
class _Component:
    """One third-party component the demo uses."""

    name: str
    license_name: str
    text: str
    distribution: str | None = None
    """Installed distribution to read the live version from, when there is one."""

    def display_version(self) -> str:
        if self.distribution is None:
            return ""
        try:
            return metadata.version(self.distribution)
        except metadata.PackageNotFoundError:
            return ""


THIRD_PARTY_COMPONENTS: tuple[_Component, ...] = (
    _Component(
        name="PySide6 (Qt for Python)",
        license_name="LGPLv3",
        text=_LGPL_NOTICE.format(
            name="PySide6", source="https://code.qt.io/cgit/pyside/pyside-setup.git"
        ),
        distribution="PySide6",
    ),
    _Component(
        name="Qt",
        license_name="LGPLv3",
        text=_LGPL_NOTICE.format(name="Qt", source="https://code.qt.io/"),
    ),
    _Component(
        name="Tabler Icons",
        license_name="MIT",
        text=_MIT_TABLER,
    ),
    _Component(
        name="Python-Markdown",
        license_name="BSD-3-Clause",
        text=(
            "This demo renders assistant Markdown with the Python-Markdown package,\n"
            "distributed under the BSD 3-Clause license. Full text ships with the\n"
            "installed distribution and at https://python-markdown.github.io/#license"
        ),
        distribution="markdown",
    ),
)
"""What the demo app itself pulls in beyond the AnyInfer SDK.

The SDK's own dependencies are the SDK's to declare; this list is scoped to the demo
frontend on purpose.
"""


class LicensesDialog(QDialog):
    """Third-party components on the left, the selected component's license on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Third-party licenses")
        self.setMinimumSize(640, 460)

        layout = QVBoxLayout(self)
        caption = QLabel(
            "Components this demonstration application uses, beyond the AnyInfer SDK "
            "itself. Versions are read from the installed packages."
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._list.setAccessibleName("Third-party components")
        for component in THIRD_PARTY_COMPONENTS:
            version = component.display_version()
            label = f"{component.name} {version}".strip()
            item = QListWidgetItem(f"{label}\n{component.license_name}")
            item.setData(Qt.ItemDataRole.UserRole, component.text)
            self._list.addItem(item)
        self._list.currentItemChanged.connect(self._on_selected)
        splitter.addWidget(self._list)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(_monospace())
        self._text.setAccessibleName("License text")
        splitter.addWidget(self._text)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._list.setCurrentRow(0)

    def _on_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self._text.setPlainText(
            str(current.data(Qt.ItemDataRole.UserRole)) if current is not None else ""
        )


class AboutDialog(QDialog):
    """The wordmark, what this application is, and the SDK version it runs against."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import anyinfer

        self.setWindowTitle("About AnyInfer Demo")
        self.setFixedSize(420, 260)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo = QSvgWidget()
        variant = "dark" if theme.is_dark_active() else "light"
        logo.load(str(asset_path(f"anyinfer-horizontal-{variant}.svg")))
        logo.setFixedSize(260, 56)
        logo.setAccessibleName("AnyInfer")
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Demonstration Application")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        version = QLabel(f"AnyInfer SDK {anyinfer.__version__}")
        version.setObjectName("Muted")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(version)

        row = QHBoxLayout()
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        row.addWidget(buttons)
        row.addStretch(1)
        layout.addLayout(row)
