"""MkDocs build hooks, referenced from ``hooks:`` in mkdocs.yml.

Two jobs:

1. Expose the package version to the theme templates so the header's "Download vX.Y.Z"
   button (overrides/partials/header.html) always shows the version the site was built
   from. The version is read from pyproject.toml — the single source of truth — rather
   than imported from the package, so the hook works even in a docs-only environment.
2. Expose the generated provider count to templates. The generated provider index is
   registry-backed and already checked for drift, so the site never carries a second count.
3. Substitute ``{{ extra.anyinfer_version }}`` inside Markdown source (MkDocs, unlike
   templates, does not Jinja-render page content) so pages like downloads.md can show a
   version pill without a macros plugin.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any


def on_config(config: Any) -> Any:
    """Inject release metadata used by theme templates."""
    root = Path(config.config_file_path).parent
    pyproject = root / "pyproject.toml"
    with pyproject.open("rb") as handle:
        config.extra["anyinfer_version"] = tomllib.load(handle)["project"]["version"]
    provider_index = (root / "docs" / "providers" / "all.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*(\d+) providers\*\*", provider_index)
    if match is None:
        raise ValueError("generated provider index does not declare its provider count")
    config.extra["anyinfer_provider_count"] = int(match.group(1))
    return config


def on_page_markdown(markdown: str, *, config: Any, **kwargs: Any) -> str:
    """Replace the ``{{ extra.anyinfer_version }}`` placeholder in page source."""
    return markdown.replace("{{ extra.anyinfer_version }}", config.extra["anyinfer_version"])
