# Embeddings and reranking

Embedding and reranking are stateless inference operations, typed and routed the same way
generation is — but they are not generation. `EmbeddingRequest` and `RerankRequest` are
their own types; nothing here is ever added as a field on `GenerationRequest`.

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

Both accept a single target, a fallback chain, or a route the same way `generate()` does.

## What AnyInfer will not do for you

AnyInfer produces vectors and relevance rankings. It does not persist them, build a search
index, crawl a corpus, or decide what an application sends to a model next. There is no
vector database in the core, and no plan to grow one — that boundary is deliberate. An
application that wants storage and search brings its own store (or a small optional add-on
package built on these same types) and feeds it with `embed()`/`rerank()` results exactly
like it would feed any other vector database.

## The embedding-space safety rule

Two embedding vectors are only meaningfully comparable when they came from the same model,
the same revision, and — for models that distinguish it — the same input-intent handling.
A query re-embedded with a fallback model produces numbers that look exactly as plausible as
the ones the primary model would have produced, and will silently fail to match anything in
an index built against the primary model. That failure is worse than an ordinary provider
error, because nothing in the response says it happened.

AnyInfer's answer is `EmbeddingSpace`, carried on every `EmbeddingResult`:

```python
print(result.space.provider_id, result.space.model, result.space.dimensions)
```

By default, embedding routes retry on the **same resolved target only** — no cross-provider
or cross-model fallback. A fallback chain that reaches a different `provider:model` is
refused *before* any request is sent: AnyInfer never guesses that two spaces are
equivalent, so the request fails with an actionable error instead of returning a
wrong-but-plausible vector. If you genuinely want vectors that may not be comparable —
an expert recovery workflow, for example — pass `allow_incompatible_fallback=True`; the
result then always carries a warning naming both targets.

You may also assert the space you expect up front:

```python
result = client.embed(
    ["hello"],
    target="ollama:nomic-embed-text",
    expected_space=my_stored_index_space,
)
```

A successful response from a target that does not match `expected_space` is rejected rather
than returned.

## Input intent

Some embedding models produce measurably better retrieval when a query and the documents it
will be compared against are embedded with different instructions, even though both pass
through the same model:

```python
query_vec = client.embed(["capital of France"], target="ollama:nomic-embed-text", input_type="query")
doc_vecs = client.embed(docs, target="ollama:nomic-embed-text", input_type="document")
```

A provider that does not distinguish input intent ignores the field. A model that requires
it but received none degrades per its own documented default, and that degradation is
recorded as a warning rather than silently substituted.

## Reranking and document identity

`RerankDocument` ids are caller-owned and opaque — AnyInfer never generates or interprets
them. Every `RankedItem` carries back the original index and the document id it was given,
so a caller can always map a ranked result back to its source without a lookup table, and a
malformed provider response (an out-of-range or duplicate index) is rejected rather than
guessed at.

Scores are meaningful only within one result from one target. They are never comparable
across providers or models, and AnyInfer never merges or averages scores from separate
rerank attempts.

## Batching

Providers disagree on how many inputs, documents, tokens, or bytes one request may carry.
Splitting an oversized request is core policy, never something an adapter decides on its
own: it only happens against a verified limit, and an embedding batch failure is all-or-error
— you never get back an `EmbeddingResult` silently missing vectors. Reranking is not
automatically split across documents and concatenated, because scores from separate document
batches are not assumed globally comparable unless a provider documents otherwise.

## Frontends

The sidecar exposes `POST /v1/embeddings` as an OpenAI-compatible codec, and
`POST /v1/anyinfer/rerank` as an AnyInfer-native route (there is no established OpenAI-shaped
rerank dialect to emulate). The CLI exposes `anyinfer embed` and `anyinfer rerank`. All three
surfaces are projections over the same `AsyncClient.embed()`/`AsyncClient.rerank()` calls —
none of them carry their own routing or validation logic.
