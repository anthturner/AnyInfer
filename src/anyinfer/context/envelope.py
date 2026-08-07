"""The context envelope: how reduced documents are rendered, and how they are measured.

One module owns both rendering and byte accounting, deliberately. When those live apart
they drift, and a selector that measures blocks differently than it renders them produces
envelopes that overrun the budget it just checked. Here, the accounting *is* the rendering
— `block_bytes()` measures the exact string `render_*` produces.

The format is a documented, mechanical data envelope, not a template: neutral XML-ish
tags, attribute values HTML-escaped, no prose and no placeholders. Applications own every
word of prompt around it. It is stable enough that apps may parse it back out of stored
transcripts, so changing it is a breaking change.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Mapping, Sequence

from .documents import ContextDocument

__all__ = [
    "CONTEXT_TAG",
    "TIERS_TAG",
    "block_bytes",
    "render_chunk_block",
    "render_corpus",
    "render_digest_block",
    "render_extract_block",
    "render_file_block",
    "render_module_block",
    "render_tiers",
    "wrapper_bytes",
]

CONTEXT_TAG = "context"
"""Wrapper element for the ``whole``, ``ranked``, and ``packed`` representations."""

TIERS_TAG = "context-tiers"
"""Wrapper element for the module-rollup tier."""


def _attr(value: str) -> str:
    """Escape an attribute value, quotes included."""
    return html.escape(value, quote=True)


def render_file_block(document: ContextDocument) -> str:
    """Render a whole document."""
    return (
        f'<file path="{_attr(document.path)}" sha256="{document.sha256}">{document.content}</file>'
    )


def render_extract_block(document: ContextDocument) -> str:
    """Render a document's structural extract."""
    return (
        f'<file-extract path="{_attr(document.path)}" sha256="{document.sha256}">'
        f"{document.extract}</file-extract>"
    )


def render_chunk_block(
    document: ContextDocument, text: str, start_line: int, end_line: int
) -> str:
    """Render one contiguous span of a document, with its line range."""
    return (
        f'<file-chunk path="{_attr(document.path)}" sha256="{document.sha256}" '
        f'lines="{start_line}-{end_line}">{text}</file-chunk>'
    )


def render_module_block(
    module: str,
    *,
    file_count: int,
    corpus_share: float,
    languages: Sequence[str],
    dependencies: str = "",
    symbols: str = "",
) -> str:
    """Render one module's rollup entry.

    Empty ``dependencies`` or ``symbols`` omit their line entirely — a bare label
    conveys nothing and costs tokens.
    """
    lines = [
        f'<module path="{_attr(module)}" files="{file_count}" '
        f'corpus_share="{corpus_share:.3f}" languages="{_attr(", ".join(languages))}">'
    ]
    if dependencies:
        lines.append(f"dependencies: {dependencies}")
    if symbols:
        lines.append(f"symbols: {symbols}")
    lines.append("</module>")
    return "\n".join(lines)


def render_digest_block(digests: Mapping[str, str]) -> str:
    """Render app-supplied module digests.

    The library renders digests; it never generates them. Spending inference to
    summarize a corpus is an application's decision, not a side effect of packing.
    """
    if not digests:
        return ""
    inner = "\n".join(
        f'  <module path="{_attr(name)}">{digests[name]}</module>' for name in sorted(digests)
    )
    return f"<module-digests>\n{inner}\n</module-digests>"


def render_corpus(blocks: Iterable[str]) -> str:
    """Wrap rendered blocks in the corpus element."""
    body = "\n".join(blocks)
    if not body:
        return f"<{CONTEXT_TAG}></{CONTEXT_TAG}>"
    return f"<{CONTEXT_TAG}>\n{body}\n</{CONTEXT_TAG}>"


def render_tiers(module_blocks: Sequence[str], *, coverage_files: int) -> str:
    """Wrap module rollup blocks in the tiers element."""
    if not module_blocks:
        return ""
    body = "\n".join(module_blocks)
    return f'<{TIERS_TAG} coverage_files="{coverage_files}">\n{body}\n</{TIERS_TAG}>'


def block_bytes(block: str) -> int:
    """UTF-8 byte length of a rendered block, plus the newline that joins it.

    Selection loops add this per admitted block, so it must account for the separator
    the renderer will insert.
    """
    return len(block.encode("utf-8")) + 1


def wrapper_bytes(tag: str = CONTEXT_TAG) -> int:
    """Byte cost of an empty wrapper, charged before any block is admitted."""
    return len(f"<{tag}>\n\n</{tag}>".encode())
