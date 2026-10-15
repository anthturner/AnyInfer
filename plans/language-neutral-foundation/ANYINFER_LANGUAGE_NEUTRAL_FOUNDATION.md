# AnyInfer language-neutral foundation

**Resume from the first unchecked box in §5. Read §1 to §4 of this file and the
[shared specification](../../specification/core-generation.md) and
[maintenance contract](../../specification/MAINTENANCE.md) before touching any box. Each box ends in a
test gate; a box is done when its gate passes, not when its edits exist.**

**Status:** execution authorized 2026-10-15. The user requested resetting to upstream
`develop`, restoring these plans, integrating outstanding relevant PRs/issues, relocating
Python and all affected tooling/docs, and implementing/testing the shared foundation and C#
proof. This authorizes M0–M2 within the settled profile, including the bounded M2.1 proof
plan; it does not authorize expanding product scope or publishing language packages.
The [execution log](EXECUTION_LOG.md) records the baseline, work ownership and gate evidence.
The prior [review](evidence/REWRITTEN_PLAN_REVIEW.md) remains supporting planning evidence.
Future boxes are checked only after their gates pass; runtime feasibility and publishing
decisions retain their named gates.
**Python evidence baseline:** `13b9e65acfb01038464069ca5fa80f50a9df035c` on `develop`.
Recheck `git rev-parse HEAD` and `anyinfer.__file__` before executing any box.

Deviations are recorded in place with a `> NOTE:` line under the affected box, giving the
reason and the new resume point. Historical rationale, audits, and superseded contract
drafts live under [evidence/](evidence/README.md); they inform milestone 3 and later but
are not alternate plans.

## 1. Goal and the reason for native ports

AnyInfer gives a Python application one contract over many inference providers: routing,
retry, repair, validation, redaction, timing, and accounting live in the core, and adapters
only translate. The goal of this plan is to offer the same contract, with the same observed
behaviour, as a native library in other mainstream languages. C# is first.

A native port is preferred over a client for the existing sidecar because the sidecar still
needs a Python runtime somewhere, and because a library-level integration can expose
insights to the host application (attempt trails, repair activity, timing, future operation
accounting) that an HTTP boundary flattens. The sidecar remains a supported integration
path; it is not the strategy for first-class language support.

| State | Outcome | Boundary |
|---|---|---|
| **Current: Python** | The Python implementation supplies the observed behaviour that seeds the reference corpus. | Python behaviour is preserved. A discovered mismatch between Python and the specification is classified before any code changes. |
| **Next: Python + C#** | Both implementations pass the same `core-generation` corpus through their own drivers. | Bounded profile equivalence. Not a claim that C# has every Python product feature. |
| **Future: more languages** | Each port repeats milestone 4 against the same frozen corpus revision. | Java and TypeScript on Node.js are examples, not commitments. |

## 2. Settled decisions

| ID | Decision | Reason |
|---|---|---|
| A1 | Specification plus data-only conformance corpus plus independent native implementations, each with its own driver. Python initializes the reference; once a corpus revision is frozen, newer Python behaviour does not silently redefine it. | The proven pattern (JSON Schema Test Suite, Protobuf conformance, OpenTelemetry). No shared native binary, code generator, or policy interpreter. |
| A2 | One repository with a common source root: `src/python/**` and `src/csharp/**`. The three shard packages (`anyinfer-store`, `anyinfer-shared`, `anyinfer-confidential`) move under `src/python/` with the core; they are future parity targets with their own C# siblings, outside v0. The specification and corpus live at `specification/`. Python tests stay at `tests/`; C# tests live under `src/csharp/`. | Pricing refresh, catalog pinning, contract drift, and conformance tooling already live here and both implementations consume them. One language per root keeps the eventual `src/csharp/AnyInfer.Store` beside `src/python/anyinfer-store`. Splitting repositories can happen when a package ships. |
| A3 | Milestone 1 is the `core-generation` profile only: generation, structured output with repair, routing. Aggregate operation accounting is milestone 3 with its own plan; existing usage, ledger, and manifest behavior remain unchanged. | Aggregate accounting is a new feature Python does not have; coupling the first port to it doubles the surface. The archived accounting contracts are the input to milestone 3. |
| A4 | Two forward-compatibility hooks make milestone 3 easier to add: the fixture format reserves an optional `expected.accounting` section (must be `null` in v0), and the C# core routes every adapter entry through one invocation boundary (box M2.3). | The boundary is a useful future hook. Milestone 3 owns the decisions about lifecycle, usage provenance, no-entry operations, terminal outcomes, and any additional seams. |
| A5 | A malformed value of an admitted schema keyword (for example `required: 17`) is handled on Python's existing late path and yields exactly one issue with rule `invalid_schema` at the defective input-schema location, including index segments when present. Message wording is free per implementation. Fixtures contain at most one defect per schema. | Single-defect fixtures avoid requiring a cross-library choice among multiple defects. The old I1 exact-defect domain is superseded; the larger O1 capture design remains an A6 fallback. |
| A6 | Repair feedback is compared as ordered portable issues (rule, instance path, schema path, parameters) and implementation-local native feedback. Python preserves its current selected native strings byte-for-byte and captures the actual assessment made for each production helper invocation; it never recomputes validation to infer selection. A private immutable `NativeAssessment` pairs the selected portable `Issue` projection with the selected native rendered messages and native error metadata. Projection outside v0 may be unavailable and never narrows the Python API. | Portable issue identity permits cross-language comparison while the lossless native assessment preserves Python's current feedback, including broader schemas. The small call-local seam is preferred to restoring the full archived capture; revisit that capture only if the bounded proof or isolation gates fail. |
| A7 | W1 is closed. A root `$schema` other than absent or exactly `https://json-schema.org/draft/2020-12/schema` (including `null`) is outside the admitted domain. | The exclusion closes the portable question; it does not erase honestly recorded native warning observations. |
| A8 | Dialect pinned to the Draft 2020-12 keyword subset in the specification draft §4. C# implements that subset directly over `System.Text.Json`'s `Utf8JsonReader` (not `JsonNode`, which rejects duplicate keys); string ordering uses code-point comparison, not `CompareOrdinal`. No third-party validator. | The selected hand-written validator gives direct control of issue identity and ordering. |
| A9 | v0 observations use ordinary JSON only: integers remain exact and finite decimal values retain binary64 lexical distinction including signed zero. `$special` and `$codepoints` are literal object keys everywhere. Nonfinite values, lone surrogates, and an injective future tagged encoding are deferred together. Parsed structured results use JSON Schema equality; other observations use type-aware comparison. Placeholder objects are allowed only at explicitly schema-typed expected-message segment positions, never inside arbitrary schema or result JSON. | Ordinary JSON prevents collisions between value tags and admitted literal objects while keeping v0 fixtures directly inspectable. |
| A10 | Fixture format v0 uses a virtual clock for routing health and backoff, an adapter script at the adapter-event level, and a distinct transport fixture family for the OpenAI chat dialect. Timeout and byte-limit proof uses native timeout and mocked transport behavior. | Routing and repair semantics need fixture control; timeout and raw-wire behavior must be tested at their actual boundaries. |
| A11 | C# targets `net8.0`. Runtime dependencies: none beyond the BCL. Test dependency: xunit. A `netstandard2.0` target for .NET Framework consumers is a packaging decision after M2, not part of the proof, because it would add `System.Text.Json` and `Microsoft.Bcl.AsyncInterfaces` as package dependencies. | Broadest reach: a `net8.0` library is consumable from .NET 8, 9, and 10 applications, and everything the profile needs (`IAsyncEnumerable`, `CancellationToken`, `Utf8JsonReader`, streaming `HttpClient`) is in the .NET 8 BCL. .NET 8's support end date (2026-11-10) affects runtime patching for consumers, not what the library can target or what CI can build. Compatibility breadth is the point of the port. |
| A12 | Python tooling is not the universal driver API. A final conformance driver verifies the corpus release identity before running and reports its own environment binding; an unreleased development observation verifies its hashed inventory instead. | Independence is the point of a native port. |
| A13 | Writing or reproducing a reference run starts only from a clean committed implementation, driver, fixture, and specification-input revision. Its manifest binds `reference_run_revision`; actual imports; interpreter; complete runtime/dependency lock and resource identities (`httpx2`, `jsonschema`, `jsonschema-specifications`, `referencing`, `attrs`, `rpds-py` as applicable); selected validator/defaults/resources; warning policy; and production timestamp. Production dependency ranges remain unchanged. Ordinary later Python and native-language runs report their own source/environment bindings. | The oracle must identify the actual executable environment and the normative inputs it ran, without changing normal installation policy. |
| A14 | Python gains a private time seam: `AsyncClient(..., _clock=None, _sleep=None)` keyword-only. `_clock` is passed to the existing `HealthCache(clock=...)` parameter; `_sleep` is stored as `self._sleep` on the client and used by the generation mixin's backoff in place of the bare `asyncio.sleep`. Production behaviour is unchanged when both are `None`. Zero-length backoffs are skipped and not recorded, as today. | Backoff currently calls `asyncio.sleep` directly and `HealthCache()` is constructed without a clock, so the existing `clock` parameter in `routing/health.py` is unreachable from the public client. |
| A15 | Profile-boundary cases get the verdict `extension` only when the fixture explicitly marks the case and the implementation declares that exact feature name in its report's `extensions` list. `extension` never counts as `pass`; Python declares all eight v0 extension feature names, including `schema.unknown_keywords_ignored`. Selected native out-of-domain outcomes, including raw validation exceptions or warnings such as `$schema: null` with declared warnings-as-errors, may be recorded honestly as `extension`. Harness/setup/fatal-runtime failure, skipped execution, or missing required evidence is `error`. Unexpected cancellation cannot manufacture extension; genuine native cancellation propagates, while an explicit cancellation case compares its expected native outcome normally. Missing portable projection outside the admitted domain is expected, not a capture failure. | Python intentionally accepts broader schemas and inputs. The honest reference result is an explicit extension, not a fake driver-side failure. |
| A16 | The prompt-mechanism schema injection is normative: the exact instruction text, the canonical JSON rendering of the schema (sorted keys, two-space indent, ASCII escapes), and the append-to-last-system-message rule are in the specification draft §5. Fixtures reference it with a `{"$schema_prompt": true}` segment rather than repeating it. | What the model sees is the contract. The rendering is small enough to specify exactly and the C# side can produce it without a Python dependency. |

Superseded directions, kept under `evidence/` for milestone 3 and later: I1 exact
malformed-schema domain, F1 evidence-bridge comparison, the L1/C1/M1 accounting lifecycle
matrix, and the operation accounting candidate contract. O1's full private capture remains
archived as the fallback if A6's bounded proof or isolation gates fail.

## 3. Profile `core-generation` v0

The shared specification owns the detail. The boundary, in one table:

| Area | In v0 | Out of v0 (declared `unsupported_input` before inference where requested) |
|---|---|---|
| Execution | Async buffered and streaming generation through one core; concurrent independent operations; cancellation and disposal. | Sync facade. |
| Messages | Ordered text parts in system, user, assistant roles. | Multimodal parts, tool messages (extension). |
| Targets | Explicit `provider:model`, split at the first colon. | Aliases (extension), catalog resolution, discovery. |
| Sampling | Existing text sampling fields; unset values omitted. | Provider-specific escape hatches. |
| Structured output | Admitted 2020-12 subset; extraction; validation against the original schema; the `prompt` mechanism with normative prompt injection; same-target repair with per-attempt budget and provider ceiling clamp. | Selecting or executing a native `json_schema`, `json_mode`, or `grammar` mechanism (O6); `$ref` and combinators (extension). |
| Routing | Ordered targets; duplicate-target skip; per-target retry policy; retryable predicate; backoff with Retry-After; health suppression; attempt trail; post-content protocol-error guard. | Pacing, reservations, spend enforcement, redirection routes. |
| Results and events | Normalized result, parsed structured output, target, finish reason, nullable usage, timing presence, local repair count; typed attempt, content, usage, timing, terminal events; `repair_attempted` and `parameter_dropped` telemetry. | Accounting snapshots (milestone 3). |
| Adapters | Fixture adapter (driver-owned) and one OpenAI-compatible chat-completions adapter. | Responses dialect, every other provider, model listing, health probes. |
| Errors | Semantic categories, retry fields, bounded redacted detail. | Stable numeric codes (open until a second port needs them). |

Everything in `DESIGN.md` that is not in this table (local acquisition, context budgeting,
tools, embeddings, reranking, pricing refresh, CLI, demo, sidecar, MCP) remains part of the
product and part of the Python SDK. Its absence from v0 describes an incomplete port.

## 4. Layout

Literal paths. Create nothing until the box that owns it.

| Path | Owner box | Content |
|---|---|---|
| `src/python/anyinfer/`, `src/python/anyinfer_demo/`, `src/python/anyinfer-store/`, `src/python/anyinfer-shared/`, `src/python/anyinfer-confidential/` | M0.1 | Relocated Python packages, unchanged content. |
| `src/python/anyinfer/schema/validate.py` | M1.1 | Structured issue seam. |
| `src/python/anyinfer/_client/async_client.py`, `_client/generation.py` | M1.5 | Private time seam (A14). |
| `.gitattributes` | M1.3 | `specification/** text eol=lf` so release hashes are platform-stable. |
| `scripts/check_markdown_links.py` | M1.2 | Stdlib link checker over a directory of Markdown files; exits non-zero on a broken relative link. |
| `specification/README.md` | M1.2 | Profiles, vocabulary, verdicts, how a report is read. |
| `specification/core-generation.md` | M1.2 | The normative profile text. |
| `specification/MAINTENANCE.md` | M1.2U | Immutable-release maintenance and compatibility rules. |
| `specification/schemas/fixture-v0.schema.json` | M1.3 | Core fixture schema. |
| `specification/schemas/transport-v0.schema.json` | M1.3 | Transport fixture schema. |
| `specification/schemas/report-v0.schema.json` | M1.3 | Conformance report schema. |
| `specification/schemas/inventory-v0.schema.json` | M1.3 | Versioned case-inventory schema. |
| `specification/inventories/core-generation-v0.json` | M1.4 | Requirement mappings and exact core, transport, and driver-assertion records; transport fixture files follow in M1.6. |
| `specification/fixtures/core-generation/<family>/<slug>.json` | M1.4 | Named core corpus inventory and requirement coverage in specification draft §17. |
| `specification/fixtures/transport/openai-chat/<slug>.json` | M1.6 | Named HTTP transport corpus and requirement coverage in specification draft §17. |
| `specification/reference/python-<rev7>.json` | M1.7 | Reference manifest written by the Python driver. |
| `specification/reference/python-<rev7>.environment.json` | M1.7 | Reference environment and resource identities. |
| `specification/releases/core-generation-v0.json` | M1.G | Frozen identity: hashes of normative specifications, schemas, exact fixture inventories, reference manifest, and the reference environment identity artifact. |
| `scripts/validate_fixtures.py` | M1.3 | Validates fixtures and inventories, including named coverage checks; `workspace check` phase. |
| `tests/test_schema_capture.py` | M1.1 | Private assessment-collector compatibility tests. |
| `tests/test_schema_capture_integration.py` | M1.1 | Native operation, correction, cancellation and consumer-context capture proofs. |
| `scripts/freeze_release.py` | M1.G | Writes the release file; with `--verify` recomputes and compares hashes. |
| `scripts/compare_reports.py` | M1.5 | Rejects unqualified/development reports and compares two qualified report files case by case. |
| `tests/testing/portable/bad_fixtures/core-generation/missing-expected.json` | M1.3 | Deliberately broken fixture for the validator's negative test. |
| `tests/testing/portable/` (everything else) | M1.5 | Python driver (private; promoted to `anyinfer.testing.portable` only if a second consumer appears). |
| `src/csharp/AnyInfer.sln`, `src/csharp/AnyInfer/` (class library), `src/csharp/AnyInfer.Conformance/` (xunit project: driver and corpus runner), `src/csharp/AnyInfer.Tests/` (xunit unit tests) | M2.1 | C# library, driver, unit tests. |
| `plans/language-neutral-foundation/ANYINFER_CSHARP_PROOF.md` | M2.1 | Bounded C# execution plan. |

## 5. Execution checklist

Phases run in order. M1.2 and M1.2U establish the normative and maintenance contracts; M1.3
then establishes their schemas; M1.4 and M1.6 author their respective fixture families against
those contracts. M1.1 and M1.5 to M1.7 are serial. Sub-agents never touch git state.

### M0: Common source root

This phase has no dependency on anything below and may ship as its own pull request first.
M1 and later use `src/python/` paths and therefore depend on it.

- [x] M0.P Reconcile the upstream baseline requested by the user. Preserve and verify the
  19-file plan overlay and pre-reset recovery point; reset to freshly fetched upstream
  `develop`; review open GitHub PRs/issues and integrate relevant changes without bypassing
  branch protection. Prefer one reviewed integration PR for overlapping refreshes, with
  provenance for each original PR and explicit treatment of superseded snapshots.
  **Gate:** combined relevant updates pass `workspace check` and GitHub's required `ci-ok`;
  the upstream integration result, original PR dispositions, issues inventory and resulting
  baseline commit are recorded in `EXECUTION_LOG.md`. No unrelated untracked work is removed.
  > NOTE: The reset and verified plan overlay completed at source HEAD `13b9e65`; the
  > user's existing untracked nested `AnyInfer/` checkout is retained. Content authoring for
  > M1.2/M1.2U may proceed independently; no runtime box is accepted before its prerequisites.
  > NOTE: PR #51 contains the reviewed combined updates at `b166241` and passed all 12
  > local gate steps. M0.1 authoring proceeds from that commit while GitHub CI runs;
  > acceptance of M0.1 still waits for M0.P's protected integration result.
  > NOTE: Completed via PR #51, required `ci-ok` SUCCESS, merged 2026-10-15 at
  > `955054fd90d86cb1eb1a3cb3f4a0ebfd7171164d`. All ten original PRs are closed as
  > integrated or superseded; no open issues or PRs remain from that inventory. The repository
  > enforces squash merges: after verifying identical source trees, a soft baseline update
  > preserved all relocation work while adopting the upstream squash commit.

- [x] M0.1 Move `src/anyinfer`, `src/anyinfer_demo`, `src/anyinfer-store`, `src/anyinfer-shared`,
  and `src/anyinfer-confidential` under `src/python/`. Update every path literal: `pyproject.toml`
  (`[tool.hatch.build.targets.wheel] packages`, sdist `include`, ruff `src` and per-file ignores,
  `[tool.mypy] files`, pytest `testpaths`); `workspace.py` (`REPO_MARKERS`, `LINT_PATHS`, `SHARDS`,
  the `ROOT / "src" / "anyinfer"` rglob, the `sys.path.insert`, the PyInstaller `--paths`, the demo
  assets path); `mkdocs.yml` (`paths: [src]` and any other); `.github/workflows/ci.yml` and
  `docs-site.yml` shard installs; `catalog-refresh.yml` prose; `scripts/*.py` `sys.path` inserts
  and path constants (`check_catalog_drift`, `check_pricing_drift`, `validate_pricing`,
  `validate_catalog`, `pin_catalog`, `pin_runtimes`, `generate_provider_index`); `AGENTS.md`
  layout table and §Layout line; `DESIGN.md` §18 tree; `contracts/copilot.md`, `m365-copilot.md`,
  `NEW-PROVIDER.md`, `DRIFT-CHECK.md`; `docs/contributing/automation.md`, `branding.md`,
  `docs/guides/installation.md`, `confidentiality-tiers.md`, `vector-store.md`, `demo-app.md`,
  `docs/contributing/README.md`; `CONTRIBUTING.md`; `.gitignore`; `plans/CODEBASE_STATUS.md`
  and `plans/DEBLOAT.md`; `src/python/anyinfer_demo/sdk_help.py`;
  `src/python/anyinfer/capabilities/pricing_table.py`; and the tests that assert path strings
  (`tests/test_workspace.py`, `test_agent_instructions.py`, `test_cli_context.py`,
  `test_catalog_data.py`, `test_branding.py`, `test_pricing_drift.py`, `test_pricing.py`);
  and `src/anyinfer-store/README.md`, `src/anyinfer-shared/README.md`, and
  `src/anyinfer-confidential/README.md` editable-install paths. Relocated content is otherwise
  unchanged.
  Reinstall the editable package and the three shards.
  **Gate:** `.\.venv\Scripts\python.exe -c "import anyinfer; print(anyinfer.__file__)"` prints a
  path under `src\python\`; `.\workspace.cmd check` passes; the coordinator reviews the
  explicit old-to-new file mapping and staged diff against the recorded pre-phase state.
  File contents are identical except the named path updates, and no unrelated work is staged
  or changed. Git's rename labels are review evidence, not the correctness criterion.
  > NOTE: Memory says a stale editable `.pth` can silently point at another checkout. The
  > import check above is mandatory, not optional.
  > NOTE: The coordinator moved five roots and verified all 249 tracked files byte-for-byte
  > against a SHA-256 old-to-new mapping at `b166241`. Tooling, documentation and source/test
  > path updates run as three disjoint workstreams. The coordinator alone reconciles this
  > shared checkbox after their targeted checks and the complete phase gate.
  > NOTE: All 12 `workspace check --fail-fast` steps passed (96.0s), with an isolated
  > pytest cache. The actual five imports resolve under `src/python/`; all 249 mapped files
  > exist with no extras. The only five package-content changes are exact path substitutions.
  > Independent review found four doubly relocated inner-shard paths in legacy plan anchors;
  > those were corrected and doc links rechecked. No material relocation finding remains.

### M1: Specification, corpus, and Python driver

- [x] M1.1 Lossless native assessment seam. Keep the existing `validator_for` / `check_schema` /
  `iter_errors` / relevance / cap path and its exact selected native strings for every schema,
  including schemas outside the profile. Do not refactor `validate` through
  `render_issue(portable_issue)`. In `src/python/anyinfer/schema/validate.py`, add frozen,
  private immutable `Issue` and `NativeAssessment` types: each assessment pairs the selected
  portable projection with selected native rendered messages, selected native error metadata,
  original input/schema paths, pre-sort native occurrence ordinal/group, and actual selected
  order. `NativeAssessment` is not a public API; a projection outside v0 may be unavailable.
  Capture the actual helper assessment per invocation, never a recomputed validation pass. For
  `required`, derive individual missing names from the original required-array order and instance
  membership, associating occurrences without parsing prose; native `validator_value` is the
  whole array. Preserve `SchemaError.path`, including index segments rather than assuming only a
  keyword path.

  Add a minimal private test-only `ContextVar` collector. It records operation identity and an
  adapter-entry ordinal. Keep owned operation/entry state in the executing generator so that it
  persists through adapter cleanup and subsequent validation. Activate and reset helper capture
  context synchronously around the actual extraction/validation/builder invocations; never keep
  a context token active across an async-generator yield or an await. Independent operations
  and any native producer tasks receive separate state. Observe
  extraction and validation/exhaustion so actual selected occurrences, order, multiplicity, and
  required-name association
  flow to the formatter suffix and the entered-wire evidence. The collector is private and owned,
  never an arbitrary user callback or reentrant observer. Collector/projection failure,
  incomplete snapshot, or cap exhaustion makes evidence unavailable and conformance fail; it
  never changes the native result, retry/repair decisions, exception/cancellation, or strings.
  Disabled capture does no capture work. Bound private capture to 128 assessments and 1,048,576
  snapshot bytes per operation; no default disk or network export. Sink faults never replace an
  existing exception/cancellation or introduce an await/yield or task-cancellation manipulation,
  and the context is always reset. The tests cover controlled, non-racing collector/projection/cap
  faults only; they preserve native outcomes but do not promise containment of process-fatal
  failures, malicious/reentrant code, or ambient-cancellation races. Genuine native cancellation
  always propagates; capture completeness is separate. These bounds exist only for the private
  harness, not an SDK integration requirement.

  Give an assessment from completed original or failed-content entry `N` its own
  `source_entry_ordinal`; a later correction is entry `N+1` with its own ordinal and a
  `repair_assessment_ref` to that assessment ID. Do not require the ordinals to be equal. The
  actual formatter/builder arguments and output, and the entered correction wire, must link to
  that same assessment reference; an absent preparation or entry has no call reference. A
  correction role denotes the actual repair transition, never merely a template substring in user
  text.

  Add tests for broader-schema string equality, `x` versus `y` with the same portable type but
  distinct native messages, dotted versus nested paths, six missing required properties capped at
  five in original required order, interleaved tied rules, distinct source/correction IDs and
  ordinal linkage, terminal exhaustion, malformed
  extraction/native `SchemaError`, simultaneous independent operations, capture fault/cap
  isolation, and disabled capture in `tests/test_schema_capture.py` and
  `tests/test_schema_capture_integration.py`. SDK users do nothing new.
  **Gate:** `.\.venv\Scripts\python.exe -m pytest -q tests/test_schema.py tests/test_schema_partial.py tests/test_schema_capture.py tests/test_schema_capture_integration.py`
  passes with existing string assertions untouched and the A6 bounded-proof/isolation tests
  passing. If either gate cannot be met, stop and revisit archived O1 full capture before
  changing native behavior.
  > NOTE: Static execution audit found that Python's async stream is consumed directly by
  > `AsyncStream.__anext__`; it has no background producer task. A generator-wide ContextVar
  > token would leak into the consumer and could be reset from a different task. The small
  > seam therefore also touches `_client/generation.py`, retains operation state explicitly,
  > and scopes ContextVar activation to synchronous helper calls. Add consumer-context and
  > cross-task stream advancement/close isolation tests. This changes private observation
  > mechanics only; public stream, validation, retry and repair behavior stay unchanged.
  > NOTE: Private record/collector types live in `schema/_capture.py`; actual helper
  > assessment remains in `schema/validate.py`. Unit projection/bounds and native operation
  > integration proofs have disjoint test files. The seam remains unaccepted until all bounded
  > proof/isolation cases and independent code review pass; initial partial green runs did not
  > establish completion.
  > NOTE: Cold review found that a failed preparation snapshot could leave a correction-wire
  > assessment reference without its preparation record. Retention now has an explicit success
  > result; the caller must retain the correction role but omit the reference after capture
  > failure. Acceptance also requires independent assessment-count/byte-cap proofs and exact
  > selected occurrence, native feedback and builder/wire linkage checks.
  > NOTE: Accepted after final independent fault-boundary review, the exact four-file schema/
  > capture gate (91 tests), and all 13 repository gate steps passing in 76.6 seconds.
  > Argument-construction and entered-wire sink failures are contained by observation-only
  > guards; direct fault tests preserve native returns, exceptions, cancellation and repair.
- [x] M1.2 Write `specification/README.md` and `specification/core-generation.md` from the
  specification draft §1 to §18. Promote the normative fixture format, driver actions and
  language-neutral proof recipes/predicates from §§14 and 17; the draft must not remain their
  only source. Normative text only; rationale stays in the draft.
  No Python symbol names appear in the normative text except in a clearly marked
  "Python reference notes" appendix. The authored documents must respect the schemas and
  maintenance contract before M1.G; do not claim unsupported parallel dependencies.
  Also write `scripts/check_markdown_links.py` (stdlib only).
  **Gate:** `.\.venv\Scripts\python.exe scripts/check_markdown_links.py specification plans/language-neutral-foundation`
  exits 0; a reviewer agent reports no contradiction between the two files and the
  specification draft, and every finding it raises is dispositioned in a `> NOTE:` here.
  > NOTE: Independent review found malformed promotion fragments, implementation symbols
  > outside the reference appendix, undefined plan labels and an unresolved-reference link
  > checker gap. All were corrected; final independent review reports no open finding.
  > The coordinator also corrected 18 double-decoded section marks using explicit UTF-8.
  > The exact link gate passes (`Markdown links OK (23 file(s))`); undefined reference,
  > missing-target and missing-fragment negative checks fail as required.
- [x] M1.2U Write `specification/MAINTENANCE.md` before M1.G. Define immutable release IDs;
  compatible changes versus breaking changes/new releases; review required to rebaseline a
  reference or change its inputs; per-native-implementation supported revisions; and required
  checks when Python behavior or a provider changes. Require old assets to remain reconstructible
  from an immutable annotated Git tag and recorded commit in an external index or release tag,
  with every manifest-hashed file retrievable from that tag; avoid a self-referential manifest
  field cycle. Do not invent publishing authority or support windows: independently supported
  releases require a user owner/support decision.
  **Gate:** `.\.venv\Scripts\python.exe scripts/check_markdown_links.py specification plans/language-neutral-foundation`
  exits 0 and a reviewer confirms the maintenance rules are compatible with M1.G.
  > NOTE: Independent review required explicit change-trigger checks and preservation of
  > reference/release manifest field identities. Both were added; final review reports the
  > maintenance/bootstrap contract compatible, with no ownership or support-window claim.
- [x] M1.3 Write `specification/schemas/fixture-v0.schema.json`, `transport-v0.schema.json`,
  `report-v0.schema.json`, and `inventory-v0.schema.json` from the shared specification, plus
  `scripts/validate_fixtures.py` (stdlib and `jsonschema` only) that validates every file under `specification/fixtures/core-generation/`
  against the fixture schema and every file under `specification/fixtures/transport/` against the
  transport schema, exiting non-zero on the first failure. It accepts `--root <dir>` to validate
  another tree with the same directory-to-schema rule (`core-generation/` and `transport/`
  subdirectories), validates `specification/inventories/core-generation-v0.json`, and supports
  `--check-coverage --family core-generation` against its explicit requirement-to-case mappings.
  Case records are `{id, kind: fixture|driver_assertion, path|null, family, extension}`; a
  driver assertion has a `recipe_ref` to a language-neutral normative predicate, never a Python
  path masquerading as a fixture. Inventory absence is allowed only in the initial authoring
  stage; `--check-coverage` and release verification require it. Wire the validator into
  `workspace.py` as a `check` phase. Also create
  `tests/testing/portable/bad_fixtures/core-generation/missing-expected.json` (a fixture with
  no `expected` key) and add the `.gitattributes` rule `specification/** text eol=lf`.
  **Gate:** the script exits 0 on an empty fixtures tree and exits non-zero with
  `--root tests/testing/portable/bad_fixtures`; its inventory validation rejects an invalid
  record and its coverage mode rejects a missing requirement mapping.
  > NOTE: Schema authoring exposed a representation gap in the already-required image
  > extension case: text-only fixture messages cannot construct an image input. Shared §14
  > now permits an explicit `{role, parts}` input variant only for `messages.non_text_parts`,
  > with typed text/image-URL parts. Drivers invoke the native boundary honestly; the profile
  > stays text-only. Schema negatives must reject the variant on an ordinary core case.
  > NOTE: Review clarified that extension fixtures' zero-call `unsupported_input` expectation
  > is the portable baseline, not a replacement for declared extensions' actual native outcome.
  > Required driver cases now have an explicit `evidence: {recipe_ref, observations}` report
  > record: the recipe must match the inventory and native observations must be nonempty.
  > This closes the existing mandatory-evidence requirement without prescribing native spy APIs.
  > NOTE: An `extension` verdict also requires an explicit native outcome and ordered actual
  > adapter-entry evidence; it cannot be an unsupported-input baseline plus a verdict label.
  > Failed/errored cases may report unavailable evidence as null, preserving terminal-failure
  > reporting while preventing a qualified result. The §16 record shapes own these rules.
  > NOTE: Cold review requires mutually exclusive transport inputs, strict Base64 validation,
  > coverage resolved against the supplied asset root, and consecutive extension-entry ordinals.
  > Coordinator review additionally found the core outcome schema rejected every legal outcome;
  > positive result/error/none fixtures must pass alongside the negative gates. The §13 integer
  > bound is the stated inclusive ±2^63 range; its two corrupted glyphs are repaired and the
  > endpoints made explicit. This fixes the asset codec, without changing Python input handling.
  > NOTE: Further positive-case review requires nullable mechanisms for unstructured calls and
  > rule-specific nullable extraction/invalid-schema paths. Inventory records must agree with
  > the selected file's path, ID and family; sampling/actions and expected-message marker
  > positions must satisfy the closed fixture protocol. Shared §14 now spells out script
  > event/action variants so drivers cannot invent semantics for otherwise untyped actions.
  > NOTE: Accepted after independent review found no correctness blocker, all 13 repository
  > gate steps passed, and the final 12-test asset gate closed direct path-substitution and
  > family-drift proof gaps. Schemas are UTF-8 without BOM, LF-only. Authoring validation
  > remains developmental: no inventory, reference observation or release is claimed yet.
- [x] M1.4 Author `specification/inventories/core-generation-v0.json` before the final oracle:
  its requirement-to-case mappings and exact case records define the named core inventory. Add
  one fixture file per `kind: fixture` record; record transport coverage obligations that M1.6
  must satisfy as requirement mappings, while language-neutral driver assertions carry their
  normative recipes/predicates in the shared specification.
  Cover every admitted failing validation rule and
  its portable parameters/order, lazy invalid-second-target behavior, correction/exhaustion,
  and every timeout/byte-limit requirement: timeout default, supplied value, correction reset,
  per-entry reset, and cleanup timeout; plus raw UTF-8 transport bytes, buffered and streamed
  paths, and byte-limit reset on correction. Cover within-winning-entry `Usage.merge` overlay and
  null preservation, including an explicit total that is not recomputed; these are existing usage
  semantics, not accounting.
  Capture effective timeout and maximum bytes for every entered wire. Script entries gain an
  await-release gate/action with a fail-safe watchdog. Timing assertions compare signal order,
  never elapsed thresholds. Use actual native timeout for timeout proof and preserve production
  `asyncio.timeout`; do not substitute a fake timeout. Extension cases are explicitly marked,
  declare one of the eight feature names (including `schema.unknown_keywords_ignored`), and do
  not use a driver-side fake rejection. Expected values may be `to_be_observed` until M1.7.
  Agents split by family; no two agents write the same family.
  **Gate:** `.\.venv\Scripts\python.exe scripts/validate_fixtures.py --check-coverage --family core-generation`
  passes; it proves every named core requirement has a case, each inventory ID is unique with no
  missing or extra fixture files, and extension feature names are exactly the declared set. This
  is partial DEVELOPMENT coverage only, never release-qualified proof. No fixed case total is
  asserted.
  > NOTE: Authoring starts from accepted seam/assets commit `90c2605`. Three disjoint owners
  > write normalization/repair, schema-admission/extraction/validation, and routing/streaming/
  > lifecycle plus the shared inventory. The coordinator owns this joint checkbox and reconciles
  > coverage after all families report, avoiding concurrent edits to the master. Initial
  > expectations stay `to_be_observed`; their empty observations are authoring placeholders,
  > not claims about native outcomes. Asset files must be UTF-8 without BOM and LF-only.
  > NOTE: Review requires fine-grained runtime/adapter obligation mappings to §§2–14 rather
  > than family-level §17 labels. Shared §17 distinguishes these case mappings from mandatory
  > global report/release qualification checks; no runtime case can waive those gates. The
  > admitted-full-subset fixture must actually include the admitted keywords and annotation
  > data, not merely carry a comprehensive-sounding name.
  > NOTE: Input review found generic-success routing/lifecycle scripts that could not enter
  > their named branches; a fresh owner corrects all 25 affected files. Scripted failure
  > categories are closed to real adapter errors, including `stream_protocol`; core failures
  > cannot be injected. Shared §17 makes buffered/streamed mirroring and native duplicate-key
  > iteration-order observation explicit, so ordinary value equality cannot hide missing proof.
  > NOTE: Accepted with 85 pending core fixtures, 112 case/crosscutting requirement mappings,
  > exact canonical case-kind/recipe identities, clean independent re-reviews, the staged core
  > coverage gate, and all 13 repository gate steps passing in 79.5 seconds. The final
  > incremental 15-test asset gate also passes. Full coverage deliberately fails only for the
  > 11 transport fixture files due in M1.6; these counts describe this authored revision.
- [ ] M1.5 Python driver under `tests/testing/portable/`. Includes the A14 time seam:
  `AsyncClient.__init__` gains `_clock: Callable[[], float] | None = None` and
  `_sleep: Callable[[float], Awaitable[None]] | None = None`; `_clock` is forwarded to the
  existing `HealthCache(clock=...)` at the construction site in `async_client.py`; `_sleep`
  is stored as `self._sleep` and `generation.py`'s backoff awaits `self._sleep(delay)` when set,
  else `asyncio.sleep(delay)`. Add a test that both defaults reproduce current behaviour. The
  driver provides: a fixture provider (a `ProviderDescriptor` plus adapter, registered the same
  way `anyinfer.testing.ScriptedProvider` registers itself; record the exact registration call
  in a `> NOTE:` here) that replays the fixture's adapter script and exposes
  `max_repair_attempts` from `adapter.max_repair_attempts`; a virtual clock recording each
  non-zero backoff; an await-release script gate/action with a fail-safe watchdog for real native
  timeout and cleanup-timeout proof; a pytest plugin option `--portable-report <path>` that runs
  every fixture through the real `AsyncClient` with the real router and repair loop, captures
  every adapter entry, effective wire timeout/max bytes, every public event, every
  `repair_attempted` and `parameter_dropped` telemetry event, A6's actual assessment evidence,
  and the result or error, applies the A15 extension rule, and writes explicitly UNRELEASED
  development observations against the hashed draft inventory; and `--write-reference <path>`
  for the manifest (specification draft §15). It cannot write `report-v0` before M1.G supplies a
  release hash. The driver never reimplements routing, repair, or validation selection. The
  `driver/concurrent-operations-independent` assertion (§17) lives here as a plain test.
  Also implement `scripts/compare_reports.py` and its negative tests against synthetic/Python
  reports: reject development observations, missing/extra/duplicate IDs, wrong release/hash,
  stale counts, errors/failures, absent/mismatched driver evidence, absent native extension
  outcomes/entry evidence, and ineligible extension verdicts; permit only the qualified
  reference-extension versus other-language-pass disagreement.
  **Gate:** `.\.venv\Scripts\python.exe -m pytest -q tests/testing/portable` passes against
   every named extraction/repair requirement plus the seam, timeout, wire-limit projection, and independent
  operation tests. The development observation identifies script/core evidence; it is not a
  release-qualified conformance report.
  > NOTE: Execute this larger box in bounded waves. First establish the replay adapter/gates,
  > the private time seam, and independent value/expected-segment helpers in disjoint files.
  > Then wire native execution/projection and driver predicates; finally add report/reference
  > identity and fail-closed comparison tooling. The coordinator records each wave below and
  > owns this shared checkbox. No partial wave establishes the M1.5 gate.
  - [ ] M1.5a Replay substrate: `tests/testing/portable/{__init__,adapter,test_adapter}.py`;
    private time seam in `_client/{async_client,generation}.py` plus
    `tests/testing/portable/test_time_seam.py`; value/segment helpers in
    `tests/testing/portable/{values,test_values}.py`. Each owner runs its targeted tests and
    lint/types; an independent review clears their interfaces before the execution runner.
  - [ ] M1.5b Native runner/projection, all core fixture executions, explicit buffered mirror,
    native duplicate-key order, capture causality and real timeout/cancellation/lifecycle
    predicates; pytest options write development observations only. Gate: targeted portable
    tests execute every authored core fixture with no unavailable mandatory evidence.
  - [ ] M1.5c Reference/report identity support and `scripts/compare_reports.py` with its
    required negative tests. Gate: incomplete/development/wrong-identity/failing reports
    cannot qualify, and the documented qualified synthetic/Python comparisons behave exactly
    as required. The enclosing M1.5 gate still requires all waves together.
- [ ] M1.6 Transport fixtures and driver support in `tests/testing/portable/transport.py` for an
  actual native mocked OpenAI chat-completions transport. `transport-v0` distinguishes an
  `adapter` case (`input.adapter_config` and `input.wire`) from a `core_http` case
  (`input.adapter_config` and `input.operation`). Ordered `responses` supply status, headers,
  and base64 byte chunks; `expected.http_requests` checks actual method/path/headers/JSON and
  stream mode. Associated wire-entry observations check effective timeout/max bytes; these
  are not imaginary HTTP headers or `HttpClient` byte-limit arguments. Both HTTP modes yield
  typed adapter events or an error. `core_http` adds the normal core expectations for repair,
  events, results and failures. Assert outgoing buffered/streamed requests, sampling omission,
  message/prompt projection, SSE split/chunk cases, non-SSE errors and functional raw-byte
  limits/reset. The adapter never receives expected outcomes as inputs.
  **Gate:** `.\.venv\Scripts\python.exe -m pytest -q tests/testing/portable tests/test_openai_compat.py`
  passes; `.\.venv\Scripts\python.exe scripts/validate_fixtures.py --check-coverage` proves
  complete DEVELOPMENT coverage for core and transport requirements. This remains unreleased.
- [ ] M1.7 Oracle run has two stages. First, run the UNRELEASED development oracle against the
  hashed draft inventory to fill every pending
  expectation and classify each mismatch as fixture error, specification error, or Python bug in
  a `> NOTE:` here; a Python bug is filed, not fixed in this box. Reconcile the inputs through the
  coordinator and commit the implementation, driver, fixture, inventory, and specification-input
  revision A.
  Second, from clean committed revision A, verify actual imports and write the complete
  environment lock/resource-identity artifact and `specification/reference/python-<rev7>.json`.
  Run the clean reference-observation oracle with Python declaring all eight extension feature
  names. Generated observation/manifest outputs may be output-only exceptions; executable inputs
  must not be dirty.
  **Gate:** no pending expectations; the clean reference observation has zero `fail`/`error`, exact inventory coverage and
  only permitted explicitly marked extension cases; the manifest records A13's complete
  environment binding; `.\workspace.cmd check` passes. This is not yet a `report-v0` or a
  conformance claim.
- [ ] M1.G **Corpus freeze.** Write `scripts/freeze_release.py` and freeze
  `specification/releases/core-generation-v0.json` as a candidate. The candidate hashes
  `specification/README.md`, `core-generation.md`, `MAINTENANCE.md`, schemas, inventory, every
  listed fixture, reference manifest, and environment artifact. It embeds or derives the exact
  case set from the inventory; binds reference-run revision A; and places its own release-file
  hash only in generated reports as `release_sha256`, avoiding a circular self-file hash.
  `--verify` checks all hashes, exact inventory, and no pending expectations. Rerun Python's full
  corpus against the candidate to write the first FINAL `report-v0` bound to its release hash.
  Reports state exact complete IDs, uniqueness, no extras, derived counts, release identity, and
  actual native environment and the final report's own current clean code revision. Comparison is
  fail-closed: `fail` or `error` is never success even
  if reports match; matching eligible extension verdicts are allowed, and the sole allowed
  disagreement is reference-extension versus another language's pass.
  **Gate:** `.\.venv\Scripts\python.exe scripts/freeze_release.py --verify core-generation-v0`
  exits 0; the final Python report has `fail: 0`, `error: 0`, exact inventory coverage, and only
  permitted marked extensions; negative gates reject empty, missing, extra, duplicate,
  stale-count, changed-specification/reference, wrong-hash, and extension-on-mandatory-case
  reports; a cold reviewer reports no open finding. The candidate is not public or supported
  until a separate publishing decision. Do not use one global hash that silently adds future
  fixtures to old releases.
  > NOTE: A later committed release record (called B here) records generated manifests and the
  > release file, and the immutable annotated retrieval tag targets it; additional tool-only
  > commits are allowed. Reference reproduction checks out A and supplies frozen released assets
  > from B through `--root`; it does not require a circular self-commit. Later Python and C# runs
  > verify frozen assets and report their own source/environment bindings; only
  > `--write-reference` requires the exact reference-run preflight.

### M2: C# proof

- [ ] M2.1 Write `ANYINFER_CSHARP_PROOF.md`: project list from §4, namespace layout, public type
  names for request, message, result, event, and error, the single adapter-invocation boundary
  (A4), the fixture-adapter and driver design, native timer/assessment observation and mocked HTTP proof, release
  verification/report-completeness rules, `dotnet test` commands, and per-box file
  ownership. Decide proceed / narrow / stop after reading the frozen corpus and record it there.
  **Gate:** the coordinator records proceed / narrow / stop against the frozen corpus and
  verifies that the proof plan remains within the user's M0–M2 execution authorization.
  A scope expansion or compatibility reversal requires a new user decision.
  > NOTE: The user's 2026-10-15 execution request authorizes this bounded C# proof. It
  > supersedes the earlier separate approval handoff; it does not waive corpus or test gates.
- [ ] M2.2 Types, schema subset validator over `Utf8JsonReader`, extraction, canonical JSON
  rendering for prompt injection. Unit coverage for every admitted keyword, every extraction
  branch, duplicate keys, code-point string ordering, and the rendering of each JSON value kind.
  **Gate:** `dotnet test src/csharp/AnyInfer.Tests` passes.
- [ ] M2.3 Async core: request normalization, routing with retry/backoff/health, repair loop,
  streaming with `IAsyncEnumerable`, cancellation, the post-content guard, and the single
  adapter-invocation boundary (A4) through which every adapter entry passes. Own the internal
  test seam observing native timer creation/configuration/disposal and actual assessment
  linkage; C# must prove the same driver predicates without depending on Python instrumentation.
  **Gate:** `dotnet test src/csharp/AnyInfer.Tests` passes.
- [ ] M2.4 Fixture adapter and conformance driver in the `AnyInfer.Conformance` xunit project;
  verify frozen assets and exact inventory, then run core and available driver cases as explicit
  unreleased/subset development observations. Reject missing, duplicate, extra, wrong-release,
  wrong-hash, stale-count, or improperly exempted extension cases whenever a complete report is
  attempted. Do not claim a complete `report-v0` or profile proof before M2.5 supplies native
  HTTP execution.
  **Gate:** `dotnet test src/csharp/AnyInfer.Conformance` passes and writes only the documented
  subset DEVELOPMENT observation with its own source/environment binding.
- [ ] M2.5 OpenAI-compatible chat-completions adapter over `HttpClient`; run the transport fixtures
  through a native mocked transport that asserts method/path/headers/JSON/default stream mode,
  associated effective wire limits, response status/headers/raw chunks, buffered and streamed
  results/errors, and the schema/repair envelope. The adapter must not read expected outcomes to
  manufacture requests. Implement C# native timer-freshness and context-spy equivalents for the
  same language-neutral driver predicates; a Python-only proof cannot substitute for these cases.
  **Gate:** `dotnet test src/csharp/AnyInfer.Conformance` passes including the transport family
  and every named HTTP/limit driver proof requirement, then writes the first complete `report-v0`
  with `fail: 0` and `error: 0` against every mandatory inventory case.
- [ ] M2.G **Port gate.** `.\.venv\Scripts\python.exe scripts/compare_reports.py <python-report.json> <csharp-report.json>` exits 0:
  every exact, unique released case ID has the same verdict in both reports, no report has a
  `fail` or `error`, and the only exception is an explicitly marked case where Python reports
  its declared `extension` and C# reports `pass`. Differences and unsupported features are listed
  in the C# report.
  Report a bounded native proof, not product parity. Packaging and publishing are a separate
  decision.
  **Gate:** the compare script exits 0 and its output is pasted into the box report.

### M3: Operation accounting (separate plan)

- [ ] M3.1 Write `plans/language-neutral-foundation/ANYINFER_ACCOUNTING.md` using the archived
  [operation accounting](evidence/ANYINFER_OPERATION_ACCOUNTING.md) and
  [lifecycle](evidence/ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md) contracts as input. It defines
  the Python API, the `expected.accounting` fixture section (A4), lifecycle and
  usage-provenance observations, no-entry and terminal outcomes, and the C# instrumentation
  seams, including whether the invocation boundary needs companions. Not started until M2.G
  passes.
  **Gate:** user approval of that file.

### M4: Additional ports (repeat per language)

- [ ] M4.1 Feasibility note under `plans/language-neutral-foundation/`: map numeric, string,
  async, and cancellation semantics to the runtime; report any mandatory rule the runtime
  cannot satisfy.
  **Gate:** user decision proceed / stop recorded in the note.
- [ ] M4.2 Bounded plan like `ANYINFER_CSHARP_PROOF.md`.
  **Gate:** user approval.
- [ ] M4.3 Implement; run the frozen corpus; write the report with environment binding.
  **Gate:** the language's own test command passes and the report shows `fail: 0`, `error: 0`.
- [ ] M4.G `.\.venv\Scripts\python.exe scripts/compare_reports.py <python-report.json> <native-report.json>`
  exits 0 with the A15 exception.

## 6. Verification commands

From the checkout on PowerShell:

```powershell
.\.venv\Scripts\python.exe -c "import anyinfer; print(anyinfer.__file__)"
.\.venv\Scripts\python.exe -m pytest -q tests/test_schema.py tests/test_schema_partial.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_schema_capture.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_schema_capture_integration.py
.\.venv\Scripts\python.exe -m pytest -q tests/testing/portable
.\.venv\Scripts\python.exe scripts/validate_fixtures.py
.\.venv\Scripts\python.exe scripts/validate_fixtures.py --check-coverage --family core-generation
.\.venv\Scripts\python.exe scripts/validate_fixtures.py --check-coverage
.\.venv\Scripts\python.exe scripts/freeze_release.py --verify core-generation-v0
.\.venv\Scripts\python.exe scripts/compare_reports.py <python-report.json> <csharp-report.json>
.\workspace.cmd test
.\workspace.cmd check
dotnet test src/csharp/AnyInfer.Tests
dotnet test src/csharp/AnyInfer.Conformance
```

Targeted checks run while iterating; `workspace check` and the C# suites run once per box
gate. Never run two heavy suites concurrently.

## 7. Reporting

Each box report states: HEAD, box ID, files changed, the gate command and its result verbatim,
and the next unchecked box. Corpus runs additionally state the release identity, cases run,
`pass`/`fail`/`error`/`extension` counts taken from the report file, and each mismatch with its
classification.

## 8. Archived material

`evidence/` holds the P0 to P2 planning history, the P1 and I1 audits, the choice records, the
readiness review, and the six superseded contract drafts. They are consulted for milestone 3
and for rationale; they do not supply boxes.

## 9. Decisions reserved for later gates

No further user choice blocks this planning handoff. The selected source layout and
`net8.0` target are settled in A2/A11. Later decisions have explicit owners and timing:

| Decision | Required gate |
|---|---|
| Publishing authority, maintenance ownership and support windows | M1.2U, before independently supported public releases. |
| Proceed, narrow or stop the bounded C# proof after inspecting the frozen corpus | M2.1. |
| Feasibility and scope of each additional native port | M4.1/M4.2. |
