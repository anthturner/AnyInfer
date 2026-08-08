"""Anthropic's Messages API (`contracts/anthropic.md`).

Uses the common HTTP transport rather than an official SDK. Three ways this dialect differs
from the OpenAI shape, each handled below:

- **System prompts are a top-level field**, not a message with ``role: "system"``.
- **``max_tokens`` is required**, so a request that leaves it unset gets a documented
  default rather than a 400.
- **Typed SSE events**, not delta-shaped chunks: content arrives as indexed content blocks
  with ``content_block_delta`` events, and thinking is its own delta type.

The TTFT rule is deliberate: a ``thinking_delta`` *does* stop the first-token clock (the
model has started working and the user sees activity) but is excluded from the answer text.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from typing import Any

import httpx2

from ..errors import ProviderError, StreamProtocolError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    ModelCapabilities,
    Sourced,
)
from ..types.events import ReasoningDelta, TextDelta, ToolCallDelta, UsageUpdate
from ..types.messages import Message, Text, ToolCall, ToolResult
from ..types.requests import ReasoningEffort, Sampling, ToolSpec
from ..types.results import FinishReason, Usage
from .base import AdapterEvent, AdapterFinal, ProviderConfig, WireRequest
from .http import build_client, classify_status, map_transport_error, read_error_detail
from .sse import iter_sse

__all__ = ["ANTHROPIC_VERSION", "AnthropicAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
"""Pinned API version header, per the contract snapshot."""

_OAUTH_BETA = "oauth-2025-04-20"
"""Beta flag required alongside a bearer token.

``/v1/messages`` rejects an OAuth token without it, so it is sent unconditionally on the
OAuth path rather than left to the caller to remember.
"""

_DEFAULT_MAX_TOKENS = 4096
"""Used when the caller sets none, because the API rejects a request without it."""

_STOP_REASONS: Mapping[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "refusal": "content_filter",
}


class AnthropicAdapter:
    """Adapter for the Anthropic Messages API.

    Also the adapter for every *Anthropic-compatible* endpoint. Several providers
    (Moonshot, Z.ai, DeepSeek, xAI, MiniMax, SambaNova, and others) expose a Messages
    endpoint beside their OpenAI-compatible one; pointing ``base_url`` at it is all that
    is needed, because the dialect is the same.

    **Two credential shapes.** An Anthropic API key goes on ``x-api-key``; a claude.ai
    OAuth token (``ant auth print-credentials --access-token``) goes on ``Authorization:
    Bearer`` and additionally requires the provider's OAuth beta flag. They are not
    interchangeable spellings of one header, which is why the OAuth token is its own
    setup field rather than something sniffed out of the key's text.
    """

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        # The registered id, so an Anthropic-compatible endpoint registered under its
        # own provider id attributes errors to itself rather than to "anthropic".
        self.provider_id = config.provider_id
        headers = {
            "content-type": "application/json",
            "anthropic-version": config.api_version or ANTHROPIC_VERSION,
        }
        oauth_token = _option_str(config.options, "oauth_token")
        if oauth_token:
            headers["authorization"] = f"Bearer {oauth_token}"
            headers["anthropic-beta"] = _OAUTH_BETA
        elif config.api_key:
            headers["x-api-key"] = config.api_key
        headers.update({k.lower(): v for k, v in config.headers.items()})
        self._client = build_client(
            base_url=(config.base_url or _DEFAULT_BASE_URL).rstrip("/"),
            headers=headers,
            timeout_s=config.timeout_s,
            transport=config.transport,
        )

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List models, following the cursor pagination the API uses."""
        models: list[DiscoveredModel] = []
        params: dict[str, Any] = {"limit": 100}

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
            entries = payload.get("data") if isinstance(payload, Mapping) else None
            if not isinstance(entries, list):
                break
            for entry in entries:
                if isinstance(entry, Mapping) and entry.get("id"):
                    models.append(
                        DiscoveredModel(
                            id=str(entry["id"]),
                            capabilities=ModelCapabilities(
                                features=Sourced(_ANTHROPIC_FEATURES, "discovered")
                            ),
                        )
                    )

            if not payload.get("has_more") or not payload.get("last_id"):
                break
            params["after_id"] = payload["last_id"]

        return models

    async def health(self) -> Health:
        """Probe readiness with a bounded model listing."""
        try:
            response = await self._client.get("/v1/models", params={"limit": 1})
        except httpx2.HTTPError as exc:
            return Health(ok=False, detail=str(exc)[:200])
        if response.status_code >= 400:
            return Health(ok=False, detail=f"HTTP {response.status_code}")
        return Health(ok=True)

    # ---- generation ------------------------------------------------------------------

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one generation against ``POST /v1/messages``."""
        payload = self.build_payload(req)
        try:
            async with self._client.stream(
                "POST",
                "/v1/messages",
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

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Translate a wire request into a Messages API body."""
        system_text, messages = _split_system(req.messages)

        payload: dict[str, Any] = {
            "model": req.model,
            "messages": [self._encode_message(m) for m in messages],
            "max_tokens": req.sampling.max_output_tokens or _DEFAULT_MAX_TOKENS,
            "stream": True,
        }
        if system_text:
            payload["system"] = system_text

        self._apply_sampling(payload, req.sampling)

        tools = [self._encode_tool(t) for t in req.tools]
        if req.mechanism in ("json_schema", "grammar") and req.wire_schema is not None:
            # Anthropic has no response-format field: a schema is emulated as a single
            # forced tool call, which the API *does* constrain (open question 7).
            tools.append(
                {
                    "name": req.schema_name or "respond",
                    "description": "Return the response in the required structure.",
                    "input_schema": dict(req.wire_schema),
                }
            )
            payload["tool_choice"] = {"type": "tool", "name": req.schema_name or "respond"}
        elif req.tools:
            payload["tool_choice"] = self._encode_tool_choice(req.tool_choice)

        if tools:
            payload["tools"] = tools

        payload.update(req.reasoning_wire)
        payload.update(req.extra_options)
        return payload

    def _apply_sampling(self, payload: dict[str, Any], sampling: Sampling) -> None:
        """Add only the sampling fields the caller actually set."""
        if sampling.temperature is not None:
            payload["temperature"] = sampling.temperature
        if sampling.top_p is not None:
            payload["top_p"] = sampling.top_p
        if sampling.stop:
            payload["stop_sequences"] = list(sampling.stop)

    def _encode_message(self, message: Message) -> dict[str, Any]:
        """Encode one message into Anthropic's content-block form."""
        blocks: list[dict[str, Any]] = []

        for part in message.content:
            if isinstance(part, Text):
                if part.text:
                    blocks.append({"type": "text", "text": part.text})
            elif isinstance(part, ToolCall):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": part.id,
                        "name": part.name,
                        "input": dict(part.arguments),
                    }
                )
            elif isinstance(part, ToolResult):
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": part.call_id,
                        "content": part.content,
                        **({"is_error": True} if part.is_error else {}),
                    }
                )

        # Tool results are carried on a *user* turn in this dialect, not a "tool" role.
        role = "user" if message.role in ("user", "tool") else "assistant"
        return {"role": role, "content": blocks or [{"type": "text", "text": ""}]}

    def _encode_tool(self, tool: ToolSpec) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": dict(tool.parameters),
        }

    def _encode_tool_choice(self, choice: str) -> dict[str, Any]:
        if choice == "auto":
            return {"type": "auto"}
        if choice == "none":
            return {"type": "none"}
        if choice == "required":
            return {"type": "any"}
        return {"type": "tool", "name": choice}

    def _events_from_chunk(self, chunk: Any, state: _StreamState) -> Iterable[AdapterEvent]:
        """Translate one typed SSE event into adapter events."""
        if not isinstance(chunk, Mapping):
            return
        kind = chunk.get("type")

        if kind == "message_start":
            message = chunk.get("message")
            if isinstance(message, Mapping):
                usage = _parse_usage(message.get("usage"))
                if usage is not None:
                    state.usage = state.usage.merge(usage)
                    yield UsageUpdate(usage)
            return

        if kind == "content_block_start":
            block = chunk.get("content_block")
            index = chunk.get("index")
            if (
                isinstance(block, Mapping)
                and isinstance(index, int)
                and block.get("type") == "tool_use"
            ):
                slot = state.tool_slot(index)
                yield ToolCallDelta(
                    index=slot,
                    call_id=str(block.get("id", "")) or None,
                    name=str(block.get("name", "")) or None,
                    arguments_fragment="",
                )
            return

        if kind == "content_block_delta":
            delta = chunk.get("delta")
            index = chunk.get("index")
            if not isinstance(delta, Mapping):
                return
            delta_type = delta.get("type")

            if delta_type == "text_delta":
                text = delta.get("text")
                if isinstance(text, str) and text:
                    yield TextDelta(text)
            elif delta_type == "thinking_delta":
                thinking = delta.get("thinking")
                if isinstance(thinking, str) and thinking:
                    yield ReasoningDelta(thinking)
            elif delta_type == "input_json_delta" and isinstance(index, int):
                fragment = delta.get("partial_json")
                if isinstance(fragment, str) and fragment:
                    yield ToolCallDelta(
                        index=state.tool_slot(index),
                        call_id=None,
                        name=None,
                        arguments_fragment=fragment,
                    )
            return

        if kind == "message_delta":
            delta = chunk.get("delta")
            if isinstance(delta, Mapping):
                reason = delta.get("stop_reason")
                if isinstance(reason, str):
                    state.finish_reason = _STOP_REASONS.get(reason, "other")
            usage = _parse_usage(chunk.get("usage"))
            if usage is not None:
                state.usage = state.usage.merge(usage)
                yield UsageUpdate(usage)
            return

        if kind == "error":
            error = chunk.get("error")
            message = ""
            if isinstance(error, Mapping):
                message = str(error.get("message", ""))
            raise ProviderError(
                message or "anthropic reported a stream error", provider=self.provider_id
            )

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


class _StreamState:
    """Tracks stop reason, usage, and the mapping from block index to tool slot."""

    __slots__ = ("finish_reason", "tool_slots", "usage")

    def __init__(self) -> None:
        self.finish_reason: FinishReason = "stop"
        self.usage = Usage()
        self.tool_slots: dict[int, int] = {}

    def tool_slot(self, block_index: int) -> int:
        """Map a content-block index onto a dense tool-call slot.

        Block indices count *all* blocks, text included, so a response with prose before a
        tool call would otherwise report a non-zero first tool index.
        """
        slot = self.tool_slots.get(block_index)
        if slot is None:
            slot = len(self.tool_slots)
            self.tool_slots[block_index] = slot
        return slot

    def finalize(self) -> AdapterFinal:
        """Build the terminal adapter event."""
        usage = self.usage.normalized()
        return AdapterFinal(
            finish_reason=self.finish_reason,
            usage=usage if usage != Usage() else None,
        )


def _option_str(options: Mapping[str, Any], key: str) -> str:
    """Read one option as a stripped string, treating anything else as absent."""
    value = options.get(key)
    return value.strip() if isinstance(value, str) else ""


def _split_system(messages: Sequence[Message]) -> tuple[str, list[Message]]:
    """Pull system messages out into the top-level ``system`` field."""
    system_parts: list[str] = []
    remaining: list[Message] = []
    for message in messages:
        if message.role == "system":
            text = "".join(p.text for p in message.content if isinstance(p, Text))
            if text:
                system_parts.append(text)
        else:
            remaining.append(message)
    return "\n\n".join(system_parts), remaining


def _parse_usage(payload: Any) -> Usage | None:
    """Read Anthropic's usage block, including its cache accounting."""
    if not isinstance(payload, Mapping):
        return None

    def field(name: str) -> int | None:
        value = payload.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    usage = Usage(
        input_tokens=field("input_tokens"),
        output_tokens=field("output_tokens"),
        cache_read_tokens=field("cache_read_input_tokens"),
        cache_write_tokens=field("cache_creation_input_tokens"),
    )
    return usage if usage != Usage() else None


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto extended thinking.

    Anthropic budgets thinking in *tokens* rather than naming effort levels, so each level
    maps to a budget. ``minimal`` disables thinking outright.
    """
    if effort is None:
        return {}
    if effort == "minimal":
        return {"thinking": {"type": "disabled"}}
    budgets = {"low": 1024, "medium": 4096, "high": 16384}
    return {"thinking": {"type": "enabled", "budget_tokens": budgets[effort]}}


_ANTHROPIC_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
    | Feature.CACHE_USAGE
)


descriptor = ProviderDescriptor(
    id="anthropic",
    display_name="Anthropic",
    aliases=("claude",),
    factory=AnthropicAdapter,
    locality="hosted",
    default_base_url=_DEFAULT_BASE_URL,
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="Anthropic API key",
                kind="secret",
                required=False,
                help_text=(
                    "A console.anthropic.com key, sent as the x-api-key header. Accepts "
                    "env:// and credential://."
                ),
                placeholder="env://ANTHROPIC_API_KEY or a literal key",
            ),
            SetupField(
                key="oauth_token",
                label="claude.ai OAuth token",
                kind="secret",
                required=False,
                help_text=(
                    "A subscription token from 'ant auth print-credentials "
                    "--access-token', sent as a bearer token. Use this instead of an API "
                    "key, not alongside one. Short-lived: it needs re-issuing when it "
                    "expires."
                ),
                placeholder="env://ANTHROPIC_OAUTH_TOKEN or sk-ant-oat01-…",
            ),
            SetupField(
                key="api_version",
                label="API version",
                kind="api-version",
                required=False,
                advanced=True,
                default_value=ANTHROPIC_VERSION,
                help_text=(
                    f"Leave empty unless pinning a version. Defaults to {ANTHROPIC_VERSION}."
                ),
                placeholder=ANTHROPIC_VERSION,
            ),
        ),
        model_selection="discover-or-manual",
        any_of=(("api_key", "oauth_token"),),
        requirement_note=(
            "Supply either an Anthropic API key or a claude.ai OAuth token. "
            "If both are set, the OAuth token wins."
        ),
    ),
    reasoning_translator=_translate_reasoning,
    default_capabilities=ModelCapabilities(features=Sourced(_ANTHROPIC_FEATURES, "default")),
)
"""Descriptor for the Anthropic provider."""
