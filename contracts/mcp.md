# mcp — Protocol Contract

Status: tool-source client — **implemented** (`tools/list` and `tools/call` only).
Last verified: 2026-08-09 — specification survey at implementation time; the adapter is
written against this snapshot. **Not yet verified against a live server or the published
specification changelog** — run the drift check before relying on it.

This snapshot is not an inference provider. Like `huggingface.md`, it records a protocol
AnyInfer speaks for a different purpose: Model Context Protocol servers are a *source of
tool definitions and an execution transport* for tools the application already chose to
trust. The scope is deliberately two methods wide.

## Upstream sources
- https://modelcontextprotocol.io/specification
- https://modelcontextprotocol.io/specification/basic/lifecycle
- https://modelcontextprotocol.io/specification/server/tools
- https://modelcontextprotocol.io/specification/basic/transports

## Wire contract
### Endpoints
MCP is JSON-RPC 2.0 over one of two transports; there is no fixed URL path.

- **stdio** — the client spawns the server process and speaks newline-delimited JSON-RPC
  over its stdin/stdout. Server stderr is log output and is never parsed as protocol.
- **streamable HTTP** — `POST <url>` with a JSON-RPC body; the server answers with either
  `application/json` (one response) or `text/event-stream` (a response plus notifications).

Methods used, and only these:

| Method | Direction | Purpose |
|---|---|---|
| `initialize` | client → server | Handshake and version negotiation |
| `notifications/initialized` | client → server | Completes the handshake |
| `tools/list` | client → server | Discover tools; may be paginated by `nextCursor` |
| `tools/call` | client → server | Execute one tool |

**Deliberately not spoken:** `prompts/*`, `resources/*`, `roots/*`, `completion/*`,
`logging/*`, and — importantly — `sampling/*`. A server asking the client to run a
generation would drive inference through the caller's credentials; that is a capability to
grant deliberately, not one to inherit from a tool integration.

### Auth
- **stdio** — no protocol-level authentication. Credentials reach the server through its
  process environment, which AnyInfer resolves through `anyinfer.credentials` and registers
  for redaction before spawning.
- **streamable HTTP** — whatever the server requires, sent as request headers supplied by
  the caller. AnyInfer adds no authentication scheme of its own.

### Version pins
- Sent in `initialize` as `protocolVersion`. Pinned: **`2025-06-18`**.
- The server answers with the version it will speak. AnyInfer accepts a server that answers
  with the pinned version or an older one it recognizes; a server answering with an
  unrecognized version fails with a typed error naming both sides rather than proceeding on
  a guess.
- **VERIFY on the next drift run:** the current specification revision, and whether the
  accepted-version set needs widening. This is date-versioned and moves.

### Request fields
`initialize` params:

- `protocolVersion` — the pinned string above.
- `capabilities` — `{}`. AnyInfer advertises no client capabilities, because it implements
  none of the client-side features (sampling, roots, elicitation) that a capability would
  claim. Advertising one it does not honor is how a server ends up waiting on a request
  that never comes.
- `clientInfo` — `{"name": "anyinfer", "version": <package version>}`.

`tools/list` params: `cursor` when continuing a paginated listing, absent otherwise.

`tools/call` params: `name` (the server's own tool name, un-namespaced) and `arguments`
(the object the model produced, validated against the tool's `inputSchema` by the model's
provider, not re-validated here).

### Response fields
`initialize` result: `protocolVersion`, `capabilities`, `serverInfo`. Only
`protocolVersion` is load-bearing; the rest is recorded for diagnostics.

`tools/list` result:

- `tools[]` — each with `name`, `description`, and `inputSchema` (a JSON Schema object).
  The schema is passed through to `ToolSpec.parameters` **unmodified**: it is already the
  shape providers expect, and re-deriving it would only lose fidelity.
- `tools[].annotations` — optional behavioural hints: `title`, `readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`. Captured onto `ToolSpec`.
  **These are untrusted server-supplied hints.** The specification says so explicitly, and
  AnyInfer treats them accordingly: they may gate an optimization, and they may never gate
  a security decision. Nothing is granted more access because a server called it read-only.
- `nextCursor` — present when more tools remain.

`tools/call` result:

- `content[]` — content blocks. `{"type": "text", "text": ...}` blocks are joined into
  `ToolResult.content`. Any other block type is replaced by a bounded placeholder naming
  what was dropped, because a silently discarded image is a wrong answer with no evidence.
- `isError` — when true, the call becomes `ToolResult(is_error=True)` and the loop
  continues, matching the tool loop's existing rule that a failing tool is a normal
  conversational event rather than an exception.

### Streaming
The streamable-HTTP transport may answer with `text/event-stream`. AnyInfer reads SSE
frames, correlates JSON-RPC responses by `id`, and ignores notifications it does not
implement. Tool *results* are not streamed incrementally into the model: a tool call
produces one `ToolResult` when it completes.

### Errors
- JSON-RPC error objects (`{"code", "message", "data"}`) on a request become
  `ToolLoopError` when they are protocol-level (unknown method, invalid params, handshake
  failure), because the loop cannot recover by re-asking.
- A tool that fails *its own* work reports `isError: true` in a successful JSON-RPC
  response; that becomes an error-flagged `ToolResult`, which the model may recover from.
- Transport death — process exit, closed stream, HTTP failure — raises `ToolLoopError`.
- `-32601` (method not found) on `tools/list` means the server exposes no tool surface;
  reported as a typed error naming the server rather than as an empty tool set, since
  silently having no tools looks identical to a misconfiguration.

## Watchlist
- **Protocol revision date** and the accepted-version set (see Version pins).
- **`annotations` field names and semantics** — currently `readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`. These gate a memoization
  optimization, so a rename that silently reads as "absent" would disable it rather than
  corrupt it — but it should be caught, not tolerated.
- **Structured tool output** — whether `tools/call` gains a first-class structured result
  alongside `content[]`, which would change what flattening loses.
- **Pagination** on `tools/list`, and whether `nextCursor` semantics change.
- **Transport deprecations** — the HTTP+SSE transport that streamable HTTP replaced, and
  whether stdio framing gains options.
