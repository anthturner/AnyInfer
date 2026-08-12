# cohere — Protocol Contract

Status: **implemented** — `providers/cohere.py`: the native v2 Chat API, plus v2 embed
and v2 rerank.
Last verified: chat 2026-08-07; embeddings and rerank 2026-08-12 — against live Cohere
documentation (sources below).

## Upstream sources
- https://docs.cohere.com/reference/chat
- https://docs.cohere.com/reference/chat-stream
- https://docs.cohere.com/docs/streaming
- https://docs.cohere.com/docs/compatibility-api
- https://docs.cohere.com/reference/list-models
- https://docs.cohere.com/docs/models
- https://docs.cohere.com/docs/reasoning
- https://docs.cohere.com/docs/command-a-plus
- https://docs.cohere.com/docs/how-does-cohere-pricing-work
- https://cohere.com/pricing
- https://docs.cohere.com/reference/embed (embeddings, verified 2026-08-12)
- https://docs.cohere.com/reference/rerank (rerank, verified 2026-08-12)

## Why v2, not the compatibility API

`https://api.cohere.ai/compatibility/v1` exists and would work as a preset. The native v2
API is what makes Cohere worth choosing: grounded generation with document citations, its
own thinking channel, and usage that separates billed units from processed tokens.

## Wire contract

### Endpoints
- `POST https://api.cohere.com/v2/chat` — generation, streaming and unary
- `GET https://api.cohere.com/v1/models?endpoint=chat` — discovery, cursor-paginated via
  `page_token`; reports `context_length` and `features`

### Auth
- `Authorization: Bearer <api_key>`. Conventionally `env://CO_API_KEY`.

### Version pins
- The API version is in the path (`/v2`).

### Request fields sent
- `model`, `messages[]`, and **`stream` — which is required, not optional**, on every
  request.
- Sampling under Cohere's own names: `temperature`, **`p`** (not `top_p`), `max_tokens`,
  `stop_sequences`.
- `tools[]` in OpenAI function shape; `tool_choice` takes the **uppercase** enum
  `REQUIRED` or `NONE`. There is no way to name a specific tool, and no explicit `auto` —
  omitting the field *is* auto.
- `response_format`: type `json_object` plus `json_schema`, which is required when the
  type is `json_object`.
- `thinking`: type `enabled` or `disabled` plus `token_budget` — reasoning effort maps to
  a token budget, since Cohere budgets rather than naming levels.

### Response fields read
- `message.content[]` — `text` and `thinking` blocks, the latter surfaced as reasoning and
  kept out of the answer.
- `message.tool_calls[]` with `function.arguments` as a JSON string, plus a
  `message.tool_plan` string this adapter does not currently surface.
- `finish_reason` — **uppercase**: `COMPLETE` and `STOP_SEQUENCE` to stop, `MAX_TOKENS` to
  length, `TOOL_CALL` to tool_calls, `ERROR` and `TIMEOUT` to other. Unknown values
  normalize to other.
- `usage` — normalized counts follow `usage.tokens` (what was processed, which is what a
  context window measures) rather than `usage.billed_units`; `cached_tokens` becomes cache
  reads.

### Streaming
SSE with **typed event objects**, not delta chunks: `message-start`, `content-start`,
`content-delta`, `content-end`, `tool-plan-delta`, `tool-call-start`, `tool-call-delta`,
`tool-call-end`, `citation-start`, `citation-end`, `message-end`.

**Usage and the finish reason arrive only in `message-end`.**

### Errors
- JSON `{message, id}` with HTTP 400/401/403/404/422/429/498/499/500/501/503/504, mapped
  by the shared status classification.

### Embeddings request fields (`POST /v2/embed`, verified 2026-08-12)
- `model` (required), `texts` (list of strings, **maximum 96 per call** — endpoint-wide,
  fed into `EmbeddingCapabilities.max_batch_inputs`), `input_type` (**required**, no
  documented default; enum `search_document`/`search_query`/`classification`/`clustering`/
  `image`), `embedding_types` (default `["float"]`; also `int8`/`uint8`/`binary`/
  `ubinary`/`base64`), `output_dimension` (embed-v4+ only: 256/512/1024/1536),
  `truncate` (default `END`; also `NONE`/`START`), `max_tokens`, `priority`.
- The adapter sends `model`, `texts`, `input_type` (mapped from AnyInfer's intent
  vocabulary: query→`search_query`, document→`search_document`, classification and
  clustering verbatim), `embedding_types: ["float"]` explicitly, and `output_dimension`
  when the request asked for dimensions. A request with no input intent is **refused
  locally** — the field is required upstream and no default is documented, so sending
  one would be a guess.
- Embedding models and dimensions (docs/models, verified 2026-08-12): `embed-v4.0`
  (1536 default; 256/512/1024/1536; 128k context), `embed-english-v3.0` (1024, 512),
  `embed-english-light-v3.0` (384, 512), `embed-multilingual-v3.0` (1024, 512),
  `embed-multilingual-light-v3.0` (384, 512).

### Embeddings response fields (`POST /v2/embed`, verified 2026-08-12)
- `id`, `embeddings` (an **object keyed by embedding type** — the adapter reads
  `embeddings.float`, a list of float arrays in input order), `texts`, `meta` with
  `api_version`, `billed_units` (`input_tokens`, `search_units`, …), `tokens`
  (`input_tokens`, `output_tokens`), `warnings`.
- Normalized usage follows `meta.tokens` (same convention as chat); `billed_units` is
  **not** encoded into `Usage` — billed search units are never fake tokens — and remains
  reachable via `retain_raw`.
- **Unverified:** whether vectors are unit-normalized — not stated in the reference or
  models docs, so `EmbeddingWireResult.normalized` stays `None`. (A live call on
  2026-08-12 measured L2 ≈ 1.0 for `embed-english-light-v3.0`, but one observation is
  not a documented guarantee.) The error-body shape for `/v2/embed` specifically is not
  documented; the adapter assumes the platform-wide `{message, id}` shape chat documents.
- **Live-verified 2026-08-12** (trial key): embed returned the declared 384 dimensions
  for `embed-english-light-v3.0` with `meta.tokens.input_tokens` populated; rerank
  returned correctly ordered positional indexes with `top_n` honored.

### Rerank request fields (`POST /v2/rerank`, verified 2026-08-12)
- `model` (required), `query` (required), `documents` (required, **list of strings**),
  `top_n`, `max_tokens_per_doc` (default 4096 — longer documents are truncated
  server-side, not rejected), `priority`.
- The documentation "recommend[s] against sending more than 1,000 documents in a single
  request" — a documented recommendation, not an enforced cap; it is what
  `RerankCapabilities.max_documents` declares.
- Rerank models (docs/models, verified 2026-08-12): `rerank-v4.0-pro`, `rerank-v4.0-fast`
  (32k context), `rerank-v3.5`, `rerank-english-v3.0`, `rerank-multilingual-v3.0` (4k).

### Rerank response fields (`POST /v2/rerank`, verified 2026-08-12)
- `results[]` with `index` (**positional within the submitted `documents` array** — the
  adapter maps it back onto the caller-supplied document index before the core validates
  it) and `relevance_score` (documented as [0, 1], explicitly not ratio-scaled:
  "not accurate to assume a score of 0.9 means the document is 2x more relevant").
- `id`, `meta` with `billed_units` (`search_units`), `tokens`, `warnings`. Usage follows
  `meta.tokens` where present — but in live traffic (verified 2026-08-12 with a real
  key) rerank responses carried **only** `billed_units: {search_units: ...}` with no
  `tokens` block at all, so normalized `Usage` is typically empty for rerank. Search
  units stay un-encoded, as above.
- **Cross-batch comparability: not documented.** Nothing states that scores from
  separately submitted document batches share a scale, so `rerank_cross_batch` keeps its
  refuse-by-default for this provider.
- **Unverified:** the exact search-unit definition (the pricing docs say rerank "priced
  based on the quantity of searches" without defining documents-per-unit); the error-body
  shape for `/v2/rerank` specifically (assumed platform `{message, id}`).

### Streaming
Embeddings and rerank responses are not streamed.

## Watchlist
- **Citations and `documents[]`** — the grounded-RAG surface (`citation_options` with
  modes ENABLED/DISABLED/FAST/ACCURATE/OFF) is reachable through `provider_options` but
  not normalized; citations are not currently surfaced on results.
- `safety_mode` (CONTEXTUAL/STRICT/OFF), `strict_tools`, `logprobs` — unmodelled.
- `tool_plan`, the model's stated plan before calling tools, is read but discarded.
- `k` (top-k) has no normalized equivalent; reachable through `provider_options`.
- **Embed:** image and mixed `inputs` embedding unmodelled (text-only for now);
  `embedding_types` other than `float` (int8/binary/base64) unmodelled; `truncate`
  defaults to `END` upstream, meaning over-length inputs are silently truncated —
  reachable via `provider_options` but not normalized. Watch the 96-text ceiling and
  the `input_type` enum for drift.
- **Rerank:** watch the 1,000-document recommendation and `max_tokens_per_doc` default;
  structured/YAML document reranking guidance unmodelled.
- **Discovery** (`GET /v1/models?endpoint=chat`) deliberately filters to chat models, so
  embed/rerank models are not discovered — static capabilities carry them until
  operation-aware discovery lands.
