# voyage — Protocol Contract

Status: **implemented** — `providers/voyage.py`, embeddings and reranker.
Last verified: 2026-09-28 — re-fetched live Voyage documentation (sources below), which
embeds Voyage's own OpenAPI 3.0 schema (`x-readme` code samples plus a full
`components.schemas`/`paths` document served inline in the reference page's HTML) —
the strongest evidence this snapshot has had to date. Not yet verified against live
traffic; flagged in the watchlist.

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
- **New, out of scope for this adapter:** Voyage's OpenAPI spec (embedded in
  https://docs.voyageai.com/reference/embeddings-api, fetched 2026-09-28) also declares
  `POST /contextualizedembeddings` (contextualized chunk embeddings), `POST
  /multimodalembeddings` (text/image embeddings), `GET/POST /files`, and
  `GET/POST /batches` (async batch processing). None are implemented by
  `providers/voyage.py`; see Watchlist.

### Auth
- `Authorization: Bearer <api_key>`. Conventionally `env://VOYAGE_API_KEY`. Confirmed by
  the OpenAPI `securitySchemes.ApiKeyAuth`: `{"type": "apiKey", "in": "header", "name":
  "Authorization: Bearer"}` (source as above, fetched 2026-09-28).

### Version pins
- The API version is in the path (`/v1`). No header or query parameter carries a version,
  and no dated preview channel is documented, so a version change would arrive as a new
  path — visible in the endpoint list above rather than silently. Confirmed via the
  OpenAPI `servers` entry: `https://api.voyageai.com/v1` (fetched 2026-09-28).

### Embeddings request fields (verified 2026-08-12, re-verified 2026-09-28)
- `model` (required), `input` (string or array, **maximum 1,000 entries**),
  `input_type` (default null; `"query"` or `"document"` — the only two intents, mapped
  1:1 from the normalized vocabulary; classification/clustering have no wire value and
  are never sent), `truncation` (default **true** — over-length inputs truncate
  server-side), `output_dimension`, `output_dtype` (default `float`; also
  int8/uint8/binary/ubinary), `encoding_format` (null or base64).
- Per-request token budgets vary by model (1M for the lite 4/3.5 models, 320K for
  voyage-4/3.5/2, 120K for the large/code/finance/law models) — request-total budgets,
  not per-input caps, so they are recorded here rather than forced into
  `max_input_tokens`. Verbatim from the OpenAPI schema's `input` description, unchanged.

### Embeddings response (verified 2026-08-12, re-verified 2026-09-28)
- `object: "list"`, `data[]` with `object`/`embedding`/`index`, `model`,
  `usage.total_tokens`. Entries carry their input index and the adapter orders by it
  rather than trusting arrival order; out-of-range or duplicate indexes are rejected.
  Confirmed against the OpenAPI schema's literal example: `{"object":"list","data":
  [{"object":"embedding","embedding":[...],"index":0}, ...],"model":"voyage-4-large",
  "usage":{"total_tokens":8}}`.
- Usage reports **only** `total_tokens` — mapped to `Usage.total_tokens`, with
  `input_tokens` left unknown rather than assumed equal. No `prompt_tokens` field
  appears anywhere in the reference page's static content.
- **Resolved (was unverified):** `output_dimension`'s default is now documented as
  1024, with `2048`/`1024`/`512`/`256` as the selectable values, for `voyage-4-large`,
  `voyage-4`, `voyage-4-lite`, `voyage-3-large`, `voyage-3.5`, `voyage-3.5-lite`, and
  `voyage-code-3` (source: https://docs.voyageai.com/reference/embeddings-api,
  OpenAPI `output_dimension` field description, fetched 2026-09-28). The adapter
  already leaves `dimensions` as `None` unless the caller supplies it, so this needs no
  adapter change — informational only.

### Rerank request fields (verified 2026-08-12, re-verified 2026-09-28)
- `model` (required), `query` (required), `documents` (required, list of strings —
  "The number of documents cannot exceed 1,000", a **hard limit**), `top_k` (Voyage's
  spelling of `top_n`), `return_documents` (default false), `truncation` (default true).
  The OpenAPI schema declares exactly these six properties and no others.
- Query/token budgets by model: 8,000 query tokens and 600K total for rerank-2.5/-lite;
  smaller for older models (see source). Unchanged from the prior audit.

### Rerank response (verified 2026-08-12, re-verified 2026-09-28)
- `object: "list"`, `data[]` with `index` (**positional within the submitted
  `documents` array**, mapped back onto the caller-supplied document index before core
  validation) and `relevance_score`, `model`, `usage.total_tokens`. Confirmed against
  the OpenAPI schema's literal example: `{"object":"list","data":[{"relevance_score":
  0.455078125,"index":0}, ...],"model":"rerank-2.5-lite","usage":{"total_tokens":8}}`.
- **Cross-batch comparability: not documented** — `rerank_cross_batch` keeps its
  refuse-by-default here too.

### Streaming
Embeddings and rerank responses are not streamed.

### Errors
- Standard HTTP statuses mapped by the shared classification.
- **Resolved (was unverified):** the error-body shape is now documented directly in
  Voyage's OpenAPI schema — both the `4XX` and `5XX` response objects specify
  `{"detail": "<the error message>"}` as the JSON body (source:
  https://docs.voyageai.com/reference/embeddings-api, `components.responses.4XX`/`5XX`,
  fetched 2026-09-28; identical schema is referenced from the rerank endpoint). This
  already matches what `read_error_detail` extracts today (it falls back to reading a
  bare `detail` key when there is no `error` wrapper), so no adapter change is implied —
  informational only.

## Watchlist
- **Not yet live-verified** — the first live lane should confirm `data[]` ordering
  matches the documented index semantics against real traffic (the error-body shape and
  usage fields are now confirmed from Voyage's own OpenAPI schema — see Errors and
  Embeddings response above).
- `output_dtype` quantized encodings and base64 `encoding_format` — unmodelled (float
  only); reachable via `provider_options`.
- The 1,000-input and 1,000-document ceilings, and the per-model token budgets.
- A model-listing endpoint, if one ever appears — `list_models()` should use it.
- **New capabilities, not implemented by this adapter:** `/contextualizedembeddings`
  (contextualized chunk embeddings), `/multimodalembeddings` (text/image embeddings),
  and `/files` + `/batches` (async batch processing) all now appear in Voyage's OpenAPI
  schema (fetched 2026-09-28). None affect the wire contract for the two operations this
  adapter implements; tracked here as a capability-catalog / roadmap item, not a defect.
