# vertex — Protocol Contract

Status: **implemented** — `providers/vertex.py`, a `gemini` subclass for generation;
embeddings implemented 2026-08-12 with a Vertex-native `:predict` override (not
inherited from Gemini — see below).
Last verified: 2026-08-12 — generation section against 2026-08-07 live documentation;
embeddings section fetched live 2026-08-12.

## Upstream sources
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/inference
- https://cloud.google.com/vertex-ai/generative-ai/pricing
- https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/generativeaionvertexai-claude-3-streaming
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/count-tokens
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/migrate/migrate-google-ai
- https://developers.google.com/identity/protocols/oauth2/service-account
- https://ai.google.dev/gemini-api/docs/thinking
- https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/text-embeddings-api
  (embeddings, fetched live 2026-08-12)

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

## Embeddings (verified live 2026-08-12)

**Not the Gemini shape.** Every embedding model Vertex documents —
`gemini-embedding-001`, `text-embedding-005`, `text-multilingual-embedding-002`, and the
legacy `textembedding-gecko@001` — uses the generic Vertex `predict` verb, not Gemini's
`batchEmbedContents`. `VertexAdapter.embed()` overrides `GeminiAdapter.embed()` entirely
rather than reusing it.

### Endpoint
`POST {base}/projects/{project}/locations/{location}/publishers/google/models/{model}:predict`
— same addressing as generation.

### Request body
```json
{
  "instances": [{"content": "text", "task_type": "RETRIEVAL_DOCUMENT", "title": "..."}],
  "parameters": {"autoTruncate": true, "outputDimensionality": 768}
}
```
- `content` (required), `task_type` (optional; defaults server-side to `RETRIEVAL_QUERY`
  when omitted), `title` (optional, only valid with `task_type=RETRIEVAL_DOCUMENT` — not
  sent, since `EmbeddingWireRequest` carries no per-input title field)
- `task_type` enum: `RETRIEVAL_QUERY`, `RETRIEVAL_DOCUMENT`, `SEMANTIC_SIMILARITY`,
  `CLASSIFICATION`, `CLUSTERING`, `QUESTION_ANSWERING`, `FACT_VERIFICATION`,
  `CODE_RETRIEVAL_QUERY` — the adapter maps the four normalized intents
  (query/document/classification/clustering); the other four are reachable only through
  `provider_options`
- `outputDimensionality` forwards `EmbeddingWireRequest.dimensions`; `autoTruncate` is
  never set explicitly (provider default `true` is left alone)

### Response body
```json
{"predictions": [{"embeddings": {"values": [0.1, ...], "statistics": {"truncated": false, "token_count": 4}}}]}
```
One prediction per instance, in request order. `statistics.token_count` summed across
predictions becomes `Usage.input_tokens`; there is no separate output-token concept for
embeddings.

### Limits (quoted from the how-to guide, 2026-08-12)
> Limit: five texts of up to 2,048 tokens per text for all models except
> textembedding-gecko@001. The max input token length for textembedding-gecko@001 is
> 3072. For gemini-embedding-001, each request can only include a single input text.

Declared in `static_embedding_capabilities`: `max_batch_inputs=1` for
`gemini-embedding-001`, `5` for the others; `max_input_tokens` 2,048 (3,072 for the
gecko model). Output dimensions: up to 3,072 for `gemini-embedding-001`, up to 768 for
`text-embedding-005` and `text-multilingual-embedding-002` (declared as `dimensions`,
the default when `outputDimensionality` is not set).

## Watchlist

- **Server-side tools are not claimed here, though the adapter inherits Gemini's
  projection.** Vertex has published a different spelling for grounded search than the
  Gemini API at various points (`googleSearchRetrieval` versus `googleSearch`), and the
  current one has not been verified against Google's own documentation. The descriptor
  therefore declares no `server_tools`, so a request naming one is refused locally rather
  than sent as a block Vertex may reject. Verify the spelling on the next drift run and
  declare it then. Noted 2026-08-25.
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
- The API reference navigation lists an `embedContent` method under
  `publishers.models` alongside `predict` — not documented in the how-to guide used
  here, so not assumed to be a live alternate surface for any current model. Re-check
  if a future embedding model's docs point at it instead of `:predict`.
