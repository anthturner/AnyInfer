# openai — Protocol Contract

Status: M2 adapter — **implemented** (Responses API).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://platform.openai.com/docs/api-reference/responses
- https://platform.openai.com/docs/api-reference/models
- https://platform.openai.com/docs/changelog

## Wire contract
### Endpoints
- `POST https://api.openai.com/v1/responses` — generation (Responses API, NOT chat completions)
- `GET https://api.openai.com/v1/models` — discovery
### Auth
- `Authorization: Bearer <api_key>`
### Version pins
- None (Responses API is unversioned-by-header at snapshot time)
### Request fields
- `model`, `input` (message list), `instructions` (system), `stream`,
  `max_output_tokens`, `temperature`, `top_p`,
  `reasoning: {"effort": <minimal|low|medium|high>}` (normalized effort translated here),
  `text.format` for structured output (json_schema), `tools`
### Prompt caching (placement)
- Mechanism: **implicit**. Caching is applied automatically to a sufficiently long, stable
  prompt prefix; there is no field to send and AnyInfer sends none. The core's only duty is
  to leave the prefix undisturbed, and to warn a caller whose own prompt changes its prefix
  between turns.
- Declared on the descriptor as `cache_mechanism="implicit"`, with no mark budget.
- Cache hits are reported in the usage block (see Response fields) and are counted inside
  the reported prompt-token total on this API — which is why cache-aware pricing reprices
  rather than adds. **VERIFY on the next drift run**: both the automatic-caching threshold
  and whether cached tokens remain included in `prompt_tokens`.

### Response fields
- `output_text` aggregate; `output[]` items (message / reasoning / tool call),
  `status`, `usage.input_tokens`, `usage.output_tokens`, `usage.total_tokens`,
  `usage.output_tokens_details.reasoning_tokens`
### Streaming
- SSE typed events; text via `response.output_text.delta`; completion via
  `response.completed` (carries final usage); tool-call and reasoning events per event type
### Errors
- Non-2xx `{"error": {...}}`; retryable statuses {408, 409, 425, 429} ∪ ≥500; `Retry-After`

## Watchlist
- Responses API evolves quickly: new event types, `text.format` schema-mode changes
- Chat-completions deprecation posture for first-party API
- Model catalog churn (gpt-5 family) affecting bundled capability catalog + pricing
