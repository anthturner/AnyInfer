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
    CachePolicy,
    GenerationRequest,
    HistoryPolicy,
    Sampling,
    SchemaSpec,
    ToolSpec,
)
from ..types.results import FinishReason, Generation, Usage

__all__ = [
    "CACHE_FIELD",
    "HISTORY_FIELD",
    "MANIFEST_FIELD",
    "OPENAI_FINISH_REASONS",
    "chunk_from_event",
    "completion_from_generation",
    "decode_messages",
    "encode_messages",
    "final_chunk",
    "manifest_chunk",
    "request_from_openai",
    "request_to_openai",
    "wants_manifest",
]

OPENAI_FINISH_REASONS: Mapping[FinishReason, str] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "content_filter": "content_filter",
    "other": "stop",
}
"""AnyInfer finish reasons rendered back into OpenAI's closed set."""

HISTORY_FIELD = "anyinfer_history"
"""Request-body extension carrying a per-request conversation-compaction policy.

The request surface is a documented *superset* of OpenAI chat completions, and this is
what that superset is for: a caller with a different tolerance for losing history says so
per request, instead of every deployment needing its own gateway. The field decodes into
`GenerationRequest.history` — the codec chooses nothing and applies nothing; the client
it fronts owns the behaviour, exactly as it does for the Python API.
"""

CACHE_FIELD = "anyinfer_cache"
"""Request-body extension carrying a per-request prompt-cache policy.

The same superset argument as `HISTORY_FIELD`, for a decision with a cost attached: a
caller who does not want their prompt held on the provider's side, or who wants it held
when the gateway does not ask for that by default, says so per request. Decodes into
`GenerationRequest.cache`.
"""

MANIFEST_FIELD = "anyinfer_manifest"
"""Request-body flag asking for the run manifest, and the response key it comes back in.

The result-side half of the same superset argument `HISTORY_FIELD` makes. Every routing,
mechanism, and provenance decision this library takes was reachable only from Python; a
caller on the standalone binary could use every one of them and see none of them. Opt-in,
because a stock OpenAI client must get a byte-identical response — so absence of the field
means absence of the key, on the non-streaming body and in the stream alike.
"""

_RESERVED_FIELDS = frozenset(
    {
        "model", "messages", "stream", "stream_options", "temperature", "top_p",
        "max_tokens", "max_completion_tokens", "stop", "tools", "tool_choice",
        "response_format", "metadata", "n", "user", HISTORY_FIELD, CACHE_FIELD,
        MANIFEST_FIELD,
    }
)


def wants_manifest(body: Mapping[str, Any]) -> bool:
    """Whether this request asked for its run manifest.

    Args:
        body: The parsed request JSON.

    Returns:
        ``True`` when the request set the extension to a truthy value.

    Raises:
        ValueError: If the field is present but is not a boolean, so a client that
            mis-spelled it learns rather than silently getting no manifest.
    """
    if MANIFEST_FIELD not in body:
        return False
    value = body[MANIFEST_FIELD]
    if not isinstance(value, bool):
        raise ValueError(f"{MANIFEST_FIELD} must be true or false")
    return value


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
        history=_decode_history(body.get(HISTORY_FIELD)),
        cache=_decode_cache(body.get(CACHE_FIELD)),
        provider_options=_decode_passthrough(body),
        metadata={k: str(v) for k, v in (body.get("metadata") or {}).items()},
    )
    return target, request, bool(body.get("stream"))


def _decode_cache(raw: Any) -> CachePolicy | None:
    """Decode the ``anyinfer_cache`` extension into a typed policy.

    Absent means "whatever the gateway was configured with", which is normally nothing.
    ``false`` means "not for this request" — a caller who does not want their prompt held
    on the provider's side can say so without the deployment changing.

    Raises:
        ValueError: On a malformed policy, so a client learns its request was wrong instead
            of silently getting the gateway's default.
    """
    if raw is None:
        return None
    if raw is False:
        return CachePolicy(mode="off")
    if raw is True:
        return CachePolicy()
    if not isinstance(raw, Mapping):
        raise ValueError(f"{CACHE_FIELD} must be an object, true, or false")

    known = {"mode", "min_segment_tokens", "max_marks", "include_tools", "include_system"}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{CACHE_FIELD} has unknown key(s): {', '.join(sorted(unknown))}")

    try:
        return CachePolicy(**dict(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{CACHE_FIELD} is invalid: {exc}") from exc


def _decode_history(raw: Any) -> HistoryPolicy | None:
    """Decode the ``anyinfer_history`` extension into a typed policy.

    Absent means "whatever the gateway was configured with". ``false`` means "not for this
    request" — a caller who would rather see the overflow error than a quietly shortened
    conversation can say so without the deployment changing.

    Raises:
        ValueError: On a malformed policy, so a client learns its request was wrong
            instead of silently getting the gateway's default.
    """
    if raw is None:
        return None
    if raw is False:
        return HistoryPolicy(enabled=False)
    if raw is True:
        return HistoryPolicy()
    if not isinstance(raw, Mapping):
        raise ValueError(f"{HISTORY_FIELD} must be an object, true, or false")

    unknown = set(raw) - {"enabled", "mode", "keep_recent", "keep_system"}
    if unknown:
        raise ValueError(
            f"{HISTORY_FIELD} has unknown key(s): {', '.join(sorted(unknown))}"
        )
    fields: dict[str, Any] = {}
    for key in ("enabled", "keep_system"):
        if key in raw:
            if not isinstance(raw[key], bool):
                raise ValueError(f"{HISTORY_FIELD}.{key} must be true or false")
            fields[key] = raw[key]
    if "keep_recent" in raw:
        value = raw["keep_recent"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{HISTORY_FIELD}.keep_recent must be an integer")
        fields["keep_recent"] = value
    if "mode" in raw:
        fields["mode"] = str(raw["mode"])
    try:
        return HistoryPolicy(**fields)
    except ValueError as exc:
        raise ValueError(f"{HISTORY_FIELD}: {exc}") from exc


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

    if request.history is not None:
        body[HISTORY_FIELD] = {
            "enabled": request.history.enabled,
            "mode": request.history.mode,
            "keep_recent": request.history.keep_recent,
            "keep_system": request.history.keep_system,
        }

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
    include_manifest: bool = False,
) -> dict[str, Any]:
    """Render a `Generation` as a ``chat.completion`` object.

    Args:
        result: The generation to render.
        model: The ``model`` string to echo back.
        completion_id: The completion id to stamp.
        created: Unix timestamp; defaults to now.
        include_manifest: Attach the run manifest under `MANIFEST_FIELD`. Off by default,
            so a stock client's response is byte-identical to what it was before manifests
            existed. Serialization only — nothing here assembles a manifest.
    """
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
    if include_manifest and result.manifest is not None:
        body[MANIFEST_FIELD] = result.manifest.to_dict()
    return body


def manifest_chunk(
    result: Generation,
    *,
    model: str,
    completion_id: str = "chatcmpl-anyinfer",
    created: int | None = None,
) -> dict[str, Any] | None:
    """Render the terminal manifest frame for a streaming response.

    Shaped as an ordinary ``chat.completion.chunk`` with an empty ``choices`` array — the
    same envelope the trailing usage chunk uses — so a reader that has never heard of the
    extension parses it, finds no delta, and moves on.

    Args:
        result: The finished generation.
        model: The ``model`` string to echo back.
        completion_id: The completion id to stamp.
        created: Unix timestamp; defaults to now.

    Returns:
        The frame, or ``None`` when the generation carries no manifest.
    """
    if result.manifest is None:
        return None
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created if created is not None else int(time.time()),
        "model": model,
        "choices": [],
        MANIFEST_FIELD: result.manifest.to_dict(),
    }


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
