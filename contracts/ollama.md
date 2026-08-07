# ollama — Protocol Contract

Status: M1 adapter — **implemented** (native API, not the /v1 compat layer).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://github.com/ollama/ollama/blob/main/docs/api.md
- https://github.com/ollama/ollama/releases

## Wire contract
### Endpoints
- `POST {base}/api/chat` — generation (default base `http://127.0.0.1:11434`)
- `GET {base}/api/tags` — installed models (name, size, parameter_size, quantization, digest)
- `GET {base}/api/ps` — loaded models incl. `size_vram` (observed VRAM residency)
- `POST {base}/api/pull` — model download (used by tier provisioning)
### Auth
- None by default; optional `Authorization: Bearer` for proxied deployments
### Version pins
- None; behavior tracked via release notes
### Request fields
- `model`, `messages`, `stream`, `format` (JSON-schema object for grammar-enforced
  structured output, or `"json"`), `think` (bool or effort for reasoning models),
  `keep_alive` (session retention, e.g. `"10m"`), `options: {num_predict, temperature,
  top_p, stop, num_ctx, num_gpu}`
### Response fields
- `message.content`, `message.thinking`, `done`, `done_reason`,
  `prompt_eval_count` (input tokens), `eval_count` (output tokens),
  `total_duration`, `load_duration`, `prompt_eval_duration`, `eval_duration` (ns phases)
### Streaming
- NDJSON (one JSON object per line, not SSE); terminal object has `done: true` + counters
### Errors
- Non-2xx `{"error": "<message>"}`; connection-refused → ProviderUnavailable (server not
  running); model-missing 404 distinguishes pull-needed

## Watchlist
- Schema-projection quirks: llama.cpp grammar limits under `format` (Frisket strips
  minLength/maxLength, drops minItems/maxItems ≥ 2000) — revalidate per release
- `think` parameter evolution (effort levels vs boolean)
- GPU-spill detection fields (`size_vram` in /api/ps) — Frisket warns when a GPU model
  spills to CPU; field shape must hold
- Native /v1 OpenAI-compat layer maturing (could someday replace native dialect)
