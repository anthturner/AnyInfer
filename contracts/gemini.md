# gemini — Protocol Contract

Status: **implemented** — `providers/gemini.py`, native `generateContent` protocol.
Last verified: 2026-08-07 — against the live Gemini API documentation (sources below).

## Upstream sources
- https://ai.google.dev/api/generate-content
- https://ai.google.dev/api/models
- https://ai.google.dev/gemini-api/docs/thinking
- https://ai.google.dev/gemini-api/docs/function-calling
- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/api-errors
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/openai (compatibility layer — deliberately unused)
- https://ai.google.dev/gemini-api/docs/generate-content/file-input-methods

## Why native, not the OpenAI-compatibility layer

`https://generativelanguage.googleapis.com/v1beta/openai/` exists and is documented as
beta. It **silently ignores** OpenAI parameters it does not implement — the failure mode
AnyInfer exists to eliminate — and Gemini-specific features (thinking config, safety
settings, cached content, grounding tools) are only reachable through `extra_body`. The
native protocol is used instead.

## Wire contract

### Endpoints
- `POST {base}/models/{model}:generateContent` — unary generation
- `POST {base}/models/{model}:streamGenerateContent?alt=sse` — streaming. Without
  `alt=sse` the API returns a JSON *array* of chunks rather than an SSE stream; the
  adapter always sends `alt=sse`.
- `GET {base}/models?pageSize=&pageToken=` — discovery, cursor-paginated
  (`nextPageToken` absent on the last page). Default base is
  `https://generativelanguage.googleapis.com/v1beta`.

### Auth
- `x-goog-api-key: <api_key>`. No `Authorization` header is sent.

### Version pins
- The API version is part of the base URL (`/v1beta`); overriding `base_url` selects it.

### Request fields sent
- `contents[]`: `{role: "user"|"model", parts: [Part]}`. Assistant turns are spelled
  `model`; **tool results ride on a `user` turn**, not a dedicated role.
- `Part` shapes emitted: `{text}`, `{functionCall: {name, args, id?}}`,
  `{functionResponse: {name, response}}`, `{inlineData: {mimeType, data}}`, and
  `{fileData: {mimeType, fileUri}}`.
- Video (added 2026-08-25) reuses the same two source shapes — `inlineData` for a short
  inline clip, `fileData` for a Files-API URI or a public video URL — with an optional
  **sibling** `videoMetadata: {startOffset?, endOffset?, fps?}` on the same Part. Offsets
  are protobuf durations (a decimal string ending in `s`), which is the one place this
  dialect departs from plain JSON numbers; `fps` is a plain number. All three are omitted
  when the caller set none, so provider defaults are never restated as caller choices. The media shapes were verified 2026-08-10 against
  the provider-owned file-input guide. A synthesized `call_N` id is *not* echoed back
  as a `functionCall.id` — it is ours, not a key Gemini issued.
- `functionResponse.response` must be an object: a non-JSON tool result is wrapped as
  `{"output": ...}`, or `{"error": ...}` when the result is error-flagged.
- `systemInstruction: {parts: [{text}]}` — system messages are a top-level field.
- `generationConfig`: `temperature`, `topP`, `maxOutputTokens`, `stopSequences`,
  `seed`, `presencePenalty`, `frequencyPenalty`, `responseMimeType`, `responseSchema`,
  `thinkingConfig`. Unset sampling fields are omitted entirely.
- `generationConfig.responseLogprobs: true` plus optional `generationConfig.logprobs:
  <int>` (added 2026-08-25). The count is the number of *alternatives* per position;
  Gemini rejects `logprobs: 0`, so a request for the chosen token alone sends the boolean
  without the count.
- `tools[0].functionDeclarations[]`: `{name, description, parameters}` with parameters
  projected to the accepted schema subset.
- `toolConfig.functionCallingConfig`: `{mode: "NONE"|"ANY", allowedFunctionNames?}`.
  `auto` sends no `toolConfig` at all (the API default).
- `provider_options["gemini"]` is merged into the request body verbatim, which is how
  `cachedContent`, `safetySettings`, and grounding tools are reached.

### Structured output
- `responseMimeType: "application/json"` plus `responseSchema` (mechanism `json_schema`),
  or `responseMimeType` alone (mechanism `json_mode`).
- `responseSchema` accepts an **OpenAPI-subset** schema. The adapter's `project_schema`
  keeps only: `type`, `format`, `description`, `nullable`, `enum`, `properties`,
  `required`, `items`, `minItems`, `maxItems`, `minimum`, `maximum`, `propertyOrdering`,
  `anyOf`, `prefixItems`, `additionalProperties`, `title`, `default`. Anything else
  (`$schema`, `pattern`, `unevaluatedProperties`, …) is **dropped**, because an unknown
  keyword fails the whole request. The core still validates responses against the
  caller's canonical schema.

### Reasoning
- `generationConfig.thinkingConfig.thinkingLevel` ∈ `minimal|low|medium|high`; those four
  normalized effort levels map straight across. Normalized `none` has no `thinkingLevel`
  spelling and is sent as `thinkingConfig.thinkingBudget: 0` instead. Models that cannot
  disable thinking clamp server-side.
- Thoughts arrive as parts flagged `thought: true` → `ReasoningDelta`, excluded from the
  answer text. Parts may carry `thoughtSignature`, which callers should echo back
  verbatim in multi-turn conversations.
- Older 2.5-era numeric `thinkingBudget` / `includeThoughts` fields still exist; reach
  them through `provider_options` if a specific budget is required.

### Response fields read
- `candidates[0].content.parts[]` — `text` (with `thought` flag), `functionCall`.
- `candidates[0].logprobsResult` — `chosenCandidates[{token, logProbability}]` and
  `topCandidates[{candidates[{token, logProbability}]}]`. Google splits what other
  dialects nest: the two arrays are **parallel by position**, so recovering one token with
  its alternatives means zipping them. `topCandidates` is absent entirely unless the
  request asked for a positive alternatives count.
- `candidates[0].finishReason` — `STOP`→stop, `MAX_TOKENS`→length,
  `SAFETY`/`RECITATION`/`BLOCKLIST`/`PROHIBITED_CONTENT`/`SPII`/`IMAGE_SAFETY`/
  `BLOCKED_SAFETY`/`LANGUAGE`→content_filter, `MALFORMED_FUNCTION_CALL`/
  `FINISH_REASON_UNSPECIFIED`/`OTHER`→other. The enum is open; unrecognized values
  normalize to `other`.
- `promptFeedback.blockReason` — a blocked prompt returns **no candidates at all**, so
  this is what distinguishes a refusal from an empty stop.
- `usageMetadata`: `promptTokenCount`, `candidatesTokenCount`, `thoughtsTokenCount`,
  `cachedContentTokenCount`, `totalTokenCount`.
  **`candidatesTokenCount` excludes thoughts**, and thinking bills at the output rate,
  so normalized `output_tokens = candidatesTokenCount + thoughtsTokenCount`;
  `thoughtsTokenCount` is also surfaced as `reasoning_tokens`.

### Streaming
- SSE `data: <GenerateContentResponse>` per chunk, each a full response object with
  incremental parts. **No `[DONE]` sentinel** — the stream ends when the response closes.
- `usageMetadata` is cumulative and arrives on later chunks; the core's usage merge
  handles it.

### Errors
- Current documentation shows `{"error": {"code", "message"}}`; the classic surface also
  returns `{"error": {"code": int, "message", "status": "RESOURCE_EXHAUSTED", details[]}}`.
  Both are read through the shared error-detail extractor.
- Status mapping is the shared HTTP classification: 401/403→AuthError, 404→
  ModelNotFoundError, 429→RateLimitError, ≥500→ProviderUnavailableError.
- Official retry guidance: retry only 429/408/5xx with exponential backoff and jitter;
  never retry 400/403 — which is what the default retry predicate already does.

### Embeddings (`POST /v1beta/models/{model}:batchEmbedContents`, verified 2026-08-12)
- Verified against `ai.google.dev/gemini-api/docs/embeddings` and `ai.google.dev/api/embeddings`.
- The adapter always uses the batch endpoint (single inputs included): `requests[]`
  entries each carry `model: "models/{id}"`, `content: {parts: [{text}]}`, optional
  `output_dimensionality` (top level, snake_case in the guide's own curl), and
  `taskType` — **only for models that document task types**. `gemini-embedding-2`
  explicitly does not ("use prompt instructions instead"), so the adapter never sends
  it there; `gemini-embedding-001` (legacy) accepts
  `RETRIEVAL_QUERY`/`RETRIEVAL_DOCUMENT`/`CLASSIFICATION`/`CLUSTERING`, mapped from the
  normalized intent vocabulary.
- Response: `embeddings[]` with `values[]` (floats, request order) and `usageMetadata`
  with `promptTokenCount` → `input_tokens`.
- Models and dimensions (verified 2026-08-12): both `gemini-embedding-2` (current,
  multimodal-capable) and `gemini-embedding-001` (legacy, text-only) default to
  **3,072** dimensions; 128-3,072 supported, 768/1536/3072 recommended — declared as
  `dimension_choices`.
- **Unverified:** any batch-size ceiling for `batchEmbedContents` (not stated —
  `max_batch_inputs` stays `None`, so over-ceiling requests refuse locally rather than
  split at a guessed size); whether returned vectors are unit-normalized at reduced
  dimensionalities.

## Watchlist

- **The new "Interactions" API.** Google's guides are migrating to
  `POST /v1beta/interactions?alt=sse` with typed step objects (`function_call`,
  `function_result`, `thought_summary`, `thought_signature`) and a
  `total_thought_tokens` usage field. `generateContent` remains fully documented and is
  not marked deprecated, but new features are being documented Interactions-first. This
  is the single most important drift signal for this adapter.
- `thinkingLevel` vs the older numeric `thinkingBudget` — field casing and accepted
  ranges were not simultaneously visible on the loadable reference pages; re-verify
  before hardcoding budgets.
- `finishReason` enum growth (newer values such as `FUNCTION_CALLING_MODE` and
  `THINKING` were surfaced but not double-confirmed) — handled defensively by
  normalizing unknown values to `other`.
- `generationConfig.responseJsonSchema` (standard JSON Schema, as opposed to the OpenAPI
  subset) exists on `FunctionDeclaration`; whether it is accepted on `generationConfig`
  could not be confirmed. If it is, the projection could be relaxed.
- Pricing tiers change by prompt length (>200k-token tier costs roughly double for Pro
  models) — the bundled pricing table records the standard tier only.
