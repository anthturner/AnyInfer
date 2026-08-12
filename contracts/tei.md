# tei — Protocol Contract

Status: **implemented** — `providers/tei.py`, the native TEI dialect (embed + rerank).
Last verified: 2026-08-12 — against the project's OpenAPI specification and quick tour
(sources below). Not yet verified against a live server; flagged per item below.

## Upstream sources
- https://huggingface.co/docs/text-embeddings-inference/quick_tour
- https://raw.githubusercontent.com/huggingface/text-embeddings-inference/main/docs/openapi.json
  (the canonical OpenAPI spec; the rendered reference at
  huggingface.github.io/text-embeddings-inference is JS-only and unfetchable headlessly)

## Why the native dialect, not the OpenAI-compatible route

TEI also mounts an OpenAI-compatible `POST /v1/embeddings`, which would work as a preset.
The native routes are what make TEI worth a dedicated adapter: `POST /rerank` — the one
local reranking endpoint in the initial provider set — and `GET /info`, which reports the
loaded model's identity and type so operations arrive with `discovered` provenance.

## One model per server

A TEI container serves exactly one model, chosen at startup. Consequences this adapter
encodes: the model half of a target string is advisory (`tei:anything` reaches the same
model; discovery reports the real id), and the descriptor declares
`operations={embedding, rerank}` while `/info`'s `model_type` narrows which one this
*particular* endpoint serves.

## Wire contract

### Endpoints
- `POST /embed` — embeddings, batch-native
- `POST /rerank` — reranking
- `GET /info` — identity/limits: `model_id`, `model_type` (tagged object, e.g.
  `{"embedding": {...}}` or `{"reranker": {...}}`), `max_input_length`,
  `max_batch_tokens`, `max_client_batch_size`, `version`

### Auth
- None by default (a loopback service). `Authorization: Bearer <key>` only when the
  server was started with `--api-key`; conventionally `env://TEI_API_KEY`.

### Embed request fields (verified 2026-08-12 from the OpenAPI spec)
- `inputs` (string or array of strings, required), `normalize` (default **true**),
  `truncate` (default false — over-length input errors rather than silently truncating),
  `truncation_direction` (default `right`), `prompt_name`, `dimensions` (nullable).
- The adapter sends `inputs` (always an array) and `dimensions` when requested; the
  server's `normalize: true` default is left in force, so
  `EmbeddingWireResult.normalized` reports what was actually sent — `True` unless a
  `provider_options` override changed it, in which case the override's value is
  reported.

### Embed response (verified 2026-08-12)
- A bare array of arrays of floats, in input order. No model field, no usage — usage
  stays `None`, never zero.
- **Per-request input ceiling**: `/info.max_client_batch_size` reports it per server, so
  no static `max_batch_inputs` is declared (it would be a guess about someone's
  deployment); until a discovery channel for embedding capabilities exists, callers with
  large corpora set `BatchPolicy.max_items_override` to their server's reported value.

### Rerank request fields (verified 2026-08-12)
- `query` (required), `texts` (array of strings, required), `raw_scores` (default
  false), `return_text` (default false), `truncate`, `truncation_direction`.
- **No native `top_n`**, and the spec does not state a result order. The adapter sorts
  by score descending and applies `top_n` client-side — a deterministic translation
  onto the normalized ranked contract, recorded here rather than assumed of the server.

### Rerank response (verified 2026-08-12)
- Array of `{index, score, text?}`; `index` is **positional within the submitted
  `texts` array** and is mapped back onto the caller-supplied document index before the
  core validates it (same treatment as the Cohere adapter).

### Errors
- JSON `{error, error_type}` with 413 (batch too large), 422 (tokenization), 424
  (inference failure), 429 (overloaded), mapped by the shared status classification;
  `retry-after` honoured on 429.

### Streaming
Embeddings and rerank responses are not streamed.

## Watchlist
- **Not yet live-verified**: everything above comes from the project's own spec and
  docs, not observed traffic — the first live lane should confirm the `/info`
  `model_type` spelling (tagged object vs plain string; the adapter accepts both) and
  the rerank result order.
- `prompt_name`/prompts, `raw_scores`, sequence-classification (`/predict`) —
  unmodelled; reachable via `provider_options`.
- `max_client_batch_size` as a discovered batch limit once a discovery channel for
  embedding capabilities exists.
- The OpenAI-compatible `/v1/embeddings` mount, if the native `/embed` route ever
  deprecates.
