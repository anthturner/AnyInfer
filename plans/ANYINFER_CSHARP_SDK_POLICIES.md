# C# request policies, raw tools and cache placement

Resume from the first unchecked box. This is the executable child of SDK.5c in
`ANYINFER_CSHARP_SDK.md`. The user authorized full Python-aligned SDK implementation in
phases; this plan refines that existing work. Python source authority remains
`199c3f833e568334b629edd7d89f41a3b76efe2a`. Current prerequisite source is
`c7dc295d680fe51b39309fa7e17d65bf2cd7e307`, acceptance
`ce71c5ee8a87aff3c137eba843d443feb642fbca`. All ownership checklist gates pass there.

**Execution gate:** POL.0 through POL.6 gates are recorded; resume
POL.7 full-workspace and clean-revision acceptance. Root owns this shared
checklist, solution/workspace registration, builds and Git. Authors own only their named
source paths, report saved snapshots/reviews, and never run a shared build. Re-read a file
before editing it; preserve other authors' changes. No package publication/version bump.

## 1. Boundaries and decisions

- Use one GenerationCore and AsyncStream path. FrozenV0 retains all 102 observations and
  released hashes. New policy/tool/cache behavior is PublicSdk-only; internal frozen
  constructors receive no policy, context gate, cache plan or limiter injection.
- Keep accepted winning-entry usage/pricing/manifest commit, caller/iterator/close identity,
  synchronous close intent, signal/join ordering and post-join reservation release exact.
  No observer/estimator/factory/adapter/cleanup exception is recategorized merely because
  it passed through a new feature. Typed provider errors retain existing routing behavior.
- Pull forward SDK.7a's raw tool request/event/result/feedback subset because declaring
  public tools must expose their results. Callable registration/dispatch/loops remain SDK.7b.
  Images/audio/documents/reasoning/citations/server tools remain their own SDK.7 scope.
- Pull forward reusable cache policy/planning/typed wire marks from SDK.9b. Context/history
  reduction, ranking, distillation and cache-specific provider breadth remain unfinished.
  Generic OpenAI-compatible descriptors declare **no cache mechanism**, exactly as Python;
  do not invent an OpenAI cache field or infer placement from usage counters.
- Continue native checked Int64 token accounting and fixed p28/HalfEven EDecimal arithmetic.
  Public estimates do not become provider invoices or totals of all wire attempts.

## 2. Public and internal contracts

### Raw request/result surface

Append copied `IEnumerable<ToolSpec>? tools = null`, `string toolChoice = "auto"`, and
`CachePolicy? cache = null` to GenerationRequest. Snapshot declarations, reject null
elements, preserve order, retain auto/none/required/specific-name choice meaning. Existing
ToolSpec/ToolAnnotations are reused. Append matching optional tails to prompt/messages
Generate/Stream and Budget overloads on AsyncClient/Client without changing existing
positional arguments. Request-object overloads use the same path. Default-repair and
other request reconstruction must preserve all new fields.
Do not reject empty declarations with a non-auto choice at GenerationRequest admission:
Python accepts this, and generic OpenAI omits both tools/choice fields when tools are empty.
The existing direct legacy/Frozen WireRequest guard remains scoped to that older profile.

Add immutable ContentPart variants `ToolCall(string id, string name, JsonObject arguments)`
and `ToolResult(string callId, string content, bool isError = false)`. Add
`ToolCallDelta(int index, string? callId, string? name, string argumentsFragment)` to the
public StreamEvent union. Add copied `Generation.ToolCalls` as a constructor tail after
the existing manifest argument; WithManifest must preserve it. Add public XML docs.

PublicSdk normalization preserves part order and typed tool feedback; Frozen keeps its
existing text-only admission/flattening. Extend admission to the actual source-supported
tool role/content forms. OpenAI projects the first ToolResult in a message as one `role:
tool` message with that result's call ID/content, ignoring other parts and later results.
Modern tool-role messages may also contain the other admitted Text/ToolCall forms; do not
impose a ToolResult-only restriction that the source model does not have.
Do not invent an is_error wire field. Without ToolResult, preserve source role/text
projection and project ToolCall parts as tool_calls, with content null if no text exists.
Tool arguments use the actual JSON object, not a substitute DTO. Include mixed/multiple
result and empty-text call cases in literal wire tests.
The OpenAI function.arguments field is itself a JSON string: modern projection uses the
qualified WriteAccounting compact/default-spaces/ASCII mode for Python json.dumps spelling,
not a compact outer-wire writer whose whitespace would remain visible inside that string.
Schema prompt injection and repair reconstruction preserve existing typed parts.

EntrySession assembles tool fragments per index: retain the latest truthy id/name, append
every arguments fragment, enumerate calls by ascending index, synthesize `call_{index}`
for a missing ID and empty name when missing. Parse only object JSON arguments; malformed
or non-object arguments become an empty object plus warnings. **Any** ToolCallDelta is
content, even empty fields: set first-content timing and route content-emitted guards.
If calls exist and terminal finish is `stop`, normalize to `tool_calls`; otherwise retain
the finish reason. Retry/repair buffers stay distinct; only the winning entry's calls and
warnings reach Generation. Result/manifest payload privacy must not leak tool arguments by
default. With explicit payload capture enabled, record winning arguments in call order
using the existing manifest writer's sorted/default-separator policy and redaction.
Parse actual modern inbound tool calls in both buffered and SSE responses even when no
tools were declared; outbound tools/choice omission still follows declaration count.
No tool function executes.

### Estimation and cache

TokenEstimation flattens each message in part order: Text.Value; ToolCall.Name then
accounting JSON of its arguments; ToolResult.Content. Make one estimator call per message
plus four planning-only tokens. Unsupported parts remain unpriced; tool parts do not.
Estimate each declared tool separately, in request order, as insertion-ordered
`{name, description, parameters}` accounting JSON. Then estimate schema once. Preserve
messages -> tools -> schema -> calibration call/arithmetic order and checked sums.

New root `CacheMode { Off, Auto, Explicit }` and `CachePolicy`:
`(CacheMode mode=Auto, long minSegmentTokens=1024, int maxMarks=4,
bool includeTools=true, bool includeSystem=true)`. Validate known mode, min >= 0,
marks >= 1; Active iff mode != Off. New Capabilities `CacheMechanism { Explicit, Implicit }`,
`CacheMark(int Segment, long EstimatedTokens)`, immutable CachePlan with optional mechanism,
copied marks/reasons, checked estimated-cacheable total and Active, and
`CachePlanning.Plan(request, policy, capabilities, descriptor, estimator)`.

Append descriptor `CacheMechanism? cacheMechanism=null`, `int cacheMaxMarks=0`,
`long cacheMinTokens=0`. Zero descriptor max means use policy ceiling. Add copied
`WireRequest.CacheMarks` of segment indexes, default empty. Append
`IEnumerable<int>? cacheMarks=null` after toolChoice on both wire constructors and
RequestNormalizer.CreateWireRequest, preserving all earlier argument positions.
Mark sentinels: tools -2,
system -1, messages zero-based. Typed marks are available to actual custom adapters;
the generic HTTP adapter does not serialize a made-up field.

Absent/off policy returns empty plan. Missing descriptor mechanism returns source reason;
explicit additionally requires Feature.CachePlacement. Implicit has no marks and estimates
stable prefix only. Explicit candidates occur tools, system, stable non-system prefix in
that order. The stable prefix ends at the second-to-last non-system message index, not a
test for final-user role. Floor=max(policy min, descriptor min); cap=min(policy max,
descriptor max or policy max). Keep candidates >= floor; stable largest-first selection
preserves source candidate order on ties, then selected marks sort by segment for wire.
Use checked Int64 estimates. Cache tool sizing uses one ordered list, unlike per-tool
EstimateRequest calls. System text joins with newline. Preserve source include flags.

CachePlan.PrefixSignature returns a string shaped like Python's literal
`{system character count}:{system hash low32 as eight lowercase hex}:{tools hash low32 as
eight lowercase hex}`. Use native process-local ordinal string hashes on the normalized
system and sorted-key tools JSON; count Unicode scalars for valid text, not UTF-16 units.
Document equality/change diagnostic use, not persistent or cross-runtime hash identity.
The shared profile compares equality/change and string shape only. Do not create a new
persistent SHA-256 API. Keep signature JSON distinct from accounting insertion-order
sizing. Reuse existing JSON writer policy machinery if a sorted mode is needed; do not
build another serializer.

An Explicit policy on an implicit descriptor keeps its active implicit plan; emit
ParameterDropped("cache.mode", "the target offers implicit caching, not explicit marks")
and CachePlanned. An explicit descriptor without placement capability gets an inactive
plan and ParameterDropped instead. Do not disable usable implicit caching just because
the caller requested marks. Any inactive plan under an active Auto or Explicit policy
emits ParameterDropped("cache.mode", first reason or "no cacheable segment"). Only absent/
Off policies return silently. Descriptor-less opaque native adapters report the declared-
mechanism-unavailable outcome without inventing descriptor facts or doing estimation.

Request cache overrides client cache, including Off. Plan once per original route attempt,
before its repair loop. Every correction reuses that plan/marks even when repair messages
change; it emits no second cache-plan/prefix event. Retries/fallback create a new original
attempt plan. Reuse CachePlanned, ParameterDropped and ProviderDiagnostic. Only implicit
plans check prefix stability. A changed existing signature emits the existing
ProviderDiagnostic with code "cache.prefix-unstable", severity "info", no request ID,
and message "the cacheable prefix changed since the last request to this target, so the
provider's prompt cache will not be hit". Fold it into the current builder's notes through
RequestTelemetry. Compute signature outside the private per-client/per-target gate, update
state under that gate, then emit outside it before any Explicit-to-implicit drop and
CachePlanned. Explicit plans do not track prefixes. No new prefix-event family is added.

Preserve Int64 cache estimates through CachePlanned.EstimatedCacheableTokens and
CacheFacet.EstimatedCacheableTokens (including constructor, strict integer JSON decode and
telemetry serialization). Do not narrow the pure planner's long total to int. MarkCount
remains int; existing small-value JSON and all other field widths remain unchanged.

### Client admission

Append `SpendPolicy? spendPolicy=null`, `bool contextGate=true`,
`IReadOnlyDictionary<string, RateLimiter>? limiters=null`, `CachePolicy? cachePolicy=null`
after current estimator/ledger tails on public constructors and FromConfig/FromAdapters,
and forward through Client. Copy limiter maps with native normalized instance IDs,
ordinal lookup and duplicate-after-normalization refusal. Limiters remain caller-owned.
Supplying any policy creates a ledger if none was supplied, even inactive; subscribe once
through the normal dispatcher. A supplied ledger/estimator retains current ownership.

One internal GenerationPolicyContext holds immutable client services/settings, not another
router. Create its cache-service seam in POL.2, the first active consumer, then extend that
same type for pacing/admission in POL.3/4. Do not create a second cache-only orchestration
context or expose inactive policy settings early. Keep data in NormalizedRequest and services outside it. Per-target order is:
resolve -> dedupe -> TargetResolved -> health skip -> pool materialize -> **await factory
acquisition GetAdapterAsync** -> note capabilities -> AttemptStarted -> spend -> context ->
cache/wire -> pacing/timeout/adapter entry. Refusal means the core does not invoke adapter
Generate/the generation wire path for that target. Arbitrary credential/factory work may
itself perform HTTP and is outside that guarantee. Preserve source estimator call order.

Automatic spend estimates the high range with identity TokenCalibration; public Budget
continues descriptor calibration. Apply unknown/refuse, then per-request, then total
reservation. Equality passes. Unknown/refuse error's LimitUsd follows Python
`max_request_usd or max_total_usd` truthiness, so zero falls through. Unknown/allow reserves
nothing new; a prior known same-request-ID reservation remains until terminal completion
or close if a later fallback is unknown/allowed. This conservative boundary matches the
pinned Python implementation; do not add a native-only early release. SpendLimitException remains pre-dispatch nonretryable and does not become a
provider fallback error. Reserve once per original attempt: retry/fallback replaces the
same telemetry request-ID reservation, schema corrections do not recheck/re-reserve.

Default context gate uses descriptor calibration and only trusted whole-window Floor:
unknown/default/unpriced passes; Floor > trusted window refuses. Reserve/headroom/planning
tokens do not gate. Reuse ContextBudgeting.ContextGateError/CheckContextFit; don't duplicate
its math. Gate errors retain source provider, generate phase and nonretryable meaning.
Reuse UsageEstimated and other existing typed facts. Preserve final ledger charging only
on winning RequestCompleted, terminal failure removal and post-join/never-started release.

Append copied `Route.ContextWindowTargets`, default empty. For ContextLengthException
from either preflight or provider, replace remaining targets with a configured nonempty
specialized chain and dedupe by resolved identity. If that chain filters to zero, do not
restore the ordinary chain. An empty configured chain preserves ordinary fallback.
No specialized chain for unrelated errors; preserve retry/content/health behavior.
For modern generic OpenAI generation, port the pinned HTTP context classification:
only status 413/422 whose bounded error detail contains a case-insensitive source marker
(`context length`, `context_length`, `too many tokens`, `maximum context`) yields the
typed overflow. Read source error-detail shapes; a 400/code alone does not qualify.
Keep Frozen/lifecycle status-only behavior and unrelated status mappings unchanged.

### Pacing and transport ownership

Append `RateLimits? limits=null` to ProviderSettings/Of and preserve it through aliases,
defaults and ProviderConfig. Append descriptor `bool governsOwnTransport=false`.
Each instance lazily selects one effective limiter: injected mapping wins unchanged;
an inactive injected value still overrides active settings and creates no replacement.
Otherwise create from active settings, descriptor dialect, provider ID and client events,
with seesResponses false for opaque/own transport. Don't rebind injected event callbacks
or dispose caller limiters. Absent/inert settings leave transport unchanged.

Normal factories contractually consume ProviderConfig.Transport. With an active limiter
and !GovernsOwnTransport, pool creates a per-build GovernedHttpMessageHandler and supplies
it via an internal config transport override. No supplied raw: create default primary
handler owned by wrapper. Built-in supplied raw: wrapper borrows pool-owned raw; adapter
owns wrapper. Ordinary factory supplied raw: wrapper owns raw under the existing transfer.
Never conflate wrapper ownership with raw-handler pool ownership. No provider-ID branch.

Factory throw after pool-created wrapper construction triggers wrapper cleanup while
preserving the exact original factory exception, even if cleanup faults. Resolver/options
failure before handoff does not consume transport. A transferred non-pool supplied raw
handler becomes non-rebuildable after wrapper cleanup/late adapter discard; subsequent
acquisition refuses with actionable ConfigException rather than reusing a consumed handler.
Fresh default handlers and borrowed built-in raw handlers remain rebuildable. Do not add
an unrequested public handler-factory API or silently change arbitrary-factory ownership.

Own-transport descriptors receive unwrapped config transport and acquire one client-side
slot per original/correction entry **before EntryTimeoutScope**. Hold it through iterator
cleanup. Never also inject a handler governor. FromAdapters is opaque own transport: an
explicit injected instance limiter uses this outer slot, with no fabricated header reads.
Normal governed HTTP waits occur within existing entry timeout. Retry backoff/materialization
remain outside entry timers; each correction/retry gets a fresh entry timer/acquisition.

For an outer own-transport slot, inspect the existing ordered raw-parent cancellation
supplier before acquisition and immediately after it. If caller/iterator/close intent won
after a lease was acquired, dispose that lease before throwing the prioritized owned OCE.
The lease's finally covers pre-entry cancellation, adapter enumeration and cleanup faults.
Do not rely solely on deferred lease-child cancellation to prevent dispatch after close.
Do not catch/rewrite factory, adapter or user callback OCEs to implement these checkpoints.
Add a narrow internal RateLimiter.AcquireAsync overload accepting that parent supplier.
Translate OCE only in catch scopes directly surrounding the limiter's owned semaphore/
TimeProvider-delay awaits, and only when the effective child is cancelled and the supplier
returns an actually requested/cancelled parent (including published close intent).
Acquire/Observe callbacks remain outside those catches; planted callback/source OCEs keep
their exact identity. Standalone public AcquireAsync preserves existing behavior.

Use one internal standard TimeProvider for entry timers, carried by
GenerationPolicyContext.EntryTimeProvider (System by default) through OperationContext
and AdapterInvocationBoundary to EntryTimeoutScope. Friend core/boundary tests can supply
the same virtual provider as RateLimiter; public constructors gain no clock parameter.
PublicSdk EntryTimeoutScope owns an ITimer that requests its existing timeout CTS at the
current arm point, after lifecycle initialization, and joins/disposes the timer before
disposing registrations/CTS resources. Timer callback execution uses existing owner scopes;
callback faults must be retained for joined cleanup, never escape a worker unobserved.
Observe a retained worker fault only after joining cleanup; preserve any earlier source,
factory, iterator or cleanup failure. If the worker fault is sole failure, rethrow that
same object via EDI. Don't use CancellationIdentityContext as a substitute for the owned
wait/source-callback distinction.
Frozen has no policy clock and keeps the current CancelAfter implementation/lifecycle.
Retry IOperationClock remains separate and unchanged. This pins actual inside/outside
deadline behavior without real sleeps, scheduler guesses or test-only flags. The standard
timer/CTS distinction is grounded in the
[.NET 8 runtime source](https://github.com/dotnet/runtime/blob/v8.0.0/src/libraries/System.Private.CoreLib/src/System/Threading/CancellationTokenSource.cs).

The internal governing handler acquires before SendAsync, observes every response including
non-2xx, then transfers lease to LeaseContent. **Only content/response disposal releases**,
after original-content cleanup; no raw-stream release path. Adapter's existing nested
finally closes body then response. Send/Observe/wrap failure cleans response/lease while
retaining primary exception; content failure likewise wins lease cleanup failure. Attempt
every cleanup and release exact-once. Merge response and content headers using ordinal
ignore-case keys and comma-space repeated values. Never release at headers.

All Acquire/Observe and observer callbacks execute in the existing asynchronous and
captured synchronous owner contexts, outside private pool/stream/limiter state monitors.
The existing per-instance creation semaphore still spans the factory await, so factory
HTTP callbacks can run within that serialization boundary. Reject same-instance factory
reentry before its semaphore wait using a private AsyncLocal chain of reference-identical
InstanceState scopes. Push only around descriptor.Factory; each scope has shared active
state cleared in finally, so nested A-to-B-to-A construction fails promptly while other
instances and work captured after a factory returns remain allowed. Do not release the
creation gate or introduce a shared-build refactor. Existing owner self-disposal guards
remain in force. An injected limiter's callback is never rebound; its exact fault escapes
after permit unwind, while client observers retain the existing dispatcher isolation.

AttemptPacing is per original/correction entry, attached before acquisition/invocation,
detached on first AdapterEvent and in finally; never leak AsyncLocal state into consumer
code across a yield. Write that entry's queued_ms on success/failure; final Generation
uses winning entry only. Handler creates no pacing scope. Models/health reuse handler
observation/body ownership with existing lifecycle timeout and no generation entry slot;
own-transport lifecycle calls get no core limiter. Raw Probe bypasses generation admission,
the generation request-event spine and ledger, but actual governed HTTP may still emit
limiter events without an AttemptPacing request context. Do not suppress or rebind those
transport callbacks.

## 3. Configuration and proof boundaries

Port only actual shared-config producers: provider limits and root cache policy, with
strict source field/default/validation semantics. Python default_route remains a list of
target strings; ContextWindowTargets is a public Route API only, with no invented config
key or route-object encoding. A bare convenience target does not inherit a client's
specialized target chain, while an explicitly supplied Route retains its chain. Continue
rejecting unimplemented root context/history; spend remains constructor policy, not a new
shared config key. Update config reference/examples and strict parser tests together.

Add a separate input-only `request-policy-v1` corpus and actual independent public Python
and C# observers. Don't alter frozen assets or use Python as the native implementation.
Record raw source/corpus metadata using the accepted stamped-build handshake. Random
request IDs, clocks and prefix hashes compare causal relations (same-ID flags, event
ordering, equal/changed signatures), not fabricated fixed IDs or normalized money. Public
usage/cost/unknown/zero/typed tool values and declared wire marks remain actual values.
No alternate policy calculator, expected-output fixture or invoice claim.

Extract only common provenance/envelope/process plumbing into private
`scripts/_csharp_observation.py`; accounting keeps its exact local value/error/order/native-only
comparator and all controls. New closed verifier `scripts/check_csharp_request_policy.py`
owns its own shape/error contracts and rejects unexpected types/records/metadata. Native
observer `AnyInfer.RequestPolicy` uses compiled SDK revision plus
`RequestPolicySourceDirty`, no runtime Git fallback; Python uses execution-time Git and
exact raw corpus bytes. Both fail closed for missing/stale metadata. Synthetic checker
tests must catch false passes, but never substitute for executed native/public evidence.

## 4. Execution checklist and file ownership

- [x] **POL.0 — Contract gate.** Root reconciles this plan against cold 500e protocol/math
  and ec8 lifetime reviews. Review custom-factory transfer/consumption guard, wrapper
  disposal, AsyncLocal detach, input/estimator ordering and Frozen isolation. Confirm the
  specified internal TimeProvider/owned timer path and outer parent checkpoints, including
  exact source identity during queued cancellation. Resolve findings in place before
  granting source. Gate: both reviewers clean.
  > NOTE: Both independent bounded rereviews are clean, recorded in Traycer
  > `csharp-sdk/sdk-five-policy-protocol-review` and `sdk-five-policy-lifetime-review`.
  > Corrected cache mark reuse/refusal scope and pinned timer/owned-wait source identity.
- [x] **POL.1 — Raw tools.** c708 owns Models.cs, GenerationEvent.cs,
  Schema/RequestAdmission.cs, Core/RequestNormalizer.cs, Core/GenerationCore.cs, necessary
  schema prompt/repair preservation helpers and AsyncClient.cs/Client.cs request forwarding.
  cab owns Providers/WireRequest.cs and OpenAIChatAdapter.cs typed feedback/wire projection.
  c16 owns Capabilities/TokenEstimation.cs sizing updates only. Agree exact saved signatures
  before consumers. 04f owns new RawToolGenerationTests.cs; 1e owns independent Python raw
  tool stimuli/HTTP controls. Test empty deltas, ordering, malformed args, stop normalization,
  estimator strings/order, feedback, repair, clone and privacy. No callable execution.
  Gate: cold source/lifetime reviews, root zero-warning build/focused tests, frozen controls.
  > NOTE: Root gates pass: four independent Python controls, eleven focused raw-tool cases,
  > all 550 native unit tests and 93 conformance tests, with compiler warnings treated as
  > errors. Both final cold review artifacts are clean (`sdk-five-raw-tools-protocol-review`
  > and `sdk-five-raw-tools-lifetime-review` in Traycer). Corrected source gaps cover modern
  > tool-role admission, explicit redacted manifest arguments, and undeclared inbound calls.
  > CapabilityProbeRunner and ManifestBuilderTests received empty-tools/auto constructor
  > defaults. RoutingTests now pins public ordered Text parts versus Frozen joined text.
  > Distinct malformed discarded retry/repair calls prove winner-only calls/warnings;
  > retryable StreamProtocolException pins the empty-delta content guard. Python product,
  > released assets and frozen fixtures are unchanged. This is an uncommitted phase gate,
  > not full SDK.5c acceptance or callable tool execution.
- [x] **POL.2 — Cache producer.** c16 owns new CachePolicy.cs and
  Capabilities/{CachePlan.cs,CachePlanning.cs}, plus minimal Json/JsonWriter.cs signature
  policy if needed. cab owns descriptor metadata and WireRequest marks; c708 owns request/
  client cache tails, new Core/GenerationPolicyContext.cs and existing-core planning/telemetry,
  plus the cache-estimate-only Int64 seam in Events/{TelemetryEvent,TelemetrySerialization}.cs
  and Manifest/{ManifestFacets,ManifestSerialization}.cs.
  04f owns new CachePlanningTests.cs.
  Test exact estimator shapes, sentinels/stable prefix/ties/floors/caps/include flags,
  checked overflow, process-local signature equality/change, explicit capability refusal,
  request-Off precedence, implicit fallback/degradation, repair mark/event reuse and generic
  no-field. Gate: cold reviews and
  root focused pure/public execution with no inert public cache tail.
  > NOTE: GenerationPolicyContext creation is pulled forward from POL.4 because cache is
  > its first service consumer. c708 owns this same private seam throughout; later phases
  > extend it instead of introducing another router/context. POL.2 grants no spend,
  > limiter/timeout, config or reduction behavior. Agree saved cache signatures before
  > dependent edits; root continues to own all shared gates and checklist acceptance.
  > c16's pure CachePolicy/CachePlan/CachePlanning and internal WriteCacheSignature seam
  > are saved and held; 500e's pure and descriptor/wire producer reviews are clean.
  > All production and tests are saved and held. PrefixSignature
  > is an instance method; compare no
  > fixed process hashes. Source discovery corrected the plan's invented CachePrefixChanged
  > name: Python uses ProviderDiagnostic, already supported by native telemetry/manifest.
  > Root also found and removed the old Int32 estimate bottleneck under the new producer.
  > Final controls cover inactive Auto drops, target/client isolation, implicit diagnostic
  > ordering, explicit no-advisory behavior and >Int32 exact event/manifest roundtrips.
  > Both wire constructors and normalizer share the final cacheMarks tail.
  > Root's unchanged Python cache-planning/placement baseline passes all 28 tests.
  > Native compilation succeeds after test-helper-only lambda/dictionary adaptations.
  > Corrected a test fixture to provide genuine equal-size/under-floor candidates while
  > retaining the separate multiple-history boundary control. Root gates now pass all
  > thirteen cache cases, all 563 native unit tests and 93 conformance tests. Both cold
  > integration reviews are clean, including the full held test file, recorded in Traycer
  > `sdk-five-cache-protocol-review` and `sdk-five-cache-lifetime-review`. POL.2 is closed;
  > full workspace and clean-revision acceptance remain POL.7.
- [x] **POL.3 — Governor and pacing.** cab owns ProviderSettings.cs,
  Providers/{ProviderConfig.cs,ProviderDescriptor.cs,ProviderRegistry.cs},
  Core/ProviderRegistry.cs, narrow Routing/RateLimiter.cs owned-wait overload and new
  Routing/GovernedHttpMessageHandler.cs; earlier cab-owned
  adapter/wire files remain cab-owned. c708 owns client injection/config forwarding and
  GenerationCore/AdapterInvocationBoundary/EntryTimeoutScope/OperationContext pacing,
  the narrow Internal/OperationCapture.cs entry pacing fields and Routing/AttemptPacing.cs
  handoff, and
  the reviewed internal clock path. 1e owns new GovernedTransportTests.cs;
  The fresh `complete_entry_pacing` implementer owns own-transport/entry timing controls
  in EntryPacingTests.cs after the held 04f snapshot. c16 owns independent
  timer callback/fault/resource controls in new EntryTimerFailureTests.cs; helpers stay
  private to each test file and product sources remain held.
  Test header/error observation, permit through held content cleanup, Send/Observe/content
  failures, cancellation in queue, exact-once release, injected inactive precedence,
  per-instance isolation, own no-double-slot, caller callback ownership, factory callback
  reentry rejection/inactive-context continuation, late rebuild and
  transferred-raw refusal. Gate: cold protocol/lifetime reviews, root focused HTTP/timing
  tests, and accepted ownership/lifecycle tests all pass.
  > NOTE: Both final cold source/test reviews are clean in Traycer's
  > sdk-five-governor-protocol-review and sdk-five-governor-lifetime-review artifacts.
  > Root gate: dotnet test AnyInfer.sln --no-restore --verbosity minimal passes all
  > 604 native unit tests and 93 conformance tests, with zero compiler warnings/errors.
  > The 41 added controls cover governed HTTP, actual entry pacing and timer failures.
  > The unchanged Python limiter/timeout reference also passes 57 tests.
  > Full workspace and clean-revision acceptance remain POL.7; this is an uncommitted
  > phase gate on the accepted ownership prerequisite, with SDK.5c still unchecked.
  >
  > Source review fixed original-caller identity on handler-owned waits, timer arm/disposal
  > failure unwind, synchronous close-marker checkpoints and outer-permit cleanup after
  > iterator failure. Callbacks remain outside state monitors; the factory serialization
  > semaphore remains held, with active same-instance factory reentry rejected before wait.
  > Injected limiter callbacks retain ownership and exact source faults. Models/health/probe
  > keep their separate lifecycle rules; there is no broad source-exception remapping.
  >
  > After a stalled author handoff, a fresh implementer completed core controls, while
  > c16 independently authored timer-failure controls. Root retained the one GenerationCore
  > path and added no product hook. PublicSdk telemetry is required in manual stream fixtures;
  > Frozen remains on its existing CancelAfter path. Raw lease tests retain deterministic
  > simultaneous-parent priority/marker coverage without a new scheduling-race claim.
  > Retry/correction controls use 0.5s discarded and 1s winning waits; consumer attribution
  > passes at initial TimingMark, first adapter content and finalization, so no early-detach
  > change is warranted. Timer controls retain actual AggregateException/DeferredFailure
  > identity, worker joins, owner guards and earlier native/cleanup-fault precedence.
  >
  > Runtime corrected fixture assumptions about default retries/health gating, both aliases'
  > header facts, direct source faults and initial timing events. The SSE fixture now supplies
  > actual event-stream content, starts a live second read, and holds cancellation cleanup
  > until release; close and the next generation remain pending until real cleanup completes.
  > Failure paths release gates before bounded task/stream/client joins and retain primary
  > failures. Root also corrected test-only imports/raw-string mechanics and EOF whitespace.
  > AttemptPacing and OperationCapture required no shape changes.

- [x] **POL.4 — Admission/overflow/config.** c708 owns the existing internal
  Core/GenerationPolicyContext.cs, normalizer/core/client/Models routing and existing
  telemetry/manifest admission seams above. cab owns Config/AnyInferConfig.cs parsing,
  serialization and existing ConfigTests.cs, with an exact saved Cache property handoff.
  c16 owns new PolicyContextTests.cs after source signatures are saved; 1e owns new
  tests/test_request_policy_admission.py for independent Python baseline controls, then
  distinct native PolicyAdmissionHttpTests.cs after the native API handoff.
  Test factory-before-refusal/no Generate (not arbitrary factory HTTP);
  unknown/zero/equal/trusted/default; identity
  spend vs descriptor Budget calibration; active/inactive auto-ledger; retry/fallback
  replacement vs correction no recheck; overflow specialized-chain replacement/dedupe;
  callback fault/caller cancellation/early/unadvanced close release; no completion/charge
  on refusal; async post-close Budget/Spend purity and sync pre-work guard. Gate: cold
  source/math/lifetime reviews, root focused config/core/HTTP tests and result/event/ledger/
  manifest consistency. No context/history reducer or automatic tool execution.
  > NOTE: POL.4 phase gate passes: all 70 focused config/core/HTTP controls, all 657
  > native unit tests and 93 conformance tests, with zero compiler warnings/errors.
  > The independent Python admission baseline passes four controls. Final cold protocol
  > and lifetime reviews are clean in Traycer's sdk-five-admission-protocol-review and
  > sdk-five-admission-lifetime-review artifacts. This is an uncommitted phase gate;
  > full workspace, independent policy profile and clean-revision proof remain POL.5-7.
  >
  > Existing tracked SpendPolicy/SpendLimitException are reused. Provider limits/root
  > cache now parse, serialize and reach actual FromConfig consumers. Strict config stays
  > target-list-only for default_route; specialized targets remain copied public Route
  > data, context/history stay rejected, and spend is not a root key. Exact empty/partial/
  > full nested serialization controls use established canonical sorted keys.
  >
  > Spend admission is after factory acquisition and before core Generate; automatic
  > identity estimates, known retry/fallback reservation replacement, repair no-recheck,
  > inactive auto-ledger, cancellation/early/unadvanced release, calibrated Budget and
  > winning result/event/manifest/ledger consistency are executed. Known reservations
  > remain through unknown/allowed fallback until terminal cleanup in both runtimes;
  > source review withdrew a proposed native-only early release, and a held-fallback
  > regression pins retention and terminal removal.
  >
  > Real HTTP controls exposed missing modern context-error translation. The bounded
  > adapter/contract port now recognizes only Python's 413/422 plus detail markers,
  > preserves first-truthy JSON/raw fallback and 400-scalar bounds, omits RetryAfter only
  > on the typed context branch, and preserves Frozen/lifecycle/ordinary mappings.
  > Positives, negatives, raw-boundary and direct legacy-handler controls execute.
  >
  > Root corrected iterator-catch/test syntax/analyzer mechanics and fixture-only
  > assumptions about planning-token ceilings, schema-valid responses and already-observed
  > cancellation. Adapter-origin OCEs remain source exceptions rather than being rewritten
  > to caller tokens. The old EventLifecycle sequence now includes the default context
  > gate's source-backed UsageEstimated fact and its exact request/target/method fields.
  > Public unsupported content still fails before policy; the existing
  > PricingAndBudgetTests.Context_gate_uses_only_trusted_whole_window_lower_bound_not_planning_reserve_or_default_facts
  > covers the pure unpriced-part guard. AccountingLifecycleTests retain post-close pure
  > async queries and sync pre-work refusal. No media/reducer/tool execution was added.
- [x] **POL.4R — Source parity follow-ups exposed by independent proof.** c708 owns the
  missing-price spend guard and missing unsupported-header ParameterDropped in
  Core/GenerationCore.cs, disjoint new public test files and their leaves
  ANYINFER_CSHARP_POLICY_UNKNOWN_PRICE.md / ANYINFER_CSHARP_POLICY_LIMITER_DIAGNOSTIC.md.
  cab owns modern streaming Accept in OpenAIChatAdapter.cs, a disjoint public handler test
  and contracts/openai-compat.md under ANYINFER_CSHARP_POLICY_STREAM_ACCEPT.md. No changes
  to observer output can substitute for these source semantics. Root cold-reviews and runs
  focused checks, then coherent full native/conformance/preservation and fresh comparison.
  Gate: source-faithful public tests, zero compiler warnings/errors, preserved Frozen assets
  and accounting, then actual stamped observations without estimator/event/header erasure.
  > NOTE: Source review confirms missing-price automatic spend currently invokes the
  > estimator too early and unsupported-header ParameterDropped is missing, though limiter
  > behavior/reason metadata already agree. Modern streaming also needs explicit semantic
  > SSE Accept with Python's per-request override precedence. U/S source is held for cold
  > review; L diagnostic placement is active. Cache-null defaults already agree and stay
  > unchanged. Root batches native compilation/tests after the coherent source holds.
  > Root's coherent held-source gate now passes 22 focused controls, 679 native unit
  > tests and 93 conformance tests with zero compiler warnings/errors. Accounting again
  > passes 42 shared plus two observed native-only boundaries; FrozenV0 passes 102/102
  > DEVELOPMENT/UNRELEASED with tracked assets unchanged. Fresh Python/native runs each
  > contain 29 schema-valid observations and 41 operations with matching source/corpus
  > metadata and registered-secret redaction. U/L/S cold source reviews are clean.
  > The added retry-original diagnostic control exposed only test mechanics: an async
  > iterator needed a yield, record-value IndexOf confused identical drop events, and an
  > xUnit analyzer required its predicate overload. Root's corrected four-test diagnostic
  > gate now passes without warnings/errors; the narrow cold test closure remains open.
  > Root accepts the bounded POL.4R source phase after clean L.2R cold test closure and
  > strict comparison of all 34 actual header pairs (six streaming/SSE) in fresh independent
  > observations. U.3/L.3/S.3 are closed; raw estimator/event/header facts stay retained.
  > Parent POL.5 comparison is still incomplete and full workspace remains POL.7.
- [x] **POL.5 — Independent policy proof.** 1e owns new
  tests/fixtures/request-policy-v1/inputs.json and tests/test_request_policy_parity.py.
  cab owns the new AnyInfer.RequestPolicy project directory after its
  library work is held. 2ff owns common verifier extraction, new policy checker and
  tests/test_csharp_request_policy.py, retaining tests/test_csharp_accounting.py controls.
  Root owns solution/project registration and workspace.py/tests/test_workspace.py wiring:
  request-policy verifier after accounting before package in existing csharp phase; add
  new checker/helper to lint/format paths, total 20 steps, no new skip flag. Observers use
  actual public clients/adapters/handlers and causal resource gates; deterministic clocks
  and pure limiter arithmetic stay native unit coverage. Gate: cold producer/false-pass/resource reviews; root Python/native
  producer execution, strict comparison, existing accounting 42 shared/two native-only and
  frozen 102 controls remain passing. Report corpus coverage/exclusions honestly.
  > NOTE: Independent Python/native case-contract preparation is read-only until root
  > freezes the combined kind/value schema. The mechanics-only helper extraction can
  > proceed independently under ANYINFER_CSHARP_OBSERVATION_HELPER.md; its owner ticks
  > that disjoint checklist after targeted pure-Python gates. Root owns shared registration,
  > native execution and the parent acceptance checkbox.
  > The input-only contract/corpus draft is owned under
  > ANYINFER_CSHARP_POLICY_PYTHON_PROOF.md P.1; consumer implementations wait for root's
  > P.2 freeze. Public-only causal proof excludes internal clocks and unported media;
  > profile-local structured operation outcomes retain actual runtime error types.
  > Root accepted helper H.4 after a clean cold review, 32 targeted Python tests and
  > actual accounting execution: 42 shared matches and both native-only controls observed
  > with matching revision/dirty/raw-corpus provenance. Evidence is
  > .tmp-tests/accounting/helper-extraction/run-gjhzscqx/report.json. Workspace command/lint
  > wiring and its targeted tests pass; request-policy execution remains blocked on the
  > precise P.2 schema and causal corpus revision, so POL.5 stays unchecked.
  > The fresh sdk-five-profile-contract-review rejected freezing the first draft: input
  > grammar/scripts/config and intermediate reservation witnesses were incomplete.
  > P.1S in ANYINFER_CSHARP_POLICY_PYTHON_PROOF.md and O.2R in
  > ANYINFER_CSHARP_POLICY_PROJECTION.md are now SAVED/HELD. Root independently passed
  > their 23 pure contract controls. Resume the combined cold P.2/O.3 review; input/output
  > schemas and native seam mapping remain separate from runtime proof. The prepared native
  > and verifier handoffs are ANYINFER_CSHARP_POLICY_NATIVE_PROOF.md and
  > ANYINFER_CSHARP_POLICY_VERIFIER.md. No observer/checker implementation is granted yet.
  > The combined cold review found typed-capture/qualification gaps after the first
  > executable schemas. Root settled the correction protocol in Traycer's
  > sdk-five-policy-contract-decisions: actual public outcome/tool/error types, typed
  > HTTP/event/wire/privacy/resource captures, exact ledger versus resource checkpoints,
  > fixed context-floor stimuli and literal successful usage. Both schema authors own
  > bounded correction gates; P.2/O.3 remain open pending coherent cold closure.
  > Public seam review confirms send/header/body/cleanup order is observable; it cannot
  > establish that a second worker reached a private semaphore. The shared profile excludes
  > that witness and raw RateLimitWaited counts/durations; native friend-core tests retain
  > the internal queue/timer claims.
  > Root also executed the unchanged native FrozenV0 development profile during the
  > disjoint schema/docs wave: 102 pass, zero fail/error/unavailable. Evidence is
  > .tmp-tests/request-policy-prerequisites/frozen-development.json, explicitly
  > DEVELOPMENT/UNRELEASED. The first invocation refused a missing output parent; root
  > created the scratch directory and reran successfully without a source change. This
  > is preservation evidence, not publication or clean-revision acceptance.
  > Root accepted P.2/O.3 after combined cold closure, 23 independent pure contract tests
  > and two editorial corrections. The exact 29-case corpus/schema bytes are recorded in
  > sdk-five-policy-profile-freeze. Resume P.3/P.4 Python observer,
  > ANYINFER_CSHARP_POLICY_NATIVE_PROOF.md N.1-N.3 native observer and
  > ANYINFER_CSHARP_POLICY_VERIFIER.md V.1-V.3 checker under explicit disjoint grants.
  > No actual policy observer execution/comparison is accepted yet; schemas/corpus stay held.
  > Native N.1 saved its csproj/compiled-provenance entry seam. Root registered
  > AnyInfer.RequestPolicy in AnyInfer.sln without restore/build/run; N.2/N.3 remain
  > mutable until the author reports the full source held. The initial checker snapshot
  > passed 38 policy/helper/accounting tests, but cold review found four P1s: attempts versus
  > sends, incomplete causal qualification, resource partial-order comparison and raw-JSON
  > runtime-type mapping. Resume verifier V.3R; V.1/V.2 are reopened and actual comparison
  > stays blocked until the corrected checker and meaningful controls pass cold review. Config
  > consumer transport-only public composition is clarified in the freeze artifact;
  > parsed policy values stay unchanged and no product hook was added.
  > Independent Python implementation then exposed a concrete output-schema omission:
  > RequestFailed contains terminal ErrorInfo (AllTargetsFailed/SpendLimit included), not
  > only an attempt error. Root verified both public sources and authorized projection
  > O.3R. Root accepted its narrow schema/test correction after 77 pure tests and direct
  > validation of all local terminal names. The new output hash is in the freeze record;
  > input/corpus bytes and product behavior remain unchanged. Corrected-checker cold
  > rereview remains open, and neither observer runtime comparison is accepted yet.
  > Latest resume: verifier V.3S addresses five remaining cold-review P1s; its author
  > remains Terra with high reasoning. The first public Python pytest/standalone execution
  > produced 29 schema-valid records under matching provenance at
  > .tmp-tests/request-policy/root-python/run-bd02b231b4fa476584fe548dec7711e9, but cold
  > source review rejected causal/privacy/cleanup/provenance gaps; resume Python P.4R.
  > Native restore passed; the first stamped build exposed three projection/type errors,
  > whose source fixes are saved but uncompiled. Native cold review additionally requires
  > closed kind/procedure rejection and bounded joins; resume N.3R before N.4 rerun.
  > Projection O.3S now separates public manifest_usage (eight confirmed facet fields,
  > no server_tool_uses) from result/event Usage; AttemptCompleted ordinal derives from
  > matching public AttemptStarted. This controlled schema correction awaits its new
  > held hash. Inputs and SDK product behavior remain unchanged; no policy comparison,
  > full/clean-revision acceptance or package publication is claimed.
  > Root independently passed all 87 V.3S/schema/corpus/helper/accounting controls and
  > accepted the narrow O.3S output grammar; its replacement hash is in the freeze record.
  > Native N.3R now compiles under stamped provenance with zero warnings/errors. Actual
  > admission snapshots originate at public Send/Generate entry after policy admission,
  > not earlier AttemptStarted/retry/fallback labels; missing captures fail. Callback
  > projection faults are retained across observer isolation. Native source review and
  > the AttemptCompleted output-field alignment precede its first execution. Python P.4R
  > and verifier V.3S cold review remain active; no independent comparison is accepted.
  > Native cold review then closed the enum/join origins but found cancellation identity
  > and primary-failure cleanup gaps. Root also identified missing distinct concurrent
  > invocations and stream content readiness in the held procedure implementation. Resume
  > native N.3S before execution; compiled source alone is not causal observer acceptance.
  > Python P.4R's first three-operation governor attempt bypassed the actual governor:
  > its descriptor factory replaced ProviderConfig.Transport with a raw MockTransport.
  > Root requires public ProviderSettings transport attachment and preservation of the
  > pool-supplied transport through the builtin factory before adjudicating cancellation.
  > This is an observer setup correction; frozen inputs and product behavior stay held.
  > Fresh verifier rereview closed script/order, schema, resource association and typed
  > error-pair boundaries but found three remaining P1s. Resume V.3T: checkpoint histories
  > follow actual named capture points, unsent cancellation closes no nonexistent body,
  > and attempt/cache/tool witnesses require ordered operation joins. O.3S remains accepted;
  > V.4 and independent comparison remain blocked until corrected cold closure.
  > Native N.3S stamped compilation passes without warnings/errors. Its first actual CLI
  > execution stops before output because RequestStarted correlation is deferred until
  > invocation context is gone. A full held-source protocol/capture review now consolidates
  > remaining native gaps before another correction grant; no runtime proof is accepted.
  > The full native review validated five composition/capture P1s; resume N.3T on the
  > same cheaper Terra author with high reasoning. Python P.4R passes five root tests and
  > fresh schema/provenance execution (29 records, 43 operations), but its cache descriptor
  > composition still needs cold closure. No mechanism implies a capability grant: config
  > Auto's actual capability-refusal drop versus request-Off silence is the valid consumer
  > distinction, while dedicated explicit-mark input supplies CACHE_PLACEMENT. The freeze
  > records this source-backed clarification without changing input/schema bytes.
  > Root's V.3T pure gate passes 91 controls; independent Ruff/format-check found one
  > unformatted long line, assigned as a whitespace-only correction while cold review
  > continues. The fresh Python P.4R run is
  > .tmp-tests/request-policy/root-python-p4r/run-1a154906879/observations.json:
  > 29 schema-valid records, 43 operations and matching raw-corpus/revision/dirty metadata.
  > Its missing cache setup remains an observer finding; structural execution is not a
  > qualifying policy pass. Native N.3T now owns all five consolidated protocol findings.
  > The exact held V.3T snapshot now passes all 91 tests and Ruff/format gates. Cold causal
  > review leaves one Cache-Off telemetry-silence P1 for V.3U. Python cold P.4R rereview
  > leaves three observer P1s (governor subshape, cache setup and final stream close) for
  > P.4S; earlier event/provenance/redaction/barrier fixes are closed. No input/schema or
  > product behavior changes are needed, and independent comparison remains pending.
  > Native N.3T is saved; root's first recompile found two scalar-string helper call-site
  > errors. The author owns only that mechanics correction before the stamped compile/CLI
  > retry. Resume N.4 after its SAVED/HELD handoff and cold rereview; source remains
  > uncommitted on ce71c5ee8a87aff3c137eba843d443feb642fbca. P.4S/V.3U remain active.
  > Scalar reading and repeated-attempt lookup now compile cleanly and pass bounded cold
  > rereview. The next CLI run reaches the existing one-handler-per-instance ownership
  > guard: the observer reused one raw handler across settings. The owner now allocates
  > fresh handlers bound to actual instance identities and validates literal script
  > association. Product ownership rules stay unchanged; retry N.4 only after SAVED/HELD.
  > Root V.3U gates now pass all 96 pure controls and Ruff/format checks; narrow cold
  > rereview remains open. Native instance handlers compile and pass the ownership guard.
  > CLI next exposes cancellation bookkeeping: InvokeAsync already records its exact-token
  > cancellation, so joining that classified task must validate the recorded outcome;
  > raw pending reads still require their exact-token OCE. The owner corrects that split
  > and invocation-order operation projection before the next N.4 retry. No runtime output
  > or independent comparison is accepted yet.
  > Root V.3U now passes all 96 pure controls and its bounded cold rereview is clean.
  > Actual Python P.4S execution also passes eight producer controls and emits 29
  > schema-valid records (41 operations), but the first full local qualification rejects
  > all 29. Source adjudication separates checker defects (public attempts are one-based
  > per target) from lost producer facts (error trails, resource instance association and
  > checkpoint timing). Direct SpendLimit emits no RequestFailed on Python's path but does
  > on the accepted native lifecycle; its explicit profile treatment remains under review.
  > Resume Python P.4T capture corrections; no comparison or product change is accepted.
  > Native's latest stamped compile has zero warnings/errors, but its actual CLI exceeded
  > an external 35-second guard without output and was terminated. The author now traces
  > the observer guard/cleanup path with nonpayload diagnostics before another bounded run.
  > Current failure/evidence details are in Traycer sdk-five-policy-runtime-qualification.
  > Root source adjudication now grants verifier V.3V: one-based per-target attempts,
  > finite direct-spend terminal profiles and explicitly reported terminal manifest
  > estimator bookkeeping. Raw facts remain preserved, admission/repair evidence stays
  > shared, and arbitrary event/history differences remain failures. Python P.4T also
  > receives a controlled input-only beta:unpriced-model correction because Python
  > descriptor pricing cannot distinguish two aliases of the same model. Replacement
  > frozen SHA and fresh observations remain required after the held save.
  > Native composed-stream diagnostics remove the synchronous hang. Actual execution now
  > exits promptly at the early-stream raw OCE identity guard; exact supplied-read versus
  > original-caller identity is under source/contract review, with acceptance unchanged.
  > P.1T/P.4T is now held: root passes all 26 corpus/producer tests and Ruff, verifies
  > that only the three beta model occurrences changed, and freezes input SHA
  > 92e0fc9f6e128db05719446a91b891e9ee9cacc989d97f392496a8f08e649316.
  > Fresh Python evidence .tmp-tests/request-policy/root-python-p4t/run-1a154b664ca/observations.json
  > has 29 schema-valid records and 41 operations with matching provenance. Actual beta
  > cost is unknown, the original known reservation survives handoff, and cleanup releases
  > it; cold P.4T source review and V.3V qualification remain open. Native raw-read review
  > permits only the recorded cancelled public-read token or original caller token after
  > the real cancellation barrier; N.3U adds focused negative controls before rerun.
  > Cold P.4T/P.1T rereview is clean; the Python source/input slice now has independent
  > source and execution closure, while P.5 still requires qualification/comparison.
  > Native N.3U's six cancellation-oracle tests pass with zero compiler warnings/errors.
  > Actual CLI proceeds past early-stream but exposes a new setup defect: client
  > capability overrides promote default window provenance to trusted Override. Resume
  > N.3V descriptor default/static composition plus an actual default-estimator recording
  > wrapper. No product change or fabricated capability grant is authorized.
  > Root V.3V passes all 100 pure controls and Ruff, then actual Python qualification
  > advances to 18 of 29. Remaining source-backed corrections are P.4U (fresh baseline,
  > queued public-pending witness and uniform public tool-stream driving), V.3W (terminal
  > recovery work versus manifest suffix, implicit degradation/drop/changed-prefix ordering,
  > and outbound-feedback-only repair evidence), and native N.3V composition/stream driving.
  > The freeze records those capture clarifications without another corpus/schema change.
  > Synthetic gates/cold closure have again proved insufficient alone; POL.5 remains open
  > until actual qualified native/Python traces and their full comparison pass.
  > Root P.4U execution passes all eight producer controls and Ruff. Fresh output
  > .tmp-tests/request-policy/root-python-p4u/run-1a154c57ec4/observations.json contains
  > 29 closed-schema records with matching revised-corpus/source provenance and redaction.
  > All five fresh baselines are empty, queued operation 1 has a public pending witness
  > before cancellation with no send, and fragmented public deltas retain literal order.
  > Cold P.4U source review is clean. V.3W/native N.3V remain pending; no comparison is accepted.
  > Native N.3V observer compilation now passes after a brace-only correction. The actual
  > revised-corpus CLI passes all admission/context cases, then refuses the literal empty
  > arguments_fragment through an overstrict fixture string reader. The owner corrects
  > only that admitted fixture field and the test-helper interface type, with a regression
  > through the real ScriptQueue/RecordingAdapter/public stream. N.3V capability composition
  > receives cold source review while these bounded parser/test mechanics are corrected.
  > Root now passes all nine observer controls with zero compiler warnings/errors after
  > test-only JSON-type/alias/timing-event mechanics. The guarded CLI executes the first
  > 27 experiments, then its own ten-second guard catches config_consumer awaiting a held
  > first body before gate release. Resume native N.3W gated configuration choreography,
  > actual public-start/pending witnesses and synchronized concurrent capture. No native
  > observation envelope or comparison is accepted from that failed run.
  > Cold review closes immutable N.3V capability composition and the raw-read cancellation
  > predicate. N.3W also adds the requested unrequested-caller negative and exact terminal
  > tool-call assertions; mutable procedure/fixture/concurrency review remains open.
  > Root V.3W passes all 102 pure controls and Ruff; actual Python P.4U qualification
  > reaches 26 of 29. Resume verifier V.3X for the real concurrent-refusal estimate and
  > terminal-index warning order. Python P.4V corrects cancelled-body hold/release/join
  > choreography and records early-stream cancellation; the resource partial order remains
  > strict. Native N.3W and cold checker implementation review continue independently.
  > Root P.4V passes all nine producer tests and Ruff. Fresh Python evidence
  > .tmp-tests/request-policy/root-python-p4v/run-1a154d508dd/observations.json validates
  > all 29 records/provenance/redaction; direct checks prove cancel < release < body close
  > < recovery entry for both held-cancellation procedures. Cold P.4V review and V.3X
  > qualification remain pending; no native comparison or phase acceptance is claimed.
  > Cold P.4V rereview is clean; its Python producer slice now has independent source and
  > execution closure. V.3X reports 105 pure controls but remains source-only. A fresh
  > verifier review confirms cancellation-completion and unconstrained recovery-history
  > gaps; V.3Y corrects them before actual qualification. RequestFailed stays the closed
  > five-field public ErrorInfo projection; full terminal spend amounts remain separately
  > compared. Native N.3W remains in progress, with no accepted native envelope.
  > N.3W is now held and root passes all eleven focused observer controls. The guarded
  > native CLI exits zero and emits 29 closed-schema records/41 operations at
  > .tmp-tests/request-policy/root-native-n3w-d559dd4509fd4be7893466e02c1e5ffd/observations.json.
  > Raw corpus/source metadata and registered-secret redaction pass. The previously blocked
  > config case now executes both actual public operations. Cold native review, V.3Y
  > qualification and independent comparison remain required before N.4/POL.5 acceptance.
  > Independent N.3W review is now clean: public-start/body gate choreography, short capture
  > locks and actual per-instance resource identities retain bounded primary-preserving
  > cleanup. Both Python and native producer slices are held; resume V.3Y and actual
  > qualification/comparison, without another product or schema change.
  > Root V.3Y passes all 106 pure controls and Ruff; its immutable cold review is clean.
  > Actual qualification reaches 28/29 in each runtime: the remaining nullable delta-name
  > rejection contradicts the frozen string-or-null schema and is corrected narrowly in
  > V.3Z. Fresh preservation gates pass accounting 42 shared plus two observed native-only
  > boundaries, and FrozenV0 102/102 DEVELOPMENT/UNRELEASED with tracked assets unchanged.
  > Root V.3Z passes 107 pure controls/Ruff and both actual runs now qualify 29/29 with a
  > matching handshake. The first default stamped comparison executes successfully but
  > reports 1 match/28 mismatches. Source review identifies ordinary native clients enabling
  > manifest payloads and special comparator paths bypassing typed traversal/resource
  > rules or failing to compose operation-local direct-spend and manifest profiles. Resume
  > disjoint native N.3X and verifier V.3AA; keep all raw mismatches and no phase acceptance.
  > Root V.3AA passes all 109 pure controls and Ruff; cold comparator review is pending.
  > Replaying prior byte-preserved evidence confirms canonical comparison rules now retain
  > the approved direct-spend profile. It also exposes inconsistent ordinary fixture base
  > paths. N.3X now includes the settled offline /v1 base setting plus actual path capture,
  > alongside payload-disabled defaults; parsed config paths stay literal. Root awaits the
  > consolidated native hold before rerunning compiled/default comparison gates.
  > Root N.3X passes twelve focused controls, a zero-warning stamped build and clean cold
  > source review. All 29 fresh native observations qualify; bounded producer gate N.4 is
  > accepted. The new stamped comparison reaches 8/29 matches. Header captures, concurrent
  > telemetry and one handoff estimate require source adjudication before any new waiver
  > or SDK change. V.3AB repairs an impossible synthetic composition positive with two
  > fully qualified legal concurrent records. Parent POL.5/POL.7 remain unchecked.
  > Source adjudication distinguishes real policy/header/diagnostic gaps from permitted
  > transport defaults and cross-operation scheduling. V.3AC implements the frozen finite
  > header and causal telemetry comparison with raw evidence retained; it must not waive
  > the actual SDK fixes. Python P.4W forwards the frozen max_output_tokens:0 that its
  > kwargs previously omitted. No corpus/schema bytes change from these corrections.
  > Root passes P.4W's ten producer tests and V.3AC's 111 pure verifier controls, including
  > Ruff checks. The next actual stamped run rebuilds cleanly and qualifies both complete
  > envelopes but still compares 8/29. Its raw evidence is retained at
  > .tmp-tests/request-policy/root-stamped-v3ac-b1d4a5c5512149718a49a939eb265707/run-vqkaeyj_/report.json.
  > V.3AD corrects the safe Bearer redaction guard, validates auth before equality, keeps
  > configured buffered Accept/other configured headers strict, and requires semantic
  > content-type/stream Accept on both captures. Accept case-alias mutations are required.
  > No source event, estimate history or semantic header may be waived to accept a run.
  > Root V.3AD passes all 111 pure controls and Ruff. Its new stamped run still compares
  > 8/29 because native FixtureTransport copies raw HTTP header values into observations.
  > The credential guard is correctly rejecting that capture; N.3Y applies the public
  > registered-secret redactor at the actual header capture boundary with a real handler
  > regression. Native producer N.4 is reopened for this bounded correction and fresh
  > execution. No credential-safety waiver or SDK behavior change is authorized.
  > V.3AD cold source review is clean. Two test-only comparison controls remain: the
  > separately allowed bare redaction marker and configured-header provenance from the
  > matching config.providers entry. The author owns only tests/leaf for this closure;
  > checker semantics remain held while native N.3Y corrects capture redaction.
  > N.3Y now passes thirteen focused controls and cold review. The fresh stamped build
  > has no warnings/errors; both 29-record envelopes qualify with matching metadata and
  > no literal credentials/registered synthetic secrets. Native N.4 is reaccepted and
  > comparison advances to 26/29 at
  > .tmp-tests/request-policy/root-stamped-n3y-d7a58178f9534f13a287c02425ce2389/run-f__ghihg/report.json.
  > Remaining differences are native selected diagnostic wording inside fixed repair
  > feedback and Python's manual early-stream path dropping consumed timing events.
  > P.4X corrects only actual event capture. The established native-assessment contract is
  > under source review before any repair-feedback comparison decision; no SDK edit or
  > general message normalization is authorized.
  > Source/contract review confirms foundation proof intentionally retains runtime-local
  > selected native assessment feedback inside the shared correction template. Root grants
  > V.3AE's closed no_json_candidate repair-feedback comparison for the two existing
  > no-candidate stimuli, with full structural/script/event/schema/tool witnesses and raw
  > texts retained/reported. No SDK repair or schema/corpus edit is authorized. P.4X source
  > review is clean and all eleven producer controls plus Ruff pass; the next default
  > stamped run waits for the held verifier correction and its adversarial controls.
  > Root V.3AE passes 112 pure controls and Ruff. The actual fresh stamped comparison
  > advances to 28/29 at
  > .tmp-tests/request-policy/root-stamped-v3ae-b59167206c5947b183d65eed17beccad/run-9vbpcvst/report.json.
  > The sole remaining exclusion is an overnarrow procedure guard: the frozen tool repair
  > uses tool_stream, not repair_no_recheck. V.3AF admits exactly these two repair shapes
  > under the same predicate and adds a fully qualifying actual tool_stream/stream-entry
  > positive plus negatives. Raw evidence and all non-diagnostic fields remain strict.
  > Root accepts POL.5 after clean combined V.3AE/AF cold closure, 112 pure controls/Ruff,
  > eleven Python producer and thirteen native producer controls, then actual independent
  > stamped execution with 29/29 shared matches and zero compiler warnings/errors. Evidence:
  > .tmp-tests/request-policy/root-stamped-v3af-2a02d81f54a8416183a8e3f587aa83c2/run-41x8uvlc/report.json.
  > Both runtimes report 29 records/41 operations, matching ce71c5e dirty=true source and
  > raw corpus metadata; frozen input/schema hashes remain unchanged. The coherent SDK
  > preserves accounting 42+2 and FrozenV0 102/102 DEVELOPMENT/UNRELEASED. P.5/V.4 are
  > checked. Root has started the full workspace gate for POL.7; committed clean-source
  > proof, package and parent SDK.5c acceptance remain outstanding.
- [x] **POL.6 — Documentation/package.** c16 owns new compiled
  examples/csharp-sdk/RequestPolicyExample.cs, Program.cs calls, guides csharp-sdk.md and
  python-to-csharp.md, reference csharp-sdk.md, guides/README.md, src/csharp/README.md,
  scripts/check_csharp_package.py and tests/test_csharp_packaging.py. Include exact compiled
  source in both guides, execute each method offline, prove public API in isolated package
  consumer. Document transport ownership/rebuild limit, generic cache default, context
  default/refusal, winning-only spend, explicit policy/store ownership and lifecycle timer
  distinction. No plans links under docs and no unported tool-loop/rich-media claims.
  Gate: source-linked examples, strict docs, package graph/license/hash/consumer tests.
  > NOTE: Disjoint source-only D.1-D.4 is granted under
  > ANYINFER_CSHARP_POLICY_DOCUMENTATION.md while POL.5 input/output schemas are revised.
  > Production APIs are held and the author wave had no observer/schema/shared-file
  > ownership or native process grant. Root's final D.5 acceptance is recorded below.
  > Initial root package/example execution exposed fixture-oracle errors and weak raw
  > tool boundary checks. c16 owns the final D.4S correction in the disjoint docs leaf;
  > dependency/license/hash/revision controls and corrected pacing documentation are
  > cold-clean. Root reruns compiled/package/strict-docs gates only after SAVED/HELD.
  > Root accepted D.5 after the clean final cold review, revised Release offline example,
  > 23 packaging controls and actual isolated package consumer passed. The successful
  > consumer is .tmp-tests/nuget/policy-documentation/run-f4awn2fr (zero compiler warnings
  > and errors). All four docs-check/docs-build steps pass, including 50 runnable examples
  > and strict site build. Initial fixture errors were corrected without product changes;
  > the final package proof retains dependency/license/hash/revision controls. This
  > disjoint phase closes while POL.5 continues; no package publication/version bump or
  > SDK.5c/full-workspace/clean-revision acceptance is claimed.
- [ ] **POL.7 — Acceptance.** Root reconciles all saved files/reviews/checklists, then one
  full workspace check after coherent source is frozen. Require zero compiler warnings,
  every actual profile, all unit/conformance/config/example/package/docs gates and unchanged
  released assets. Commit explicit paths, run clean-revision policy/accounting/package
  proofs, record source/reports/acceptance and clean tree. Only then check parent SDK.5c;
  SDK.7/9 stay unchecked beyond their explicitly completed prerequisite subsets. Resume SDK.6.
  > NOTE: The first full run's test/conformance/doc-example shutdowns fail only on the
  > known shared .pytest_cache Windows ACL; all C# steps, strict docs build and other gates
  > pass. Root reruns the unchanged full gate with PYTEST_ADDOPTS selecting one fresh
  > ignored cache directory. No warnings are suppressed. Commit preparation also finds
  > the raw-pinned request-policy corpus/schema files lack checkout newline protection;
  > root adds text eol=lf for that fixture directory in .gitattributes, preserving their
  > current LF bytes and frozen hashes across Windows/Linux checkout. Direct Git-attribute
  > and staged-byte checks accompany this bounded repository-metadata correction.
  > Root's isolated-cache full workspace rerun passes all 20 steps in 147.6s, including
  > 681 native unit and 93 conformance tests, accounting 42+2, policy 29/29, isolated package
  > consumption, compiled examples and strict documentation. Log:
  > .tmp-tests/workspace-policy-6c7ae73b72e140ca8a0303fd4c8ccd95/workspace-check.log.
  > Whitespace checks pass. Resume POL.7 at explicit-path source commit, then clean-revision
  > policy/accounting/package proofs and acceptance record; no later SDK milestone is done.

> NOTE: POL.0 through POL.6 gates are recorded. Resume POL.7 full/clean-revision acceptance
> in the current working tree on accepted
> prerequisite `ce71c5ee8a87aff3c137eba843d443feb642fbca`.
> POL.5 prepares independent input-only observers and the closed stamped verifier.
> Full/clean-revision acceptance remains POL.7.
> Lifetime critique pinned deterministic timer placement, synchronous-parent checkpoints,
> owned-wait-only cancellation translation and joined timer fault precedence above.
> Protocol critique corrected an earlier discovery error: Python plans cache once before
> the repair loop and reuses it (`generation.py:859-880,1015-1038`). Refusal guarantees
> no core generation dispatch, not no arbitrary factory I/O. Both bounded rereviews closed
> cleanly before the POL.1 source grants.
