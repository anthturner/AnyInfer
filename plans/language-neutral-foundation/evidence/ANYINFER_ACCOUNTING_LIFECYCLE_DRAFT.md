# AnyInfer — draft accounting lifecycle and error matrix

> **Archived 2026-10-15.** Superseded by the revised [master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md)
> and [specification draft](../SPECIFICATION_DRAFT.md). Kept as input for milestone 3
> (operation accounting) and as rationale. Not an active plan; its checklists and gates do not apply.
> Primary input to milestone 3, box M3.1.

**Status:** planning proposal for selected L1; no accounting implementation or fixtures.
**Created:** 2026-10-14. **Evidence HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Resume/status:** [foundation plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Selected-policy owner:** the foundation plan.
**Record/aggregation owner:** [accounting candidate](ANYINFER_OPERATION_ACCOUNTING.md).
**Related:** [schema admission](ANYINFER_SCHEMA_ADMISSION_DRAFT.md),
[repair comparison](ANYINFER_REPAIR_FEEDBACK_DRAFT.md),
[P1 evidence](ANYINFER_P1_EVIDENCE_AUDIT.md).

This matrix proposes precise accounting observations around unchanged native Python
control flow. All new states/records/commit seams are additions, not existing Python
features. No cancellation dominance, live finalized notification, coordinated client
close, legacy ledger change, or private-builder leak fix is included.
Selected C1 permits an explicit unknown reporting reason for confirmed native cancellation when known
causes lack sufficient attribution evidence. Exact evidence/version/API rules remain gates.

**Language path:** Python is the current baseline; Python and C# are next proof targets.
Portable lifecycle and accounting semantics apply to every admitted future native language,
including Java or JavaScript/TypeScript on Node.js, through explicit native mappings.
They are not Python event/exception identities or C# types. SDK shape may be idiomatic;
shared versioned data and corpus requirements remain common, with no selected runtime
wrapper, mandatory generator, native binary, or wire encoding.

## 1. Proposed boundaries and ownership

| Boundary | Proposed observation | Current source / limitation |
|---|---|---|
| Acceptance | After request construction/coercion, route selection, and creation of the lazy source/handle have succeeded; publish operation identity with that handle. | `AsyncClient.stream` resolves the request/route before `_new_run` and returns `AsyncStream`. Construction failure is preacceptance; exact additive publication must be verified. |
| Execution start | First native source advancement, before its lazy preflight/telemetry. | Construction is not advancement. `RequestStarted` is later and can itself fail; it is not the accounting start trigger. |
| Adapter invocation | Immediately as the core crosses the adapter API boundary to evaluate `adapter.generate(wire)`, including an immediate exception from this generate method/iterator-factory call. | This is distinct from descriptor/provider-factory construction in `_pool.get`, which precedes the boundary and creates no call. Wire building, pacing acquisition, and timeout-context entry also precede it. Iterator creation, first advancement, dispatch, and receipt are separate evidence. Async-generator body execution is not the call-count trigger. |
| Invocation execution end | After adapter iteration and required provider-context cleanup end, whether successfully or by fault. | Final adapter usage is consumed before cleanup but merged into the legacy buffer afterward. New accounting captures observations without moving that legacy merge. |
| Call finalization | After invocation end and that response's validation/outcome classification, before a subsequent call entry or operation terminal commit. | A call may remain open for classification after its execution end offset is known. Validation time belongs to the operation interval; it is not appended to provider execution duration. |
| Accounting success | After existing completion callbacks and builder result/manifest preparation, immediately before successful `StreamEnded` is exposed. | Router `mark_healthy`, nested generator exit, and outer registry/ledger cleanup occur later. Success cannot mean all router teardown already finished. |
| Accounting failure/cancellation | When the native source has actually terminated before success commit, after required teardown has determined the escaping outcome; before propagation to the awaiting consumer if observable at an approved wrapper seam. | Do not commit a provisional failure while retry/cleanup can still replace it. The exact wrapper/exception seam remains implementation-design work. |
| Confirmed never-started close | Successful first close of an unadvanced native source; finalize zero-call consumer closure. | P1 observes no legacy telemetry/result, incomplete manifest, and a retained builder. Add accounting without asserting old cancellation telemetry or fixing the builder. |
| Postcommit fault | Separate bounded handle diagnostic referencing operation/committed revision. | Never mutate a committed snapshot, extend its interval, mask the native exception, or introduce a new live callback. Auxiliary representation remains proposed. |

An immutable snapshot contains one coherent summary and all its call revisions. A
semantic change publishes a higher operation revision; reading or replaying it does
not add work again. Terminal commitment requires every entered call to be final.
No synthetic call is created for health skips, route/preflight work, waiting, or a
repair that was prepared but never crossed the adapter API boundary.

## 2. Operation state and field validity

`elapsed_ms` below is the measured monotonic interval since execution start. Running
snapshots sample it; terminal snapshots freeze it. Zero is a measured zero when start
occurred, or the defined zero for a confirmed never-started terminal operation.

| Operation state | `finalized` / start / elapsed | Calls / `final_call_id` | `error` / `cancellation_reason` |
|---|---|---|---|
| No accepted operation | No snapshot or accounting ID. | None. | Public construction error may exist; it is not an operation terminal record. |
| `accepted` | False; `execution_started=false`; elapsed null. | Zero; final ID null. | Both null. A rejected/faulted close can leave this state if the source remains live. |
| `running` | False; start true; finite nonnegative measured elapsed. | Zero or more open/final calls; final ID null. | Both null. Earlier failed-call errors remain in call records; intent/nonterminal faults are diagnostics. |
| `succeeded` | True; start true; finite frozen elapsed. | At least one call; all final; final ID references the winning completed call. | Both null. Winning validation passed, or no schema was requested. |
| `failed` | True; started or confirmed never-started termination; frozen elapsed, zero when never started. | All calls final; may be zero; final ID null. | Bounded typed primary error required; cancellation reason null. Observed cancellation intent cannot overwrite the native primary failure. |
| `cancelled` | True; started or confirmed never-started termination; frozen elapsed, zero when never started. | All calls final; may be zero; final ID null. | Error null; reason `caller_cancelled`, confirmed `consumer_closed`, or selected C1 `unknown` when native cancellation is confirmed but attribution is insufficient. Unknown requires bounded attribution diagnostics; it is not unknown terminality. |

Started=false always implies zero calls. `repair_call_count` counts entered correction
calls, is at most `call_count`, and does not count `RepairAttempted` emissions alone.
Completed earlier calls may exist in failed/cancelled operations. A succeeded operation
may include earlier failed or schema-invalid calls. Failure/cancellation does not by
itself invalidate complete metric evidence; unknown dispatch/work never becomes zero.
Final zero-call metric totals follow the companion's zero-observed-invocation rule.

No transient winning-call ID is exposed as `final_call_id` before success commit.
Immutable finalized call records retain their earlier outcome even when operation
cleanup, a legacy callback, or a later call determines a different operation outcome.

## 3. Call outcome, validation, and error matrix

Call outcome describes the adapter invocation including required provider cleanup.
Core validation/result/observer faults are separately classified at operation scope;
they do not retroactively turn a successfully completed invocation into a transport
failure. This proposal clarifies the companion's completed-but-schema-invalid case.

| Observed call condition | Call outcome / validation | Call error | Operation consequence |
|---|---|---|---|
| Entered, iterator still active | `open`; validation `pending` if requested, otherwise `not_requested`. | Null until final classification; interim observed faults remain diagnostics. | Running; no success or failure merely from partial content/usage. |
| Invocation/cleanup completed, no schema | `completed`; `not_requested`. | Null. | Can proceed to result preparation. |
| Extraction and original-schema validation succeed | `completed`; `passed`. | Null. | Can succeed after later required result/callback/manifest steps. |
| Empty/malformed extraction, ordinary schema violations, or caught invalid-schema feedback | `completed`; `failed`. | Null; retain validation diagnostics separately. | Repair may follow with same target; exhaustion is an operation schema failure. |
| Provider exception, iterator fault, or immediate `generate(wire)` method/iterator-factory-call fault | `failed`; `not_performed` if schema requested, otherwise `not_requested`. | Actual primary exception after required provider cleanup. | Retry/fallback only where the actual exception path reaches the router's caught `ProviderError` handling and predicate/budget permit it. Otherwise the native fault escapes; accounting cannot make it retryable. |
| Terminal adapter response then cleanup fault | `failed`; requested validation `not_performed`. | Cleanup fault if it is the actual escaping primary. Earlier native exception is secondary only when actually observed. | Retain consumed terminal evidence; preserve retry predicate, original-request restart, and fresh repair budget. |
| Native cancellation/consumer closure ends invocation with successful cleanup | `cancelled`; requested validation `not_performed`. | Null; cancellation evidence separate from typed failure. | Operation cancellation only if this actually ends the operation before success commit. |
| Cleanup replaces cancellation with an escaping fault | `failed`; requested validation `not_performed`. | Escaping cleanup fault. | Do not force cancelled or suppress a retry; cancellation intent may be diagnostic evidence. |
| Invocation/cleanup complete, then close/cancellation ends the source before assessment finishes | `completed`; requested validation `not_performed`, with closure/interruption reason. | Null for the completed invocation. | Operation follows the actual closure/cancellation. This can happen at the synthesized terminal-usage yield before `_validate`; do not leave validation pending or relabel the invocation as cancelled. |
| Invocation complete, validator internally throws or assessment is interrupted | `completed`; requested validation `not_performed`, with reason below. | Null for the completed adapter invocation; operation receives the native assessment fault/cancellation. | No invented ordinary schema feedback; no implicit repair for an unexpected validator fault. |
| Completed assessment, then result preparation/legacy callback/builder fault | Preserve completed call and passed/failed/not-requested assessment. | Unchanged. | Observe native flow; failure can terminate the operation or be handled by existing routing according to the actual exception path. |

**Proposed missing-field amendment:** add nullable `validation_reason` to a call.
It is required for final `not_performed` and null for all other validation states.
Candidate reasons: `invocation_failed`, `invocation_cancelled`, `consumer_closed`,
`assessment_interrupted`, or `assessment_fault`. Here `not_performed` means no
completed validation assessment, including an assessment that began and was interrupted;
it does not falsely claim that no validation instruction executed. A final record
cannot retain `pending`. Exact category spelling/versioning remains D4/D8 work.

`response_complete` and `dispatch_state` are independent evidence fields. Cleanup
failure can coexist with response_complete=true. No `AdapterFinal` does not alone
prove false; empty usage does not alone prove no dispatch. Define mappings per
adapter before any conformance claim; the lifecycle enum cannot recover lost evidence.

## 4. Termination and close/error scenarios

| Native observation | Proposed accounting result | Existing channels / required qualification |
|---|---|---|
| Invalid public input before acceptance | No operation. | Preserve native exception and timing. |
| Lazy preflight/target/acquisition failure that ends the native operation before any adapter entry | Failed operation, started=true, zero calls. | Legacy `RequestFailed` may or may not exist; do not backfill it. A failure handled by native routing leaves the operation running instead. |
| Descriptor/provider factory fails during `_pool.get` | No entered generation call; operation follows native acquisition failure. | Distinct from `adapter.generate(wire)` throwing, which creates one failed call before first iteration. Do not instrument both as the same factory boundary. |
| Retryable correction provider failure, then successful original + correction | Earlier failed call retained; succeeded operation with all calls visible. | P1 restart trace has four calls, two corrections, legacy repair numbers 1 then 1, winning local repair count 1. |
| Schema exhaustion after completed response | Failed operation; final call remains completed/validation failed; final_call_id null. | Existing exception `SchemaViolationError`; no guaranteed `RequestFailed`; manifest/result semantics unchanged. |
| Cancellation requested while cleanup later drives retry | Remain running while native retry proceeds; eventual native outcome controls terminal state. | Intent alone cannot abort accounting/routing or relabel the failed call. Combined race is unexecuted evidence work. |
| Native caller cancellation escapes after teardown, before success commit | Cancelled operation, reason caller_cancelled; all entered calls final. | Native cancellation propagates. Every native port needs an evidenced cause/source mapping; exception-class names alone do not establish intent. |
| Native cancellation is confirmed but caller-versus-consumer attribution is insufficient | Cancelled operation, reason unknown; all calls final, with bounded observed attribution diagnostics. | C1 is reporting only. A cancellation-shaped exception alone does not prove caller intent. Do not guess a winner from first/last intent or use unknown to bypass terminal-state evidence. |
| Successful close of unadvanced source | Cancelled, consumer_closed, started=false, elapsed zero, zero calls. | New accounting only; old manifest incomplete/result unavailable, no legacy events in P1 probe. |
| Successful close before commit after some advancement | Cancelled, consumer_closed; earlier final calls unchanged, active call finalized by its own outcome. | Elapsed measured; `.result` unavailable unless independently captured. Provider cleanup and outer termination must actually finish. |
| Close fault/concurrent rejection while source remains live | Retain accepted/running state; publish observed fault/intent as bounded diagnostics in a new nonterminal snapshot revision. | `AsyncStream.aclose` sets its local `_closed` before awaiting source close. That flag and a later no-op close are not closure proof. Do not retry/serialize close as a hidden policy fix. |
| Faulted close actually terminates source before commit | Failed with actual terminal primary error; never-started termination has elapsed zero. | Do not label consumer cancellation merely because close was requested. Need observable source-end/error evidence. |
| Ordinary legacy observer exception is warned/suppressed | No new terminal state from the suppressed fault; continue native flow. | Preserve warnings and suppression behavior. |
| Legacy observer `BaseException` or warning-as-error escapes | Classify the native terminating cause after cleanup, unless existing routing handles it and continues. | An earlier ledger subscriber may already have counted completion; new accounting cannot undo or duplicate that input. |
| Builder note_result succeeds but a later build step faults | Observe native outcome; may fail before accounting success commit. | Manifest can already be complete while accounting fails and stream result is absent. Never force manifest completeness to match accounting. |
| Success committed, then consumer closes or native router/source teardown faults | Retain immutable success; record bounded postcommit fault independently; native error still surfaces. | `.result` can already exist while `collect()` later raises. Ledger is neither rolled back nor applied again. |
| Client adapter disposal | No automatic operation cancellation/terminalization. | Preserve current disposal; source termination is observed separately. No client_closed reason in this profile. |
| Unexpected source exhaustion without success/close/cancellation evidence | Proposed failed accounting diagnostic `missing_terminal_result`. | Preserve native exhaustion/collect behavior; do not invent a replacement surfaced exception. Reachability and category require verification. |

Current `_route_events` catches `ProviderError` for provider retry/fallback. Generic
iterator/cleanup errors, unexpected assessment faults, escaping observer
`BaseException`, and warning-as-error faults do not become provider retries merely
because they happened during generation. One existing conversion matters:
`_run_attempt` converts a caught built-in `TimeoutError` to retryable `TransportError`.
Observe the actual escaping exception after context cleanup/conversion and the scope
in which it is caught. Ordinary observer `Exception`, including a `ProviderError`
raised by an observer, is normally warned/suppressed before routing sees it.

For competing close/cancellation evidence, use the observed terminating native cause.
Selected C1 adds `unknown` attribution only when native cancelled termination is
already established and the two known causes lack sufficient evidence. Require a
bounded cause-attribution diagnostic describing observed source facts/flags; taxonomy
and caps remain D4/D8 work. This does not change cancellation/cleanup/routing control
flow. A source that is still live remains nonterminal; an unclassified terminal
outcome is still a freeze blocker. A cleanup fault remains the actual failure if it
replaces cancellation, including any retry driven by native handling. Committed
attribution cannot be rewritten when later evidence appears.

## 5. Completion order and terminal fault reporting

Proposed order, preserving the source's existing channels:

```text
adapter iteration -> required provider cleanup -> extraction/validation
call outcome finalized -> successful result preparation
legacy AttemptCompleted -> legacy RequestCompleted
builder.note_result -> builder.build/result attachment (if enabled)
new accounting success commit -> StreamEnded exposed -> AsyncStream.result capture
subsequent generator resume/close -> router health update where native flow reaches it
outer source cleanup: builder registry removal / legacy ledger release
```

The health update is not guaranteed on early close. Provider diagnostics/pricing and
result assembly occur before legacy completion; their faults remain native behavior.
The success accounting interval ends at commit. For a failure/cancellation before
commit, the interval includes native teardown needed to determine that terminal cause.
This asymmetry is intentional: neither success nor failure asserts caller collection.

| Error record field | Candidate rule |
|---|---|
| Semantic category/code | Stable profile meaning; preserve native exception identity internally. Full category registry/version is not frozen. Unknown native failures use an explicit unclassified category, never a success or transport guess. |
| `observed_stage` | Proposed separate stage of observation: preflight, adapter invocation, provider cleanup, assessment, result preparation, legacy callback, manifest preparation, router/source teardown, or consumer close. Do not overwrite an existing provider error's `phase`. |
| Provider / native phase / retryable / Retry-After / HTTP status / hint | Retain available structured fields with explicit null where unavailable. Actual router decisions remain native; accounting does not derive a new retry policy from this record. |
| Bounded redacted detail | Preserve useful terminal failure context without schema/output payloads, credentials, arbitrary native objects, or unbounded stacks. Exact caps are D4/D8 gates. |
| Secondary faults / cause evidence | Include only observed exceptions/causes. Earlier cancellation intent is not automatically a suppressed native exception. Do not flatten an exception group or choose its primary member without an explicit mapping. |
| Postcommit diagnostic | Independent bounded record tied to operation ID and committed revision; terminal snapshot and its revision remain unchanged. No live callback/persistent exporter required. Exact handle storage/inspection semantics remain an API gate. |

Before terminal commit, a close fault with a still-live source needs nonterminal
diagnostic access through the snapshot's existing diagnostics and a higher revision;
it must not populate summary.error while state is accepted/running.
After commit, diagnostics likewise cannot be appended inside the immutable snapshot.
The auxiliary bounded record surface is proposed for postcommit faults only, preserving
the terminal snapshot's equality/revision meaning. Its storage/access remains a gate;
no second diagnostics API is required for nonterminal faults.

## 6. Remaining evidence and review gates

The foundation plan owns selected M1: small semantic failure families plus observed stage and qualified native
evidence. Classification does not decide operation terminality, overwrite native
phase, or create retry policy. It does not freeze this accounting schema's error
registry/API. O1 private capture remains separate from accounting/legacy observers.
The [private capture design](ANYINFER_PRIVATE_CAPTURE_DESIGN.md) proposes concrete
records/carriers and fault isolation; its ResultObserved is evidence of native result
observation only, never this draft's unimplemented accounting success commit.

| Gate | What must be established before normative accounting |
|---|---|
| Handle/API | Accepted-operation publication, success-only legacy result access, buffered-generation failure inspection, and bounds/lifetime of auxiliary diagnostics. No new public API chosen here. |
| Native races | Source termination evidence for rejected/faulted close, cancellation masked by cleanup, concurrent advancement, and ambiguous terminating cause. Existing `_closed` does not answer these. |
| Error mapping | Validation interruption, generic/fatal exceptions, exception groups/chains, observer warnings, and faults during cleanup. Preserve native outcomes while capturing evidence. |
| Retry fault classes | Pair caught retryable/nonretryable `ProviderError` with generic iterator/cleanup errors, built-in timeout conversion, observer suppression, and escaped fatal/warning faults. Assert native retry/call counts; accounting classification must never create an extra retry. |
| Atomic state | One coherent snapshot per revision; all calls final before terminal commit; no manufactured outcome from locking/scheduling; stable ID ownership. |
| Postcommit continuation | Verify that supported native paths cannot re-enter an adapter after success commit. If a later fault is handled by routing and does cause more calls, immutable success plus complete operation accounting conflict; stop and revise the commit boundary/contract explicitly. Do not discard the calls or stop native routing as an instrumentation fix. |
| Compatibility | Completion callback/builder/result ordering, postcommit faults, old ledger/event/manifest behavior, and prepared-but-unentered corrections. |
| Route scope | Specialized context/content-policy chains remain D8/C11 scope work. If admitted, add their response-discard/validation-not-performed and redirection cases; do not treat the current table as defining or silently excluding them. |
| Observation/pricing | D5/D8 evidence preservation, validity/source/coverage, and independent tariff/aggregate rules remain unresolved by this lifecycle table. |

The [I1 native history audit](ANYINFER_I1_NATIVE_HISTORY_AUDIT.md) now directly
observes buffered representative exhaustion, correction-failure restart/reset, null
warning branches, and iterator-close-before-schema-assessment behavior. It also
observes the absence of legacy terminal events on its failure paths. None of the
proposed accounting records/commit/race semantics was implemented or verified there.
The rest of this table retains its source-derived/proposal evidence level.
Source anchors: `_client/async_client.py:stream/_new_run/aclose`,
`_client/stream.py:AsyncStream`, `_client/generation.py:_routed_stream/_route_events/_run_attempt/_validate`,
`providers/base.py:aclosing_if_supported`, and `events/observers.py:EventDispatcher.emit`.
T1–T5 provide first-profile trace families; T6 persistent ingestion remains deferred.
