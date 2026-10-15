# Completed planning history

**Historical record.** This preserves completed preparation and its dated evidence
limits before consolidation on 2026-10-15. Resume only from the active
[master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md). Old next-step directions
and authorization notes below are historical, not current instructions.

### P0 — Tracking draft (completed)

- [x] P0.1 Capture the objective, selected direction, profile exclusions, accounting
  candidate, evidence gaps, and approval boundaries in these two plan documents.
- [x] P0.2 Obtain a cold review for contradictory rules, accidental behavior changes,
  missing decision gates, and claims stronger than the evidence; reconcile findings.
  Three findings were corrected: exact manifest completeness, legacy local repair-event
  numbering, and preservation of unhealthy-skip routing records. This is a draft
  review, not resolution of D1–D8 or a conformance pass.
- [x] P0.G **Document gate:** verify linked paths and source anchors, review the changed
  files, and confirm that only intended planning/review documents were written.
  No runtime or fixture verification is implied by this gate.
  Passed at P0: both plan links and review links resolved, named evidence paths
  existed, formatting checks passed, and no tracked runtime files changed. No tests
  ran in that drafting step; execution subsequently continued into authorized P1.

### P1 — Bounded evidence audit and direction selection

- [x] P1.1 Read the current `DESIGN.md` and the source map. Build the rule inventory in
  the [P1 audit record](ANYINFER_P1_EVIDENCE_AUDIT.md), part of this plan, with four
  classifications: supported Python behavior, candidate addition,
  deliberate profile exclusion, or discrepancy requiring a decision. Record HEAD and
  distinguish static inference from directly tested behavior.
- [x] P1.2 Inspect and record source/test evidence and gaps for repair success/exhaustion,
  correction transport failure followed by
  original-request retry, provider repair ceilings, health skips, partial-stream failure,
  cleanup exceptions, lazy stream close, cancellation, and final observer delivery.
  Record missing tests without writing fixtures or fixing code in this tranche.
  > NOTE: Existing cases passed (302 across two targeted runs). Bounded probes verified
  > failed-correction restart/reset, zero-advance close, schema failure telemetry,
  > parser/usage behavior, and pricing. Cleanup-fault/cancellation races and the new
  > accounting contract remain unexecuted; they are identified source-only gaps.
- [x] P1.3 Resolve D1/D2/D3 sufficiently to draft observable requirements; identify any
  proposal that changes current externally visible behavior. Present those reversals
  separately for decision. Preserve the chosen restart and repair-budget behavior.
  > NOTE: User selected S1/F1/L1 in the linked walkthrough. C01/C02 are addressed by
  > parsing compatibility and semantic feedback, with detailed domain/evidence gates
  > retained. C03–C06 are addressed by observing native outcomes and deferring live
  > notifications/lifecycle revisions. C07–C09 still require evidence-preserving
  > observations and independent aggregation/pricing rules at D5/D8. No runtime
  > behavior or fixture file was changed. Source remains
  > `13b9e65acfb01038464069ca5fa80f50a9df035c`; no commit was created.
- [x] P1.G **Evidence gate:** every proposed mandatory rule has a source/decision and
  a planned observation; unresolved conflicts are named blockers, not inferred fixes.
  Stop and report the bounded audit before drafting assets outside `plans/`.
  > NOTE: Selected dispositions are reconciled across all four planning documents.
  > Independent review found no remaining substantive contradiction; local links,
  > fenced blocks, and whitespace passed the document gate. T6 persistence and live
  > notifications remain deferred. This closes evidence/direction selection only;
  > detailed specification verification and P2–P5 authorization remain separate.
  > Resume at P2.1 only within a subsequent go-ahead; source HEAD is unchanged and
  > no runtime changes, fixtures, or commit were created.

### P2 — Detailed planning, then normative specification (separate scopes)

- [x] P2.0 Draft concrete schema admission, repair-feedback comparison, and accounting
  lifecycle/error tables under `plans/`, using S1/F1/L1 and current Python evidence.
  Classify candidate choices and remaining gates explicitly. No runtime or fixture
  changes; normative publishing paths remain outside this authorization.
  > NOTE: Three linked draft documents supply the keyword/exclusion/admission table,
  > semantic issue/order/evidence record, and operation/call lifecycle/error matrix.
  > They retain numeric/Unicode, schema ownership, selected-feedback bridge,
  > ambiguous native cancellation/races, and postcommit continuation as explicit
  > verification gates. `validation_reason` and observation-stage/auxiliary-error
  > records are candidate amendments, not existing public fields.
- [x] P2.0G **Planning-table gate:** obtain a cold source/compatibility critique,
  reconcile the candidate/selection/audit pointers, verify local links and Markdown,
  and confirm that only planning documents changed. Stop at this reviewable draft;
  this gate does not freeze a profile or authorize P2.1 normative assets.
  > NOTE: Cold review's three findings were resolved and independently reread:
  > malformed dialect metadata versus caught schema feedback; provider acquisition
  > versus generate-method entry; actual ProviderError-only routing/conversions.
  > The audit records bounded review probes separately from P1's 302 existing tests.
  > Local links, fenced blocks, table columns, and whitespace passed. Source HEAD
  > remains `13b9e65acfb01038464069ca5fa80f50a9df035c`; no runtime/fixture/commit changes.
  > Resume at P2.1 only after further authorization and its detailed decision gates.

- [x] P2.0C Walk through the remaining N/U/I/C choices and record explicit selections
  in the detailed choice document. Reconcile the affected drafts after selections;
  distinguish encoding/evidence choices from any deliberate limitation of parity.
  > NOTE: User selected N1/U1/I1/C1. The linked choice owner records the alternatives
  > and remaining gates. I1's bounded exact malformed-feedback scope explicitly
  > qualifies F1 there; ordinary instance F1 and all native retry/repair/ledger
  > semantics are preserved. C1 changes cause reporting only, not control flow.
- [x] P2.0CG **Choice-document gate:** cold-review recommendations and dispositions,
  verify links/Markdown/scope, and leave remaining evidence/wire/API gates explicit.
  Stop after planning updates; no normative assets, runtime changes, or fixtures.
  > NOTE: Four preselection guardrails were incorporated: explicit I1 scope/results,
  > numeric observation versus schema equality, Unicode decoder/transport boundaries,
  > and C1 confirmed-cancellation-only reporting. Independent rereview found no
  > substantive contradiction after selections were reconciled. Local links,
  > Markdown tables/fences, whitespace, and repository scope checks passed. No new
  > runtime probe/test suite/fixture/implementation/commit was produced; HEAD remains
  > `13b9e65acfb01038464069ca5fa80f50a9df035c`. Resume at P2.1 only with further
  > authorization and its remaining evidence/wire/API/domain decisions satisfied.

- [x] P2.0I Draft I1's closed exact malformed-schema domain and scope/result reporting
  matrix under `plans/`. Separate native admission/late branches from comparison
  membership; preserve selected-error granularity and current restart/repair behavior.
  > NOTE: The linked I1 draft proposes only root required/type integer-kind 17, with
  > absent/canonical dialect and key-order variants. Null dialect metadata is a
  > warning-sensitive outside-domain control. Planned/observed schema membership,
  > scope, actual feedback evidence, independent behavior, and verdicts are separate.
- [x] P2.0IG **I1 planning gate:** obtain an independent source/compatibility critique,
  reconcile record/report ownership and all linked planning documents, verify local
  links/Markdown/repository scope, and stop with explicit identity/bridge/fixture gates.
  > NOTE: Cold review findings were reconciled and independently reread: null-metadata
  > warning policy, retained mismatched feedback evidence, linked historical wording,
  > and disjoint control/qualified verdicts. This is a document gate, not a native
  > behavior pass. Full selected-error identity, pinned reference environment/resources,
  > private evidence-seam design, and end-to-end histories remain open. No new runtime
  > probe/test/fixture/implementation/commit was produced; HEAD remains
  > `13b9e65acfb01038464069ca5fa80f50a9df035c`. Resume at P2.1 only with a further
  > go-ahead and its remaining decisions/evidence gates satisfied.

- [x] P2.0E Audit actual selected `SchemaError` identities for all six proposed R/T
  dialect/order shapes and declared warning policies, plus null-metadata selector
  branches. Bind caught-object evidence to the unmodified helper's feedback; record
  environment/resources and distinguish direct observations from generation inference.
  > NOTE: Root owns planning edits. Read-only scouts own disjoint exact-identity and
  > warning-boundary observations; no saved probe, fixture, or runtime change.
  > NOTE: The I1 helper audit records 30 helper invocations and six separate selector
  > calls, with discovery/independent checks separated from case counts. All six
  > R/T shapes have actual caught-object evidence under two declared policies;
  > null's nonfatal feedback versus exception before check_schema is directly
  > observed. These are helper results, not generation or full-conformance passes.
- [x] P2.0EG **I1 evidence gate:** independently check evidence strength and draft
  consistency, reconcile linked planning documents, verify local links/Markdown/scope,
  and retain private bridge/end-to-end/portable-classification gates. Stop after the
  evidence record; no automatic normative asset or implementation authorization.
  > NOTE: Independent cold review found no substantive contradiction or overclaim.
  > Local-link/Markdown/scope checks and all three recorded resource-byte hashes
  > passed. Only plans were written; no existing test suite, generation run, fixture,
  > implementation, artifact outside plans, or commit was produced. HEAD remains
  > `13b9e65acfb01038464069ca5fa80f50a9df035c`. Resume at P2.1 only with a further
  > go-ahead and its remaining decision/evidence gates satisfied.

- [x] P2.0N Observe native I1 histories through the real async generation core:
  exact-shape budget-zero/one exhaustion, distinct latest-only corrections, correction-
  provider failure followed by original restart/fresh local budget, extraction first,
  null warning policies, and cleanup failure before assessment. Capture actual
  request/evidence boundaries and legacy events without implementing accounting.
  > NOTE: Read-only scouts own the exact-shape matrix and restart/boundary probes;
  > root owns all planning writes, independent confirmation, and cleanup observation.
  > A static scripted model cannot place a correction-time failure or vary output;
  > use the existing response-sequence fake for those observations, not inferred traces.
  > NOTE: Native audit records 27 fully counted invocations (52 HTTP requests plus
  > four normalized-only adapter entries) and two additional setup-limited null runs.
  > It confirms exhaustion, latest-only corrections, four-call restart/reset, and
  > representative extraction/null/iterator-close boundaries. Direct selected-to-
  > entered-wire binding is T0; R0 retains prepared/HTTP evidence and an explicit
  > same-correction wire gap. Legacy failure telemetry remains unchanged.
- [x] P2.0NG **Native-history evidence gate:** cold-review observations and limits,
  reconcile linked plans, check local links/Markdown/repository scope, and retain
  unexecuted lifecycle/bridge/profile/transport gates. Stop after planning records.
  > NOTE: Cold review required narrowing representative full wire binding to T0;
  > R0's missing same-correction wire capture remains explicit. Rereview found no
  > unresolved substantive finding. Local links/Markdown/arithmetic/scope checks
  > passed; Python/fixture/legacy behavior is unchanged. Source HEAD remains
  > `13b9e65acfb01038464069ca5fa80f50a9df035c`; no commit was created.
  > Resume at P2.1 only with further authorization and its remaining decisions/gates.

- [x] P2.0O Walk through the private capture strategy and failure-mapping choices,
  obtain explicit selections, and record their meaning/alternatives under `plans/`.
  Keep private evidence capture distinct from public accounting and legacy telemetry.
  > NOTE: User selected O1 private opt-in capture points, M1 stage plus small semantic
  > failure families, and W1 leaving null metadata's portable reference condition open.
  > M1 was labelled F1 in this interview only; existing F1 repair feedback is unchanged.
- [x] P2.0OG **Observation-choice gate:** cold-review the minimum scope, failure
  isolation, classification versus verdict/terminality, and W1 freeze blocker;
  reconcile linked drafts and verify links/Markdown/scope. Stop after planning.
  > NOTE: Cold review's effective-base ambiguity was corrected: capture the actual
  > builder input after native preparation, not presumed caller input. Rereview
  > found no unresolved contradiction; private/public boundaries and M1 mismatch
  > precedence are explicit. Local links/Markdown/scope passed. No runtime probe,
  > implementation, fixture, or commit was produced; HEAD remains
  > `13b9e65acfb01038464069ca5fa80f50a9df035c`. W1 still blocks its affected freeze
  > decision. Resume at P2.1 only with further authorization and remaining gates met.

- [x] P2.0D Draft private capture records, context propagation, and capture-failure
  isolation under O1/M1. Preserve native expression/cleanup order, public signatures,
  actual effective repair base, and required uncertainty. Keep W1 open.
  > NOTE: The private capture design proposes immutable records/snapshots, explicit
  > per-operation capture_session with narrow task-local bindings, native router
  > handling/restart linkage, and sticky degradation with separate outward evidence.
  > Prepared/failed/interrupted/unentered corrections remain distinct. No public
  > API, accounting commit, or warning policy is selected by these draft details.
- [x] P2.0DG **Private design gate:** cold-review context ownership, lazy/foreign-task
  streams, snapshot/selection semantics, evidence-loss/fatal handling, record validity,
  and comparison/report compatibility; reconcile linked plans and document checks.
  Stop at a reviewable proposal; no implementation or fixtures.
  > NOTE: Cold review added actual router handling/predecessor evidence and narrowed
  > outcome-equivalence gates to controlled non-racing cases; opt-in timing cost is
  > explicit. Narrow rereview found no remaining contradiction. Linked feedback,
  > choice and lifecycle drafts are reconciled. Local-link/Markdown/scope checks
  > passed; only planning documents changed, with no new runtime probe/test, implementation,
  > fixture, external artifact or commit. HEAD remains
  > `13b9e65acfb01038464069ca5fa80f50a9df035c`. W1 and future implementation/evidence
  > gates remain open. Resume at P2.1 only with further authorization and its gates met.
