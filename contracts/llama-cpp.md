# llama-cpp — Protocol Contract (supervised llama-server)

Status: M1 adapter — **implemented** (openai-compat subclass over a supervised local subprocess).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://github.com/ggml-org/llama.cpp/tree/master/tools/server (server README = API doc)
- https://github.com/ggml-org/llama.cpp/releases

## Wire contract
### Endpoints
- `POST http://127.0.0.1:{port}/v1/chat/completions` — generation (openai-compat dialect)
- `GET  http://127.0.0.1:{port}/health` — readiness (`{"status":"ok"}` when model loaded)
- `GET  http://127.0.0.1:{port}/v1/models` — reports the single loaded model
### Auth
- None; loopback-only binding enforced by the supervisor (DESIGN.md §12, §20)
### Version pins
- llama.cpp build pinned per runtime manifest (`b10199` at snapshot time);
  AnyInfer re-pins at M1 and records the tag here
- Backend runtime variants: cpu / cuda / rocm / vulkan / metal, ranked
  {cuda:30, metal:25, vulkan:20, cpu:10}
### Request fields
- openai-compat plus server-side structured output: `response_format.json_schema`
  compiles to GBNF grammar (true grammar enforcement — mechanism `grammar`);
  schema projection quirks: repetition-limit constraints (strip minLength/maxLength,
  huge minItems/maxItems) as in the Ollama projection
### Response fields
- As openai-compat; `timings` object (prompt_n, predicted_n, per-phase ms) when enabled
### Streaming
- SSE as openai-compat
### Errors
- Connection refused/reset during load → supervisor state consulted before classifying
  (starting vs crashed → LocalRuntimeError with server log tail in `detail`)

## Server invocation contract (supervisor → llama-server CLI)
- Flags emitted by the tuner: `--model <gguf>`, `--ctx-size`, `--threads`,
  `--batch-size`, `--ubatch-size`, `--n-gpu-layers` (999 accelerated / 0 cpu),
  `--cache-type-k`, `--cache-type-v` (q8_0 under aggressive posture), `--no-kv-offload`
  (when applicable), `--host 127.0.0.1`, `--port <ephemeral>`
- CLI flag names are a drift surface: verify against the pinned release's `--help`

## Watchlist
- Server API additions/renames between pinned builds (health shape, timings fields,
  /v1/models shape)
- GBNF/json_schema compilation limits (drives schema projection rules)
- CLI flag renames (tuner emission table must match the pinned build)
