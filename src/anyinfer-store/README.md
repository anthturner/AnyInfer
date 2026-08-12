# anyinfer-store

A small-scale, single-process, embedded vector store for `anyinfer.embed()`/`anyinfer.rerank()`
results — never a clustered, replicated, or "production vector database" story, permanently,
not just for v1.

**Target corpus size:** thousands to low hundreds of thousands of vectors. Not millions; not
billions. **Target deployment shape:** one process, one machine, one writer — no replication,
no sharding. When you outgrow this, point a real vector database (pgvector, Qdrant, Weaviate,
Pinecone, ...) at `anyinfer.embed()`/`anyinfer.rerank()` directly; both consume the same
public `EmbeddingResult`/`RerankResult` types this package does.

```bash
pip install -e src/anyinfer-store
```

```python
from anyinfer_store import VectorStore

store = VectorStore.open("corpus.db")
store.add("doc-1", result.vectors[0], space=result.space, text="the document text")
matches = store.query(query_vector, space=result.space, top_k=5)
```

See `plans/VECTOR_STORE_ADDON.md` and the published vector store guide for the full design
and the explicit, permanent scale boundary.
