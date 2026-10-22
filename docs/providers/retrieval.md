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
| [Input intents](../concepts/embeddings.md#input-intent) | `query` and `document` only; `classification`/`clustering` have no wire value, are never sent, and the result carries a warning | All four: `query` → `retrieval.query`, `document` → `retrieval.passage`, `classification` verbatim, `clustering` → `separation` (Jina's clustering-flavored task, recorded in the contract) |
| Embedding batches | [Batching engages](../concepts/embeddings.md#batching) at 1,000 inputs | No documented ceiling: Jina batches internally, so no limit is invented; requests above the library's sanity ceilings refuse locally, and `BatchPolicy.max_items_override` applies an independently verified limit |
| Rerank documents | 1,000 is a hard cap; the core refuses larger requests unless `rerank_cross_batch` opts into chunk-local rankings | `top_n` is taken natively by the reranker |
| Truncation | Defaults on server-side: over-length inputs are cut, not rejected. Disable per call with `provider_options={"voyage": {"truncation": False}}` | — |
| Dimensionality | — | Matryoshka truncation via `dimensions=`; `late_chunking` via `provider_options={"jina": {"late_chunking": True}}` |

## Notes

Two behaviors are shared:

- **No model listing.** Neither API has a listing endpoint, so `client.models("voyage")`
  and `client.models("jina")` return empty lists; the verified model set ships in each
  descriptor's [capabilities](../concepts/capabilities.md).
- **Usage is `total_tokens` only.** Both public and raw results keep the input and output
  breakdown unknown rather than inventing it.

## C# proof boundary

The bounded prerelease C# proof has native built-in retrieval adapters for Voyage and
[Text Embeddings Inference](tei.md). Its Voyage example uses a caller-supplied
`env://VOYAGE_API_KEY` reference and scripted HTTP responses; hosted Voyage traffic has not
been live-verified. Jina remains available through the Python SDK but has no C# built-in
adapter in this proof.

```csharp
--8<-- "examples/csharp-sdk/VoyageExample.cs"
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
