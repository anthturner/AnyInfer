# Embeddings and Reranking

Embedding and reranking are stateless inference operations, typed and
[routed](routing.md) the same way generation is, but they are not generation.
`EmbeddingRequest` and `RerankRequest` are their own types; nothing here is ever added as
a field on `GenerationRequest`.

```python
import anyinfer as ai

client = ai.Client([ai.ProviderSettings.of("ollama")])

result = client.embed(
    ["What is the capital of France?", "Paris is the capital of France."],
    target="ollama:nomic-embed-text",
)
print(len(result.vectors), result.space.dimensions)
```

```python
ranked = client.rerank(
    "What is the capital of France?",
    ["Paris is the capital of France.", "Berlin is the capital of Germany."],
    target="ollama:some-rerank-model",
)
for item in ranked.items:
    print(item.document_id, item.score)
```

Both accept a single [target](targets.md), a fallback chain, or a route the same way
`generate()` does.

AnyInfer produces vectors and relevance rankings; it does not persist them, build a
search index, or crawl a corpus. An application brings its own store and feeds it with
these results, or uses the small optional
[`anyinfer-store` add-on](../guides/vector-store.md), which draws the boundary in detail.

## The Embedding-Space Safety Rule

Two embedding vectors are only meaningfully comparable when they came from the same
model, the same revision, and (for models that distinguish it) the same input-intent
handling. A query re-embedded by a fallback model produces numbers that look exactly as
plausible as the primary model's, and will fail to match anything in an index built
against the primary. Nothing in the response says it happened, which makes this failure
worse than an ordinary provider error.

AnyInfer's answer is `EmbeddingSpace`, carried on every `EmbeddingResult`:

```python
print(result.space.provider_id, result.space.model, result.space.dimensions)
```

By default, embedding routes retry on the same resolved target only: no cross-provider
or cross-model fallback. A chain that reaches a different `provider:model` is refused
*before* any request is sent, with an actionable
[`ConfigError`](../reference/errors.md), because AnyInfer never guesses that two spaces
are equivalent. A caller that genuinely wants vectors that may not be comparable passes
`allow_incompatible_fallback=True`; the result then always carries a warning naming both
targets.

A caller can also assert the expected space up front:

```python
result = client.embed(
    ["hello"],
    target="ollama:nomic-embed-text",
    expected_space=my_stored_index_space,
)
```

A successful response from a target that does not match `expected_space` is rejected
rather than returned.

## Input Intent

Some embedding models produce measurably better retrieval when a query and the documents
it will be compared against are embedded with different instructions:

```python
query_vec = client.embed(["capital of France"], target="ollama:nomic-embed-text", input_type="query")
doc_vecs = client.embed(docs, target="ollama:nomic-embed-text", input_type="document")
```

A provider that does not distinguish input intent ignores the field. A model that
requires it but received none degrades per its own documented default, and that
degradation is recorded as a warning.

## Reranking and Document Identity

`RerankDocument` ids are caller-owned and opaque; AnyInfer never generates or
interprets them. Every `RankedItem` carries back the original index and the document id
it was given, so a caller can always map a ranked result back to its source, and a
malformed provider response (an out-of-range or duplicate index) is rejected rather than
guessed at.

Scores are meaningful only within one result from one target. They are never comparable
across providers or models, and AnyInfer never merges or averages scores from separate
rerank attempts.

## Batching

Providers disagree on how many inputs, documents, tokens, or bytes one request may
carry. Splitting an oversized request is core policy, never an adapter's own decision,
and it only happens against a verified limit:

- An oversized embedding request against a target with a verified batch limit is split
  into ordered chunks, dispatched concurrently, and re-assembled in input order. A batch
  failure is all-or-error; a caller never gets back an `EmbeddingResult` silently missing
  vectors.
- When no verified limit exists, a request up to a bounded default goes out as a single
  call, and anything larger is refused with an actionable error rather than a guessed
  provider maximum.
- Reranking is not automatically split, because scores from separate document batches
  are not globally comparable unless a provider documents otherwise.

The `batch=` parameter takes an `anyinfer.BatchPolicy`: `max_concurrency` bounds
parallel chunks, `allow_split=False` refuses splitting outright, `max_items_override`
supplies a limit the caller has verified, and `rerank_cross_batch=True` is the
explicit opt-in for chunk-local rerank rankings, with a warning that the scores are not
one global ordering.

## Frontends

The [sidecar](../serve/README.md) exposes `POST /v1/embeddings` as an OpenAI-compatible
codec and `POST /v1/anyinfer/rerank` as an AnyInfer-native route (there is no
established OpenAI-shaped rerank dialect to emulate). The [CLI](../guides/cli.md)
exposes `anyinfer embed` and `anyinfer rerank`. All three surfaces are projections over
the same `AsyncClient` calls.

!!! tip "Key Takeaways"
    - Embedding and rerank requests are their own typed operations with their own
      routing rule: same resolved target only, unless incompatible fallback is
      explicitly allowed.
    - Every result carries its `EmbeddingSpace`, and `expected_space=` turns a stored
      index's assumptions into an enforced precondition.
    - Batch splitting happens only against verified limits and is all-or-error; rerank
      scores are never merged across batches.
    - Storage and search stay outside the core; `anyinfer-store` is the optional add-on
      for having them without a database.

## See Also

<div class="anyinfer-see-also" markdown>

- [Semantic search over a small corpus](../examples/semantic-search.md): the runnable
  example.
- [Embed, store, and query](../guides/vector-store.md): the optional persistence add-on.
- [Text Embeddings Inference](../providers/tei.md) ·
  [Voyage AI and Jina AI](../providers/retrieval.md): the retrieval-only providers.

</div>
