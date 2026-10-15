> **Historical supporting record.** Current decisions, language roadmap, readiness,
> and execution order belong to the [active master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
> Old alternatives, next-step directions, and authorization notes below are not current instructions.

# AnyInfer P1 evidence audit

**Execution status:** owned by [the foundation plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
Read that plan and [the accounting candidate](ANYINFER_OPERATION_ACCOUNTING.md) before resuming.
**Audited:** 2026-10-14, source HEAD `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Environment:** repository `.venv`, Python 3.13.15, installed `jsonschema` 4.26.0.
**Outcome:** evidence collection complete; subsequent P1.3 selected S1/F1/L1 in the
[decision walkthrough](ANYINFER_P1_3_CHOICES.md). Detailed specification gates remain
open; the foundation checklist owns current readiness status.

Only planning documents were updated. Existing tests and bounded in-memory observations
ran without writing new scripts or conformance fixtures. No production implementation,
provider snapshot, release, branch, or commit was changed. The pre-existing untracked
`AnyInfer/` directory is outside this audit.

This is an evidence record, not a normative specification. It separates the selected
restart/repair-budget and legacy-ledger behavior from proposed accounting additions
and possible policy changes. Current Python quirks are recorded without declaring
that every one must become a cross-language requirement.

## 1. Evidence legend and verification

Rule classes:

- **B:** current Python behavior, to preserve within its declared scope.
- **A:** new accounting instrumentation/contract; absent from current Python.
- **X:** deliberate first-profile exclusion; Python may support it.
- **C:** discrepancy or compatibility decision; must be resolved before normative claims.

Evidence strength:

- **T:** the named existing test was included in a passing module in R1/R2 below.
- **P:** directly observed in a bounded in-memory probe during this audit.
- **S:** static control-flow/type inspection; adjacent tests do not prove the specific case.
- **Outside run:** an existing test was read but was not part of R1/R2.

Source paths without a `src/anyinfer/` prefix in the tables are relative to that
package; `tests/` paths are relative to the repository. Named symbols and test selectors
are the durable anchors; any line references describe this HEAD only. A missing-test
claim means no direct case was found in the inspected modules, not a proof about every
possible test in the repository.

### Existing tests run

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
# R1: exit 0; 72 passed.
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_schema.py tests/test_schema_partial.py tests/test_routing.py tests/test_events_ordering.py

# R2: exit 0; 230 passed.
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_types.py tests/test_spend_ledger.py tests/test_pricing.py tests/test_observers.py tests/test_sync_client.py tests/test_manifest.py tests/test_errors_and_redaction.py tests/test_openai_compat.py
```

R1 collected 36 schema, 6 schema-partial, 21 routing, and 9 event-ordering cases.
Together the two runs passed **302 existing cases in 12 modules**. Neither run is
`workspace check`; no full repository-gate or new-accounting conformance pass is claimed.
The probes below used the repository interpreter, disabled bytecode generation, and
used local scripted adapters/HTTP mock transports only. They are not committed regression
tests and do not supply a portable conformance corpus.

## 2. Current Python rule inventory

### Requests, schema, repair, and routing

| ID / class | Current rule and evidence | Source / direct test | Future conformance observation |
|---|---|---|---|
| B01 | Text parts concatenate in order; convenience constructors retain roles. **T** | `src/anyinfer/types/messages.py`; `tests/test_types.py::test_message_text_concatenates_text_parts`, `test_convenience_constructors_set_roles`. | Capture normalized messages and adapter request, including multiple text parts and role order. |
| B02 | Explicit targets split at the first colon; target/model whitespace is stripped and provider normalization/aliases applied. **S**, canonical resolved rendering **T**. | `catalog/resolve.py`: `resolve_target`; `types/requests.py`: `Target` grammar; `tests/test_types.py::test_resolved_target_renders_canonically`. `tests/test_registry_and_catalog.py::test_model_ids_may_contain_colons`, `test_explicit_provider_and_model`, `test_provider_alias_is_normalized_during_resolution` are **outside run**. | Model text containing colons, actual whitespace handling, provider normalization, unknown provider/model, and excluded catalog aliases. Do not confuse route selection with concrete target resolution. |
| B03 | Unset sampling uses provider defaults; `with_messages` preserves other request fields. Target-specific unsupported controls can be dropped with `ParameterDropped`. Wildcard options merge with provider-specific options taking precedence. **T/S**. | `types/requests.py`: `Sampling`, `GenerationRequest.with_messages`; `_client/wire.py`: `build_wire_request`, `dropped_parameters`; `_run_attempt` emits drops; `tests/test_types.py::test_with_messages_preserves_every_other_field`, `test_no_provider_invents_a_sampling_default`. `tests/test_sampling_controls.py` is **outside run**. | Assert omitted versus supplied wire fields, correction sampling/options, drop reasons, and wildcard precedence. Profile exclusion and supported-field target degradation are distinct; see C11. |
| B04 | Schema coercion accepts a mapping or Python `model_json_schema()` object; validity is not established by coercion. **T/S** | `types/requests.py`: `SchemaSpec.coerce`; `tests/test_schema.py::test_coerce_accepts_a_plain_mapping`, `test_coerce_accepts_a_pydantic_style_model`. | Shared schema data is JSON; Python object coercion is a language-specific convenience. Separate invalid schema from invalid generated content. |
| B05 | Parse whole output first; on failure try the first balanced object/array, respecting strings/escapes. **T** | `schema/validate.py`: `extract_json`, `_first_balanced`; `tests/test_schema.py::test_extract_plain_json`, `test_extract_json_from_a_code_fence`, `test_extract_json_array`, `test_extract_ignores_braces_inside_strings`. | Whole scalar/object/array, prose/fences, malformed first candidate, escapes, and multiple candidates. |
| B06 | Schema dialect follows `jsonschema.validators.validator_for`; invalid schemas return error text; errors are relevance-sorted and capped at five. **T/P/S** | `schema/validate.py`: `validate`, `MAX_REPORTED_ERRORS`; `tests/test_schema.py::test_validation_reports_an_invalid_schema_rather_than_crashing`, `test_validation_reports_missing_fields`. | Explicit dialect/keyword inputs, invalid schema, error cap/order, and original-schema validation after projection. Installed default is an observation, not a released dialect choice. |
| B07 | Mechanism ladder is grammar, JSON Schema, JSON mode, then prompt; unknown capabilities select prompt. **T** | `schema/mechanism.py`: `choose_mechanism`; `tests/test_schema.py::test_mechanism_ladder`, `test_unknown_capabilities_fall_to_the_weakest_mechanism`. | Profile-supported mechanism/capability combinations and provenance; no claim of grammar support merely because a runtime is excluded. |
| B08 | Repair is opt-in, same resolved target, original messages plus latest invalid output/errors. **T/S/P** | `schema/repair.py`: `REPAIR_PROMPT`, `build_repair_messages`; `_client/generation.py`: `_run_attempt`; `tests/test_schema.py::test_repair_messages_extend_the_conversation`, `test_repair_loop_recovers_a_violation`. | Capture each correction request. Assert literal outer template and policy for validator-generated feedback. |
| B09 | Requested repair ceiling is clamped by descriptor; repair counter/budget reset for each outer routing attempt. **T** for ceiling; **P/S** for failed-correction restart. | `_client/generation.py`: `_repair_budget`, `_route_events`, `_run_attempt`; `tests/test_schema.py::test_provider_repair_ceiling_clamps_the_caller_budget`, `test_provider_repair_ceiling_is_reported_not_silent`; probe P3. | Four calls, two entered corrections, local repair event numbers `1,1`, winning result local repair count one. No request-wide budget. |
| B10 | Schema exhaustion raises `SchemaViolationError`, outside `ProviderError` routing/fallback. It may retain deterministic partial structured data. **T/S/P** | `_run_attempt` validation/exhaustion branch; `tests/test_schema.py::test_schema_violation_raises_without_a_repair_budget`, `test_repair_budget_is_bounded`; `tests/test_schema_partial.py`; probe P2. | Schema failure must not consume provider fallback. Distinguish response completion, validation failure, and operation failure. |
| B11 | Retry follows the default predicate or caller override; auth/context are declined by default, with a separate credential-refresh exception in the router. **T/S** | `routing/policy.py`: `Retry`, `never_retry_client_errors`; `_route_events` auth refresh; `tests/test_routing.py::test_default_retry_predicate_declines_deterministic_failures`, `test_non_retryable_error_does_not_retry`. | Exact predicate/backoff and error fields. Credential refresh and specialized context/content chains need explicit profile exclusion or inclusion; do not silently simplify full Python routing. |
| B12 | Ordered fallback, capped exponential/Retry-After waiting, and health suppression retain the routing trail. Health skips create legacy `AttemptRecord(skipped_unhealthy)`. **T** | `_route_events`; `routing/policy.py`: `backoff_delay`; `tests/test_routing.py::test_fallback_advances_to_the_next_target`, `test_health_gate_skips_a_recently_failed_target`, `test_backoff_is_exponential_and_capped`, `test_retry_after_header_is_honored`. | Record skipped targets but create no new accounting call; measure waits in operation elapsed time. |
| B13 | The post-content retry/fallback guard specifically tests `StreamProtocolError`; other retryable provider failures can restart after content. **S** | `_route_events` `StreamProtocolError` branch, around line 490. No focused guard-versus-transport regression found in inspected modules. | Inject both error classes before/after content; assert current route choice and separate attempt boundaries. |
| B14 | Timeout is per adapter iteration, including correction; default 120 seconds, byte cap 1,048,576 per response. Required iterator close occurs before validation. **T** for timeout; **S** for correction/cleanup distinctions. | `types/requests.py`: defaults; `_run_attempt` timeout and `aclosing_if_supported`; `tests/test_routing.py::test_attempt_timeout_is_a_typed_retryable_transport_error`; compatible adapter response-limit tests. | Deadline/byte-cap on each invocation, closure ordering, and failure during correction cleanup. No direct correction-byte-cap/cleanup-fault test found. |

### Usage, cost, telemetry, and lifecycle

| ID / class | Current rule and evidence | Source / direct test | Future conformance observation |
|---|---|---|---|
| B15 | `Usage.normalized` fills a missing total; `merge` overlays later known fields and cannot erase with `None`. It does not remember that a total was derived. **T/P** | `types/results.py`: `Usage`; `tests/test_types.py::test_usage_normalization_computes_a_missing_total`, `test_usage_merge_prefers_later_known_values`; probe P4. | Repeated cumulative reports versus deltas, missing/zero values, and derived component updates. |
| B16 | `Usage.sum` requires all parts known and returns unknown for empty input. `_usage.merge_usage` instead preserves known subtotals; neither is the new accounting contract. **S/P** | `types/results.py`: `Usage.sum`; `_usage.py`: `merge_usage`; probe P4. Strict search-unit behavior is asserted in `tests/test_embeddings_reranking.py` **outside run**. | Strict total versus partial subtotal, empty new operation versus empty legacy sum. Do not change helper semantics. |
| B17 | OpenAI-compatible usage parsing drops malformed integer types, accepts negative integers, and derives totals before core events. Buffered output can carry both `UsageUpdate` and `AdapterFinal`. **S/P** | `providers/http.py`: `read_int`; `providers/openai_compat.py`: `_parse_usage`, buffered/streaming generation; `providers/base.py`: `AdapterFinal`; probe P4. | Ensure repeated observations are overlays, not separate calls. Preserve per-field validity and report/derivation evidence before it is lost. |
| B18 | Terminal `AdapterFinal` is consumed before close, but terminal usage is merged only after close contexts exit. Corrections have fresh buffers; final result fields come from the winning buffer. **S/T/P** | `_run_attempt`; `routing/attempts.py`: `AttemptBuffer`; `tests/test_events_ordering.py::test_repair_restarts_the_attempt_clock_and_the_delta_sequence`; probe P3. | Capture terminal usage despite cleanup fault; maintain winning result usage/timing and expose earlier calls only through new accounting. |
| B19 | `with_cost` preserves an existing cost; otherwise pricing computes from usage/capabilities. Existing `cost_usd` has mixed reported/computed sources. Missing cache counts can still produce a number. **T/P/S** | `capabilities/pricing.py`: `with_cost`, `compute_cost`, `_input_cost`; `tests/test_pricing.py::test_generate_computes_cost_from_the_table`; `tests/test_deepseek_xai.py::test_xai_reported_cost_wins_over_computed_pricing` **outside run**; probe P5. | Reported charge and computed estimate separately; immutable tariff evidence; stricter new full-pricing coverage must not change old `cost_usd`. |
| B20 | Ledger records `RequestCompleted`, not correction/failed-call usage. Unknown cost increments an unknown-request counter; missing token counts contribute zero to legacy token buckets. **T/S** | `capabilities/ledger.py`: `SpendTotals.plus`, `SpendLedger.on_event`; `tests/test_spend_ledger.py::test_a_ledger_observes_a_real_client`, `test_an_unpriced_target_counts_as_unknown`, `test_a_genuine_zero_is_not_an_unknown`. | Legacy totals remain unchanged even when new call accounting sees more work. Do not infer complete token coverage from legacy buckets. |
| B21 | `SpendStore` persists aggregate buckets without operation identity, revision/conflict checks, or deduplication. Repeated legacy completion application can count twice. **S** | `capabilities/ledger.py`: `SpendLedger.record`, `SpendStore`; failure-event metadata/reservation removal is in `on_event`; entered-source finalization separately calls ledger `release`. | Do not route new finalized events into the old persistence format or retrofit dedup silently. Optional future store requires separate design. |
| B22 | Stream construction creates a core UUID4-hex correlation ID and, when enabled, a builder before lazy router execution. Start telemetry occurs on advancement. **S/P** | `_client/async_client.py`: `stream`, `_new_run`; `_routed_stream`, `_route_events`; probe P1. | Distinguish public request coercion/route selection, acceptance, execution start, and adapter entry. The existing generation ID is a candidate identity source, not caller-supplied metadata. |
| B23 | Unstarted close produces no telemetry/result and retains the registered builder. Started-source cleanup removes it. `.result` is captured only upon `StreamEnded`; manifests can be read earlier. **P/T** | `_client/stream.py`: `AsyncStream`; `_routed_stream` finally; probe P1; `tests/test_manifest.py::TestAssembly::test_abandoned_stream_leaves_no_builder_behind` advances once; `tests/test_sync_client.py::test_result_before_consumption_is_an_error`. | Zero-advance close and started partial close must be distinct. New terminal inspection and registry release are additions, not today's behavior. |
| B24 | `RequestFailed` covers selected routing failures, not all schema/config/preflight errors or cancellation. **P/S/T** | `_route_events` explicit emissions/catch; probe P2; `tests/test_observers.py::test_request_failed_event_on_exhaustion` covers routed exhaustion. | Enumerate each terminal source; use independent accounting finalization without reinterpreting legacy failure telemetry. |
| B25 | `AttemptCompleted` and `RequestCompleted` precede `builder.note_result` and `StreamEnded`. Ledger application can precede caller collection. Manifest complete is `result is not None`. **S/T** | `_run_attempt` lines 1029–1047; `manifest.py`: `ManifestBuilder.build`; `_client/stream.py`; `tests/test_observers.py::test_lifecycle_events_for_a_successful_request`, `tests/test_events_ordering.py::test_stream_ended_is_last_and_unique`. | Cross-channel ordering and observer actions around completion, builder state, new accounting commit, and result collection. Separate existing tests do not prove the combined ordering. |
| B26 | Iterator/stream close faults propagate; no explicit cancellation-over-cleanup-error rule exists. Client close disposes adapters without tracking all active operations. **S** | `providers/base.py`: `aclosing_if_supported`; `_client/stream.py`: `aclose`; `_client/async_client.py`: `aclose`; `_client/providers.py`: `AdapterPool.aclose`. `tests/test_sync_client.py::test_early_close_does_not_hang`, `test_close_is_idempotent` cover narrower behavior. | Cancellation during repair/backoff/cleanup, close racing active operations, primary/secondary errors, and client reuse/closure. |
| B27 | Observers run synchronously outside the subscription lock; ordinary `Exception` produces a warning, but `BaseException` is not caught. Payloads strip per subscriber. **S/T** | `events/observers.py`: `EventDispatcher.emit`; `tests/test_observers.py::test_a_failing_observer_does_not_break_the_others`, `test_payload_fields_are_stripped_by_default`. | New finalization delivery/reentry without changing the legacy bus. Warning-as-error policy can also propagate; this is a static consequence, not a tested race. |
| B28 | Capability provenance includes `override` as well as catalog/discovered/probed/default. Error snapshots are bounded/redacted but are not a complete serialization of every exception field. **S/T** | `types/capabilities.py`: `Provenance`; `types/results.py`: `ErrorInfo`; `errors.py`: `snapshot`; `tests/test_types.py::test_stronger_provenance_wins_an_overlay`, `tests/test_pricing.py::test_override_beats_discovered`, `tests/test_errors_and_redaction.py::test_snapshot_is_a_faithful_serializable_record`. | All current provenance tags and semantic error fields; do not make Python class names or loss of hint/retry-after the universal wire shape by accident. |

## 3. Candidate additions and explicit exclusions

| ID / class | Candidate rule / boundary | Evidence gap and planned observation |
|---|---|---|
| A01 | Accepted-operation handle, immutable snapshots, strictly ordered revisions, unique operation/call identity. | No existing `AccountingSnapshot` or `OperationFinalized`; T5 needs acceptance/start/close and stale/conflicting revision cases. Existing UUID4 generation IDs may be reusable within this scope, subject to the approved API. |
| A02 | Every entered original/correction/retry/fallback gets a new call record with causal/local repair identity. | P3 proves invocation sequence only; no per-call result record exists. T1 needs all four calls and independent usage/validation/outcome evidence. |
| A03 | Failure/cancellation retain a typed terminal accounting summary without a successful `StreamEnded`. | P1/P2 show why legacy stream result/manifest/telemetry cannot supply it. Test schema, provider, preflight, unknown-dispatch, and never-started cases independently. |
| A04 | Capture consumed terminal observations before cleanup, keeping existing final-result processing order. | Existing control flow can lose them. T1 cleanup-fault variant remains unexecuted; require a custom closable iterator with terminal usage then close fault. |
| A05 | Report-vs-derived source ranking, per-metric invalid-terminal markers, derivation recomputation, and complete/partial/unknown coverage. | Current event types lack the evidence needed; malformed values can be dropped before core sees them. T2/T3 require evidence-preserving adapter/core observations, with explicit behavior for old adapters lacking provenance. |
| A06 | Fixed generation metrics, observed subtotal, withheld complete total, coverage counts, zero-call aggregate zero. | These are new meanings; do not replace `Usage.sum`, `_usage.merge_usage`, or legacy ledger arithmetic. T4/T5 test unknown/zero/applicability and successful/failed/cancelled terminal totals. |
| A07 | Reported charge separated from computed price with reproducible tariff/method evidence. | Current `cost_usd` is mixed-source; absent provenance cannot be guessed. T4 tests known reported charge, unknown charge, partial tariff inputs, and fully priced estimates without altering legacy cost. |
| A08 | Authoritative inspectable terminal snapshot; consumer replaces snapshots. L1 defers new live finalized notifications. | T5 must verify native outcome/commit order, handle inspection, legacy callback interactions, and late wrapper diagnostics. New notification delivery/isolation/reentry guarantees belong to a later opt-in design; the old bus remains unchanged. |
| A09 | Optional future aggregate store deduplicates atomic identity-and-totals ingestion and rejects conflicts. | Legacy store has no such identity. T6 is future-consumer design, not mandatory first-profile persistence or automatic I/O. |
| X01 | Tools/reasoning controls/multimodal/citations/server tools/logprobs; embeddings/rerank/batching. | Python supports more. Request a excluded feature explicitly and observe profile-specific unsupported outcome before inference; preserve full Python API behavior. |
| X02 | Local acquisition/supervision/hardware and context/history/distillation/arenas. | These remain AnyInfer product features; their absence means partial port coverage. Already-running local compatible HTTP targets remain possible. |
| X03 | Broad providers, aliases/catalogs/discovery/probes, full pricing refresh and frontends/config loader. | Current registry/config/cassettes are raw material, not a ready portable specification. Programmatic C# setup must not create a competing config format. |
| X04 | Credential-refresh policy, pacing/cache placement/reservations/spending enforcement. | Their full Python behavior must not be simplified through a supposed equivalent generic route. Specialized routing chains and provider-option support remain a scope decision in C11, not a settled exclusion here. |
| X05 | Persistent aggregate store/outbox, sync C# facade, Java/full SDK packaging. | No silent expansion to satisfy candidate trace families. T6 persistence is not a first-profile prerequisite. |

## 4. Compatibility conflict register

The conservative disposition is to record and resolve these before changing runtime
behavior. A separate accounting view can intentionally use different aggregation
rules; that does not permit changing the legacy fields it observes.
The subsequent detailed schema draft qualifies C01: malformed recognized features
can reach different late branches. `validator_for()` is outside the caught
`check_schema()` `SchemaError` branch; malformed root `$schema` can escape as a native
assessment fault rather than repair feedback. Detailed tables classify this without
changing the original P1 test/probe claims.

| ID / priority | Conflict / failure scenario | Conservative disposition and gate |
|---|---|---|
| C01 / high | Portable strict JSON or early schema rejection differs from Python: scalar roots parse, duplicate keys are last-value-wins, `NaN`/overflow can parse as nonfinite floats; malformed schemas become validator errors after coercion, potentially after inference. | D1/S1 selected: bound schema admission while preserving Python response parsing. Unsupported schema features and admitted-but-invalid schemas are distinct; no Python preflight tightening is authorized. Exact dialect/keywords, numeric/Unicode/special-value representation, and invalid-schema timing remain gates. Broader schema support stays outside parity claims. |
| C02 / high | Byte-identical repair feedback is not guaranteed by another JSON Schema validator or another `jsonschema` version; order/text become part of the correction request. | D2/F1 selected: equivalent actually selected/sent violations with wording flexibility; preserve the outer template, original/latest-response construction, and cap. Prove a private selection-to-prompt evidence bridge and pin typed rule/path/parameters and selection/order. Independent revalidation or final success does not prove it. No identical-prompt claim. |
| C03 / high | Candidate cancellation precedence and `client_closed` outcomes do not match an existing coordinated lifecycle. Cleanup faults propagate; client close does not track/cancel all operations. | D3/L1 selected: observe native outcomes; cancellation intent alone cannot terminalize accounting or override routing. Cancellation dominance and coordinated client-close cancellation are deferred. Native error/race mapping still requires cases; a failed call can precede operation success. |
| C04 / high | Candidate terminal zero-call close differs from accepted lazy Python streams: no terminal event, incomplete manifest, builder remains registered on zero advancement. | D3/L1: confirmed successful zero-advance closure can finalize new accounting, with no claim of legacy telemetry/result completion. Faulted/rejected close must observe whether native flow actually ended. Handle ownership/races remain gates; releasing the retained Python builder is a separate change, and reproducing that private leak is not a C# requirement. |
| C05 / high | Strong observer-isolation/reentry guarantee exceeds the legacy dispatcher: `BaseException` and warning policy can escape inline; reentry has no terminal guard. | D3/L1: new live finalization delivery/isolation/reentry guarantees are deferred. Existing typed telemetry and dispatcher behavior remain unchanged. Snapshot visibility during legacy callbacks and escaping callback errors still need explicit state/order cases. |
| C06 / high | A legacy `RequestFailed` subscriber misses schema failure/cancellation; `RequestCompleted` precedes manifest completion and successful caller collection. Schema-failure manifest may retain an `ok` adapter attempt while remaining incomplete. | D3/L1: proposed accounting success commit follows legacy completion callbacks and builder result capture, before `StreamEnded`. Independent failure accounting does not backfill old telemetry or change ledger inputs, manifest completeness, or `.result`. Exact failure/postcommit ordering remains a gate. |
| C07 / high | Rich metric rules cannot be reconstructed from existing `UsageUpdate`/`AdapterFinal`: derived/reported origin and malformed-terminal presence may already be lost. | D5/D8: specify an evidence-preserving, payload-free observation contract or explicit degradation for older adapters. Do not label unclassified numbers reported or missing fields invalid. Changing old result normalization is not the solution. |
| C08 / medium | Candidate negative-value invalidation and derived recomputation differ from existing helpers: `-1` replaces 10, and updating output 4 to 5 can leave previously derived total 10. | D5/D8: implement any stricter rules only in the new accounting view. Preserve old helper and result behavior; T2/T3 must expose both views without treating an old helper fix as additive instrumentation. |
| C09 / medium | Candidate full-pricing coverage may withhold a number where current pricing fills `cost_usd`, including missing cache figures. Existing cost may already be provider-reported or computed. | D5/D8: retain old cost/ledger values; new coverage is independent, and tariff-required dimensions are explicit. Obtain source evidence before splitting cost; never infer its origin from presence alone. |
| C10 / medium | The original profile listed four provenance tags, while current source also supports application `override`. DESIGN examples omit newer fields; the `Target` grammar docstring says model text is verbatim, but `resolve_target` strips it. | Correct the draft's tags to include `override`; D5 still owns wire representation. Use current source for the detailed behavioral inventory, including model trimming, and record documentation discrepancies. No architecture reversal or documentation fix outside planning is implied. |
| C11 / medium | Initial profile scope does not yet pin specialized context/content chains or provider-option escape hatches. Python also distinguishes target-specific parameter degradation from a profile-excluded requested feature. | P2.1/D8: enumerate supported route/option fields and explicit exclusions before fixtures freeze. Preserve existing `ParameterDropped` behavior for supported controls; do not replace it with blanket pre-dispatch rejection. Do not label unsettled scope a selected exclusion. |

## 5. Observation probes and trace disposition

### P1 — Accepted stream closed without advancement

With a local `ScriptedProvider`, manifests enabled, and a recording observer:

```python
stream = client.stream("hi", target="scripted:m")
await stream.aclose()  # no preceding __anext__
```

Observed builder count remained `1 -> 1`; no telemetry was emitted; manifest
`complete` remained false; `.result` raised the existing consumption `RuntimeError`.
An existing abandoned-stream regression advances once and therefore does not cover
this case. This validates the current-state conflict in C04, not candidate finalization.

### P2 — Schema failure does not imply legacy failure telemetry

Local `ScriptedModel("m", text="definitely not json")`; request schema:

```json
{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}
```

Calling `stream.collect()` with repair absent raised `SchemaViolationError`.
Recorded telemetry was `['RequestStarted']`, with neither `RequestFailed` nor
`RequestCompleted`. Manifest remained incomplete and its adapter attempt was labelled
`ok`; `.result` was unavailable. Builder registry was released after the started
source failed (`builders_after=0`). New accounting must retain the terminal schema
error independently; changing the old attempt/manifest/telemetry semantics is not authorized.

### P3 — Failed correction restarts the original request and repair budget

Actual OpenAI-compatible adapter over an HTTP mock transport, target `openai-compat:m`,
prompt `who?`, object schema requiring `name` and `age`, repair budget one, route max
attempts two and zero backoff. Response sequence:

```text
1 original -> {"name":"Ada"} (invalid: missing age)
2 correction -> HTTP 500 "temporary"
3 original -> {"name":"Ada"} (invalid: missing age)
4 correction -> {"name":"Ada","age":36} (valid)
```

Observed four requests with message lengths `[2,4,2,4]`, identical original requests
at positions one/three, and identical corrections at positions two/four. Each resolved
model was `m`; prompt mechanism inserted the schema system message. Both correction
prompts used the latest invalid output and feedback `- <root>: 'age' is a required property`.
Legacy repair event numbers were `[1,1]`; one `RequestCompleted` was emitted. Winning
result reported `repair_attempts=1`, usage input 11/output 7/total 18, and routing
trail `retried, ok`.

This verifies the central restart/reset behavior dynamically. It does **not** execute
T1's stronger terminal-response-then-cleanup-fault variant, new call records, or a
cancellation race. No committed direct regression case was added.

### P4 — Parser and usage permissiveness / provenance loss

`extract_json("42")` returned integer 42; `{"a":1,"a":2}` returned `{"a":2}`;
`NaN` returned a float NaN; `1e999` returned float infinity. All extraction error
values were null. This does not assert that every schema accepts those values.
`validator_for({})` selected `Draft202012Validator` in this installed environment.

Actual `Usage`/integer-reader observations:

```text
Usage(input=6, output=4).normalized() -> total=10
that value.merge(Usage(output=5)) -> input=6, output=5, total=10
Usage(total=10).merge(Usage(total=-1)) -> total=-1
Usage.sum([]) -> all optional scalar fields unknown
read_int({"x":"4"}, "x") -> None
read_int({"x":-1}, "x") -> -1
```

Input/output abbreviations above name `input_tokens`/`output_tokens`. These are current
helper/parser observations, not approved new-accounting outcomes.

### P5 — Cost origin and missing cache counts

`Usage(input_tokens=100, output_tokens=50)` with cache fields absent, pricing input
2/output 10 per million, and trusted capability provenance produced `Decimal('0.00070')`.
`default` provenance left it unknown; catalog/discovered/probed/override allowed pricing.
A second probe set cache-read rate 0.5 and cache-write rate 3 per million with the same
missing cache counts; current `compute_cost` still returned `0.00070`.
Existing `cost_usd=9` was preserved by `with_cost`.

These demonstrate current pricing behavior. They do not establish that a new tariff
contract may call all missing cache inputs complete. The source-specific reported-cost
regression read outside R1/R2 is `test_xai_reported_cost_wins_over_computed_pricing`:
its provider tick charge survives as 1.25 rather than a calculated substitute.

### Six candidate trace families after P1

| Family | What P1 establishes | Still required before new conformance |
|---|---|---|
| T1 | P3 proves correction provider failure -> original restart -> reset budget/local event count; source proves cleanup before validation. | Cleanup-fault terminal usage capture, per-call outcomes/records, and cancellation mutations. |
| T2 | P4 proves negative integers can replace valid values; malformed integers can disappear at parsing. | Evidence-preserving invalid-terminal marker, replacement window, independent metric coverage, and numeric bounds. |
| T3 | P4 proves derived source is not retained and legacy total can become stale. | Report-vs-derived rank, component lineage/recomputation, discrepancy coverage, and same-rank ordering. |
| T4 | P5 proves mixed-origin cost and cache-missing legacy computation; strict/additive usage helpers differ. | Fixed metric applicability, aggregate coverage, retained tariff evidence, and separate charge/estimate totals. |
| T5 | P1 proves never-started-close conflict; source proves distinct telemetry/manifest/collection boundaries. | Atomic start/close/finalization, immutable revision replacement/conflict checks, reentry, and authoritative terminal handle. |
| T6 | Legacy store contains no operation-ID ingestion/dedup contract. | Optional future atomic store/conflict tests; no mandatory first-profile persistence or outbox. |

## 6. DESIGN/source comparison and test-kit limits

The product definition, typed generation primitive, async core, translate-only adapters,
original-schema enforcement, and opt-in repair agree with the selected direction.
The first profile's local/context exclusions limit its coverage; they do not revise
those product goals.

Relevant differences or omissions requiring explicit specification work:

- DESIGN's request/result/event snippets omit current fields; its route snippet has
  `on_fallback`, while current `Route` instead exposes TTL and specialized chains.
  Do not translate the illustrative dataclasses as the C# contract.
- Structured-output prose says repair stays within the same routing budget, but does
  not state that correction provider failure can re-enter outer routing and renew the
  repair counter. P3 supplies that missing detail without reversing the architecture.
- Routing prose **does** describe unhealthy-skip records. The omission is the specific
  post-content `StreamProtocolError` exception to general fallback behavior, not the
  existence of health-skip trail entries.
- Four-tag provenance examples and computed-cost comments are narrower than current
  source: application `override` exists, and some adapters report actual cost.
- The `Target` grammar docstring describes model remainder as verbatim, while actual
  resolution strips surrounding model whitespace. Future normalization cases must
  pin the implementation behavior rather than translating that docstring literally.
- No existing specification establishes a universal cancellation/cleanup winner,
  accepted-operation accounting lifecycle, or aggregate-price evidence model.

Current conformance uses Python-callable harness/setup and capability skips. Cassettes
match method/path and replay decoded bodies, so they cannot prove correction prompts,
usage evidence lineage, or transport-framing boundaries. Current `ScriptedProvider`
supports useful status/truncation/malformed JSON/timeout/refusal scenarios, but does
not supply a terminal-usage-plus-close-fault iterator or accounting revisions/coverage.
Keep the new corpus independent and assert requests as well as responses; do not
rewrite these facilities into a second router or count a skipped accounting case as
passing. Those are future P3 tasks, not changes performed by this audit.

## 7. Audit-time questions and subsequent P1.3 disposition

At the end of evidence collection, P1 distinguished supported behavior from additions
and policy changes but left the following choices open. This table records those
audit-time questions; current selections belong to the linked P1.3 walkthrough.

| Decision | Established by audit | Remaining choice before normative drafting |
|---|---|---|
| D1 | Python parser quirks, current validator selection, coercion/invalid-schema timing, and original-schema enforcement. | Python-equivalent domain versus explicitly narrower portable JSON/Schema profile; dialect/keywords/references/formats, Unicode/numeric limits, malformed input timing. |
| D2 | Literal repair template, original/latest-response conversation construction, five-error cap, and validator-dependent feedback. | Exact common error renderer for a bounded domain versus declared semantic feedback equivalence; stable order and actual prompt expectations. |
| D3 | Lazy execution, zero-advance close, missing legacy failure coverage, completion ordering, close propagation, observer limitations, and adapter disposal. | Accepted handle API/ownership, terminal linearization, new-surface exception policy, and explicit selection or deferral of lifecycle behavior changes C03–C06. |

The user subsequently selected S1/F1/L1. These directions resolve the shape of D1–D3:
bounded schemas with Python parsing compatibility, semantic equivalence of selected
repair guidance, and snapshot-first accounting of native outcomes. The conflict
register above incorporates those dispositions without converting unresolved detailed
rules into verified behavior.

The foundation checklist owns the resume point. Remaining planning work must pin
schema admission/parsing, actual feedback evidence, and the lifecycle/error matrix.
D4/D5/D8 also require numeric/wire rules and an evidence-preserving adapter/core
observation design before rich accounting can be frozen. Preserve current retry/repair,
legacy events/helpers, ledger/persistence, and manifest/result access. No runtime fix,
fixture, or C# work follows automatically from this report or the selections.

## 8. Cold review and document gate

An independent cold review sampled source/test anchors and compared all three planning
documents. Its one remaining finding was a wording ambiguity in checked P1.2: the word
"trace" could imply execution of cleanup/cancellation cases that were only inspected.
The checklist now says to inspect and record source/test evidence and gaps; its note
retains the exact distinction between executed probes and unexecuted candidate cases.

That audit-time review did not choose a JSON/Schema domain, repair renderer,
cancellation policy, or accounting observation API. P1.3's later user selections are
recorded separately; they do not retroactively strengthen the executed evidence.
Repository changes remain limited to planning documents; linked documents and qualified
test selectors are checked as part of the planning-document gate.
That gate corrected the B02 test-name citations and recorded actual model whitespace
trimming before finalizing this audit record.

A subsequent independent reconciliation review checked the user-selected S1/F1/L1
across all four planning documents and found no remaining substantive contradiction.
The accounting freeze condition was narrowed to mandatory first-profile portions of
T1–T5; T6 persistence remains deferred. Baseline JSON is explicitly test/contract data,
with no generated-runtime or code-reuse-percentage promise. Local link, fenced-block,
and whitespace checks passed. P1.G is complete in the foundation checklist; detailed
specification gates remain open. At that P1.3 reconciliation, no additional runtime
tests or probes were needed; the earlier 302-case result is unchanged evidence.

## 9. Subsequent P2.0 planning-table review

The [schema admission](ANYINFER_SCHEMA_ADMISSION_DRAFT.md),
[repair comparison](ANYINFER_REPAIR_FEEDBACK_DRAFT.md), and
[lifecycle/error matrix](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md) are detailed planning
proposals under selected S1/F1/L1, not normative assets. Further static reading used
the same source HEAD and installed `jsonschema` 4.26.0. No new fixture, persistent
probe script, runtime implementation, or test suite was written/run in this tranche.

| Cold-review finding | Disposition in the drafts |
|---|---|
| High: malformed root `$schema` can escape before the caught `SchemaError` branch. | Admission preserves actual late fault versus feedback behavior; no fabricated issue/correction. Explicit malformed-metadata and extraction-first cases are freeze gates. |
| Medium: “factory fault” could mean provider construction or the generate iterator factory. | Provider acquisition/construction before `generate(wire)` creates zero generation calls; crossing that generate expression creates one even if it immediately throws. Paired boundary cases are required. |
| Medium: generic/fatal/warning faults could be misread as routable provider errors. | Actual caught `ProviderError` scope, predicate, and budget control retry. Built-in timeout conversion and ordinary observer suppression are explicit; accounting cannot introduce retries. |

Narrow independent rereview found those three substantive findings resolved. Remaining
gates include native races/unknown cancellation cause, schema numeric/Unicode/ownership
boundaries, actual selected-feedback evidence, invalid-schema first-defect equivalence,
postcommit continuation, and D4/D5/D8 wire/observation/API choices.

### Direct bounded review probe — schema assessment only

The independent reviewer directly called `anyinfer.schema.validate.validate({}, schema)`
using the repository `.venv`. These are ephemeral assessment observations, not P1 test
counts, generation traces, passing conformance cases, or provider requests.

| Schema supplied | Direct observation |
|---|---|
| `{"$schema": []}` | `TypeError: unhashable type: 'list'`. |
| `{"$schema": {}}` | `TypeError: unhashable type: 'dict'`. |
| `{"$schema": 17}` | `AttributeError: 'int' object has no attribute 'decode'`. |
| `{"$schema": null}` | One caught feedback string: `the supplied JSON Schema is itself invalid: None is not of type 'string'`. |
| `{"type": 17}` | One caught invalid-schema feedback string; this review record does not assert its exact renderer text. |
| `{"required": 17}` | One caught invalid-schema feedback string; this review record does not assert its exact renderer text. |

Source explains the distinction: `schema/validate.py:validate` selects `validator_for`
outside its `check_schema` exception handler. Installed `validators.check_schema`
raises a `SchemaError` for its first iterated meta-schema error; it does not use
AnyInfer's instance-error relevance ordering. Generation/repair consequences remain
source-derived until an authorized end-to-end case runs. The earlier 302-test evidence
is unchanged; these observations are recorded separately rather than added to that count.

## 10. Subsequent P2.0C detailed choices

The user selected N1/U1/I1/C1 in the
[detailed choice walkthrough](ANYINFER_P2_DETAIL_CHOICES.md). That file owns the
selections and alternatives; the three drafts and accounting companion incorporate
them. This step added source reading and planning-document changes only: no new
runtime probe, test suite, fixture, or implementation. Earlier direct observations
and the 302-test P1 result keep their original scopes.

Cold review required four guardrails before the selections were reconciled:

| Guardrail | Recorded disposition |
|---|---|
| I1 cannot masquerade as full F1 invalid-schema parity. | Explicit exact/qualified comparison scope and independent detailed result; uncovered malformed shapes cannot pass detailed feedback. Missing evidence on a mandatory exact case cannot downgrade its scope. |
| Numeric representation identity is not schema assertion equality. | N1 preserves exact decoded observations while `enum`/`const`, type, and bounds retain the pinned validator's numeric behavior. No new NaN payload/sign or public native-result-type requirement. |
| Unicode value/JSON-decoder/transport stages differ. | U1 preserves actually decoded sequences; native rejection where Python decodes is a classified mismatch, not a manufactured string or an automatically equivalent failure. Schema/response/raw-text representation and transport evidence remain gates. |
| Unknown cancellation cause is reporting only. | C1 applies only after cancelled terminality is confirmed, with bounded attribution diagnostics. It cannot infer terminality from intent/_closed, change native retry/cleanup, or revise a committed snapshot. |

Source reading confirmed `_client/wire.py:_inject_schema_prompt` sorts schema keys
for its prompt text (`sort_keys=True`), independently of original schema insertion
order used by validation/error enumeration. The drafts now distinguish those orders.
No new Unicode decoder result, numeric limit, cancellation race, or invalid-schema
exact-domain membership was established by this walkthrough.

Independent final consistency review found no substantive contradiction after the
four selections and guardrails were reconciled. Local link/Markdown/scope checks
passed; the master owns completed P2.0C/P2.0CG and the next resume point. These
document gates do not verify native Unicode/numeric compatibility, actual-feedback
bridge implementation, or cancellation races and do not authorize normative assets.

## 11. Subsequent I1 closed-domain/reporting draft

This section records the original drafting tranche's evidence limits. The later
helper audit in section 12 supplies new direct observations without rewriting that
historical scope.

The [I1 domain/reporting proposal](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md) defines
the candidate root R/T families, strict integer-kind 17 values, allowed canonical-
dialect/order variants, outside-domain boundaries, and checkpoint/case reporting.
This adds no new direct observation or conformance pass. Source HEAD and the installed
`jsonschema` 4.26.0 reference remain unchanged; installed `jsonschema-specifications`
is 2025.9.1. No runtime probe or test suite ran.

Static reading included installed `jsonschema_specifications/schemas/draft202012/`
`vocabularies/validation` and `vocabularies/core`, `validators.check_schema`,
`_keywords.anyOf/type`, and error-field/context preservation. The source suggests
an array-type primary defect for `required: 17` and an aggregate `anyOf` for `type: 17`.
These are candidate identities, not
directly captured selected-error evidence. Existing helper probes establish caught
feedback only; absent/explicit dialect, insertion-order variants, actual paths,
aggregate context, and generation/correction binding remain verification gates.

Further static reading found that `validators.validator_for` can emit a
`DeprecationWarning` for `$schema: null` before `check_schema`. Repository
`pyproject.toml` configures pytest warnings as errors. The earlier helper's caught
null-metadata feedback remains evidence for that helper environment; it does not
prove the same branch under a fatal-warning policy. The proposed exact domain was
therefore narrowed to R/T. Null metadata is an outside-domain, warning-sensitive
boundary: qualified caught feedback under a declared nonfatal-warning environment,
or a source-predicted assessment fault under warnings-as-errors, each requiring its
own predeclared environment and branch evidence. No warning suppression, Python
policy change, new SDK warning option, or universal C# warning category is proposed.
Pinning validator/specification resources, selection/format-checker defaults, and
warning policy plus portable fault classification remains a freeze gate.

Scope/result metadata is now owned by an enclosing planned-checkpoint report. Actual
feedback records describe only feedback that occurred; they are not fabricated for
planned no-feedback controls. Comparison limits never move Python validation earlier
or alter error classes, correction construction, outer retry, repair counters, legacy
events/ledger inputs, manifest completeness, or stream result availability.

Cold review required retaining captured wrong/unexpected feedback records even when
the enclosing checkpoint fails; a null reference cannot discard available selected-
feedback evidence. The report and matrix now distinguish that from actual no-feedback
faults and incomplete identity. Planned versus observed membership/scope remains
fixed, missing exact evidence blocks rather than downgrades, and no-feedback or
qualified checkpoints cannot inflate exact-invalid-schema coverage totals.

## 12. Subsequent I1 helper evidence audit

The [I1 selected-error/warning audit](ANYINFER_I1_EVIDENCE_AUDIT.md) owns the new
direct evidence. It captured actual caught R/T error objects across all six proposed
dialect/order shapes and two declared policies, confirming R's array-type leaf and
T's aggregate `anyOf` with ordered children. It also observed null metadata's
nonfatal-feedback and fatal-warning branches. Earlier sections retain their historical
scope; their source-only or string-only evidence was not retroactively stronger.

This tranche executed bounded helper/selector observations only, with evidence/counts
separated from the prior 302-test result. No native generation history, existing test
suite, fixture, production observation seam, Python policy change, or C# implementation
was run/written. The I1 draft is reconciled to the new helper evidence while retaining
domain/environment approval, portable mapping, bridge, and end-to-end gates.

## 13. Subsequent I1 native history audit

The [native history audit](ANYINFER_I1_NATIVE_HISTORY_AUDIT.md) owns 2026-10-15's
buffered native observations. It confirms zero/one-budget exhaustion for all six
exact shapes, latest-only corrections, correction-c2 provider failure followed by
original restart and fresh local budget, extraction-first feedback, and representative
null/iterator-cleanup branches. T0 directly binds selected/helper/build evidence to
entered-wire corrections. R0 has selected/prepared evidence with HTTP invocation
correspondence; direct same-correction schema-feedback wire binding and all-variant
native object/order capture remain open.

Its fully recorded groups contain 27 native invocations, 52 HTTP generation requests,
and four normalized-only adapter entries. Two additional exploratory null invocations
have incomplete request/event evidence; no complete total is claimed across all work.
The audit separates these units and repeated observations from mandatory case counts.
The earlier helper/302-test evidence keeps its original scope.

Legacy schema/selector-warning/generic-cleanup failure paths observed no terminal
RequestCompleted/RequestFailed events. That gap is preserved. No accounting records,
spend persistence, private bridge implementation, fixture, or Python policy change
was introduced. The full profile, streaming/race, environment/semantic mapping, and
approved bridge gates remain separate from these bounded native observations.

## 14. Subsequent private observation/failure choices

The user selected O1/M1/W1 in the
[private conformance walkthrough](ANYINFER_PRIVATE_CONFORMANCE_CHOICES.md): private
opt-in capture, stage plus small semantic failure families, and an explicitly open
portable null-metadata expectation. That owner records alternatives and proposed
minimum capture groups; no hook interface or portable code registry is frozen.

This step adds source reading and planning text only, not new native observations,
fixtures, or implementation. Existing audit counts and evidence levels are unchanged.
Classification remains separate from terminality, native retry/repair, comparison
verdict, legacy events/ledger, and the unresolved portable reference condition.
