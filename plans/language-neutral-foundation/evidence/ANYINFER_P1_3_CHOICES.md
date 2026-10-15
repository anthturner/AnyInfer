> **Historical supporting record.** Current decisions, language roadmap, readiness,
> and execution order belong to the [active master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
> Old alternatives, next-step directions, and authorization notes below are not current instructions.

# AnyInfer P1.3 — conservative decision walkthrough

**Status:** user selected S1/F1/L1; directions settled, detailed specification not frozen.
**Created:** 2026-10-14.
**Scope:** planning documents only. No runtime changes, fixtures, branch, commit, or release.
**Resume/status owner:** [foundation plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Evidence:** [P1 audit](ANYINFER_P1_EVIDENCE_AUDIT.md), source HEAD
`13b9e65acfb01038464069ca5fa80f50a9df035c`.

The conservative objective is a small shared surface whose claims are testable,
while preserving the selected Python restart/repair budgets and legacy result,
telemetry, manifest, and ledger semantics. This walkthrough separates schema
admission, response parsing, repair feedback, and accounting finality; choosing a
cleaner rule in one area must not silently change behavior in another.

The user selected the recommended direction for each question in the structured
P1.3 walkthrough. This settles the shape of the next specification draft without
freezing its keyword table, wire representation, SDK API, or conformance expectations.
This file owns those three selections; the other planning documents link to them.
The accounting companion incorporates L1 but remains a candidate behind its gates.
Later [N1/U1/I1/C1 selections](ANYINFER_P2_DETAIL_CHOICES.md) refine these directions.
I1 explicitly limits detailed invalid-schema feedback equivalence to a declared exact
domain; ordinary valid-schema instance feedback retains F1. C1 reports unknown cause
only for confirmed native cancellation. These are documented refinements, not a new
retry/repair or lifecycle policy.

## How the baseline JSON is used, and what is reused

The proposed baseline is versioned contract and conformance data. A fixture describes
an input request, scripted provider observations/failures, and expected requests,
events, results, errors, or accounting snapshots. Each language's test driver reads
the same fixture, feeds the native engine, and compares the observed behavior. The
driver interprets the test scenario; the production engine implements the specified
retry, repair, routing, and lifecycle rules in native code. No production policy
interpreter, deterministic runtime generator, or Protobuf foundation is selected.

Three different schema/data layers must stay distinct:

| Layer | Purpose and consumer | Reuse boundary |
|---|---|---|
| Caller-supplied structured-output schema | Tells the core how to validate a model response; a native adapter may project it into a provider request. | D1/S1 bounds the schema domain for parity. Validation, projection, extraction, and repair behavior still need native implementations. |
| Kit schemas and baseline fixture JSON | Describe portable record shapes and test scenarios; validators/test drivers consume them. | Shared across languages. D1's model-output keyword subset does not restrict the kit's own meta-schemas. Fixture data does not become a production routing/repair program. |
| Optional shared provider/capability/preset data | Supplies declared endpoints, options, or capability facts where a future profile needs them. | Export only explicitly modeled data with source/provenance ownership. The first proof does not promise a portable export of the whole registry. |

Retry, repair, and lifecycle are implemented once in each language's core and used
by that core's providers. They are not separate implementations for every provider.
Many compatible services can use one native adapter with declarative presets; distinct
protocols still need native request/response translation. A provider contract can be
shared without making its executable adapter language-neutral.

Optional code generation could later derive types, codecs, or tables from approved
machine-readable definitions. Protobuf could later encode selected records if a
wire/interprocess use case justifies it. Neither supplies the behavioral rules or
replaces conformance, and neither is required for the selected native-port approach.

There is no defensible code-reuse percentage yet: no cross-language code inventory
or port exists. The intended shared assets are the upstream contract and conformance
data; most executable runtime code is native per language. Estimate implementation
effort separately from shared data once the bounded profile and proof are concrete.

## D1 — Schema domain and response parsing

Audit conflicts: C01; baseline rules B04–B10 and parser probe P4.

| Choice | What it means | Cost / boundary |
|---|---|---|
| S1 — bounded schema subset, Python parsing baseline (**recommended**) | Version a small admitted schema domain, then reproduce the observed extraction/parsing behavior for responses within that domain. | More parser-compatibility work than finite-only JSON, but no silent change to audited repair outcomes. Broader Python schema support remains outside the first parity claim. |
| S2 — stricter portable response policy | Select strict finite JSON parsing and explicitly document the response-domain differences, or plan a separately approved opt-in Python policy. | Simpler parser contract; duplicate/nonfinite handling can change success/repair outcomes even for valid requests. This is not merely an unsupported schema keyword. |
| S3 — full Python schema/parser surface | Attempt compatibility with the currently accepted schema dialects/keywords and parser behavior. | Largest validation and feedback burden; ties the first port to more library-specific behavior and makes a small proof harder. |

S1 separates two contracts:

- **Schema admission:** specify the dialect and allowed validation/annotation keywords.
  A candidate starting point is an explicit 2020-12 subset for types, object properties/
  required/additional-properties, arrays/items, enum/const, and simple bounds. References,
  combinators, regex/format behavior, and other keywords need explicit inclusion/exclusion.
  This is a proposed starting point, not an approved keyword list.
- **Response parsing:** preserve whole-text parsing then the existing first balanced
  object/array fallback, scalar roots, duplicate-key last-value behavior, and audited
  nonfinite/overflow cases. Do not improve the scanner or reject those cases without
  declaring a compatibility change.

For example, `42` can parse as a scalar, `{"a":1,"a":2}` becomes `{"a":2}`, and
`NaN` can parse as a nonfinite number in Python. A strict alternative may issue a
correction where Python accepts the parsed value. Schema admission alone cannot
make that response-level difference disappear.

An unsupported schema feature and an admitted-but-invalid schema are distinct.
Python coercion does not establish schema validity; validation errors can be found
after inference and can enter repair. Choosing S1 does not authorize moving Python
schema validation into preflight or converting those errors into constructor failures.
Explicit first-C# admission rules must not be mistaken for the behavior of Python's
broader API.

**Before freeze:** exact dialect/keywords/annotations, invalid-schema timing, reference/
format policy, numeric/Unicode boundaries, and a portable expectation representation
for nonfinite/native values. No parity claim while these cases are undefined.

## D2 — Repair-feedback equivalence

Audit conflict: C02; baseline rules B06/B08 and restart probe P3.

| Choice | What it means | Cost / boundary |
|---|---|---|
| F1 — equivalent selected violations, wording may differ (**recommended**) | Match the actual selected violations and correction strategy; preserve Python's current strings and allow language-specific explanatory wording. | Needs a verified semantic bridge, but avoids making one validator's prose the permanent cross-language interface. Do not claim byte-identical correction prompts. |
| F2 — exact versioned common renderer | Specify identical feedback rendering for the admitted schema domain, reproducing current Python messages or separately revising prompt behavior. | More renderer/escaping/order work and stronger coupling to current messages. A formatter that changes Python wording is a separately visible change. |
| F3 — opaque native feedback | Test validation/repair budgets and final outcomes without strong feedback equivalence. | Lowest comparison effort, weakest ability to detect cross-language drift in what the correction asks the model to fix. |

F1 still requires the exact outer `REPAIR_PROMPT` template, original messages plus
only the latest invalid response, the same resolved target/request settings, and
the selected five-error cap. Wording differences do not excuse missing or different
violations.
The later I1 selection qualifies this claim for malformed original schemas: detailed
selected-defect parity is required only in its declared exact domain. Other malformed
feedback is explicitly qualified/not-covered, with native branch/history/budget
behavior separately reported. Do not summarize that qualification as full F1
invalid-schema feedback parity.

For the missing `age` example, Python currently sends
`- <root>: 'age' is a required property`. Another renderer may say that the root object
is missing `age`, while conveying the same required-property violation. Both must
be traceable to the guidance actually included in the correction request.

Normalized comparison needs keyword/rule identity, typed instance-path segments,
relevant typed parameters, and an explicit relevance/tie-selection/order rule. An
object key `"0"` and an array index `0` are not interchangeable paths. Selection and
the cap matter when more than five violations exist.

**Before freeze:** prove a private/test-only bridge from Python's actual selection-
to-prompt boundary to the comparison evidence. Current `validate()` returns rendered
strings and discards the structured `ValidationError` objects. Re-validating the
response independently, parsing ambiguous prose generically, or observing eventual
success does not prove equivalence of the selected/sent feedback. This direction
does not authorize a new public diagnostics API, changed Python prompt, or default
logging of schema/output payloads.

## D3 — Accounting lifecycle

Audit conflicts: C03–C06; baseline B22–B27 and probes P1/P2.

| Choice | What it means | Cost / boundary |
|---|---|---|
| L1 — snapshots first, observe native outcomes (**recommended**) | Add an authoritative accounting handle/snapshots without changing retry, cleanup, cancellation, legacy callback, ledger, or result semantics. Defer new live finalized notifications. | Smallest new lifecycle surface. Consumers inspect the handle after completion/failure/close; notification-driven accounting is a later opt-in design. |
| L2 — snapshots plus opt-in finalized notification | Preserve native outcomes, but add live new-surface notification with explicit delivery/reentry/exception rules. | Additional ordering/isolation work. No new event is routed to old subscribers implicitly; notification semantics require their own gates. |
| L3 — coordinated lifecycle revision before porting | Select cancellation-dominates, active-operation tracking/client-close cancellation, or other revised outcomes as an explicit contract revision. | Larger behavioral change and compatibility matrix; keeps the port waiting on a lifecycle redesign. Current Python behavior cannot be described as already equivalent. |

Under selected L1, cancellation/close intent alone does not commit a terminal state
or instruct routing. Cancellation finality follows the native outcome or confirmed
consumer closure, rather than merely the request to cancel/close.
If cleanup produces an error that drives retry, the call may be failed while the
operation later succeeds. Preserve that native flow and record cancellation intent
only as evidence where observed. Do not force the call or operation to `cancelled`
because the request was made.

A successfully completed zero-advance `aclose()` can finalize a **new accounting**
snapshot as consumer-closed, never started, elapsed zero, and zero calls. This does
not assert that legacy cancellation telemetry occurred: the audit observed none.
It does not redefine `.result` or manifest `complete`. A close fault or concurrent
close rejection must not be treated as successful closure: first determine whether
the native source actually ended; if still live, accounting remains nonterminal.

The proposed success order preserves the existing channels:

```text
required provider cleanup and validation finish
result assembled
legacy AttemptCompleted
legacy RequestCompleted (existing ledger input)
existing manifest builder receives result
new accounting success snapshot committed
StreamEnded exposed
stream handle captures its Generation result
outer generator/consumer cleanup follows native behavior
```

The detailed [lifecycle matrix](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md) records that
router health marking and outer teardown can follow `StreamEnded`. Earlier shorthand
about routing finishing before this event did not establish that stronger guarantee.

During a legacy completion callback the accounting view may still be running and
the stream result unavailable. Accounting success means the core prepared the
successful result; it does not prove that the consumer collected it. A later close
does not reopen a committed accounting snapshot. Failure/cancellation ordering,
postcommit wrapper faults, reentrant legacy actions, and start/close races still need
an exact state/field table and executable cases before freeze.

L1 defers `OperationFinalized` delivery and its subscriber-isolation/reentry guarantees.
The existing observer bus is unchanged, including its `BaseException` and warning
behavior. L2 would additionally need to define exactly where notification occurs,
which exceptions propagate, what later subscribers receive, and what reentrant
actions can observe. None of those choices may mask the original native failure.

Client adapter disposal is not automatically operation cancellation. The proposed
`client_closed` cancellation reason is deferred unless coordination is selected
explicitly. Fixing Python's retained builder on zero-advance close is a separately
named cleanup change; reproducing that private leak is not a native C# requirement.

**Before freeze:** handle acceptance/ownership, close-fault disposition, native
primary-error classification, call-versus-operation outcomes, commit ordering,
postcommit diagnostics, and race cases. Detailed observation provenance/coverage
still requires D5/D8; lifecycle selection cannot supply evidence that adapters lost.

## Selection record — confirmed by the user

| Decision | Selection | Status |
|---|---|---|
| D1 | S1 — bounded schema subset with Python parsing compatibility | Selected. Exact admitted domain and special-value representation remain before-freeze gates. S2/S3 were not selected. |
| D2 | F1 — equivalent selected violations; wording may differ | Selected, with the later I1 explicit malformed-schema coverage qualification linked above. Actual selection-to-prompt evidence, issue identity, and cap/order still require verification. F2/F3 were not selected. |
| D3 | L1 — snapshots first, observe native outcomes | Selected. Live finalized notifications, cancellation dominance, coordinated client-close cancellation, and implicit legacy-bus changes are deferred. L2/L3 were not selected. |

The first profile requires authoritative inspectable accounting snapshots, not live
`OperationFinalized` delivery. Future aggregate consumers can inspect finalized
handles; persistent ingestion remains outside the first profile. Existing typed
telemetry is unchanged by the notification deferral.

P1.3 direction selection and P1.G reconciliation/review are complete. This does not
authorize runtime changes or fixtures, and does not erase the remaining
specification/wire/API verification gates. The foundation checklist owns the next
authorized resume point.
