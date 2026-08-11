"""The provider-adapter contract.

An adapter **only translates**. It receives a fully-resolved `WireRequest` — concrete
model, chosen mechanism, projected schema, translated reasoning effort, merged options — and
yields normalized events. It never retries, never validates a schema, never measures TTFT,
and never consults routing policy: all of that is the core's job, which is what keeps the
adapter inventory thin enough for one conformance suite to cover.

If you find yourself adding control flow to an adapter, stop and move it to the core.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..types.capabilities import DiscoveredModel, Health
from ..types.events import ReasoningDelta, TextDelta, ToolCallDelta, UsageUpdate
from ..types.messages import Message
from ..types.operations import EmbeddingInputIntent
from ..types.requests import Sampling, ToolSpec
from ..types.results import Diagnostic, FinishReason, Mechanism, Usage

if TYPE_CHECKING:
    from ..events.telemetry import TelemetryEvent

__all__ = [
    "AdapterEvent",
    "AdapterFinal",
    "EmbeddingWireRequest",
    "EmbeddingWireResult",
    "EmbedsText",
    "GeneratesText",
    "ProviderAdapter",
    "ProviderConfig",
    "ProviderLifecycle",
    "RerankWireDocument",
    "RerankWireRequest",
    "RerankWireResult",
    "ReranksText",
    "SupportsDiagnostics",
    "WireRankedItem",
    "WireRequest",
]


def _encode_function_tool(tool: ToolSpec) -> dict[str, Any]:
    """Encode a tool in the OpenAI-compatible function wrapper shared by several dialects."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


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
        cache_marks: Where the core decided the prompt cache should be engaged, as segment
            indices — ``-2`` for the tool declarations, ``-1`` for the system block, and
            zero-based message indices otherwise. Empty for every request without a cache
            policy, and for every provider whose cache needs no marks. An adapter's whole
            duty here is to spell each mark in its own wire format; deciding *where* they
            go is the core's, and belongs to `anyinfer.capabilities.cache`.
        extra_options: ``provider_options[this_provider]``, passed through verbatim.
        session_state: Opaque continuation data from an open
            `Session`, or ``None`` for an
            independent request. The distinction matters: ``{}`` means *a session is open
            and has nothing stored yet* — the first turn, while ``None`` means there is
            no session at all. Only providers declaring ``supports_sessions`` ever receive
            a value, and only they interpret it; the core stores and forwards it without
            reading it.
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
    cache_marks: tuple[int, ...] = ()
    extra_options: Mapping[str, Any] = field(default_factory=dict)
    session_state: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AdapterFinal:
    """Terminal event every adapter must yield exactly once on success.

    Attributes:
        finish_reason: Normalized stop reason.
        usage: Final usage, when the provider reported any.
        phases: Provider-reported phase timings in milliseconds (e.g. model load).
        raw: The provider payload. Adapters attach it unconditionally; the core keeps it
            on the result only when the client opted in via ``retain_raw``.
        session_state: Continuation data to remember for the next turn of an open
            session, or ``None`` when there is none. Opaque to the core.
    """

    finish_reason: FinishReason
    usage: Usage | None = None
    phases: Mapping[str, float] = field(default_factory=dict)
    raw: Any | None = None
    session_state: Mapping[str, Any] | None = None


AdapterEvent = TextDelta | ReasoningDelta | ToolCallDelta | UsageUpdate | AdapterFinal
"""The strict subset of events an adapter may emit."""


@runtime_checkable
class ProviderLifecycle(Protocol):
    """The lifecycle every provider adapter implements, regardless of which operations it supports.

    Three methods, no more: discovery, health, and cleanup. An adapter additionally
    implements one or more of `GeneratesText`, `EmbedsText`, `ReranksText` — whichever
    operations its descriptor declares support for (see `ProviderDescriptor.operations`).
    A retrieval-only adapter (a hosted reranker with no chat endpoint) implements this plus
    `ReranksText` and nothing else; it needs no dummy `generate()`.
    """

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """Enumerate models this provider offers."""
        ...

    async def health(self) -> Health:
        """Cheap readiness probe consulted by the router's health gate."""
        ...

    async def aclose(self) -> None:
        """Release transports and any supervised resources."""
        ...


@runtime_checkable
class GeneratesText(Protocol):
    """A provider adapter that can generate text.

    `generate()` is the single generation entry point and always yields events — a
    buffered provider emits one delta plus a final, and the core drains it for
    non-streaming callers. Adapters may implement it either as an ``async def`` generator
    or as a plain method returning an async iterator; both satisfy this signature.
    """

    def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one generation, yielding normalized events.

        Raises:
            anyinfer.errors.ProviderError: With ``retryable``/``retry_after_s`` set. Adapters
                classify; the router decides.
        """
        ...


@dataclass(frozen=True, slots=True)
class EmbeddingWireRequest:
    """An embedding request, fully resolved for one provider.

    Attributes:
        model: The concrete model id.
        inputs: Texts to embed, in the exact order the response must preserve.
        input_type: Requested input intent, already validated against what this provider
            accepts; ``None`` when no intent is asserted or the provider ignores the concept.
        dimensions: Requested output dimensionality, or ``None`` for the model's default.
        timeout_s: Per-attempt wall clock.
        max_response_bytes: Cap on the response body.
        extra_options: ``provider_options[this_provider]``, passed through verbatim.
    """

    model: str
    inputs: tuple[str, ...]
    input_type: EmbeddingInputIntent | None = None
    dimensions: int | None = None
    timeout_s: float = 120.0
    max_response_bytes: int = 1_048_576
    extra_options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddingWireResult:
    """What an adapter returns from one embedding call.

    Attributes:
        vectors: Raw vector components, in input order. Validated into `EmbeddingVector`
            by the core, not the adapter.
        model: The concrete model id the provider reports serving the request, when it
            reports one; falls back to the requested model otherwise.
        dimensions: The vector length actually returned, when the provider states it
            separately from the vector data.
        normalized: Whether the provider states these vectors are unit-normalized.
        usage: Usage the provider reported for this call, when any.
        raw: The provider payload, attached unconditionally; the core retains it only when
            the request opted in.
    """

    vectors: tuple[tuple[float, ...], ...]
    model: str | None = None
    dimensions: int | None = None
    normalized: bool | None = None
    usage: Usage | None = None
    raw: Any | None = None


@runtime_checkable
class EmbedsText(Protocol):
    """A provider adapter that can embed text into vectors."""

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one embedding call, buffered — embeddings are never streamed.

        Raises:
            anyinfer.errors.ProviderError: With ``retryable``/``retry_after_s`` set.
        """
        ...


@dataclass(frozen=True, slots=True)
class RerankWireDocument:
    """One document sent to a provider's rerank call.

    Attributes:
        index: Position in the original request, so the adapter's translation cannot lose
            it even when the provider's own response omits echoing an id.
        text: The document text.
    """

    index: int
    text: str


@dataclass(frozen=True, slots=True)
class RerankWireRequest:
    """A rerank request, fully resolved for one provider.

    Attributes:
        model: The concrete model id.
        query: The query text.
        documents: Documents to rank, indexed by their position in the original request.
        top_n: Requested result truncation, or ``None`` for every document ranked.
        timeout_s: Per-attempt wall clock.
        max_response_bytes: Cap on the response body.
        extra_options: ``provider_options[this_provider]``, passed through verbatim.
    """

    model: str
    query: str
    documents: tuple[RerankWireDocument, ...]
    top_n: int | None = None
    timeout_s: float = 120.0
    max_response_bytes: int = 1_048_576
    extra_options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WireRankedItem:
    """One ranked document as a provider reported it.

    Attributes:
        index: The document's position in `RerankWireRequest.documents`, as the provider
            reported it. The core validates this is in range and unique before trusting it.
        score: The provider's relevance score.
    """

    index: int
    score: float


@dataclass(frozen=True, slots=True)
class RerankWireResult:
    """What an adapter returns from one rerank call.

    Attributes:
        items: Ranked documents as the provider returned them, in the provider's own
            result order. The core validates index integrity before building `RankedItem`s.
        model: The concrete model id the provider reports serving the request, when it
            reports one.
        usage: Usage the provider reported for this call, when any.
        raw: The provider payload, attached unconditionally.
    """

    items: tuple[WireRankedItem, ...]
    model: str | None = None
    usage: Usage | None = None
    raw: Any | None = None


@runtime_checkable
class ReranksText(Protocol):
    """A provider adapter that can rerank documents against a query."""

    async def rerank(self, req: RerankWireRequest) -> RerankWireResult:
        """Run one rerank call, buffered — reranking is never streamed.

        Raises:
            anyinfer.errors.ProviderError: With ``retryable``/``retry_after_s`` set.
        """
        ...


@runtime_checkable
class ProviderAdapter(Protocol):
    """What every text-generation provider adapter implements.

    Structurally this is `ProviderLifecycle` plus `GeneratesText`, kept as one combined name
    so the seventeen existing generation adapters need no change. A new adapter that only
    embeds or only reranks implements `ProviderLifecycle` plus `EmbedsText`/`ReranksText`
    instead.
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


@runtime_checkable
class SupportsDiagnostics(Protocol):
    """An adapter that can report on the state of its own runtime.

    Optional, and declared on the descriptor
    (``reports_diagnostics=True``) rather than discovered by probing for the method: the
    core asks providers that advertise the ability, so which providers can do this is
    readable from the registry instead of from a dozen ``hasattr`` calls.

    Implementations must be cheap and must not raise. A diagnostic that costs a
    round trip on every request is worse than the condition it reports, and the core
    treats collection failures as "nothing to report" — advisory data must never turn a
    successful generation into a failed one.
    """

    async def diagnostics(self) -> Sequence[Diagnostic]:
        """Report anything notable about this provider's current runtime state."""
        ...
