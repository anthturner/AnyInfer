"""Result-side types: usage, timing, attempt records, and the final generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from .messages import ToolCall
from .requests import CacheMechanism, ResolvedTarget

if TYPE_CHECKING:  # pragma: no cover — imported for the annotation only
    from ..arena import ArenaResult
    from ..context_request import ContextSummary
    from ..manifest import RunManifest

__all__ = [
    "DETAIL_MAX_CHARS",
    "AttemptRecord",
    "Diagnostic",
    "DiagnosticSeverity",
    "ErrorInfo",
    "FinishReason",
    "Generation",
    "Mechanism",
    "Outcome",
    "Timing",
    "Usage",
]

DETAIL_MAX_CHARS = 512
"""Upper bound on `ErrorInfo.detail`, applied after redaction."""

DiagnosticSeverity = Literal["info", "warning"]
"""How much a runtime diagnostic should worry the caller. Never an error: a condition that
should fail a request is an exception, not a note attached to a successful one."""


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Something a provider noticed about *itself* while serving requests.

    Not an error and not a capability: an error stops a request, and a capability is a
    fact about a model. This is the third thing — the request worked, and something about
    how it worked is worth saying out loud. A model that spilled out of VRAM and is now
    running at a tenth of its expected speed answers perfectly; the caller simply has no
    way to know why it took ninety seconds unless the provider says so.

    Diagnostics are advisory by construction: collecting them never fails a request, a
    provider that cannot answer reports nothing, and nothing here is load-bearing for
    routing. Content-free — a diagnostic describes the runtime, never the prompt.

    Attributes:
        code: Stable machine-readable identifier, e.g. ``"ollama.gpu-spill"``. Callers
            match on this; the message is for people.
        severity: ``"warning"`` for a condition degrading this request, ``"info"`` for
            context that merely explains it.
        message: One human-readable sentence, already bounded and redacted.
    """

    code: str
    severity: DiagnosticSeverity
    message: str


@dataclass(frozen=True, slots=True)
class Usage:
    """Token accounting for one generation.

    Every field is optional: a provider that does not report a number leaves it ``None``
    rather than reporting a guess.

    Attributes:
        input_tokens: Tokens in the prompt, as counted by the provider.
        output_tokens: Tokens the model generated, including tool-call payloads.
        total_tokens: Prompt plus completion tokens; `normalized` fills it from the other
            two when the provider does not report it.
        cache_read_tokens: Prompt tokens served from the provider's prompt cache.
        cache_write_tokens: Prompt tokens written into the provider's prompt cache.
        reasoning_tokens: Tokens spent on hidden reasoning/thinking, where reported.
        cost_usd: Cost of the call in US dollars, computed from per-token pricing when
            pricing is known.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: Decimal | None = None

    def normalized(self) -> Usage:
        """Fill ``total_tokens`` from input + output when both are known."""
        if self.total_tokens is not None:
            return self
        if self.input_tokens is None or self.output_tokens is None:
            return self
        return replace(self, total_tokens=self.input_tokens + self.output_tokens)

    def merge(self, other: Usage) -> Usage:
        """Overlay ``other``'s known fields onto this one.

        Later usage reports win; ``None`` never overwrites a known value. Streaming
        providers report usage incrementally, so the router merges rather than replaces.
        """
        return Usage(
            input_tokens=_pick(self.input_tokens, other.input_tokens),
            output_tokens=_pick(self.output_tokens, other.output_tokens),
            total_tokens=_pick(self.total_tokens, other.total_tokens),
            cache_read_tokens=_pick(self.cache_read_tokens, other.cache_read_tokens),
            cache_write_tokens=_pick(self.cache_write_tokens, other.cache_write_tokens),
            reasoning_tokens=_pick(self.reasoning_tokens, other.reasoning_tokens),
            cost_usd=_pick(self.cost_usd, other.cost_usd),
        )


_T = TypeVar("_T")


def _pick(current: _T | None, incoming: _T | None) -> _T | None:
    return current if incoming is None else incoming


@dataclass(frozen=True, slots=True)
class Timing:
    """Centrally-measured timings for one attempt.

    All values are measured by the core against ``time.monotonic()`` so that definitions are
    identical across providers. ``phases`` carries provider-reported sub-timings (e.g.
    Ollama's model load) in milliseconds.

    Attributes:
        started_at: Monotonic-clock reading when the attempt began; meaningful only for
            computing intervals, not as wall-clock time.
        first_token_ms: Time to the first content event (text, reasoning, or tool-call
            delta) after attempt start; ``None`` when no content ever arrived.
        total_ms: Full duration of the attempt, start to completion.
        output_tokens_per_s: Decode throughput, measured from first token to completion;
            ``None`` when output tokens or first-token time are unknown.
        phases: Provider-reported sub-timings, keyed by phase name, in milliseconds.
    """

    started_at: float
    first_token_ms: float | None = None
    total_ms: float = 0.0
    output_tokens_per_s: float | None = None
    phases: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """A serializable, already-redacted snapshot of any AnyInfer error.

    Captured from the exception at failure time, so attempt records and telemetry can
    carry the failure long after the exception itself has been handled.

    Attributes:
        type_name: Class name of the exception this snapshot was captured from.
        provider: Id of the provider involved, or ``None`` for provider-independent
            failures.
        phase: Request-lifecycle stage that failed (``configure``, ``discover``,
            ``generate``, ``stream``, ``validate``, or ``cleanup``).
        retryable: Whether retrying the identical request could plausibly succeed.
        http_status: Status code, for failures that came from an HTTP response.
        detail: Human-readable description, already redacted and capped at
            `DETAIL_MAX_CHARS` characters.
    """

    type_name: str
    provider: str | None
    phase: str
    retryable: bool
    http_status: int | None
    detail: str


Outcome = Literal["ok", "retried", "failed", "skipped_unhealthy", "redirected"]
"""How a single routing attempt ended.

``redirected`` marks a completed attempt whose content-filter refusal sent the route to
``Route.content_policy_targets`` instead of surfacing the refusal.
"""


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One entry in a request's routing trail.

    Attributes:
        target: The provider and model this attempt was sent to.
        outcome: How the attempt ended.
        error: Snapshot of the failure, for attempts that did not succeed.
        timing: Measured timings, when the attempt progressed far enough to have any.
    """

    target: ResolvedTarget
    outcome: Outcome
    error: ErrorInfo | None = None
    timing: Timing | None = None


FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "other"]
"""Normalized reason a generation stopped."""

Mechanism = Literal["grammar", "json_schema", "json_mode", "prompt"]
"""How structured output was requested of the provider."""


@dataclass(frozen=True, slots=True)
class Generation:
    """The final result of a generation request.

    Attributes:
        text: The assistant's full text output. Empty when the model answered only
            with tool calls or structured output.
        structured: The parsed, schema-validated object when structured output was
            requested; ``None`` otherwise.
        tool_calls: Tool invocations the model requested, in order. Empty when none.
        target: The provider and model that actually produced this result — after
            routing, so it may differ from the first target asked for.
        finish_reason: Normalized reason the generation stopped.
        usage: Token accounting, normalized across providers.
        timing: Centrally-measured latency for the winning attempt.
        structured_mechanism: How structured output was enforced for this result
            (``grammar``, ``json_schema``, ``json_mode``, or ``prompt``); ``None``
            when no schema was requested.
        cache_mechanism: How prompt caching was engaged (``explicit`` marks, or
            ``implicit`` prefix stability); ``None`` when no policy was in force or the
            target offered nothing. Distinct from ``usage.cache_read_tokens``, which is
            what the provider *reported* — this is what was asked of it.
        repair_attempts: How many schema-repair round-trips were needed before
            ``structured`` validated. ``0`` means the first response validated.
        attempts: The full routing trail, including failed and retried attempts.
        warnings: Non-fatal notices accumulated along the way (capability
            downgrades, estimated values, and the like).
        raw: The provider-native response payload, as an escape hatch for fields
            the normalized types do not carry. ``None`` unless the request asked
            to keep it.
        manifest: The run manifest — one content-free record of which target won, which
            mechanisms were used, what was dropped or reduced, and what it cost. ``None``
            when the client was built with manifests switched off. It is a *projection* of
            this call's telemetry events and this result, never an independent account of
            them.
        arena: Every arena candidate and the terminal selection, or ``None`` for an
            ordinary generation.
        context_reduction: Content-free account of per-request corpus reduction.
    """

    text: str
    structured: Any | None
    tool_calls: tuple[ToolCall, ...]
    target: ResolvedTarget
    finish_reason: FinishReason
    usage: Usage
    timing: Timing
    structured_mechanism: Mechanism | None = None
    cache_mechanism: CacheMechanism | None = None
    repair_attempts: int = 0
    attempts: tuple[AttemptRecord, ...] = ()
    warnings: tuple[str, ...] = ()
    raw: Any | None = None
    manifest: RunManifest | None = None
    arena: ArenaResult | None = None
    context_reduction: ContextSummary | None = None
