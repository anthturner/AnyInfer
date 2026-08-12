# Embed, store, and query — without a database

`anyinfer-store` is a small-scale, single-process, embedded vector store — never a
clustered, replicated, or "production vector database" story, permanently, not just for
v1. **Read that boundary before you read anything else on this page.**

**Target corpus size:** documents numbering in the thousands to low hundreds of thousands
of vectors, at typical embedding dimensions (384-3072). Not millions; not billions.
**Target deployment shape:** one process, one machine, one writer — no replication, no
sharding, no distributed consensus, no multi-writer coordination. It fits the same audience
`llama.cpp` local inference already serves: prototyping, personal tools, small internal
apps, notebooks, CLI utilities, single-tenant desktop or local-first applications.

**The explicit escape hatch:** when you outgrow this — millions of vectors, multi-region
reads, a managed control plane — the documented answer is to point a real vector database
(pgvector, Qdrant, Weaviate, Pinecone, ...) at `anyinfer.embed()`/`anyinfer.rerank()`
directly. Both consume the exact same public `EmbeddingResult`/`RerankResult` types this
package does, so nothing about how you call AnyInfer changes when you graduate — only where
the vectors end up. This package is never a stepping stone toward a hosted, scaled version
of itself; there isn't going to be one.

```bash
pip install -e src/anyinfer-store   # from a repository checkout, until a first PyPI release
```

## Embed, store, query

```python
import anyinfer as ai
from anyinfer_store import VectorStore

client = ai.Client([ai.ProviderSettings.of("ollama")])
store = VectorStore.open("corpus.db")

for doc_id, text in documents.items():
    result = client.embed([text], target="ollama:nomic-embed-text", input_type="document")
    store.add(doc_id, result.vectors[0], space=result.space, text=text)

query = client.embed(["what did the release notes say about pricing?"],
                      target="ollama:nomic-embed-text", input_type="query")
matches = store.query(query.vectors[0], space=query.space, top_k=5)
for match in matches:
    print(match.entry.id, match.score, match.entry.text)

store.close()
```

`VectorStore.query` refuses a query whose embedding space doesn't match the store's bound
space — the identical cross-space safety rule AnyInfer's own routing applies to a fallback
target (see [the embedding-space safety rule](../concepts/embeddings.md#the-embedding-space-safety-rule)),
applied to persistence: a wrong-but-plausible vector comparison fails loudly instead of
returning a confident-looking, meaningless result.

## Second-stage reranking

Coarse vector search, then a real rerank pass over its top-k candidates:

```python
from anyinfer_store import query_and_rerank

items = await query_and_rerank(
    store, query.vectors[0], "what did the release notes say about pricing?",
    space=query.space, client=async_client, rerank_target="cohere:rerank-v3.5",
    candidate_k=20, top_n=5,
)
```

Reranking needs text — an entry stored without `text=` cannot be reranked, and
`query_and_rerank` refuses rather than inventing a document from nothing.

## Lifecycle

```python
store.remove(doc_id)          # delete one entry
store.compact()               # reclaim disk space after deletions (VACUUM)
store.export_jsonl("out.jsonl")   # portable interchange format
another_store.import_jsonl("out.jsonl")
```

A store is one SQLite file — copying it is a valid backup or migration strategy on its own;
`export_jsonl`/`import_jsonl` exist for moving data between formats or into the escape
hatch above, not as the only way to move a store.

## What's deliberately not here

- **No approximate index.** Similarity search is brute-force cosine similarity, in pure
  Python — the whole point at this package's stated scale, and simpler to reason about
  than tuning an ANN index for a few thousand rows. `SIZE_WARNING_THRESHOLD` (200,000
  entries) is where `VectorStore.add` starts warning you may be past the point brute force
  stays comfortably fast — a signal, not a hard limit.
- **No network service of its own.** This is a library, matching AnyInfer core's own "no
  daemon" posture.
- **No multi-writer concurrency guarantees** beyond SQLite's own file-locking.
- **No automatic corpus collection.** Your application still owns deciding what gets
  embedded and stored — the same discipline `anyinfer.context` already applies: nothing is
  collected or embedded on your behalf.

See `plans/VECTOR_STORE_ADDON.md` in the repository for the full design record.
