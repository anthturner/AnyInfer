"""MkDocs build hooks, referenced from ``hooks:`` in mkdocs.yml.

Four jobs:

1. Expose the package version to the theme templates so the header's "Download vX.Y.Z"
   button (overrides/partials/header.html) always shows the version the site was built
   from. The version is read from pyproject.toml — the single source of truth — rather
   than imported from the package, so the hook works even in a docs-only environment.
2. Expose the generated provider count to templates. The generated provider index is
   registry-backed and already checked for drift, so the site never carries a second count.
3. Substitute ``{{ extra.anyinfer_version }}`` inside Markdown source (MkDocs, unlike
   templates, does not Jinja-render page content) so pages like downloads.md can show a
   version pill without a macros plugin.
4. Write ``llms.txt`` and ``llms-full.txt`` into the site root: a link index and a
   full-text bundle for coding agents. Both are derived from the navigation and the built
   pages, so a page added to the nav appears without a hand edit and a deleted one cannot
   linger — the only arrangement in which a machine-readable docs index stays true.
"""

from __future__ import annotations

import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

LLMS_INDEX = "llms.txt"
"""Curated link index; the filename is the community convention, not ours to choose."""

LLMS_FULL = "llms-full.txt"
"""Concatenated page text, for an agent that wants the corpus rather than the map."""

LLMS_FULL_SPLIT_BYTES = 800_000
"""Roughly 200k tokens. Past this the bundle should become a per-section split with
``llms.txt`` as the index; the build logs its size so the threshold is observed rather
than guessed at."""

_SUMMARIES: dict[str, str] = {}
"""One-line summary per page source path, harvested from its first prose paragraph."""

_BODIES: dict[str, str] = {}
"""Rendered body text per page source path, navigation chrome stripped."""

_NAV: Any = None
"""The built navigation, captured so the post-build hook can walk it in the site's order."""


def on_config(config: Any) -> Any:
    """Inject release metadata used by theme templates, and reset per-build state."""
    global _NAV

    _SUMMARIES.clear()
    _BODIES.clear()
    _NAV = None

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
    resolved = markdown.replace("{{ extra.anyinfer_version }}", config.extra["anyinfer_version"])
    page = kwargs.get("page")
    if page is not None:
        _SUMMARIES[page.file.src_uri] = _first_paragraph(resolved)
    return resolved


def on_nav(nav: Any, **kwargs: Any) -> Any:
    """Capture the navigation so the index can be written in the site's own order."""
    global _NAV

    _NAV = nav
    return nav


def on_post_page(output: str, *, page: Any, **kwargs: Any) -> str:
    """Capture each page's rendered body text, without navigation or chrome.

    The *rendered* HTML rather than the Markdown source, because the API reference is
    generated at build time: its Markdown is a handful of ``:::`` directives, and a bundle
    built from that would advertise a complete reference while containing none of it.
    """
    _BODIES[page.file.src_uri] = _article_text(output)
    return output


def on_post_build(*, config: Any, **kwargs: Any) -> None:
    """Write the two agent-facing text files into the built site.

    Raises:
        ValueError: If the index came out empty, or if either file carries an internal
            ADR identifier. Both are build failures rather than test failures because
            these files are the ones read in somebody else's repository, where nothing
            here can correct them, and the build is the last place that can.
    """
    site_dir = Path(config.site_dir)
    index = _render_index(config)
    if "\n## " not in index:
        raise ValueError(f"{LLMS_INDEX} lists no pages; the navigation hook produced nothing")
    (site_dir / LLMS_INDEX).write_text(index, encoding="utf-8")

    bundle = _render_full(config)
    for name, text in ((LLMS_INDEX, index), (LLMS_FULL, bundle)):
        leak = re.search(r"\bADR-\d", text)
        if leak is not None:
            raise ValueError(
                f"{name} contains the internal identifier {leak.group(0)!r}; state the "
                "rule in plain words in the source page instead"
            )
    (site_dir / LLMS_FULL).write_text(bundle, encoding="utf-8")

    size = len(bundle.encode("utf-8"))
    note = " - past the split threshold" if size > LLMS_FULL_SPLIT_BYTES else ""
    print(f"INFO    -  {LLMS_FULL} is {size / 1024:.0f} KiB{note}")


# ---- rendering -----------------------------------------------------------------------


def _render_index(config: Any) -> str:
    """Build the link index: an H1, a blockquote summary, then sections of links."""
    lines = [
        f"# {config.site_name}",
        "",
        f"> {_collapse(config.site_description)}",
        "",
        f"Version {config.extra['anyinfer_version']}. Full text of every page below: "
        f"{_absolute(config, LLMS_FULL)}",
        "",
    ]
    for title, pages in _sections(config):
        if not pages:
            continue
        lines.append(f"## {title}")
        lines.append("")
        for page_title, url, summary, _src in pages:
            suffix = f": {summary}" if summary else ""
            lines.append(f"- [{page_title}]({url}){suffix}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _render_full(config: Any) -> str:
    """Concatenate every navigated page's body text, in navigation order."""
    parts = [
        f"# {config.site_name} - full documentation",
        "",
        f"Version {config.extra['anyinfer_version']}. Generated from the built site; the "
        f"link index is at {_absolute(config, LLMS_INDEX)}.",
    ]
    for title, pages in _sections(config):
        for page_title, url, _summary, src in pages:
            body = _BODIES.get(src, "")
            if not body:
                continue
            parts.append(f"\n\n---\n\n# {title} / {page_title}\n\nSource: {url}\n")
            parts.append(body)
    return "\n".join(parts).rstrip("\n") + "\n"


def _sections(config: Any) -> list[tuple[str, list[tuple[str, str, str, str]]]]:
    """Flatten the navigation into ``(section, [(title, url, summary, source path)])``.

    Two levels only. The site nests no deeper in a way that matters to a reader who wants
    a list of links, and a faithfully nested index is harder to consume than the thing it
    indexes.
    """
    sections: list[tuple[str, list[tuple[str, str, str, str]]]] = []
    if _NAV is None:
        return sections

    def collect(item: Any, into: list[tuple[str, str, str, str]]) -> None:
        if getattr(item, "is_page", False):
            src = item.file.src_uri
            into.append(
                (item.title or src, _absolute(config, item.url), _SUMMARIES.get(src, ""), src)
            )
        elif getattr(item, "is_section", False):
            for child in item.children:
                collect(child, into)

    for item in _NAV.items:
        pages: list[tuple[str, str, str, str]] = []
        collect(item, pages)
        if not pages:
            continue
        title = item.title or ("Overview" if getattr(item, "is_page", False) else "Pages")
        sections.append((title, pages))
    return sections


def _absolute(config: Any, url: str) -> str:
    """Join a site-relative URL onto the configured site URL."""
    base = str(config.site_url or "/").rstrip("/")
    return f"{base}/{url.lstrip('/')}"


def _first_paragraph(markdown: str) -> str:
    """The page's first prose paragraph, flattened to one line.

    Headings, code fences, admonitions, tables, and HTML blocks are skipped: a summary
    that opens with ``<p align="center">`` says nothing about the page.
    """
    buffer: list[str] = []
    fenced = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if not stripped:
            if buffer:
                break
            continue
        if stripped.startswith(("#", "|", "<", "!!!", "===", ":::", "- ", "* ", ">")):
            if buffer:
                break
            continue
        buffer.append(stripped)
    text = _collapse(" ".join(buffer))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    return text if len(text) <= 200 else text[:197].rstrip() + "..."


def _collapse(text: Any) -> str:
    """Whitespace-collapse a value onto one line."""
    return " ".join(str(text or "").split())


class _ArticleText(HTMLParser):
    """Extract the readable text of a Material page's ``<article>`` element.

    Everything outside the article is navigation, search, and the footer — the chrome an
    agent has no use for and that would otherwise repeat on every page in the bundle.
    """

    _SKIP = frozenset({"script", "style", "nav", "svg", "button", "form"})
    _BREAK = frozenset({"p", "div", "li", "tr", "br", "pre", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.chunks: list[str] = []
        # A dropped subtree is tracked by the *name* of the element that opened it, and by
        # how many of that same element are nested inside. Counting every open tag instead
        # goes wrong the first time a void element (`<br>`, `<img>`) appears inside the
        # subtree: it never closes, the counter never returns to zero, and the rest of the
        # page silently disappears, which is exactly what a plain counter did here, since
        # every Material heading ends in an `<a class="headerlink">`.
        self._skip_tag: str | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Enter the article, or note that this subtree is chrome to be dropped."""
        if self._skip_tag is not None:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag == "article":
            self.depth += 1
            return
        if self.depth == 0:
            return
        classes = dict(attrs).get("class") or ""
        if tag in self._SKIP or "headerlink" in classes or "md-source-file" in classes:
            self._skip_tag = tag
            self._skip_depth = 1
            return
        if tag in self._BREAK:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """Leave the article or a dropped subtree, keeping block boundaries."""
        if self._skip_tag is not None:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth <= 0:
                    self._skip_tag = None
            return
        if tag == "article" and self.depth:
            self.depth -= 1
            return
        if self.depth and tag in self._BREAK:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        """Keep text that is inside the article and outside every dropped subtree."""
        if self.depth and self._skip_tag is None:
            self.chunks.append(data)


def _article_text(html: str) -> str:
    """Strip a rendered page down to the text inside its article element."""
    parser = _ArticleText()
    parser.feed(html)
    parser.close()
    # Collapse the run of blank lines every closing tag contributes, but keep paragraph
    # breaks: an agent reading a wall of text loses the structure the page had.
    out: list[str] = []
    for raw in "".join(parser.chunks).splitlines():
        line = raw.strip()
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()
