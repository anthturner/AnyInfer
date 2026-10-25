# Coding Agents and Workstreams

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

Each workflow follows the same shape (one tool-neutral procedure file, three thin entry
points that only make it discoverable):

| Workflow | Canonical procedure | What it owns |
|---|---|---|
| `add-provider` | [`contracts/NEW-PROVIDER.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/NEW-PROVIDER.md) | Adding a preset, a dedicated adapter, or a new embedding/rerank binding: research first, then adapter, registration, docs, tests, verification |
| `check-provider-drift` | [`contracts/DRIFT-CHECK.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md) | Auditing existing contract snapshots against current upstream docs, and the report format |
| `propagate-provider-change` | [`contracts/PROPAGATE-CHANGE.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/PROPAGATE-CHANGE.md) | Turning verified upstream evidence into a coordinated change across the shared specification and every registered SDK implementation |
| `anyinfer-integration` | [`docs/agents/INTEGRATION.md`](../agents/INTEGRATION.md) | Using AnyInfer from an application, read in somebody else's repository |

The first two are two halves of one lifecycle: `NEW-PROVIDER.md` produces a contract
snapshot, `DRIFT-CHECK.md` keeps it true afterwards. `PROPAGATE-CHANGE.md` takes an adopted
finding from either one into the shared specification and the Python and C# implementations.

## Scheduled Repository Checks

Three weekly workflows watch for the world changing underneath the repository.

The pricing-drift check is a detector, not an updater. It compares the bundled pricing
table's exact provider/model keys against Chutes and Avian as direct sources, with
OpenRouter as a secondary tripwire for the OpenAI and Anthropic entries that carry an
OpenRouter id. A clean run means every source was reachable, every compared entry was still
listed, and every compared value matched; other providers' prices are not compared at all, and
a contributor changing a rate still confirms it against the provider's own pricing
documentation. Run it locally with
`python scripts/check_pricing_drift.py` (`--format json` for machine output,
`--report PATH` to write the versioned JSON report, `--live-source NAME` to probe one
real source). Exit codes: 0 clean, 1 drift found, 2 a source failed or the report is
invalid. Source fixtures for its tests live under `tests/fixtures/pricing/`, and where
the bundled prices come from is covered in
[cost and spending](../concepts/cost.md#where-prices-come-from).

The weekly catalog re-check confirms the model catalog's pinned entries still match
upstream. The contract drift check audits provider contract snapshots against current
public API documentation, following
[`contracts/DRIFT-CHECK.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md).

One further workflow follows the same two-stage shape but is not on a schedule. The
changelog workflow writes a branch's [changelog](changelog.md) entries into the
`Unreleased` section when its pull request opens, and pins that section to a version when
a push declares one. Both modes push onto the feature branch, so the prose is reviewed with the
work it describes.

## Workstream Boundaries

Start in the narrowest workstream that owns the behavior:

| Workstream | Primary paths | Responsibility |
|---|---|---|
| Shared foundation | `specification/`, `contracts/`, `maintenance/` | Language-neutral behavior profiles and their immutable corpora, provider contract snapshots, and cross-implementation maintenance; a later SDK profile never silently expands a sealed release |
| Native C# SDK | `src/csharp/`, `examples/csharp-sdk/`, C# SDK docs and verification scripts | Independent .NET execution over the shared contracts and data, with an async core and sync facade; adapters translate and orchestration stays in the native core |
| Core engine and Python SDK | `src/python/anyinfer/` except `cli.py` and `serve/` | Requests, typed events, routing, adapters, capabilities, local inference, client lifecycle |
| Shared configuration | `src/python/anyinfer/config/` | The versioned JSON format the Python SDK, CLI, sidecar, and demo share |
| Command-line tool | `src/python/anyinfer/cli.py` | Argument parsing, terminal output, and exit codes for the one-shot and operator commands (`init`, `run`, `verify`, `doctor`, `serve`, and the rest) |
| OpenAI-compatible sidecar | [`src/python/anyinfer/serve/`](../serve/README.md) | OpenAI wire codec, ASGI application, and service-unit rendering; never a second routing core |
| Demo application | [`src/python/anyinfer_demo/`](../guides/demo-app.md), `tests/demo_app/` | Offline reference UI and integration example; not part of core behavior |

[`AGENTS.md`](https://github.com/anthturner/AnyInfer/blob/main/AGENTS.md) holds the canonical
version of this table. Python tests mirror those boundaries under `tests/`; native tests live in
the C# solution under `src/csharp/`. Shared behavior belongs in the engine or configuration
package, not copied into the CLI, sidecar, or demo. A change that crosses a
boundary should say why in its pull request and update every affected guide.

## Keeping the Shims in Sync

The test suite checks that each tool-specific shim points to its canonical file and stays
small. When a rule changes:

1. Edit `AGENTS.md` or the canonical workflow document.
2. Change a shim only if its pointer or invocation syntax changed.
3. Run `python workspace.py check`.

Do not add a second copy of the rules for convenience; link to the owning document.
