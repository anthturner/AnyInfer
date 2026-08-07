# anthropic — Protocol Contract

Status: M2 adapter — **implemented** (Messages API).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://docs.anthropic.com/en/api/messages
- https://docs.anthropic.com/en/api/models-list
- https://docs.anthropic.com/en/api/versioning
- https://docs.anthropic.com/en/release-notes/api

## Wire contract
### Endpoints
- `POST https://api.anthropic.com/v1/messages` — generation
- `GET https://api.anthropic.com/v1/models` — discovery (cursor-paginated: `first_page`,
  `has_more`, `after_id`)
### Auth
Two mutually exclusive credential shapes; the adapter sends one or the other, never both.
- **API key** (console.anthropic.com): `x-api-key: <key>`
- **OAuth token** (claude.ai subscription, from `ant auth print-credentials
  --access-token`): `authorization: Bearer <token>` **plus** `anthropic-beta:
  oauth-2025-04-20`. `/v1/messages` rejects the bearer token without that beta flag, so
  the adapter sends it unconditionally on this path rather than leaving it to the caller.
  Tokens are short-lived and are not auto-refreshed — configuration holds whatever the
  user supplied.
- Both paths also send `anthropic-version: 2023-06-01`.
### Version pins
- `anthropic-version: 2023-06-01`
### Request fields
- `model`, `max_tokens` (required), `system` (top-level, not a message role),
  `messages[{role: user|assistant, content}]`, `stream`, `temperature`, `top_p`,
  `stop_sequences`, `tools`, `tool_choice`; reasoning-effort wire form recorded in
  ModelFit as `output_config: {"effort": e}` — VERIFY on first drift run (extended
  thinking may instead use `thinking: {"type":"enabled","budget_tokens":N}`)
### Response fields
- `content[]` blocks (`text`, `tool_use`, `thinking`), `stop_reason`
  (`end_turn|max_tokens|stop_sequence|tool_use`), `usage.input_tokens`,
  `usage.output_tokens`, `usage.cache_creation_input_tokens`,
  `usage.cache_read_input_tokens`
### Streaming
- SSE typed events: `message_start`, `content_block_start`, `content_block_delta`
  (`text_delta`, `input_json_delta`, `thinking_delta`), `content_block_stop`,
  `message_delta` (stop_reason + cumulative usage), `message_stop`
- TTFT rule: `thinking_delta` stops the first-token clock but is excluded from answer text
### Errors
- Non-2xx `{"type":"error","error":{"type","message"}}`; 429 + `retry-after`;
  529 `overloaded_error` treated retryable

## Watchlist
- `anthropic-version` header updates / new required beta headers
- `oauth-2025-04-20` beta flag: whether it graduates to GA (making it droppable) or is
  superseded, and whether the endpoint set it gates widens beyond `/v1/messages`
- Native structured-output mechanism (we plan tool-based emulation — open question 7;
  verify whether a first-class json_schema output mode now exists)
- Reasoning/effort wire form (see Request fields caveat)
- New usage fields; models-list pagination shape
