# azure-foundry — Protocol Contract (Azure AI Foundry)

Status: M2 adapter — **implemented** (openai-compat subclass); embeddings implemented
2026-08-12 (`OpenAICompatEmbeddingsMixin` composed onto the same dialect).
Last verified: 2026-09-21 — live drift check; generation section directly re-verified against
Microsoft's own chat reference (see below), not just carried over from the 2026-08-05 survey.

## Upstream sources
- https://learn.microsoft.com/en-us/azure/ai-foundry/openai/reference — still reachable
  (200), but its content has narrowed: as of this run it documents only the image-generation
  and audio (transcription/translation) REST operations, and explicitly redirects readers
  elsewhere for chat completions/embeddings/etc. Not a useful source for the Wire contract
  section below anymore; kept for the audio/image operations it still covers.
- https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/chat — **added
  2026-09-21**: the actual current chat-completions reference the `/reference` page now
  points to; used to re-verify the Request/Response fields below.
- https://learn.microsoft.com/en-us/azure/ai-foundry/openai/api-version-lifecycle
- https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/embeddings (embeddings,
  fetched 2026-08-12, re-fetched 2026-09-21, unchanged)
- **Documentation rebrand noted 2026-09-21:** Microsoft is restructuring these docs under a
  `Microsoft Foundry` canonical path (`/azure/foundry/openai/...`) rather than
  `/azure/ai-foundry/openai/...`; the `ai-foundry` URLs above still resolve today (200, not a
  dead link), so this is not urgent, but expect the canonical path to change in a future
  rotation.

## Wire contract
### Endpoints
- `POST {base_url}/chat/completions` — base_url is resource-specific, e.g.
  `https://<resource>.services.ai.azure.com/openai/v1`; `api-version` query param when the
  deployment requires it
- **OK, reconfirmed 2026-09-21** (rest/api/microsoft-foundry/azureopenai/chat): Microsoft's own
  quickstart examples primarily show the `https://<resource>.openai.azure.com/openai/v1/` form
  of `base_url`, and the api-version-lifecycle guide states explicitly that **both**
  `<resource>.openai.azure.com` and `<resource>.services.ai.azure.com` are accepted for the v1
  surface. This snapshot previously documented only the `.services.ai.azure.com` form — add the
  `.openai.azure.com` form as equally valid, not a replacement.
- **CONFIRMED (resolves prior Watchlist item):** the version-less `/openai/v1` surface is now
  **GA**, not merely preview (api-version-lifecycle page, table row `Data plane | v1 preview |
  v1`). Its own `api-version` query param, when passed, only takes the enum `v1` or `preview`
  (default `v1`) — no longer the monthly `YYYY-MM-DD` dated versions from the older
  deployment-scoped surface.
- `POST {base_url}/embeddings` — same v1, deployment-less surface as chat; `model` is the
  deployment name, exactly as `openai_compat_embeddings.py`'s body shape (verified
  2026-08-12, re-fetched 2026-09-21, unchanged).  `api-version` appended the same way as chat
  when the deployment requires the older query-pinned surface.
- `GET {base_url}/models` — deployment discovery
### Auth
- Entra: `Authorization: Bearer <token>` via `azure-identity`
  (`DefaultAzureCredential`; interactive-broker variant supported); Foundry token scope as
  recorded in `credentials/entra.py`; static `api-key` header supported as
  alternative
- OK, reconfirmed 2026-09-21: the chat reference's security schemes are exactly these two,
  plus an OAuth2 implicit flow scoped to `https://cognitiveservices.azure.com/.default` —
  consistent with (not additional to) what `credentials/entra.py` already implements.
### Version pins
- `api-version` per deployment (configured, not hardcoded); recorded per-app
### Request fields
- openai-compat dialect with overrides: output-token parameter is
  **`max_completion_tokens`** (not `max_tokens`) — **OK, reconfirmed 2026-09-21** directly
  against the chat reference's request-body table.
  Reasoning effort as `reasoning_effort` for o-series/gpt-5-family deployments — **OK,
  reconfirmed 2026-09-21**; the accepted enum is now `none, minimal, low, medium, high, xhigh`
  (`xhigh` is new, documented as supported for models after `gpt-5.1-codex-max`; not previously
  recorded here).
- NEW-CAPABILITY (chat reference, 2026-09-21): the same request-body additions noted in
  openai-compat.md are present on this dialect too — `prompt_cache_key`/`prompt_cache_retention`
  (successors to `user`), `parallel_tool_calls`, `safety_identifier`, `store`, `modalities`, and
  `prediction`. None are currently sent by the adapter.
- Embeddings: identical body to `openai_compat_embeddings.py` (`model`, `input`,
  optional `dimensions`, optional `encoding_format`); no Azure-specific fields observed.
### Response fields
- As openai-compat
- NEW-CAPABILITY (chat reference, 2026-09-21): `usage.completion_tokens_details.{audio_tokens,
  accepted_prediction_tokens,rejected_prediction_tokens}` and message-level
  `annotations[].url_citation` (for web-search results) are present on the wire and not currently
  read — same gap as openai-compat.md. `usage.prompt_tokens_details.cached_tokens` and
  `usage.completion_tokens_details.reasoning_tokens` are read here too: `AzureFoundryAdapter`
  inherits `OpenAICompatAdapter._parse_usage` and does not override it.
- Embeddings: as `openai_compat_embeddings.py` (`data[].{index,embedding}`, `model`,
  `usage.{prompt_tokens,total_tokens}`)
### Streaming
- SSE as openai-compat
### Errors
- As openai-compat, plus Entra token acquisition failures → AuthError (hint: az login /
  credential chain); 401/403 distinguish authentication vs authorization
- Embeddings 404 specifically means the endpoint is missing `/openai/v1/` or `model` is
  not a valid deployment name (documented troubleshooting entry, reconfirmed 2026-09-21)

### Embedding limits (verified 2026-08-12, re-fetched 2026-09-21 — unchanged,
learn.microsoft.com/azure/ai-foundry/openai/how-to/embeddings)
- Max 2,048 inputs per request (same ceiling as OpenAI itself)
- Max 8,192 tokens per individual input
- Max 300,000 tokens aggregate across all inputs in one request (HTTP 400 above this,
  even if every individual input is under its own limit)
- **Not statically declared** in `static_embedding_capabilities`: `model` is a
  tenant-chosen deployment name, not a fixed catalog id, so these limits cannot be keyed
  reliably per model the way OpenAI's fixed model ids allow.

### When the token is acquired (corrected 2026-08-26)

Per request, on first use, cached until five minutes before its reported expiry — not at
construction. `DefaultAzureCredential` walks a chain that spawns `az`, `pwsh`, and `azd`
and probes the IMDS endpoint over HTTP, so acquiring at construction made building a
client shell out and block on network timeouts before the caller had asked for anything,
and pinned a single token for the life of the process — which an Entra token outlives by
about an hour. The chain is blocking, so it runs in a worker thread rather than on the
event loop shared with in-flight requests.

## Watchlist
- `api-version` lifecycle/retirements — **the version-less `/openai/v1` surface is now
  confirmed GA** (2026-09-21), no longer just watched as "newer"; retire this line once the
  contract prose above is treated as settled rather than provisional
- The documentation rebrand from `azure/ai-foundry/openai/*` to `azure/foundry/openai/*` noted
  above — watch for the old paths going from 200 to a redirect or 404
- Scope strings and credential-chain behavior in `azure-identity` major versions
- Divergences from vanilla openai-compat (parameter renames, content filter annotations
  in responses)
- Whether Azure ever exposes a listing endpoint that tags which deployments are
  embedding-capable (would let discovery stamp `operations` per-model, as LM Studio does)
- **The refresh margin is not verified against a live tenant.** Expiry is read from
  `AccessToken.expires_on`, and a credential that reports none refreshes on every
  request rather than caching a token it cannot date. Noted 2026-08-26.
