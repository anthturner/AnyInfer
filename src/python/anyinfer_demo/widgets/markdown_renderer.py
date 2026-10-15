"""Safe Markdown→HTML for assistant messages.

Model output is untrusted text. ``markdown.Markdown`` alone allows raw HTML and script-shaped
constructs through; this module always runs its output through an allow-list sanitizer before
it reaches `QTextEdit.setHtml()`, so a response can never inject markup this app did not
intend to render.
"""

from __future__ import annotations

import html as _html
from html.parser import HTMLParser
from urllib.parse import urlsplit

import markdown

__all__ = ["render_markdown"]

_ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "code",
    "pre",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "a",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "hr",
    "span",
}
_ALLOWED_ATTRS = {"a": {"href"}}
_VOID_TAGS = {"br", "hr"}

_md = markdown.Markdown(extensions=["fenced_code", "tables", "toc"], output_format="html")


def render_markdown(text: str) -> str:
    """Render ``text`` as sanitized HTML safe to pass to `QTextEdit.setHtml()`.

    Python-Markdown intentionally emits HTML rather than XML, including unclosed void tags
    and named HTML entities. A tolerant parser sanitizes that output without turning an
    otherwise valid message into escaped preformatted text.
    """
    _md.reset()
    raw_html = _md.convert(text)
    sanitizer = _AllowListHTMLParser()
    sanitizer.feed(raw_html)
    sanitizer.close()
    return sanitizer.html


def _safe_href(value: str) -> bool:
    """Allow ordinary web/mail links and local document fragments, never script URLs."""
    compact = "".join(value.split())
    scheme = urlsplit(compact).scheme.casefold()
    return not scheme or scheme in {"http", "https", "mailto"}


class _AllowListHTMLParser(HTMLParser):
    """Tolerant HTML parser that emits only the demo's small rendering allow-list."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._open_tags: list[str] = []

    @property
    def html(self) -> str:
        """Return balanced sanitized HTML after parsing has completed."""
        return "".join((*self._parts, *(f"</{tag}>" for tag in reversed(self._open_tags))))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag not in _ALLOWED_TAGS:
            return
        rendered_attrs: list[str] = []
        seen: set[str] = set()
        for name, value in attrs:
            name = name.casefold()
            if name in seen or name not in _ALLOWED_ATTRS.get(tag, set()) or value is None:
                continue
            if tag == "a" and name == "href" and not _safe_href(value):
                continue
            seen.add(name)
            rendered_attrs.append(f' {name}="{_html.escape(value, quote=True)}"')
        self._parts.append(f"<{tag}{''.join(rendered_attrs)}>")
        if tag not in _VOID_TAGS:
            self._open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        before = len(self._open_tags)
        self.handle_starttag(tag, attrs)
        if len(self._open_tags) > before:
            opened = self._open_tags.pop()
            self._parts.append(f"</{opened}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag not in self._open_tags:
            return
        while self._open_tags:
            opened = self._open_tags.pop()
            self._parts.append(f"</{opened}>")
            if opened == tag:
                break

    def handle_data(self, data: str) -> None:
        self._parts.append(_html.escape(data))
