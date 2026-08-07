# m365-copilot — Protocol Contract (Microsoft 365 Copilot)

Status: M3 adapter — **implemented** (interactive auth only; conformance-exempt).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/
- https://learn.microsoft.com/en-us/graph/api/resources/copilot-api-overview

## Wire contract
### Endpoints
- Copilot chat/interaction endpoint(s) as implemented in Frisket
  `microsoft_365_copilot.py` (httpx2; exact routes to be transcribed verbatim when the M3
  adapter is ported — VERIFY against live docs at that time)
### Auth
- Entra **interactive-only** (`azure-identity` / `azure-identity-broker`); scopes recorded
  in Frisket `entra.py::M365_COPILOT_CHAT_SCOPES`; no client-credential/headless flow
  available → CI live-testing exempt (conformance matrix), degraded headless story
  documented (NOTES.md open question 5)
### Version pins
- Graph/Copilot API version segment as used by Frisket
### Request fields
- Prompt/conversation payload; no native structured output → schema is prompt-injected
  (mechanism `prompt`); no temperature/sampling controls exposed
### Response fields
- Message text; attributions/citations metadata (retained in `raw`, not normalized in v1);
  usage generally absent → Usage fields None
### Streaming
- Verify: Frisket uses non-streaming; if live API offers streaming, mark NEW-CAPABILITY
### Errors
- 401/403 → AuthError with interactive-login hint; throttling 429 + Retry-After; tenant
  licensing errors → ConfigError (hint: M365 Copilot license required)

## Watchlist
- This API surface is young and shifting: endpoint routes, licensing gates, tenant
  admin-consent requirements
- Any addition of app-only/daemon auth (would unlock headless CI + serve-binary use)
- Usage/metering fields appearing in responses
