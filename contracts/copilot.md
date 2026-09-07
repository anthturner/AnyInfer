# copilot — Protocol Contract (GitHub Copilot)

Status: M1 adapter — **implemented** (SDK-driven).
Last verified: 2026-09-07 — live-verified against pypi.org/project/github-copilot-sdk
(current release 1.0.13, 2026-09-04) and docs.github.com/en/copilot.
Findings from this run: contract-drift/2026-09-07.

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
### Runtime location
- The `cli_path` option and `COPILOT_CLI_PATH` are passed as
  `CopilotClient(connection=StdioRuntimeConnection(path=...))`, **not** as a flat
  `cli_path=` keyword: `CopilotClient.__init__` is keyword-only with no `**kwargs`, so an
  unrecognized name raises `TypeError` rather than being ignored. Absent, nothing is sent
  and the SDK performs its own discovery. `tests/test_copilot.py` binds the adapter's
  kwargs against the installed SDK's real signature so a rename fails there.
- **DRIFT, found 2026-09-07**: the live SDK (1.0.13) documents `RuntimeConnection`
  construction as factory functions — `RuntimeConnection.for_stdio(path=None, args=None)`,
  `.for_tcp(port=0, connection_token=None, path=None, args=None)`, `.for_uri(url,
  connection_token=None)`, `.for_inprocess()` (experimental, FFI) — not a directly
  constructed `StdioRuntimeConnection(path=...)` class, which is what the adapter calls
  (`src/anyinfer/providers/copilot.py`, `_ensure_client`). If `copilot.StdioRuntimeConnection`
  no longer exists as of the version actually resolved by `>=0.1`, every request that sets
  `cli_path`/`COPILOT_CLI_PATH` raises `AttributeError` instead of working. `tests/
  test_copilot.py`'s signature-binding check only catches this against whatever version is
  installed in CI, not against what PyPI serves today. Verified against
  https://pypi.org/project/github-copilot-sdk/ (manual-lifecycle and RuntimeConnection
  code samples). Adapter follow-up needed; not changed here.
### Version pins
- `github-copilot-sdk` version range pinned in the `[copilot]` extra (set at M1) as
  `>=0.1` (open-ended; see `pyproject.toml`). Live PyPI version as of 2026-09-07 is
  **1.0.13** (released 2026-09-04) — a major-version jump from the pinned floor, and the
  session-lifecycle and connection-construction DRIFT items below are exactly the kind of
  break an unbounded floor exposes. **Proposed action**: give this extra an upper bound (or
  at least re-pin the floor to a version verified against the current session API) rather
  than widening the gap further.
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
  `session.close()`/`aclose()` remaining callable more than once per session object.
  **DRIFT, found 2026-09-07**: the live SDK's own manual-lifecycle example is
  `client = CopilotClient(); await client.start(); session = await
  client.create_session(...); ...; await session.disconnect(); await client.stop()` — the
  session-level shutdown method shown is `disconnect()`, not `close()`/`aclose()`; a
  context-manager form (`async with await client.create_session(...) as session`) is also
  now supported. The adapter's per-request cleanup
  (`getattr(session, "close", None) or getattr(session, "aclose", None)`,
  `src/anyinfer/providers/copilot.py:246`) and its swept-session shutdown
  (`_SHUTDOWN_METHODS = ("stop", "close", "aclose")`, same file, applied to held sessions
  too) do not probe for `disconnect`. If the installed SDK's `Session` no longer exposes
  `close`/`aclose`, both paths silently find nothing to call (the `if close is not None`
  guard skips cleanup without raising) and leak the underlying CLI session on every
  request. `client.stop()` for the *client* itself is unaffected — `"stop"` is already
  first in `_SHUTDOWN_METHODS` and matches the live doc. Verified against
  https://pypi.org/project/github-copilot-sdk/. Adapter follow-up needed (add `disconnect`
  to the probed session-shutdown names); not changed here.
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
- ~~SDK API surface churn~~ — **confirmed churning, 2026-09-07**: session shutdown and
  `RuntimeConnection` construction both changed shape (see DRIFT items above); re-check
  every run until the SDK is out of its young phase
- `auto` sentinel semantics + the model set it may delegate to (capability conjunction
  inputs, DESIGN.md §7)
- Model catalog changes: live docs now show `"gpt-5"` and `"claude-sonnet-4.5"` as example
  model ids (the snapshot's illustrative `gpt-4.1` is stale); per-model quotas/billing
  signals still not itemized in provider docs
- Session resume support (the token-cache path) — verify per SDK release
- **New, 2026-09-07**: docs.github.com now describes BYOK (bring-your-own-key) and
  server-to-server token auth for custom LLM providers, in addition to the `gh`/Copilot CLI
  device flow this adapter uses exclusively. Not yet assessed for whether either unlocks a
  headless/non-interactive path for this adapter — worth a follow-up, not a contract change
  here since no request/response shape was confirmed for it.
