"""A rerank-backed semantic ranker for context reduction.

`anyinfer.context` deliberately never imports the client — context reduction is a leaf
consumer, and its default ranking is lexical and offline. The seam it exposes is the
`SemanticRanker` protocol; this module is the client-side convenience constructor that
fills it, following the same shared-composition pattern as `build_catalog_view`.

```python
client = anyinfer.Client(providers)
reduction = anyinfer.context.select(
    documents,
    "how is retry backoff computed?",
    max_tokens=8_000,
    ranker=anyinfer.semantic_ranker(client, "cohere:rerank-v3.5"),
)
```
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ..types.operations import BatchPolicy, RerankDocument

if TYPE_CHECKING:
    from ..context import ContextDocument
    from ..context.rank import SemanticRanker
    from ..types.requests import Target
    from .sync_client import Client

__all__ = ["semantic_ranker"]


class _RerankBackedRanker:
    """Scores context documents with one rerank call through a synchronous client.

    Document ids are the context paths, so scores come back keyed exactly the way
    `context.select` reads them. A document the provider did not rank (a ``top_n``
    somewhere, a truncated tail) is simply absent and scores 0.0 downstream — never
    invented.
    """

    def __init__(self, client: Client, target: Target, batch: BatchPolicy | None) -> None:
        self._client = client
        self._target = target
        self._batch = batch

    def scores(self, documents: Sequence[ContextDocument], query: str) -> Mapping[str, float]:
        """Score every document's relevance to ``query``, keyed by document path."""
        if not documents:
            return {}
        result = self._client.rerank(
            query,
            [RerankDocument(id=doc.path, text=doc.content) for doc in documents],
            target=self._target,
            batch=self._batch,
        )
        return {item.document_id: item.score for item in result.items}


def semantic_ranker(
    client: Client, target: Target, *, batch: BatchPolicy | None = None
) -> SemanticRanker:
    """Build a `SemanticRanker` for `anyinfer.context.select` from a rerank target.

    One rerank call per reduction, spending real provider usage — which is exactly why
    context reduction does not do this by default. Reduction is synchronous, so this
    takes the synchronous `Client`.

    Args:
        client: An open synchronous client configured with the target's provider.
        target: A rerank-capable target, e.g. ``"cohere:rerank-v3.5"``.
        batch: Batching policy for corpora larger than the provider's document limit.
            Splitting a rerank produces chunk-local scores, so enabling
            ``rerank_cross_batch`` here trades global comparability for coverage — the
            result's warning says so.

    Returns:
        An object satisfying the `SemanticRanker` protocol.
    """
    return _RerankBackedRanker(client, target, batch)
