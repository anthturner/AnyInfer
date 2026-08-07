"""The ``distill`` strategy: map/reduce a corpus that will never fit.

The other strategies decide what to *drop*. This one reads everything and writes something
shorter: each chunk is summarized against the query (the map phase), then the notes are
synthesized into one answer (the reduce phase).

It is separated from `anyinfer.context.select` by construction, because it is the one
strategy that **spends money**. It takes your client, issues real generation calls, and
reports the count and aggregate usage so the multiplier is never a surprise.

Two properties distinguish this from a naive map/reduce. Reduction is **hierarchical**: if
the map notes together exceed the target's window, they are reduced in batches and the
batch summaries reduced again, rather than being sent in one overflowing request. And a
**deterministic reducer** can replace the reduce call entirely, so an application that
merges structurally pays for the map phase only.

Prompts here are mechanical scaffolding — "here is chunk 3 of 9, take notes" — not
application prose. You own the question; override ``map_instructions`` and
``reduce_instructions`` to own the framing too.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..capabilities.budget import ContextBudget
from ..errors import ConfigError
from ..events.observers import Observer
from ..events.telemetry import ContextReduced
from ..types.requests import Sampling
from ..types.results import Generation, Usage
from .documents import ContextDocument
from .pack import DEFAULT_CHUNK_TOKENS, Chunk, split_document

__all__ = [
    "DEFAULT_CONCURRENCY",
    "Distillation",
    "SupportsGenerate",
    "SupportsGenerateSync",
    "distill",
    "distill_sync",
]

DEFAULT_CONCURRENCY = 4
"""Map calls in flight at once. Bounded because a fan-out is someone's rate limit."""

_MAP_INSTRUCTIONS = (
    "You are reading one part of a larger body of material. Take notes that answer the "
    "request below, using only what this part contains. Preserve specific facts, names, "
    "and figures. Do not write a final answer, and do not mention that the material was "
    "split into parts."
)

_REDUCE_INSTRUCTIONS = (
    "Below are notes taken from separate parts of one body of material. Synthesize them "
    "into a single coherent answer to the request. Do not mention notes, parts, or "
    "chunks; write as though you read the whole thing."
)

_LABEL_PATTERNS = (
    re.compile(r"^#{1,6}\s*(chunk|part|section)\s+\d+.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(
        r"^(intermediate\s+)?notes?\s+\d+(\s+of\s+\d+)?\s*:?\s*$", re.IGNORECASE | re.MULTILINE
    ),
)
"""Scaffolding labels a model sometimes echoes; stripped from the final text."""

_BLANK_RUN = re.compile(r"\n{3,}")


@runtime_checkable
class SupportsGenerate(Protocol):
    """The slice of an async client `distill()` needs.

    A structural protocol rather than an import, so this subpackage never depends on the
    client — `anyinfer.AsyncClient` satisfies it as-is.
    """

    async def generate(self, messages: Any, *, target: str, **kwargs: Any) -> Generation:
        """Generate one result."""
        ...

    def budget(self, messages: Any, *, target: str, **kwargs: Any) -> ContextBudget:
        """Compute a context budget without issuing a request."""
        ...


@runtime_checkable
class SupportsGenerateSync(Protocol):
    """The synchronous mirror of `SupportsGenerate`, satisfied by `anyinfer.Client`."""

    def generate(self, messages: Any, *, target: str, **kwargs: Any) -> Generation:
        """Generate one result."""
        ...

    def budget(self, messages: Any, *, target: str, **kwargs: Any) -> ContextBudget:
        """Compute a context budget without issuing a request."""
        ...


@dataclass(frozen=True, slots=True)
class Distillation:
    """What a distillation produced, and what it cost.

    Attributes:
        text: The synthesized answer.
        chunk_count: How many chunks the source was split into.
        calls: Total generation calls spent, map and reduce together. This is the
            multiplier over a single request.
        usage: Merged usage across every call, including cost when providers report it.
        reduce_depth: 1 for a single-pass reduce; higher when notes were reduced in
            batches and the batch summaries reduced again.
        notes: The intermediate map outputs. Payload-bearing — excluded from ``repr``
            and never placed in telemetry.
    """

    text: str
    chunk_count: int
    calls: int
    usage: Usage
    reduce_depth: int = 1
    notes: tuple[str, ...] = field(default=(), repr=False)

    def summary(self) -> str:
        """A one-line, content-free description of the run."""
        return (
            f"distilled {self.chunk_count} chunk(s) in {self.calls} call(s), "
            f"reduce depth {self.reduce_depth}"
        )

    def event(self, *, max_tokens: int) -> ContextReduced:
        """Build the telemetry event describing this distillation."""
        return ContextReduced(
            strategy="distill",
            representation="distill",
            candidate_count=self.chunk_count,
            selected_count=self.chunk_count,
            omitted_count=0,
            estimated_tokens=self.usage.output_tokens or 0,
            max_tokens=max_tokens,
            calls=self.calls,
        )


async def distill(
    source: str | Iterable[ContextDocument],
    query: str,
    *,
    client: SupportsGenerate,
    target: str,
    max_output_tokens: int = 1024,
    chunk_tokens: int | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    map_instructions: str | None = None,
    reduce_instructions: str | None = None,
    reducer: Callable[[Sequence[str]], str] | None = None,
    observer: Observer | None = None,
) -> Distillation:
    """Summarize a corpus larger than the window by mapping and reducing over it.

    Args:
        source: Raw text, or documents. Documents split per document, because a document
            boundary is a natural chunk boundary.
        query: What the summary should answer.
        client: Anything satisfying `SupportsGenerate` — normally an
            `anyinfer.AsyncClient`.
        target: Where to send the calls.
        max_output_tokens: Ceiling on the final answer.
        chunk_tokens: Chunk size. Derived from the target's remaining budget when
            omitted.
        concurrency: Map calls in flight at once.
        map_instructions: Replaces the default note-taking instruction.
        reduce_instructions: Replaces the default synthesis instruction.
        reducer: Merge the notes deterministically instead of with a reduce call. Saves
            every reduce call, and makes the merge reproducible.
        observer: Receives a `ContextReduced` event when the run finishes.

    Returns:
        The `Distillation`.

    Raises:
        ConfigError: When ``chunk_tokens`` is omitted and the target's context window is
            unknown. An unknown window stays unknown — the caller chooses the number.
    """
    from ..types.messages import user

    map_prompt = map_instructions or _MAP_INSTRUCTIONS
    resolved_chunk_tokens = chunk_tokens or _derive_chunk_tokens(
        client, target=target, map_prompt=map_prompt, query=query
    )

    chunks = _chunks_for(source, chunk_tokens=resolved_chunk_tokens)
    if not chunks:
        return Distillation(text="", chunk_count=0, calls=0, usage=Usage())

    map_cap = _map_output_cap(len(chunks), max_output_tokens)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run_map(position: int, chunk: str) -> Generation:
        async with semaphore:
            return await client.generate(
                [user(_map_message(map_prompt, query, chunk, position, len(chunks)))],
                target=target,
                sampling=Sampling(max_output_tokens=map_cap),
            )

    results = await asyncio.gather(
        *(run_map(index, text) for index, text in enumerate(chunks, start=1))
    )
    notes = [result.text for result in results]
    usage = _merge_usage(result.usage for result in results)
    calls = len(results)

    if reducer is not None:
        # A deterministic merge spends nothing and is reproducible.
        return _finish(reducer(notes), chunks, calls, usage, 1, notes, observer, max_output_tokens)

    text, reduce_calls, reduce_usage, depth = await _reduce(
        notes,
        query=query,
        client=client,
        target=target,
        instructions=reduce_instructions or _REDUCE_INSTRUCTIONS,
        max_output_tokens=max_output_tokens,
    )
    usage = _merge_usage([usage, reduce_usage]) if reduce_usage else usage
    return _finish(
        text, chunks, calls + reduce_calls, usage, depth, notes, observer, max_output_tokens
    )


def distill_sync(
    source: str | Iterable[ContextDocument],
    query: str,
    *,
    client: SupportsGenerateSync,
    target: str,
    max_output_tokens: int = 1024,
    chunk_tokens: int | None = None,
    map_instructions: str | None = None,
    reduce_instructions: str | None = None,
    reducer: Callable[[Sequence[str]], str] | None = None,
    observer: Observer | None = None,
) -> Distillation:
    """Run `distill()` sequentially against a synchronous client.

    Chunks are processed one at a time: concurrency is the async path's feature, and a
    sync caller that wants it should use `distill()` with an `anyinfer.AsyncClient`.

    Args and returns are as `distill()`, minus ``concurrency``.

    Raises:
        ConfigError: When ``chunk_tokens`` is omitted and the window is unknown.
    """
    from ..types.messages import user

    map_prompt = map_instructions or _MAP_INSTRUCTIONS
    resolved_chunk_tokens = chunk_tokens or _derive_chunk_tokens(
        client, target=target, map_prompt=map_prompt, query=query
    )
    chunks = _chunks_for(source, chunk_tokens=resolved_chunk_tokens)
    if not chunks:
        return Distillation(text="", chunk_count=0, calls=0, usage=Usage())

    map_cap = _map_output_cap(len(chunks), max_output_tokens)
    results = [
        client.generate(
            [user(_map_message(map_prompt, query, text, index, len(chunks)))],
            target=target,
            sampling=Sampling(max_output_tokens=map_cap),
        )
        for index, text in enumerate(chunks, start=1)
    ]
    notes = [result.text for result in results]
    usage = _merge_usage(result.usage for result in results)

    if reducer is not None:
        return _finish(
            reducer(notes),
            chunks,
            len(results),
            usage,
            1,
            notes,
            observer,
            max_output_tokens,
        )

    merged = client.generate(
        [user(_reduce_message(reduce_instructions or _REDUCE_INSTRUCTIONS, query, notes))],
        target=target,
        sampling=Sampling(max_output_tokens=max_output_tokens),
    )
    usage = _merge_usage([usage, merged.usage])
    return _finish(
        merged.text,
        chunks,
        len(results) + 1,
        usage,
        1,
        notes,
        observer,
        max_output_tokens,
    )


async def _reduce(
    notes: list[str],
    *,
    query: str,
    client: SupportsGenerate,
    target: str,
    instructions: str,
    max_output_tokens: int,
) -> tuple[str, int, Usage | None, int]:
    """Synthesize notes, recursing in batches when they will not fit at once."""
    from ..types.messages import user

    depth = 1
    calls = 0
    usage: Usage | None = None
    current = notes

    while True:
        message = _reduce_message(instructions, query, current)

        if _fits(client, message, target) or len(current) == 1:
            result = await client.generate(
                [user(message)],
                target=target,
                sampling=Sampling(max_output_tokens=max_output_tokens),
            )
            calls += 1
            usage = _merge_usage([usage, result.usage] if usage else [result.usage])
            return _strip_labels(result.text), calls, usage, depth

        # Too much to synthesize in one call: summarize in batches, then summarize the
        # summaries. A single-pass reduce would simply overflow here.
        summaries: list[str] = []
        for batch in _fitting_batches(current, client, instructions, query, target):
            result = await client.generate(
                [user(_reduce_message(instructions, query, batch))],
                target=target,
                sampling=Sampling(max_output_tokens=max_output_tokens),
            )
            calls += 1
            usage = _merge_usage([usage, result.usage] if usage else [result.usage])
            summaries.append(result.text)

        # No progress means the notes are individually too large for this target, and
        # batching further would loop — so take the first summary and stop.
        current = summaries[:1] if len(summaries) >= len(current) else summaries
        depth += 1


def _fits(client: SupportsGenerate | SupportsGenerateSync, message: str, target: str) -> bool:
    """Whether one reduce message fits the target's window.

    An unknown window reports ``None``, which is treated as "proceed" — the same rule
    the pre-dispatch gate uses, since refusing on an unknown is worse than one failed
    round trip.
    """
    from ..types.messages import user

    return client.budget([user(message)], target=target).fits is not False


def _fitting_batches(
    notes: Sequence[str],
    client: SupportsGenerate | SupportsGenerateSync,
    instructions: str,
    query: str,
    target: str,
) -> list[list[str]]:
    """Group notes into batches that each fit the target's window.

    Sizing by count alone does not converge — halving a list of notes that are each
    large still yields batches that overflow. Batches are grown note by note and closed
    when the next one would not fit.
    """
    batches: list[list[str]] = []
    current: list[str] = []

    for note in notes:
        candidate = [*current, note]
        if current and not _fits(client, _reduce_message(instructions, query, candidate), target):
            batches.append(current)
            current = [note]
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches


def _finish(
    text: str,
    chunks: list[str],
    calls: int,
    usage: Usage,
    depth: int,
    notes: list[str],
    observer: Observer | None,
    max_output_tokens: int,
) -> Distillation:
    """Assemble the result and emit its telemetry."""
    distillation = Distillation(
        text=_strip_labels(text),
        chunk_count=len(chunks),
        calls=calls,
        usage=usage.normalized(),
        reduce_depth=depth,
        notes=tuple(notes),
    )
    if observer is not None:
        observer.on_event(distillation.event(max_tokens=max_output_tokens))
    return distillation


def _chunks_for(source: str | Iterable[ContextDocument], *, chunk_tokens: int) -> list[str]:
    """Split the source into chunk texts, per document when documents were supplied."""
    if isinstance(source, str):
        if not source.strip():
            return []
        document = ContextDocument(path="<input>", content=source, sha256="")
        return [chunk.text for chunk in split_document(document, chunk_tokens=chunk_tokens)]

    texts: list[str] = []
    for document in source:
        if not document.content.strip():
            continue
        pieces: list[Chunk] = split_document(document, chunk_tokens=chunk_tokens)
        texts.extend(f"{document.path}\n{piece.text}" for piece in pieces)
    return texts


def _derive_chunk_tokens(
    client: SupportsGenerate | SupportsGenerateSync,
    *,
    target: str,
    map_prompt: str,
    query: str,
) -> int:
    """Size chunks from what remains after the map prompt's own overhead.

    Raises:
        ConfigError: When the target's context window is unknown. Guessing one would be
            the 16k-fallback mistake the budget calculator already refuses to make.
    """
    from ..types.messages import user

    skeleton = _map_message(map_prompt, query, "", 1, 1)
    budget = client.budget([user(skeleton)], target=target)
    remaining = budget.remaining_tokens
    if remaining is None or remaining <= 0:
        raise ConfigError(
            f"distill needs an explicit chunk_tokens for {target!r}: its context window "
            "is unknown",
            hint="pass chunk_tokens=, or choose a target with a known context window",
        )
    return max(DEFAULT_CHUNK_TOKENS, remaining)


def _map_message(instructions: str, query: str, chunk: str, position: int, total: int) -> str:
    """Build one map-phase prompt."""
    header = f"{instructions}\n\nRequest: {query}"
    if total > 1:
        header += f"\n\n(This is part {position} of {total}.)"
    return f"{header}\n\n<chunk>\n{chunk}\n</chunk>"


def _reduce_message(instructions: str, query: str, notes: Sequence[str]) -> str:
    """Build the reduce-phase prompt from intermediate notes."""
    blocks = "\n".join(
        f'<note index="{index}">\n{note}\n</note>' for index, note in enumerate(notes, start=1)
    )
    return f"{instructions}\n\nRequest: {query}\n\n{blocks}"


def _map_output_cap(chunk_count: int, max_output_tokens: int) -> int | None:
    """Cap map-phase output so the notes themselves stay reducible.

    Many chunks means many notes; without a per-note ceiling the reduce phase inherits an
    input larger than the corpus slice that produced it.
    """
    if chunk_count <= 1 or max_output_tokens <= 768:
        return None
    if chunk_count >= 16:
        return 384
    if chunk_count >= 8:
        return 512
    return 1024


def _merge_usage(usages: Iterable[Usage]) -> Usage:
    """Sum usage across calls.

    Distinct from `Usage.merge`, which overlays a later report onto an earlier one:
    here every call is a separate charge, so the counts add.
    """
    total = Usage()
    for usage in usages:
        total = Usage(
            input_tokens=_add(total.input_tokens, usage.input_tokens),
            output_tokens=_add(total.output_tokens, usage.output_tokens),
            total_tokens=_add(total.total_tokens, usage.total_tokens),
            cache_read_tokens=_add(total.cache_read_tokens, usage.cache_read_tokens),
            cache_write_tokens=_add(total.cache_write_tokens, usage.cache_write_tokens),
            reasoning_tokens=_add(total.reasoning_tokens, usage.reasoning_tokens),
            cost_usd=_add(total.cost_usd, usage.cost_usd),
        )
    return total


def _add(current: Any, incoming: Any) -> Any:
    """Add two optional numbers, keeping ``None`` when neither side reported."""
    if current is None:
        return incoming
    if incoming is None:
        return current
    return current + incoming


def _strip_labels(text: str) -> str:
    """Remove scaffolding labels a model echoed, and collapse the gaps they leave."""
    cleaned = text
    for pattern in _LABEL_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return _BLANK_RUN.sub("\n\n", cleaned).strip()
