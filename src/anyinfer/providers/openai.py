"""OpenAI's Responses API (`contracts/openai.md`).

The Responses API, not chat completions: it is OpenAI's current surface, and it exposes
reasoning effort and reasoning-token accounting that the chat-completions shape does not.
Callers wanting the older dialect can point the ``openai-compat`` provider at
``https://api.openai.com/v1``.

Its streaming protocol is typed events (``response.output_text.delta``,
``response.completed``, …) rather than delta chunks, so the mapping is explicit rather than
inherited from `anyinfer.providers.openai_compat`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import aclosing
from typing import Any, ClassVar

import httpx2

from ..errors import Phase, ProviderError, StreamProtocolError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    ModelCapabilities,
    RateLimitHeaders,
    Sourced,
)
from ..types.events import ReasoningDelta, TextDelta, ToolCallDelta, UsageUpdate
from ..types.messages import (
    AudioPart,
    DocumentPart,
    ImagePart,
    Message,
    Text,
    ToolCall,
    ToolResult,
)
from ..types.operations import EmbeddingCapabilities
from ..types.requests import ReasoningEffort, Sampling, ToolSpec
from ..types.results import FinishReason, Usage
from ._multimodal import base64_data, data_url, media_subtype
from .base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest
from .http import build_client, classify_status, map_transport_error, read_error_detail, read_int
from .openai_compat_embeddings import OpenAICompatEmbeddingsMixin
from .sse import iter_sse

__all__ = ["OpenAIAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://api.openai.com/v1"

_INCOMPLETE_REASONS: Mapping[str, FinishReason] = {
    "max_output_tokens": "length",
    "content_filter": "content_filter",
}


class OpenAIAdapter(OpenAICompatEmbeddingsMixin):
    """Adapter for the OpenAI Responses API."""

    provider_id: ClassVar[str] = "openai"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        headers = {"content-type": "application/json"}
        if config.api_key:
            headers["authorization"] = f"Bearer {config.api_key}"
        headers.update({k.lower(): v for k, v in config.headers.items()})
        self._client = build_client(
            base_url=(config.base_url or _DEFAULT_BASE_URL).rstrip("/"),
            headers=headers,
            timeout_s=config.timeout_s,
            transport=config.transport,
        )

    def _classify(
        self,
        status: int,
        detail: str,
        headers: Mapping[str, str],
        phase: Phase = "generate",
    ) -> ProviderError:
        """Error-classification hook required by `OpenAICompatEmbeddingsMixin`.

        Every other adapter composing that mixin also inherits `OpenAICompatAdapter`,
        which supplies this. This one does not -- the Responses API is its own dialect --
        so without this method the mixin's error path raised `AttributeError` instead of a
        typed, retryable `ProviderError`, and the router could not retry a rate-limited
        embeddings call because what it caught was not a provider error at all.

        A default on the mixin would fix it in the wrong place: `openrouter` and `ollama`
        override `_classify` for dialect-specific mapping, and the mixin sits *before*
        the compat adapter in every other user's MRO, so a default there would shadow
        those overrides.
        """
        return classify_status(
            status, provider=self.provider_id, detail=detail, headers=headers, phase=phase
        )

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List models from ``GET /models``."""
        try:
            response = await self._client.get("/models")
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="discover") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                headers=response.headers,
                phase="discover",
            )
        payload = response.json()
        entries = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(entries, list):
            return []
        return [
            DiscoveredModel(
                id=str(entry["id"]),
                capabilities=ModelCapabilities(features=Sourced(_OPENAI_FEATURES, "discovered")),
            )
            for entry in entries
            if isinstance(entry, Mapping) and entry.get("id")
        ]

    async def health(self) -> Health:
        """Probe readiness by listing models."""
        try:
            response = await self._client.get("/models")
        except httpx2.HTTPError as exc:
            return Health(ok=False, detail=str(exc)[:200])
        if response.status_code >= 400:
            return Health(ok=False, detail=f"HTTP {response.status_code}")
        return Health(ok=True)

    # ---- generation ------------------------------------------------------------------

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one generation against ``POST /responses``."""
        payload = self.build_payload(req)
        try:
            async with self._client.stream(
                "POST",
                "/responses",
                json=payload,
                timeout=req.timeout_s,
                headers={"accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise classify_status(
                        response.status_code,
                        provider=self.provider_id,
                        detail=read_error_detail(body),
                        headers=response.headers,
                    )

                state = _StreamState()
                # `aclosing`: an early close of this generator (a consumer breaking out of
                # a stream) must also close the SSE parser's, or it and the open connection
                # are left to finalize during GC instead of closing deterministically.
                async with aclosing(
                    iter_sse(
                        response.aiter_bytes(),
                        max_bytes=req.max_response_bytes,
                        provider=self.provider_id,
                    )
                ) as chunks:
                    async for chunk in chunks:
                        for event in self._events_from_chunk(chunk, state):
                            yield event
                yield state.finalize()
        except (ProviderError, StreamProtocolError):
            raise
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="stream") from exc

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Translate a wire request into a Responses API body."""
        instructions, items = _split_instructions(req.messages)

        payload: dict[str, Any] = {
            "model": req.model,
            "input": items,
            "stream": True,
        }
        if instructions:
            payload["instructions"] = instructions

        self._apply_sampling(payload, req.sampling)

        if req.mechanism == "json_schema" and req.wire_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": req.schema_name or "response",
                    "schema": dict(req.wire_schema),
                }
            }
        elif req.mechanism == "json_mode":
            payload["text"] = {"format": {"type": "json_object"}}

        if req.tools:
            payload["tools"] = [self._encode_tool(t) for t in req.tools]
            payload["tool_choice"] = self._encode_tool_choice(req.tool_choice)

        payload.update(req.reasoning_wire)
        payload.update(req.extra_options)
        return payload

    def _apply_sampling(self, payload: dict[str, Any], sampling: Sampling) -> None:
        """Add only the sampling fields the caller actually set."""
        if sampling.temperature is not None:
            payload["temperature"] = sampling.temperature
        if sampling.top_p is not None:
            payload["top_p"] = sampling.top_p
        if sampling.max_output_tokens is not None:
            payload["max_output_tokens"] = sampling.max_output_tokens

    def _encode_tool(self, tool: ToolSpec) -> dict[str, Any]:
        """Encode a tool in the Responses API's flattened form."""
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        }

    def _encode_tool_choice(self, choice: str) -> Any:
        if choice in ("auto", "none", "required"):
            return choice
        return {"type": "function", "name": choice}

    def _events_from_chunk(self, chunk: Any, state: _StreamState) -> Iterable[AdapterEvent]:
        """Translate one typed Responses event into adapter events."""
        if not isinstance(chunk, Mapping):
            return
        kind = str(chunk.get("type", ""))

        if kind == "response.output_text.delta":
            delta = chunk.get("delta")
            if isinstance(delta, str) and delta:
                yield TextDelta(delta)
            return

        if kind in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            delta = chunk.get("delta")
            if isinstance(delta, str) and delta:
                yield ReasoningDelta(delta)
            return

        if kind == "response.output_item.added":
            item = chunk.get("item")
            index = chunk.get("output_index")
            if (
                isinstance(item, Mapping)
                and isinstance(index, int)
                and item.get("type") == "function_call"
            ):
                yield ToolCallDelta(
                    index=state.tool_slot(index),
                    call_id=str(item.get("call_id") or item.get("id") or "") or None,
                    name=str(item.get("name", "")) or None,
                    arguments_fragment="",
                )
            return

        if kind == "response.function_call_arguments.delta":
            index = chunk.get("output_index")
            delta = chunk.get("delta")
            if isinstance(index, int) and isinstance(delta, str) and delta:
                yield ToolCallDelta(
                    index=state.tool_slot(index),
                    call_id=None,
                    name=None,
                    arguments_fragment=delta,
                )
            return

        if kind in ("response.completed", "response.incomplete", "response.failed"):
            response = chunk.get("response")
            if isinstance(response, Mapping):
                usage = _parse_usage(response.get("usage"))
                if usage is not None:
                    state.usage = state.usage.merge(usage)
                    yield UsageUpdate(usage)
                state.finish_reason = _finish_reason(response, state)
            if kind == "response.failed":
                raise ProviderError(
                    _failure_detail(chunk) or "the response failed",
                    provider=self.provider_id,
                )
            return

        if kind == "error":
            raise ProviderError(
                _failure_detail(chunk) or "openai reported a stream error",
                provider=self.provider_id,
            )

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


class _StreamState:
    """Tracks finish reason, usage, and output-index to tool-slot mapping."""

    __slots__ = ("finish_reason", "saw_tool_call", "tool_slots", "usage")

    def __init__(self) -> None:
        self.finish_reason: FinishReason = "stop"
        self.usage = Usage()
        self.tool_slots: dict[int, int] = {}
        self.saw_tool_call = False

    def tool_slot(self, output_index: int) -> int:
        """Map an output-item index onto a dense tool-call slot."""
        slot = self.tool_slots.get(output_index)
        if slot is None:
            slot = len(self.tool_slots)
            self.tool_slots[output_index] = slot
        self.saw_tool_call = True
        return slot

    def finalize(self) -> AdapterFinal:
        """Build the terminal adapter event."""
        usage = self.usage.normalized()
        return AdapterFinal(
            finish_reason=self.finish_reason,
            usage=usage if usage != Usage() else None,
        )


def _finish_reason(response: Mapping[str, Any], state: _StreamState) -> FinishReason:
    """Derive a normalized finish reason from a terminal response object."""
    details = response.get("incomplete_details")
    if isinstance(details, Mapping):
        reason = details.get("reason")
        if isinstance(reason, str):
            return _INCOMPLETE_REASONS.get(reason, "other")
    if state.saw_tool_call:
        return "tool_calls"
    status = response.get("status")
    return "other" if isinstance(status, str) and status != "completed" else "stop"


def _failure_detail(chunk: Mapping[str, Any]) -> str:
    """Read an error message from a failure event."""
    for key in ("error", "response"):
        value = chunk.get(key)
        if isinstance(value, Mapping):
            error = value.get("error", value)
            if isinstance(error, Mapping):
                message = error.get("message")
                if isinstance(message, str):
                    return message
    message = chunk.get("message")
    return message if isinstance(message, str) else ""


def _split_instructions(messages: Sequence[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Split system messages into ``instructions`` and encode the rest as input items."""
    instructions: list[str] = []
    items: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "system":
            text = "".join(p.text for p in message.content if isinstance(p, Text))
            if text:
                instructions.append(text)
            continue

        for part in message.content:
            if isinstance(part, ToolResult):
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": part.call_id,
                        "output": part.content,
                    }
                )
            elif isinstance(part, ToolCall):
                items.append(
                    {
                        "type": "function_call",
                        "call_id": part.id,
                        "name": part.name,
                        "arguments": json.dumps(dict(part.arguments)),
                    }
                )

        text = "".join(p.text for p in message.content if isinstance(p, Text))
        modal = [p for p in message.content if isinstance(p, ImagePart | DocumentPart | AudioPart)]
        if text or modal:
            content_type = "output_text" if message.role == "assistant" else "input_text"
            content: list[dict[str, Any]] = []
            if text:
                content.append({"type": content_type, "text": text})
            for part in modal:
                if isinstance(part, ImagePart):
                    image: dict[str, Any] = {
                        "type": "input_image",
                        "image_url": part.url or data_url(part.media_type, part.data or b""),
                    }
                    if part.detail is not None:
                        image["detail"] = part.detail
                    content.append(image)
                elif isinstance(part, DocumentPart):
                    file: dict[str, Any] = {"type": "input_file"}
                    if part.data is not None:
                        file["file_data"] = data_url(part.media_type, part.data)
                    else:
                        file["file_url"] = part.url
                    if part.filename is not None:
                        file["filename"] = part.filename
                    content.append(file)
                elif isinstance(part, AudioPart):
                    content.append(
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64_data(part.data),
                                "format": media_subtype(part.media_type),
                            },
                        }
                    )
            items.append(
                {
                    "role": message.role,
                    "content": content,
                }
            )

    return "\n\n".join(instructions), items


def _parse_usage(payload: Any) -> Usage | None:
    """Read the Responses usage block, including reasoning tokens."""
    if not isinstance(payload, Mapping):
        return None

    reasoning = None
    details = payload.get("output_tokens_details")
    if isinstance(details, Mapping):
        reasoning = read_int(details, "reasoning_tokens")

    cached = None
    input_details = payload.get("input_tokens_details")
    if isinstance(input_details, Mapping):
        cached = read_int(input_details, "cached_tokens")

    usage = Usage(
        input_tokens=read_int(payload, "input_tokens"),
        output_tokens=read_int(payload, "output_tokens"),
        total_tokens=read_int(payload, "total_tokens"),
        cache_read_tokens=cached,
        reasoning_tokens=reasoning,
    )
    return usage if usage != Usage() else None


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Pass normalized effort through — the Responses API uses the same vocabulary."""
    return {} if effort is None else {"reasoning": {"effort": effort}}


_OPENAI_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.JSON_MODE
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
    | Feature.CACHE_USAGE
)


_RATE_LIMIT_HEADERS = RateLimitHeaders(
    requests_remaining="x-ratelimit-remaining-requests",
    requests_reset="x-ratelimit-reset-requests",
    tokens_remaining="x-ratelimit-remaining-tokens",
    tokens_reset="x-ratelimit-reset-tokens",
    limit_requests="x-ratelimit-limit-requests",
    limit_tokens="x-ratelimit-limit-tokens",
)
"""OpenAI's rate-limit dialect. Resets are durations (``1s``, ``6m0s``), not instants.

Recorded in ``contracts/openai.md``. The project-scoped variants
(``x-ratelimit-*-project-tokens``) are deliberately not read: they describe a different
bucket than the one a single client's requests draw from.
"""

_STATIC_EMBEDDING_CAPABILITIES = {
    # Verified against developers.openai.com/api/reference (embeddings/create) on
    # 2026-08-12: at most 2,048 inputs per request, 8,192 tokens per input, and no
    # input-intent concept anywhere in the request schema (hence the declared-empty
    # intents). Default dimensions are not stated in the reference, so they stay None.
    model: EmbeddingCapabilities(
        max_batch_inputs=2_048, max_input_tokens=8_192, input_intents=()
    )
    for model in ("text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002")
}


descriptor = ProviderDescriptor(
    id="openai",
    display_name="OpenAI",
    factory=OpenAIAdapter,
    locality="hosted",
    default_base_url=_DEFAULT_BASE_URL,
    requires_base_url=False,
    operations=frozenset({"generation", "embedding"}),
    static_embedding_capabilities=_STATIC_EMBEDDING_CAPABILITIES,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=True,
                help_text="Accepts a literal, env://VAR, or credential://system/name.",
                placeholder="env://OPENAI_API_KEY or a literal key",
                env_var="OPENAI_API_KEY",
            ),
            SetupField(
                key="base_url",
                label="Base URL",
                kind="endpoint",
                required=False,
                advanced=True,
                default_value=_DEFAULT_BASE_URL,
                help_text=f"Defaults to {_DEFAULT_BASE_URL}.",
            ),
        ),
        model_selection="discover-or-manual",
    ),
    reasoning_translator=_translate_reasoning,
    default_capabilities=ModelCapabilities(features=Sourced(_OPENAI_FEATURES, "default")),
    # Prompt caching is automatic on a stable prefix — there is nothing to mark, so the
    # core's only duty is to leave the prefix undisturbed. Recorded in contracts/openai.md.
    cache_mechanism="implicit",
    rate_limit_headers=_RATE_LIMIT_HEADERS,
)
"""Descriptor for the OpenAI provider."""
