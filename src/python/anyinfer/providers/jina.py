"""Jina AI (`contracts/jina.md`).

A specialist retrieval provider: embeddings and reranking, no generation. The
embeddings API is OpenAI-*shaped* but carries Jina's own ``task`` vocabulary and
``late_chunking``. Jina documents a model-listing endpoint, but this bounded SDK subset
keeps manual model selection and empty discovery — a dedicated adapter, not a preset.

Jina v3's task vocabulary covers all four normalized intents: ``retrieval.query``,
``retrieval.passage``, ``classification``, and ``separation``. V4 accepts only query and
document, while the four known v5 models use their model-specific ``clustering`` spelling.
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

__all__ = ["JinaAdapter", "descriptor"]

_DEFAULT_BASE_URL = "https://api.jina.ai/v1"

_TASKS: Mapping[str, str] = {
    "query": "retrieval.query",
    "document": "retrieval.passage",
    "classification": "classification",
    "clustering": "separation",
}
"""Normalized intents mapped onto Jina ``task`` values.

The model-specific v5 clustering exception is applied in `_build_embedding_payload`.
"""

_V5_CLUSTERING_MODELS = frozenset(
    {
        "jina-embeddings-v5-text-small",
        "jina-embeddings-v5-text-nano",
        "jina-embeddings-v5-omni-small",
        "jina-embeddings-v5-omni-nano",
    }
)
"""Known v5 IDs whose model-specific task enum spells clustering literally."""

_V4_INPUT_INTENTS = frozenset({"query", "document"})
"""Jina v4's documented embedding-task subset."""


class JinaAdapter(OpenAIShapedRetrievalMixin):
    """Adapter for Jina AI's embeddings and reranker APIs.

    Discovery (``list_models``/``health``), lifecycle (``aclose``), and the OpenAI-shaped
    embeddings response parsing all come from `OpenAIShapedRetrievalMixin` — Jina's only
    genuinely distinct piece on the embeddings side is its ``task`` request vocabulary,
    built by `_build_embedding_payload` below. Reranking has its own response envelope
    (``results`` rather than ``data``, and a plain ``top_n``), so it stays here in full.
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
            proxy=config.proxy,
            verify=config.verify,
            client_cert=config.client_cert,
            origin_bound_header_names=("authorization", *config.headers.keys()),
        )

    # ---- embedding ---------------------------------------------------------------------

    def _build_embedding_payload(self, req: EmbeddingWireRequest) -> dict[str, Any]:
        """Build ``POST /v1/embeddings`` body in Jina's own dialect."""
        payload: dict[str, Any] = {"model": req.model, "input": list(req.inputs)}
        if (
            req.input_type is not None
            and req.input_type in _TASKS
            and (req.model != "jina-embeddings-v4" or req.input_type in _V4_INPUT_INTENTS)
        ):
            payload["task"] = (
                "clustering"
                if req.input_type == "clustering" and req.model in _V5_CLUSTERING_MODELS
                else _TASKS[req.input_type]
            )
        if req.dimensions is not None:
            payload["dimensions"] = req.dimensions
        payload.update(req.extra_options)
        return payload

    # ---- reranking ---------------------------------------------------------------------

    async def rerank(self, req: RerankWireRequest) -> RerankWireResult:
        """Run one rerank call against ``POST /v1/rerank``.

        Jina takes ``top_n`` directly; ``index`` is positional within the submitted
        ``documents`` array and is mapped back onto the caller-supplied document index,
        exactly as the Cohere and TEI adapters do. The response nests ranks under
        ``results`` rather than ``data``.
        """
        payload: dict[str, Any] = {
            "model": req.model,
            "query": req.query,
            "documents": [doc.text for doc in req.documents],
        }
        if req.top_n is not None:
            payload["top_n"] = req.top_n
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
        data = payload.get("results")
        if not isinstance(data, list):
            raise ProviderError("rerank response is missing a 'results' array", phase="validate")
        items: list[WireRankedItem] = []
        for entry in data:
            if not isinstance(entry, Mapping):
                raise ProviderError(
                    "rerank response contains a non-object entry", phase="validate"
                )
            position = entry.get("index")
            score = entry.get("relevance_score")
            if not isinstance(position, int) or isinstance(position, bool):
                raise ProviderError("rerank entry is missing an integer 'index'", phase="validate")
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


_EMBED_INTENTS: tuple[EmbeddingInputIntent, ...] = (
    "query",
    "document",
    "classification",
    "clustering",
)

_STATIC_EMBEDDING_CAPABILITIES = {
    # Verified against jina.ai/embeddings and Jina's own model publications on
    # 2026-08-12. No per-request input ceiling is documented ("batches internally"), so
    # max_batch_inputs stays None — over-ceiling requests refuse locally rather than
    # split at a guessed size. Default dimensions are not uniformly stated; None.
    "jina-embeddings-v3": EmbeddingCapabilities(input_intents=_EMBED_INTENTS),
    "jina-embeddings-v4": EmbeddingCapabilities(input_intents=("query", "document")),
}
_STATIC_EMBEDDING_CAPABILITIES.update(
    {
        # jina.ai/embeddings (verified 2026-10-15): the v5 omni models also
        # accept text, but this adapter intentionally retains its text-only
        # input contract.  Both v5 families support Matryoshka dimensions.
        "jina-embeddings-v5-text-small": EmbeddingCapabilities(
            dimensions=1_024,
            dimension_choices=(32, 64, 128, 256, 512, 1_024),
            max_input_tokens=32_768,
            input_intents=_EMBED_INTENTS,
        ),
        "jina-embeddings-v5-omni-small": EmbeddingCapabilities(
            dimensions=1_024,
            dimension_choices=(32, 64, 128, 256, 512, 1_024),
            max_input_tokens=32_768,
            input_intents=_EMBED_INTENTS,
        ),
        "jina-embeddings-v5-text-nano": EmbeddingCapabilities(
            dimensions=768,
            dimension_choices=(32, 64, 128, 256, 512, 768),
            max_input_tokens=8_192,
            input_intents=_EMBED_INTENTS,
        ),
        "jina-embeddings-v5-omni-nano": EmbeddingCapabilities(
            dimensions=768,
            dimension_choices=(32, 64, 128, 256, 512, 768),
            max_input_tokens=8_192,
            input_intents=_EMBED_INTENTS,
        ),
    }
)

_STATIC_RERANK_CAPABILITIES = {
    # jina.ai/reranker (verified 2026-08-12): "no hard limit on the number of documents
    # per request" — so none is declared, and the sanity ceiling governs.
    model: RerankCapabilities(native_top_n=True)
    for model in (
        "jina-reranker-v3",
        "jina-reranker-v3.5",
        "jina-reranker-m0",
        "jina-reranker-v2-base-multilingual",
    )
}


descriptor = ProviderDescriptor(
    id="jina",
    display_name="Jina AI",
    aliases=("jinaai",),
    factory=JinaAdapter,
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
                placeholder="env://JINA_API_KEY or a literal key",
                env_var="JINA_API_KEY",
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
"""Descriptor for the Jina AI provider."""
