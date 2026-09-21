# openrouter — Protocol Contract

Status: M3 adapter — **implemented** (openai-compat subclass).
Last verified: 2026-09-21 — live drift check.

## Upstream sources
- https://openrouter.ai/docs/api-reference/overview
- https://openrouter.ai/docs/api-reference/list-available-models — **dead** (404, confirmed both
  by the deterministic tripwire and a live fetch on 2026-09-21). Corrected URL:
  https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties
  (fetched 2026-09-21; response shape unchanged — see below)
- https://openrouter.ai/docs/changelog

## Wire contract
### Endpoints
- `POST https://openrouter.ai/api/v1/chat/completions` — generation
- `GET https://openrouter.ai/api/v1/models` — discovery **with rich metadata**: per-model
  `context_length`, `pricing` (prompt/completion per-token USD strings), supported
  parameters — feeds the capability layer with `discovered` provenance including pricing.
  OK, reconfirmed 2026-09-21 at the corrected doc URL above; also carries `architecture`
  (modalities), `top_provider`, and third-party `benchmarks` — not currently read.
- NEW-CAPABILITY (2026-09-21): `GET /models` now also accepts filtering/sort query params
  (`min/max_intelligence_index`, `min/max_agentic_index`, `min/max_coding_index`,
  `min/max_tool_success_rate`, `min/max_output_price`, `min/max_age_days`, `sort`), added
  2026-07-07 per the changelog. Not used by discovery today; would let the adapter narrow a
  catalog fetch server-side instead of filtering client-side.
- NEW-CAPABILITY (changelog, GA 2026-07-25): a Responses-API-shaped endpoint is now generally
  available on OpenRouter (schema unchanged from its beta, just reclassified from
  `beta.responses` to `responses` in their OpenAPI grouping). The adapter here only implements
  the Chat Completions surface (openai-compat dialect) — out of scope for this snapshot's wire
  contract, but worth noting for the roadmap.
### Auth
- `Authorization: Bearer <api_key>`; optional attribution headers (`HTTP-Referer`,
  `X-Title`)
- NEW-CAPABILITY (2026-09-21): the canonical header is now documented as
  `X-OpenRouter-Title` (`X-Title` still accepted as an alias); a new `X-OpenRouter-Categories`
  header sets marketplace classification categories for the app. Neither is sent by the
  adapter today.
### Version pins
- None
### Request fields
- openai-compat dialect; `model` uses namespaced ids (`vendor/model`); optional
  `provider` routing preferences object; `usage: {include: true}` for usage accounting;
  structured output via `response_format` where the underlying model supports it
  (capability varies per model — probe/metadata territory)
### Response fields
- As openai-compat; usage may include cost accounting; `model` echoes the concrete model
  actually served (upstream may route)
### Streaming
- SSE as openai-compat; keep-alive comment lines (`: OPENROUTER PROCESSING`) must be
  ignored by the SSE parser
- UNVERIFIABLE (2026-09-21): the overview page fetched this run didn't re-render the specific
  keep-alive comment text; not contradicted, just not re-confirmed. The changelog's July-2026
  entries do describe streaming schema additions (`ImageGenTextChunkEvent`,
  `MessagesToolAdditionBlock`/`RemovalBlock` union variants for MCP tools,
  `FusionCallAnalysisInProgressEvent` renaming `judge_model`→`analyst_model`) that are on
  OpenRouter's own extended surface, not the plain chat-completions dialect this adapter reads
  — noted for awareness, not applied.
### Errors
- openai-compat shapes plus 402 (insufficient credits) → typed as AuthError-adjacent
  billing error with hint; moderation blocks surfaced distinctly
- UNVERIFIABLE (2026-09-21): the 402 shape specifically wasn't re-confirmed this run (no error
  documentation page was fetched); not contradicted by anything found.

## Watchlist
- `/models` metadata schema (pricing field format, supported_parameters) — our richest
  `discovered`-provenance source; shape changes ripple into the capability assembler
- Upstream model routing semantics vs our `auto`-sentinel conjunction rule (DESIGN.md §7)
- SSE comment/keep-alive framing quirks
- The `/models` filtering params and `X-OpenRouter-Categories` header above (both new
  2026-09-21) — adapter follow-up work items, not yet wired up
