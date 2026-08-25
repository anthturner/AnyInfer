# Codebase Status — AnyInfer (v2)

**Date:** 2026-08-25 · **As of:** commit `ed337b8` on `main` · **Supersedes:** v1 (commit
`42e2106` baseline; retrievable from this file's git history).

**Method:** five parallel verification reviews re-checked every v1 closure claim against
current source — commit messages were not trusted — plus a fresh review of the ~8,400 new
lines and a full gate run. **Result of that gate:** `workspace test` and `workspace check`
both pass — all 11 steps: 2,796 tests, `mypy --strict` clean (202 files), all four
import-linter contracts kept, conformance suite, docstring coverage (436/436), strict docs
build. Zero TODO/FIXME markers in `src/`.

**Closure summary:** 49 of v1's 63 tracker items are verified closed across commits
`48cd786..ed337b8`. Closed items are REMOVED from this document per owner instruction
(2026-08-25); remaining and new items are renumbered. The **Was** column maps v2 IDs to v1
IDs, which is what the commit messages up to `ed337b8` cite. Items marked Was = "new" were
found in this v2 review, mostly at the edges of the newly landed code.

**How to address items:** `A`–`G` are the sections; `A.1` is an item; `A.1.2` is a numbered
remediation step. Cite an index to scope a future cleanup. Line numbers are valid as of the
commit above; paths and symbol names are the durable anchors.

**Living document:** check off a step's `- [ ]` when it lands; flip the item's Status cell in
the tracker when every step is done (note partial completion inline). If a fix changes a
finding's facts, edit the item's Long text and date the edit. Within v2, do not reuse a
retired index; a future full rebuild (v3) may renumber again with a Was column.

**Status glyphs:** `[ ]` open · ✅ done · 🚧 blocked on an external event · ⏭️ deliberately
skipped, with the reason recorded on the item · 🔁 recurring watch-item, not closable.

---

## Burn-down run — 2026-08-25

Every item at effort M or below outside sections E and G was closed, except the five that
cannot be closed by code. **22 items closed:** A.1, A.3, B.1–B.5, C.1–C.3, D.1–D.6, F.2–F.9.
**Not closed, by category:** F.10 and C.4 are owner-action and externally gated (⏭️/🚧);
A.2 and D.7 are record-only/recurring by their own terms; all of section E and plan §G are
outside the burn-down filter — E items are net-new features and §G is hardware- and
demand-gated.

`workspace check` passes all 11 steps after the run (2,844 core tests + 37 in the
confidential add-on, `mypy --strict` clean over 203 files, all four import-linter contracts
kept, docstring coverage complete, strict docs build).

**Three findings surfaced by doing the work**, each recorded on its item: the §18 layout
drift test only compared filenames and so could not have caught A.1's move (now fixed and
verified to fail on injected drift); `context_request.py` cannot move to either destination
A.1.1 proposed without breaking an architecture contract (recorded as a decision in DESIGN
§18 instead); and D.7's never-verified snapshot count is seven, not six.

**Three pre-existing dependency-drift bugs found and fixed** (new section H). H.1 was
reported first as a deprecation to plan for; investigating it on the owner's instruction
showed it was already breaking, and a sweep for the same shape then turned up H.2 (two
independent breaks in the copilot adapter, one of them a silent subprocess leak) and H.3.
All three shared a root: the seam where our code meets a dependency was either mocked by
something more permissive than the real thing, or not executed by any test at all.

---

## Remediation tracker

**Scoring:** *Sev* maps stated severity (High=5, Medium-High=4, Medium=3,
Low-Medium/Medium-Low=2, Low=1). *Pri* is urgency and leverage per unit of effort (5 = do
now). *Score* = Sev × Pri; rows sorted by Score. **Effort** approximates implementation
cost: XS = minutes · S = an hour or a few · M = a day or two · L = several days to a week ·
XL = multi-week or externally gated. **Burn-down filter:** everything outside section E and
plan §G clears at S or below except A.1/A.2 (both M) — sorting by Effort and taking XS+S is
the "no new features" backlog; the 13 XS rows are one sitting. **Batching hints:** B.1 +
B.2 + B.3 + B.5 + C.2 + C.3 + D.1's doc steps are one post-fix docs-reconciliation pass;
F.2 + F.3 + C.1 are one credential-plugin work item; F.4 + F.9 are a minutes-long hygiene
batch.

| Status | ID | Was | Item | Sev | Pri | Score | Effort |
|---|---|---|---|---|---|---|---|
| `[ ]` | E.1 | E.1 | Async batch inference APIs (OpenAI Batch, Anthropic Message Batches) | 5 | 3 | 15 | XL |
| `[ ]` | F.1 | F.1 | Tier 3 attestation is detection, not attestation (→ plan §G) | 5 | 3 | 15 | XL (→ §G) |
| `[ ]` | G.3 | G.4 | CPU attestation-quote verification behind the `attest` extra | 5 | 3 | 15 | L |
| `[ ]` | E.2 | E.2 | Typed `seed` / `logprobs` / penalty sampling controls | 4 | 3 | 12 | L |
| ✅ | F.2 | new | Unknown credential schemes fall through to LiteralResolver; plugin issues discarded | 3 | 4 | 12 | S |
| `[ ]` | G.1 | G.2 | Demand gate: identify a confidential-tier design partner | 3 | 4 | 12 | XS |
| `[ ]` | G.2 | G.3 | CC hardware validation sprint (rent, capture, fixture) | 4 | 3 | 12 | M |
| `[ ]` | E.5 | E.5 | OpenAI Responses API endpoint on the sidecar | 3 | 3 | 9 | L |
| `[ ]` | E.6 | E.6 | Ship accurate token estimators behind the existing protocol | 3 | 3 | 9 | M |
| `[ ]` | G.4 | G.5 | Claims and docs update once quote verification lands | 3 | 3 | 9 | S |
| ✅ | B.1 | new | README embeddings enumeration omits Gemini and llama.cpp | 2 | 4 | 8 | XS |
| ✅ | B.2 | new | Observability guide contradicts the shipped sinks it never mentions | 2 | 4 | 8 | S |
| ✅ | C.1 | new | `anyinfer.credential_stores` entry-point group undocumented | 2 | 4 | 8 | S |
| ✅ | D.1 | new | `anyinfer_cache` wire extension: undocumented, one-way, untested | 2 | 4 | 8 | S |
| `[ ]` | E.3 | E.3 | Provider-native server-side tools (web search, code execution) | 4 | 2 | 8 | XL |
| ✅ | D.2 | new | Proxy/TLS settings do not reach auth token exchanges; boundary unstated | 2 | 3 | 6 | S |
| `[ ]` | E.4 | E.4 | Typed citations / grounded-generation output | 3 | 2 | 6 | L |
| ✅ | F.3 | new | Credential-store plugins can shadow built-in schemes | 2 | 3 | 6 | S |
| ✅ | B.5 | new | AGENTS.md misnames the demo tests subpackage | 1 | 5 | 5 | XS |
| ✅ | F.4 | new | Relay (and sidecar) auth 500s on a non-ASCII bearer token | 1 | 5 | 5 | XS |
| ✅ | F.9 | new | `ci.yml` has no `permissions:` block | 1 | 5 | 5 | XS |
| ✅ | B.3 | new | Serve page's wire-contract prose trails the codec | 1 | 4 | 4 | XS |
| ✅ | C.2 | new | New config/plugins public API missing from the API reference | 1 | 4 | 4 | S |
| ✅ | C.3 | new | Request-body cap has a flag but no prose documentation | 1 | 4 | 4 | XS |
| `[ ]` | E.7 | E.7 | Video input parts | 2 | 2 | 4 | M |
| `[ ]` | E.8 | E.8 | Runtime credential rotation / hot reload | 2 | 2 | 4 | M |
| ✅ | F.5 | new | Relay HTTP surface lacks the request-body cap | 1 | 4 | 4 | S |
| ✅ | F.6 | new | Telemetry-sink redaction edge gaps (dict keys, `default=str`, chmod) | 1 | 4 | 4 | XS |
| ✅ | B.4 | new | Proxy/TLS keys documented as universal but no-op on copilot | 1 | 3 | 3 | S |
| ✅ | D.3 | new | Sidecar rejects `reasoning_effort: "none"` | 1 | 3 | 3 | S |
| ✅ | D.4 | new | `LoggingObserver` options escape load-time validation | 1 | 3 | 3 | S |
| ✅ | D.6 | new | `ProviderSettings` TLS docstrings + missing forwarding test | 1 | 3 | 3 | S |
| ✅ | F.7 | new | Demo literal-secret stripping fails open for unknown providers | 1 | 3 | 3 | S |
| ✅ | F.8 | new | Body-limit middleware replays a truncated body on disconnect | 1 | 3 | 3 | S |
| ⏭️ | F.10 | F.13 | `COHERE.key`: rotate and move to env/keyring (kept by owner decision) | 1 | 3 | 3 | XS |
| `[ ]` | G.5 | G.6 | GPU SPDM attestation (explicitly deferred; triggers recorded) | 3 | 1 | 3 | XL |
| ✅ | A.1 | A.5 | Physically group the root evaluation modules (deferred move) | 1 | 2 | 2 | M |
| ⏭️ | A.2 | new | Mixin `TYPE_CHECKING` signature stubs can drift compatibly | 1 | 2 | 2 | M |
| ✅ | D.5 | new | Observer-config decisions unrecorded (payload-free-only; import-at-parse) | 1 | 2 | 2 | XS |
| 🔁 | D.7 | D.7.4 | Contract-snapshot live-verification burn-down | 1 | 2 | 2 | XS |
| `[ ]` | E.9 | E.11 | Local model store guided eviction (`prune`) | 1 | 2 | 2 | M |
| ✅ | A.3 | new | `cli.py` stay-single-file decision lacks a growth threshold | 1 | 1 | 1 | XS |
| ✅ | H.1 | new | Documented `verify` + `client_cert` combination is a `TypeError` in httpx2 | 4 | 5 | 20 | S |
| ✅ | H.2 | new | Copilot `cli_path` is a `TypeError`; `aclose` leaks the CLI process | 4 | 5 | 20 | S |
| ✅ | H.3 | new | Dead `filterwarnings` exemption silently covers future starlette drift | 1 | 4 | 4 | XS |
| 🚧 | C.4 | C.3.2 | Delete add-on install caveats when the first PyPI release ships | 1 | 1 | 1 | XS |

---

# A. Codebase technical state

## A.0 Overall assessment

**Verdict: excellent, and better than v1.** The v1 debt is paid: `async_client.py` went from
4,186 to 2,557 lines via a verified pure-move mixin split (`GenerationExecutionMixin`,
`ArenaExecutionMixin`, `SpendGovernanceMixin` + `stream.py`/`messages.py` — removed/re-added
lines compared as multisets, nothing dropped); the demo package was cleanly renamed to
`anyinfer_demo` (wheel collision risk gone); the import-linter sidecar contract now covers
the whole `anyinfer.serve` package so new modules are policed on arrival; and DESIGN.md §18
is regenerated **and enforced by a bidirectional layout-drift test**
(`tests/test_agent_instructions.py::test_design_section_18_layout_matches_the_tree`), so the
v1 doc-drift class cannot silently recur. Decisions taken instead of code (cli.py stays one
module; `MainWindow` accepted as demo-grade) are recorded in DESIGN.md with reasoning and
exit conditions. New modules (`events/sinks.py`, `plugins.py`) are well-homed and
boundary-clean. What remains below is watch-list, not debt.

## A.1 — Physically group the root evaluation modules

**Severity:** Low · **Confidence:** High · **Was:** A.5 (remainder)
**Paths:** `src/anyinfer/arena.py`, `compare.py`, `compare_diff.py`, `context_request.py`

**Brief:** The v1 sprawl finding was closed by documenting every root module in §18 (drift-
tested), but the physical grouping was deliberately deferred because moving changes public
import paths (`anyinfer.arena`, `anyinfer.compare`).

**Long:** Deferral was the right call to keep the remediation batch mechanical — but the
window is pre-1.0 only. Once 1.0 freezes the API, `anyinfer/evaluate/` (or similar) requires
deprecation shims forever; before it, the move is one commit plus import updates.

**Remediation:**
- [x] **A.1.1** Done 2026-08-25: `arena.py`, `compare.py`, `compare_diff.py` moved to
  `src/anyinfer/evaluate/` with a package docstring stating why the three group together.
  Top-level re-exports in `anyinfer/__init__.py` are unchanged, so `ai.ArenaResult` and
  `ai.TargetComparison` still resolve; `anyinfer.compare_diff` did move to
  `anyinfer.evaluate.compare_diff` (its API-reference directives, `workspace.py`'s
  `_PUBLIC_SURFACES`, and two test modules updated in the same change).
  **`context_request.py` was NOT moved, and cannot be** — both suggested destinations
  break an architecture contract: it imports `anyinfer.context`, which the "Types are leaf
  modules" contract forbids for anything under `types/`; and moving it into `context/`
  would make `types/requests.py`/`types/results.py` direct importers of a forbidden
  module. The root placement is load-bearing, which is what its own docstring already
  said. Recorded as a decision in DESIGN §18 rather than left as a deferred move.

  **Finding surfaced while doing this:** the §18 drift test did **not** force the update,
  contrary to this item's premise — `_tree_modules()` compared bare *filenames*, so moving
  a module between packages left it green. A second test
  (`test_design_section_18_places_each_module_in_the_right_package`) now checks placement,
  and was confirmed to fail on an injected misplacement before being kept.
- [ ] **A.1.2** If 1.0 arrives first, close this item as "root layout is final" and delete
  the §18 annotations that call these placements provisional.

## A.2 — Mixin `TYPE_CHECKING` signature stubs can drift compatibly

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `src/anyinfer/_client/generation.py:237-291`, `arena_exec.py:85-180`,
`spend.py:55-66`

**Brief:** The A.1 split's mixins carry hand-maintained `TYPE_CHECKING` copies of sibling
method signatures (e.g. `arena_exec.py` restates the full 20-parameter `generate`); mypy
checks override *compatibility*, not equality, so a compatibly-extended real signature
leaves stubs silently stale until a mixin calls the new parameter.

**Long:** The design is self-aware (each block says "Declared, never defined — `AsyncClient`
supplies these") and makes the coupling visible, which beats implicit `Any`. But it is a new
duplication class the pre-split file did not have. Related cohesion wart, same root:
`messages.py` hosts the `_spend_prechecked` ContextVar alongside message coercion because two
mixins need it and neither may import the client back.

**Remediation:**
- [ ] **A.2.1** If the stubs churn (first time a stub goes stale in review): introduce a
  single `_ClientProtocol` Protocol all three mixins reference, so each signature exists
  twice (protocol + real) instead of up to four times. Until then, no action — record-only.

**Skipped 2026-08-25 (⏭️):** the item's own trigger has not fired. No stub went stale in
this pass, and acting early would spend an M-sized refactor removing a duplication that is
not yet costing anything.

## A.3 — `cli.py` stay-single-file decision lacks a growth threshold

**Severity:** Low · **Confidence:** Medium · **Was:** new
**Paths:** `src/anyinfer/cli.py` (3,801 lines), `DESIGN.md:869-877`

**Brief:** The recorded decision's exit condition is "revisit if it keeps growing" with no
number — and the file grew 25 lines in the very batch that recorded it (D.3-of-v1 serve
flags land here, as will every future CLI-visible feature).

**Remediation:**
- [x] **A.3.1** Add a concrete trigger to the DESIGN §18 note (suggest: "revisit at 4,500
  lines"), so the clause is executable rather than re-litigated ad hoc.

---

# B. Reality vs documentation posture

## B.0 Overall posture

**Verdict: v1's findings are fully paid; the new drift is same-window growth.** All seven v1
items verified closed: the sidecar page now matches the route table, the conformance matrix
gained a third glyph (🔗 "implemented, verified by dedicated tests") with its header count
*derived at render time*, the CLI/§18/count enumerations all reconcile (re-counted today: 86
presets exact, 20 adapters, 18 error classes, 20 typed events), and the §18 drift test closes
the class. The five new items share one root: commits later in the same window
(`ff8fdcc`, `ed337b8`) updated reference pages but not the guides/README/serve-page prose
that restates the same facts. **Working rule worth adopting:** when a feature lands, grep the
docs for sibling restatements of the fact it changes — the reference page is never the only
place.

## B.1 — README embeddings enumeration omits Gemini and llama.cpp

**Severity:** Low-Medium · **Confidence:** High · **Was:** new
**Paths:** `README.md:208-210` vs `src/anyinfer/providers/gemini.py:789`,
`llama_cpp.py:664`, `docs/providers/gemini.md:103`, `docs/providers/llama-cpp.md:105`

**Brief:** The front-page "Embeddings and/or reranking are live today on …" sentence omits
Gemini and llama.cpp, both of which declare `operations={"generation","embedding"}`, have
dedicated tests, show 🔗 in the just-regenerated conformance matrix, and are documented as
embedding-capable on their own provider pages.

**Long:** This is the v1 B.2 story's last unswept surface: the matrix fix corrected the
generated page but not the hand-written README sentence restating the same set. A user
choosing an embedding target from the README rules out two working providers, and the README
now contradicts two provider pages and the matrix — the repo's own no-self-contradiction
class.

**Remediation:**
- [x] **B.1.1** Add Gemini and llama.cpp to the README sentence (llama.cpp with its
  embeddings-server caveat if wanted); grep `docs/` for any other restatement of the
  embeddings-capable set and align wording in the same commit.

## B.2 — Observability guide contradicts the shipped sinks it never mentions

**Severity:** Medium-Low · **Confidence:** High · **Was:** new
**Paths:** `docs/guides/observability.md:69-72` vs `src/anyinfer/events/sinks.py`,
`docs/reference/configuration.md:481-504`

**Brief:** The guide's "A JSONL Trail" section tells users to hand-write the exact ~40-line
observer that `JsonlObserver` now ships to eliminate, and never names `LoggingObserver`,
`JsonlObserver`, or the `observers` config block — while the configuration reference says
"`logging` and `jsonl` ship with the library."

**Long:** `ed337b8` updated the two reference pages but not the guide, so the site
simultaneously teaches "build it yourself" and "it's built in." The guide is the page users
actually read when they want an audit trail.

**Remediation:**
- [x] **B.2.1** Rewrite the JSONL Trail section around `JsonlObserver` + the `observers`
  config block; link `reference/api/telemetry.md`'s sink section; keep a one-line "writing
  your own observer" pointer for the custom case.

## B.3 — Serve page's wire-contract prose trails the codec

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `docs/serve/README.md:95-105` vs `src/anyinfer/serve/openai_codec.py:127,328-341,367`

**Brief:** The "Survives" list omits `reasoning_effort` (now typed and cross-provider
translated, added in `ff8fdcc` after the page's last edit), and the deliberate 400s for
`n>1` and `logprobs`/`top_logprobs` appear nowhere on the page defining what the wire
accepts.

**Remediation:**
- [x] **B.3.1** Add `reasoning_effort` to the Survives list; one sentence on the
  `n`/`logprobs` refusals and why (single-completion primitive; unreturnable billing).

## B.4 — Proxy/TLS keys documented as universal but no-op on copilot

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `docs/reference/configuration.md:48-77` vs `src/anyinfer/providers/copilot.py`

**Brief:** The configuration reference presents `proxy`/`verify`/`client_cert` as
per-provider-instance keys with no exceptions; every HTTP adapter honors them via
`build_client`, but the copilot adapter delegates transport to `github-copilot-sdk` and
never reads them — the parser accepts the keys and the runtime ignores them.

**Remediation:**
- [x] **B.4.1** Either document the copilot exception in the TLS section, or (better) raise
  `ConfigError`/warn when these keys are set on a provider whose adapter cannot honor them —
  matching the parser's existing "reject noise" style (`verify: true` is already rejected
  with a hint).

## B.5 — AGENTS.md misnames the demo tests subpackage

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `AGENTS.md:106` vs `tests/demo_app/`, `AGENTS.md:60`

**Brief:** The line the v1 A.6 fix corrected is false again in one detail: it now lists the
mirrored test subpackages as "`context/`, `anyinfer_demo/`, `mcp/`, `testing/`", but the
directory kept its old name `tests/demo_app/` through the package rename — as line 60 of the
same file correctly states.

**Remediation:**
- [x] **B.5.1** Change line 106's token to `demo_app/` (matching line 60 and the tree), or
  rename the directory — one word either way.

---

# C. Quality of documentation

## C.0 Overall quality

**Verdict: still top-decile; v1's items all closed.** The confidential add-on now has a real
generated API reference (all 23 directives import-resolve), first-run snippets are
copy-paste runnable, the glossary/nav/skeleton polish all landed, and the changelog question
is answered explicitly (GitHub Releases canonical, stated in `reference/README.md`). The new
items are coverage gaps for brand-new features — written into reference pages but not into
the guides and API-reference surfaces users reach first.

## C.1 — `anyinfer.credential_stores` entry-point group undocumented

**Severity:** Low-Medium · **Confidence:** High · **Was:** new
**Paths:** `src/anyinfer/plugins.py:48-49`, `src/anyinfer/credentials/resolver.py:102-115`
vs `docs/concepts/credentials.md`, `docs/reference/configuration.md:151`

**Brief:** A shipped extension point whose stated purpose is discoverability-from-config
("the sidecar has no other way to reach one") is invisible to the people it exists for: zero
mentions anywhere in `docs/` — while the sibling `anyinfer.observers` group is documented.

**Long:** An organization wanting its vault scheme available to the sidecar binary cannot
learn the group name, the precedence rule (plugins resolve *ahead of* built-ins), or the
protocol to implement without reading source. Document this together with the F.2/F.3 fixes
so the precedence and failure semantics described are the hardened ones.

**Remediation:**
- [x] **C.1.1** Add a "Custom credential schemes" section to `docs/concepts/credentials.md`:
  group name, `CredentialResolver` protocol, precedence, and failure behavior
  (post-F.2/F.3); cross-link from configuration.md's credentials section.

## C.2 — New config/plugins public API missing from the API reference

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `src/anyinfer/config/__init__.py:29-41`, `src/anyinfer/plugins.py` vs
`docs/reference/api/configuration.md`

**Brief:** `ObserverSpec`, `build_observers`, and `BUILTIN_OBSERVERS` joined
`anyinfer.config.__all__` (and configuration.md tells users to call `build_observers`), but
no reference page renders their signatures; the `anyinfer.plugins` module (`PluginLoadIssue`,
`load_observers`, `load_credential_stores`, group constants) likewise has no reference
surface. This dents the previously verified "every public export has a directive" property.

**Remediation:**
- [x] **C.2.1** Add mkdocstrings directives for the three config names to
  `docs/reference/api/configuration.md` (and the pre-existing `COMMENT_KEY` nit).
- [x] **C.2.2** Either add a small plugins section to an existing API page or
  underscore-privatize whatever in `anyinfer.plugins` is not meant to be public — one or the
  other, recorded.

## C.3 — Request-body cap has a flag but no prose documentation

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `src/anyinfer/serve/app.py:57-64`, `src/anyinfer/cli.py:66-75` vs
`docs/serve/README.md` (Security section)

**Brief:** The 10 MiB default, the 413 response, `--max-request-bytes`, and the `0` disable
value exist in code and the auto-rendered docstring only; a CLI operator or a client
debugging a 413 finds nothing in prose.

**Remediation:**
- [x] **C.3.1** One bullet in the serve README's Security section: default, flag, `0` to
  disable, and that the cap is enforced while reading (a lying `Content-Length` doesn't
  help).

## C.4 — Delete add-on install caveats when the first PyPI release ships

**Severity:** Low · **Confidence:** High · **Was:** C.3.2 (blocked on external event)
**Paths:** `docs/guides/installation.md:45-47`, `docs/guides/confidentiality-tiers.md:44-45`,
`docs/guides/vector-store.md:10`

**Brief:** The v1 fix added consistent "install from a checkout until PyPI" caveats; this is
the standing reminder to remove all of them in one commit when `anyinfer-confidential` /
`anyinfer-store` / `anyinfer-shared` first publish.

**Remediation:**
- [ ] **C.4.1** On first add-on PyPI release: delete the caveats in all three files (grep
  for "checkout" under `docs/` to catch strays) in one commit.

**Blocked 2026-08-25 (🚧):** gated on an external event — `anyinfer-confidential`,
`anyinfer-store`, and `anyinfer-shared` have not published. Caveat text left intact.

---

# D. Completeness of current features

## D.0 Overall completeness

**Verdict: v1's items all closed with tests; new gaps cluster at the edges of the new
features.** Verified this round: base64 embeddings encoding, typed `reasoning_effort`
round-trip, serve `repair`/`context` config, explicit `n`/logprobs 400s,
`ConfidentialityReport.from_status`, recorded demo exemptions, and the DESIGN ledger
reconciliation. The E.9/E.10/E.12/E.13-of-v1 feature closures are real implementations with
tests (the sinks and the §20a decision log notably strong). The items below are where the
new code meets pre-existing machinery or its own docs. One stale v1 claim corrected: the
model store already tracks `last_used_at`, so only the `prune` surface remains (now E.9).

## D.1 — `anyinfer_cache` wire extension: undocumented, one-way, untested

**Severity:** Medium-Low · **Confidence:** High · **Was:** new
**Paths:** `src/anyinfer/serve/openai_codec.py:88,134,369,400-428` vs
`docs/serve/README.md:241-243`, `docs/concepts/caching.md`; `request_to_openai`

**Brief:** The codec decodes a fifth extension, `anyinfer_cache` (→ typed `CachePolicy`),
but the serve README's Key Takeaways enumerates the extensions as a closed set of four,
`request_to_openai` never re-encodes `request.cache` (a lossy gap — DESIGN §22 invariant 1
calls any such gap "a design bug, caught by a round-trip test"; the test passes only because
it never generates the field), and no test anywhere exercises the extension.

**Long:** This is v1's B.1 shape at smaller scale — a shipped wire capability the canonical
page's own enumeration denies — plus a genuine codec asymmetry the project's own invariant
forbids. Whoever added the decode did the request side only.

**Remediation:**
- [x] **D.1.1** Mirror `request.cache` in `request_to_openai` (or record the one-way choice
  in the codec docstring and exempt it from the invariant explicitly).
- [x] **D.1.2** Add a codec round-trip case that generates the field.
- [x] **D.1.3** Add `anyinfer_cache` to the serve README's extension enumeration and a
  paragraph in `docs/concepts/caching.md`'s sidecar note.

## D.2 — Proxy/TLS settings do not reach auth token exchanges; boundary unstated

**Severity:** Medium-Low · **Confidence:** High (code), Medium (impact) · **Was:** new
**Paths:** `src/anyinfer/providers/cloud_auth.py:395`, `providers/azure_foundry.py:76-95`,
`src/anyinfer/mcp/transport.py:190`, `src/anyinfer/local/sources/huggingface.py:182`,
`local/services.py:112-117`

**Brief:** The v1-E.9 settings thread through all eleven HTTP data-plane adapters, but the
Google OAuth token exchange uses a bare `httpx2.Client`, Entra rides the azure SDK's own
stack, and MCP transport and model downloads take no TLS settings — so a Vertex instance
configured with a corp CA behind an intercepting proxy has `generateContent` succeed and its
token exchange fail TLS verification, and no doc sentence draws the line.

**Remediation:**
- [x] **D.2.1** Thread `proxy`/`verify` into `GoogleTokenSource` (it already has a
  `transport` seam, so the plumbing pattern exists).
- [x] **D.2.2** Add one sentence to configuration.md's TLS section stating what the keys do
  NOT cover (auth token endpoints other than Google's once D.2.1 lands, MCP servers, model
  downloads) and that env vars govern those.

## D.3 — Sidecar rejects `reasoning_effort: "none"`

**Severity:** Low · **Confidence:** Medium · **Was:** new
**Paths:** `src/anyinfer/serve/openai_codec.py` (`_decode_reasoning_effort`),
`src/anyinfer/types/requests.py:108` (`ReasoningEffort` literal)

**Brief:** The v1-D.2 fix types `reasoning_effort` and refuses unknown values loudly —
correct — but the normalized vocabulary (`minimal|low|medium|high`) is narrower than
OpenAI's current one, which accepts `"none"` on newer models; a stock client that worked via
passthrough now gets a 400 against an OpenAI backend.

**Remediation:**
- [x] **D.3.1** Done 2026-08-25 by owner decision (extend the literal): `ReasoningEffort`
  now carries `"none"`, distinct from both `"minimal"` and `None`. Every registered
  descriptor spells it in its own terms — `thinking: disabled` (anthropic, cohere, bedrock,
  deepseek), `think: false` (ollama), `thinkingBudget: 0` (gemini, vertex),
  `reasoning: "off"` (lm-studio), `reasoning: {enabled: false}` (openrouter and the
  `reasoning-object` preset style), and the literal value passed through where the provider
  tracks OpenAI's vocabulary (openai, azure-foundry, nebius, xai, the `effort` preset
  style). `tests/test_reasoning_effort.py` pins each mapping plus three invariants: every
  descriptor translates every level, `none` never becomes a *positive* level, and
  `None`/`"none"`/`"minimal"` stay mutually distinct.

  **Two preset styles omit the field instead** (`effort-min-low`, `effort-three-level`):
  those providers publish enums with no off value, so clamping onto `low` would request
  more reasoning than was asked for, and passing `none` would be rejected upstream. Each
  translator docstring records the choice. Vocabulary restatements updated in `cli.py`
  choices, DESIGN §5, the CLI/OpenAI/configuration docs, and the
  openai/nebius/gemini/lm-studio/xai contract snapshots.

## D.4 — `LoggingObserver` options escape load-time validation

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `src/anyinfer/events/sinks.py:101-115`, `src/anyinfer/config/__init__.py:965-1012`

**Brief:** `build_observers` promises a typo "fails at load rather than at the first event,"
but `LoggingObserver.__init__` accepts any `level` unvalidated: `{"level": "INFO"}` (a
string) passes load, then `isEnabledFor("INFO")` raises `TypeError` on every event, which
the dispatcher suppresses after one `RuntimeWarning` — a silently empty access log. Also
`logger` only accepts a `Logger` object, so a config file cannot select a logger name.

**Remediation:**
- [x] **D.4.1** Accept `level: int | str` (resolve strings, raise `ValueError` on unknown —
  already mapped to `ConfigError` by `build_observers`) and `logger: Logger | str | None`;
  add a config-load test for the string forms.

## D.5 — Observer-config decisions unrecorded

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `src/anyinfer/config/__init__.py:950-955`, `src/anyinfer/plugins.py:66-68`,
`docs/reference/configuration.md:503`

**Brief:** Two defensible-looking choices in the observers block are nowhere recorded as
choices: config-named sinks are always payload-free with no opt-in path (while the docs say
"unless the subscription opts into payloads," which config-only deployments cannot do), and
validating a non-builtin observer name at load calls `point.load()`, importing third-party
code during `load_config`.

**Remediation:**
- [x] **D.5.1** One sentence in the observers block docs: config-named sinks are payload-free
  by design; fix the "unless the subscription opts in" wording for the config path.
- [x] **D.5.2** Either validate names against entry-point *metadata* without `.load()` at
  parse time, or record import-at-parse as the accepted behavior in the parser docstring.

## D.6 — `ProviderSettings` TLS docstrings + missing forwarding test

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `src/anyinfer/_client/providers.py:37-66`, `tests/test_config.py:585-636`

**Brief:** `ProviderSettings`' Attributes list stops before the new
`proxy`/`verify`/`client_cert` fields, and no test pins that `build_client` actually
forwards them into `httpx2.AsyncClient` (or that they're ignored under a supplied
`transport`) — the one seam a regression could slip through untested; current tests assert
config→settings only.

**Remediation:**
- [x] **D.6.1** Add the three attribute docstrings; add one unit test inspecting the built
  client for both the set-fields and transport-supplied cases.

## D.7 — Contract-snapshot live-verification burn-down

**Severity:** Low · **Confidence:** High · **Was:** D.7.4 (ongoing)
**Paths:** `contracts/*.md`, `.github/workflows/contract-drift.yml`

**Brief:** Unchanged this window: six snapshots still carry the bold "Not yet verified
against live provider documentation" marker (anthropic, copilot, m365-copilot, openai,
openai-compat, openrouter), and jina/voyage self-describe never-live-verified calls, with
ollama/azure-foundry generation sections resting on code survey.

**Long:** Self-scheduling — the weekly drift workflow ranks never-verified snapshots first —
so this needs patience more than work; it stays tracked so the count is watched rather than
assumed.

**Remediation:**
- [ ] **D.7.1** Let the drift rotation clear them; record clearance dates in each snapshot
  as runs land. Check the count at the next status rebuild; escalate only if it has not
  moved.

**Recount 2026-08-25: seven, not six.** `contracts/ollama.md` also carries the "Not yet
verified against live provider documentation" marker, which this item's Brief omitted. The
full current set is anthropic, copilot, m365-copilot, ollama, openai, openai-compat,
openrouter. Unchanged otherwise — still self-scheduling, still watch-only.

---

# E. Obvious feature misses

## E.0 Scope discipline

Four v1 misses closed this window with real implementations: per-instance **proxy/CA/mTLS**
(v1 E.9), **plugin entry-point groups** for credential stores and observers (v1 E.10),
**shipped logging/JSONL telemetry sinks** (v1 E.12), and the **fenced-non-goals decision
log** — now DESIGN.md §20a, recording dated decisions on MCP server exposure, exact-match
replay, and same-provider key pooling, each with a revisit trigger (v1 E.13). The v1
non-goals list remains honored and re-verified: response/semantic caching, image/audio/video
*output*, fine-tuning, load balancing, org control plane, agent-framework constructs, prompt
templating, cross-provider continuation, run retention, non-Python SDKs — none of these are
misses; do not "fix" them. Everything below was re-verified absent on 2026-08-25 (v2) by
grep against current source.

## E.1 — Async batch inference APIs (OpenAI Batch, Anthropic Message Batches)

**Severity:** High · **Confidence:** High · **Was:** E.1

**Expected because:** every major provider sells a ~50%-discounted deferred batch tier, and
AnyInfer's identity is cost-aware dispatch (pricing tables, `SpendPolicy`, `SpendLedger`,
per-request cost estimation). Evals, backfills, and offline enrichment are this audience's
staple workloads. **Evidence of absence (re-verified):**
`grep -rniE "message_batch|/batches|batch_id" src/anyinfer` → zero hits; every "batch" in
the codebase is synchronous embedding-input splitting or llama-server tuning. Not a stated
non-goal.

**Long:** The typed request model, capability provenance, and pricing tables are *more*
valuable in batch mode, yet the library cannot express "submit these 10k requests at half
price" — users drop to raw provider SDKs and lose structured-output enforcement, telemetry,
and cost accounting on their highest-volume traffic.

**Remediation sketch:**
- [ ] **E.1.1** New operation type per the embeddings pattern: `BatchGenerationRequest →
  BatchHandle → BatchResult`, an opt-in `SubmitsBatches` protocol adapters implement
  individually (OpenAI, Anthropic, Bedrock, Vertex, Groq all ship batch endpoints),
  descriptor-declared.
- [ ] **E.1.2** Reuse `GenerationRequest` as the line-item type and existing codecs for
  serialization; typed submitted/completed lifecycle events.
- [ ] **E.1.3** The run-retention non-goal holds: AnyInfer never persists the job registry —
  the handle is the caller's to store.

## E.2 — Typed `seed` / `logprobs` / penalty sampling controls

**Severity:** Medium-High · **Confidence:** High · **Was:** E.2

**Expected because:** OpenAI-dialect table stakes accepted by ~80 of the presets, and the
product's core promise is "no per-engine branches in consuming apps." **Evidence of absence
(re-verified):** `Sampling` in `types/requests.py` still has exactly `temperature`,
`top_p`, `max_output_tokens`, `stop`; no logprobs surface on `Generation`. Preset notes
still tell users to hand-spell provider variants (Mistral `random_seed`).

**Long:** The `provider_options` escape hatch defeats the promise — a seeded run requires
knowing each provider's spelling, and logprobs have nowhere to land in normalized results,
which hard-stops eval harnesses and classification-with-confidence callers. The sidecar now
400s `logprobs` explicitly (v1 D.4 fix), which is honest but makes the gap a visible wall
for OpenAI-client migrations.

**Remediation sketch:**
- [ ] **E.2.1** Extend `Sampling` additively with `seed`, `presence_penalty`,
  `frequency_penalty` (defaults `None`; never invent a value).
- [ ] **E.2.2** Add a `logprobs` request field with a typed `TokenLogprob` result surface on
  `Generation`; emit the existing `ParameterDropped` event where unsupported.
- [ ] **E.2.3** Sidecar codec: decode these as typed fields and retire the `logprobs` 400
  (the `n>1` refusal stays).

## E.3 — Provider-native server-side tools (web search, code execution)

**Severity:** Medium-High · **Confidence:** High · **Was:** E.3

**Expected because:** Anthropic, OpenAI, Gemini, and xAI all ship server-executed tools;
"grounded answer with fresh web results" is a top application feature. **Evidence of absence
(re-verified):** `grep -rniE "web_search|server_tool|code_interpreter" src/anyinfer` → zero
code hits; `ToolSpec` models client-executed tools only. The "not an agent framework"
non-goal fences planning/memory, not provider-native passthrough — the provider executes the
tool inside one request/response, squarely translate-only territory.

**Remediation sketch:**
- [ ] **E.3.1** Add a `ServerToolSpec` union member beside `ToolSpec`, typed per capability
  (`web_search`, `code_execution`), capability-declared with provenance so unsupported
  targets refuse before dispatch.
- [ ] **E.3.2** Map server-tool result blocks to a typed event; add per-invocation pricing
  line items.

## E.4 — Typed citations / grounded-generation output

**Severity:** Medium · **Confidence:** High · **Was:** E.4

**Expected because:** RAG-with-attribution is a dominant pattern; Anthropic citations,
Cohere grounded chat, and Gemini grounding metadata all return structures users must render.
**Evidence of absence (re-verified):** no `Citation` type in `types/`; the gap remains
self-acknowledged in two adapters (`m365_copilot.py` retains citations on `raw`;
`cohere.py`'s docstring advertises grounded citations its generate path never requests).

**Remediation sketch:**
- [ ] **E.4.1** Add `citations` to `Generation` and a citation event to the event union;
  adapters map each dialect.
- [ ] **E.4.2** Request-side grounding documents reuse `DocumentPart`/context blocks.
- [ ] **E.4.3** Sidecar projects citations under an `anyinfer_*` extension field (and, per
  D.1's lesson, document + round-trip-test the extension in the same change).

## E.5 — OpenAI Responses API endpoint on the sidecar

**Severity:** Medium · **Confidence:** High · **Was:** E.5

**Expected because:** the Responses API is OpenAI's current-generation surface and
Responses-first SDKs/frameworks 404 against a chat-completions-only gateway — while
AnyInfer's *own* OpenAI adapter speaks `POST /responses` upstream, so the project already
treats it as the real dialect. **Evidence of absence (re-verified):** `serve/app.py`'s route
table has no `/v1/responses`; the catch-all 404s it.

**Remediation sketch:**
- [ ] **E.5.1** Add `serve/responses_codec.py` beside `openai_codec.py` mapping
  `POST /v1/responses` (input items → `Message` parts, `text.format` → `SchemaSpec`,
  semantic streaming events) under the wire-codec invariants; update the serve README route
  table in the same commit (B.3's lesson).
- [ ] **E.5.2** Refuse `previous_response_id` explicitly or map it onto `Session` — never
  silently emulate server-side state.

## E.6 — Ship accurate token estimators behind the existing protocol

**Severity:** Medium · **Confidence:** High · **Was:** E.6

**Expected because:** context budgeting is a headline capability and the category norm
(tiktoken, Anthropic `count_tokens`, llama-server `/tokenize`) makes real counts assumed.
**Evidence of absence (re-verified):** `capabilities/estimate.py` still ships only the
byte-heuristic; tiktoken appears in docstrings only; no `[tokenizers]` extra. The
`TokenEstimator` protocol is complete; implementations are wholly absent — so the context
gate, cache-mark placement, and `SpendPolicy.max_request_usd` all run on a heuristic.

**Remediation sketch:**
- [ ] **E.6.1** Ship optional estimators behind extras: tiktoken-backed (exact for
  OpenAI-family), Anthropic count-tokens endpoint (opt-in, cached), llama-server
  `/tokenize` for local targets.
- [ ] **E.6.2** Wire per-provider selection through `TokenCalibration` with provenance so
  gating knows when a floor is exact.

## E.7 — Video input parts

**Severity:** Low-Medium · **Confidence:** High · **Was:** E.7

**Brief:** `ContentPart` still models Text/ToolCall/ToolResult/Image/Document/Audio — no
`VideoPart` (re-verified), so a Gemini video request (a marquee Gemini use case) cannot be
expressed. The multimodal non-goal covers *outputs*, not video input; this is unaddressed
rather than fenced.

**Remediation:**
- [ ] **E.7.1** Add `VideoPart` (data-or-URL, `video/*` media-type check, its own byte
  ceiling) to `types/messages.py`; project in `providers/_multimodal.py` for Gemini/Vertex;
  refuse elsewhere via trusted capability absence.

## E.8 — Runtime credential rotation / hot reload

**Severity:** Medium-Low · **Confidence:** Medium · **Was:** E.8

**Brief:** Re-verified untouched by the plugin/TLS work: `api_key` references are still
resolved once at adapter build (`_client/providers.py:299`; docstring says so), with no
TTL/lazy re-resolution and no 401-triggered retry — rotating a key still means restarting
the installed sidecar service, while `cloud_auth.py` proves the refresh pattern exists for
cloud tokens.

**Remediation:**
- [ ] **E.8.1** Make credential resolution lazy-per-request or TTL-cached in header
  construction (the `cloud_auth.py` refresh-margin pattern is the in-tree template).
- [ ] **E.8.2** Treat a 401-after-success as a trigger to re-resolve once before failing.

## E.9 — Local model store guided eviction (`prune`)

**Severity:** Low · **Confidence:** High · **Was:** E.11 (revised)
**Paths:** `src/anyinfer/local/store.py`, `src/anyinfer/cli.py`

**Brief:** v1 correction: `last_used_at` already exists and is maintained on store entries
(`store.py:148,533`), so the recency-data half of the v1 finding was stale. What remains is
the surface: no `prune` command and no disk budget — cleanup is manual `models rm` with no
guidance, while the tier-recommendation flow accumulates stale multi-GB variants across
hardware upgrades.

**Remediation:**
- [ ] **E.9.1** Add `anyinfer models prune [--keep-bytes N]` proposing least-recently-used
  deletions from the existing `last_used_at` data, interactive confirm, never touching
  externally-registered entries. Automatic eviction stays out.

---

# F. Security posture

## F.0 Overall posture

**Verdict: materially hardened; the v1 vulnerabilities are gone.** Verified this round: the
Relay derives tenants from authenticated tokens (timing-safe, body-tenant mismatch 403s,
tests pin the exact old hole), the demo never persists literal secrets and writes config at
0600, confidential CLI key material is 0600-from-creation, the sidecar body cap enforces
*while reading* (chunked-transfer-proof), redaction registers encoded forms of each secret,
weights verification pins fds and re-checks inode identity immediately before spawn (with
the residual mmap window honestly documented), all 50 workflow `uses:` are SHA-pinned with
Dependabot watching, and attestation now fails closed on unknown GPU CC values with the
overselling prose rewritten. v1's F.13 closed *partially* by explicit owner decision: the
key file stays, at 0600, never committed (F.10 below). The new findings are the edges of the
new code — the credential-plugin cluster (F.2, F.3) is the one to fix before publicizing the
extension point.

## F.1 — Tier 3 attestation is detection, not attestation (→ plan §G)

**Severity:** High (claim-integrity) · **Confidence:** High · **Was:** F.1 ·
**Class:** accepted-risk (now honestly labeled everywhere)
**Paths:** `src/anyinfer/local/attestation.py`, `src/anyinfer/providers/confidential_execution.py`

**Brief:** Unchanged in substance: `end_to_end` rests on device-node existence and
`nvidia-smi` parsing; no quote is generated or verified. What DID land (v1 G.1): the
overselling is gone — DESIGN §30.4 now says "What ships today is TEE detection, not
attestation," the GPU CC parse fails closed on unknown values with fixture tests, and all
three consumer surfaces carry the advisory-local-only warning. The honest posture is fully
shipped; the crypto is not.

**Remediation:** tracked entirely by plan **§G** (hardware- and demand-gated). Mark this
item done when G.1–G.4 complete (G.5 may remain open). v1 step mapping for old commit
references: F.1.1→G.3, F.1.2→G.3.3, F.1.3/F.1.4→done (v1 G.1), F.1.5→G.3.4.

## F.2 — Unknown credential schemes fall through to LiteralResolver; plugin issues discarded

**Severity:** Medium · **Confidence:** High · **Was:** new · **Class:** vulnerability
(silent misconfiguration → reference string sent as a credential)
**Paths:** `src/anyinfer/credentials/literal.py:22-28`,
`src/anyinfer/credentials/resolver.py:108-115`, `src/anyinfer/plugins.py:95-134`,
`src/anyinfer/config/__init__.py:949-961`

**Brief:** `LiteralResolver.handles` declines only the built-in scheme names, so a
third-party reference like `vault://prod/openai` whose plugin is missing or failed to import
falls through the chain and is accepted **verbatim as the secret** — sent as the bearer
token to the configured provider — while the `PluginLoadIssue` records that would explain it
are bound to `_issues` and dropped at every call site.

**Long:** This is the exact silent failure the literal resolver's own comment says it exists
to prevent ("a typo'd `env:/OPENAI_KEY` fails loudly instead of silently becoming a
literal"), reintroduced for every scheme the new plugin group makes possible. The sidecar
starts cleanly, auth fails with a misleading 401, and the internal reference string goes on
the wire (to an operator-configured endpoint, so a confusing failure rather than a secret
leak). Contrast observers, where an unknown config name is a `ConfigError` at load.

**Remediation:**
- [x] **F.2.1** Make `LiteralResolver.handles` decline anything matching
  `^[a-z][a-z0-9+.-]*://` (or have `ResolverChain.resolve` raise `CredentialError` for
  scheme-shaped references nothing handled) so unknown schemes fail loudly.
- [x] **F.2.2** Surface plugin load issues: `warnings.warn` per issue at chain construction
  (matching the observer-failure precedent) or expose `plugin_issues` on the chain the way
  `ProviderRegistry` does.
- [x] **F.2.3** Validate `api_key` references against built-in + discovered schemes at
  config load, as observer names already are.

## F.3 — Credential-store plugins can shadow built-in schemes

**Severity:** Low-Medium · **Confidence:** High · **Was:** new · **Class:** hardening
**Paths:** `src/anyinfer/credentials/resolver.py:108-115`, `src/anyinfer/plugins.py:95-134`
vs `src/anyinfer/registry.py:741-763`

**Brief:** Discovered resolvers are imported, instantiated, and placed *ahead of* the
built-ins whenever the default chain is built, with no collision guard — any installed
distribution can transparently interpose on `env://` and `credential://` resolution for
every credential in the process. The providers entry-point group already enforces
id/alias-collision refusal; this group has no equivalent.

**Long:** Not a new code-execution primitive (an installed malicious package already runs at
interpreter startup via `.pth`), but it is a designed, silent interposition point on the
credential path specifically, reachable by a compromised transitive dependency, and
inconsistent with the discipline the providers group established.

**Remediation:**
- [x] **F.3.1** Refuse (or log loudly) a discovered resolver whose `handles()` claims
  `env://` or `credential://` probes, mirroring the providers group's id-taken rule.
- [x] **F.3.2** Document the trust delta in the plugins docstring and in C.1's new docs
  section, the way the URL-trust assumption is documented.

## F.4 — Relay (and sidecar) auth 500s on a non-ASCII bearer token

**Severity:** Low · **Confidence:** High (reproduced) · **Was:** new · **Class:**
vulnerability (robustness; fails closed, no bypass)
**Paths:** `src/anyinfer-confidential/src/anyinfer_confidential/app.py:53`,
`src/anyinfer/serve/app.py:451-458`

**Brief:** `secrets.compare_digest` raises `TypeError` on non-ASCII strings; Starlette
decodes headers latin-1, so any request with a byte ≥ 0x80 in the Authorization value turns
a clean 401 into an unhandled exception → 500, mintable by any unauthenticated client. The
sidecar's `_check_auth` shares the pattern.

**Remediation:**
- [x] **F.4.1** Compare bytes in both places:
  `compare_digest(expected.encode(), presented.encode("utf-8", "surrogateescape"))` (bytes
  comparison never raises); add a non-ASCII-token test to each auth suite.

## F.5 — Relay HTTP surface lacks the request-body cap

**Severity:** Low · **Confidence:** High · **Was:** new · **Class:** hardening
**Paths:** `src/anyinfer-confidential/src/anyinfer_confidential/app.py:104`

**Brief:** `await request.json()` unbounded — the same allocation issue the v1 F.6 fix
closed on the sidecar, on the relay app that shipped in the same wave. Post-auth only, so
exposure requires a tenant token; still, one misbehaving tenant can exhaust the process
serving other tenants' prompt assembly.

**Remediation:**
- [x] **F.5.1** Wrap the app in the sidecar's `_with_body_limit` pattern (dependency-free
  ASGI) with a small default — relay slot-fill requests are tiny. Fix F.8's disconnect
  handling in the shared code first so the relay inherits the corrected behavior.

## F.6 — Telemetry-sink redaction edge gaps

**Severity:** Low · **Confidence:** High · **Was:** new · **Class:** hardening
**Paths:** `src/anyinfer/events/sinks.py:63,145,150`

**Brief:** `event_to_dict`'s value redaction is thorough, but mapping *keys* never pass
through `redact()`, `json.dumps(..., default=str)` stringifies any missed leaf without
redaction, and the JSONL file's 0600 applies only at creation (a pre-existing wider-mode
file is not re-chmodded, unlike the demo-config pattern).

**Remediation:**
- [x] **F.6.1** Redact keys (`{redact(str(k)): …}`); drop `default=str` (dead code given the
  catch-all) or make it redact; `os.chmod` after open. Three one-liners plus a test with a
  secret-shaped dict key.

## F.7 — Demo literal-secret stripping fails open for unknown providers

**Severity:** Low · **Confidence:** High (path), Medium (reachability) · **Was:** new ·
**Class:** hardening
**Paths:** `src/anyinfer_demo/config.py:66-67`

**Brief:** `_secret_field_keys()` returns an empty set when the provider id is absent from
the registry, so `_without_literal_secrets` strips nothing for that entry — a stale config
entry for a broken/uninstalled provider plugin can write its literal key to disk, the exact
thing the v1 F.3 fix promises never happens. Hard to reach via the GUI; 0600 bounds
exposure.

**Remediation:**
- [x] **F.7.1** Fail safe: when the registry cannot describe a provider, drop all
  non-reference `values` for that entry (or any key matching common secret spellings); add a
  test with an unregistered provider id.

## F.8 — Body-limit middleware replays a truncated body on disconnect

**Severity:** Low · **Confidence:** High · **Was:** new · **Class:** hardening
**Paths:** `src/anyinfer/serve/app.py:504-508` (`_with_body_limit` disconnect branch)

**Brief:** On `http.disconnect` mid-read, the wrapper replays accumulated chunks downstream
with `more_body: False`, presenting truncation as a complete request instead of forwarding
the disconnect. The cap still bounds memory and truncated JSON virtually always 400s, but a
truncation landing exactly on a JSON boundary would be processed as real (spend, telemetry)
with the response going nowhere.

**Remediation:**
- [x] **F.8.1** On disconnect, forward a receive channel yielding the disconnect message (or
  return without calling the app); add an ASGI-level mid-stream-disconnect test. Do before
  F.5 reuses this code.

## F.9 — `ci.yml` has no `permissions:` block

**Severity:** Low · **Confidence:** High · **Was:** new · **Class:** hardening
**Paths:** `.github/workflows/ci.yml`

**Brief:** Every other workflow now sets workflow-level `contents: read` with per-job
elevation (the v1 F.9 posture); ci.yml sets nothing, so its `GITHUB_TOKEN` gets the
repository default, which may be write.

**Remediation:**
- [x] **F.9.1** Add top-level `permissions: contents: read` — one line, matching the other
  five workflows.

## F.10 — `COHERE.key`: rotate and move to env/keyring

**Severity:** Low · **Confidence:** High · **Was:** F.13 (partial by owner decision) ·
**Class:** local hygiene
**Paths:** `COHERE.key` (repo root, untracked, mode 0600)

**Brief:** The v1 fix did what it could without the owner: the file is now 0600, the
`.gitignore` entry was broadened to `*.key`/`*.pem`/`.env*` patterns, and it remains never
committed and excluded from the sdist. The file itself stays **on the owner's explicit
instruction**; rotation cannot be verified from code and is not claimed here.

**Remediation (owner-action):**
- [ ] **F.10.1** Move the key into an environment variable or the keyring store; delete the
  file; rotate the key if the directory was ever copied, synced, or shared.

**Skipped 2026-08-25 (⏭️) by owner instruction:** owner action on live key material, not a
code change. `COHERE.key` was not read, moved, or modified in this pass.

---

# G. Attestation implementation plan (making Tier 3's guarantee real)

## G.0 Rationale and status

The rationale stands from v1: the confidentiality story is the stated differentiator, Tier 3
is its only tier claiming a cryptographic guarantee, and implementing quote verification
converts an advertised claim into a defensible one. **Progress this window:** the
honest-claims pass landed in full (v1 G.1 — DESIGN §30.4 rewritten, GPU CC parse fails
closed on an allowlist with fixture tests, advisory-local-only documented at all three
consumers), the ceiling phrasing ships ("CPU-attested; GPU CC detected but not
quote-verified" — v1 G.6.1), the Nitro Enclaves owner decision was resolved as **deferred
past 1.0** with scope and triggers recorded (v1 G.7), and the two cheap credibility
prerequisites (Relay auth, demo key persistence) are fixed and tested. What remains is
exactly the hardware- and demand-gated core, renumbered below (Was maps v1 phase IDs).
Sequencing is unchanged: G.1 (a decision) unblocks scheduling; G.2 (rented hardware)
unblocks G.3 (the code); G.4 is the payoff; G.5 stays deferred with recorded triggers.

## G.1 — Demand gate: identify a confidential-tier design partner

**Sev 3 · Pri 4 · Was:** G.2 — a decision, not code; the differentiation argument only pays
off with a real counterparty.

- [ ] **G.1.1** Identify at least one prospective design partner: a vendor shipping prompt
  IP onto customer-owned hardware who would adopt Tier 3. Record the outcome (who, or "none
  found by <date>") here.
- [ ] **G.1.2** Decide sequencing from the answer: partner exists → schedule G.2–G.4 before
  1.0; none by 1.0 planning → mark G.2–G.5 explicitly deferred past 1.0 in DESIGN §30.4
  (the honest posture that now ships stays defensible indefinitely).

## G.2 — CC hardware validation sprint

**Sev 4 · Pri 3 · Was:** G.3 — clears the gate DESIGN itself sets (never ship unverified
security-critical code), by renting rather than building.

- [ ] **G.2.1** Rent a SEV-SNP confidential VM (Azure DCa/ECa-series suffices for the CPU
  path; an `NCCadsH100v5` instance only if GPU work is being scoped). Budget: days.
- [ ] **G.2.2** Capture real artifacts with nonces included: SEV-SNP attestation reports via
  the configfs-TSM report interface, a TDX quote if a TDX host is also rented, and positive
  `nvidia-smi conf-compute -q` output on the GPU instance.
- [ ] **G.2.3** Commit sanitized captures as test fixtures (verify no tenant-identifying
  material first) and tighten the existing GPU-CC allowlist
  (`attestation.py:_GPU_CC_CAPABLE_VALUES`) to the observed values.

## G.3 — CPU attestation-quote verification (the bounded core)

**Sev 5 · Pri 3 · Was:** G.4 — SEV-SNP + TDX quote fetch and chain verification behind the
existing `attest` extra (`cryptography>=42` already declared; no new mandatory deps).

- [ ] **G.3.1** Report acquisition: SEV-SNP report via `/sys/kernel/config/tsm/report`
  (configfs-TSM) with a caller-supplied nonce; TDX quote via the same interface where
  exposed. Lives in `anyinfer/local/` (acquisition is not protocol translation).
- [ ] **G.3.2** Verification: signature chain to vendor roots (AMD ARK → ASK → VCEK;
  Intel PCS for TDX), nonce freshness, launch-measurement check; failures raise typed
  errors in the `ConfidentialExecutionError` family with actionable `hint`s.
- [ ] **G.3.3** Add `quote_verified` to `ConfidentialExecutionStatus`, provenance-tagged and
  distinct from `end_to_end`; `ConfidentialExecutionAdapter` gates any remote-facing
  assurance on it — this retires the advisory-local-only caveats shipped by the v1 G.1 pass.
- [ ] **G.3.4** Tests: fixture-driven verification against G.2 captures including
  tampered-report and stale-nonce negatives; a live positive-case test gated on real
  hardware, marked like the existing live-credential conformance mode.

## G.4 — Claims and docs update (after G.3)

**Sev 3 · Pri 3 · Was:** G.5 — the payoff step: the differentiator becomes citable.

- [ ] **G.4.1** Rewrite DESIGN §30.4 and `docs/guides/confidentiality-tiers.md` to state the
  verified guarantee precisely: which platforms are quote-verified, what the
  nonce/measurement check proves, and the GPU ceiling (per G.5's standing statement).
- [ ] **G.4.2** Document the `attest` verification workflow on
  `docs/reference/api/confidential.md` plus a short "verifying an attested host" guide
  section.
- [ ] **G.4.3** Surface `quote_verified` provenance wherever capability claims render, per
  the rule that nothing estimated is presented as authoritative.

## G.5 — GPU SPDM attestation (explicitly deferred)

**Sev 3 · Pri 1 · Was:** G.6 — H100 CC attestation via the OpenRM SPDM path (nvtrust) is
substantially harder than the CPU path and needs sustained GPU-CC hardware access. The
ceiling statement ("CPU-attested; GPU CC detected but not quote-verified") already ships in
the tiers guide and DESIGN — keep it in every surface G.4 touches.

- [ ] **G.5.1** Re-evaluate when a design partner needs GPU offload inside the attested
  boundary, or when Blackwell CC goes GA on a hyperscaler (the §30.4 market-facts re-check
  cadence already covers this). Until one trigger fires, this stays deferred by design.

---

# H. Dependency-contract drift

## H.0 Why this section exists

v2 had no home for a finding of this shape: not a documentation gap, not a missing
feature, not our own security bug, but a dependency changing what it accepts underneath a
surface this project documents and ships. It sits between B (docs vs reality) and D
(completeness) and belongs to neither, so it gets its own letter rather than being filed
somewhere it would be read out of context.

## H.1 — Documented `verify` + `client_cert` combination raises `TypeError`

**Severity:** Medium-High · **Confidence:** High (reproduced) · **Was:** new
**Paths:** `src/anyinfer/providers/http.py` (`build_client`, `tls_kwargs`),
`src/anyinfer/providers/cloud_auth.py:_exchange`,
`docs/reference/configuration.md` (Proxies, Private CAs, and mTLS)

**Brief:** httpx2 2.10 deprecates both `verify=<str>` (a CA-bundle path) and `cert=...` (a
client certificate) in favour of a single `ssl.SSLContext`, and **refuses the two together
with a `TypeError`**. `build_client` forwarded exactly that pair. The configuration
reference's own worked example sets `proxy`, `verify`, and `client_cert` on one instance —
the corporate-CA-behind-an-intercepting-proxy-with-mTLS case the feature exists for — and
that example raised `TypeError` at client construction.

**Long:** Found while burning down D.6, and it is the same story D.6 tells: config→settings
was pinned by tests, settings→httpx was not, so the one combination that fails was never
exercised. The individually-set cases only warned, which is why nothing surfaced earlier.
Reported at first as a deprecation to plan for; on the owner's instruction to look at it
properly (2026-08-25), the reproduction showed it was already broken.

**Remediation:**
- [x] **H.1.1** Done 2026-08-25: `tls_kwargs()` in `providers/http.py` resolves `verify`
  and `client_cert` into one `ssl.SSLContext` — `create_default_context(cafile=)` or
  `(capath=)` for a path, an explicit `CERT_NONE` context for `False`, and
  `httpx2.create_ssl_context(verify=True)` for the default so `truststore` and
  `SSL_CERT_FILE`/`SSL_CERT_DIR` behaviour is delegated rather than reimplemented; the
  certificate is then applied with `load_cert_chain`. Nothing is passed when nothing is
  configured, preserving httpx's own environment handling.
- [x] **H.1.2** Shared with `GoogleTokenSource._exchange`, so the token exchange resolves
  TLS identically to the data plane (the D.2 boundary this pass established).
- [x] **H.1.3** Unreadable CA bundles and certificates now raise `ConfigError` naming the
  setting, instead of a bare `FileNotFoundError` from `ssl`.
- [x] **H.1.4** Tests in `tests/test_config.py` and `tests/test_cloud_auth.py` cover the
  combination, each setting alone, the combined-PEM form, and a
  `simplefilter("error", DeprecationWarning)` guard that fails if the raw keywords come
  back. Certificates are generated per-test via `tests/support.py:self_signed_cert` rather
  than committed, so no fixture expires.

**Note:** the public surface is unchanged — `ProviderSettings.verify` and the config file
still take a path string and a certificate tuple, which is what an operator can write in
JSON. The conversion is confined to `tls_kwargs`.

## H.2 — Copilot `cli_path` raises `TypeError`; `aclose` leaks the CLI process

**Severity:** Medium-High · **Confidence:** High (both reproduced) · **Was:** new
**Paths:** `src/anyinfer/providers/copilot.py` (`_ensure_client`, `aclose`, `_map_error`),
`contracts/copilot.md`, `docs/providers/copilot.md`

**Brief:** Two independent breaks against `github-copilot-sdk` 1.0.9, found by sweeping for
H.1's shape.

1. **`cli_path` is a `TypeError`.** The adapter called
   `CopilotClient(cli_path=...)`. Today's constructor is keyword-only with **no
   `**kwargs`**, and has no such parameter — the SDK moved to
   `connection=StdioRuntimeConnection(path=...)`. `cli_path` is a declared `SetupField`
   (so it renders in the config UI) and is documented in `docs/providers/copilot.md`,
   `docs/reference/configuration.md`, and `contracts/copilot.md`. Anyone who set it, or
   who exported `COPILOT_CLI_PATH`, got a hintless `ProviderError` wrapping the
   `TypeError`. The contract snapshot already named `RuntimeConnection`; the code had not
   caught up.
2. **`aclose` shut nothing down.** It probed for `close` then `aclose`; the SDK spells it
   `stop`. Both probes missed, the `if close is not None` guard skipped the call, and
   nothing raised — so the spawned CLI subprocess was left running on every client close.
   Silent by construction: there is no failure to observe.

**Long:** The suite passed throughout because the fake `copilot` module accepted
`**options` on the constructor and defined `close()`. The fake was more permissive than
the thing it stood in for, which is precisely what let a renamed parameter and a renamed
method through. The same lesson as H.1 and D.6: the mocked seam is the one that rots.

**Remediation:**
- [x] **H.2.1** `cli_path` and `COPILOT_CLI_PATH` now build
  `connection=StdioRuntimeConnection(path=...)`. The user-facing spelling is unchanged.
- [x] **H.2.2** `aclose` tries `stop`, `close`, `aclose` in order, falling back to the
  SDK's `__aexit__` — the one contract that has survived these renames — and the probed
  names live in `CopilotAdapter._SHUTDOWN_METHODS`.
- [x] **H.2.3** A `TypeError` naming an unexpected keyword now maps to `ConfigError` with
  a hint saying an `options` key is not accepted by the installed SDK, instead of a bare
  repr. The whole `options` block is forwarded to that constructor, so this recurs by
  design whenever the SDK's parameter set moves.
- [x] **H.2.4** The fake now mirrors the SDK: it spells shutdown `stop` and counts calls.
  Two tests bind against the **real** installed SDK rather than the fake — one binds the
  constructor kwargs to `CopilotClient.__init__`'s signature, one asserts at least one
  name in `_SHUTDOWN_METHODS` still exists. Both were confirmed to fail against the
  pre-fix call shape.
- [x] **H.2.5** `contracts/copilot.md` gained a "Runtime location" section recording the
  connection mapping and why the flat keyword cannot work.

## H.3 — Dead `filterwarnings` exemption

**Severity:** Low · **Confidence:** High · **Was:** new
**Paths:** `pyproject.toml` (`[tool.pytest.ini_options] filterwarnings`)

**Brief:** The suite ran `filterwarnings = ["error", "ignore::DeprecationWarning:starlette.testclient"]`.
starlette 1.6 no longer emits the warning that exemption was added for, so it matched
nothing — while still standing ready to swallow the *next* deprecation from that module.
A module-scoped ignore does not expire on its own.

**Remediation:**
- [x] **H.3.1** Removed; `filterwarnings = ["error"]` with no exemptions. The comment now
  says to re-add only with a specific message and a reason, never a bare module.

**Sweep note (2026-08-25):** H.2 and H.3 came out of a deliberate sweep prompted by H.1 —
warnings collected across the whole suite with `-o filterwarnings=always` (zero fired),
coverage read for dependency-facing blind spots, and then the uncovered paths *executed*
directly rather than inferred: both MCP transports, the Google service-account RS256/JWT
signing path against `cryptography` 50, `jsonschema` validate/format/extract, `otel.install`,
the keyring backend, `azure-identity`'s `get_token` signature, and every vendor attribute
named anywhere in `src/` checked for existence. Only the copilot adapter was broken.
Warnings-as-errors proved nothing about any of it, because a warning only fires on code a
test actually runs — which is the whole reason the sweep was needed.


