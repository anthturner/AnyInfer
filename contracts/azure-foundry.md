# azure-foundry — Protocol Contract (Azure AI Foundry)

Status: M2 adapter — **implemented** (openai-compat subclass); embeddings implemented
2026-08-12 (`OpenAICompatEmbeddingsMixin` composed onto the same dialect).
Last verified: 2026-08-12 — generation section from code survey (2026-08-05); embeddings
section fetched live from learn.microsoft.com.

## Upstream sources
- https://learn.microsoft.com/en-us/azure/ai-foundry/openai/reference
- https://learn.microsoft.com/en-us/azure/ai-foundry/openai/api-version-lifecycle
- https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/embeddings (embeddings,
  fetched 2026-08-12)

## Wire contract
### Endpoints
- `POST {base_url}/chat/completions` — base_url is resource-specific, e.g.
  `https://<resource>.services.ai.azure.com/openai/v1`; `api-version` query param when the
  deployment requires it
- `POST {base_url}/embeddings` — same v1, deployment-less surface as chat; `model` is the
  deployment name, exactly as `openai_compat_embeddings.py`'s body shape (verified
  2026-08-12). `api-version` appended the same way as chat when the deployment requires
  the older query-pinned surface.
- `GET {base_url}/models` — deployment discovery
### Auth
- Entra: `Authorization: Bearer <token>` via `azure-identity`
  (`DefaultAzureCredential`; interactive-broker variant supported); Foundry token scope as
  recorded in `credentials/entra.py`; static `api-key` header supported as
  alternative
### Version pins
- `api-version` per deployment (configured, not hardcoded); recorded per-app
### Request fields
- openai-compat dialect with overrides: output-token parameter is
  **`max_completion_tokens`** (not `max_tokens`); reasoning effort as
  `reasoning_effort` for o-series/gpt-5-family deployments
- Embeddings: identical body to `openai_compat_embeddings.py` (`model`, `input`,
  optional `dimensions`, optional `encoding_format`); no Azure-specific fields observed.
### Response fields
- As openai-compat
- Embeddings: as `openai_compat_embeddings.py` (`data[].{index,embedding}`, `model`,
  `usage.{prompt_tokens,total_tokens}`)
### Streaming
- SSE as openai-compat
### Errors
- As openai-compat, plus Entra token acquisition failures → AuthError (hint: az login /
  credential chain); 401/403 distinguish authentication vs authorization
- Embeddings 404 specifically means the endpoint is missing `/openai/v1/` or `model` is
  not a valid deployment name (documented troubleshooting entry, 2026-08-12)

### Embedding limits (verified 2026-08-12, learn.microsoft.com/azure/ai-foundry/openai/how-to/embeddings)
- Max 2,048 inputs per request (same ceiling as OpenAI itself)
- Max 8,192 tokens per individual input
- Max 300,000 tokens aggregate across all inputs in one request (HTTP 400 above this,
  even if every individual input is under its own limit)
- **Not statically declared** in `static_embedding_capabilities`: `model` is a
  tenant-chosen deployment name, not a fixed catalog id, so these limits cannot be keyed
  reliably per model the way OpenAI's fixed model ids allow.

## Watchlist
- `api-version` lifecycle/retirements; the newer version-less `/openai/v1` surface
- Scope strings and credential-chain behavior in `azure-identity` major versions
- Divergences from vanilla openai-compat (parameter renames, content filter annotations
  in responses)
- Whether Azure ever exposes a listing endpoint that tags which deployments are
  embedding-capable (would let discovery stamp `operations` per-model, as LM Studio does)
