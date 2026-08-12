---
provider: tei
icon: material/vector-combine
---

# Text Embeddings Inference

Hugging Face's TEI server, spoken in its **native dialect** — the one local provider in
the initial set with a real reranking endpoint. TEI serves exactly one model per
container (an embedding model or a reranker, chosen at startup), so this provider is
also the library's first retrieval-only adapter: it declares no generation at all.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: embeddings</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reranking</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery (model + operation)</span>
<span class="anyinfer-badge anyinfer-badge-no">:material-close: generation</span>
</div>

## Setup

Run a server (one model each — an embedding server and a reranker are two containers):

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

The model half of the target is advisory — the server holds one model, and
`client.models("tei")` reports its real id and operation, discovered from `GET /info`.
Two servers (an embedder and a reranker) are two configured instances:

```python
client = ai.Client([
    ai.ProviderSettings(provider_id="tei", alias="tei-embed", base_url="http://127.0.0.1:8080"),
    ai.ProviderSettings(provider_id="tei", alias="tei-rerank", base_url="http://127.0.0.1:8081"),
])
ranked = client.rerank("the query", docs, target="tei-rerank:bge-reranker")
```

## Notes

- **Vectors are unit-normalized by default** — the server's documented `normalize: true`
  default is left in force and reported on `result.space.normalized`; a
  `provider_options={"tei": {"normalize": False}}` override is reported as sent.
- **No usage**: TEI reports no token counts, so `result.usage` stays honestly empty.
- **`top_n` is applied client-side** — the endpoint has no native parameter; the
  adapter sorts by score and truncates, and the contract snapshot records that.
- **Batch ceiling is per-deployment**: `GET /info` reports `max_client_batch_size` for
  *your* server, so no static limit is declared. For corpora above it, pass
  `batch=BatchPolicy(max_items_override=<your server's value>)`.
- An `--api-key`-protected server takes `api_key="env://TEI_API_KEY"`.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/tei.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/tei.md).
