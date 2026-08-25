# voyage — Protocol Contract

Status: **implemented** — `providers/voyage.py`, embeddings and reranker.
Last verified: 2026-08-12 — against live Voyage documentation (sources below). Not yet
verified against live traffic; flagged in the watchlist.

## Upstream sources
- https://docs.voyageai.com/reference/embeddings-api
- https://docs.voyageai.com/reference/reranker-api

## Why a dedicated adapter, not a preset

The API is OpenAI-*shaped* (bearer auth, `data[]` with `embedding`/`index`, `usage`) but
diverges exactly where embeddings care: `input_type`, `output_dimension`, and
`output_dtype` are Voyage's own spellings, rerank takes `top_k`, and there is no
model-listing endpoint at all. Voyage serves no generation — this is the hosted
counterpart to TEI's retrieval-only shape.

## Wire contract

### Endpoints
- `POST https://api.voyageai.com/v1/embeddings`
- `POST https://api.voyageai.com/v1/rerank`
- **No listing endpoint** — `list_models()` is honestly empty; the verified model set
  lives in the descriptor's static capability tables. `health()` is a reachability
  probe: any HTTP answer (including the expected 404 on `/models`) counts as reachable.

### Auth
- `Authorization: Bearer <api_key>`. Conventionally `env://VOYAGE_API_KEY`.

### Version pins
- The API version is in the path (`/v1`). No header or query parameter carries a version,
  and no dated preview channel is documented, so a version change would arrive as a new
  path — visible in the endpoint list above rather than silently.

### Embeddings request fields (verified 2026-08-12)
- `model` (required), `input` (string or array, **maximum 1,000 entries**),
  `input_type` (default null; `"query"` or `"document"` — the only two intents, mapped
  1:1 from the normalized vocabulary; classification/clustering have no wire value and
  are never sent), `truncation` (default **true** — over-length inputs truncate
  server-side), `output_dimension`, `output_dtype` (default `float`; also
  int8/uint8/binary/ubinary), `encoding_format` (null or base64).
- Per-request token budgets vary by model (1M for the lite 4/3.5 models, 320K for
  voyage-4/3.5/2, 120K for the large/code/finance/law models) — request-total budgets,
  not per-input caps, so they are recorded here rather than forced into
  `max_input_tokens`.

### Embeddings response (verified 2026-08-12)
- `object: "list"`, `data[]` with `object`/`embedding`/`index`, `model`,
  `usage.total_tokens`. Entries carry their input index and the adapter orders by it
  rather than trusting arrival order; out-of-range or duplicate indexes are rejected.
- Usage reports **only** `total_tokens` — mapped to `Usage.total_tokens`, with
  `input_tokens` left unknown rather than assumed equal.
- **Unverified:** per-model default dimensions (not stated) — `dimensions` stays `None`.

### Rerank request fields (verified 2026-08-12)
- `model` (required), `query` (required), `documents` (required, list of strings —
  "The number of documents cannot exceed 1,000", a **hard limit**), `top_k` (Voyage's
  spelling of `top_n`), `return_documents` (default false), `truncation` (default true).
- Query/token budgets by model: 8,000 query tokens and 600K total for rerank-2.5/-lite;
  smaller for older models (see source).

### Rerank response (verified 2026-08-12)
- `object: "list"`, `data[]` with `index` (**positional within the submitted
  `documents` array**, mapped back onto the caller-supplied document index before core
  validation) and `relevance_score`, `model`, `usage.total_tokens`.
- **Cross-batch comparability: not documented** — `rerank_cross_batch` keeps its
  refuse-by-default here too.

### Streaming
Embeddings and rerank responses are not streamed.

### Errors
- Standard HTTP statuses mapped by the shared classification. **Unverified:** the exact
  error-body shape (the reference does not document it); `read_error_detail`'s generic
  parsing applies.

## Watchlist
- **Not yet live-verified** — the first live lane should confirm the error-body shape,
  usage fields, and that `data[]` ordering matches the documented index semantics.
- `output_dtype` quantized encodings and base64 `encoding_format` — unmodelled (float
  only); reachable via `provider_options`.
- The 1,000-input and 1,000-document ceilings, and the per-model token budgets.
- A model-listing endpoint, if one ever appears — `list_models()` should use it.
