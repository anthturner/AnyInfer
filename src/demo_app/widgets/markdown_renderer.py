"""Safe Markdown→HTML for assistant messages.

Model output is untrusted text. ``markdown.Markdown`` alone allows raw HTML and script-shaped
constructs through; this module always runs its output through an allow-list sanitizer before
it reaches `QTextEdit.setHtml()`, so a response can never inject markup this app did not
intend to render.
"""

from __future__ import annotations

import html as _html
from xml.etree import ElementTree as ET

import markdown

__all__ = ["render_markdown"]

_ALLOWED_TAGS = {
    "p", "br", "strong", "em", "code", "pre", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "a", "blockquote", "table", "thead",
    "tbody", "tr", "th", "td", "hr", "span",
}
_ALLOWED_ATTRS = {"a": {"href"}}
_VOID_TAGS = {"br", "hr"}

_md = markdown.Markdown(extensions=["fenced_code", "tables", "toc"], output_format="html")


def render_markdown(text: str) -> str:
    """Render ``text`` as sanitized HTML safe to pass to `QTextEdit.setHtml()`.

    Falls back to escaped plain text if the Markdown output is not well-formed XML (which
    ``markdown`` can produce for pathological input) rather than risk showing raw HTML.
    """
    _md.reset()
    raw_html = _md.convert(text)
    try:
        root = ET.fromstring(f"<root>{raw_html}</root>")
    except ET.ParseError:
        return f"<pre>{_html.escape(text)}</pre>"
    return "".join(_render_children(root))


def _render_children(element: ET.Element) -> list[str]:
    """Render an element's children, dropping disallowed tags but keeping their content."""
    parts: list[str] = []
    if element.text:
        parts.append(_html.escape(element.text))
    for child in element:
        parts.extend(_render_element(child))
        if child.tail:
            parts.append(_html.escape(child.tail))
    return parts


def _render_element(element: ET.Element) -> list[str]:
    inner = _render_children(element)
    if element.tag not in _ALLOWED_TAGS:
        return inner  # unwrap: keep the content, drop the tag
    attrs = "".join(
        f' {name}="{_html.escape(value, quote=True)}"'
        for name, value in element.attrib.items()
        if name in _ALLOWED_ATTRS.get(element.tag, set())
    )
    if element.tag in _VOID_TAGS:
        return [f"<{element.tag}{attrs}/>"]
    return [f"<{element.tag}{attrs}>", *inner, f"</{element.tag}>"]
