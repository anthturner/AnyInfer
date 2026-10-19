# Request-policy observation projection contract

Resume from the first unchecked box. This is the schema-only prerequisite of POL.5 in
ANYINFER_CSHARP_SDK_POLICIES.md. Owner: 2ff. Read this and the Python-proof leaf before
editing. Preserve concurrent changes, re-read owned files before minimal edits, never
change Git state, and run no native/shared build. No observer/checker implementation is
granted until root freezes P.2.

## Ownership and settled decisions

- Own tests/fixtures/request-policy-v1/observations.schema.json, new schema-only
  tests/test_request_policy_observation_schema.py, the proposed artifact
  csharp-sdk/sdk-five-policy-projection-contract-notes/index.md, and O.1-O.2 here. Root
  owns O.3. O.2R is also owned here. 1e separately owns input schema/corpus/procedures and their artifact; coordinate
  procedure/checkpoint names by message, without editing the other's files.
- Write an executable closed observation/envelope grammar plus exact field semantics.
  Top case status is always ok; nested public operations are ok/error/cancelled. Harness,
  unsupported-kind/type/input and accidental cancellation failures exit the observer.
  Required operations/evidence are nonempty; matching empty or unexpected errors cannot
  qualify. Unknown keys are rejected except explicitly declared arbitrary JSON data.
- Keep terminal caught Error metadata distinct from attempt ErrorInfo. Attempt errors
  expose only runtime_type/provider/phase/retryable/http_status. Do not synthesize missing
  retry-after or spend amounts. Operation holds the actual ordered attempt trail once.
- Use a finite explicit Python/C# runtime-name mapping, including SpendLimitError to
  SpendLimitException, ContextLengthError to ContextLengthException, AllTargetsFailedError
  to AllTargetsFailedException, and each actually used named provider error. Generic
  ProviderError to ProviderException is a literal pair, never subclass-wide acceptance.
- Direct spend refusals have actual nullable amount fields and no provider attempt trail.
  Successful configured results require non-null target/usage. Preserve actual monetary
  Decimal str / EDecimal.ToString values, integers, booleans, nulls and ordered collections.
  No rescaling, alternative accounting or profile-wide value normalizer.
- Project only confirmed public manifest fields. At minimum preserve presence and request
  correlation; any additional field needs source evidence in both runtimes. Include actual
  winner result/event/ledger/manifest cost relations without recalculating charges.
- Required intermediate ledger snapshots have procedure-defined checkpoint names and
  actual Reserved/totals values. Final zero alone cannot prove replacement/retention/release.
  Record actual estimator calls where repair/retry causality requires them.
- Random IDs, time readings and cache process hashes remain absent. Derive explicit
  correlation/order/presence relations from captured public facts. Specify exactly which
  causal barriers must have executed for an observation to qualify; no constant verdict or
  arbitrary true witness. Gate/body cleanup facts come from actual harness resources.
- Per-kind fact blocks name exact wire/tool/warning/cache/governor/config fields. Preserve
  literal ordered malformed/non-object tool warnings. Cache captures public adapter wire
  marks and typed public events; no invented OpenAI body field. Config proves consumers.
- Shared provenance uses the accepted helper mechanics: strict raw bytes, exact unique
  case/kind set, full revision/dirty/digest handshake and fresh evidence. The new profile
  adds its closed body/input rules; accounting's local semantics stay unchanged.
- Specify fail-closed synthetic controls: empty corpus/observations, unknown/missing/extra
  fields/IDs/kinds, stale provenance, bool-number/null-zero/order differences, unmapped
  runtime types, matched harness errors, missing intermediate witnesses, and fixture echo.
  Body-gate teardown releases first, cancels/observes pending work, closes streams/clients,
  uses finite hang guards and preserves primary failure over cleanup failure.

## Checklist

- [x] **O.1** Reconcile actual public result/error/manifest/ledger/event fields and write
  the complete proposed output schema/semantics. Coordinate the input procedure names
  with 1e; escalate a public API mismatch with source before inventing a field. Gate:
  JSON schema parses, all record/enum/nullability/ordering/witness rules are explicit,
  and every projection field has a named public source or actual resource capture point.
- [x] **O.2** Run json.tool and permitted schema-only validation, record any deviations,
  tick these owned boxes after re-reading and report SAVED/HELD. No checker/observer/native
  source, input corpus, workspace or product edits; no pytest/native build grant here.
- [x] **O.2R** Resolve the combined cold review using the settled correction decisions in
  sdk-five-policy-contract-decisions. Replace label bags with closed typed public/resource
  captures, actual outcomes/tool values/privacy, runtime-local names, and exact checker
  qualification tables linked to input procedures. Gate: strict JSON/meta-schema parsing,
  meaningful local-invariant mutation controls, targeted Ruff and only
  tests/test_request_policy_observation_schema.py with a unique cache. No observer/checker
  implementation or native process; report coherent SAVED/HELD for root O.3.
- [x] **O.3** Root reconciles the input and output schemas, native feasibility and cold
  critique before accepting Python-proof P.2. Only root may freeze the contract and grant
  independent implementations.
- [x] **O.3R** Correct RequestFailed telemetry to accept five-field terminal ErrorInfo
  snapshots for all five existing runtime-local names, including SpendLimit and
  AllTargetsFailed. Keep attempt/RetryScheduled/FallbackTriggered error names at the three
  provider/context types and exclude amounts/retry-after/detail from ErrorInfo. Owner 2ff.
  Gate: schema-positive local RequestFailed names for both runtimes and foreign/unknown/
  extra-field negatives, preserved attempt restrictions, strict schema parsing/meta-schema,
  targeted Ruff and approved schema/corpus/checker/helper/accounting pytest with unique
  cache. Root records the replacement output hash after coherent SAVED/HELD validation.
- [x] **O.3S** Separate closed manifest_usage from result Usage: eight confirmed public
  facet fields (input/output/total/cache-read/cache-write/reasoning/cost-string/search),
  no invented server_tool_uses. Keep actual result/event server-tool uses unchanged.
  AttemptCompleted outcome is ok and emits no synthetic attempt ordinal; completion
  correlation derives from actual preceding AttemptStarted facts for the same operation.
  Gate: schema/meta-schema and focused positive/extra-field/outcome/common-value mismatch
  controls plus approved pure test family. Owner 2ff; root records the replacement hash.

> NOTE: Root accepted narrow O.3S after independently passing all 87 approved pure tests
> and checking the closed eight-field manifest facet, nine-field result/event Usage and
> actual AttemptCompleted shape. The replacement output-schema SHA-256 is
> 542d98f6d0e21761ae338b5e4c00877d2202b95abbe5c15e00cfb16140ef69b3.
> Corpus/input hashes are unchanged. Verifier V.3S cold review and observer execution
> remain separate; this schema gate does not accept their capture origins or comparison.

> NOTE: Root accepted narrow O.3R after the coherent source handoff, all 77 approved
> pure tests and direct positive validation of all ten local RequestFailed names.
> The output-schema raw SHA-256 is now
> 23ca87757e906fa9e57041374de734abae89d20631b785eed856a31ade41eac5.
> Input/corpus hashes are unchanged. This lifts only the terminal-telemetry schema blocker;
> corrected checker V.3R still awaits independent cold review and actual runtime evidence.

> NOTE: The first proposal correctly identified terminal-versus-attempt error metadata
> and nullable successful native fields. Root resolved those boundaries above. The initial
> input draft lacks executable scripts and several reservation witnesses; both schemas
> remain proposed while the disjoint P.1R/O.1-O.2 revisions proceed.
> NOTE: O.2 used JSON parsing, Draft 2020-12 meta-schema validation, and one in-memory
> representative envelope only. No observer, corpus, native process, pytest, or shared
> checker execution was authorized or performed.
> NOTE: Initial root O.3 shape checks on the held schema reject a valid public empty
> tool-call name, but accept non-object tool arguments and string cache marks. These
> conflict with Models.ToolCall/JsonObject and WireRequest.CacheMarks integer values.
> The output-only cold review is active; O.3/P.2 remain open for one consolidated
> correction batch rather than implementing observers against this draft.
> NOTE: Root settled the neutral procedure name fallback_handoff for both known-known
> replacement and known-to-unknown retention. Literal pricing and actual checkpoint values
> distinguish them; after_fallback_handoff stays unchanged. Both authors hold the pending
> rename for the consolidated cold-review correction. Root independently passes all ten
> pure-input controls, but this does not prove the contexts/charge witnesses semantically;
> the combined review includes both held schemas and the revised 29-case corpus.
> NOTE: O.2R replaced label/count bags with a typed public/resource capture grammar and
> a procedure-keyed qualification table. Strict duplicate-key JSON parsing, Draft 2020-12
> meta-schema validation, Ruff, and six schema-local mutation controls passed using
> `.tmp-tests/request-policy-observation-schema-o2r-cache`; no observer, checker, native,
> shared, or corpus execution occurred.

> NOTE: Root accepted O.3/P.2 on 2026-10-19 after the combined cold rereview found no
> remaining P1. Corrected narrative context count nine/total 29 and all literal terminal
> cleanup checkpoint spellings; schemas/corpus were unchanged. Root independently passed
> all 23 corpus/projection controls. sdk-five-policy-profile-freeze records exact hashes.
> This closes only the contract prerequisite; actual observer origins, qualification,
> false-pass behavior and resource teardown still need independent source/run reviews.
