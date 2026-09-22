# openai-compat — Protocol Contract

Status: M0 adapter — **implemented**. Base dialect; subclassed by openrouter, azure-foundry, llama-cpp.
Last verified: 2026-09-21 — live drift check. `platform.openai.com/docs/api-reference/{chat,models}` are bot-walled
(403, confirmed again this run); verified instead against the `developers.openai.com` mirrors, the same
substitution already established for the embeddings section below.

## Upstream sources
- https://platform.openai.com/docs/api-reference/chat (the de-facto dialect spec; 403 bot-walled as of 2026-09-21,
  mirrored below)
- https://platform.openai.com/docs/api-reference/models (403 bot-walled as of 2026-09-21, mirrored below)
- https://developers.openai.com/api/docs/api-reference/chat (working mirror, fetched 2026-09-21)
- https://developers.openai.com/api/docs/api-reference/models (working mirror, fetched 2026-09-21)
- https://developers.openai.com/api/docs/guides/images-vision
- https://developers.openai.com/api/docs/guides/file-inputs
- https://developers.openai.com/api/docs/changelog (fetched 2026-09-21, covers Aug–Sep 2026 entries)

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
  parameter name), `stop`, `seed`, `presence_penalty`, `frequency_penalty`,
  `tools`, `tool_choice`,
  `response_format: {"type":"json_schema","json_schema":{...}}` or `{"type":"json_object"}`
- `logprobs: true` plus optional `top_logprobs: <int>` (added 2026-08-25). The pair is
  load-bearing: `top_logprobs` alone is rejected upstream, and `logprobs: true` alone
  returns the chosen token's own probability with no alternatives — which is why the
  normalized single count spells zero as the boolean with no companion.
- `stream_options.include_obfuscation: <bool>` (verified 2026-09-21, mirror OpenAPI spec):
  a per-chunk `obfuscation` padding field defends against side-channel timing attacks and
  is on by default; not currently read or exposed by the adapter — declare it in
  `ignored_parameters` rather than silently dropping a caller's request to disable it.
- `prompt_cache_key` (string, verified 2026-09-21): documented as the successor to `user`
  for cache-affinity hinting. Not currently sent; adapters that want cache-aware routing
  parity with the Responses dialect (see openai.md) would need this field wired up.

### Multimodal inputs
Verified 2026-08-10 for the OpenAI Chat Completions dialect. Message content arrays carry
`text`, `image_url`, `file`, and `input_audio` items; inline image and file bytes are data
URLs and inline audio is base64 in its content object. Compatibility servers vary, so this
is a projection contract rather than a capability claim: presets must discover, catalog,
or document support, and an upstream rejection remains explicit.
### Response fields
- `choices[0].message.content`, `choices[0].message.tool_calls[]`,
  `choices[0].finish_reason` (`stop|length|tool_calls|content_filter`),
  `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`
- **Read (verified 2026-09-21, mirror OpenAPI spec):** `usage.prompt_tokens_details.cached_tokens` and
  `usage.completion_tokens_details.reasoning_tokens` land in `Usage.cache_read_tokens` and
  `Usage.reasoning_tokens`, and `capabilities/pricing.py` reprices the cached share against
  `cache_read_per_1m` wherever an entry carries one. `cached_tokens` is counted inside
  `prompt_tokens`, the same accounting shape as the Responses dialect's implicit caching (openai.md).
- **Not read (verified 2026-09-21, mirror OpenAPI spec):** `usage.prompt_tokens_details.audio_tokens`
  and `usage.completion_tokens_details.{audio_tokens,accepted_prediction_tokens,rejected_prediction_tokens}`
  exist on the wire for this dialect (mirrors the Azure chat-completions surface confirmed the same run — see
  azure-foundry.md) — proposed adapter work item, not applied here.
- `choices[0].logprobs.content[]` — entries of
  `{token, logprob, bytes[], top_logprobs[{token, logprob, bytes[]}]}`. Read defensively:
  a malformed entry is skipped rather than failing a generation that otherwise succeeded,
  since log-probabilities are advisory output.
### Streaming
- SSE; `data: {json}` chunks; `choices[0].delta.content` text deltas;
  `choices[0].delta.tool_calls[]` indexed argument fragments; terminator `data: [DONE]`;
  final usage chunk when `stream_options.include_usage` set
- `choices[0].logprobs` appears **per chunk**, covering only that chunk's tokens, so the
  adapter accumulates across chunks rather than replacing.
### Errors
- Non-2xx with `{"error": {"message", "type", "code"}}`; retryable statuses
  {408, 409, 425, 429} ∪ ≥500; `Retry-After` header honored
- NEW-CAPABILITY (changelog, 2026-09-02): traffic-shedding now distinguishes a `429` with
  `code: "slow_down"` (rapid traffic increase) from a `503` with `code: "server_is_overloaded"`
  (temporary model unavailability). Both already fall inside the retryable-status set above, so
  this is not a break — but the `code` value would let error mapping distinguish the two causes
  if that granularity is ever wanted.

## Watchlist
- Servers vary on `response_format` json_schema support (capability probe territory)
- Compatibility servers vary widely on `logprobs`, `seed`, and the two penalties: several
  presets already declare them in `ignored_parameters`. As with `response_format`, this
  snapshot records the *dialect*, not a capability claim for every implementer of it.
- `max_tokens` vs `max_completion_tokens` divergence across implementations
- `stream_options.include_usage` not universally implemented (fallback: usage absent)
- Model catalog churn on the first-party API (e.g. `gpt-6-astra`, released 2026-09-03, refuses
  custom `temperature`/`top_p` on Chat Completions) is a per-model capability constraint, not a
  dialect change — left to the capability catalog, not recorded here.
