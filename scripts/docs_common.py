"""Shared source metadata and route rules for the Docusaurus documentation build."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Page:
    """One authored documentation page and its published location."""

    source: str
    sdk: str
    id: str
    slug: str
    url: str
    title: str
    section: str
    order: int

    def manifest(self) -> dict[str, object]:
        """Return the stable JSON representation consumed by the site and exports."""
        return asdict(self)


_C_SHARP_SOURCES = frozenset(
    {"guides/csharp-sdk.md", "guides/python-to-csharp.md", "reference/csharp-sdk.md"}
)
_PYTHON_ROOTS = frozenset(
    {"guides/python-sdk.md", "guides/quickstart.md", "guides/installation.md"}
)
GENERATED_PREFIX = "generated:"
"""Navigation targets with this prefix name a generated section, not an authored source."""


def load_navigation(path: Path) -> list[object]:
    """Read the preserved MkDocs navigation without importing MkDocs."""
    navigation = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(navigation, list):
        raise ValueError(f"navigation at {path} must be a JSON array")
    return navigation


def build_pages(docs_dir: Path, navigation: list[object]) -> list[Page]:
    """Inventory source pages in navigation order, including the home and downloads pages."""
    titles: dict[str, tuple[str, str, int]] = {}
    order = 0

    def visit(value: object, section: str) -> None:
        nonlocal order
        if isinstance(value, str):
            if value.startswith(GENERATED_PREFIX):
                return
            titles.setdefault(value, (_source_title(docs_dir / value), section, order))
            order += 1
            return
        if not isinstance(value, dict):
            raise ValueError(f"unsupported navigation entry {value!r}")
        for title, child in value.items():
            if not isinstance(title, str):
                raise ValueError(f"navigation title must be text, got {title!r}")
            child_section = title if section == "" else section
            if isinstance(child, str) and child.startswith(GENERATED_PREFIX):
                continue
            if isinstance(child, str):
                titles.setdefault(child, (title, child_section, order))
                order += 1
            elif isinstance(child, list):
                for item in child:
                    visit(item, child_section)
            else:
                raise ValueError(f"unsupported navigation target for {title!r}")

    for entry in navigation:
        visit(entry, "")

    # The landing page is rendered by the TSX home rather than a docs plugin. Downloads is
    # intentionally outside the curated sidebar but remains part of the published corpus.
    titles.setdefault("index.md", ("Home", "Home", 0))
    titles.setdefault("downloads.md", ("Downloads", "Home", order))

    pages: list[Page] = []
    for source, (title, section, page_order) in titles.items():
        if source == "README.md":
            continue
        if not (docs_dir / source).is_file():
            raise ValueError(f"navigation source {source!r} does not exist below {docs_dir}")
        pages.append(_page(source, title, section, page_order))
    return sorted(pages, key=lambda page: (page.order, page.source))


def _source_title(path: Path) -> str:
    """Read a navigated source's visible H1 for JSON entries without a label."""
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("# "):
                continue
            title = line[2:]
            title = re.sub(r":material-[a-z0-9-]+:(?:\{[^}]*\})?", "", title)
            title = re.sub(r"\s*\{\s*[.#][^}]+\}\s*$", "", title)
            title = title.replace("`", "").strip()
            if title:
                return title
    return path.stem


def _page(source: str, title: str, section: str, order: int) -> Page:
    path = Path(source)
    identifier = path.with_suffix("").as_posix()
    if source == "index.md":
        return Page(source, "shared", "home", "/", "/", title, section, order)
    sdk, slug = _classify(source)
    base = {"shared": "", "python": "/python", "csharp": "/csharp"}[sdk]
    return Page(source, sdk, identifier, slug, f"{base}{slug}", title, section, order)


def _classify(source: str) -> tuple[str, str]:
    """Assign a source page to a plugin and a slug relative to that plugin's base."""
    if source == "guides/python-sdk.md":
        return "python", "/"
    if source == "guides/quickstart.md":
        return "python", "/quickstart/"
    if source == "guides/installation.md":
        return "python", "/installation/"
    if source.startswith("reference/api/"):
        tail = source.removeprefix("reference/api/").removesuffix(".md")
        return "python", "/api/" if tail == "README" else f"/api/{tail}/"
    if source == "guides/csharp-sdk.md":
        return "csharp", "/"
    if source == "guides/python-to-csharp.md":
        return "csharp", "/migrating-from-python/"
    if source == "reference/csharp-sdk.md":
        return "csharp", "/reference/"
    if source == "guides/csharp-installation.md":
        return "csharp", "/installation/"
    if source == "guides/csharp-quickstart.md":
        return "csharp", "/quickstart/"
    if source.startswith("examples/csharp-") and source.endswith(".md"):
        return "csharp", f"/examples/{source.removeprefix('examples/csharp-').removesuffix('.md')}/"
    stem = source.removesuffix(".md")
    if stem.endswith("/README"):
        stem = stem[: -len("/README")]
    elif stem.endswith("/index"):
        stem = stem[: -len("/index")]
    return "shared", f"/{stem}/" if stem else "/"


def read_versions(root: Path) -> dict[str, object]:
    """Read release versions from the owning project metadata rather than constants."""
    with (root / "pyproject.toml").open("rb") as handle:
        python_version = str(tomllib.load(handle)["project"]["version"])
    props = (root / "src" / "csharp" / "Directory.Build.props").read_text(encoding="utf-8")
    match = re.search(r"<Version>([^<]+)</Version>", props)
    if match is None:
        raise ValueError("src/csharp/Directory.Build.props has no Version element")
    return {"python": python_version, "csharp": match.group(1).strip(), "addons": {}}


def legacy_url(source: str) -> str:
    """Return the former MkDocs directory URL for an authored source filename."""
    stem = source.removesuffix(".md")
    if stem in {"index", "README"}:
        return "/"
    if stem.endswith("/README") or stem.endswith("/index"):
        return f"/{stem.rsplit('/', 1)[0]}/"
    return f"/{stem}/"


def redirects_for(pages: list[Page]) -> dict[str, str]:
    """Map changed legacy URLs to their canonical SDK route, excluding the home page."""
    return {
        legacy_url(page.source): page.url
        for page in pages
        if page.source != "index.md" and legacy_url(page.source) != page.url
    }
