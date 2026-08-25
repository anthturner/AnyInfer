# anthropic — Protocol Contract

Status: M2 adapter — **implemented** (Messages API).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://docs.anthropic.com/en/api/messages
- https://docs.anthropic.com/en/api/models-list
- https://docs.anthropic.com/en/api/versioning
- https://docs.anthropic.com/en/release-notes/api
- https://platform.claude.com/docs/en/build-with-claude/vision
- https://platform.claude.com/docs/en/build-with-claude/pdf-support

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
- **Server-side tools** (added 2026-08-25) are `tools[]` entries whose `type` carries a
  **date**: `web_search_20250305` and `code_execution_20250522`, each with a `name` and an
  optional `max_uses`. The date is part of the wire type, so a version bump upstream is a
  contract change here rather than a silent behaviour change. Results stream as
  `server_tool_use` blocks (invocation) and `web_search_tool_result` /
  `code_execution_tool_result` blocks (outcome); a failure is a nested
  `web_search_tool_result_error`. Only invocation *counts* are surfaced — the queries and
  results are caller-adjacent content.
- Citations (added 2026-08-25) are a **per-document request-side opt-in**:
  `content[].citations: {"enabled": true}` on a `document` block. Without it the model
  answers without attributions, and Anthropic bills a cited answer differently, so it is
  sent only when the caller asked.
- **Absent from this protocol** (re-checked 2026-08-25): `seed`, `presence_penalty`,
  `frequency_penalty`, and any log-probability field. The Messages API publishes none of
  them, so the descriptor declares all four in `ignored_parameters` — a caller who sets
  one is told, rather than getting a successful answer that ignored it.

### Multimodal inputs
Verified 2026-08-10 against the provider-owned vision and PDF guides. Images use `image`
content blocks and documents use `document` blocks. Their `source` is either `base64` with
`media_type` and `data`, or `url` with `url`. Audio content is not projected by this
Messages adapter and is refused before transport.
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

### Citation response shape

- Streamed as `content_block_delta` with `delta.type: "citations_delta"` and
  `delta.citation`. Location shapes differ by document kind (`char_location`,
  `page_location`, `content_block_location`) and all count into the **cited document**,
  never into the answer — but each delta arrives immediately after the text it supports,
  so the answer span is recoverable from stream position. The adapter derives it that way;
  reporting `start_char_index` as an answer offset would be a different claim entirely.
- Fields read: `cited_text`, `document_index`, `document_title`.

### Message Batches (added 2026-08-25)

- `POST /v1/messages/batches` takes `{requests: [{custom_id, params}]}` where `params` is
  exactly a Messages body **minus `stream`**, which a batch cannot use and the API rejects.
  No file upload and no separate manifest endpoint, unlike OpenAI's Batch API.
- `GET /v1/messages/batches/{id}` reports `processing_status` — only `in_progress`,
  `canceling`, and `ended` — plus `request_counts` with `succeeded`/`errored`/`expired`/
  `processing`. Per-line outcomes are **not** in the batch status, which is why `ended`
  normalizes to `completed` even when every line errored.
- A cancelled batch is `ended` with `cancel_initiated_at` set; that pairing is what
  distinguishes it from a natural completion.
- `POST /v1/messages/batches/{id}/cancel` requests cancellation.
- Results are a JSONL manifest at the batch's own `results_url`, one entry per line:
  `{custom_id, result: {type: "succeeded"|"errored"|"expired"|"canceled", message?, error?}}`.
  A succeeded entry's `message` is byte-identical to a non-streaming response, so the
  adapter replays it through the same event translator a live call uses rather than
  parsing it a second way.
- **Manifest order is completion order, not submission order.** The core re-sorts.

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
