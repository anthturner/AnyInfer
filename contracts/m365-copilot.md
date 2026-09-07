# m365-copilot — Protocol Contract (Microsoft 365 Copilot)

Status: M3 adapter — **implemented** (interactive auth only; conformance-exempt).
Last verified: 2026-09-07 — live-verified against the corrected Upstream sources below.
Findings from this run: contract-drift/2026-09-07.

## Upstream sources
- https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/ (redirects to
  `/en-us/microsoft-365/copilot/extensibility/`)
- ~~https://learn.microsoft.com/en-us/graph/api/resources/copilot-api-overview~~ — **404,
  confirmed dead 2026-09-07** (also flagged dead by the deterministic stage). Corrected to:
  - https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/copilot-apis-overview
  - https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/copilot-apis-security-authentication
  - https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview
  - https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotroot-post-conversations
  - https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat

## Wire contract
### Endpoints
- **Resolved 2026-09-07, DRIFT.** The documented Chat API is a two-step flow, entirely
  under `/beta` (Microsoft's own note: "APIs under the `/beta` version are subject to
  change. Use of these APIs in production applications is not supported."):
  1. `POST https://graph.microsoft.com/beta/copilot/conversations` with an empty JSON body
     `{}` → `201 Created`, body is a `copilotConversation` shell: `{id, createdDateTime,
     displayName, status, turnCount}` (no message content yet).
  2. `POST https://graph.microsoft.com/beta/copilot/conversations/{conversationId}/chat`
     (synchronous) or `.../chat/stream` (`copilotconversation-chatoverstream`, SSE) with
     the actual message → `200 OK`, body is the updated `copilotConversation` including the
     new turn's messages.
  - **Adapter mismatch, needs follow-up (not fixed here)**: `src/anyinfer/providers/
    m365_copilot.py` defaults `_DEFAULT_BASE_URL` to `https://graph.microsoft.com/v1.0` and
    issues a single `POST {base}/copilot/conversations` per request
    (`_CHAT_PATH = "/copilot/conversations"`, used directly with the user message as the
    body). `/v1.0` does not expose this API at all per the live docs, the create-conversation
    call takes an empty body (not a message), and there is no second call to `.../chat`.
    As written, this adapter's calls do not match any documented request shape; this needs
    a conformance case and adapter review, which this workflow does not perform.
  - Verified against https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotroot-post-conversations
    and .../api/ai-services/chat/copilotconversation-chat.
### Auth
- Entra **interactive-only** (`azure-identity` / `azure-identity-broker`); no
  client-credential/headless flow available → CI live-testing exempt (conformance matrix),
  degraded headless story documented (DESIGN.md §20 #5).
  **Confirmed unchanged, 2026-09-07** (resolves the Watchlist "app-only/daemon auth" item
  for this run — still none): the Chat API's permissions table lists Delegated (work/school
  account) as the only supported type; "Delegated (personal Microsoft account)" and
  "Application" are both explicitly "Not supported." Required delegated scopes: all of
  `Sites.Read.All`, `Mail.Read`, `People.Read.All`, `OnlineMeetingTranscript.Read.All`,
  `Chat.Read`, `ChannelMessage.Read.All`, `ExternalItem.Read.All` are needed together (not
  a menu — the docs say "You need all of these"). Verified against
  https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat
  and .../copilot-apis-security-authentication.
### Version pins
- **Resolved 2026-09-07**: `/beta` only (see Endpoints); `/v1.0` does not carry this API.
### Request fields
- **Resolved 2026-09-07.** Continuing a conversation (`.../chat`) takes: `message` (the
  chat text, required), `locationHint` (**required** — e.g. `{"timeZone":
  "America/New_York"}`, not previously recorded), `additionalContext` (optional array of
  extra grounding text), `contextualResources` (optional — OneDrive/SharePoint `files[]` by
  `uri`, and/or `webContext.isWebEnabled` to toggle web-search grounding per turn). No
  native structured output → schema is prompt-injected (mechanism `prompt`); no
  temperature/sampling controls exposed. Verified against
  https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat.
### Response fields
- **Resolved 2026-09-07.** The `copilotConversation` body: `id`, `createdDateTime`,
  `displayName`, `state`/`status`, `turnCount`, `messages[]` where each message has `text`,
  `adaptiveCards[]`, `attributions[]` (`attributionType`: `annotation`|`citation`,
  `providerDisplayName`, `attributionSource`: `model`|`grounding`, `seeMoreWebUrl`, plus
  unused image fields), and `sensitivityLabel` (mostly null in examples). No usage/token
  field appears anywhere in the response — confirms the snapshot's existing "Usage fields
  None" assertion (OK, unchanged). Attributions/citations remain reasonable to keep on
  `raw` rather than normalize, since the shape above is still Graph-`/beta` and may move.
### Streaming
- **NEW-CAPABILITY, resolved 2026-09-07** (was an open VERIFY): the live API does offer
  streaming. A dedicated streamed endpoint exists
  (`copilotconversation-chatoverstream`) returning SSE with `Content-Type:
  text/event-stream`; "Streamed conversations aren't supported in Graph Explorer." The
  adapter's current non-streaming behavior is a real gap against a capability upstream now
  offers, not just an implementation choice — capability-catalog/adapter follow-up item.
### Errors
- 401/403 → AuthError with interactive-login hint; throttling 429 + Retry-After; tenant
  licensing errors → ConfigError (hint: M365 Copilot license required). **Not
  independently re-verified this run** — no error-shape example was found on the pages
  fetched; still consistent with the general Microsoft Graph error contract, but the
  Chat-API-specific error body shape remains UNVERIFIABLE against the sources cited above.

## Watchlist
- This API surface is young and shifting: endpoint routes, licensing gates, tenant
  admin-consent requirements. **Confirmed still true 2026-09-07**: the entire Chat API is
  `/beta`-only and Microsoft states beta-version APIs are unsupported in production —
  re-verify every run, this is exactly the kind of surface that moves without notice.
- Any addition of app-only/daemon auth (would unlock headless CI + serve-binary use) — none
  found this run (see Auth)
- Usage/metering fields appearing in responses — none found in the Chat API response body
  itself; a separate "Copilot usage reports API"
  (`api/admin-settings/reports/resources/copilotreportroot`) exists for tenant-level
  adoption/usage reporting, but that is an admin/reporting surface, not per-request usage
  telemetry on the chat response — not equivalent to what this item was watching for
- National cloud availability, found 2026-09-07: the Chat API create-conversation endpoint
  is available in the Global service, US Gov L4, and US Gov L5 (DoD) clouds, and explicitly
  **not** available in the China (21Vianet) cloud — worth recording if AnyInfer ever needs
  to target a sovereign cloud base URL for this provider
