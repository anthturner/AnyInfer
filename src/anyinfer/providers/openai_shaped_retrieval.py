"""Shared plumbing for OpenAI-*shaped*, retrieval-only providers.

Jina and Voyage are both specialist embeddings-and-reranking providers with no generation
endpoint, no model-listing endpoint, and an embeddings response that carries the OpenAI
``{data: [{index, embedding}]}`` envelope even though the *request* vocabulary is each
provider's own (``task`` for Jina; ``input_type``/``output_dimension`` for Voyage). That
request-side divergence is why this is a separate module from `openai_compat_embeddings.py`
rather than a rename of it — a preset there opts into the OpenAI-compatible dialect
end-to-end, but these two only share the response shape.

This module's response parsing is also intentionally stricter than
`OpenAICompatEmbeddingsMixin`'s: a missing or malformed entry raises `ProviderError` instead
of being silently skipped, matching Jina's and Voyage's own contract snapshots and preserved
here rather than loosened to match the other mixin.

Composed into an adapter class expecting the host to provide ``self._client`` (an
`httpx2.AsyncClient` already pointed at the right base URL), ``self.provider_id``, and
``self._build_embedding_payload`` (the one genuinely provider-specific piece: the request
vocabulary) — the same shape `OpenAICompatEmbeddingsMixin` expects of its host, so the two
mixins read the same way side by side.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import httpx2

from ..errors import ProviderError
from ..types.capabilities import DiscoveredModel, Health
from ..types.results import Usage
from .base import EmbeddingWireRequest, EmbeddingWireResult
from .http import check_response_size, classify_status, map_transport_error, read_error_detail

if TYPE_CHECKING:
    from typing import Protocol

    class _RetrievalHost(Protocol):
        """The attributes a host adapter must provide; checked only by the type checker.

        `OpenAIShapedRetrievalMixin` does not inherit this, for the same reason
        `OpenAICompatEmbeddingsMixin`'s analogous protocol is not inherited: doing so would
        give the mixin its own (unimplemented) copies of these members, which shadow the
        host class's real ones when the mixin is listed first in an MRO.
        """

        provider_id: str
        _client: httpx2.AsyncClient

        def _build_embedding_payload(self, req: EmbeddingWireRequest) -> dict[str, Any]: ...

__all__ = ["OpenAIShapedRetrievalMixin", "parse_retrieval_usage"]


def parse_retrieval_usage(payload: Any) -> Usage | None:
    """Read a Jina/Voyage-shaped usage block: ``total_tokens`` is all either reports."""
    if not isinstance(payload, Mapping):
        return None
    total = payload.get("total_tokens")
    if isinstance(total, int) and not isinstance(total, bool):
        return Usage(total_tokens=total)
    return None


class OpenAIShapedRetrievalMixin:
    """Discovery, lifecycle, and embeddings-response parsing shared by Jina and Voyage.

    What stays on the adapter subclass: authentication headers, the default base URL, the
    static model-capability tables, and ``_build_embedding_payload`` — the one place the two
    providers' request vocabularies actually diverge.
    """

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """This provider documents no listing endpoint; the answer is honestly empty.

        The models an adapter built on this mixin was verified against live in the
        descriptor's static capability tables, which is catalog knowledge rather than
        discovery — reporting them here would stamp ``discovered`` provenance on something
        the provider never said.
        """
        return ()

    async def health(self) -> Health:
        """Reachability probe: any HTTP answer from the endpoint counts.

        There is no documented health or listing route, so this asks for one and treats
        *any* HTTP status — including the expected 404 — as proof the service answered.
        Only a transport failure reports unhealthy.
        """
        host: _RetrievalHost = self  # type: ignore[assignment]
        try:
            response = await host._client.get("/models")
        except httpx2.HTTPError as exc:
            return Health(ok=False, detail=str(exc)[:200])
        return Health(
            ok=True,
            detail=f"endpoint reachable (HTTP {response.status_code}; no listing API)",
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP transport."""
        host: _RetrievalHost = self  # type: ignore[assignment]
        await host._client.aclose()

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one embedding call against ``POST /embeddings``."""
        host: _RetrievalHost = self  # type: ignore[assignment]
        payload = host._build_embedding_payload(req)
        try:
            response = await host._client.post(
                "/embeddings", json=payload, timeout=req.timeout_s
            )
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=host.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            raise classify_status(
                response.status_code,
                provider=host.provider_id,
                detail=read_error_detail(response.content),
                headers=response.headers,
                phase="generate",
            )
        check_response_size(response.content, req.max_response_bytes, provider=host.provider_id)
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
            usage=parse_retrieval_usage(payload.get("usage")),
            raw=payload,
        )
