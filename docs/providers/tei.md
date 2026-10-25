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

TEI serves one model per server process. The commands below use the pinned CPU image
and model revisions that were exercised on 2026-10-22. Both published ports bind to
loopback, so they are available only on the local machine:

```shell
docker run --rm -p 127.0.0.1:8080:80 \
  ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4@sha256:8419f533857b503ebf6ec292a95d4f1cf9c0464ac8b8abeef39518cf110e5726 \
  --model-id BAAI/bge-small-en-v1.5 \
  --revision 5c38ec7c405ec4b44b94cc5a9bb96e735b38267a

docker run --rm -p 127.0.0.1:8081:80 \
  ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4@sha256:8419f533857b503ebf6ec292a95d4f1cf9c0464ac8b8abeef39518cf110e5726 \
  --model-id BAAI/bge-reranker-base \
  --revision 2cfc18c9415c912f9d8155881c133215df768a70
```

Then point a client at it:

```python
import anyinfer as ai

client = ai.Client([ai.ProviderSettings.of("tei")])  # defaults to 127.0.0.1:8080
result = client.embed(["What is deep learning?"], target="tei:BAAI/bge-small-en-v1.5")
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
ranked = client.rerank(
    "the query", docs, target="tei-rerank:BAAI/bge-reranker-base"
)
```

The two tested deployments used `BAAI/bge-small-en-v1.5` at revision
`5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` for embeddings and
`BAAI/bge-reranker-base` at revision `2cfc18c9415c912f9d8155881c133215df768a70`
for reranking. `GET /info` reported TEI 1.9.4 for both processes. These are tested
pins, not required choices for other deployments.

## Use TEI from C#

The C# SDK (prerelease) has a built-in `tei` descriptor for buffered embedding and reranking.
Configure each server process as its own instance, matching the loopback ports above:

```csharp
--8<-- "examples/csharp-sdk/TeiServersExample.cs:servers"
```

### Discover the Served Models

As in Python, the model half of a target is advisory. `ModelsAsync` reads `GET /info` and,
given an operation, returns the served model only when the process embeds or reranks
respectively, so a server started with the other kind of model is filtered out before any
operation request:

```csharp
--8<-- "examples/csharp-sdk/TeiServersExample.cs:discover"
```

`topN` is applied client-side, after sorting by score, and each ranked item keeps your document
ID and its original index. Usage stays unknown (`null`), never zero, so a `SpendLedger` counts
these requests in `UnknownRequests`. The offline runner executes this recipe against scripted
`/info`, `/embed`, and `/rerank` responses and checks the discovered targets, the unknown usage,
the normalized `EmbeddingSpace`, the caller IDs, and that a reranker on the embedding port stops
the recipe before any operation request. The same public calls, operation-filtered discovery
followed by buffered embedding and reranking, were exercised against the pinned TEI 1.9.4 CPU
deployment on 2026-10-22.

### Batch Against a Verified Server Limit

The C# descriptor does not hydrate the limits `/info` reports: the offline case's `/info`
declares `max_client_batch_size` 2, and three inputs still go in one request. When you have
verified a server's limit, pass it explicitly:

```csharp
--8<-- "examples/csharp-sdk/RetrievalBatchingExample.cs:embed"
```

See [batch large retrieval requests](../guides/csharp-sdk.md#batch-large-retrieval-requests) for
the batch-failure and rerank rules, and the [C# retrieval recipes](../guides/csharp-sdk.md#embed-and-rerank)
for raw payload retention, manifests, operation routes, and `EmbeddingSpace` checks.

## Notes

- **Vectors are unit-normalized by default**: the server's documented `normalize: true`
  default is left in force and reported on `result.space.normalized`; a
  `provider_options={"tei": {"normalize": False}}` override is reported as sent.
- **Unknown usage**: TEI's response body carries no token counts, so usage accounting
  fields remain unknown (`None` in Python, `null` in C#), never zero. The observed `x-compute-tokens`
  header is not in the published API contract and is not used for accounting.
- **`top_n` is applied client-side**: the endpoint has no native parameter; the
  adapter sorts by score and truncates, and the contract snapshot records that.
- **Limits remain unknown to the SDK**: although `/info` reports deployment limits, the
  Python adapter and C# descriptor do not hydrate batching, token, or dimension limits.
  Supply a verified `BatchPolicy(max_items_override=...)` when you need client-side
  batching against a known server ceiling.
- A server configured with `--api-key` / `API_KEY` expects a Bearer token. In Python,
  `api_key="env://TEI_API_KEY"` is the client-side credential convention, and in C# the
  same reference is passed as `apiKey`; it is separate from the server's `API_KEY`
  environment variable.
- Omitted or null request `truncate` inherits the server's `auto_truncate` setting. In the
  tested deployment that setting was true; an explicit `truncate: false` returned 422 for
  an over-length input. See the current [wire contract](https://github.com/anthturner/AnyInfer/blob/main/contracts/tei.md) for details.

## Wire Contract

For the exact request/response fields this adapter depends on, see
[contracts/tei.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/tei.md).
Python traffic was recorded against the pinned TEI 1.9.4 image and model revisions on
2026-10-22; the three sanitized cassettes replay in CI without a server. The older
2026-08-24 TEI 1.8.3 evidence is retained in the contract as historical evidence.
Buffered C# embedding and reranking were exercised against the pinned TEI 1.9.4 CPU deployment on 2026-10-22.

## See Also

<div class="anyinfer-see-also" markdown>

- [Voyage AI and Jina AI](retrieval.md): the hosted counterparts to this retrieval-only
  shape.
- [Embeddings and reranking](../concepts/embeddings.md): the normalized operations and
  batching rules.
- [C# SDK guide](../guides/csharp-sdk.md#embed-and-rerank): the native retrieval recipes.

</div>
