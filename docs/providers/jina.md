---
provider: jina
icon: material/spider-web
---

# Jina AI

A specialist retrieval provider — embeddings and reranking, no generation. Jina's
`task` vocabulary covers every normalized input intent, including a clustering-flavored
`separation` task, and its reranker takes `top_n` natively.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: embeddings</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reranking</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: input intents (all four)</span>
<span class="anyinfer-badge anyinfer-badge-no">:material-close: generation</span>
</div>

## Setup

```python
import anyinfer as ai

client = ai.Client([ai.ProviderSettings.of("jina", api_key="env://JINA_API_KEY")])

docs = client.embed(corpus, target="jina:jina-embeddings-v3", input_type="document")
query = client.embed([question], target="jina:jina-embeddings-v3", input_type="query")
ranked = client.rerank(question, candidates, target="jina:jina-reranker-v3", top_n=5)
```

## Notes

- **Every intent maps**: `query` → `retrieval.query`, `document` →
  `retrieval.passage`, `classification` verbatim, and `clustering` → `separation`
  (Jina's clustering-flavored task — a deliberate mapping, recorded in the contract).
- **No documented request ceilings** — Jina batches internally, so no limit is
  invented; requests above the library's sanity ceilings refuse locally, and
  `BatchPolicy.max_items_override` applies a limit you have verified.
- **Usage is `total_tokens` only** — `input_tokens` stays unknown rather than assumed.
- **No model listing**: `client.models("jina")` is empty by honesty; the verified model
  set ships in the descriptor's capabilities.
- Matryoshka `dimensions` truncation and `late_chunking` are reachable via `dimensions=`
  and `provider_options={"jina": {"late_chunking": True}}`.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/jina.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/jina.md).
