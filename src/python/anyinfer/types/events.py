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

from .requests import ServerToolKind
from .results import AttemptRecord, Citation, Generation, Usage

__all__ = [
    "AttemptFailed",
    "CitationDelta",
    "ReasoningDelta",
    "ServerToolDelta",
    "ServerToolSource",
    "ServerToolStatus",
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
class CitationDelta:
    """One attribution the model reported, as soon as it reported it.

    Named a *delta* to match its siblings even though a citation arrives whole: it is a
    stream event that adds to the answer, and callers rendering attributions live need it
    at the moment it lands rather than at `StreamEnded`. Every citation on the terminal
    result also appeared here first, so a consumer may use either and never both.

    Deliberately **not** a content event: a citation does not start the first-token clock.
    Cohere emits its first citation only after the span it supports, so counting one as
    first content would report a time-to-first-token later than the text the user already
    saw.

    Attributes:
        citation: The attribution, with whatever the dialect reported about it.
    """

    citation: Citation


ServerToolStatus = Literal["started", "completed", "failed"]
"""Where a provider-run tool is in its lifecycle."""


@dataclass(frozen=True, slots=True)
class ServerToolSource:
    """One source a provider-run search consulted.

    Attributes:
        url: Where it came from.
        title: The page's title, when the provider reports one.
    """

    url: str = ""
    title: str = ""


@dataclass(frozen=True, slots=True)
class ServerToolDelta:
    """A provider-run tool started, or finished and returned something.

    Emitted so a caller watching a stream can say *why* an answer paused — a web search
    takes seconds, and a stream that stops producing text for that long is otherwise
    indistinguishable from a stalled connection — and, on completion, what it found.

    Carrying the result is the point rather than a nicety. "Grounded answer with fresh web
    results" is the application feature this exists for, and an application that can render
    the answer but not the sources behind it has the less useful half. This is a *stream*
    event, on the content channel beside `TextDelta`, so carrying content is what it is for;
    the payload-free rule governs telemetry events, which these are not.

    Deliberately **not** a content event, so it does not start the first-token clock: a
    provider that searches before writing anything has not produced a token yet, and
    counting one would make time-to-first-token mean something different for those requests
    than for every other.

    Attributes:
        kind: Which capability ran.
        status: Where in its lifecycle it is.
        sources: What a search returned, in the order the provider listed it. Empty on a
            ``started`` event, and for kinds that return no sources.
        output: What a code execution printed. Empty when there was none.
        detail: Why a ``failed`` invocation failed, as the provider stated it.
    """

    kind: ServerToolKind
    status: ServerToolStatus
    sources: tuple[ServerToolSource, ...] = ()
    output: str = ""
    detail: str = ""


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
    TextDelta
    | ReasoningDelta
    | ToolCallDelta
    | CitationDelta
    | ServerToolDelta
    | UsageUpdate
    | TimingMark
    | AttemptFailed
    | StreamEnded
)
"""Any event a consumer may observe."""


def is_content_event(event: object) -> bool:
    """Whether an event is content-bearing, i.e. it starts the first-token clock."""
    return isinstance(event, TextDelta | ReasoningDelta | ToolCallDelta)
