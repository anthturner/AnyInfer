# copilot — Protocol Contract (GitHub Copilot)

Status: M1 adapter — **implemented** (SDK-driven).
Last verified: 2026-08-05 — code survey of the sibling projects; adapter implemented against this snapshot. **Not yet verified against live provider documentation** — run the drift check before relying on it.

## Upstream sources
- https://pypi.org/project/github-copilot-sdk/ (SDK releases + changelog)
- https://docs.github.com/en/copilot (product-level changes, model availability)

## Wire contract
### Endpoints
- No direct HTTP: `github-copilot-sdk` (`CopilotClient`, `RuntimeConnection`) spawns and
  drives the Copilot CLI as a subprocess runtime
### Auth
- Delegated: existing `gh`/Copilot CLI login (device flow); no key material handled by us;
  `COPILOT_CLI_PATH` overrides CLI discovery
### Version pins
- `github-copilot-sdk` version range pinned in the `[copilot]` extra (set at M1)
### Request fields
- Session-based: system prompt + user prompt per session turn; model id or `"auto"`
  sentinel (provider-side model delegation); no native structured-output mode — schema is
  prompt-injected (mechanism `prompt`); reasoning effort sent as `reasoning_effort` in the
  session options
### Session lifetime
- Without an open `Session`, one SDK session is created and closed per request, and prior
  turns are folded into the user prompt with role markers
- With one, the SDK session object is **held across turns** and closed when the adapter
  closes; a resumed turn sends only the newest user message, because the service still
  holds everything before it
- Depends on: `client.create_session(**options)`, `session.send(prompt)`, and
  `session.close()`/`aclose()` remaining callable more than once per session object
- Sampling controls (`temperature`, `top_p`, `max_output_tokens`, `stop`) and
  caller-supplied `tools` have no session-API wire form; the descriptor declares them in
  `ignored_parameters`, so requesting them raises `ParameterDropped` telemetry instead of
  silently no-oping
### Response fields
- Assistant message events aggregated to final text; usage from `assistant.usage` events:
  `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`,
  `reasoning_tokens`
### Streaming
- SDK event callbacks (message/delta/usage events) mapped to StreamEvents
### Errors
- SDK/CLI exceptions mapped: CLI-missing → ConfigError (hint: install/`COPILOT_CLI_PATH`);
  auth failures → AuthError (hint: `copilot login`); rate/limit events → RateLimitError

## Watchlist
- SDK API surface churn (young SDK; event names, session API, usage event shape)
- `auto` sentinel semantics + the model set it may delegate to (capability conjunction
  inputs, DESIGN.md §7)
- Model catalog changes (ids like gpt-4.1 availability), per-model quotas/billing signals
- Session resume support (the token-cache path) — verify per SDK release
