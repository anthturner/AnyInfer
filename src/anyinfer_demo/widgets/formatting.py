"""Byte-count formatting shared across widgets that are not part of one dialog's package.

A standalone leaf module rather than a member of `models_dialog/`: `add_model_dialog.py`
and the Models dialog's panels both need this, and `add_model_dialog.py` is itself
imported by `models_dialog/__init__.py`, so sourcing it from inside that package would
create an import cycle.
"""

from __future__ import annotations


def _bytes(count: int | None) -> str:
    """Format a byte count for a table cell, or an em dash when it is unknown.

    An em dash rather than ``0``: the catalog genuinely does not know the size of every
    entry, and a zero there would read as a free download.
    """
    if count is None:
        return "—"
    size = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"
