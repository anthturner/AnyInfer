"""Hugging Face Text Embeddings Inference (`contracts/tei.md`).

TEI serves exactly **one model per server** — an embedding model, a reranker, or a
sequence classifier — chosen when the container starts. That shape makes it this
library's first retrieval-only provider: the descriptor declares no generation at all,
and which operation a given endpoint actually serves is *discovered* from ``GET /info``'s
``model_type`` rather than assumed from configuration.

Because the server holds one model, the model half of a target string is advisory:
``tei:anything`` reaches the same model, and discovery reports the real id. The native
``/embed`` and ``/rerank`` dialects are spoken directly — TEI also exposes an
OpenAI-compatible ``/v1/embeddings``, but the native routes carry the reranker, which is
the reason to point this library at TEI in the first place.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx2

from ..errors import ProviderError
from ..registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Health, ModelCapabilities, Sourced
from ..types.operations import InferenceOperation
from .base import (
    EmbeddingWireRequest,
    EmbeddingWireResult,
    ProviderConfig,
    RerankWireRequest,
    RerankWireResult,
    WireRankedItem,
    resolve_rerank_index,
)
from .http import build_client, check_response_size, classify_status, map_transport_error

__all__ = ["TEIAdapter", "descriptor"]

_DEFAULT_BASE_URL = "http://127.0.0.1:8080"

_MODEL_TYPE_OPERATIONS: Mapping[str, frozenset[InferenceOperation]] = {
    "embedding": frozenset({"embedding"}),
    "reranker": frozenset({"rerank"}),
}
"""``/info`` ``model_type`` values mapped to operations (verified 2026-08-12).

A ``classifier`` server serves neither normalized operation and reports an empty set.
"""


class TEIAdapter:
    """Adapter for a Text Embeddings Inference server's native dialect."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self.provider_id = config.provider_id
        headers = {"content-type": "application/json", "accept": "application/json"}
        if config.api_key:
            # Only meaningful when the server was started with --api-key.
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
        )

    # ---- discovery -------------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """Report the server's one model, with its operation discovered from ``/info``."""
        info = await self._info()
        model_id = info.get("model_id")
        if not isinstance(model_id, str) or not model_id:
            return ()
        model_type = info.get("model_type")
        operations: Sourced[frozenset[InferenceOperation]] | None = None
        if isinstance(model_type, Mapping) and len(model_type) == 1:
            # The spec spells model_type as a tagged object, e.g. {"embedding": {...}}.
            (kind,) = model_type.keys()
            operations = Sourced(
                _MODEL_TYPE_OPERATIONS.get(str(kind), frozenset()), "discovered"
            )
        elif isinstance(model_type, str):
            operations = Sourced(
                _MODEL_TYPE_OPERATIONS.get(model_type, frozenset()), "discovered"
            )
        return (
            DiscoveredModel(
                id=model_id,
                capabilities=ModelCapabilities(operations=operations),
            ),
        )

    async def health(self) -> Health:
        """Probe readiness via ``/info``."""
        try:
            info = await self._info()
        except ProviderError as exc:
            return Health(ok=False, detail=exc.detail[:200])
        model_id = info.get("model_id")
        return Health(ok=True, detail=f"serving {model_id}" if model_id else "")

    async def _info(self) -> Mapping[str, Any]:
        try:
            response = await self._client.get("/info")
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="discover") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=_error_detail(response.content),
                headers=response.headers,
                phase="discover",
            )
        payload = response.json()
        return payload if isinstance(payload, Mapping) else {}

    # ---- embedding ---------------------------------------------------------------------

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one embedding call against ``POST /embed``.

        The server embeds with ``normalize: true`` unless told otherwise (documented
        default, verified 2026-08-12), so the result reports ``normalized`` from what was
        actually sent rather than guessing.
        """
        payload: dict[str, Any] = {"inputs": list(req.inputs)}
        if req.dimensions is not None:
            payload["dimensions"] = req.dimensions
        payload.update(req.extra_options)
        try:
            response = await self._client.post("/embed", json=payload, timeout=req.timeout_s)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=_error_detail(response.content),
                headers=response.headers,
                phase="generate",
            )
        check_response_size(response.content, req.max_response_bytes, provider=self.provider_id)
        body = response.json()
        if not isinstance(body, list):
            raise ProviderError("embed response is not an array of vectors", phase="validate")
        if len(body) != len(req.inputs):
            raise ProviderError(
                f"embed response returned {len(body)} vectors for {len(req.inputs)} inputs",
                phase="validate",
            )
        vectors: list[tuple[float, ...]] = []
        for entry in body:
            if not isinstance(entry, list):
                raise ProviderError(
                    "embed response contains a non-array vector", phase="validate"
                )
            vectors.append(tuple(float(v) for v in entry))
        sent_normalize = payload.get("normalize", True)
        return EmbeddingWireResult(
            vectors=tuple(vectors),
            dimensions=len(vectors[0]) if vectors else None,
            normalized=sent_normalize if isinstance(sent_normalize, bool) else None,
            usage=None,  # TEI reports no usage; None is the honest answer, never zero.
            raw=body,
        )

    # ---- reranking ---------------------------------------------------------------------

    async def rerank(self, req: RerankWireRequest) -> RerankWireResult:
        """Run one rerank call against ``POST /rerank``.

        The endpoint has no native ``top_n`` and its spec does not state a result order,
        so the adapter sorts by score descending and truncates — a deterministic
        translation onto the normalized ranked contract, recorded in the snapshot.
        ``index`` is positional within the ``texts`` array sent; it is mapped back onto
        the caller-supplied `RerankWireDocument.index` exactly as the Cohere adapter does.
        """
        payload: dict[str, Any] = {
            "query": req.query,
            "texts": [doc.text for doc in req.documents],
            "return_text": False,
        }
        payload.update(req.extra_options)
        try:
            response = await self._client.post("/rerank", json=payload, timeout=req.timeout_s)
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=self.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=self.provider_id,
                detail=_error_detail(response.content),
                headers=response.headers,
                phase="generate",
            )
        check_response_size(response.content, req.max_response_bytes, provider=self.provider_id)
        body = response.json()
        if not isinstance(body, list):
            raise ProviderError("rerank response is not an array of ranks", phase="validate")
        items: list[WireRankedItem] = []
        for entry in body:
            if not isinstance(entry, Mapping):
                raise ProviderError(
                    "rerank response contains a non-object rank", phase="validate"
                )
            position = entry.get("index")
            score = entry.get("score")
            if not isinstance(position, int) or isinstance(position, bool):
                raise ProviderError(
                    "rerank rank is missing an integer 'index'", phase="validate"
                )
            if not isinstance(score, int | float) or isinstance(score, bool):
                raise ProviderError(
                    "rerank rank is missing a numeric 'score'", phase="validate"
                )
            index = resolve_rerank_index(req, position)
            items.append(WireRankedItem(index=index, score=float(score)))
        items.sort(key=lambda item: item.score, reverse=True)
        if req.top_n is not None:
            items = items[: req.top_n]
        return RerankWireResult(items=tuple(items), usage=None, raw=body)

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        await self._client.aclose()


def _error_detail(content: bytes) -> str:
    """Read TEI's ``{error, error_type}`` body, degrading to the raw text."""
    try:
        payload = json.loads(content)
    except ValueError:
        return content.decode("utf-8", errors="replace")[:300]
    if isinstance(payload, Mapping) and isinstance(payload.get("error"), str):
        return str(payload["error"])[:300]
    return content.decode("utf-8", errors="replace")[:300]


descriptor = ProviderDescriptor(
    id="tei",
    display_name="Text Embeddings Inference",
    aliases=("text-embeddings-inference",),
    factory=TEIAdapter,
    locality="local",
    default_base_url=_DEFAULT_BASE_URL,
    requires_base_url=False,
    operations=frozenset({"embedding", "rerank"}),
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="base_url",
                label="Base URL",
                kind="endpoint",
                required=False,
                advanced=True,
                default_value=_DEFAULT_BASE_URL,
                help_text=f"Defaults to {_DEFAULT_BASE_URL}; one TEI server serves one model.",
            ),
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=False,
                advanced=True,
                help_text="Only when the server was started with --api-key.",
                placeholder="env://TEI_API_KEY or a literal key",
                env_var="TEI_API_KEY",
            ),
        ),
        model_selection="discover-or-manual",
    ),
)
"""Descriptor for the Text Embeddings Inference provider."""
