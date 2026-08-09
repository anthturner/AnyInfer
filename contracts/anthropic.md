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
  `output_config: {"effort": e}` — VERIFY on first drift run (extended
  thinking may instead use `thinking: {"type":"enabled","budget_tokens":N}`)
### Prompt caching (placement)
- Mechanism: **explicit**. `cache_control: {"type": "ephemeral"}` attaches to a content
  block, a `system` content block, or a tool declaration, and marks everything *before and
  including* it as the cacheable prefix.
- The adapter sends a mark only when the core's cache planner placed one; a request with no
  cache policy is byte-identical to what shipped before placement existed.
- A marked `system` field is sent as a one-element content-block list rather than a bare
  string, because `cache_control` cannot attach to a string.
- A tools mark attaches to the **last** tool declaration, since the tool block precedes the
  messages and a mark covers the prefix up to itself.
- Declared on the descriptor as `cache_mechanism="explicit"`, `cache_max_marks=4`,
  `cache_min_tokens=1024`. **VERIFY on the next drift run**: the breakpoint ceiling and the
  minimum cacheable prefix are the values recorded here, and both are the kind of limit
  that moves; the minimum also varies by model on this API.
- Retention window is whatever the API's default for `ephemeral` is; AnyInfer does not
  select a TTL. If a longer window becomes selectable per request, that is a new field to
  record here before the adapter sends it.

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
### Rate-limit headers
Verified 2026-08-09 against https://platform.claude.com/docs/en/api/rate-limits (the
`docs.anthropic.com` URL now 301s there).
- Read by the descriptor's dialect: `anthropic-ratelimit-requests-remaining`,
  `anthropic-ratelimit-requests-reset`, `anthropic-ratelimit-tokens-remaining`,
  `anthropic-ratelimit-tokens-reset`, `anthropic-ratelimit-requests-limit`,
  `anthropic-ratelimit-tokens-limit`.
- Reset values are **RFC 3339 instants**, not durations. Every derived wait is clamped
  before it is taken, so a skewed clock costs a bounded pause rather than a hang.
- The `tokens` pair is documented as reporting *the most restrictive limit currently in
  effect*, which is why it is read in preference to the `input-tokens` / `output-tokens`
  pairs. Remaining token counts are rounded to the nearest thousand.
- Not read: `anthropic-ratelimit-input-tokens-*`, `anthropic-ratelimit-output-tokens-*`,
  `anthropic-priority-*-tokens-*` (Priority Tier only), and `anthropic-fast-*` (fast mode).
  Each describes a different bucket than the one an ordinary request draws from.
- Only uncached input tokens count toward the ITPM limit on most models, so a cached prefix
  raises effective throughput without raising the limit. AnyInfer does not model this: it
  paces on what the headers report, which already reflects it.

## Watchlist
- Rate-limit header names and the RFC 3339 reset format; whether the `tokens` pair keeps
  its "most restrictive limit in effect" meaning
- `anthropic-version` header updates / new required beta headers
- `oauth-2025-04-20` beta flag: whether it graduates to GA (making it droppable) or is
  superseded, and whether the endpoint set it gates widens beyond `/v1/messages`
- Native structured-output mechanism (we plan tool-based emulation — open question 7;
  verify whether a first-class json_schema output mode now exists)
- Reasoning/effort wire form (see Request fields caveat)
- New usage fields; models-list pagination shape
