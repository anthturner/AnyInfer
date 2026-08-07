# openrouter — Protocol Contract

Status: M3 adapter — **implemented** (openai-compat subclass).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://openrouter.ai/docs/api-reference/overview
- https://openrouter.ai/docs/api-reference/list-available-models
- https://openrouter.ai/docs/changelog

## Wire contract
### Endpoints
- `POST https://openrouter.ai/api/v1/chat/completions` — generation
- `GET https://openrouter.ai/api/v1/models` — discovery **with rich metadata**: per-model
  `context_length`, `pricing` (prompt/completion per-token USD strings), supported
  parameters — feeds the capability layer with `discovered` provenance including pricing
### Auth
- `Authorization: Bearer <api_key>`; optional attribution headers (`HTTP-Referer`,
  `X-Title`)
### Version pins
- None
### Request fields
- openai-compat dialect; `model` uses namespaced ids (`vendor/model`); optional
  `provider` routing preferences object; `usage: {include: true}` for usage accounting;
  structured output via `response_format` where the underlying model supports it
  (capability varies per model — probe/metadata territory)
### Response fields
- As openai-compat; usage may include cost accounting; `model` echoes the concrete model
  actually served (upstream may route)
### Streaming
- SSE as openai-compat; keep-alive comment lines (`: OPENROUTER PROCESSING`) must be
  ignored by the SSE parser
### Errors
- openai-compat shapes plus 402 (insufficient credits) → typed as AuthError-adjacent
  billing error with hint; moderation blocks surfaced distinctly

## Watchlist
- `/models` metadata schema (pricing field format, supported_parameters) — our richest
  `discovered`-provenance source; shape changes ripple into the capability assembler
- Upstream model routing semantics vs our `auto`-sentinel conjunction rule (DESIGN.md §7)
- SSE comment/keep-alive framing quirks
