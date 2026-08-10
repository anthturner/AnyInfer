"""The run manifest: one artifact that explains a call.

Every fact in a `RunManifest` is already computed somewhere on the request path — which
target won, which structured-output mechanism was used, what got dropped, what got
reduced, what it cost, and on what provenance. What was missing was an *assembly*: a
developer who wanted the whole story had to subscribe an observer before dispatch and
reimplement the join by hand, and a developer on the sidecar could not get it at all.

The manifest is a **terminal projection**, never a second source of truth. Every field is
computed from one request's telemetry events, the `GenerationRequest` they came from, the
capabilities the router resolved for its targets, and the `Generation` it produced. Nothing
here is measured independently, so the manifest and the event stream cannot disagree —
`tests/test_manifest.py` holds that line.

Two consequences follow from that rule. Events stay the contract for *observers watching a
system*; the manifest is the contract for *a developer holding one call*. And the manifest
is content-free by default, on exactly the same terms as events: no prompt text, no
completion text, no tool arguments, no schema bodies. A schema is recorded as a SHA-256
digest and its title. Opting into payloads populates `RunManifest.payloads` and nothing
else, and every string in it passes through `anyinfer.redaction`.

Nothing here writes anything anywhere. Serializing a manifest, storing it, or rotating a
directory of them is the caller's business; a durable store is not this library's.

```python
result = client.generate("hi", target="scripted:m")
manifest = result.manifest
print(manifest.route.resolved, manifest.structured.chosen)
print(render(manifest))
```
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from decimal import Decimal
from typing import Any, TypeVar, cast

from .capabilities.estimate import TokenEstimator, estimate_request
from .events.telemetry import (
    AttemptCompleted,
    AttemptStarted,
    CachePlanned,
    ContextReduced,
    FallbackTriggered,
    FirstToken,
    ParameterDropped,
    ProviderDiagnostic,
    RateLimitWaited,
    RepairAttempted,
    RequestCompleted,
    RequestFailed,
    RequestStarted,
    RetryScheduled,
    TargetResolved,
    TelemetryEvent,
    UsageEstimated,
)
from .redaction import redact
from .schema.mechanism import MechanismRung, choose_mechanism
from .types.capabilities import ModelCapabilities
from .types.requests import GenerationRequest, ResolvedTarget
from .types.results import ErrorInfo, Generation

__all__ = [
    "MANIFEST_FORMAT",
    "AttemptFacet",
    "CacheFacet",
    "CapabilityFacet",
    "ContextFacet",
    "DroppedParameter",
    "ManifestBuilder",
    "MechanismRung",
    "PayloadFacet",
    "ReductionRecord",
    "RepairRecord",
    "RequestFacet",
    "RouteFacet",
    "RouteStep",
    "RunManifest",
    "SchemaFacet",
    "SourcedFact",
    "TimingFacet",
    "UsageFacet",
    "manifest_json_schema",
    "render",
    "schema_digest",
]

MANIFEST_FORMAT = "1"
"""Manifest format version.

Bumped when an existing field's *meaning* changes, never when a field is added — a reader
that ignores unknown keys survives additions, which is the same rule the context envelope
follows.
"""


# ---- facets --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourcedFact:
    """One capability value the call consumed, with its provenance intact.

    Provenance is carried verbatim rather than collapsed into a bare value: "the context
    window was 8192" and "the context window was *assumed* to be 8192" are different
    statements, and a manifest that could not tell them apart would be useless for the
    question it exists to answer.

    Attributes:
        name: Which capability this is, e.g. ``context_window``.
        value: The value itself, rendered as JSON-safe data.
        provenance: Where it came from — ``catalog``, ``discovered``, ``probed``,
            ``default``, or ``override``.
    """

    name: str
    value: Any
    provenance: str


@dataclass(frozen=True, slots=True)
class RequestFacet:
    """Shape and fingerprints of what was asked for — never the payload.

    Attributes:
        message_count: How many messages the request carried.
        role_counts: Message count per role, in role order.
        char_count: Total characters of message text.
        estimated_tokens: Planning-side input estimate, or ``None`` when not computed.
        schema_present: Whether structured output was requested.
        schema_name: The schema's label, which is a title rather than content.
        schema_digest: SHA-256 of the canonical schema JSON, so two runs can be compared
            without either one carrying the schema body.
        tool_names: Names of the tools offered, in order.
        tool_choice: How tool use was constrained.
        sampling: Sampling controls actually set, omitting the ones left unset.
        reasoning: Requested reasoning effort, when one was asked for.
        timeout_s: Per-attempt wall clock the request carried, when set.
        repair_budget: Repair round-trips the request allowed.
        metadata_keys: Keys of caller-supplied metadata; values may be anything.
    """

    message_count: int = 0
    role_counts: Mapping[str, int] = field(default_factory=dict)
    char_count: int = 0
    estimated_tokens: int | None = None
    schema_present: bool = False
    schema_name: str | None = None
    schema_digest: str | None = None
    tool_names: tuple[str, ...] = ()
    tool_choice: str = "auto"
    sampling: Mapping[str, Any] = field(default_factory=dict)
    reasoning: str | None = None
    timeout_s: float | None = None
    repair_budget: int = 0
    metadata_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteStep:
    """One target the router considered, and what became of it.

    Attributes:
        target: The resolved target, as ``provider:model``.
        outcome: ``ok``, ``failed``, ``retried``, ``skipped_unhealthy``, ``redirected``, or
            ``abandoned`` for a target the route left before it produced a result.
        reason: Why, in the words the router used — a health gate, a context overflow, a
            content-policy redirect, or the error that ended it.
    """

    target: str
    outcome: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RouteFacet:
    """Which targets were asked for, which one answered, and what happened between.

    Attributes:
        requested: The fallback chain as the caller wrote it, unresolved.
        resolved: The target that produced the result, or ``None`` when none did.
        considered: Every target the router touched, in the order it touched them.
    """

    requested: tuple[str, ...] = ()
    resolved: str | None = None
    considered: tuple[RouteStep, ...] = ()


@dataclass(frozen=True, slots=True)
class CapabilityFacet:
    """Every provenance-tagged capability the call actually consumed.

    Attributes:
        target: The target these capabilities describe.
        facts: One entry per known capability field, provenance intact.
    """

    target: str = ""
    facts: tuple[SourcedFact, ...] = ()


@dataclass(frozen=True, slots=True)
class AttemptFacet:
    """One attempt against one target, with the reason it ended as it did.

    Attributes:
        target: The resolved target attempted.
        attempt_number: 1-based count against this target; a fallback restarts it at 1.
        outcome: How it ended, using the same vocabulary as `anyinfer.AttemptRecord`.
        error: The failure snapshot, for an attempt that did not succeed.
        first_token_ms: Time to the first content delta, when any arrived.
        total_ms: Full duration of the attempt.
        queued_ms: How long client-side pacing held it before dispatch.
        retry_reason: Why a retry was scheduled after this attempt, when one was.
        retry_delay_s: How long the router waited before retrying.
        paced_s: Seconds this attempt spent waiting on a rate limiter, and why, summed per
            reason.
    """

    target: str
    attempt_number: int = 1
    outcome: str = "ok"
    error: ErrorInfo | None = None
    first_token_ms: float | None = None
    total_ms: float | None = None
    queued_ms: float | None = None
    retry_reason: str | None = None
    retry_delay_s: float | None = None
    paced_s: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RepairRecord:
    """One schema-repair round trip.

    Attributes:
        attempt_number: 1-based repair count within this generation.
        mechanism: The mechanism in force when validation failed.
        errors: The validation messages that triggered the repair.
    """

    attempt_number: int
    mechanism: str | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SchemaFacet:
    """What was asked of the structured-output ladder, and what it delivered.

    Attributes:
        requested: Whether the request carried a schema at all.
        chosen: The mechanism the ladder selected before dispatch.
        used: The mechanism the winning attempt actually used.
        ladder: Every rung considered, strongest first, with the reason each was rejected.
        repair_attempts: How many repair round-trips were spent.
        repairs: One record per repair, with the validation errors that caused it.
        validated: Whether a structured value was finally produced.
    """

    requested: bool = False
    chosen: str | None = None
    used: str | None = None
    ladder: tuple[MechanismRung, ...] = ()
    repair_attempts: int = 0
    repairs: tuple[RepairRecord, ...] = ()
    validated: bool = False


@dataclass(frozen=True, slots=True)
class CacheFacet:
    """What was planned for the target's prompt cache, and what it reported back.

    ``read_tokens`` and ``write_tokens`` are what the *provider* said; everything else is
    what was asked of it. The two are kept apart because an intention is not a saving.

    Attributes:
        policy_mode: The cache mode in force, or ``None`` when no policy applied.
        mechanism: How caching was engaged — ``explicit`` marks or ``implicit`` prefix
            stability — or ``None`` when nothing was engaged.
        mark_count: How many marks were placed; always zero for ``implicit``.
        estimated_cacheable_tokens: Planning-side size of what the plan tried to cache.
        read_tokens: Prompt tokens the provider reported serving from its cache.
        write_tokens: Prompt tokens the provider reported writing into its cache.
    """

    policy_mode: str | None = None
    mechanism: str | None = None
    mark_count: int = 0
    estimated_cacheable_tokens: int = 0
    read_tokens: int | None = None
    write_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ReductionRecord:
    """One context reduction applied on the way to dispatch.

    Attributes:
        strategy: The strategy requested, or ``history`` for a compacted conversation.
        representation: The strategy actually applied.
        candidate_count: Documents — or messages — offered to the reducer.
        selected_count: Documents kept at detail fidelity, or messages retained.
        omitted_count: What was not represented in detail.
        estimated_tokens: Planning-side estimate of the result.
        max_tokens: The budget the reduction was held to.
        binding_constraints: Which ceilings excluded at least one candidate.
        calls: Generation calls the reduction itself spent.
        complete: Whether nothing was omitted.
    """

    strategy: str
    representation: str
    candidate_count: int = 0
    selected_count: int = 0
    omitted_count: int = 0
    estimated_tokens: int = 0
    max_tokens: int = 0
    binding_constraints: tuple[str, ...] = ()
    calls: int = 0
    complete: bool = True


@dataclass(frozen=True, slots=True)
class ContextFacet:
    """Reductions the request went through before it was sent.

    Attributes:
        reductions: One record per reduction, in the order they were applied.
    """

    reductions: tuple[ReductionRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class DroppedParameter:
    """A requested parameter the target would not honour as asked.

    Attributes:
        target: Which target withheld it.
        parameter: The parameter name, dotted for a field of a compound one.
        reason: What the target did instead.
    """

    target: str
    parameter: str
    reason: str


@dataclass(frozen=True, slots=True)
class UsageFacet:
    """Token accounting and cost, with estimated figures marked as estimated.

    Attributes:
        input_tokens: Prompt tokens, as counted by the provider.
        output_tokens: Generated tokens.
        total_tokens: Prompt plus completion.
        cache_read_tokens: Prompt tokens served from the provider's cache.
        cache_write_tokens: Prompt tokens written into it.
        reasoning_tokens: Tokens spent on hidden reasoning, where reported.
        cost_usd: Cost as a decimal string, or ``None`` when pricing is not trustworthy
            for this target. Never zero for an unpriced call.
        estimated_fields: Usage fields that were derived rather than reported, each with
            the method used.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: str | None = None
    estimated_fields: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TimingFacet:
    """Centrally-measured latency for the winning attempt.

    Attributes:
        first_token_ms: Time to the first content delta.
        total_ms: Full duration.
        output_tokens_per_s: Decode throughput.
        phases: Provider-reported sub-timings, in milliseconds.
    """

    first_token_ms: float | None = None
    total_ms: float | None = None
    output_tokens_per_s: float | None = None
    phases: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PayloadFacet:
    """The strings a content-free manifest deliberately leaves out.

    Populated only when a manifest is built with payloads enabled, and every value here
    has already passed through the redaction registry. The default manifest carries
    ``None`` in its place, which is what makes "safe to paste into a public issue tracker"
    a structural property rather than a promise about field contents.

    Attributes:
        prompt_text: The request's message text, flattened.
        response_text: The final response text.
        schema_body: The JSON Schema the request carried.
        tool_arguments: Arguments of each tool call the model requested, as JSON.
        repair_texts: The responses that failed validation, in repair order.
    """

    prompt_text: str | None = None
    response_text: str | None = None
    schema_body: str | None = None
    tool_arguments: tuple[str, ...] = ()
    repair_texts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunManifest:
    """One versioned, content-free record of what a single call did.

    Attributes:
        format: Manifest format version; see `MANIFEST_FORMAT`.
        anyinfer_version: The library version that produced it, so a stale record is
            recognisable as one.
        request_id: The correlation id every event for this call carried.
        complete: Whether the call finished. ``False`` on a manifest read from a cancelled
            or still-running stream, where the record is a partial account rather than a
            wrong one.
        request: Shape and fingerprints of what was asked for.
        route: Targets requested, considered, and resolved.
        capability: Provenance-tagged capabilities the call consumed.
        attempts: The routing trail, one entry per attempt.
        structured: The structured-output ladder and the repair loop.
        cache: Prompt-cache plan and reported accounting.
        context: Reductions applied before dispatch.
        dropped: Parameters the target would not honour.
        usage: Token accounting and cost.
        timing: Latency of the winning attempt.
        notes: Warnings and provider diagnostics, in the order they arrived.
        payloads: Prompt and response text, present only when explicitly asked for.
    """

    format: str = MANIFEST_FORMAT
    anyinfer_version: str = ""
    request_id: str = ""
    complete: bool = False
    request: RequestFacet = RequestFacet()
    route: RouteFacet = RouteFacet()
    capability: CapabilityFacet = CapabilityFacet()
    attempts: tuple[AttemptFacet, ...] = ()
    structured: SchemaFacet = SchemaFacet()
    cache: CacheFacet = CacheFacet()
    context: ContextFacet = ContextFacet()
    dropped: tuple[DroppedParameter, ...] = ()
    usage: UsageFacet = UsageFacet()
    timing: TimingFacet = TimingFacet()
    notes: tuple[str, ...] = ()
    payloads: PayloadFacet | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render the manifest as JSON-safe data.

        Returns:
            A plain dictionary of primitives, lists, and dictionaries — directly
            serializable with `json.dumps`.
        """
        return cast("dict[str, Any]", _encode(self))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunManifest:
        """Rebuild a manifest from `to_dict` output.

        Unknown keys are ignored, which is what makes the format's additive rule safe: a
        reader on an older release still loads a newer manifest.

        Args:
            data: A mapping produced by `to_dict`, or parsed from one.

        Returns:
            The reconstructed manifest.
        """
        return cast("RunManifest", _decode(cls, data))

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the manifest to a JSON string.

        Args:
            indent: Indentation passed to `json.dumps`; ``None`` for the compact form.

        Returns:
            The serialized manifest.
        """
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


# ---- encoding ------------------------------------------------------------------------


def _encode(value: Any) -> Any:
    """Render a manifest tree as JSON-safe data."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_encode(item) for item in value]
    return value


_NESTED: Mapping[tuple[type, str], type] = {
    (RunManifest, "request"): RequestFacet,
    (RunManifest, "route"): RouteFacet,
    (RunManifest, "capability"): CapabilityFacet,
    (RunManifest, "attempts"): AttemptFacet,
    (RunManifest, "structured"): SchemaFacet,
    (RunManifest, "cache"): CacheFacet,
    (RunManifest, "context"): ContextFacet,
    (RunManifest, "dropped"): DroppedParameter,
    (RunManifest, "usage"): UsageFacet,
    (RunManifest, "timing"): TimingFacet,
    (RunManifest, "payloads"): PayloadFacet,
    (RouteFacet, "considered"): RouteStep,
    (CapabilityFacet, "facts"): SourcedFact,
    (AttemptFacet, "error"): ErrorInfo,
    (SchemaFacet, "ladder"): MechanismRung,
    (SchemaFacet, "repairs"): RepairRecord,
    (ContextFacet, "reductions"): ReductionRecord,
}
"""Which dataclass each nested manifest field decodes into.

Explicit rather than reflected from annotations: the annotations are strings under
``from __future__ import annotations``, and a decoder that parses them would be a small
type evaluator nobody asked for.
"""


def _decode(cls: type, data: Mapping[str, Any]) -> Any:
    """Rebuild one dataclass from JSON-safe data, ignoring unknown keys."""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        raw = data[f.name]
        annotation = str(f.type)
        nested = _NESTED.get((cls, f.name))
        if nested is not None and raw is not None:
            raw = (
                [_decode(nested, item) for item in raw]
                if annotation.startswith("tuple")
                else _decode(nested, raw)
            )
        if raw is not None:
            if annotation.startswith("tuple"):
                raw = tuple(raw)
            elif annotation.startswith("Mapping"):
                raw = dict(raw)
        kwargs[f.name] = raw
    return cls(**kwargs)


# ---- the builder ---------------------------------------------------------------------


class ManifestBuilder:
    """Folds one request's events into a `RunManifest`.

    An internal observer scoped to a single ``request_id``: the client hands it every
    event it emits for that request, plus the two things events do not carry — the request
    itself and the capabilities the router resolved. It costs one small object per
    in-flight request and no extra work per event.

    The builder is deliberately tolerant. A manifest read part-way through a stream, or
    after a cancellation, is a partial account with ``complete=False`` rather than an
    error — a cancelled call is exactly the one whose story a caller most wants.

    Args:
        request: The request being run.
        requested_targets: The fallback chain as the caller wrote it.
        request_id: The correlation id shared by this request's events.
        anyinfer_version: Version string stamped onto the record.
        payloads: Capture prompt, response, schema, and tool text — redacted — into
            `RunManifest.payloads`. Off by default, on the same terms as telemetry.
        estimator: Token counting strategy for the request's planning estimate.
    """

    __slots__ = (
        "_anyinfer_version",
        "_attempts",
        "_cache",
        "_capabilities",
        "_capability_target",
        "_current",
        "_dropped",
        "_estimator",
        "_notes",
        "_payloads",
        "_reductions",
        "_repairs",
        "_request",
        "_request_id",
        "_requested",
        "_resolved",
        "_result",
        "_steps",
        "_usage_estimates",
        "_want_payloads",
    )

    def __init__(
        self,
        request: GenerationRequest,
        requested_targets: Sequence[str],
        *,
        request_id: str,
        anyinfer_version: str = "",
        payloads: bool = False,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self._request = request
        self._requested = tuple(str(t) for t in requested_targets)
        self._request_id = request_id
        self._anyinfer_version = anyinfer_version
        self._want_payloads = payloads
        self._estimator = estimator
        self._attempts: list[AttemptFacet] = []
        self._steps: list[RouteStep] = []
        self._dropped: list[DroppedParameter] = []
        self._reductions: list[ReductionRecord] = []
        self._repairs: list[RepairRecord] = []
        self._notes: list[str] = []
        self._usage_estimates: dict[str, str] = {}
        self._cache = CacheFacet()
        self._capabilities: ModelCapabilities | None = None
        self._capability_target = ""
        self._current: AttemptFacet | None = None
        self._resolved: str | None = None
        self._result: Generation | None = None
        self._payloads: dict[str, Any] = {}

    # -- inputs the event stream does not carry ----------------------------------------

    def note_capabilities(self, target: ResolvedTarget, capabilities: ModelCapabilities) -> None:
        """Record the capabilities the router resolved for one target.

        Called once per target the route reaches; the last one wins, because the
        capabilities that matter are the ones the answering target was judged by.
        """
        self._capabilities = capabilities
        self._capability_target = str(target)

    def note_cache_policy(self, mode: str | None) -> None:
        """Record which cache mode was in force, whether or not it could be honoured."""
        self._cache = _replace_facet(self._cache, policy_mode=mode)

    def note_repair_text(self, text: str) -> None:
        """Record a response that failed validation, for a payload-carrying manifest."""
        if self._want_payloads and text:
            self._payloads.setdefault("repair_texts", []).append(redact(text))

    def note_result(self, result: Generation) -> None:
        """Attach the finished `Generation` this request produced."""
        self._result = result

    # -- the event fold ----------------------------------------------------------------

    def observe(self, event: TelemetryEvent) -> None:
        """Fold one telemetry event into the record.

        Events for other requests are ignored, so a builder can be fed from a shared
        dispatcher without correlating upstream.
        """
        request_id = getattr(event, "request_id", None)
        if isinstance(request_id, str) and request_id and request_id != self._request_id:
            return

        if isinstance(event, RequestStarted):
            return
        if isinstance(event, TargetResolved):
            self._resolved = str(event.target)
            return
        if isinstance(event, AttemptStarted):
            self._flush_attempt()
            self._current = AttemptFacet(
                target=str(event.target), attempt_number=event.attempt_number
            )
            return
        if isinstance(event, FirstToken):
            self._update(first_token_ms=event.at_ms)
            return
        if isinstance(event, RateLimitWaited):
            self._record_pacing(event)
            return
        if isinstance(event, AttemptCompleted):
            self._update(
                outcome="ok",
                total_ms=event.timing.total_ms,
                first_token_ms=event.timing.first_token_ms,
                queued_ms=event.timing.phases.get("queued_ms"),
            )
            self._flush_attempt()
            self._steps.append(RouteStep(str(event.target), "ok"))
            return
        if isinstance(event, RetryScheduled):
            self._update(
                outcome="retried",
                error=event.error,
                retry_reason=event.error.detail,
                retry_delay_s=event.delay_s,
            )
            self._flush_attempt()
            self._steps.append(RouteStep(str(event.target), "retried", event.error.detail))
            return
        if isinstance(event, FallbackTriggered):
            reason = (
                event.error.detail
                if event.error is not None
                else "a content-filter refusal redirected the route"
            )
            self._close_failed(event.error)
            self._steps.append(
                RouteStep(
                    str(event.from_target),
                    "abandoned" if event.error is not None else "redirected",
                    reason,
                )
            )
            return
        if isinstance(event, RepairAttempted):
            self._repairs.append(
                RepairRecord(
                    attempt_number=event.attempt_number,
                    mechanism=event.mechanism,
                    errors=tuple(event.errors),
                )
            )
            if event.raw_text:
                self.note_repair_text(event.raw_text)
            return
        if isinstance(event, ParameterDropped):
            self._dropped.append(
                DroppedParameter(str(event.target), event.parameter, event.reason)
            )
            return
        if isinstance(event, CachePlanned):
            self._cache = _replace_facet(
                self._cache,
                mechanism=event.mechanism or None,
                mark_count=event.mark_count,
                estimated_cacheable_tokens=event.estimated_cacheable_tokens,
            )
            return
        if isinstance(event, ContextReduced):
            self._reductions.append(
                ReductionRecord(
                    strategy=event.strategy,
                    representation=event.representation,
                    candidate_count=event.candidate_count,
                    selected_count=event.selected_count,
                    omitted_count=event.omitted_count,
                    estimated_tokens=event.estimated_tokens,
                    max_tokens=event.max_tokens,
                    binding_constraints=tuple(event.binding_constraints),
                    calls=event.calls,
                    complete=event.omitted_count == 0,
                )
            )
            return
        if isinstance(event, UsageEstimated):
            self._usage_estimates[event.field_name] = event.method
            return
        if isinstance(event, ProviderDiagnostic):
            self._notes.append(event.diagnostic.message)
            return
        if isinstance(event, RequestCompleted):
            return
        if isinstance(event, RequestFailed):
            self._close_failed(event.error)
            return

    def _record_pacing(self, event: RateLimitWaited) -> None:
        """Attribute a rate-limit wait to the attempt that paid for it."""
        if self._current is None:
            return
        paced = dict(self._current.paced_s)
        paced[event.reason] = paced.get(event.reason, 0.0) + event.waited_s
        self._update(paced_s=paced)

    def _update(self, **changes: Any) -> None:
        """Amend the attempt in flight, if there is one."""
        if self._current is None:
            return
        self._current = _replace_facet(self._current, **changes)

    def _flush_attempt(self) -> None:
        """Move the attempt in flight onto the trail."""
        if self._current is not None:
            self._attempts.append(self._current)
            self._current = None

    def _close_failed(self, error: ErrorInfo | None) -> None:
        """Close the attempt in flight as a failure, when one is still open."""
        if self._current is None:
            return
        if self._current.outcome == "ok":
            self._update(outcome="failed", error=error)
        elif error is not None and self._current.error is None:
            self._update(error=error)
        self._flush_attempt()

    # -- assembly ----------------------------------------------------------------------

    def build(self) -> RunManifest:
        """Assemble the record from everything folded in so far.

        Safe to call at any point: before the call finishes it returns a partial manifest
        with ``complete=False``.
        """
        result = self._result
        attempts = tuple(self._attempts)
        if self._current is not None:
            attempts = (*attempts, self._current)

        return RunManifest(
            format=MANIFEST_FORMAT,
            anyinfer_version=self._anyinfer_version,
            request_id=self._request_id,
            complete=result is not None,
            request=self._request_facet(),
            route=RouteFacet(
                requested=self._requested,
                resolved=str(result.target) if result is not None else None,
                considered=tuple(self._steps),
            ),
            capability=self._capability_facet(),
            attempts=attempts,
            structured=self._schema_facet(),
            cache=self._cache_facet(),
            context=ContextFacet(reductions=tuple(self._reductions)),
            dropped=tuple(self._dropped),
            usage=self._usage_facet(),
            timing=self._timing_facet(),
            notes=tuple(self._notes) + (tuple(result.warnings) if result else ()),
            payloads=self._payload_facet(),
        )

    def _request_facet(self) -> RequestFacet:
        request = self._request
        roles: dict[str, int] = {}
        chars = 0
        for message in request.messages:
            roles[message.role] = roles.get(message.role, 0) + 1
            chars += len(message.text)
        sampling = {
            name: value
            for name, value in (
                ("temperature", request.sampling.temperature),
                ("top_p", request.sampling.top_p),
                ("max_output_tokens", request.sampling.max_output_tokens),
                ("stop_count", len(request.sampling.stop) or None),
            )
            if value is not None
        }
        schema = request.schema
        return RequestFacet(
            message_count=len(request.messages),
            role_counts=roles,
            char_count=chars,
            estimated_tokens=self._estimated_tokens(),
            schema_present=schema is not None,
            schema_name=schema.name if schema is not None else None,
            schema_digest=schema_digest(schema.json_schema) if schema is not None else None,
            tool_names=tuple(tool.name for tool in request.tools),
            tool_choice=request.tool_choice,
            sampling=sampling,
            reasoning=request.reasoning,
            timeout_s=request.timeout_s,
            repair_budget=request.repair.max_attempts if request.repair else 0,
            metadata_keys=tuple(sorted(request.metadata)),
        )

    def _estimated_tokens(self) -> int | None:
        """The planning-side input estimate, or ``None`` if it cannot be computed."""
        try:
            return estimate_request(self._request, estimator=self._estimator).tokens
        except Exception:  # noqa: BLE001 — a manifest never fails the call it describes
            return None

    def _capability_facet(self) -> CapabilityFacet:
        capabilities = self._capabilities
        if capabilities is None:
            return CapabilityFacet()
        facts: list[SourcedFact] = []
        for name in (
            "context_window",
            "max_output_tokens",
            "default_temperature",
            "default_top_p",
        ):
            sourced = getattr(capabilities, name)
            if sourced is not None:
                facts.append(SourcedFact(name, sourced.value, sourced.provenance))
        features = capabilities.features
        facts.append(
            SourcedFact(
                "features",
                sorted(flag.name for flag in type(features.value) if flag in features.value),
                features.provenance,
            )
        )
        pricing = capabilities.pricing
        if pricing is not None:
            facts.append(
                SourcedFact(
                    "pricing",
                    {
                        "input_per_1m": str(pricing.value.input_per_1m),
                        "output_per_1m": str(pricing.value.output_per_1m),
                        "currency": pricing.value.currency,
                    },
                    pricing.provenance,
                )
            )
        return CapabilityFacet(target=self._capability_target, facts=tuple(facts))

    def _schema_facet(self) -> SchemaFacet:
        request, result = self._request, self._result
        if request.schema is None:
            return SchemaFacet()
        chosen = choose_mechanism(self._capabilities)
        return SchemaFacet(
            requested=True,
            chosen=chosen,
            used=result.structured_mechanism if result is not None else None,
            ladder=_ladder_report(self._capabilities, chosen),
            repair_attempts=(result.repair_attempts if result is not None else len(self._repairs)),
            repairs=tuple(self._repairs),
            validated=result is not None and result.structured is not None,
        )

    def _cache_facet(self) -> CacheFacet:
        result = self._result
        if result is None:
            return self._cache
        return _replace_facet(
            self._cache,
            mechanism=self._cache.mechanism or result.cache_mechanism,
            read_tokens=result.usage.cache_read_tokens,
            write_tokens=result.usage.cache_write_tokens,
        )

    def _usage_facet(self) -> UsageFacet:
        result = self._result
        if result is None:
            return UsageFacet(estimated_fields=dict(self._usage_estimates))
        usage = result.usage
        return UsageFacet(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cost_usd=str(usage.cost_usd) if usage.cost_usd is not None else None,
            estimated_fields=dict(self._usage_estimates),
        )

    def _timing_facet(self) -> TimingFacet:
        result = self._result
        if result is None:
            return TimingFacet()
        timing = result.timing
        return TimingFacet(
            first_token_ms=timing.first_token_ms,
            total_ms=timing.total_ms,
            output_tokens_per_s=timing.output_tokens_per_s,
            phases=dict(timing.phases),
        )

    def _payload_facet(self) -> PayloadFacet | None:
        if not self._want_payloads:
            return None
        result = self._result
        schema = self._request.schema
        arguments: tuple[str, ...] = ()
        if result is not None:
            arguments = tuple(
                redact(json.dumps(dict(call.arguments), sort_keys=True))
                for call in result.tool_calls
            )
        prompt = "\n\n".join(m.text for m in self._request.messages if m.text)
        return PayloadFacet(
            prompt_text=redact(prompt) if prompt else None,
            response_text=redact(result.text) if result is not None and result.text else None,
            schema_body=(
                redact(json.dumps(dict(schema.json_schema), sort_keys=True))
                if schema is not None
                else None
            ),
            tool_arguments=arguments,
            repair_texts=tuple(self._payloads.get("repair_texts", ())),
        )


_FacetT = TypeVar("_FacetT")


def _replace_facet(facet: _FacetT, **changes: Any) -> _FacetT:
    """Rebuild a frozen facet with some fields changed, ignoring ``None`` overwrites."""
    values = {f.name: getattr(facet, f.name) for f in fields(cast("Any", facet))}
    values.update({name: value for name, value in changes.items() if value is not None})
    rebuilt: _FacetT = type(facet)(**values)
    return rebuilt


def _ladder_report(
    capabilities: ModelCapabilities | None, chosen: str
) -> tuple[MechanismRung, ...]:
    """Explain the structured-output ladder: which rungs were available, and why not."""
    _, rungs = choose_mechanism(capabilities, with_trail=True)
    return rungs


def schema_digest(json_schema: Mapping[str, Any]) -> str:
    """Fingerprint a JSON Schema without carrying its body.

    Canonical form: keys sorted, no whitespace. Two requests carrying the same schema
    produce the same digest whatever order their keys were written in, which is what makes
    a digest usable in a golden file.

    Args:
        json_schema: The schema to fingerprint.

    Returns:
        A ``sha256:`` prefixed hex digest.
    """
    canonical = json.dumps(dict(json_schema), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---- rendering -----------------------------------------------------------------------


def render(manifest: RunManifest, *, width: int = 80) -> str:
    """Render a manifest as the human tree the CLI prints.

    The record is data and this is presentation: nothing here is a source of truth, and a
    caller wanting machine-readable output should use `RunManifest.to_dict` instead.

    Args:
        manifest: The record to render.
        width: Column budget; long reasons are wrapped inside it.

    Returns:
        A multi-line string, without a trailing newline.
    """
    lines: list[str] = []
    status = "complete" if manifest.complete else "incomplete (stream not drained)"
    lines.append(f"run {manifest.request_id or '(unknown)'} - {status}")
    lines.append(
        f"  anyinfer {manifest.anyinfer_version or '?'}, manifest format {manifest.format}"
    )

    route = manifest.route
    lines.append("  route")
    lines.append(f"    requested   {', '.join(route.requested) or '(none)'}")
    lines.append(f"    resolved    {route.resolved or '(none)'}")
    for step in route.considered:
        detail = f" - {step.reason}" if step.reason else ""
        lines.extend(_wrap(f"    * {step.target}: {step.outcome}{detail}", width))

    if manifest.attempts:
        lines.append("  attempts")
        for attempt in manifest.attempts:
            parts = [f"#{attempt.attempt_number}", attempt.target, attempt.outcome]
            if attempt.total_ms is not None:
                parts.append(f"{attempt.total_ms:.0f}ms")
            if attempt.first_token_ms is not None:
                parts.append(f"ttft {attempt.first_token_ms:.0f}ms")
            if attempt.queued_ms:
                parts.append(f"queued {attempt.queued_ms:.0f}ms")
            lines.append("    " + " ".join(parts))
            if attempt.error is not None:
                lines.extend(_wrap(f"      error: {attempt.error.detail}", width))
            if attempt.retry_delay_s is not None:
                lines.append(f"      retry after {attempt.retry_delay_s:.2f}s")

    structured = manifest.structured
    if structured.requested:
        lines.append("  structured output")
        lines.append(f"    chosen      {structured.chosen} (used: {structured.used or '-'})")
        for rung in structured.ladder:
            mark = "+" if rung.available else "-"
            suffix = f" - {rung.reason}" if rung.reason else ""
            lines.extend(_wrap(f"    {mark} {rung.mechanism}{suffix}", width))
        lines.append(f"    repairs     {structured.repair_attempts}")
        for repair in structured.repairs:
            for error in repair.errors:
                lines.extend(_wrap(f"      #{repair.attempt_number}: {error}", width))

    if manifest.capability.facts:
        lines.append(f"  capabilities ({manifest.capability.target})")
        for fact in manifest.capability.facts:
            lines.extend(_wrap(f"    {fact.name:<20}{fact.value} [{fact.provenance}]", width))

    cache = manifest.cache
    if cache.policy_mode or cache.mechanism or cache.read_tokens:
        lines.append("  cache")
        lines.append(f"    policy      {cache.policy_mode or '(none)'}")
        lines.append(f"    mechanism   {cache.mechanism or '(none)'}")
        if cache.mark_count:
            lines.append(f"    marks       {cache.mark_count}")
        if cache.read_tokens is not None:
            lines.append(f"    reported    {cache.read_tokens} read")

    for reduction in manifest.context.reductions:
        lines.append(
            f"  reduced {reduction.strategy} -> {reduction.representation}: "
            f"{reduction.selected_count}/{reduction.candidate_count} kept, "
            f"{reduction.omitted_count} omitted"
        )

    for drop in manifest.dropped:
        lines.extend(_wrap(f"  dropped {drop.parameter}: {drop.reason}", width))

    usage = manifest.usage
    lines.append("  usage")
    lines.append(
        f"    tokens      {usage.input_tokens if usage.input_tokens is not None else '?'} in / "
        f"{usage.output_tokens if usage.output_tokens is not None else '?'} out"
    )
    cost = f"${usage.cost_usd}" if usage.cost_usd else "unknown (no trusted pricing)"
    lines.append(f"    cost        {cost}")
    for field_name, method in sorted(usage.estimated_fields.items()):
        lines.extend(_wrap(f"    estimated   {field_name}: {method}", width))

    timing = manifest.timing
    if timing.total_ms is not None:
        lines.append("  timing")
        lines.append(f"    total       {timing.total_ms:.0f} ms")
        if timing.first_token_ms is not None:
            lines.append(f"    first token {timing.first_token_ms:.0f} ms")
        for phase, value in sorted(timing.phases.items()):
            lines.append(f"    {phase:<12}{value:.0f} ms")

    for note in manifest.notes:
        lines.extend(_wrap(f"  note: {note}", width))

    if manifest.payloads is not None:
        lines.append("  payloads captured (redacted)")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    """Wrap one line to ``width``, indenting continuations under their own bullet."""
    if len(text) <= width:
        return [text]
    body = text.lstrip()
    lead = " " * (len(text) - len(body))
    wrapped = textwrap.wrap(body, width=width, initial_indent=lead, subsequent_indent=lead + "  ")
    return wrapped or [text]


# ---- the published schema ------------------------------------------------------------


def manifest_json_schema() -> dict[str, Any]:
    """The JSON Schema a serialized manifest validates against.

    Published so a golden-file workflow has something to check against, and marked pre-1.0
    alongside the rest of this API. Readers must ignore unknown keys: the format adds
    fields without a version bump, and only a change of meaning bumps `MANIFEST_FORMAT`.

    Returns:
        The schema as a plain dictionary.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AnyInfer run manifest",
        "type": "object",
        "required": ["format", "request_id", "request", "route", "usage", "timing"],
        "properties": {
            "format": {"type": "string"},
            "anyinfer_version": {"type": "string"},
            "request_id": {"type": "string"},
            "complete": {"type": "boolean"},
            "request": {
                "type": "object",
                "properties": {
                    "message_count": {"type": "integer"},
                    "role_counts": {"type": "object"},
                    "char_count": {"type": "integer"},
                    "estimated_tokens": {"type": ["integer", "null"]},
                    "schema_present": {"type": "boolean"},
                    "schema_name": {"type": ["string", "null"]},
                    "schema_digest": {"type": ["string", "null"]},
                    "tool_names": {"type": "array", "items": {"type": "string"}},
                    "tool_choice": {"type": "string"},
                    "sampling": {"type": "object"},
                    "reasoning": {"type": ["string", "null"]},
                    "timeout_s": {"type": ["number", "null"]},
                    "repair_budget": {"type": "integer"},
                    "metadata_keys": {"type": "array", "items": {"type": "string"}},
                },
            },
            "route": {
                "type": "object",
                "properties": {
                    "requested": {"type": "array", "items": {"type": "string"}},
                    "resolved": {"type": ["string", "null"]},
                    "considered": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target": {"type": "string"},
                                "outcome": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "capability": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "facts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {},
                                "provenance": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "attempts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "attempt_number": {"type": "integer"},
                        "outcome": {"type": "string"},
                        "error": {"type": ["object", "null"]},
                        "first_token_ms": {"type": ["number", "null"]},
                        "total_ms": {"type": ["number", "null"]},
                        "queued_ms": {"type": ["number", "null"]},
                        "retry_reason": {"type": ["string", "null"]},
                        "retry_delay_s": {"type": ["number", "null"]},
                        "paced_s": {"type": "object"},
                    },
                },
            },
            "structured": {
                "type": "object",
                "properties": {
                    "requested": {"type": "boolean"},
                    "chosen": {"type": ["string", "null"]},
                    "used": {"type": ["string", "null"]},
                    "ladder": {"type": "array", "items": {"type": "object"}},
                    "repair_attempts": {"type": "integer"},
                    "repairs": {"type": "array", "items": {"type": "object"}},
                    "validated": {"type": "boolean"},
                },
            },
            "cache": {
                "type": "object",
                "properties": {
                    "policy_mode": {"type": ["string", "null"]},
                    "mechanism": {"type": ["string", "null"]},
                    "mark_count": {"type": "integer"},
                    "estimated_cacheable_tokens": {"type": "integer"},
                    "read_tokens": {"type": ["integer", "null"]},
                    "write_tokens": {"type": ["integer", "null"]},
                },
            },
            "context": {
                "type": "object",
                "properties": {"reductions": {"type": "array", "items": {"type": "object"}}},
            },
            "dropped": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "parameter": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "usage": {
                "type": "object",
                "properties": {
                    "input_tokens": {"type": ["integer", "null"]},
                    "output_tokens": {"type": ["integer", "null"]},
                    "total_tokens": {"type": ["integer", "null"]},
                    "cache_read_tokens": {"type": ["integer", "null"]},
                    "cache_write_tokens": {"type": ["integer", "null"]},
                    "reasoning_tokens": {"type": ["integer", "null"]},
                    "cost_usd": {"type": ["string", "null"]},
                    "estimated_fields": {"type": "object"},
                },
            },
            "timing": {
                "type": "object",
                "properties": {
                    "first_token_ms": {"type": ["number", "null"]},
                    "total_ms": {"type": ["number", "null"]},
                    "output_tokens_per_s": {"type": ["number", "null"]},
                    "phases": {"type": "object"},
                },
            },
            "notes": {"type": "array", "items": {"type": "string"}},
            "payloads": {"type": ["object", "null"]},
        },
    }
