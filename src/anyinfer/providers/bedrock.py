"""AWS Bedrock's Converse API (`contracts/bedrock.md`).

Converse is Bedrock's *unified* interface: one request shape across Claude, Nova, Llama,
Mistral, and DeepSeek, rather than the per-model bodies ``InvokeModel`` demands. That is
exactly the normalization AnyInfer wants, so this adapter speaks Converse and never
InvokeModel.

Four things make this dialect unusual:

- **Streaming is binary.** ``ConverseStream`` answers with AWS's
  ``vnd.amazon.eventstream`` framing and offers no SSE or JSON alternative, so the
  decoder in `anyinfer.providers.eventstream` is not optional.
- **Auth is signed, or a bearer key.** A Bedrock API key is used verbatim when supplied;
  otherwise every request is SigV4-signed from resolved AWS credentials.
- **Content is a list of typed blocks**, and tool results ride on a *user* turn.
- **Usage arrives only in the terminal ``metadata`` event** — a stream closed on
  ``messageStop`` reports no tokens at all.

Model-specific parameters that Converse does not model (Claude's ``top_k`` or extended
thinking, for instance) pass through ``additionalModelRequestFields``.

Embeddings are the one operation Converse does not offer at all — Bedrock only serves
them through the older, per-model ``InvokeModel`` action. `embed()` therefore speaks two
per-model dialects on one action, chosen by `req.model`'s prefix: Titan Text Embeddings
V2's own body shape (``inputText``/``dimensions``/``normalize`` in,
``embedding``/``inputTextTokenCount`` out, one input per call), verified live 2026-08-12
against docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html;
and Cohere Embed v3's shape (``texts``/``input_type``/``embedding_types`` in, a
type-keyed ``embeddings`` dict out — the same shape and parse as hosted Cohere, see
`cohere.py`), verified live 2026-08-14 against
docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-embed-v3.html.

Rerank is a third action entirely — ``bedrock-agent-runtime``'s ``POST /rerank``, a
different host and a different SigV4-signed service than ``InvokeModel``/``Converse``
(though verified via botocore's own service model 2026-08-14 to share the same SigV4
signing name, ``bedrock``). It is genuinely model-agnostic at the wire level: the same
request/response shape serves both ``amazon.rerank-v1:0`` and ``cohere.rerank-v3-5:0``,
selected only by the ``modelArn`` inside `rerankingConfiguration`, never by a per-model
body dialect the way `embed()` needs. See `contracts/bedrock.md` for the citations.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Mapping, Sequence
from contextlib import aclosing
from typing import Any

import httpx2

from ..errors import ConfigError, ProviderError, StreamProtocolError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Feature, Health, ModelCapabilities, Sourced
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
from ..types.operations import EmbeddingCapabilities, EmbeddingInputIntent, RerankCapabilities
from ..types.requests import ReasoningEffort, Sampling, ToolSpec
from ..types.results import FinishReason, Usage
from ._multimodal import base64_data, media_subtype, neutral_filename, unsupported
from .base import (
    AdapterEvent,
    AdapterFinal,
    EmbeddingWireRequest,
    EmbeddingWireResult,
    ProviderConfig,
    RerankWireRequest,
    RerankWireResult,
    WireRankedItem,
    WireRequest,
    resolve_rerank_index,
)
from .cloud_auth import AwsCredentials, resolve_aws_credentials, sigv4_headers
from .eventstream import EventStreamMessage, iter_event_stream
from .http import (
    build_client,
    check_response_size,
    classify_status,
    map_transport_error,
    read_error_detail,
    read_int,
)

__all__ = ["BedrockAdapter", "descriptor"]

_DEFAULT_REGION = "us-east-1"
_SIGNING_SERVICE = "bedrock"

_STOP_REASONS: Mapping[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "guardrail_intervened": "content_filter",
    "content_filtered": "content_filter",
    "malformed_model_output": "other",
    "malformed_tool_use": "other",
    "model_context_window_exceeded": "length",
}

_RETRYABLE_EXCEPTIONS: Mapping[str, int] = {
    "throttlingException": 429,
    "modelNotReadyException": 429,
    "serviceUnavailableException": 503,
    "internalServerException": 500,
    "modelStreamErrorException": 424,
    "modelTimeoutException": 408,
}
"""In-stream exception frames, mapped to the status the shared classifier expects."""

_COHERE_INPUT_TYPES: Mapping[EmbeddingInputIntent, str] = {
    "query": "search_query",
    "document": "search_document",
    "classification": "classification",
    "clustering": "clustering",
}
"""Same spellings, same mapping, as hosted Cohere's own ``_INPUT_TYPES`` in `cohere.py` —
Bedrock's Cohere Embed v3 speaks Cohere's own vocabulary verbatim, just through
``InvokeModel`` instead of Cohere's REST API."""

_COHERE_EMBED_INTENTS: tuple[EmbeddingInputIntent, ...] = tuple(_COHERE_INPUT_TYPES)


class BedrockAdapter:
    """Adapter for Amazon Bedrock's Converse API."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self.provider_id = config.provider_id
        options = dict(config.options)

        self._region = str(options.get("region") or _DEFAULT_REGION)
        self._api_key = config.api_key
        self._credentials: AwsCredentials | None = None
        if not self._api_key:
            # Deferred to first use only for the key; credentials are cheap to resolve
            # and failing at construction gives a much clearer error than failing mid-run.
            self._credentials = resolve_aws_credentials(options)
            if self._credentials is None:
                raise ConfigError(
                    "bedrock needs either a Bedrock API key or AWS credentials",
                    provider=self.provider_id,
                    hint=(
                        "set api_key to a Bedrock API key (or env://AWS_BEARER_TOKEN_BEDROCK), "
                        "or configure AWS credentials via the environment, a boto3 profile, "
                        "or options={'aws_access_key_id': ..., 'aws_secret_access_key': ...}"
                    ),
                )

        base_url = config.base_url or f"https://bedrock-runtime.{self._region}.amazonaws.com"
        self._base_url = base_url.rstrip("/")
        self._client = build_client(
            base_url=self._base_url,
            headers={"content-type": "application/json"},
            timeout_s=config.timeout_s,
            transport=config.transport,
        )

    # ---- auth ------------------------------------------------------------------------

    def _auth_headers(self, *, method: str, path: str, body: bytes) -> dict[str, str]:
        """Build the per-request auth headers: a bearer key, or a SigV4 signature."""
        if self._api_key:
            return {"authorization": f"Bearer {self._api_key}"}
        if self._credentials is None:
            raise ConfigError("bedrock AWS credentials are unavailable", provider=self.provider_id)
        return sigv4_headers(
            credentials=self._credentials,
            method=method,
            url=f"{self._base_url}{path}",
            region=self._region,
            service=_SIGNING_SERVICE,
            body=body,
            headers={"content-type": "application/json"},
        )

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """List foundation models from the Bedrock control plane.

        The control plane is a *different* host than the runtime, so this signs against
        it separately. Accounts without ``bedrock:ListFoundationModels`` get an empty
        list rather than an error — discovery is a convenience, and a permission gap
        should not make the provider look broken.
        """
        host = f"https://bedrock.{self._region}.amazonaws.com"
        path = "/foundation-models"
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        elif self._credentials is not None:
            headers.update(
                sigv4_headers(
                    credentials=self._credentials,
                    method="GET",
                    url=f"{host}{path}",
                    region=self._region,
                    service=_SIGNING_SERVICE,
                    body=b"",
                    headers=headers,
                )
            )

        try:
            response = await self._client.get(f"{host}{path}", headers=headers)
        except httpx2.HTTPError:
            return []
        if response.status_code >= 400:
            return []

        payload = response.json()
        summaries = payload.get("modelSummaries") if isinstance(payload, Mapping) else None
        if not isinstance(summaries, list):
            return []
        return [
            _parse_model(entry)
            for entry in summaries
            if isinstance(entry, Mapping) and entry.get("modelId")
        ]

    async def health(self) -> Health:
        """Report whether credentials are present.

        Deliberately not a network call: every Bedrock runtime endpoint costs a
        generation, and the control plane may be denied by policy even when inference
        works perfectly.
        """
        if self._api_key or self._credentials is not None:
            return Health(ok=True, detail=f"credentials present for {self._region}")
        return Health(ok=False, detail="no Bedrock API key or AWS credentials")

    # ---- embedding -------------------------------------------------------------------

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Dispatch to the InvokeModel body Titan or Cohere Embed v3 actually speaks.

        Bedrock's two embedding families use unrelated request/response shapes on the
        same `InvokeModel` action — there is no third, unified embeddings action the way
        Converse unifies generation — so this branches on `req.model`'s prefix rather
        than pretending one shape fits both.
        """
        if req.model.startswith("cohere."):
            return await self._embed_cohere(req)
        return await self._embed_titan(req)

    async def _embed_titan(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one or more Titan Text Embeddings V2 calls through ``InvokeModel``.

        Titan accepts exactly one ``inputText`` per call — there is no batch field —
        so this issues one `InvokeModel` request per input and reassembles them in
        order. `max_batch_inputs=1` is declared for the model so the core's batching
        policy keeps `req.inputs` to one item in normal operation; looping here keeps
        the adapter correct even when called directly with more.
        """
        vectors: list[tuple[float, ...]] = []
        total_tokens = 0
        saw_token_count = False
        last_payload: Any = None

        for text in req.inputs:
            body_fields: dict[str, Any] = {"inputText": text}
            if req.dimensions is not None:
                body_fields["dimensions"] = req.dimensions
            body_fields.update(req.extra_options)
            body = json.dumps(body_fields).encode("utf-8")

            path = f"/model/{_quote_model(req.model)}/invoke"
            try:
                response = await self._client.post(
                    path,
                    content=body,
                    headers=self._auth_headers(method="POST", path=path, body=body),
                    timeout=req.timeout_s,
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
            check_response_size(
                response.content, req.max_response_bytes, provider=self.provider_id
            )

            try:
                parsed = json.loads(response.content)
            except ValueError as exc:
                raise ProviderError(
                    f"bedrock returned a non-JSON embedding body: {exc}",
                    provider=self.provider_id,
                    phase="validate",
                ) from exc
            if not isinstance(parsed, Mapping):
                raise ProviderError(
                    "titan embedding response is not a JSON object", phase="validate"
                )
            last_payload = parsed

            embedding = parsed.get("embedding")
            if not isinstance(embedding, list):
                raise ProviderError(
                    "titan embedding response is missing an 'embedding' array",
                    phase="validate",
                )
            vectors.append(tuple(float(v) for v in embedding))

            token_count = parsed.get("inputTextTokenCount")
            if isinstance(token_count, int) and not isinstance(token_count, bool):
                total_tokens += token_count
                saw_token_count = True

        usage = Usage(input_tokens=total_tokens) if saw_token_count else None
        return EmbeddingWireResult(
            vectors=tuple(vectors),
            dimensions=len(vectors[0]) if vectors else None,
            usage=usage,
            raw=last_payload,
        )

    async def _embed_cohere(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one Cohere Embed v3 call through ``InvokeModel``.

        Unlike Titan, Cohere Embed v3 accepts a batch of ``texts`` per call (up to 96,
        live-verified 2026-08-14) — one request regardless of `req.inputs` length.
        ``embedding_types`` is always sent explicitly as ``["float"]`` so the response
        shape is deterministic (a type-keyed dict), the same choice `cohere.py` already
        makes for hosted Cohere and the same parse this reuses.
        """
        if req.input_type is None:
            raise ConfigError(
                "Cohere Embed v3 requires an input type and documents no default",
                provider=self.provider_id,
                hint=(
                    "pass input_type='document' for corpus text, 'query' for search "
                    "queries, or 'classification'/'clustering' — AnyInfer never guesses "
                    "an intent, because query and document embeddings are not comparable "
                    "unless produced with matching intents"
                ),
            )
        body_fields: dict[str, Any] = {
            "texts": list(req.inputs),
            "input_type": _COHERE_INPUT_TYPES[req.input_type],
            "embedding_types": ["float"],
        }
        body = json.dumps(body_fields).encode("utf-8")
        path = f"/model/{_quote_model(req.model)}/invoke"
        try:
            response = await self._client.post(
                path,
                content=body,
                headers=self._auth_headers(method="POST", path=path, body=body),
                timeout=req.timeout_s,
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

        try:
            parsed = json.loads(response.content)
        except ValueError as exc:
            raise ProviderError(
                f"bedrock returned a non-JSON embedding body: {exc}",
                provider=self.provider_id,
                phase="validate",
            ) from exc
        if not isinstance(parsed, Mapping):
            raise ProviderError("cohere embedding response is not a JSON object", phase="validate")

        embeddings = parsed.get("embeddings")
        floats = embeddings.get("float") if isinstance(embeddings, Mapping) else None
        if not isinstance(floats, list):
            raise ProviderError(
                "cohere embedding response is missing an 'embeddings.float' array",
                phase="validate",
            )
        if len(floats) != len(req.inputs):
            raise ProviderError(
                f"cohere embedding response returned {len(floats)} vectors for "
                f"{len(req.inputs)} inputs",
                phase="validate",
            )
        vectors: list[tuple[float, ...]] = []
        for entry in floats:
            if not isinstance(entry, list):
                raise ProviderError(
                    "cohere embedding response contains a non-array vector", phase="validate"
                )
            vectors.append(tuple(float(v) for v in entry))

        # No usage/token-count field anywhere in this response — verified live
        # 2026-08-14, unlike Titan's `inputTextTokenCount`. Unknown, never zero.
        return EmbeddingWireResult(
            vectors=tuple(vectors),
            dimensions=len(vectors[0]) if vectors else None,
            usage=None,
            raw=parsed,
        )

    # ---- reranking ---------------------------------------------------------------------

    async def rerank(self, req: RerankWireRequest) -> RerankWireResult:
        """Run one rerank call through the ``bedrock-agent-runtime`` ``Rerank`` action.

        A genuinely different host and service surface than `embed()`/`generate()`
        (``bedrock-agent-runtime`` vs. ``bedrock-runtime``), though SigV4-signed under
        the same ``bedrock`` signing name — confirmed 2026-08-14 against botocore's own
        ``bedrock-agent-runtime`` service model, not guessed. Model-agnostic at the wire
        level: `req.model` becomes a `modelArn`
        (``arn:aws:bedrock:{region}::foundation-model/{model}``), the only thing that
        distinguishes ``amazon.rerank-v1:0`` from ``cohere.rerank-v3-5:0`` on this action.
        """
        payload: dict[str, Any] = {
            "queries": [{"type": "TEXT", "textQuery": {"text": req.query}}],
            "sources": [
                {
                    "type": "INLINE",
                    "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": doc.text}},
                }
                for doc in req.documents
            ],
            "rerankingConfiguration": {
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "modelConfiguration": {
                        "modelArn": f"arn:aws:bedrock:{self._region}::foundation-model/{req.model}"
                    },
                    **({"numberOfResults": req.top_n} if req.top_n is not None else {}),
                },
            },
        }
        payload.update(req.extra_options)
        body = json.dumps(payload).encode("utf-8")

        host = f"https://bedrock-agent-runtime.{self._region}.amazonaws.com"
        path = "/rerank"
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        elif self._credentials is not None:
            headers.update(
                sigv4_headers(
                    credentials=self._credentials,
                    method="POST",
                    url=f"{host}{path}",
                    region=self._region,
                    service=_SIGNING_SERVICE,
                    body=body,
                    headers=headers,
                )
            )
        else:
            raise ConfigError("bedrock AWS credentials are unavailable", provider=self.provider_id)

        try:
            response = await self._client.post(
                f"{host}{path}", content=body, headers=headers, timeout=req.timeout_s
            )
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=read_error_detail(response.content),
                headers=response.headers,
                phase="generate",
            )
        check_response_size(response.content, req.max_response_bytes, provider=self.provider_id)

        try:
            parsed = json.loads(response.content)
        except ValueError as exc:
            raise ProviderError(
                f"bedrock returned a non-JSON rerank body: {exc}",
                provider=self.provider_id,
                phase="validate",
            ) from exc
        if not isinstance(parsed, Mapping):
            raise ProviderError("rerank response is not a JSON object", phase="validate")
        results = parsed.get("results")
        if not isinstance(results, list):
            raise ProviderError("rerank response is missing a 'results' array", phase="validate")

        items: list[WireRankedItem] = []
        for entry in results:
            if not isinstance(entry, Mapping):
                raise ProviderError(
                    "rerank response contains a non-object result", phase="validate"
                )
            position = entry.get("index")
            score = entry.get("relevanceScore")
            if not isinstance(position, int) or isinstance(position, bool):
                raise ProviderError(
                    "rerank result is missing an integer 'index'", phase="validate"
                )
            if not isinstance(score, int | float) or isinstance(score, bool):
                raise ProviderError(
                    "rerank result is missing a numeric 'relevanceScore'", phase="validate"
                )
            index = resolve_rerank_index(req, position)
            items.append(WireRankedItem(index=index, score=float(score)))

        # No usage/search-unit field anywhere in this response — verified live 2026-08-14
        # against AWS's own Rerank guide and its boto3 code example.
        return RerankWireResult(items=tuple(items), usage=None, raw=parsed)

    # ---- generation ------------------------------------------------------------------

    async def generate(self, req: WireRequest) -> AsyncGenerator[AdapterEvent, None]:
        """Run one generation through Converse or ConverseStream."""
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
        """Translate a wire request into a Converse request body."""
        system_blocks, turns = _split_system(req.messages)

        payload: dict[str, Any] = {
            "messages": [self._encode_message(m) for m in turns],
        }
        if system_blocks:
            payload["system"] = system_blocks

        inference = _inference_config(req.sampling)
        if inference:
            payload["inferenceConfig"] = inference

        tools = [self._encode_tool(t) for t in req.tools]
        if req.mechanism in ("json_schema", "grammar") and req.wire_schema is not None:
            # Converse has no response-format field, so a schema becomes a forced tool
            # call — the same emulation the Anthropic adapter uses, and for the same
            # reason: the API genuinely constrains tool input.
            name = req.schema_name or "respond"
            tools.append(
                {
                    "toolSpec": {
                        "name": name,
                        "description": "Return the response in the required structure.",
                        "inputSchema": {"json": dict(req.wire_schema)},
                    }
                }
            )
            payload["toolConfig"] = {
                "tools": tools,
                "toolChoice": {"tool": {"name": name}},
            }
        elif tools:
            payload["toolConfig"] = {
                "tools": tools,
                **_tool_choice(req.tool_choice),
            }

        extra = dict(req.reasoning_wire)
        extra.update(req.extra_options)
        additional = extra.pop("additionalModelRequestFields", None)
        if isinstance(additional, Mapping):
            payload["additionalModelRequestFields"] = dict(additional)
        payload.update(extra)
        return payload

    def _encode_message(self, message: Message) -> dict[str, Any]:
        """Encode one turn into Converse's typed content blocks."""
        blocks: list[dict[str, Any]] = []

        for part in message.content:
            if isinstance(part, Text):
                if part.text:
                    blocks.append({"text": part.text})
            elif isinstance(part, ToolCall):
                blocks.append(
                    {
                        "toolUse": {
                            "toolUseId": part.id,
                            "name": part.name,
                            "input": dict(part.arguments),
                        }
                    }
                )
            elif isinstance(part, ToolResult):
                blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": part.call_id,
                            "content": [{"text": part.content}],
                            **({"status": "error"} if part.is_error else {}),
                        }
                    }
                )
            elif isinstance(part, ImagePart):
                source = _bedrock_media_source(self.provider_id, part.data, part.url)
                blocks.append(
                    {
                        "image": {
                            "format": media_subtype(part.media_type, jpeg=True),
                            "source": source,
                        }
                    }
                )
            elif isinstance(part, DocumentPart):
                source = _bedrock_media_source(self.provider_id, part.data, part.url)
                blocks.append(
                    {
                        "document": {
                            "format": media_subtype(part.media_type),
                            "name": neutral_filename(part.filename, "document"),
                            "source": source,
                        }
                    }
                )
            elif isinstance(part, AudioPart):
                blocks.append(
                    {
                        "audio": {
                            "format": media_subtype(part.media_type),
                            "source": {"bytes": base64_data(part.data)},
                        }
                    }
                )

        # Tool results ride on a user turn here, as in the Anthropic dialect.
        role = "user" if message.role in ("user", "tool") else "assistant"
        return {"role": role, "content": blocks or [{"text": ""}]}

    def _encode_tool(self, tool: ToolSpec) -> dict[str, Any]:
        return {
            "toolSpec": {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": {"json": dict(tool.parameters)},
            }
        }

    # ---- buffered path ---------------------------------------------------------------

    async def _generate_buffered(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncIterator[AdapterEvent]:
        """Issue a unary Converse request and emit it as a one-shot stream."""
        path = f"/model/{_quote_model(req.model)}/converse"
        body = json.dumps(payload).encode("utf-8")

        try:
            response = await self._client.post(
                path,
                content=body,
                headers=self._auth_headers(method="POST", path=path, body=body),
                timeout=req.timeout_s,
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
            parsed = json.loads(response.content)
        except ValueError as exc:
            raise StreamProtocolError(
                f"bedrock returned a non-JSON body: {exc}", provider=self.provider_id
            ) from exc

        for event in self._events_from_response(parsed):
            yield event

    def _events_from_response(self, payload: Any) -> Iterable[AdapterEvent]:
        """Translate a buffered Converse response into a synthetic event stream."""
        if not isinstance(payload, Mapping):
            raise StreamProtocolError(
                "bedrock returned a non-object response", provider=self.provider_id
            )

        output = payload.get("output")
        message = output.get("message") if isinstance(output, Mapping) else None
        blocks = message.get("content") if isinstance(message, Mapping) else None

        slot = 0
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, Mapping):
                    continue
                text = block.get("text")
                if isinstance(text, str) and text:
                    yield TextDelta(text)
                reasoning = _reasoning_text(block.get("reasoningContent"))
                if reasoning:
                    yield ReasoningDelta(reasoning)
                use = block.get("toolUse")
                if isinstance(use, Mapping):
                    yield ToolCallDelta(
                        index=slot,
                        call_id=str(use.get("toolUseId", "")) or None,
                        name=str(use.get("name", "")) or None,
                        arguments_fragment=json.dumps(dict(use.get("input") or {})),
                    )
                    slot += 1

        usage = _parse_usage(payload.get("usage"))
        if usage is not None:
            yield UsageUpdate(usage)

        raw_reason = payload.get("stopReason")
        finish = _STOP_REASONS.get(raw_reason, "other") if isinstance(raw_reason, str) else "stop"
        yield AdapterFinal(
            finish_reason=finish,
            usage=usage,
            phases=_latency_phases(payload.get("metrics")),
            raw=payload,
        )

    # ---- streaming path --------------------------------------------------------------

    async def _generate_streaming(
        self, req: WireRequest, payload: dict[str, Any]
    ) -> AsyncGenerator[AdapterEvent, None]:
        """Stream ConverseStream, decoding AWS's binary event framing."""
        path = f"/model/{_quote_model(req.model)}/converse-stream"
        body = json.dumps(payload).encode("utf-8")

        try:
            async with self._client.stream(
                "POST",
                path,
                content=body,
                headers=self._auth_headers(method="POST", path=path, body=body),
                timeout=req.timeout_s,
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
                # `aclosing`: an early close of this generator must also close the frame
                # decoder's, or it and the open connection are left to finalize during GC
                # instead of closing deterministically.
                async with aclosing(
                    iter_event_stream(
                        response.aiter_bytes(),
                        max_bytes=req.max_response_bytes,
                        provider=self.provider_id,
                    )
                ) as frames:
                    async for frame in frames:
                        for event in self._events_from_frame(frame, state):
                            yield event
                yield state.finalize()
        except (ProviderError, StreamProtocolError):
            raise
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="stream") from exc

    def _events_from_frame(
        self, frame: EventStreamMessage, state: _StreamState
    ) -> Iterable[AdapterEvent]:
        """Translate one decoded event-stream frame into adapter events."""
        if frame.is_exception:
            raise self._exception_error(frame)

        payload = frame.json()
        if not isinstance(payload, Mapping):
            return

        kind = frame.event_type
        if kind == "contentBlockStart":
            start = payload.get("start")
            index = payload.get("contentBlockIndex")
            if isinstance(start, Mapping) and isinstance(index, int):
                use = start.get("toolUse")
                if isinstance(use, Mapping):
                    yield ToolCallDelta(
                        index=state.tool_slot(index),
                        call_id=str(use.get("toolUseId", "")) or None,
                        name=str(use.get("name", "")) or None,
                        arguments_fragment="",
                    )
            return

        if kind == "contentBlockDelta":
            delta = payload.get("delta")
            index = payload.get("contentBlockIndex")
            if not isinstance(delta, Mapping):
                return
            text = delta.get("text")
            if isinstance(text, str) and text:
                yield TextDelta(text)
            reasoning = _reasoning_text(delta.get("reasoningContent"))
            if reasoning:
                yield ReasoningDelta(reasoning)
            use = delta.get("toolUse")
            if isinstance(use, Mapping) and isinstance(index, int):
                fragment = use.get("input")
                if isinstance(fragment, str) and fragment:
                    yield ToolCallDelta(
                        index=state.tool_slot(index),
                        call_id=None,
                        name=None,
                        arguments_fragment=fragment,
                    )
            return

        if kind == "messageStop":
            reason = payload.get("stopReason")
            if isinstance(reason, str):
                state.finish_reason = _STOP_REASONS.get(reason, "other")
            return

        if kind == "metadata":
            # Usage lives here and nowhere else: a stream closed on messageStop would
            # report no tokens at all.
            usage = _parse_usage(payload.get("usage"))
            if usage is not None:
                state.usage = state.usage.merge(usage)
                yield UsageUpdate(usage)
            state.phases.update(_latency_phases(payload.get("metrics")))

    def _exception_error(self, frame: EventStreamMessage) -> ProviderError:
        """Map an in-stream exception frame onto the shared status classification."""
        name = str(frame.headers.get(":exception-type") or frame.event_type or "")
        detail = ""
        payload = frame.json()
        if isinstance(payload, Mapping):
            detail = str(payload.get("message") or payload.get("Message") or "")
        status = _RETRYABLE_EXCEPTIONS.get(name, 400)
        return classify_status(
            status,
            provider=self.provider_id,
            detail=detail or f"bedrock stream error: {name or 'unknown'}",
            phase="stream",
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


class _StreamState:
    """Accumulates cross-frame state so the terminal event is complete."""

    __slots__ = ("finish_reason", "phases", "tool_slots", "usage")

    def __init__(self) -> None:
        self.finish_reason: FinishReason = "stop"
        self.usage = Usage()
        self.tool_slots: dict[int, int] = {}
        self.phases: dict[str, float] = {}

    def tool_slot(self, block_index: int) -> int:
        """Map a content-block index onto a dense tool-call slot.

        Block indices count text blocks too, so a response with prose before a tool call
        would otherwise report a non-zero first tool index.
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
            phases=dict(self.phases),
        )


def _split_system(messages: Sequence[Message]) -> tuple[list[dict[str, str]], list[Message]]:
    """Pull system messages into Converse's top-level ``system`` block list."""
    system: list[dict[str, str]] = []
    remaining: list[Message] = []
    for message in messages:
        if message.role == "system":
            if message.text:
                system.append({"text": message.text})
        else:
            remaining.append(message)
    return system, remaining


def _inference_config(sampling: Sampling) -> dict[str, Any]:
    """Build ``inferenceConfig`` from only the fields the caller actually set."""
    config: dict[str, Any] = {}
    if sampling.temperature is not None:
        config["temperature"] = sampling.temperature
    if sampling.top_p is not None:
        config["topP"] = sampling.top_p
    if sampling.max_output_tokens is not None:
        config["maxTokens"] = sampling.max_output_tokens
    if sampling.stop:
        config["stopSequences"] = list(sampling.stop)
    return config


def _tool_choice(choice: str) -> dict[str, Any]:
    """Translate normalized tool choice into Converse's ``toolChoice``.

    ``none`` has no Converse spelling, so it is expressed by omitting tools entirely at
    the call site; here it simply sends no choice.
    """
    if choice == "auto":
        return {"toolChoice": {"auto": {}}}
    if choice == "required":
        return {"toolChoice": {"any": {}}}
    if choice == "none":
        return {}
    return {"toolChoice": {"tool": {"name": choice}}}


def _reasoning_text(block: Any) -> str:
    """Read reasoning text out of a ``reasoningContent`` union, ignoring signatures."""
    if not isinstance(block, Mapping):
        return ""
    text = block.get("text")
    if isinstance(text, str):
        return text
    nested = block.get("reasoningText")
    if isinstance(nested, Mapping):
        inner = nested.get("text")
        if isinstance(inner, str):
            return inner
    return ""


def _parse_usage(payload: Any) -> Usage | None:
    """Read Converse's usage block, including its cache accounting."""
    if not isinstance(payload, Mapping):
        return None

    usage = Usage(
        input_tokens=read_int(payload, "inputTokens"),
        output_tokens=read_int(payload, "outputTokens"),
        total_tokens=read_int(payload, "totalTokens"),
        cache_read_tokens=read_int(payload, "cacheReadInputTokens"),
        cache_write_tokens=read_int(payload, "cacheWriteInputTokens"),
    )
    return usage if usage != Usage() else None


def _latency_phases(metrics: Any) -> dict[str, float]:
    """Read Bedrock's reported latency into the phase-timing map."""
    if not isinstance(metrics, Mapping):
        return {}
    latency = metrics.get("latencyMs")
    if isinstance(latency, int | float) and not isinstance(latency, bool):
        return {"provider_latency": float(latency)}
    return {}


def _quote_model(model: str) -> str:
    """Percent-encode a model id for the request path.

    Model ids may be inference-profile ids or full ARNs, which contain colons and slashes
    that must survive as path data rather than being read as separators.
    """
    import urllib.parse

    return urllib.parse.quote(model, safe="")


def _parse_model(entry: Mapping[str, Any]) -> DiscoveredModel:
    """Read one foundation-model summary from the control plane."""
    features = Feature.SYSTEM_PROMPT
    streaming = entry.get("responseStreamingSupported")
    if streaming is not False:
        features |= Feature.STREAMING
    if "TEXT" in (entry.get("outputModalities") or []):
        features |= Feature.TOOLS
    return DiscoveredModel(
        id=str(entry["modelId"]),
        capabilities=ModelCapabilities(features=Sourced(features, "discovered")),
    )


def _translate_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Map normalized effort onto Claude-style extended thinking.

    Converse has no reasoning field of its own; thinking is a model-specific parameter, so
    it travels in ``additionalModelRequestFields``. Bedrock forwards unknown fields to the
    model, which ignores them, so this is harmless on models without thinking, and the
    escape hatch remains available for other spellings.
    """
    if effort is None:
        return {}
    if effort == "minimal":
        return {"additionalModelRequestFields": {"thinking": {"type": "disabled"}}}
    budgets = {"low": 1024, "medium": 4096, "high": 16384}
    return {
        "additionalModelRequestFields": {
            "thinking": {"type": "enabled", "budget_tokens": budgets[effort]}
        }
    }


def _bedrock_media_source(provider_id: str, data: bytes | None, url: str | None) -> dict[str, Any]:
    if data is not None:
        return {"bytes": base64_data(data)}
    if url is not None and url.startswith("s3://"):
        return {"s3Location": {"uri": url}}
    raise unsupported(provider_id, "remote media", "Bedrock Converse accepts only s3:// URIs")


_BEDROCK_FEATURES = (
    Feature.STREAMING
    | Feature.JSON_SCHEMA
    | Feature.TOOLS
    | Feature.REASONING
    | Feature.SYSTEM_PROMPT
    | Feature.CACHE_USAGE
)


_STATIC_EMBEDDING_CAPABILITIES = {
    # Verified live 2026-08-12 against docs.aws.amazon.com/bedrock/latest/userguide/
    # titan-embedding-models.html and model-parameters-titan-embed-text.html: 8,192
    # max input tokens / 50,000 max input characters (whichever binds first — only the
    # token ceiling is representable here); output 1,024 dims by default, 512 or 256 via
    # `dimensions`; exactly one inputText per InvokeModel call. No task-type/intent
    # concept in the request schema.
    "amazon.titan-embed-text-v2:0": EmbeddingCapabilities(
        dimensions=1_024,
        dimension_choices=(1_024, 512, 256),
        max_batch_inputs=1,
        max_input_tokens=8_192,
        input_intents=(),
    ),
    # Verified live 2026-08-14 against docs.aws.amazon.com/bedrock/latest/userguide/
    # model-parameters-embed-v3.html: 96 texts per call, 2,048 characters per text
    # (stated in characters, not tokens, on this page; converted at the page's own
    # "1 token is about 4 characters" rule to stay consistent with every other
    # provider's token-denominated `max_input_tokens` here). 1,024 dims, no `dimensions`
    # override on this action (Bedrock's Cohere v3 has no `output_dimension` field).
    "cohere.embed-english-v3": EmbeddingCapabilities(
        dimensions=1_024,
        max_batch_inputs=96,
        max_input_tokens=512,
        input_intents=_COHERE_EMBED_INTENTS,
    ),
    "cohere.embed-multilingual-v3": EmbeddingCapabilities(
        dimensions=1_024,
        max_batch_inputs=96,
        max_input_tokens=512,
        input_intents=_COHERE_EMBED_INTENTS,
    ),
}

_STATIC_RERANK_CAPABILITIES: Mapping[str, RerankCapabilities] = {
    # Verified 2026-08-14 against botocore's own bedrock-agent-runtime service model:
    # RerankSourcesList allows 1-1000 documents, and the numberOfResults integer field
    # allows 1-1000 too — both action-level constraints on `Rerank`, not per-model, so
    # the same figures apply to every model reachable through this one action.
    model: RerankCapabilities(max_documents=1_000, native_top_n=True)
    for model in ("amazon.rerank-v1:0", "cohere.rerank-v3-5:0")
}


descriptor = ProviderDescriptor(
    id="bedrock",
    display_name="AWS Bedrock",
    aliases=("aws-bedrock", "amazon-bedrock"),
    factory=BedrockAdapter,
    locality="hosted",
    default_base_url=None,
    requires_base_url=False,
    operations=frozenset({"generation", "embedding", "rerank"}),
    static_embedding_capabilities=_STATIC_EMBEDDING_CAPABILITIES,
    static_rerank_capabilities=_STATIC_RERANK_CAPABILITIES,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="Bedrock API key",
                kind="secret",
                required=False,
                help_text=(
                    "A Bedrock API key, sent as a bearer token. Leave empty to sign "
                    "requests with AWS credentials instead."
                ),
                placeholder="env://AWS_BEARER_TOKEN_BEDROCK or a literal key",
                env_var="AWS_BEARER_TOKEN_BEDROCK",
            ),
            SetupField(
                key="region",
                label="AWS region",
                kind="text",
                required=False,
                default_value=_DEFAULT_REGION,
                help_text=f"Defaults to {_DEFAULT_REGION}.",
                placeholder=_DEFAULT_REGION,
            ),
            SetupField(
                key="base_url",
                label="Runtime endpoint",
                kind="endpoint",
                required=False,
                advanced=True,
                # No ``default_value``: the default endpoint follows whatever region is
                # configured, so stating one region's host as *the* standard would be
                # wrong for everybody who changed the field above it.
                help_text="Defaults to the regional Bedrock runtime host.",
                placeholder=f"https://bedrock-runtime.{_DEFAULT_REGION}.amazonaws.com",
            ),
            SetupField(
                key="aws_access_key_id",
                label="AWS access key ID",
                kind="text",
                required=False,
                advanced=True,
                help_text=(
                    "Sign with an explicit access key instead of the ambient credential "
                    "chain. Requires the secret access key too."
                ),
                placeholder="AKIA…",
            ),
            SetupField(
                key="aws_secret_access_key",
                label="AWS secret access key",
                kind="secret",
                required=False,
                advanced=True,
                help_text=(
                    "The secret half of the access key above. Accepts env:// and credential://."
                ),
                placeholder="env://AWS_SECRET_ACCESS_KEY",
                env_var="AWS_SECRET_ACCESS_KEY",
            ),
            SetupField(
                key="aws_session_token",
                label="AWS session token",
                kind="secret",
                required=False,
                advanced=True,
                help_text="Only for temporary (STS) credentials.",
                placeholder="env://AWS_SESSION_TOKEN",
                env_var="AWS_SESSION_TOKEN",
            ),
            SetupField(
                key="profile",
                label="AWS profile",
                kind="host-profile",
                required=False,
                advanced=True,
                help_text=("A named profile to resolve through boto3, when it is installed."),
                placeholder="default",
            ),
        ),
        model_selection="discover-or-manual",
        requirement_note=(
            "Leave every credential field empty to use the ambient AWS chain "
            "(environment, profile, or instance role). Otherwise supply either a Bedrock "
            "API key or an access key ID and secret access key."
        ),
    ),
    reasoning_translator=_translate_reasoning,
    default_capabilities=ModelCapabilities(features=Sourced(_BEDROCK_FEATURES, "default")),
)
"""Descriptor for the AWS Bedrock provider."""
