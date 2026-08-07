"""Access to the bundled brand assets in this package.

The files here are copies of ``docs/assets/`` (the project's published brand kit) — copied
rather than referenced across the repo boundary so the demo app still finds them when
installed from a wheel or a PyInstaller bundle, where ``docs/`` does not ship.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

__all__ = ["asset_path", "read_svg"]

_PACKAGE = "demo_app.assets"


def asset_path(name: str) -> Path:
    """The filesystem path to a bundled asset, resolved through the installed package."""
    return Path(str(resources.files(_PACKAGE) / name))


def read_svg(name: str) -> str:
    """The raw text of a bundled SVG asset."""
    return resources.files(_PACKAGE).joinpath(name).read_text(encoding="utf-8")
