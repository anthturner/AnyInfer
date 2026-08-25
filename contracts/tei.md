# tei — Protocol Contract

Status: **implemented** — `providers/tei.py`, the native TEI dialect (embed + rerank).
Last verified: 2026-08-24 — **live**, against two real servers running the official
`ghcr.io/huggingface/text-embeddings-inference:cpu-1.8` image (reporting version 1.8.3),
one loaded with `BAAI/bge-small-en-v1.5` and one with `BAAI/bge-reranker-base`. The
traffic is committed as `tests/cassettes/tei_{embed,info,rerank}.json` and replays
offline. The wire-shape assertions below were confirmed against the project's OpenAPI
specification on 2026-08-12 and against observed traffic on 2026-08-24.

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

### Version pins
- **No API version anywhere** — paths are unversioned and TEI sends no version header.
  The server's build identity comes from `GET /info`'s `version` field, which is the only
  thing a caller can pin against; the adapter reads it for diagnostics. A breaking change
  to an unversioned local API is therefore invisible until a request fails, which is why
  the watchlist below tracks build-specific behaviour explicitly.

### Embed request fields (spec 2026-08-12; live 2026-08-24)
- `inputs` (string or array of strings, required), `normalize` (default **true**),
  `truncate` (default false — over-length input errors rather than silently truncating),
  `truncation_direction` (default `right`), `prompt_name`, `dimensions` (nullable).
- The adapter sends `inputs` (always an array) and `dimensions` when requested; the
  server's `normalize: true` default is left in force, so
  `EmbeddingWireResult.normalized` reports what was actually sent — `True` unless a
  `provider_options` override changed it, in which case the override's value is
  reported.

### Embed response (spec 2026-08-12; live 2026-08-24 — 384 floats per input, no usage body)
- A bare array of arrays of floats, in input order. No model field, no usage — usage
  stays `None`, never zero.
- **Per-request input ceiling**: `/info.max_client_batch_size` reports it per server, so
  no static `max_batch_inputs` is declared (it would be a guess about someone's
  deployment); until a discovery channel for embedding capabilities exists, callers with
  large corpora set `BatchPolicy.max_items_override` to their server's reported value.

### Rerank request fields (spec 2026-08-12; live 2026-08-24)
- `query` (required), `texts` (array of strings, required), `raw_scores` (default
  false), `return_text` (default false), `truncate`, `truncation_direction`.
- **No native `top_n`**, and the spec does not state a result order. The adapter sorts
  by score descending and applies `top_n` client-side — a deterministic translation
  onto the normalized ranked contract, recorded here rather than assumed of the server.

### Rerank response (spec 2026-08-12; live 2026-08-24)
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
- **Undocumented usage headers (observed 2026-08-24, build 1.8.3).** Every `/embed` and
  `/rerank` response carries `x-compute-tokens`, `x-compute-characters`, and a set of
  timing headers (`x-compute-time`, `x-tokenization-time`, `x-queue-time`,
  `x-inference-time`). None appears anywhere in the published OpenAPI document, which is
  why the adapter does **not** read them: usage built on an undocumented header would
  vanish silently on any release, and the drift check compares against documentation that
  never mentioned it, so nothing would notice. If upstream documents them, this becomes
  the token accounting TEI is currently recorded as not having.
- **Rerank result order (observed 2026-08-24, build 1.8.3): descending by score.** The
  OpenAPI document still states no ordering guarantee, so the adapter keeps sorting; the
  observation is recorded so a future change is visible, not so the sort can be removed.
- `/info.model_type` is a **tagged object**, confirmed live in both shapes:
  `{"embedding": {"pooling": "cls"}}` on the embedder and
  `{"reranker": {"id2label": ..., "label2id": ...}}` on the reranker. The adapter's
  acceptance of a plain string is now belt-and-braces rather than a hedge.
- `prompt_name`/prompts, `raw_scores`, sequence-classification (`/predict`) —
  unmodelled; reachable via `provider_options`.
- `max_client_batch_size` as a discovered batch limit once a discovery channel for
  embedding capabilities exists.
- The OpenAI-compatible `/v1/embeddings` mount, if the native `/embed` route ever
  deprecates.
