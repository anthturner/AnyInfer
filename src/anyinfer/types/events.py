"""Stream events: the generation primitive.

A generation *is* an ordered stream of these events; the non-streaming API drains the stream
and returns `StreamEnded.result`. The ordering guarantees below are binding and
conformance-tested:

1. Zero or more `AttemptFailed` may precede any content (failed targets, retries).
2. Within one attempt, ``TimingMark("attempt_start")`` comes first, and
   ``TimingMark("first_token")`` appears exactly once immediately before the first content
   delta.
3. `StreamEnded` is always the final event, exactly once. An unrecoverable failure
   raises instead of yielding it.
4. Within one attempt, concatenating every `TextDelta.text` equals
   ``StreamEnded.result.text``.

Guarantees 2 and 4 are scoped *per attempt*: a mid-stream schema repair re-runs the
target inside the same stream, marked by a fresh ``TimingMark("attempt_start")``. After
that mark the delta sequence restarts, and ``result.text`` reflects the final attempt
only — a consumer rendering deltas should treat each ``attempt_start`` as "clear and
start over".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .results import AttemptRecord, Generation, Usage

__all__ = [
    "AttemptFailed",
    "ReasoningDelta",
    "StreamEnded",
    "StreamEvent",
    "TextDelta",
    "TimingMark",
    "TimingMarkName",
    "ToolCallDelta",
    "UsageUpdate",
    "is_content_event",
]


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A fragment of visible answer text."""

    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    """A fragment of reasoning/thinking text, excluded from the answer text."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    """A fragment of a tool call.

    Fragments are correlated by `index` — the tool-call slot within the response.
    Concatenate `arguments_fragment` per index, then JSON-parse the result.

    Attributes:
        index: The tool-call slot within the response this fragment belongs to.
        call_id: Provider-assigned call id, on fragments that carry it.
        name: Name of the tool being called, on fragments that carry it.
        arguments_fragment: The next piece of this slot's JSON argument text; may be
            empty.
    """

    index: int
    call_id: str | None
    name: str | None
    arguments_fragment: str


@dataclass(frozen=True, slots=True)
class UsageUpdate:
    """A usage report; may arrive mid-stream and more than once."""

    usage: Usage


TimingMarkName = Literal["attempt_start", "first_token"]
"""Named points on the attempt clock."""


@dataclass(frozen=True, slots=True)
class TimingMark:
    """A centrally-measured timing point, in milliseconds since attempt start.

    Attributes:
        name: Which point on the attempt clock this marks.
        at_ms: Milliseconds elapsed since the attempt started.
    """

    name: TimingMarkName
    at_ms: float


@dataclass(frozen=True, slots=True)
class AttemptFailed:
    """A target attempt failed; a retry or fallback may follow.

    Attributes:
        record: The failed attempt's routing-trail entry: target, outcome, error
            snapshot, and any timing.
    """

    record: AttemptRecord


@dataclass(frozen=True, slots=True)
class StreamEnded:
    """Terminal event carrying the assembled result."""

    result: Generation


StreamEvent = (
    TextDelta | ReasoningDelta | ToolCallDelta | UsageUpdate | TimingMark | AttemptFailed
    | StreamEnded
)
"""Any event a consumer may observe."""


def is_content_event(event: object) -> bool:
    """Whether an event is content-bearing, i.e. it starts the first-token clock."""
    return isinstance(event, TextDelta | ReasoningDelta | ToolCallDelta)
