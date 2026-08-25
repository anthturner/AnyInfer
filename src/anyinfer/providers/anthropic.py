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

import json
import time
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import aclosing
from typing import Any

import httpx2

from ..errors import ProviderError, StreamProtocolError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import (
    DiscoveredModel,
    Feature,
    Health,
    ModelCapabilities,
    RateLimitHeaders,
    Sourced,
)
from ..types.events import (
    CitationDelta,
    ReasoningDelta,
    ServerToolDelta,
    ServerToolSource,
    TextDelta,
    ToolCallDelta,
    UsageUpdate,
)
from ..types.messages import (
    AudioPart,
    DocumentPart,
    ImagePart,
    Message,
    Text,
    ToolCall,
    ToolResult,
    VideoPart,
)
from ..types.operations import (
    BatchHandle,
    BatchLine,
    BatchReport,
    BatchResult,
    BatchStatus,
)
from ..types.requests import (
    ReasoningEffort,
    ResolvedTarget,
    Sampling,
    ServerToolKind,
    ServerToolSpec,
    ToolSpec,
)
from ..types.results import (
    DETAIL_MAX_CHARS,
    Citation,
    ErrorInfo,
    FinishReason,
    Generation,
    ServerToolUse,
    Timing,
    Usage,
)
from ._multimodal import base64_data, unsupported
from .base import (
    AdapterEvent,
    AdapterFinal,
    BatchWireRequest,
    ProviderConfig,
    WireRequest,
)
from .http import build_client, classify_status, map_transport_error, read_error_detail, read_int
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

_EPHEMERAL = {"type": "ephemeral"}
"""The only ``cache_control`` type this API defines. Sent verbatim on a marked block."""

_SYSTEM_SEGMENT = -1
"""Mirror of `anyinfer.capabilities.cache.SYSTEM_SEGMENT`.

Repeated rather than imported: an adapter importing from the capability layer would invert
the dependency the layering forbids, and these two integers are part of the adapter
contract documented on ``WireRequest.cache_marks``.
"""

_TOOLS_SEGMENT = -2
"""Mirror of `anyinfer.capabilities.cache.TOOLS_SEGMENT`; see `_SYSTEM_SEGMENT`."""

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
            proxy=config.proxy,
            verify=config.verify,
            client_cert=config.client_cert,
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
        """Translate a wire request into a Messages API body."""
        system_text, messages = _split_system(req.messages)
        marks = set(req.cache_marks)

        payload: dict[str, Any] = {
            "model": req.model,
            "messages": [
                self._encode_message(m, citations_enabled=req.cite_documents)
                for m in messages
            ],
            "max_tokens": req.sampling.max_output_tokens or _DEFAULT_MAX_TOKENS,
            "stream": True,
        }
        if system_text:
            # A marked system block becomes a content-block list, which is the only form
            # `cache_control` may be attached to; unmarked it stays a plain string.
            payload["system"] = (
                [{"type": "text", "text": system_text, "cache_control": _EPHEMERAL}]
                if _SYSTEM_SEGMENT in marks
                else system_text
            )
        if marks:
            self._mark_messages(payload["messages"], req, marks)

        self._apply_sampling(payload, req.sampling)

        # Server tools lead: they are typed blocks the API matches by `type`, not by name,
        # and keeping them first leaves the caller's own declarations contiguous for the
        # cache mark below, which covers everything before the *last* entry.
        tools: list[dict[str, Any]] = [_encode_server_tool(spec) for spec in req.server_tools]
        tools.extend(self._encode_tool(t) for t in req.tools)
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
            if _TOOLS_SEGMENT in marks:
                # Anthropic caches tool declarations by marking the *last* one: a mark
                # covers everything before it, and the tool block precedes the messages.
                tools[-1] = {**tools[-1], "cache_control": _EPHEMERAL}
            payload["tools"] = tools

        payload.update(req.reasoning_wire)
        payload.update(req.extra_options)
        return payload

    def _mark_messages(
        self,
        encoded: list[dict[str, Any]],
        req: WireRequest,
        marks: set[int],
    ) -> None:
        """Attach ``cache_control`` to the last content block of each marked message.

        Marks arrive as indices into the *request's* messages, which include the system
        turns this dialect hoists into a top-level field. They are translated to indices
        into the encoded list here rather than in the core, because which messages survive
        encoding is a fact about this dialect.
        """
        offsets: dict[int, int] = {}
        encoded_index = 0
        for index, message in enumerate(req.messages):
            if message.role == "system":
                continue
            offsets[index] = encoded_index
            encoded_index += 1

        for mark in sorted(m for m in marks if m >= 0):
            position = offsets.get(mark)
            if position is None or position >= len(encoded):
                continue
            blocks = encoded[position]["content"]
            if blocks:
                blocks[-1] = {**blocks[-1], "cache_control": _EPHEMERAL}

    def _apply_sampling(self, payload: dict[str, Any], sampling: Sampling) -> None:
        """Add only the sampling fields the caller actually set."""
        if sampling.temperature is not None:
            payload["temperature"] = sampling.temperature
        if sampling.top_p is not None:
            payload["top_p"] = sampling.top_p
        if sampling.stop:
            payload["stop_sequences"] = list(sampling.stop)

    def _encode_message(
        self, message: Message, *, citations_enabled: bool = False
    ) -> dict[str, Any]:
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
            elif isinstance(part, ImagePart):
                source = (
                    {"type": "url", "url": part.url}
                    if part.url is not None
                    else {
                        "type": "base64",
                        "media_type": part.media_type,
                        "data": base64_data(part.data or b""),
                    }
                )
                blocks.append({"type": "image", "source": source})
            elif isinstance(part, DocumentPart):
                source = (
                    {"type": "url", "url": part.url}
                    if part.url is not None
                    else {
                        "type": "base64",
                        "media_type": part.media_type,
                        "data": base64_data(part.data or b""),
                    }
                )
                document: dict[str, Any] = {"type": "document", "source": source}
                if citations_enabled:
                    # Request-side opt-in: without it the model answers without
                    # attributions, and Anthropic bills a cited answer differently.
                    document["citations"] = {"enabled": True}
                blocks.append(document)
            elif isinstance(part, AudioPart):
                raise unsupported(self.provider_id, "audio")
            elif isinstance(part, VideoPart):
                raise unsupported(self.provider_id, "video")

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
            if isinstance(block, Mapping) and block.get("type") == "server_tool_use":
                tool_kind = _SERVER_TOOL_KINDS.get(str(block.get("name", "")))
                if tool_kind is not None:
                    state.server_tools[tool_kind] = state.server_tools.get(tool_kind, 0) + 1
                    yield ServerToolDelta(kind=tool_kind, status="started")
                return
            if isinstance(block, Mapping) and block.get("type") in _SERVER_TOOL_RESULTS:
                yield _server_tool_result(block)
                return
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
                    state.answer_length += len(text)
                    yield TextDelta(text)
            elif delta_type == "citations_delta":
                citation = _parse_citation(delta.get("citation"), state)
                if citation is not None:
                    yield CitationDelta(citation)
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

    # ---- batches ---------------------------------------------------------------------
    #
    # Anthropic's Message Batches API takes the whole job as JSON — no file upload, no
    # separate download endpoint for the manifest — so this is the shape the protocol was
    # designed against. Each line's `params` is exactly the body a live request would have
    # sent, built by the same `build_payload`, minus the streaming flag a batch cannot use.

    async def submit_batch(self, req: BatchWireRequest) -> BatchHandle:
        """Submit to ``POST /v1/messages/batches``.

        Raises:
            anyinfer.errors.ProviderError: The provider refused the submission.
        """
        payload = {
            "requests": [
                {"custom_id": custom_id, "params": self._batch_params(line)}
                for custom_id, line in req.lines
            ]
        }
        body = await self._batch_call("POST", "/v1/messages/batches", json=payload)
        return BatchHandle(
            batch_id=str(body.get("id", "")),
            provider_id=self.provider_id,
            model=req.model,
            line_count=len(req.lines),
            submitted_at=time.time(),
        )

    def _batch_params(self, line: WireRequest) -> dict[str, Any]:
        """One line's request body: the live shape, with streaming removed.

        A batch is answered whole, so `stream` is meaningless there and Anthropic rejects
        it. Everything else — tools, system, sampling, cache marks — is identical, which is
        the point of reusing `build_payload` rather than writing a second translator.
        """
        params = self.build_payload(line)
        params.pop("stream", None)
        return params

    async def batch_status(self, handle: BatchHandle) -> BatchReport:
        """Report state from ``GET /v1/messages/batches/{id}``."""
        body = await self._batch_call("GET", f"/v1/messages/batches/{handle.batch_id}")
        return self._report(handle, body)

    async def cancel_batch(self, handle: BatchHandle) -> BatchReport:
        """Ask the provider to cancel, via ``POST .../cancel``."""
        body = await self._batch_call(
            "POST", f"/v1/messages/batches/{handle.batch_id}/cancel"
        )
        return self._report(handle, body)

    def _report(self, handle: BatchHandle, body: Mapping[str, Any]) -> BatchReport:
        """Normalize one batch object into a report."""
        counts = body.get("request_counts")
        counts = counts if isinstance(counts, Mapping) else {}
        status = _BATCH_STATUSES.get(str(body.get("processing_status", "")), "in_progress")
        if status == "completed" and body.get("cancel_initiated_at"):
            status = "cancelled"
        return BatchReport(
            handle=handle,
            status=status,
            completed=int(counts.get("succeeded", 0) or 0),
            failed=int(counts.get("errored", 0) or 0) + int(counts.get("expired", 0) or 0),
        )

    async def fetch_batch(self, handle: BatchHandle) -> BatchResult:
        """Download finished lines from the batch's ``results_url``.

        Raises:
            anyinfer.errors.ProviderError: The batch has not finished, or the download
                failed. Refused rather than returning an empty result, which a caller
                would read as "every line failed".
        """
        body = await self._batch_call("GET", f"/v1/messages/batches/{handle.batch_id}")
        report = self._report(handle, body)
        if not report.finished:
            raise ProviderError(
                f"batch {handle.batch_id} is {report.status}, not finished",
                provider=self.provider_id,
                retryable=True,
                hint="poll batch_status until it reports finished",
            )
        results_url = body.get("results_url")
        if not isinstance(results_url, str) or not results_url:
            return BatchResult(handle=handle, status=report.status)

        try:
            response = await self._client.get(results_url)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                headers=response.headers,
            )
        return BatchResult(
            handle=handle,
            status=report.status,
            lines=tuple(self._parse_lines(response.text)),
        )

    def _parse_lines(self, jsonl: str) -> Iterable[BatchLine]:
        """Parse the JSONL manifest, one line per submitted request."""
        for raw in jsonl.splitlines():
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(entry, Mapping):
                continue
            yield self._parse_line(entry)

    def _parse_line(self, entry: Mapping[str, Any]) -> BatchLine:
        """Turn one manifest entry into a line, replaying it through the event path.

        A succeeded line's `message` is byte-identical to a non-streaming response, so it
        is fed through the same chunk translator a live call uses — which is what makes a
        batched answer carry the same tool calls, usage, and finish reason a live one
        would, rather than a reduced copy assembled here.
        """
        custom_id = str(entry.get("custom_id", ""))
        result = entry.get("result")
        if not isinstance(result, Mapping):
            return BatchLine(custom_id=custom_id, error=_batch_error("malformed result entry"))
        kind = str(result.get("type", ""))
        if kind != "succeeded":
            detail = result.get("error")
            reason = ""
            if isinstance(detail, Mapping):
                reason = str(detail.get("message", "") or detail.get("type", ""))
            return BatchLine(custom_id=custom_id, error=_batch_error(reason or kind))

        body = result.get("message")
        if not isinstance(body, Mapping):
            return BatchLine(custom_id=custom_id, error=_batch_error("result carried no message"))
        return BatchLine(custom_id=custom_id, result=_generation_from_message(body))

    async def _batch_call(
        self, method: str, path: str, *, json: Any = None
    ) -> Mapping[str, Any]:
        """Issue one batch-control request, classifying failures the usual way.

        Raises:
            anyinfer.errors.ProviderError: The call failed or returned a non-object body.
        """
        try:
            response = await self._client.request(method, path, json=json)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                headers=response.headers,
            )
        body = response.json()
        if not isinstance(body, Mapping):
            raise StreamProtocolError(
                "anthropic returned a non-object batch body", provider=self.provider_id
            )
        return body

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


class _StreamState:
    """Tracks stop reason, usage, and the mapping from block index to tool slot."""

    __slots__ = (
        "answer_length",
        "cited_through",
        "finish_reason",
        "server_tools",
        "tool_slots",
        "usage",
    )

    def __init__(self) -> None:
        self.finish_reason: FinishReason = "stop"
        self.usage = Usage()
        self.tool_slots: dict[int, int] = {}
        self.server_tools: dict[ServerToolKind, int] = {}
        """How many times each server-side tool started, counted from its own blocks.

        Anthropic also reports a `server_tool_use` total in usage, but only for search;
        counting the blocks covers every kind uniformly and needs no per-kind branch."""
        self.answer_length = 0
        self.cited_through = 0
        """How far into the answer the citations so far have reached.

        Anthropic reports character offsets into the *cited document*, never into its own
        answer, but it emits each `citations_delta` immediately after the text that
        citation supports. So the span in the answer is recoverable — it runs from wherever
        the last citation ended to wherever the text has reached now — and recovering it is
        what lets a caller highlight the sentence rather than only name the source."""

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
            server_tool_uses=tuple(
                ServerToolUse(kind=kind, uses=count)
                for kind, count in sorted(self.server_tools.items())
            ),
        )


def _option_str(options: Mapping[str, Any], key: str) -> str:
    """Read one option as a stripped string, treating anything else as absent."""
    value = options.get(key)
    return value.strip() if isinstance(value, str) else ""


_BATCH_STATUSES: Mapping[str, BatchStatus] = {
    # Anthropic reports two processing states and nothing else; per-line outcomes live in
    # the manifest rather than in the batch's own status, which is why `ended` maps to
    # `completed` even when every line errored.
    "in_progress": "in_progress",
    "canceling": "in_progress",
    "ended": "completed",
}


def _batch_error(detail: str) -> ErrorInfo:
    """Record one line's failure without inventing a status code for it.

    A batch line's failure is reported in the manifest, not as an HTTP response, so there
    is no status to carry — and stamping a plausible one would be a fact this library made
    up about somebody else's system.
    """
    return ErrorInfo(
        type_name="ProviderError",
        provider="anthropic",
        phase="generate",
        retryable=False,
        http_status=None,
        detail=detail[:DETAIL_MAX_CHARS],
    )


def _generation_from_message(message: Mapping[str, Any]) -> Generation:
    """Assemble a `Generation` from one batched message body.

    Reuses this module's own block reader, so a batched answer carries the tool calls,
    usage, and finish reason a live one would rather than a second, drifting parser.

    Assembled here rather than through the router's attempt buffer, deliberately: an
    adapter must not import from `anyinfer.routing` — the "adapters never orchestrate"
    contract enforces exactly that — and a manifest line has nothing to orchestrate anyway.
    The routing fields a live result carries are genuinely absent: nothing routed, and no
    clock of ours ran on this side.
    """
    state = _StreamState()
    text: list[str] = []
    calls: list[ToolCall] = []
    citations: list[Citation] = []
    usage = Usage()

    for event in _events_from_message(message, state):
        if isinstance(event, TextDelta):
            text.append(event.text)
        elif isinstance(event, UsageUpdate):
            usage = usage.merge(event.usage)
        elif isinstance(event, CitationDelta):
            citations.append(event.citation)
        elif isinstance(event, ToolCallDelta):
            calls.append(
                ToolCall(
                    id=event.call_id or f"call_{event.index}",
                    name=event.name or "",
                    arguments=_batch_arguments(event.arguments_fragment),
                )
            )

    final = state.finalize()
    if final.usage is not None:
        usage = usage.merge(final.usage)
    finish_reason = final.finish_reason
    if calls and finish_reason == "stop":
        finish_reason = "tool_calls"
    return Generation(
        text="".join(text),
        structured=None,
        tool_calls=tuple(calls),
        target=ResolvedTarget(provider_id="anthropic", model=str(message.get("model", ""))),
        finish_reason=finish_reason,
        usage=usage.normalized(),
        timing=Timing(started_at=0.0, total_ms=0.0),
        citations=tuple(citations),
        server_tool_uses=final.server_tool_uses,
    )


def _batch_arguments(fragment: str) -> Mapping[str, Any]:
    """Parse one batched tool call's arguments, tolerating an unparseable payload.

    A live call's arguments arrive as streamed fragments the router reassembles; here the
    whole object arrives at once. Either way an argument payload that is not a JSON object
    yields an empty one rather than failing the line — the rest of the answer is still
    worth returning.
    """
    try:
        parsed = json.loads(fragment or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _events_from_message(
    message: Mapping[str, Any], state: _StreamState
) -> Iterable[TextDelta | ReasoningDelta | ToolCallDelta | CitationDelta | UsageUpdate]:
    """Translate a buffered message body into the events a stream would have produced."""
    usage = _parse_usage(message.get("usage"))
    if usage is not None:
        state.usage = state.usage.merge(usage)
        yield UsageUpdate(usage)
    reason = message.get("stop_reason")
    if isinstance(reason, str):
        state.finish_reason = _STOP_REASONS.get(reason, "other")

    content = message.get("content")
    if not isinstance(content, list):
        return
    for index, block in enumerate(content):
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        if kind == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                state.answer_length += len(text)
                yield TextDelta(text)
            for raw in block.get("citations") or ():
                citation = _parse_citation(raw, state)
                if citation is not None:
                    yield CitationDelta(citation)
        elif kind == "thinking":
            thinking = block.get("thinking")
            if isinstance(thinking, str) and thinking:
                yield ReasoningDelta(thinking)
        elif kind == "tool_use":
            yield ToolCallDelta(
                index=state.tool_slot(index),
                call_id=str(block.get("id", "")) or None,
                name=str(block.get("name", "")) or None,
                arguments_fragment=json.dumps(block.get("input") or {}),
            )
        elif kind == "server_tool_use":
            tool_kind = _SERVER_TOOL_KINDS.get(str(block.get("name", "")))
            if tool_kind is not None:
                state.server_tools[tool_kind] = state.server_tools.get(tool_kind, 0) + 1
                yield ServerToolDelta(kind=tool_kind, status="started")
        elif kind in _SERVER_TOOL_RESULTS:
            yield _server_tool_result(block)


_SERVER_TOOL_KINDS: Mapping[str, ServerToolKind] = {
    "web_search": "web_search",
    "code_execution": "code_execution",
}
"""The tool *name* on a `server_tool_use` block, mapped back to the normalized kind."""

_SERVER_TOOL_RESULTS: Mapping[str, ServerToolKind] = {
    "web_search_tool_result": "web_search",
    "code_execution_tool_result": "code_execution",
}
"""Result block types, which name their tool in the type rather than in a field."""

def _server_tool_result(block: Mapping[str, Any]) -> ServerToolDelta:
    """Decode one server-tool result block into the event that carries its payload.

    Anthropic names the tool in the block *type* rather than in a field, and shapes the
    payload differently per tool: a search returns a list of result entries, while a code
    execution returns one object with stdout, stderr, and a return code. Both failure
    shapes are a `content` object whose own type ends in `_error`.
    """
    tool_kind = _SERVER_TOOL_RESULTS[str(block.get("type"))]
    content = block.get("content")
    if isinstance(content, Mapping) and str(content.get("type", "")).endswith("_error"):
        return ServerToolDelta(
            kind=tool_kind,
            status="failed",
            detail=str(content.get("error_code", "") or ""),
        )
    if tool_kind == "web_search":
        entries = content if isinstance(content, Sequence) and not isinstance(content, str) else ()
        return ServerToolDelta(
            kind=tool_kind,
            status="completed",
            sources=tuple(
                ServerToolSource(
                    url=str(entry.get("url", "") or ""),
                    title=str(entry.get("title", "") or ""),
                )
                for entry in entries
                if isinstance(entry, Mapping) and entry.get("url")
            ),
        )
    if isinstance(content, Mapping):
        # stderr is appended rather than dropped: a failed execution's message is the
        # useful half, and a non-zero return code is not itself a tool failure.
        parts = [
            str(content.get(field, "") or "") for field in ("stdout", "stderr")
        ]
        return ServerToolDelta(
            kind=tool_kind, status="completed", output="".join(parts)
        )
    return ServerToolDelta(kind=tool_kind, status="completed")


_ANTHROPIC_SERVER_TOOLS: Mapping[str, tuple[str, str]] = {
    # (wire type, tool name). The type carries a date because Anthropic versions these
    # tools in the type itself — a pin recorded in the contract snapshot, not a guess.
    "web_search": ("web_search_20250305", "web_search"),
    "code_execution": ("code_execution_20250522", "code_execution"),
}


def _encode_server_tool(spec: ServerToolSpec) -> dict[str, Any]:
    """Encode one server tool as Anthropic's dated tool block."""
    wire_type, name = _ANTHROPIC_SERVER_TOOLS[spec.kind]
    encoded: dict[str, Any] = {"type": wire_type, "name": name}
    if spec.max_uses is not None:
        encoded["max_uses"] = spec.max_uses
    return encoded


def _parse_citation(raw: Any, state: _StreamState) -> Citation | None:
    """Translate one Anthropic citation object into a normalized `Citation`.

    Anthropic publishes several location shapes — character, page, and content-block
    indices into the cited document — which differ only in the unit they count in. None of
    them is an offset into the answer, so the source location travels as ``quoted_text``
    plus the document's identity, and the *answer* span is derived from where the stream
    had reached when this citation arrived (see `_StreamState.cited_through`).

    Returns ``None`` for a shape carrying neither quoted text nor a document identity,
    since a citation that names nothing is not worth surfacing.
    """
    if not isinstance(raw, Mapping):
        return None
    quoted = raw.get("cited_text")
    document_index = raw.get("document_index")
    title = raw.get("document_title")
    if not isinstance(quoted, str) and not isinstance(document_index, int):
        return None
    start = state.cited_through
    end = state.answer_length
    state.cited_through = end
    return Citation(
        start_index=start,
        end_index=end,
        quoted_text=quoted if isinstance(quoted, str) else "",
        document_index=document_index if isinstance(document_index, int) else None,
        title=title if isinstance(title, str) else "",
    )


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

    usage = Usage(
        input_tokens=read_int(payload, "input_tokens"),
        output_tokens=read_int(payload, "output_tokens"),
        cache_read_tokens=read_int(payload, "cache_read_input_tokens"),
        cache_write_tokens=read_int(payload, "cache_creation_input_tokens"),
    )
    return usage if usage != Usage() else None


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto extended thinking.

    Anthropic budgets thinking in *tokens* rather than naming effort levels, so each level
    maps to a budget. ``minimal`` disables thinking outright.
    """
    if effort is None:
        return {}
    if effort in ("none", "minimal"):
        # Anthropic has no "think as little as possible" setting, so `minimal` and `none`
        # reach the same wire form by different routes: `minimal` because disabled is the
        # closest available level, `none` because disabled is exactly what was asked for.
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
    | Feature.CACHE_PLACEMENT
    | Feature.CITATIONS
    | Feature.WEB_SEARCH
    | Feature.CODE_EXECUTION
)


_RATE_LIMIT_HEADERS = RateLimitHeaders(
    requests_remaining="anthropic-ratelimit-requests-remaining",
    requests_reset="anthropic-ratelimit-requests-reset",
    tokens_remaining="anthropic-ratelimit-tokens-remaining",
    tokens_reset="anthropic-ratelimit-tokens-reset",
    limit_requests="anthropic-ratelimit-requests-limit",
    limit_tokens="anthropic-ratelimit-tokens-limit",
)
"""Anthropic's rate-limit dialect. Resets are RFC 3339 instants, not durations.

Recorded in ``contracts/anthropic.md``. The ``tokens`` pair is read rather than the
separate ``input-tokens`` and ``output-tokens`` pairs because Anthropic documents it as the
*most restrictive* limit currently in effect, which is the one a client about to send a
request needs, and the only one whose meaning does not change with the tier.
"""

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
                env_var="ANTHROPIC_API_KEY",
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
                env_var="ANTHROPIC_OAUTH_TOKEN",
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
    ignored_parameters=("seed", "presence_penalty", "frequency_penalty", "logprobs"),
    operations=frozenset({"generation", "batch"}),
    server_tools=frozenset({"web_search", "code_execution"}),
    default_capabilities=ModelCapabilities(features=Sourced(_ANTHROPIC_FEATURES, "default")),
    # Per-segment `cache_control` marks, up to four breakpoints, with a documented
    # minimum cacheable prefix. Recorded in contracts/anthropic.md.
    cache_mechanism="explicit",
    cache_max_marks=4,
    cache_min_tokens=1024,
    rate_limit_headers=_RATE_LIMIT_HEADERS,
)
"""Descriptor for the Anthropic provider."""
