# Semantic Search over a Small Corpus

For a corpus small enough to hold in memory, semantic search needs no vector store: this
example embeds a handful of documents, embeds a query with the matching intent, and ranks
by cosine similarity itself, with persistence left to the optional
[`anyinfer-store`](../guides/vector-store.md) add-on. As written it runs offline against
`anyinfer.testing.FakeEmbeddingRerankProvider` (a deterministic pseudo-embedding that
proves the wiring, not retrieval quality), so point `EMBED_TARGET`/`RERANK_TARGET` at a
real provider (`ollama:nomic-embed-text`, `openai:text-embedding-3-small`, a local
[TEI](../providers/tei.md) server) when you want ranking by meaning.

```python
import math

import anyinfer as ai
from anyinfer.testing import FakeEmbeddingRerankProvider

provider = FakeEmbeddingRerankProvider(
    "offline", embedding_dimensions={"embed-small": 8}, rerank_models=["rerank-small"]
)
registry = ai.ProviderRegistry(load_builtins=False, load_entry_points=False)
provider.register(registry)
EMBED_TARGET = "offline:embed-small"
RERANK_TARGET = "offline:rerank-small"

CORPUS = [
    "The moon landing happened in 1969",
    "Sourdough bread needs a live starter",
    "Apollo 11 was the spacecraft that carried astronauts to the moon",
]
QUERY = "Apollo spacecraft that reached the moon"


def cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


with ai.Client(
    [ai.ProviderSettings.of(provider.provider_id)],
    registry=registry,
    use_default_catalog=False,
) as client:
    # Query and document embeddings must be built with matching intent — see below —
    # and, for cross-provider safety, from the same target.
    corpus_embedded = client.embed(CORPUS, target=EMBED_TARGET, input_type="document")
    query_embedded = client.embed(QUERY, target=EMBED_TARGET, input_type="query")
    query_vector = query_embedded.vectors[0].values

    ranked = sorted(
        zip(CORPUS, corpus_embedded.vectors, strict=True),
        key=lambda pair: cosine_similarity(query_vector, pair[1].values),
        reverse=True,
    )
    best_match, _ = ranked[0]  # the fake's hash-based vectors make this arbitrary; see above

    # A reranker scores the same corpus against a query in one call, no manual
    # similarity math needed — worth reaching for once a corpus outgrows "just loop over
    # the vectors yourself."
    reranked = client.rerank(QUERY, CORPUS, target=RERANK_TARGET)
    assert CORPUS[reranked.items[0].index] == (
        "Apollo 11 was the spacecraft that carried astronauts to the moon"
    )
```

Intents (`input_type`), the
[embedding-space safety rule](../concepts/embeddings.md#the-embedding-space-safety-rule)
that `result.space` implements, and batching are core concepts, covered in
[Embeddings and reranking](../concepts/embeddings.md); what follows is specific to
building a small in-memory index.

## Index/Query Compatibility, Applied

`result.space` is exactly what you store alongside the vectors so a later query can
check it matches before comparing anything:

```python
if query_embedded.space.compatible_with(stored_space):
    ...  # safe to compare
```

## Fallback and Local Embeddings

`operation_routes={"embedding": ai.Route(targets=[...])}` on the client (or
`--config`'s `operation_routes` key) sets the default route `embed()` uses when no
`target=`/`route=` is passed; it is the same mechanism `default_route` gives generation, kept
separate so an embedding fallback chain is never accidentally reused for chat traffic.
Local engines are first-class fallback members: [TEI](../providers/tei.md),
[Ollama](../providers/ollama.md), and [LM Studio](../providers/lm-studio.md) all embed,
so a chain like `[local-tei:bge-large, openai:text-embedding-3-small]` tries the free
local model first and only spends money if it is unreachable.

## See Also

<div class="anyinfer-see-also" markdown>

- [Embeddings and reranking](../concepts/embeddings.md): intents, spaces, and batching.
- [Embed, store, and query — without a database](../guides/vector-store.md): the same
  loop persisted in a single SQLite file.
- [Error catalog](../reference/errors.md#embedding-and-rerank-refusals):
  the refusal a mismatched embedding fallback raises.

</div>
