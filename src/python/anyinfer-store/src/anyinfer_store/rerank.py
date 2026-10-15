"""Optional second-stage reranking over a `VectorStore` query's top-k candidates.

A thin composition, not a new ranking algorithm: `query_and_rerank` calls
`VectorStore.query` for coarse candidates, then hands their text to
`anyinfer.AsyncClient.rerank` for the real second pass. This module owns none of the
ranking logic itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import VectorStoreError
from .store import VectorStore

if TYPE_CHECKING:
    from anyinfer import AsyncClient
    from anyinfer.types.operations import EmbeddingSpace, RankedItem

__all__ = ["query_and_rerank"]


async def query_and_rerank(
    store: VectorStore,
    query_vector: list[float],
    query_text: str,
    *,
    space: EmbeddingSpace,
    client: AsyncClient,
    rerank_target: str,
    candidate_k: int = 20,
    top_n: int | None = None,
) -> tuple[RankedItem, ...]:
    """Coarse vector search, then a real rerank pass over its candidates.

    Args:
        store: The store to search.
        query_vector: The query's embedding, in `space`.
        query_text: The query's original text — reranking scores text, not vectors.
        space: The embedding space `query_vector` was produced in; must be compatible
            with `store`'s bound space (see `VectorStore.query`).
        client: An `anyinfer.AsyncClient` to dispatch the rerank call through.
        rerank_target: The rerank target, e.g. ``"cohere:rerank-v3.5"``.
        candidate_k: How many coarse vector matches to hand to the reranker.
        top_n: Passed through to `AsyncClient.rerank`; `None` returns every candidate,
            reordered.

    Raises:
        anyinfer_store.VectorStoreError: A candidate has no stored `text` — reranking
            needs text, and this package never invents it.
    """
    candidates = store.query(query_vector, space=space, top_k=candidate_k)
    missing_text = [c.entry.id for c in candidates if c.entry.text is None]
    if missing_text:
        raise VectorStoreError(
            f"cannot rerank: entries stored without text: {missing_text} "
            "(pass text= to VectorStore.add for anything you intend to rerank)"
        )

    from anyinfer.types.operations import RerankDocument

    documents = [RerankDocument(id=c.entry.id, text=c.entry.text or "") for c in candidates]
    result = await client.rerank(query_text, documents, target=rerank_target, top_n=top_n)
    return result.items
