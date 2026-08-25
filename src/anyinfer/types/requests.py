"""Request-side types: sampling knobs, schemas, tools, targets, and the request itself.

These are the inputs a caller controls. Everything here is inert data — resolution of
targets, schema mechanisms, and provider options happens in the core, not in these types,
which are used throughout the client and provider boundary.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from .messages import AudioPart, DocumentPart, ImagePart, Message, VideoPart

if TYPE_CHECKING:
    from ..context_request import ContextRequest

__all__ = [
    "ARENA_MEMO_MODES",
    "ARENA_STRATEGIES",
    "CACHE_MODES",
    "DEFAULT_MAX_INPUT_BYTES",
    "DEFAULT_MAX_INPUT_PART_BYTES",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_TIMEOUT_S",
    "HISTORY_MODES",
    "MAX_TOP_LOGPROBS",
    "ArenaPolicy",
    "CacheMechanism",
    "CacheMode",
    "CachePolicy",
    "GenerationRequest",
    "HistoryMode",
    "HistoryPolicy",
    "RateLimits",
    "ReasoningEffort",
    "Repair",
    "ResolvedTarget",
    "Sampling",
    "SchemaSpec",
    "SpendPolicy",
    "SupportsJSONSchema",
    "Target",
    "ToolAnnotations",
    "ToolChoice",
    "ToolSpec",
]

ARENA_STRATEGIES = ("first_valid", "consensus", "cheapest", "fastest", "judge", "synthesize")
"""Selection strategies accepted by `ArenaPolicy`."""

ARENA_MEMO_MODES = ("read_only", "all", "opt_in", "off")
"""Run-scoped tool memoization modes accepted by `ArenaPolicy`."""


@dataclass(frozen=True, slots=True)
class ArenaPolicy:
    """Fan one request out to fixed targets and select after every branch finishes."""

    targets: tuple[str, ...]
    strategy: Literal["first_valid", "consensus", "cheapest", "fastest", "judge", "synthesize"] = (
        "first_valid"
    )
    judge_target: str | None = None
    instructions: str | None = None
    concurrency: int = 4
    min_candidates: int = 1
    reveal_targets: bool = False
    memoize_tools: Literal["read_only", "all", "opt_in", "off"] = "read_only"

    def __post_init__(self) -> None:
        """Reject an arena whose fixed bounds or strategy are not executable."""
        if not self.targets:
            raise ValueError("arena targets must not be empty")
        if self.strategy not in ARENA_STRATEGIES:
            raise ValueError(f"unknown arena strategy {self.strategy!r}")
        if self.strategy in ("judge", "synthesize") and not self.judge_target:
            raise ValueError(f"arena strategy {self.strategy!r} requires judge_target")
        if self.concurrency < 1:
            raise ValueError("arena concurrency must be at least 1")
        if self.min_candidates < 1 or self.min_candidates > len(self.targets):
            raise ValueError("arena min_candidates must be between 1 and target count")
        if self.memoize_tools not in ARENA_MEMO_MODES:
            raise ValueError(f"unknown arena memoize_tools mode {self.memoize_tools!r}")


@dataclass(frozen=True, slots=True)
class Sampling:
    """Sampling controls.

    Every field defaults to ``None``/empty meaning *provider default*. AnyInfer never
    invents a temperature: an unset value is omitted from the wire request entirely.

    Attributes:
        temperature: Randomness of token selection; higher values sample more freely.
        top_p: Nucleus-sampling cutoff — the probability mass considered for each token.
        max_output_tokens: Upper bound on how many tokens the model may generate.
        stop: Sequences that end generation as soon as one is produced.
        seed: Requested sampling seed. A provider that honors it makes repeated identical
            requests more likely to produce identical output — *more likely*, never
            guaranteed: every provider that ships this field documents it as best-effort,
            and none of them promise reproducibility across model or backend revisions.
            Each descriptor spells it in its own dialect (``seed``, ``random_seed``);
            targets that have no such field report a dropped parameter rather than
            silently sampling freely.
        presence_penalty: Penalty applied to tokens that have already appeared at all,
            discouraging repeated topics. Provider scales differ; the value is passed
            through unchanged rather than rescaled, because a rescaled penalty is a
            number the caller cannot reason about.
        frequency_penalty: Penalty scaled by how often a token has already appeared,
            discouraging verbatim repetition.
    """

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    stop: tuple[str, ...] = ()
    seed: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None

    def __post_init__(self) -> None:
        """Reject sampling values no provider could act on.

        Raises:
            ValueError: If the seed is negative, or a penalty is not finite.
        """
        if self.seed is not None and self.seed < 0:
            raise ValueError("sampling seed must not be negative")
        for name in ("presence_penalty", "frequency_penalty"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")


ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]
"""Normalized reasoning effort; each descriptor translates it to its provider's wire form.

``none`` asks for reasoning to be *disabled*, and is distinct from both ``minimal`` and
from leaving the field unset. ``minimal`` means "think as little as you can", ``none``
means "do not think", and `None` means "whatever this model does by default" — three
different requests that produce three different wire forms. The level exists because
OpenAI's own vocabulary accepts it on current models, and a sidecar caller sending it
against an OpenAI backend must not be refused for using the dialect the gateway claims.

Not every provider can express it. Where a provider publishes a reasoning enum with no
off value, the descriptor omits the field rather than substituting a level the caller did
not ask for; each `ReasoningTranslator` documents its own choice.
"""


@runtime_checkable
class SupportsJSONSchema(Protocol):
    """Duck type for pydantic-style models supplied as schemas."""

    def model_json_schema(self) -> Mapping[str, Any]:
        """Return the JSON Schema describing this model."""
        ...


@dataclass(frozen=True, slots=True)
class SchemaSpec:
    """A structured-output contract.

    The ``json_schema`` here is the *canonical* schema. Providers may receive a projected
    variant on the wire, but responses are always validated against this one.

    Attributes:
        json_schema: The canonical JSON Schema every response is validated against.
        name: Label for the schema, passed to providers whose wire format names the
            expected response shape.
    """

    json_schema: Mapping[str, Any]
    name: str = "response"

    @classmethod
    def coerce(cls, obj: SchemaSpec | SupportsJSONSchema | Mapping[str, Any]) -> SchemaSpec:
        """Accept a `SchemaSpec`, a JSON-schema mapping, or a pydantic-style model.

        Args:
            obj: The schema in any accepted form.

        Returns:
            An equivalent `SchemaSpec`.

        Raises:
            TypeError: If ``obj`` is none of the accepted forms.
        """
        if isinstance(obj, SchemaSpec):
            return obj
        model_json_schema = getattr(obj, "model_json_schema", None)
        if callable(model_json_schema):
            schema = model_json_schema()
            name = getattr(obj, "__name__", None) or type(obj).__name__
            return cls(json_schema=dict(schema), name=str(name))
        if isinstance(obj, Mapping):
            title = obj.get("title")
            return cls(
                json_schema=dict(obj),
                name=str(title) if isinstance(title, str) and title else "response",
            )
        raise TypeError(
            "schema must be a SchemaSpec, a JSON-schema mapping, or an object exposing "
            f"model_json_schema(); got {type(obj).__name__}"
        )


@dataclass(frozen=True, slots=True)
class ToolAnnotations:
    """Behavioural hints a tool source advertises about a tool.

    **Untrusted by construction.** These arrive from whatever declared the tool — a Model
    Context Protocol server, most often, and the protocol that defines them says plainly
    that a client must not treat them as guarantees. AnyInfer honours that: a hint may gate
    an *optimization*, and it may never gate a security decision. Nothing is granted more
    access, skipped, or auto-approved because a server called it read-only.

    Every field is ``None`` when the source said nothing, which is different from ``False``
    — "not stated" and "stated not to be" are not the same claim.

    Attributes:
        title: A human-readable name, when the source offers one distinct from ``name``.
        read_only: The tool does not modify its environment.
        destructive: The tool may perform irreversible updates.
        idempotent: Repeating the call with identical arguments changes nothing further.
        open_world: The tool touches systems outside a closed, predictable set.
    """

    title: str | None = None
    read_only: bool | None = None
    destructive: bool | None = None
    idempotent: bool | None = None
    open_world: bool | None = None

    @property
    def stated(self) -> bool:
        """Whether the source said anything at all."""
        return any(
            value is not None
            for value in (
                self.title,
                self.read_only,
                self.destructive,
                self.idempotent,
                self.open_world,
            )
        )


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the model may call.

    Attributes:
        name: Identifier the model uses to invoke the tool.
        description: What the tool does, shown to the model to guide when to call it.
        parameters: JSON Schema describing the tool's arguments.
        annotations: Untrusted behavioural hints from whatever declared the tool. Empty for
            tools declared in Python, where the code is its own description.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]
    annotations: ToolAnnotations = ToolAnnotations()


ToolChoice = Literal["auto", "none", "required"] | str
"""``"auto" | "none" | "required"``, or a specific tool name."""


@dataclass(frozen=True, slots=True)
class Repair:
    """Opt-in bounded repair budget for schema violations.

    Attributes:
        max_attempts: Maximum repair round-trips after a schema violation before the
            violation is surfaced as an error.
    """

    max_attempts: int = 1


HistoryMode = Literal["last_resort", "proactive"]
"""When conversation compaction runs relative to context-overflow routing."""

HISTORY_MODES = ("last_resort", "proactive")
"""Accepted `HistoryPolicy.mode` values."""


@dataclass(frozen=True, slots=True)
class HistoryPolicy:
    """Opt-in conversation compaction, applied by the client on the request path.

    A prompt that outgrows the window has two possible answers: send it somewhere with a
    bigger window, or make it smaller. The router has always owned the first
    (``Route.context_window_targets``). This owns the second, at the same layer, so the
    Python API, the command line, and the OpenAI-compatible frontend all behave the same
    way, because all three are the same client wearing different skins.

    Compaction is never silent: it emits a ``ContextReduced`` telemetry event, and it is
    off unless a policy is supplied.

    Attributes:
        enabled: Whether to compact at all. Present so a configuration file can turn the
            policy off without deleting how it was tuned.
        mode: ``last_resort`` compacts only after the route's context-overflow chain is
            exhausted, so a larger-window model is always preferred to losing history.
            ``proactive`` compacts to fit the resolved target before dispatch, trading
            that preference for one fewer failed preflight.
        keep_recent: Trailing messages held at full fidelity.
        keep_system: Whether system messages are protected wherever they appear.

    See `anyinfer.context.compact_history` for the rules compaction follows and for the
    same behaviour as a function you call yourself.
    """

    enabled: bool = True
    mode: HistoryMode = "last_resort"
    keep_recent: int = 6
    keep_system: bool = True

    def __post_init__(self) -> None:
        """Reject a policy that cannot be applied.

        Raises:
            ValueError: On an unknown mode or a negative recent window.
        """
        if self.mode not in HISTORY_MODES:
            raise ValueError(
                f"history mode must be one of {', '.join(HISTORY_MODES)}; got {self.mode!r}"
            )
        if self.keep_recent < 0:
            raise ValueError(f"keep_recent must be zero or greater; got {self.keep_recent!r}")

    @property
    def active(self) -> bool:
        """Whether this policy will actually compact anything."""
        return self.enabled


CacheMechanism = Literal["explicit", "implicit"]
"""How a provider's prompt cache is engaged.

``explicit``
    The provider accepts per-segment cache marks on the wire, so the core decides where the
    cacheable prefix ends and the adapter spells that mark.
``implicit``
    The provider caches stable prefixes on its own. There is nothing to send; the core's
    only duty is to leave the prefix undisturbed and to notice when the caller's own
    request defeats it.
"""

CacheMode = Literal["off", "auto", "explicit"]
"""What a request asks for.

``auto`` uses the strongest mechanism the target offers. ``explicit`` asks for marks and
reports a dropped parameter if the target has none, which is the setting for a caller who
would rather know than silently get nothing.
"""

CACHE_MODES = ("off", "auto", "explicit")
"""Accepted `CachePolicy.mode` values."""


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """Opt-in prompt-cache placement for one request.

    Off unless asked for. Caching changes what a provider bills and how long it retains a
    copy of the prompt, and neither is a decision this library makes on a caller's behalf —
    a request that carries no policy is cached exactly as much as it was before this
    existed, which is not at all.

    What it caches is the *prefix you send*, on the provider's side, for the provider's
    retention window. It never skips a call and never reuses an answer.

    Attributes:
        mode: ``off`` disables placement; ``auto`` uses the strongest available mechanism;
            ``explicit`` requires per-segment marks and reports a dropped parameter when
            the target has none.
        min_segment_tokens: Segments estimated smaller than this are not worth marking —
            below a provider's own floor a mark is billed as a cache *write* that no later
            read ever amortizes.
        max_marks: Most marks to place, clamped down to whatever the provider accepts.
        include_tools: Whether tool declarations may be marked. They are stable across a
            conversation and often large, so they are usually the best single mark.
        include_system: Whether the system block may be marked.
    """

    mode: CacheMode = "auto"
    min_segment_tokens: int = 1024
    max_marks: int = 4
    include_tools: bool = True
    include_system: bool = True

    def __post_init__(self) -> None:
        """Reject a policy that cannot be applied.

        Raises:
            ValueError: On an unknown mode, a negative floor, or a non-positive mark budget.
        """
        if self.mode not in CACHE_MODES:
            raise ValueError(
                f"cache mode must be one of {', '.join(CACHE_MODES)}; got {self.mode!r}"
            )
        if self.min_segment_tokens < 0:
            raise ValueError(
                f"min_segment_tokens must be zero or greater; got {self.min_segment_tokens!r}"
            )
        if self.max_marks < 1:
            raise ValueError(f"max_marks must be at least one; got {self.max_marks!r}")

    @property
    def active(self) -> bool:
        """Whether this policy will attempt any placement."""
        return self.mode != "off"


@dataclass(frozen=True, slots=True)
class SpendPolicy:
    """A ceiling on what one client may spend. Off unless supplied.

    Checked before dispatch, beside the context gate, so a refusal costs nothing. This is
    the caller's own policy on their own client — it shares no state with any other
    process and enforces no organization quota, which this library deliberately leaves to
    the deployment around it.

    Attributes:
        max_total_usd: Ceiling on this client's cumulative spend. ``None`` means no ceiling.
        max_request_usd: Ceiling on any single request's *estimated* cost.
        on_unknown: What to do when a target's cost cannot be estimated, because its
            pricing is missing or untrusted. ``allow`` preserves today's behaviour;
            ``refuse`` is for callers who would rather fail than spend blind. There is no
            third option that treats unknown as zero — a guard that does that enforces
            nothing while appearing to.
    """

    max_total_usd: Decimal | None = None
    max_request_usd: Decimal | None = None
    on_unknown: Literal["allow", "refuse"] = "allow"

    def __post_init__(self) -> None:
        """Reject a ceiling that cannot be enforced.

        Raises:
            ValueError: On a negative ceiling or an unknown ``on_unknown`` value.
        """
        for name in ("max_total_usd", "max_request_usd"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative; got {value!r}")
        if self.on_unknown not in ("allow", "refuse"):
            raise ValueError(f"on_unknown must be 'allow' or 'refuse'; got {self.on_unknown!r}")

    @property
    def active(self) -> bool:
        """Whether this policy can refuse anything."""
        return (
            self.max_total_usd is not None
            or self.max_request_usd is not None
            or self.on_unknown == "refuse"
        )


@dataclass(frozen=True, slots=True)
class RateLimits:
    """Client-side pacing for one provider instance. Inert unless configured.

    This paces *this process's own* requests to one provider so an application that fans
    out does not discover the provider's limits by being throttled by them. It shares no
    state with any other process, enforces no quota the provider did not state, and never
    influences which target is chosen — a limiter that picked a different provider because
    this one was busy would be load balancing, which this library deliberately does not do.

    With every field left at its default, a request is dispatched exactly as it was before
    this existed: no permit, no delay, no bookkeeping.

    Attributes:
        max_concurrent: Most requests in flight at once for this instance. ``None`` means
            unbounded, which is today's behaviour.
        requests_per_minute: Sustained request rate. Enforced as a token bucket, so a burst
            up to the per-minute allowance is permitted and then paced.
        min_interval_s: Smallest gap between two dispatches, for providers that object to
            bursts regardless of the rate.
        respect_headers: Whether to slow down when the provider's own rate-limit headers
            say its window is nearly exhausted. Inert when the provider declares no header
            dialect, since there is nothing to read.
        reserve_fraction: Fraction of the provider's stated remaining allowance to leave
            untouched, between 0 and 1. Matters whenever this process is not the only
            consumer of the key: stopping at the last request in the window means the other
            consumer is the one that gets throttled.
    """

    max_concurrent: int | None = None
    requests_per_minute: float | None = None
    min_interval_s: float = 0.0
    respect_headers: bool = True
    reserve_fraction: float = 0.0

    def __post_init__(self) -> None:
        """Reject a limit that cannot be honoured.

        Raises:
            ValueError: On a non-positive bound, a negative interval, or a reserve
                fraction outside the unit interval.
        """
        if self.max_concurrent is not None and self.max_concurrent < 1:
            raise ValueError(f"max_concurrent must be at least one; got {self.max_concurrent!r}")
        if self.requests_per_minute is not None and self.requests_per_minute <= 0:
            raise ValueError(
                f"requests_per_minute must be greater than zero; got {self.requests_per_minute!r}"
            )
        if self.min_interval_s < 0:
            raise ValueError(
                f"min_interval_s must be zero or greater; got {self.min_interval_s!r}"
            )
        if not 0.0 <= self.reserve_fraction < 1.0:
            raise ValueError(
                "reserve_fraction must be at least zero and less than one; "
                f"got {self.reserve_fraction!r}"
            )

    @property
    def active(self) -> bool:
        """Whether this policy can delay anything.

        A bare `RateLimits()` *is* active: it means "pace me by what the provider reports",
        which is the least a caller who asked for governance at all can mean. Opting out is
        spelled by supplying no limits, not by supplying empty ones — so
        `RateLimits(respect_headers=False)` with no bounds is the one inert instance, and
        it is inert honestly rather than by accident.
        """
        return (
            self.max_concurrent is not None
            or self.requests_per_minute is not None
            or self.min_interval_s > 0
            or self.respect_headers
        )


DEFAULT_TIMEOUT_S = 120.0
"""Per-attempt wall clock applied when a request leaves ``timeout_s`` unset."""

DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
"""Cap on total streamed response bytes per attempt."""

DEFAULT_MAX_INPUT_PART_BYTES = 20 * 1024 * 1024
"""Maximum inline bytes in one multimodal content part."""

DEFAULT_MAX_INPUT_BYTES = 50 * 1024 * 1024
"""Maximum inline multimodal bytes across one generation request."""

MAX_TOP_LOGPROBS = 20
"""Most alternative tokens per position a request may ask for.

The ceiling is the smallest one published by a provider that accepts the field at all
(OpenAI's ``top_logprobs``), so a request valid here is valid everywhere the feature
exists. Refusing at construction beats discovering the limit as a provider 400 after the
prompt has already been assembled.
"""


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """A fully-specified generation request, independent of any provider.

    This type is a deliberate superset of the OpenAI chat-completions request surface so the
    serve frontend stays a lossless codec.

    ``provider_options`` is the escape hatch for provider-specific parameters: keys are
    provider ids, values are mappings passed to that provider's adapter verbatim. The
    special key ``"*"`` applies to whichever provider ends up serving the request, with a
    provider-specific namespace winning field-by-field over the wildcard.

    Attributes:
        messages: The conversation so far, oldest turn first.
        schema: Structured-output contract to enforce, when one was requested.
        tools: Tools the model is allowed to call.
        tool_choice: Whether tool use is automatic, forbidden, required, or pinned to one
            named tool.
        sampling: Sampling controls; unset fields fall through to provider defaults.
        reasoning: Requested reasoning effort, for models that support it.
        timeout_s: Per-attempt wall-clock budget; ``None`` means `DEFAULT_TIMEOUT_S`.
        max_response_bytes: Cap on total streamed response bytes per attempt.
        repair: Budget for schema-repair round-trips; ``None`` disables repair.
        provider_options: Provider-specific parameters keyed by provider id, passed to
            the serving adapter verbatim (see above for the ``"*"`` wildcard rule).
        metadata: Opaque caller-supplied labels, carried through unchanged and echoed in
            telemetry.
        history: Per-request conversation-compaction policy, overriding the client's
            default. ``None`` means "use the client's". Carried on the request rather than
            passed alongside it so the serve frontend stays a lossless codec: an
            ``anyinfer_history`` object on the wire decodes into exactly this field.
        cache: Per-request prompt-cache placement, overriding the client's default.
            ``None`` — the default — means no placement at all, since caching changes what
            a provider bills. Carried on the request for the same codec reason as
            ``history``: an ``anyinfer_cache`` object on the wire decodes into this field.
        arena: Per-request fixed fan-out policy, overriding the client's default. Adapters
            never see it; the client runs and selects every candidate before projection.
        context: Explicit caller-approved documents to reduce for the resolved target.
            ``None`` preserves ordinary generation byte-for-byte.
        logprobs: How many alternative tokens to report a log-probability for at each
            generated position. ``None`` — the default — asks for none, and is the only
            value that costs nothing: every provider that returns logprobs inflates the
            response with them. ``0`` asks for the chosen token's own probability and no
            alternatives, which is what a confidence-scoring caller needs; a positive value
            additionally asks for that many runners-up. A target known not to report them
            emits a dropped-parameter event rather than returning an empty ``logprobs``
            a caller would have to notice for themselves.
        cite_documents: Ask the target to attribute its answer to the documents this
            request supplied. Every dialect that can do this treats it as a request-side
            opt-in — a model does not volunteer citations — and several bill differently
            for a cited answer, so it is off by default and never inferred from the mere
            presence of a `DocumentPart`. A target that cannot cite reports a dropped
            parameter; the answer still arrives, without attributions.
    """

    messages: tuple[Message, ...]
    schema: SchemaSpec | None = None
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: ToolChoice = "auto"
    sampling: Sampling = Sampling()
    reasoning: ReasoningEffort | None = None
    timeout_s: float | None = None
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_input_part_bytes: int = DEFAULT_MAX_INPUT_PART_BYTES
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES
    repair: Repair | None = None
    provider_options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)
    history: HistoryPolicy | None = None
    cache: CachePolicy | None = None
    arena: ArenaPolicy | None = None
    context: ContextRequest | None = None
    logprobs: int | None = None
    cite_documents: bool = False

    def __post_init__(self) -> None:
        """Enforce multimodal request byte ceilings before any adapter can run."""
        if self.max_input_part_bytes < 1 or self.max_input_bytes < 1:
            raise ValueError("multimodal input byte ceilings must be positive")
        if self.logprobs is not None and not 0 <= self.logprobs <= MAX_TOP_LOGPROBS:
            raise ValueError(f"logprobs must be between 0 and {MAX_TOP_LOGPROBS}")
        total = 0
        for message in self.messages:
            for part in message.content:
                data = (
                    part.data
                    if isinstance(part, ImagePart | DocumentPart | AudioPart | VideoPart)
                    else None
                )
                if data is None:
                    continue
                size = len(data)
                if size > self.max_input_part_bytes:
                    raise ValueError(
                        f"a multimodal part is {size} bytes; the per-part limit is "
                        f"{self.max_input_part_bytes}"
                    )
                total += size
        if total > self.max_input_bytes:
            raise ValueError(
                f"multimodal inputs total {total} bytes; the request limit is "
                f"{self.max_input_bytes}"
            )

    @property
    def effective_timeout_s(self) -> float:
        """The per-attempt timeout, resolving ``None`` to the default."""
        return DEFAULT_TIMEOUT_S if self.timeout_s is None else self.timeout_s

    def with_messages(self, messages: Sequence[Message]) -> GenerationRequest:
        """Return a copy of this request with different messages.

        Used by the repair loop and the tool loop, which extend the conversation without
        touching any other request field.
        """
        return replace(self, messages=tuple(messages))


Target = str
"""Where a request should go.

Grammar::

    Target  = ALIAS | PROVIDER ":" MODEL
    PROVIDER = [a-z0-9-]+      (after normalization: lowercased, stripped, "_" -> "-")
    MODEL    = the remainder verbatim

Split on the **first** colon only — model ids may themselves contain colons
(``"ollama:qwen3:8b"``). A target without a colon must match a catalog alias.
"""


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """A target after alias and provider-alias resolution.

    Attributes:
        provider_id: Normalized id of the provider that will serve the request.
        model: The model identifier, verbatim as the provider expects it.
        via_alias: The catalog alias this target was resolved from, if any.
    """

    provider_id: str
    model: str
    via_alias: str | None = None

    def __str__(self) -> str:
        """Render as the canonical ``provider:model`` spelling."""
        return f"{self.provider_id}:{self.model}"
