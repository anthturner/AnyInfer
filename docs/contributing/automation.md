# Coding-agent instructions

AnyInfer supports Codex, Claude Code, and GitHub Copilot with one authoritative instruction
set. [`AGENTS.md`](https://github.com/anthturner/anyinfer/blob/main/AGENTS.md) is the source
of truth for repository rules, architecture constraints, tests, and workstream ownership.

The tool-specific files are discovery shims only:

| Tool | Discovery file | Workflow shim |
|---|---|---|
| Codex | `AGENTS.md` | `.agents/skills/check-provider-drift/SKILL.md` |
| Claude Code | `CLAUDE.md` | `.claude/skills/check-provider-drift/SKILL.md` |
| GitHub Copilot | `.github/copilot-instructions.md` | `.github/prompts/check-provider-drift.prompt.md` |

The shims point back to the canonical source and must not restate repository rules. This
prevents one tool from operating under a stale or subtly different architecture. Provider
drift works the same way: [`contracts/DRIFT-CHECK.md`](https://github.com/anthturner/anyinfer/blob/main/contracts/DRIFT-CHECK.md)
owns the procedure and report format; the Codex and Claude skills and Copilot prompt only
make it discoverable in those tools.

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

## Keeping the shims honest

The test suite checks that each tool-specific shim points to its canonical file and stays
small. When a rule changes:

1. Edit `AGENTS.md` or the canonical workflow document.
2. Change a shim only if its pointer or invocation syntax changed.
3. Run `python workspace.py check`.

Do not add a second copy of the rules for convenience; link to the owning document.
