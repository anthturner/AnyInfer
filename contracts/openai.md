# openai — Protocol Contract

Status: M2 adapter — **implemented** (Responses API).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://platform.openai.com/docs/api-reference/responses
- https://platform.openai.com/docs/api-reference/models
- https://platform.openai.com/docs/changelog
- https://developers.openai.com/api/docs/guides/images-vision
- https://developers.openai.com/api/docs/guides/file-inputs

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
  `max_output_tokens`, `temperature`, `top_p`, `top_logprobs`,
  `reasoning: {"effort": <none|minimal|low|medium|high>}` (normalized effort translated here),
  `text.format` for structured output (json_schema), `tools`
- **Server-side tools** (added 2026-08-25) are bare marker objects in `tools[]`:
  `{"type": "web_search"}` and `{"type": "code_interpreter", "container": {"type": "auto"}}`.
  Neither takes a per-tool use ceiling, so `server_tools.max_uses` is declared in
  `ignored_parameters`. Lifecycle arrives as typed stream events —
  `response.web_search_call.in_progress`/`.completed` and the `code_interpreter_call`
  pair. The intermediate `.searching`/`.interpreting` events are deliberately not mapped:
  they say the same thing with more granularity than a normalized status carries, and
  counting them would inflate the invocation count.
- **Absent from this dialect** (verified 2026-08-25): `seed`, `presence_penalty`, and
  `frequency_penalty` exist on chat-completions but not on Responses, so the adapter never
  sends them and the descriptor declares all three in `ignored_parameters`.
- `top_logprobs` is a bare count here — there is no companion boolean, and `0` is a valid
  value meaning "the chosen token's own probability, no alternatives".

### Multimodal inputs
Verified 2026-08-10 against the provider-owned image and file-input guides above.
- Image input is an `input_image` content item with `image_url` set to an HTTPS URL or a
  `data:<media-type>;base64,...` URL; `detail` is preserved when supplied.
- Inline documents are `input_file` items with `filename` and a data URL in `file_data`;
  remote documents use `file_url`.
- Audio is projected as an `input_audio` item only for models that accept audio input.
  Capability remains model-specific; the adapter does not claim all OpenAI models accept it.
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
### Rate-limit headers
Verified 2026-08-09 against https://developers.openai.com/api/docs/guides/rate-limits (the
`platform.openai.com` guide URL now 301s there).
- Read by the descriptor's dialect: `x-ratelimit-remaining-requests`,
  `x-ratelimit-reset-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-tokens`,
  `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`.
- Reset values are **durations** in Go's compound form — `1s`, `6m0s` — not instants and
  not bare seconds.
- Not read: `x-ratelimit-*-project-tokens`. The project-scoped bucket is a different
  allowance than the one a single client's requests draw from, and pacing against it would
  hold back requests the key itself could still make.
- 429 responses also carry `Retry-After`, which the router already honours on the way down.

### Embeddings request fields (`POST /v1/embeddings`, verified 2026-08-12)
- Verified against `developers.openai.com/api/reference/resources/embeddings/methods/create`
  (the `platform.openai.com` mirror was bot-blocked on the verification date and is noted
  as such rather than assumed).
- `model` (required; `text-embedding-3-small`/`text-embedding-3-large`/
  `text-embedding-ada-002`), `input` (string or array; **at most 2,048 array entries**,
  **8,192 tokens per input**, and **300,000 tokens summed per request**),
  `encoding_format` (`float`/`base64`), `dimensions` (text-embedding-3 and later only),
  `user`.
- **There is no input-intent field anywhere in the request schema** — the adapter's
  static capabilities declare an empty intent set, so a caller's `input_type` produces
  the ignored-intent warning rather than silently doing nothing.
- The adapter sends `model`, `input` (scalar collapses to a bare string), and
  `dimensions` when requested, via the shared OpenAI-compatible embeddings dialect
  (`providers/openai_compat_embeddings.py`, float and base64 decoding both verified in
  its own tests).

### Embeddings response fields (`POST /v1/embeddings`, verified 2026-08-12)
- `object: "list"`, `data[]` with `embedding`/`index`/`object: "embedding"`, `model`,
  `usage` with `prompt_tokens`/`total_tokens`.
- **Unverified:** default output dimensions per model — the current reference and model
  pages do not state them, so `EmbeddingCapabilities.dimensions` stays `None` rather
  than carrying a remembered number. Embedding pricing appears on the model pages
  ($0.02/1M for 3-small, $0.13/1M for 3-large, 2026-08-12) but enters `pricing.json`
  only through the pricing pipeline, never by hand.

## Watchlist
- Rate-limit header names and the duration format of the reset values
- Responses API evolves quickly: new event types, `text.format` schema-mode changes
- Chat-completions deprecation posture for first-party API
- Model catalog churn (gpt-5 family) affecting bundled capability catalog + pricing
- Embeddings: the 2,048-input / 8,192-token / 300k-summed-token limits, and whether the
  reference starts stating per-model default dimensions (unverified today)
