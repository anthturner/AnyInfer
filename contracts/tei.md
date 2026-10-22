# tei — Protocol Contract

Status: **contract refreshed; TEI 1.9.4 runtime qualified on 2026-10-22**. Python adapter: `src/python/anyinfer/providers/tei.py`. Native routes: `POST /embed`, `POST /rerank`, `GET /info`.
Last verified: 2026-10-22 — pinned Linux/amd64 `cpu-1.9.4` image ran two loopback-only processes and reported 1.9.4 from `/info`; the older 2026-08-24 `cpu-1.8` cassettes are retained only as historical evidence.

## Upstream sources

Sources fetched 2026-10-22:

- [Tagged v1.9.4 OpenAPI](https://raw.githubusercontent.com/huggingface/text-embeddings-inference/v1.9.4/docs/openapi.json) — canonical HTTP schema (`info.version` 1.9.4).
- [Tagged v1.9.4 HTTP server](https://raw.githubusercontent.com/huggingface/text-embeddings-inference/v1.9.4/router/src/http/server.rs) — route handlers, nullable truncation resolution, response construction.
- [Tagged v1.9.4 router types](https://raw.githubusercontent.com/huggingface/text-embeddings-inference/v1.9.4/router/src/lib.rs) — `Info` and model metadata.
- [Tagged v1.9.4 router arguments](https://raw.githubusercontent.com/huggingface/text-embeddings-inference/v1.9.4/router/src/main.rs) — `--auto-truncate` launch default and `--revision` support.
- [Tagged v1.9.4 README](https://raw.githubusercontent.com/huggingface/text-embeddings-inference/v1.9.4/README.md) — supported deployment and API-key configuration.
- [TEI Quick Tour](https://huggingface.co/docs/text-embeddings-inference/en/quick_tour) — current deployment and native endpoint examples.
- [v1.9.4 release](https://github.com/huggingface/text-embeddings-inference/releases/tag/v1.9.4) — release tag and provenance.
- [Pinned BGE-small model metadata](https://huggingface.co/api/models/BAAI/bge-small-en-v1.5/revision/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a?blobs=true) and [pinned BGE-reranker model metadata](https://huggingface.co/api/models/BAAI/bge-reranker-base/revision/2cfc18c9415c912f9d8155881c133215df768a70?blobs=true) — immutable Hub revisions and published files.

The rendered Swagger page is JavaScript-driven; use the tagged raw OpenAPI instead.

## Wire contract

### Endpoints

- `POST /embed` — embeddings; batch-native.
- `POST /rerank` — reranking; one query and an ordered list of texts.
- `GET /info` — deployment identity, type, effective limits, and version.
- `GET /health` — raw health probe. The SDK health path remains `/info` to establish readiness and identity together.

`/info` returns `model_id`, `model_type`, `served_model_name`, `max_concurrent_requests`, `max_input_length`, `max_batch_tokens`, `max_client_batch_size`, `auto_truncate`, `tokenization_workers`, and `version`. These are deployment data. This SDK slice does not hydrate capabilities or batching/token/dimension limits from `/info`; leave limits unknown. v1.9.4 adds required `served_model_name` relative to v1.8.3; it is for OpenAI-compatible routes and is ignored by native discovery. A process serves one configured model; a request target model is advisory and does not replace returned target/model from cached discovery.

Discovery returns the single nonempty `model_id` or an empty list. Known `embedding` and `reranker` forms map to their operations. Python also accepts the compatible plain string form. An unknown but recognized `model_type` yields a discovered empty operation set; missing or invalid type leaves the fact unknown.

### Auth

The server is unauthenticated unless launched with `--api-key` / `API_KEY`. When enabled it accepts `Authorization: Bearer <key>`. `TEI_API_KEY` is AnyInfer's optional client configuration convention, not TEI's server environment variable. The native C# descriptor uses provider id `tei`, alias `text-embeddings-inference`, display name `Text Embeddings Inference`, locality `Local`, and exactly `Embedding` + `Rerank`; it has no static capabilities, price, fixed dimension, intent claim, or batching limit. Default endpoint is `http://127.0.0.1:8080`; endpoint and secret setup fields are optional, discover-or-manual model selection is used, and the configured transport is pool-owned. These are SDK decisions, not upstream protocol facts.

Start with JSON Content-Type/Accept and optional Bearer authentication. Configured headers override defaults case-insensitively, as in Python; content headers attach to request content. Preserve configured base-path joining semantics. Python `httpx2` joining for paths with and without a leading slash, trailing slash, and non-root base path has been confirmed to preserve the base path; C# URI behavior must match. Invalid URL/header construction uses existing typed configuration errors. Configured instance identity is retained for errors and telemetry; core credential resolution/redaction remains authoritative.

### Version pins

Native paths are unversioned; no version header or query parameter is sent. `/info.version` reports the running build. The v1.9.4 OpenAPI's own `info.version` is documentation metadata, not proof of a running process version.

### Request fields

**Embedding (`POST /embed`).** v1.9.4 request schema: required `inputs` (one input or an array), optional nullable `dimensions`, `normalize` (default true), `prompt_name`, nullable `truncate`, and `truncation_direction` (default `right`). Python sends `inputs` as an array and adds `dimensions` only when requested; it sends no model or input intent. Per-call provider options overlay native defaults last, including collisions with `inputs`, `dimensions`, and `normalize`. Provider configuration `options` and `api_version` are ignored; do not add rejection logic or merge those fields into requests.

**Rerank (`POST /rerank`).** v1.9.4 request schema: required `query` and `texts`; optional `raw_scores` (default false), `return_text` (default false), nullable `truncate`, and `truncation_direction`. Python sends `query`, wire-order `texts`, and `return_text: false`; it sends no model, caller IDs, original indexes, or `top_n`. Per-call provider options overlay defaults last, including collisions with `query`, `texts`, and `return_text`. Do not add a reserved-field filter.

**Truncation inheritance.** The OpenAPI marks `truncate` nullable. Tagged `router/src/http/server.rs` uses `req.truncate.unwrap_or(info.auto_truncate)` for `/embed` and `/rerank`; tagged `router/src/main.rs` says `--auto-truncate` defaults true. Explicit true enables truncation, explicit false disables it, and omitted/null inherits the server setting. The old 2026-08-12 OpenAPI and 2026-08-24 live snapshot described false as an unconditional request default; that description is historical v1.8.3-era evidence, not the current behavior. TEI.2 must probe omitted, null, true, and false.

### Response fields

**Embedding.** Success is a bare array of float arrays, in input order. Preserve rows/order and raw response. Dimensions are inferred from the first row, or unknown for no rows. Normalized reports the final payload's boolean `normalize`, default true; a non-boolean override yields unknown. Empty, ragged, or non-finite vectors reach existing core validation; do not tighten permissive wire DTO constructors. Model and usage remain unknown; never use zero for missing usage or infer usage from headers.

**Rerank.** Success entries contain positional integer `index`, numeric `score`, optional `text`. Map positional indexes to submitted document indexes. Stable-sort descending by score, preserving provider order on ties, then apply TopN client-side. There is no native `top_n` request field and OpenAPI gives no ordering guarantee; preserve client sorting regardless of observed order. Keep raw as the original response array; returned text does not replace caller-owned projection. Model and usage remain unknown. Do not compare scores across calls or relax the core cross-batch boundary. C# rejects malformed index/score shapes according to the execution plan.

### Streaming

Embedding and rerank responses are buffered JSON, not streamed. There is no stream terminator or TTFT event.

### Errors

OpenAPI documents 400 (empty batch), 413 (batch size), 422 (tokenization), 424 (inference/backend), and 429 (overload) on native retrieval routes. `ErrorResponse` has `error` and `error_type`; the enum capitalization and generated lowercase examples conflict. Do not depend on `error_type` spelling. Extract a string `error` when present, otherwise use bounded UTF-8 replacement-decoded body text.

Preserve Python `providers/http.py:classify_status` semantics: 401/403 auth and nonretryable; 404 model missing and nonretryable; 429 retryable rate-limit; 413/422 become context-overflow only with the shared marker; >=500 unavailable/retryable; other >=400 remain base provider errors with only shared retryable statuses marked retryable. Connection failures map unavailable; owned timeout/transport IO maps transport errors. Malformed response shape is validation-phase and nonretryable. Operation transport/status failures use compatibility phase `generate`; discovery uses `discover`. Honor only numeric delta-seconds `Retry-After`, matching Python `parse_retry_after`; ignore HTTP-date values. This does not claim TEI emits the header. No usage, timing, or Retry-After response-header contract appears in the v1.9.4 OpenAPI; ignore undocumented `x-compute-*` and timing headers and leave usage `None`.

## Watchlist

### Pinned runtime executed 2026-10-22

| Item | Selected value | Evidence/status |
| --- | --- | --- |
| Image | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4@sha256:8419f533857b503ebf6ec292a95d4f1cf9c0464ac8b8abeef39518cf110e5726` | Local image inspection matched this immutable digest, `linux/amd64`, and the selected CPU image. `/info.version` on both processes was `1.9.4` and `/info.sha` was `e80ef225ed0e6cb1717ce632a6a84b6cf211bb67`. |
| Platform | Linux/amd64 CPU image | Docker Desktop Linux daemon (`x86_64`) ran named, labeled containers bound only to `127.0.0.1:8080` and `127.0.0.1:8081`. |
| Embed model | `BAAI/bge-small-en-v1.5`, revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` | `/info.model_id` and `model_sha` matched; the running process downloaded and loaded `onnx/model.onnx`. |
| Rerank model | `BAAI/bge-reranker-base`, revision `2cfc18c9415c912f9d8155881c133215df768a70` | `/info.model_id` and `model_sha` matched; the running process downloaded and loaded `onnx/model.onnx`. |
| Endpoints | `http://127.0.0.1:8080` embed; `http://127.0.0.1:8081` rerank | `GET /info`, `GET /health`, and public Python embed/rerank calls succeeded. |

The image manifest's advertised compressed layers plus config total 239,313,275 bytes. Pinned repositories advertise safetensors of 133,466,304 and 1,112,206,140 bytes. These are registry metadata, not observed download totals. Do not put downloaded models or image layers in source/package artifacts.

The live matrix established: scalar and batch embedding responses were 384-dimensional; `normalize: false` succeeded; requested `dimensions: 128` succeeded; and the reranker returned positional indices and scores. For a 602-token embedding request with server `auto_truncate: true`, omitted and null `truncate` succeeded, explicit `true` succeeded, and explicit `false` returned 422. Empty inputs returned 400. Sending `/embed` to the reranker or `/rerank` to the embedder returned 424. A separately owned temporary API-key process returned 401 without a Bearer header and a public Python call with a disposable configured key succeeded; the key was not retained in cassettes or evidence.

Fresh cassettes were recorded from the pinned servers on 2026-10-22 and replayed offline with recording disabled. They retain live `x-compute-*` headers but do not treat them as usage/timing data; the CPU image's observed `x-compute-type` header was `gpu+optimized`, so it is not a reliable backend/provenance claim.

### Native transport safeguards

These are native client safeguards, not TEI limits and not a rewrite of Python lifecycle buffering:

- Limit native `/info` body reads to 1 MiB.
- Read at most 64 KiB of HTTP error diagnostics; use a bounded raw-prefix fallback if the JSON error object is incomplete.
- Count received operation bytes before success parsing, including chunked responses or missing/incorrect Content-Length, against the existing `MaxResponseBytes` unchanged.
- Classify HTTP status before success caps so a large error body does not turn (for example) a 401 into vector validation.

### Still unverified

Overload and server-side cancellation remain unverified; no unsafe load test or backend-cancellation claim was made. TEI did not emit `Retry-After` in this qualification, so its numeric-delta parsing remains a Python compatibility rule rather than a runtime emission claim. Do not promote undocumented compute/timing headers to Usage or Timing. The live rerank response happened to be score-descending, but the SDK still sorts because the protocol does not promise that order.
