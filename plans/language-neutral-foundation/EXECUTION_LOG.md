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

Commit this reviewed checkpoint, then execute the first unchecked M1.5c.1 box. Start with
explicit selected-root validation and one shared data-only release/report binding helper;
comparison/reference consumers depend on its accepted API. No owner is authorized to alter
Python retry/repair or implement aggregate accounting. The coordinator owns shared plan
acceptance and serializes tracked test slots.
