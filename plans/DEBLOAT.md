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

**Calibration note (2026-08-25):** review of D.1 exposed a systematic bias in the original
audit: it measured *usage* (zero callers) without checking *intent* (documented extension
point, advertised package, designed-for-downstream seam). Every item that proposes
**deleting capability or public surface** — A.1, A.2, D.1, D.3, D.5, D.8, D.11 — has been
re-checked against `docs/` and reframed below; none is a default-delete. Items that
**consolidate implementation without changing behavior** (all of B, C, E, F, G, H, and the
rest of A) are immune to this failure mode: collapsing 35 copies of an error ladder removes
no feature. Weight your trust accordingly.

**Risk key (added 2026-08-25):** every item now carries a risk rating for prioritizing
low-risk pruning.
🟢 **low** — mechanical or additive; the existing gates (`workspace check`: 2,800+ tests,
`mypy --strict`, import-linter, conformance, strict docs build) reliably catch a botched
attempt, and nothing user-visible can change.
🟡 **medium** — behavior-adjacent: a correct execution changes nothing, but the failure
mode is *silent* (wire format, persisted file, probe semantics, teardown ordering) or the
blast radius is wide; needs a named guard before starting.
🔴 **high / decision** — changes public surface, documented behavior, or a shipped
artifact; wrongness is not detectable by the gates because the gates encode the current
choice. These are owner calls, not pruning.
The risk stated is the risk of *doing the item*; skipping any item is always safe, except
G.1.

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

| Section | Theme | Deletable/collapsible | Risk profile |
|---|---|---|---|
| A | Dead code — delete outright | ~900 LOC | mixed: A.3–A.6 🟢, A.1/A.2 🔴/🟡 |
| B | Provider-layer duplication | ~1,700 LOC | mostly 🟡 (wide, well-gated) |
| C | Client-layer duplication | ~500 LOC | 🟡–🔴 (core request path) |
| D | Speculative abstraction | ~800–1,900 LOC | mixed: half 🟢, half 🔴 decisions |
| E | Test suite | ~2,900 LOC | mostly 🟢 (coverage-preserving) |
| F | Prose artifacts | ~60–100 KB | 🟢 with owner review |
| G | Working-tree hygiene | ~35 MB on disk | 🟢 (G.2 corrected — see item) |

**Effort:** XS = minutes · S = an hour or a few · M = a day or two · L = several days.
**Conf:** confidence the item is safe/real as stated.

---

## A — Dead code: delete outright (~900 LOC)

- [ ] **A.1 · `src/anyinfer-shared/`: advertised package, zero known consumers — a
  product decision, not a code cleanup** — its only export (`ConfidentialityReport`,
  `src/anyinfer-shared/src/anyinfer_shared/__init__.py:51`) is imported by nothing in the
  repo, and the only object ever satisfying its `from_status()` protocol is a fake in its
  own test. But it is *documented as a shipping PyPI package* whose stated purpose is
  downstream composition (`docs/guides/installation.md:42`,
  `docs/reference/api/confidential.md:5`) — zero internal importers is consistent with
  its design, not evidence against it. The real cost is four CI install/test steps
  (`.github/workflows/ci.yml:139,220,268,305`, `workspace.py:544`) for a package with no
  known users. Options: keep shipping it (close this item), fold the type into
  `anyinfer-confidential`, or retire it — an owner call tied to the hosted-Relay roadmap
  (see the confidentiality-tiers plan), not a debloat default.
  **0 or ~325 LOC + CI time · Effort S · Conf high on facts, policy on outcome**
  **Risk:** 🔴 to remove (retracts an advertised package; if anything external already
  depends on it, breakage is invisible to our gates) · 🟢 to keep. If retiring: docs and
  package must go in the same PR, and the PyPI name should be yanked/deprecated, not
  abandoned.
- [ ] **A.2 · `local/sources/direct_url.py` + `local_path.py` resolvers — verify intent
  before touching** — loaded via the importlib side-effect loop in
  `local/sources/__init__.py`, but every catalog entry in the shipped data uses
  `"huggingface"` (163×); `"url"`/`"local"` appear zero times, and no docs page mentions
  them. Referenced only by tests of themselves. **Open question that decides the item:**
  can a user-authored catalog entry name `resolver: "url"`? If yes, this is an
  undocumented feature (document it or remove it deliberately); if no, it is dead code.
  **0 or ~259 LOC · Effort S · Conf med on facts, intent unverified**
  **Risk:** 🟡 until the open question is answered (an hour of reading
  `local/sources/__init__.py:196` and the catalog-loading path), then 🟢 to delete or
  🔴 if it turns out to be a reachable feature. The verification itself is free.
- [ ] **A.3 · 21 test-only public methods** — accessors with no production caller, written
  for tests that assert them. Largest: `ModelStore.adopt_external`
  (`local/store.py:631`, 77 LOC), `ModelStore.resolve_within` (`local/store.py:307`),
  `ContextTuning.ranking_is_default` (`context/settings.py:164`), plus a demo-side tail
  (`main_window.py:180-192`, `chat_view.py:475`, `conversation.py:183`). Full list in the
  audit; delete method + its test together. **~200 LOC · Effort S · Conf high**
  **Risk:** 🟢 with one mandatory step — grep `docs/` for each name before deleting
  (verified absent for `adopt_external`/`resolve_within`; the other 19 were not
  individually docs-checked). Technically these are public API on an 18-day-old package;
  external-user risk is near zero but nonzero. Delete method and test in the same commit
  so coverage numbers don't lie in between.
- [ ] **A.4 · Zero-reference public functions** — `Catalog.from_files`
  (`catalog/model.py:595`, docstring claims a role `load_default_catalog` doesn't give it),
  `ScriptedProvider.with_model` (`testing/scripted.py:423`),
  `ServerSupervisor.set_runtime_backend` (`local/server.py:474`). Each greps to exactly one
  hit: its own `def`. **~42 LOC · Effort XS · Conf high**
  **Risk:** 🟢. One caveat: `with_model` lives in `anyinfer.testing`, which is documented
  API for third-party adapter authors — it's not in the module's `__all__` or any doc
  page, so exposure is theoretical, but check the docs grep like A.3.
- [ ] **A.5 · 41 `__all__`-exported constants never read outside their module** — e.g.
  `context/rank.py` `STOP_WORDS`/`TERM_SATURATION`/…, `schema/mechanism.py`
  `MECHANISM_LADDER`, `local/sources/huggingface.py` `PICKLE_PATTERNS`. Keep the constants,
  drop the `__all__` entries so they stop being API-frozen. **41 lines of API surface ·
  Effort XS · Conf high**
  **Risk:** 🟢. The constants stay; only star-import users of submodules (an anti-pattern
  nobody documented) could notice. mypy and the docs build will confirm nothing referenced
  them.
- [ ] **A.6 · Make module-internal "public" names private** — `ServiceDefinition` +
  `current_platform` (`serve/service.py:144,81`), `ObserverSpec`
  (`config/__init__.py:918`, documented API nobody constructs), `query_terms`
  (`context/rank.py:281`). Rename to `_`-private; shrinks the documented surface.
  **~70 LOC of surface · Effort XS · Conf med**
  **Risk:** 🟡, only because `ObserverSpec` has a mkdocstrings entry
  (`docs/reference/api/configuration.md:37`) — privatizing it is a (tiny) documented-API
  retraction and the strict docs build will fail until the directive is removed in the
  same commit. The other two are 🟢.

## B — Provider-layer duplication (~1,700 LOC)

The primitives mostly exist (`providers/http.py`, `presets.py:_TRANSLATORS`); what's
missing is composition. Items B.1–B.4 are one refactor wave over `src/anyinfer/providers/`.
**Shared risk shape for the whole section:** wide blast radius (every adapter) but strong
gates (per-adapter tests + conformance suite + `mypy --strict`); the danger is not a loud
break but a *quiet semantic change* to one adapter's error mapping or wire format. The
standing mitigation for every B item: port one adapter per commit, run its test file plus
the conformance suite, and diff recorded wire bodies where tests capture them.

- [ ] **B.1 · The buffered-POST error ladder, 35 sites** — try/POST → `map_transport_error`
  → `classify_status` → byte-cap check → JSON-parse, ~14 lines each, in every adapter
  (representative: `bedrock.py:665-704` ≡ `cohere.py:267-298`). Five sites open-code the
  size check instead of calling the existing `http.check_response_size`. Add
  `post_json(...)` to `providers/http.py`; each site becomes one `await`. **~420 LOC ·
  Effort M · Conf high**
  **Risk:** 🟡. The 35 sites are *near*-identical, not identical — a few pass different
  `read_error_detail` arguments or phase labels, and flattening a real difference into the
  helper silently changes one provider's error classification. Mitigation: build the
  helper's parameter surface from a diff of all 35 sites *first*; any site that doesn't
  fit the signature stays open-coded rather than being forced. Buffered paths only —
  don't let the helper creep toward streaming.
- [ ] **B.2 · `HttpAdapterBase`: `__init__`/`health()`/`aclose()`** — `aclose` is verbatim
  in 9 adapters; `health` is the same 8 lines in 8 adapters modulo probe path;
  the `__init__` header-building block is 204 lines across 11 files with four AST-identical
  copies (`tei.py:56`, `voyage.py:62`, `cohere.py:101`, `jina.py:71`). **~270 LOC · Effort
  M · Conf high**
  **Risk:** `aclose` hoist 🟢 (verbatim ×9). `health` 🟡 — probe paths and pagination
  params are per-provider facts, and a wrong default turns "reachability probe" into a 404
  that marks a healthy provider unhealthy; keep path/param as required arguments with no
  defaults. `__init__` 🟡 — header-merge order (`headers.update` after auth) is
  security-relevant (auth header override behavior); preserve order exactly and add one
  test asserting a user-supplied `authorization` header wins/loses the same way it does
  today.
- [ ] **B.3 · `SetupField` descriptor boilerplate** — 35 near-identical
  api_key/base_url blocks (361 lines) across 19 modules. Add
  `registry.api_key_field(env_var=...)` / `base_url_field(default=...)` factories.
  **~300 LOC · Effort S · Conf high**
  **Risk:** 🟢. Pure data construction; descriptors are asserted by tests and rendered by
  the demo's settings UI. Keep every string byte-identical (help text, placeholder) —
  any wording "improvement" during the move turns a refactor into a UI change.
- [ ] **B.4 · `_StreamState` base class** — 219 lines across 7 adapters;
  `finalize()` AST-identical in four, `tool_slot()` identical in two. Hoist to
  `providers/base.py`, keep dialect-specific fields in subclasses. **~120 LOC · Effort S ·
  Conf high**
  **Risk:** 🟡 despite being mechanical, because streaming reassembly is where adapter
  bugs are silent (a dropped `finish_reason` or misordered tool slot produces plausible
  output). Hoist *only* the AST-identical methods, change nothing else in the same
  commit, and lean on the conformance `event_ordering` case as the tripwire.
- [ ] **B.5 · Fold `jina.py`/`voyage.py` into the shared retrieval mixin** — 130 of ~200
  code lines identical; the entire behavioural delta is `top_n` vs `top_k`, `"results"` vs
  `"data"`, and the capability table. Same move absorbs the four drifting copies of
  `_parse_rerank_response` (`cohere.py:556`, `jina.py:133`, `voyage.py:123`, inline in
  `tei.py:178`). **~250 LOC · Effort M · Conf high**
  **Risk:** 🟡. The wire-key table IS the adapter — transposing `top_n`/`top_k` sends a
  silently ignored parameter to the wrong provider. The existing tests assert
  `seen["top_n"]`-style captures, which is exactly the right tripwire; make sure both
  providers' capture tests survive the merge un-weakened (E.2 merges the *tests* — do
  B.5 and E.2 as one change so the parametrized tests are written against the new shape).
- [ ] **B.6 · Reasoning translators: 14 copies of 5 shapes** — `presets.py:271
  _TRANSLATORS` is already the registry; `azure_foundry.py:109` and `copilot.py:455` are
  byte-identical, `openrouter.py:152` is AST-identical to `presets.py:253`. Point adapters
  at the registry. **~60 LOC · Effort S · Conf high**
  **Risk:** 🟢 for the byte/AST-identical consolidations; 🟡 only if any adapter gets
  *re-keyed* to a different translator shape during the move — the failure (an effort
  string a provider rejects, or silently drops) surfaces at request time, not in unit
  tests, unless `tests/test_reasoning_effort.py` covers that adapter. Consolidate
  spellings, change zero mappings.
- [ ] **B.7 · Six thin OpenAI-compat adapters vs `presets.py`** — `nebius`, `xai`,
  `openrouter`, `deepseek`, `azure_foundry`, `lm_studio` re-hand-write descriptors and
  helpers `presets.py` already generates from a `CompatPreset`. Promote the shared bits
  (`_parse_pricing`, feature detection) into `openai_compat.py` and convert each descriptor
  tail to a preset entry, keeping only genuine overrides. Fixes the §H.1 pricing drift as a
  side effect. **~250 LOC · Effort M · Conf med**
  **Risk:** 🟡, the highest in section B. Descriptor conversion can silently change
  config surface (setup fields, capability flags, alias resolution) for six providers at
  once, and "genuine override vs. copy-paste" requires a judgment call per adapter.
  Mitigation: snapshot each adapter's rendered `ProviderDescriptor` to a fixture *before*
  starting and assert byte-equality after — that converts the whole item to 🟢-verifiable.
  Do the `_parse_pricing` promotion first and separately (that half is 🟢 and fixes H.1).
- [ ] **B.8 · Cross-module verbatim helpers** — `_kill_tree` + process-group flags
  AST-identical in `local/server.py:700` and `mcp/transport.py:297` (→ shared
  `_process.py`); `_billions` in `local/fit.py:278` vs `local/variants.py:526`;
  hardware-stat signature loop in `local/hardware.py:298` vs `local/attestation.py:383`.
  **~60 LOC · Effort S · Conf high**
  **Risk:** `_billions`/stat-loop 🟢. `_kill_tree` 🟡 — it's platform-sensitive process
  control and Windows CI was fixed *this week* (`7884a70`); the copies are AST-identical
  today so the merge is safe, but land it separately and watch the Windows shard, since a
  process-group regression there presents as hung CI, not a red test.

## C — Client-layer duplication (~500 LOC)

- [ ] **C.1 · The route/attempt/fallback loop exists three times** —
  `operations.py:298-584` (`dispatch_embed`), `operations.py:585-836` (`dispatch_rerank`,
  47% line-identical to embed), and `generation.py:331-536` (`_route_events`). The retry
  driver `_attempt_with_retry` (`operations.py:96`) is already generic over the wire type —
  apply the same trick one level up with a `_dispatch_operation(call=, merge=, validate=)`.
  The two retry loops are **already inconsistent** (generation guards `if delay > 0` before
  sleeping; operations doesn't). **~300 LOC · Effort M · Conf med-high**
  **Risk:** 🟡 for merging embed+rerank (they're symmetric, heavily tested, and the event
  sequence they emit is asserted by tests) · 🔴 for folding generation's loop in too —
  that loop carries health-marking, content-policy redirect, and streaming semantics, and
  unifying it *forces* resolving the sleep-when-zero inconsistency, which is a
  user-observable timing change either way. Recommendation: do embed+rerank now; extract
  only the small `_retry_step` for generation; leave the rest of generation's loop alone
  until there's a reason.
- [ ] **C.2 · One dataclass↔JSON helper instead of four** — the same problem is solved
  independently by `manifest.py:600-665` (`_encode`/`_decode` + hand-maintained `_NESTED`
  table), `events/sinks.py:44-70` (`_json_safe`), `_context_wire.py` (bespoke codec with
  hand-synced key sets), and `config/__init__.py`'s 12 `_parse_*`/`_*_json` pairs. Pick the
  reflection-based one, delete the rest. Overlaps D.2/D.6 — do together. **~250 LOC here,
  more via D · Effort M · Conf med**
  **Risk:** 🔴 as originally stated, 🟡 with a guard — these codecs produce *persisted and
  consumed formats*: manifest JSON is a documented artifact (`docs/examples/golden-manifest.md`),
  config files round-trip through the `_*_json` pairs, and `_context_wire` is a wire
  format. A unified codec that differs by one key ordering or None-handling detail
  corrupts silently. Mandatory guard: golden-file fixtures for all four formats
  (one exists: `tests/manifests/plugin_fixture.json`) asserting byte-stable output
  *before* the consolidation starts. With goldens in place, 🟡.
- [ ] **C.3 · Sync facade drift guard** — `sync_client.py` is correctly logic-free (every
  method forwards to the async client), but 508 of 918 lines restate 22-param signatures
  with **no parity test and no codegen**: a kwarg added to `AsyncClient.embed` silently
  never exists on `Client.embed`. Cheapest fix is not deletion — add one
  `test_sync_facade_signatures_match` walking `inspect.signature` over the public methods.
  **~15 LOC added, drift class closed · Effort XS · Conf high**
  **Risk:** 🟢 — purely additive; the only possible failure is the new test being too
  strict (e.g. flagging intentional sync/async doc differences), which fails loudly in CI,
  not silently.
- [ ] **C.4 · Unwind the `_client` mixin split's coupling manifests** —
  `GenerationExecutionMixin` opens with 55 lines of `if TYPE_CHECKING:` re-declaring 9
  attributes + 7 methods the host class supplies (`generation.py:234-291`; same pattern
  `spend.py:55-68`). The mixins have exactly one user and "not usable alone" docstrings.
  `operations.py` in the same package already uses the simpler style: module functions
  taking the client. Converge on that. **~80 LOC · Effort M · Conf med**
  **Risk:** 🟡 for churn, 🟢 for semantics — it's an internal reorg fully covered by
  `mypy --strict` and the client test suite; nothing observable changes. The real cost is
  a large-diff review and conflicts with any in-flight `_client` work (note C.1 touches
  the same files — sequence them, don't parallelize). Deliberately reverses part of the
  A.1.1–A.1.4 split from the status tracker; note the decision there when done.

## D — Speculative abstraction (~800 LOC firm; up to ~1,900 with owner calls)

- [ ] **D.1 · Plugin/entry-point machinery: documented, tested, zero adopters — decide,
  don't default-delete** — three entry-point groups (`plugins.py` entire file,
  `registry.py:101-131,713-799`, `config/__init__.py:935-991` which does entry-point
  *discovery inside config validation*). The built-ins do **not** use it: providers load
  via static `builtin_descriptors()` (`registry.py:715-719`), observers via the
  `BUILTIN_OBSERVERS` tuple, credential schemes via the hardcoded resolver chain — the
  entry-point lane is exclusively for third parties, and total published plugins across
  the repo and all shards is **zero** (the only entry point anywhere is `pytest11`).
  However: it is *advertised public API* (`docs/contributing/writing-an-adapter.md:141`,
  `docs/providers/README.md:139`, `docs/concepts/credentials.md:142`,
  `docs/reference/configuration.md:191,527`, `docs/guides/demo-app.md:54`, DESIGN §
  several), and `plugins.py`'s rationale is sound — the sidecar has no constructor, so
  config-nameable extension needs entry points. Options: (a) keep it as a deliberate
  ecosystem bet and close this item; (b) retract it everywhere at once — loaders *and* the
  ~5 doc pages. Removing code while docs still promise it is the one wrong answer.
  **0 or ~330 LOC + docs · Effort S–M · Conf high on facts, policy on outcome**
  **Risk:** 🔴 to retract (public-contract retraction; any unannounced third-party
  adapter in the wild breaks invisibly) · 🟢 to keep and close. Owner's stated lean:
  keep.
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
  **Risk:** split by scope. Minimum move 🟡 — schema generation must be proven equivalent
  to the hand schema (diff generated vs. hand-written as a one-time test; where they
  disagree, that's drift *found*, and each disagreement needs a human to say which side is
  right). Maximum move 🔴 — the manifest's shape is documented
  (`docs/examples/golden-manifest.md`) and downstream consumers may parse it; restructuring
  its provenance is a product change wearing a refactor's clothes.
- [ ] **D.3 · `TokenEstimator`: keep the protocol, prune only the internal threading** —
  the protocol is a *documented extension point* (`docs/concepts/budgeting.md:73` shows
  plugging in tiktoken; "one implementor" is by design — the second is the user's), so
  the constructor seam and the protocol itself stay. What's cuttable is the internal
  plumbing: `capabilities/cache.py` threads the estimator through 6 private helpers and
  it rides as a kwarg on several internal call chains that could read it from the client
  once. **~40–60 LOC, not the 120 originally claimed · Effort S · Conf med**
  **Risk:** 🟢 — internal-only after the reframe; `mypy --strict` plus the budgeting
  tests cover it. The one thing to preserve: a custom estimator supplied at the
  constructor must still reach every internal use (that's the documented promise) — one
  test injecting a counting-fake estimator and asserting it was consulted closes the
  question.
- [ ] **D.4 · Four `local/` Protocols shadowing catalog types field-for-field** — `Tier`,
  `TierSource`, `SelectableVariant` (8 mirrored fields), `SizedEntry` — each with one
  implementor, existing to dodge a layering rule that **no import-linter contract
  enforces** (`pyproject.toml:229-307` has four contracts; none covers local↔catalog).
  Either enforce the rule or use `TYPE_CHECKING` imports. **~110 LOC · Effort S · Conf
  med-high**
  **Risk:** 🟢 at runtime (no behavior change either way). The only real risk is
  architectural: the protocols encode a stated design intent (local must not import
  catalog) that the contracts never enforced. Deleting them *and* adding the import-linter
  contract is contradictory — pick one: enforce the layering (keep protocols, add
  contract) or abandon it (delete protocols, use TYPE_CHECKING imports). Either is 🟢;
  doing neither deliberately is how the current state happened.
- [ ] **D.5 · `context/select.py` plan/outlook comparison layer** — `ReductionPlan` /
  `StrategyOutlook` / `plan()` have exactly one real caller (`cli.py:2998`); 5 strategy
  names dispatch to 3 implementations; `ContextTuning` carries 17 knobs of which 5
  (`salience_damping`, `salience_iterations`, `feedback_documents`, `shingle_size`,
  `rollup_share`) have zero non-default use and zero test coverage — but at least
  `rollup_share` is in the documented API table (`docs/reference/api/context.md:52`), so
  knob removal is a documented-surface change: test the knobs or retract them, per knob,
  deliberately. The `plan()`/`ReductionPlan` layer (one real caller) is the safe half of
  this item. **~150–250 LOC · Effort M · Conf med, knobs are a surface decision**
  **Risk:** knobs 🔴 (documented API retraction, per knob). `plan()` layer 🟡, not 🟢:
  its one caller is a *user-facing CLI command* — removing the layer means reimplementing
  that command's output via `select()` calls, and the CLI's stdout is de-facto interface
  (scripts may parse it). Golden-capture the command's output for a fixed input first;
  byte-equal after = safe.
- [ ] **D.6 · `config/__init__.py`: 1,273 lines for a 12-field dataclass** — 12 bespoke
  parse/dump codec pairs plus 24 copies of the `isinstance-or-raise` shape guard (53 sites
  repo-wide share the shape — also `catalog/model.py` ×15). Add `_as_object/_as_array/
  _as_str` narrowing helpers; replace codec pairs via C.2. The `observers` block alone is
  126 LOC to name two built-in classes. **~300 LOC · Effort M · Conf med**
  **Risk:** narrowing helpers 🟢 (same checks, same messages, one spelling). Codec
  replacement 🟡 bordering 🔴 — config error messages are user-facing UX that
  `tests/test_config.py` (853 lines) asserts against, and a reflection-based codec will
  not naturally reproduce hand-tuned messages like "providers[2].options must be an
  object". Constraint for whoever does it: the 853 lines of config tests must pass
  *unmodified* — if the refactor needs to edit expected error strings, that's the signal
  it changed UX, not just implementation.
- [ ] **D.7 · One JSON-store helper instead of five** — the format_version + `.tmp` +
  `os.replace` + swallow-errors-on-read pattern is hand-rolled in
  `capabilities/ledger.py:267`, `benchmark.py:240` (whose neighbor *cites* the other's
  contract and reimplements it), `local/store.py:360`, `local/hardware.py:642`,
  `local/runtimes.py:331`. **~150 LOC · Effort S · Conf med-high**
  **Risk:** 🟡 — these five files persist user state, and one of them is the **spend
  ledger** (budget governance: a read-path change that silently returns "empty" instead
  of "corrupt" resets someone's spend tracking). The pattern is genuinely identical, but
  each store's *recovery* semantics (what happens on version mismatch / partial write)
  must be table-tested per store before unifying. On-disk format must not change at all —
  this is a code move, not a format migration.
- [ ] **D.8 · Proxy/TLS settings: plumbed through 11 adapters, set by nobody** —
  `ProviderSettings.proxy/verify/client_cert` (commit `ed337b8`) have zero call sites in
  tests, demo, or shards; `verify` in particular is untested and `httpx` treats
  `False`/`None` differently. **Policy call, not a delete-by-default:** this was a
  deliberate E-item feature. Either add the missing tests (making it real) or revert until
  a user exists. Also: `honors_connection_settings` (`registry.py:404`) duplicates what the
  adapter signature already proves. **~80 LOC or +tests · Effort S · Conf med**
  **Risk:** add-tests path 🟢 (purely additive, and the `verify` False-vs-None ambiguity
  is exactly what the tests would pin down — this path *reduces* existing risk). Revert
  path 🔴 (removes a shipped, config-file-reachable feature; any user who set `proxy` in
  a config since `ed337b8` breaks on upgrade). Recommendation: test it, don't revert it.
- [ ] **D.9 · Descriptor/Protocol double-bookkeeping** — `SupportsDiagnostics` protocol
  (`providers/base.py:454`) vs `reports_diagnostics` descriptor flag (`registry.py:517`):
  two live mechanisms for one fact that can disagree (`generation.py:178` checks the flag,
  `operations.py` isinstance-checks the protocol). Pick the descriptor. Related: ~10
  `ProviderDescriptor` booleans are true for exactly one provider — fine to keep the
  pattern, but stop adding a field per quirk. **~60 LOC + policy · Conf med**
  **Risk:** 🟡 — converging on the descriptor changes behavior for any adapter where the
  two mechanisms *currently disagree*. Step one is a five-minute audit: for all 21
  adapters, assert flag == isinstance result. If they all agree (likely), the
  consolidation is 🟢; any disagreement found is a live bug to fix first (add it to §H).
- [ ] **D.10 · Small indirection tail** — `check_context_fit` 8-param wrapper over two
  calls with one real caller (`capabilities/gating.py:71`, inline into
  `generation.py:740`); `_ConfigurePhaseError`/`_RetryableProviderError` 23-line forwarding
  `__init__`s that flip one default (`errors.py:119,165` → class attribute);
  `errors.unknown_name(kind, name, known)` helper to absorb 11 hand-built "unknown X /
  known Xs:" raises. **~115 LOC · Effort S · Conf med**
  **Risk:** 🟢 with two named cautions: the error classes are public API users `except`
  on — leaf class names and inheritance must not change, only the private intermediates'
  internals; and `check_context_fit` is re-exported at `__init__.py:59,438` — check
  whether it's in docs before inlining (if documented, keep the name as a one-line
  delegate).
- [ ] **D.11 · Flatten the re-export stack — docs actively use both spellings** —
  `types/__init__.py` (179 lines, zero definitions, 71 of 81 names also in the root
  `__all__`) and `capabilities/__init__.py` (68 lines, 20 of 32 duplicated) give most
  public symbols three import spellings. Correction to the original claim: docs *do*
  teach the deep spelling (`from anyinfer.types.capabilities import …` in
  `docs/guides/comparing-targets.md:18` and `docs/guides/testing-your-app.md:131`), so
  this is a real API break with published users of both paths. If done at all: pick one
  spelling, update docs, deprecate for a minor version first. Cheapest genuine win is
  narrower — stop *adding* names to three surfaces. **0–250 LOC · Effort S–M · Conf med,
  surface decision**
  **Risk:** 🔴 to flatten now (import breaks for anyone following the current docs) ·
  🟢 to adopt the stop-adding policy and revisit at the next minor version.

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
  **Risk:** 🟡, and honestly assessed, harder than the original estimate implied: doc
  snippets call real providers with real keys, so a fenced-block extractor needs a
  substitution layer (fake targets injected per snippet) to *execute* them — that's more
  than 60 LOC, or the extractor only import/syntax-checks snippets (weaker but still
  better than hand copies). Sequencing removes most risk: build the extractor, let both
  run side by side for one PR, then delete the hand copies. Never delete first.
- [ ] **E.2 · Retrieval test triplication** — `test_voyage.py`/`test_jina.py`/`test_tei.py`
  are the same file (61 changed lines out of 595 between voyage and jina, normalized).
  One parametrized `test_retrieval_adapters.py` over `(adapter_cls, wire-key table)`.
  Do together with B.5. **~450 LOC · Effort S · Conf high**
  **Risk:** 🟢 — coverage-preserving by construction (every case becomes a parametrize
  row). One caution: the ~61 genuinely different lines are the per-provider substance;
  diff the merged file against all three originals to prove no case was averaged away.
- [ ] **E.3 · Demo suite: hoist 481 lines of function-body imports** — nearly every test in
  `tests/demo_app/` re-imports its subject inside the body (143 imports in
  `test_demo_app.py` alone). Pure mechanics, 12% of the demo suite. **481 LOC · Effort S ·
  Conf high**
  **Risk:** 🟢, verified: the suspicion that inline imports guard headless collection is
  already handled — `test_demo_app.py:17` has module-level
  `pytest.importorskip("PySide6")`, so hoisted `anyinfer_demo.*` imports are safe **as
  long as they sit below the importorskip line** (they execute PySide6 imports at module
  load). That ordering constraint is the entire risk; a CI run without the demo extra
  confirms it.
- [ ] **E.4 · ~25 parametrize clusters** — 2,364 test functions, only 76 `parametrize`
  marks. Mapped clusters with line ranges in the audit (worst: `test_rate_limits.py:161-256`
  6 near-identical functions; `test_cli_run.py`, `test_serve_embeddings.py`,
  `test_bedrock_vertex.py`, …). **~450 LOC · Effort S · Conf high**
  **Risk:** 🟢. Two minor notes: test IDs change (anything referencing old node IDs —
  flake quarantines, `-k` habits — needs updating), and "near-identical" clusters need
  the same diff-check as E.2 so a real variation isn't parametrized into oblivion.
- [ ] **E.5 · Byte-cap clones ×13 replaced free conformance coverage** — 13 hand-copied
  `test_*_rejects_a_response_over_the_byte_cap` tests, while the conformance suite's own
  `embedding_byte_cap`/`rerank_byte_cap` cases are explicitly **switched off** in those
  harnesses (`test_voyage.py:286` etc. set `byte_cap=False`). Delete the clones, re-enable
  the flag — coverage improves. **~180 LOC · Effort S · Conf high**
  **Risk:** 🟡 for one specific reason: `byte_cap=False` was set *deliberately* in each
  harness, and nobody has recorded why. Possibly the fakes can't produce oversized bodies
  under those harnesses — in which case flipping the flag fails loudly (fine) — but if
  the conformance case passes *vacuously* for some harness, deleting the hand test loses
  real coverage silently. Per harness: flip the flag, watch the case actually *fail* when
  the cap is honored-check is inverted (mutation-check it once), then delete the clone.
- [ ] **E.6 · Shared helpers into `tests/support.py` / conftest** — 320 hand-written
  `try/finally: aclose()` blocks (the clients already support `async with`); 30 private
  `_client`/`_adapter`/`_capture`/`_registry` helper copies across 30 files; 20 byte-
  identical conformance-runner wrappers (→ one parametrized test, or an
  `assert_conformance` helper in `anyinfer.testing`, which third-party adapter authors are
  currently copy-pasting too); tests re-implementing `eventstream_frame` the SDK already
  exports (`test_bedrock_vertex.py:67`). **~850 LOC · Effort M · Conf high**
  **Risk:** 🟢 for the mechanical hoists (async-with is semantically identical to
  try/finally-aclose). Two carve-outs: adding `assert_conformance` to `anyinfer.testing`
  is a *public API addition* (name it once, correctly — it's forever); and the 30 helper
  copies are only *near*-identical — a helper that quietly passes different default
  settings than the file-local one it replaces changes what those tests test. Diff each
  replacement against the local original.
- [ ] **E.7 · Delete the anti-tests** — brand-constant change-detectors that regex the
  source against a copy of itself (`test_branding.py:33-45`, `test_demo_app.py:1802-1809`);
  Qt-plumbing tests asserting a setter set (`test_demo_app.py:2049-2131` minus the one real
  splitter-invariant test); trivial frozen-dataclass tests already covered by the
  parametrized invariant test in the same file (`test_types.py:62-71`,
  `test_embeddings_reranking.py:1182-1194`). **~330 LOC · Effort XS–S · Conf high**
  **Risk:** 🟢 with one judgment call flagged honestly: the brand-constant tests *do*
  provide intentional-change friction (a teammate can't drift the palette without a red
  test). That's their entire value; deleting trades a change-detector's annoyance for its
  friction. The audit's position — they can't catch a *bug* — stands; keep them only if
  palette-lock is a policy someone actually wants. The other deletions are strictly
  redundant coverage, verified.
- [ ] **E.8 · `fakes.py` internal hoists** — `_vector()` ×5 (one already drifted to a
  hardcoded `range(8)`), `next_response()` ×5, `_consume()` ×2, near-identical `__init__`
  ×5 → hoist onto `_FakeServerBase`. **~150 LOC · Effort S · Conf high**
  **Risk:** 🟡, not 🟢, for one reason: `anyinfer.testing` is documented public API for
  third-party adapter authors, and the drifted `_vector` (`fakes.py:1240`, hardcoded
  `range(8)`) means fixing the drift *changes fake behavior* under non-default
  dimensions — any downstream test relying on the buggy 8-dim output breaks. That's the
  right outcome (see H.4), but it's a behavior fix shipped inside a refactor; land H.4
  first as its own commit, then the hoists are 🟢.

## F — Prose artifacts (~60–100 KB)

- [ ] **F.1 · Generate the mechanical half of `contracts/openai-compat-presets.md`** —
  163 KB / 2,462 lines, the largest file in the repo; 86 presets × a 6-label skeleton where
  five of six facts are already declarative data in `providers/presets.py`. Keep the
  hand-researched compatibility notes; generate the rest (the
  `scripts/generate_provider_index.py` pattern already exists). **~40–60 KB · Effort M ·
  Conf high**
  **Risk:** 🟡 — two non-obvious constraints. The file is an input to the drift-check
  process (`scripts/validate_contracts.py` enforces `REQUIRED_HEADINGS`; the
  `/check-provider-drift` skill reads these snapshots), so the generated output must keep
  the validator and the drift workflow working. And generation must be one-way-safe: the
  hand-researched notes live in the same file, so a naive regenerate-and-overwrite
  destroys research. Split the file (generated section + hand notes, or per-preset
  include) before automating.
- [ ] **F.2 · Trim `plans/CODEBASE_STATUS.md` history** — 72 KB; the burn-down narrative,
  v1→v2 `Was` mapping, and the header self-correction are git history, not living state.
  Keep open items + method. **~15–25 KB · Effort S · Conf med**
  **Risk:** 🟢 mechanically (git history preserves everything), but it's the owner's
  working tracker with its own stated conventions ("closed items are REMOVED per owner
  instruction" — the narrative sections may be deliberate keep-decisions). Propose the cut
  as a diff, don't just apply it.
- [ ] **F.3 · Cut DESIGN.md's four completed-plan sections** — §19 (shipped roadmap), §20
  (5 of 6 decisions struck through as resolved), §24 (superseded hand matrix; the generated
  one lives in `docs/reference/conformance-matrix.md`), §25 (docs plan that shipped).
  **~190 lines · Effort XS · Conf high**
  **Risk:** 🟢 for §19/§20/§25. §24 gets a flag: its own text says it "remains the
  design-intent matrix" — i.e., someone already decided to keep it as intent-vs-reality
  documentation. Cutting it overrides that recorded decision; check DESIGN §18's
  decision-log conventions (the repo records reversals there) and log the removal the
  same way.
- [ ] **F.4 · Merge or cross-link the two adapter-writing procedures** —
  `contracts/NEW-PROVIDER.md` steps 2/3/5 duplicate the middle four sections of
  `docs/contributing/writing-an-adapter.md`. One should own the procedure; the other
  points at it (repo policy already says contracts/ is canonical). **~150 lines · Effort S
  · Conf med**
  **Risk:** 🟢 with a path constraint: `CLAUDE.md`, three skills, and `.github/prompts/`
  all hard-reference `contracts/NEW-PROVIDER.md` — that file must keep its path and its
  procedure-owner role; the docs page becomes the pointer, not the other way around. The
  strict docs build catches broken links.
- [ ] **F.5 · Decide `plans/RATE_LIMIT_AWARENESS.md`** — 27 KB, self-declared "not
  started", referenced by nothing. Queue it or archive it. **0–27 KB · Effort XS**
  **Risk:** 🟢 — it's a decision about a file nothing references; git history keeps it
  either way.
- [ ] **F.6 · Delete ~50 section-banner comments** — `# ---- selection ----…` navigation
  chrome, concentrated in `anyinfer_demo/` (~35) and `cli.py` (11). The only unambiguous
  comment slop in the codebase. **~50 lines · Effort XS · Conf high**
  **Risk:** 🟢 — comments only; no gate even notices.

## G — Working-tree hygiene (not repo bloat; on disk only)

- [ ] **G.1 · Move `COHERE.key` out of the repo root — today.** A live 40-byte credential,
  saved from history only by the `*.key` gitignore pattern; one `git add --force` or a
  pattern edit away from a leak. Move to the OS keychain or `~/.config/anyinfer/`, rotate
  if in doubt. **Effort XS · Conf high**
  **Risk:** 🟢 to do; the risk lives entirely in *not* doing it. Only step that needs
  care: whatever currently reads it (an env var? a local config?) must be repointed in
  the same sitting so local dev doesn't silently fall back to no-credential behavior.
- [ ] **G.2 · Purge gitignored dross — with a targeted command, not `git clean -fdX`** —
  `site/` 19 MB, `tests/__pycache__` 16 MB (73% of the "21 MB of tests"), 28 more
  `__pycache__` dirs, `.coverage`. **Correction (2026-08-25):** this item originally
  suggested `git clean -fdX`, which is **dangerous here** — `-X` removes *all* ignored
  files, which includes `COHERE.key` (fine only after G.1), any `.env`, virtualenvs, and
  IDE state. Use targeted deletion instead:
  `rm -rf site/ .coverage && find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} +`
  **~35 MB · Effort XS · Conf high**
  **Risk:** 🟢 with the targeted command (everything named is regenerable) · 🔴 with
  blanket `-fdX` (credential and environment loss). This correction is itself an instance
  of the review this document exists for.

## H — Found while looking (bugs, not bloat — fix regardless)

1. **OpenRouter pricing parser accepts JSON booleans** — `openrouter.py:103-128
   _parse_pricing` is the same 24 lines as `nebius.py:130-155` minus the
   `isinstance(raw, bool)` guard and `ValueError` catch: a JSON `true` in a price field
   becomes `Decimal(1)` on OpenRouter only. Direct consequence of B.7's copy-paste.
   *Fix risk 🟢: copy nebius's guard; one test.*
2. **Retry-loop inconsistency** — generation sleeps only `if delay > 0`; the
   embed/rerank loop sleeps unconditionally (`operations.py:96` vs `generation.py`
   `_route_events`). See C.1. *Fix risk 🟡: either direction is a user-observable timing
   change; pick one deliberately and note it.*
3. **Sync facade has no drift guard** — see C.3; one XS test closes the class. *Fix risk
   🟢.*
4. **`fakes.py:1240 _vector`** hardcodes `range(8)` where its four siblings honor
   `self._dimensions` — a fake that lies about dimensions under non-default config. *Fix
   risk 🟢 internally, 🟡 for downstream users of the documented testing API whose tests
   relied on the wrong dimension — a behavior fix, so its own commit (see E.8).*
5. **`test_presets.py` exhaustive matrix** (86 presets × ~26 cases) is ~half of full-suite
   wall time re-proving one shared dialect — already marked `exhaustive`/honest, but worth
   remembering when CI minutes hurt. *No action proposed.*

---

## Suggested order — now organized as risk lanes

**🟢 Green lane (do in any order, no guards needed):**
G.1 (credential — today), G.2 (targeted purge), C.3 (parity test), H.1 + H.3 (bug fixes),
F.5, F.6, A.4, A.5, E.2, E.3, E.4, E.6 (mechanical hoists), E.7, A.3 (with the docs-grep
step), B.3, B.6 (spelling-only), D.3, D.4 (either direction), D.10, F.4, D.8's add-tests
path. **Roughly 2,500–3,000 LOC of pruning with no realistic way to lose.**

**🟡 Yellow lane (each needs its named guard first — guards are listed in the items):**
E.5 (verify why byte_cap was off), E.8 after H.4, E.1 (extractor before deletion), B.1
(param-surface diff), B.2 (probe args explicit, header-order test), B.4 (AST-identical
only), B.5+E.2 together, B.7 (descriptor snapshot fixtures), B.8's `_kill_tree` (watch
Windows), C.1's embed+rerank half, C.4 (sequence after C.1), D.2's minimum move (schema
diff), D.5's plan layer (CLI golden), D.6 (config tests unmodified), D.7 (recovery-semantics
table, ledger care), D.9 (agreement audit first), F.1 (split file before generating), C.2
(goldens for all four formats first), A.2 (answer the reachability question), F.2/F.3
(owner sign-off on the cuts).

**🔴 Red lane (owner decisions; not pruning, and skipping them costs nothing):**
A.1 (ship/fold/retire the shard), D.1 (keep or retract the plugin contract — stated lean:
keep), D.2's maximum move, D.5's documented knobs, D.8's revert path (recommend against),
D.11 (import-path break — adopt stop-adding instead).

*Guardrail for all of it: `workspace check` (mypy --strict, import-linter, conformance,
docstring coverage, docs build) is the safety net that makes this tractable — run it per
batch, land batches separately, and keep the 100%-docstring gate in mind: deleted public
symbols also delete their docstring obligations, which is the direction we want. The green
lane's ~2,500–3,000 LOC is the answer to "low-risk pruning": all of it is
behavior-preserving, none of it touches documented surface, and every item in it fails
loudly rather than silently if botched.*
