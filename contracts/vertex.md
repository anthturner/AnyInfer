# vertex — Protocol Contract

Status: **implemented** — `providers/vertex.py`, a `gemini` subclass.
Last verified: 2026-08-07 — against live Google Cloud documentation (sources below).

## Upstream sources
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/inference
- https://cloud.google.com/vertex-ai/generative-ai/pricing
- https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/generativeaionvertexai-claude-3-streaming
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/count-tokens
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/migrate/migrate-google-ai
- https://developers.google.com/identity/protocols/oauth2/service-account
- https://ai.google.dev/gemini-api/docs/thinking

## Relationship to the Gemini adapter

Vertex serves the same models over the **same `generateContent` protocol**. The
differences are entirely addressing and auth, so this subclasses `providers/gemini.py`
rather than restating its translation — see `contracts/gemini.md` for the wire shape,
which applies here unchanged.

## Wire contract

### Endpoints
- `POST {base}/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent`
- the same path with `:streamGenerateContent?alt=sse` for streaming

Base is `https://aiplatform.googleapis.com/v1` for the `global` location (the default),
and `https://{location}-aiplatform.googleapis.com/v1` for a regional one. Newer models
are served **only** from the global endpoint.

### Auth
`Authorization: Bearer <OAuth2 access token>`, applied **per request** because the token
expires. There is no API-key auth on the standard endpoint. Resolution order:

1. An explicit token supplied as `api_key` (for example from
   `gcloud auth print-access-token`), used verbatim and never refreshed — the caller owns
   its lifetime.
2. `google-auth`'s application default credentials, when installed.
3. A service-account JSON key, signed as a JWT and exchanged at
   `https://oauth2.googleapis.com/token` with grant type
   `urn:ietf:params:oauth:grant-type:jwt-bearer`.

Scope: `https://www.googleapis.com/auth/cloud-platform`. Tokens are cached until two
minutes before expiry.

### Version pins
- The API version is in the base URL (`/v1`).

### Request and response fields
As `contracts/gemini.md` — `contents` and `parts`, `systemInstruction`,
`generationConfig` (including `thinkingConfig`), `tools[].functionDeclarations`,
`usageMetadata`. The per-field schema pages were JS-rendered and could not be diffed field
by field this session; the method surface and types were confirmed.

### Request fields
- Identical to the Gemini native dialect — `VertexAdapter` subclasses `GeminiAdapter` and
  overrides endpoint construction and authentication only. See
  [gemini.md](gemini.md) for the authoritative field list.

### Response fields
- Identical to the Gemini native dialect; see [gemini.md](gemini.md).

### Streaming
- Identical to the Gemini native dialect (`streamGenerateContent` with SSE framing); see
  [gemini.md](gemini.md).

### Errors
- Google API error envelope shared with Gemini (`{"error": {"code", "message", "status"}}`),
  plus the OAuth failures specific to this surface: an expired or wrongly-scoped
  service-account token surfaces as 401/403 and maps to an auth error rather than a
  retryable one.

### Discovery
**Not offered.** Vertex exposes no listing endpoint comparable to the AI Studio one, so
`list_models()` returns empty rather than inventing a hardcoded table. Name models
explicitly in the target.

### Health
Reports whether a token can be acquired. No generation is spent.

## Watchlist
- **Claude on Vertex** uses `rawPredict`/`streamRawPredict` with the Anthropic Messages
  body and an `anthropic_version` field — a different surface this adapter does not cover.
  Reachable today by pointing the **anthropic** adapter's `base_url` at it.
- Regional and multi-region endpoints carry roughly a 10% pricing premium over global for
  Claude Sonnet 4.5 and newer; specific regional endpoints serve older models only.
- Documentation has moved to `docs.cloud.google.com` and the product is branded "Gemini
  Enterprise Agent Platform"; endpoint hostnames are unchanged.
- An Express-mode API-key path exists but could not be verified.
- Message Batches, Models, Admin, Usage, and Files APIs are **not** available on Vertex.
- 30 MB request payload limit.
