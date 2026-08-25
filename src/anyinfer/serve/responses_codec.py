"""Wire codec for OpenAI's Responses API — ``POST /v1/responses``.

The second dialect this sidecar speaks, and the reason it needs one: the Responses API is
OpenAI's current-generation surface, and a Responses-first SDK 404s against a
chat-completions-only gateway. This project already treats it as the real dialect —
`anyinfer.providers.openai` speaks ``POST /responses`` *upstream* — so a gateway that
could not accept it was projecting a shape it does not itself prefer.

Everything here is translation. No routing, validation, or policy decision lives in this
module; it decodes one wire shape into `GenerationRequest` and
encodes `Generation` back, exactly as `openai_codec`
does for chat completions. The two share the request type, which is what keeps them from
becoming two cores.

**What is deliberately refused rather than emulated.** Responses is a *stateful* API:
``previous_response_id`` continues a conversation the server remembers, and ``store``
asks it to remember one. This gateway remembers nothing — run retention is a stated
non-goal — so both are refused with an explanation instead of being accepted and quietly
ignored. Silently dropping ``previous_response_id`` would produce an answer with no
conversation history, which reads as a bad model rather than a missing feature.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from typing import Any

from ..types.messages import (
    AudioPart,
    ContentPart,
    DocumentPart,
    ImagePart,
    Message,
    Text,
    ToolCall,
    ToolResult,
)
from ..types.requests import (
    GenerationRequest,
    Sampling,
    SchemaSpec,
    ToolSpec,
)
from ..types.results import Generation, Usage

# Sibling-module internals, imported rather than re-implemented. These decode wire *forms*
# (data URLs, base64, the AnyInfer extension objects) that both dialects carry identically;
# a second copy would be a second place to fix the next edge case found in one of them.
from .openai_codec import (
    ARENA_FIELD,
    CACHE_FIELD,
    CITE_DOCUMENTS_FIELD,
    CONTEXT_FIELD,
    HISTORY_FIELD,
    MANIFEST_FIELD,
    VIDEO_CONTENT_TYPE,
    _decode_arena,
    _decode_base64,
    _decode_cache,
    _decode_context,
    _decode_data_url,
    _decode_flag,
    _decode_history,
    _decode_passthrough,
    _decode_reasoning_effort,
    _decode_video,
    _opt_float,
    _opt_int,
    _parse_arguments,
    encode_citation,
)

__all__ = [
    "RESPONSE_STATUSES",
    "encode_response",
    "request_from_responses",
    "response_stream_events",
]

RESPONSE_STATUSES: Mapping[str, str] = {
    "stop": "completed",
    "tool_calls": "completed",
    "length": "incomplete",
    "content_filter": "incomplete",
    "other": "completed",
}
"""AnyInfer finish reasons rendered into the Responses API's ``status`` field.

``length`` and ``content_filter`` become ``incomplete`` with an
``incomplete_details.reason``, which is how this dialect says "the model stopped early"
— it has no per-choice ``finish_reason``.
"""

_INCOMPLETE_REASONS: Mapping[str, str] = {
    "length": "max_output_tokens",
    "content_filter": "content_filter",
}

_UNSUPPORTED_STATEFUL_FIELDS: Mapping[str, str] = {
    "previous_response_id": (
        "this gateway is stateless and stores no responses, so there is no conversation "
        "to continue. Send the prior turns in `input` instead"
    ),
    "store": (
        "this gateway stores no responses; run retention is a deliberate non-goal. Omit "
        "the field rather than asking for storage that will not happen"
    ),
}


def request_from_responses(
    body: Mapping[str, Any], *, context_tuning: Any = None
) -> tuple[str, GenerationRequest, bool]:
    """Decode a Responses API request body.

    Args:
        body: The parsed request JSON.
        context_tuning: Default ``ContextTuning`` for a request whose context extension
            omits its own, as in `openai_codec.request_from_openai`.

    Returns:
        A ``(target, request, stream)`` triple. ``target`` is the ``model`` field taken
        verbatim: an AnyInfer target *is* a model string, in this dialect as in the other.

    Raises:
        ValueError: The body asks for server-side state this gateway does not keep, or a
            field is malformed. Refused rather than dropped — an answer assembled without
            the conversation the caller referenced reads as a bad model, not as a missing
            feature.
    """
    target = str(body.get("model", "")).strip()

    for field_name, reason in _UNSUPPORTED_STATEFUL_FIELDS.items():
        value = body.get(field_name)
        if value not in (None, False):
            raise ValueError(f"{field_name!r} is not supported: {reason}")

    messages = _decode_input(body.get("input"))
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions:
        # A system message rather than a separate field: the normalized request has one
        # conversation, and every adapter already knows how its provider spells a system
        # turn. Prepended, so an `input` that also carries one keeps its own precedence.
        messages = (Message(role="system", content=(Text(instructions),)), *messages)

    request = GenerationRequest(
        messages=messages,
        schema=_decode_text_format(body.get("text")),
        tools=_decode_tools(body.get("tools")),
        tool_choice=_decode_tool_choice(body.get("tool_choice")),
        sampling=Sampling(
            temperature=_opt_float(body.get("temperature")),
            top_p=_opt_float(body.get("top_p")),
            max_output_tokens=_opt_int(body.get("max_output_tokens")),
        ),
        reasoning=_decode_reasoning_effort(_reasoning_effort(body.get("reasoning"))),
        history=_decode_history(body.get(HISTORY_FIELD)),
        cache=_decode_cache(body.get(CACHE_FIELD)),
        arena=_decode_arena(body.get(ARENA_FIELD)),
        context=_decode_context(body.get(CONTEXT_FIELD), context_tuning),
        provider_options=_decode_passthrough(body),
        metadata={k: str(v) for k, v in (body.get("metadata") or {}).items()},
        logprobs=_opt_int(body.get("top_logprobs")),
        cite_documents=_decode_flag(body, CITE_DOCUMENTS_FIELD),
    )
    return target, request, bool(body.get("stream"))


def _reasoning_effort(raw: Any) -> Any:
    """Pull ``reasoning.effort`` out of this dialect's nested object."""
    if isinstance(raw, Mapping):
        return raw.get("effort")
    return None


def _decode_input(raw: Any) -> tuple[Message, ...]:
    """Decode ``input``: a bare string, or the dialect's typed item list.

    Raises:
        ValueError: An item is not an object, or names a type this codec cannot map.
    """
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (Message(role="user", content=(Text(raw),)),) if raw else ()
    if not isinstance(raw, list):
        raise ValueError("input must be a string or an array of items")

    messages: list[Message] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("each input item must be an object")
        kind = item.get("type")

        if kind == "function_call":
            messages.append(
                Message(
                    role="assistant",
                    content=(
                        ToolCall(
                            id=str(item.get("call_id") or item.get("id") or ""),
                            name=str(item.get("name", "")),
                            arguments=_parse_arguments(item.get("arguments")),
                        ),
                    ),
                )
            )
            continue

        if kind == "function_call_output":
            messages.append(
                Message(
                    role="tool",
                    content=(
                        ToolResult(
                            call_id=str(item.get("call_id", "")),
                            content=_as_output_text(item.get("output")),
                        ),
                    ),
                )
            )
            continue

        if kind in (None, "message"):
            role = str(item.get("role", "user"))
            content = _decode_item_content(item.get("content"))
            if content:
                messages.append(Message(role=role, content=content))  # type: ignore[arg-type]
            continue

        raise ValueError(f"unsupported input item type {kind!r}")
    return tuple(messages)


def _as_output_text(raw: Any) -> str:
    """Render a ``function_call_output`` payload as the text a model reads."""
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, default=str)


def _decode_item_content(content: Any) -> tuple[ContentPart, ...]:
    """Decode one message item's content array.

    The part names differ from chat completions — ``input_text`` rather than ``text``,
    ``input_image`` rather than ``image_url`` — which is why this is its own function
    rather than a call into the other codec.

    Raises:
        ValueError: A part is missing the field its type requires.
    """
    if isinstance(content, str):
        return (Text(content),) if content else ()
    if not isinstance(content, list):
        return ()

    parts: list[ContentPart] = []
    for raw in content:
        if not isinstance(raw, Mapping):
            continue
        kind = raw.get("type")

        if kind in ("input_text", "output_text", "text"):
            text = raw.get("text")
            if isinstance(text, str) and text:
                parts.append(Text(text))
        elif kind == "input_image":
            url = raw.get("image_url")
            if not isinstance(url, str) or not url:
                raise ValueError("input_image content requires image_url")
            media_type, data, resolved = _decode_data_url(url)
            detail = raw.get("detail")
            parts.append(
                ImagePart(
                    data=data,
                    url=resolved,
                    media_type=media_type or "image/png",
                    detail=(detail if detail in ("auto", "low", "high") else None),
                )
            )
        elif kind == "input_file":
            source = raw.get("file_data", raw.get("file_url"))
            if not isinstance(source, str):
                raise ValueError("input_file content requires file_data or file_url")
            media_type, data, resolved = _decode_data_url(source)
            filename = raw.get("filename")
            parts.append(
                DocumentPart(
                    data=data,
                    url=resolved,
                    media_type=media_type or "application/pdf",
                    filename=str(filename) if isinstance(filename, str) else None,
                )
            )
        elif kind == "input_audio":
            audio = raw.get("input_audio", raw)
            if not isinstance(audio, Mapping) or not isinstance(audio.get("data"), str):
                raise ValueError("input_audio content requires base64 data")
            fmt = str(audio.get("format", "wav")).lower()
            media_type = {"wav": "audio/wav", "mp3": "audio/mpeg"}.get(fmt, f"audio/{fmt}")
            parts.append(AudioPart(_decode_base64(str(audio["data"])), media_type))
        elif kind == VIDEO_CONTENT_TYPE:
            parts.append(_decode_video(raw.get(VIDEO_CONTENT_TYPE)))
    return tuple(parts)


def _decode_text_format(raw: Any) -> SchemaSpec | None:
    """Decode ``text.format`` into a structured-output contract.

    This dialect flattens what chat completions nests: the schema and its name sit
    directly on the format object rather than under a ``json_schema`` key.

    Raises:
        ValueError: A ``json_schema`` format carries no schema.
    """
    if not isinstance(raw, Mapping):
        return None
    fmt = raw.get("format")
    if not isinstance(fmt, Mapping):
        return None
    kind = fmt.get("type")
    if kind == "json_schema":
        schema = fmt.get("schema")
        if not isinstance(schema, Mapping):
            raise ValueError("text.format of type json_schema requires a schema object")
        return SchemaSpec(json_schema=dict(schema), name=str(fmt.get("name", "response")))
    if kind == "json_object":
        # No schema on the wire; the core enforces JSON-ness through its json_mode
        # mechanism, and an empty object schema is what says "any JSON object".
        return SchemaSpec(json_schema={"type": "object"}, name="response")
    return None


def _decode_tools(raw: Any) -> tuple[ToolSpec, ...]:
    """Decode the dialect's *flattened* function tools.

    Responses puts ``name``/``parameters`` directly on the tool object where chat
    completions nests them under ``function``. Non-function tool types are skipped here
    rather than refused: they are provider-native server tools, which travel on the
    request's own server-tool surface rather than as client-executed `ToolSpec`.
    """
    if not isinstance(raw, list):
        return ()
    tools: list[ToolSpec] = []
    for entry in raw:
        if not isinstance(entry, Mapping) or entry.get("type") not in (None, "function"):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        tools.append(
            ToolSpec(
                name=name,
                description=str(entry.get("description", "")),
                parameters=dict(entry.get("parameters") or {}),
            )
        )
    return tuple(tools)


def _decode_tool_choice(raw: Any) -> str:
    """Decode ``tool_choice``; this dialect's pinned form is flattened too."""
    if isinstance(raw, str) and raw in ("auto", "none", "required"):
        return raw
    if isinstance(raw, Mapping):
        name = raw.get("name")
        if isinstance(name, str) and name:
            return name
    return "auto"


# ---- the response object -------------------------------------------------------------


def encode_response(
    result: Generation,
    *,
    model: str,
    response_id: str | None = None,
    created: int | None = None,
    include_manifest: bool = False,
) -> dict[str, Any]:
    """Encode a finished `Generation` as a Responses API response object.

    Args:
        result: The assembled generation.
        model: Echoed back as the response's ``model``.
        response_id: Response id; generated when omitted.
        created: Unix timestamp; defaults to now.
        include_manifest: Attach the run manifest under the manifest extension, so a stock
            client's response stays byte-identical to what it was without it.

    Returns:
        The response object, with ``output`` carrying one item per thing the model
        produced — reasoning, message, and function calls, in that order.
    """
    output: list[dict[str, Any]] = []

    if result.text or not result.tool_calls:
        content: list[dict[str, Any]] = [
            {"type": "output_text", "text": result.text, "annotations": _annotations(result)}
        ]
        if result.logprobs:
            # The dialect has no logprobs field of its own on a content part, so this
            # rides the same extension name the chat codec uses. A stock client ignores it.
            content[0]["logprobs"] = [
                {"token": token.token, "logprob": token.logprob} for token in result.logprobs
            ]
        output.append(
            {
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex[:24]}",
                "status": "completed",
                "role": "assistant",
                "content": content,
            }
        )

    output.extend(
        {
            "type": "function_call",
            "id": f"fc_{uuid.uuid4().hex[:24]}",
            "call_id": call.id,
            "name": call.name,
            "arguments": json.dumps(dict(call.arguments)),
            "status": "completed",
        }
        for call in result.tool_calls
    )

    body: dict[str, Any] = {
        "id": response_id or f"resp_{uuid.uuid4().hex[:24]}",
        "object": "response",
        "created_at": created if created is not None else int(time.time()),
        "status": RESPONSE_STATUSES[result.finish_reason],
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        # Stated rather than omitted: this gateway keeps nothing, and a client that reads
        # the field learns that without having to send `store` and be refused.
        "store": False,
        "error": None,
        "incomplete_details": _incomplete_details(result),
    }
    usage = _encode_usage(result.usage)
    if usage is not None:
        body["usage"] = usage
    if include_manifest and result.manifest is not None:
        body[MANIFEST_FIELD] = result.manifest.to_dict()
    if result.arena is not None:
        from .openai_codec import arena_to_dict

        body[ARENA_FIELD] = arena_to_dict(result.arena)
    if result.context_reduction is not None:
        body[CONTEXT_FIELD] = result.context_reduction.to_dict()
    return body


def _annotations(result: Generation) -> list[dict[str, Any]]:
    """Render citations as the dialect's content-part annotations.

    The one place this codec has a *native* home for something the chat dialect needed an
    extension for: Responses content parts carry `annotations`, which is what a grounded
    answer's attributions are for.
    """
    return [
        {"type": "url_citation", **encode_citation(citation)} for citation in result.citations
    ]


def _incomplete_details(result: Generation) -> dict[str, Any] | None:
    """Say why the model stopped early, when it did."""
    reason = _INCOMPLETE_REASONS.get(result.finish_reason)
    return {"reason": reason} if reason else None


def _encode_usage(usage: Usage) -> dict[str, Any] | None:
    """Encode usage under this dialect's names, which differ from chat completions'."""
    if usage.input_tokens is None and usage.output_tokens is None:
        return None
    inputs = usage.input_tokens or 0
    outputs = usage.output_tokens or 0
    encoded: dict[str, Any] = {
        "input_tokens": inputs,
        "output_tokens": outputs,
        "total_tokens": usage.total_tokens or (inputs + outputs),
    }
    if usage.cache_read_tokens is not None:
        encoded["input_tokens_details"] = {"cached_tokens": usage.cache_read_tokens}
    if usage.reasoning_tokens is not None:
        encoded["output_tokens_details"] = {"reasoning_tokens": usage.reasoning_tokens}
    return encoded


# ---- semantic streaming ----------------------------------------------------------------


class _ResponseStream:
    """Turns AnyInfer's event stream into the Responses API's *semantic* event sequence.

    The two dialects stream differently in kind, not just in spelling. Chat completions
    emits one repeated chunk shape and leaves the client to reassemble it; Responses emits
    a narrated lifecycle — an item was added, a content part opened, text arrived, the part
    closed, the item closed — where every event names what it belongs to. A client written
    against it *depends* on that narration: an `output_text.delta` with no preceding
    `content_part.added` has nowhere to land.

    So this class is a small state machine rather than a mapping function. It opens items
    lazily, on the first event that needs one, and closes whatever is open when the stream
    ends — which is what keeps the sequence well-formed for a caller that only ever
    produced text, only tool calls, or both.

    Args:
        model: Echoed on every response snapshot.
        response_id: The response's id, stable across its events.
        created: Unix timestamp for the response object.
    """

    __slots__ = (
        "_created",
        "_model",
        "_open_item",
        "_reasoning_item",
        "_reasoning_open",
        "_response_id",
        "_sequence",
        "_text",
        "_text_item",
        "_text_open",
        "_tool_items",
    )

    def __init__(self, *, model: str, response_id: str, created: int) -> None:
        self._model = model
        self._response_id = response_id
        self._created = created
        self._sequence = 0
        self._open_item = 0
        self._text_open = False
        self._reasoning_open = False
        self._text: list[str] = []
        self._text_item = ""
        self._reasoning_item = ""
        self._tool_items: dict[int, tuple[int, str]] = {}

    def _event(self, kind: str, **fields: Any) -> dict[str, Any]:
        """Stamp one event with its type and monotonic sequence number."""
        self._sequence += 1
        return {"type": kind, "sequence_number": self._sequence, **fields}

    def _snapshot(self, status: str) -> dict[str, Any]:
        """A response object for the lifecycle events that carry one."""
        return {
            "id": self._response_id,
            "object": "response",
            "created_at": self._created,
            "status": status,
            "model": self._model,
            "output": [],
            "store": False,
            "error": None,
        }

    def created(self) -> list[dict[str, Any]]:
        """The opening pair every Responses stream begins with."""
        return [
            self._event("response.created", response=self._snapshot("in_progress")),
            self._event("response.in_progress", response=self._snapshot("in_progress")),
        ]

    def text_delta(self, text: str) -> list[dict[str, Any]]:
        """Open the message item and content part on demand, then emit the delta."""
        events: list[dict[str, Any]] = []
        if not self._text_open:
            events.extend(self._close_reasoning())
            item_id = f"msg_{uuid.uuid4().hex[:24]}"
            events.append(
                self._event(
                    "response.output_item.added",
                    output_index=self._open_item,
                    item={
                        "type": "message",
                        "id": item_id,
                        "status": "in_progress",
                        "role": "assistant",
                        "content": [],
                    },
                )
            )
            events.append(
                self._event(
                    "response.content_part.added",
                    item_id=item_id,
                    output_index=self._open_item,
                    content_index=0,
                    part={"type": "output_text", "text": "", "annotations": []},
                )
            )
            self._text_open = True
            self._text_item = item_id
        events.append(
            self._event(
                "response.output_text.delta",
                item_id=self._text_item,
                output_index=self._open_item,
                content_index=0,
                delta=text,
            )
        )
        self._text.append(text)
        return events

    def reasoning_delta(self, text: str) -> list[dict[str, Any]]:
        """Emit reasoning under its own item, rather than dropping it.

        The dialect models reasoning as a `reasoning` output item whose summary streams as
        its own delta type. Folding it into the answer text would corrupt the answer;
        discarding it would lose something the caller asked for and paid for.
        """
        events: list[dict[str, Any]] = []
        if not self._reasoning_open:
            item_id = f"rs_{uuid.uuid4().hex[:24]}"
            events.append(
                self._event(
                    "response.output_item.added",
                    output_index=self._open_item,
                    item={
                        "type": "reasoning",
                        "id": item_id,
                        "status": "in_progress",
                        "summary": [],
                    },
                )
            )
            self._reasoning_open = True
            self._reasoning_item = item_id
        events.append(
            self._event(
                "response.reasoning_summary_text.delta",
                item_id=self._reasoning_item,
                output_index=self._open_item,
                summary_index=0,
                delta=text,
            )
        )
        return events

    def tool_delta(
        self, index: int, call_id: str | None, name: str | None, fragment: str
    ) -> list[dict[str, Any]]:
        """Open a function-call item for a new slot, then stream its arguments."""
        events: list[dict[str, Any]] = []
        slot = self._tool_items.get(index)
        if slot is None:
            events.extend(self._close_text())
            events.extend(self._close_reasoning())
            self._open_item += 1
            item_id = f"fc_{uuid.uuid4().hex[:24]}"
            events.append(
                self._event(
                    "response.output_item.added",
                    output_index=self._open_item,
                    item={
                        "type": "function_call",
                        "id": item_id,
                        "call_id": call_id or f"call_{index}",
                        "name": name or "",
                        "arguments": "",
                        "status": "in_progress",
                    },
                )
            )
            slot = (self._open_item, item_id)
            self._tool_items[index] = slot
        if fragment:
            events.append(
                self._event(
                    "response.function_call_arguments.delta",
                    item_id=slot[1],
                    output_index=slot[0],
                    delta=fragment,
                )
            )
        return events

    def _close_text(self) -> list[dict[str, Any]]:
        """Close the message item, if one is open."""
        if not self._text_open:
            return []
        self._text_open = False
        text = "".join(self._text)
        return [
            self._event(
                "response.output_text.done",
                item_id=self._text_item,
                output_index=self._open_item,
                content_index=0,
                text=text,
            ),
            self._event(
                "response.content_part.done",
                item_id=self._text_item,
                output_index=self._open_item,
                content_index=0,
                part={"type": "output_text", "text": text, "annotations": []},
            ),
            self._event(
                "response.output_item.done",
                output_index=self._open_item,
                item={
                    "type": "message",
                    "id": self._text_item,
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text, "annotations": []}],
                },
            ),
        ]

    def _close_reasoning(self) -> list[dict[str, Any]]:
        """Close the reasoning item, if one is open."""
        if not self._reasoning_open:
            return []
        self._reasoning_open = False
        return [
            self._event(
                "response.output_item.done",
                output_index=self._open_item,
                item={
                    "type": "reasoning",
                    "id": self._reasoning_item,
                    "status": "completed",
                    "summary": [],
                },
            )
        ]

    def _close_tools(self, result: Generation) -> list[dict[str, Any]]:
        """Close every open function-call item, with its finished arguments."""
        events: list[dict[str, Any]] = []
        for index, (output_index, item_id) in sorted(self._tool_items.items()):
            call = result.tool_calls[index] if index < len(result.tool_calls) else None
            arguments = json.dumps(dict(call.arguments)) if call is not None else "{}"
            events.append(
                self._event(
                    "response.function_call_arguments.done",
                    item_id=item_id,
                    output_index=output_index,
                    arguments=arguments,
                )
            )
            events.append(
                self._event(
                    "response.output_item.done",
                    output_index=output_index,
                    item={
                        "type": "function_call",
                        "id": item_id,
                        "call_id": call.id if call is not None else f"call_{index}",
                        "name": call.name if call is not None else "",
                        "arguments": arguments,
                        "status": "completed",
                    },
                )
            )
        return events

    def completed(
        self, result: Generation, *, include_manifest: bool = False
    ) -> list[dict[str, Any]]:
        """Close whatever is open and emit the terminal event with the full response."""
        events = [*self._close_text(), *self._close_reasoning(), *self._close_tools(result)]
        response = encode_response(
            result,
            model=self._model,
            response_id=self._response_id,
            created=self._created,
            include_manifest=include_manifest,
        )
        status = response["status"]
        kind = "response.completed" if status == "completed" else f"response.{status}"
        events.append(self._event(kind, response=response))
        return events

    def failed(self, message: str, code: str) -> dict[str, Any]:
        """Report a mid-stream failure in the dialect's own terms.

        The status line is long gone by the time this can happen, so a terminal event is
        the only way left to tell the client — the same reasoning the chat codec's error
        record follows.
        """
        response = self._snapshot("failed")
        response["error"] = {"code": code, "message": message}
        return self._event("response.failed", response=response)


def response_stream_events(*, model: str, response_id: str, created: int) -> _ResponseStream:
    """Build the streaming state machine for one response.

    Args:
        model: Echoed on every response snapshot.
        response_id: The response's id, stable across its events.
        created: Unix timestamp for the response object.

    Returns:
        A fresh `_ResponseStream`. One per request: it holds that response's open items.
    """
    return _ResponseStream(model=model, response_id=response_id, created=created)
