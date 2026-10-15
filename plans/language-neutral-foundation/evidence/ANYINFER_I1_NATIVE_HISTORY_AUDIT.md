> **Historical supporting record.** Current decisions, language roadmap, readiness,
> and execution order belong to the [active master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
> Old alternatives, next-step directions, and authorization notes below are not current instructions.

# AnyInfer — I1 native generation history audit

**Status:** bounded native observations; no frozen contract or profile pass.
**Observed:** 2026-10-15. **HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Scope:** findings under `plans/` only. No implementation, fixture, saved probe,
dependency change, live provider, network socket, branch, or commit.
**Resume/status:** [foundation checklist](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Rule owner:** [I1 domain/reporting draft](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md).
**Earlier object evidence:** [I1 helper audit](ANYINFER_I1_EVIDENCE_AUDIT.md).
**Related:** [repair-feedback record](ANYINFER_REPAIR_FEEDBACK_DRAFT.md),
[lifecycle matrix](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md),
[P1 evidence history](ANYINFER_P1_EVIDENCE_AUDIT.md).

The real async generation core was exercised through buffered `AsyncClient.generate`.
The observed histories confirm late schema handling, bounded correction/exhaustion,
original-request restart and fresh local repair budget, extraction-first behavior,
and cleanup before schema assessment. They also preserve a legacy observability gap:
the terminal schema, selector-warning, and generic cleanup failures in event-recorded
runs produced no `RequestCompleted` or `RequestFailed` telemetry event.

## 1. Method, environment, and evidence boundaries

The checkout and repository `.venv` remained unchanged. Observations used stdin
scripts with `.venv/Scripts/python.exe -B`, Python 3.13.15, `jsonschema` 4.26.0, and
`jsonschema-specifications` 2025.9.1; source resolved to this checkout's
`src/anyinfer/schema/validate.py`. The earlier helper audit records resource hashes;
the same three raw-byte hashes were rechecked and matched on 2026-10-15. This run
did not approve an immutable environment/profile revision.

| Setup | What it can establish | Limit |
|---|---|---|
| Existing `ScriptedProvider` / `ScriptedModel` | Native core over the compatible adapter and in-process HTTP transport; recorded request JSON, exceptions, legacy events. | Success text is static; declared failures are consumed before success. It cannot express a failure specifically during correction or changing successful output. |
| Existing `FakeOpenAIServer` with an ordered `FakeResponse` list | Different bodies/statuses at specific HTTP requests, including 503 on correction c2; actual request JSON from the compatible adapter. | HTTP JSON is transport evidence, not an internal `WireRequest` object or network dispatch. |
| Ephemeral normalized adapter/iterator | Real core calling a registered adapter; actual entered `WireRequest` objects and deterministic per-invocation `aclose` behavior. | Adapter supplies only text/final events or a cleanup fault. No HTTP projection/framing coverage. No retry/repair/validation loop is implemented in it. |
| Temporary tracing in selected runs | Actual extraction return, schema-helper input, caught error fields, helper feedback, and repair-builder inputs/returns. | Observation only; timing can be perturbed. Not an approved reusable bridge and not complete field capture for every variant. Hooks are restored in `finally`. |

All runs used synthetic content and in-process transports/iterators. No credentials
or provider endpoints were contacted. Clients/adapters were closed. No existing test
suite was run, and these counts do not amend P1's earlier 302-test result.

Early discovery captured HTTP JSON rather than internal objects. A supplemental
trace attempt captured no helper frames and is not evidence of missing assessment.
The later independent trace used the actual imported function code objects and did
capture native helper/build frames. One adapter trace looked up the wrong argument
name (`request` instead of `req`); its empty wire capture is not zero work. Those
operations retain their actual HTTP/helper evidence. Later runs directly captured
actual entered wire objects at the appropriate boundary.

## 2. Executed observations and units

`R0/R1/R2/T0/T1/T2` have the exact meanings in the helper audit: integer-kind 17;
absent or canonical Draft 2020-12 dialect; both explicit root insertion orders.
The table includes discovery/repeated confirmations separately, rather than counting
each as another mandatory conformance case.

| Group | Native generation invocations | HTTP generation requests | Normalized-only adapter entries | Purpose / terminal outcome |
|---|---:|---:|---:|---|
| All six exact shapes, explicit `Repair(0)` and `Repair(1)` | 12 | 18 | 0 | One or two requests respectively; all exhaust as `SchemaViolationError`. |
| R0/T0 distinct-output corrections, `Repair(2)` | 2 | 6 | 0 | Original plus two corrections; latest-only conversation and final raw text. |
| R0/T0 correction-c2 503, route attempts 2, `Repair(1)` | 2 | 8 | 0 | Original/correction/original/correction; terminal schema failure. |
| R0/T0 extraction-first, `Repair(1)` | 2 | 4 | 0 | Extraction repair, then malformed-schema exhaustion. |
| Initial R/T discovery, `Repair(1)` | 2 | 4 | 0 | Repeated schema exhaustion, shown separately from the six-shape matrix. |
| Initial R with 503 on original c1, `Repair(1)` | 1 | 3 | 0 | Provider retry before repair; does not prove correction-failure restart. |
| Independent traced R0 correction-failure restart | 1 | 4 | 0 | Actual schema errors/builds and original restart; repair numbers 1, 1. |
| Independent explicit null warning-policy pair | 2 | 3 | 0 | Nonfatal: two requests and schema exhaustion. Error: one request and escaping warning. |
| Independent traced T0 `Repair(2)` with normal iterator close | 1 | 0 | 3 | Actual schema/build/wire binding and cleanup completion before each schema-helper entry. |
| R0 iterator-close fault after final event | 1 | 0 | 1 | `RuntimeError`; no observed schema-helper entry, preparation, repair, or retry. |
| Independent traced R0 extraction-first | 1 | 2 | 0 | One extraction failure, one later schema-helper entry; two entered internal wire objects. |

The fully recorded groups total **27 native invocations, 52 HTTP generation requests,
and four additional normalized-only adapter entries**. These are distinct observed
units, not published accounting records, case-pass counts, or provider charges.
Buffered HTTP request counts do not prove the timing of an adapter iterator-factory
boundary; the normalized-only entries were recorded directly at `generate(req)`.
"Fully recorded" here describes invocation/request counts, not complete field or
event coverage in every run. The later sections identify which runs retained actual
objects, helper frames, messages, or telemetry; no missing field becomes an exact pass.

Two additional exploratory null invocations retained terminal exceptions but not
reliable request/event counts. Their report originally claimed one request/no repair
under nonfatal policy despite intended `Repair(1)`, without retained server/event
evidence. That unsupported count was withdrawn. They remain setup-limited observations
and are superseded for detailed history by the independent pair. Thus 52 plus four
is the total for the fully recorded groups, **not a complete work total for all 29
native invocations**. No missing count is silently treated as zero.

## 3. Late assessment and exhaustion for the exact shapes

For every exact shape, explicit zero budget produced one HTTP request and terminal
`SchemaViolationError`. Budget one produced two requests and one
`RepairAttempted(attempt_number=1)`, followed by terminal `SchemaViolationError`.
These were explicit `Repair(max_attempts=0/1)` configurations; omitted repair/`None`
was not a separate observed control in this tranche.

| Family | Native terminal `errors` feedback |
|---|---|
| R | `the supplied JSON Schema is itself invalid: 17 is not of type 'array'` |
| T | `the supplied JSON Schema is itself invalid: 17 is not valid under any of the given schemas` |

This is not early schema rejection: a controlled provider response is obtained
before the terminal schema failure. Neither a valid parsed response nor a correction
can repair the original malformed schema. Python nevertheless uses the configured
repair allowance; it does not stop early because schema repair is impossible.

The six-shape matrix preserved serialized schema text in the injected instruction
and native error feedback. Its actual assessment objects/input snapshots were not
captured for every variant. Do not infer original assessment key order from the
injected schema text, whose serializer sorts keys. The helper audit supplies all-six
object identities; direct native input/object binding below covers the R0/T0
representatives rather than silently closing every variant's bridge gate.

## 4. Distinct corrections and actual feedback binding

R0 and T0 were each run with successful response bodies `{"first":1}`,
`{"latest":2}`, and `{"final":3}`, budget two, and sampling
`temperature=.37`, `top_p=.81`, `seed=9`. Each made three HTTP requests and exhausted
with final `raw_text` exactly `{"final":3}`.

The first correction appended `{"first":1}` and the repair suffix. The second used
the original conversation plus only `{"latest":2}` and the suffix; the earlier
assistant/correction pair was absent. Serialized original schema text and sampling
were preserved. Request JSON supports these assertions without being relabelled an
internal wire object.

An independent normalized-only T0 run captured actual inputs and objects:

- Three schema-helper entries used original `{"type":17}`, against the three
  different parsed response values. Each actual caught error had `validator=anyOf`,
  input path `["type"]`, and ordered context keywords `enum`, `type`.
- Each helper returned the single T feedback string. Two real repair-builder calls
  received original `system("audit sys")`, `user("audit user")` plus the latest raw
  response and that error tuple. Actual returned messages were retained.
- Entered internal wire messages matched those prepared conversations plus the
  core's schema injection. The second correction contained only `{"latest":2}`.
- Model `m`, temperature `.37`, top-p `.81`, seed `9`, timeout `7` seconds, and response
  cap `2048` were supplied. Direct assertions retained model, temperature, timeout,
  and byte cap at all three entries; HTTP runs separately checked serialized sampling.
- Local repair numbers were `1, 2`; terminal raw text was the final body. No completed
  result was constructed or returned.

Actual correction user text equals the native template with its selected error list:

```text
Your previous response did not match the required JSON schema. Errors:
- the supplied JSON Schema is itself invalid: 17 is not valid under any of the given schemas
Respond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.
```

The R0 restart confirmation also traced actual caught `type=array` errors, original
schema inputs, returned feedback, and actual repair-builder inputs/returns. It has
corresponding HTTP correction-body evidence, but no direct same-correction internal
wire capture. Thus T0 has the direct selected-feedback -> prepared -> entered-wire
chain here; R0 has selected/prepared evidence plus HTTP invocation correspondence.
The later R0 extraction wires carry extraction guidance and cannot substitute for
missing direct R0 schema-feedback wire binding. That boundary remains open.
These observations do not implement the proposed comparison record, portable
semantic extractor, noninterfering bridge, or complete every required variant/stage.

## 5. Correction failure restarts the original request and local budget

R0/T0 each used `Retry(max_attempts=2)` with zero backoff, `Repair(1)`, actual original
system/user messages, and nondefault temperature. The HTTP response sequence was:

| Call | Native request role | Scripted response | Observed consequence |
|---|---|---|---|
| c1 | Original | `{"step":1}` | Caught malformed-schema feedback; repair event number 1. |
| c2 | First correction | HTTP 503, Retry-After 0 | One `RetryScheduled(attempt_number=1)`; outer attempt retries. |
| c3 | Original again | `{"step":3}` | Original conversation restored; caught feedback and fresh local repair event number 1. |
| c4 | Correction based on c3 | `{"step":4}` | Malformed schema still fails; local budget exhausted as `SchemaViolationError`. |

Every run had four HTTP requests, two repairs numbered **1, 1**, one retry, and no
successful result. c1/c3 messages matched; c4 echoed c3's body, not c1/c2's history.
The target/model and supplied temperature stayed fixed.

Independent R0 tracing additionally observed schema-helper entries only for c1/c3/c4,
all with original `{"required":17}` and the corresponding parsed values. The actual
repair-builder original messages were reset for both corrections. There was no
schema assessment on c2's provider error. Final `raw_text` was `{"step":4}`.
This directly confirms the earlier source-derived four-call trace. It does not impose
a request-wide repair ceiling or count the two repair events as one local number 2.

## 6. Extraction first, null policies, and cleanup boundaries

### Extraction may consume the only correction before schema assessment

R0/T0 each received non-JSON text then a parsed object under budget one. The first
repair cited `response was not JSON and contained no JSON object or array`; the
parsed correction then exhausted as the malformed-schema `SchemaViolationError`.

Independent R0 tracing retained the sequence:
`extract_json -> extraction error -> build repair -> entered correction -> parsed
object -> one schema-helper entry -> caught SchemaError -> exhausted`.
There was one repair and no second message build. Its terminal errors described R's
schema defect, while the actually invoked correction guidance described extraction.
A final exception's errors therefore cannot stand in for what was sent earlier.
Actual internal wire objects were captured for these two invocations of the adapter.

### Null metadata preserves the declared warning policy through the native core

Independent observations explicitly passed `Repair(1)` and retained HTTP requests,
events, helper frames, and warning records:

| Policy | Native observed history |
|---|---|
| `always` for DeprecationWarning | Two responses; two recorded warnings; two actual caught `type=string` schema errors at input path `["$schema"]`; one repair number 1; terminal `SchemaViolationError` with the second raw body. |
| `error` for DeprecationWarning | One response; the warning escapes from `validate` before a feedback tuple; no repair-builder call/repair/retry; terminal `DeprecationWarning`. |

The latter trace's Python `return` event has value null during exception unwinding;
it is not a successful helper return or an empty-error tuple. Null metadata remains
outside exact I1 membership in both policies. No warning suppression, early Python
schema rejection, new provider error, or retry policy is introduced.

### Adapter iterator cleanup precedes schema assessment

The normalized adapter returned a custom async iterator: text, one `AdapterFinal`,
then normal iteration exhaustion. Its separate `aclose` completed or raised. It did
not throw the cleanup fault from the iteration body or from client shutdown.

For each of the three normal T0 invocations, the observed order was:

```text
generate -> final yielded -> iteration exhausted -> iterator aclose completed -> schema-helper entry
```

For R0 with `aclose` raising `RuntimeError("audit cleanup fault")`, one adapter
invocation yielded text and a final event, then exhausted iteration. The close fault
escaped; tracing observed zero schema-helper entries/preparations, and there were
zero repair/retry events. The captured final event did not force validation or a
successful result past cleanup. Later client-level adapter close was a separate
operation and completed. Source places the whole `_validate` call after this context
exit; the direct trace here proves the schema-helper/preparation boundary, not all
possible cleanup/cancellation races.

## 7. Compatibility findings and remaining scope

| Finding | Disposition |
|---|---|
| Request restart/local repair reset are confirmed. | Keep existing four-call behavior and local event numbers. No request-wide budget. |
| Extraction feedback and terminal schema errors can differ. | Retain per-assessment/prepared/invoked evidence. Eventual exception prose cannot reconstruct sent guidance. |
| Iterator final observation is weaker than completed native success. | Preserve cleanup exceptions and prevent fabricated validation/repair/result evidence. |
| Legacy terminal telemetry is incomplete for these failure paths. | Event-recorded schema failures, promoted warning, and generic cleanup fault emitted neither RequestCompleted nor RequestFailed. Absence is not success or proof that no work happened. Keep legacy semantics; additive accounting remains separately unimplemented. |
| HTTP/body equality is weaker than original schema/ordered-object evidence. | Keep the all-variant snapshot/bridge gate. Never infer original key order from sorted prompt JSON. |
| Temporary tracing is not the future evidence API. | Actual native representative evidence is stronger than helper-only evidence, but bridge isolation, full fields, IDs, and all variants/stages remain unapproved. |
| No new contradiction requires changing Python policy. | The audited histories support the narrow proposed direction. Missing native error codes/events are reporting/design gates, not authority to add prevalidation, suppress warnings, retry schema failures, or rewrite the ledger. |

Still unverified here: public streaming consumption, partial-content failures,
cancellation/cleanup races, provider ceilings, every allowed mechanism/projection,
every exact variant's native object/order snapshot, direct same-correction R0 schema-
feedback wire binding, prepared-but-never-invoked
correction, a separate omitted-repair control, mutable caller inputs, full transport
framing, provider breadth, authoritative aggregate snapshots, persistence, and C#
parity. Some have earlier source/test evidence; this tranche does not strengthen
them by association. No spend ledger or persistence was attached for a compatibility
test, so unchanged code is not reported as a new ledger conformance pass.

Next conservative work is to settle the bounded private observation/report mapping
and remaining profile/domain/environment decisions, then authorize a specific next
tranche. No normative assets, fixture files, bridge implementation, or port follows
automatically from this audit.

Source anchors: `_client/generation.py:_run_attempt/_validate/_route_events`,
`schema/validate.py:extract_json/validate`, `schema/repair.py:build_repair_messages`,
`providers/base.py:aclosing_if_supported/WireRequest`,
`providers/openai_compat.py:generate`, `testing/scripted.py`, and `testing/fakes.py`.

## 8. Cold review and document gate

Independent review found an overclaim in the first draft's representative binding
wording. The record and linked drafts now reserve direct selected/prepared/entered-
wire binding for T0; R0 retains selected/prepared plus HTTP correspondence and an
open same-correction wire gap. Extraction wire evidence does not fill that gap.
Narrow rereview found no unresolved substantive finding.

Review checked arithmetic, incomplete exploratory counts, request/field boundaries,
extraction versus terminal feedback, iterator-close scope, missing legacy terminal
events, and remaining gates. Local links/Markdown/whitespace and table arithmetic
passed across eleven planning documents. Environment/source and the three existing
resource hashes were rechecked; HEAD is unchanged. Only Markdown under `plans/` was
written, with no implementation, fixture, saved probe, external artifact, or commit.
The foundation checklist owns completion and the next authorized resume point.
