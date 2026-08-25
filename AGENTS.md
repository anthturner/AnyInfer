# AnyInfer — Agent Instructions

Canonical instructions for all AI coding agents (Codex, Claude Code, GitHub Copilot, and
others). Tool-specific files (`CLAUDE.md`, `.github/copilot-instructions.md`) defer here.

## What this project is

AnyInfer is an application-owned hybrid inference runtime for Python. One typed core spans
hosted providers, routing hubs, existing local services, and a supervised `llama.cpp`
process; it also owns structured-output enforcement, context budgeting and reduction,
routing, telemetry, and capability provenance. Provider breadth is compatibility inventory,
not the product definition. A preset registry (`providers/presets.py`) covers eighty-six
OpenAI-compatible services and engines through one adapter. It is intended to replace the
bespoke provider layer an application would otherwise hand-roll.

Adding a provider: if it needs real protocol translation, write a dedicated adapter with a
`contracts/<id>.md` snapshot. If it only differs by endpoint, auth spelling, and quirks, add
a `CompatPreset` entry instead — and record its verification in
`contracts/openai-compat-presets.md`. Either way the procedure is
[contracts/NEW-PROVIDER.md](contracts/NEW-PROVIDER.md) — including when the addition is a
new embedding or reranking binding on a provider that already exists.

**Current status: implemented, pre-1.0.** [DESIGN.md](DESIGN.md) is the authoritative
architecture document — it carries the goals and non-goals, the ADRs, the open questions,
and the risk register. Read it before proposing or writing code. Do not contradict an ADR
or a stated non-goal without flagging it explicitly as a proposed reversal.

**Branch model:** `feature/*` → `develop` → `main`, both protected branches gated on the
aggregate `ci-ok` check. Merges to `main` rebuild the library distribution and a Linux
bundle; a version bump builds the full bundle matrix and cuts a GitHub Release. See
[docs/contributing/releasing.md](docs/contributing/releasing.md).

## Instruction authority and workstreams

This file is the single authoritative instruction set for Codex, Claude Code, GitHub
Copilot, and other coding agents. `CLAUDE.md` and `.github/copilot-instructions.md` are
discovery shims only: they point here and contain no independent engineering policy. A
tool-specific skill or prompt may adapt invocation syntax, but the procedure it runs must
live in one tool-neutral canonical file. Today three procedures follow that model:
`contracts/NEW-PROVIDER.md`, `contracts/DRIFT-CHECK.md`, and `docs/agents/INTEGRATION.md`
are authoritative; the Codex and Claude skills and the Copilot prompts beside each are thin
entry points.

**The same rule governs instruction text that ships outward.** Agent instructions this
project *emits* — `anyinfer agents-md`, the `llms.txt` pair built with the docs site, and
`docs/agents/INTEGRATION.md` with its three shims — are read in somebody else's
repository, where nothing here can correct them. So they are derived, never authored
twice: generated from the registry, the installed distribution metadata, and the package
version, or else a shim over a canonical file, and covered by the same shim tests. Two
consequences follow. Every generated artifact carries the version it was generated from,
so a reader can notice a stale one. And the no-ADR-identifiers rule applies with full
force: an outward artifact is the likeliest place for `ADR-NNN` to leak into a stranger's
codebase, so `tests/test_agent_instructions.py` asserts its absence from all of them.

Keep these product surfaces distinct:

| Workstream | Owned paths | Boundary |
|---|---|---|
| Core SDK / inference engine | `src/anyinfer/` except `cli.py` and `serve/` | Owns normalized types, orchestration, providers, routing, local inference, config, and public Python APIs. It never depends on a frontend. **Model and runtime acquisition live in `local/`, never in an adapter** — fetching weights is not protocol translation. |
| Demo application | `src/anyinfer_demo/`, `tests/demo_app/` | A reference integrator built on supported public APIs. It stays offline-capable with the fake provider and never becomes a second implementation of routing, validation, configuration, or telemetry. |
| One-shot CLI and operator commands | `src/anyinfer/cli.py`, CLI tests | Owns argument parsing, terminal presentation, and process exit codes for `init`, `agents-md`, `run`, `embed`, `rerank`, `compare`, `verify`, `benchmark`, `doctor`, `providers`, `models`, `runtime`, `context`, `conform`, `mcp`, and `serve`. `serve`'s parser lives here, but its semantics belong to the sidecar workstream. It delegates inference, reduction, and config semantics to public core APIs. Collection (filesystem walking for `context`) belongs here, never in `anyinfer.context`, and endpoint/credential discovery for `init` belongs in `anyinfer.local.discovery`. |
| OpenAI-compatible sidecar | `src/anyinfer/serve/`, sidecar tests | Owns the OpenAI wire codec and ASGI lifecycle, plus the operator-tooling renderer `service.py` (systemd/launchd/Windows units) that ships beside them — it emits text and imports nothing but `errors`, so it lives with the thing it starts rather than in the CLI. It stays a projection over `AsyncClient`; no provider, routing, validation, or config policy belongs here. The import-linter contract covers the whole package, so a new `serve/` module is inside the boundary the moment it exists. |
| Shared configuration | `src/anyinfer/config/`, configuration docs and tests | One versioned format feeds Python SDK callers, the CLI, the sidecar, and compatible demo settings. Frontends may add flags, but they must not fork file semantics. |

Cross-cutting changes must update every affected workstream in one change. In particular,
changes to shared configuration require SDK, CLI, sidecar, reference-doc, and example
coverage; branding changes require both `docs/assets/` and packaged demo assets; public API
changes require the generated reference and runnable examples.

## Architecture rules (condensed from the ADRs — read DESIGN.md §23 for rationale)

1. **The primitive is `GenerationRequest → typed event stream`** (ADR-001). Never make the
   OpenAI wire format the internal representation; it is one dialect at the edges.
2. **Adapters only translate** (ADR-003). Provider adapters expose exactly
   `list_models / health / generate(→events) / aclose`. Retry, fallback, schema validation,
   repair, timing, usage normalization, telemetry, and redaction live in the core — never in
   an adapter. If you find yourself adding control flow to an adapter, stop.
3. **Async core, sync facade** (ADR-002). New functionality is implemented async-first;
   the sync `Client` wraps via the background-loop facade. Never add sync-only paths.
4. **llama.cpp = supervised `llama-server` over loopback** (ADR-004). No `llama-cpp-python`.
5. **Capability data is provenance-tagged** (ADR-005): `catalog | discovered | probed |
   default`. Never present an estimated value as authoritative.
6. **Telemetry contract is typed in-process events** (ADR-006); OTel is a lazy optional
   bridge. Nothing is written to disk/network by default; events are payload-free by default.
7. **Slim core** (ADR-007): mandatory deps are `httpx2` + `jsonschema` only. New dependencies
   go behind extras and require justification. No official provider SDKs except
   `github-copilot-sdk` (extra).
8. **Providers register via frozen descriptors** (ADR-008) with declarative setup specs —
   never per-engine `if/elif` branches in core, config, or UI-facing code.
9. **The sidecar frontend is a wire codec, never a second core** (ADR-009). Its four M0
   invariants (request superset of OpenAI chat completions, event-stream sufficiency for
   chunk reconstruction, Target-in-model-string, concurrent streams) must not be broken by
   any core change.

## Coding conventions

- Python ≥ 3.11. Frozen `dataclasses` with `slots=True` for domain types; `typing.Protocol`
  for interfaces. **No pydantic dependency** (caller-supplied pydantic models are accepted as
  schema inputs via duck-typed `model_json_schema()` only).
- Errors: raise the shallow hierarchy in `anyinfer.errors` with structured fields
  (`provider`, `phase`, `retryable`, `retry_after_s`, `http_status`, `detail`, `hint`).
  `detail` must be bounded and pass redaction; `hint` is the actionable next step for users.
- Secrets: anything credential-shaped goes through `anyinfer.credentials` and is registered
  for redaction. Never log, print, or embed secrets in errors, events, or fixtures.
- Local servers bind `127.0.0.1` only unless `allow_remote_exposure=True`.
- Layout: `src/anyinfer/` per DESIGN.md §18. Tests are flat `tests/test_<area>.py` modules — an area is often a group of related adapters, so bedrock's tests live in `test_bedrock_vertex.py` — plus mirrored subpackages for `context/`, `anyinfer_demo/`, `mcp/`, and `testing/`. Grep for the symbol rather than guessing a path from the module name.

## Testing and documentation obligations

- **Two test tracks.** `workspace test` is the inner loop: the fast track, seconds, every
  adapter's own module and the whole core, skipping the `exhaustive` preset matrix and
  `slow` packaging builds. `workspace test --provider <id>` narrows to one provider's
  modules plus the invariants a provider change trips — editing one adapter does not need
  the rest exercised. `workspace check` is the gate and the only thing that says
  the suite passes; run it before committing. `test` cannot be made to run everything, on
  purpose.
- Every provider adapter must pass the shared conformance suite (`anyinfer.testing`) in
  cassette and fake-server modes; live mode is opt-in via real credentials. A new adapter PR
  includes: adapter, conformance run, its column in the conformance matrix (DESIGN.md §24),
  its **contract snapshot** in `contracts/`, and its provider docs page.
- Doc examples must run against the fake providers in CI — do not write examples that can't
  execute.
- Public symbols require docstrings; the docs build fails otherwise.
- **Documentation must not contradict itself.** A page that states a count (of concept
  pages, providers, error classes) or enumerates a set (an index table, a hierarchy
  diagram) must match the actual file tree and source — verify it, don't estimate it, and
  re-verify it whenever the thing it counts changes. When the same claim is deliberately
  restated in more than one file (README.md mirroring `docs/index.md`, a hand-written
  reference page next to its generated twin), treat every copy as one edit: grep for the
  other instances before considering the change done, and use identical wording where the
  claim is meant to be identical. Prefer a short curated list with a link to the canonical
  full index over hand-duplicating that index's contents — a link cannot drift the way a
  copied list can. A stale count or a self-contradictory claim is a documentation bug, not
  a style nit; it is exactly the kind of thing this project's own docs promise readers they
  can trust.
- **No ADR mentions in user-facing text.** `ADR-NNN` numbers are internal shorthand: they
  must not appear anywhere under `docs/`, in the root `README.md`, or in any public
  docstring (mkdocstrings renders those onto the published site). State the rule in plain
  words instead. ADR citations belong only in DESIGN.md, AGENTS.md, and internal code
  comments that never render.

## Provider contract snapshots and drift checking

`contracts/<provider>.md` records exactly what upstream protocol details AnyInfer
depends on per provider: endpoints, auth headers, version pins, request fields sent, response
fields read, streaming framing, and error-mapping inputs — each with a last-verified date.
Two snapshots are not inference providers: `contracts/huggingface.md` covers the weights
source model acquisition depends on, and `contracts/mcp.md` covers the Model Context
Protocol AnyInfer speaks to source tool definitions. Both are audited by the same procedure.

A snapshot is written **before** the adapter it specifies, as Step 1 of
[contracts/NEW-PROVIDER.md](contracts/NEW-PROVIDER.md) — the canonical, tool-agnostic
procedure for adding a provider, a preset, or a new embedding/rerank binding on an existing
provider. Its entry points follow the same shape as the drift check's below: the
`add-provider` skill (Codex `$add-provider`, Claude Code `/add-provider`), the
`add-provider` Copilot prompt, or the file itself.

These snapshots are then the input to the **provider drift check**, a semi-automated audit
that compares each snapshot against the provider's *current* public documentation and
changelogs:

- Procedure (canonical, tool-agnostic): [contracts/DRIFT-CHECK.md](contracts/DRIFT-CHECK.md)
- Scheduled: the weekly `contract-drift` workflow selects snapshots deterministically
  (`scripts/check_contract_drift.py`, never-live-verified first, then oldest) and runs the
  procedure against them. Needs no provider credentials — snapshots record what a provider
  publishes, not what an authenticated call returns.
- Codex: invoke the `check-provider-drift` skill (`$check-provider-drift`).
- Claude Code: invoke the `check-provider-drift` skill (`/check-provider-drift`).
- Copilot Chat: run the `check-provider-drift` prompt (`.github/prompts/`).
- Other agents: follow DRIFT-CHECK.md directly when asked to "check provider drift".

When you change an adapter's wire behavior, update its contract snapshot **in the same
change**. When a drift check finds upstream changes, propose contract/adapter/matrix updates
— do not silently rewrite snapshots without citing the upstream source.

## Things agents get wrong here — explicit warnings

- Do not "helpfully" swap raw httpx2 dialects for official provider SDKs.
- Do not add retry/backoff logic inside adapters (it belongs to the router).
- Do not collapse `Sourced[T]` provenance into bare values.
- Do not bundle llama-server binaries, GGUF files, or model weights into wheels or
  PyInstaller specs — they are runtime-fetched by design.
- Do not hand-edit a hash, size, revision, or `last_verified` date in
  `catalog/models.json`, `local/runtimes.json`, or `capabilities/pricing.json`. Those files
  are written by `scripts/pin_catalog.py`, `scripts/pin_runtimes.py`, and the pricing
  refresh, which read the values from upstream. An entry that cannot be verified is dropped,
  never shipped half-pinned.
- Do not add `huggingface_hub` (or any provider SDK) to reach a weights source. The Hugging
  Face HTTP API is spoken directly and recorded in `contracts/huggingface.md`; that scope is
  deliberately bounded to two endpoints and one download URL shape.
- Do not invent new top-level config keys; extend `ProviderSetupSpec` so UIs stay generic.
- Timestamps/dates in contracts and docs are real dates — never fabricate a
  "last-verified" date without actually verifying.
