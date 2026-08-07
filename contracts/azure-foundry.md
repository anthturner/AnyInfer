# azure-foundry — Protocol Contract (Azure AI Foundry)

Status: M2 adapter — **implemented** (openai-compat subclass).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://learn.microsoft.com/en-us/azure/ai-foundry/openai/reference
- https://learn.microsoft.com/en-us/azure/ai-foundry/openai/api-version-lifecycle

## Wire contract
### Endpoints
- `POST {base_url}/chat/completions` — base_url is resource-specific, e.g.
  `https://<resource>.services.ai.azure.com/openai/v1`; `api-version` query param when the
  deployment requires it
- `GET {base_url}/models` — deployment discovery
### Auth
- Entra: `Authorization: Bearer <token>` via `azure-identity`
  (`DefaultAzureCredential`; interactive-broker variant supported); Foundry token scope as
  recorded in Frisket `entra.py::FOUNDRY_SCOPE`; static `api-key` header supported as
  alternative
### Version pins
- `api-version` per deployment (configured, not hardcoded); recorded per-app
### Request fields
- openai-compat dialect with overrides: output-token parameter is
  **`max_completion_tokens`** (not `max_tokens`); reasoning effort as
  `reasoning_effort` for o-series/gpt-5-family deployments
### Response fields
- As openai-compat
### Streaming
- SSE as openai-compat
### Errors
- As openai-compat, plus Entra token acquisition failures → AuthError (hint: az login /
  credential chain); 401/403 distinguish authentication vs authorization

## Watchlist
- `api-version` lifecycle/retirements; the newer version-less `/openai/v1` surface
- Scope strings and credential-chain behavior in `azure-identity` major versions
- Divergences from vanilla openai-compat (parameter renames, content filter annotations
  in responses)
