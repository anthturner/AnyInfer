# xai — Protocol Contract

Status: **implemented** — `providers/xai.py`, an `openai-compat` subclass.
Last verified: 2026-08-07 — against the live xAI API documentation (sources below).

## Upstream sources
- https://docs.x.ai/docs/overview
- https://docs.x.ai/developers/pricing
- https://docs.x.ai/developers/models
- https://docs.x.ai/developers/models/grok-4.3
- https://docs.x.ai/developers/grok-4-5
- https://docs.x.ai/developers/model-capabilities/legacy/chat-completions
- https://docs.x.ai/developers/tools/web-search
- https://docs.x.ai/docs/api-reference
- https://docs.x.ai/developers/rest-api-reference/inference/models

## Wire contract

### Endpoints
- `POST https://api.x.ai/v1/chat/completions` — generation. **Documented as legacy**:
  xAI states new features arrive on the Responses API (`POST /v1/responses`) first.
- `GET https://api.x.ai/v1/language-models` — rich discovery: per-model context window
  and prices (USD cents per 100M tokens, including cached and search rates). Falls back
  to `GET /v1/models` on 404.
- `https://api.x.ai` also exposes an Anthropic-compatible Messages endpoint, reachable
  by pointing the **anthropic** adapter's `base_url` there.

### Auth
- `Authorization: Bearer <api_key>`.

### Version pins
- None.

### Request fields sent
- openai-compat dialect with **`max_completion_tokens`** rather than the deprecated
  `max_tokens`.
- `reasoning_effort` from normalized effort: `minimal` clamps to `low` (only some models
  accept `none`, and silently disabling reasoning would change the answer more than the
  caller asked). Normalized `none` is passed through as `none` rather than clamped — a
  model that rejects it should say so, not be sent more reasoning than was requested.
  `grok-4.20` ships as separate `-reasoning`/`-non-reasoning` variants instead of taking
  the parameter.

### Response fields read
- openai-compat shapes, plus **`usage.cost_in_usd_ticks`** (1 USD = 10^10 ticks): the
  exact billed amount, including server-side tool fees and tiered pricing. It is adopted
  as `usage.cost_usd`, outranking any table-computed estimate.
- Discovery reads `max_prompt_length`, `prompt_text_token_price`, and
  `completion_text_token_price`, yielding `discovered`-provenance pricing.

### Streaming
- SSE as openai-compat.

### Errors
- openai-compat shapes; shared status classification applies.

## Billing notes (not modelled per-token)
- Tiered pricing: prompts ≥200k tokens bill **all** tokens at the higher tier.
- Web Search $5 per 1,000 calls; Code Execution $5 per 1,000 invocations;
  usage-violation charge $0.05 per flagged request.
- Batch discounts are documented per model.
Because all of these are already reflected in `cost_in_usd_ticks`, the reported cost is
authoritative and the pricing table's entries are a preflight estimate only.

## Watchlist
- **The Responses API becoming primary.** Chat completions is explicitly legacy; server-
  side tools (web_search, x_search, code_execution, file_search, MCP) are Responses-only.
  This is the main drift signal for this adapter.
- The old Live Search `search_parameters` mechanism has disappeared from current docs in
  favor of a server-side tools array.
- Deferred completions (`GET /v1/chat/deferred-completion/{request_id}`) — unused here.
- Whether raw reasoning content is ever exposed (no `reasoning_content` documented).
