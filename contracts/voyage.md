# voyage — Protocol Contract

Status: **implemented** — `providers/voyage.py`, embeddings and reranker.
Last verified: 2026-10-22 — against current Voyage documentation (sources below). Not yet
verified against live traffic; flagged in the watchlist.

## Upstream sources
- https://docs.voyageai.com/reference/embeddings-api
- https://docs.voyageai.com/reference/reranker-api
- https://docs.voyageai.com/docs/embeddings
- https://docs.voyageai.com/docs/error-codes

The 2026-10-22 check confirms the existing text-only request vocabulary and limits.
This is documentation evidence, not authenticated traffic. The Python adapter remains
the implemented behavioral baseline for the native C# binding; neither implementation
claims quantized/base64 output support or newly catalogued models from this check.

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
- **No documented listing endpoint in the scoped references** — `list_models()` is empty; the verified model set
  lives in the descriptor's static capability tables. `health()` is a reachability
  probe: any HTTP answer (including the expected 404 on `/models`) counts as reachable.

### Auth
- `Authorization: Bearer <api_key>`. Conventionally `env://VOYAGE_API_KEY`.

### Version pins
- The API version is in the path (`/v1`). No header or query parameter carries a version,
  and no dated preview channel is documented, so a version change would arrive as a new
  path — visible in the endpoint list above rather than silently.

### Embeddings request fields (verified 2026-10-22)
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

### Embeddings response (verified 2026-10-22)
- `object: "list"`, `data[]` with `object`/`embedding`/`index`, `model`,
  `usage.total_tokens`. Entries carry their input index and the adapter orders by it
  rather than trusting arrival order; out-of-range or duplicate indexes are rejected.
- Usage reports **only** `total_tokens` — mapped to `Usage.total_tokens`, with
  `input_tokens` left unknown rather than assumed equal.
- The current reference documents 1024 as the default for its listed variable-dimension
  models, with 2048/1024/512/256 supported. This catalog fact is not a response observation:
  the adapter derives dimensions from the returned vector and leaves normalization unknown.

### Rerank request fields (verified 2026-10-22)
- `model` (required), `query` (required), `documents` (required, list of strings —
  "The number of documents cannot exceed 1,000", a **hard limit**), `top_k` (Voyage's
  spelling of `top_n`), `return_documents` (default false), `truncation` (default true).
- Query/token budgets by model: 8,000 query tokens and 600K total for rerank-2.5/-lite;
  smaller for older models (see source).

### Rerank response (verified 2026-10-22)
- `object: "list"`, `data[]` with `index` (**positional within the submitted
  `documents` array**, mapped back onto the caller-supplied document index before core
  validation) and `relevance_score`, `model`, `usage.total_tokens`.
- **Cross-batch comparability: not documented** — `rerank_cross_batch` keeps its
  refuse-by-default here too.

### Streaming
Embeddings and rerank responses are not streamed.

### Errors
- Standard HTTP statuses mapped by the shared classification. **Verified 2026-10-22:**
  both reference pages embed an OpenAPI schema documenting the 4XX body as
  `{"detail": "<string>"}` ("The error message."); 5XX carries no documented body
  schema. `read_error_detail`'s generic fallback (`providers/http.py`) reads an
  unwrapped top-level `detail` key correctly already, so no adapter change follows from
  this.
- The rendered reference omits the response schemas; the raw page's `ssr-props` embeds
  the OpenAPI schemas. These confirm indexed embedding/rerank entries, `model`, and
  `usage.total_tokens`. The rerank schema describes service results as descending by
  relevance; the adapter preserves service order and sends `top_k`, without local sorting.

## Watchlist
- **Not yet live-verified** — the first live lane should confirm the usage fields and
  that `data[]` ordering matches the documented index semantics. The error-body shape is
  now confirmed from the docs' embedded OpenAPI schema (see Errors above) but not yet
  seen on live traffic.
- `output_dtype` quantized encodings and base64 `encoding_format` — unmodelled (float
  only); reachable via `provider_options`.
- The 1,000-input and 1,000-document ceilings, and the per-model token budgets.
- A model-listing endpoint, if one ever appears — `list_models()` should use it.
- No listing or health API was found in the scoped official references on 2026-10-22.
  Empty discovery and the `/models` reachability probe describe adapter behavior; a 404
  proves only that the endpoint answered, not credential validity or model readiness.
- Current model guides also list newer models beyond the existing static capability
  table. This binding preserves that table; this check does not infer unsupported model
  capabilities or widen normalized operations.
