# nebius — Protocol Contract

Status: **implemented** — dedicated `openai-compat` subclass.
Last verified: 2026-08-08 — official Token Factory documentation and the live official
OpenAPI schema (`20260723-111246028`). No credentialed inference request was made.

## Upstream sources

- https://docs.tokenfactory.nebius.com/quickstart
- https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion
- https://docs.tokenfactory.nebius.com/api-reference/models/list-models
- https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models
- https://docs.tokenfactory.nebius.com/ai-models-inference/json
- https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling
- https://api.tokenfactory.nebius.com/docs
- https://nebius.com/token-factory/prices

## Wire contract

### Endpoints

- `POST https://api.tokenfactory.nebius.com/v1/chat/completions` — generation.
- `GET https://api.tokenfactory.nebius.com/v1/models?verbose=true` — discovery with rich
  metadata. On 400, 404, or 422, the adapter retries `GET /v1/models` without `verbose` and
  returns ids only.

### Auth

- `Authorization: Bearer <api_key>`.

### Version pins

- No API version parameter or version header.
- OpenAPI build `20260723-111246028` was the schema inspected for this verification.

### Request fields

- Shared chat-completions fields from `contracts/openai-compat.md`.
- `reasoning_effort` receives the normalized `minimal`, `low`, `medium`, or `high` value
  unchanged. The upstream schema also accepts `none`, `xhigh`, and `max`; callers can send
  those through `provider_options`.
- Structured output uses `response_format`; tool calling uses `tools` and `tool_choice`.

### Response fields

- Shared chat-completions text, tool-call, finish-reason, and usage fields.
- Reasoning text is read from `reasoning_content`, with `reasoning` accepted as the documented
  alias, and emitted as `ReasoningDelta` rather than answer text.
- Rich model discovery reads `id`, `context_length`, `quantization`, `supported_features`, and
  the `pricing.prompt` and `pricing.completion` decimal strings. Prices are per token and are
  scaled to AnyInfer's per-million-token representation.

### Streaming

- OpenAI-style SSE chat-completion chunks and `[DONE]` termination.
- Visible answer fragments arrive in `choices[0].delta.content`; reasoning fragments arrive in
  `choices[0].delta.reasoning_content` or `choices[0].delta.reasoning`.

### Errors

- Shared OpenAI-compatible status and error-shape classification.
- A 400, 404, or 422 only triggers fallback when requesting the optional verbose model list;
  authentication, rate-limit, and server failures remain typed failures.

## Watchlist

- The rich model schema, especially pricing units and `supported_features` names.
- The two reasoning response field names and the seven-value reasoning-effort ladder.
- Model flavor ids such as the `-fast` suffix; they are distinct ids with distinct prices.
- Regional API hosts. The adapter defaults only to the host in the official quickstart.
