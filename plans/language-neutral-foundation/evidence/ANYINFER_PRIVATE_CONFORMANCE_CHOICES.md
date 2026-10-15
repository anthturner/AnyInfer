> **Historical supporting record.** Current decisions, language roadmap, readiness,
> and execution order belong to the [active master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
> Old alternatives, next-step directions, and authorization notes below are not current instructions.

# AnyInfer — private observation seam and portable failure choices

**Status:** user selected O1/M1/W1; exact interfaces, encodings, and freeze gates remain open.
**Created:** 2026-10-15. **Source HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Scope:** planning Markdown under `plans/` only; no implementation, fixture, or new probe.
**Resume/status:** [foundation checklist](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Evidence:** [native history audit](ANYINFER_I1_NATIVE_HISTORY_AUDIT.md),
[helper audit](ANYINFER_I1_EVIDENCE_AUDIT.md).
**Related rule owners:** [feedback comparison](ANYINFER_REPAIR_FEEDBACK_DRAFT.md),
[I1 domain/reporting](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md),
[lifecycle/error matrix](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md).

This file owns the three choices and their rationale. It proposes the minimum
capture scope and mapping obligations without publishing an API or failure-code
registry. The [private capture design](ANYINFER_PRIVATE_CAPTURE_DESIGN.md) now owns
the concrete record/carrier/isolation proposal under O1/M1; its details are drafts,
not additional user selections or implementation approval. W1 remains open.
The structured interview labelled the recommended failure choice F1;
this document calls it **M1** to avoid collision with the existing F1 repair-feedback
selection. S1/F1/L1 and N1/U1/I1/C1 retain their existing meanings.

## 1. Why four facts must remain separate

| Audit observation | Consequence for the private seam |
|---|---|
| An extraction repair can be followed by terminal malformed-schema errors. | Record actual selected feedback at each assessment; do not reconstruct sent guidance from the final exception. |
| A builder can prepare a correction before any adapter entry. | Prepared messages are evidence of preparation, not another call or proof of invocation. |
| T0 has direct selected/prepared/entered-wire evidence; R0 currently has selected/prepared plus HTTP correspondence. | Preserve evidence boundary and missing linkage. A matching HTTP body is not relabelled an internal wire capture. |
| Prompt injection sorts schema keys. | Original assessment schema/order must be observed independently of rendered prompt JSON. |
| Iterator close can fail after a final event and before schema assessment. | Keep invocation/cleanup outcome separate from response observation, assessment, and native termination. |
| Some native failures emit no terminal legacy telemetry. | Observe actual source/wrapper outcomes rather than infer success or zero work from missing RequestFailed/RequestCompleted. |

These are evidence requirements. None changes Python's validation timing,
original-request restart, per-outer-attempt repair allowance, event numbering,
native exceptions, or ledger/result/manifest meanings.

Here the correction's **effective base** means the messages actually passed as
`original` to `build_repair_messages` for that native outer attempt. It need not be
the caller's unmodified input: `_run_attempt` can replace its local request after
proactive history compaction. History/context reduction is excluded from the first
profile, so controlled cases must establish that scope; O1 still records actual
native inputs and never suppresses broader Python preparation to make them match.

## 2. O — How to obtain private evidence

| Option | Meaning | Cost / boundary |
|---|---|---|
| **O1 — private opt-in capture points, selected** | A harness-owned collector observes facts at their real native boundaries. No public observer/event contract. | Requires a separately authorized small core change later; avoids relying on interpreter tracing for the durable kit. Exact carrier and fault containment remain design gates. |
| O2 — external tracing/wrappers only | Continue interpreter tracing and adapter/HTTP wrappers without core hooks. | No capture-hook core edits, but tracing is Python-specific and has already missed required fields/links. Missing evidence must block the relevant assertion. Not selected. |
| O3 — tracing first, hooks only for proven gaps | Maintain tracing initially and add hooks in a later tranche. | Stages cost but temporarily owns two evidence paths and postpones the seam decision. Not selected. |

O1 is private and disabled by default. The initial consumer is the controlled
conformance harness, using synthetic case data. No new public telemetry event,
callback subscription, persistent log, network exporter, provider option, or payload
in ordinary operation accounting follows from it. Reusing `EventDispatcher` would
inherit payload stripping and warning/suppression behavior; it is not the selected
delivery path. Existing `RepairAttempted` and terminal events retain their meaning.

### Minimum capture scope: four logical boundary groups

These are logical facts, not four public callbacks or a frozen hook count. One
group may need observations at more than one source location.

| Boundary group / native anchors | Minimum private evidence | Required distinction |
|---|---|---|
| **Assessment** — `_client/generation.py:_validate`; `schema/validate.py:extract_json/validate` | Actual original schema value/order reference and response observation; extraction branch; real caught SchemaError or actual instance-error selection before rendering; returned feedback; escaping assessment fault. | Extraction and caught-schema feedback are different from an uncaught selector/validator fault. Capture actual enumeration/selection/cap/order; never revalidate to invent equivalent issues. |
| **Correction preparation** — `schema/repair.py:build_repair_messages` and its caller in `_run_attempt` | Triggering assessment reference, latest raw response, actual error tuple, the actual effective base supplied as `original`, and successfully returned prepared messages/template. | An assessment may have no correction. RepairAttempted alone does not prove preparation; preparation does not prove adapter entry. Caller input cannot substitute for the effective native base. |
| **Invocation and required cleanup** — `_run_attempt`; `providers/base.py:aclosing_if_supported` | Actual entry across `adapter.generate(wire)`, entered wire snapshot/reference, any linked preparation, consumed terminal observation, iterator/cleanup outcome and actual escaping exception. | Built wire/pacing/acquisition are not entered calls. Immediate generate-method/factory faults do count at the existing boundary. AdapterFinal is not successful cleanup or assessment. |
| **Native result/source/wrapper outcome** — `_generate_request`, `_routed_stream`, `AsyncStream` as applicable | Result/StreamEnded observation separately from actual source termination and outward return/exception/confirmed close or cancellation after required teardown. | A result can be observed before later teardown faults. `_closed`, intent, or missing legacy events cannot supply source termination or rewrite a prior success commit. |

For ordinary instance errors, the seam must preserve actual pre-sort enumeration
position before the current relevance sort/truncation destroys it. Observe the
selected sequence before `_describe` reduces errors to strings. For I1, retain the
actual caught primary SchemaError, its defective-input path, meta-constraint evidence,
and aggregate context; T's wrapper is not replaced by a convenient child.

If extraction needs candidate-boundary/decoder evidence for a required case, capture
the facts while the native extractor has them. Do not run its scanner/decoder again
to fill missing fields or alter candidate selection. Existing feedback/category
requirements determine what is necessary; O1 does not require a general parser log.

### Correlation, snapshots, and capture failure

| Concern | Minimum design obligation / remaining decision |
|---|---|
| Ownership | One private observation context per native operation, owned by the harness. No process-global current-case state or cross-operation mutable collector. The concrete design proposes an explicit session with narrow task-local enrollment/helper bindings; review/verification remains gated. No new public API argument/export or adapter protocol requirement is selected. |
| Correlation | Link case, outer attempt, entered invocation, assessment, and preparation with private opaque references/ordinals. Do not use Python object IDs/timestamps as portable IDs or reuse accounting IDs by assumption. A preparation has no entered-call identity until that boundary occurs. |
| Stable evidence | Preserve actually observed original value/order and messages at the boundary. A retained mutable pointer alone cannot prove a later snapshot's value/order. N1/U1 and typed paths still govern portable observations; their final encoding remains open. |
| No extra semantic work | Reuse already computed native intermediates where possible. No extra validation/enumeration, schema normalization, custom Mapping traversal, deep-copy policy, or rendering/serialization whose side effects change native handling. Controlled input stability and snapshot materialization need an explicit design. |
| Delivery | Private in-process capture without user callbacks, awaits, locks/reentry into generation, event-bus delivery, or default I/O. The collector is not allowed to schedule repairs, throw a substitute provider error, or change request fields. |
| Ordinary capture failure | Preserve native execution/outward outcome and mark the affected evidence incomplete; the driver blocks the affected required comparison after native execution, rather than silently passing or making the core fail early. Do not warn through a path that warnings-as-errors could turn into a new native failure. Reliable incomplete-evidence signalling and exact containment are implementation-design gates. |
| Fatal failures/cancellation | No blanket BaseException swallowing, cancellation suppression, forced draining/retry, or invented terminality. Catastrophic runner/capture loss cannot produce a pass. Exact behavior/isolation remains a pre-implementation gate; zero interference under arbitrary failure is not claimed. |
| Privacy/lifetime | Controlled case references/payloads only in the opted-in private context. No raw exception/schema/output objects in default telemetry/accounting. Bounds, deterministic detach/release, and concurrent-case isolation must be specified before implementation. |

Capture handles/correlation data must not be smuggled into public request metadata,
provider options, or wire payloads. Explicit private propagation is an internal
design choice, not a new `observe` parameter on public schema/client/adapter APIs.

The first bounded design can focus on I1 buffered observations, but cannot call that
full generation/accounting conformance. Streaming, zero-advance close, cancellation,
post-result teardown, and all-variant field coverage retain their existing gates.
O1 does not choose the public accounting handle or implement authoritative snapshots.

## 3. M — What failure meaning is portable

| Option | Meaning | Cost / boundary |
|---|---|---|
| **M1 — observed stage plus small semantic families, selected** | Compare native origin/outcome and a small semantic family, with qualified native evidence retained separately. | Distinguishes materially different failures without freezing Python class names into the portable contract. Exact family/stage spelling and mappings remain draft. |
| M2 — detailed defect-specific portable codes | Assign finer codes for warning promotion, selector faults, validator defects, and similar native details. | Larger compatibility surface; more native evidence and mapping decisions before freeze. Not selected. |
| M3 — one failure category plus native evidence | Collapse failures and rely on per-case branch checks. | Smaller vocabulary but less meaningful portable classification; branch assertions still cannot be omitted. Not selected. |

The minimum proposed representation is **semantic family + observed stage + error
role + qualified native evidence**. It is a conformance/report mapping, not an error
factory or a new router predicate. Native `ErrorInfo.phase`, provider, retryable,
Retry-After, HTTP status and hint remain available when actually present; observed
stage never overwrites phase. Missing fields stay unavailable/null as applicable.

To keep family and stage orthogonal, the following are candidate family meanings,
not released wire codes:

| Candidate family | Evidence needed | Example / stage implication |
|---|---|---|
| `schema_exhaustion` | Actual core exhaustion branch and its native SchemaViolationError. | Completed response, failed extraction/validation, no repair allowance remaining, including configured zero. Operation schema failure does not turn the completed invocation into a transport failure. |
| `provider_failure` | Actual provider-error identity/path and native handling, after required cleanup/conversion determines what escapes or is retried. | A retryable 503 and a provider error raised during cleanup retain provider semantics; observed stage distinguishes them. Predicate/budget decisions remain native. |
| `native_fault` | Known unexpected native fault at an evidenced stage, without the preceding semantic origins. | Assessment fault versus cleanup fault is distinguished by stage. Generic RuntimeError at iterator close is not invented provider failure. |
| `unclassified` | A failure is actually observed but semantic origin or required mapping is unresolved. | Honest diagnostic fallback; cannot satisfy a mandatory known-family expectation or hide missing evidence. Exception groups/chains are not flattened to force a known family. |

A proved wrong branch/family remains a mismatch even if other mapping evidence is
missing. Where required origin/mapping cannot be established, block that assertion;
do not use `unclassified` to hide a known mismatch or invent an expected family.
This follows the I1 report's existing mismatch-over-missing-evidence precedence.

The outcome/role axis is separate: handled/retried/suppressed observations, an escaping
precommit terminal failure, and a post-result/postcommit diagnostic are not equivalent.
Use the lifecycle owner's actual commitment rules; a wrapper exception alone cannot
retroactively fail an already committed successful accounting snapshot. A collector
must not manufacture a success commit or classify a still-running source as terminal.

Cancellation is also separate from these failure families. C1 still requires confirmed
native cancelled termination before caller/consumer/unknown cause attribution. A
cancellation-shaped native exception or `_closed` flag alone is insufficient. No
literal C# exception class name automatically determines terminality or cause.

### Mapping the audited histories

| Actual native observation | Proposed portable interpretation | What cannot follow from it |
|---|---|---|
| R/T feedback with budget left | Completed assessment/failed validation; actual selected feedback; native repair may follow. | Not a terminal schema_exhaustion merely because the schema is malformed. |
| R/T or extraction feedback with no allowance left | `schema_exhaustion`, evidenced core assessment/exhaustion stage; outward native SchemaViolationError. | No provider retry/fallback, fake RequestFailed event, or replacement ledger input. |
| Correction c2 gets 503 then c3 restarts original | `provider_failure` at invocation, handled/retried; preserve observed restart and local repair reset. | It is not the operation's terminal primary error when native execution continues. |
| Null metadata under nonfatal warning policy | Caught invalid-schema feedback; detailed feedback outside exact I1 remains qualified. | A recorded warning is not a terminal failure. Captured null identity does not expand I1 membership. |
| Null metadata under error policy | `native_fault` at assessment, with native promoted-warning evidence; native exception preserved. | Classification alone does not settle its portable expected outcome under W1 below. |
| Final event followed by generic iterator-close fault | `native_fault` at provider cleanup; failed invocation with assessment not completed under the existing lifecycle proposal. | No fabricated schema issue, prepared correction, successful result, or cancellation precedence. |
| Known ProviderError escapes provider cleanup | `provider_failure` at provider cleanup; actual router handling still governs continuation. | Do not recategorize it as a generic nonretryable cleanup fault because of stage alone. |
| New capture mechanism loses evidence | Harness evidence failure; relevant comparison blocked. | Not a native provider/assessment error, a skipped mandatory case, or permission to change native outcome. |

Native class names, warning text, stacks and meta-schema indices may remain private
reference evidence. They are not automatically shared equality keys. The language-
neutral meaning comes from actual branch/origin plus existing structured fields and
the case's expected behavior. Exact Python messages/exceptions remain unchanged.

## 4. W — Null metadata's reference condition

| Option | Meaning | Scope consequence |
|---|---|---|
| **W1 — portable expectation stays open, selected** | Keep both observed Python policy controls; do not select one as the portable baseline yet. | Blocks this portion of profile freeze. Both controls remain useful native evidence; neither proves C# parity or makes the missing choice an optional skipped case. |
| W2 — pin warnings-as-errors for this boundary | Portable baseline requires late assessment failure on null metadata. | Nonfatal Python repair behavior needs a separately qualified claim. A C# semantic mapping is still required; no Python-wide policy change. Not selected. |
| W3 — pin nonfatal warnings for this boundary | Portable baseline requires late caught schema feedback and normal repair budgeting. | Fatal-warning Python behavior needs separate qualification. No warning suppression or repository-wide filter change follows. Not selected. |

Under W1, it is possible to classify the **observed Python outcome** using M1 while
the **portable expected outcome** remains unresolved. These are different questions.
The two native reference controls have predeclared policies/branches; keep them fixed.
Do not build a portable case whose expected branch is chosen after observing its run.

No I1 scope/result is downgraded: caught null feedback remains outside exact detailed
comparison; an uncaught fault has no fabricated feedback record. A portable profile
claim requiring the unresolved boundary stays blocked, rather than reporting a
matched branch or silently excluding a mandatory case. Report the unresolved reference
condition explicitly. W1 does not alter S1 admission, I1 membership, native repair
budgeting, or the existing null warning policies.

## 5. Remaining bounded design gates

| Gate | Required next detail |
|---|---|
| Private context/carrier | Review/verify the concrete design's explicit session, one-shot owner-task enrollment, synchronous helper frame and detach/lifetime; prove no cross-operation leakage. No new public surface assumed. |
| Capture records and locations | Review/verify the concrete records, original-order/typed-value snapshots and actual native selection provenance; close all-variant/R0 wire evidence gaps with later authorized runs. |
| Ordinary/fatal capture failures | Review/verify the sticky health/prefix and separate outward observation design without changing native messages, events, exceptions, scheduling, cleanup, or retry; retain catastrophic runner loss and cancellation limits. |
| Correlation and closure | Link prepared versus entered corrections, original retry/reset, actual source termination, result observation and postcommit faults; never infer from intent or legacy event absence. |
| Mapping coverage | Exact semantic-origin and stage mappings for admitted cases, TimeoutError conversion, handled/suppressed faults, native groups/chains and unclassified diagnostics. No universal class-name heuristic. |
| Portable reference condition | W1 remains open before the affected profile can freeze. Classification of known Python traces does not close it. |
| Verification scope | Later authorized checks must include hook-disabled compatibility, opt-in capture failure, multiple concurrent cases, exact feedback/message/wire linkage and the remaining native lifecycle cases. No implementation or fixture is authorized here. |

Source anchors: `schema/validate.py:extract_json/validate/_describe`,
`schema/repair.py:build_repair_messages`,
`_client/generation.py:_validate/_run_attempt/_route_events/_routed_stream`,
`providers/base.py:aclosing_if_supported/GeneratesText`,
`_client/async_client.py:_generate_request`, `_client/stream.py:AsyncStream`,
and `events/observers.py:EventDispatcher.emit`. Relative source paths are under
`src/anyinfer/`. This walkthrough added source reading and planning text only.

## 6. Review and status

Cold review found one ambiguity: a correction's original messages could be read as
the caller's input rather than the effective base after native preparation. This
walkthrough and the feedback draft now require the actual builder argument and
retain the first profile's history/context exclusion. Review also checked private
ownership, no public metadata/API leakage, and mismatch precedence for incomplete
mapping. Narrow rereview found no unresolved contradiction.

The planning-document gate checks local links, Markdown tables/fences, whitespace,
and repository scope. O1/M1/W1 are recorded directions, not an implemented hook,
released failure registry, closed W1 expectation, or conformance pass. No new runtime
probe/test, fixture, implementation, external artifact, or commit was produced.
