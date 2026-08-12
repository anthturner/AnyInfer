"""anyinfer-store: a small-scale, single-process, embedded vector store.

Never imported by `anyinfer` core, and never a dependency of it. See the module docstring
of `store` for the permanent scale boundary this package commits to, and
`plans/VECTOR_STORE_ADDON.md` for the full design record.
"""

from __future__ import annotations

from .errors import EmbeddingSpaceMismatchError, VectorStoreError
from .rerank import query_and_rerank
from .store import SIZE_WARNING_THRESHOLD, QueryResult, VectorEntry, VectorStore

__all__ = [
    "SIZE_WARNING_THRESHOLD",
    "EmbeddingSpaceMismatchError",
    "QueryResult",
    "VectorEntry",
    "VectorStore",
    "VectorStoreError",
    "query_and_rerank",
]
