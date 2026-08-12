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

from collections.abc import Mapping, Sequence
from typing import Any

import httpx2

from ..errors import ProviderError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Health
from ..types.operations import (
    EmbeddingCapabilities,
    EmbeddingInputIntent,
    RerankCapabilities,
)
from ..types.results import Usage
from .base import (
    EmbeddingWireRequest,
    EmbeddingWireResult,
    ProviderConfig,
    RerankWireRequest,
    RerankWireResult,
    WireRankedItem,
)
from .http import build_client, classify_status, map_transport_error, read_error_detail

__all__ = ["VoyageAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://api.voyageai.com/v1"

_INPUT_TYPES: Mapping[str, str] = {"query": "query", "document": "document"}
"""The two intents Voyage documents (verified 2026-08-12); the rest are never sent."""


class VoyageAdapter:
    """Adapter for Voyage AI's embeddings and reranker APIs."""

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

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """Voyage documents no listing endpoint; the answer is honestly empty.

        The models this adapter was verified against live in the descriptor's static
        capability tables, which is catalog knowledge rather than discovery — reporting
        them here would stamp ``discovered`` provenance on something the provider never
        said.
        """
        return ()

    async def health(self) -> Health:
        """Reachability probe: any HTTP answer from the endpoint counts.

        There is no documented health or listing route, so this asks for one and treats
        *any* HTTP status — including the expected 404 — as proof the service answered.
        Only a transport failure reports unhealthy.
        """
        try:
            response = await self._client.get("/models")
        except httpx2.HTTPError as exc:
            return Health(ok=False, detail=str(exc)[:200])
        return Health(
            ok=True,
            detail=f"endpoint reachable (HTTP {response.status_code}; no listing API)",
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()

    # ---- embedding ---------------------------------------------------------------------

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one embedding call against ``POST /v1/embeddings`` (Voyage's own dialect)."""
        payload: dict[str, Any] = {"model": req.model, "input": list(req.inputs)}
        if req.input_type is not None and req.input_type in _INPUT_TYPES:
            payload["input_type"] = _INPUT_TYPES[req.input_type]
        if req.dimensions is not None:
            payload["output_dimension"] = req.dimensions
        payload.update(req.extra_options)
        try:
            response = await self._client.post("/embeddings", json=payload, timeout=req.timeout_s)
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
        return self._parse_embed_response(req, response.json())

    def _parse_embed_response(
        self, req: EmbeddingWireRequest, payload: Any
    ) -> EmbeddingWireResult:
        if not isinstance(payload, Mapping):
            raise ProviderError("embeddings response is not a JSON object", phase="validate")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderError(
                "embeddings response is missing a 'data' array", phase="validate"
            )
        if len(data) != len(req.inputs):
            raise ProviderError(
                f"embeddings response returned {len(data)} vectors for "
                f"{len(req.inputs)} inputs",
                phase="validate",
            )
        # Entries carry their input index; order by it rather than trusting arrival order.
        vectors: list[tuple[float, ...] | None] = [None] * len(req.inputs)
        for entry in data:
            if not isinstance(entry, Mapping):
                raise ProviderError(
                    "embeddings response contains a non-object entry", phase="validate"
                )
            index = entry.get("index")
            values = entry.get("embedding")
            if not isinstance(index, int) or isinstance(index, bool):
                raise ProviderError(
                    "embeddings entry is missing an integer 'index'", phase="validate"
                )
            if not (0 <= index < len(req.inputs)) or vectors[index] is not None:
                raise ProviderError(
                    f"embeddings entry has an out-of-range or duplicate index {index}",
                    phase="validate",
                )
            if not isinstance(values, list):
                raise ProviderError(
                    "embeddings entry is missing an 'embedding' array", phase="validate"
                )
            vectors[index] = tuple(float(v) for v in values)
        model = payload.get("model")
        return EmbeddingWireResult(
            vectors=tuple(v for v in vectors if v is not None),
            model=model if isinstance(model, str) else None,
            dimensions=len(vectors[0]) if vectors and vectors[0] is not None else None,
            usage=_parse_usage(payload.get("usage")),
            raw=payload,
        )

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
            index = (
                req.documents[position].index
                if 0 <= position < len(req.documents)
                else position
            )
            items.append(WireRankedItem(index=index, score=float(score)))
        model = payload.get("model")
        return RerankWireResult(
            items=tuple(items),
            model=model if isinstance(model, str) else None,
            usage=_parse_usage(payload.get("usage")),
            raw=payload,
        )


def _parse_usage(payload: Any) -> Usage | None:
    """Read Voyage's usage block: ``total_tokens`` is all it reports."""
    if not isinstance(payload, Mapping):
        return None
    total = payload.get("total_tokens")
    if isinstance(total, int) and not isinstance(total, bool):
        return Usage(total_tokens=total)
    return None


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
