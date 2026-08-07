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
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_TIMEOUT_S",
    "GenerationRequest",
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
