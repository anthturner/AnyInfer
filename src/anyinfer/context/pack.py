"""The ``packed`` strategy: rank and pack at sub-document granularity.

Ranking whole documents wastes budget when the answer is one function in a large file.
``packed`` splits documents into chunks, ranks the chunks, and packs the best ones —
retrieval-shaped selection without any retrieval infrastructure.

Two properties keep it honest. Splitting is boundary-aware: chunks break at blank lines,
then at line breaks, and only hard-cut as a last resort, so a chunk rarely severs a
statement. And adjacent selected chunks are coalesced when rendered, so a contiguous run
of a file appears as one block with one line span rather than as fragments that imply
gaps where there are none.

Pinned documents are never chunked — pinning means "the user chose this file", and
sending a piece of it would answer a question they did not ask.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from ..capabilities.estimate import TokenEstimator
from .dedup import DuplicateMap
from .documents import ContextDocument, RankCache
from .envelope import (
    block_bytes,
    render_chunk_block,
    render_corpus,
    wrapper_bytes,
    wrapper_text,
)
from .rank import build_rank_cache, expand_query, score_document, tokenize
from .select import Reduction, _blocks_for, _collapse_counts, _order_constraints
from .settings import DEFAULT_TUNING, ContextTuning

__all__ = [
    "DEFAULT_CHUNK_TOKENS",
    "MIN_CHUNK_TOKENS",
    "Chunk",
    "reduce_packed",
    "split_document",
]

DEFAULT_CHUNK_TOKENS = 512
"""Target chunk size. Large enough for a whole function, small enough to pack several."""

MIN_CHUNK_TOKENS = 64
"""Tail chunks below this merge backward rather than standing alone."""

_BYTES_PER_TOKEN = 3
"""The planning heuristic's inverse, used to turn a token target into a character budget.

An explicit, documented conversion; not a silent conflation of tokens with characters.
"""

_BOUNDARY_FLOOR = 0.25
"""A boundary earlier than this fraction of the budget is not worth honoring."""


@dataclass(frozen=True, slots=True)
class Chunk:
    """One span of a document.

    Attributes:
        document: The document this came from.
        text: The span's text.
        index: Position within the document, from zero.
        start_line: First line of the span, 1-based and inclusive.
        end_line: Last line of the span, 1-based and inclusive.
    """

    document: ContextDocument
    text: str
    index: int
    start_line: int
    end_line: int


def split_document(
    document: ContextDocument, *, chunk_tokens: int = DEFAULT_CHUNK_TOKENS
) -> list[Chunk]:
    """Split a document into boundary-aware chunks with line spans.

    Prefers the last blank line within budget, falls back to the last line break, and
    hard-cuts only when neither lands past a quarter of the budget.

    Args:
        document: The document to split.
        chunk_tokens: Target chunk size in planning tokens.

    Returns:
        Chunks in document order. A document shorter than one chunk yields exactly one.
    """
    budget = max(1, chunk_tokens * _BYTES_PER_TOKEN)
    content = document.content
    chunks: list[Chunk] = []
    position = 0
    line = 1
    index = 0

    while position < len(content):
        remaining = content[position:]
        cut = len(remaining) if len(remaining) <= budget else _boundary(remaining, budget)
        text = remaining[:cut]
        line_count = text.count("\n")
        chunks.append(
            Chunk(
                document=document,
                text=text,
                index=index,
                start_line=line,
                end_line=line + line_count,
            )
        )
        position += cut
        line += line_count
        index += 1

    if not chunks:
        chunks.append(Chunk(document=document, text="", index=0, start_line=1, end_line=1))
    return _merge_short_tail(chunks)


def _boundary(text: str, budget: int) -> int:
    """Find the cut point: paragraph break, then line break, then hard cut."""
    window = text[:budget]
    floor = int(budget * _BOUNDARY_FLOOR)

    paragraph = window.rfind("\n\n")
    if paragraph >= floor:
        return paragraph + 2
    newline = window.rfind("\n")
    if newline >= floor:
        return newline + 1
    return budget


def _merge_short_tail(chunks: list[Chunk]) -> list[Chunk]:
    """Fold a runt final chunk into its predecessor."""
    if len(chunks) < 2:
        return chunks
    tail = chunks[-1]
    if len(tail.text) >= MIN_CHUNK_TOKENS * _BYTES_PER_TOKEN:
        return chunks
    previous = chunks[-2]
    merged = Chunk(
        document=previous.document,
        text=previous.text + tail.text,
        index=previous.index,
        start_line=previous.start_line,
        end_line=tail.end_line,
    )
    return [*chunks[:-2], merged]


def reduce_packed(
    *,
    strategy: str,
    candidates: list[ContextDocument],
    ordered: list[ContextDocument],
    query: str,
    max_tokens: int,
    max_bytes: int,
    max_documents: int,
    estimator: TokenEstimator,
    render_order: str,
    chunk_tokens: int | None = None,
    tuning: ContextTuning = DEFAULT_TUNING,
    duplicates: DuplicateMap = DuplicateMap(),
    rank_cache: RankCache | None = None,
) -> Reduction:
    """Pack the best-ranked chunks of the corpus into the budget.

    Pinned documents go in whole, first. The rest are chunked, every chunk is ranked
    against the query, and chunks are admitted in rank order until the budget is spent.

    Args:
        strategy: The requested strategy name, preserved on the result.
        candidates: Every offered document.
        ordered: The documents that survived duplicate collapse, in rank order.
        query: What the request is about.
        max_tokens: Token budget.
        max_bytes: Byte ceiling.
        max_documents: Ceiling on *documents* represented, not chunks.
        estimator: Token counting strategy.
        render_order: ``path`` or ``rank``; ``path`` groups a document's chunks together.
        chunk_tokens: Target chunk size; ``tuning.chunk_tokens`` when omitted.
        tuning: Supplies the chunk size and the query-expansion settings chunk ranking
            uses, so a chunk is scored against the same expanded query a document is.
        duplicates: Documents collapsed into others, rendered as pointers beside their
            representative.
        rank_cache: Corpus statistics; rebuilt when absent.

    Returns:
        The `Reduction`, with chunk counts in ``tier_metadata``.
    """
    constraints: set[str] = set()
    used_tokens = estimator.estimate(wrapper_text()).tokens
    used_bytes = wrapper_bytes()
    size = chunk_tokens if chunk_tokens is not None else tuning.chunk_tokens

    pinned = [document for document in ordered if document.pinned]
    unpinned = [document for document in ordered if not document.pinned]

    whole: list[ContextDocument] = []
    for document in pinned:
        if len(whole) >= max_documents:
            constraints.add("document count")
            break
        block = _blocks_for(document, duplicates)
        cost_tokens = estimator.estimate(block).tokens
        cost_bytes = block_bytes(block)
        if used_tokens + cost_tokens > max_tokens:
            constraints.add("tokens")
            continue
        if used_bytes + cost_bytes > max_bytes:
            constraints.add("bytes")
            continue
        whole.append(document)
        used_tokens += cost_tokens
        used_bytes += cost_bytes

    chunks: list[Chunk] = []
    for document in unpinned:
        chunks.extend(split_document(document, chunk_tokens=size))

    corpus = rank_cache or build_rank_cache(ordered, split_identifiers=tuning.split_identifiers)
    ranked_chunks = _rank_chunks(chunks, query, corpus, ordered, tuning)

    selected: list[Chunk] = []
    represented = {document.path for document in whole}
    for chunk in ranked_chunks:
        path = chunk.document.path
        if path not in represented and len(represented) >= max_documents:
            constraints.add("document count")
            continue
        block = render_chunk_block(chunk.document, chunk.text, chunk.start_line, chunk.end_line)
        cost_tokens = estimator.estimate(block).tokens
        cost_bytes = block_bytes(block)
        if used_tokens + cost_tokens > max_tokens:
            constraints.add("tokens")
            continue
        if used_bytes + cost_bytes > max_bytes:
            constraints.add("bytes")
            continue
        selected.append(chunk)
        represented.add(path)
        used_tokens += cost_tokens
        used_bytes += cost_bytes

    text = _render(whole, selected, render_order, duplicates)
    represented_documents = {document.path: document for document in whole}
    for chunk in selected:
        represented_documents.setdefault(chunk.document.path, chunk.document)
    documents = sorted(represented_documents.values(), key=lambda d: (d.path, d.sha256))
    exact, near = _collapse_counts(duplicates)
    partial = _partial_count(chunks, selected)

    return Reduction(
        strategy=strategy,
        representation="packed",
        documents=tuple(documents),
        candidate_count=len(candidates),
        text=text,
        estimated_tokens=estimator.estimate(text).tokens,
        max_tokens=max_tokens,
        max_bytes=max_bytes,
        max_documents=max_documents,
        total_bytes=len(text.encode("utf-8")),
        binding_constraints=_order_constraints(constraints),
        collapsed_exact=exact,
        collapsed_near=near,
        partial_count=partial,
        tier_metadata={
            "whole_documents": len(whole),
            "chunks_selected": len(selected),
            "chunks_available": len(chunks),
            "partial_documents": partial,
            "chunk_tokens": size,
        },
    )


def _partial_count(available: Sequence[Chunk], selected: Sequence[Chunk]) -> int:
    """How many documents were represented by only some of their chunks.

    A document whose every chunk was admitted arrived whole, even though it was rendered
    as spans — reporting it as partial would understate a reduction that lost nothing.
    """
    totals: Counter[str] = Counter(chunk.document.path for chunk in available)
    taken: Counter[str] = Counter(chunk.document.path for chunk in selected)
    return sum(1 for path, count in taken.items() if count < totals[path])


def _rank_chunks(
    chunks: list[Chunk],
    query: str,
    corpus: RankCache,
    documents: Sequence[ContextDocument],
    tuning: ContextTuning,
) -> list[Chunk]:
    """Order chunks by relevance, tie-broken by path then position.

    A chunk is scored as a small document whose body is the chunk text but whose path
    signals, including the anchor bonus — come from its parent, so a chunk of
    ``credentials.py`` still benefits from its filename. Query expansion is resolved once
    against the whole corpus rather than per chunk: feedback terms harvested from a single
    chunk would describe that chunk, not the query.
    """
    terms = expand_query(query, documents, cache=corpus, tuning=tuning)
    scored: list[tuple[Chunk, float]] = []
    for chunk in chunks:
        surrogate = ContextDocument(
            path=chunk.document.path,
            content=chunk.text,
            sha256=chunk.document.sha256,
            pinned=False,
            language=chunk.document.language,
        )
        scored.append(
            (chunk, score_document(surrogate, terms, _chunk_cache(surrogate, corpus, tuning)))
        )

    scored.sort(key=lambda pair: (-pair[1], pair[0].document.path, pair[0].index))
    return [chunk for chunk, _ in scored]


def _chunk_cache(
    surrogate: ContextDocument, corpus: RankCache, tuning: ContextTuning
) -> RankCache:
    """Build a per-chunk cache that keeps the corpus's document-frequency statistics.

    Term frequencies come from the chunk; inverse document frequency comes from the whole
    corpus, so a term that is rare corpus-wide still scores as rare inside a chunk.
    """
    tokens = tokenize(surrogate.content, split_identifiers=tuning.split_identifiers)
    return RankCache(
        term_counts={surrogate.path: Counter(tokens)},
        document_frequency=corpus.document_frequency,
        document_lengths={surrogate.path: len(tokens)},
        total_documents=max(1, corpus.total_documents),
        split_identifiers=tuning.split_identifiers,
    )


def _render(
    whole: list[ContextDocument],
    chunks: list[Chunk],
    render_order: str,
    duplicates: DuplicateMap,
) -> str:
    """Render whole documents and coalesced chunk spans into one envelope."""
    blocks: list[tuple[str, str]] = [
        (document.path, _blocks_for(document, duplicates)) for document in whole
    ]

    by_document: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_document.setdefault(chunk.document.path, []).append(chunk)

    for path, group in by_document.items():
        group.sort(key=lambda c: c.index)
        for run in _coalesce(group):
            first, last = run[0], run[-1]
            blocks.append(
                (
                    path,
                    render_chunk_block(
                        first.document,
                        "".join(chunk.text for chunk in run),
                        first.start_line,
                        last.end_line,
                    ),
                )
            )

    if render_order != "rank":
        blocks.sort(key=lambda pair: pair[0])
    return render_corpus(block for _, block in blocks)


def _coalesce(group: list[Chunk]) -> list[list[Chunk]]:
    """Group index-adjacent chunks into contiguous runs."""
    runs: list[list[Chunk]] = []
    for chunk in group:
        if runs and chunk.index == runs[-1][-1].index + 1:
            runs[-1].append(chunk)
        else:
            runs.append([chunk])
    return runs
