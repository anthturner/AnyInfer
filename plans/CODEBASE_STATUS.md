# Codebase Status — AnyInfer

**Date:** 2026-08-25 · **As of:** commit `42e2106` on `main` · **Method:** six parallel code-first
reviews (organization, docs-vs-reality, docs quality, feature completeness, feature misses,
security), with high-severity claims independently re-verified against source. **The code was
treated as the source of truth throughout**; documentation claims were checked against it, never
the reverse.

**Updated 2026-08-25:** added §G (attestation implementation plan); converted to a living
tracker — per-item scores and checkboxes throughout.

**How to address items:** every finding has a stable index. `A`–`G` are the sections; `A.1`
is an item; `A.1.2` is a numbered remediation step inside that item. Cite an index (e.g. "fix
B.2", "do F.4.1 only") to scope a future cleanup. Line numbers are valid as of the commit above
and may drift; paths and symbol names are the durable anchors.

**Living document:** check off a step's `- [ ]` when it lands; flip the item's Status cell in
the tracker below to `[x]` when every step is done (note partial completion inline). If a fix
changes a finding's facts, edit the item's Long text and date the edit. New work gets the next
free index in its section — never reuse a retired index.

**Severity:** High = user-harming or trust-breaking today · Medium = will bite soon or misleads
· Low = polish, hygiene, or documented-tradeoff surfacing.

---

## Remediation tracker

**Scoring:** *Sev* maps each item's stated severity to a number (High=5, Medium-High=4,
Medium=3, Low-Medium/Medium-Low=2, Low=1). *Pri* is urgency and leverage per unit of effort
(5 = do now, 1 = whenever). *Score* = Sev × Pri; rows are sorted by Score, so the top of the
table is the work queue. **Batching hints:** the doc-drift items (B.2–B.5, B.7, D.7) are one
reconciliation pass — do them together and add the B.4.3 drift test so the class can't recur;
F.4 + F.9 + F.13 are one quick hygiene batch; A.1 is best done pre-1.0.

| Status | ID | Item | Sev | Pri | Score |
|---|---|---|---|---|---|
| `[x]` | B.1 | Sidecar docs deny endpoints the sidecar actually serves | 5 | 5 | 25 |
| `[x]` | F.2 | Relay ASGI app serves decrypted prompt IP with no authentication | 5 | 5 | 25 |
| `[x]` | G.1 | Attestation honest-claims pass (reword oversell, pin GPU parse) | 5 | 5 | 25 |
| `[x]` | B.6 | Error docs `missing_fields` → real attribute `missing_required` | 3 | 5 | 15 |
| `[ ]` | E.1 | Async batch inference APIs (OpenAI Batch, Anthropic Message Batches) | 5 | 3 | 15 |
| `[ ]` | F.1 | Tier 3 "attested execution" is detection, not attestation (→ plan §G) | 5 | 3 | 15 |
| `[x]` | F.3 | Demo app persists literal API keys despite "memory only" guarantee | 3 | 5 | 15 |
| `[x]` | F.4 | Confidential CLI writes private keys with default file permissions | 3 | 5 | 15 |
| `[ ]` | G.4 | CPU attestation-quote verification behind the `attest` extra | 5 | 3 | 15 |
| `[x]` | B.2 | Conformance matrix mislabels implemented embeddings (3 providers) | 3 | 4 | 12 |
| `[x]` | B.3 | CLI subcommand enumerations stale in AGENTS.md and DESIGN.md | 3 | 4 | 12 |
| `[x]` | B.4 | DESIGN.md §18 package layout has drifted from the tree | 3 | 4 | 12 |
| `[x]` | B.5 | Stale counts: matrix header, adapter list, "other twenty", "about ten" | 3 | 4 | 12 |
| `[x]` | C.2 | First-call code snippets are not copy-paste runnable | 3 | 4 | 12 |
| `[x]` | D.1 | Sidecar `/v1/embeddings` rejects the OpenAI SDK's default encoding | 3 | 4 | 12 |
| `[x]` | D.2 | `reasoning_effort` is unreachable through the sidecar | 3 | 4 | 12 |
| `[x]` | D.3 | No repair config for serve; config `context` block ignored | 3 | 4 | 12 |
| `[ ]` | E.2 | Typed `seed` / `logprobs` / penalty sampling controls | 4 | 3 | 12 |
| `[ ]` | G.2 | Demand gate: identify a confidential-tier design partner | 3 | 4 | 12 |
| `[ ]` | G.3 | CC hardware validation sprint (rent, capture, fixture) | 4 | 3 | 12 |
| `[ ]` | A.1 | `AsyncClient` god-module split | 3 | 3 | 9 |
| `[ ]` | C.1 | No API reference for the confidential add-on packages | 3 | 3 | 9 |
| `[ ]` | E.5 | OpenAI Responses API endpoint on the sidecar | 3 | 3 | 9 |
| `[ ]` | E.6 | Ship accurate token estimators behind the existing protocol | 3 | 3 | 9 |
| `[ ]` | F.5 | Sealed-template license gating: tripwire vs lock (fix or re-scope claim) | 3 | 3 | 9 |
| `[ ]` | G.5 | Claims and docs update once quote verification lands | 3 | 3 | 9 |
| `[ ]` | E.3 | Provider-native server-side tools (web search, code execution) | 4 | 2 | 8 |
| `[ ]` | E.4 | Typed citations / grounded-generation output | 3 | 2 | 6 |
| `[ ]` | E.9 | Explicit proxy / custom CA / mTLS configuration | 2 | 3 | 6 |
| `[ ]` | A.6 | Fix the "tests mirror the package" AGENTS.md claim | 1 | 5 | 5 |
| `[x]` | F.9 | `catalog-refresh` workflow write scope on its read-only job | 1 | 5 | 5 |
| `[x]` | F.13 | Loose `COHERE.key` credential file in the working tree | 1 | 5 | 5 |
| `[x]` | A.3 | `serve/service.py` workstream boundary + import-linter scope | 1 | 4 | 4 |
| `[ ]` | B.7 | Extras/snapshot enumerations incomplete (`mcp` extra, `contracts/mcp.md`) | 1 | 4 | 4 |
| `[ ]` | C.3 | Add-on install story contradicts itself (PyPI vs checkout) | 1 | 4 | 4 |
| `[ ]` | E.7 | Video input parts | 2 | 2 | 4 |
| `[ ]` | E.8 | Runtime credential rotation / hot reload | 2 | 2 | 4 |
| `[x]` | F.8 | Third-party GitHub Actions pinned to mutable tags | 1 | 4 | 4 |
| `[ ]` | G.7 | Nitro Enclaves decision (resolve or explicitly defer) | 2 | 2 | 4 |
| `[ ]` | A.4 | Generic top-level `demo_app` package ships in the core wheel | 1 | 3 | 3 |
| `[ ]` | C.5 | `installation.md` breaks the guide skeleton and dead-ends | 1 | 3 | 3 |
| `[ ]` | C.7 | README routes readers through retired redirect URLs | 1 | 3 | 3 |
| `[ ]` | D.4 | Sidecar silently swallows `n>1`, never projects logprobs back | 1 | 3 | 3 |
| `[ ]` | D.5 | `ConfidentialityReport` has no producer anywhere | 1 | 3 | 3 |
| `[ ]` | D.7 | DESIGN.md's open-decisions ledger drift (both directions) | 1 | 3 | 3 |
| `[ ]` | E.12 | Shipped logging/JSONL sink for the telemetry stream | 1 | 3 | 3 |
| `[x]` | F.6 | Sidecar has no request-body size limit | 1 | 3 | 3 |
| `[x]` | F.7 | Config-controlled URLs (SSRF / `file://`) trust assumption undocumented | 1 | 3 | 3 |
| `[ ]` | F.12 | SECURITY.md canonical org/domain diverges across the repo | 1 | 3 | 3 |
| `[ ]` | G.6 | GPU SPDM attestation (explicitly deferred; state the ceiling) | 3 | 1 | 3 |
| `[ ]` | A.2 | `cli.py` is a 3,776-line single module | 1 | 2 | 2 |
| `[ ]` | A.5 | Root-of-package module sprawl in `anyinfer/` | 1 | 2 | 2 |
| `[ ]` | C.4 | Provider pages drift from their own skeleton at the edges | 1 | 2 | 2 |
| `[ ]` | C.6 | Nav labels and page H1s diverge on ~17 pages | 1 | 2 | 2 |
| `[ ]` | C.8 | Glossary omits load-bearing terms | 1 | 2 | 2 |
| `[ ]` | C.9 | No changelog or upgrade-notes surface | 1 | 2 | 2 |
| `[ ]` | D.6 | Demo app never touches arena, compare, or run manifests | 1 | 2 | 2 |
| `[ ]` | E.10 | Entry-point extensibility beyond provider adapters | 1 | 2 | 2 |
| `[ ]` | E.11 | Local model store disk budget / guided eviction | 1 | 2 | 2 |
| `[ ]` | F.10 | Redaction is exact-substring only | 1 | 2 | 2 |
| `[ ]` | F.11 | Model-weight verification load-time TOCTOU window | 1 | 2 | 2 |
| `[ ]` | A.7 | Demo `MainWindow` is an 88-method single class | 1 | 1 | 1 |
| `[ ]` | E.13 | Non-goals worth a deliberate revisit (decision log, not a defect) | — | — | — |

---

# A. Codebase technical state

## A.0 Overall assessment

**Verdict: excellent, with debt concentrated in two oversized modules.** The declared
architecture (AGENTS.md workstreams, ADR-001..009) matches the code almost everywhere, and —
rarely seen — the two hardest boundaries are *mechanically enforced*: `pyproject.toml:225-298`
carries four import-linter contracts run in CI codifying "adapters never orchestrate"
(ADR-003), "sidecar is a codec around the client" (ADR-009), leaf types, and context-reduction
isolation. Verified strengths:

- **Adapters genuinely only translate.** Zero retry/backoff loops in
  `src/anyinfer/providers/*.py`; shared helpers (`http.py`, `sse.py`, `eventstream.py`,
  `_multimodal.py`) keep dialect adapters tiny (`deepseek.py` 178 lines, `xai.py` 220).
- **Slim-core claim is exact.** `dependencies = ["httpx2>=2.0", "jsonschema>=4.21"]`; every
  extra carries a justification comment; core never imports Qt or the sub-packages.
- **Conventions hold under sampling.** 211 `@dataclass(frozen=True, slots=True)` occurrences,
  22 `Protocol` interfaces, the structured error fields exactly as declared, the documented
  background-loop sync facade.
- **No dead code found.** AST import-graph scan produced only false positives (lazy string
  registration, package re-exports).
- **Monorepo sharding convention followed.** `anyinfer-store/-confidential/-shared` are
  standalone sub-projects depending on published `anyinfer>=0.1.0`, not root build entries.

The findings below are about *concentration and bookkeeping*, not boundary violations. No
high-severity findings in this section.

## A.1 `AsyncClient` is a 4,186-line god-module

**Severity:** Medium · **Confidence:** High
**Paths:** `src/anyinfer/_client/async_client.py`

**Brief:** The async client is a facade in name but hosts nearly all generation orchestration,
spend, cache, arena, and store logic inline in one 89-method class.

**Long:** `class AsyncClient` (line 262 → ~3888) contains routed generation execution
(`_routed_stream`, `_route_events`, `_run_attempt` — the last a ~275-line method), arena
fan-out, compare, spend governance, cache planning, context compaction, model-store
operations, and verification/benchmark entry points. Delegation seams already exist and work
(`embed`/`rerank` dispatch to `_client/operations.py`; verify/benchmark import from their own
modules), so this is drift, not design. DESIGN.md §18 itself envisioned `_client/` containing
a `stream.py` that was never split out (`AsyncStream` sits at line 4104 of the same file).
Any change to retries, spend, caching, or arena means editing this one file — it is the main
navigability tax in the codebase.

**Remediation** (mechanical moves; `tests/test_routing.py`, `test_arena.py`,
`test_spend_ledger.py`, `test_sync_client.py` are the net):
- [ ] **A.1.1** Extract `_run_attempt` / `_route_events` / `_routed_stream` + private helpers into
  `_client/generation.py` (or `routing/execute.py`), keeping `AsyncClient` as the composing
  facade.
- [ ] **A.1.2** Move `AsyncStream` (and stream helpers) into `_client/stream.py`, matching the
  layout §18 already promises.
- [ ] **A.1.3** Move arena execution methods into `_client/arena_exec.py`; move spend-check
  helpers beside `capabilities/ledger.py`.
- [ ] **A.1.4** Update DESIGN.md §18's `_client/` listing to the resulting real layout (do with
  B.4).

## A.2 `cli.py` is a 3,776-line single module

**Severity:** Low · **Confidence:** High
**Paths:** `src/anyinfer/cli.py`

**Brief:** The CLI honors its boundary (imports only public core surfaces, no `_client`
reach-ins) but concentrates 16 command families in one file.

**Long:** ~120 top-level defs/classes/parsers covering init, run, serve, verify, benchmark,
doctor, providers, models (5 sub-subcommands), runtime (3), context, mcp, conform,
embed/rerank, compare/diff. AGENTS.md/DESIGN §18 decree a single `cli.py`, so this is
sanctioned, and the lazy per-command import style keeps startup cheap. Delegation quality is
good — the issue is purely bulk, second-largest module in the repo.

**Remediation:**
- [ ] **A.2.1** Either: convert to a `cli/` package (`cli/__init__.py` keeps `main` so
  `[project.scripts] anyinfer = "anyinfer.cli:main"` is untouched), one module per command
  family.
- [ ] **A.2.2** Or: record the single-file rule as a deliberate decision in DESIGN.md §18 so the
  size is a documented choice rather than an accident. Pick one; A.2.1 preferred if the file
  keeps growing.

## A.3 `serve/service.py` sits outside its declared workstream and its import-linter contract

**Severity:** Low · **Confidence:** High
**Paths:** `src/anyinfer/serve/service.py`, `pyproject.toml:246-262`, `AGENTS.md:62`

**Brief:** A 682-line operator-tooling module (systemd/launchd/Windows service rendering)
lives in `serve/` even though AGENTS.md restricts `serve/` to "the OpenAI wire codec and ASGI
lifecycle" and assigns operator commands to the CLI workstream.

**Long:** The module is well-behaved (pure rendering, imports only `..errors.ConfigError`),
but the import-linter sidecar contract names only `anyinfer.serve.openai_codec` and
`anyinfer.serve.app` as sources, so `service.py` and `embeddings_codec.py` sit outside the
mechanical enforcement — nothing would catch them importing `anyinfer.providers` tomorrow.

**Remediation:**
- [x] **A.3.1** Change the import-linter contract's `source_modules` to `["anyinfer.serve"]` so
  every present and future serve module is covered (cheap, do regardless).
- [x] **A.3.2** Either move `service.py` under CLI ownership, or amend the AGENTS.md sidecar row
  to name service-definition rendering as owned. Amending the row is the smaller change.

## A.4 Generic top-level `demo_app` package ships in the core wheel

**Severity:** Low · **Confidence:** High
**Paths:** `pyproject.toml:98-102`, `src/demo_app/`

**Brief:** Every `pip install anyinfer` installs a top-level `demo_app` package — precisely
the generic-name collision risk the same file articulates and rejects for `workspace` three
lines earlier.

**Long:** `packages = ["src/anyinfer", "src/demo_app"]`. The comment above it refuses to ship
`workspace.py` because "a wheel that installs a generic top-level `workspace` module would
collide with unrelated distributions." `demo_app` is an equally plausible name for another
distribution's package; a collision corrupts whichever installs second. The wheel also
carries Qt widget code and SVG assets SDK users never need. (Import-time behavior is fine:
`demo_app/__init__.py` guards missing PySide6 with an actionable hint.)

**Remediation:**
- [ ] **A.4.1** Rename the shipped package to `anyinfer_demo` (update
  `[project.scripts] anyinfer-demo`, imports in `tests/demo_app/`, docs references), **or**
- [ ] **A.4.2** Split it into an `anyinfer-demo` sub-project per the existing monorepo sharding
  convention (it already has the shape: own entry point, own extra, own test tree).

## A.5 Root-of-package module sprawl in `anyinfer/`

**Severity:** Low · **Confidence:** Medium
**Paths:** `src/anyinfer/*.py`

**Brief:** New features have been landing as flat root modules (`arena.py`, `compare.py`,
`compare_diff.py`, `manifest.py`, `redaction.py`, `context_request.py`, plus `_`-prefixed
glue) rather than in the subpackage taxonomy the layout defines.

**Long:** Individually each module is coherent and imported by real consumers; the pattern is
drift. `compare.py`/`compare_diff.py`/`arena.py` form a de-facto "evaluation" area with no
package; `context_request.py` sits beside the `context/` package it relates to. A newcomer
cannot tell curated-public from internal glue at the root except by the underscore.

**Remediation:**
- [ ] **A.5.1** When convenient (pre-1.0 is the moment): group arena/compare/compare_diff into an
  `anyinfer/evaluate/` package; fold `context_request.py` into `context/` or `types/`.
- [ ] **A.5.2** Record the surviving root modules in DESIGN.md §18 (do with B.4). Low urgency.

## A.6 Tests do not mirror the package as AGENTS.md claims

**Severity:** Low · **Confidence:** High
**Paths:** `tests/`, `AGENTS.md:106`

**Brief:** AGENTS.md says "Tests mirror the package under `tests/`"; reality is ~100 flat
`test_*.py` files with only four mirrored subdirectories (`context/`, `demo_app/`, `mcp/`,
`testing/`).

**Long:** Coverage itself is broad — targeted cross-checks found no untested core module
(`embeddings_codec` via `test_serve_embeddings.py`, `m365_copilot` via
`test_hosted_adapters.py`, etc.). The harm is discoverability (bedrock's tests live in
`test_bedrock_vertex.py`) and that the instruction is false as written, which trains agents to
distrust the instruction file.

**Remediation:**
- [ ] **A.6.1** Amend AGENTS.md:106 to describe the real convention ("flat `test_<area>.py`
  modules plus mirrored subpackages for context/demo_app/mcp/testing"). Physically re-nesting
  ~100 files buys little; do not do it just for the claim.

## A.7 Demo `MainWindow` is an 88-method single class

**Severity:** Low · **Confidence:** High
**Paths:** `src/demo_app/main_window.py`

**Brief:** The demo's central window (1,544 lines, ~88 methods) concentrates wiring, state,
and handlers for every panel, out of step with the otherwise fine-grained widget decomposition
around it.

**Long:** Classic Qt failure mode, and demo code, so stakes are low. The boundary that matters
holds: all inference goes through the public `Client` via `engine.py`, widgets never touch
`anyinfer` directly. The cost is that the reference application's most-read file is its least
readable.

**Remediation:**
- [ ] **A.7.1** Optional: extract per-panel controllers (chat, telemetry, models) the way
  `widgets/models_dialog/` already splits its panels. Acceptable as-is for a demo.

---

# B. Reality vs documentation posture

## B.0 Overall posture

**Verdict: unusually trustworthy, with drift concentrated in countable prose.** ~75 concrete
claims were verified against code; ~85-90% held exactly. Verified accurate: the 86-preset and
20-adapter counts (exact, consistent across five files); the error catalog's 18-class
hierarchy, structured fields, and every documented config key against the parser; all
mkdocstrings identifiers across 17 reference pages resolving; contract snapshots existing for
all 20 adapters with honest, non-fabricated dates; zero `ADR-` strings in user-facing text
with the enforcing test present; ADR-004/006/007 all holding in code. The failures below are
almost all *growth the prose never re-counted* — written before the retrieval adapters,
presets matrix rows, and new CLI commands landed. One finding (B.1) actively harms users; the
rest mislead agents and reconcilers.

## B.1 Sidecar docs deny endpoints the sidecar actually serves

**Severity:** High · **Confidence:** High (re-verified directly)
**Paths:** `docs/serve/README.md:62-70` vs `src/anyinfer/serve/app.py:282-288`; contradicted
by `docs/concepts/embeddings.md:124-126`, `docs/guides/comparing-targets.md:84`

**Brief:** The sidecar's canonical reference page enumerates three endpoints and states
"Embeddings and generated image/audio outputs are out of scope," while the code registers six
routes including a fully implemented `POST /v1/embeddings`, `POST /v1/anyinfer/rerank`, and
`POST /v1/anyinfer/compare` — which two *other* doc pages correctly describe.

**Long:** This is the worst kind of drift: a false negative on the product's canonical page.
A reader of `docs/serve/README.md` will conclude embedding traffic must go elsewhere, when
`serve/app.py:212-263` implements complete, tested codecs. The repository violates its own
"documentation must not contradict itself" rule (AGENTS.md:126-135) — the concepts page and
the comparing-targets guide already document the true behavior.

**Remediation:**
- [x] **B.1.1** Add rows to `docs/serve/README.md`'s "What It Serves" table for
  `POST /v1/embeddings`, `POST /v1/anyinfer/rerank`, `POST /v1/anyinfer/compare`.
- [x] **B.1.2** Rewrite the exclusion sentence to scope it to generated image/audio *outputs*
  only, linking `concepts/embeddings.md`.

## B.2 Conformance matrix labels implemented embeddings "declared unsupported" (3 providers)

**Severity:** Medium · **Confidence:** High
**Paths:** `docs/reference/conformance-matrix.md` vs `src/anyinfer/providers/lm_studio.py`,
`gemini.py`, `llama_cpp.py`; harnesses in `tests/test_cohere_lmstudio.py`, `test_gemini.py`,
`test_llama_cpp.py`

**Brief:** The generated matrix — pitched as "generated from executed tests," and DESIGN R2's
declared source of truth — shows `➖` ("declared unsupported") for lm-studio, gemini, and
llama-cpp embeddings, yet all three adapters implement embeddings, declare
`operations={"generation","embedding"}` on their descriptors, and have dedicated passing
tests.

**Long:** Root cause is harness coverage, not code: the shared conformance harnesses'
`Capabilities` default `embedding=False`, and the embedding tests for these three providers
live *outside* the harness (e.g. `test_cohere_lmstudio.py:690`; llama-cpp's harness comment at
`test_llama_cpp.py:919-923` says "covered by the dedicated tests above rather than claimed
here"). The published matrix therefore tells users three providers can't embed when shipped
code actively routes embeddings to them — and README.md:204-206 plus the provider pages
contradict the matrix. A user choosing an embedding target from the matrix would wrongly rule
them out.

**Remediation:**
- [ ] **B.2.1** Not taken in favour of B.2.2. llama-cpp's harness cannot honestly claim
  embeddings — they need a server started with `--embeddings`, a *different* resident
  server for the same model — so a shared-harness flag would misrepresent it, and the
  same "the proof lives next door" shape covers all three. B.2.2's 🔗 glyph makes that
  state legible instead of collapsing it onto ➖. Still worth doing later as extra
  coverage; it is no longer needed to fix the mislabeling. *(2026-08-25)*
- [x] **B.2.2** Alternatively (or additionally), add a third matrix glyph ("✅ via dedicated
  tests") emitted from an explicit harness annotation, so `➖` stops covering two different
  truths.
- [x] **B.2.3** Regenerate with `python workspace.py matrix`.

## B.3 CLI subcommand enumerations stale in AGENTS.md and DESIGN.md

**Severity:** Medium · **Confidence:** High
**Paths:** `AGENTS.md:61`, `DESIGN.md:836-837` vs `src/anyinfer/cli.py`

**Brief:** AGENTS.md's CLI workstream row enumerates 10 subcommands; `cli.py` registers 16
(adds `serve`, `embed`, `rerank`, `compare`, `conform`, `mcp`). DESIGN §18 has a *different*
stale list missing `embed`/`rerank`/`compare` — two authoritative files disagreeing with the
code and with each other.

**Long:** AGENTS.md is the file agents are told to trust for ownership boundaries, and its own
rule says enumerated sets must match source. An agent adding an embed-related CLI flag today
cannot tell from the instruction files that the command exists.

**Remediation:**
- [x] **B.3.1** Update AGENTS.md:61 to the full 16-command list (note that `serve`'s parser lives
  in cli.py while its semantics belong to the sidecar workstream).
- [x] **B.3.2** Update DESIGN.md:836-837 to add `embed`, `rerank`, `compare`.

## B.4 DESIGN.md §18 package layout has drifted from the tree

**Severity:** Medium · **Confidence:** High
**Paths:** `DESIGN.md:804-850` vs `src/anyinfer/`, `pyproject.toml`

**Brief:** The layout section AGENTS.md declares normative ("Layout: `src/anyinfer/` per
DESIGN.md §18") describes a materially smaller codebase: it omits three shipped adapters
(`jina.py`, `voyage.py`, `tei.py`) plus `confidential_execution.py` and six provider helpers;
omits root modules `arena.py`, `compare.py`, `compare_diff.py`, `manifest.py`, `redaction.py`,
`context_request.py`; lists a `_client/stream.py` that never existed; lists `serve/` as three
files (real: five); and its extras enumeration omits `attest`.

**Long:** Agents are directed to read DESIGN.md before writing code; following §18 today, an
agent would misplace new stream helpers and miss that shared adapter helpers already exist in
`providers/http.py`/`eventstream.py`. This matters more here than in most projects because
AGENTS.md makes stale enumerations an explicit bug class.

**Remediation:**
- [x] **B.4.1** Regenerate §18 from the tree (one `find src/anyinfer -name '*.py'` pass), including
  the `providers/` helper modules and the real root-module list.
- [x] **B.4.2** Add `[attest]` to §18's extras enumeration (DESIGN.md:845-848).
- [x] **B.4.3** Consider a test in the style of `tests/test_agent_instructions.py` that diffs
  §18's file list against the tree, so the layout can never silently drift again.

## B.5 Stale counts: matrix header, adapter list, "other twenty", "about ten classes"

**Severity:** Medium (aggregate) · **Confidence:** High

**Brief:** Four independent countable claims are wrong, all with the same root cause — prose
written before later growth, never re-counted.

**Long / sub-items** (each independently addressable):
- [x] **B.5.1** *"The twenty that speak HTTP"* — `workspace.py:1002-1006` (`_MATRIX_HEADER`, baked
  into the generated `docs/reference/conformance-matrix.md:8-13`) claims twenty HTTP-transport
  rows; the table has 24 rows of which 22 use HTTP fakes. DESIGN.md:1356-1358 makes the same
  claim scoped to the 20 dedicated adapters, where "twenty HTTP + copilot + llama-cpp" is
  arithmetically impossible. Fix: derive the count at render time or reword to a non-count in
  both places; regenerate.
- [x] **B.5.2** *Nineteen adapters enumerated as twenty* — DESIGN.md:1349-1352 says "Twenty
  dedicated adapters (the original nine plus …)" and then names only ten more; Nebius is
  missing from the parenthetical. Fix: add "Nebius Token Factory" to the list.
- [x] **B.5.3** *"The other twenty"* — AGENTS.md:113-114 and `docs/contributing/testing.md:32` both
  say editing one of 20 adapters spares "the other twenty." Fix: "the other nineteen" or
  reword to "the rest" in both files (identical wording per the repo's own duplication rule).
- [x] **B.5.4** *"About ten classes"* — `docs/reference/errors.md:7` says the hierarchy is "about
  ten classes"; `errors.py` exports 18, and the page's own diagram (lines 26-45) draws all 18.
  Fix: "eighteen classes" or drop the number.

## B.6 Error docs reference `error.missing_fields`; the attribute is `missing_required`

**Severity:** Medium · **Confidence:** High (re-verified directly)
**Paths:** `docs/reference/errors.md:266` vs `src/anyinfer/errors.py:277,287,296`

**Brief:** The error catalog's "How to fix" tip tells users to inspect
`error.missing_fields`; the real `SchemaViolationError` attribute is `missing_required`, so
following the docs raises `AttributeError`.

**Long:** The one API-shape falsehood in an otherwise exactly-accurate error catalog. It
appears in a debugging tip, so it gets copy-pasted at the worst possible moment — while
handling a failure.

**Remediation:**
- [x] **B.6.1** Change `error.missing_fields` → `error.missing_required` at
  `docs/reference/errors.md:266`.

## B.7 Extras and snapshot enumerations incomplete (`mcp` extra, `contracts/mcp.md`)

**Severity:** Low · **Confidence:** High

**Brief / sub-items:**
- [ ] **B.7.1** `docs/guides/installation.md:13-23`'s extras table omits the `mcp` extra, which
  `pyproject.toml` defines and `docs/guides/tool-loop.md:103` instructs users to install.
  Fix: add a `mcp` row ("nothing installed — feature marker; see the tool-loop guide").
- [ ] **B.7.2** AGENTS.md:147 and `contracts/README.md:32-34` say "*One* snapshot is not an
  inference provider" (huggingface.md); `contracts/mcp.md` exists and self-describes as the
  second. Fix: "Two snapshots…" in AGENTS.md; add an mcp.md bullet to contracts/README.md.

---

# C. Quality of documentation

## C.0 Overall quality

**Verdict: top-decile for a pre-1.0 project — grade A-.** The 2026-08 overhaul worked: one
voice across ~100 pages, a coherent reader-need architecture, zero broken relative links, zero
stale TODO/"coming soon" markers, and honest scoping throughout ("detection, not cryptographic
attestation"; "Not millions; not billions"). Verified strengths: every one of the 209 public
exports has a mkdocstrings directive (422 total, all resolving); nav and disk are in perfect
sync with build-time redirect validation; every example states its offline/credentials story
and is exercised in CI; the reference pages are real reference (field contracts, generated
dated matrix, 526 lines of worked config cases); first-class agent-facing docs (`llms.txt`
pair generated from the built nav with size budgets and leak checks); uniform page skeletons
(17/17 guides, 18/18 concepts carry Key Takeaways + See Also). The findings are polish at the
margins; C.1 and C.2 are the two worth scheduling.

## C.1 No API reference for the confidential add-on packages

**Severity:** Medium · **Confidence:** High
**Paths:** `docs/guides/confidentiality-tiers.md`, `docs/reference/api/` (absent page);
precedent: `docs/reference/api/vector-store.md`

**Brief:** The vector-store add-on got a generated mkdocstrings reference page; the
confidential and shared add-ons did not — a shipped, headline-marketed feature's signatures
(`TemplateVault`, `Relay`, `RelayRegistry`, `ConfidentialityReport`, ~10 more) are documented
only inside one guide's prose.

**Long:** A developer implementing Tier 1-2 has nowhere to look up `TemplateVault`'s
constructor options (`revocation_checker`, `revocation_fail_closed` are mentioned in passing)
or what fields `ConfidentialityReport` carries; the subpackage READMEs defer to "DESIGN.md
§30", an internal design record. The in-repo pattern for solving this already exists, so the
absence reads as oversight, not decision.

**Remediation:**
- [ ] **C.1.1** Add `docs/reference/api/confidential.md` with mkdocstrings directives for
  `anyinfer_confidential` and `anyinfer_shared` public names, mirroring vector-store.md's
  framing; add to the SDK Reference nav.
- [ ] **C.1.2** Link it from confidentiality-tiers.md's See Also; point the subpackage READMEs at
  it instead of DESIGN.md §30.

## C.2 First-call code snippets are not copy-paste runnable

**Severity:** Medium · **Confidence:** High
**Paths:** `README.md:31`, `docs/index.md:21,33`, `docs/guides/quickstart.md:38,57,109,152`

**Brief:** The very first code a new user meets — README, homepage, quickstart — raises
`NameError` when pasted: `text`/`prompt` are free variables the CI harness supplies.

**Long:** Deliberate style (keep the snippet about the API), but the quickstart's own framing
is "from `pip install` to a working result," and it promises "every example on this page is
executed in CI… so none of it can quietly rot" — true for the harness, not for the reader's
paste. Every downstream example page gets this right by being a complete program; only the
entry-path fragments have the gap.

**Remediation:**
- [x] **C.2.1** In README.md, docs/index.md, and quickstart's "Your First Call" only, define the
  input inline (one-line literal or `open("release-notes.txt").read()`). Later quickstart
  sections may keep free variables once the pattern is established.

## C.3 Add-on install story contradicts itself (PyPI vs source checkout)

**Severity:** Low · **Confidence:** High
**Paths:** `docs/guides/installation.md:45-47` vs `docs/guides/confidentiality-tiers.md:36`,
`docs/guides/vector-store.md`, `docs/examples/semantic-search.md`

**Brief:** installation.md honestly says the add-on packages install from a repository
checkout "until a first PyPI release ships," but the confidentiality guide shows a bare
`pip install "anyinfer-confidential[relay]"` that will fail against PyPI, and the vector-store
guide / semantic-search example teach `anyinfer_store` as if a pip install away.

**Remediation:**
- [ ] **C.3.1** Add a one-line "ships as a separate package; install from a checkout for now" note
  (linking installation.md's section) to confidentiality-tiers.md, vector-store.md, and
  semantic-search.md.
- [ ] **C.3.2** When the packages hit PyPI, delete all four caveats in one commit.

## C.4 Provider pages drift from their own skeleton at the edges

**Severity:** Low · **Confidence:** High
**Paths:** `docs/providers/*.md` (esp. `vertex.md`)

**Brief:** The provider skeleton (lede → badges → Setup → features → Wire Contract) holds for
the spine, but: vertex.md is the only adapter page with no `## Wire Contract` section; `## See
Also` appears on 9 of 20 adapter pages and is absent from the 11 most-visited ones; a
`## Supported` table appears on only 7.

**Remediation:**
- [ ] **C.4.1** Add `## Wire Contract` to vertex.md.
- [ ] **C.4.2** One rule for See Also: add to the 11 lacking it or remove from the 9 that have it.
- [ ] **C.4.3** Optional: a Supported table on every adapter page for cross-provider scanning.

## C.5 `installation.md` breaks the guide skeleton and dead-ends

**Severity:** Low · **Confidence:** High
**Paths:** `docs/guides/installation.md`

**Brief:** The only non-index guide without Key Takeaways or See Also, ending at "Verify the
Install" with no onward link — the one gap in the site's otherwise careful next-step trail.

**Remediation:**
- [ ] **C.5.1** Append a See Also (quickstart, configuration, providers) and a Key Takeaways tip,
  matching the other 17 guides.

## C.6 Nav labels and page H1s diverge on ~17 pages

**Severity:** Low · **Confidence:** High
**Paths:** `mkdocs.yml` nav vs page H1s (e.g. `docs/guides/streaming.md`, `cli.md`,
`demo-app.md`, `reference/api/serve.md`, `contributing/automation.md`)

**Brief:** Roughly one page in six is named differently in the sidebar than at the top of the
page ("Stream Typed Events" vs "Stream to a Terminal"; "Reference Application" vs "The Pack-In
Demo Application"), taxing search and cross-link lookup.

**Remediation:**
- [ ] **C.6.1** For the semantically different pairs (streaming, cli, demo-app, api/serve,
  automation, vector-store, python-sdk), converge either direction. Leave pure abbreviations
  alone.

## C.7 README routes readers through retired redirect URLs

**Severity:** Low · **Confidence:** High
**Paths:** `README.md:59,113-114,229` vs `scripts/mkdocs_hooks.py:50-51` (REDIRECTS map)

**Brief:** The README links `guides/when-to-use/` and `guides/integration-paths/` — both
redirect stubs for merged pages — and in one spot uses the retired and canonical URL for the
same content three lines apart.

**Remediation:**
- [ ] **C.7.1** Replace with canonical URLs (`why-anyinfer/`, `guides/`), adjusting link text where
  the target is now a section rather than a page.
- [ ] **C.7.2** Grep first-party files (README, `docs/agents/INTEGRATION.md`, skills, contracts)
  for the other REDIRECTS keys in the same pass.

## C.8 Glossary omits load-bearing terms

**Severity:** Low · **Confidence:** Medium
**Paths:** `docs/reference/glossary.md`

**Brief:** 23 well-crafted entries, but missing the vocabulary the site leans on hardest:
Preset, Run Manifest, Session, Arena, Reduction, Extra, Confidentiality Tier.

**Remediation:**
- [ ] **C.8.1** Add ~6 card entries (one sentence + canonical-page link each) following the
  existing card/anchor pattern.

## C.9 No changelog or upgrade-notes surface

**Severity:** Low · **Confidence:** Medium
**Paths:** absent `CHANGELOG*`; `README.md:255-256`

**Brief:** A project that warns "the public API may still move before 1.0" gives upgraders no
in-docs record of what moved; GitHub Releases are the only change record and the docs never
say so explicitly.

**Remediation:**
- [ ] **C.9.1** Either add a short `docs/reference/changelog.md` linking each GitHub Release and
  recording API-visible changes only, or add one line to reference/README.md's API Stability
  section declaring GitHub Releases the canonical change record.

---

# D. Completeness of current features

## D.0 Overall completeness

**Verdict: unusually finished for its size.** Zero TODO/FIXME/XXX/HACK markers across all four
packages in `src/`; the only `NotImplementedError`s are deliberate scaffolding. Every M0–M5
milestone in DESIGN.md §19 is materially delivered; the executed conformance matrix shows zero
failing cells. Verified complete end-to-end: embeddings/rerank (core + CLI + sidecar + demo
panel), the tool loop on both facades, sessions, arena/compare/compare_diff (core + CLI +
sidecar extensions), run manifests (opt-in on all three response surfaces + CLI trace),
benchmark, the verification probe, multimodal inputs (no adapter silently drops parts — each
encodes or raises typed `UnsupportedInputError`), SealedTemplate and Tier 4 provenance crypto
(real AES-256-GCM / Ed25519, weights re-hashed on every check), and the catalog/pricing/drift
refresh automation.

The remaining incompleteness clusters in three places: **(1) the confidential tier's
operational story** — Tier 3 attestation, the hosted Relay, and license-gating depth, indexed
under **F.1, F.2, F.5** because their remediations are security work; **(2) sidecar edge
fidelity to stock OpenAI clients** (D.1–D.4); **(3) representation drift** — the conformance
matrix and DESIGN ledger trailing the code (B.2, D.7).

## D.1 Sidecar `/v1/embeddings` rejects the OpenAI SDK's default `encoding_format`

**Severity:** Medium · **Confidence:** High (code re-verified; SDK default worth confirming)
**Paths:** `src/anyinfer/serve/embeddings_codec.py:62-67`

**Brief:** The codec 400s on `encoding_format="base64"` — the official `openai` Python
client's default — so the most common stock client fails against an endpoint whose reason to
exist is stock-client compatibility.

**Long:** The comment frames base64 as "a response-encoding choice AnyInfer does not project,"
which is right for `EmbeddingResult` but wrong for the codec, whose job is exactly to
re-encode at the wire; base64-packing a float32 array is ~10 lines. The incompatibility is
invisible to AnyInfer's own tests because they speak float.

**Remediation:**
- [x] **D.1.1** Accept `"base64"` and encode each vector as base64 little-endian float32 in
  `embeddings_response` (thread the requested format through the codec return).
- [x] **D.1.2** Add a conformance case exercising the real `openai` SDK's default request shape.

## D.2 `reasoning_effort` is unreachable through the sidecar

**Severity:** Medium · **Confidence:** High
**Paths:** `src/anyinfer/serve/openai_codec.py:298-343`, `serve/app.py:293-339`

**Brief:** `reasoning_effort` — a standard OpenAI chat-completions field — is not reserved by
the codec, so it falls into verbatim `provider_options` passthrough instead of the typed
`GenerationRequest.reasoning` field, and the core's cross-provider reasoning translation
(Anthropic thinking budgets etc.) never engages for sidecar callers.

**Long:** The request type exists explicitly "so the serve frontend stays a lossless codec"
(`types/requests.py:518-521`); this is the one first-class generation parameter the codec
loses. A client sending `reasoning_effort:"high"` gets it forwarded raw to whatever dialect
serves the request — plausibly accepted by an OpenAI-compatible backend, never translated for
Anthropic/Gemini/Bedrock, silently absent elsewhere.

**Remediation:**
- [x] **D.2.1** Add `"reasoning_effort"` to `_RESERVED_FIELDS`; decode into
  `GenerationRequest.reasoning` in `request_from_openai`; pass `reasoning=` through
  `_generate`/`_stream_chunks`; mirror in `request_to_openai`.
- [x] **D.2.2** Add a round-trip codec test.

## D.3 Sidecar deployments cannot enable schema repair; config `context` block ignored

**Severity:** Medium · **Confidence:** High (re-verified directly)
**Paths:** `src/anyinfer/cli.py` (`cmd_serve`, ~line 965-985), `src/anyinfer/config/__init__.py:123-132`,
`src/anyinfer/_context_wire.py:61-66`

**Brief:** `cmd_serve` constructs `AsyncClient` without `repair=` and `AnyInferConfig` has no
repair field, so structured output through the sidecar validates (422 on violation) but never
repairs — the loop M2 hardened is reachable from Python and the CLI (`run --repair`) but not
from any serve deployment. The shared config's `context` tuning block likewise never reaches
the gateway (wire requests fall back to `DEFAULT_TUNING`).

**Long:** The sidecar is pitched as the way non-Python callers get the SDK's behavior; this
asymmetry is discovered only by comparing failure rates against the Python path.

**Remediation:**
- [x] **D.3.1** Add an optional `repair` block (e.g. `max_attempts`) to `AnyInferConfig`; pass it
  in `cmd_serve`'s `AsyncClient` construction.
- [x] **D.3.2** Use `config.context` as the default tuning for wire context requests that omit
  `tuning`.
- [x] **D.3.3** Document both in `docs/reference/configuration.md`.

## D.4 Sidecar silently swallows `n>1` and never projects logprobs back

**Severity:** Low · **Confidence:** High
**Paths:** `src/anyinfer/serve/openai_codec.py` (`_RESERVED_FIELDS` line ~127,
`completion_from_generation`, passthrough at ~490-497)

**Brief:** `"n"` is reserved but never read — a client requesting `n=3` gets one choice with
no error; `logprobs`/`top_logprobs` are *not* reserved, so they forward upstream (possibly
billed) with no response path to carry results back.

**Long:** The codec elsewhere takes pride in "telling the client beats silently applying the
gateway's default"; these are the two spots where the principle isn't applied. (Typed logprobs
end-to-end is E.2; this item is only about the sidecar's silence.)

**Remediation:**
- [ ] **D.4.1** Return 400 for `n>1` ("not supported; use `anyinfer_arena` for fan-out").
- [ ] **D.4.2** Either reserve `logprobs`/`top_logprobs` with a 400 or document one-way
  passthrough; add codec tests for both.

## D.5 `ConfidentialityReport` has no producer anywhere

**Severity:** Low · **Confidence:** High
**Paths:** `src/anyinfer-shared/src/anyinfer_shared/__init__.py`

**Brief:** The composite type that is the `anyinfer-shared` package's stated reason to exist
is never constructed by any AnyInfer code path, helper, example, or doc snippet — apps must
invent the composition themselves.

**Long:** The no-cross-import design is deliberate and sound, but "an application composing
both packages" is currently supported by zero examples: nothing maps
`ConfidentialExecutionStatus` → `execution_attested`, nothing marks `template_sealed` after a
vault render, and the confidentiality-tiers guide never mentions the type.

**Remediation:**
- [ ] **D.5.1** Add a composing helper (e.g. `ConfidentialityReport.from_status(status,
  template_sealed=..., relay_used=...)`) or a documented snippet in confidentiality-tiers.md
  so the type has one demonstrated producer.

## D.6 Demo app never touches arena, compare, or run manifests

**Severity:** Low · **Confidence:** High
**Paths:** `src/demo_app/`, `tests/demo_app/test_library_coverage.py`

**Brief:** Three headline features (arena fan-out, target comparison, run-manifest inspection)
plus MCP have no demo surface, and the demo's library-coverage test is hand-curated, so the
gap is invisible to CI.

**Long:** The demo doubles as living documentation; a user exploring it would conclude
AnyInfer has no multi-target story even though the CLI and sidecar both expose one. Nothing in
`test_library_coverage.py` exempts these features — they are simply absent, so the omission is
an accident rather than a decision.

**Remediation:**
- [ ] **D.6.1** Add a Compare surface (extend Target Inspector) driving `client.compare` against
  two fake-provider models; surface `Generation.manifest` in the telemetry view.
- [ ] **D.6.2** Either add an arena toggle on the composer, or record explicit exemptions in
  `test_library_coverage.py`'s docstring so omissions become decisions.

## D.7 DESIGN.md's open-decisions ledger has drifted from the code, both directions

**Severity:** Low · **Confidence:** High
**Paths:** `DESIGN.md` §19, §20, §24, §30.4

**Brief:** §20.4 ("default catalog cadence") is still open though the refresh workflows exist;
§19 M5's release-signing gap and §30.4's "invest in real Nitro Enclaves support" owner
decision remain genuinely open with nothing started; ten contract snapshots still self-describe
as never live-verified.

**Long:** The Nitro item is the largest silent commitment: DESIGN records an owner decision to
build real new scope (vsock networking, no GPU, no persistent storage) and nothing anywhere
starts it — no module, no tracking surface. Meanwhile §20.4 staying "open" makes risk R6 read
worse than reality. The snapshot debt is self-scheduling (the drift workflow ranks unverified
snapshots first) but until runs clear it, ten adapters' wire contracts rest on code survey
alone.

**Remediation:**
- [ ] **D.7.1** Mark §20.4 *Resolved*, citing `catalog-refresh.yml` and `pricing-refresh.yml`.
- [ ] **D.7.2** Either open a tracked design section/issue for Nitro Enclaves or downgrade the
  §30.4 owner decision to "deferred" explicitly.
- [ ] **D.7.3** Add a release-signing checklist item to `docs/contributing/releasing.md`.
- [ ] **D.7.4** Let the drift rotation burn down the ten unverified snapshots; record clearance
  dates in `contracts/*.md` as they clear.

---

# E. Obvious feature misses

## E.0 Scope discipline

Every candidate miss was checked against DESIGN.md §2's non-goals and the ADRs before being
listed. **Honored non-goals — NOT misses, do not "fix":** response/semantic caching (ADR-012:
"out of scope permanently"; prompt caching IS implemented), image generation / TTS / STT /
fine-tuning (ADR-016), load balancing and adaptive routing, org control plane (virtual keys,
RBAC, quotas), agent-framework constructs, prompt templating, cross-provider stream
continuation (feasibility gate re-checked 2026-08-10 and failed), run retention (ADR-014),
non-Python SDKs (the sidecar binary is the answer). Also verified **present** before ruling
out: prompt-cache placement, reasoning-effort translation, sidecar bearer auth, `/health`,
OTel metrics+traces, retry/backoff config, header-aware client-side rate limiting,
PDF/document/audio input, Entra/SigV4/GCP auth, vLLM multi-GPU variants, quantization gating.

## E.1 Async batch inference APIs (OpenAI Batch, Anthropic Message Batches)

**Severity:** High · **Confidence:** High

**Expected because:** every major provider sells a ~50%-discounted deferred batch tier, and
AnyInfer's identity is cost-aware dispatch (pricing tables, `SpendPolicy`, `SpendLedger`,
per-request cost estimation). Evals, backfills, and offline enrichment are exactly the
workloads this audience runs.

**Evidence of absence:** `grep -rniE "message_batch|/batches|batch_id" src/anyinfer` → zero
hits; every "batch" in the codebase is synchronous embedding-input splitting or llama-server
tuning. Not a stated non-goal — DESIGN.md never mentions it.

**Long:** AnyInfer's typed request model, capability provenance, and pricing tables are *more*
valuable in batch mode, yet the library cannot express "submit these 10k requests at half
price." Users must drop to raw provider SDKs and lose structured-output enforcement,
telemetry, and cost accounting for their highest-volume traffic.

**Remediation sketch:**
- [ ] **E.1.1** New operation type per ADR-017's pattern: `BatchGenerationRequest → BatchHandle →
  BatchResult`, an opt-in `SubmitsBatches` protocol adapters implement individually (OpenAI,
  Anthropic, Bedrock, Vertex, Groq all have batch endpoints), descriptor-declared.
- [ ] **E.1.2** Reuse `GenerationRequest` as the line-item type and existing codecs for
  serialization; typed submitted/completed lifecycle events per ADR-006.
- [ ] **E.1.3** Honor ADR-014: AnyInfer never persists the job registry — the handle is the
  caller's to store.

## E.2 Typed `seed` / `logprobs` / penalty sampling controls

**Severity:** Medium-High · **Confidence:** High

**Expected because:** OpenAI-dialect table stakes accepted by ~80 of the presets, and goal 1
promises "no per-engine branches in consuming apps."

**Evidence of absence:** `Sampling` (`types/requests.py:88-105`) has exactly four fields
(`temperature`, `top_p`, `max_output_tokens`, `stop`). No `seed`, `logprobs`,
`presence_penalty`, `frequency_penalty`, `logit_bias`, or `n` anywhere in `types/`;
`Generation` has no logprobs surface. Preset notes prove users must hand-spell them
(`presets.py:472`: Mistral "uses random_seed instead of seed").

**Long:** The `provider_options` escape hatch defeats the core promise: a seeded run requires
knowing each provider's spelling. Logprobs are worse — even passed through, the normalized
result types have nowhere to carry them back, so eval harnesses and
classification-with-confidence callers (bread-and-butter for this audience) hit a hard stop.

**Remediation sketch:**
- [ ] **E.2.1** Extend `Sampling` additively with `seed`, `presence_penalty`, `frequency_penalty`
  (defaults `None` = provider default; never invent a value).
- [ ] **E.2.2** Add a `logprobs` request field with a typed `TokenLogprob` result surface on
  `Generation`, and emit the existing `ParameterDropped` event where unsupported.
- [ ] **E.2.3** Move these from passthrough/reserved to decoded fields in the sidecar codec
  (closes D.4's logprobs half).

## E.3 Provider-native server-side tools (web search, code execution)

**Severity:** Medium-High · **Confidence:** High

**Expected because:** Anthropic, OpenAI, Gemini, and xAI all ship server-executed tools;
"grounded answer with fresh web results" is one of the most common application features.

**Evidence of absence:** `grep -rniE "web_search|server_tool|computer_use|code_interpreter"
src/anyinfer` → nothing but a comment; `ToolSpec` models exclusively client-executed tools.
The "not an agent framework" non-goal fences planning/memory, not provider-native tool
passthrough — the provider executes the tool inside one request/response, squarely ADR-003
translate-only territory.

**Long:** A user can inject a raw tool block via `provider_options`, but the response's
`server_tool_use`/result content blocks aren't modeled by the stream parsers, so results
degrade to `raw`-payload archaeology and per-search billing is missed.

**Remediation sketch:**
- [ ] **E.3.1** Add a `ServerToolSpec` union member beside `ToolSpec`, typed per capability
  (`web_search`, `code_execution`), declared per-provider with provenance (ADR-005) so
  unsupported targets refuse before dispatch.
- [ ] **E.3.2** Map server-tool result blocks to a typed event; add per-invocation pricing line
  items.

## E.4 Typed citations / grounded-generation output

**Severity:** Medium · **Confidence:** High

**Expected because:** RAG-with-attribution is a dominant pattern; Anthropic citations, Cohere
grounded chat, and Gemini grounding metadata all return structures users need to render.

**Evidence of absence:** self-acknowledged in two adapters — `m365_copilot.py:14` ("v1 has no
typed [citations]"); `cohere.py:1-5` advertises "grounded generation with document citations"
as the reason to use Cohere's native API, then never sends a `documents` field on the generate
path and exposes no citation type (none exists in `types/`).

**Remediation sketch:**
- [ ] **E.4.1** Add `citations: tuple[Citation, ...]` to `Generation` and a citation event to the
  event union; adapters map each dialect.
- [ ] **E.4.2** Request-side grounding documents reuse `DocumentPart`/context blocks — no new
  field.
- [ ] **E.4.3** Sidecar projects citations under an `anyinfer_*` extension field per the
  documented superset pattern.

## E.5 OpenAI Responses API endpoint on the sidecar

**Severity:** Medium · **Confidence:** High

**Expected because:** the Responses API is OpenAI's current-generation surface; 2026-era
OpenAI SDK paths and the Agents SDK default to it. AnyInfer's *own* OpenAI adapter already
speaks `POST /responses` upstream (`providers/openai.py:145-150`), so the project itself
treats Responses as the real dialect — while its sidecar serves only chat completions
(`serve/app.py:282-288`; anything else 404s).

**Remediation sketch:**
- [ ] **E.5.1** Add `serve/responses_codec.py` beside `openai_codec.py` mapping `POST
  /v1/responses` (input items → `Message` parts, `text.format` → `SchemaSpec`, semantic
  streaming events) under ADR-009's invariants.
- [ ] **E.5.2** Explicitly refuse or map `previous_response_id` onto `Session` — ADR-014 forbids
  server-side run storage; never silently emulate.

## E.6 No accurate token estimator ships behind the complete protocol

**Severity:** Medium · **Confidence:** High

**Expected because:** context budgeting is headline goal 10, and the category norm (tiktoken
everywhere, Anthropic `count_tokens`, llama-server `/tokenize`) makes real counts an assumed
capability.

**Evidence of absence:** `capabilities/estimate.py:3-5` names all three better implementations
in its own docstring and ships none; no tiktoken usage, no `count_tokens` call, no
`[tokenizers]` extra. The `TokenEstimator` protocol is complete; implementations are wholly
absent — so the context gate, cache-mark placement (`min_segment_tokens`), and
`SpendPolicy.max_request_usd` all run on a byte heuristic.

**Remediation sketch:**
- [ ] **E.6.1** Ship optional estimators behind extras per ADR-007: tiktoken-backed (exact for
  OpenAI-family), Anthropic count-tokens endpoint (opt-in, cached), llama-server `/tokenize`
  for local targets.
- [ ] **E.6.2** Wire per-provider selection through `TokenCalibration`, keeping provenance so
  gating knows when a floor is exact.

## E.7 Video input parts

**Severity:** Low-Medium · **Confidence:** High

**Brief:** `ContentPart` models Text/ToolCall/ToolResult/Image/Document/Audio — no
`VideoPart`, so a Gemini video request (a marquee Gemini use case) cannot be expressed at all.
ADR-016's non-goal sentence covers outputs and endpoints, not video *input*; this is
unaddressed rather than fenced.

**Remediation:**
- [ ] **E.7.1** Add `VideoPart` (data-or-URL, `video/*` media-type check, its own byte ceiling) to
  `types/messages.py`; project in `providers/_multimodal.py` for Gemini/Vertex; refuse
  elsewhere via trusted capability absence per ADR-016.

## E.8 Runtime credential rotation / hot reload

**Severity:** Medium-Low · **Confidence:** Medium

**Brief:** API keys are resolved once at adapter construction (`_client/providers.py:51-54`;
static headers baked into the pooled client) — rotating a key means restarting the installed
sidecar service. `cloud_auth.py` already refreshes GCP/AWS tokens with expiry margins, proving
the need is understood for tokens but not extended to keys; Azure Entra's token can even end
up baked static via the compat constructor.

**Remediation:**
- [ ] **E.8.1** Make credential resolution lazy-per-request or TTL-cached in header construction
  (the `cloud_auth.py` refresh-margin pattern is the in-tree template).
- [ ] **E.8.2** Treat a 401-after-success as a trigger to re-resolve once before failing. The
  existing `env://`/`credential://` references already express "look it up" — honor them more
  than once.

## E.9 Explicit proxy / custom CA / mTLS configuration

**Severity:** Low-Medium · **Confidence:** Medium-High

**Brief:** `providers/http.py:build_client` accepts only
`base_url`/`headers`/`timeout_s`/`transport`; no `proxy`, `verify`/CA-bundle, or client-cert
surface anywhere in `ProviderSettings`. Enterprise users behind TLS-intercepting proxies —
exactly the environments the confidential tier courts — depend on undocumented env-var
behavior that cannot differ per provider instance; mTLS to an internal gateway has no path
short of abusing the test-seam `transport`.

**Remediation:**
- [ ] **E.9.1** Add `proxy`, `ca_bundle`/`verify`, `client_cert` to `ProviderSettings`, threaded
  into `httpx2.AsyncClient` (no new dependency); mirror in the config schema and
  `docs/reference/configuration.md`; document the env-var fallback either way.

## E.10 Entry-point extensibility beyond provider adapters

**Severity:** Low · **Confidence:** High

**Brief:** ADR-008 makes entry-point discovery a headline feature, but
`ENTRY_POINT_GROUP = "anyinfer.providers"` is the only group. Credential stores, observers,
estimators, and reducers are constructor-injection only — unavailable to the standalone
sidecar binary, which can only discover what entry points hand it.

**Remediation:**
- [ ] **E.10.1** Add narrow groups where the config/sidecar path needs them most:
  `anyinfer.credential_stores` (resolver schemes) and `anyinfer.observers` (config-nameable
  telemetry sinks), with ADR-008's validation discipline. Reducers/estimators can stay
  injection-only.

## E.11 Local model store disk budget / guided eviction

**Severity:** Low · **Confidence:** High

**Brief:** `local/store.py` tracks `total_bytes` but nothing bounds them: no LRU, no
`last_used`, no prune command — cleanup is entirely manual (`anyinfer models rm`) with no
recency data to guide it, while the tier-recommendation flow accumulates stale multi-GB
variants across hardware upgrades.

**Remediation:**
- [ ] **E.11.1** Record `last_used` on `StoreEntry` when `locate_model`/server launch touches an
  entry.
- [ ] **E.11.2** Add `anyinfer models prune [--keep-bytes N]` proposing least-recently-used
  deletions with interactive confirm (the store's "never deletes external entries" caution
  must hold). Automatic eviction stays out.

## E.12 Shipped logging/JSONL sink for the telemetry stream

**Severity:** Low · **Confidence:** High

**Brief:** Typed events and OTel export exist, but the simplest sink — structured lines to
stdlib `logging` or JSONL to a file — must be hand-written by every consumer;
`events/observers.py` ships only the protocol, `Subscription`, and the dispatcher.

**Remediation:**
- [ ] **E.12.1** Add `LoggingObserver`/`JsonlObserver` (~50 lines each) reusing the per-event
  attribute extraction pattern from `otel.py` — content-free by default, `payloads=True`
  opt-in, honoring redaction; expose as a config option so the sidecar binary gets an
  access-log story.

## E.13 Non-goals worth a deliberate revisit (labeled as such — these are decisions, not bugs)

**Severity:** — · **Confidence:** High that each is currently fenced

- [ ] **E.13.1** *MCP server exposure.* `docs/guides/tool-loop.md:158` routes non-Python clients
  to the OpenAI sidecar, but MCP-only hosts (Claude Desktop, IDE agents) cannot consume an
  OpenAI endpoint. An MCP projection would fit ADR-009's wire-codec discipline.
- [ ] **E.13.2** *Exact-match response replay.* ADR-012's "permanently out of scope" reasoning
  targets semantic caching's risks more than exact replay's; exact-match is table stakes in
  every gateway in this category.
- [ ] **E.13.3** *Same-provider key pooling.* The load-balancing fence prohibits choosing a
  different *target*; rotating among several keys for the *same* target is arguably not target
  selection and is expected at scale.

---

# F. Security posture

## F.0 Overall posture

**Verdict: the core runtime holds up well; the weaknesses cluster at the edges** (the
confidential add-on and the Qt demo). Verified strengths:

- **Sidecar exposure discipline, enforced three places.** Constant-time token comparison
  (`serve/app.py:423`, `secrets.compare_digest`); both `cli.py:943-955` and
  `serve/service.py:296-315` refuse a non-loopback bind without `--allow-remote-exposure`
  *and* a token; `local/server.py:257-264` enforces the same for supervised llama-server. The
  AGENTS.md loopback claim verifies.
- **Hash-before-execute supply chain.** `downloads.py` verifies SHA-256 into a `.part` file
  before `replace()`; `runtimes.py:install_runtime` fetches→verifies→unpacks→executes; pins
  are machine-generated from upstream release digests.
- **Real archive-traversal defense.** `runtimes.py:_unpack` checks every zip/tar member for
  containment and symlink/hardlink targets; tar uses `filter="data"`.
- **Token-on-redirect discipline.** `huggingface.py:trusted_redirect` strips `Authorization`
  on cross-origin hops.
- **Layered cassette secret defense.** Wholesale auth-header stripping plus an independent
  `audit_cassette` re-scan; none of the committed cassettes contain auth headers.
- **Clean fundamentals.** No `pickle`/`eval`/`exec`/unsafe-yaml anywhere in `src/`; all
  subprocess call sites are argument-vector-only with bounded waits and isolated process
  groups; jsonschema used without remote `$ref` resolution; the demo's markdown renderer is a
  strict allow-list parser (no XSS-equivalent), and external links open only on hardcoded
  constants; no `pull_request_target` and no secret exposure to fork PRs in CI.

## F.1 Tier 3 "attested execution" is TEE detection, not cryptographic attestation

**Severity:** High (as a claim-integrity matter; Medium as immediate exploit surface) ·
**Confidence:** High · **Class:** accepted-risk (documented) bordering vulnerability
**Paths:** `src/anyinfer/local/attestation.py`, `src/anyinfer/providers/confidential_execution.py`,
`DESIGN.md` §30.4, `docs/guides/confidentiality-tiers.md`

**Brief:** `end_to_end=True` — the gate `ConfidentialExecutionAdapter` refuses generation on —
is backed by `/dev/sev-guest`-style device-node existence and `nvidia-smi conf-compute -q`
text parsing. No attestation quote is ever generated, signed, or verified against
AMD/Intel/NVIDIA certificate chains; the "attest-extra-gated verification step" the module's
own docstring references (`attestation.py:70-74`) does not exist anywhere.

**Long:** A fabricated device node satisfies every probe; there is nothing for a *remote*
relying party to trust, though DESIGN §30.4's own definition of Tier 3 is that "remote
attestation proves that to the vendor's software." Three mitigating facts: the user-facing
guide discloses this honestly ("detection, not cryptographic attestation"); DESIGN records the
gap as deliberate ("this environment cannot exercise the positive case against real
CC-capable hardware, and shipping unverified security-critical code is worse than an honest,
documented gap"); and the fail-closed refusal path genuinely works. But DESIGN §30.4's opening
sentence ("the only tier with a real cryptographic guarantee") oversells what ships, and two
sub-gaps compound it: **(a)** the GPU CC "capable" parse has never been observed against a
real positive (`attestation.py:288-297` says so itself; a novel `nvidia-smi` output like
`"N/A"` would read as capable — and this parse was already wrong once in the module's
history); **(b)** Tier 4's weights verification hashes the file at check time while
llama-server loads it later (`provenance.py:129-164` vs `server.py:_spawn` ~358-407) — a
TOCTOU window that matters exactly inside the deployment Tier 3 targets (also listed as F.11).

**Remediation:** superseded by the phased implementation plan in **section G** (added
2026-08-25) — track progress there, not here. Mapping from the originally proposed steps:
F.1.1 → G.4.1/G.4.2 · F.1.2 → G.4.3 · F.1.3 → G.1.1/G.1.3 · F.1.4 → G.1.2 (then G.3.3) ·
F.1.5 → G.4.4. Mark this item done when G.1–G.5 are complete (G.6 may remain open).

## F.2 Relay ASGI app serves decrypted prompt IP with no authentication

**Severity:** High · **Confidence:** High (re-verified directly) · **Class:** vulnerability
**Paths:** `src/anyinfer-confidential/src/anyinfer_confidential/app.py:36-60`, `relay.py:93-105,155-156`

**Brief:** `build_app`'s handler reads `tenant_id` straight from the client-supplied request
body — no auth check, no middleware — and returns `result.assembled_prompt`. Any client that
can reach the endpoint and supply a known or guessed `tenant_id`+`routing_key` receives the
decrypted, assembled prompt: the exact IP Tier 2 exists to protect.

**Long:** `RelayRegistry`'s per-tenant scoping is structurally sound *given a trusted
tenant_id*, but here the caller declares its own, so isolation collapses to "don't know the
other tenant's id" — not an access control. Contrast the core sidecar, which refuses
non-loopback exposure without a bearer token because "an unauthenticated LLM gateway on a LAN
is a credential laundering service"; the relay handles strictly more sensitive material with
strictly less protection, and nothing in the README warns that `build_app` must be wrapped.
Compounding operational gaps: `mode:"forward"` is unreachable over HTTP (`build_app` never
decodes `provider_settings`, so it always 404s via `RelayError`), the registry is in-memory
only with no provisioning surface, and there is no hosted deployment story (docs concede
"AnyInfer does not currently operate a hosted instance") — this matches the known
"hosted Relay ops" gap.

**Remediation:**
- [x] **F.2.1** Add authentication to `build_app` (bearer token or mTLS); derive `tenant_id` from
  the authenticated principal, never the body; reject a body `tenant_id` that disagrees.
- [x] **F.2.2** Handle `mode:"forward"` explicitly at the HTTP layer: either decode short-lived
  provider settings or return 400 "assemble only" — never the current misleading 404.
- [x] **F.2.3** Add a registry-provisioning helper (JSON/file-based) and a self-host deployment
  checklist (TLS, token issuance, tenant binding) to the package README /
  confidentiality-tiers.md.
- [x] **F.2.4** Until F.2.1 lands, document loudly that `build_app` is unauthenticated and must be
  wrapped.

## F.3 Demo app persists literal API keys despite a documented "memory only" guarantee

**Severity:** Medium · **Confidence:** High · **Class:** vulnerability
**Paths:** `src/demo_app/config.py:8-10,201-212,263-267`, `src/demo_app/widgets/settings_dialog.py:406,575-584`

**Brief:** `config.py`'s docstring guarantees "the demo's config file on disk holds no key
material. Literal keys typed into the dialog are kept in memory only" — but `to_config()`
captures all field text including literal secrets, `to_json()` emits them verbatim, and
`save()` writes them with default permissions. The secret-field placeholder actively invites a
literal ("env://VARIABLE_NAME or a literal key").

**Long:** No code path strips or converts a literal secret before save (grep-confirmed: no
`env://` conversion, no secret filter, no memory-only branch). The guarantee is simply false.
`demo.json` under `~/.config/anyinfer-demo/` is written 0644-minus-umask, readable by other
local users and swept into backups/sync. Bounded to the demo and to users who type literals —
but the app both invites the literal and promises it's safe.

**Remediation:**
- [x] **F.3.1** Preferred (matches stated intent): detect a literal in a `secret`-kind field and
  exclude it from `to_json()`, keeping it in the in-memory config only; tell the user
  ("literal keys are session-only — use env:// to persist").
- [x] **F.3.2** Regardless: write `demo.json` at mode 0600 (create-before-write, the
  `serve/service.py` pattern).
- [x] **F.3.3** Not needed: F.3.1 landed, so the docstring guarantee is now true. Its
  wording was tightened to name the one place that enforces it. *(2026-08-25)*

## F.4 Confidential CLI writes private keys with default file permissions

**Severity:** Medium · **Confidence:** High · **Class:** hardening
**Paths:** `src/anyinfer-confidential/src/anyinfer_confidential/cli.py:19,26,47`

**Brief:** The vendor's AES-256 sealing key, Ed25519 license-signing private key, and license
blobs are written via bare `Path.write_bytes` — world/group-readable under a normal umask —
while `serve/service.py:278-281` in the same repo already demonstrates the correct
0600-before-write pattern for its token file.

**Long:** These are the crown-jewel secrets of the confidential tiers: the signing key mints
licenses gating all template decryption; the AES key decrypts every template sealed under its
id. On a shared build machine or CI runner, another local user or a later job can read them.

**Remediation:**
- [x] **F.4.1** Write all three outputs via `os.open(path, O_WRONLY|O_CREAT|O_TRUNC, 0o600)` +
  `fdopen`, mirroring `serve/service.py:write_service`; print a note that the file is
  mode-restricted.

## F.5 Sealed-template license gating is a code-path tripwire, not a cryptographic lock

**Severity:** Medium · **Confidence:** High · **Class:** hardening / docs-gap
**Paths:** `src/anyinfer-confidential/src/anyinfer_confidential/sealed_template.py:16-19,173-176`,
`license.py:116-147,143`

**Brief:** The docstring claims an install without a valid license "cannot produce a single
rendered prompt," but license validity never enters key derivation: `TemplateVault` holds both
the AES key and the ciphertext, and the Ed25519 check gates only the `render()` code path — a
bundle holder can call `AESGCM(key).decrypt(...)` directly.

**Long:** Inherent to client-side sealing, and Tier 1's *confidentiality* ceiling is honestly
scoped to static extraction — but the *licensing* claim is stronger than the confidentiality
claim and isn't caveated the same way. Secondary realism notes: expiry uses local wall-clock
(`time.time()` — clock rollback defeats it), and online revocation defaults to fail-open
(`revocation_fail_closed=False` — documented tradeoff; fine, but high-assurance deployments
should be steered to `True` explicitly in docs).

**Remediation:**
- [ ] **F.5.1** Either derive the template-decryption key from license-blob material (wrap the AES
  key per-deployment under a key delivered inside the signed license) so an invalid license
  genuinely cannot decrypt, **or** amend `sealed_template.py:16-19` and
  confidentiality-tiers.md to state the enforcement lives in the vault code path only.
- [ ] **F.5.2** Docs: recommend `revocation_fail_closed=True` for high-assurance deployments and
  spell out the "never checked yet" fail-open.

## F.6 Sidecar has no request-body size limit

**Severity:** Low · **Confidence:** High · **Class:** hardening
**Paths:** `src/anyinfer/serve/app.py` (`create_app`, handlers' `await request.json()`)

**Brief:** Every handler buffers the entire body into memory with no `content-length` cap or
streaming bound — an authenticated (or loopback) client can force unbounded allocation with a
multi-gigabyte JSON body. DoS, not disclosure; matters most under `--allow-remote-exposure`.

**Remediation:**
- [x] **F.6.1** Add middleware in `create_app` rejecting bodies over a configurable limit (a few
  MB default), enforced while reading to defend against a missing/lying `content-length`.

## F.7 Config-controlled URLs (SSRF / `file://`) — trust assumption undocumented

**Severity:** Low · **Confidence:** Medium · **Class:** accepted-risk / docs-gap
**Paths:** `src/anyinfer/local/sources/direct_url.py:53-131`, `local/acquire.py:634-635,748`,
`src/anyinfer/mcp/transport.py:200-220`, provider `base_url` generally

**Brief:** Provider base_urls, MCP endpoints, and direct model-source URLs are fetched without
host filtering (`169.254.169.254` included), and a `file://` source URL reads/registers an
arbitrary local path. All inputs are configuration — trusted in the default posture, and the
sidecar does *not* expand the surface (serve targets resolve to pre-configured providers) —
but the trust assumption is stated nowhere, and it becomes real the moment an application lets
lower-trust input influence any of these values.

**Remediation:**
- [x] **F.7.1** Document the trust assumption ("provider base_urls, MCP URLs, and model-source
  URLs are trusted configuration") in the configuration reference and custom-providers guide.
- [ ] **F.7.2** Optional, not taken. Deliberately deferred: a resolve-and-check guard would
  need an opt-in flag, a private-range policy, and a re-resolve at connect time to be
  worth anything against DNS rebinding, and the default posture (configuration is
  operator-written) does not need it. F.7.1 now states the assumption and tells an app
  that *does* expose these values what to do instead. Revisit if a first-party
  multi-tenant surface ever accepts a caller-supplied URL. *(2026-08-25)*

## F.8 Third-party GitHub Actions pinned to mutable tags

**Severity:** Low · **Confidence:** High · **Class:** hardening
**Paths:** `.github/workflows/*.yml` (`astral-sh/setup-uv@v6`, `anthropics/claude-code-action@v1`,
`pypa/gh-action-pypi-publish@release/v1`, `actions/*@vN`)

**Brief:** A force-moved or compromised tag executes attacker-controlled code in jobs holding
`ANTHROPIC_API_KEY`/`CLAUDE_CODE_OAUTH_TOKEN` and the PyPI OIDC identity. Triggers are all
`schedule`/`workflow_dispatch`/tag-push (never fork-PR — a genuine strength), so the residual
risk is purely the mutable-tag surface.

**Remediation:**
- [x] **F.8.1** Pin third-party actions to full commit SHAs (version in a comment), prioritizing
  secret-bearing and publishing jobs; enable Dependabot for actions.

## F.9 `catalog-refresh` workflow grants write scope to its read-only job

**Severity:** Low · **Confidence:** High · **Class:** hardening
**Paths:** `.github/workflows/catalog-refresh.yml:30-32` vs `contract-drift.yml:50-51,98-100`

**Brief:** Workflow-level `contents: write / pull-requests: write` means the deterministic
`check` job inherits scope it never needs; `contract-drift.yml` in the same repo already does
this correctly (read at top, write only in the `propose` job).

**Remediation:**
- [x] **F.9.1** Set workflow default `contents: read`; move write permissions into the `propose`
  job, copying `contract-drift.yml`.

## F.10 Redaction is exact-substring only

**Severity:** Low · **Confidence:** Medium · **Class:** hardening
**Paths:** `src/anyinfer/redaction.py:44,49-58`

**Brief:** `redact()` does plain `text.replace(secret, REDACTED)` with a 6-char floor: a
secret embedded JSON-escaped, URL-encoded, or base64'd is missed. Understood limitation (the
cassette audit exists precisely because redaction "only removes what it was told about") —
defense-in-depth, not a hole.

**Remediation:**
- [ ] **F.10.1** Where feasible, redact structured payloads before serialization (the
  manifest/partial paths already do via `_redact_value`); consider registering common
  encodings of each secret at registration time.

## F.11 Model-weight verification has a load-time TOCTOU window

**Severity:** Low · **Confidence:** Medium · **Class:** hardening
**Paths:** `src/anyinfer/local/provenance.py:129-164`, `src/anyinfer/local/server.py` (`_spawn`)

**Brief:** Tier 4 hashes `weights_path` at check time; llama-server memory-maps the file
later; nothing pins the file in between. Only meaningful where an attacker has local write
access inside a confidential deployment — layered on F.1.

**Remediation:**
- [ ] **F.11.1** Verify against an open file descriptor and load from that same descriptor (or
  verify inside the attested boundary immediately before load) so checked bytes and loaded
  bytes are provably identical.

## F.12 SECURITY.md is real but the canonical org/domain diverges across the repo

**Severity:** Low · **Confidence:** Medium · **Class:** docs-gap
**Paths:** `SECURITY.md:10-13`, `serve/service.py:433`

**Brief:** The reporting process (GitHub private advisories at `github.com/anthturner/…` +
email fallback) is genuine and its security claims all verify against code; only the naming
diverges (`anthturner` org vs `anyinfer.dev` docs domain in the systemd `Documentation=` URL
and site links).

**Remediation:**
- [ ] **F.12.1** Before 1.0, reconcile the canonical org/domain across SECURITY.md, the systemd
  unit, and the docs site so a vulnerability reporter cannot be misdirected.

## F.13 Loose `COHERE.key` credential file in the working tree

**Severity:** Low · **Confidence:** High (independently verified) · **Class:** local hygiene
**Paths:** `COHERE.key` (repo root, untracked)

**Brief:** A 40-byte plaintext file consistent with a live Cohere API key sits at the repo
root. Verified: explicitly listed in `.gitignore` (line 34), never in any commit, excluded
from the sdist include-list — so exposure is limited to local tooling that scoops the
directory, archives/copies of the worktree, or a future ignore-rule edit.

**Long:** Not a codebase defect — nothing in `src/` or `tests/` references it — but the
project's own credential story (`env://` references, keyring extra, redaction registry) exists
precisely so keys never live as loose files beside code.

**Remediation:**
- [x] **F.13.1** Partial, by the owner's call *(2026-08-25)*: the file is kept, but tightened
  to mode 0600 so other local users cannot read it, and `.gitignore` now patterns `*.key`,
  `*.pem`, and `.env*` instead of naming this one file — the previous entry meant a
  credential with any other name was committable. **Still open for the owner:** moving the
  value to `env://` or the keyring and deleting the file, and rotating it if this directory
  was ever copied, synced, or shared.

---

# G. Attestation implementation plan (making Tier 3's guarantee real)

## G.0 Rationale and decision frame

The confidentiality story is the product's stated differentiator, and Tier 3 is its only tier
claiming a cryptographic guarantee — a claim that today rests on device-node detection (F.1).
Implementing quote verification is therefore not "add a feature to stand out"; it is "make the
thing already advertised true," which makes it higher-leverage than any new differentiator.
Three constraints shape the plan: **(1)** DESIGN.md's own principle — never ship unverified
security-critical code — makes *hardware access* the gate, not code, so the honest-claims pass
(G.1) lands first and the implementation waits for real captured artifacts (G.3); **(2)** the
confidential tier's credibility fails cheaper elsewhere first — F.2 (Relay auth) and F.3 (demo
key persistence) should land before or alongside G.1; **(3)** scope splits the bounded CPU
path (G.4) from GPU SPDM attestation (G.6, explicitly deferred). **Trigger:** a real design
partner (G.2) justifies G.3–G.5 before 1.0; without one, G.3+ can follow 1.0 while G.1 lands
regardless — the honest-gap posture stays defensible only as long as the prose stops saying
"real cryptographic guarantee" before the crypto exists.

## G.1 Honest-claims pass (immediate; no hardware needed)

**Sev 5 · Pri 5** — stop overselling while the gap exists. Hours of work; absorbs F.1.3/F.1.4.

- [x] **G.1.1** Reword DESIGN.md §30.4's opening sentence ("The only tier with a real
  cryptographic guarantee") to "the only tier *designed for* a real cryptographic guarantee;
  today it performs TEE detection, with quote verification planned" — and sweep
  `docs/guides/confidentiality-tiers.md` plus any marketing surface for equivalent phrasing
  (the guide's own "detection, not cryptographic attestation" wording is the model).
- [x] **G.1.2** Pin the GPU CC positive parse (`local/attestation.py:288-297`): switch from
  `!= "None"` to an allowlist of observed-positive values with a logged "unknown value treated
  as not capable" fallback; add fixture tests for capable/incapable/garbled
  `nvidia-smi conf-compute -q` outputs (NVIDIA's published samples until G.3 captures real
  ones).
- [x] **G.1.3** Document at every `end_to_end` consumer (docstrings on
  `ConfidentialExecutionStatus`, `confidential_execution_status()`, the adapter) that the
  field is advisory-local-only until `quote_verified` (G.4.3) exists.

## G.2 Demand gate (a decision, not code)

**Sev 3 · Pri 4** — the differentiation argument only pays off with a real counterparty.

- [ ] **G.2.1** Identify at least one prospective design partner: a vendor shipping prompt IP
  onto customer-owned hardware who would adopt Tier 3. Record the outcome (who, or "none
  found by <date>") here.
- [ ] **G.2.2** Decide sequencing from the answer: partner exists → schedule G.3–G.5 before
  1.0; none by 1.0 planning → mark G.3–G.6 explicitly deferred past 1.0 in DESIGN §30.4
  (keeping G.1's honest posture as the shipped story).

## G.3 CC hardware validation sprint

**Sev 4 · Pri 3** — clears the gate DESIGN itself sets, by renting rather than building.

- [ ] **G.3.1** Rent a SEV-SNP confidential VM (an Azure DCa/ECa-series confidential VM
  suffices for the CPU path; add an `NCCadsH100v5` instance only if GPU work is being
  scoped). Budget: days, not weeks.
- [ ] **G.3.2** Capture real artifacts with nonces included: SEV-SNP attestation reports via
  the configfs-TSM report interface, a TDX quote if a TDX host is also rented, and positive
  `nvidia-smi conf-compute -q` output on the GPU instance.
- [ ] **G.3.3** Commit sanitized captures as test fixtures (verify they contain no
  tenant-identifying material first) and tighten G.1.2's allowlist to the observed values.

## G.4 CPU attestation-quote verification (the bounded core)

**Sev 5 · Pri 3** — SEV-SNP + TDX quote fetch and chain verification behind the existing
`attest` extra (`cryptography>=42` is already declared; no new mandatory dependencies,
honoring the slim-core rule).

- [ ] **G.4.1** Report acquisition: SEV-SNP report via `/sys/kernel/config/tsm/report`
  (configfs-TSM) with a caller-supplied nonce; TDX quote via the same interface where the
  host exposes it. Lives in `anyinfer/local/` per the workstream table (acquisition is not
  protocol translation).
- [ ] **G.4.2** Verification: signature chain to vendor roots (AMD ARK → ASK → VCEK for
  SEV-SNP; Intel PCS for TDX), nonce freshness, and launch-measurement check; failures raise
  typed errors in the existing `ConfidentialExecutionError` family with `hint` set to the
  operator's next step.
- [ ] **G.4.3** Add a `quote_verified` field to `ConfidentialExecutionStatus`, provenance-
  tagged and distinct from `end_to_end`; `ConfidentialExecutionAdapter` gates any
  remote-facing assurance on `quote_verified`, never on detection alone. (Closes F.1.2.)
- [ ] **G.4.4** Tests: fixture-driven verification against G.3 captures, including tampered-
  report and stale-nonce negative cases; a live positive-case test gated on real hardware,
  marked like the existing live-credential conformance mode. (Closes F.1.5.)

## G.5 Claims and docs update (after G.4)

**Sev 3 · Pri 3** — the payoff step: the differentiator becomes citable.

- [ ] **G.5.1** Rewrite DESIGN §30.4 and `docs/guides/confidentiality-tiers.md` to state the
  verified guarantee precisely: which platforms are quote-verified, what the nonce/measurement
  check proves, and the GPU ceiling (per G.6.1).
- [ ] **G.5.2** Document the `attest` verification workflow on the confidential API reference
  page (C.1's new page) plus a short "verifying an attested host" guide section.
- [ ] **G.5.3** Surface `quote_verified` provenance wherever capability claims render
  (capabilities docs; a conformance-matrix note if applicable), per the provenance rule that
  nothing estimated is presented as authoritative.

## G.6 GPU SPDM attestation (explicitly deferred)

**Sev 3 · Pri 1** — H100 CC attestation via the OpenRM SPDM path (nvtrust tooling) is
substantially harder than the CPU path and needs sustained GPU-CC hardware access.

- [ ] **G.6.1** Until implemented, state the ceiling in every surface G.5 touches, per the
  project's own "every tier states its ceiling" doctrine: "CPU-attested; GPU CC detected but
  not quote-verified."
- [ ] **G.6.2** Re-evaluate when a design partner needs GPU offload inside the attested
  boundary, or when Blackwell CC goes GA on a hyperscaler (the §30.4 market-facts re-check
  cadence already covers this).

## G.7 Nitro Enclaves decision (ties to D.7.2)

**Sev 2 · Pri 2** — resolve the standing owner decision rather than leaving it silently open.

- [ ] **G.7.1** Either open a tracked design section for real Nitro Enclaves support (scope:
  vsock-only networking, no GPU, no persistent storage; attestation via NSM documents would
  be a G.4-style follow-on) or downgrade the DESIGN §30.4 owner decision to "deferred"
  explicitly. Doing nothing is the only wrong outcome.
