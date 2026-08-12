---
provider: voyage
icon: material/sail-boat
---

# Voyage AI

A specialist retrieval provider — embeddings and reranking, no generation. The hosted
counterpart to [TEI](tei.md)'s retrieval-only shape, with native `query`/`document`
input intents and a real reranker.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: embeddings</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reranking</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: input intents (query/document)</span>
<span class="anyinfer-badge anyinfer-badge-no">:material-close: generation</span>
</div>

## Setup

```python
import anyinfer as ai

client = ai.Client([ai.ProviderSettings.of("voyage", api_key="env://VOYAGE_API_KEY")])

docs = client.embed(corpus, target="voyage:voyage-3.5", input_type="document")
query = client.embed([question], target="voyage:voyage-3.5", input_type="query")
ranked = client.rerank(question, candidates, target="voyage:rerank-2.5", top_n=5)
```

## Notes

- **Intents are `query` and `document` only.** `classification`/`clustering` have no
  wire value here — they are never sent, and the result carries a warning saying so.
- **Batching engages at 1,000 inputs** (embeddings) and the rerank document limit of
  1,000 is a hard cap — the core refuses larger rerank requests unless
  `rerank_cross_batch` opts into chunk-local rankings.
- **Truncation defaults on** server-side: over-length inputs are cut, not rejected.
  Disable per call with `provider_options={"voyage": {"truncation": False}}`.
- **Usage is `total_tokens` only** — `input_tokens` stays unknown rather than assumed.
- **No model listing**: `client.models("voyage")` is empty by honesty (the API has no
  listing endpoint); the verified model set ships in the descriptor's capabilities.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/voyage.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/voyage.md).
