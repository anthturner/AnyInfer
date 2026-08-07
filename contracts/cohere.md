# cohere — Protocol Contract

Status: **implemented** — `providers/cohere.py`, the native v2 Chat API.
Last verified: 2026-08-07 — against live Cohere documentation (sources below).

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

## Watchlist
- **Citations and `documents[]`** — the grounded-RAG surface (`citation_options` with
  modes ENABLED/DISABLED/FAST/ACCURATE/OFF) is reachable through `provider_options` but
  not normalized; citations are not currently surfaced on results.
- `safety_mode` (CONTEXTUAL/STRICT/OFF), `strict_tools`, `logprobs` — unmodelled.
- `tool_plan`, the model's stated plan before calling tools, is read but discarded.
- `k` (top-k) has no normalized equivalent; reachable through `provider_options`.
