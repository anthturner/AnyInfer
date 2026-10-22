---
icon: material/vector-triangle
---

# Voyage AI and Jina AI

The two hosted specialist retrieval providers:
[embeddings and reranking](../concepts/embeddings.md), no generation. Both serve native
`query`/`document` input intents and a real reranker; they differ in task vocabulary,
batch ceilings, and truncation behavior.

## Setup

=== "Voyage"

    ```python
    import anyinfer as ai

    client = ai.Client([ai.ProviderSettings.of("voyage", api_key="env://VOYAGE_API_KEY")])

    docs = client.embed(corpus, target="voyage:voyage-3.5", input_type="document")
    query = client.embed([question], target="voyage:voyage-3.5", input_type="query")
    ranked = client.rerank(question, candidates, target="voyage:rerank-2.5", top_n=5)
    ```

=== "Jina"

    ```python
    import anyinfer as ai

    client = ai.Client([ai.ProviderSettings.of("jina", api_key="env://JINA_API_KEY")])

    docs = client.embed(corpus, target="jina:jina-embeddings-v3", input_type="document")
    query = client.embed([question], target="jina:jina-embeddings-v3", input_type="query")
    ranked = client.rerank(question, candidates, target="jina:jina-reranker-v3", top_n=5)
    ```

## Provider Differences

| | Voyage AI | Jina AI |
|---|---|---|
| [Input intents](../concepts/embeddings.md#input-intent) | `query` and `document` only; `classification`/`clustering` have no wire value, are never sent, and the result carries a warning | `query` → `retrieval.query`, `document` → `retrieval.passage`, `classification` verbatim; `clustering` is `clustering` for the four supported v5 embedding IDs and `separation` otherwise. v4 exposes only query/document normalized intents. |
| Embedding batches | [Batching engages](../concepts/embeddings.md#batching) at 1,000 inputs | No documented ceiling: Jina batches internally, so no limit is invented; requests above the library's sanity ceilings refuse locally, and `BatchPolicy.max_items_override` applies an independently verified limit |
| Rerank documents | 1,000 is a hard cap; the core refuses larger requests unless `rerank_cross_batch` opts into chunk-local rankings | `top_n` is taken natively by the reranker |
| Truncation | Defaults on server-side: over-length inputs are cut, not rejected. Disable per call with `provider_options={"voyage": {"truncation": False}}` | — |
| Dimensionality | — | Matryoshka truncation via `dimensions=`; `late_chunking` via `provider_options={"jina": {"late_chunking": True}}` |

## Notes

Two behaviors are shared:

- **Manual selection with empty discovery.** The supported SDK subset returns empty lists
  from `client.models("voyage")` and `client.models("jina")`; Jina's documented model-listing
  endpoint is not implemented by this bounded discovery surface. The verified model set ships in
  each descriptor's [capabilities](../concepts/capabilities.md).
- **Usage is `total_tokens` only.** Public normalized usage keeps the input and output
  breakdown unknown rather than inventing it. When raw retention is opted in, the raw payload
  preserves reported prompt or modality usage fields without promoting them into that normalized
  breakdown.

## C# proof boundary

The bounded prerelease C# proof has native built-in retrieval adapters for Jina, Voyage and
[Text Embeddings Inference](tei.md). Its Voyage example uses a caller-supplied
`env://VOYAGE_API_KEY` reference and scripted HTTP responses; hosted Voyage traffic has not
been live-verified. Its Jina example uses the same offline scripted-handler form; hosted Jina
traffic has not been live-verified.

```csharp
--8<-- "examples/csharp-sdk/VoyageExample.cs"
```

```csharp
--8<-- "examples/csharp-sdk/JinaExample.cs"
```

## Wire Contract

For the exact request/response fields each adapter depends on, see
[contracts/voyage.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/voyage.md)
and
[contracts/jina.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/jina.md).

## See Also

<div class="anyinfer-see-also" markdown>

- [Text Embeddings Inference](tei.md): the local counterpart to this retrieval-only
  shape.
- [Embeddings and reranking](../concepts/embeddings.md): intents, spaces, and batching.

</div>
