# Provider Contract Snapshots

One file per provider recording **exactly the upstream protocol details AnyInfer depends
on** — nothing else. These are the diff targets for the drift check
([DRIFT-CHECK.md](DRIFT-CHECK.md)) and the wire-level specification adapter implementers
code against (with DESIGN.md §8 as the behavioral contract).

Two procedures own this directory's lifecycle, and both are tool-agnostic:

- [NEW-PROVIDER.md](NEW-PROVIDER.md) — adding a provider. A snapshot is researched and
  written *before* the adapter it specifies; the rest of the procedure covers registration,
  the generated docs surfaces, tests, and verification.
- [DRIFT-CHECK.md](DRIFT-CHECK.md) — auditing an existing snapshot against the provider's
  current public documentation.

[TEMPLATE.md](TEMPLATE.md) is the starting shape for a new snapshot.

## Rules

- **Update the snapshot in the same change** whenever an adapter's wire behavior changes.
- `Last verified` records a real verification event (date + against what). Never backdate,
  never bump without checking (see AGENTS.md warnings).
- Initial snapshots (2026-08-05) are derived from a survey of working adapter code, **not**
  from live documentation — each is marked accordingly. The first `check-provider-drift`
  run establishes the true baseline for those.
- Snapshots added from 2026-08-07 onward (`gemini`, `deepseek`, `xai`, `nebius`, and
  `openai-compat-presets`) *were*
  verified against live documentation, with per-assertion sources recorded. The one
  exception is the `groq` entry inside the presets file: its documentation blocked
  automated access, so it is built from the official SDK reference and flagged for the
  next drift check.
- **`huggingface.md` is not an inference provider.** It records the weights-source API model
  acquisition depends on. It follows the same schema and the same drift procedure, because a
  third-party protocol we depend on is a third-party protocol we depend on.
- **`mcp.md` is not an inference provider either.** It records the Model Context Protocol
  as a source of tool definitions and an execution transport, scoped to `tools/list` and
  `tools/call`. Same schema, same drift procedure, same reason.
- **`openai-compat-presets.md` covers many providers in one file** — the presets share one
  adapter, so they share one snapshot, with a section per provider. Treat each section as
  an independent unit when drift-checking.

## File schema

```markdown
# <provider-id> — Protocol Contract

Status: <adapter milestone / implemented / planned>
Last verified: <date> — <against what (live docs / code survey / release notes)>

## Upstream sources
- <url>  (docs, changelog, release notes — everything the drift check should fetch)

## Wire contract
### Endpoints        <method, path, purpose — only the ones we call>
### Auth             <headers/flows/scopes we use>
### Version pins     <API versions, SDK versions, release tags we pin>
### Request fields   <fields we send, incl. translations (e.g. reasoning effort wire form)>
### Response fields  <fields we read: text, usage, finish reason, errors>
### Streaming        <framing (SSE/NDJSON/events), delta event types we parse, terminator>
### Errors           <status codes / error shapes we classify on>

## Watchlist
<things likely to change that we care about: announced deprecations, beta features we
emulate today, version headers, model-listing shapes>
```
