# AnyInfer operation accounting — candidate contract and traces

> **Archived 2026-10-15.** Superseded by the revised [master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md)
> and [specification draft](../SPECIFICATION_DRAFT.md). Kept as input for milestone 3
> (operation accounting) and as rationale. Not an active plan; its checklists and gates do not apply.
> Primary input to milestone 3, box M3.1.

**Current decisions, execution status, and next authorized work belong to [the
foundation plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md). Resume from its first
authorized unchecked box after reading this supporting contract.**

**Status:** active candidate definition; selected policies and open gates are distinct
below. It is not frozen or implemented.
**Created:** 2026-10-14.
**Evidence baseline:** HEAD `13b9e65acfb01038464069ca5fa80f50a9df035c`.
The [P1 evidence audit](ANYINFER_P1_EVIDENCE_AUDIT.md) adds 302 passing targeted
existing tests and bounded probes to the original source inspection/logical traces.
There are no executable candidate-accounting fixtures or implementation results.

This companion records accounting refinements. The selected direction is additive accounting while
preserving Python's current restart/repair-budget and ledger behavior. The fields,
wire encodings, race rules, and diagnostics below are proposals to test against that
direction. A contradiction or observable behavior change must be surfaced before freeze.
Selected policy is snapshots first, observing native outcomes. It excludes mandatory
live finalization delivery and cancellation-dominance assumptions; field and evidence
gates remain open.
The [lifecycle/error matrix](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md) owns the detailed
candidate state validity, boundary ordering, validation reasons, and native-error
mapping. This companion owns the aggregate record definitions/rules and trace families.
The [schema](ANYINFER_SCHEMA_ADMISSION_DRAFT.md) and
[repair comparison](ANYINFER_REPAIR_FEEDBACK_DRAFT.md) drafts supply related proposals;
none is a frozen specification or an implemented observation bridge.
The foundation plan owns the selected-policy ledger. C1 extends candidate cancellation
attribution as reporting only; N1/U1's permissive
response-value observations do not change accounting count/money validation rules.

**Language path:** Python is the current baseline. Python and C# are next, to prove
portable semantics and shared corpus/data requirements without making Python classes or
C# types the contract. Any admitted future native language (for example Java or
JavaScript/TypeScript on Node.js) maps these requirements explicitly; SDK shapes remain
idiomatic. No runtime wrapper, mandatory code generator, native binary, wire encoding,
or library is selected here.

## 1. Boundary and compatibility

An **operation** is one accepted logical generation request. An **invocation/call**
is one entry into the adapter's generation invocation, including original requests,
corrections, retries, and fallbacks. It is not evidence that a physical network request
was sent, that the provider performed work, or that billing occurred. Hidden provider
retries/work are outside the observation boundary.

Health suppression, rejected preflight, and retry waiting do not create call records.
An entered invocation that fails before dispatch does create one. Request creation
that fails before acceptance creates no operation. The exact acceptance boundary for
each public SDK method must be specified at the lifecycle gate.

The existing result and event contract remains intact:

- `Generation.usage` and timing remain the winning call's current view; local
  `repair_attempts` does not become an operation-wide counter.
- `AttemptRecord` remains a routing trail, not a record for every correction.
- `RequestCompleted`, `RequestFailed`, and `RepairAttempted` retain their meanings.
  `RepairAttempted.attempt_number` remains local to each outer routing attempt and
  resets on restart; it is not the new operation-wide `repair_call_count`.
- `SpendLedger` still counts completed-request usage and keeps its existing unknown
  counts/reservations; `SpendStore` is not silently upgraded or repurposed.
- `RunManifest.complete` retains the existing builder condition `result is not None`:
  an existing generation result has been assembled. Aggregate state/finalization
  never overrides this condition, including failure/cancellation snapshots.
- Usage normalization/merge/sum helpers are not silently changed by these new rules.
  In particular, new zero-call aggregates do not redefine `Usage.sum([])`.

An opt-in aggregate consumer would use a separately identified finalized-operation
snapshot/handle with deduplication if it persists records. No new live accounting
notification is required by the first profile. A persistent consumer/store is also
excluded initially; its constraints are recorded for future implementation.

## 2. Proposed records

An immutable `AccountingSnapshot` contains `summary` and ordered `calls`, all
describing the same operation revision. Consumers replace snapshots; they do not
add a snapshot to its predecessor. Field names below are working names, not public
SDK symbols. Fields are required with explicit null where indicated; optional future
extensions and unknown-field policy require a versioning decision.

### OperationSummary

| Field | Candidate meaning |
|---|---|
| `format_version`, `contract_revision`, `profile` | Record-format version, immutable **accounting specification** revision, and applicable behavior profile. Neither revision is a provider snapshot date. Actual IDs/release policy remain open. |
| `operation_id` | Core-assigned collision-resistant operation identity. Do not trust caller correlation data as identity or assume old request IDs are valid operation IDs. |
| `request_id` | Optional correlation with existing events/manifests; reuse an existing core ID only after its scope/collision properties are verified. |
| `revision` | Strictly increasing operation-wide semantic snapshot revision. One revision cannot name different accounting content. |
| `state`, `finalized` | `accepted`, `running`, `succeeded`, `failed`, or `cancelled`; terminal states have `finalized=true`, and nonterminal states have `false`. Exactly one terminal commit. |
| `execution_started`, `elapsed_ms` | Start flag and operation execution elapsed time, including preflight, calls, validation, backoff, and required provider cleanup. Null before start; final never-started operation has elapsed zero. |
| `call_count`, `repair_call_count` | Entered adapter invocations and entered correction invocations across all routing attempts. Scheduling a repair that never enters the adapter does not increment these. |
| `final_call_id` | Successful result's invocation; required for success, otherwise null. Completed calls may exist in failed/cancelled operations. |
| `metrics` | Aggregate observations for the fixed applicable metric set, with coverage counts and withheld complete totals. |
| `pricing` | Separate reported-charge and calculated-estimate summaries with their evidence/coverage; not a combined dollar total. |
| `error` | Required bounded/redacted terminal error for `failed`; null otherwise. Cancellation reasons are separate from typed failures. |
| `cancellation_reason` | `caller_cancelled`, confirmed `consumer_closed`, or selected C1 `unknown` when native cancellation is confirmed but cause attribution is insufficient; null otherwise. Unknown requires bounded attribution diagnostics, not guessed terminality. `client_closed` remains deferred. Native-cause mapping, evidence taxonomy, races, enum versioning and API remain gates. |
| `diagnostics` | Bounded/redacted discrepancies, invalid observations, and precommit secondary/nonterminal faults; no prompts, output payloads, credentials, or arbitrary provider objects. Postcommit faults need a separate bounded observation surface because the terminal snapshot is immutable. Diagnostic taxonomy/caps remain open. |

### CallRecord

| Field | Candidate meaning |
|---|---|
| `operation_id`, `call_id`, `sequence` | Operation identity, unique call identity within it, and invocation-entry order. The tuple `(operation_id, call_id)` identifies a call; sequence is contiguous and starts at one. |
| `route_attempt_id` | Identifies one outer routing attempt. Original and correction calls share it; a retry/fallback gets another. Skipped targets are not calls. |
| `repair_index`, `trigger_call_id` | Original call has index zero; correction indices increase within the routing attempt and reset on restart. Corrections point to the invalid response that triggered them. Exact causal metadata for retries/fallbacks remains open. |
| `target` | Actual resolved provider/model, not just requested alias or display label. |
| `state`, `outcome` | `open`/`final`; null outcome while open, then `completed`, `failed`, or `cancelled`. A completed response may fail schema validation. |
| `validation` | `not_requested`, `pending`, `passed`, `failed`, or `not_performed`. Final records have no pending validation. Define which state applies when validation itself is interrupted or throws. |
| `validation_reason` | Proposed nullable reason required for final `not_performed`, otherwise null. The lifecycle matrix distinguishes invocation failure/closure from assessment interruption/fault; this field is a candidate amendment, not a released API. |
| `dispatch_state` | `not_attempted`, `attempted`, `response_received`, or `unknown`, based only on observable evidence. Call entry alone is insufficient for `attempted`. |
| `response_complete` | True/false/unknown, independent of invocation outcome. A full response followed by cleanup failure may have true with `outcome=failed`. Exact response-completion evidence requires adapter mapping. |
| `timing` | Monotonic operation-relative invocation start/end offsets and nullable call-relative first-content latency. Invocation end includes required adapter cleanup; validation/classification can finish afterward. No cross-process clock comparisons. |
| `metrics`, `estimates` | Separate per-metric observed values and estimated values with provenance/coverage. Estimates never fill observed totals. |
| `error`, `secondary_errors` | Native invocation/provider-cleanup primary failure if failed; bounded/redacted additional observed errors. A cleanup fault may be primary even if cancellation was requested; do not demote it automatically. Completed response assessment/result/callback faults are operation-scope errors; schema-invalid completed responses use validation diagnostics rather than masquerading as transport failure. See the lifecycle matrix. |

`MetricObservation` has `value`, `basis` (`reported`, `derived`, `unknown`),
`coverage` (`complete`, `partial`, `unknown`), a nullable versioned `method`, and a
nullable uncertainty reason. Unknown observations have null value; known partial
observations retain a value with a reason. Derived observations require a reproducible
method and the input evidence. The validity matrix must be made explicit in the schema.

Draft generation metrics are `input_tokens`, `output_tokens`, `total_tokens`,
`cache_read_tokens`, `cache_write_tokens`, and `reasoning_tokens`. Their applicability
rules still need approval. Search units, server-tool counts, embeddings and reranking
do not become first-profile metrics merely because Python's `Usage` also carries them.

Draft wire representation: semantic integer counts/ordinals/revisions as canonical
decimal strings, finite money as canonical plain decimal strings, durations as finite
nonnegative milliseconds. These choices are **not frozen**. Specify integer bounds,
decimal precision/rounding, leading zeros/signs, duration encoding, invalid numeric
inputs, size limits, equality, and representability in each admitted native runtime
before release; C# is the next implementation to verify.

## 3. Observation and aggregate rules

### Per-call observation

1. Normalize adapter usage into cumulative snapshots before overlaying. A provider
   dialect that emits deltas needs an explicit adapter normalization rule; do not add
   every `UsageUpdate` indiscriminately.
2. Missing fields do not erase known observations. Known zero requires evidence.
3. Valid reported values outrank derived values. Terminality selects precedence only
   among otherwise equally ranked valid observations. Exact same-rank source ordering
   must be specified rather than inferred from thread/event arrival.
4. Recompute derived totals when their component evidence changes; derived totals
   cannot overwrite a valid explicit reported total.
5. An invalid terminal value is not equivalent to an absent value. Preserve the last
   valid observation as partial, with a per-metric invalid-terminal marker/diagnostic.
   Later derivation or an omitted field cannot restore complete coverage. A valid
   authoritative replacement before finalization may clear that metric's marker.
6. Preserve valid but inconsistent provider reports and diagnose the discrepancy;
   do not silently replace a reported total with input plus output. The gate must
   specify whether a discrepancy affects each metric's coverage.
7. Capture consumed terminal usage before cleanup can throw. This is an accounting
   addition; existing winning-result merge/validation order must be preserved.
8. Complete coverage means the observation covers that call's reported scope according
   to the profile; it does not certify the provider's accuracy or eventual invoice.

> NOTE: P1 found that current `UsageUpdate`/`AdapterFinal` carry no basis, coverage,
> validity marker, or source ordering. The compatible adapter can derive a total or
> drop a malformed field before emitting usage. D5/D8 must define an evidence-preserving
> observation path or honest degradation for legacy adapters. These candidate rules
> cannot be inferred from current `Usage`, and do not authorize changing its merge/
> normalization behavior. See audit C07/C08 and probes P3/P4.

### Operation aggregation

The applicable metric set is fixed by the generation profile and cannot change mid
operation to hide missing observations. Applicability is distinct from reporting:
an applicable unreported cache metric is unknown unless evidence supports zero.
Unsupported operation kinds must not leak into a generation call's aggregation.

For each applicable metric:

- `observed_subtotal` sums known complete and partial call observations. It is null
  if calls exist but no call has a known value; it is not a guaranteed billing lower bound.
- Coverage counts classify every call as complete, partial, or unknown, and sum to
  `call_count` for that metric. Validation failure does not automatically make provider
  usage partial; failed/cancelled invocation status is not a usage-coverage shortcut.
- `complete_total` is withheld until operation finalization, and then exists only
  when every applicable call observation is complete. Failure/cancellation alone does
  not prohibit a complete total when all observed calls have complete evidence.
- A finalized zero-call operation has subtotal and complete total zero with all
  coverage counts zero. This is zero observed invocation work, not proof that no
  preflight/cleanup work or external provider work occurred.

Timing is separate from metric summation: use a monotonic execution interval for
the operation, not a sum of call durations. Retry waits and validation belong in the
operation interval; post-terminal wrapper diagnostics do not reopen it.

### Pricing evidence

Keep `reported_cost_usd` for an actual directly reported charge separate from
`priced_cost_usd` for a calculated estimate. Python's current `Usage.cost_usd` can
hold either a provider-reported value or centrally computed pricing; `with_cost`
preserves an existing value. The bare field does not identify its origin. Do not
relabel every value as reported or computed, and do not add the interpretations together.

A calculated estimate needs an immutable tariff snapshot or resolvable immutable
reference, target/model, currency, rates and units, required billed dimensions,
method/rounding version, and observed input evidence. A partial sum may be exposed
as `priced_subtotal`; `fully_priced_estimate` requires all applicable calls to have
complete required inputs and a valid applicable tariff. Missing cache dimensions
can block full pricing even when total tokens are known. No tokenizer estimate may
make this observed-input condition pass.

Tariff schema, rate applicability, discounts, currency policy, retained provenance,
and rounding are decision-gate work. Default unknown pricing is preferable to a
plausible number whose assumptions cannot be inspected.

> NOTE: Current pricing can compute a legacy cost with missing cache figures, even
> when cache rates exist (audit P5). A stricter `fully_priced_estimate` belongs only
> to the new view; existing `Generation.usage.cost_usd` and ledger totals stay intact.
> Tariff-required dimensions and observation provenance must be explicit before freeze.

## 4. Lifecycle, uncertainty, and terminal failures

Selected L1 uses a single immutable accounting terminal commit while observing
native control flow. It does not introduce a controller that changes retry,
cancellation, cleanup, disposal, or legacy callbacks. Accounting state updates must
be coherent without serializing native execution differently to manufacture outcomes.

> NOTE: P1.3 defers cancellation dominance, client-close coordination, new live
> finalization callbacks, and changes to legacy observer isolation. Current Python
> still lacks universal failure telemetry; legacy completion precedes manifest/result
> capture. Preserve those meanings and expose terminal accounting independently.

- Create an accepted accounting handle before execution begins, if the approved SDK
  API exposes one. Argument rejection before acceptance creates no handle/summary.
- Observe first native advancement before preflight as execution start. A successful
  zero-advance `aclose()` confirms consumer closure and finalizes the new accounting
  view as cancelled, never started, elapsed zero, and zero calls. This is a new
  accounting finalization, not a claim that legacy cancellation telemetry exists.
- Close/cancellation intent alone is nonterminal. A close fault or concurrent close
  rejection must not be reported as successful closure. If the source is still live,
  retain nonterminal accounting; if it has ended, classify the actual native outcome.
  Precise race/error cases must be verified before freeze.
- Finalize an invocation after required provider cleanup and validation/outcome
  classification. Cleanup failure follows the existing router's error predicate;
  a failed call does not itself force immediate operation failure.
- Mark cancellation when native cancellation actually ends the relevant flow or
  consumer closure is confirmed. If cleanup replaces cancellation with an error,
  preserve that primary error and any retry it drives. Record cancellation intent
  only where observed; do not relabel a failed call as cancelled. A later operation
  success does not erase the earlier call failure.
  If cancellation is confirmed but caller/consumer attribution cannot be established,
  selected C1 permits unknown reason with bounded evidence. It does not make close
  intent or `_closed` proof of termination and never changes native control flow.
- A terminal failure/cancellation before accounting success commit can finalize the
  operation while previously finalized calls remain unchanged. A request to cancel
  alone cannot do so. No close/late error reopens a committed terminal snapshot.
- On success preserve this order: required provider cleanup and validation;
  assembled result; legacy `AttemptCompleted`; legacy `RequestCompleted`; existing
  builder result/manifest completion when enabled; accounting success commit;
  `StreamEnded`; stream-handle result capture. Existing callbacks/ledger inputs are
  not reordered. An escaping legacy callback failure before commit follows native
  behavior, even if an earlier subscriber already counted completion.
  Router health marking and outer generator teardown follow `StreamEnded` in current
  source. They are not prerequisites already completed at this proposed commit seam;
  the lifecycle draft explicitly gates postcommit fault/continuation handling.
- Accounting success describes the prepared core result, not guaranteed consumer
  collection. During a legacy completion callback the snapshot may still be running,
  manifest incomplete, and `.result` unavailable. Failure/closure ordering and
  postcommit wrapper faults require explicit state/error cases.
- The first profile requires inspectable snapshots, not `OperationFinalized` delivery.
  No new finalization callback reaches old subscribers; the old dispatcher, including
  `BaseException`/warning behavior, remains unchanged. Live notification delivery,
  isolation, and reentry are deferred to a separate opt-in design.
- The handle is the authoritative inspection surface, including failure and
  cancellation. `.result` remains success-only under existing stream semantics.
- Faults after commit are separately bounded diagnostics; a finalized snapshot is
  not edited in place and the execution interval does not grow afterward. Preserve
  native surfaced errors; the auxiliary diagnostic surface still needs definition.
- Client adapter disposal is not automatically `client_closed` cancellation. The
  retained builder on Python zero-advance close is a separately named cleanup issue;
  accounting does not implicitly fix it or require another native port to reproduce
  the private leak.

An adapter call may be entered yet have unknown dispatch or completion. An early
disconnect may leave all usage unknown. Preserve those distinctions; neither a
transport exception nor cancellation proves zero provider work.

The above requires a precise state/error validity table, observed start/closure
linearization, disposition of validation exceptions, source-to-error mapping,
legacy-callback interactions, and executable race cases before it can be normative.
It does not authorize changing native cancellation/cleanup behavior as instrumentation.

## 5. Adversarial trace catalogue

These six trace families test the most recent findings. Expected states below are
candidate expectations. The actual Python driver must verify existing behavior and
identify where additive instrumentation or a separately approved behavior change is
required. They are not six passing tests.
P1 observed selected baseline paths: HTTP failure during correction followed by
restart/reset, zero-advance close, schema failure telemetry, usage helpers, and pricing.
It did not execute the new records or the terminal-usage-then-cleanup-fault/cancellation
variants. The audit's trace-disposition table records this distinction.

### T1 — Cleanup failure, retry/repair reset, and cancellation races

Route retry attempts: 2. Requested repair budget: 1. Script:

```text
route attempt A / c1 repair_index=0: original request -> invalid JSON
route attempt A / c2 repair_index=1: correction -> AdapterFinal -> retryable TransportError in cleanup
route attempt B / c3 repair_index=0: original request -> invalid JSON
route attempt B / c4 repair_index=1: correction -> valid JSON -> cleanup succeeds
```

Expected normal path: four call records, two entered repair calls, and final call
`c4`. The final Python result still has local `repair_attempts=1` and winning-call
usage/timing. Legacy `RepairAttempted.attempt_number` values are `1`, then `1`, not
`1`, then `2`; only new accounting uses the operation-wide repair count of two.
`c2` retains observed terminal usage, has failed outcome and validation
not performed. `c3` must use the original request, not `c2`'s correction conversation.
Both outer attempts get their own repair budget. Exact route/correction counts must
be asserted with request captures, not inferred only from the returned text.

Mutations under selected native-outcome L1:

- Request cancellation while `c2` is open, then fail cleanup. Do not assume the
  fault is secondary or forbid `c3/c4`: record the actual primary error and preserve
  the retry path it drives. If native cancellation instead ends the flow, account
  for that outcome. This combined race remains unexecuted and needs a native trace.
- Finalize a call, then native cancellation/confirmed closure ends the operation
  before success commit: cancelled operation, immutable finalized call. Mere intent
  before commit is insufficient; a pending cancellation may surface after commit.
- Close after success commit: no outcome replacement or second ledger application.
  Preserve any surfaced wrapper/close fault as postcommit behavior/diagnostics. No
  live finalized notification is required in the first profile.
- Use `StreamProtocolError` after content versus retryable transport failure after
  content: preserve Python's specific routing distinction; do not apply a universal
  partial-content no-retry rule.

### T2 — Invalid terminal observation must not become complete again

```text
c1 reported total_tokens=10 complete
c1 terminal reported total_tokens=-1 (invalid)
c1 derive total_tokens=10 from otherwise valid components
```

Expected candidate: retain total 10 as partial with invalid-terminal reason;
derivation cannot clear it, and finalized complete total is absent. Missing terminal
value alone would retain the previous valid observation without fabricating this
invalid-value condition. An authoritative valid replacement before finalization can
clear the total's marker; unaffected metrics retain independent coverage.

Additional mutations: nonfinite number, overflow under the chosen bounds, malformed
numeric string, invalid zero/sign encoding, and update arriving after finalization.
The exact permitted replacement window and update-source rank are freeze blockers.

### T3 — Derived recomputation and reported precedence

```text
input=6, output=4 -> derived total=10
output changes to 5 -> derived total=11
reported total=12 -> reported total retained
later terminal derived total=13 -> cannot replace reported 12
valid higher-precedence reported replacement=13 -> replace reported 12
```

Expected candidate: recompute when derived inputs change; explicit reported totals
outrank calculated totals regardless of terminal flag. Diagnose disagreement with
components. Define the source rank, coverage on discrepancy, and derived coverage
when one input is partial before writing an executable expectation.

### T4 — Fixed applicability, unknown charges, and missing tariff inputs

```text
c1 complete reported total_tokens=10
c2 complete reported total_tokens=15
neither call reports an actual monetary charge
cache inputs required by the chosen tariff are missing
```

Expected finalized candidate: observed subtotal and complete token total 25, two
complete total-token calls, and unknown reported charge. Full calculated pricing is
absent because required inputs are missing. No search-unit aggregate appears in the
generation profile. A complete observed cache zero requires evidence; a tariff that
genuinely does not need that field must state that in its calculation method.

Mutations: use a rerank/search call as generation input and require explicit unsupported
failure; report cache values as known zero versus missing and observe pricing coverage.

### T5 — Snapshot ordering, conflicting revisions, and start/close races

```text
r0 accepted
r1 running
r2 open c1 with 5 observed tokens
r3 final c1 with 12 observed tokens
r4 finalized operation with total 12
snapshot observation/replay order: r3, r2, r4, r4
```

Expected consumer: accept `r3`, ignore stale `r2`, replace with `r4`, and ignore
identical `r4`. Do not add 5+12+12. Equal identity/revision with different accounting
content is a conflict, not an update. Canonical equality must ignore object key
order/serialization whitespace while retaining all semantically meaningful content.
This tests snapshot semantics; it does not require live push delivery.

Start/close mutations:

- Successful close completes before first native advancement: cancelled new accounting
  view, never started, elapsed zero, no calls; legacy manifest/result access unchanged.
- Start wins then native cancellation/confirmed closure ends flow before dispatch:
  cancelled, started, measured elapsed, no call if adapter entry did not occur.
- Close fails/rejects while source remains live: retain nonterminal state and record
  observed fault/intent; do not invent closure or change native execution ordering.
- Start wins then preflight rejection: failed, started, measured elapsed, no calls,
  typed failure required.
- Adapter entry wins before dispatch failure: one failed call, dispatch evidence may
  still be `not_attempted` or `unknown`; it is not a zero-call operation.

### T6 — Durable ingestion identity and delivery limits

This family constrains a future opt-in persistent aggregate consumer, not mandatory
first-profile persistence:

```text
ingest finalized operation O1 with complete total=10 -> stored total 10
restart; re-ingest identical O1 -> stored total 10
re-ingest O1 with conflicting finalized total=12 -> conflict; stored total remains 10
ingest new finalized operation O2 with total=12 -> stored total 22
```

Commit deduplication identity/equality evidence and aggregate application atomically:
a crash must persist both or neither. Legacy rows without a valid new identity cannot
enter this ingestion path. Keep incomplete/unknown counters distinct from known
subtotals; the trace's arithmetic assumes complete records.

The finalized handle remains inspectable even when an optional exporter/consumer
never ingests it. Such a consumer cannot count the operation or claim complete session/
provider billing. Live finalization notification and outbox/disk writes are excluded
from the first profile; a future exporter requires separately selected delivery rules.

## 6. Source-backed facts and gaps to verify

| Fact or gap | Anchor / consequence |
|---|---|
| Repair budget is computed within `_run_attempt`; outer retry invokes it again. | `_client/generation.py`: `_route_events`, `_run_attempt`, `_repair_budget`. No request-wide ceiling is introduced. |
| Corrections use original messages plus latest invalid output/errors. | `schema/repair.py`: `build_repair_messages`; `_run_attempt` assigns `current` from `request.with_messages(...)`. No cumulative correction conversation. |
| Terminal adapter usage is captured before context exit but processed after cleanup. | `_run_attempt` captures `AdapterFinal`; merge follows `aclosing_if_supported`/timeout/pacing contexts. Cleanup failure can lose observations from the current public result/event path. |
| Final winning-call usage gets pricing; completed-request telemetry feeds the ledger. | `_run_attempt`, `capabilities/pricing.py`, `events/telemetry.py`, `capabilities/ledger.py`. Aggregate computed price is a separate addition. |
| `Usage.merge` overlays known fields; `Usage.sum` requires every part known and returns unknown for an empty input. | `types/results.py`: do not reinterpret these helpers as snapshot ingestion or a zero-call summary. `server_tool_uses` is not covered by those helpers and is outside the initial profile. |
| Stream consumption is lazy; existing `.result` is available only after `StreamEnded`. | `_client/stream.py`: `AsyncStream`. New never-started/failure/cancellation inspection requires an approved API/lifecycle seam. |
| Corrections are not independent legacy routing records or ledger entries; repair-event numbering is local to each outer attempt. Unhealthy skips still create legacy routing entries. | `AttemptRecord`, `RepairAttempted`, `RequestCompleted`, `SpendLedger`; `_route_events` appends `skipped_unhealthy`, while new accounting adds no call for a skip. Preserve those distinctions. |
| No committed direct tests were found for failed-correction repair-budget reset, cleanup-before-validation/usage loss, or zero-consumption stream close. | P1 in-memory probes verified restart/reset and zero-advance close's current behavior; the cleanup-fault accounting case remains source-only. Existing modules are starting points, not a new-accounting pass. |

> NOTE: Evidence strength is recorded in the P1 audit. Static control flow and bounded
> observations are not an executed portable conformance kit. S1/F1/L1 directions are
> selected; detailed schema, feedback-evidence, state/order, and wire gates remain.
> any discovered mismatch must be classified before changing code.

## 7. Conditions before freezing or implementing

The foundation plan's D1–D8/P1–P4 gates own execution. This list defines the missing
precision those gates must supply, without creating a second status checklist:

- Verification of the draft state/field validity matrix: nullability, dispatch/completion evidence,
  terminal errors, validation interruption, cancellation cause/evidence mapping, final
  call identity, and zero-call terminal aggregates.
- An exact acceptance/start/terminal linearization and separation of required provider
  cleanup, legacy callbacks, accounting commit, and postcommit wrapper teardown.
  New live finalized notification is deferred; it is not a first-profile freeze gate.
- Metric applicability, supported units/ranges, source ranking, invalidation/replacement
  window, discrepancy coverage, and propagation through every derived metric.
- Canonical numeric and identity encoding, version compatibility, immutable revision
  rules, equality/conflict detection, and bounded diagnostic/error schemas.
- Inspectable immutable price evidence and separate provider-charge/calculated-price
  coverage, including the case where no tariff is available.
- A concrete nonbreaking Python accounting handle API and old observer/ledger/manifest
  regression expectations. Reuse of existing request IDs must be demonstrated.
- Executable request/event/error/clock traces for the first-profile portions of
  T1–T5, with intentional unsupported cases and no silent schema/accounting capability
  skips. T6's persistent-store cases remain deferred; do not turn them into a
  first-profile freeze gate by referring to all six conceptual families together.
- If persistent aggregate ingestion is later selected: a separate store format,
  atomic identity-and-totals application, conflict checks, explicit unknown counters,
  and a stated delivery/completeness scope. No legacy automatic migration.

Until these conditions are closed, this definition is a reviewable working reference.
It is sufficient to guide a bounded evidence audit, not to assert C# parity or to
release an accounting schema.
