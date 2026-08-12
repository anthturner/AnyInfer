# jina — Protocol Contract

Status: **implemented** — `providers/jina.py`, embeddings and reranker.
Last verified: 2026-08-12 — against Jina's product documentation and its own model
publications (sources below); the interactive API reference (`api.jina.ai/redoc`) is
JS-only and unfetchable headlessly, recorded as such. Not yet live-verified.

## Upstream sources
- https://jina.ai/embeddings/ (request shape, task vocabulary, models)
- https://jina.ai/reranker/ (rerank request shape, models, no-hard-limit statement)
- https://huggingface.co/jinaai/jina-reranker-v3 and Jina's reranker announcement posts
  (rerank response shape: `results[]` with `index`/`relevance_score`,
  `usage.total_tokens`)

## Wire contract

### Endpoints
- `POST https://api.jina.ai/v1/embeddings`
- `POST https://api.jina.ai/v1/rerank`
- **No listing endpoint** — `list_models()` is honestly empty; `health()` is a labeled
  reachability probe (any HTTP answer counts).

### Auth
- `Authorization: Bearer <api_key>`. Conventionally `env://JINA_API_KEY`.

### Embeddings request fields (verified 2026-08-12)
- `model` (required), `input` (array of strings; no per-request ceiling documented —
  "batches inputs internally"), `task` — Jina's intent vocabulary, covering all four
  normalized intents: query→`retrieval.query`, document→`retrieval.passage`,
  classification→`classification`, and **clustering→`separation`** (Jina's
  clustering-flavored task; a deliberate mapping recorded here, not an upstream
  equivalence claim), plus `text-matching` (unmapped), `dimensions` (Matryoshka
  truncation), `late_chunking`, `embedding_type`/format options, `normalized`.
- The adapter sends `model`, `input`, `task` (when an intent was given), and
  `dimensions`; everything else is reachable via `provider_options`.

### Embeddings response (corroborated 2026-08-12, not yet live-verified)
- OpenAI-shaped: `data[]` with `embedding`/`index` (adapter orders by the reported
  index and rejects out-of-range/duplicates), `usage.total_tokens` →
  `Usage.total_tokens` only, never assumed into `input_tokens`.
- **Unverified:** per-model default dimensions; the exact error-body shape.

### Rerank request fields (verified 2026-08-12)
- `model`, `query`, `documents` (list of strings; **"no hard limit on the number of
  documents per request"** — so no `max_documents` is declared and the sanity ceiling
  governs), `top_n` (native), `return_documents` (default false).

### Rerank response (verified 2026-08-12 from Jina's own publications)
- `results[]` with `index` (**positional within the submitted `documents`**, mapped
  back onto the caller-supplied index before core validation) and `relevance_score`;
  `model`; `usage.total_tokens`.
- **Cross-batch comparability: not documented** — refuse-by-default stands.

### Streaming
Embeddings and rerank responses are not streamed.

## Watchlist
- **Not yet live-verified** — first live lane confirms the embeddings response shape,
  error bodies, and usage fields.
- The clustering→`separation` mapping, should Jina document its tasks more precisely.
- `late_chunking`, multimodal inputs (v4/m0), quantized `embedding_type` values —
  unmodelled; reachable via `provider_options`.
- A listing endpoint, if one appears.
