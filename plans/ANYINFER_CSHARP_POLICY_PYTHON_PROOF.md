# Request-policy input contract and Python observer

Resume from the first unchecked box. Parent: POL.5 in
`ANYINFER_CSHARP_SDK_POLICIES.md`. Owner: 1e. You are not alone; preserve all other edits,
re-read files before minimal changes, and never change Git state. Use traycer-implement.

Own only `tests/fixtures/request-policy-v1/{inputs.json,schema.json}`, new pure-input
`tests/test_request_policy_corpus.py`, future
`tests/test_request_policy_parity.py`, the draft artifact
`csharp-sdk/sdk-five-request-policy-profile-contract/index.md`, and P.1/P.3/P.4 below.
Root owns P.2/P.5 and the parent checklist. P.1R is also owned here. Draft decisions stay
marked open until P.2. The observation schema and its proposed artifact have a separate
owner under ANYINFER_CSHARP_POLICY_PROJECTION.md; do not edit those files.

## Settled scope

- Input envelope: profile `request-policy-v1` plus a cases array. Every case has nonempty
  unique `id`, closed `kind` and input-only setup/actions/scripts; no expected values,
  verdicts, result flags or output templates. Define precise per-kind input fields in the
  draft before either runtime consumes them.
- Closed kinds: admission, context_route, tool_stream, cache, governor, config_policy.
  Use up to 32 cases across all six families, with at least two cases per family and
  concrete coverage witnesses rather than a count-based acceptance claim. Keep the repeated observer/manifest
  FF/TF/FT/TT privacy matrix in existing event proof rather than spending four new cases.
  Raw-tool default versus explicit argument capture remains in scope.
- An experiment returns `status:ok` and actual facts under `value`. Its operations have
  actual ok/error/cancelled outcomes; typed refusal/provider errors are nested structured
  facts, including actual runtime type names. Harness/unsupported-kind failures exit
  nonzero instead of being counted as matching error observations.
- Error projection excludes diagnostic messages/details/hints. Use closed runtime-type
  mappings in the checker, actual provider/phase/retryable/http_status/retry_after fields
  and nullable spend amounts. Cancellation records actual requested/cancelled relations;
  runtime OCE/CancelledError identity remains outside shared comparison.
- Preserve actual usage/ledger/manifest money strings, integer/null/bool semantics, tool
  calls/ordered warnings and typed cache marks. Do not rescale values to force matches.
  Tool warnings are shared ordered literals, verified against both held source paths.
- Request IDs, process hashes and clock readings compare declared causal relations, not
  fabricated constants. No universal normalizer. Only real public clients, descriptors,
  recording adapters/handlers, events, ledgers and manifests produce facts.
- Nonempty specialized chains filtered to visited targets exhaust; only an actually empty
  configured chain preserves ordinary fallback. Bare targets do not inherit special chains.
- Public native rich-media admission is unfinished, so shared unpriced-media dispatch is
  excluded; existing pure budgeting tests own that guard. Unknown/default/equality/opt-out
  context cases remain shared. No new production hook, internal clock, reflection or friend
  access is permitted. Compare governor queue/header/body/cleanup causality, no delay values.
- Include known retry/fallback reservation replacement, repair no-recheck, cancellation/
  early-close release, and known-context-refusal to unknown/allow retention until terminal
  cleanup. Public SpendLedger.reserved/Reserved are available; no private state access.
- Cache uses publicly registered custom descriptors plus actual WireRequest marks for
  explicit placement; generic OpenAI keeps no declared mechanism/no invented wire field.
  Include Off, explicit capability refusal or implicit degradation, and prefix same/change
  relations through actual diagnostics. Native timer fault/opaque ownership/range/fairness
  mechanics remain unit/accounting exclusions.
- Freeze recursive closed input records in schema.json; arbitrary provider JSON bodies,
  schemas and tool argument/parameter data are explicit literal-data positions. Unknown
  harness keys, actions, types, mixed target/route selectors, empty case sets and unmatched
  instance/descriptor references fail. No dispatch branch may depend on a case ID.
- HTTP scripts contain literal status/headers and JSON body or raw UTF-8/SSE chunks with
  explicit content type/framing; opaque completion strings are not expanded into responses.
  Recording-adapter event scripts are a separately named input variant. Define finite gate
  ownership, readiness/release/cancellation and script-consumption semantics per procedure.
- Use actual shared config keys (api_key, not credential). Synthetic bare literals require
  LiteralResolver; env references use an isolated fixture environment restored in finally.
  No literal:// resolver is assumed. Config cases exercise public consumers only, including
  real limits queueing and configured Auto cache versus explicit caller Off; pure parser
  matrices remain existing ConfigTests. Descriptor ID, adapter ID and instance alias must
  be connected by the actual public registry/settings APIs.
- Fixed estimator inputs are permitted through the public estimator interface. Use them
  with priced tight ceilings and recorded estimator/ledger checkpoints so equality,
  reservation replacement and repair no-recheck are causal. Include the four planning
  tokens per message and schema/tool estimation in stimuli; do not implement a calculator.
- Explicit policy on an implicit descriptor emits its degradation ParameterDropped then
  CachePlanned. A changed implicit prefix first emits ProviderDiagnostic; the observation
  schema records actual order and no process hash bytes. Generic OpenAI remains undeclared.

## Checklist

- [x] **P.1** Encode a draft precise case/input/output contract in the named artifact and
  20-25 literal input-only cases. Record unresolved shape choices for root, without
  implementing observers yet. Gate: `.venv/Scripts/python.exe -m json.tool
  tests/fixtures/request-policy-v1/inputs.json` parses; report unique IDs/kinds and no
  expected-output fields after static inspection.
- [x] **P.1R** Resolve the cold P.1 findings in the input artifact/corpus, add the closed
  schema and pure validation controls, and coordinate exact procedure/checkpoint names
  with the projection owner. Mandatory causal coverage includes tight known retry and
  known fallback replacement, priced repair no-recheck, concurrent total refusal followed
  by cancellation/recovery, early stream close, and held known-context-to-unknown retention
  through terminal cleanup. Correct known-pricing zero-limit and equality fixtures; add
  actual empty/non-object tool deltas, default versus explicit winning-argument capture,
  positive/empty/filtered context chains and bare-target isolation. Gate: json.tool,
  schema validation of every case, mutation tests for closed nested records and references,
  targeted Ruff and tests/test_request_policy_corpus.py with a unique cache directory.
  Report the case-to-witness table and hold; no SDK observer/native/checker execution.
- [x] **P.1S** Resolve the combined cold review and root decisions in
  sdk-five-policy-contract-decisions, including exclusive unions/strict schema keys,
  fallback_handoff, exact ledger versus resource checkpoints, causal fixed context floors
  and literal successful/winning usage. Add meaningful typed ToolCall/ToolResult feedback
  stimuli and negative controls. Gate: strict JSON/schema validation, targeted Ruff and
  tests/test_request_policy_corpus.py with a unique cache; report SAVED/HELD and no observer.
- [x] **P.1T** Apply the controlled input-only model-isolation correction for the held
  known-to-unknown context route: keep alpha's priced `model`, give beta
  `unpriced-model`, and use that literal beta target in both route selectors. Add a pure
  corpus regression for the same-descriptor/different-model boundary and update the
  observer's frozen digest only after the input is held. Gate: corpus and owned observer
  tests; no schema, product, checker, or native change.
- [x] **P.2** Root reviews/pressure-tests and freezes the exact schema with native/checker
  owners before any consumer implementation. This checkbox is root-only.
- [x] **P.3** After explicit root grant, implement independent public Python observation
  through the frozen inputs with raw-byte digest/execution-time source provenance and
  finally-safe bounded barriers. Gate: targeted Python observer tests and actual
  `--observe INPUT OUTPUT` execution; no expected-results table.
- [x] **P.4** After implementation, run targeted Ruff check/format/check and approved
  pytest/observer execution, tick after re-reading, and report SAVED/HELD actual coverage
  and exclusions. No native builds or verifier acceptance claim.
- [x] **P.4R** Close sdk-five-policy-python-observer-review findings: actual operation/
  request-ID and AttemptStarted→AttemptCompleted correlation; causal checkpoints without
  terminal backfill; real three-operation queued refusal/cancellation procedures; public
  secret registration/redaction; gate-first bounded primary-preserving cleanup with real
  adapter-close callbacks; strict frozen input and source identity captured before dispatch.
  Project actual manifest usage fields separately from result Usage. Gate: meaningful
  regression controls for these origins plus all 29 standalone observations/schema,
  targeted Ruff and owned pytest with a unique cache. No other observer/checker/input/
  product edits. Root retains cold rereview and P.5 acceptance.
- [x] **P.4S** Close the remaining P.4R governor/cache/early-close review findings. Only
  the declared queue gate uses three operations; ordinary body/error gates use two actual
  public calls. Apply literal recording descriptor metadata/features/provenance and actual
  configured instance identity, retain Auto-refusal versus request-Off semantics, and make
  every early-stream close bounded with primary-failure precedence. Owner 1e. Gate: actual
  public producer regressions for those paths, Ruff, owned pytest and fresh 29-record
  standalone/schema validation; no product/input/schema/native/checker edits.
- [x] **P.4T** Capture public evidence at the correct boundary: pending admission
  checkpoints arm from telemetry but snapshot only at actual handler/recording entry;
  failures retain an actual `AllTargetsFailedError` trail and derive terminal state from
  captured telemetry. Start ordinary governor/config operation 1 while operation 0's body
  remains held, while preserving queue-only operation 2 cancellation/recovery. Gate: owned
  Ruff and corpus/observer tests; no native/checker/product edits.
- [x] **P.4U** Restore the pre-invocation `before_dispatch` baseline, add an actual
  queue-operation readiness witness before cancellation, and consume every `tool_stream`
  case through the public stream API. Gate: Ruff, owned observer tests, and a fresh
  29-record standalone/schema validation; no input/schema/product/native/checker edits.
- [x] **P.4V** Preserve actual body lifetime after public cancellation: the observer-private
  held-body seam acknowledges real cancellation, waits its existing release gate, then
  rethrows unchanged. Order early-stream and concurrent cancellation/recovery around that
  boundary and prove release-before-close-before-recovery. Gate: Ruff, owned observer tests,
  and fresh 29-record standalone/schema validation; no fixture/schema/product changes.
- [x] **P.4W** Preserve literal `max_output_tokens` only when the frozen request supplies
  it by passing a public `Sampling` control. Prove every sending context case retains literal
  zero as OpenAI-compatible `max_tokens`, while trusted preflight refusal remains unsent.
  Gate: owned Ruff, observer tests, and fresh standalone/schema/provenance validation; no
  fixture/schema/product/native/checker edits.
- [x] **P.4X** Project actual admitted ToolCallDelta and first/last-token timing events
  through one shared observer helper for both ordinary public streams and the manual
  early-stream close consumer. Prove early-stream `first_token` capture remains present
  before cancellation. Gate: owned Ruff, observer tests, and fresh standalone/schema/
  provenance validation; no fixture/schema/product/native/checker edits.
- [x] **P.5** Root compares independently executed native/Python evidence, validates the
  strict checker and all preserved profiles, then closes parent POL.5.

> NOTE: Root accepts P.5 after final P.4X cold closure and eleven producer controls/Ruff,
> final native thirteen-control/cold closure, 112 pure verifier controls and clean combined
> checker review. A fresh default stamped build independently executes both observers and
> passes all 29 shared cases (41 operations each), retaining raw facts and named finite
> runtime differences at
> .tmp-tests/request-policy/root-stamped-v3af-2a02d81f54a8416183a8e3f587aa83c2/run-41x8uvlc/report.json.
> Frozen corpus/schema hashes are unchanged; accounting remains 42 shared plus two observed
> native boundaries and FrozenV0 102/102 DEVELOPMENT/UNRELEASED. Dirty-source profile closure
> does not claim POL.7 full-workspace or clean-revision acceptance.

> NOTE: Root accepted P.2 on 2026-10-19 after combined cold closure and 23 independently
> passing contract tests. The freeze record is sdk-five-policy-profile-freeze; input and
> output schemas/corpus stay held. The next explicit root grant is P.3/P.4 only, with
> actual public Python execution and disjoint source ownership. Final comparison is P.5.
> NOTE: P.1 draft saved with 24 literal input-only cases across the six closed kinds and
> a companion artifact that records the proposed input/value projection. The named JSON and
> static-ID/kind/no-expected-field gate passed; P.2 remains root-only and must freeze the
> checker/type-family shape before either consumer starts.
> NOTE: Root accepted the cold critique's P1 findings on 2026-10-19. P.1's JSON/static
> gate validated syntax and input-only direction, not executability or causal coverage.
> The original 20-25 case cap is widened to 32 so required lifetime transitions need not
> be hidden in one oversized procedure. P.2 stays unchecked until input/output schemas,
> public registration seams, teardown and false-pass rules have coherent cold closure.
> NOTE: P.1R saved a recursively closed input schema, 28 balanced literal cases, a pure
> corpus mutation/reference suite, and the revised contract artifact. The named json.tool,
> schema-validation, Ruff, and isolated corpus-test gates pass. Procedure/checkpoint names
> align with the projection-owner draft; P.2 remains root-only and no observer/checker was
> implemented or executed.
> NOTE: P.1S hardened the input-only contract with strict duplicate-key parsing, exclusive
> HTTP/recording/event and message-part unions, exact ledger checkpoint sequences separated
> from resource readiness, fixed-estimator context stimuli, explicit successful usages, and
> 29 literal cases. The named JSON/meta-schema/corpus-validation, Ruff, and isolated pure
> corpus-test gates passed. P.2 remains root-only; no observer, checker, native, or SDK
> runtime was implemented or executed in this slice.

> NOTE: Root independently ran the first held Python source: owned pytest passed and
> .tmp-tests/request-policy/root-python/run-bd02b231b4fa476584fe548dec7711e9/observations.json
> contains 29 closed-schema records with matching current revision/dirty/corpus provenance.
> Cold review nevertheless found fabricated/lost causal evidence and unsafe privacy/cleanup
> paths, so this is structural execution evidence only; P.3/P.4/P.5 stay unchecked.
> P.4R is the current correction. Root retained Terra and raised this bounded task's
> reasoning to high after the initial source failed capture-origin review.

> NOTE: P.3/P.4/P.4R saved an independent public Python observer on 2026-10-19. Its
> operation/request-ID mapping is captured at `RequestStarted`; completed attempts require
> a preceding public attempt start; declared ledger checkpoints are captured at their named
> public barriers or fail. The three-operation cancellation paths now retain the public
> governed transport instead of bypassing it with a raw handler. Registered secrets are
> redacted recursively in every captured payload-bearing shape; default and explicit
> manifest payload capture use distinct public clients. Gate-first cleanup releases bodies,
> cancels and bounded-joins work, then closes clients while preserving a primary failure.
> Ruff check/format, owned pytest (five tests, unique cache), a fresh 29-case `--observe`,
> and held-schema validation passed. This is SAVED/HELD observer evidence only; root retains
> cold review, native comparison, checker acceptance, and P.5.

> NOTE: P.4S saved on 2026-10-19. Queue-gated governor cases retain their three public
> operations (held, unsent cancellation, recovery); ordinary body/error gates use only two
> public calls. Recording descriptors now receive frozen cache metadata and literal feature
> provenance through public provider settings, preserving explicit marks, refusal, implicit
> degradation ordering, and Auto-refusal versus request-Off silence. Early-stream cleanup is
> gate-first, bounded, and retains the primary failure over a blocked close. Ruff,
> eight owned tests with a unique cache, and a fresh 29-record observe/schema/provenance
> validation against output-schema SHA256 542d98f6d0e21761ae338b5e4c00877d2202b95abbe5c15e00cfb16140ef69b3
> passed. The observer remains held for root cold review and P.5; no native/checker
> comparison is claimed here.

> NOTE: P.1T/P.4T saved on 2026-10-19. The known-to-unknown fixture now uses beta's
> literal `unpriced-model` to prevent same-model pricing bleed while retaining the public
> descriptor boundary; its raw input SHA256 is
> 92e0fc9f6e128db05719446a91b891e9ee9cacc989d97f392496a8f08e649316. Public admission
> snapshots now occur only at actual HTTP/recording entry after telemetry arms the named
> checkpoint. Ordinary body/error/config gates create a second public operation before the
> first body releases and reject a premature second send; only the literal queue gate keeps
> a third recovery operation. The public seam remains model-keyed rather than offering a
> general per-instance pricing override, which is an explicit root-level scope limit rather
> than a provenance claim. Ruff and the 26 owned corpus/observer tests passed. Root retains
> output validation, cold review, cross-runtime comparison, and P.5.

> NOTE: P.4U saved on 2026-10-19. `before_dispatch` is now captured immediately before
> the first public SDK call, while telemetry only arms later admission checkpoints for
> actual adapter entry. Queue op1 records `pending_observed` directly after public
> `RequestStarted` and before cancellation; no private-semaphore state is claimed. All tool
> cases—including recording fragments and default/explicit capture modes—use public stream
> consumption so actual deltas are observed. Ruff and eight owned observer tests passed;
> a fresh 29-record output validates against schema SHA256
> 542d98f6d0e21761ae338b5e4c00877d2202b95abbe5c15e00cfb16140ef69b3 with matching revised
> corpus provenance. Root retains cold review and P.5.

> NOTE: P.4V saved on 2026-10-19. `_BodyGate` now observes a real `CancelledError` from
> the public body read, holds it behind the existing literal release event, then rethrows
> the original cancellation. Early-stream and concurrent-held generation wait for that
> private barrier before release, so the recorded public body close and recovery occur only
> after release. Queue op1 remains an unsent cancellation without a body gate. Ruff and nine
> owned observer tests passed; a fresh 29-record output validates against the held schema.
> This is observer evidence only, not qualification or cross-runtime acceptance.

> NOTE: P.4W saved on 2026-10-19. The observer maps a present literal
> `max_output_tokens` to public `Sampling(max_output_tokens=...)`, preserving an explicit
> zero without changing absent semantics. The trusted preflight refusal still has no HTTP
> capture; each of the four sending context cases records OpenAI-compatible `max_tokens: 0`.
> Ruff, ten owned observer tests, and a fresh 29-record standalone/schema/provenance
> validation passed. This remains held observer evidence only, not qualification or
> cross-runtime acceptance.

> NOTE: P.4X saved on 2026-10-19. Ordinary and manual early-close public stream consumers
> now share the same admitted ToolCallDelta and first/last-token timing projection. The
> early-close loop projects public events before recognizing its literal first text delta,
> so cancellation retains an actual `first_token` capture without adding synthetic events.
> Ruff, eleven owned observer tests, and fresh 29-record standalone/schema/provenance
> validation passed. This remains held observer evidence only, not qualification or
> cross-runtime acceptance.
