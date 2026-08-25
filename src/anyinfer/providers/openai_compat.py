"""The OpenAI-compatible chat-completions dialect.

Base adapter for every endpoint speaking ``POST /chat/completions``: OpenAI-compatible
servers, OpenRouter, Azure AI Foundry, and supervised llama-server. Wire details are
transcribed from `contracts/openai-compat.md`; subclasses override the small number of
hooks where dialects diverge (output-token parameter name, extra headers, model listing).

This is one dialect among several, not the internal representation.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Mapping, Sequence
from contextlib import aclosing
from typing import Any, ClassVar

import httpx2

from ..errors import Phase, ProviderError, StreamProtocolError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Feature, Health, ModelCapabilities, Sourced
from ..types.events import TextDelta, ToolCallDelta, UsageUpdate
from ..types.messages import (
    AudioPart,
    DocumentPart,
    ImagePart,
    Message,
    Text,
    ToolCall,
    ToolResult,
)
from ..types.requests import Sampling, ToolSpec
from ..types.results import FinishReason, TokenLogprob, Usage
from ._logprobs import parse_openai_logprobs
from ._multimodal import base64_data, data_url, media_subtype
from .base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest, _encode_function_tool
from .http import build_client, classify_status, map_transport_error, read_error_detail, read_int
from .sse import iter_sse

__all__ = ["OpenAICompatAdapter", "descriptor"]

_FINISH_REASONS: Mapping[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "content_filter": "content_filter",
}


class OpenAICompatAdapter:
    """Adapter for OpenAI-compatible chat-completions endpoints."""

    output_tokens_field: ClassVar[str] = "max_tokens"
    """Overridden by dialects that renamed it (Azure uses ``max_completion_tokens``)."""

    default_chat_path: ClassVar[str] = "/chat/completions"
    default_models_path: ClassVar[str] = "/models"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        # The registered id, so a preset built on this adapter (groq, together, …)
        # attributes errors and events to itself rather than to "openai-compat".
        self.provider_id = config.provider_id
        # Instance attributes rather than class constants: subclasses (Azure) append
        # query parameters per deployment, which must not leak across instances.
        self.chat_path = self.default_chat_path
        self.models_path = self.default_models_path
        self._client = build_client(
            base_url=(config.base_url or "").rstrip("/"),
            headers=self._build_headers(config),
            timeout_s=config.timeout_s,
            transport=config.transport,
            proxy=config.proxy,
            verify=config.verify,
            client_cert=config.client_cert,
        )

    def _build_headers(self, config: ProviderConfig) -> dict[str, str]:
        """Assemble request headers. Subclasses add dialect-specific ones."""
        headers = {"content-type": "application/json"}
        if config.api_key:
            headers["authorization"] = f"Bearer {config.api_key}"
        headers.update({k.lower(): v for k, v in config.headers.items()})
        return headers

    def _classify(
        self,
        status: int,
        detail: str,
        headers: Mapping[str, str],
        phase: Phase = "generate",
    ) -> ProviderError:
        """Error-classification hook. Subclasses map dialect-specific statuses."""
        return classify_status(
            status, provider=self.provider_id, detail=detail, headers=headers, phase=phase
        )

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List models from ``GET /models``."""
        try:
            response = await self._client.get(self.models_path)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="discover") from exc
        if response.status_code >= 400:
            raise self._classify(
                response.status_code,
                read_error_detail(response.content),
                response.headers,
                phase="discover",
            )
        payload = response.json()
        entries = payload.get("data") if isinstance(payload, Mapping) else payload
        if not isinstance(entries, list):
            return []
        return [self._parse_model(e) for e in entries if isinstance(e, Mapping)]

    def _parse_model(self, entry: Mapping[str, Any]) -> DiscoveredModel:
        """Build a discovered model. Subclasses enrich this from richer listings."""
        return DiscoveredModel(id=str(entry.get("id", "")))

    async def health(self) -> Health:
        """Probe readiness by listing models — the cheapest universally-available call."""
        try:
            response = await self._client.get(self.models_path)
        except httpx2.HTTPError as exc:
            return Health(ok=False, detail=str(exc)[:200])
        if response.status_code >= 400:
            return Health(ok=False, detail=f"HTTP {response.status_code}")
        return Health(ok=True)

    # ---- generation ------------------------------------------------------------------

    async def generate(self, req: WireRequest) -> AsyncGenerator[AdapterEvent, None]:
        """Run one generation, yielding normalized events."""
        payload = self.build_payload(req)
        if req.stream:
            # `aclosing`: an early close of this generator (a consumer breaking out of a
            # stream) must also close `_generate_streaming`'s, or its open connection and
            # SSE parser are left to finalize during GC instead of closing deterministically.
            async with aclosing(self._generate_streaming(req, payload)) as events:
                async for event in events:
                    yield event
        else:
            async for event in self._generate_buffered(req, payload):
                yield event

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Translate a `WireRequest` into a chat-completions request body."""
        payload: dict[str, Any] = {
            "model": req.model,
            "messages": [self._encode_message(m) for m in req.messages],
        }
        self._apply_sampling(payload, req.sampling)

        if req.stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}

        if req.tools:
            payload["tools"] = [self._encode_tool(t) for t in req.tools]
            payload["tool_choice"] = self._encode_tool_choice(req.tool_choice)

        response_format = self._encode_response_format(req)
        if response_format is not None:
            payload["response_format"] = response_format

        if req.logprobs is not None:
            # Two fields, not one: the dialect's `logprobs` is the boolean that turns the
            # feature on, and `top_logprobs` is how many alternatives to include. Sending
            # `top_logprobs: 0` without the boolean returns nothing at all.
            payload["logprobs"] = True
            if req.logprobs > 0:
                payload["top_logprobs"] = req.logprobs

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
            payload[self.output_tokens_field] = sampling.max_output_tokens
        if sampling.stop:
            payload["stop"] = list(sampling.stop)
        if sampling.seed is not None:
            payload["seed"] = sampling.seed
        if sampling.presence_penalty is not None:
            payload["presence_penalty"] = sampling.presence_penalty
        if sampling.frequency_penalty is not None:
            payload["frequency_penalty"] = sampling.frequency_penalty

    def _encode_response_format(self, req: WireRequest) -> dict[str, Any] | None:
        """Encode the structured-output mechanism, when it has a wire form.

        ``prompt`` has none — the core already injected the instruction into the system
        message, so this returns ``None`` for it.
        """
        if req.mechanism == "json_schema" and req.wire_schema is not None:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": req.schema_name or "response",
                    "schema": dict(req.wire_schema),
                    "strict": False,
                },
            }
        if req.mechanism == "json_mode":
            return {"type": "json_object"}
        return None

    def _encode_message(self, message: Message) -> dict[str, Any]:
        """Encode one message, splitting tool results into their own wire shape."""
        tool_results = [p for p in message.content if isinstance(p, ToolResult)]
        if tool_results:
            result = tool_results[0]
            return {
                "role": "tool",
                "tool_call_id": result.call_id,
                "content": result.content,
            }

        text = "".join(p.text for p in message.content if isinstance(p, Text))
        modal = any(isinstance(p, ImagePart | DocumentPart | AudioPart) for p in message.content)
        content: str | list[dict[str, Any]] | None = text
        if modal:
            content = []
            for part in message.content:
                if isinstance(part, Text):
                    content.append({"type": "text", "text": part.text})
                elif isinstance(part, ImagePart):
                    image: dict[str, Any] = {
                        "url": part.url or data_url(part.media_type, part.data or b"")
                    }
                    if part.detail is not None:
                        image["detail"] = part.detail
                    content.append({"type": "image_url", "image_url": image})
                elif isinstance(part, DocumentPart):
                    file: dict[str, Any] = {}
                    if part.data is not None:
                        file["file_data"] = data_url(part.media_type, part.data)
                    else:
                        file["file_url"] = part.url
                    if part.filename is not None:
                        file["filename"] = part.filename
                    content.append({"type": "file", "file": file})
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
        encoded: dict[str, Any] = {"role": message.role, "content": content}
        calls = [p for p in message.content if isinstance(p, ToolCall)]
        if calls:
            encoded["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(dict(c.arguments))},
                }
                for c in calls
            ]
            if not content:
                encoded["content"] = None
        return encoded

    def _encode_tool(self, tool: ToolSpec) -> dict[str, Any]:
        return _encode_function_tool(tool)

    def _encode_tool_choice(self, choice: str) -> Any:
        if choice in ("auto", "none", "required"):
            return choice
        return {"type": "function", "function": {"name": choice}}

    # ---- streaming path --------------------------------------------------------------

    async def _generate_streaming(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncGenerator[AdapterEvent, None]:
        """Stream via SSE, degrading to the buffered path if the server ignores ``stream``."""
        try:
            async with self._client.stream(
                "POST",
                self.chat_path,
                json=payload,
                timeout=req.timeout_s,
                headers={"accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise self._classify(
                        response.status_code, read_error_detail(body), response.headers
                    )

                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    # The server accepted the request but answered with a buffered body.
                    # That body is a perfectly good completion, so use it rather than
                    # paying for a second round trip.
                    body = await response.aread()
                    for event in self._events_from_completion(self._parse_json(body), req):
                        yield event
                    return

                state = _StreamState()
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

    def _events_from_chunk(self, chunk: Any, state: _StreamState) -> Iterable[AdapterEvent]:
        """Translate one SSE chunk into zero or more adapter events."""
        if not isinstance(chunk, Mapping):
            return

        usage = chunk.get("usage")
        if isinstance(usage, Mapping):
            parsed = self._parse_usage(usage)
            state.usage = state.usage.merge(parsed) if state.usage else parsed
            yield UsageUpdate(parsed)

        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        choice = choices[0]
        if not isinstance(choice, Mapping):
            return

        finish = choice.get("finish_reason")
        if isinstance(finish, str):
            state.finish_reason = _FINISH_REASONS.get(finish, "other")

        # Streamed log-probabilities arrive per chunk, covering only that chunk's tokens,
        # so they accumulate rather than replace.
        state.logprobs.extend(parse_openai_logprobs(choice.get("logprobs")))

        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            return

        content = delta.get("content")
        if isinstance(content, str) and content:
            yield TextDelta(content)

        yield from self._iter_tool_call_deltas(delta)

    def _iter_tool_call_deltas(self, container: Mapping[str, Any]) -> Iterable[ToolCallDelta]:
        """Read ``tool_calls`` from a streaming delta or a buffered message.

        Buffered messages carry no per-call ``index``, so enumeration order stands in.
        """
        calls = container.get("tool_calls")
        if not isinstance(calls, list):
            return
        for position, call in enumerate(calls):
            if not isinstance(call, Mapping):
                continue
            index = call.get("index")
            function = call.get("function")
            name = None
            arguments = ""
            if isinstance(function, Mapping):
                raw_name = function.get("name")
                name = raw_name if isinstance(raw_name, str) else None
                raw_args = function.get("arguments")
                arguments = raw_args if isinstance(raw_args, str) else ""
            call_id = call.get("id")
            yield ToolCallDelta(
                index=index if isinstance(index, int) else position,
                call_id=call_id if isinstance(call_id, str) else None,
                name=name,
                arguments_fragment=arguments,
            )

    # ---- buffered path ---------------------------------------------------------------

    async def _generate_buffered(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncIterator[AdapterEvent]:
        """Issue a non-streaming request and emit its result as a one-delta stream."""
        body = dict(payload)
        body.pop("stream", None)
        body.pop("stream_options", None)
        try:
            response = await self._client.post(self.chat_path, json=body, timeout=req.timeout_s)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id) from exc

        if response.status_code >= 400:
            raise self._classify(
                response.status_code, read_error_detail(response.content), response.headers
            )
        if len(response.content) > req.max_response_bytes:
            raise StreamProtocolError(
                f"response exceeded max_response_bytes ({req.max_response_bytes} bytes)",
                provider=self.provider_id,
            )
        for event in self._events_from_completion(self._parse_json(response.content), req):
            yield event

    def _parse_json(self, body: bytes) -> Any:
        """Decode a completion body, typing a non-JSON 200 as a protocol failure.

        A raw ``JSONDecodeError`` would escape the router's error handling entirely —
        no attempt record, no retry, no failure telemetry.
        """
        try:
            return json.loads(body)
        except ValueError as exc:
            raise StreamProtocolError(
                f"provider returned a non-JSON completion body: {exc}",
                provider=self.provider_id,
            ) from exc

    def _events_from_completion(self, payload: Any, req: WireRequest) -> Iterable[AdapterEvent]:
        """Translate a buffered chat-completion body into a synthetic event stream."""
        if not isinstance(payload, Mapping):
            raise StreamProtocolError(
                "provider returned a non-object completion body",
                provider=self.provider_id,
            )

        choices = payload.get("choices")
        message: Mapping[str, Any] = {}
        finish_reason: FinishReason = "stop"
        logprobs: tuple[TokenLogprob, ...] = ()
        if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
            choice = choices[0]
            raw_message = choice.get("message")
            if isinstance(raw_message, Mapping):
                message = raw_message
            raw_finish = choice.get("finish_reason")
            if isinstance(raw_finish, str):
                finish_reason = _FINISH_REASONS.get(raw_finish, "other")
            logprobs = parse_openai_logprobs(choice.get("logprobs"))

        content = message.get("content")
        if isinstance(content, str) and content:
            yield TextDelta(content)

        yield from self._iter_tool_call_deltas(message)

        usage_payload = payload.get("usage")
        usage = self._parse_usage(usage_payload) if isinstance(usage_payload, Mapping) else None
        if usage is not None:
            yield UsageUpdate(usage)
        yield AdapterFinal(
            finish_reason=finish_reason, usage=usage, raw=payload, logprobs=logprobs
        )

    def _parse_usage(self, usage: Mapping[str, Any]) -> Usage:
        """Read the dialect's usage block."""
        details = usage.get("prompt_tokens_details")
        cache_read = read_int(details, "cached_tokens") if isinstance(details, Mapping) else None
        completion_details = usage.get("completion_tokens_details")
        reasoning = (
            read_int(completion_details, "reasoning_tokens")
            if isinstance(completion_details, Mapping)
            else None
        )
        return Usage(
            input_tokens=read_int(usage, "prompt_tokens"),
            output_tokens=read_int(usage, "completion_tokens"),
            total_tokens=read_int(usage, "total_tokens"),
            cache_read_tokens=cache_read,
            reasoning_tokens=reasoning,
        ).normalized()

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


class _StreamState:
    """Accumulates cross-chunk streaming state so the final event is complete."""

    __slots__ = ("finish_reason", "logprobs", "usage")

    def __init__(self) -> None:
        self.finish_reason: FinishReason = "stop"
        self.usage: Usage | None = None
        self.logprobs: list[TokenLogprob] = []

    def finalize(self) -> AdapterFinal:
        return AdapterFinal(
            finish_reason=self.finish_reason,
            usage=self.usage,
            logprobs=tuple(self.logprobs),
        )


descriptor = ProviderDescriptor(
    id="openai-compat",
    display_name="OpenAI-compatible endpoint",
    aliases=("openai-compatible", "oai-compat"),
    factory=OpenAICompatAdapter,
    locality="hosted",
    default_base_url=None,
    requires_base_url=True,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="base_url",
                label="Base URL",
                kind="endpoint",
                required=True,
                help_text="Root of the API, up to and including any version segment.",
                placeholder="http://localhost:8080/v1",
            ),
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=False,
                help_text="Optional for keyless local servers.",
                placeholder="env://VARIABLE_NAME or a literal key",
            ),
        ),
        model_selection="discover-or-manual",
    ),
    default_capabilities=ModelCapabilities(
        features=Sourced(Feature.STREAMING | Feature.TOOLS | Feature.SYSTEM_PROMPT, "default"),
    ),
)
"""Descriptor for the generic OpenAI-compatible provider."""
