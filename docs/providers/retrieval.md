---
icon: material/vector-triangle
---

# Voyage AI and Jina AI

The two hosted specialist retrieval providers:
[embeddings and reranking](../concepts/embeddings.md), no generation. Both serve native
`query`/`document` input intents and a real reranker; they differ in task vocabulary,
batch ceilings, and truncation behavior.

## Setup

The setup below is Python; the C# form is under
[Use Voyage and Jina from C#](#c-proof-boundary).

=== "Voyage (Python)"

    ```python
    import anyinfer as ai

    client = ai.Client([ai.ProviderSettings.of("voyage", api_key="env://VOYAGE_API_KEY")])

    docs = client.embed(corpus, target="voyage:voyage-3.5", input_type="document")
    query = client.embed([question], target="voyage:voyage-3.5", input_type="query")
    ranked = client.rerank(question, candidates, target="voyage:rerank-2.5", top_n=5)
    ```

=== "Jina (Python)"

    ```python
    import anyinfer as ai

    client = ai.Client([ai.ProviderSettings.of("jina", api_key="env://JINA_API_KEY")])

    docs = client.embed(corpus, target="jina:jina-embeddings-v3", input_type="document")
    query = client.embed([question], target="jina:jina-embeddings-v3", input_type="query")
    ranked = client.rerank(question, candidates, target="jina:jina-reranker-v3", top_n=5)
    ```

## Provider Differences

The table uses Python spellings. In C#, the same settings are `BatchPolicy.MaxItemsOverride`,
`BatchPolicy.RerankCrossBatch`, the `dimensions` argument, and a `providerOptions` entry keyed by
the provider instance ID (`voyage`, `jina`, or the alias you configured).

| | Voyage AI | Jina AI |
|---|---|---|
| [Input intents](../concepts/embeddings.md#input-intent) | `query` and `document` only; `classification`/`clustering` have no wire value, are never sent, and the result carries a warning | `query` → `retrieval.query`, `document` → `retrieval.passage`, `classification` verbatim; `clustering` is `clustering` for the four supported v5 embedding IDs and `separation` otherwise. v4 exposes only query/document normalized intents. |
| Embedding batches | [Batching engages](../concepts/embeddings.md#batching) at 1,000 inputs | No documented ceiling: Jina batches internally, so no limit is invented; requests above the library's sanity ceilings refuse locally, and `BatchPolicy.max_items_override` applies an independently verified limit |
| Rerank documents | 1,000 is a hard cap; the core refuses larger requests unless `rerank_cross_batch` opts into chunk-local rankings | `top_n` is taken natively by the reranker |
| Truncation | Defaults on server-side: over-length inputs are cut, not rejected. Disable per call with `provider_options={"voyage": {"truncation": False}}` | — |
| Dimensionality | `output_dimension` via the shared `dimensions=` argument | Matryoshka truncation via `dimensions=`; `late_chunking` via `provider_options={"jina": {"late_chunking": True}}` |

## Notes

Two behaviors are shared:

- **Manual selection with empty discovery.** The supported SDK subset returns empty lists
  from `client.models("voyage")` and `client.models("jina")` (`ModelsAsync` in C#); Jina's
  documented model-listing endpoint is not implemented by this bounded discovery surface. The
  verified model set ships in each descriptor's [capabilities](../concepts/capabilities.md).
- **Usage is `total_tokens` only.** Public normalized usage keeps the input and output
  breakdown unknown rather than inventing it. When raw retention is opted in, the raw payload
  preserves reported prompt or modality usage fields without promoting them into that normalized
  breakdown.

## Use Voyage and Jina from C# {#c-proof-boundary}

The C# SDK (prerelease) registers built-in Voyage and Jina descriptors for buffered text
embedding and reranking, beside [Text Embeddings Inference](tei.md). The examples give each
provider an instance alias and accept an `env://` key reference, such as `env://VOYAGE_API_KEY`;
the key is resolved when the first call needs that instance, and an unset variable fails with
`CredentialException` before any request. Both adapters have offline
scripted-handler evidence only: hosted Voyage and hosted Jina traffic have not been
live-verified from C#.

### Embed and Rerank

```csharp
--8<-- "examples/csharp-sdk/VoyageExample.cs"
```

```csharp
--8<-- "examples/csharp-sdk/JinaExample.cs"
```

The scripted handlers in these examples check the native request each adapter sends, and the
example runner's assertions check the results that come back:

- **Input intents.** `EmbeddingInputIntent.Query` and `Document` become Voyage's `input_type`
  `query` and `document`, and Jina's `task` `retrieval.query` and `retrieval.passage`.
- **Native top N.** `topN` is sent as Voyage's `top_k` and Jina's `top_n`.
- **Caller identity.** Each `RankedItem` carries your `RerankDocument` ID and the document's
  original index: both providers answer here with only the second document, which comes back as
  `lighthouse` at index 1.
- **Total-only usage.** Normalized usage carries the reported `total_tokens` and leaves input
  and output tokens unknown. With `retainRaw: true`, the raw payload keeps fields such as Jina's
  `prompt_tokens` without promoting them into normalized usage.
- **Content-free manifests.** Retrieval manifests never carry request or response payloads.

### Batch Limits in C#

Voyage's descriptor declares 1,000 embedding inputs and 1,000 rerank documents per request for
its listed models, so the default `BatchPolicy` splits a larger embedding call into ordered
batches and refuses a larger rerank call before dispatch unless `RerankCrossBatch` opts into
chunk-local rankings. Jina declares no ceiling, so nothing is guessed: a call is sent as one
request, and more than 2,048 embedding inputs or 1,000 rerank documents are refused locally with
`ConfigException`. Supply `BatchPolicy.MaxItemsOverride` only for a limit you have verified. The
offline runner checks a 1,001-input Voyage call that becomes batches of 1,000 and 1, a refused
1,001-document Voyage rerank, and refused 2,049-input and 1,001-document Jina calls. The
[batching recipe](../guides/csharp-sdk.md#batch-large-retrieval-requests) shows the override,
and [route retrieval and keep vectors comparable](../guides/csharp-sdk.md#route-retrieval-and-keep-vectors-comparable)
shows operation routes and `EmbeddingSpace` checks for an index built with either provider.

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
- [C# SDK guide](../guides/csharp-sdk.md#embed-and-rerank): the native retrieval recipes.

</div>
