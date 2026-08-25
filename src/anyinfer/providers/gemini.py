"""Google's Gemini API — the native ``generateContent`` protocol (`contracts/gemini.md`).

Deliberately the **native** protocol rather than Google's OpenAI-compatibility layer at
``/v1beta/openai/``. That layer is documented as beta and *silently ignores* parameters it
does not implement — the exact failure mode AnyInfer exists to eliminate, while thinking
levels, response schemas, safety settings, context caching, and grounding tools are
native-only or better supported here.

Five ways this dialect differs from the OpenAI shape, each handled below:

- **Turns are ``contents`` with ``parts``**, and the assistant role is spelled ``model``.
- **System prompts are a top-level ``systemInstruction``**, not a message.
- **Sampling lives under ``generationConfig``**, not at the top level.
- **Thinking is a level, not a budget**, and thinking tokens are billed as output but
  reported separately in ``usageMetadata.thoughtsTokenCount``.
- **Tool results are a ``functionResponse`` part on a user turn**, correlated by name
  (and id, when the model supplied one).

Thought signatures ride through unchanged: Gemini asks that reasoning parts be echoed
back verbatim in multi-turn conversations, so they are preserved rather than stripped.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Mapping, Sequence
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
from ..types.operations import EmbeddingCapabilities, EmbeddingInputIntent
from ..types.requests import ReasoningEffort, Sampling, ToolSpec
from ..types.results import FinishReason, Usage
from ._multimodal import base64_data
from .base import (
    AdapterEvent,
    AdapterFinal,
    EmbeddingWireRequest,
    EmbeddingWireResult,
    ProviderConfig,
    WireRequest,
)
from .http import (
    build_client,
    check_response_size,
    classify_status,
    map_transport_error,
    read_error_detail,
    read_int,
)
from .sse import iter_sse

__all__ = ["GeminiAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

_FINISH_REASONS: Mapping[str, FinishReason] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "IMAGE_SAFETY": "content_filter",
    "BLOCKED_SAFETY": "content_filter",
    "LANGUAGE": "content_filter",
    "MALFORMED_FUNCTION_CALL": "other",
    "FINISH_REASON_UNSPECIFIED": "other",
    "OTHER": "other",
}
"""Gemini's finish reasons are an open enum; unknown values normalize to ``other``."""

_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "format",
        "description",
        "nullable",
        "enum",
        "properties",
        "required",
        "items",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "propertyOrdering",
        "anyOf",
        "prefixItems",
        "additionalProperties",
        "title",
        "default",
    }
)
"""Keywords Gemini's response-schema subset accepts; anything else is dropped."""


_TASK_TYPES: Mapping[EmbeddingInputIntent, str] = {
    "query": "RETRIEVAL_QUERY",
    "document": "RETRIEVAL_DOCUMENT",
    "classification": "CLASSIFICATION",
    "clustering": "CLUSTERING",
}
"""Normalized intents mapped to Gemini ``taskType`` values (verified 2026-08-12).

Only models that document task types receive one; the current ``gemini-embedding-2``
does not (its guide says to use prompt instructions), so the adapter never sends it
there.
"""


class GeminiAdapter:
    """Adapter for the Gemini API's native content-generation protocol."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self.provider_id = config.provider_id
        headers = {"content-type": "application/json"}
        if config.api_key:
            headers["x-goog-api-key"] = config.api_key
        headers.update({k.lower(): v for k, v in config.headers.items()})
        self._client = build_client(
            base_url=(config.base_url or _DEFAULT_BASE_URL).rstrip("/"),
            headers=headers,
            timeout_s=config.timeout_s,
            transport=config.transport,
        )

    def _model_path(self, model: str, method: str) -> str:
        """Build the request path for one model and method.

        A subclass hook: Vertex addresses the same models by project and location, and
        that addressing is the *only* thing it changes about the request path.
        """
        return f"/models/{model}:{method}"

    def _request_headers(self) -> dict[str, str]:
        """Per-request headers beyond the client's defaults.

        Empty here — the API key is a client-level header. A subclass whose credential
        expires (Vertex's OAuth token) supplies it per request instead.
        """
        return {}

    @staticmethod
    def project_schema(schema: Mapping[str, Any]) -> Mapping[str, Any]:
        """Reduce a JSON Schema to the OpenAPI subset ``responseSchema`` accepts.

        Unsupported keywords are dropped rather than sent: Gemini rejects the whole
        request on an unknown field, and the core validates against the *canonical*
        schema afterwards regardless, so dropping a constraint costs strictness on the
        wire but never correctness in the result.
        """
        return _project(schema)

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List models from ``GET /models``, following page tokens.

        The listing reports real input and output limits, so context windows arrive with
        ``discovered`` provenance rather than being catalogued estimates.
        """
        models: list[DiscoveredModel] = []
        params: dict[str, Any] = {"pageSize": 1000}

        while True:
            try:
                response = await self._client.get("/models", params=params)
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
            models.extend(self._parse_model(e) for e in entries if isinstance(e, Mapping))

            token = payload.get("nextPageToken")
            if not isinstance(token, str) or not token:
                break
            params["pageToken"] = token

        return models

    def _parse_model(self, entry: Mapping[str, Any]) -> DiscoveredModel:
        """Read one listing entry, keeping the ``models/`` prefix off the id."""
        name = str(entry.get("name", ""))
        model_id = name.removeprefix("models/")

        features = Feature.STREAMING | Feature.SYSTEM_PROMPT | Feature.CACHE_USAGE
        methods = entry.get("supportedGenerationMethods")
        if isinstance(methods, list) and "generateContent" in methods:
            features |= Feature.TOOLS | Feature.JSON_SCHEMA | Feature.JSON_MODE
        if entry.get("thinking") is True:
            features |= Feature.REASONING

        return DiscoveredModel(
            id=model_id,
            capabilities=ModelCapabilities(
                context_window=_sourced_limit(entry.get("inputTokenLimit")),
                max_output_tokens=_sourced_limit(entry.get("outputTokenLimit")),
                features=Sourced(features, "discovered"),
            ),
        )

    async def health(self) -> Health:
        """Probe readiness with a bounded model listing."""
        try:
            response = await self._client.get("/models", params={"pageSize": 1})
        except httpx2.HTTPError as exc:
            return Health(ok=False, detail=str(exc)[:200])
        if response.status_code >= 400:
            return Health(ok=False, detail=f"HTTP {response.status_code}")
        return Health(ok=True)

    # ---- generation ------------------------------------------------------------------

    # ---- embedding ---------------------------------------------------------------------

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one embedding call against ``:batchEmbedContents``.

        The batch endpoint serves single inputs too, so one code path covers both. Task
        types map from the normalized intent vocabulary for models that accept them;
        ``gemini-embedding-2`` documents no ``taskType`` support (verified 2026-08-12:
        "use prompt instructions instead"), so the field is never sent to it.
        """
        model_ref = f"models/{req.model}"
        send_task_type = req.input_type is not None and not req.model.startswith(
            "gemini-embedding-2"
        )
        entry_extra: dict[str, Any] = {}
        if req.dimensions is not None:
            entry_extra["output_dimensionality"] = req.dimensions
        requests = []
        for text_input in req.inputs:
            entry: dict[str, Any] = {
                "model": model_ref,
                "content": {"parts": [{"text": text_input}]},
                **entry_extra,
            }
            if send_task_type and req.input_type is not None:
                entry["taskType"] = _TASK_TYPES[req.input_type]
            entry.update(req.extra_options)
            requests.append(entry)

        path = self._model_path(req.model, "batchEmbedContents")
        try:
            response = await self._client.post(
                path,
                json={"requests": requests},
                timeout=req.timeout_s,
                headers=self._request_headers(),
            )
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id) from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                headers=response.headers,
            )
        check_response_size(response.content, req.max_response_bytes, provider=self.provider_id)
        return self._parse_embed_response(req, response.json())

    def _parse_embed_response(
        self, req: EmbeddingWireRequest, payload: Any
    ) -> EmbeddingWireResult:
        if not isinstance(payload, Mapping):
            raise ProviderError("embeddings response is not a JSON object", phase="validate")
        entries = payload.get("embeddings")
        if not isinstance(entries, list):
            raise ProviderError(
                "embeddings response is missing an 'embeddings' array", phase="validate"
            )
        if len(entries) != len(req.inputs):
            raise ProviderError(
                f"embeddings response returned {len(entries)} vectors for "
                f"{len(req.inputs)} inputs",
                phase="validate",
            )
        vectors: list[tuple[float, ...]] = []
        for entry in entries:
            values = entry.get("values") if isinstance(entry, Mapping) else None
            if not isinstance(values, list):
                raise ProviderError(
                    "embeddings response entry is missing a 'values' array", phase="validate"
                )
            vectors.append(tuple(float(v) for v in values))

        usage = None
        meta = payload.get("usageMetadata")
        if isinstance(meta, Mapping):
            count = meta.get("promptTokenCount")
            if isinstance(count, int) and not isinstance(count, bool):
                usage = Usage(input_tokens=count)

        return EmbeddingWireResult(
            vectors=tuple(vectors),
            dimensions=len(vectors[0]) if vectors else None,
            usage=usage,
            raw=payload,
        )

    async def generate(self, req: WireRequest) -> AsyncGenerator[AdapterEvent, None]:
        """Run one generation against ``:streamGenerateContent`` or ``:generateContent``."""
        payload = self.build_payload(req)
        if req.stream:
            # `aclosing`: an early close of this generator must also close
            # `_generate_streaming`'s, or its open connection is left to finalize during
            # GC instead of closing deterministically.
            async with aclosing(self._generate_streaming(req, payload)) as events:
                async for event in events:
                    yield event
        else:
            async for event in self._generate_buffered(req, payload):
                yield event

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Translate a wire request into a ``GenerateContentRequest`` body."""
        system_text, turns = _split_system(req.messages)

        payload: dict[str, Any] = {"contents": [self._encode_message(m) for m in turns]}
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        config = self._generation_config(req)
        if config:
            payload["generationConfig"] = config

        if req.tools:
            payload["tools"] = [
                {"functionDeclarations": [self._encode_tool(t) for t in req.tools]}
            ]
            mode = self._encode_tool_choice(req.tool_choice)
            if mode is not None:
                payload["toolConfig"] = {"functionCallingConfig": mode}

        payload.update(req.extra_options)
        return payload

    def _generation_config(self, req: WireRequest) -> dict[str, Any]:
        """Assemble ``generationConfig``: sampling, structured output, and thinking."""
        config: dict[str, Any] = {}
        sampling: Sampling = req.sampling
        if sampling.temperature is not None:
            config["temperature"] = sampling.temperature
        if sampling.top_p is not None:
            config["topP"] = sampling.top_p
        if sampling.max_output_tokens is not None:
            config["maxOutputTokens"] = sampling.max_output_tokens
        if sampling.stop:
            config["stopSequences"] = list(sampling.stop)

        if req.mechanism in ("json_schema", "grammar") and req.wire_schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseSchema"] = dict(req.wire_schema)
        elif req.mechanism == "json_mode":
            config["responseMimeType"] = "application/json"

        config.update(req.reasoning_wire)
        return config

    def _encode_message(self, message: Message) -> dict[str, Any]:
        """Encode one turn into Gemini's ``Content`` shape."""
        parts: list[dict[str, Any]] = []

        for part in message.content:
            if isinstance(part, Text):
                if part.text:
                    parts.append({"text": part.text})
            elif isinstance(part, ToolCall):
                call: dict[str, Any] = {
                    "functionCall": {"name": part.name, "args": dict(part.arguments)}
                }
                if part.id and not part.id.startswith("call_"):
                    # Synthesized ids are ours, not Gemini's; echoing one back would be
                    # a correlation key the API never issued.
                    call["functionCall"]["id"] = part.id
                parts.append(call)
            elif isinstance(part, ToolResult):
                parts.append(
                    {
                        "functionResponse": {
                            "name": part.call_id,
                            "response": _tool_response_body(part),
                        }
                    }
                )
            elif isinstance(part, ImagePart | DocumentPart | AudioPart):
                if isinstance(part, AudioPart) or part.data is not None:
                    data = part.data if part.data is not None else b""
                    parts.append(
                        {"inlineData": {"mimeType": part.media_type, "data": base64_data(data)}}
                    )
                else:
                    parts.append({"fileData": {"mimeType": part.media_type, "fileUri": part.url}})

        # Tool results ride on a user turn in this dialect; only the model speaks "model".
        role = "model" if message.role == "assistant" else "user"
        return {"role": role, "parts": parts or [{"text": ""}]}

    def _encode_tool(self, tool: ToolSpec) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": _project(tool.parameters),
        }

    def _encode_tool_choice(self, choice: str) -> dict[str, Any] | None:
        if choice == "auto":
            return None
        if choice == "none":
            return {"mode": "NONE"}
        if choice == "required":
            return {"mode": "ANY"}
        return {"mode": "ANY", "allowedFunctionNames": [choice]}

    # ---- streaming path --------------------------------------------------------------

    async def _generate_streaming(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncGenerator[AdapterEvent, None]:
        """Stream ``:streamGenerateContent?alt=sse``, translating each chunk."""
        path = self._model_path(req.model, "streamGenerateContent")
        try:
            async with self._client.stream(
                "POST",
                path,
                params={"alt": "sse"},
                json=payload,
                timeout=req.timeout_s,
                headers={"accept": "text/event-stream", **self._request_headers()},
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
                # `aclosing`: an early close of this generator must also close the SSE
                # parser's, or it and the open connection are left to finalize during GC
                # instead of closing deterministically.
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

    async def _generate_buffered(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncIterator[AdapterEvent]:
        """Issue a unary ``:generateContent`` request and emit it as one stream."""
        path = self._model_path(req.model, "generateContent")
        try:
            response = await self._client.post(
                path,
                json=payload,
                timeout=req.timeout_s,
                headers=self._request_headers(),
            )
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
            body = json.loads(response.content)
        except ValueError as exc:
            raise StreamProtocolError(
                f"gemini returned a non-JSON body: {exc}", provider=self.provider_id
            ) from exc

        state = _StreamState()
        for event in self._events_from_chunk(body, state):
            yield event
        final = state.finalize()
        yield AdapterFinal(
            finish_reason=final.finish_reason,
            usage=final.usage,
            phases=final.phases,
            raw=body,
        )

    def _events_from_chunk(self, chunk: Any, state: _StreamState) -> Iterable[AdapterEvent]:
        """Translate one ``GenerateContentResponse`` into zero or more adapter events."""
        if not isinstance(chunk, Mapping):
            return

        error = chunk.get("error")
        if isinstance(error, Mapping):
            raise ProviderError(
                str(error.get("message") or "gemini reported a stream error"),
                provider=self.provider_id,
            )

        usage = _parse_usage(chunk.get("usageMetadata"))
        if usage is not None:
            state.usage = state.usage.merge(usage)
            yield UsageUpdate(usage)

        feedback = chunk.get("promptFeedback")
        if isinstance(feedback, Mapping) and feedback.get("blockReason"):
            # A blocked prompt produces no candidates at all, so the refusal would
            # otherwise finish as an empty "stop".
            state.finish_reason = "content_filter"

        candidates = chunk.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return
        candidate = candidates[0]
        if not isinstance(candidate, Mapping):
            return

        reason = candidate.get("finishReason")
        if isinstance(reason, str):
            state.finish_reason = _FINISH_REASONS.get(reason, "other")

        content = candidate.get("content")
        if not isinstance(content, Mapping):
            return
        parts = content.get("parts")
        if not isinstance(parts, list):
            return

        for part in parts:
            if not isinstance(part, Mapping):
                continue
            yield from self._events_from_part(part, state)

    def _events_from_part(
        self, part: Mapping[str, Any], state: _StreamState
    ) -> Iterable[AdapterEvent]:
        """Translate one ``Part``: text, a thought, or a function call."""
        text = part.get("text")
        if isinstance(text, str) and text:
            # A part flagged `thought` is reasoning, not answer text — the same
            # separation Anthropic's thinking deltas get.
            if part.get("thought") is True:
                yield ReasoningDelta(text)
            else:
                yield TextDelta(text)

        call = part.get("functionCall")
        if isinstance(call, Mapping):
            name = call.get("name")
            args = call.get("args")
            index = state.next_tool_slot()
            call_id = call.get("id")
            yield ToolCallDelta(
                index=index,
                call_id=str(call_id) if isinstance(call_id, str) and call_id else None,
                name=str(name) if isinstance(name, str) else None,
                # Gemini sends complete arguments as an object rather than streamed
                # string fragments, so one fragment carries the whole payload.
                arguments_fragment=json.dumps(dict(args)) if isinstance(args, Mapping) else "",
            )

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


class _StreamState:
    """Accumulates cross-chunk streaming state so the final event is complete."""

    __slots__ = ("finish_reason", "tool_slots", "usage")

    def __init__(self) -> None:
        self.finish_reason: FinishReason = "stop"
        self.usage = Usage()
        self.tool_slots = 0

    def next_tool_slot(self) -> int:
        """Allocate the next dense tool-call index.

        Gemini emits each call whole rather than in fragments, so slots are assigned in
        arrival order instead of being correlated back to a provider-supplied index.
        """
        slot = self.tool_slots
        self.tool_slots += 1
        return slot

    def finalize(self) -> AdapterFinal:
        """Build the terminal adapter event."""
        usage = self.usage.normalized()
        return AdapterFinal(
            finish_reason=self.finish_reason,
            usage=usage if usage != Usage() else None,
        )


def _split_system(messages: Sequence[Message]) -> tuple[str, list[Message]]:
    """Pull system messages out into the top-level ``systemInstruction`` field."""
    system_parts: list[str] = []
    remaining: list[Message] = []
    for message in messages:
        if message.role == "system":
            if message.text:
                system_parts.append(message.text)
        else:
            remaining.append(message)
    return "\n\n".join(system_parts), remaining


def _tool_response_body(result: ToolResult) -> dict[str, Any]:
    """Wrap a tool result in the object ``functionResponse.response`` requires.

    The field is typed as a structured object, so a plain string is nested under a key
    rather than sent bare. JSON output is passed through as the object it already is.
    """
    key = "error" if result.is_error else "output"
    try:
        parsed = json.loads(result.content)
    except ValueError:
        return {key: result.content}
    return parsed if isinstance(parsed, dict) else {key: parsed}


def _parse_usage(payload: Any) -> Usage | None:
    """Read ``usageMetadata``, keeping thinking tokens visible.

    ``candidatesTokenCount`` excludes thoughts, and thinking is billed at the output
    rate, so output tokens are the sum — otherwise every reasoning request would
    under-report its cost.
    """
    if not isinstance(payload, Mapping):
        return None

    candidates = read_int(payload, "candidatesTokenCount")
    thoughts = read_int(payload, "thoughtsTokenCount")
    output = None
    if candidates is not None or thoughts is not None:
        output = (candidates or 0) + (thoughts or 0)

    usage = Usage(
        input_tokens=read_int(payload, "promptTokenCount"),
        output_tokens=output,
        total_tokens=read_int(payload, "totalTokenCount"),
        cache_read_tokens=read_int(payload, "cachedContentTokenCount"),
        reasoning_tokens=thoughts,
    )
    return usage if usage != Usage() else None


def _project(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Recursively keep only the schema keywords Gemini documents."""
    projected: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _SCHEMA_KEYWORDS:
            continue
        if key == "properties" and isinstance(value, Mapping):
            projected[key] = {
                name: _project(sub) for name, sub in value.items() if isinstance(sub, Mapping)
            }
        elif key in ("items", "additionalProperties") and isinstance(value, Mapping):
            projected[key] = _project(value)
        elif key in ("anyOf", "prefixItems") and isinstance(value, list):
            projected[key] = [_project(v) for v in value if isinstance(v, Mapping)]
        else:
            projected[key] = value
    return projected


def _sourced_limit(value: Any) -> Sourced[int] | None:
    """Tag a reported token limit as discovered, ignoring absent or nonsense values."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return Sourced(value, "discovered")
    return None


_THINKING_LEVELS: Mapping[ReasoningEffort, str] = {
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
}


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto ``thinkingConfig.thinkingLevel``.

    Gemini names thinking levels rather than budgeting tokens, so the four normalized
    levels map straight across. Models that cannot disable thinking simply clamp the
    request upward on the server side.
    """
    if effort is None:
        return {}
    return {"thinkingConfig": {"thinkingLevel": _THINKING_LEVELS[effort]}}


_GEMINI_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.JSON_MODE
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
    | Feature.CACHE_USAGE
)


_STATIC_EMBEDDING_CAPABILITIES = {
    # Verified against ai.google.dev (embeddings guide + API reference) on 2026-08-12:
    # both current models output 3,072 dimensions by default with 128-3,072 supported
    # (768/1536/3072 recommended). gemini-embedding-2 documents no taskType support;
    # gemini-embedding-001 (legacy) accepts the four mapped task types. No batch-size
    # ceiling is stated for batchEmbedContents, so max_batch_inputs stays None.
    "gemini-embedding-2": EmbeddingCapabilities(
        dimensions=3_072, dimension_choices=(768, 1_536, 3_072), input_intents=()
    ),
    "gemini-embedding-001": EmbeddingCapabilities(
        dimensions=3_072,
        dimension_choices=(768, 1_536, 3_072),
        input_intents=("query", "document", "classification", "clustering"),
    ),
}


descriptor = ProviderDescriptor(
    id="gemini",
    display_name="Google Gemini",
    aliases=("google", "google-gemini", "ai-studio"),
    factory=GeminiAdapter,
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
                help_text=(
                    "Sent as the x-goog-api-key header. Conventionally "
                    "env://GEMINI_API_KEY. Accepts env:// and credential://."
                ),
                placeholder="env://GEMINI_API_KEY or a literal key",
                env_var="GEMINI_API_KEY",
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
    default_capabilities=ModelCapabilities(features=Sourced(_GEMINI_FEATURES, "default")),
)
"""Descriptor for the Google Gemini provider."""
