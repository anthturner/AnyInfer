---
kind: spec
title: Language-neutral foundation execution record
---

# Execution record

The [master plan](ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md) owns the checklist. Resume its
first unchecked box; this log records evidence and handoffs rather than a competing plan.

## Authorization and preserved baseline — 2026-10-15

The user authorized the upstream reset, plan overlay, relevant PR/issue integration, complete
Python source relocation, shared-foundation implementation and native C# proof/testing.
Product scope stays Python current → Python+C# next → additional native languages future.
Aggregate operation accounting remains M3; publishing packages remains a separate decision.

- Initial branch/HEAD: `develop`, `13b9e65acfb01038464069ca5fa80f50a9df035c`.
- Freshly fetched `origin/develop` initially matched that HEAD; `origin` is the sole remote,
  `git@github.com:anthturner/AnyInfer.git`.
- Reset completed; all 19 plan-overlay files were copied and verified byte-for-byte before
  restoration. Recovery branch: `backup/pre-foundation-20261015-115654`.
- Backup directory:
  `C:/Users/antho/.traycer/epics/a4822703-eee2-44cb-960c-47b3ae3d4c73/scratch/foundation-backup-20261015-115654/`.
- Execution branch: `feature/language-neutral-foundation`.
- Pre-existing untracked nested `AnyInfer/` tree was preserved during reset, then removed
  at the user's explicit cleanup request below.
- Stale native `group_foundation_plans` agent was already interrupted; stop was reissued.
  Traycer's task inventory showed no other live child at the initial audit.

## Upstream integration audit

GitHub initially returned 10 open PRs and no open issues. Two read-only reviewers own
pricing/catalog/contracts and dependency-workflow review respectively. Source relocation
discovery is separate. `develop` requires `ci-ok` with strict up-to-date checks; its
administrative bypass is not used.

| PR | Initial purpose/status |
|---|---|
| #38 | Contract drift audit 2026-09-28; CI successful. |
| #41 | Pricing refresh 2026-10-05; no CI checks present. |
| #42 | Contract drift audit 2026-10-05; CI successful. |
| #44 | Pricing refresh 2026-10-12; no CI checks present. |
| #45 | Catalog refresh 2026-10-12; CI successful. |
| #46 | Contract drift audit 2026-10-12; CI successful. |
| #47 | Upload-artifact 7.0.2; CI successful. |
| #48 | Download-artifact 8.0.2; CI successful. |
| #49 | setup-uv 10.3.0; CI successful. |
| #50 | claude-code-action 1.0.248; CI successful. |

The planned integration path is one reviewed combined PR for relevant updates, followed by
the required local/GitHub gates. Original PRs are not closed or represented as merged until
their reviewed content has actually landed or an explicit superseding disposition is recorded.

### Reviewed integration set

The integration branch is `feature/upstream-refresh-integration`, based on `13b9e65`.
The coordinator applied the reviewed changes without committing, in this order:
`#45`, `#44`, `#46`, then `#47`–`#50`. Older snapshots `#38`/`#42` are superseded by `#46`;
`#41` is superseded by `#44`. The latest Voyage contract correctly distinguishes documented
4XX error bodies from undocumented 5XX bodies.

The pricing PR's failed manual CI run `38266602084` exposed stale frozen source fixtures,
not an action-version failure. Its four changed model rows and the Avian parser expectation
were reconciled with the reviewed prices. The pricing drift module passed all 24 tests.
The Jina follow-up adds verified text-capable v5 embedding IDs and reranker v3.5 to operation
capability maps. Its shared query/document context window is deliberately not asserted as a
per-document limit. The focused Jina module passed all 11 tests.

Both narrow modules initially completed their assertions but encountered access denial writing
the pre-existing `.pytest_cache/v/cache`. Isolated cache paths (or cache-plugin disablement)
avoid that local filesystem fault without skipping tests. The full integration gate uses
`PYTEST_ADDOPTS=-o cache_dir=.tmp-tests/upstream-integration-cache`.

M1.2/M1.2U authoring proceeded in parallel in four new, unstaged files. Its independent review
is pending. Those files are not included in the upstream integration commit.

The first complete `workspace check` finished with all runtime, conformance, sidecar,
documentation and architecture checks passing, but failed `types` and `changelog`.
On Windows, the `os.pread` feature branch was inferred as `Any`; a typed optional callable
preserves the existing native/fallback behavior. Git's UTF-8 changelog output was decoded with
the process locale, obscuring em-dash release headings; explicit UTF-8 decoding fixes the
immutability check. These baseline portability fixes are included in the integration rather
than bypassing either gate.

The second complete gate passed all 12 steps (78.5 seconds). Reviewed integration commit:
`b166241e94706b639587fe43c6bfb31903e09eae`; GitHub integration PR: #51. The foundation branch
fast-forwarded to that tested commit while the required GitHub matrix runs.

PR #51 then passed the Linux 3.11/3.14 and Windows 3.14 matrix plus the required `ci-ok`.
It merged on 2026-10-15 at `955054fd90d86cb1eb1a3cb3f4a0ebfd7171164d`. The repository's rules
require a squash merge; the merge-commit attempt was refused and the protected squash merge
succeeded without bypass. After verifying identical source-tree hashes, a soft baseline update
adopted that upstream commit while preserving all relocation edits. Original PRs #44–#50
were closed as integrated; #38/#41/#42 were closed as superseded. GitHub returned no open PRs
after this reconciliation, and the issues inventory was empty.

## M0.1 relocation authoring

The coordinator verified resolved absolute source/destination paths, moved all five package
roots once, and verified 249 tracked files byte-for-byte. The pre-edit SHA-256 mapping is
`C:/Users/antho/.traycer/epics/a4822703-eee2-44cb-960c-47b3ae3d4c73/scratch/python-relocation-before.json`.
The independent workstreams own tooling/workflows, current documentation, and source/test path
references. Shared plan checkboxes and Git state remain coordinator-owned. Phase acceptance
waits for upstream protected integration, provenance checks and the complete gate.

M1.1's execution audit corrected an internal assumption before implementation: Python's native
stream has no background producer task. Operation state remains generator-local, while
ContextVar tokens are confined to synchronous helper calls so consumer tasks cannot inherit a
leaked capture context. The master records the companion generation hooks and isolation tests.

M0.1 acceptance: all 12 `workspace check --fail-fast` steps passed in 96.0 seconds with an
isolated pytest cache; all five actual package imports resolve beneath `src/python/`.
There are exactly 249 new mapped source files and no missing/extra files. The five modified
package files (three shard READMEs, pricing URL prose, demo help links) equal their old source
with path substitutions only; the remaining 244 are byte-identical. Independent review found
four doubled inner-shard paths in legacy plan anchors; those were corrected and all 309
Markdown files' relative links rechecked. The source relocation has no open material finding.

M1.2/M1.2U acceptance: the shared profile, vocabulary, maintenance contract and Markdown
checker passed independent review after the recorded promotion/maintenance fixes. The exact
link gate passes across 23 specification/plan files; undefined reference, missing-target and
missing-fragment negatives fail. Normative bodies have no undefined private plan labels or
Python implementation symbols. The first unchecked master box is M1.1.

## Environment

- Python: CPython 3.13.15; initial import resolved to `D:/projects/AnyInfer/src/anyinfer/`.
- Installed .NET SDKs: 6.0.428, 8.0.425, 10.0.401. The C# proof targets `net8.0`.
- `gh`, Git, `dotnet`, and `uv` are available; `rg` is absent, so discovery uses `git grep`.
- Full/heavy checks run serially. M0 and the independently authored M1.2/M1.2U gates passed.

## Handoff after shared-contract authoring (`9ad4bdd`)

- Plan-overlay commit: `2399c6f`; completed relocation commit: `baf06e1`.
- First unchecked box: M1.1. Its private records/helpers and generator integration are split
  between disjoint owners; the initial incomplete slice was not accepted. Unit proofs and
  native integration proofs must both pass independent review and the combined repository gate.
- M1.3 schemas/validator/CI wiring are authored and under independent review. Empty authoring
  validation is developmental; no corpus, reference run, release identity or C# proof is claimed.
- §14 closes the already-required image-boundary input representation with an extension-only
  typed parts form. §16 requires native extension outcomes/actual entries and passing driver
  recipe observations; missing evidence becomes an error, with honest unavailable evidence
  permitted on errored/failed cases. Independent review found these clarifications consistent
  with the settled bounded profile.
- The native corpus and C# implementation remain future boxes. No package has been published.

### M1.1 / M1.3 cold-review correction history

M1.1 review found an absent preparation could still leave a correction assessment reference.
The helper now returns whether evidence was retained; the generation owner makes that linkage
conditional while preserving the actual correction role and native repair result. Additional
proofs distinguish assessment-count limits from byte limits and assert selected occurrence
order, exact native feedback, preparation and wire causality, cancellation and cross-task
consumer-context isolation. Review and the combined gate remain pending.

M1.3 review found transport inputs were not exclusive, Base64 encoding was only annotated,
custom-root coverage could consult the checkout, and extension-entry ordinals needed semantic
validation. The coordinator also found no positive core-outcome test: the schema's property
closure rejected all legal outcomes. Those corrections are assigned before fixture authoring.
The original ±2^63 value-model wording is inclusive at both endpoints; the shared text now
spells those endpoints explicitly and repairs two corrupted ± glyphs. No Python domain or
retry/repair semantics are changed by that asset-codec correction.

Independent M1.1 re-review is clean after the linkage and proof corrections. The first
combined gate passed lint, types, import/contract checks, asset validation and changelog,
then failed the test phase: the new script test imported `scripts` only under
`python -m pytest`, while the real gate invokes `pytest.exe` in workers; and DESIGN §18
omitted the new private `_capture.py` module. Both are assigned for narrow corrections.
Gate shell: `08fc4b48-514b-42ce-a9d2-8bccc6ba4070` (exit 1). No milestone is checked from this run.

Coordinator fault injection then found two argument-construction paths outside the capture
guard: extraction and invalid-schema evidence could throw from the validation module's
imported `_freeze` binding. Both are now assigned narrow observation-only guards and exact
native-return parity tests. A prior clean review did not establish that proof.

The M1.3 second review also requires declared fixture path/ID/family agreement, closed
sampling and script variants, and positional repair/schema placeholders. Positive cases
exposed nullable mechanism and extraction/schema-error path representation gaps; those
are corrected before corpus authoring. The shared fixture protocol now explicitly names
its script event/action variants. All remain acceptance work for the existing boxes.

The fault-boundary audit found one further unguarded entry-sink append before adapter
invocation. The helper now contains that controlled failure, and an actual SDK integration
test proves the request still enters the adapter and returns its valid native result while
capture is marked unavailable. Extraction and late-schema projection faults now target the
actual imported binding. The final M1.1 review and repository gate remain required.

### M1.1 / M1.3 acceptance

Final independent M1.1 fault-boundary review has no open finding. The coordinator reran the
exact four-file capture/schema gate successfully (91 tests). M1.3 review has no correctness
blocker; its final test-only additions directly reject declared-path substitution and family
drift, and the exact `pytest.exe -n 2 tests/test_portable_assets.py` gate passes all 12 tests.

The second combined `workspace check --fail-fast` run passed all 13 steps in 76.6 seconds,
including the complete test suite, architecture/provider conformance, fixtures, executable
documentation and strict site build. Shell `08fc4b48-514b-42ce-a9d2-8bccc6ba4070` retains
both runs; the second exits 0. Two final test-only identity negatives were verified by the
incremental 12-test asset run after that full run. Shared Markdown links pass across 23 files.
All four schema files have explicit UTF-8/no-BOM/LF byte checks. No public Python API,
retry/repair, usage, ledger or manifest behavior changed.

The master now checks M1.1/M1.3. Resume at M1.4: author the named data-only core fixture
families and full requirement inventory, keeping unobserved expectations explicitly pending.
No corpus release, qualified report, reference environment or native C# proof exists yet.

### M1.4 authoring handoff (`90c2605`)

Accepted private capture and asset gates are committed at
`90c26057b8b96b7b064f37f6356fe2022c27d564`. Three disjoint data-only authoring briefs own:

- normalization and repair fixtures;
- schema-admission, extraction and validation fixtures;
- routing, streaming and lifecycle fixtures plus the single complete inventory.

The coordinator will run the development family coverage gate and independent review after
all owners finish. Transport fixture paths and driver assertions appear as future obligations
in the inventory, while transport data/execution remain M1.6. Pending expectations carry no
native-equivalence claim. Resume from this unchecked box and commit if context is lost.

### M1.4 authoring review

The core tree contains 85 pending fixture files. The complete inventory lists 96 fixture
obligations (including 11 transport inputs still owned by M1.6) and six native driver
assertions; these are authoring counts, not execution or conformance counts. The staged core
coverage gate passes. Full coverage correctly fails on the 11 missing transport files only.

Cold review corrected the admission case to exercise the entire admitted subset, and a fresh
owner corrected all 25 routing/streaming/lifecycle files after generic success scripts had
failed to enter their named paths. The corrected scenarios pass re-review. Case mappings are
now individual behavior records plus crosscutting prompt/result/value obligations, with real
normative fragments. Reference validation rejects missing targets/fragments and escape paths
outside the selected specification tree. Script failures use closed native adapter categories;
core outcomes cannot be injected to fake a passing case.

Shared §17 now explicitly requires a fresh buffered mirror for the buffered/streamed case,
and a native member-order observation for the interleaved `z,a,z` duplicate-key case. General
JSON Schema value equality remains unchanged. Full-subset, ordering and reference-boundary
re-reviews are clean. Final canonical case-kind/recipe checks are in progress to prevent
substituting a different driver predicate while retaining a mandatory case ID.

The M1.4 full repository gate is running in shell `f0f8247e-04e1-487c-82e7-0de264c4cc7c`.
The master box remains unchecked until that run and the final incremental negative tests pass.

### M1.4 acceptance and next resume point

The full gate passed all 13 steps in 79.5 seconds (shell above, exit 0). The staged core
coverage command exits 0; full coverage exits 1 with exactly the 11 not-yet-authored transport
files. Final incremental asset tests pass all 15 cases, including canonical driver recipe and
case-kind substitutions; independent review found no open material finding. Shared Markdown
links pass across 23 files. All 85 core expectations remain `to_be_observed`.

Resume at M1.5a. It splits replay adapter/gates, private time seam, and value/segment helpers
into disjoint ownership before a second wave wires the native runner/projection. M1.5b and
M1.5c complete native predicates and fail-closed report/reference tooling. These subdivisions
make the existing box executable; they add no SDK scope or conformance claim.

### M1.5a handoff

M1.4 is committed at `55442cfdbbd5b86fd8de927ce2a7f758e41ba5b3`. The coordinator created
the private portable package initializer before parallel work began. Current disjoint owners
are replay adapter/gates with native adapter tests; the private client time seam with its
independent tests; and a mechanical fixture model-shape correction plus schema/negative tests.
The correction preserves the three false capability flags and nests them under `capabilities`
as §14's existing example specifies. This unreleased encoding mismatch was found while
settling the replay interface and is closed before native fixture execution. Value/segment
helpers follow as the remaining M1.5a slice. No M1.5 sub-box is accepted yet.

### M1.5a numeric-control decision and review

Actual native execution observed timeout `None` becoming wire `120.0`, explicit `17`
remaining an integer, and explicit `17.0` remaining a float. On 2026-10-15 the user selected
numeric comparison for declared control fields. Shared §13 and master A9 now scope that
rule to timeout, Retry-After, route backoff/health duration, and continuous sampling controls
at their typed positions, including wire/HTTP projections. It does not coerce requests,
relax generic observation equality, round exact integers, or change Python runtime behavior.

Cold review cleared the private time seam and fixture model wrapper. Adapter review found
an unbounded readiness wait; the corrected wait uses the same watchdog and harness-error
classification as release waits. Independent closure review and its 12-test gate are clean.
Value helpers remain under independent review; the joint sub-box stays unchecked until the
combined gate passes.

### M1.5a accepted

Value-helper review found that a bare string could masquerade as a sequence of native
messages. The helper now rejects scalar/non-sequence evidence and preserves actual tuple
order and multiplicity. The five-test helper gate and independent closure review are clean.
The combined pre-fix targeted gate passed 96 tests; the final repository gate includes the
added feedback tests and passed all 13 steps in 71.7 seconds, exit 0 (shell
`313448c6-6cf5-4574-901a-495f334cc810`). Shared Markdown links pass across 23 files.
An independent data check confirms all 85 core fixture edits only wrap their existing model
flags under `capabilities`.

Resume at M1.5b: build raw records/projection, native execution, and comparison in disjoint
files before adding driver recipes and pytest development output. The parent M1.5 box is
unchecked; neither pending expectations nor passing substrate tests establish conformance.

### M1.5b first-wave handoff

Accepted M1.5a commit: `3dffc424676dc405bb61c614b9275d011828c934`. Three disjoint
implementation briefs are active: `records.py`, `projection.py`, `test_projection.py`;
`runner.py`, `test_runner.py`; and `comparison.py`, `test_comparison.py`, all beneath
`tests/testing/portable/`. The frozen `NativeRun` record carries actual native events,
result/exception and failure stage, telemetry, capture records, adapter wires, clock advances,
cleanup facts and an optional independent buffered mirror. Projection never recomputes
validation; execution never reads expected outcomes; comparison expands only typed expected
segments against actual causal evidence. Pending expectations cannot receive a pass verdict.

All three owners report back before acceptance or the next implementation wave. Timer and
other mandatory driver recipes, pytest development output, and M1.5c qualification tooling
are still outstanding. Resume with their implementation reports and independent cold review;
the master M1.5b and parent M1.5 boxes remain unchecked.

### M1.5b first-wave review — not accepted

The initial runner executes all 85 authored core inputs, but that run does not yet prove
the intended cancellation threshold or complete observation fidelity. Its review is active.
The initial six-test projection slice was rejected by independent review for four P1 gaps:
malformed extension evidence; incomplete actual-wire/correction-source verification;
unmapped construction/configuration failures; and JSON key coercion/domain bypass. The
11-test comparison slice is separately under review. No M1.5b acceptance gate has passed.

Corrections retain the agreed APIs and shared contract. `NativeRun` gains three additive
raw facts at the end of the dataclass: actual `input_messages`, original `input_schema`, and
`construction_origin` set only around the native sampling constructor. This permits causal
and typed-origin checks without parsing error prose or recomputing native validation.
Request-construction errors keep a null phase as shared §12 requires; only target and
configuration failures use `configure`. The coordinator corrected an earlier brief that
had misstated construction phase, without amending the contract or Python behavior.

Runner review also rejected the initial cancellation path: it ignored the declared event
threshold and suppressed the cancellation outcome. Script/harness faults were mislabeled as
operation errors, making the 85-case smoke assertion vacuous. Comparison review rejected a
non-normative `same_as_call` encoding, subset-only result comparison, and a mirror predicate
that could accept copied streamed evidence. Those corrections are assigned to their owners.
The raw record now also retains actual `consumption_mode`; mirror comparison requires a
buffered mode plus distinct native operation identities/objects and matching case binding.
The first projection revision is under re-review; its new raw-input fields do not alone
establish template/prefix verification. All M1.5b checkboxes remain open.

### M1.5b recovery ownership

Projection re-review kept open template/original-prefix verification, type-aware actual-wire
checks, redacted error evidence and complete ordinary-JSON output validation. The coordinator
transferred `projection.py`/`test_projection.py` to a fresh native implementer
`projection_repair`; the prior owner is held. The runner's two requested parent-cancellation/
watchdog cleanup tests were still not delivered after repeated handoffs, so `runner.py`/
`test_runner.py` transfer to fresh native implementer `runner_lifecycle_repair`; its prior
owner is held too. The latter may extend only the existing `construction_origin` Literal in
`records.py` with actual native messages/repair/route constructor tags. All other record fields
and agreed projection APIs remain stable. Known native construction failures retain null
phase; driver codec/setup failures are harness faults.

Comparison's same-as encoding and complete result shape passed closure review. Its owner
adds disjoint native operation-ID verification alongside object identity so a copied stream
capture cannot masquerade as a fresh buffered mirror. These are private proof corrections,
without production or specification changes. Resume at the still-unchecked M1.5b from
`3dffc424676dc405bb61c614b9275d011828c934`, with the current working changes preserved.

Comparison closure is now independently clean. The verifier confirmed normative reference
encoding, complete result comparison, and fresh-mirror checks using distinct capture objects
and disjoint valid native operation IDs; its targeted module passes all 12 tests. The review
artifact is `foundation-execution/comparison-review` in the task artifact tree. This accepts
the comparator correction only. Projection and runner lifecycle corrections, their independent
reviews, mandatory driver recipes, development-output integration and the joint M1.5b gate
remain outstanding.

### User-authorized nested-directory cleanup

The user explicitly requested removing the nested `AnyInfer/` copy on 2026-10-15.
The coordinator verified its resolved absolute path was exactly
`D:/projects/AnyInfer/AnyInfer`, beneath the intended workspace and not a reparse point,
then removed only that directory with native PowerShell. The path no longer exists and
Git status no longer lists it. The earlier reset and preservation statements describe the
reset-time precaution; no foundation source or tracked work was reset during this cleanup.

Projection's fresh-implementation review found two further P1s before acceptance: extension
capture must validate original/correction roles even when portable mechanism projection is
unavailable, and a terminal schema assessment must belong to the final actual entered wire.
The owner is correcting both with real-capture mutation tests; the prior nine-test green
result does not close these proof obligations. Runner lifecycle review is still independent
and active. No M1.5b checkbox or unreviewed driver source is committed as complete.

Runner review otherwise cleared lifecycle/native execution and identified one remaining
fixture-sweep assertion gap: nonempty adapter requests must require exactly one available
operation capture, rather than accepting an empty list through `all(...)`. Its owner fixes
that test. A separate `test_execution.py` owner now composes actual execution, projection and
comparison across all 85 core fixtures, with honest declared extensions and no pass verdict
for pending expectations. Cross-layer failures are reported for correction before any joint
gate; they cannot be skipped or weakened into pending success.

### Serialized verification recovery

Final projection code inspection closed the unknown-role and stale-terminal-assessment P1s;
the reviewer's independent test attempt did not finish and is explicitly unconfirmed. The
runner smoke predicate is corrected, with its final test retry also unconfirmed after lost
tool handles. The integration test exists but its first run likewise has no captured exit.
No unconfirmed command is recorded as a pass.

Process inspection found stale pytest invocations from this task's earlier runs. The
coordinator removed 122 verified workspace-owned stale roots and their descendants (248
processes total), checking executable/command ownership, parent absence or PID reuse, task
timestamps and live process start times. One earlier task-cache invocation with a stale live
parent was identified separately. Audit manifests are in task scratch as
`pytest-orphan-cleanup-20261015.json` and `pytest-orphan-cleanup-20261015-final.json`.
Unrelated processes were excluded.

One tracked serialized gate now runs in shell `a6e4a58d-a01f-473e-93fd-870770be3179`:
`pytest.exe -q -n 0 -o cache_dir=.tmp-tests/portable-joined-serial tests/testing/portable`.
All workers are held from additional test launches. This run supplies the missing joint
execution/projection/comparison evidence; its result is pending.

The tracked serial gate completed with exit 1 and exactly two failing integration cases:
`schema-admission/unsupported-boolean-subschema` and
`schema-admission/unsupported-dialect-null`. The comparator attempted mandatory portable-error
projection before its declared-extension branch, rejecting the native `TypeError` and actual
warnings-as-errors `DeprecationWarning`. Their honest native extension evidence is allowed by
the settled contract. The comparator owner corrects dispatch order without bypassing capture
integrity, changing warning policy, weakening the integration test or editing Python behavior.
Runner's final code review is clean; the joined run reported no runner/projection unit failure.
The whole portable gate remains failed until its tracked rerun passes.

The next tracked run passed all 85 real core integrations and 228 tests overall, with one
stale unit-test mock failure: its `validate_capture` double omitted the newly exercised
`allow_unprojectable` keyword. Independent review also found that early extension dispatch
needed an explicit cancellation/fatal-BaseException guard. Both are assigned to the comparator
owner; no fixture, warning policy or production behavior changes. The 229-test run is still
failed, not a gate pass, until the correction is verified in the serialized rerun.

The final portable rerun passed **234 tests in 6.31 seconds**, exit 0, with all 85 real
fixture integrations. Independent comparator code review closed the cancellation/fatal guard;
projection and runner closure reviews are also clear. The full repository gate is now running
in shell `a4c48aa8-dc1d-4922-957d-30621139f3d7`, with an isolated pytest cache and the
installed xdist plugin's supported `PYTEST_XDIST_AUTO_NUM_WORKERS=2` cap. This limits
parallelism only; no gate or test is excluded.

M1.5b is subdivided into the native execution checkpoint, five core native driver recipes,
and pytest development-output integration. These subdivisions make the existing obligations
explicit; reference qualification remains M1.5c/M1.7/M1.G and HTTP proof remains M1.6.
No native recipe or development-output file is authored until its checkpoint prerequisite
passes. The full-gate result and checkpoint commit remain pending.

### M1.5b.1 execution checkpoint accepted

The tracked full gate passed all 13 steps in **560.5 seconds**, exit 0 (shell
`a4c48aa8-dc1d-4922-957d-30621139f3d7`). It used the supported xdist two-worker cap and
an isolated cache without excluding any test. The separate combined portable gate passed
**234 tests**, including every one of the 85 current core fixtures through actual native
execution, projection and comparison. Projection, comparator and runner reviews are clean.

The checkpoint includes raw typed facts, lossless capture/projection linkage, native
fixture execution/cancellation/lifecycle, strict scoped comparison and honest declared
extension evidence. No fixture expectation or production runtime changed in this wave.
Pending expectations remain pending, and no reference manifest, frozen release or qualified
conformance report is claimed. M1.5b remains open for core driver predicates and development
output; M1.5c and later gates remain untouched.

### M1.5b.2 and M1.5b.3 execution history

The native execution checkpoint is committed at
`1275e889f576bbaab7492c24ff691ab3722ca3ef`. Three disjoint Terra-medium owners are now
authoring the existing next obligations:

- Core concurrency/assessment recipes and `proofs.py` dispatcher: agent
  `04f0bc20-ef3f-4048-9249-961fffa69ee4`, owning `proofs.py`/`test_proofs.py`.
- Real native timer/context recipes: agent `cab6145b-7c79-48e5-a321-0dbc60795f0e`,
  owning `proof_timeouts.py`/`test_proof_timeouts.py`.
- Explicitly unreleased observation driver/pytest integration: agent
  `1e09179c-3413-4551-b0e4-65cb177a5654`, owning `driver.py`/`conftest.py`/`test_driver.py`.

All paths are beneath `tests/testing/portable/`. The dispatcher contract is the five exact
core recipe IDs and `await run_core_driver_assertion(recipe_ref)` returning actual native
evidence only after its predicate. The timeout module returns native facts through
`await observe_timeout_recipe(recipe_ref)`. Development output binds selected draft inputs,
keeps pending/extension outcomes honest and names unexecuted inventory IDs. Reference writing
still fails closed until the later clean-reference preflight.

Workers run lightweight lint/types but request a coordinator test slot before launching
pytest. One tracked targeted gate runs at a time; no repeated detached 30-second invocations.
The coordinator owns shared plan acceptance. No native recipe, development-output or parent
M1.5b checkbox is accepted yet; await these owners' implementation reports, then verify them.

Concurrency/assessment recipes and the development driver are code-ready with Ruff passing;
their independent read-only reviews are active. Their cross-module type checks and targeted
tests await the timeout helper. The driver owner corrects its own canonical shared-exception
import rather than changing a peer's export. No placeholder timeout module or unconfirmed
test result is accepted, and no worker pytest slot has been granted yet.

All three next-wave modules are now code-ready. The timeout owner passed compile/Ruff;
its PATH did not expose mypy, so the coordinator will use `.venv/Scripts/mypy.exe`.
Core-proof review found one P1 before testing: merely retaining a list of assessment kinds
did not prove the required extraction/late-invalid-schema kinds and actual selected native
occurrences. The owner adds structural predicates and controlled mutation negatives before
the tracked combined slot. Native timer and development-driver reviews proceed independently;
all pytest launches remain held until these static corrections are ready.

Timeout review identified a separate P1: final entered/exited flags could not prove disposal
before the next native entry. Its owner records ordered native enter/exit facts and asserts
each prior exit precedes the next entry, with out-of-order/missing-disposal negative controls.
This adds evidence only, without replacing native timers or comparing elapsed thresholds.

Development-driver review found that requiring all declared transport files at this stage
would block the native core observation before M1.6 authors those files. Development preflight
therefore requires every executable core and normative input, explicitly records missing future
transport files as unexecuted with their inventory identities, and validates/hashes any selected
transport files already present. It never falls back to checkout inputs. Complete reference and
release gates still require every transport file. The driver owner also reconciles the agreed
driver evidence envelope and tests the actual executable import boundary before acceptance.

Core-assessment structural review closed its first finding, then caught a native-message prefix
comparison that would parse rendered prose. The owner removes that comparison and keeps typed
metadata and captured native feedback as independent facts from the same actual assessment.
Timeout ordered-disposal corrections are ready for independent closure. No new test pass or
checkbox is claimed until the tracked combined proof/driver gate executes.

The first tracked combined proof/development-driver gate exited 1: **4 failed, 17 passed**
(shell `282788d4-6928-453f-97b0-742a66be64dd`). Development-driver tests passed. The native
proof failures exposed an extraction-predicate mismatch, a test monkeypatch importing the
non-package `tests` namespace, and two timeout predicates reading a nonexistent `category`
from the actual typed `ErrorInfo` attempt snapshot. Owners correct those private proof
assumptions using native captured facts and structured snapshot fields; production Python,
fixture expectations and retry/repair behavior stay unchanged. Combined explicit mypy and
portable Ruff passed before this run, but they did not establish native proof acceptance.

The second tracked targeted run exited 1: **1 failed, 21 passed**. Native timeout and
cancellation proofs now pass; assessment completeness exposed a genuine draft fixture error:
`repair/exhaustion-two-invalid` and `repair/invalid-then-valid` require `age` but do not
constrain its type, so their scripted string ages are valid and never enter correction.
Python's result is correct. This is early M1.7-style input reconciliation, not an SDK defect
or a reason to weaken the proof. Agent `c16f5f94-b124-40f4-9deb-8121afdbc093` owns a bounded
audit/correction of all eight repair JSON inputs, preserving pending expectations and LF bytes,
with actual native per-case observations. The proof owner holds semantic predicates until
those inputs are stable. No new milestone is accepted yet.

The repair-family correction adds only `properties.age.type: integer` to each of the eight
schemas; scripts, controls and pending expectations are unchanged. Independent review confirms
the intended branch inputs. The core-proof owner's single authorized tracked run passed
**4 tests**, exit 0 (shell `a62abbc9-d8f0-45ce-9d1a-5d0eaa91bd24`); the coordinator inspected
its retained log. Final core/timer and development-driver code reviews are clear.

The coordinator is now exercising the actual pytest `--portable-report` path in shell
`0d91864b-619f-4491-b0ad-bb27b961c7a2`, including fresh execution of all core observations
and five native driver recipes. Its output remains explicitly UNRELEASED, with transport
obligations unexecuted. Full repository acceptance and the next checkpoint commit remain
pending; no checkbox is changed yet.

The actual pytest development-output command passed **10 timeout-proof tests**, exit 0.
The coordinator parsed its output: 90 executed records comprise 85 core fixtures (76 pending,
9 declared extensions) and 5 passing core driver recipes; all 12 transport obligations are
explicitly unexecuted. No executed record is fail/error. The output remains UNRELEASED and
ineligible for `report-v0`. The full repository gate is running in tracked shell
`51f9db42-1d1f-45c3-8ce5-78e62bc93646` with the existing two-worker cap and isolated cache.

Read-only preparation for M1.5c identified implicit checkout schema/normative globals in the
existing validator and duplicated selected-root checks in the private driver. The next wave
first makes those validation inputs explicit and creates one shared data-only release-binding
helper; comparison and reference consumers follow its accepted API. No source code from a
selected corpus directory is executed. This is upcoming work, not a current-gate acceptance.

The first full repository gate stopped at its test phase with one stale runner-test assertion:
`test_runner_records_supplied_wire_controls_and_repair_drop_telemetry` expected only
`ParameterDropped`. The corrected ceiling fixture now genuinely repairs and correctly also
emits `RepairAttempted`. Lint, types, both contract steps, fixtures and changelog passed;
the test phase failed, so this is not a full-gate pass. The test owner updates the exact typed
telemetry assertions and removes its now-redundant local schema workaround, then runs the
single affected node in its granted tracked slot. A complete repository rerun remains required.

The single affected telemetry test and Ruff passed (tracked owner shell
`4f6010e0-4ce5-47b8-990f-4aa112904535`); the coordinator inspected the diff and log.
It asserts exact ordered typed drop/repair events and their parameter/attempt fields using
the corrected canonical fixture. The full gate rerun uses the same root shell with cache
`.tmp-tests/m15b-native-proof-checkpoint-final`; its result is pending.

An additional optional strict-mypy sweep of the entire private test subtree found 32 test-only
annotation/negative-input diagnostics in five pre-existing test modules. No runtime driver
module was diagnosed; this sweep is broader than the project's configured source-only gate.
The seven new proof/driver modules pass explicit strict mypy. Do not describe the optional
whole-test sweep as passing or change runtime behavior to satisfy test-annotation assumptions.

### M1.5b.2 and M1.5b.3 accepted

The final full repository gate passed **all 13 steps in 274.5 seconds**, exit 0, in root
shell `51f9db42-1d1f-45c3-8ce5-78e62bc93646`. The coordinator inspected the retained
summary. Core/timer, development-driver, repair-input and telemetry-test reviews are clean.
The existing source-only mypy gate passes; the seven new modules also pass explicit mypy.
Actual CLI observation retains 85 core cases, five passing native driver predicates and
12 unexecuted transport obligations without manufacturing a qualified report.

The accepted checkpoint includes seven private proof/driver files, the corrected eight
repair schemas, the exact telemetry-test correction and plan evidence. It changes no
production Python behavior or pending fixture expectations. Parent M1.5/M1.5b remain open
for reference/report support; HTTP, reference production, corpus freeze and C# remain later
gates.

### Current resume point: M1.5c.1

The reviewed checkpoint is committed at `ece93723c7e9558e1d680caa80a80d5b276002ac`;
the coordinator verified a clean working tree and the relocated Python import. Execute
the first unchecked M1.5c.1 box. Start with
explicit selected-root validation and one shared data-only release/report binding helper;
comparison/reference consumers depend on its accepted API. No owner is authorized to alter
Python retry/repair or implement aggregate accounting. The coordinator owns shared plan
acceptance and serializes tracked test slots.

The first M1.5c.1 slice is assigned to agent `c16f5f94-b124-40f4-9deb-8121afdbc093`,
owning only `scripts/validate_fixtures.py` and `tests/test_portable_assets.py`. It adds explicit
selected specification-root parameters to validation/report APIs while preserving defaults,
and a shared strict `read_json` entry point. Its one tracked asset-test slot is authorized.
Agent `04f0bc20-ef3f-4048-9249-961fffa69ee4` prepares the release-binding API read-only;
agent `1e09179c-3413-4551-b0e4-65cb177a5654` independently prepares reference/environment
preflight facts read-only. No common helper, comparison script or reference writer is
implemented until the coordinator settles those interfaces. No reference/release artifact
or C# parity claim exists yet.

Reference preparation settled implementation details before writer authoring: enumerate the
complete installed distribution lock with exact versions and metadata/RECORD provenance,
bind actual loaded runtime code and deterministic JSON content hashes of selected registry
resources, and scope an exact strict warning filter only to reference execution (restore
ambient filters afterward). No credential-bearing direct URL contents are exported. A/B
reproduction imports clean executable A; B supplies frozen data only. Exact generated output
exceptions never exempt arbitrary dirty source or overwrite sealed inputs.

Release-helper proposal review corrected two compatibility traps: matching eligible extension
verdicts remain allowed, and equal source/driver revisions across monorepo implementations are
legitimate. Frozen release verification must validate its closed listed input set without
globbing unrelated later fixtures. The validator owner therefore adds an optional explicit
`fixture_paths` selection through the same checks; ordinary authoring validation retains its
whole-tree missing/extra behavior.

The initial selected-root API test run reported 15 pass/2 fail because temporary explicit
roots lacked their own schemas. The owner corrected those test inputs honestly and is adding
explicit-list isolation/negative tests before its next single tracked slot. No common helper,
qualified comparison, reference artifact or M1.5c checkbox is accepted yet.

The coordinator's tracked selected-validation gate passed **19 tests**, exit 0 (shell
`2266a811-3809-46a9-8001-ea2518588d90`). Cold review nevertheless found explicit-root
inventory fallback for a distinct fixture tree, acceptance of intermediate symlink-directory
components, and inconsistent missing-root diagnostics. The validator owner closes these
with targeted regressions before the API is accepted or used by the release helper. The
passing first module run does not close those findings.

Selected validation is now accepted as the helper's input API: all three review findings
are closed; the owner's tracked 22-test asset-module run exited 0 in shell
`d73f53d0-6892-47f1-b502-f5d82a5a376b`, whose log the coordinator inspected. The coordinator
also reran validator mypy and both-file Ruff successfully. Defaults remain compatible;
explicit roots bind schemas/inventory/normative refs, and explicit file lists reject links
and escapes without globbing future inputs. The overall M1.5c.1 box stays open for its helper.

Agent `04f0bc20-ef3f-4048-9249-961fffa69ee4` now owns only new
`scripts/portable_release_assets.py` and `tests/test_portable_release_assets.py`. Its agreed
API is `ReleaseBindingError`, frozen `ReleaseAssets`, `load_release_assets(root, release_path)`,
`validate_qualified_report(report_path, assets)` and `require_comparable_reports(left, right,
assets)`. It imports trusted source-checkout validation code only, verifies exact frozen
file/inventory/reference/environment identities and report qualification, and performs no writes.
The selected root remains data-only. Passing report rows never bypass full qualification.

The helper owner has one exclusive persistent-shell test slot with at most three serialized
owned-module runs; this replaces the inefficient one-failed-run handback pattern while still
preventing concurrent suites and lost exec handles. Other workers remain test-held. Tests
construct only temporary synthetic complete release trees; no actual M1.6 transport fixture,
reference, release or qualified native report is authored by this box. Compare/reference
consumers remain held until the helper API and private Python environment format are reviewed.

The first helper draft is **not accepted**, despite three synthetic tests passing. Root/cold
review found a direct-mapping qualification bypass, selected-root/manifest path gaps, numeric-key
objects accepted as normalized results, fatal/cancellation evidence gaps, shallow mutable
bindings, incomplete metadata checks and missing negative coverage. A broad six-code mypy
suppression invalidated its claimed strict type-check evidence and must be removed. The same
owner has one consolidated correction wave and exclusive tracked test slot; compare/reference
consumers remain held.

The coordinator refined one review finding: a complete installed-distribution lock is
intentionally a superset of required runtime packages, and its raw environment digest already
binds every extra row. For explicit producer consistency, manifest `packages` now projects
the entire installed lock's name/version set exactly. Metadata hash is required; RECORD and
direct-URL hash keys are explicit and nullable only for absent artifacts. Matching eligible
extensions and equal monorepo commits remain legal. A normalized extension result must contain
all ten named, typed fields; additional JSON fields remain allowed by the existing report
schema. This corrects helper validation, not Python runtime behavior or release scope.

The corrected helper passes coordinator-run Ruff and genuinely unsuppressed strict mypy.
Its last authorized targeted run reports 19 pass/1 skip/1 fail; the remaining failure exposes
the shared validator still reconstructing canonical normative refs through a directory named
`specification`. Agent `c16f5f94-b124-40f4-9deb-8121afdbc093` owns the precise mapping fix
and arbitrary-basename regression in its existing two files. No prose-filter, temp-tree,
symlink workaround or policy exception is authorized. The helper is stable under cold
re-review; compare/reference consumers and M1.5c.1 acceptance remain held.

The shared normative-ref mapping fix is ready with its tracked asset module reporting
23 pass, exit 0 (owner shell `a8b0b3ad-c26b-4963-b811-2808d15393be`); a separate read-only
closure checks that precise delta. Helper review closed its path, immutable-binding,
package-projection, unsuppressed-typing and shared-qualification fixes, then found two
remaining evidence issues: legal `none: true` extension outcomes were rejected, and result
subfields/direct mappings were not fully checked against the declared ordinary JSON domain.
The helper owner fixes both within its next exclusive tracked slot.

Hash closure also requires every inventory `spec_ref` target to belong to the verified
release file set. An unrelated unreferenced future file remains ignored; an actual normative
reference cannot silently point at unbound text. The correction includes that guard and a
temporary synthetic regression, without globbing later assets or changing v0 runtime behavior.

The owner’s final helper run reported **31 pass, 1 platform skip**, exit 0; the coordinator
inspected its retained log. A subsequent defensive type guard had only static validation,
so root launched the combined asset/helper modules against the final source in tracked shell
`911289c5-1415-43b3-9f98-b7226bf6a811`. Final cold review closed the result, none-outcome,
surrogate and normative-reference hash findings, but root/reviewer found one remaining domain
contradiction: direct report validation excludes `+2^63` while the settled v0 domain includes
both endpoints. Correct that bound and add direct-report endpoint regressions after this
stable-source run; a green run of the preceding source cannot establish final acceptance.

The combined stable-source gate passed **54 tests, 1 platform skip** in 105.23 seconds,
exit 0. The subsequent endpoint node passed after placing its control values in schema-valid
driver observations. A final bounded metadata review also requires present validator
selection/defaults and nonempty hashed resource identities, and ties both reference artifact
basenames to A's seven-character prefix. The helper owner closes those structural omissions
without treating JSON metadata as proof of native execution.

The three-function release-binding interface is stable while these final predicates are
corrected. Agent `c16f5f94-b124-40f4-9deb-8121afdbc093` may therefore author M1.5c.2 in
only new `scripts/compare_reports.py` and `tests/test_compare_reports.py`, with no shared
helper edits and no pytest launch until the exclusive slot is granted. This parallel authoring
does not accept M1.5c.1 or waive its pending review/test gate. Reference writing and all real
reference/release artifacts remain held.

Agent `1e09179c-3413-4551-b0e4-65cb177a5654` owns a disjoint first M1.5c.3 slice in new
`tests/testing/portable/reference.py` and `test_reference.py`: real clean-source/import/corpus
preflight, actual environment capture and scoped strict warnings. This slice performs no
output writes or driver/plugin integration. It may author against the stable binding API;
the writer is a later reviewed integration step. Tests remain serialized by root, and no
reference or parent checkbox is accepted on code readiness alone.

The initial writer-free reference slice is not proof-ready: its first tests covered only
warning scope, leaving the requested provenance and environment failure matrix unproved.
The owner acknowledged this and is expanding tests while closing lexical link, tracked-import
and selected-B binding checks. Independent review owns the same scope read-only. Existing
sealed B evidence cannot be an output destination; reproduction writes only the two exact
new generated filenames under executable A's `specification/reference/`, never over an
existing destination. This technical destination choice preserves the settled A/B contract.

The comparison CLI is code-ready with static checks reported; its independent review and
next exclusive tracked test slot remain pending. It imports trusted sibling binding code,
loads selected release assets once, and writes no files. Neither code readiness nor prior
helper tests accept the M1.5c parent.

### M1.5c.1 and M1.5c.2 accepted; resume M1.5c.3

The helper owner's metadata matrix ran **38 pass, 1 platform skip, 1 fail**, exposing URI
uniqueness being checked on URI/hash pairs. Its minimal URI-key correction passed the final
root identity/CLI gate: **25 tests passed in 97.48 seconds**, exit 0, shell
`a50b0825-5927-4835-8b7d-339bc89bf6f7`. Root inspected the retained summary. The earlier
combined asset/helper gate passed 54 tests with one platform skip; the endpoint correction
also has direct report-boundary proof. Independent release-binding and CLI reviews are clear.
Root reran Ruff over the six changed script/test files and unsuppressed strict mypy over
the five applicable script/new-test modules successfully.

M1.5c.1 and M1.5c.2 are checked. The parent and M1.5c.3 remain open for reviewed clean
reference preflight, actual environment capture, writer/plugin integration and their gates.
Nothing is committed yet; the full repository gate remains mandatory before the next commit.
No actual frozen release/reference artifact or conformance claim exists. Current source HEAD
remains `ece93723c7e9558e1d680caa80a80d5b276002ac`.

The first writer-free reference-module gate (shell
`c42bdc6f-21f2-4437-8ed1-b33bf60facc5`) exited 1. It showed two ordinary failures before
a test-only global `sys.modules` replacement removed `warnings` and broke pytest's own
failure reporting. No complete pass/fail tally or preflight acceptance is inferred from
that interrupted run. The owner replaces this with scoped module facts/patches, corrects
the noncallable validator stand-in and folds the remaining cold-review proof requirements.
It has one exclusive persistent slot with at most two serialized owned-module reruns;
all other pytest launches remain held. Production Python behavior and the corpus are unchanged.

Final preflight review retains two High findings for the correction wave: supplied roots
were resolved before lexical link checks, including a dangling final output link; capture
could record a swapped foreign private driver without a fresh tracked/contained check.
The owner must prove those actual rejection paths and the real dirty/pending/missing/import
helpers, in addition to repairing the synthetic harness. Orchestration mocks alone do not
establish this gate. Writer/plugin authoring remains held until the snapshot passes review
and its targeted tests. Read-only preparation of M1.6's existing transport interfaces may
proceed independently; no transport fixture or implementation is authorized in that prep.

A read-only local toolchain check found .NET SDK **8.0.425** and runtime **8.0.31**
installed, alongside other SDK/runtime versions. No installation or source change was needed.
This removes a local setup uncertainty for the settled `net8.0` proof; it is not M2
feasibility acceptance, which still depends on the frozen corpus and its named gates.

The corrected writer-free reference module passed **12 tests, 1 platform skip** in
23.07 seconds, exit 0 (owner shell `12436db1-7f3b-4cb0-977b-c56af666f248`); root inspected
the log. The Git wrapper now preserves raw porcelain, and validator evidence distinguishes
the actual instance format-checker default from the separately available class checker.
Agent `c7089bf7-a970-4b5f-960e-4bbdbe32dd26` owns only new
`test_reference_preflight.py` for independent direct helper/corpus/Git/link/import proofs;
the preflight owner holds its existing two files. Final closure and these proofs remain open.

Read-only transport preparation confirmed a separate unreleased schema contradiction:
closed transport `expected` omitted the profile's general `status` marker, so pending native
expectations could not be honestly represented. Corrective M1.5c.1a requires explicit
observed/pending status, pending-only expected objects and the existing complete observed
assertions. Agent `c16f5f94-b124-40f4-9deb-8121afdbc093` owns only that schema, its normative
example, asset tests and the synthetic transport builder/release negative in
`tests/test_portable_release_assets.py`. The previous helper owner has relinquished that test
file. No actual transport inputs or expectations are authored. The first unchecked box is
now M1.5c.1a; c.3 direct-proof authoring continues independently.

The c.1a affected modules are running in root shell
`20c4459f-ae94-4363-a903-e5493dac0525`. Markdown links passed across all 23 specification
and plan files. Cold review found no transport-status schema defect but requests direct
`core_http` observed/pending and both opposite-outcome negatives in addition to the adapter
branch. Those test-only additions wait for the fixed-source run to finish.

Final reference code review still found three fail-open paths despite the prior module pass:
capture omitted role-prefix checks on tracked imports, foreign private modules could be
classified from their path and skipped, and an intermediate ancestor of a supplied root
could be resolved before link inspection. The preflight owner corrects source; the independent
proof owner adds direct regressions plus a real trusted sibling-loader check. No writer
integration or c.3 acceptance proceeds on the earlier green snapshot.

M1.5c.1a is accepted: the two affected modules passed **64 tests, 1 platform skip** in
132.61 seconds, exit 0 (root shell `20c4459f-ae94-4363-a903-e5493dac0525`), and the final
status-branch node passed with clean review closure (owner shell
`4b366c92-97f5-4b7c-a2c6-06aa531c75ea`). Root inspected both retained logs. No real
transport fixture or expectation was authored.

The combined final reference modules ran **22 pass, 1 platform skip, 1 fail** in 29.35
seconds, exit 1 (root shell `048f86e8-7b7e-4685-baf6-f7728c99e737`). Every independent
direct rejection proof passed. The remaining capture-unit setup used a fake checkout root
while the actual private `portable` package was genuinely loaded elsewhere, so the improved
capture correctly refused it. The preflight owner fixes only that unit setup using actual
checkout provenance and a scoped temporary dependency probe; production guards stay intact.
The first unchecked box remains M1.5c.3, including its still-unimplemented writer integration.

The small capture-unit correction preserved actual checkout imports and introduced only a
scoped temporary `httpx._reference_capture_probe`. Its two-node run proved the byte change,
then failed on stale expected error wording for the correctly refused foreign import;
the assertion alone was corrected. Root is rerunning both reference modules plus the
symmetric tracked wrong-role driver proof in shell `62adbb0c-700b-40ce-b2c8-17e7d07764b0`.
The shared helper/builder are held during that fixed-source run.

M1.5c.3 is subdivided into writer-free proof, writer and driver integration gates. With the
preflight source API reviewed and stable, agent `04f0bc20-ef3f-4048-9249-961fffa69ee4`
owns only new `reference_writer.py`/`test_reference_writer.py` plus the narrow pure
reference-evidence extraction in `scripts/portable_release_assets.py` and its test file.
The helper test ownership returns from the completed transport-status owner. New writer
authoring may proceed independently; helper/builder edits wait until root's current reference
gate finishes. The callback is internal trusted native execution, never selected-root code
or a user plugin. Pre/post execution input binding and no-replace publication are required;
all real reference production remains gated to M1.7.

M1.5c.3a is accepted: the final combined native-fact/direct-proof gate passed **24 tests,
1 platform skip** in 33.86 seconds, exit 0 (root shell
`62adbb0c-700b-40ce-b2c8-17e7d07764b0`), and the bounded final review closed its symmetric
driver proof item without source weakening. Root inspected the retained result. The first
unchecked child is now M1.5c.3b; the enclosing reference/phase boxes remain open.

The first writer source is code-ready but **not proof-ready**: its assigned test file had
only import-level coverage. Root transferred only `test_reference_writer.py` to agent
`c7089bf7-a970-4b5f-960e-4bbdbe32dd26` for actual controlled-observer/publication tests;
agent `04f0bc20-ef3f-4048-9249-961fffa69ee4` holds the writer and shared validation source
pending consolidated cold review. Positives must use the actual development observation
shape, and publication faults must preserve preexisting outputs/staging files. No writer
pytest gate, actual artifact or parent acceptance is claimed from import/type checks.

Cold writer review found four P1s before testing: its count check did not match actual
development `Counter` output with `unexecuted: 0`; it omitted unexecuted and full native
extension evidence checks; fixed PID staging cleanup could delete a preexisting file and
did not bootstrap the absent output directory; and the extracted metadata validator could
accept direct nonordinary JSON. The source owner corrects these together, sharing case/evidence
policy with qualified-report validation and preserving typed counts (booleans never count
as integers). The independent test owner uses actual development shapes and controlled
native/publication failures. No writer gate or source acceptance is inferred yet.

Root source inspection did not substantiate the first owner's later "all four fixed"
report: the actual writer still lacked shared full case/evidence validation and missing
reference-directory bootstrap, and checked an invented `UNRELEASED: true` marker instead
of native `development_observation: "UNRELEASED"`. Its corrected typed sparse counts,
ordinary-metadata guard and owned temporary staging are retained. The owner is held.
Agent `c16f5f94-b124-40f4-9deb-8121afdbc093` now owns only `reference_writer.py`,
`scripts/portable_release_assets.py` and `tests/test_portable_release_assets.py` for a fresh
bounded correction. Agent `c7089bf7-a970-4b5f-960e-4bbdbe32dd26` retains the independent
writer tests. No driver format change is authorized; positives use its real native envelope.
No pytest begins until the mandatory tests and actual consolidated source fixes are ready.

The replacement source owner reports the real native development envelope, shared batch
case/evidence validation and first-run directory preparation implemented; independent writer
tests now pass unsuppressed strict typing without an unrelated driver import. Source/tests
remain held and pytest has not begun. Root's source inspection found that directory
preparation still derives from selected data root B instead of executable A's specification
directory, contrary to the accepted preflight contract. The cold reviewer is checking this
and the complete writer correction before a test slot is granted. In parallel, the prior
driver owner is mapping c.3c CLI/plugin integration read-only, including optional observation
output failure handling. The first unchecked box remains M1.5c.3b.

The consolidated writer review confirms the prior four corrections but identifies two
remaining P1s: directory preparation targets B instead of A, and its development-row view
incorrectly requires fixture-only top-level `observations` on native driver-assertion rows.
The replacement source owner corrects both; the independent test owner now models real
fixture/driver row shapes and separate B data with exact A output paths. No pytest slot is
granted until this fixed snapshot is held for closure review.

For c.3c, the private option will be `--write-reference REVISION`, a nonzero lowercase
40-character A revision, deriving both canonical A filenames. `--portable-report` remains
optional and ordinary development behavior is preserved. Reference-mode report publication
will join the writer's owned transaction so a requested report failure cannot leave a false
reference pair; the exact small callback interface is still to be finalized after c.3b.

Final bounded source review closes both writer P1s. Root independently inspected the A-only
directory preparation and native kind-specific row view, then ran Ruff and unsuppressed
strict mypy over the four helper/writer source and test modules: both passed. Two test-only
setup expectations were corrected without weakening source: synthetic A includes its existing
`specification` directory, while only `reference` starts absent; an existing environment
destination expects the early preflight error, while a raced hard-link still expects
`FileExistsError`. The combined targeted gate is running in root shell
`56ce0279-1b1b-4fa5-8b27-2fe356c8de5a`, with source and tests held.

That gate exited 1: helper tests passed, while three writer tests all encountered the same
invalid synthetic baseline. The test builder listed extension features per eligible case
without deduplicating the shared dialect feature (nine cases, eight features), so the actual
writer correctly refused before drift/publication predicates. The independent test owner
corrects only the builder and strengthens negative-test causality: validate the untouched
baseline, then check the intended diagnostic for each isolated mutation. Ineligible-case
tests retain valid full declarations instead of substituting an unrelated invented feature.
Writer/helper source stays held; root will rerun only the changed writer module next.

The writer-only rerun (`acf089bf-ef43-461b-b1fd-6ad4140ca3e0`) passed six tests and failed
one diagnostic-order assertion in 6.86 seconds. Successful A publication/B immutability,
drift, cancellation, metadata refusal and race cleanup now pass. Null driver evidence is
correctly rejected by the selected case schema before the later semantic recipe check;
the negative matrix expected the later wording. The independent test owner has the sole
pytest slot to correct only diagnostic-order expectations and run the complete seven-test
writer module persistently. Source remains unchanged; a new source defect must be escalated.

Root inspection and the reviewer confirmed an additional direct-case P1: the new shared
successful-case validator checks ordinary JSON only in fixture observations, leaving driver
or extension nested evidence able to contain nonfinite numbers, lone surrogates or integers
outside v0 bounds. Qualified report mappings already reject those values. The helper owner
will add the same whole-case-list guard and isolated nested-evidence regressions, preserving
inclusive endpoints. Edits wait until the independent writer test owner's sole run releases
the pytest slot; no source changes are allowed underneath that run. c.3b remains unchecked.

M1.5c.3b is accepted: root's joined helper/writer gate
`c9bf730d-5a82-47aa-b122-22e8d0bf8ac8` passed **53 tests, 1 platform skip** in 43.00
seconds, exit 0. Root inspected the retained log, the whole-case guard and nested-evidence
regressions; Ruff and unsuppressed strict mypy passed across all four helper/writer modules.
The final independent code delta is clean. Both native case shapes and exact A-output/B-data
separation are now proved. The first unchecked child is M1.5c.3c; no real reference artifact
has been written, and the enclosing phase/full repository gate remains open.

M1.5c.3c ownership is disjoint: agent `c16f5f94-b124-40f4-9deb-8121afdbc093` owns only
the writer's optional trusted publication callback; agent
`c7089bf7-a970-4b5f-960e-4bbdbe32dd26` owns its independent writer tests; agent
`1e09179c-3413-4551-b0e4-65cb177a5654` owns driver/plugin integration and its tests.
The callback runs after final validation, publishes an optional new observation report,
and returns its owned rollback action so later reference failure cannot strand partial
output. Ordinary development output keeps its existing replacement behavior. No agent
runs pytest before root assigns the serialized joined slot.

The driver owner also has two bounded private typing corrections: import the existing
`MissingEvidenceError` from its canonical values module in `comparison.py`, and access
the same stdlib `asyncio.timeout` object directly in `proof_timeouts.py` instead of relying
on an implicit SDK-module re-export. These resolve six known transitive strict diagnostics
without changing production code, timeout delegation or proof policy. Existing timeout
and complete portable checks must still pass in the joined gate.

The c.3c hook is source-ready and its independent callback tests are authored, but review
found one remaining publication-ownership race: metadata cleanup unconditionally unlinks
paths and can delete a replacement environment file. The writer owner changes the byte
publisher to return an identity-guarded rollback, recording the owned staging identity before
linking and comparing the destination's own identity on cleanup. Independent tests replace
the environment inode before manifest failure and require that replacement to survive while
the callback-owned report rolls back. The driver report publisher will reuse this same byte
primitive after its path/serialization checks. No pytest runs during the correction.

The integration source remains held for consolidated CLI/plugin/path review. Root also found
that the requested shared strict loader/selected validator reuse was omitted and the new
report-path guard blocks all of A rather than the named protected inputs. These are not
accepted as silent scope changes; the driver owner receives one consolidated correction
after review. The first unchecked box is still M1.5c.3c.

Root's source-path-only Windows probe corrected one review assumption: `Path.absolute()`
retains an absolute path's `..` segments here, allowing a lexical prefix test to miss a
destination that resolves into protected inputs. The integration correction walks links
before canonicalization, then checks and returns the canonical destination. It also reuses
the trusted strict validator, permits named safe A output paths outside protected inputs,
and adds real pytest parser/lifecycle/controller proofs rather than only direct hook calls.

The isolated writer callback/identity-ownership gate
`0c781d82-896d-4f2d-bf6b-4ceb1010ce28` exited 0 with **12 tests passing**. Root inspected
the retained log and actual staging-before-link/lstat-guarded rollback implementation.
The independent replacement-inode and callback-cleanup resilience tests pass. Driver
integration remains in correction; the enclosing c.3c gate is not yet accepted.

The driver correction is source-ready: strict loading and exact selected-fixture validation
delegate to the trusted A-side validator; report destinations are canonicalized after link
inspection and protect A metadata/specification plus B while permitting safe named scratch
output. Report publication reuses the accepted identity-safe byte primitive. The subprocess
harness was tightened before launch: explicit 60-second child timeouts, append-only startup
events detecting duplicate worker hooks, and a real parser startup-refusal case. Root's
35-test targeted driver/writer gate is running in
`7b293ca3-8357-4550-9cad-a9e3e3a9e702`; all source/test files are held. Final driver
review runs read-only in parallel. No reference files are generated in the checkout.

The targeted integration gate exited 1: **32 passed, 2 failed, 1 setup error** in 22.92
seconds. Writer tests passed. Test-only corrections enable the pytester fixture, expect the
earlier shared inventory diagnostic, and mutate valid fixture fields for NaN/surrogate
domain controls instead of unrelated malformed JSON/schema shapes. Final review also
requires the child writer to await and forward the actual raw observer callback, rather
than manually substitute its return value; that proof correction is authored.

The selected-schema failure is a real shared-helper boundary defect: an unresolved asset
schema `$ref` escapes during evaluation, after construction checks. The shared validator
owner now owns only the two validator/release scripts and their two asset test modules to
return useful diagnostics, keep local references working and disable external retrieval of
unbound schema assets. The direct case validator must reuse that policy. Native SDK schema
behavior is unchanged. Driver/writer files stay held; no pytest runs until this correction
and its tests are stable for review.

Read-only M1.6 preparation identified an open authoring-contract gap: transport inputs leave
adapter configuration and direct-wire/core-operation fields schema-open, and the profile
does not yet fix the header projection. The proposed minimal mapping follows existing
native constructors; semantic controlled headers (content type, configured headers and
nonsecret fixture authorization) are the proposed comparison boundary, excluding client
framing/default headers. This is recorded as a proposal only. Root must settle and encode
the literal shared data contract before transport fixture authoring; no M1.6 file was written.

The joined selected-assets/driver/writer gate
`35c1636d-5f9e-4059-b13f-5bff27dba4d3` exited 1 with **105 passed, 1 skipped and 2 failed**
in 284.22 seconds. Both failures are driver test setup: a marker control searches the
pending corpus for a marker that is absent, and the pytester child selects checkout
configuration before loading the temporary trusted plugin. The driver test owner corrects
those controls without changing product behavior. The shared-validator owner separately
restores omitted-root custom-corpus Markdown resolution, proves no external retrieval by
recording zero calls, and loads the trusted validator once per case-validation batch.
Files remain under disjoint ownership; pytest is held until the corrections are stable.
M1.5c.3c remains the first unchecked box.

The five-node focused gate `56936ec7-ade6-4a6f-a1a2-fcab7fd01ad0` exited 1 with **2 passed
and 3 failed** in 72.69 seconds. Both selected-schema evaluation controls passed. The new
legacy positive exposed an incorrect inventory-depth inference; the validator now restores
the exact prior root-based omitted-argument branch. The driver marker control used literal
strings rather than typed marker objects, and its child pytest selected unrelated checkout
tests; both are corrected in test setup with actual marker objects, isolated child config
and explicit child test paths. The driver owner holds the sole persistent three-node slot
for these controls and the adjacent-root regression. Other files remain held, and no broader
suite or phase acceptance is claimed.

The driver owner's retained shell `b19d89c7-6b2e-4a06-8854-85acfc03649a` now passes all
three focused nodes in **9.93 seconds**, exit 0. Root inspected the final log and code:
the child selects its own configuration/test file, explicitly loads the trusted plugin and
xdist where needed, disables ambient plugin autoload, and preserves raw observer identity,
controller-only startup and failure/refusal assertions. The legacy adjacent-root control
also passes. Root now runs unsuppressed strict mypy over the 15 changed/new private support
modules followed by the complete 13-phase `workspace check --fail-fast` in
`ef2d5801-2a58-4341-860c-f999b1a335f7`, with two xdist workers. All source files remain
held; M1.5c.3c awaits that gate and final bounded review closure.

The first full-gate attempt reached test-session cleanup without a test-failure report but
exited 1 because Windows denied access to the pre-existing `.pytest_cache/v/cache` directory;
warnings-as-errors correctly made that cache warning fatal. No source or warning-policy
change follows. Root restarted the same persistent shell with a fresh
`.tmp-tests/reference-full-repository-final` pytest cache, retaining both workers and every
repository phase. The prior unsuppressed 15-module type check passed. Both final cold
reviews are clean; complete repository acceptance still awaits the rerun.

M1.6's next execution slices are now explicit in the master checklist. The real adapter
uses the configured HTTP transport seam; a transparent wrapper installed only in a fresh
built-in descriptor registry records actual native WireRequest objects before delegation.
This preserves the accepted capture-vs-request validation instead of weakening it to
compare a snapshot with itself. No SDK API, global registry, provider behavior or actual
transport fixture has changed during this preparation.

The complete rerun in `ef2d5801-2a58-4341-860c-f999b1a335f7` exited 0: **all 13 repository
steps passed in 237.0 seconds**, including the full test track, adapter/serve conformance,
fixture validation, contracts, lint/types, documentation checks/examples and strict site
build. Root inspected the retained final summary and the final selected-root/driver review
closures. The separate unsuppressed strict check passed all 15 changed/new support modules.
M1.5c.3c and its now-complete M1.5 parents are checked. No actual reference/release directory
was produced. The next source work starts at M1.6a after this checkpoint commit.

Checkpoint committed as `ecc4f2dfdfece1ab477d7dde1024e8027b3372ff` (`Bind reference evidence
and qualify portable reports`); root verified the working tree was clean afterward.
M1.6 now runs with disjoint owners: `c7089bf7-a970-4b5f-960e-4bbdbe32dd26` owns only the
transport schema/profile wording; `c16f5f94-b124-40f4-9deb-8121afdbc093` owns selected local
schema binding and synthetic asset tests; `1e09179c-3413-4551-b0e4-65cb177a5654` owns the
private native HTTP runner/tests and minimal shared runner extraction. Existing SDK,
projection strictness, driver dispatch and actual transport fixture authoring stay outside
these first slices. Root serializes tests and master-checklist acceptance. No worker runs
pytest until the shared contract/code is ready for a joined gate.

M1.6a schema/selected-local resource support and synthetic controls are source-ready. Root's
asset-only gate is `7b70530f-e8f0-46e2-b7dc-b7b1a8fffb8e`; independent contract review runs
read-only alongside it. M1.6b cold review rejected the first runner slice: it ignored fixture
adapter configuration, projected a shape incompatible with valid observed expectations, and
failed to classify unused scripted responses after native errors as harness faults. The
transport owner corrects these plus schema-valid baseline/real lifecycle proofs in its two
private files. No native transport test is launched against that rejected slice, and no
M1.6 box is checked yet.

The asset gate `7b70530f-e8f0-46e2-b7dc-b7b1a8fffb8e` exited 1 with **74 passed, 1 skipped,
1 failed** in 82.88 seconds. Its failure reproduces the independent resource-admission
finding: a selected sibling without dialect metadata reaches `Resource.from_contents` and
escapes as `CannotDetermineSpecification`. The validator owner now pins registered sibling
objects to exact Draft 2020-12, self-checks them before resource creation, translates admission
faults to diagnostics, and owns the sole narrow test slot for those controls. The existing
unresolved-reference test keeps its distinct evaluation purpose by supplying valid explicit
dialect metadata before the missing external reference. Transport runner correction remains
in its separate private files; all other source is held.

M1.6a's final joined gate in `7b70530f-e8f0-46e2-b7dc-b7b1a8fffb8e` passed **78 tests with
one platform skip in 45.81 seconds**, exit 0. Root inspected the full retained result and
reran affected Ruff plus unsuppressed strict mypy on the three eligible support modules.
The contract/admission review is clean. Both old driver-test constructors now use valid
pending data, with a valid-base64 baseline before its isolated malformed mutation. M1.6a is
accepted; its owner receives the serialized checklist update. M1.6b source defects are closed
by review; native runtime evidence still awaits actual HTTP lifecycle proofs and the focused
test slot. Pending input authoring is independent and may now start under M1.6c.1.

The first native HTTP gate `76c7f832-2bdf-4b58-a8cb-de2d640005df` exited 1 with **12 passed,
4 failed** in 6.51 seconds. The core literal comparison needs a useful observed-delta
diagnostic; a recorder cancellation control cancelled outside its generator-owned await;
both core lifecycle controls had an invalid underscore in their fixture ID. Independent
review additionally found real adapter cleanup bypass on cancellation. Root inspected the
HTTP core path and found it omitted schema/repair, default consumption and native
telemetry/clock/input-schema facts. The native owner now owns a minimal shared extraction in
`runner.py` so both synthetic and HTTP adapters use the accepted execution body. The lifecycle
owner rewrites its proofs through the actual transport runner, without manually closing the
adapter after cancellation; private file ownership remains disjoint.

All eleven pending transport inputs are authored and strict default coverage validates.
They are not accepted yet: root decoded the raw-byte fixture and found escaped ASCII instead
of actual multibyte UTF-8 (297 bytes equalled 297 full-response characters, over cap 80).
The author corrects that stimulus using actual UTF-8 and a cap between whole-response decoded
character count and raw-byte count. A separate cold intent review audits every literal input
and response before M1.6c.1 acceptance. Expected blocks remain exactly status-only pending.

M1.6c.1 data-only authoring is accepted after root reran strict complete coverage and
independently decoded the corrected stored Base64: whole SSE response 147 Unicode code
points, 177 UTF-8 bytes, cap 147, with 30 literal non-ASCII characters. The separate cold
review closed all eleven pending inputs. No native outcome is inferred; M1.7 owns
expectation reconciliation. The author receives the sole c.1 checklist lease.

The first shared HTTP execution correction still omitted virtual health/backoff clocks and
filtered configured headers by an x-prefix heuristic; root requested preservation of the
accepted clock facts, all explicitly configured semantic headers, and typed core
construction origins. The lifecycle proof now invokes the actual runner with no manual
adapter/client cleanup; its SSE stimuli are being checked for actual LF framing and a
real content observation before the next serialized gate.

The next M1.6b joined gate is owned serially by the transport implementer in retained
shell `75e9a0e8-0d98-4e4a-b3bc-2ecf868ab0a2`, covering transport, actual runner lifecycle,
existing runner, projection and comparison tests. Root inspected the first two failure
logs: lifecycle setup used zero total attempts (no HTTP execution) and repeated directory
creation; the controlled expected core result used an incorrect timing marker and an
invented `success` attempt value instead of native `ok`. These test inputs are corrected
without changing SDK/projection semantics. A final source delta now preserves nested core
comparison error-versus-fail and its diagnostic, with actual retry/backoff and typed
construction-origin controls. Acceptance remains held pending the combined rerun and
independent final review.

M1.6b is accepted. Root inspected final retained shell
`75e9a0e8-0d98-4e4a-b3bc-2ecf868ab0a2`: **148 passed in 20.87 seconds**, exit 0, covering
transport, actual runner lifecycle, existing runner/projection/comparison. Root separately
reran unsuppressed strict mypy over all four changed support modules, passing. Final cold
review has no material finding. The transport owner completed the serialized b checkbox
lease; SDK behavior and pending corpus expectations remain unchanged.

M1.6c.2 and c.3 now have disjoint owners. `04f0bc20` owns only the new HTTP proof module/tests
and existing centralized proof dispatcher/tests. `c16f5f94` owns only the driver and its
driver/execution tests, removing staged optional transport handling and dispatching every
inventory obligation. Their settled dispatcher signature stays unchanged and gains the
sixth declared recipe, so source authoring can proceed together; runtime gates wait for
both ready states. All selected fixtures must now be mandatory, hashed and passed to one
trusted complete-coverage validation. Pending verdicts retain existing development
representation; no qualified report, reference or release claim follows. Root retains the
sole serialized heavy-test slot until a combined gate is granted.

On the user's continuation, root checked live ownership and the proof worker's retained
transcript. The worker had ended with mandatory predicates/tests unfinished; the proof was
not accepted or runtime-gated. Root transferred only `proof_transport.py`/`proofs.py` to
`1e09179c` and the independent `test_proof_transport.py`/`test_proofs.py` matrix to `c7089bf7`,
with explicit expected replies and disjoint ownership. The former owner acknowledged hold.
The invalid buffered cap-1 ASCII substitute and unconditional core-run rejection must be
replaced with actual multibyte predicates; full correction linkage/raw-byte evidence remains
mandatory. Driver source review is clean, and root inspected the separate 11-case boundary
gate (2.72 seconds) plus forced-import compatibility node (1.98 seconds), both passing.
The first unchecked box remains M1.6c.2; no full 102-case success is claimed yet.

The new source/independent proof matrix passed root Ruff and unsuppressed strict mypy
across seven integration modules. Root joined gate
`d0f1faba-7694-4f9b-b85d-3bfa537e88a9` finished **163 passed, 2 failed in 23.57 seconds**.
Both failures were negative-control diagnostic ordering: removing a native capture entry
correctly hits the shared missing-evidence guard, and a one-byte malformed UTF-8 substitute
no longer establishes the overflow stimulus. The independent native positives and fixture
execution controls passed, but this is not proof acceptance. Cold review confirmed missing
actual-mode binding, top-level HTTP/wire-to-core capture linkage, and the exact invalid/valid
assessment predicate. Source and test owners now correct those in their disjoint files;
root explicitly corrected the review's accidental minimum-rule wording to this fixture's
actual age type violation. No SDK, fixture expectation, reference or release is changed.

The corrected native proof matrix passed **22 tests in 0.51 seconds** in retained shell
`901a7424-e06a-41d9-b149-7451b17d7e87`. Root inspected the final exact-one-issue guard and
wrong-rule/wrong-path/surplus-issue mutations, then reran strict mypy across all 13 M1.6
support modules successfully. The complete named M1.6 portable/OpenAI gate previously
passed **378 tests with one platform skip in 39.98 seconds** in `d0f1faba...`. The last
small guard is covered by the focused run and will be included in final repository checks.

Root's final standalone development-driver audit has exactly 102 inventory-ordered unique
rows, 104 raw-hashed selected inputs, and counts `{None: 87, extension: 9, pass: 6,
unexecuted: 0}` with no unexecuted rows. Its JSON is explicitly UNRELEASED and remains under
`.tmp-tests/m16-development-observation.json`; no reference or release was produced.
The initial full repository run `92a35290-22a0-49c1-82fc-884824966c19` was deliberately
stopped before the final exact-issue change; it is not acceptance evidence. A fresh-cache
full rerun waits for final bounded cold-review closure. All executable source remains held.

M1.6 is accepted. After clean final proof review, the fresh-cache rerun in
`92a35290-22a0-49c1-82fc-884824966c19` passed **all 13 repository steps in 280.4 seconds**,
exit 0. Root inspected the retained summary. The final source includes the exact invalid
issue signature and its independent negative controls. The driver covers all 102 obligations
with no fail/error or unexecuted row; all 96 fixture expectation blocks remain pending for
M1.7. This establishes complete development execution, not a reference or released report.
The driver owner receives the sole M1.6c.3/parent checkbox lease before the phase commit.
Next is M1.7a's causal expectation-staging utility; no fixture expectation is changed yet.

M1.6 was committed as `61aa4544af0ece70355a78eaf0842f1eea44e83f`; root verified a clean
working tree. M1.7a inspection found an unreleased specification error: nested core call
messages expand native-feedback markers, but outbound HTTP bodies compare the corresponding
feedback literally. That would require another native validator to repeat Python's prose.
M1.7a.1 closes only the core-HTTP expected message-content position, with causal entry binding,
shared marker validation and literal adapter/other-JSON boundaries. The pure utility follows
under M1.7a.2; expectation writes remain M1.7b.

M1.7a.1 is accepted. Root inspected joined shell
`ccfcf6be-9071-4ffd-a573-d94a9e07dd6a`: **459 passed, two platform skips in 74.43 seconds**,
exit 0, with Ruff, strict typing on three changed support modules and all 23 Markdown
links checks passing. Independent final review is clean. Before testing, root corrected
invalid structural equality between HTTP multipart and flattened core text, then prevented
noncandidate array concatenation and an early-return path that skipped later messages.
The focused validator/coverage and 19-test transport gates also passed. Source remains
uncommitted pending the coherent reconciliation phase; no fixture expectations were changed.
Resume at M1.7a.2: pure native-fact reconciliation utility and independent tests, with writes
still reserved for M1.7b.

M1.7a.2's first focused matrix (`c90e92e2-df5f-4a88-aa1c-075a16426bac`) finished
**13 passed, 10 failed** in 2.09 seconds. Root confirmed one source defect: an eligible,
declared extension with unavailable capture was mislabeled as an authorization/domain error
after its comparator returned error. Eligibility must be checked independently; authorized
missing native evidence remains `MissingEvidenceError`. The source owner corrects only that
boundary while the test owner fixes proven path/setup/category mistakes. The empty-message
case actually enters the native adapter; shared section 2 explicitly leaves that behavior
unobserved, so its test must retain the observation instead of assuming a construction
failure. True invalid-sampling construction remains the zero-entry control. No SDK,
specification behavior or fixture input is changed. The focused slot stays with the test
owner for the same retained shell after source stability; acceptance is still pending.

M1.7a.2 is accepted. Root inspected retained `c90e92e2...`: the corrected full matrix passed
**22 tests in 3.48 seconds**, and the isolated same-case-ID kind guard passed in 0.13 seconds.
Independent final review closed all findings. Root then ran
`7c6555e7-c343-4473-bcfa-492f96107312`: **389 passed, one platform skip in 38.71 seconds**,
exit 0, with Ruff and strict typing on both new modules passing. The two new private modules
are explicitly staged in Git so actual loaded-module provenance sees tracked sources;
there is no new commit or reference artifact. The first unchecked execution box is M1.7b:
stage all 96 expected envelopes in an isolated complete specification copy, retain actual
audit rows, classify/review against named requirements, and apply only accepted data later.

M1.7b isolated copy `.tmp-tests/m17-stage-61aa454-02/specification` retained its audit at
`m17b-audit.json`. Native authoring staged **85/96**, leaving eleven original documents
pending after identical private-comparator failures. Shell
`efc214f4-230b-4001-9b39-622a85e43aed` exited 0 because it collected the whole audit; this
is not acceptance, and full selected validation/fresh 102-case observation did not run.
Root inspected the source: `_messages_equal` requested native correction feedback for
every user message at index > 0, including original retry calls. Root declined a proposed
authoring workaround that forced earlier-call references: literal repeated messages are
valid shared data. A narrow comparator fix now looks up feedback only for explicit typed
repair-feedback segments, with independent retry/failover regressions before a fresh B03
stage. SDK/input/spec behavior stays unchanged. Separately, metadata review verified the
exact 60/36 split and requested two precision corrections: zero *repair* attempts, and
*attempts* extraction before malformed-schema assessment. Canonical fixtures remain pending.

The B02 comparator correction is accepted after root inspected **51 passing tests in
2.42 seconds** in retained `c90e92e2...` and a clean bounded code review. Feedback lookup
requires an exact singleton marker with boolean identity (`is True`), preserving numeric
1/1.0 as malformed segments. Native retry/failover/failed-stream regressions retain full
literal original messages without earlier-call authoring workarounds. Source is held and
the same native oracle shell now owns a fresh B03 full staging run; B02 remains preserved.
No canonical fixture or SDK changes have occurred. The first unchecked box remains M1.7b.

Fresh B03 native staging completed in the same retained oracle shell
`efc214f4-230b-4001-9b39-622a85e43aed`: **96 staged, zero failures** under
`.tmp-tests/m17-stage-61aa454-03/specification`. The sibling `m17b-audit.json` records
UNRELEASED/dirty-source status, code/input hashes, native comparison rows and a fresh
102-case development observation with **93 pass, nine extension, zero fail/error/unexecuted**.
Full selected validation returned no problems. Root inspected the retained audit and exit-0
log; empty-message evidence is one operation/one original entry with `messages: []`, no
assessments, and a successful result. Canonical data is still untouched. Independent reviewers
now own disjoint 45-case and 51-case semantic cohorts, with a third verifier checking all
96 raw hashes, ordered nonexpected invariants and audit coverage before any application.

The 51-case schema/extraction/validation/transport cohort is clean; root inspected every
recorded disposition. The independent all-96 invariant review also has zero findings:
all raw before/after hashes, exact nonexpected types/member order, ordinary-JSON domain,
encoding, six implementation hashes and fresh 102-case/104-input audit bindings match.
The remaining 45-case semantic review found a real fixture stimulus gap in
`streaming/first-token-mark-once-per-attempt`: the first `{"ok":false}` response satisfies
its required-only schema, leaving the authored correction script unused. Root classified
this as fixture data, preserving the named original/correction requirement with a narrow
`properties.ok.const: true` correction instead of weakening the description or changing
SDK behavior. B03 stays frozen as historical evidence; finish the remaining semantic
review, serialize its required data corrections, and retain a fresh full staging audit
before canonical expectation application. M1.7b remains the first unchecked box at HEAD
`61aa4544af0ece70355a78eaf0842f1eea44e83f`.

Root inspected the complete 45-case semantic table. Its remaining 43 cases are clean;
the first-token stimulus gap and empty-list pending normative language are the only
dispositions requiring edits. The empty-list adoption preserves observed Python behavior:
normalization admits the empty list without a synthetic caller message, while schema
injection follows section 5. It is not a promise of exactly one entry for every route.
The data owner has a disjoint three-file brief for the single schema correction, durable
empty-list description, and two normative placeholder replacements. The native owner is
authorized to run a fresh B04 all-96 stage after those cheap checks pass, preserving B03.
No canonical expected block has been applied; final M1.7b acceptance remains pending.

The exact three-file stimulus/norm correction passed coverage, Markdown links and encoding
checks; root inspected both fixture diffs and the two normative replacements. The fresh B04
native stage in retained `efc214f4-230b-4001-9b39-622a85e43aed` then exited 0: all 96 staged,
zero failures, selected validation empty, and a fresh 102-case/104-input observation with
93 pass / nine extension / zero fail, error or unexecuted. Its disposable ordered invariant
now also requires scalar type identity. Root inspected the audit and final log. The corrected
first-token case has original/correction entries, two ordered start/first-token pairs,
one repair and final `ok: true`; empty messages retains one original empty wire with zero
assessments. B02/B03 remain frozen. Independent corrected-case and all-96 hash/order checks
run before the guarded canonical expected/description application; no expected data has yet
been applied to the canonical tree.

B04 semantic closure is clean: both prior findings are resolved and the other 43 core
cohort envelopes are byte-identical to B03. The all-96 independent invariant recheck has
zero findings, with exactly two approved fixture deltas and all 104 raw hashes matching.
Root accepted the guarded dryrun manifest, then authorized one snapshot-based application.
All 96 canonical fixture writes match their approved proposed hashes; 59 further description
updates complete the reviewed 60 mappings because empty messages was updated earlier.
All 36 already-durable descriptions are unchanged. Application audit and original-byte
backups remain under `.tmp-tests/m17-apply-61aa454-04/`. Coverage, Markdown and encoding
checks passed, as did root Ruff and strict mypy across nine changed support/test modules.

Root canonical joined gate `d55ecb4f-4084-408c-8a61-cc02f48e1690` finished **477 passed,
12 failed, two platform skips in 59.94 seconds**. All canonical corpus execution/count
assertions passed. The twelve failures are synthetic comparison/reconciliation tests that
retain newly observed expected calls while changing request/message/schema/extension
inputs, or still expect pending cancellation from checked-in data. The independent test
owner has the two affected test files and a focused slot to create explicit fresh pending
authoring setups; observed preservation controls and source/data remain held. Final
repository acceptance and clean revision A are still pending; no reference output exists.

The narrow synthetic authoring fix passed **51 tests in 3.27 seconds** in retained
`c90e92e2-df5f-4a88-aa1c-075a16426bac`; root inspected the exact two-file diff and exit-0
log. Deliberate pending fixtures are now deep-copied authoring inputs, while observed
segment preservation and strict reconciliation provenance remain unchanged. The final
postapply independent review has no open finding: every expected envelope, input/script
value and member order is preserved, all 96 applied hashes match, and all 60 reviewed
description strings exactly match the approved plain-text manifest/canonical values.
The initial 17 artifact-table code-formatting differences were resolved only in the
review table under the pre-application plain-prose disposition; no corpus/audit changed.

M1.7b is accepted. Root inspected final shell `1898982c-52b7-49a0-b424-2ee4677c54dd`:
**all 13 repository steps passed in 194.7 seconds**, exit 0. The canonical corpus has
96 observed fixtures and covers all 102 obligations as 93 pass / nine eligible extensions,
with no pending, fail, error or unexecuted row. Root now commits the reviewed implementation,
driver, schema, specification and fixture inputs as revision A. Resume at M1.7c from that
clean commit; no executable/normative input may change while the actual reference writer
runs. The generated manifest will record the exact full A revision without a self-hash cycle.

Clean input revision A was committed as `fc537872b4e419fa0a01c60e595288099924564b`
(`Reconcile observed core and native transport expectations`), with exactly 110 approved
paths including all 96 fixtures. Root verified no tracked/untracked input changes and
actual import `D:/projects/AnyInfer/src/python/anyinfer/__init__.py` before production.
Root shell `f3d4b84e-c1ab-4253-ac2e-533cff2c7990` then ran the actual private CLI with
`--write-reference fc537872b4e419fa0a01c60e595288099924564b` and an ignored development
observation output. It exited 0 and published only `specification/reference/python-fc53787.json`
and `python-fc53787.environment.json`; no tracked input changed during production.

Manifest SHA-256 is `0e43d1ba3ae5d7e02a19c411b0329b822a8f84a3ed41abb567441ceef72d7ead`;
the bound raw environment SHA-256 is
`f4660ede3c08285e498a12d5cfcb2fcbb09130efbc2b130077880d473265e4ea`.
Root's shared evidence validation accepted the metadata and all 102 successful case rows,
with eight declared feature names, 93 pass / nine honest extensions / zero unexecuted.
The preserved observation is explicitly UNRELEASED/ineligible and remains ignored at
`.tmp-tests/m17-reference-fc53787-observation.json`; the manifest itself is metadata only.
Independent audits close source/revision/timestamp/raw input bindings and exact installed
environment identity: 97 distribution locks, seven required packages, two import roles,
221 loaded module files (158 repository / 63 virtual-environment), the actual interpreter,
20 validator resources and strict warning policy. Both reviews have no open finding.
M1.7c waits only for final repository checks with the generated outputs present and the
reference metadata commit; no frozen release or qualified report exists yet.

M1.7 is accepted. Root inspected final reference-output gate
`6b66f310-cb2d-4c72-ac80-e4eb426a6bb3`: **all 13 repository steps passed in 188.1 seconds**,
exit 0. Both canonical reference artifacts retain the independently checked raw hashes;
their actual producer remains clean input A `fc537872b4e419fa0a01c60e595288099924564b`.
The metadata commit records those outputs, completed M1.7 boxes and the next resume point
M1.Ga. The ignored observation stays development-only, and no release or qualified report
has been generated.

Read-only M1.G preparation confirmed two missing producers: `scripts/freeze_release.py`
and the private final-report writer. Root split their disjoint implementation/test ownership
into M1.Ga/b, with candidate tooling/asset commit C before the actual complete report run.
That sequence keeps ordinary report execution fully clean and binds its own current code,
runtime, OS and dependency versions using the existing report-v0 fields; reference A's full
environment sidecar is not copied or redefined. M1.Gc/d retain complete repository, native
execution, cold review and local-only immutable retrieval gates before C# work begins.

The reference metadata record was committed as `31784ab5638de56ec53484768d12e54be04c2253`
(`Record clean Python reference environment and run`); root verified the resulting tree
was clean. Reference-run A remains `fc537872b4e419fa0a01c60e595288099924564b`.
Resume at M1.Ga. The new producer wave has disjoint ownership: `c7089bf7` owns only the
freeze writer/test; `1e09179c` owns only the final-report producer/test and any minimal
shared runtime-collector extraction in the reference helper/test. Both must finish source,
meaningful negative controls and static checks before receiving the sole pytest/native
slot. No candidate, final report or C# source is created in this authoring wave.

M1.Ga's first eight focused tests passed in 10.73 seconds, but cold review correctly held
acceptance for three source defects: payload-byte equality was not owned-file identity and
left partial writes, `os.O_BINARY` was Windows-only, and fixed 102/96/106 cardinality gates
duplicated inventory policy. The owner corrected only the freeze writer/test. Descriptor
device/inode plus `lstat` now protects replacement files and cleans owned partial output;
portable flags and inventory-derived counts have direct controls. Root inspected corrected
source and retained `c90e92e2...`: **12 passed in 6.17 seconds**, exit 0, with Ruff, strict
typing and clean final cold source review. M1.Ga is accepted; its serialized checkbox
lease is complete and released. Four new producer source/test paths are marked intent-to-add solely for
loaded-module tracking in tests; no content commit or actual candidate was produced.

M1.Gb is source/static-ready with new producer/test and minimal shared import-path checking
extraction in `reference.py`. Its disjoint cold review is in progress. Root granted the
sole focused slot for the new report tests plus existing reference, preflight and writer
compatibility tests, using a fresh cache. All canonical normative inputs, reference artifacts
and release/report outputs remain held until that producer gate and code review close.

The first M1.Gb compatibility gate passed 41 tests with one skip in 25.61 seconds. Cold
review identified a remaining provenance defect: checking the package root and producer
path did not bind the actual observer or already-loaded private/runtime submodules. The
owner is correcting that boundary and adding foreign-module controls before a fresh
four-file gate. The actual 102-row baseline already uses the shared release qualifier;
its evidence/declaration assertions will be strengthened. M1.Gb remains unchecked, and
no canonical candidate or final report has been written.

M1.Gb is accepted after the retained four-file gate passed 43 tests with one skip in
34.86 seconds, followed by the real qualification baseline and tracked wrong-role
regressions (one pass each). Shared provenance binds the actual observer and loaded SDK
and portable-module roles before observation and publication. The real 102-row baseline
uses the shared qualifier and checks eight declarations, null ordinary evidence and
structured driver/extension evidence. Ruff/strict typing and final cold review are clean.

Root created the actual M1.Gc candidate with explicit `reference/python-fc53787.json`,
then ran the planned `freeze_release.py --verify core-generation-v0`; both commands
exited 0. Candidate raw SHA-256 is
`16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391`.
The reference manifest/environment retain their independently audited hashes. The
candidate now awaits independent closed-set review and the full repository gate before
the intermediate clean code/asset commit C. No final report has been produced.

Independent candidate review verified all 106 raw hashes and the exact 102-case closed
inventory with no pending data; the historical reference binding is unchanged. The first
full candidate gate stopped at tests: all 11 failures come from the new freeze tests
copying the now-existing canonical generated release into their temporary authoring tree.
They then correctly encounter collision refusal before reaching their intended branches.
Only that test-copy setup is being corrected to omit top-level release/report outputs;
production writer policy and the audited candidate remain held unchanged. A fresh full
gate is required after its focused controls and bounded review pass.

The test helper now excludes generated outputs only at the top level of the copied
specification, preserving every authored input and the explicit collision tests. Root
inspected the retained final focused result: 12 passed in 7.56 seconds, exit 0. The
candidate raw hash is unchanged. The full gate was restarted with a fresh cache; the
intermediate commit and actual final-report run remain held until it passes.

The corrected candidate gate passed all 13 repository steps in 205.5 seconds, exit 0,
in root shell `16ab4376-30c1-410a-b101-ad5dacc74daa`. The test-copy delta has clean bounded
review, and the independent candidate audit confirms all 106 exact raw input hashes,
102 inventory records and the unchanged reference binding. Planned release verification
was repeated successfully with the same raw SHA. Root now commits only the eight
reviewed tooling/test/plan/log/candidate paths as intermediate C, then verifies its clean
full revision before executing M1.Gd. Resume at M1.Gd; no final report exists yet.
