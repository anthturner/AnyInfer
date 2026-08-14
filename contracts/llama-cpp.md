# llama-cpp — Protocol Contract (supervised llama-server)

Status: M1 adapter — **implemented** (openai-compat subclass over a supervised local subprocess),
now including embeddings.
Last verified: 2026-08-14 — embeddings section live-verified end to end (real pinned
llama-server b10327 build, real nomic-embed-text-v1.5 GGUF, real HTTP calls through the
production adapter code, not just documentation); multimodal endpoint and `--mmproj`
invocation checked 2026-08-10 against the current upstream server README; the remaining
protocol snapshot retains its 2026-08-05 code-survey basis.

## Upstream sources
- https://github.com/ggml-org/llama.cpp/tree/master/tools/server (server README = API doc)
- https://github.com/ggml-org/llama.cpp/releases

## Wire contract
### Endpoints
- `POST http://127.0.0.1:{port}/v1/chat/completions` — generation (openai-compat dialect)
- `POST http://127.0.0.1:{port}/v1/embeddings` — embeddings, **only on a server started
  with `--embeddings`** (live-verified 2026-08-14, see below)
- `GET  http://127.0.0.1:{port}/health` — readiness (`{"status":"ok"}` when model loaded)
- `GET  http://127.0.0.1:{port}/v1/models` — reports the single loaded model
### Auth
- None; loopback-only binding enforced by the supervisor (DESIGN.md §12, §20)
### Version pins
- llama.cpp build pinned per runtime manifest (`b10327` at snapshot time);
  AnyInfer re-pins at M1 and records the tag here
- Backend runtime variants: cpu / cuda / rocm / vulkan / metal, ranked
  {cuda:30, metal:25, vulkan:20, cpu:10}
### Request fields
- openai-compat plus server-side structured output: `response_format.json_schema`
  compiles to GBNF grammar (true grammar enforcement — mechanism `grammar`);
  schema projection quirks: repetition-limit constraints (strip minLength/maxLength,
  huge minItems/maxItems) as in the Ollama projection
- The OpenAI-compatible chat endpoint accepts typed `image_url` content. A vision request
  is sent only for a catalog artifact with a verified projector companion; documents and
  audio remain explicitly unsupported by this adapter.
### Response fields
- As openai-compat; `timings` object (prompt_n, predicted_n, per-phase ms) when enabled
### Streaming
- SSE as openai-compat
### Errors
- Connection refused/reset during load → supervisor state consulted before classifying
  (starting vs crashed → LocalRuntimeError with server log tail in `detail`)
- `/v1/embeddings` against a server started **without** `--embeddings`: `501` with body
  `{"error":{"code":501,"message":"This server does not support embeddings. Start it
  with \`--embeddings\`","type":"not_supported_error"}}` — live-verified 2026-08-14.
  There is no runtime toggle; the flag is startup-only, which is why
  `LlamaCppAdapter.embed()` uses a distinct supervisor key (`f"{model}:embeddings"`) from
  `generate()`'s, never sharing a resident process between the two.

### Embeddings — live-verified 2026-08-14
`POST /v1/embeddings` is **genuinely OpenAI-shaped** once `--embeddings` is set — request
`{"model": "...", "input": "..."|[...]}`, response
`{"model": "...", "object": "list", "usage": {"prompt_tokens", "total_tokens"},
"data": [{"embedding": [...], "index": 0, "object": "embedding"}, ...]}`, checked live
against `nomic-embed-text-v1.5` (768 dims). `OpenAICompatEmbeddingsMixin` — the same code
`openai.py`/`lm_studio.py` use — handles it with zero changes; no llama.cpp-specific
parsing was needed. `providers/llama_cpp.py`'s `_Delegate` composes it onto
`OpenAICompatAdapter`.

The **native**, non-`/v1`, `/embedding` endpoint (singular) also exists and was checked
for contrast — its shape is different (a bare list of results, not an OpenAI `data`
envelope, and each vector is nested one level deeper: `{"index": 0, "embedding":
[[...]]}`) — deliberately **not used**, since `/v1/embeddings` requires no
llama.cpp-specific parsing at all.

## Server invocation contract (supervisor → llama-server CLI)
- Flags emitted by the tuner: `--model <gguf>`, optional `--mmproj <projector.gguf>` for a
  catalog vision artifact, `--ctx-size`, `--threads`,
  `--batch-size`, `--ubatch-size`, `--n-gpu-layers` (999 accelerated / 0 cpu),
  `--cache-type-k`, `--cache-type-v` (q8_0 under aggressive posture), `--no-kv-offload`
  (when applicable), `--flash-attn on` (accelerated), `--host 127.0.0.1`,
  `--port <ephemeral>`, `--embeddings` (only when `ServerPlan.embeddings=True`,
  live-verified 2026-08-14 — see "Embeddings" above for why this is startup-only)
- CLI flag names are a drift surface: verify against the pinned release's `--help`
- Live-verified 2026-08-14: when `--embeddings` is set and the plan's `batch_size` (2048
  default) exceeds `ubatch_size`, the server itself logs a warning and clamps
  `batch_size` down to `ubatch_size` to avoid an assertion failure — a server-side safety
  net, not something the tuner needs to pre-empt.

## Watchlist
- Server API additions/renames between pinned builds (health shape, timings fields,
  /v1/models shape)
- GBNF/json_schema compilation limits (drives schema projection rules)
- CLI flag renames (tuner emission table must match the pinned build)
- Multimodal support is marked experimental upstream; watch typed content shapes,
  projector discovery, and the `/v1/models` multimodal capability.
- No pinned CUDA build exists yet for `linux-amd64` in the runtime table (confirmed
  2026-08-14 via `anyinfer runtime install cuda`: "no pinned cuda llama-server build
  exists for this platform") — only cpu/rocm/vulkan are pinned. A real NVIDIA GPU on this
  platform currently falls back to the Vulkan backend rather than CUDA; re-pinning a CUDA
  build is a `scripts/pin_runtimes.py` maintainer decision, not made here.
- Embedding-capable catalog entries (dimensions, native context, pooling type) are not
  yet representable in the catalog schema — `static_embedding_capabilities` is
  deliberately empty for this provider; see `plans/EMBEDDING_RERANKING_CONTINUATION.md`
  T11.
