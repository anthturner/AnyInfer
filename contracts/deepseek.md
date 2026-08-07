# deepseek — Protocol Contract

Status: **implemented** — `providers/deepseek.py`, an `openai-compat` subclass.
Last verified: 2026-08-07 — against the live DeepSeek API documentation (sources below).

## Upstream sources
- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/quick_start/pricing
- https://api-docs.deepseek.com/api/create-chat-completion
- https://api-docs.deepseek.com/api/list-models/
- https://api-docs.deepseek.com/guides/anthropic_api
- https://api-docs.deepseek.com/guides/thinking_mode/
- https://api-docs.deepseek.com/updates/

## Wire contract

### Endpoints
- `POST https://api.deepseek.com/chat/completions` — generation (`/v1` is an alias)
- `GET https://api.deepseek.com/models` — discovery
- `POST https://api.deepseek.com/anthropic/v1/messages` — an Anthropic-compatible
  Messages endpoint. AnyInfer reaches it by pointing the **anthropic** adapter's
  `base_url` there; no separate adapter exists or is needed.

### Auth
- `Authorization: Bearer <api_key>` on the OpenAI-compatible surface.
- `x-api-key: <api_key>` on the Anthropic-compatible surface.

### Version pins
- None.

### Request fields sent
- openai-compat dialect, plus the non-standard `thinking` object and `reasoning_effort`
  when a reasoning effort is requested.
- Normalized effort maps to DeepSeek's accepted values: `minimal`/`low` → `low`,
  `medium`/`high` → `high`. (`medium` and `xhigh` are rewritten to `high` upstream, so
  they are mapped here rather than sent and silently rewritten.) `max` is reachable
  through `provider_options`.
- Thinking is **on by default**; a normalized effort always sends
  `thinking={"type": "enabled"}`. Disabling it is a deliberate act:
  `provider_options={"deepseek": {"thinking": {"type": "disabled"}}}`.

### Silently-ignored parameters
- `temperature` and `top_p` are discarded while thinking is enabled — the default —
  so both are declared in `ignored_parameters` and surface as `ParameterDropped`.
- `frequency_penalty` and `presence_penalty` are documented as deprecated no-ops;
  AnyInfer does not model them, so no drop event is needed.

### Response fields read
- openai-compat shapes, plus **`reasoning_content`** beside `content`
  (`delta.reasoning_content` when streaming) → `ReasoningDelta`, excluded from the
  answer text.
- Usage adds `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens`
  (`prompt_tokens` = hit + miss). Hits are read as `cache_read_tokens`; caching is
  automatic with no opt-in and no cache-control parameters.
- `completion_tokens_details.reasoning_tokens` → `reasoning_tokens`; reasoning consumes
  completion tokens and bills at the output rate.

### Streaming
- SSE as openai-compat, with `reasoning_content` deltas arriving before `content`.

### Errors
- openai-compat shapes. One extra finish reason, `insufficient_system_resource`;
  unrecognized values already normalize to `other`.

## Model ids
- `GET /models` returns exactly `deepseek-v4-flash` and `deepseek-v4-pro`. The legacy
  `deepseek-chat` / `deepseek-reasoner` aliases were **discontinued 2026-07-24**.

## Watchlist
- `reasoning_effort` value support per model (`deepseek-v4-pro` was temporarily
  high/max only, with full support expected shortly after this snapshot).
- Cache-hit vs cache-miss pricing: the bundled pricing table records the standard
  (miss) rate only, so cost is a ceiling on cache-heavy workloads.
- The Responses-style `output_config={effort: ...}` surface, currently unused here.
- Model-id churn — the aliases discontinued in July 2026 are a precedent.
