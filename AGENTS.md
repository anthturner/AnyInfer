# AnyInfer — Agent Instructions

Canonical instructions for all AI coding agents (Codex, Claude Code, GitHub Copilot, and
others). Tool-specific files (`CLAUDE.md`, `.github/copilot-instructions.md`) defer here.

## What this project is

AnyInfer is an application-owned hybrid inference runtime for Python. One typed core spans
hosted providers, routing hubs, existing local services, and a supervised `llama.cpp`
process; it also owns structured-output enforcement, context budgeting and reduction,
routing, telemetry, and capability provenance. Provider breadth is compatibility inventory,
not the product definition. A preset registry (`providers/presets.py`) covers eighty-six
OpenAI-compatible services and engines through one adapter. AnyInfer replaces the bespoke
provider layers of three sibling projects: `../Frisket`, `../ModelFit`, `../mote-cli`.

Adding a provider: if it needs real protocol translation, write a dedicated adapter with a
`contracts/<id>.md` snapshot. If it only differs by endpoint, auth spelling, and quirks, add
a `CompatPreset` entry instead — and record its verification in
`contracts/openai-compat-presets.md`.

**Current status: implemented, pre-1.0.** [DESIGN.md](DESIGN.md) is the authoritative
architecture document; [NOTES.md](NOTES.md) is the running record of decisions (D1–D32),
assumptions, open questions, and risks. Read both before proposing or writing code. Do not
contradict a numbered decision or an ADR without flagging it explicitly as a proposed
reversal.

**Branch model:** `feature/*` → `develop` → `main`, both protected branches gated on the
aggregate `ci-ok` check. Merges to `main` rebuild release packages; a version bump cuts a
GitHub Release. See [docs/contributing/releasing.md](docs/contributing/releasing.md).

## Instruction authority and workstreams

This file is the single authoritative instruction set for Codex, Claude Code, GitHub
Copilot, and other coding agents. `CLAUDE.md` and `.github/copilot-instructions.md` are
discovery shims only: they point here and contain no independent engineering policy. A
tool-specific skill or prompt may adapt invocation syntax, but the procedure it runs must
live in one tool-neutral canonical file. Today the provider drift check follows that model:
`contracts/DRIFT-CHECK.md` is authoritative; the Codex and Claude skills and the Copilot
prompt are thin entry points.

Keep these product surfaces distinct:

| Workstream | Owned paths | Boundary |
|---|---|---|
| Core SDK / inference engine | `src/anyinfer/` except `cli.py` and `serve/` | Owns normalized types, orchestration, providers, routing, local inference, config, and public Python APIs. It never depends on a frontend. **Model and runtime acquisition live in `local/`, never in an adapter** — fetching weights is not protocol translation. |
| Demo application | `src/demo_app/`, `tests/demo_app/` | A reference integrator built on supported public APIs. It stays offline-capable with the fake provider and never becomes a second implementation of routing, validation, configuration, or telemetry. |
| One-shot CLI and operator commands | `src/anyinfer/cli.py`, CLI tests | Owns argument parsing, terminal presentation, and process exit codes for `run`, `doctor`, and `providers`. It delegates inference and config semantics to public core APIs. |
| OpenAI-compatible sidecar | `src/anyinfer/serve/`, sidecar tests | Owns only the OpenAI wire codec and ASGI lifecycle. It stays a projection over `AsyncClient`; no provider, routing, validation, or config policy belongs here. |
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
- Layout: `src/anyinfer/` per DESIGN.md §18. Tests mirror the package under `tests/`.

## Testing and documentation obligations

- Every provider adapter must pass the shared conformance suite (`anyinfer.testing`) in
  cassette and fake-server modes; live mode is opt-in via real credentials. A new adapter PR
  includes: adapter, conformance run, its column in the conformance matrix (DESIGN.md §24),
  its **contract snapshot** in `contracts/`, and its provider docs page.
- Doc examples must run against the fake providers in CI — do not write examples that can't
  execute.
- Public symbols require docstrings; the docs build fails otherwise.
- **No ADR mentions in user-facing text.** `ADR-NNN` numbers are internal shorthand: they
  must not appear anywhere under `docs/`, in the root `README.md`, or in any public
  docstring (mkdocstrings renders those onto the published site). State the rule in plain
  words instead. ADR citations belong only in DESIGN.md, NOTES.md, AGENTS.md, and internal
  code comments that never render.

## Provider contract snapshots and drift checking

`contracts/<provider>.md` records exactly what upstream protocol details AnyInfer
depends on per provider: endpoints, auth headers, version pins, request fields sent, response
fields read, streaming framing, and error-mapping inputs — each with a last-verified date.
One snapshot is not an inference provider: `contracts/huggingface.md` covers the weights
source model acquisition depends on, and is audited by the same procedure.

These snapshots are the input to the **provider drift check**, a semi-automated audit that
compares each snapshot against the provider's *current* public documentation and changelogs:

- Procedure (canonical, tool-agnostic): [contracts/DRIFT-CHECK.md](contracts/DRIFT-CHECK.md)
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
