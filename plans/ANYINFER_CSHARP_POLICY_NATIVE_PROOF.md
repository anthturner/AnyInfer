# Native public request-policy observer

Resume from the first unchecked box. This is the native observer part of POL.5 in
ANYINFER_CSHARP_SDK_POLICIES.md. Owner: cab. Read DESIGN.md, the whole parent plan, the
frozen input/output schemas and their contract artifacts before implementation. This
checklist records the intended handoff; **no implementation is granted before root P.2**.

## Ownership and boundaries

- Own only the new `src/csharp/AnyInfer.RequestPolicy/` project directory and N.1-N.3
  below. Root owns N.4, solution/workspace registration, shared plans, all native builds
  and Git. You are not alone; preserve other edits and re-read before minimal changes.
- After P.2, the authority is `tests/fixtures/request-policy-v1/{inputs.json,schema.json,
  observations.schema.json}` plus the settled policy-contract-decisions and final
  input/projection contracts. Do not edit those contracts, Python code, product sources,
  existing tests, package versions, released assets or another author's files.
- Implement an independent observer, not a second policy engine or a port of the Python
  observer. Use public AsyncClient/Client, configured descriptors, handlers, adapters,
  SpendLedger, estimator, telemetry, Generation and RunManifest. No reflection, friend
  access, internal clock/hook, alternate calculator, or expected-output table.
- Branch only on declared input kind/procedure/transport/action. A case ID identifies
  evidence and never chooses behavior. HTTP bodies and recording events remain literal
  stimuli. Parse and reject unsupported/unknown inputs instead of inventing defaults.
- The executable accepts exactly INPUT OUTPUT. Read raw input bytes once, compute their
  lowercase SHA-256, then parse them strictly (including duplicate keys and finite JSON).
  Produce the closed request-policy-v1 envelope with runtime csharp. Obtain full lowercase
  40-hex source revision only from the SDK assembly's AnyInferSourceRevision metadata;
  obtain source_dirty only from compiled RequestPolicySourceDirty entry metadata. Missing
  or malformed metadata fails the process. No runtime Git/source fallback.
- The executable project references only AnyInfer; use the existing net8.0/warnings as
  errors conventions. RequestPolicySourceDirty defaults to true when absent and is emitted
  as assembly metadata. Root passes SourceRevisionId and the dirty property at build time.
- Capture actual typed public values under the frozen schema. Use canonical native money
  strings, Int64 usage/cache counts, exact nullable values, raw tool fragments and ordered
  warnings. Do not fabricate Usage when absent; complete successful fixtures supply it.
  Apply the public SDK redactor to payload-bearing projections and omit credentials.
- Record request-ID equality from captured public facts without emitting random IDs.
  Provider events without request identity remain unassociated. Resource records arise
  at actual owned handler/body/close/cancel boundaries. No private queue readiness,
  RateLimitWaited count/duration, arbitrary completion flag or elapsed-time success test.
- Every owned gate releases in finally before cancellation/join/stream/client disposal.
  Bound pending joins as hang guards; retain primary failures over cleanup failures.
  An unsupported or accidental harness error exits nonzero, never a matching observation.

## Checklist

- [x] **N.1** After explicit P.2 grant, add the executable csproj, strict two-path input
  reader, compiled provenance validation and envelope writer. Gate: statically trace all
  source/digest metadata to the actual input bytes and compiled assemblies; report coherent
  project surfaces for root registration without running native processes.
- [x] **N.2** Implement all frozen procedures through public clients and literal offline
  HTTP/recording stimuli. Cover each declared script exactly once where required; create
  the actual public descriptor/instance/configuration and fixed-estimator inputs. Gate:
  report a case-to-public-entry/capture map for every input case, with no ID dispatch,
  expected answers, alternate router or policy arithmetic.
- [x] **N.3** Complete typed event/wire/result/manifest/ledger/checkpoint/resource projection
  and failure-safe teardown. Re-read, tick owned boxes, NOTE deviations, report SAVED/HELD
  paths and honest exclusions. Gate: source inspection against the frozen schema and
  explicit cancellation/cleanup ownership; no build/test/Git process grant.
- [x] **N.3R** Close the native observer cold-review unknown-kind/procedure and unbounded
  join findings, preserving primary failures and releasing gates before bounded cleanup.
  Reject unsupported input before dispatch, retain the accepted public-only/raw-byte/
  compiled-metadata seams and direct manifest-facet projection, and preserve JSON payload
  shape/redaction. Gate: static source/case/resource trace, coherent SAVED/HELD and honest
  NOTE; no author build/test/process/Git. Root N.4 reruns stamped compile and CLI gates.
- [x] **N.3S** Close the remaining observer cancellation/stream-cleanup findings and
  complete the declared concurrent/gated procedures. Match cancellation only to its
  declared observer token, retain primary work faults through every bounded cleanup,
  drive early streams through actual content before second-read readiness, and create
  the distinct refusal/queued/recovery invocations required by the frozen procedure.
  Owner cab; only observer source and this leaf may change. Gate: explicit source/resource
  trace and SAVED/HELD report; root retains compilation, execution and cold rereview.
- [x] **N.3T** Close the five native protocol/capture findings: capture request/operation
  associations at event delivery, apply literal capability features/provenance, retain the
  actual recording descriptor identity, execute both default/explicit payload modes through
  public clients, and consume configured Auto before the second request's Off override.
  Missing cache capability is a real refusal, never inferred from descriptor mechanism.
  Owner cab; observer directory plus this leaf only. Gate: full literal-input/public-source
  case trace and SAVED/HELD, then root stamped compile, execution and cold review.
- [x] **N.3U** Extract the observer-only early-stream raw-read cancellation predicate and
  cover its causal token/barrier boundaries through internals-visible focused tests. The
  predicate accepts only a declared caller token or the actual requested fixture-read token
  after the actual fixture barrier; successful, unrelated, absent-barrier, and unrequested
  read outcomes remain failures. Gate: source/test trace and SAVED/HELD; root retains test
  reference, compilation, execution, cold review, and guarded CLI ownership.
- [x] **N.3V** Compose declared default capability facts through public descriptor defaults,
  catalog/static facts through public descriptor model rows, and true overrides through the
  client override seam without retagging provenance. Record the actual public heuristic when
  no literal estimator is declared. Gate: source/test trace and SAVED/HELD; root retains
  targeted test, guarded CLI, cold review, and acceptance ownership.
- [x] **N.3W** Drive declared gated config/governor operations concurrently through actual
  public RequestStarted and handler-entry barriers, while synchronizing observer capture state
  without claiming private queue readiness. Gate: source/test trace and SAVED/HELD; root retains
  all compile, runtime, guarded-CLI, and cold-review ownership.
- [x] **N.3X** Keep ordinary and default manifest clients on the public payload-disabled
  setting; create a distinct payload-enabled client only for the literal explicit capture mode.
  Gate: source/test trace and SAVED/HELD; root retains all compile and runtime ownership.
- [x] **N.3Y** Apply the public registered-secret redactor to captured HTTP header values,
  retaining names and noncredential values while preventing resolved fixture credentials from
  appearing in observations. Gate: source/test trace and SAVED/HELD; root retains all compile
  and runtime ownership.
- [x] **N.4** Root cold-reviews source and resources, registers the project, restores and
  builds with stamped metadata, executes actual native observation and validates closed
  output/provenance. Resolve compile/runtime findings without weakening inputs or facts.
  The final independent comparison and preservation gates remain parent POL.5/POL.7.

> NOTE: Root accepted P.2/O.3 on 2026-10-19; sdk-five-policy-profile-freeze identifies the
> held bytes. N.1-N.3 begin only on the corresponding explicit root message. Their grant
> is source-only, while root owns all native builds and N.4. SDK.5c remains unchecked.

> NOTE: N.1-N.3 source was held on 2026-10-19. The observer reads raw corpus bytes once,
> validates compiled/entry metadata without a Git fallback, projects only public client,
> descriptor, configuration, handler, adapter, stream, telemetry, manifest, ledger and
> resource facts, and releases declared body gates before all client/handler cleanup. N.4
> remains the required compilation, execution and schema-validation gate; none was run
> during this source-only authoring lease.

> NOTE: N.4's first stamped compile identified three observer projection mechanics on
> 2026-10-19. The narrow source correction records ordinary terminal errors as non-cancelled,
> derives AttemptCompleted numbering only from a matching preceding public AttemptStarted,
> and projects RunManifest.UsageFacet directly without inventing server-tool usage or
> reparsing its literal cost string. Root retains the rerun and all runtime/schema gates.

> NOTE: N.3R closed on 2026-10-19 by pinning the input digest before parsing or dispatch,
> rejecting every unsupported kind/procedure, and using observer-only bounded joins after
> gate release for pending stream/operation/client work. A timeout is a process-level
> harness failure, never an SDK fact. Cancellation is recorded only for observer-requested
> caller/close paths. Structured/tool/wire payloads now retain their JSON shape through the
> public redactor. Root still owns the required N.4 compile, runtime and schema rerun.

> NOTE: N.3R origin alignment on 2026-10-19 moved admission/replacement/fallback/repair
> snapshots off telemetry labels and onto actual public handler/adapter entry callbacks with
> operation plus consumed-script ordinal. Telemetry now only marks the next actual admission
> where core ordering requires it; missing declared checkpoints fail the observer. Isolated
> observer callback exceptions are retained and rethrown before output unless an earlier
> primary public failure already wins.

> NOTE: Root's N.3S stamped compile passes with zero warnings/errors. The first actual
> native CLI execution then exits before producing observations: deferred telemetry
> serialization tries to associate RequestStarted after the invocation context is cleared.
> The full native protocol/capture review is active on the held source; association must
> originate at actual event delivery. No output/runtime/independent comparison is accepted.
> Root scratch directory: .tmp-tests/request-policy/root-native/run-1a15489c6cf.

> NOTE: O.3S updated the held schema SHA on 2026-10-19. AttemptCompleted remains validated
> against its preceding same-request/same-target public start, but emits no synthetic attempt
> field; the checker derives that relation from the captured starts.

> NOTE: N.3S source trace on 2026-10-19 makes observer cancellation conditional on both the
> declared token being requested and the caught OCE carrying that exact token. Streaming now
> retains its first enumeration failure through bounded enumerator/stream cleanup. The declared
> procedures drive early-close through a public TextDelta, perform held/refused/cancelled/recovery
> and gated queue choreography as distinct public invocations, and associate body-resource facts
> with the operation that actually opened the body. Root retains compilation, execution and cold
> rereview; no author process ran.

> NOTE: N.3T source trace on 2026-10-19 binds request IDs and attempt starts at public
> telemetry delivery through async-flow operation context, so terminal serialization is
> side-effect free. Literal capability features/provenance, descriptor identity, dual
> default/explicit public manifest clients, and parsed-config Auto-before-request-Off are
> composed from frozen inputs without inferred cache capability. Root retains compilation,
> execution and cold review; no author process ran.

> NOTE: Root's N.3T compile found two scalar-json helper call mechanics on 2026-10-19.
> The observer now reads capture-mode and feature array items through a strict local scalar
> string helper; no capability, mode, or procedure semantics changed. Root retains the retry.

> NOTE: A real N.3T corpus retry exposed valid repeated AttemptStarted events for one public
> request/target. The causal lookup now retains the latest actual start while the ordered
> captured telemetry retains every event. No synthetic ordinal or event coalescing was added.

> NOTE: A subsequent N.3T corpus retry found that the observer had reused one raw handler
> across configured instances, which the public SDK correctly rejects. The observer now creates
> one ScriptQueue-backed handler for each public ProviderSettings attachment and validates each
> consumed script against that actual configured instance; recording adapters perform the same
> entry validation. Handler-close facts retain the handler's instance identity. Root retains the
> compile/runtime retry; no author process ran.

> NOTE: The next N.3T diagnostic confirmed that InvokeAsync classifies a matching declared
> OCE into a cancelled operation and then completes normally. Observer joins now distinguish
> that classified task outcome from the manual pending-read's raw OCE, which still requires
> exact-token matching. Operations project in unique invocation-index order only; raw telemetry
> and resources retain their observed order. Root retains the retry; no author process ran.

> NOTE: The early-stream fixture now signals an observer-private barrier only when its actual
> supplied ReadAsync token cancels, then holds that read behind the declared release gate before
> rethrowing the original OCE. The procedure waits for that barrier before release, and the full
> procedure has a bounded observer hang guard that releases gates before cleanup. This adds no
> SDK timeout or output fact; root retains compilation and execution.

> NOTE: External diagnostics found the early procedure blocking synchronously before its guard
> could arm through a derived MemoryStream read path. The fixture now composes a private
> MemoryStream and routes each sync/async read overload through exactly one gate wait before a
> direct inner read. The procedure is scheduled only to arm the observer-private guard before
> that fixture prefix; it does not add an SDK timeout or alter public ownership context.

> NOTE: The composed-fixture run reached a real raw-OCE token mismatch. Pending root contract
> adjudication, the fixture retains the actual cancelled read token and emits only six
> nonpayload stderr booleans when the existing exact-token predicate rejects an OCE. It neither
> accepts a different token nor rewrites the source exception.

> NOTE: N.3U source trace on 2026-10-19 replaces the diagnostic-only raw pending-read check
> with `RawReadCancellation`: an observer-only oracle captures the pending task, declared
> caller token, actual read token, and observed fixture barrier after the bounded join. It
> accepts the unchanged OCE only for the requested caller/read-token alternatives and rethrows
> every other OCE by exact identity. Focused internals-visible tests cover both valid tokens,
> successful completion, unrelated identity, missing barrier, and an unrequested read token.
> The corpus pin now names the root-held P.1T bytes. Root retains all compile, test, cold-review,
> and guarded-CLI gates; no author process ran.

> NOTE: Root's N.3U targeted compile found one mechanical named-argument casing error in the
> focused observer test. The sole correction uses the record's `CancellationObserved` parameter
> name; predicate behavior and test scenarios are unchanged. Root retains the focused retry.

> NOTE: N.3V source trace on 2026-10-19 preserves literal capability provenance by composing
> default facts into `ProviderDescriptor.DefaultCapabilities`, catalog/static facts into its
> model rows, and only explicit override facts through `AsyncClient` overrides. The observer
> records public default heuristic calls through a delegating estimator rather than replacing
> them with a zero calculator. Focused public-client controls distinguish the same default and
> catalog context floor, and verify heuristic-call capture. Root retains all compile, runtime,
> and guarded-CLI gates; no author process ran.

> NOTE: N.3V additionally treats every declared `tool_stream` procedure as a public stream,
> including both default and explicit manifest-payload clients. This retains literal public
> tool-delta ordering before the terminal result even when the input request omits `stream`.
> The source changes no response script, SDK hook, or expected value; the focused public-client
> regression uses fragmented adapter tool calls to guard that projection boundary.

> NOTE: Root's N.3V focused compile found one extra closing brace after the final
> `PolicyCase` member. The mechanical correction restores the single top-level type boundary;
> capability composition and estimator behavior are unchanged. Root retains the focused retry.

> NOTE: The N.3V focused test compile required the shared public-client helper to accept its
> actual `IProviderAdapter` contract, allowing the fragmented-tool adapter through without
> changing any test stimulus or assertion. Root retains the focused retry.

> NOTE: N.3V's fixture parser permits an actual empty `arguments_fragment` only when the
> field is present as a JSON string. IDs and procedure metadata retain their nonempty reader.
> The focused regression drives `ScriptQueue` and `RecordingAdapter` through public streaming,
> observing the empty tool delta before its terminal result. Root retains all gates.

> NOTE: N.3W replaces the unreachable sequential gated config call with actual first-body
> readiness, second public RequestStarted, no-second-send-before-release, release, and bounded
> joins. The queue governor performs the same public-start witness before cancelling its unsent
> second invocation. Observer capture maps and fixture scripts use scoped async-flow operation
> identity plus short capture locks; no waits or SDK work run under those locks. Focused controls
> cover the public config choreography, both raw-read caller-requested boundaries, and the
> empty-fragment terminal tool result. Root retains all compile/runtime/review gates; no author
> process ran.

> NOTE: Root's N.3W gate passes eleven focused controls after changing the test's empty
> native object construction to `new JsonObject([])`. The guarded CLI exits zero at
> `.tmp-tests/request-policy/root-native-n3w-d559dd4509fd4be7893466e02c1e5ffd/observations.json`,
> emitting 29 closed-schema records/41 operations with matching compiled source/dirty/corpus
> metadata and registered-secret redaction. Independent N.3W source review is now clean,
> including concurrent capture locks, public-start gates, release-first cleanup, and the
> two requested negative/terminal controls. Actual verifier qualification remains pending;
> N.4 is not yet accepted.

> NOTE: N.3X restores the initial observer client to the public payload-disabled default for
> every ordinary and default-capture operation. The only payload-enabled observer client is
> the separately constructed literal explicit-capture client. A focused PolicyCase control
> observes a null default manifest payload and redacted explicit tool arguments. Root retains
> compilation and runtime gates; no author process ran.

> NOTE: N.3X additionally fixes the ordinary offline harness setting to
> `https://policy.invalid/v1`; parsed config URLs remain literal and unchanged. The focused
> PolicyCase regression asserts each ordinary HTTP capture uses `/v1/chat/completions`.

> NOTE: N.3Y redacts every captured merged HTTP header value through the public registered-
> secret redactor after preserving its actual case-normalized name and joined value. Literal
> fixture keys flow through the public ResolverChain, which registers the resolved secret
> before adapter creation; a PolicyCase handler control retains content-type and streaming
> Accept while observing `Bearer [redacted]` and no raw credential in serialized evidence.

> NOTE: Root accepts the bounded N.4 producer gate on 2026-10-19: final N.3X cold review is
> clean, twelve focused controls pass, and the default stamped run builds without warnings
> or errors and validates all 29 native records against schema/provenance/qualification.
> Evidence is the native.json in
> `.tmp-tests/request-policy/root-stamped-v3aa-n3x-b3b65a3882aa41cc869ad13ab277be37/run-plkltkbs`.
> Root strengthened the selected payload JsonNode test with an assignable-JsonValue assertion
> to resolve nullable compilation. Independent comparison still fails (8/29 matches); N.4
> acceptance does not close P.5, V.4, parent POL.5, or full/clean-revision POL.7.

> NOTE: Root reopened N.4 when strict header comparison exposed raw captured credentials.
> N.3Y's public-redactor correction now has clean cold closure; all thirteen observer tests
> pass, and the new stamped build has zero warnings/errors. Fresh native/Python envelopes
> each qualify all 29 records with matching source/corpus metadata, and literal credentials
> plus registered synthetic secrets are absent. All 34 captured header pairs pass the held
> semantic rules. Root reaccepts this bounded producer gate at
> .tmp-tests/request-policy/root-stamped-n3y-d7a58178f9534f13a287c02425ce2389/run-f__ghihg/native.json.
> Comparison is 26/29 and remains outside N.4 acceptance.
