"""Cohere's native v2 Chat API (`contracts/cohere.md`).

Cohere publishes an OpenAI compatibility endpoint, but the native v2 API is where the
things worth using Cohere for actually live: grounded generation with document citations,
its own thinking channel, and a usage block that separates billed units from raw tokens.
This adapter speaks v2.

Four deltas from the OpenAI shape:

- **Enumerations are uppercase.** ``finish_reason`` is ``COMPLETE``/``MAX_TOKENS``/
  ``TOOL_CALL``, and ``tool_choice`` takes ``REQUIRED``/``NONE`` — lowercase values are
  rejected.
- **Streaming is typed events**, not delta chunks: ``content-delta``, ``tool-call-delta``,
  ``message-end``, each with its own shape.
- **Usage arrives only in ``message-end``**, so a stream closed early reports nothing.
- **``stream`` is required**, not optional, on every request.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from typing import Any

import httpx2

from ..errors import ProviderError, StreamProtocolError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Feature, Health, ModelCapabilities, Sourced
from ..types.events import ReasoningDelta, TextDelta, ToolCallDelta, UsageUpdate
from ..types.messages import Message, Text, ToolCall, ToolResult
from ..types.requests import ReasoningEffort, Sampling, ToolSpec
from ..types.results import FinishReason, Usage
from ._multimodal import has_multimodal, unsupported
from .base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest, _encode_function_tool
from .http import build_client, classify_status, map_transport_error, read_error_detail
from .sse import iter_sse

__all__ = ["CohereAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://api.cohere.com"

_FINISH_REASONS: Mapping[str, FinishReason] = {
    "COMPLETE": "stop",
    "STOP_SEQUENCE": "stop",
    "MAX_TOKENS": "length",
    "TOOL_CALL": "tool_calls",
    "ERROR": "other",
    "TIMEOUT": "other",
}
"""Cohere's uppercase finish reasons, normalized."""

_THINKING_BUDGETS: Mapping[ReasoningEffort, int] = {
    "low": 1024,
    "medium": 4096,
    "high": 16384,
}


class CohereAdapter:
    """Adapter for Cohere's v2 Chat API."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self.provider_id = config.provider_id
        headers = {"content-type": "application/json", "accept": "application/json"}
        if config.api_key:
            headers["authorization"] = f"Bearer {config.api_key}"
        headers.update({k.lower(): v for k, v in config.headers.items()})
        self._client = build_client(
            base_url=(config.base_url or _DEFAULT_BASE_URL).rstrip("/"),
            headers=headers,
            timeout_s=config.timeout_s,
            transport=config.transport,
        )

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List chat-capable models, following the listing's page tokens.

        The listing reports real context lengths, so windows arrive with ``discovered``
        provenance.
        """
        models: list[DiscoveredModel] = []
        params: dict[str, Any] = {"page_size": 1000, "endpoint": "chat"}

        while True:
            try:
                response = await self._client.get("/v1/models", params=params)
            except httpx2.HTTPError as exc:
                raise map_transport_error(
                    exc, provider=self.provider_id, phase="discover"
                ) from exc
            if response.status_code >= 400:
                raise classify_status(
                    response.status_code,
                    provider=self.provider_id,
                    detail=read_error_detail(response.content),
                    headers=response.headers,
                    phase="discover",
                )

            payload = response.json()
            entries = payload.get("models") if isinstance(payload, Mapping) else None
            if not isinstance(entries, list):
                break
            models.extend(_parse_model(e) for e in entries if isinstance(e, Mapping))

            token = payload.get("next_page_token")
            if not isinstance(token, str) or not token:
                break
            params["page_token"] = token

        return models

    async def health(self) -> Health:
        """Probe readiness with a bounded model listing."""
        try:
            response = await self._client.get("/v1/models", params={"page_size": 1})
        except httpx2.HTTPError as exc:
            return Health(ok=False, detail=str(exc)[:200])
        if response.status_code >= 400:
            return Health(ok=False, detail=f"HTTP {response.status_code}")
        return Health(ok=True)

    # ---- generation ------------------------------------------------------------------

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one generation against ``POST /v2/chat``."""
        payload = self.build_payload(req)
        if req.stream:
            async for event in self._generate_streaming(req, payload):
                yield event
        else:
            async for event in self._generate_buffered(req, payload):
                yield event

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Translate a wire request into a v2 chat body."""
        payload: dict[str, Any] = {
            "model": req.model,
            "messages": [self._encode_message(m) for m in req.messages],
            # Not optional in this API: the field is required on every request.
            "stream": bool(req.stream),
        }
        self._apply_sampling(payload, req.sampling)

        if req.tools:
            payload["tools"] = [self._encode_tool(t) for t in req.tools]
            choice = _tool_choice(req.tool_choice)
            if choice is not None:
                payload["tool_choice"] = choice

        if req.mechanism in ("json_schema", "grammar") and req.wire_schema is not None:
            payload["response_format"] = {
                "type": "json_object",
                "json_schema": dict(req.wire_schema),
            }
        elif req.mechanism == "json_mode":
            payload["response_format"] = {"type": "json_object"}

        payload.update(req.reasoning_wire)
        payload.update(req.extra_options)
        return payload

    def _apply_sampling(self, payload: dict[str, Any], sampling: Sampling) -> None:
        """Add only the sampling fields the caller set, under Cohere's names."""
        if sampling.temperature is not None:
            payload["temperature"] = sampling.temperature
        if sampling.top_p is not None:
            # Cohere spells nucleus sampling `p`, and top-k `k`.
            payload["p"] = sampling.top_p
        if sampling.max_output_tokens is not None:
            payload["max_tokens"] = sampling.max_output_tokens
        if sampling.stop:
            payload["stop_sequences"] = list(sampling.stop)

    def _encode_message(self, message: Message) -> dict[str, Any]:
        """Encode one message, splitting tool results into their own role."""
        if has_multimodal((message,)):
            raise unsupported(self.provider_id, "multimodal")
        results = [p for p in message.content if isinstance(p, ToolResult)]
        if results:
            result = results[0]
            return {
                "role": "tool",
                "tool_call_id": result.call_id,
                "content": result.content,
            }

        text = "".join(p.text for p in message.content if isinstance(p, Text))
        calls = [p for p in message.content if isinstance(p, ToolCall)]
        if calls:
            encoded: dict[str, Any] = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(dict(call.arguments)),
                        },
                    }
                    for call in calls
                ],
            }
            if text:
                encoded["content"] = text
            return encoded

        return {"role": message.role, "content": text}

    def _encode_tool(self, tool: ToolSpec) -> dict[str, Any]:
        return _encode_function_tool(tool)

    # ---- buffered path ---------------------------------------------------------------

    async def _generate_buffered(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncIterator[AdapterEvent]:
        """Issue a non-streaming chat request and emit it as one stream."""
        try:
            response = await self._client.post("/v2/chat", json=payload, timeout=req.timeout_s)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id) from exc

        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                headers=response.headers,
            )
        if len(response.content) > req.max_response_bytes:
            raise StreamProtocolError(
                f"response exceeded max_response_bytes ({req.max_response_bytes} bytes)",
                provider=self.provider_id,
            )

        try:
            parsed = json.loads(response.content)
        except ValueError as exc:
            raise StreamProtocolError(
                f"cohere returned a non-JSON body: {exc}", provider=self.provider_id
            ) from exc

        for event in self._events_from_response(parsed):
            yield event

    def _events_from_response(self, payload: Any) -> Iterable[AdapterEvent]:
        """Translate a buffered v2 chat response into a synthetic event stream."""
        if not isinstance(payload, Mapping):
            raise StreamProtocolError(
                "cohere returned a non-object response", provider=self.provider_id
            )

        message = payload.get("message")
        if isinstance(message, Mapping):
            blocks = message.get("content")
            if isinstance(blocks, list):
                for block in blocks:
                    if not isinstance(block, Mapping):
                        continue
                    kind = block.get("type")
                    text = block.get("text") or block.get("thinking")
                    if not isinstance(text, str) or not text:
                        continue
                    if kind == "thinking":
                        yield ReasoningDelta(text)
                    else:
                        yield TextDelta(text)

            for index, call in enumerate(message.get("tool_calls") or []):
                if not isinstance(call, Mapping):
                    continue
                function = call.get("function")
                name = function.get("name") if isinstance(function, Mapping) else None
                arguments = function.get("arguments") if isinstance(function, Mapping) else ""
                yield ToolCallDelta(
                    index=index,
                    call_id=str(call.get("id", "")) or None,
                    name=str(name) if isinstance(name, str) else None,
                    arguments_fragment=arguments if isinstance(arguments, str) else "",
                )

        usage = _parse_usage(payload.get("usage"))
        if usage is not None:
            yield UsageUpdate(usage)

        raw_reason = payload.get("finish_reason")
        finish: FinishReason = "stop"
        if isinstance(raw_reason, str):
            finish = _FINISH_REASONS.get(raw_reason, "other")
        yield AdapterFinal(finish_reason=finish, usage=usage, raw=payload)

    # ---- streaming path --------------------------------------------------------------

    async def _generate_streaming(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncIterator[AdapterEvent]:
        """Stream ``POST /v2/chat``, translating Cohere's typed SSE events."""
        try:
            async with self._client.stream(
                "POST",
                "/v2/chat",
                json=payload,
                timeout=req.timeout_s,
                headers={"accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    detail = read_error_detail(await response.aread())
                    raise classify_status(
                        response.status_code,
                        provider=self.provider_id,
                        detail=detail,
                        headers=response.headers,
                    )

                state = _StreamState()
                async for chunk in iter_sse(
                    response.aiter_bytes(),
                    max_bytes=req.max_response_bytes,
                    provider=self.provider_id,
                ):
                    for event in self._events_from_chunk(chunk, state):
                        yield event
                yield state.finalize()
        except (ProviderError, StreamProtocolError):
            raise
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="stream") from exc

    def _events_from_chunk(self, chunk: Any, state: _StreamState) -> Iterable[AdapterEvent]:
        """Translate one typed stream event into adapter events."""
        if not isinstance(chunk, Mapping):
            return
        kind = chunk.get("type")
        delta = chunk.get("delta")
        index = chunk.get("index")

        if kind == "content-delta":
            content = _nested(delta, "message", "content")
            if isinstance(content, Mapping):
                text = content.get("text")
                if isinstance(text, str) and text:
                    yield TextDelta(text)
                thinking = content.get("thinking")
                if isinstance(thinking, str) and thinking:
                    yield ReasoningDelta(thinking)
            return

        if kind == "tool-call-start":
            calls = _nested(delta, "message", "tool_calls")
            if isinstance(calls, Mapping) and isinstance(index, int):
                function = calls.get("function")
                name = function.get("name") if isinstance(function, Mapping) else None
                yield ToolCallDelta(
                    index=state.tool_slot(index),
                    call_id=str(calls.get("id", "")) or None,
                    name=str(name) if isinstance(name, str) else None,
                    arguments_fragment="",
                )
            return

        if kind == "tool-call-delta":
            calls = _nested(delta, "message", "tool_calls")
            if isinstance(calls, Mapping) and isinstance(index, int):
                function = calls.get("function")
                fragment = function.get("arguments") if isinstance(function, Mapping) else None
                if isinstance(fragment, str) and fragment:
                    yield ToolCallDelta(
                        index=state.tool_slot(index),
                        call_id=None,
                        name=None,
                        arguments_fragment=fragment,
                    )
            return

        if kind == "message-end" and isinstance(delta, Mapping):
            reason = delta.get("finish_reason")
            if isinstance(reason, str):
                state.finish_reason = _FINISH_REASONS.get(reason, "other")
            # Usage lives only here; a stream closed earlier reports nothing.
            usage = _parse_usage(delta.get("usage"))
            if usage is not None:
                state.usage = state.usage.merge(usage)
                yield UsageUpdate(usage)

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


class _StreamState:
    """Accumulates cross-event streaming state."""

    __slots__ = ("finish_reason", "tool_slots", "usage")

    def __init__(self) -> None:
        self.finish_reason: FinishReason = "stop"
        self.usage = Usage()
        self.tool_slots: dict[int, int] = {}

    def tool_slot(self, stream_index: int) -> int:
        """Map a stream index onto a dense tool-call slot."""
        slot = self.tool_slots.get(stream_index)
        if slot is None:
            slot = len(self.tool_slots)
            self.tool_slots[stream_index] = slot
        return slot

    def finalize(self) -> AdapterFinal:
        """Build the terminal adapter event."""
        usage = self.usage.normalized()
        return AdapterFinal(
            finish_reason=self.finish_reason,
            usage=usage if usage != Usage() else None,
        )


def _nested(container: Any, *keys: str) -> Any:
    """Walk a chain of mapping keys, returning ``None`` at the first miss."""
    current = container
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _tool_choice(choice: str) -> str | None:
    """Translate normalized tool choice into Cohere's uppercase enum.

    Cohere accepts only ``REQUIRED`` and ``NONE``; there is no way to name a specific
    tool, and no explicit ``auto`` — omitting the field *is* auto.
    """
    if choice == "required":
        return "REQUIRED"
    if choice == "none":
        return "NONE"
    return None


def _parse_usage(payload: Any) -> Usage | None:
    """Read Cohere's usage block.

    ``tokens`` is what was processed and ``billed_units`` is what is charged; the
    normalized counts follow ``tokens``, since that is what a context window measures.
    """
    if not isinstance(payload, Mapping):
        return None
    tokens = payload.get("tokens")
    source = tokens if isinstance(tokens, Mapping) else payload.get("billed_units")
    if not isinstance(source, Mapping):
        return None

    def field(container: Mapping[str, Any], name: str) -> int | None:
        value = container.get(name)
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return int(value) if isinstance(value, float) and value.is_integer() else None

    cached = payload.get("cached_tokens")
    usage = Usage(
        input_tokens=field(source, "input_tokens"),
        output_tokens=field(source, "output_tokens"),
        cache_read_tokens=cached
        if isinstance(cached, int) and not isinstance(cached, bool)
        else None,
    )
    return usage if usage != Usage() else None


def _parse_model(entry: Mapping[str, Any]) -> DiscoveredModel:
    """Read one model-listing entry."""
    features = Feature.STREAMING | Feature.SYSTEM_PROMPT | Feature.JSON_SCHEMA | Feature.JSON_MODE
    capabilities = entry.get("features")
    if isinstance(capabilities, list):
        if "tools" in capabilities:
            features |= Feature.TOOLS
        if "thinking" in capabilities or "reasoning" in capabilities:
            features |= Feature.REASONING
    else:
        features |= Feature.TOOLS

    window = entry.get("context_length")
    context = (
        Sourced(int(window), "discovered")
        if isinstance(window, int | float) and not isinstance(window, bool) and window > 0
        else None
    )
    return DiscoveredModel(
        id=str(entry.get("name", "")),
        capabilities=ModelCapabilities(
            context_window=context, features=Sourced(features, "discovered")
        ),
    )


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto Cohere's thinking object.

    Cohere budgets thinking in tokens rather than naming levels, so each level maps to a
    budget; ``minimal`` disables thinking outright.
    """
    if effort is None:
        return {}
    if effort == "minimal":
        return {"thinking": {"type": "disabled"}}
    return {"thinking": {"type": "enabled", "token_budget": _THINKING_BUDGETS[effort]}}


_COHERE_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.JSON_MODE
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
)


descriptor = ProviderDescriptor(
    id="cohere",
    display_name="Cohere",
    factory=CohereAdapter,
    locality="hosted",
    default_base_url=_DEFAULT_BASE_URL,
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=True,
                help_text=("Conventionally env://CO_API_KEY. Accepts env:// and credential://."),
                placeholder="env://CO_API_KEY or a literal key",
                env_var="CO_API_KEY",
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
    default_capabilities=ModelCapabilities(features=Sourced(_COHERE_FEATURES, "default")),
)
"""Descriptor for the Cohere provider."""
