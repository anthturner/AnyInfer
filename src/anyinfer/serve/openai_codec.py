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

import base64
import binascii
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from .._context_wire import decode_context_request, encode_context_request
from ..evaluate.arena import arena_to_dict
from ..types.events import StreamEvent, TextDelta, ToolCallDelta
from ..types.messages import (
    AudioPart,
    ContentPart,
    DocumentPart,
    ImagePart,
    Message,
    Text,
    ToolCall,
    ToolResult,
    VideoPart,
)
from ..types.requests import (
    ArenaPolicy,
    CachePolicy,
    GenerationRequest,
    HistoryPolicy,
    ReasoningEffort,
    Sampling,
    SchemaSpec,
    ToolSpec,
)
from ..types.results import FinishReason, Generation, TokenLogprob, Usage

__all__ = [
    "ARENA_FIELD",
    "CACHE_FIELD",
    "CONTEXT_FIELD",
    "HISTORY_FIELD",
    "MANIFEST_FIELD",
    "OPENAI_FINISH_REASONS",
    "VIDEO_CONTENT_TYPE",
    "chunk_from_event",
    "completion_from_generation",
    "decode_messages",
    "encode_logprobs",
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
because a stock OpenAI client must get a byte-identical response, so absence of the field
means absence of the key, on the non-streaming body and in the stream alike.
"""

ARENA_FIELD = "anyinfer_arena"
"""Per-request arena policy and result-side candidate evidence extension."""

CONTEXT_FIELD = "anyinfer_context"
"""Stateless caller-supplied corpus reduction request and content-free summary."""

VIDEO_CONTENT_TYPE = "anyinfer_video"
"""Message-content extension carrying a video input part.

The other four extensions are top-level request keys; this one is a *content item*,
because that is how the dialect it extends grows — `input_audio` and `file` were both
added as content types, not as request fields, and a video belongs inside the message it
was attached to. Its object is the wire spelling of a
`VideoPart`: ``{"url"|"data", "media_type",
"start_offset_s"?, "end_offset_s"?, "fps"?}``.

A stock OpenAI client never sends it and never sees it. It exists so the request surface
stays a genuine superset — a video part expressible in Python must survive the round trip
through this codec, and chat completions has no content type of its own to carry one.
"""

_RESERVED_FIELDS = frozenset(
    {
        "model",
        "messages",
        "stream",
        "stream_options",
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "stop",
        "tools",
        "tool_choice",
        "response_format",
        "reasoning_effort",
        "metadata",
        "n",
        "logprobs",
        "top_logprobs",
        "user",
        HISTORY_FIELD,
        CACHE_FIELD,
        MANIFEST_FIELD,
        ARENA_FIELD,
        CONTEXT_FIELD,
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

        parts: list[ContentPart] = list(_decode_content(entry.get("content")))
        for call in entry.get("tool_calls") or ():
            if not isinstance(call, Mapping):
                continue
            function = call.get("function")
            name = ""
            arguments: Mapping[str, Any] = {}
            if isinstance(function, Mapping):
                name = str(function.get("name", ""))
                arguments = _parse_arguments(function.get("arguments"))
            parts.append(ToolCall(id=str(call.get("id", "")), name=name, arguments=arguments))
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


def _decode_video(raw: Any) -> VideoPart:
    """Decode the video content extension into a `VideoPart`.

    Raises:
        ValueError: The object is missing, is not an object, names neither a URL nor
            inline data, or carries a non-numeric offset or frame rate. Refused rather
            than defaulted: a video the gateway silently dropped is a question answered
            about footage the model never saw.
    """
    if not isinstance(raw, Mapping):
        raise ValueError(f"{VIDEO_CONTENT_TYPE} content requires an object")
    url = raw.get("url")
    data = raw.get("data")
    if isinstance(url, str) and url:
        media_type, decoded, resolved_url = _decode_data_url(url)
    elif isinstance(data, str) and data:
        media_type, decoded, resolved_url = None, _decode_base64(data), None
    else:
        raise ValueError(f"{VIDEO_CONTENT_TYPE} content requires url or base64 data")

    def _number(key: str) -> float | None:
        value = raw.get(key)
        if value is None:
            return None
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError(f"{VIDEO_CONTENT_TYPE}.{key} must be a number")
        return float(value)

    return VideoPart(
        data=decoded,
        url=resolved_url,
        media_type=str(raw.get("media_type") or media_type or "video/mp4"),
        start_offset_s=_number("start_offset_s"),
        end_offset_s=_number("end_offset_s"),
        fps=_number("fps"),
    )


def _encode_video(part: VideoPart) -> dict[str, Any]:
    """Encode a `VideoPart` back into the content extension, omitting unset fields."""
    encoded: dict[str, Any] = {"media_type": part.media_type}
    if part.url is not None:
        encoded["url"] = part.url
    else:
        encoded["data"] = base64.b64encode(part.data or b"").decode("ascii")
    for key in ("start_offset_s", "end_offset_s", "fps"):
        value = getattr(part, key)
        if value is not None:
            encoded[key] = value
    return encoded


def _decode_content(content: Any) -> tuple[ContentPart, ...]:
    if isinstance(content, str):
        return (Text(content),) if content else ()
    if not isinstance(content, list):
        return ()
    parts: list[ContentPart] = []
    for raw in content:
        if not isinstance(raw, Mapping):
            continue
        kind = raw.get("type")
        if kind == "text":
            text = raw.get("text")
            if isinstance(text, str) and text:
                parts.append(Text(text))
        elif kind == "image_url":
            image = raw.get("image_url")
            image = {"url": image} if isinstance(image, str) else image
            if not isinstance(image, Mapping) or not isinstance(image.get("url"), str):
                raise ValueError("image_url content requires image_url.url")
            media_type, data, url = _decode_data_url(str(image["url"]))
            detail = image.get("detail")
            parts.append(
                ImagePart(
                    data=data,
                    url=url,
                    media_type=media_type or "image/png",
                    detail=(detail if detail in ("auto", "low", "high") else None),
                )
            )
        elif kind == VIDEO_CONTENT_TYPE:
            parts.append(_decode_video(raw.get(VIDEO_CONTENT_TYPE)))
        elif kind == "input_audio":
            audio = raw.get("input_audio")
            if not isinstance(audio, Mapping) or not isinstance(audio.get("data"), str):
                raise ValueError("input_audio content requires base64 data")
            fmt = str(audio.get("format", "wav")).lower()
            media_type = {"wav": "audio/wav", "mp3": "audio/mpeg"}.get(fmt, f"audio/{fmt}")
            parts.append(AudioPart(_decode_base64(str(audio["data"])), media_type))
        elif kind == "file":
            file = raw.get("file")
            if not isinstance(file, Mapping):
                raise ValueError("file content requires a file object")
            source = file.get("file_data", file.get("file_url"))
            if not isinstance(source, str):
                raise ValueError("file content requires file_data or file_url")
            media_type, data, url = _decode_data_url(source)
            parts.append(
                DocumentPart(
                    data=data,
                    url=url,
                    media_type=media_type or "application/pdf",
                    filename=(str(file["filename"]) if file.get("filename") is not None else None),
                )
            )
    return tuple(parts)


def _decode_data_url(value: str) -> tuple[str | None, bytes | None, str | None]:
    if not value.startswith("data:"):
        return None, None, value
    header, separator, payload = value.partition(",")
    if not separator or ";base64" not in header:
        raise ValueError("inline multimodal content must use a base64 data URL")
    media_type = header[5:].split(";", 1)[0]
    return media_type, _decode_base64(payload), None


def _decode_base64(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("multimodal content contains invalid base64 data") from exc


def _data_url(media_type: str, data: bytes) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


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


def request_from_openai(
    body: Mapping[str, Any], *, context_tuning: Any = None
) -> tuple[str, GenerationRequest, bool]:
    """Decode an OpenAI chat-completions request body.

    Args:
        body: The parsed request JSON.
        context_tuning: Default ``ContextTuning`` for a request whose context extension
            omits its own ``tuning``. The gateway supplies the deployment's configured
            tuning, so wire callers inherit it rather than always falling back to the
            library defaults. Typed opaquely on purpose: the sidecar is a codec and does
            not import the context implementation, so it forwards the object onward
            without inspecting it.

    Returns:
        A ``(target, request, stream)`` triple. ``target`` is the ``model`` field taken
        verbatim — an AnyInfer target *is* an OpenAI model string (invariant 3), which is
        what makes federation free.
    """
    target = str(body.get("model", "")).strip()

    # Refused, not ignored. The codec's rule elsewhere is that telling the client beats
    # silently applying the gateway's default, and `n` was reserved but never read — so
    # n=3 returned one choice with no error. The companion `logprobs` refusal is gone:
    # the normalized result now carries log-probabilities, so the field decodes instead.
    requested_choices = body.get("n")
    if requested_choices is not None and requested_choices != 1:
        raise ValueError(
            f"n={requested_choices!r} is not supported: AnyInfer returns one choice per "
            "request. Use the anyinfer_arena extension to fan out across targets."
        )

    sampling = Sampling(
        temperature=_opt_float(body.get("temperature")),
        top_p=_opt_float(body.get("top_p")),
        max_output_tokens=_opt_int(body.get("max_completion_tokens", body.get("max_tokens"))),
        stop=_decode_stop(body.get("stop")),
        seed=_opt_int(body.get("seed")),
        presence_penalty=_opt_float(body.get("presence_penalty")),
        frequency_penalty=_opt_float(body.get("frequency_penalty")),
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
        reasoning=_decode_reasoning_effort(body.get("reasoning_effort")),
        history=_decode_history(body.get(HISTORY_FIELD)),
        cache=_decode_cache(body.get(CACHE_FIELD)),
        arena=_decode_arena(body.get(ARENA_FIELD)),
        context=_decode_context(body.get(CONTEXT_FIELD), context_tuning),
        provider_options=_decode_passthrough(body),
        metadata={k: str(v) for k, v in (body.get("metadata") or {}).items()},
        logprobs=_decode_logprobs(body),
    )
    return target, request, bool(body.get("stream"))


def _decode_logprobs(body: Mapping[str, Any]) -> int | None:
    """Collapse the dialect's two log-probability fields into one normalized count.

    OpenAI splits the ask across a boolean and a count, and only the boolean turns the
    feature on — ``top_logprobs`` without ``logprobs: true`` is an error upstream. The
    normalized request has one field, so the pair collapses: absent or false means no ask,
    true means the count (defaulting to zero, "the chosen token only").

    Raises:
        ValueError: If ``top_logprobs`` was sent without ``logprobs: true``, or the pair
            is not the documented boolean-and-integer. Refused rather than reinterpreted,
            because guessing which half the caller meant is how a request gets billed for
            data nobody asked for.
    """
    enabled = body.get("logprobs")
    count = body.get("top_logprobs")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("logprobs must be true or false")
    if count is not None and (not isinstance(count, int) or isinstance(count, bool)):
        raise ValueError("top_logprobs must be an integer")
    if not enabled:
        if count is not None:
            raise ValueError("top_logprobs requires logprobs: true")
        return None
    return count or 0


def _decode_reasoning_effort(raw: Any) -> ReasoningEffort | None:
    """Decode OpenAI's ``reasoning_effort`` into the normalized effort level.

    Typed rather than passed through, so the core's cross-provider translation engages
    for sidecar callers too — an Anthropic thinking budget, a Gemini thinking config.
    Passing it through verbatim silently did nothing for every non-OpenAI dialect.

    ``none`` is accepted alongside the four effort levels because OpenAI's own vocabulary
    accepts it on current models: a stock client that worked against this gateway by
    passthrough must not start getting a 400 for speaking the dialect the gateway claims
    to project. It decodes to a request for reasoning *off*, which each descriptor spells
    in its provider's own terms.

    Raises:
        ValueError: The value is not one of the normalized levels. Refused rather than
            dropped: now that the field is reserved, silently ignoring an unrecognized
            value would tell the caller nothing while quietly changing what the model was
            asked to do.
    """
    if raw is None:
        return None
    if raw in ("none", "minimal", "low", "medium", "high"):
        return cast("ReasoningEffort", raw)
    raise ValueError(
        f"reasoning_effort must be one of none, minimal, low, medium, high (got {raw!r})"
    )


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


def _decode_arena(raw: Any) -> ArenaPolicy | None:
    """Decode the complete arena policy extension without applying it in the codec."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"{ARENA_FIELD} must be an object")
    known = {
        "targets",
        "strategy",
        "judge_target",
        "instructions",
        "concurrency",
        "min_candidates",
        "reveal_targets",
        "memoize_tools",
    }
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{ARENA_FIELD} has unknown key(s): {', '.join(sorted(unknown))}")
    targets = raw.get("targets")
    if (
        not isinstance(targets, list)
        or not targets
        or not all(isinstance(item, str) and item for item in targets)
    ):
        raise ValueError(f"{ARENA_FIELD}.targets must be a non-empty array of strings")
    fields = dict(raw)
    fields["targets"] = tuple(targets)
    try:
        return ArenaPolicy(**fields)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{ARENA_FIELD} is invalid: {exc}") from exc


def _decode_context(raw: Any, default_tuning: Any = None) -> Any:
    """Decode the context extension; reduction remains in the core client."""
    return decode_context_request(raw, default_tuning=default_tuning)


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
        raise ValueError(f"{HISTORY_FIELD} has unknown key(s): {', '.join(sorted(unknown))}")
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
        options.update({str(k): dict(v) for k, v in namespaced.items() if isinstance(v, Mapping)})
    if extra:
        options.setdefault("*", dict(extra))
    return options


def _opt_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _opt_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


# ---- request: AnyInfer -> OpenAI (round-trip verification) ---------------------------


def encode_logprobs(logprobs: Sequence[TokenLogprob]) -> dict[str, Any]:
    """Encode normalized log-probabilities into the dialect's ``logprobs`` object.

    Args:
        logprobs: The result's tokens, in generation order.

    Returns:
        The ``{"content": [...]}`` object a chat-completions choice carries. ``bytes`` is
        emitted as ``null`` when the upstream provider did not report it, rather than
        being reconstructed by encoding the token: a client comparing byte offsets would
        then be trusting our guess about the provider's tokenizer.
    """
    return {"content": [_encode_logprob(token, with_top=True) for token in logprobs]}


def _encode_logprob(token: TokenLogprob, *, with_top: bool) -> dict[str, Any]:
    """Encode one token entry, with its alternatives when this is a top-level one."""
    entry: dict[str, Any] = {
        "token": token.token,
        "logprob": token.logprob,
        "bytes": list(token.bytes) if token.bytes is not None else None,
    }
    if with_top:
        entry["top_logprobs"] = [
            _encode_logprob(alternative, with_top=False) for alternative in token.top
        ]
    return entry


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

        modal = any(
            isinstance(p, ImagePart | DocumentPart | AudioPart | VideoPart)
            for p in message.content
        )
        if modal:
            modal_content: list[dict[str, Any]] = []
            for part in message.content:
                if isinstance(part, Text):
                    modal_content.append({"type": "text", "text": part.text})
                elif isinstance(part, ImagePart):
                    image_url = part.url or _data_url(part.media_type, part.data or b"")
                    image: dict[str, Any] = {"url": image_url}
                    if part.detail is not None:
                        image["detail"] = part.detail
                    modal_content.append({"type": "image_url", "image_url": image})
                elif isinstance(part, DocumentPart):
                    file: dict[str, Any] = {}
                    if part.data is not None:
                        file["file_data"] = _data_url(part.media_type, part.data)
                    else:
                        file["file_url"] = part.url
                    if part.filename is not None:
                        file["filename"] = part.filename
                    modal_content.append({"type": "file", "file": file})
                elif isinstance(part, VideoPart):
                    modal_content.append(
                        {"type": VIDEO_CONTENT_TYPE, VIDEO_CONTENT_TYPE: _encode_video(part)}
                    )
                elif isinstance(part, AudioPart):
                    fmt = "mp3" if part.media_type in ("audio/mp3", "audio/mpeg") else "wav"
                    modal_content.append(
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(part.data).decode("ascii"),
                                "format": fmt,
                            },
                        }
                    )
            content: str | list[dict[str, Any]] | None = modal_content
        else:
            content = "".join(p.text for p in message.content if isinstance(p, Text))
        entry: dict[str, Any] = {"role": message.role, "content": content}
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
            if not content:
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
    if sampling.seed is not None:
        body["seed"] = sampling.seed
    if sampling.presence_penalty is not None:
        body["presence_penalty"] = sampling.presence_penalty
    if sampling.frequency_penalty is not None:
        body["frequency_penalty"] = sampling.frequency_penalty

    if request.logprobs is not None:
        # Back out to the dialect's two fields, mirroring `_decode_logprobs`. `0` means
        # "chosen token only", which the dialect spells as the boolean with no count.
        body["logprobs"] = True
        if request.logprobs > 0:
            body["top_logprobs"] = request.logprobs

    if request.reasoning is not None:
        body["reasoning_effort"] = request.reasoning

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
    if request.cache is not None:
        body[CACHE_FIELD] = {
            "mode": request.cache.mode,
            "min_segment_tokens": request.cache.min_segment_tokens,
            "max_marks": request.cache.max_marks,
            "include_tools": request.cache.include_tools,
            "include_system": request.cache.include_system,
        }
    if request.arena is not None:
        body[ARENA_FIELD] = {
            "targets": list(request.arena.targets),
            "strategy": request.arena.strategy,
            "judge_target": request.arena.judge_target,
            "instructions": request.arena.instructions,
            "concurrency": request.arena.concurrency,
            "min_candidates": request.arena.min_candidates,
            "reveal_targets": request.arena.reveal_targets,
            "memoize_tools": request.arena.memoize_tools,
        }
    if request.context is not None:
        body[CONTEXT_FIELD] = encode_context_request(request.context)

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
    if result.logprobs:
        body["choices"][0]["logprobs"] = encode_logprobs(result.logprobs)
    usage = _encode_usage(result.usage)
    if usage is not None:
        body["usage"] = usage
    if include_manifest and result.manifest is not None:
        body[MANIFEST_FIELD] = result.manifest.to_dict()
    if result.arena is not None:
        body[ARENA_FIELD] = arena_to_dict(result.arena)
    if result.context_reduction is not None:
        body[CONTEXT_FIELD] = result.context_reduction.to_dict()
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
    same envelope the trailing usage chunk uses, so a reader that has never heard of the
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
    it, which is exactly the bug the core's own parser is written to avoid.
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
    if result.arena is not None:
        yield {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": stamp,
            "model": model,
            "choices": [],
            ARENA_FIELD: arena_to_dict(result.arena),
        }
    if result.context_reduction is not None:
        yield {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": stamp,
            "model": model,
            "choices": [],
            CONTEXT_FIELD: result.context_reduction.to_dict(),
        }
