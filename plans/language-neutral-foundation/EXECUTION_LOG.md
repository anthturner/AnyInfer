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
- Pre-existing untracked nested `AnyInfer/` tree remains outside the change.
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

### Current resume point: M1.5a

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
