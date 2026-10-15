# AnyInfer — I1 exact malformed-schema domain and reporting draft

> **Archived 2026-10-15.** Superseded by the revised [master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md)
> and [specification draft](../SPECIFICATION_DRAFT.md). Kept as input for milestone 3
> (operation accounting) and as rationale. Not an active plan; its checklists and gates do not apply.
> Retired by decision A5 (one invalid_schema issue, wording free) and A6 (pure-function issue seam).

**Status:** closed-domain planning proposal under selected I1; not frozen or implemented.
**Created:** 2026-10-14. **Evidence HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Scope:** Markdown planning documents only. No fixture, schema asset, driver, or runtime change.
**Resume/status:** [foundation plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Selected-policy owner:** the foundation plan.
**Record owner:** [repair-feedback comparison](ANYINFER_REPAIR_FEEDBACK_DRAFT.md).
**Related:** [schema admission](ANYINFER_SCHEMA_ADMISSION_DRAFT.md),
[lifecycle/error matrix](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md),
[evidence audit](ANYINFER_P1_EVIDENCE_AUDIT.md). Supporting historical evidence:
[I1 helper audit](ANYINFER_I1_EVIDENCE_AUDIT.md) and
[native-history audit](ANYINFER_I1_NATIVE_HISTORY_AUDIT.md).

This file owns the proposed exact I1 shape predicate, checkpoint/reporting matrix,
and coverage requirements. I1 is already selected; these particular shapes and
field spellings remain draft. Actual selected identities are now captured at the
helper boundary; portable identity mapping, approved evidence binding through the
generation core, and the rest of the freeze gates remain open.

**Language path:** Python is the current baseline; Python and C# are next proof targets.
The closed six-shape I1 proposal and its qualified outside-domain feedback apply as
portable semantics to any admitted future native language, including Java or
JavaScript/TypeScript on Node.js. Each native parser, warning control, numeric, and
Unicode rule requires an explicit mapping. Native exception/type identities are not the
contract; SDK shapes may be idiomatic, while versioned data and the shared corpus remain
common. A future driver reports its own environment/source and matches the upstream
bundle; it does not require installed Python/.NET or host-environment equality. No wire
encoding or library is selected.

## 1. Keep three classifications separate

| Classification | What it answers | What it must not do |
|---|---|---|
| S1 feature admission | Is this request within the bounded generation profile? | I1 membership cannot change preflight rejection, schema validity timing, or Python's broader API. |
| I1 input-shape membership | Does a given schema value match the closed predicate below? Apply it separately to the planned input and observed schema at assessment. | Membership is computed for comparison/reporting, not as a new runtime validation gate. The fixed planned scope cannot be rewritten by an observed defect or an implementation's schema rewrite. |
| Planned/observed assessment | Was extraction, caught invalid-schema feedback, an uncaught assessment fault, or an earlier failure expected/observed here? | A malformed schema alone does not prove meta-validation was reached or that any feedback was sent. |

An S1-admitted schema outside I1 still follows native execution; its caught invalid-
schema detailed feedback is qualified/not-covered. An S1-excluded feature retains
its declared profile exclusion, rather than becoming an I1-qualified late schema
error. A mandatory exclusion test still checks the unsupported outcome before
inference; it is not a skipped test or detailed-feedback pass.

## 2. Closed exact-domain predicate

Working domain label: `i1-root-single-defect`. A published immutable domain revision
is unassigned. Before conformance use, its reference must resolve this complete
predicate, admitted dialect/default rules, semantic defect rules, and evidence
baseline; do not identify a domain only by a mutable filename or validator version.

Let `D` be the exact decoded string `https://json-schema.org/draft/2020-12/schema`.
Let `J17` be the decoded **integer-kind** value 17. `17.0`, a boolean, numeric text,
and any other integer are not J17. Shape matching must not use host numeric equality
that equates integers, integral floats, and booleans. Use N1's value-kind distinction.

All exact members are original schema objects satisfying one row:

| Family | Entire permitted root key set | Exact values | Dialect/order variants |
|---|---|---|---|
| R — malformed required | Only `required`, or only `required` plus `$schema`. | `required` is J17. If `$schema` exists, it is D. | Absent or explicit dialect are separate variants. With both keys, both insertion orders belong; preserve the actual order. |
| T — malformed type | Only `type`, or only `type` plus `$schema`. | `type` is J17. If `$schema` exists, it is D. | Same absent/explicit and insertion-order treatment as R. |

No other key, annotation, nested schema, additional defect,
or alternate decoded value belongs to this draft domain. The predicate concerns
the coerced original schema value, not serialized whitespace or spelling of JSON
escapes. External schema-name metadata and other request controls do not alter
membership, but their existing effects on messages/wire/route must still be asserted.

The absent-dialect variants are bound to the audited default behavior; a future
default change cannot be hidden by injecting `$schema` into the request. Pin the
reference environment/default before freezing those variants, or explicitly revise
the domain rather than silently dropping them. The reference environment must bind
`jsonschema`, the `jsonschema-specifications` package and actual meta-schema resources,
validator selection/registry defaults, format-checker defaults, and warning policy.
The installed packages inspected here are 4.26.0 and 2025.9.1 respectively; version
numbers alone do not establish the complete environment or selected-error identity.

`$schema: null` is deliberately outside the exact set. Installed `validator_for`
can warn before reaching the caught `check_schema` branch, and the repository's
pytest configuration treats warnings as errors. The earlier caught-feedback helper
observation therefore does not establish a uniform branch across warning policies.
The subsequent I1 audit directly observed both caught feedback under a nonfatal
policy and a warning exception before `check_schema` under an error policy.
Define the reference environment and expected branch before running that boundary
control; do not suppress warnings or change Python policy to make it fit. This
environment binding is not a new public SDK warning option or a universal host-runtime
warning policy. Portable classification of a native warning promoted to failure remains a
gate; a Python warning class is not automatically a portable error code.

For controlled conformance cases, schema inputs must remain stable. Compare against
the actual original schema snapshot used at each assessment, with evidence binding
it to the fixed case input. Keep planned and observed memberships separate. A proved
schema value/order change fails the preservation check; it cannot downgrade an exact
case or upgrade a qualified case. If mutation or an incomplete bridge makes the
observed value/order uncertain, report observed membership/evidence unresolved and
block the affected exact claim without changing its planned scope.
Do not add a runtime deep-copy or mutation policy as an instrumentation fix.

### Deliberate outside-domain boundaries

| Input difference | Classification |
|---|---|
| `required` is integer 18, floating 17.0, false, or an array containing a non-string | Outside exact I1. If the reference reaches caught invalid-schema feedback, detailed comparison is qualified/not-covered. Do not assume a branch without reference evidence. |
| Both `type` and `required` are malformed | Outside exact I1, even when both individually resemble covered defects. No permission to accept whichever complaint a validator chooses. |
| A valid `title`, `description`, `properties`, or other admitted sibling is added | Outside exact I1, even if only one defect remains. This is a comparison limit, not a new unsupported runtime request. |
| The same bad value appears inside `properties` or `items` | Outside exact I1. Typed nested paths are not implied by root coverage. |
| Root schema is exactly `{"$schema": null}` | Outside exact I1 and warning-sensitive. The I1 helper audit observed caught feedback under a nonfatal-warning policy and an escaping warning before `check_schema` under an error policy. Caught detailed feedback remains qualified/not-covered. Bind the fixed reference environment and verify native generation controls; an unknown environment blocks the control rather than choosing its expectation from the observed result. |
| Root `$schema` is array, object, or integer | Outside exact-feedback I1; the existing review observed escaping validator-selection faults for representative values. These require no-feedback branch controls, not fabricated invalid-schema issues. |
| A different dialect string, nested dialect switch, or excluded keyword is present | Use S1's declared feature-exclusion rule. An admitted bad sibling does not erase that profile boundary. Raw Python behavior remains unchanged. |
| No schema, a valid admitted schema, or an SDK coercion failure | I1 does not apply. Ordinary generation/F1 or the existing preacceptance error path supplies the expectation. |

This small domain can be expanded only through an explicit revised predicate and
coverage/evidence review. Never infer closure under adding annotations, moving a
defect, changing its value, or combining individually covered forms.

## 3. Selected-defect identity and evidence strength

The [I1 helper audit](ANYINFER_I1_EVIDENCE_AUDIT.md) captured actual caught
`SchemaError` objects and feedback for all six R/T dialect/order shapes under two
declared warning policies. It confirms the primary identities below, including T's
ordered child context. Null's policy-dependent helper branches were also observed;
that boundary remains outside exact membership. That helper tranche did not verify
generation histories. The later native audit observes exhaustion across all shapes,
T0 selected/prepared/entered-wire binding, R0 selected/prepared evidence with HTTP
invocation correspondence, restart/reset, and cleanup/null boundaries. Direct R0
schema-feedback wire binding, a production bridge, portable semantic extractor, full
all-variant native object/order evidence, and full exact-feedback baseline remain open.

| Family | Input-schema defect location | Observed helper primary constraint | Evidence still needed before freeze |
|---|---|---|---|
| R | Typed object-key path `required`. | Array-type requirement for the `required` keyword value; primary keyword `type`, required kind array, empty context. | Portable semantic mapping and actual assessment/prepared/invoked binding through the native core. Helper fields/feedback for all variants are in the audit. |
| T | Typed object-key path `type`. | Meta-schema `anyOf`: a recognized simple-type string OR a nonempty unique array of recognized simple-type strings. Primary is the aggregate wrapper with ordered enum then array-type children. | Preserve the observed wrapper/alternatives/context in portable mapping and native feedback binding. Do not flatten it into R's array-type error or count children as separately selected feedback. |

All rows produce one selected caught-error issue when that branch is reached; the
ordinary five-instance-error cap does not turn a wrapper and its children into
multiple feedback bullets. Native explanatory wording may differ, while the covered
selected constraint and location must match.
T's internal meta-schema `anyOf` is separate from S1's exclusion of caller-supplied
combinators. That exclusion cannot remove a covered malformed-type obligation, and
this observed wrapper does not expand caller feature admission.

For ordinary violations, the feedback record's schema path locates the assertion.
For I1 invalid-schema feedback, it locates the defective input via `SchemaError.path`;
the response-instance path is null. `SchemaError.schema_path` identifies the meta-
schema constraint and remains separate evidence. Preserve aggregate structure where
relevant. Library-specific pointer indices are not automatically universal rule IDs.

The future private bridge must observe the actual caught primary error, preserve
Python's string, and bind that error to the selected feedback and any real correction
invocation. Revalidation, a normalized leaf chosen from `context`, or a matching
final exception string is insufficient. Unknown identity blocks exact verification;
it cannot downgrade a mandatory exact member into qualified coverage.
The foundation plan owns O1's selected capture direction and M1 failure mapping.
Under selected W1, null
metadata's portable expected condition remains unresolved and blocks that part of
profile freeze. Its fixed-policy Python reference controls remain valid evidence;
classifying their observed failures is not choosing a portable expected branch.

## 4. Reporting unit and proposed fields

The reporting unit is a **planned checkpoint**, not an operation, call, issue, or
snapshot. A case can contain several checkpoints across original/correction/retry
calls. Fix expected checkpoint order/requiredness in the case definition before
execution; preserve unexpected actual checkpoints and fail the relevant sequence
assertion instead of discarding them. New wire fields/enum spellings remain proposals.

| Report field | Proposed semantics |
|---|---|
| Case/checkpoint identity, profile/comparison revision, domain reference | Stable driver-local identities and immutable rule references. No published values assigned here. Domain reference is required when claiming I1 coverage. |
| Reference-environment binding | Fixed baseline identity/configuration covering validator/resources/defaults and warning policy; retain evidence of the actual environment. Branch expectations are set before execution. An environment mismatch or unknown binding blocks a reference claim; do not adapt expected branches to make the observed run pass. |
| Planned/observed schema references and memberships | Separate fixed case input from actual assessment snapshot/order. Each membership is inside/outside/unresolved. Expected scope uses planned membership; observed membership/value/order confirms binding or exposes schema-preservation mismatch. Missing actual evidence cannot rewrite the plan. |
| `expected_branch`, `observed_branch` | Separately retain extraction feedback, caught invalid-schema feedback, instance feedback, assessment fault, earlier provider/cleanup failure, or pre-inference profile exclusion, as actually evidenced. Do not derive a branch just from a missing feedback record. |
| `comparison_scope` | `exact_extraction`, `exact_instance`, `exact_invalid_schema`, or `qualified_invalid_schema` for planned feedback checks. Null only for a planned no-feedback control. Exact-invalid scope requires planned inside-domain membership and expected caught feedback; membership alone is insufficient. An exact match additionally requires actual input/selection evidence binding. |
| Actual feedback record reference | Nullable. Required for an exact match and whenever selected feedback is sufficiently captured to establish a mismatch, including unexpected feedback in a no-feedback control. Null is permitted for an actually observed no-feedback/fault branch or incomplete evidence that cannot supply the record. Retain any available partial evidence separately; never manufacture a `RepairFeedbackComparison` for a fault or uncaptured identity. |
| `detailed_feedback_result` | `matched`, `mismatched`, `not_covered`, `evidence_unavailable`, or proposed `not_applicable`. The last is reserved for a predeclared no-feedback control; it is not an escape for an exact checkpoint that was unexpectedly missed. |
| Independent behavior results | Branch/order, original-schema preservation, original/correction messages, target/settings, budget/call counts, terminal behavior, and accounting expectations each report matched/mismatched/evidence_unavailable/not_applicable. Not-applicable requires the check truly be outside that predeclared checkpoint. |
| Evidence/reason references | Distinguish missing bridge, wrong branch, wrong selected constraint/path, wrong order/multiplicity, and expected earlier termination. Keep payload-bearing case evidence private; do not add it to default accounting telemetry. |

This report wraps actual feedback evidence; no-feedback controls have no feedback
record. Scope/result metadata belongs to this enclosing report, not the evidence
record itself. An unexpected actual record is retained without overriding its planned
checkpoint scope. A reference baseline is also subject to these evidence requirements; Python
cannot pass exact comparison merely because it supplies the initial strings.

## 5. Scope/result matrix

| Planned checkpoint | Actual evidence | Detailed result | Required disposition |
|---|---|---|---|
| Exact I1 caught feedback | Complete actual selected defect matches covered primary constraint/path/parameters | matched | Exact feedback obligation met; other required behavior checks still determine the case verdict. |
| Exact I1 caught feedback | Wrong primary constraint/path/grouping/multiplicity is established | mismatched | Fail; do not substitute a convenient child, choose another schema defect, or downgrade scope. |
| Exact I1 caught feedback | A wrong feedback/fault/early-rejection branch is established where the case requires assessment | mismatched | Fail branch and feedback obligations. Captured wrong feedback requires its actual record; null is allowed only for fault/early/no-feedback or incomplete feedback identity, with available evidence retained. Do not fabricate an issue record for a no-feedback fault. |
| Exact I1 caught feedback | Bridge/identity/actual-schema evidence is missing or incomplete | evidence_unavailable | Block exact verification. A separately established behavior mismatch still makes the case fail. |
| Qualified outside-domain caught feedback | Branch/history/budget evidence matches; native defect may differ | not_covered | Qualified branch coverage only; never exact or general invalid-schema selected-defect parity. |
| Qualified outside-domain caught feedback | A required branch/history/budget behavior is wrong | not_covered | Case fails its independent obligation; lack of detailed coverage cannot hide a known behavioral mismatch. |
| Planned extraction failure, including before later invalid-schema assessment | Captured actual extraction reason and correction behavior | Exact-extraction result under F1 | Compare extraction at this checkpoint. Later caught feedback/fault gets its own expected checkpoint and I1 membership. |
| Planned provider/cleanup/assessment fault before any selected feedback | Expected no-feedback branch and all required native behavior are observed | not_applicable | No-feedback control may pass. Inside-domain membership alone earns no exact-defect coverage. |
| Planned no-feedback control | Unexpected feedback or correction is established | mismatched | Fail the no-feedback/behavior obligation; retain actual unexpected feedback without claiming expected I1 coverage. |
| Any mandatory checkpoint | Required observations are missing; no proved mismatch | evidence_unavailable for an exact detail obligation; retain not_covered for qualified detail or not_applicable for a planned no-feedback detail check | The missing independent behavior check reports evidence_unavailable and blocks the case. Missing required evidence is neither a pass nor a scope exclusion. |
| Required S1 exclusion control | Correct declared unsupported outcome before inference | not_applicable | Control can pass; zero provider calls where expected. Do not convert it into an excluded/skipped mandatory case. |

For extraction/ordinary-instance checkpoints, existing F1 exactness still applies.
`not_applicable` and `not_covered` have different meanings: a planned no-feedback
branch versus deliberately unclaimed detailed invalid-schema comparison. Neither
increments an exact-feedback match count.

## 6. Native behavior and mandatory coverage intent

Do not prevalidate the schema at request acceptance or stop repairs because an
invalid schema cannot be fixed by a model response. Existing Python attempts repair
when it has errors and budget. All semantic verdicts must be tied to the real native
core and scripted/controlled adapter; a harness must not implement another repair loop.
Provider rejection/cleanup can prevent late assessment, so use an appropriate
controlled adapter to establish core assessment behavior rather than assuming a
hosted provider accepts malformed schemas.

Required conformance coverage, before claiming this domain implemented (the native
audit supplies bounded observations, not fixtures or a completed coverage gate):

- Each R/T family reaches caught meta-feedback after successful provider cleanup.
  Cover every permitted dialect/order variant, not only one representative.
- With repair off/zero and with one available correction, preserve the original
  schema, exact outer template, selected semantic defect, original-plus-latest-response
  conversation, resolved target/settings, local event count, and exhaustion behavior.
- Extraction failure first, then parsed output on correction: the first checkpoint
  is exact extraction; the second reaches its own caught-schema or assessment-fault
  expectation. Preserve prior records/counters when the later assessment faults.
- Provider/cleanup failure before assessment: expected no-feedback control. A captured
  terminal response does not force validation past a cleanup exception.
- A correction provider failure re-enters outer retry with the original request and
  fresh local repair budget. For R, two route attempts with repair budget one can
  produce four entered calls, two corrections, and legacy repair numbers 1 then 1.
  If c1/c3/c4 all parse and reach the same invalid-schema feedback while c2 is a
  retryable provider failure, c4 exhausts as schema failure: no successful result.
  R0/T0 and an independent traced R0 run now directly observe this history in the
  native audit; it remains distinct from a portable conformance-fixture pass.
- Out-of-domain value/sibling/nesting/compound boundaries and malformed `$schema`
  faults are reported with the correct scope and actual native branch. Include S1
  exclusion precedence and mandatory evidence-missing/wrong-defect reporting cases.
- The null-metadata boundary has separately predeclared controls for nonfatal-warning
  and warnings-as-errors reference environments. Do not count either as exact I1
  feedback coverage, invent a portable warning category, or accept an unevidenced
  environment-dependent branch. Both helper branches are now observed in the linked
  helper and native audits. Portable fault mapping and the full profile gate remain
  unverified; explicit native policies did not change Python's warning defaults.

Schema exhaustion is `SchemaViolationError`, not a `ProviderError` retry/fallback
trigger. An uncaught assessment fault is not a fabricated schema-feedback repair.
Only the native caught provider-error path/predicate/budget controls outer retry;
keep its existing timeout conversion and partial-stream rules. Do not make a new
request-wide repair budget. Legacy ledger/events/manifests/result access retain their
meanings; proposed per-call/aggregate accounting is separate and not implemented here.

## 7. Case verdicts and report totals

Each case gets exactly one verdict, with proved required mismatches taking precedence
over missing evidence. A case can match exact feedback yet fail history/budgets.

| Verdict | Required meaning |
|---|---|
| `exact_pass` | All applicable required checks are evidenced/matched; at least one exact feedback checkpoint is met; no qualified detailed checkpoint occurs. No-feedback subchecks add no exact coverage. |
| `qualified_branch_pass` | All required behavior/exact subchecks match, but at least one detailed malformed checkpoint is qualified/not-covered. Not a full feedback-parity case. |
| `control_pass` | All required checkpoints are predeclared no-feedback or feature-exclusion controls and match all obligations; no exact or qualified detailed-feedback checkpoint belongs to that case. A mixed qualified-feedback/control case uses qualified_branch_pass when all checks match. |
| `failed` | Any required behavioral/selected-feedback expectation is proved wrong, regardless of other matches or missing evidence. |
| `blocked` | No proved mismatch, but required membership/branch/bridge/identity/sequence evidence is unavailable. Missing mandatory capability is not silently omitted. |
| `not_in_run_profile` | Case deliberately outside the declared run profile. It cannot contain a mandatory obligation of that profile; required unsupported-feature controls are never put here. |

Report case counts by these verdicts, and checkpoint counts separately by scope and
detailed result. Never sum calls, issues, or repeated snapshots into either count.
Required checkpoint counts must reconcile with the predeclared cases; missing or
extra actual checkpoints remain visible in sequence/behavior failures.

Every profile report names the immutable exact-domain reference and its evidence
baseline, lists required variant/check coverage and missing/blocked items, and states
that **general invalid-schema selected-defect parity is not claimed under I1**.
All current required cases passing does not broaden that claim. A source-inspected
or direct-helper-only baseline is not an end-to-end exact-feedback conformance pass.
An exact-extraction match or no-feedback control cannot fill a missing exact-invalid-
schema family/variant obligation. A run-wide I1 conclusion must fail for a required
mismatch and remain blocked for missing required evidence/coverage; otherwise it may
verify only the declared I1 scope, never general malformed-schema feedback parity.
An existing-behavior-only I1 audit must name that limited run scope. It cannot count
unimplemented mandatory operation accounting as passed or move it outside a full
generation profile merely to obtain a green I1 report.

## 8. Conditions before freeze or fixtures

| Gate | Needed evidence / disposition |
|---|---|
| Domain approval/version | Review this exact predicate and deliberately narrow scope; assign immutable profile/domain/comparison references only at the later publishing gate. |
| Reference environment | Bind validator and specification-resource versions/identities, defaults, and warning policy; verify null-metadata controls under their predeclared environments and settle portable failure classification without changing native policy. |
| Full selected identity | The audit captures helper objects/paths/context for all variants. Approve portable semantic mapping and bind actual native-core assessment/prepared/sent feedback without surrogate revalidation; resolve discrepancies before freezing aliases. |
| End-to-end native behavior | The native audit observes buffered histories and representative actual binding. Complete all-variant input/order/field evidence, prepared-but-not-invoked controls, remaining admitted lifecycle/mechanism cases, and portable corpus verification through the real core. |
| Report consistency | Verify nullability/scope/result/verdict combinations, exact versus qualified counts, mandatory cases/variants, and mismatch-over-blocked precedence. |
| Nonbreaking evidence seam | Approve the private bridge/API design without changing strings, exceptions, scheduling, budgets, legacy outputs, or default payload logging. |

Source anchors relative to `src/anyinfer/`: `schema/validate.py:validate`,
`schema/repair.py:build_repair_messages`, `_client/generation.py:_validate/_run_attempt/_route_events`,
and `errors.py:SchemaViolationError/ProviderError`. Installed static references:
`jsonschema/validators.py:check_schema`, `_keywords.py:anyOf/type`,
`exceptions.py:_Error`, and `jsonschema_specifications/schemas/draft202012/`
`metaschema.json` plus `vocabularies/core` and `vocabularies/validation`.
Warning-policy anchors are installed `validators.py:validator_for` and repository
`pyproject.toml:[tool.pytest.ini_options].filterwarnings`.
The original drafting tranche produced no runtime probe or fixture. Subsequent
bounded helper observations are recorded in the I1 audit; no implementation,
fixture, or end-to-end conformance run followed.
