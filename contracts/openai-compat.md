# openai-compat — Protocol Contract

Status: M0 adapter — **implemented**. Base dialect; subclassed by openrouter, azure-foundry, llama-cpp.
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://platform.openai.com/docs/api-reference/chat (the de-facto dialect spec)
- https://platform.openai.com/docs/api-reference/models

## Wire contract
### Endpoints
- `POST {base_url}/chat/completions` — generation (default base `https://api.openai.com/v1`)
- `GET {base_url}/models` — discovery
### Auth
- `Authorization: Bearer <api_key>` (optional for keyless local servers)
### Version pins
- None; dialect assumed stable at the chat-completions surface
### Request fields
- `model`, `messages[{role, content}]`, `stream`, `stream_options.include_usage: true`,
  `temperature`, `top_p`, `max_tokens` (subclasses may override the output-token
  parameter name), `stop`, `tools`, `tool_choice`,
  `response_format: {"type":"json_schema","json_schema":{...}}` or `{"type":"json_object"}`
### Response fields
- `choices[0].message.content`, `choices[0].message.tool_calls[]`,
  `choices[0].finish_reason` (`stop|length|tool_calls|content_filter`),
  `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`
### Streaming
- SSE; `data: {json}` chunks; `choices[0].delta.content` text deltas;
  `choices[0].delta.tool_calls[]` indexed argument fragments; terminator `data: [DONE]`;
  final usage chunk when `stream_options.include_usage` set
### Errors
- Non-2xx with `{"error": {"message", "type", "code"}}`; retryable statuses
  {408, 409, 425, 429} ∪ ≥500; `Retry-After` header honored

## Watchlist
- Servers vary on `response_format` json_schema support (capability probe territory)
- `max_tokens` vs `max_completion_tokens` divergence across implementations
- `stream_options.include_usage` not universally implemented (fallback: usage absent)
