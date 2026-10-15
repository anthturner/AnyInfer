> **Historical supporting record.** Current decisions, language roadmap, readiness,
> and execution order belong to the [active master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
> Old alternatives, next-step directions, and authorization notes below are not current instructions.

# AnyInfer — detailed compatibility choice walkthrough

**Status:** user selected N1/U1/I1/C1; detailed wire/evidence/API rules remain unfrozen.
**Created:** 2026-10-14. **Evidence HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Scope:** planning documents only; no runtime changes, fixtures, or normative assets.
**Resume/status:** [foundation checklist](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Settled directions:** [S1/F1/L1](ANYINFER_P1_3_CHOICES.md) remain selected.
**Detailed drafts:** [schema domain](ANYINFER_SCHEMA_ADMISSION_DRAFT.md),
[feedback comparison](ANYINFER_REPAIR_FEEDBACK_DRAFT.md), and
[accounting lifecycle](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md).
**Evidence:** [audit and bounded review observations](ANYINFER_P1_EVIDENCE_AUDIT.md).

This file owns only the following detailed choices and their eventual user selections.
It does not change the earlier S1/F1/L1 selections or freeze the exact wire/API shape.
The user selected N1/U1/I1/C1 in the structured walkthrough. This file owns those
selections; linked drafts incorporate them without treating remaining gates as closed.

## N — Represent numeric observations without changing their meaning

S1 already preserves Python-compatible response parsing. The remaining choice is how
the portable kit describes those observed values. It is not permission to switch
runtime validation to strict finite JSON or exact decimal arithmetic.

| Option | Meaning | Cost / compatibility |
|---|---|---|
| N1 — exact integer text and binary64 representation (**recommended**) | Tagged integer with exact decimal value; tagged binary64 value with exact finite bit representation, signed infinity, or NaN category. | Explicit and independent of culture/decimal formatting. Ordinary finite floats and signed zero can be reproduced exactly; special categories avoid requiring meaningless NaN payload parity. Human-readable display may accompany the authoritative value. |
| N2 — round-trip numeric text and special-value tags | Tagged integers use exact decimal text; finite floats use a standardized round-trip decimal spelling, with tags for NaN/infinities and preserved signed zero. | Easier to read; requires a shared decimal parsing/rendering/canonicalization rule. It still must reproduce binary64 outcomes, not exact decimal validation. |

Examples: a response `1.0` is decoded as a floating value but qualifies as an integer
under the installed validator; boolean `true` is neither integer nor number.
`1e999` decodes to positive infinity in the audit. Signed zero can carry distinct
representation while comparing numerically equal to zero.

**Selected N1 direction:** preserve representation identity for finite floats and signed
zero; compare NaN observations by category, without equating NaN with an ordinary
number in schema validation. The kit's observed-value equality and JSON Schema's
`enum`/`const` numeric equality are different operations. A bit-identical response
comparison must not make `1` and `1.0` unequal inside a schema assertion.
NaN payload/sign are not first-profile semantic expectations unless an admitted
operation proves they affect an observable outcome; retain an explicit gate for that.
Tagged decoded observation identity is only the corpus-comparison operation. Schema
`enum`/`const` retains semantic numeric equality (`1` equals `1.0`, signed zeros
compare equal, booleans stay distinct); type and bounds retain their separately
pinned validator outcomes. A native implementation must not reuse tag/bit equality
as its schema assertion equality.

Counts/money in accounting use their own proposed integer/finite-decimal domain.
Response-side NaN/infinities must never become valid accounting counts or charges.
The representation is for shared observations/expectations; the native C# public
structured-result type remains D7/API work.

Integer digit limits, numeric token/response size, rounding, exponent underflow,
and interpreter configuration remain evidence gates. Do not pick a smaller limit
merely because a native primitive overflows; do not claim arbitrary unlimited input
from the existence of Python integers. Pin the supported reference environment and
its relevant settings before giving a versioned compatibility guarantee. Any stricter
portable limit would be an explicit profile difference requiring disposition.

## U — Preserve Unicode values versus declare a narrower response domain

Python-compatible character counting and no normalization are already the proposed
baseline. The unresolved boundary is isolated surrogate code points and their
representation through the kit/native parser/transport.

| Option | Meaning | Cost / compatibility |
|---|---|---|
| U1 — preserve exact Python string sequences (**recommended**) | Carry decoded code-point values, including isolated surrogate values when Python accepts them; no normalization. Count/order using Python-compatible values. | Needs an exact representation/decoder path where standard serializers replace or reject surrogates. Avoids silently changing validation or feedback selection for an admitted response. |
| U2 — scalar-only portable strings | Restrict the declared shared response domain to Unicode scalar values, keeping code-point count and no normalization for that domain. | Simpler use of strict Unicode codecs. This is a declared narrowing: a valid request can receive a response Python accepts but the bounded port cannot represent. Unsupported-response/failure/repair/accounting behavior must be specified separately; it cannot be disguised as equivalent parsing. |

Examples: an astral character counts as one Python character, while C# UTF-16
`String.Length` counts its two code units. Precomposed `é` and `e` plus combining
acute are different sequences and have different lengths; normalization would change
schema validation. A property key containing an astral character can sort differently
under Python code-point order and a UTF-16 code-unit comparator, affecting which five
violations are selected.

**Selected U1 direction; candidate representation:** a tagged sequence of integer code-point values for
exact string observations where necessary, allowing isolated surrogate values. A
paired escape that the reference decoder combines becomes the corresponding astral
value; an isolated surrogate remains a distinct single value. Do not automatically
combine two raw surrogate values in an already-decoded Python sequence. Exact raw
provider text, schema strings/keys, and decoded observations need lossless kit handling
where ordinary JSON string decoding would otherwise merge or replace them. Numeric code-point encoding
keeps the kit file valid JSON without depending on a reader's surrogate-string policy.
This does not select a public C# string/result API or require tagging ordinary public
strings. A transport that rejects bytes/escapes can fail before any decoded value exists;
do not manufacture a parsed string after an actual native adapter failure.

Pin the decoded-value rules, escape/pair handling, exact trimming whitespace set,
Unicode database/version effects, and ordering. Prompt schema injection currently uses
`json.dumps(..., indent=2, sort_keys=True)`; that serialization choice does not prove
provider HTTP response-decoder behavior. Test decoded values and transport separately
once fixtures are authorized. No decoder or fixture is changed in this walkthrough.

| Unicode stage | Meaning for U1 |
|---|---|
| Python decodes a syntactically escaped isolated surrogate | Preserve the actually decoded value as exact observation evidence; confirm the reference case before claiming parity. |
| Malformed/raw transport encoding fails before JSON decoding | Preserve and classify the native adapter/decode failure; no parsed value exists to preserve. |
| Native JSON parser rejects a syntactically escaped surrogate Python decodes | Explicit compatibility mismatch to resolve, not a fabricated parsed value or an automatically equivalent transport failure. |

Preserving a native transport fault does not itself establish compatibility: if the
Python adapter accepts/replaces the same transport input and proceeds, that difference
also needs explicit classification. U1 does not permit a native parser/decoder gap
to count as a pass merely because the accounting faithfully recorded its failure.

## I — Invalid-schema feedback coverage and defect identity

Keep current timing/branches regardless of the feedback-comparison choice. Ordinary
instance feedback still follows selected F1. Malformed root `$schema` array/object/
integer can cause an uncaught late validator-selection fault; null produced
one caught invalid-schema feedback string in the bounded review probe's environment.
Subsequent source reading found a warning before that branch which can become fatal
under pytest's warning policy. The I1 draft therefore treats null metadata as an
outside-domain environment-sensitive control. Neither branch becomes an early Python
rejection or a new retry rule; no warning suppression is proposed.
The subsequent [I1 helper audit](ANYINFER_I1_EVIDENCE_AUDIT.md) directly observed both
null branches and captured selected R/T error identities across all declared
dialect/order variants. The selected domain remains unfrozen and unchanged.

The difficult choice is matching the particular defect in a caught `SchemaError`.
Python's installed meta-validator raises its first iterated meta-schema error; it
does not apply AnyInfer's ordinary depth/relevance sort. Another validator may choose
a different defect or aggregate wrapper, especially with multiple malformed keywords.

| Option | Meaning | Cost / compatibility |
|---|---|---|
| I1 — exact defect comparison for a declared bounded malformed-schema set (**recommended for the first proof**) | Specify the required malformed forms/cases and compare the actual selected defect for those. Preserve branch/budget/history semantics more broadly, but explicitly limit detailed invalid-schema feedback equivalence outside that set. | Smallest strong proof. This is an explicit qualification of F1's invalid-schema coverage, not complete feedback parity for every malformed admitted schema. Uncovered cases cannot count as a detailed-feedback pass. |
| I2 — full selected-defect parity for admitted malformed schemas | Match the selected meta-validation defect across every malformed shape in the admitted domain, including aggregate/group/tie behavior. | Strongest claim; can require a common meta-validation/selection layer or extensive native compatibility work. Python's strings/ordering still stay intact unless separately revised. |
| I3 — category/branch equivalence for invalid schemas | Compare invalid-schema feedback category, late timing, correction history/budgets, and terminal behavior; allow different described defects. Ordinary valid-schema instance violations keep F1. | Simplest, but deliberately weaker about what invalid-schema guidance asks the model to fix. Requires an explicit exception to selected-defect equivalence rather than labeling it full F1. |

The [I1 domain/reporting draft](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md) owns a closed
candidate set of root shapes, its exact value/key/dialect/order constraints, and
separate no-feedback/extraction/exclusion controls. Portable mapping of the captured
helper identities and end-to-end evidence remain gates; the draft does not imply coverage of other values,
annotations, nesting, or compound defects.

For example, `required: 17` and `type: 17` separately return caught feedback in the
review. With both malformed, do not claim that any complaint about either keyword is
equivalent to Python's actual first error. Under I1, a compound case outside the
declared set has qualified/unsupported detailed-feedback comparison, not a passing
exact-defect assertion. Branch behavior still needs its own classified expectation.

This comparison limitation does not reject malformed requests earlier, add a second
validator/router, or fabricate a different runtime error. Profile/report vocabulary
must distinguish required exact-feedback coverage from qualified broader malformed
behavior; freeze that vocabulary before claiming a cross-language profile pass.
If that qualification is unacceptable, choose I2 rather than silently filling the gap.
Under I1, a later record/report must carry comparison scope and result separately:
declared exact cases can be matched/mismatched; uncovered cases are qualified and
`not_covered` for detailed feedback, never a detailed-feedback pass. A declared
mandatory exact case with missing evidence cannot downgrade itself to qualified.
Branch/history/budget results are reported independently. No completed feedback
record is fabricated for an uncaught assessment fault.
The user selected this explicit qualification. A profile report must name the
declared exact malformed domain and state that general invalid-schema selected-defect
parity is not claimed. All current mandatory cases passing cannot erase that boundary.

## C — Cancellation outcome known, cause attribution uncertain

L1 already selects native outcomes over cancellation intent. The remaining choice
is how to report confirmed native cancellation when its cause cannot be attributed
to caller cancellation versus consumer closure. Unknown cause is distinct from an
unknown terminal outcome or a source that is still live.

| Option | Meaning | Cost / compatibility |
|---|---|---|
| C1 — explicit unknown cancellation reason with evidence (**recommended**) | Allow `cancellation_reason=unknown` only when cancellation terminality is confirmed but known reasons lack sufficient evidence; retain bounded diagnostic evidence. | Honest terminal accounting without a fabricated cause. Adds one candidate enum value; version/readers must handle it. No existing Python cancellation policy or ledger change. |
| C2 — nullable reason with an explicit attribution-status field | Cancelled summaries can have reason null plus mandatory attribution `unknown`; known attribution carries a known reason. | Equivalent honesty with an additional field/nullability matrix. Bare null cannot mean both not-cancelled and unattributed without the status. |
| C3 — known causes only, keep unattributed cases a coverage blocker | Retain the two known reasons; do not claim supported cancellation accounting for ambiguous causes until evidence/classification closes the gap. | Smallest record enum, but postpones a mandatory concurrency/race claim. Never leave a confirmed terminated source falsely running or relabel it failed just to fit the record. |

**Selected C1 direction; proposed detailed matrix:**

| Actual observation before success commit | Proposed result |
|---|---|
| Native operation ends through cancellation; caller cause is established | Cancelled / caller_cancelled. |
| Successful source close actually ends the operation; consumer cause is established | Cancelled / consumer_closed. |
| Native cancellation ending is established, cause cannot be distinguished | Cancelled / unknown; require a bounded cause-attribution diagnostic with the observed evidence. |
| Close merely requested or rejected while source remains live | Keep accepted/running; fault/intent diagnostics only. |
| Cleanup replaces cancellation with a fault | Follow the actual fault and any native retry; no forced cancellation reason. |
| Already committed success, then cancellation/close arrives | Preserve immutable success; use the separately proposed postcommit diagnostic surface for observed late faults. |

Possible diagnostic evidence is a typed set of observed flags/source-boundary facts,
not arbitrary native objects or payloads. A cancellation-shaped exception alone
does not prove external caller intent; an observer can raise such an exception too.
Likewise, `_closed=true` on the stream is not closure confirmation. No first/last-
intent timestamp rule arbitrates a winner or changes native control flow.

Known attribution may coexist with earlier conflicting intent; report the actual
observed termination cause. If terminal state itself cannot be classified, C1's
unknown reason does not solve it: source-outcome mapping remains a freeze gate.
Once committed, later attribution evidence cannot rewrite the snapshot; any late
evidence stays in separate diagnostics. `client_closed` remains deferred.
Selecting C1 authorizes designing the third reporting value, not a lifecycle policy
revision. Terminal mapping, bounded evidence taxonomy, enum/version compatibility,
and API gates still precede a normative rule or implementation. No close flag/intent
may manufacture cancelled/unknown, and no late attribution reopens a committed record.

## Selection record — confirmed by the user

| Choice | Current status | Gates that a selection will not close |
|---|---|---|
| N | N1 selected: exact integer observations and binary64-based float observations, with special categories. N2 not selected. | Exact tags/encoding/equality, numeric limits/settings, native parser feasibility. |
| U | U1 selected: exact decoded sequences, including isolated surrogate values; no normalization. U2 not selected. | Escape/pair/transport behavior, whitespace/Unicode version, public native representation. |
| I | I1 selected: exact selected-defect comparison for a declared bounded malformed-schema domain; explicit qualified/not-covered detailed feedback outside it. I2/I3 not selected. | Approval/versioning of the closed-domain proposal, reference environment/resources/warning policy, selected-error bridge/identity, and verification of its reporting matrix. |
| C | C1 selected: unknown attribution only for confirmed native cancelled terminal outcomes. C2/C3 not selected. | Evidence taxonomy/bounds, terminal source mapping/races, enum versioning and public API. |

Source-derived examples are logical comparisons unless the audit names a direct
observation. No new test suite, runtime probe, implementation, or fixture was produced
by this choice walkthrough. The three drafts and accounting companion incorporate
these directions; cold consistency review and the document gate belong to the master
checklist. No selection authorizes implementation, fixtures, or normative publishing.
