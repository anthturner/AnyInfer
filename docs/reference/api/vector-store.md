# Vector Store Add-On

`anyinfer_store`: a small-scale, single-process, embedded vector store; a separate
installable distribution, never imported by `anyinfer` core and never a dependency of it.
See the [vector store guide](../../guides/vector-store.md) for the full walkthrough and the
explicit, permanent scale boundary this package commits to.

```python
from anyinfer_store import VectorStore, query_and_rerank
```

<div class="anyinfer-api-block" markdown>

::: anyinfer_store.VectorStore

::: anyinfer_store.VectorEntry

::: anyinfer_store.QueryResult

::: anyinfer_store.query_and_rerank

::: anyinfer_store.SIZE_WARNING_THRESHOLD

::: anyinfer_store.VectorStoreError

::: anyinfer_store.EmbeddingSpaceMismatchError

</div>
