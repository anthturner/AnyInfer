"""History compaction: fit a conversation, not a corpus.

The rest of this subpackage reduces material an app collected. This module reduces
material the app *produced* — the conversation so far. In any agentic loop that is where
the window actually goes: tool results are large, numerous, and almost never re-read, and
a transcript that has grown past the budget is the most common way a working application
starts failing.

The rules are chosen so the result is still a *valid* conversation, which is the part
naive truncation gets wrong:

- **System messages are never touched.** They are instructions, not history.
- **The recent window is never touched.** The last few turns are what the model is
  actually answering.
- **Tool-call pairing is never broken.** A message carrying a `ToolCall` or a `ToolResult`
  is never dropped, only emptied — providers reject a call with no result and a result
  with no call, so dropping one of a pair trades an oversized request for a rejected one.
- **Elision is visible in the transcript.** An emptied payload is replaced by a marker
  saying how much went, not by silence.

This is a pure function: messages in, messages out. It never touches
`GenerationRequest.messages` and issues no calls — where the compacted history goes is the
application's decision, exactly as the context envelope's placement is.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from ..capabilities.estimate import (
    PER_MESSAGE_OVERHEAD_TOKENS,
    HeuristicTokenEstimator,
    TokenEstimator,
)
from ..events.observers import Observer
from ..events.telemetry import ContextReduced
from ..types.messages import ContentPart, Message, Text, ToolCall, ToolResult

__all__ = [
    "DEFAULT_KEEP_RECENT",
    "MIN_ELIDABLE_CHARS",
    "HistoryCompaction",
    "compact_history",
]

DEFAULT_KEEP_RECENT = 6
"""Trailing messages held at full fidelity.

Six covers a tool call, its result, and the exchange around them — enough that the model
is never asked to continue from a turn it cannot see.
"""

MIN_ELIDABLE_CHARS = 200
"""Payloads shorter than this are left alone; the marker would cost more than it saves."""


def _marker(characters: int) -> str:
    """The stand-in for an elided payload."""
    return f"[elided {characters} characters]"


@dataclass(frozen=True, slots=True)
class HistoryCompaction:
    """What compaction produced, and what it cost.

    Attributes:
        messages: The compacted conversation, ready to send.
        original_count: Messages offered.
        dropped_count: Messages removed entirely.
        elided_results: Tool results whose payload was replaced by a marker.
        elided_texts: Text parts whose payload was replaced by a marker.
        estimated_tokens: Planning-side estimate of the compacted conversation.
        original_tokens: The same estimate before compaction.
        max_tokens: The budget it was held to.
        fits: Whether the result is within that budget. ``False`` means the protected
            messages alone exceed it, and no further compaction was available — the
            caller decides what to do, because dropping a system prompt or the current
            turn is not a decision a library should make quietly.
    """

    messages: tuple[Message, ...]
    original_count: int
    dropped_count: int
    elided_results: int
    elided_texts: int
    estimated_tokens: int
    original_tokens: int
    max_tokens: int
    fits: bool

    @property
    def changed(self) -> bool:
        """Whether anything was dropped or elided at all."""
        return bool(self.dropped_count or self.elided_results or self.elided_texts)

    @property
    def complete(self) -> bool:
        """Whether the conversation reached the model intact."""
        return not self.changed and self.fits

    @property
    def saved_tokens(self) -> int:
        """How many planning tokens compaction recovered."""
        return max(0, self.original_tokens - self.estimated_tokens)

    def metadata(self) -> dict[str, Any]:
        """The full machine-readable record, for logging or a debug pane."""
        return {
            "original_count": self.original_count,
            "kept_count": len(self.messages),
            "dropped_count": self.dropped_count,
            "elided_results": self.elided_results,
            "elided_texts": self.elided_texts,
            "original_tokens": self.original_tokens,
            "estimated_tokens": self.estimated_tokens,
            "saved_tokens": self.saved_tokens,
            "max_tokens": self.max_tokens,
            "fits": self.fits,
            "complete": self.complete,
        }

    def summary(self) -> str:
        """A one-line, content-free description of what happened.

        Safe to show a user or write to a log: counts and ceilings only, never message
        text.
        """
        parts = [
            f"history: {len(self.messages)} of {self.original_count} message(s)",
            f"~{self.estimated_tokens} of {self.max_tokens} tokens",
        ]
        if self.dropped_count:
            parts.append(f"{self.dropped_count} dropped")
        if self.elided_results or self.elided_texts:
            parts.append(f"{self.elided_results + self.elided_texts} payload(s) elided")
        if not self.fits:
            parts.append("still over budget")
        return "; ".join(parts)

    def event(self) -> ContextReduced:
        """Build the telemetry event describing this compaction."""
        return ContextReduced(
            strategy="history",
            representation="compacted" if self.changed else "whole",
            candidate_count=self.original_count,
            selected_count=len(self.messages),
            omitted_count=self.dropped_count,
            estimated_tokens=self.estimated_tokens,
            max_tokens=self.max_tokens,
            binding_constraints=() if self.fits else ("tokens",),
        )


def compact_history(
    messages: Iterable[Message],
    *,
    max_tokens: int,
    estimator: TokenEstimator | None = None,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    keep_system: bool = True,
    observer: Observer | None = None,
) -> HistoryCompaction:
    """Shrink a conversation to fit a token budget without invalidating it.

    Three passes over the unprotected middle, cheapest loss first: tool-result payloads
    are elided, then long text payloads, then plain messages are dropped outright. Each
    pass stops the moment the conversation fits, so a transcript that needs one large
    tool result elided loses exactly that and nothing else.

    Args:
        messages: The conversation so far.
        max_tokens: The budget. Normally ``client.budget(...).remaining_tokens`` less
            whatever the next turn will add — an explicit number, because an unknown
            window stays unknown.
        estimator: Token counting strategy; defaults to the byte heuristic.
        keep_recent: Trailing messages held at full fidelity.
        keep_system: Whether system messages are protected wherever they appear. Leave
            this on unless the application's system prompt is genuinely disposable.
        observer: Receives a `ContextReduced` event describing the outcome.

    Returns:
        The `HistoryCompaction`. Check ``fits``: a conversation whose protected messages
        alone exceed the budget comes back unchanged and honest rather than mutilated.

    Raises:
        ValueError: On a non-positive budget or a negative ``keep_recent``.
    """
    if max_tokens < 1:
        raise ValueError(f"max_tokens must be positive; got {max_tokens}")
    if keep_recent < 0:
        raise ValueError(f"keep_recent must be zero or greater; got {keep_recent}")

    original = list(messages)
    counter = estimator or HeuristicTokenEstimator()
    costs = [_message_tokens(message, counter) for message in original]
    original_tokens = sum(costs)

    if original_tokens <= max_tokens:
        return _finish(
            tuple(original),
            original=original,
            dropped=0,
            elided_results=0,
            elided_texts=0,
            tokens=original_tokens,
            original_tokens=original_tokens,
            max_tokens=max_tokens,
            observer=observer,
        )

    protected = _protected_indices(original, keep_recent=keep_recent, keep_system=keep_system)
    working = list(original)
    total = original_tokens
    middle = [index for index in range(len(original)) if index not in protected]

    elided_results = 0
    elided_texts = 0

    for index in middle:
        if total <= max_tokens:
            break
        rewritten, count = _elide_results(working[index])
        if count:
            total += _recost(working, costs, index, rewritten, counter)
            working[index] = rewritten
            elided_results += count

    for index in middle:
        if total <= max_tokens:
            break
        rewritten, count = _elide_texts(working[index])
        if count:
            total += _recost(working, costs, index, rewritten, counter)
            working[index] = rewritten
            elided_texts += count

    dropped: set[int] = set()
    for index in middle:
        if total <= max_tokens:
            break
        if _carries_tools(working[index]):
            # Dropping half a call/result pair turns an oversized request into a
            # rejected one. Its payload is already a marker; that is all we take.
            continue
        dropped.add(index)
        total -= costs[index]

    kept = tuple(message for index, message in enumerate(working) if index not in dropped)
    return _finish(
        kept,
        original=original,
        dropped=len(dropped),
        elided_results=elided_results,
        elided_texts=elided_texts,
        tokens=total,
        original_tokens=original_tokens,
        max_tokens=max_tokens,
        observer=observer,
    )


def _finish(
    kept: tuple[Message, ...],
    *,
    original: Sequence[Message],
    dropped: int,
    elided_results: int,
    elided_texts: int,
    tokens: int,
    original_tokens: int,
    max_tokens: int,
    observer: Observer | None,
) -> HistoryCompaction:
    """Assemble the result and emit its telemetry."""
    compaction = HistoryCompaction(
        messages=kept,
        original_count=len(original),
        dropped_count=dropped,
        elided_results=elided_results,
        elided_texts=elided_texts,
        estimated_tokens=tokens,
        original_tokens=original_tokens,
        max_tokens=max_tokens,
        fits=tokens <= max_tokens,
    )
    if observer is not None:
        observer.on_event(compaction.event())
    return compaction


def _protected_indices(
    messages: Sequence[Message], *, keep_recent: int, keep_system: bool
) -> set[int]:
    """Indices compaction must not touch."""
    protected = set(range(max(0, len(messages) - keep_recent), len(messages)))
    if keep_system:
        protected.update(
            index for index, message in enumerate(messages) if message.role == "system"
        )
    return protected


def _recost(
    working: Sequence[Message],
    costs: list[int],
    index: int,
    rewritten: Message,
    estimator: TokenEstimator,
) -> int:
    """Update the cost table for one rewritten message, returning the delta."""
    updated = _message_tokens(rewritten, estimator)
    delta = updated - costs[index]
    costs[index] = updated
    return delta


def _elide_results(message: Message) -> tuple[Message, int]:
    """Replace substantial tool-result payloads with a marker."""
    parts: list[ContentPart] = []
    elided = 0
    for part in message.content:
        if isinstance(part, ToolResult) and len(part.content) >= MIN_ELIDABLE_CHARS:
            parts.append(replace(part, content=_marker(len(part.content))))
            elided += 1
        else:
            parts.append(part)
    return (replace(message, content=tuple(parts)), elided) if elided else (message, 0)


def _elide_texts(message: Message) -> tuple[Message, int]:
    """Replace substantial text payloads with a marker."""
    parts: list[ContentPart] = []
    elided = 0
    for part in message.content:
        if isinstance(part, Text) and len(part.text) >= MIN_ELIDABLE_CHARS:
            parts.append(Text(_marker(len(part.text))))
            elided += 1
        else:
            parts.append(part)
    return (replace(message, content=tuple(parts)), elided) if elided else (message, 0)


def _carries_tools(message: Message) -> bool:
    """Whether a message participates in a tool-call pairing."""
    return any(isinstance(part, ToolCall | ToolResult) for part in message.content)


def _message_tokens(message: Message, estimator: TokenEstimator) -> int:
    """Planning-side token cost of one message, wire framing included.

    The same accounting the request estimator performs, so a budget computed there and a
    compaction performed here agree about what a message costs.
    """
    parts: list[str] = []
    for part in message.content:
        if isinstance(part, Text):
            parts.append(part.text)
        elif isinstance(part, ToolCall):
            parts.append(part.name)
            parts.append(json.dumps(dict(part.arguments), default=str))
        elif isinstance(part, ToolResult):
            parts.append(part.content)
    return estimator.estimate("".join(parts)).tokens + PER_MESSAGE_OVERHEAD_TOKENS
