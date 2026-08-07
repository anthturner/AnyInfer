"""OpenAI wire ⇄ AnyInfer codec.

The serve frontend is a **codec, never a second core**. This module is the whole of its
translation logic: OpenAI chat-completions JSON in, `GenerationRequest` out; typed
`StreamEvent`s in, ``chat.completion.chunk`` JSON out. It contains no routing, retry,
validation, credential, or provider logic — those live in the core and are reached through a
normal `AsyncClient`.

The codec's four invariants are core obligations and are round-trip tested here:

1. `GenerationRequest` is a **superset** of the OpenAI chat-completions surface.
2. The event stream is **sufficient to reconstruct** a ``chat.completion.chunk`` sequence.
3. `Target` is representable in a ``model`` string.
4. The client supports many concurrent independent streams.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..types.events import StreamEvent, TextDelta, ToolCallDelta
from ..types.messages import Message, Text, ToolCall, ToolResult
from ..types.requests import (
    GenerationRequest,
    Sampling,
    SchemaSpec,
    ToolSpec,
)
from ..types.results import FinishReason, Generation, Usage

__all__ = [
    "OPENAI_FINISH_REASONS",
    "chunk_from_event",
    "completion_from_generation",
    "decode_messages",
    "encode_messages",
    "final_chunk",
    "request_from_openai",
    "request_to_openai",
]

OPENAI_FINISH_REASONS: Mapping[FinishReason, str] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "content_filter": "content_filter",
    "other": "stop",
}
"""AnyInfer finish reasons rendered back into OpenAI's closed set."""

_RESERVED_FIELDS = frozenset(
    {
        "model", "messages", "stream", "stream_options", "temperature", "top_p",
        "max_tokens", "max_completion_tokens", "stop", "tools", "tool_choice",
        "response_format", "metadata", "n", "user",
    }
)


# ---- request: OpenAI -> AnyInfer -----------------------------------------------------


def decode_messages(raw: Sequence[Mapping[str, Any]]) -> tuple[Message, ...]:
    """Decode an OpenAI ``messages`` array into typed messages."""
    messages: list[Message] = []
    for entry in raw:
        role = str(entry.get("role", "user"))
        if role == "tool":
            messages.append(
                Message(
                    role="tool",
                    content=(
                        ToolResult(
                            call_id=str(entry.get("tool_call_id", "")),
                            content=_as_text(entry.get("content")),
                        ),
                    ),
                )
            )
            continue

        parts: list[Text | ToolCall | ToolResult] = []
        text = _as_text(entry.get("content"))
        if text:
            parts.append(Text(text))
        for call in entry.get("tool_calls") or ():
            if not isinstance(call, Mapping):
                continue
            function = call.get("function")
            name = ""
            arguments: Mapping[str, Any] = {}
            if isinstance(function, Mapping):
                name = str(function.get("name", ""))
                arguments = _parse_arguments(function.get("arguments"))
            parts.append(
                ToolCall(id=str(call.get("id", "")), name=name, arguments=arguments)
            )
        normalized_role = role if role in ("system", "user", "assistant") else "user"
        messages.append(Message(role=normalized_role, content=tuple(parts)))  # type: ignore[arg-type]
    return tuple(messages)


def _as_text(content: Any) -> str:
    """Flatten OpenAI's string-or-parts content into text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, Mapping) and part.get("type") == "text"
        )
    return ""


def _parse_arguments(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def request_from_openai(body: Mapping[str, Any]) -> tuple[str, GenerationRequest, bool]:
    """Decode an OpenAI chat-completions request body.

    Args:
        body: The parsed request JSON.

    Returns:
        A ``(target, request, stream)`` triple. ``target`` is the ``model`` field taken
        verbatim — an AnyInfer target *is* an OpenAI model string (invariant 3), which is
        what makes federation free.
    """
    target = str(body.get("model", "")).strip()

    sampling = Sampling(
        temperature=_opt_float(body.get("temperature")),
        top_p=_opt_float(body.get("top_p")),
        max_output_tokens=_opt_int(
            body.get("max_completion_tokens", body.get("max_tokens"))
        ),
        stop=_decode_stop(body.get("stop")),
    )

    tools = tuple(
        ToolSpec(
            name=str(fn.get("name", "")),
            description=str(fn.get("description", "")),
            parameters=dict(fn.get("parameters") or {}),
        )
        for tool in (body.get("tools") or ())
        if isinstance(tool, Mapping)
        for fn in [tool.get("function")]
        if isinstance(fn, Mapping)
    )

    request = GenerationRequest(
        messages=decode_messages(body.get("messages") or ()),
        schema=_decode_response_format(body.get("response_format")),
        tools=tools,
        tool_choice=_decode_tool_choice(body.get("tool_choice")),
        sampling=sampling,
        provider_options=_decode_passthrough(body),
        metadata={k: str(v) for k, v in (body.get("metadata") or {}).items()},
    )
    return target, request, bool(body.get("stream"))


def _decode_stop(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(str(s) for s in raw)
    return ()


def _decode_tool_choice(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, Mapping):
        function = raw.get("function")
        if isinstance(function, Mapping):
            return str(function.get("name", "auto"))
    return "auto"


def _decode_response_format(raw: Any) -> SchemaSpec | None:
    if not isinstance(raw, Mapping):
        return None
    if raw.get("type") != "json_schema":
        return None
    spec = raw.get("json_schema")
    if not isinstance(spec, Mapping):
        return None
    schema = spec.get("schema")
    if not isinstance(schema, Mapping):
        return None
    return SchemaSpec(json_schema=dict(schema), name=str(spec.get("name", "response")))


def _decode_passthrough(body: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    """Route unrecognized extra-body fields to ``provider_options``.

    OpenAI clients rely on extra-body passthrough to reach provider-specific features; the
    escape hatch must survive the codec or the frontend is strictly less capable than the
    SDK. Fields outside any provider namespace land under the ``"*"`` wildcard, which the
    core forwards to whichever provider ends up serving the request.
    """
    extra = {k: v for k, v in body.items() if k not in _RESERVED_FIELDS}
    if not extra:
        return {}
    namespaced = extra.pop("provider_options", None)
    options: dict[str, Mapping[str, Any]] = {}
    if isinstance(namespaced, Mapping):
        options.update(
            {str(k): dict(v) for k, v in namespaced.items() if isinstance(v, Mapping)}
        )
    if extra:
        options.setdefault("*", dict(extra))
    return options


def _opt_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _opt_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


# ---- request: AnyInfer -> OpenAI (round-trip verification) ---------------------------


def encode_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Encode typed messages back into an OpenAI ``messages`` array."""
    encoded: list[dict[str, Any]] = []
    for message in messages:
        results = [p for p in message.content if isinstance(p, ToolResult)]
        if results:
            encoded.append(
                {
                    "role": "tool",
                    "tool_call_id": results[0].call_id,
                    "content": results[0].content,
                }
            )
            continue

        text = "".join(p.text for p in message.content if isinstance(p, Text))
        entry: dict[str, Any] = {"role": message.role, "content": text}
        calls = [p for p in message.content if isinstance(p, ToolCall)]
        if calls:
            entry["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": json.dumps(dict(c.arguments)),
                    },
                }
                for c in calls
            ]
            if not text:
                entry["content"] = None
        encoded.append(entry)
    return encoded


def request_to_openai(
    target: str, request: GenerationRequest, *, stream: bool = False
) -> dict[str, Any]:
    """Encode a request back into OpenAI wire form.

    The inverse of `request_from_openai()`, and the basis of the round-trip test that
    enforces invariant 1: anything the OpenAI surface can express must survive the trip.
    """
    body: dict[str, Any] = {
        "model": target,
        "messages": encode_messages(request.messages),
    }
    if stream:
        body["stream"] = True

    sampling = request.sampling
    if sampling.temperature is not None:
        body["temperature"] = sampling.temperature
    if sampling.top_p is not None:
        body["top_p"] = sampling.top_p
    if sampling.max_output_tokens is not None:
        body["max_tokens"] = sampling.max_output_tokens
    if sampling.stop:
        body["stop"] = list(sampling.stop)

    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": dict(t.parameters),
                },
            }
            for t in request.tools
        ]
        body["tool_choice"] = (
            request.tool_choice
            if request.tool_choice in ("auto", "none", "required")
            else {"type": "function", "function": {"name": request.tool_choice}}
        )

    if request.schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.schema.name,
                "schema": dict(request.schema.json_schema),
            },
        }

    if request.metadata:
        body["metadata"] = dict(request.metadata)
    return body


# ---- response: AnyInfer -> OpenAI ----------------------------------------------------


def completion_from_generation(
    result: Generation,
    *,
    model: str,
    completion_id: str = "chatcmpl-anyinfer",
    created: int | None = None,
) -> dict[str, Any]:
    """Render a `Generation` as a ``chat.completion`` object."""
    message: dict[str, Any] = {"role": "assistant", "content": result.text or None}
    if result.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(dict(call.arguments)),
                },
            }
            for call in result.tool_calls
        ]
    body: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created if created is not None else int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": OPENAI_FINISH_REASONS[result.finish_reason],
            }
        ],
    }
    usage = _encode_usage(result.usage)
    if usage is not None:
        body["usage"] = usage
    return body


def _encode_usage(usage: Usage) -> dict[str, Any] | None:
    if usage.input_tokens is None and usage.output_tokens is None:
        return None
    return {
        "prompt_tokens": usage.input_tokens or 0,
        "completion_tokens": usage.output_tokens or 0,
        "total_tokens": usage.total_tokens or 0,
    }


def chunk_from_event(
    event: StreamEvent,
    *,
    model: str,
    completion_id: str = "chatcmpl-anyinfer",
    created: int | None = None,
) -> dict[str, Any] | None:
    """Render one stream event as a ``chat.completion.chunk``.

    Returns ``None`` for events with no OpenAI equivalent (timing marks, attempt records) —
    they are AnyInfer-native observability that the OpenAI wire format cannot carry.
    """
    stamp = created if created is not None else int(time.time())
    envelope: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": stamp,
        "model": model,
    }

    if isinstance(event, TextDelta):
        envelope["choices"] = [
            {"index": 0, "delta": {"content": event.text}, "finish_reason": None}
        ]
        return envelope

    if isinstance(event, ToolCallDelta):
        function: dict[str, Any] = {"arguments": event.arguments_fragment}
        if event.name:
            function["name"] = event.name
        call: dict[str, Any] = {"index": event.index, "function": function}
        if event.call_id:
            call["id"] = event.call_id
            call["type"] = "function"
        envelope["choices"] = [
            {"index": 0, "delta": {"tool_calls": [call]}, "finish_reason": None}
        ]
        return envelope

    return None


def final_chunk(
    result: Generation,
    *,
    model: str,
    completion_id: str = "chatcmpl-anyinfer",
    created: int | None = None,
    include_usage: bool = True,
) -> Iterable[dict[str, Any]]:
    """Render the terminal chunks: the finish reason, then optionally usage.

    Usage rides in its own trailing chunk with an empty ``choices`` array, matching
    ``stream_options.include_usage``. Clients that stop reading at ``finish_reason`` miss
    it — which is exactly the bug the core's own parser is written to avoid.
    """
    stamp = created if created is not None else int(time.time())
    yield {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": stamp,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": OPENAI_FINISH_REASONS[result.finish_reason],
            }
        ],
    }
    usage = _encode_usage(result.usage)
    if include_usage and usage is not None:
        yield {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": stamp,
            "model": model,
            "choices": [],
            "usage": usage,
        }
