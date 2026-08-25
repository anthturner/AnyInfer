# Debloat / Deslop Hitlist

**Date:** 2026-08-25 · **As of:** commit `7884a70` on `fix/codebase-status-p1`.

**Method:** five parallel audits over the full tree — dead/unused code (AST + full-corpus
reference analysis), duplication (≥3-line identical-run scanning across `src/` and
`tests/`), over-abstraction (Protocol/registry/plumbing census), test bloat (all 2,364
test functions), and prose/comment slop (sampled 10k+ `src/` lines plus `docs/`,
`contracts/`, `plans/`, `scripts/`). Overlapping findings are merged below; each item
keeps `file:line` anchors valid at the commit above — paths and symbol names are the
durable anchors.

**This is a hitlist, not a burn-down.** Nothing here has been changed. Cite items as
`DEBLOAT B.3` to scope future work; check off `- [ ]` when an item lands. Indices are
local to this document (they do not collide with `CODEBASE_STATUS.md`'s A–H).

---

## Verdict

The fear was "AI bloat"; the reality is more specific. At the **line level this codebase
is unusually clean** — across 77.6k `src/` LOC the audits found ~0.3 no-information
comment lines per 100, exactly 2 `logger.` calls (events are the observability channel),
zero TODO/FIXME, zero deprecated shims, zero dead CLI flags, zero `__all__` entries naming
missing symbols, and only 12 zero-assertion tests out of 2,364. Typical LLM slop
(narrating comments, log spam, defensive try/except) is essentially absent.

The bloat is **structural, and it is real**: roughly **8,000 LOC (~6–7% of the tracked
Python)** split across four shapes, plus ~60–100 KB of prose:

1. **Copy-paste across provider adapters and their tests** — the same HTTP error ladder,
   stream-state class, health/aclose, descriptor boilerplate, and rerank parser written
   10–35× (§B, §E). This is the largest and lowest-risk vein, and it is already drifting
   (two live bugs found — see §H).
2. **Speculative machinery with zero users** — a plugin/entry-point system with no
   plugins in existence, a Protocol with one implementor plumbed through 104 references,
   proxy/TLS settings no test or caller sets (§D).
3. **Parallel representations of the same facts** — `manifest.py`'s 16-facet hierarchy
   mirroring `events/telemetry.py`, a hand-written JSON Schema mirroring the dataclasses,
   dataclass↔JSON codecs written four different ways, stacked `__init__` re-export layers
   giving most symbols three import paths (§C, §D).
4. **Tests that add lines, not assurance** — one 1,042-line file of hand-copied doc
   snippets posing as drift detection, three retrieval test files that are the same file,
   481 lines of function-body imports in the demo suite (§E).

Also: ~35 MB of the on-disk footprint is gitignored build output/bytecode, not repo
content, and a **live Cohere credential sits at the repo root** (§G — do this one today).

| Section | Theme | Deletable/collapsible | Effort profile |
|---|---|---|---|
| A | Dead code — delete outright | ~900 LOC | mostly XS–S |
| B | Provider-layer duplication | ~1,700 LOC | S–M |
| C | Client-layer duplication | ~500 LOC | M |
| D | Speculative abstraction | ~1,900 LOC | S–M, two policy calls |
| E | Test suite | ~2,900 LOC | mostly S, mechanical |
| F | Prose artifacts | ~60–100 KB | S |
| G | Working-tree hygiene | ~35 MB on disk | XS |

**Effort:** XS = minutes · S = an hour or a few · M = a day or two · L = several days.
**Conf:** confidence the item is safe/real as stated.

---

## A — Dead code: delete outright (~900 LOC)

- [ ] **A.1 · `src/anyinfer-shared/` is an orphaned sub-package** — its only export
  (`ConfidentialityReport`, `src/anyinfer-shared/src/anyinfer_shared/__init__.py:51`) is
  imported by nothing: not core, not `anyinfer-confidential`, not `anyinfer-store` (checked
  all shard `pyproject.toml` dependency lists and a full-tree grep). The only object ever
  satisfying its `from_status()` protocol is a fake in its own test. Yet CI installs and
  tests it in four places (`.github/workflows/ci.yml:139,220,268,305`, `workspace.py:544`).
  Delete the shard + its CI steps, or fold the type into `anyinfer-confidential` if it is
  the planned seam for hosted-Relay work — decide, don't keep paying build time for zero
  consumers. **~325 LOC + CI time · Effort S · Conf high**
- [ ] **A.2 · `local/sources/direct_url.py` + `local_path.py` resolvers** — loaded via the
  importlib side-effect loop in `local/sources/__init__.py`, but every catalog entry in the
  shipped data uses `"huggingface"` (163×); `"url"`/`"local"` appear zero times. Referenced
  only by tests of themselves. Dead-in-practice; delete or gate behind the first catalog
  entry that needs them. **~259 LOC · Effort S · Conf med**
- [ ] **A.3 · 21 test-only public methods** — accessors with no production caller, written
  for tests that assert them. Largest: `ModelStore.adopt_external`
  (`local/store.py:631`, 77 LOC), `ModelStore.resolve_within` (`local/store.py:307`),
  `ContextTuning.ranking_is_default` (`context/settings.py:164`), plus a demo-side tail
  (`main_window.py:180-192`, `chat_view.py:475`, `conversation.py:183`). Full list in the
  audit; delete method + its test together. **~200 LOC · Effort S · Conf high**
- [ ] **A.4 · Zero-reference public functions** — `Catalog.from_files`
  (`catalog/model.py:595`, docstring claims a role `load_default_catalog` doesn't give it),
  `ScriptedProvider.with_model` (`testing/scripted.py:423`),
  `ServerSupervisor.set_runtime_backend` (`local/server.py:474`). Each greps to exactly one
  hit: its own `def`. **~42 LOC · Effort XS · Conf high**
- [ ] **A.5 · 41 `__all__`-exported constants never read outside their module** — e.g.
  `context/rank.py` `STOP_WORDS`/`TERM_SATURATION`/…, `schema/mechanism.py`
  `MECHANISM_LADDER`, `local/sources/huggingface.py` `PICKLE_PATTERNS`. Keep the constants,
  drop the `__all__` entries so they stop being API-frozen. **41 lines of API surface ·
  Effort XS · Conf high**
- [ ] **A.6 · Make module-internal "public" names private** — `ServiceDefinition` +
  `current_platform` (`serve/service.py:144,81`), `ObserverSpec`
  (`config/__init__.py:918`, documented API nobody constructs), `query_terms`
  (`context/rank.py:281`). Rename to `_`-private; shrinks the documented surface. **~70 LOC
  of surface · Effort XS · Conf med**

## B — Provider-layer duplication (~1,700 LOC)

The primitives mostly exist (`providers/http.py`, `presets.py:_TRANSLATORS`); what's
missing is composition. Items B.1–B.4 are one refactor wave over `src/anyinfer/providers/`.

- [ ] **B.1 · The buffered-POST error ladder, 35 sites** — try/POST → `map_transport_error`
  → `classify_status` → byte-cap check → JSON-parse, ~14 lines each, in every adapter
  (representative: `bedrock.py:665-704` ≡ `cohere.py:267-298`). Five sites open-code the
  size check instead of calling the existing `http.check_response_size`. Add
  `post_json(...)` to `providers/http.py`; each site becomes one `await`. **~420 LOC ·
  Effort M · Conf high**
- [ ] **B.2 · `HttpAdapterBase`: `__init__`/`health()`/`aclose()`** — `aclose` is verbatim
  in 9 adapters; `health` is the same 8 lines in 8 adapters modulo probe path;
  the `__init__` header-building block is 204 lines across 11 files with four AST-identical
  copies (`tei.py:56`, `voyage.py:62`, `cohere.py:101`, `jina.py:71`). **~270 LOC · Effort
  M · Conf high**
- [ ] **B.3 · `SetupField` descriptor boilerplate** — 35 near-identical
  api_key/base_url blocks (361 lines) across 19 modules. Add
  `registry.api_key_field(env_var=...)` / `base_url_field(default=...)` factories.
  **~300 LOC · Effort S · Conf high**
- [ ] **B.4 · `_StreamState` base class** — 219 lines across 7 adapters;
  `finalize()` AST-identical in four, `tool_slot()` identical in two. Hoist to
  `providers/base.py`, keep dialect-specific fields in subclasses. **~120 LOC · Effort S ·
  Conf high**
- [ ] **B.5 · Fold `jina.py`/`voyage.py` into the shared retrieval mixin** — 130 of ~200
  code lines identical; the entire behavioural delta is `top_n` vs `top_k`, `"results"` vs
  `"data"`, and the capability table. Same move absorbs the four drifting copies of
  `_parse_rerank_response` (`cohere.py:556`, `jina.py:133`, `voyage.py:123`, inline in
  `tei.py:178`). **~250 LOC · Effort M · Conf high**
- [ ] **B.6 · Reasoning translators: 14 copies of 5 shapes** — `presets.py:271
  _TRANSLATORS` is already the registry; `azure_foundry.py:109` and `copilot.py:455` are
  byte-identical, `openrouter.py:152` is AST-identical to `presets.py:253`. Point adapters
  at the registry. **~60 LOC · Effort S · Conf high**
- [ ] **B.7 · Six thin OpenAI-compat adapters vs `presets.py`** — `nebius`, `xai`,
  `openrouter`, `deepseek`, `azure_foundry`, `lm_studio` re-hand-write descriptors and
  helpers `presets.py` already generates from a `CompatPreset`. Promote the shared bits
  (`_parse_pricing`, feature detection) into `openai_compat.py` and convert each descriptor
  tail to a preset entry, keeping only genuine overrides. Fixes the §H.1 pricing drift as a
  side effect. **~250 LOC · Effort M · Conf med**
- [ ] **B.8 · Cross-module verbatim helpers** — `_kill_tree` + process-group flags
  AST-identical in `local/server.py:700` and `mcp/transport.py:297` (→ shared
  `_process.py`); `_billions` in `local/fit.py:278` vs `local/variants.py:526`;
  hardware-stat signature loop in `local/hardware.py:298` vs `local/attestation.py:383`.
  **~60 LOC · Effort S · Conf high**

## C — Client-layer duplication (~500 LOC)

- [ ] **C.1 · The route/attempt/fallback loop exists three times** —
  `operations.py:298-584` (`dispatch_embed`), `operations.py:585-836` (`dispatch_rerank`,
  47% line-identical to embed), and `generation.py:331-536` (`_route_events`). The retry
  driver `_attempt_with_retry` (`operations.py:96`) is already generic over the wire type —
  apply the same trick one level up with a `_dispatch_operation(call=, merge=, validate=)`.
  The two retry loops are **already inconsistent** (generation guards `if delay > 0` before
  sleeping; operations doesn't). **~300 LOC · Effort M · Conf med-high**
- [ ] **C.2 · One dataclass↔JSON helper instead of four** — the same problem is solved
  independently by `manifest.py:600-665` (`_encode`/`_decode` + hand-maintained `_NESTED`
  table), `events/sinks.py:44-70` (`_json_safe`), `_context_wire.py` (bespoke codec with
  hand-synced key sets), and `config/__init__.py`'s 12 `_parse_*`/`_*_json` pairs. Pick the
  reflection-based one, delete the rest. Overlaps D.2/D.6 — do together. **~250 LOC here,
  more via D · Effort M · Conf med**
- [ ] **C.3 · Sync facade drift guard** — `sync_client.py` is correctly logic-free (every
  method forwards to the async client), but 508 of 918 lines restate 22-param signatures
  with **no parity test and no codegen**: a kwarg added to `AsyncClient.embed` silently
  never exists on `Client.embed`. Cheapest fix is not deletion — add one
  `test_sync_facade_signatures_match` walking `inspect.signature` over the public methods.
  **~15 LOC added, drift class closed · Effort XS · Conf high**
- [ ] **C.4 · Unwind the `_client` mixin split's coupling manifests** —
  `GenerationExecutionMixin` opens with 55 lines of `if TYPE_CHECKING:` re-declaring 9
  attributes + 7 methods the host class supplies (`generation.py:234-291`; same pattern
  `spend.py:55-68`). The mixins have exactly one user and "not usable alone" docstrings.
  `operations.py` in the same package already uses the simpler style: module functions
  taking the client. Converge on that. **~80 LOC · Effort M · Conf med**

## D — Speculative abstraction (~1,900 LOC)

- [ ] **D.1 · Plugin/entry-point machinery for an ecosystem of size zero** — three entry-
  point groups (`plugins.py` entire file, `registry.py:101-131,713-799`,
  `config/__init__.py:935-991` which does entry-point *discovery inside config validation*),
  guarded by `_reserved_scheme_claimed_by` security machinery against hostile plugins.
  Total published plugins across the repo and all shards: **zero** (the only entry point
  anywhere is `pytest11`). The built-ins are a static list, a 2-entry dict, and a 3-tuple.
  Delete the loaders; restore them the day a third-party provider actually ships.
  **~330 LOC · Effort S–M · Conf high**
- [ ] **D.2 · `manifest.py` parallel hierarchy** — 16 `*Facet` dataclasses + a 438-line
  builder re-projecting facts the 20 `events/telemetry.py` dataclasses already carry (its
  own docstring: "terminal projection, never a second source of truth"), plus
  `manifest_json_schema()` (`manifest.py:1257+`) — a **hand-written JSON Schema literal
  duplicating the dataclass definitions**, guaranteed to drift — plus the hand-maintained
  `_NESTED` decoder table (`:614-641`). Biggest single item in the codebase. Minimum move:
  generate the schema from the dataclasses and delete `_NESTED` via C.2; maximum move:
  render manifests from the event list. **~400–700 LOC · Effort M–L · Conf med-high**
  *(policy call: the manifest is a shipped, documented artifact — decide how much of its
  independence is deliberate before cutting)*
- [ ] **D.3 · `TokenEstimator` Protocol: one implementor, 104 references of plumbing** —
  threaded as a kwarg/attribute through 8 modules (`capabilities/estimate.py:86` protocol,
  `HeuristicTokenEstimator` the sole implementor; `cache.py` threads it through 6 private
  helpers). Keep the seam only at the two public client constructors; call the function
  directly elsewhere. **~120 LOC · Effort S · Conf high**
- [ ] **D.4 · Four `local/` Protocols shadowing catalog types field-for-field** — `Tier`,
  `TierSource`, `SelectableVariant` (8 mirrored fields), `SizedEntry` — each with one
  implementor, existing to dodge a layering rule that **no import-linter contract
  enforces** (`pyproject.toml:229-307` has four contracts; none covers local↔catalog).
  Either enforce the rule or use `TYPE_CHECKING` imports. **~110 LOC · Effort S · Conf
  med-high**
- [ ] **D.5 · `context/select.py` plan/outlook comparison layer** — `ReductionPlan` /
  `StrategyOutlook` / `plan()` have exactly one real caller (`cli.py:2998`); 5 strategy
  names dispatch to 3 implementations; `ContextTuning` carries 17 knobs of which 5
  (`salience_damping`, `salience_iterations`, `feedback_documents`, `shingle_size`,
  `rollup_share`) have zero non-default use and zero test coverage. Collapse the dead knobs
  to constants; let the CLI loop over `select()`. **~250 LOC · Effort M · Conf med**
- [ ] **D.6 · `config/__init__.py`: 1,273 lines for a 12-field dataclass** — 12 bespoke
  parse/dump codec pairs plus 24 copies of the `isinstance-or-raise` shape guard (53 sites
  repo-wide share the shape — also `catalog/model.py` ×15). Add `_as_object/_as_array/
  _as_str` narrowing helpers; replace codec pairs via C.2. The `observers` block alone is
  126 LOC to name two built-in classes. **~300 LOC · Effort M · Conf med**
- [ ] **D.7 · One JSON-store helper instead of five** — the format_version + `.tmp` +
  `os.replace` + swallow-errors-on-read pattern is hand-rolled in
  `capabilities/ledger.py:267`, `benchmark.py:240` (whose neighbor *cites* the other's
  contract and reimplements it), `local/store.py:360`, `local/hardware.py:642`,
  `local/runtimes.py:331`. **~150 LOC · Effort S · Conf med-high**
- [ ] **D.8 · Proxy/TLS settings: plumbed through 11 adapters, set by nobody** —
  `ProviderSettings.proxy/verify/client_cert` (commit `ed337b8`) have zero call sites in
  tests, demo, or shards; `verify` in particular is untested and `httpx` treats
  `False`/`None` differently. **Policy call, not a delete-by-default:** this was a
  deliberate E-item feature. Either add the missing tests (making it real) or revert until
  a user exists. Also: `honors_connection_settings` (`registry.py:404`) duplicates what the
  adapter signature already proves. **~80 LOC or +tests · Effort S · Conf med**
- [ ] **D.9 · Descriptor/Protocol double-bookkeeping** — `SupportsDiagnostics` protocol
  (`providers/base.py:454`) vs `reports_diagnostics` descriptor flag (`registry.py:517`):
  two live mechanisms for one fact that can disagree (`generation.py:178` checks the flag,
  `operations.py` isinstance-checks the protocol). Pick the descriptor. Related: ~10
  `ProviderDescriptor` booleans are true for exactly one provider — fine to keep the
  pattern, but stop adding a field per quirk. **~60 LOC + policy · Effort S · Conf med**
- [ ] **D.10 · Small indirection tail** — `check_context_fit` 8-param wrapper over two
  calls with one real caller (`capabilities/gating.py:71`, inline into
  `generation.py:740`); `_ConfigurePhaseError`/`_RetryableProviderError` 23-line forwarding
  `__init__`s that flip one default (`errors.py:119,165` → class attribute);
  `errors.unknown_name(kind, name, known)` helper to absorb 11 hand-built "unknown X /
  known Xs:" raises. **~115 LOC · Effort S · Conf med**
- [ ] **D.11 · Flatten the re-export stack** — `types/__init__.py` (179 lines, zero
  definitions, 71 of 81 names also in the root `__all__`) and `capabilities/__init__.py`
  (68 lines, 20 of 32 duplicated) give most public symbols three import spellings; nothing
  in tests or docs uses the `anyinfer.types.*` spelling for 6 of its names. Breaking-change
  caveat: deprecate in docs first, delete at the next minor. **~250 LOC · Effort S · Conf
  med**

## E — Test suite (~2,900 LOC, mostly mechanical)

The suite is healthier than feared — no fake-echo epidemic (~6 tautological tests total),
no snapshot-blob problem, `test_library_coverage.py` is real coverage (don't touch it),
`fakes.py` has no dead features. The bloat is concentrated:

- [ ] **E.1 · `test_docs_examples.py` is a drift machine, not drift detection** — 50 tests
  name a docs page in a docstring, then re-implement the snippet **by hand**; several
  "matches the docs" tests hardcode the doc's contents without opening the file
  (`test_provider_listing_matches_the_docs`, `test_documented_aliases_resolve`,
  `test_every_trap_row_has_a_test` compares only counts). A docs edit cannot fail this
  file; it manufactures false confidence. Exactly one test genuinely reads a doc
  (`:564-580`). Replace with a ~60-LOC fenced-block extractor over `docs/**/*.md` — real
  coverage for less money. **~900 LOC, small real coverage swap · Effort M · Conf high**
- [ ] **E.2 · Retrieval test triplication** — `test_voyage.py`/`test_jina.py`/`test_tei.py`
  are the same file (61 changed lines out of 595 between voyage and jina, normalized).
  One parametrized `test_retrieval_adapters.py` over `(adapter_cls, wire-key table)`.
  Do together with B.5. **~450 LOC · Effort S · Conf high**
- [ ] **E.3 · Demo suite: hoist 481 lines of function-body imports** — nearly every test in
  `tests/demo_app/` re-imports its subject inside the body (143 imports in
  `test_demo_app.py` alone). Pure mechanics, 12% of the demo suite. **481 LOC · Effort S ·
  Conf high**
- [ ] **E.4 · ~25 parametrize clusters** — 2,364 test functions, only 76 `parametrize`
  marks. Mapped clusters with line ranges in the audit (worst: `test_rate_limits.py:161-256`
  6 near-identical functions; `test_cli_run.py`, `test_serve_embeddings.py`,
  `test_bedrock_vertex.py`, …). **~450 LOC · Effort S · Conf high**
- [ ] **E.5 · Byte-cap clones ×13 replaced free conformance coverage** — 13 hand-copied
  `test_*_rejects_a_response_over_the_byte_cap` tests, while the conformance suite's own
  `embedding_byte_cap`/`rerank_byte_cap` cases are explicitly **switched off** in those
  harnesses (`test_voyage.py:286` etc. set `byte_cap=False`). Delete the clones, re-enable
  the flag — coverage improves. **~180 LOC · Effort S · Conf high**
- [ ] **E.6 · Shared helpers into `tests/support.py` / conftest** — 320 hand-written
  `try/finally: aclose()` blocks (the clients already support `async with`); 30 private
  `_client`/`_adapter`/`_capture`/`_registry` helper copies across 30 files; 20 byte-
  identical conformance-runner wrappers (→ one parametrized test, or an
  `assert_conformance` helper in `anyinfer.testing`, which third-party adapter authors are
  currently copy-pasting too); tests re-implementing `eventstream_frame` the SDK already
  exports (`test_bedrock_vertex.py:67`). **~850 LOC · Effort M · Conf high**
- [ ] **E.7 · Delete the anti-tests** — brand-constant change-detectors that regex the
  source against a copy of itself (`test_branding.py:33-45`, `test_demo_app.py:1802-1809`);
  Qt-plumbing tests asserting a setter set (`test_demo_app.py:2049-2131` minus the one real
  splitter-invariant test); trivial frozen-dataclass tests already covered by the
  parametrized invariant test in the same file (`test_types.py:62-71`,
  `test_embeddings_reranking.py:1182-1194`). **~330 LOC · Effort XS–S · Conf high**
- [ ] **E.8 · `fakes.py` internal hoists** — `_vector()` ×5 (one already drifted to a
  hardcoded `range(8)`), `next_response()` ×5, `_consume()` ×2, near-identical `__init__`
  ×5 → hoist onto `_FakeServerBase`. **~150 LOC · Effort S · Conf high**

## F — Prose artifacts (~60–100 KB)

- [ ] **F.1 · Generate the mechanical half of `contracts/openai-compat-presets.md`** —
  163 KB / 2,462 lines, the largest file in the repo; 86 presets × a 6-label skeleton where
  five of six facts are already declarative data in `providers/presets.py`. Keep the
  hand-researched compatibility notes; generate the rest (the
  `scripts/generate_provider_index.py` pattern already exists). **~40–60 KB · Effort M ·
  Conf high**
- [ ] **F.2 · Trim `plans/CODEBASE_STATUS.md` history** — 72 KB; the burn-down narrative,
  v1→v2 `Was` mapping, and the header self-correction are git history, not living state.
  Keep open items + method. **~15–25 KB · Effort S · Conf med**
- [ ] **F.3 · Cut DESIGN.md's four completed-plan sections** — §19 (shipped roadmap), §20
  (5 of 6 decisions struck through as resolved), §24 (superseded hand matrix; the generated
  one lives in `docs/reference/conformance-matrix.md`), §25 (docs plan that shipped).
  **~190 lines · Effort XS · Conf high**
- [ ] **F.4 · Merge or cross-link the two adapter-writing procedures** —
  `contracts/NEW-PROVIDER.md` steps 2/3/5 duplicate the middle four sections of
  `docs/contributing/writing-an-adapter.md`. One should own the procedure; the other
  points at it (repo policy already says contracts/ is canonical). **~150 lines · Effort S
  · Conf med**
- [ ] **F.5 · Decide `plans/RATE_LIMIT_AWARENESS.md`** — 27 KB, self-declared "not
  started", referenced by nothing. Queue it or archive it. **0–27 KB · Effort XS**
- [ ] **F.6 · Delete ~50 section-banner comments** — `# ---- selection ----…` navigation
  chrome, concentrated in `anyinfer_demo/` (~35) and `cli.py` (11). The only unambiguous
  comment slop in the codebase. **~50 lines · Effort XS · Conf high**

## G — Working-tree hygiene (not repo bloat; on disk only)

- [ ] **G.1 · Move `COHERE.key` out of the repo root — today.** A live 40-byte credential,
  saved from history only by the `*.key` gitignore pattern; one `git add --force` or a
  pattern edit away from a leak. Move to the OS keychain or `~/.config/anyinfer/`, rotate
  if in doubt. **Effort XS · Conf high**
- [ ] **G.2 · Purge gitignored dross** — `site/` 19 MB, `tests/__pycache__` 16 MB (73% of
  the "21 MB of tests"), 28 more `__pycache__` dirs, `.coverage`. `git clean -ndX` first to
  preview, then `-fdX`. None of it is tracked; this fixes the *perception* of bloat that
  motivated this audit. **~35 MB · Effort XS · Conf high**

## H — Found while looking (bugs, not bloat — fix regardless)

1. **OpenRouter pricing parser accepts JSON booleans** — `openrouter.py:103-128
   _parse_pricing` is the same 24 lines as `nebius.py:130-155` minus the
   `isinstance(raw, bool)` guard and `ValueError` catch: a JSON `true` in a price field
   becomes `Decimal(1)` on OpenRouter only. Direct consequence of B.7's copy-paste.
2. **Retry-loop inconsistency** — generation sleeps only `if delay > 0`; the
   embed/rerank loop sleeps unconditionally (`operations.py:96` vs `generation.py`
   `_route_events`). See C.1.
3. **Sync facade has no drift guard** — see C.3; one XS test closes the class.
4. **`fakes.py:1240 _vector`** hardcodes `range(8)` where its four siblings honor
   `self._dimensions` — a fake that lies about dimensions under non-default config.
5. **`test_presets.py` exhaustive matrix** (86 presets × ~26 cases) is ~half of full-suite
   wall time re-proving one shared dialect — already marked `exhaustive`/honest, but worth
   remembering when CI minutes hurt.

---

## Suggested order

1. **Now (XS, no review risk):** G.1 credential, G.2 clean, F.3, F.5, F.6, A.4, A.5, C.3's
   parity test, H.4's one-line fake fix.
2. **One sitting each:** E.3 (import hoist), E.5 (byte-cap swap), E.7 (anti-tests), B.3
   (SetupField factories), B.6 (translators), A.3, A.6, D.10.
3. **The provider wave (B.1→B.2→B.4→B.5→B.7 with E.2 alongside):** biggest LOC payoff,
   one subsystem, conformance suite catches regressions; fixes H.1 en route.
4. **The representation wave (C.2 + D.2 + D.6 + D.7):** one dataclass↔JSON story, then the
   manifest decision.
5. **Policy calls to make deliberately, not by default:** A.1 (delete vs fold the shard),
   D.2's ceiling, D.8 (test it or revert it), D.11 (public-surface break).

*Guardrail for all of it: `workspace check` (mypy --strict, import-linter, conformance,
docstring coverage, docs build) is the safety net that makes this tractable — run it per
batch, land batches separately, and keep the 100%-docstring gate in mind: deleted public
symbols also delete their docstring obligations, which is the direction we want.*
