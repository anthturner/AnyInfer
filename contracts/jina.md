# jina — Protocol Contract

Status: **implemented** — `providers/jina.py`, embeddings and reranker.
Last verified: 2026-10-26 — against Jina's product documentation, its own model
publications, and the docs.jina.ai API reference (sources below); the interactive API
reference (`api.jina.ai/redoc`) is still JS-only and unfetchable headlessly (last
confirmed 2026-10-12). The per-endpoint request/response schemas inside
`docs.jina.ai/openapi.json` / `api.md` were not reached this run (oversized pages, only
the first 100K characters read). Not yet verified against live traffic.

## Upstream sources
- https://jina.ai/embeddings/ (request shape, task vocabulary, models)
- https://jina.ai/reranker/ (rerank request shape, models, no-hard-limit statement)
- https://jina.ai/en-US/news/jina-embeddings-v5-text-distilling-4b-quality-into-sub-1b-multilingual-embeddings/
  (v5 text dimensions and context limits)
- https://jina.ai/en-US/news/jina-embeddings-v5-omni-multimodal-embeddings-for-text-image-audio-and-video/
  (v5 omni text compatibility, dimensions, and context limits)
- https://huggingface.co/jinaai/jina-reranker-v3 and Jina's reranker announcement posts
  (rerank response shape: `results[]` with `index`/`relevance_score`,
  `usage.total_tokens`)
- https://docs.jina.ai/api.md and https://docs.jina.ai/openapi.json (shared error body
  and error-code table; added 2026-10-26)

## Wire contract

### Endpoints
- `POST https://api.jina.ai/v1/embeddings`
- `POST https://api.jina.ai/v1/rerank`
- **No listing endpoint** — `list_models()` is honestly empty; `health()` is a labeled
  reachability probe (any HTTP answer counts).

### Auth
- `Authorization: Bearer <api_key>`. Conventionally `env://JINA_API_KEY`.

### Version pins
- The API version is in the path (`/v1`). No header or query parameter carries a version.
  Jina publishes model generations (v3, v4, m0) as *model ids* rather than API versions,
  so a new generation is a catalog change, not a wire change.

### Embeddings request fields (verified 2026-08-12)
- `model` (required), `input` (array of strings; no per-request ceiling documented —
  "batches inputs internally"), `task` — Jina's intent vocabulary, covering all four
  normalized intents: query→`retrieval.query`, document→`retrieval.passage`,
  classification→`classification`, and **clustering→`separation`** (Jina's
  clustering-flavored task; a deliberate mapping recorded here, not an upstream
  equivalence claim), plus `text-matching` (unmapped), `dimensions` (Matryoshka
  truncation), `truncate` (over-limit inputs otherwise fail), `late_chunking`,
  `embedding_type`/format options, `normalized`.
- The adapter sends `model`, `input`, `task` (when an intent was given), and
  `dimensions`; everything else is reachable via `provider_options`.

### Embeddings response (corroborated 2026-08-12, not yet live-verified)
- OpenAI-shaped: `data[]` with `embedding`/`index` (adapter orders by the reported
  index and rejects out-of-range/duplicates), `usage.total_tokens` →
  `Usage.total_tokens` only, never assumed into `input_tokens`.
- For multimodal calls, Jina also documents a `usage.image_tokens` breakdown. The
  adapter remains text-only, so it preserves the complete raw payload but does not
  normalize that modality-specific field.
- **Unverified:** default dimensions for the older v3/v4 models; the exact error-body
  shape.

### Rerank request fields (verified 2026-08-12)
- `model`, `query`, `documents` (list of strings; **"no hard limit on the number of
  documents per request"** — so no `max_documents` is declared and the sanity ceiling
  governs), `top_n` (native), `return_documents` (default false).

### Rerank response (verified 2026-08-12 from Jina's own publications)
- `results[]` with `index` (**positional within the submitted `documents`**, mapped
  back onto the caller-supplied index before core validation) and `relevance_score`;
  `model`; `usage.total_tokens`.
- **Cross-batch comparability: not documented** — refuse-by-default stands.

### Errors
- **Documented 2026-10-26** (source: https://docs.jina.ai/api.md, error section): failures
  carry `detail`, a machine `code` (e.g. `INPUT_TOKEN_LIMIT_EXCEEDED` 400,
  `INPUT_MODEL_NOT_FOUND` 400, `AUTH_INVALID_API_KEY`/`AUTH_MISSING_API_KEY` 401,
  `AUTHZ_INSUFFICIENT_BALANCE` 403, `RATE_*_LIMIT_EXCEEDED` 429, `INTERNAL_ERROR` 500,
  `SERVICE_UNAVAILABLE` 503, `SERVICE_TIMEOUT` 504) and `request_id`; only
  `/v1/chat/completions` uses an OpenAI envelope, and embeddings/rerank are stated not to
  be exceptions. Not yet seen on live traffic, and the per-endpoint schema was not read.
- The adapter maps HTTP status alone through the shared status classification and reads no
  provider-specific error field, so nothing breaks; whether to surface `detail`/`code`/
  `request_id` is a proposed adapter follow-up, not applied here.

### Streaming
Embeddings and rerank responses are not streamed.

### Published static model capabilities (verified 2026-10-15; omni/rerank rechecked 2026-10-26)
- `jina-embeddings-v5-text-small` and `jina-embeddings-v5-omni-small`: 1,024
  dimensions; Matryoshka choices 32/64/128/256/512/1,024 (the omni page lists 768 as well
  — 32/64/128/256/512/768/1,024; the text page says only "32 to 1024"); 32,768-token text
  input.
- `jina-embeddings-v5-text-nano` and `jina-embeddings-v5-omni-nano`: 768 dimensions;
  Matryoshka choices 32/64/128/256/512/768; 8,192-token text input.
- `jina-reranker-v3.5`: native `top_n`; a 131,072-token shared window for the query
  and all documents, with automatic truncation (the v3 model card additionally states up
  to 64 documents processed at once in that window — not a request ceiling). That is not a per-document ceiling, so
  `max_tokens_per_document` remains unset.

The omni models accept multimodal inputs upstream, but AnyInfer's embedding request is
text-only. They are listed here only for their verified text-compatible operation.

## Watchlist
- **Not yet live-verified** — first live lane confirms the embeddings response shape,
  error bodies, and usage fields.
- The clustering→`separation` mapping, should Jina document its tasks more precisely.
- `late_chunking`, multimodal inputs (v4/m0 and v5-omni), quantized
  `embedding_type` values — unmodelled; reachable via `provider_options`.
- A listing endpoint, if one appears.
