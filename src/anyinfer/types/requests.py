"""Request-side types: sampling knobs, schemas, tools, targets, and the request itself.

These are the inputs a caller controls. Everything here is inert data — resolution of
targets, schema mechanisms, and provider options happens in the core, not in these types,
which are used throughout the client and provider boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, runtime_checkable

from .messages import Message

__all__ = [
    "CACHE_MODES",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_TIMEOUT_S",
    "HISTORY_MODES",
    "CacheMechanism",
    "CacheMode",
    "CachePolicy",
    "GenerationRequest",
    "HistoryMode",
    "HistoryPolicy",
    "ReasoningEffort",
    "Repair",
    "ResolvedTarget",
    "Sampling",
    "SchemaSpec",
    "SupportsJSONSchema",
    "Target",
    "ToolChoice",
    "ToolSpec",
]


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
    """

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    stop: tuple[str, ...] = ()


ReasoningEffort = Literal["minimal", "low", "medium", "high"]
"""Normalized reasoning effort; each descriptor translates it to its provider's wire form."""


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
class ToolSpec:
    """A tool the model may call.

    Attributes:
        name: Identifier the model uses to invoke the tool.
        description: What the tool does, shown to the model to guide when to call it.
        parameters: JSON Schema describing the tool's arguments.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]


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
    (``Route.context_window_targets``). This owns the second, at the same layer — so the
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


DEFAULT_TIMEOUT_S = 120.0
"""Per-attempt wall clock applied when a request leaves ``timeout_s`` unset."""

DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
"""Cap on total streamed response bytes per attempt."""


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
    """

    messages: tuple[Message, ...]
    schema: SchemaSpec | None = None
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: ToolChoice = "auto"
    sampling: Sampling = Sampling()
    reasoning: ReasoningEffort | None = None
    timeout_s: float | None = None
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    repair: Repair | None = None
    provider_options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)
    history: HistoryPolicy | None = None
    cache: CachePolicy | None = None

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
