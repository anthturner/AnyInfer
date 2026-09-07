# ollama — Protocol Contract

Status: M1 adapter — **implemented** (native API, not the /v1 compat layer).
Last verified: 2026-09-07 (generation) — live-verified against all five Upstream sources
below. Findings from this run: contract-drift/2026-09-07.
Embeddings section last verified: 2026-08-11 — fetched live against
`docs.ollama.com/api/embed` and the GitHub `docs/api.md`; re-checked 2026-09-07 against the
same two sources with no change found.

## Upstream sources
- https://github.com/ollama/ollama/blob/main/docs/api.md
- https://github.com/ollama/ollama/releases
- https://docs.ollama.com/api/chat
- https://docs.ollama.com/api/embed (embeddings; verified live 2026-08-11)
- https://docs.ollama.com/api-reference/show-model-details (`POST /api/show`; the older
  `docs.ollama.com/api/show` path 404s as of 2026-08-11 — use this URL instead)

## Wire contract
### Endpoints
- `POST {base}/api/chat` — generation (default base `http://127.0.0.1:11434`)
- `POST {base}/api/embed` — embeddings (current, batch-capable)
- `POST {base}/api/embeddings` — embeddings (deprecated singular-input predecessor;
  superseded by `/api/embed` per the GitHub docs, verbatim: "this endpoint has been
  superseded by `/api/embed`". AnyInfer speaks only `/api/embed`.)
- `GET {base}/api/tags` — installed models (name, size, parameter_size, quantization, digest)
- `GET {base}/api/ps` — loaded models incl. `size_vram` (observed VRAM residency)
- `POST {base}/api/pull` — model download, streamed (`local/services.py`)
### Auth
- None by default; optional `Authorization: Bearer` for proxied deployments
### Version pins
- None; behavior tracked via release notes
### Request fields
- `model`, `messages`, `stream`, `format` (JSON-schema object for grammar-enforced
  structured output, or `"json"`), `keep_alive` (session retention, e.g. `"10m"`).
- **`think` — resolved 2026-09-07** (was Watchlist "effort levels vs boolean"): confirmed
  bool *or* one of the string levels `"low"`, `"medium"`, `"high"`, `"max"` (no `"xhigh"`,
  unlike Anthropic's effort enum). Verified against https://docs.ollama.com/api/chat.
- **`logprobs`/`top_logprobs` — DRIFT, found 2026-09-07.** `docs.ollama.com/api/chat` now
  documents top-level request fields `logprobs` (bool, "whether to return log probabilities
  of the output tokens") and `top_logprobs` (int, count of most-likely tokens per
  position), plus a `logprobs` response array. This directly contradicts the snapshot's
  prior claim that "`/api/chat` defines no log-probability field at all," which is why
  `logprobs` was declared in `ignored_parameters`. **Adapter follow-up needed** (not
  changed here): if confirmed live against a running server, `ignored_parameters` should
  drop `logprobs`/`top_logprobs` and the response mapping should read the new field.
  Verified against https://docs.ollama.com/api/chat.
- **`tools` — NEW-CAPABILITY, found 2026-09-07.** `/api/chat` now documents a top-level
  `tools` array ("optional list of function tools the model may call during the chat"),
  not previously recorded here. Verified against https://docs.ollama.com/api/chat.
- **`options` object — DRIFT, found 2026-09-07.** The live, verbatim key list on
  `docs.ollama.com/api/chat` is `seed, temperature, top_k, top_p, min_p, stop, num_ctx,
  num_predict` — it no longer lists `presence_penalty`, `frequency_penalty`, or `num_gpu`
  (which this snapshot recorded as "added 2026-08-25"), and it now lists `top_k` and
  `min_p`, which were not recorded at all. This may be a documentation-completeness gap
  rather than a real removal (Ollama's `options` often passes through to the runtime and
  isn't always exhaustively documented) — **flagged, not asserted as removed**. Proposed
  action: confirm against a live server's accepted/rejected options before changing the
  adapter's option set.
- Verified 2026-08-10, unchanged 2026-09-07: vision-capable models accept base64 image
  strings in `messages[].images`. The native chat API does not define URL, document, or
  audio inputs, so those are refused before transport.
- **`images` response field — NEW-CAPABILITY, found 2026-09-07.** The response `message`
  object may now include an `images` array (base64-encoded response images), not
  previously recorded. Verified against https://docs.ollama.com/api/chat.
### Pull request/response fields
- Request: `{"model": "<name>", "stream": true}`
- Response: NDJSON lines carrying `status` (phase text), and per **layer**
  `digest` + `total` + `completed`; the counts are per layer, so the caller accumulates
  them to report whole-acquisition progress
- Failures arrive mid-stream as an `error` field on a 200 response, not as an HTTP
  status; a missing model reads `pull model manifest: file does not exist`
### Response fields
- `message.content`, `message.thinking`, `done`, `done_reason`,
  `prompt_eval_count` (input tokens), `eval_count` (output tokens),
  `total_duration`, `load_duration`, `prompt_eval_duration`, `eval_duration` (ns phases)
### Embeddings request fields (`/api/embed`, verified 2026-08-11)
- `model` (required), `input` (required — string **or** array of strings; batch input is
  native, not core-simulated one-at-a-time), `truncate` (bool, default `true` per docs —
  "If true, truncate inputs that exceed the context window"), `dimensions` (int, optional
  — native dimensionality reduction), `keep_alive` (string), `options` (runtime params:
  seed, temperature, top_k, top_p, min_p, stop, num_ctx, num_predict).
### Embeddings response fields (`/api/embed`, verified 2026-08-11)
- `model`, `embeddings` (array of arrays — batch order preserved positionally, not tagged
  by index the way OpenAI's `data[].index` is; the docs' own example returns one array per
  input in request order), `total_duration`, `load_duration`, `prompt_eval_count` (input
  tokens; there is no `eval_count`/`eval_duration`/`prompt_eval_duration` in the embed
  response — no generation phase exists for this endpoint).
- Per-model dimensions are discoverable via `POST /api/show`'s `model_info` object as a
  family-prefixed key, e.g. `"gemma4.embedding_length": 2560` — the key name varies by
  model family, so a caller cannot look it up by one fixed key across models. No explicit
  vector-normalization flag was found documented anywhere for this endpoint.
- **Unverified:** the error-body shape for `/api/embed` specifically. Neither
  `docs.ollama.com/api/embed` nor the GitHub `api.md` documents an error JSON body for this
  endpoint (searched full text). The adapter reuses the `/api/chat` `{"error": "<message>"}`
  shape shared by every native Ollama endpoint on the strength of that endpoint's own
  verified contract below, not on direct citation for `/api/embed` — flag this explicitly
  if a live probe or upstream source later contradicts it.
- **Unverified:** any explicit input-array batch-size limit. Neither source states a
  numeric cap; the adapter therefore sends whatever `BatchPolicy` allows through and relies
  on Ollama's own response/error to signal a real limit if one exists.
### Streaming
- NDJSON (one JSON object per line, not SSE); terminal object has `done: true` + counters.
  Embeddings responses are not streamed (buffered request/response).
### Errors
- Non-2xx `{"error": "<message>"}`; connection-refused → ProviderUnavailable (server not
  running); model-missing 404 distinguishes pull-needed. Verified for `/api/chat`; assumed
  but not directly cited for `/api/embed` (see above).

## Watchlist
- Schema-projection quirks: llama.cpp grammar limits under `format` (the adapter strips
  minLength/maxLength, drops minItems/maxItems ≥ 2000) — revalidate per release
- ~~`think` parameter evolution~~ — **RESOLVED 2026-09-07**: bool or `low`/`medium`/`high`/
  `max` (see Request fields)
- GPU-spill detection fields (`size_vram` in /api/ps) — the adapter warns when a GPU model
  spills to CPU; field shape must hold — not independently re-checked this run
- Native /v1 OpenAI-compat layer maturing (could someday replace native dialect)
- `/api/embed` error-body shape and batch-size ceiling remain unverified against upstream
  documentation (re-checked 2026-09-07, still absent from both sources; genuinely
  UNVERIFIABLE, not merely stale)
- **New, 2026-09-07**: `logprobs`/`top_logprobs`/`tools` request fields and an `images`
  response field, and a possible `options` key-set change (`top_k`/`min_p` in, `presence_
  penalty`/`frequency_penalty`/`num_gpu` no longer documented) — see Request fields DRIFT
  items; needs adapter-side confirmation against a live server before any code change
- **New, 2026-09-07**: release v0.33.3 (2026-09-02) changelog says "Report cached prompt
  tokens" with no field name given in the release notes text available to this run —
  UNVERIFIABLE which response field this adds; check `/api/chat` and `/api/embed` response
  schemas directly next run
