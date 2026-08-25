# Coding-agent instructions

AnyInfer supports Codex, Claude Code, and GitHub Copilot with one authoritative instruction
set. [`AGENTS.md`](https://github.com/anthturner/AnyInfer/blob/main/AGENTS.md) is the source
of truth for repository rules, architecture constraints, tests, and workstream ownership.

The tool-specific files are discovery shims only:

| Tool | Discovery file | Workflow shims |
|---|---|---|
| Codex | `AGENTS.md` | `.agents/skills/<workflow>/SKILL.md` |
| Claude Code | `CLAUDE.md` | `.claude/skills/<workflow>/SKILL.md` |
| GitHub Copilot | `.github/copilot-instructions.md` | `.github/prompts/<workflow>.prompt.md` |

The shims point back to the canonical source and must not restate repository rules. This
prevents one tool from operating under a stale or subtly different architecture.

Each workflow follows the same shape — one tool-neutral procedure file, three thin entry
points that only make it discoverable:

| Workflow | Canonical procedure | What it owns |
|---|---|---|
| `add-provider` | [`contracts/NEW-PROVIDER.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/NEW-PROVIDER.md) | Adding a preset, a dedicated adapter, or a new embedding/rerank binding: research first, then adapter, registration, docs, tests, verification |
| `check-provider-drift` | [`contracts/DRIFT-CHECK.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md) | Auditing existing contract snapshots against current upstream docs, and the report format |
| `anyinfer-integration` | [`docs/agents/INTEGRATION.md`](../agents/INTEGRATION.md) | Using AnyInfer from an application, read in somebody else's repository |

The first two are two halves of one lifecycle: `NEW-PROVIDER.md` produces a contract
snapshot, `DRIFT-CHECK.md` keeps it true afterwards.

## Workstream boundaries

Start in the narrowest workstream that owns the behavior:

| Workstream | Primary paths | Responsibility |
|---|---|---|
| Core engine and Python SDK | `src/anyinfer/` except `cli.py` and `serve/` | Requests, typed events, routing, adapters, capabilities, local inference, client lifecycle |
| Shared configuration | `src/anyinfer/config/` | The versioned JSON contract used by every integration path |
| Command-line tool | `src/anyinfer/cli.py` | Human and shell interface for `run`, `doctor`, `providers`, and sidecar startup |
| OpenAI-compatible sidecar | `src/anyinfer/serve/` | OpenAI wire codec and ASGI application; never a second routing core |
| Demo application | `src/demo_app/` | Offline reference UI and integration example; not part of core behavior |

Tests mirror those boundaries under `tests/`. Shared behavior belongs in the engine or
configuration package, not copied into the CLI, sidecar, or demo. A change that crosses a
boundary should say why in its pull request and update every affected guide.

## Keeping the shims in sync

The test suite checks that each tool-specific shim points to its canonical file and stays
small. When a rule changes:

1. Edit `AGENTS.md` or the canonical workflow document.
2. Change a shim only if its pointer or invocation syntax changed.
3. Run `python workspace.py check`.

Do not add a second copy of the rules for convenience; link to the owning document.
