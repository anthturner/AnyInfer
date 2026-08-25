"""Per-attempt accumulation: deltas in, one `Generation` out.

Everything measured here is measured identically for every provider — that uniformity is the
point of centralizing it. Adapters report only what their wire protocol
gave them; TTFT, throughput, and total duration are the core's numbers.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..types.events import CitationDelta, ReasoningDelta, TextDelta, ToolCallDelta
from ..types.messages import ToolCall
from ..types.requests import CacheMechanism, ResolvedTarget
from ..types.results import Citation, FinishReason, Timing, TokenLogprob, Usage

__all__ = ["AttemptBuffer", "ToolCallBuffer"]


@dataclass(slots=True)
class ToolCallBuffer:
    """Accumulates one tool call's fragments across deltas."""

    index: int
    call_id: str | None = None
    name: str | None = None
    arguments: str = ""

    def absorb(self, delta: ToolCallDelta) -> None:
        """Merge a fragment into this slot."""
        if delta.call_id:
            self.call_id = delta.call_id
        if delta.name:
            self.name = delta.name
        self.arguments += delta.arguments_fragment

    def build(self) -> tuple[ToolCall, str | None]:
        """Finalize into a `ToolCall`, plus a warning when arguments were unusable.

        A model that emits malformed arguments should not fail the whole generation: the
        caller gets an empty argument mapping and an explicit warning, and can decide.
        """
        parsed: Mapping[str, Any] = {}
        warning: str | None = None
        text = self.arguments.strip()
        if text:
            try:
                candidate = json.loads(text)
            except ValueError:
                warning = (
                    f"tool call {self.name or self.index} had unparseable arguments; "
                    "using an empty argument object"
                )
            else:
                if isinstance(candidate, Mapping):
                    parsed = candidate
                else:
                    warning = (
                        f"tool call {self.name or self.index} arguments were not a JSON "
                        "object; using an empty argument object"
                    )
        return (
            ToolCall(
                id=self.call_id or f"call_{self.index}",
                name=self.name or "",
                arguments=parsed,
            ),
            warning,
        )


@dataclass(slots=True)
class AttemptBuffer:
    """Accumulates one attempt's events and derives its timings."""

    target: ResolvedTarget
    started_at: float = field(default_factory=time.monotonic)
    text_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    tool_calls: dict[int, ToolCallBuffer] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    finish_reason: FinishReason = "stop"
    phases: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    first_token_ms: float | None = None
    raw: Any | None = None
    logprobs: tuple[TokenLogprob, ...] = ()
    citations: list[Citation] = field(default_factory=list)
    cache_mechanism: CacheMechanism | None = None
    """Which prompt-cache mechanism was engaged for this attempt, when any was.

    Carried on the buffer rather than derived at assembly time because the decision is made
    once, before dispatch, and a repair round trip reuses it.
    """

    def absorb(self, event: TextDelta | ReasoningDelta | ToolCallDelta | CitationDelta) -> None:
        """Accumulate one content event."""
        if isinstance(event, TextDelta):
            self.text_parts.append(event.text)
        elif isinstance(event, ReasoningDelta):
            self.reasoning_parts.append(event.text)
        elif isinstance(event, CitationDelta):
            self.citations.append(event.citation)
        else:
            slot = self.tool_calls.get(event.index)
            if slot is None:
                slot = ToolCallBuffer(index=event.index)
                self.tool_calls[event.index] = slot
            slot.absorb(event)

    def mark_first_token(self, now: float) -> float:
        """Record TTFT and return it in milliseconds."""
        elapsed_ms = (now - self.started_at) * 1000.0
        self.first_token_ms = elapsed_ms
        return elapsed_ms

    @property
    def text(self) -> str:
        """The answer text accumulated so far."""
        return "".join(self.text_parts)

    def build_tool_calls(self) -> tuple[ToolCall, ...]:
        """Finalize every tool-call slot in index order, collecting warnings."""
        calls: list[ToolCall] = []
        for index in sorted(self.tool_calls):
            call, warning = self.tool_calls[index].build()
            calls.append(call)
            if warning:
                self.warnings.append(warning)
        return tuple(calls)

    def build_timing(self, now: float | None = None) -> Timing:
        """Derive this attempt's timing.

        Throughput is measured over the *decode* window (first token to completion), not the
        whole request: including queue and prefill time would understate a model's actual
        generation rate and make providers incomparable.
        """
        end = time.monotonic() if now is None else now
        total_ms = (end - self.started_at) * 1000.0
        tokens_per_s: float | None = None
        output_tokens = self.usage.output_tokens
        if output_tokens and self.first_token_ms is not None:
            decode_ms = total_ms - self.first_token_ms
            if decode_ms > 0:
                tokens_per_s = output_tokens / (decode_ms / 1000.0)
        return Timing(
            started_at=self.started_at,
            first_token_ms=self.first_token_ms,
            total_ms=total_ms,
            output_tokens_per_s=tokens_per_s,
            phases=dict(self.phases),
        )
