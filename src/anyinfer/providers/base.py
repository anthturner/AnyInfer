"""The provider-adapter contract.

An adapter **only translates**. It receives a fully-resolved `WireRequest` — concrete
model, chosen mechanism, projected schema, translated reasoning effort, merged options — and
yields normalized events. It never retries, never validates a schema, never measures TTFT,
and never consults routing policy: all of that is the core's job, which is what keeps nine
adapters thin enough for one conformance suite to cover.

If you find yourself adding control flow to an adapter, stop and move it to the core.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..types.capabilities import DiscoveredModel, Health
from ..types.events import ReasoningDelta, TextDelta, ToolCallDelta, UsageUpdate
from ..types.messages import Message
from ..types.requests import Sampling, ToolSpec
from ..types.results import FinishReason, Mechanism, Usage

if TYPE_CHECKING:
    from ..events.telemetry import TelemetryEvent

__all__ = [
    "AdapterEvent",
    "AdapterFinal",
    "ProviderAdapter",
    "ProviderConfig",
    "WireRequest",
]


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Resolved configuration handed to an adapter factory.

    Credentials arrive already resolved and already registered for redaction; an adapter
    never sees a ``credential://`` reference.
    """

    provider_id: str
    """Id of the configured provider instance this adapter serves, e.g. ``openai`` or an
    application-chosen instance id such as ``work-azure``."""

    base_url: str | None = None
    """Endpoint to talk to, after defaults and host-shorthand expansion; ``None`` for
    providers that derive their own endpoint."""

    api_key: str | None = None
    """Resolved credential, sent however this provider expects (named header, bearer
    token, request signing); ``None`` when unconfigured."""

    api_version: str | None = None
    """Version pin for providers that version via a header or query parameter; ``None``
    means the adapter's built-in default."""

    headers: Mapping[str, str] = field(default_factory=dict)
    """Extra HTTP headers merged into every request, overriding the adapter's defaults on
    collision."""

    options: Mapping[str, Any] = field(default_factory=dict)
    """Provider-specific settings beyond the common fields (regions, tokens, launch
    knobs), with any secret values already resolved."""

    timeout_s: float = 120.0
    """Wall-clock timeout the adapter's transport applies to its HTTP calls."""

    transport: Any | None = None
    """Optional ``httpx2`` transport override. Used by the fake-server and cassette test
    modes to intercept traffic without touching the adapter's wire logic."""

    events: Callable[[TelemetryEvent], None] | None = None
    """Sink for adapter-side lifecycle telemetry (`ServerLifecycle`, `DownloadProgress`).

    Wired to the owning client's observer dispatcher. Only *lifecycle* events belong
    here — request-path telemetry stays in the core, which is what keeps adapters pure
    translators."""


@dataclass(frozen=True, slots=True)
class WireRequest:
    """A generation request, fully resolved for one provider.

    Attributes:
        model: The concrete model id (or a provider sentinel such as ``"auto"``).
        messages: The conversation, including any core-injected schema instruction.
        sampling: Sampling controls; unset fields must be omitted from the wire payload.
        reasoning_wire: Provider-specific reasoning fields, already translated.
        mechanism: The structured-output mechanism the core chose, or ``None``.
        wire_schema: The projected schema to send, or ``None`` for prompt-based mechanisms.
        schema_name: Schema name, for providers that require one.
        tools: Tools the model may call.
        tool_choice: ``"auto"``, ``"none"``, ``"required"``, or a specific tool name.
        stream: Whether to request streaming. A hint — the core handles both shapes.
        timeout_s: Per-attempt wall clock.
        max_response_bytes: Cap on total streamed bytes.
        extra_options: ``provider_options[this_provider]``, passed through verbatim.
    """

    model: str
    messages: tuple[Message, ...]
    sampling: Sampling = Sampling()
    reasoning_wire: Mapping[str, Any] = field(default_factory=dict)
    mechanism: Mechanism | None = None
    wire_schema: Mapping[str, Any] | None = None
    schema_name: str | None = None
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: str = "auto"
    stream: bool = True
    timeout_s: float = 120.0
    max_response_bytes: int = 1_048_576
    extra_options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdapterFinal:
    """Terminal event every adapter must yield exactly once on success.

    Attributes:
        finish_reason: Normalized stop reason.
        usage: Final usage, when the provider reported any.
        phases: Provider-reported phase timings in milliseconds (e.g. model load).
        raw: The provider payload. Adapters attach it unconditionally; the core keeps it
            on the result only when the client opted in via ``retain_raw``.
    """

    finish_reason: FinishReason
    usage: Usage | None = None
    phases: Mapping[str, float] = field(default_factory=dict)
    raw: Any | None = None


AdapterEvent = TextDelta | ReasoningDelta | ToolCallDelta | UsageUpdate | AdapterFinal
"""The strict subset of events an adapter may emit."""


@runtime_checkable
class ProviderAdapter(Protocol):
    """What every provider adapter implements.

    Four methods, no more. `generate()` is the single generation entry point and always
    yields events — a buffered provider emits one delta plus a final, and the core drains it
    for non-streaming callers.

    Adapters may implement ``generate`` either as an ``async def`` generator or as a plain
    method returning an async iterator; both satisfy this signature.
    """

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """Enumerate models this provider offers."""
        ...

    async def health(self) -> Health:
        """Cheap readiness probe consulted by the router's health gate."""
        ...

    def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one generation, yielding normalized events.

        Raises:
            anyinfer.errors.ProviderError: With ``retryable``/``retry_after_s`` set. Adapters
                classify; the router decides.
        """
        ...

    async def aclose(self) -> None:
        """Release transports and any supervised resources."""
        ...
