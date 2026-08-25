# Embed, Store, and Query Without a Database

`anyinfer-store` is an embedded vector store: one SQLite file that persists the vectors
[`client.embed()`](../concepts/embeddings.md) returns and answers similarity queries
in-process, with no server. It serves the same audience local inference already serves:
prototypes, personal tools, notebooks, small internal apps, single-tenant desktop and
local-first applications.

```bash
pip install -e src/anyinfer-store   # from a repository checkout, until a first PyPI release
```

The core package installs [as usual](installation.md); the store is a separate sub-project.

## Embed, Store, Query

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

!!! note "The scale boundary"
    The store targets corpora of thousands to low hundreds of thousands of vectors, at
    typical embedding dimensions (384–3072), in one process on one machine with one
    writer. Search is brute-force cosine similarity, and `VectorStore.add` warns past
    `SIZE_WARNING_THRESHOLD` (200,000 entries) that brute force may stop being comfortably
    fast. When you outgrow that (millions of vectors, multi-region reads, a managed
    control plane), point a real vector database (pgvector, Qdrant, Weaviate, Pinecone,
    ...) at `anyinfer.embed()`/`anyinfer.rerank()` directly: both consume the same public
    `EmbeddingResult`/`RerankResult` types this package does, so only where the vectors
    end up changes.

`VectorStore.query` refuses a query whose embedding space doesn't match the store's bound
space. That is, the identical cross-space safety rule AnyInfer's own routing applies to a
fallback target (see [the embedding-space safety rule](../concepts/embeddings.md#the-embedding-space-safety-rule))
is applied to persistence: a wrong-but-plausible vector comparison fails loudly instead of
returning a confident-looking, meaningless result.

## Second-Stage Reranking

Coarse vector search, then a real rerank pass over its top-k candidates:

```python
from anyinfer_store import query_and_rerank

items = await query_and_rerank(
    store, query.vectors[0], "what did the release notes say about pricing?",
    space=query.space, client=async_client, rerank_target="cohere:rerank-v3.5",
    candidate_k=20, top_n=5,
)
```

Reranking needs text: an entry stored without `text=` cannot be reranked, and
`query_and_rerank` refuses rather than inventing a document from nothing.

The [semantic search example](../examples/semantic-search.md) puts embedding, storage, and
reranking together end to end.

## Lifecycle

```python
store.remove(doc_id)          # delete one entry
store.compact()               # reclaim disk space after deletions (VACUUM)
store.export_jsonl("out.jsonl")   # portable interchange format
another_store.import_jsonl("out.jsonl")
```

A store is one SQLite file; copying it is a valid backup or migration strategy on its own, and
`export_jsonl`/`import_jsonl` exist for moving data between formats or into a real vector
database, not as the only way to move a store.

## Scope

The store is a library with no network service of its own, matching AnyInfer core's
no-daemon posture, and it collects nothing: your application decides what gets embedded
and stored, the same line [`anyinfer.context`](../concepts/context-reduction.md) draws.
Concurrent writers get SQLite's own file-locking and nothing more. DESIGN.md §29 in the
repository is the full design record.

!!! tip "Key Takeaways"
    - Every entry carries its embedding space, and a query from a different space is
      refused rather than compared (the same safety rule routing applies to embedding
      fallback).
    - Reranking needs stored text; an entry added without `text=` cannot be reranked.
    - A store is one SQLite file, so copying it is a complete backup;
      `export_jsonl`/`import_jsonl` cover interchange.
    - Outgrowing the store changes where vectors land, not how you call AnyInfer; real
      vector databases consume the same `EmbeddingResult`/`RerankResult` types.

## See Also

<div class="anyinfer-see-also" markdown>

- [Embeddings and reranking](../concepts/embeddings.md): the types and the cross-space
  safety rule.
- [Semantic search example](../examples/semantic-search.md): the full pipeline in one
  script.
- [Installation](installation.md): extras and sub-projects.

</div>
