# AnyInfer — draft repair-feedback comparison record

> **Archived 2026-10-15.** Superseded by the revised [master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md)
> and [specification draft](../SPECIFICATION_DRAFT.md). Kept as input for milestone 3
> (operation accounting) and as rationale. Not an active plan; its checklists and gates do not apply.

**Status:** planning proposal for selected F1; no bridge, schema, or fixture implemented.
**Created:** 2026-10-14. **Evidence HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Resume/status:** [foundation plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Selected-policy owner:** the foundation plan.
**Related:** [schema admission](ANYINFER_SCHEMA_ADMISSION_DRAFT.md),
[lifecycle matrix](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md),
[P1 evidence](ANYINFER_P1_EVIDENCE_AUDIT.md).
The [I1 domain/reporting draft](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md) owns the
closed malformed-schema predicate and checkpoint scope/result matrix.

F1 compares the violations actually selected and included in a correction request
for admitted valid schemas. Selected I1 requires the same exact-defect comparison
within a declared bounded malformed-schema domain; broader invalid-schema detailed
feedback is explicitly qualified/not-covered rather than claimed fully equivalent.
Explanatory wording may differ. Python's existing messages, exact outer prompt,
original-request restart, target selection, and repair budgets remain intact.
This record is private conformance evidence, not new public telemetry or a production
diagnostics API. It may contain schema/value data only inside controlled test cases;
payload-free operation accounting must never embed it by default.
The foundation plan owns selected N1/U1/I1/C1 policy. Under I1 the record/report needs
explicit comparison scope and result:
declared exact malformed shapes can receive an exact-feedback result; other caught
invalid-schema cases remain qualified/not-covered for detailed feedback. Branch/
budget/history checks remain separate. A mandatory exact case cannot silently
downgrade when bridge evidence is missing. This is an explicit user-selected
qualification of invalid-schema feedback coverage; ordinary instance F1 is unchanged.

**Language path:** Python is the current baseline and Python plus C# are next proof
targets. The same portable feedback semantics, versioned data, and corpus requirements
apply to any admitted future native language, such as Java or JavaScript/TypeScript on
Node.js. Native SDK APIs may be idiomatic; Python rendering and exception identities are
evidence, not portable identifiers. No wire encoding or implementation library is chosen.

## 1. Comparison boundaries

| Boundary | Proposed comparison | Required evidence |
|---|---|---|
| Original request | Same original ordered schema snapshot, original message sequence, requested target/settings, and schema-name metadata. | Capture the real request; do not reconstruct it from eventual output or normalize its keys. |
| Invalid response | Same response observation and selected extraction/validation outcome. | Correlate with the actual invocation and assessment, including raw text echoed in the correction. |
| Selected issues | Same ordered semantic issue sequence and multiplicity, with at most five validator errors. | Evidence from the real selection boundary, attached to the strings used by `build_repair_messages`. |
| Correction construction | Actual effective base messages supplied to the builder + latest invalid response as assistant + exact outer user template; same resolved target/settings. | No accumulating earlier correction conversations. Do not substitute caller input for the effective native base. Python native error wording stays unchanged. |
| Adapter request | The correction containing that guidance reaches the actual adapter invocation. | Bind the record to captured `WireRequest` and correction call identity; provider transport projection is asserted separately. |
| No entered correction | Prepared guidance can exist even when an observer, wire build, pacing, or cancellation prevents adapter entry. | Report prepared-only evidence. Do not increment repair call count or claim feedback was sent to the provider. |
| Repair disabled/exhausted | The assessment may select feedback without constructing a correction. | Report assessment-only evidence; do not pretend a message was prepared or invoked. |

The effective base is the actual `original` argument to `build_repair_messages` for
that native outer attempt. `_run_attempt` can replace its local request through
proactive history compaction before using `request.messages`. History/context
reduction is excluded from the first profile; its controlled cases must establish
that scope. The private seam must still preserve broader Python preparation and
cannot infer the effective base or cross-attempt equality from caller input alone.

The exact outer template remains the current `REPAIR_PROMPT` in `schema/repair.py`:

```text
Your previous response did not match the required JSON schema. Errors:
{errors}
Respond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.
```

`{errors}` is the newline-joined `- ` list. The illustrative block preserves template
text; a later corpus must also assert newline/escaping and actual message boundaries.
Prompt schema injection/provider projection may add or transform other fields; that
does not authorize changing the correction suffix or validating a projected schema.

## 2. Proposed semantic record

Working record name: `RepairFeedbackComparison`. All fields describe one assessment
and its possible correction. Names/encoding/version IDs remain draft. Input ordering
is significant where noted; accounting snapshot canonicalization is a different rule.

| Field | Proposed meaning / validity |
|---|---|
| `comparison_revision`, `profile` | Immutable comparison-rule revision and bounded schema profile. No release identifiers assigned yet. |
| `operation_ref`, `route_attempt_ref`, `trigger_call_ref` | Driver-local correlation to the operation, outer attempt, and invalid response. Map to approved accounting IDs only if available. No dependency on a Python dataclass or UUID spelling. |
| `assessment_kind` | `extraction_failure`, `invalid_schema`, or `schema_violations`. Do not label a validator crash as ordinary feedback. |
| `schema_ref`, `value_ref`, `schema_order_ref` | References to controlled case data and the original assessment inputs/order. No requirement to repeat schema/output in public records. `value_ref` is null for failed extraction. |
| `selection_complete` | True only when the actual assessment/selection finished and the bridge observed it completely. False or unavailable evidence cannot pass semantic equivalence. |
| `total_issue_count` | Number of produced top-level issues before cap, if actually observed; null if unknown. Invalid-schema/extraction feedback is a separate one-issue path, not a fabricated validator enumeration. |
| `cap`, `selected_issues` | Validator cap five; ordered issues after actual sorting/truncation. Extraction/invalid-schema paths select their single issue. Retain duplicates/multiplicity. |
| `python_rendered_feedback` | Exact selected strings used by Python, in a controlled case. These are evidence, not the language-neutral equality key. |
| `correction_stage`, `correction_call_ref` | Draft stages: `not_scheduled`, `preparation_failed`, `preparation_interrupted`, `prepared`, or `adapter_invoked`. Correction call reference is required only for adapter_invoked. Not_scheduled requires evidence that the builder was never entered, including disabled/exhausted repair or an earlier native interruption; prepared requires successful message construction. Neither prepared nor invoked proves network dispatch or provider receipt. |
| `preparation_ref`, `stage_reason_evidence_ref` | Private linkage to actual builder entry/outcome when it occurred; evidenced reason for no entry or the actual preparation fault/interruption as applicable. Failed/interrupted preparation is not renamed not_scheduled. Absence from an incomplete/live record prefix cannot prove no builder entry. |
| `message_evidence_ref`, `wire_evidence_ref` | Driver evidence linking selected issues to the real constructed suffix and captured adapter request. Message evidence exists only after successful preparation; wire evidence exists only at invocation. Native absence differs from unavailable capture. HTTP serialization checks are a separate adapter boundary. |

Comparison scope and detailed result are owned by the enclosing checkpoint report
defined in the I1 draft, rather than embedded in this actual-evidence record. That
report can exist when no feedback was expected or actually produced; it never creates
a fake `assessment_kind` or selected issue. A planned no-feedback control has null
scope and `not_applicable` detail result; an unexpectedly missed exact checkpoint
cannot use that combination to escape its obligation. Actual unexpected feedback
records are retained and compared against the fixed plan, not used to rewrite it.

The two preparation-fault stages are draft amendments from the
[private capture design](ANYINFER_PRIVATE_CAPTURE_DESIGN.md), not SDK/ledger fields
or newly selected public behavior. They retain a completed assessment's real feedback
when its later builder faults. A missing/unresolved stage is unavailable evidence,
not a sixth native stage or an inferred not_scheduled. Message/wire/correction-call
references are absent for failed/interrupted preparation. A successfully prepared
message remains prepared if a later fault prevents adapter entry.

Each selected `SemanticIssue` carries:

| Field | Proposed meaning |
|---|---|
| `category`, `rule` | Extraction, invalid-schema, or validation category plus the exact semantic reason/keyword. Native exception/type names are not rule IDs. |
| `instance_path` | Ordered typed segments: object-key segment with exact string, or array-index segment with nonnegative integer. Empty sequence means response root. Null when the issue does not concern a decoded response location, including extraction and invalid-schema issues; an extracted response may still exist as assessment context. |
| `schema_path` | For ordinary violations, typed path to the assertion in the original schema. For invalid-schema feedback, the actual defective input-schema location from caught `SchemaError.path`, if available. Its meta-schema constraint path is separate private evidence, not the input path or a response path. Never invent paths by parsing prose. |
| `parameters` | Rule-specific typed data from the actual error/inputs, as listed below. Missing required parameters make comparison incomplete. |
| `enumeration_ordinal`, `selection_ordinal` | Actual pre-sort issue position and post-sort selected position. The former is null for non-enumerated feedback. Selection positions start at one. |
| `ordering_evidence` | Depth, typed path, relevance components, and stable tie provenance where applicable. It describes the chosen order; it does not replace observing actual selection. |

Typed values use the response-domain representation proposed in the schema draft;
no JSON nonfinite literal, host `repr`, or raw dotted-path string is an equality key.

## 3. Rule parameters and issue granularity

| Rule / category | Mandatory semantic parameters | Granularity |
|---|---|---|
| `type` | Expected single schema type; observed typed value/reference sufficient to establish the mismatch. | One issue at the failing instance path. Integral floats and boolean/number separation follow the schema draft. |
| `required` | One missing property name. | One issue per missing name; path points to the containing object, not the nonexistent child. |
| `additionalProperties` false | Complete set of unexpected property names, compared in exact string order. | One aggregate issue. Do not split it into one issue per key or consume multiple cap slots. |
| `enum` | Original ordered allowed values or a case reference to them, plus observed value/reference. | One issue, with JSON Schema equality rather than host generic equality. |
| `const` | Original expected value/reference and observed value/reference. | One issue. |
| `minimum`, `maximum` | Bound, inclusive relation, observed numeric value/reference. | One issue; numeric representation/equality cannot be silently rounded differently. |
| `minLength`, `maxLength` | Bound and observed Python-compatible length. | One issue; strings remain exact without normalization. |
| `minItems`, `maxItems` | Bound and observed array count. | One issue. |
| Empty extraction | `response_empty`. | One issue, no instance path. |
| No balanced candidate | `no_json_candidate`. | One issue, no instance path; distinct from empty text. |
| Malformed first candidate | `malformed_json_candidate`; candidate boundary evidence where observed. | One issue. Native JSON decoder's explanatory wording/offset format may differ; no later-candidate rescue. |
| Invalid original schema | `invalid_schema`; offending schema location/rule/value from actual meta-validation evidence. | I1 exact cases compare the selected caught defect, not any possible defect; insufficient evidence cannot pass. Outside the declared exact domain, any detailed feedback result is qualified/not-covered, with branch/budget/history checks separate. No fabricated issue for an uncaught fault. |

An uncaught validator-selection/assessment fault is not a fourth feedback category:
no completed selected-feedback record or fabricated correction is reported for it.
For example, malformed root `$schema` may fail before `check_schema()` is reached.
If an earlier extraction failure did schedule a correction, retain that earlier
record and entered correction count; the later assessment fault does not erase it.

Schema-path and parameter comparison preserves assertion identity even when two
messages look alike. Key `"0"` differs from index `0`; key `"a.b"` differs from two
segments `"a"`, `"b"`; missing `age` differs from missing `name`. Wording flexibility
does not permit changing the constraint or omitting guidance for a selected issue.

## 4. Selection/order rule proposed from current Python

Python runs `sorted(validator.iter_errors(value), key=jsonschema.exceptions.relevance)`
and then takes five. It does not use `best_match`, collect a recursive error tree,
sort rendered messages, or stop enumeration after finding five.

For the proposed assertion subset, the weak-combinator/strong-keyword components of
the installed relevance function do not add different priorities. Proposed portable
comparison order is: deeper instance paths first; then lexicographic instance path;
then the applicable type-match component; then stable original enumeration order.
Exact string ordering follows Python code-point ordering, not locale/case-folding
or C# UTF-16 ordinal order. Array indices use integer ordering. If a reachable case
has incomparable mixed segment types, preserve/classify Python's native fault rather
than inventing a new precedence; establish reachability before freezing the rule.

Enumeration ties are meaningful. Preserve original schema member order, nested
`properties` order, array order, and keyword-specific issue order. A future fixture
format must retain ordered schema input, explicitly carrying order if its parser/
reconstructor would otherwise lose it. Do not canonicalize schema keys before
feeding Python, or sort `required` names to create a cleaner order. This is separate
from object-key-order-insensitive equality of accounting snapshots.
Schema-prompt injection's separate serializer sorts keys; that does not sort the
original schema supplied to validation or remove its enumeration-order evidence.

The extra-property name set is sorted for its aggregate parameters. Two required
issues at the same object location preserve the original `required` array order.
Six missing names must yield the same first five selected names, not any five.
Invalid-schema meta-validator selection needs a separate rule and evidence; the
ordinary instance-error relevance key does not define it.

## 5. Private evidence bridge and failure to compare

Selected O1 uses private opt-in native capture with a harness-owned collector. The
[private capture design](ANYINFER_PRIVATE_CAPTURE_DESIGN.md)
now proposes records, explicit-session propagation with a synchronous helper frame,
and capture-failure isolation. These remain subject to the implementation gates;
no hook or public telemetry surface is implemented.

The proposed bridge observes actual selected `ValidationError` objects before
`_describe` discards them, or the actual caught `SchemaError`/extraction branch.
It associates that evidence with returned strings, the real repair message build,
and any later adapter invocation. It must preserve original strings, exceptions,
enumeration, sorting, budgets, and branch behavior. This is a future implementation
design, not authorization to monkeypatch or instrument production today.

| Observability result | Conformance disposition |
|---|---|
| Complete selection evidence linked to constructed and invoked correction | Compare the ordered semantic records and separately assert wrapper/history/target/settings. |
| Complete prepared evidence but correction never entered | Compare preparation if the case expects it; account zero additional correction calls. No claim of invoked correction. |
| Complete assessment with no correction scheduled | Compare selected assessment feedback when required by the case, without suffix/wire claims. No correction invocation exists. |
| Completed assessment followed by builder fault/interruption | Retain actual selected feedback and the distinct preparation outcome. No prepared-message or correction-invocation claim. Native fault handling remains unchanged. |
| Caught invalid-schema feedback outside I1's declared exact domain | Detailed feedback is qualified/not_covered even if captured issues are available; independently report expected branch/history/budget outcomes. Never summarize this as full invalid-schema selected-defect parity. |
| Revalidation produces a matching list | Insufficient evidence of actual selected/sent guidance. Do not count as a pass. |
| Generic prose parser or eventual successful response | Insufficient evidence. Ambiguous names/paths and validator selection can hide drift. |
| Bridge unavailable, incomplete, or throws | Report verification unavailable/failing as appropriate. Do not manufacture feedback or alter native generation behavior to obtain evidence. |

The [I1 helper audit](ANYINFER_I1_EVIDENCE_AUDIT.md) captures actual R/T selected
objects for all proposed variants and null's warning-policy branches. Its temporary
trace observer is audit evidence, not an implemented or approved private bridge.
The subsequent [native history audit](ANYINFER_I1_NATIVE_HISTORY_AUDIT.md) directly
binds T0 selected feedback to prepared and entered-wire corrections. R0 has actual
selected/prepared evidence and HTTP-body invocation correspondence; direct same-
correction schema-feedback wire binding remains open. Its extraction-first
trace proves that terminal errors can differ from earlier invoked repair guidance.

Open gates are approval/verification of the proposed bridge locations and fault isolation, actual schema ownership at assessment,
approval of the proposed I1 closed domain, portable mapping of the captured identities,
and complete all-variant/stage assessment/message/wire binding beyond those observations,
typed-value wire/equality, schema-order carrier, and the complete set of parameter
extractors. Source anchors: `schema/validate.py:validate/_describe/format_errors`,
`schema/repair.py:build_repair_messages`, `_client/generation.py:_validate/_run_attempt`,
and installed `jsonschema` 4.26.0 `exceptions.by_relevance`, `validators.iter_errors`,
and `_keywords`. No public payload-bearing feedback API is selected.
