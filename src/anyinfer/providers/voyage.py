"""Voyage AI (`contracts/voyage.md`).

A specialist retrieval provider: embeddings and reranking, no generation. The API is
OpenAI-*shaped* but not OpenAI-compatible where it matters — `input_type` and
`output_dimension` are Voyage's own spellings, rerank takes `top_k`, and there is no
model-listing endpoint at all — so this is a dedicated adapter rather than a preset.

Voyage distinguishes exactly two input intents, ``query`` and ``document``; the other
two normalized intents have no wire value here, are never sent, and surface through the
core's ignored-intent warning via the declared capability set.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx2

from ..errors import ProviderError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.operations import (
    EmbeddingCapabilities,
    EmbeddingInputIntent,
    RerankCapabilities,
)
from .base import (
    EmbeddingWireRequest,
    ProviderConfig,
    RerankWireRequest,
    RerankWireResult,
    WireRankedItem,
    resolve_rerank_index,
)
from .http import (
    build_client,
    check_response_size,
    classify_status,
    map_transport_error,
    read_error_detail,
)
from .openai_shaped_retrieval import OpenAIShapedRetrievalMixin, parse_retrieval_usage

__all__ = ["VoyageAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://api.voyageai.com/v1"

_INPUT_TYPES: Mapping[str, str] = {"query": "query", "document": "document"}
"""The two intents Voyage documents (verified 2026-08-12); the rest are never sent."""


class VoyageAdapter(OpenAIShapedRetrievalMixin):
    """Adapter for Voyage AI's embeddings and reranker APIs.

    Discovery (``list_models``/``health``), lifecycle (``aclose``), and the OpenAI-shaped
    embeddings response parsing all come from `OpenAIShapedRetrievalMixin` — Voyage's only
    genuinely distinct piece on the embeddings side is its ``input_type``/``output_dimension``
    request vocabulary, built by `_build_embedding_payload` below. Reranking spells its
    truncation parameter ``top_k`` and stays here in full.
    """

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

    # ---- embedding ---------------------------------------------------------------------

    def _build_embedding_payload(self, req: EmbeddingWireRequest) -> dict[str, Any]:
        """Build ``POST /v1/embeddings`` body in Voyage's own dialect."""
        payload: dict[str, Any] = {"model": req.model, "input": list(req.inputs)}
        if req.input_type is not None and req.input_type in _INPUT_TYPES:
            payload["input_type"] = _INPUT_TYPES[req.input_type]
        if req.dimensions is not None:
            payload["output_dimension"] = req.dimensions
        payload.update(req.extra_options)
        return payload

    # ---- reranking ---------------------------------------------------------------------

    async def rerank(self, req: RerankWireRequest) -> RerankWireResult:
        """Run one rerank call against ``POST /v1/rerank``.

        Voyage spells the truncation parameter ``top_k``; ``index`` is positional within
        the submitted ``documents`` array and is mapped back onto the caller-supplied
        document index, exactly as the Cohere and TEI adapters do.
        """
        payload: dict[str, Any] = {
            "model": req.model,
            "query": req.query,
            "documents": [doc.text for doc in req.documents],
        }
        if req.top_n is not None:
            payload["top_k"] = req.top_n
        payload.update(req.extra_options)
        try:
            response = await self._client.post("/rerank", json=payload, timeout=req.timeout_s)
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
        return self._parse_rerank_response(req, response.json())

    def _parse_rerank_response(self, req: RerankWireRequest, payload: Any) -> RerankWireResult:
        if not isinstance(payload, Mapping):
            raise ProviderError("rerank response is not a JSON object", phase="validate")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderError("rerank response is missing a 'data' array", phase="validate")
        items: list[WireRankedItem] = []
        for entry in data:
            if not isinstance(entry, Mapping):
                raise ProviderError(
                    "rerank response contains a non-object entry", phase="validate"
                )
            position = entry.get("index")
            score = entry.get("relevance_score")
            if not isinstance(position, int) or isinstance(position, bool):
                raise ProviderError(
                    "rerank entry is missing an integer 'index'", phase="validate"
                )
            if not isinstance(score, int | float) or isinstance(score, bool):
                raise ProviderError(
                    "rerank entry is missing a numeric 'relevance_score'", phase="validate"
                )
            index = resolve_rerank_index(req, position)
            items.append(WireRankedItem(index=index, score=float(score)))
        model = payload.get("model")
        return RerankWireResult(
            items=tuple(items),
            model=model if isinstance(model, str) else None,
            usage=parse_retrieval_usage(payload.get("usage")),
            raw=payload,
        )


_EMBED_INTENTS: tuple[EmbeddingInputIntent, ...] = ("query", "document")

_STATIC_EMBEDDING_CAPABILITIES = {
    # Verified against docs.voyageai.com/reference/embeddings-api on 2026-08-12: at most
    # 1,000 inputs per request (endpoint-wide); input_type accepts query/document only.
    # Per-model default dimensions are not stated, so they stay None.
    model: EmbeddingCapabilities(max_batch_inputs=1_000, input_intents=_EMBED_INTENTS)
    for model in (
        "voyage-4-large",
        "voyage-4",
        "voyage-4-lite",
        "voyage-3-large",
        "voyage-3.5",
        "voyage-3.5-lite",
        "voyage-code-3",
        "voyage-finance-2",
        "voyage-law-2",
    )
}

_STATIC_RERANK_CAPABILITIES = {
    # docs.voyageai.com/reference/reranker-api (verified 2026-08-12): "The number of
    # documents cannot exceed 1,000" — a hard limit, not a recommendation.
    model: RerankCapabilities(max_documents=1_000, native_top_n=True)
    for model in ("rerank-2.5", "rerank-2.5-lite", "rerank-2", "rerank-2-lite")
}


descriptor = ProviderDescriptor(
    id="voyage",
    display_name="Voyage AI",
    aliases=("voyageai",),
    factory=VoyageAdapter,
    locality="hosted",
    default_base_url=_DEFAULT_BASE_URL,
    requires_base_url=False,
    operations=frozenset({"embedding", "rerank"}),
    static_embedding_capabilities=_STATIC_EMBEDDING_CAPABILITIES,
    static_rerank_capabilities=_STATIC_RERANK_CAPABILITIES,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=True,
                help_text="Accepts a literal, env://VAR, or credential://system/name.",
                placeholder="env://VOYAGE_API_KEY or a literal key",
                env_var="VOYAGE_API_KEY",
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
        model_selection="manual-only",
    ),
)
"""Descriptor for the Voyage AI provider."""
