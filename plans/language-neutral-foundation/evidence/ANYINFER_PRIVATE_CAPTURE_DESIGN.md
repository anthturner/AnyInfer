# AnyInfer — private capture design

> **Archived 2026-10-15.** Superseded by the revised [master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md)
> and [specification draft](../SPECIFICATION_DRAFT.md). Kept as input for milestone 3
> (operation accounting) and as rationale. Not an active plan; its checklists and gates do not apply.
> Retired by decision A5 (one invalid_schema issue, wording free) and A6 (pure-function issue seam).

**Status:** concrete design proposal under selected O1/M1; not implemented or frozen.
**Created:** 2026-10-15. **Source HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Scope:** Markdown under `plans/` only; no implementation, fixtures, or new runtime probes.
**Resume/status:** [foundation plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Selected-policy owner:** the foundation plan.
**Record/report owners:** [feedback comparison](ANYINFER_REPAIR_FEEDBACK_DRAFT.md),
[I1 scope/results](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md),
[lifecycle/errors](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md).
**Supporting historical evidence:** [native audit](ANYINFER_I1_NATIVE_HISTORY_AUDIT.md),
[helper audit](ANYINFER_I1_EVIDENCE_AUDIT.md).

This file proposes exact private record responsibilities, a hybrid context carrier,
and capture-failure containment. These are reviewable design choices under O1,
not new user selections or public APIs. **W1 remains open:** neither null-metadata
reference policy is selected as the portable expected outcome.

**Language path:** This is the private Python capture design. Python and C# are next
proof targets; any admitted future native language, such as Java or JavaScript/TypeScript
on Node.js, supplies equivalently linked native facts through its own observation hooks
and driver. Module layout, private classes, task-local bindings, and cleanup hooks below
belong to Python. Portable comparison/provenance/corpus requirements stay common.
M1's stage/family/role direction is selected; detailed mappings and encodings remain
gated. W1's portable null expectation remains open. Native exception/type identities
are qualified evidence, with no runtime wrapper, mandatory generator, native binary,
portable encoding, or implementation library selected here.

## 1. Boundary and ownership

The first implementation brief, if separately authorized, would cover controlled
async buffered generation and the common native-core capture points. It would not
claim full streaming/sync-facade/accounting conformance. Public stream lifecycle is
included in the propagation design so the carrier does not assume task affinity;
its complete verification remains a gate for the full generation profile.

No public arguments/exports, adapter protocol methods, request metadata, provider
options, wire payload fields, or legacy events carry capture state. No accounting
CallRecord/OperationSummary is created by this seam. The collector observes facts;
the driver compares them after native execution and applies existing I1 verdicts.

Proposed shared module: `src/anyinfer/_capture.py`. It would own private frozen
records, builtin-only snapshots, session/health state, and narrowly scoped context
bindings. It must not import the client, provider adapters, schema helpers, or
jsonschema; callers translate known native fields into its private inputs. This
avoids schema-to-client import cycles and adds no dependency. Nothing is created
at that path under the current authorization.

## 2. Record model

Records are append-only frozen values with immutable snapshot references. They are
private in-process evidence; names below are design identifiers, not released wire
tags or portable exception codes. Final portable encoding remains D4 work.

### Common fields and evidence values

| Field | Meaning |
|---|---|
| `operation_ref` | Harness-local identity of this captured native run. No UUID spelling, timestamp, or Python object ID requirement. |
| `sequence` | Contiguous successful append ordinal, beginning at one. Assign on successful append, not when an event is merely intended. It is evidence order, not a scheduler or clock. |
| `kind` | One of the private record kinds below. |
| Parent references | Applicable `route_attempt_ref`, `invocation_ref`, `assessment_ref`, `preparation_ref`. Inapplicable links are absent/null by the record definition; missing required links make evidence incomplete. |
| Evidence value | `observed(value)`, `not_applicable`, or `unavailable(reason)`. An observed null/false/zero is distinct from unavailable. These are conceptual private variants, not JSON encodings. |

Opaque reference namespaces are distinct. Route attempts are not calls; an entered
invocation gets its own reference even if `generate(wire)` immediately faults.
Preparations have their own identity before any correction is entered and never
reserve a call count. Strong references used temporarily to correlate native error
objects are not exported as portable IDs.

### Private records

| Record | Required facts / conditional fields |
|---|---|
| `RouteAttemptBegan` | Actual native target/outer-attempt observation and its local attempt number. An actual retry links its predecessor handling record through a private link carried only when the native retry continuation is taken; ordinals/target equality cannot invent that link. No invocation is implied; preflight can still fail. Effective-base evidence is captured later at the actual repair builder. |
| `RouteHandlingObserved` | Handling reference and outer attempt; actual caught provider error, correlated failing invocation only if its origin/link is observed; native already-computed retryable/budget-left facts and actual appended AttemptRecord outcome when reached. It records the router's handling/decision, including native outcome spelling retried, rather than proof that a retry executed. If native handling itself faults before those facts exist, retain unavailable facts or the earlier fault evidence instead of recomputing the predicate. |
| `InvocationEntered` | Invocation reference, actual resolved target/model, role `original` or `correction`, actual local `repair_attempts` and already-computed repair budget, linked preparation for a correction, and entered WireRequest snapshot. This means the adapter API expression is attempted, not dispatch/provider receipt. No policy/budget is recomputed for capture. |
| `InvocationExited` | Same invocation; observed iteration exit, terminal-adapter-event observation, optional-close lookup/cleanup outcome, and actual escaping native error before/after existing conversion where observed. Missing/unreached cleanup differs from successful cleanup. No legacy usage merge is moved. |
| `AssessmentBegan` | Assessment and triggering invocation; actual original assessment schema/order and raw-response reference before native extraction/validation. No candidate or decoder outcome is claimed before it is computed. It is not an early schema-validity gate. |
| `AssessmentFinished` | Branch `not_requested`, `extraction_failure`, `invalid_schema`, `instance_violations`, `valid`, `native_fault`, or `interrupted`; native candidate/extraction/decoder facts when actually obtained; native returned feedback only when actually returned; parsed value with explicit observed-null support; actual caught primary/selected-error evidence, completeness, cap/count/order as applicable. Fault/interruption is not fabricated feedback. |
| `PreparationBegan` | Preparation/trigger assessment; actual effective `original` argument, latest raw response, and actual error tuple at the builder call. Caller input is not substituted for a compacted effective base. No prepared-message claim yet. |
| `PreparationFinished` | Outcome `prepared`, `native_fault`, or `interrupted`; returned message snapshot only for prepared; otherwise actual native fault/interruption evidence. No invocation is implied. |
| `ResultObserved` | Actual StreamEnded/result observation at the receiving buffered wrapper or AsyncStream after the native result slot is set. Not merely result assembly or an event about to be yielded. No accounting success commit is inferred. |
| `SourceBoundaryOutcome` | Named native boundary: routed source, buffered wrapper, stream advancement, or stream close. Retain actual normal/exceptional exit versus successful exhaustion/confirmed closure, result-observed reference, and native error/cancellation facts. An advance returning a delta is not source termination. |

The exact branch/stage strings above remain private draft spellings. Observed stage,
M1 family, error role, native phase and source terminality are separate axes. Retain
known fields when another axis is unavailable; do not infer a family from class
name alone or replace an existing phase with the capture stage.

`NativeErrorView` contains known semantic origin/branch, native type identifier,
already-produced ErrorInfo fields when available, and controlled immutable evidence
references. Bundle records never retain a live exception/context chain. It never
calls `snapshot()`, `str(error)`, `repr`, arbitrary getters,
or cause/group traversal merely to populate a record. Reuse facts the native path
already computed; unavailable fields stay unavailable. The driver may separately
inspect the caught outward exception under its own bounded evidence rules outside
the core. Do not flatten native exception groups or invent a primary cause.

### Bundle, health, and outward observation

`CaptureBundle` owns case/environment/comparison references, operation/native-run
binding, the contiguous record prefix, immutable snapshot arena, captured limits,
and a copied health status. It also contains a separate **driver outward outcome**:
actual return, native exception, confirmed cancellation, or unresolved runner exit.
The latter is observed around the unmodified public call and required native close,
not obtained by appending another event through a failed collector.
The driver may temporarily hold the outward native object for bounded projection;
the retained bundle contains observed outcome facts/snapshots, not that live object.
Failure of this independent projection is unresolved driver evidence, never an
assumed success or a replacement exception sent back into native execution.

`CaptureHealth` is a session-owned preallocated object with slots for `enabled`,
`degraded`, `capture_busy`, first failed record kind, and fixed loss reason. Health
is not an AnyInfer error or a public event. A bundle marked degraded is not silently
usable as complete evidence, even if native execution returned successfully.

An early inspection can expose a nonterminal prefix. Sealing requires actual native
boundary completion or an explicit unresolved/abandoned driver outcome; it must not
pretend a still-live source has terminated. Abandoning capture disables further
capture without closing/draining the native source. Detach snapshot payloads into
the bundle/release them when the harness finishes; a live generator may retain only
disabled session/health state. No GC-based native close or accounting fix is added.

## 3. Snapshot materialization and native error selection

Snapshots accept only exact builtin null/bool/int/float/str/list/tuple/dict values,
with exact string object keys, plus explicit projections of known domain fields
supplied by the core. They do not duck-type a caller Mapping, call a custom iterator,
deepcopy, normalize schema keys, or serialize data as JSON inside the core. Unknown
types cause capture degradation while native handling continues unchanged.

| Input | Private immutable representation |
|---|---|
| Null / boolean / integer | Distinct kinds; exact immutable builtin value. No bool-as-int comparison or decimal conversion of a large integer. |
| Finite float | Binary64 observation, preserving signed zero. NaN/infinity use N1 special categories; no new NaN-payload/sign comparison requirement. |
| String | Exact immutable decoded string, including isolated surrogates; no normalization or UTF-8 conversion in capture. U1 export rules remain separate. |
| Array/container | Ordered immutable child-reference tuple. No retained mutable list as a snapshot. |
| Object/schema | Ordered immutable `(key, child_ref)` sequence. Preserve original assessment order; sorted injected prompt text is a different observation. |
| Error context | Actual selected primary and ordered child references, with typed paths/constraint data. Parent links are references rather than recursive parent serialization. Detect cycles/unsupported graphs and degrade instead of inventing a tree. |

The freezer is bounded/iterative and uses builtin operations only. Native immutable
primitives may be retained by reference; mutable containers are materialized at the
actual boundary. Internal identity memoization is allowed solely for traversal and
deduplication, never as a portable identity. An observed mutation/inconsistent
traversal degrades capture. This is not an atomic snapshot across concurrent mutable
containers or a promise to detect every mutation. The controlled harness must keep
case inputs stable for the captured interval; inability to establish that condition
blocks the affected comparison. No deep-freeze, new locking, or caller-mutation
policy is introduced into AnyInfer.

Proposed private harness defaults, fixed before a run and stored in its bundle:
4096 records, 65,536 snapshot nodes, 2,097,152 text codepoints, depth 128, 4096 error
nodes, and a 16,777,216-byte primitive-storage charge budget. These bound evidence
cost, not accepted request/response sizes, Python numeric limits, or the portable
profile. An explicitly larger case budget is declared before execution; no automatic
growth/truncation-to-pass. Exceeding a limit degrades capture and blocks affected
required comparisons while native processing retains its own limits.
The primitive-storage charge is a deterministic evidence budget, not a guaranteed
resident-memory ceiling for the Python process or a limit on native processing.

For ordinary instance errors, tap the actual single `iter_errors` enumeration to
retain occurrence ordinals, pass the same errors to the existing native sort/key,
and observe selected occurrences before `_describe`. Do not enumerate again or call
relevance a second time to infer what it did. Preserve stable ties, duplicate
occurrences, and multiplicity. Internal object/occurrence association must not change
the native ordering key; if occurrence correspondence is ambiguous, mark it incomplete.
The native cap remains five, not a capture-limit replacement.

For invalid schemas, observe the actual caught SchemaError before `.message` is
returned. Never re-run `check_schema`, select a different context leaf, or promote
T's context children into separate selected bullets. For extraction, capture only
the actual branch/candidate/decoder facts already obtained by the native extractor.

## 4. Proposed context propagation

Use an **explicit per-operation session**, with task-local state only for entry
enrollment and the synchronous schema-helper frame. A single long-lived ambient
session is rejected: AsyncStream can be created, advanced, and closed in different
tasks, and the sync facade uses another loop thread.

Use private names such as `CaptureSession` / `capture_session` for this carrier.
`_run_attempt` already has a native conversation `session`; capture must neither
replace that parameter/state nor be offered as provider session state on the wire.

### Enrollment and explicit carrier

1. The private async harness allocates session, limits, buffer, arena and health
   before calling the public API. Setup failure blocks the case before native entry;
   it does not create a native operation/call.
2. A private one-shot enrollment binding identifies that harness operation and its
   owner task. `_new_run` claims it once for ordinary generation, associates the
   actual native run ID privately, and returns an optional session alongside its
   existing request ID/builder. Its private declarations/call sites change together.
3. Pass the session explicitly through `_generate_request`, `_routed_stream`,
   `_route_events`, and `_run_attempt`. Handle `_routed_stream`'s existing fallback
   `_new_run` path too. Do not depend on future generator execution inheriting the
   creator task's ContextVar values.
4. `AsyncClient.stream` attaches the session to the created source and a private
   AsyncStream field/method without a new public constructor parameter. Construction
   is not execution. Foreign-task advancement/close uses that explicit session.
5. Enrollment is consumed once. Child tasks inheriting its binding cannot steal it:
   owner/claimed checks reject capture attachment and leave native execution alone.
   Nested/concurrent operations require separate harness enrollments/sessions; an
   unexpected extra run makes capture coverage incomplete rather than sharing records.

The harness enrollment context may surround a buffered public await, but its token
is reset only by its owner in the same harness task. It is not stored on a generator
or reset by a stream consumer. For stream construction, the harness exits enrollment
before later advancement. No caller-thread-context assumption supports the sync
facade: sync capture remains outside the first bounded implementation until an
explicit loop-thread enrollment bridge and its tests are designed.

### Synchronous helper frame

Core `_validate` binds a private frame containing the explicit session, invocation
and assessment references for the synchronous extraction/validation call only.
Reset its token in `finally` in the same task, before any yield/await. Public
`extract_json`/`validate` signatures stay unchanged. No active frame means their
existing direct-call behavior with no snapshots/enumeration/capture allocations.

Repair preparation already has the explicit session in `_run_attempt`: observe the
actual builder arguments/return there, without changing the public builder signature.
Its effective base is observed after native preparation, not copied from case input.
No synchronous helper frame lives across a provider await, yielded event, or close
from another task. Runtime/session references are never exported as portable data.

## 5. Placement preserves native evaluation and cleanup

| Native site | Proposed placement / prohibition |
|---|---|
| `_new_run`, `_generate_request`, `stream` | Bind privately after actual native run creation; preacceptance errors remain driver observations without a fabricated bound run. Do not use a new public client argument or the builder registry as capture storage. |
| `_route_events` / `_run_attempt` | Private attempt/session arguments follow actual native routing. Capture actual caught/recorded router handling with existing predicate/budget locals and existing AttemptRecord/ErrorInfo; no extra should_retry, snapshot or backoff call. Carry the predecessor link only at the actual retry continuation, then observe the next attempt independently. Preserve effective repair base; no second router or repair loop. |
| `adapter.generate(wire)` | Observe at its existing expression position, after pacing/timeout context entry. A private synchronous invocation helper may record entry/instant fault and execute the actual call exactly once. Never hoist it out of the async-with expression or count wire preparation/pacing as a call. Ordinary capture failure must still execute the native expression. |
| Optional iterator close | Share the existing close algorithm through a private implementation with explicit session support; exported `aclosing_if_supported(stream)` retains its signature/behavior. Do its optional closer lookup once at the native finally point and await the same closer. No iterator wrapper that invents `.aclose`, eager attribute probing, duplicate close, or lifetime changes. |
| Provider-context exit/conversion | Observe completion/fault after required cleanup and existing TimeoutError conversion. Keep earlier native faults as observations only when actually seen; the escaping error determines the native outcome. |
| Repair build | Native builder call is outside capture-fault exception guards. Only a successfully returned tuple is prepared. Native faults/interruption preserve their own identity and leave no fake messages. |
| Result/source/wrapper | Observe StreamEnded at actual receiving points and source/wrapper exit separately. Buffered return inside an async-with can still be replaced by its native exit fault; result observation does not mean outward return or accounting commitment. |

No capture callback, user code, warning, event emission, lock, new I/O, clock wait,
or additional validation is introduced at these sites. Capture work is synchronous;
the native close still performs its existing await. Exact factoring must prove that
disabled capture retains the original branch/evaluation order and enabled capture
does not add a scheduling policy. This is an implementation gate, not a timing claim.

Enabled capture consumes CPU and can affect wall-clock timeouts or races. There is
no zero-overhead or arbitrary timed-counterfactual equivalence guarantee. Keep actual
native deadlines/cancellation handling; do not pause/extend timeouts to hide capture
cost. Outcome-equivalence gates use controlled non-racing cases with adequate timeout
margin. Race cases retain the actual observed outcome and uncertainty, rather than
forcing a preferred cause or claiming that uninstrumented timing would match.

## 6. Capture-failure isolation protocol

| Condition | Required behavior |
|---|---|
| Capture disabled or already degraded | No payload materialization or record append. Native call/selection/build/cleanup continues. |
| Unsupported snapshot value, budget hit, projection/append exception inside capture code | Latch degradation, stop further capture writes, retain the successful prefix, continue native execution. No partial record is published. |
| Native extraction/validation/build/provider/cleanup exception | It is outside the capture guard. Observe best-effort, then preserve native propagation/handling/conversion exactly. It is not swallowed as recorder failure. |
| Native success after degradation | Driver retains the actual successful return separately; affected required evidence comparisons remain blocked. Do not invent a native error or green evidence result. |
| Native mismatch plus degradation | Established mismatches still fail; missing evidence is also reported. Incompleteness cannot downgrade a proved wrong native branch. |
| BaseException or catastrophic runner loss | No blanket BaseException swallowing, cancellation suppression, draining or retry. A capture frame left busy signals aborted/inconclusive capture to the driver. No complete native-conformance claim from this run. |

Every capture operation sets preallocated `capture_busy` before capture-only work.
It builds snapshots/records in a staging area, then appends atomically as a complete
private entry and clears busy. One published entry owns both its frozen record and
the immutable snapshot segment it references. The logical arena is the union of
published segments; staged nodes/IDs/counters cannot become visible first. References
may target only that segment or earlier published entries. An append failure leaves
no dangling published references; discard unpublished staging and retain the prefix.
Precompute charges/next ordinal before publication. Verify this publication boundary
under the chosen Python container implementation rather than assuming multiple
independent mutations are atomic. On **Exception from capture-only code**, it assigns
pre-existing constants to health slots: degraded=true, enabled=false, first kind and
loss reason; clears busy; and returns control to the native path. The guard never
encloses native calls, key functions, schema iteration, builders, or awaited cleanup.

This catch applies to Exception subclasses raised by the capture work, including
a MemoryError where latching/continuation is possible; it is not a claim that any
out-of-memory condition is recoverable. Do not allocate a formatted fault message,
append a last-ditch error event, call a user fault handler, or retry failed snapshot
work. If the fixed latch/driver cannot be trusted, the result is runner loss/inconclusive,
never an assumed complete capture. BaseException bypasses this guard and may leave
busy set; the driver records an aborted case without replacing native cancellation
or claiming an untouched counterfactual outcome under catastrophic failure.

Once degraded, counters beyond the retained prefix are unknown. The driver must not
derive total work or zero later calls from the prefix. It can still observe its own
outward return/exception. Missing tail SourceBoundaryOutcome records are not invented;
health/outward outcome are separate from the failed append channel. Successful
native output with incomplete evidence is not conformance success.

## 7. Comparison mapping and W1

Project completed AssessmentFinished/PreparationFinished/InvocationEntered facts
into the existing feedback/report proposals only when required fields and linkage
are complete. HTTP payload evidence remains a separate adapter assertion, never a
substitute internal wire snapshot. Scope is fixed from the planned case; capture
failure does not downgrade an exact I1 checkpoint or change expected branches.

The feedback comparison draft now includes proposed additional correction-stage
values `preparation_failed` and `preparation_interrupted` for an entered builder that
failed/interrupted, with message/wire/correction-call references absent.
`not_scheduled` remains for no builder entry, with its reason evidenced (including
disabled/exhausted or an earlier native interruption). These are draft amendments,
not existing SDK/ledger fields. Missing/live-tail evidence cannot establish this
negative claim; report an unavailable stage instead. No stage is inferred solely
from RepairAttempted.

RouteHandlingObserved supplies the native handled/decision role; a later linked
RouteAttemptBegan plus InvocationEntered supplies actual restart/entry evidence.
Cancellation or an observer fault after a retry decision but before continuation
does not create another attempt/call. A caught router error need not originate in
an invocation: post-result/source faults remain separately classified and cannot
be attached to the last call merely because it was most recent.

M1 classifies actual origin/stage/role while preserving native phase and retry fields.
Do not convert a provider error at cleanup into a generic nonretryable fault, or a
generic close fault into a provider error. ResultObserved supplies no accounting
commit evidence; post-result and postcommit are not synonyms.

**W1 remains unresolved.** Capture records can retain the actual null-metadata
nonfatal-feedback or promoted-warning branch under predeclared Python policies.
They cannot choose a portable expectation, manufacture feedback for a fault, expand
I1 membership, or freeze the affected profile by calling the other branch skipped.
No Python warning filter or other runtime's warning policy is selected by this design.

## 8. Future implementation map and required gates

These are proposed responsibilities only; do not create these files/changes now.

| Candidate path / symbols | Responsibility if separately approved |
|---|---|
| `src/anyinfer/_capture.py` | Private records/arena/session/health/enrollment/helper frame; stdlib-only leaf module. |
| `src/anyinfer/_client/async_client.py:_new_run/_generate_request/stream` | Claim enrollment, carry optional session privately, observe actual receiving/wrapper boundaries. |
| `src/anyinfer/_client/generation.py:_routed_stream/_route_events/_run_attempt/_validate` | Explicit context, real attempt/invocation/assessment/preparation/source facts; no policy changes. Update the mixin's private `_new_run` declaration too. |
| `src/anyinfer/schema/validate.py` | Tap actual extraction/caught/selected native evidence through the synchronous helper frame; retain public signatures and exact strings. |
| `src/anyinfer/providers/base.py:aclosing_if_supported` | Shared private factoring for explicit cleanup observation, preserving exported signature and optional-closer semantics. |
| `src/anyinfer/_client/stream.py:AsyncStream` | Private session attachment and actual advancement/close/result observations, without public constructor/API change or new close policy. |

Before an implementation brief: review records/presence rules, limits/staging and
ordinary/fatal guard placement; resolve native-error occurrence association and
comparison-stage amendments; approve precise enrollment/claim/detach/source-sealing
code locations. No implementation authorization follows from completing this draft.

Later authorized gates must cover disabled-hook equivalence; ordinary capture failure
at every boundary in controlled non-racing cases with adequate timeout margin and
unchanged native semantic handling/deadline policy; incomplete-tail reporting; exact
R/T all-variant error/order/message/wire linkage; prepared-but-uninvoked/faulted builds;
correction-c2 failure with actual handling/restart linkage and reset 1,1; a native
retry decision followed by interruption before another entry; normal/failed optional
close and immediate factory fault; concurrent/nested enrollment; stream creation/advance/close across
tasks; zero-advance close; result followed by teardown fault; and no new default
payloads/events/ledger inputs. Streaming/sync/cancellation/aggregate-accounting claims
stay gated until their own required cases are implemented and verified. W1 is not
closed by any of these mechanical checks.

Source anchors refer to the current core and audits. No new runtime evidence was
produced for this design; future gates above are requirements, not passing cases.

The source and supporting evidence record the rationale for the existing
RouteHandlingObserved linkage and controlled non-racing timing gate. They do not close
the remaining implementation, all-variant evidence, lifecycle, M1, or W1 gates.
