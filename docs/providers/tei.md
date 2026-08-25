---
provider: tei
icon: material/vector-combine
---

# Text Embeddings Inference

Hugging Face's TEI server, spoken in its native dialect; the one local provider with a
real reranking endpoint. TEI serves exactly one model per container (an embedding model
or a reranker, chosen at startup), so this provider is also the library's first
[retrieval-only](../concepts/embeddings.md) adapter: it declares no generation at all.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: embeddings</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reranking</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery (model + operation)</span>
<span class="anyinfer-badge anyinfer-badge-no">:material-close: generation</span>
</div>

## Setup

Run a server:

```shell
docker run -p 8080:80 ghcr.io/huggingface/text-embeddings-inference:cpu-1.9 \
    --model-id BAAI/bge-large-en-v1.5
```

Then point a client at it:

```python
import anyinfer as ai

client = ai.Client([ai.ProviderSettings.of("tei")])  # defaults to 127.0.0.1:8080
result = client.embed(["What is deep learning?"], target="tei:bge-large")
```

Since the server holds one model, the model half of the
[target](../concepts/targets.md) is advisory; `client.models("tei")` reports the real id
and operation, discovered from `GET /info`. An embedder and a reranker are therefore two
servers, configured as two instances:

```python
client = ai.Client([
    ai.ProviderSettings(provider_id="tei", alias="tei-embed", base_url="http://127.0.0.1:8080"),
    ai.ProviderSettings(provider_id="tei", alias="tei-rerank", base_url="http://127.0.0.1:8081"),
])
ranked = client.rerank("the query", docs, target="tei-rerank:bge-reranker")
```

## Notes

- **Vectors are unit-normalized by default**: the server's documented `normalize: true`
  default is left in force and reported on `result.space.normalized`; a
  `provider_options={"tei": {"normalize": False}}` override is reported as sent.
- **No usage**: TEI's response body carries no token counts, so `result.usage` stays
  empty; the `x-compute-tokens` header real servers send is absent from the published API
  document, so it sits on the contract's watchlist rather than in accounting.
- **`top_n` is applied client-side**: the endpoint has no native parameter; the
  adapter sorts by score and truncates, and the contract snapshot records that.
- **Batch ceiling is per-deployment**: `GET /info` reports `max_client_batch_size` for
  the *running* server, so no static limit is declared. For corpora above it, pass
  [`batch=BatchPolicy(max_items_override=<your server's value>)`](../concepts/embeddings.md#batching).
- An `--api-key`-protected server takes `api_key="env://TEI_API_KEY"`.

## Wire Contract

For the exact request/response fields this adapter depends on, see
[contracts/tei.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/tei.md).
It was verified against real servers on 2026-08-24 (`text-embeddings-inference` 1.8.3
serving `BAAI/bge-small-en-v1.5` and `BAAI/bge-reranker-base`), and that traffic is
committed as cassettes, so the lane replays in CI without a server.

## See Also

<div class="anyinfer-see-also" markdown>

- [Voyage AI and Jina AI](retrieval.md): the hosted counterparts to this retrieval-only
  shape.
- [Embeddings and reranking](../concepts/embeddings.md): the normalized operations and
  batching rules.

</div>
