"""Typed telemetry events.

These are the observability *contract*: in-process, typed, and payload-free by default. The
OTel bridge (`anyinfer.otel`) maps them to spans; it is a consumer of this contract, not
the contract itself.

Payload privacy: fields carrying prompt or response text are ``None`` unless the observer
that receives the event registered with ``payloads=True``. The dispatcher strips them per
observer, so one payload-consuming observer does not leak text to the others.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

from ..types.requests import ResolvedTarget, Target
from ..types.results import ErrorInfo, Mechanism, Timing, Usage

__all__ = [
    "PAYLOAD_FIELDS",
    "AttemptCompleted",
    "AttemptStarted",
    "ContextReduced",
    "DownloadProgress",
    "FallbackTriggered",
    "FirstToken",
    "ParameterDropped",
    "RepairAttempted",
    "RequestCompleted",
    "RequestFailed",
    "RequestStarted",
    "RetryScheduled",
    "ServerLifecycle",
    "TargetResolved",
    "TelemetryEvent",
    "UsageEstimated",
    "strip_payloads",
]


@dataclass(frozen=True, slots=True)
class RequestStarted:
    """A generation request entered the router.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        targets: The fallback chain as requested, in the order the router will try it.
        metadata: Caller-supplied labels from the request, passed through untouched.
        prompt_text: The prompt text; ``None`` unless the receiving observer registered
            with ``payloads=True``.
    """

    request_id: str
    targets: tuple[Target, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)
    prompt_text: str | None = None


@dataclass(frozen=True, slots=True)
class TargetResolved:
    """A target string resolved to a concrete provider and model.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        target: The concrete provider and model the target string resolved to.
    """

    request_id: str
    target: ResolvedTarget


@dataclass(frozen=True, slots=True)
class AttemptStarted:
    """An attempt against one resolved target began.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        target: The resolved target being attempted.
        attempt_number: 1-based count of attempts against this target; retries increment
            it, and falling back to a new target restarts it at 1.
    """

    request_id: str
    target: ResolvedTarget
    attempt_number: int


@dataclass(frozen=True, slots=True)
class FirstToken:
    """The first content delta arrived — the centrally-measured TTFT.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        target: The resolved target that produced the token.
        at_ms: Milliseconds from attempt start to the first content delta.
    """

    request_id: str
    target: ResolvedTarget
    at_ms: float


@dataclass(frozen=True, slots=True)
class AttemptCompleted:
    """An attempt finished successfully.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        target: The resolved target that served the attempt.
        usage: Token usage for the attempt, merged across every report the provider sent.
        timing: Centrally-measured attempt timings, comparable across providers.
        finish_reason: Normalized reason generation stopped, e.g. ``stop`` or ``length``.
    """

    request_id: str
    target: ResolvedTarget
    usage: Usage
    timing: Timing
    finish_reason: str


@dataclass(frozen=True, slots=True)
class RetryScheduled:
    """A retryable failure will be retried against the same target after a delay.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        target: The resolved target that will be retried.
        attempt_number: The 1-based attempt that just failed; the retry is the next one.
        delay_s: Seconds the router sleeps before the retry.
        error: Snapshot of the retryable failure.
    """

    request_id: str
    target: ResolvedTarget
    attempt_number: int
    delay_s: float
    error: ErrorInfo


@dataclass(frozen=True, slots=True)
class FallbackTriggered:
    """A target was abandoned; the router advanced to the next in the chain.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        from_target: The resolved target that was abandoned.
        to_target: The next target string the router will try, not yet resolved.
        error: Snapshot of the failure that caused the abandonment, or ``None`` when the
            switch was a content-policy redirect rather than an error.
    """

    request_id: str
    from_target: ResolvedTarget
    to_target: Target
    error: ErrorInfo | None = None


@dataclass(frozen=True, slots=True)
class RepairAttempted:
    """A schema violation triggered a repair re-prompt.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        target: The resolved target being re-prompted.
        attempt_number: 1-based count of repair attempts within this generation.
        mechanism: The structured-output mechanism in force when validation failed, when
            one was chosen.
        errors: The schema-validation messages that triggered the repair.
        raw_text: The response text that failed validation; ``None`` unless the receiving
            observer registered with ``payloads=True``.
    """

    request_id: str
    target: ResolvedTarget
    attempt_number: int
    mechanism: Mechanism | None
    errors: tuple[str, ...] = ()
    raw_text: str | None = None


@dataclass(frozen=True, slots=True)
class RequestCompleted:
    """A request produced a result.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        target: The resolved target that produced the result.
        usage: Final token usage for the request.
        timing: Final centrally-measured timings for the request.
        repair_attempts: How many repair re-prompts were needed; ``0`` means the first
            response validated.
        response_text: The final response text; ``None`` unless the receiving observer
            registered with ``payloads=True``.
    """

    request_id: str
    target: ResolvedTarget
    usage: Usage
    timing: Timing
    repair_attempts: int = 0
    response_text: str | None = None


@dataclass(frozen=True, slots=True)
class RequestFailed:
    """A request exhausted its route without a result.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        error: Snapshot of the terminal failure, after every target and retry was spent.
    """

    request_id: str
    error: ErrorInfo


@dataclass(frozen=True, slots=True)
class ParameterDropped:
    """A requested parameter was not honored as asked, because the target cannot.

    Dropping a parameter silently is how a caller ends up debugging why ``temperature=0``
    had no effect. Every drop is observable instead. The same applies to a parameter
    honored only in part — a repair budget clamped to a provider's ceiling is reported
    here too, since a budget quietly reduced from three to one is no more discoverable
    than one ignored outright.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        target: The resolved target the parameter was withheld from.
        parameter: Name of the request parameter that was not honored, dotted for a field
            of a compound one (``repair.max_attempts``).
        reason: Human-readable explanation of what the target did instead.
    """

    request_id: str
    target: ResolvedTarget
    parameter: str
    reason: str


@dataclass(frozen=True, slots=True)
class UsageEstimated:
    """A usage figure was derived rather than reported by the provider.

    Estimated and reported numbers must never be indistinguishable downstream; this event
    is what marks the difference for observers.

    Attributes:
        request_id: Correlation id shared by every event this request emits.
        target: The resolved target the estimate applies to.
        field_name: The usage field that was estimated, e.g. ``input_tokens``.
        method: How the estimate was derived.
    """

    request_id: str
    target: ResolvedTarget
    field_name: str
    method: str


@dataclass(frozen=True, slots=True)
class ContextReduced:
    """A context corpus was reduced to fit a budget.

    Reduction emulates a larger context window, and emulation is observable rather than
    silent. Content-free by construction: counts and ceilings only, never paths or
    document text — a path name can itself be sensitive.

    Attributes:
        strategy: The strategy requested (``auto`` stays ``auto``).
        representation: The strategy actually applied.
        candidate_count: Documents offered to the reducer.
        selected_count: Documents represented at detail fidelity.
        omitted_count: Documents not represented in detail.
        estimated_tokens: Planning-side estimate of the rendered envelope.
        max_tokens: The budget the reduction was held to.
        binding_constraints: Which ceilings excluded at least one document.
        calls: Generation calls spent; non-zero only for ``distill``.
    """

    strategy: str
    representation: str
    candidate_count: int
    selected_count: int
    omitted_count: int
    estimated_tokens: int
    max_tokens: int
    binding_constraints: tuple[str, ...] = ()
    calls: int = 0


@dataclass(frozen=True, slots=True)
class ServerLifecycle:
    """A supervised local server changed state.

    Attributes:
        server_id: Identifies the supervised server — the key of the model it serves.
        state: The state the server just entered.
        detail: Human-readable context, such as a stop reason or a tail of crash output;
            empty when there is nothing to add.
    """

    server_id: str
    state: Literal["starting", "ready", "stopping", "stopped", "crashed"]
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    """Progress of a model acquisition.

    ``downloaded_bytes`` and ``total_bytes`` are **aggregate across the whole acquisition**,
    which is what their names have always implied. Earlier builds reported them per file,
    so a sharded artifact restarted the counter at zero on every shard with no way for an
    observer to tell. The remaining fields carry the per-file detail that the aggregate
    figures deliberately no longer mix in.

    Attributes:
        artifact_id: The artifact or catalog variant being acquired.
        downloaded_bytes: Bytes present across every file, including bytes that were
            already on disk before this run — so resuming reports the resumed position.
        total_bytes: Total expected bytes, or ``None`` when a size is genuinely unknown.
        done: Whether the acquisition finished.
        phase: Which stage emitted this, when the acquisition engine supplied one.
        file_index: 1-based index of the file that most recently advanced.
        file_count: How many files this acquisition covers.
        filename: Name of that file.
        session_bytes: Bytes this run actually transferred, as opposed to resumed.
    """

    artifact_id: str
    downloaded_bytes: int
    total_bytes: int | None
    done: bool = False
    phase: str = ""
    file_index: int = 0
    file_count: int = 0
    filename: str = ""
    session_bytes: int = 0


TelemetryEvent = (
    RequestStarted | TargetResolved | AttemptStarted | FirstToken | AttemptCompleted
    | RetryScheduled | FallbackTriggered | RepairAttempted | RequestCompleted | RequestFailed
    | ParameterDropped | UsageEstimated | ServerLifecycle | DownloadProgress
    | ContextReduced
)
"""Any event an observer may receive."""

PAYLOAD_FIELDS: Mapping[type, tuple[str, ...]] = {
    RequestStarted: ("prompt_text",),
    RepairAttempted: ("raw_text",),
    RequestCompleted: ("response_text",),
}
"""Per-event-type fields that carry prompt or response text."""


def strip_payloads(event: TelemetryEvent) -> TelemetryEvent:
    """Return ``event`` with every payload-carrying field set to ``None``.

    Applied per observer, so observers that did not opt into payloads never see text even
    when a sibling observer did.
    """
    fields = PAYLOAD_FIELDS.get(type(event))
    if not fields:
        return event
    blanked: dict[str, Any] = dict.fromkeys(fields)
    # `replace` cannot be narrowed across a union of dataclasses, but every member of
    # PAYLOAD_FIELDS is keyed by its own type, so the fields always exist on `event`.
    return cast("TelemetryEvent", replace(cast("Any", event), **blanked))
