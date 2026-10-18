# C# SDK accounting, spend and pacing foundation

Resume from the first unchecked box. This executes SDK.5b of
`ANYINFER_CSHARP_SDK.md`; SDK.5c remains a separate request-policy integration phase.
The coordinator owns Git, this checklist, shared builds/restores and final gates.
Implementers own only the paths explicitly granted in a dispatch, re-read the affected
source before a minimal edit, and report saved source separately from executed evidence.

## 1. Authority and scope

The user authorized the full Python-aligned SDK, drafted then implemented in phases,
with Python concepts and ordinary C# conventions. This child elaborates that existing
authorization. It does not authorize publication, a version bump, new hosted services,
or changes to the released core-generation proof.

- Native starting point: SDK.5a source `68d2cc06914aaa8539eb3cc5ee8d20acdbd2a906`,
  acceptance `417d53fd1cfe07ccc81f669e4e8d1093fe88d912`; current plan-only checkpoint
  `2a0ba6f`. The 18-step gate, 474 unit / 93 conformance tests and clean-source package
  consumption are already accepted. Do not rerun them before new source warrants it.
- Python behavioral baseline remains `199c3f833e568334b629edd7d89f41a3b76efe2a`.
  Use actual `src/python/anyinfer/capabilities/{pricing,estimate,budget,gating,ledger}.py`,
  `routing/limits.py`, `_client/{generation,spend,providers,async_client}.py`,
  `types/{requests,results,capabilities}.py` and their tests. DESIGN's older examples do
  not override the actual source. Record any baseline change deliberately.
- Preserve `specification/core-generation.md`, its released corpus/manifest, all 102
  observations and their hashes. New accounting observations belong in a separate v1
  profile. FrozenV0's six-field usage overlay and raw cancellation branch stay inert.
- No new dependency: reuse PeterO.Numbers `[1.8.2]`, the existing JSON tree/writer and
  .NET 8. No Python process implements a C# operation. Python may generate verification
  observations and build-time data.

SDK.5b delivers pure pricing, estimates/budgets, ledger/store/policy values, a standalone
testable limiter, winning-result pricing and explicit client ledger/budget helpers.
SDK.5c owns automatic spend/context refusal, reservation placement, limiter injection and
transport leases, configuration activation and policy precedence. Cache/reduction,
retrieval operations and rich tool/multimodal request producers retain their later
milestones. Do not show those later APIs as implemented.

## 2. Settled behavioral boundaries

### Final usage is the winning entry

Python creates a fresh AttemptBuffer for each retry and schema correction. Final
Generation.Usage is the successful entry's later-known usage overlay, normalized once;
failed retries and discarded repair responses are not added to it. A ledger observes
RequestCompleted and counts that usage only. Failure/cancellation do not invent spend.
This is a successful-request total, not a provider invoice or an all-wire billing total.

Keep this behavior in the shared profile. Do not add a runtime accounting collector,
second router, public all-attempt report or aggregate Generation replacement. Direct
Usage.Sum vectors can qualify aggregation arithmetic; actual embedding/tool-loop
aggregation is connected by its owning later milestone.

Python attaches AdapterFinal.server_tool_uses back onto winning Usage after Merge,
because Merge deliberately clears that map. Native AdapterFinal currently has only
FinishReason/Usage. Pure tool-cost math is in scope; end-to-end provider-tool accounting
requires SDK.7's real producer. Do not fabricate a tool map or claim its integration.

### Money, counts and unknowns

- Public money is EDecimal directly, including nullable references. No decimal/double
  overloads or money wrapper. Parse operands exactly without an arithmetic context.
- Owned arithmetic uses the accepted immutable, flag-free precision-28 HalfEven context,
  Emin=-999999, Emax=999999, clamp=false and Invalid/DivideByZero/Overflow traps at every
  operation. Extend Internal/AccountingDecimal narrowly for subtraction, multiplication,
  division and signaling comparisons. ETrapException is the documented native arithmetic
  counterpart; do not catch/reclassify provider money by pre-screening it.
  Shared internal signatures are Add/Subtract/Multiply/Divide(EDecimal left, EDecimal right)
  returning EDecimal; Compare(left,right) returns the signaling comparison reduced to int;
  existing Price(EDecimal rate,long tokens) stays source-ordered; Format(EDecimal) is invariant
  native ToString. Context remains private, immutable and flag-free.
- Direct Pricing, Usage, totals and reservations preserve Python's permissive numeric
  values. Do not add blanket finite/nonnegative guards. Existing catalog parsing behavior
  stays: negative rejects; +Infinity accepted; signaling NaN comparison trap escapes.
- Known zero, null cost, absent count and zero count remain distinct. Do not put currency
  on Usage or invent currency conversion. Trust catalog/discovered/probed/override for
  calculated prices and admission bounds; Default does not authorize billing/refusal.
- Estimate/count/reservation request counters use signed long, aligned with native Usage;
  existing capability window/max-output facts remain int. Use checked sums, differences
  and float-to-long conversion. OverflowException exposes native range limits instead of
  wrapping or silently clamping. This profile's integer domain is explicitly Int64,
  unlike Python's unbounded integers; JSON arbitrary facts remain BigInteger.
- Existing public Usage.Normalized must use checked InputTokens+OutputTokens when it
  fills an absent total. An explicit TotalTokens or unknown input/output still short-circuits
  without evaluating that sum. Usage.Sum already uses checked LINQ long sums; retain its
  empty/unknown semantics. Test MaxValue+1 and MinValue-1 plus in-range boundary controls,
  including final PublicSdk winning usage. Do not change frozen six-field helpers to
  implement this public normalization fix.
- Immutable value records copy ordinal maps and preserve first-seen enumeration order.
  Money equality/hash use AccountingDecimal numeric semantics, including scale/signed-zero
  equality, and retain the accepted nonfinite representation behavior.

### Exact generation pricing order

PricingCalculator.ComputeCost(usage, capabilities) returns null without trusted pricing,
input count or output count. It computes tool cost first by enumeration order:
start Decimal(0); each missing tool rate makes the whole result null; otherwise add
Decimal(uses) * rate. Then compute output cost. Finally evaluate input + output + tools,
left to right. ComputeCost itself does not inspect a provider CostUsd override.

Every per-million branch evaluates `(Decimal(count) / 1_000_000) * rate`.
For input, read/write counts use null-as-zero only inside this already-known input branch:

1. Missing read rate or read <= 0: price all input at the full rate.
2. Otherwise uncached = input-read when input > read, **else input**, then price uncached
   at full rate plus read at read rate. Equality input==read does not set uncached to zero.
3. Add write cost only when write rate is known and write > 0. A missing write rate skips
   that supplement, matching source; it does not make the entire cost unknown.

WithCost returns the same Usage when CostUsd is non-null, even negative/nonfinite; it also
returns the same value when computation remains unknown. Otherwise copy every Usage field
and set only CostUsd. Do not use Merge to attach a cost, since Merge clears ServerToolUses.

ComputeOperationCost uses InputTokens, otherwise TotalTokens, for embedding; rerank uses
SearchUnits * PerSearchUnit. All other InferenceOperation values delegate generation.
WithOperationCost has the same provider-cost precedence. These helpers do not implement
the actual embedding/rerank operation paths.

EstimateCost low = floor/1M * input rate; high = tokens/1M * input rate + reserve/1M *
output rate. Preserve that order, trusted pricing and currency. Standalone EstimateCost
does not inspect UnpricedParts; ContextBudget.EstimatedCost does.

## 3. Native public surfaces

Use get-only immutable values with standalone XML documentation. New constructor arguments
use existing lower-camel conventions; preserve the existing PascalCase Usage arguments.
No forwarding aliases are needed for APIs first introduced here.

### Capabilities: estimates, pricing and budgets

New files under `src/csharp/AnyInfer/Capabilities/`:

| File / public surface | Contract |
| --- | --- |
| TokenEstimate.cs | sealed record TokenEstimate(long tokens, long floor); Tokens/Floor; componentwise checked Add and operator +; no invented ordering/nonnegative validation |
| ITokenEstimator.cs | ITokenEstimator.Estimate(string text) -> TokenEstimate |
| HeuristicTokenEstimator.cs | sealed record, multiplier=1.0; finite positive validation; UTF-8 bytes; ceil(ceil(bytes/3)*multiplier), floor=min(bytes/8 integer division,tokens) |
| RequestEstimate.cs | Messages/Tools/Schema TokenEstimate, optional Envelope=0/0 and UnpricedParts=0; checked Tokens/Floor sums |
| TokenEstimation.cs | static EstimateRequest(GenerationRequest, ITokenEstimator? estimator=null, TokenCalibration? calibration=null); constants EstimateBytesPerToken=3, FloorBytesPerToken=8, PerMessageOverheadTokens=4 |
| CostEstimate.cs | sealed record CostEstimate(EDecimal low, EDecimal high, string currency="USD"), numeric equality/hash |
| PricingCalculator.cs | static ComputeCost, WithCost, ComputeOperationCost, WithOperationCost, EstimateCost using the exact rules above; operation argument uses existing InferenceOperation |
| ContextBudget.cs | ContextWindow:Sourced<int>?, Estimate:RequestEstimate, OutputReserveTokens:long, HeadroomTokens:long, Pricing:Sourced<Pricing>?; computed InputAllowanceTokens/RemainingTokens:long?, Fits:bool?, EstimatedCost:CostEstimate? |
| ContextBudgeting.cs | static HeadroomFor(long window); BuildContextBudget(request, capabilities, estimator=null, calibration=null, outputReserveTokens=null, headroomTokens=null); ContextGateError(budget, provider=null, model=null); CheckContextFit(request, capabilities, estimator=null, calibration=null, outputReserveTokens=null, provider=null, model=null) |

Use explicit method parameter types/null defaults corresponding to these values; no loosely
typed bags. Sourced<T> and ModelCapabilities keep their existing native shapes.
PricingCalculator signatures use `(Usage usage, ModelCapabilities? capabilities)` for
generation helpers and append `InferenceOperation operation` for operation helpers;
EstimateCost takes `(RequestEstimate estimate, long outputReserveTokens,
Sourced<Pricing>? pricing)`. ContextGateError returns ContextLengthException?;
CheckContextFit returns ContextBudget or throws that exact error.

EstimateRequest counts concatenated Text.Value per message with no separator, then adds
4 planning-only tokens per message. Every currently unsupported nontext ContentPart adds
one UnpricedParts and contributes no guessed text. Tools is 0/0 because GenerationRequest
cannot yet represent offered tools; state that coverage in docs. SDK.7 expands the same
extractor when typed calls/results/tools/multimodal fields actually arrive.

Count the attached schema's actual immutable JsonValue via insertion-ordered, ASCII JSON
with Python default `, ` / `: ` separators, not the sorted manifest representation.
Use a new internal JsonWriter.WriteAccounting(value, int? indent=null) policy sharing the
existing traversal: preserve insertion order, Python finite-double spelling and arbitrary
integers. indent=2 supplies store formatting. All existing writer modes remain unchanged.
Schema estimation is explicit, inert sizing: no validation, cast to JsonObject, reference
resolution or change to late schema assessment. Boolean schema sizing is a documented
native extension; shared Python dict-schema vectors remain object-rooted.

Envelope = max(0,ceil(content.Tokens*calibration.Multiplier)-content.Tokens) +
calibration.OverheadTokens, floor=0; no calibration/identity => 0/0. Preserve custom
estimator call order and input bytes. No endpoint tokenizer or new dependency.

Budget rules:

- ContextWindow keeps known Default facts for planning; only the gate excludes Default.
- Reserve: explicit nonnegative -> request Sampling.MaxOutputTokens -> min(4096, known
  model MaxOutputTokens); no added clamping of an explicitly supplied/request value.
- Headroom: explicit nonnegative -> ceil(window*0.05) clamped [256,8192], or zero with
  unknown window. Input allowance=max(0,window-reserve-headroom).
- Unknown window or UnpricedParts != 0 makes Remaining/Fits unknown; UnpricedParts also
  makes budget EstimatedCost unknown. Never convert these states to false/zero.
- ContextGateError returns existing ContextLengthException only if no unpriced parts,
  trusted window, and estimate.Floor > whole window. Reserve/headroom/planning Tokens
  do not gate. Preserve source provider/model message and actionable native hint.
- CheckContextFit explicitly invokes that gate. Normal generation does not call it until
  SDK.5c, preserving existing malformed-schema timing and request semantics.

### Ledger, persistence and policy values

New `Capabilities/SpendTotals.cs`, `SpendLedger.cs`, `SpendStore.cs`:

- SpendTotals(EDecimal? cost=null, string currency="USD", long requests=0,
  long unknownRequests=0, long inputTokens=0, long outputTokens=0,
  long cacheReadTokens=0). Null constructor default becomes exact EDecimal.Zero;
  Cost itself is non-null. Complete iff UnknownRequests==0. Plus(Usage) follows Python
  addition order and known/null costs; do not validate balances or arbitrary currency.
  ToDictionary():JsonObject and static FromDictionary(JsonObject):SpendTotals? cover
  store values with exact string cost. Missing/unreadable cost returns null. Missing
  counters/currency default as source; present native fields have strict documented
  string/integer types and checked Int64 range, not Python's incidental int()/str() casts.
- SpendLedger(string currency="USD") implements Events.IObserver; public Record(target,
  usage, requestId=null), Reserve(requestId, EDecimal estimate, EDecimal? ceiling),
  Release(requestId), Reserved(), Totals(), ByTarget(), ByLabel(string key), Reset().
  Reserve returns named `(bool Accepted, EDecimal Spent, EDecimal Reserved)`; no extra
  reservation class. All reads expose independent immutable ordinal snapshots.
- On RequestStarted, copy nonempty metadata; RequestFailed removes metadata/reservation;
  RequestCompleted calls Record. Record removes matching metadata/reservation, then updates
  overall, target and labels under one lock in source order. No callbacks/I/O under lock.
  Repeated completion is not magically idempotent: preserve Python's event semantics.
- Reserve holds one lock: previous=get(id,0); reserved=sum(all current values,0)-previous;
  spent=overall.Cost; compare spent+reserved+estimate > ceiling in that order. Rejection
  leaves the old reservation unchanged; acceptance replaces it. Do not remove-before-check
  or sum-excluding-old, which changes finite-precision behavior. Release removes only the
  reservation, as Python does; do not silently change pending-metadata lifetime.
- Reset clears all maps/reservations/metadata and resets totals in configured currency.
  No cross-client global; callers can deliberately share the same ledger.
- SpendStore(string path) constructor inert; Path:string, const FormatVersion=1;
  Load():IReadOnlyDictionary<string,SpendTotals>; Accumulate(SpendLedger,string bucket="total")
  returns void. Missing/unreadable/invalid/foreign file => empty; unreadable individual
  bucket => skipped. Catch known file/JSON/conversion errors only, not arbitrary callbacks
  or arithmetic/fatal failures. Exact v1 object is format_version then buckets; bucket
  fields cost,currency,requests,unknown_requests,input_tokens,output_tokens,cache_read_tokens.
- Accumulate reads file, then ledger snapshot, refuses exact currency mismatch only when
  updating an existing bucket, adds existing+incoming in source order. Replacement of an
  existing key retains its insertion position. Evict oldest insertion keys beyond 512;
  updating a key does not make it recent. Load does not invent a cap absent from source.
- Explicit write creates parents, uses same-directory unique temporary file plus atomic
  replacement, UTF-8 without BOM, indent=2 ASCII insertion-order JSON, no trailing newline.
  The in-memory writer string is LF, while SpendStore file output uses the host newline,
  matching Python Path.write_text (CRLF on Windows, LF on Unix). Raw-byte qualification
  compares on the same host platform, using ReadAllBytes/read_bytes then strict UTF-8
  decoding, never universal-newline text readers or BOM-stripping readers.
  Clean its temporary on failure. Atomic readability is guaranteed; cross-process lossless
  read-modify-write/locking is not. No automatic store on client/ledger construction.
  Unique temporary names are a deliberate native strengthening over Python's fixed .tmp
  path; they do not make concurrent accumulation a transactional operation.
  This also excludes lossless concurrent Accumulate calls from threads sharing the same
  SpendStore instance: no instance transaction gate is added. Callers serialize RMW when
  they need that guarantee.

New root `SpendPolicy.cs`: immutable MaxTotalUsd/MaxRequestUsd nullable EDecimal,
OnUnknown="allow", Active. Only negative-ceiling comparisons and allow/refuse validation
are source-backed. +Infinity can be a ceiling; NaN follows the signaling comparison trap.
New root `SpendLimitException.cs` maps Python SpendLimitError. Constructor is
`(string message, EDecimal? limitUsd=null, EDecimal? spentUsd=null,
EDecimal? estimatedUsd=null, string? hint=null)` with get-only money properties.
It directly extends AnyInferException: native category="spend_limit", phase="generate",
retryable=false, no provider/status/retry-after; retain existing redaction for message/hint.
Python has no Category field, so spend_limit is the explicit native semantic mapping.
No request refusal or implicit ledger construction is connected in SDK.5b.

Money persistence requires its own qualification before selecting a formatter. Compare
actual Decimal.__str__ and native EDecimal output for sign/scale/signed zero, fixed/scientific
cutoffs, exponent signs, large exponents, NaN/sNaN payloads/Infinity, exact raw parsing,
culture and concurrent use. Select AccountingDecimal.Format only after this gate; prefer
qualified native ToString where exact, otherwise one bounded coefficient/exponent formatter.
No numeric coercion, second decimal implementation or equality-based masking. Migrate
existing telemetry/manifest money projection only if required and preserve all accepted
format-1 outputs with direct tests.
> NOTE: ACCT.0 executed the cold-reviewed input-only observers on 2026-10-18. All 28
> jointly parsed text/state cases and 120 concurrent text observations match. Select
> AccountingDecimal.Format(value) => value.ToString(), with no custom formatter or changes
> to accepted format-1 projections. Python accepts raw 1_000 while EDecimal rejects it;
> canonical store strings never contain underscores. This native lexical boundary and
> typed decoding scope are recorded in specification/accounting-v1.md, not normalized away.

### Standalone pacing primitives

New root RateLimits.cs: immutable maxConcurrent:int?=null, requestsPerMinute:double?=null,
minIntervalS=0, respectHeaders=true, reserveFraction=0. Validate only source comparisons:
max<1, RPM<=0, interval<0, not(0<=reserve<1). Do not add speculative finite guards.
Active iff a configured concurrency/RPM bound, positive interval, or RespectHeaders.
Thus omitted settings != bare RateLimits(); RespectHeaders=false with no bounds is inert.

New `Routing/RateLimiter.cs`, `RateLimitLease.cs`, `RateLimitParsing.cs` and internal
`AttemptPacing.cs`. Public RateLimiter constructor:

```csharp
RateLimiter(RateLimits limits, RateLimitHeaders? dialect = null,
    string providerId = "", Action<TelemetryEvent>? events = null,
    bool seesResponses = true, TimeProvider? timeProvider = null)
```

Public members: Limits, ReadsHeaders, UnsupportedHeadersReason; ObservedWaitS():double;
AcquireAsync(CancellationToken=default):ValueTask<RateLimitLease>;
Observe(IReadOnlyDictionary<string,string> headers):void. Lease implements IDisposable and
IAsyncDisposable, releasing at most once. Limiter has no client/resource ownership or
disposal that can race outstanding permits. Caller-supplied TimeProvider supplies monotonic
timestamps, UTC for resets and provider-aware Task.Delay. Keep frozen IOperationClock intact.
Widen existing RateLimitObserved.RequestsRemaining and TokensRemaining from int? to long?
to carry the same native count domain as its actual producer. Do not narrow at event
publication; existing integer JSON projection remains unchanged for prior values. This is
an explicit additive-width SDK prerequisite, not a new format field. Use checked double
to long header conversion, including the rounded positive Int64 boundary.

- Acquire configured semaphore first, then pace; any failed/cancelled acquire path releases
  an acquired permit. Snapshot/update state under a private gate, await outside it, and
  invoke event callbacks outside it. Native concurrent Observe/Acquire/reads are safe.
- Bucket starts full; capacity=max(1,RPM/60), refill=RPM/60. Interval and header delays
  compete using Python's ordered tuple max; equal-delay reason ordering is explicit.
  Consume one token/update last dispatch/decrement observed remaining only upon dispatch.
- Header waits have cumulative 60-second ceiling per acquire; configured RPM/interval
  waits do not. Both remaining and reset names are required; limit only supplies reserve
  floor=limit*reserveFraction. No invented dialect or engine-ID branch.
- Observe updates only present declared fields, retains others and reports actual parsed
  remaining facts; 429 handling later uses this same method. Reads never consume tokens.
  No visible response headers => configured bounds only, with source degradation reason.
- Parse bare nonnegative seconds, complete ms/s/m/h duration strings and timezone-aware
  ISO reset instants against TimeProvider UTC. Header counts follow float-to-integer
  truncation/nonnegative check within Int64; preserve invalid-vs-overflow distinction.
  Python _read_int catches ValueError, not OverflowError; Infinity is not silently ignored.
- Preserve Python ordered comparisons/min/max for nonfinite double edge values; do not
  substitute Math.Min/Max where NaN ordering changes behavior. Infinite native waits are
  cancellation-aware; large configured waits must not fail due solely to Task.Delay's
  timer range. Qualification includes these boundaries; no new validation by convenience.
- Positive waits emit RateLimitWaited with concurrency/interval/provider-headers; context
  absent => empty request ID. A public supplied events callback may throw, but acquired
  permits are still unwound. Sequence is calculate under gate, wait outside, report the
  completed positive wait outside, then re-enter/recompute before dispatch consumption.
  A Waited callback fault cannot consume a dispatch token, update last-dispatch or
  decrement remaining for a request that never receives a lease. Legitimate clock/refill
  progression is not rolled back. Observe callbacks happen after the observed header
  state update, as source does. No user callback is invoked under limiter locks.
- Internal AttemptPacing scopes attribution with AsyncLocal and detaches before first
  provider event/finally once wired in SDK.5c. Standalone tests can use its friend seam;
  do not yet add queued_ms or generation pacing facts without actual governed traffic.

No ProviderSettings.Limits, client limiter map, pool/HTTP handler governance or active
rate-limit config in this slice. SDK.5c will hold a permit through response/body disposal,
including error/early-close/cancellation, and avoid double governance for HttpClient.

## 4. SDK.5b integration seams

Core/ProviderRegistry.cs TargetMetadata gets a nullable full ModelCapabilities tail.
Core/TargetMetadataResolver captures that immutable snapshot once from the existing
CapabilityStore; retains it even when Features=None@Default needs the existing legacy
StructuredOutputProfile fallback. Frozen returns unchanged metadata before this path.
No new probes, network work, eager adapter construction or capability authority.

GenerationCore, PublicSdk only: after actual schema success, normalize winning usage and
apply WithCost with the selected target's full capability snapshot before AttemptCompleted,
Generation construction and stream CommitSuccess. Null native Usage remains null.
ManifestBuilder.NoteCapabilities uses that same snapshot (callback fallback for existing
internal tests), so result/event/manifest price provenance agree. Retain winning entry,
attempt and correction timing and frozen helpers exactly. Price calculation must not
mutate raw AdapterUsage/UsageUpdate events or retrospectively price failed attempts.

AsyncClient/Client constructors and FromConfig/FromAdapters append ITokenEstimator? estimator
and SpendLedger? ledger tails, forwarding the same objects. Subscribe a supplied ledger
normally via EventDispatcher, payloads=false; no client disposal of it or private ledger
transaction outside events. The same reference also supplied in observers has ordinary
duplicate-subscription behavior; do not silently deduplicate. Expose Spend():SpendTotals,
returning ledger.Totals() or a new zero total if none, matching Python.

Expose inert Budget(GenerationRequest request, string target, long? outputReserveTokens=null)
on both clients, plus `(string prompt, string target, SchemaSpec? schema=null,
Sampling? sampling=null, long? outputReserveTokens=null)` and the same overload with
`IEnumerable<Message> messages` replacing prompt. Pin the actual Python facade distinction:
AsyncClient.Budget and Spend remain callable after close, doing only pure calculation /
ledger reads; Client.Budget and Spend enforce its ordinary closed-client guard then
delegate directly without the background runner. Python sync_client.py:606-640 explicitly
calls _ensure_open for these two helpers although async_client.py:2101-2190 does not.
Do not infer their close contract solely from native Resolve/Capabilities. Resolve only
metadata/capabilities and descriptor TokenCalibration, use configured estimator, call pure
BuildContextBudget. No credentials/factory/HTTP, no route exploration or hidden gate.
Explicit target is the model being budgeted; this does not choose a route winner.
Tests call Budget before/after close with connected factory/resolver/event spies: async
returns the same budget, sync refuses before work, neither sends/constructs/reserves/emits.
An explicitly supplied ITokenEstimator is invoked by successful Budget calculation;
"pure query" does not mean suppressing that requested custom estimator.

Stream completion/close releases any ledger reservation for its exact telemetry RequestId
after native iterator, cancellation signal and lease cleanup have joined, preserving the
original terminal exception. Manual Reserve can exercise this release before SDK.5c creates
automatic reservations. No RequestFailed for OCE, no fabricated complete manifest, and no
generation costs/ledger behavior in raw probes. New automatic reservation placement belongs
to SDK.5c. Attach the idempotent request-ID-specific release to AsyncStream's existing close
notification, reached after StreamEnumerator disposal joins and by outer stream close. This covers
manual reservation against an already-published partial-manifest ID followed by closing
without enumeration; RunStreamAsync's iterator finally alone is unreachable there.
Do not acquire client/stream gates while holding the ledger lock. The close release must
not start the iterator, emit RequestStarted, construct an adapter or replace a prior fault.
Nothing starts for an unadvanced lazy stream.
> NOTE: Lifecycle review found that releasing in RunStreamAsync's iterator finally precedes
> lease cleanup. The saved implementation retains its existing active-set removal there and
> releases through once-only NotifyClosed after enumeration cleanup, including before fault
> replay. Outer stream close covers never-started streams. Normal ledger event folding retains
> its source-defined reservation removal; this change concerns the explicit cleanup release.

## 5. Executable checklist and disjoint ownership

Names below identify responsibilities, not permission to edit before a bounded dispatch.
No worker runs Git; no worker edits this shared plan concurrently. Each reports exact
paths, Python anchors, static findings, executed commands if any, and remaining gates.
Root ticks accepted boxes after re-reading this plan and evidence; deviations get NOTE lines.

- [x] **ACCT.0 — Contract and decimal-text qualification.** Root owns this plan and
  specification/accounting-v1.md; c16 may own scratch-only `.tmp-tests/accounting-text-qualification/`
  input corpus and independent Python/native observers. Do not requalify the already
  accepted library selection. Review the precise money, count, pricing, budget, ledger,
  store, limiter and integration rules against source, including any native exception
  default and method signature still needing a literal check. Root selects/records the
  text codec after executing the unchanged observers. Gate: cold math/protocol and
  concurrency/lifetime plan critiques close; actual text observations agree in the
  declared domain and divergences have explicit controlled behavior.
  > NOTE: Both independent contract reviews are closed after checked Usage normalization,
  > unadvanced-close release, precise callback ordering and facade close-state fixes.
  > Root restored/executed both unchanged observers; raw output files are under
  > .tmp-tests/accounting-text-qualification/. 28 joint values and 120 concurrent texts
  > match; the one underscore parse difference is retained explicitly. Development profile
  > is specification/accounting-v1.md. No production accounting execution is claimed.

- [x] **ACCT.1 — Pure helpers and values.** After ACCT.0 closes, 2ff owns the nine new
  Capabilities estimate/pricing/budget files above; c708 separately owns only the new
  JsonWriter accounting policy; c16 owns SpendTotals/SpendLedger/SpendStore, root policy/
  exception files, AccountingDecimal additions and the narrowly scoped checked
  Usage.Normalized change in Models.cs. 04f owns its direct width/short-circuit controls
  in AccountingValueTests.cs. Public APIs are saved coherently
  before test authors consume them. Serialize any shared writer/helper handoff. Gate:
  independent literal native math/estimate/budget/store tests, unknown-vs-zero, numeric
  equality/snapshots, direct persistence bytes and immutable context controls pass with
  zero warnings; both bounded source reviews close.
  > NOTE: Root's coordinated focused gate passes 38/38 across accounting values, pricing/
  > budgets, ledger/store and limiter controls, zero compiler warnings. Source and causal
  > reviews are closed. Store files now match actual Python host newlines with raw-byte
  > assertions; writer strings remain invariant LF. Pure helpers only are accepted here.

- [x] **ACCT.2 — Pacing state and concurrency.** Cab owns only the new RateLimits and
  Routing files plus the two RateLimitObserved nullable-count type widenings in
  Events/TelemetryEvent.cs and that event's NI-to-NL projection in
  Events/TelemetrySerialization.cs; do not edit ProviderSettings, pool, adapter, client or config. Independent
  native tests use virtual time/readiness gates, not scheduler sleeps; establish caps,
  interval/RPM order, header parse/reserve/60s ceiling, concurrent Observe/read/dispatch,
  cancellation while queued, callback faults/no phantom dispatch and exact-once lease release. Gate: these
  tests and source lifetime/protocol reviews pass with no real HTTP or invented timing.
  > NOTE: Included in root's zero-warning 38/38 gate after wait-event/Infinity oracle and
  > nullable precision assertion corrections. ISO lexical parsing, Unicode separators,
  > Int64 telemetry and callback/permit behavior have review closure; no transport wiring.

- [x] **ACCT.3 — Shared accounting profile and independent observers.** Root owns
  specification/accounting-v1.md and verifier integration. 1e owns input-only
  tests/fixtures/accounting-v1/ plus tests/test_accounting_parity.py actual Python observer;
  04f owns native accounting/ledger/store tests; c708 owns RateLimiterTests and created
  AnyInfer.Accounting; cab owns its Program.cs expansion after the initial observer handoff.
  2ff owns the verifier script and its independent malformed-evidence controls.
  Root serializes solution/workspace/package manifest edits for the new project.
  Observers call production public APIs; no alternate calculator/router, expected-output
  lookup, second serializer, verdict table or cross-language implementation bridge.
  scripts/check_csharp_accounting.py orchestrates independent observations and verifies
  declared projections/error mappings; no numeric normalization may hide persistence
  spelling or unknown/zero differences. Gate: full input-only shared profile matches;
  include traps, ordered rounding discriminators, native range refusals and concurrent
  reservations. Profile notes distinguish unsupported later producers from tested helpers.
  > NOTE: Initial Python fixture smoke passes 1/1. Fourteen shared cases plus two explicit
  > native-only controls are authored. Source/corpus stamps and comparison pipeline are
  > being completed; broad vector gaps remain explicit. Native observer is registered in
  > AnyInfer.sln and restored. ACCT.4 may proceed after ACCT.1/2 while ACCT.3 is qualified.
  > NOTE: The first stamped comparison matched 12/14 shared cases and observed both native-only
  > boundaries. Two observer mappings required correction: a fabricated request output cap and an
  > extra limiter projection. Raw evidence is .tmp-tests/accounting/run-xg5ohpq9/report.json.
  > Updated verifier/Python observer controls pass 20/20; default CLI execution is still pending.
  > NOTE: After those observer-only corrections, all 14 shared cases match and both native-only
  > boundaries are observed in .tmp-tests/accounting/run-0avjtg4o/report.json. Root rebuilt only
  > the observer against the last coherent stamped SDK binary while client edits continued.
  > The broader corpus and fresh default orchestration remain required. Workspace wiring is
  > added after solution tests and before package validation; its runner tests pass 68/68.
  > NOTE: First expanded default orchestration builds a fresh stamped observer and matches
  > 40/42 shared cases, including exact decimal trap causes, subnormal pricing and reservation
  > operation order; both native-only boundaries are observed. The two remaining limiter
  > differences are observer JSON encoding of double values as integer lexemes. The native
  > observer will delegate double writing to the existing public JSON writer; verifier
  > comparisons remain strict. Evidence: .tmp-tests/accounting/run-90zajbuw/report.json.
  > NOTE: Fresh default orchestration now passes 42/42 shared cases and both native-only
  > controls, zero build warnings: .tmp-tests/accounting/run-1xhi3x62/report.json. Updated
  > verifier/Python observer tests pass 24/24 and Ruff is clean. Review closes after confirming
  > terminal envelope float notation is presentation; typed numeric values, money strings
  > and raw Store bytes retain their declared comparisons. No new public or friend API.

- [x] **ACCT.4 — Winning-result and explicit client integration.** Cab owns narrow
  Core/ProviderRegistry.cs TargetMetadata, Core/TargetMetadataResolver.cs,
  Core/GenerationCore.cs and Manifest/ManifestBuilder.cs changes after pure handoff;
  c708 owns AsyncClient.cs/Client.cs helper/ctor/ledger-cleanup and the narrow
  GenerationStream.cs close-release notification wiring. 04f owns new
  AccountingLifecycleTests.cs; 1e owns public builtin HTTP accounting fixtures/tests.
  Tests prove provider-cost authority, trusted/default/free/unknown pricing, retries,
  fallback and actual correction winning usage, result/completion/manifest agreement,
  ledger caller ownership/shared state, known-vs-unknown totals, raw-probe exclusion,
  inert budgeting/custom estimator/calibration and explicit facade post-close behavior,
  manual reservation release on OCE/close including never-started stream close,
  same-client callbacks, source/caller identity and no post-close commit. The focused
  tests also send overflowing winning input/output counts through the public result path,
  requiring OverflowException, no completion/charge and an incomplete manifest; explicit
  reported totals remain authoritative. Gate: focused
  native lifecycle/HTTP/profile tests plus unchanged 93-test conformance pass; source and
  lifetime reviews close. No automatic admission/spend/rate policy activation.
  > NOTE: Root's focused public integration controls pass 11/11 with zero warnings, and
  > conformance passes 93/93. Source and lifecycle reviews close. Exact decimal scale and
  > ordinary disposal exception expectations were corrected from Python/native authority;
  > the caller-cancellation race asserts token identity without imposing source-object order.
  > Separate shared-input builtin HTTP accounting controls are still being authored.
  > NOTE: The separate shared HTTP fixture now passes in both actual runtimes (one Python
  > and one native test covering success, discarded correction and retry/fallback winners).
  > Exact manifest money strings retain source scale; builtin wire assertions and response/
  > transport cleanup have protocol/lifetime review closure. No provider wire-cost field
  > is fabricated. All focused ACCT.4 gates are satisfied; full acceptance follows ACCT.6.

- [x] **ACCT.5 — Docs, examples and isolated consumer.** c16 owns bounded docs tabs,
  porting/reference updates, new compiled accounting examples and package consumer;
  exact file list is granted after rereading existing docs. Present pricing provenance,
  unknown counts, winning-request scope, explicit persistence and checked native widths.
  Demonstrate public budget, ledger, pricing and standalone limiter only. Never claim
  provider invoice totals, automatic policy admission, transport pacing, rich tool billing
  or cross-process transactional store semantics. Use the same compiled C# source in the
  site. Exact five-archive dependency/license/hash graph stays unchanged. Gate: source
  block consistency, compiled offline examples, focused package tests, strict docs and
  isolated package consumer pass with zero warnings.
  > NOTE: Root executed the compiled examples, strict docs build (15.3s), package/schema
  > controls (25/25), touched Ruff checks and isolated consumer. Both guides include the
  > same compiled accounting source; bounded scope claims have cold review closure.
  > .tmp-tests/sdk-five-accounting-package/run-hjqckf_k validates the exact five-archive
  > dependency graph and fresh consumer with zero warnings. This is working-tree evidence;
  > ACCT.7 still owns clean-revision proof and no package is published.

- [x] **ACCT.6 — Working-tree acceptance and source checkpoint.** Root runs one full
  workspace check with an isolated pytest cache, including new accounting verifier,
  native whole solution, frozen observations, Python/frontend invariants, strict docs,
  compiled examples and package consumer. Inspect final diff and independent bounded
  review closure; commit only explicit owned paths. Gate: complete required suite pass,
  no unresolved defect, frozen release hashes unchanged and source commit recorded.
  > NOTE: First full workspace gate passes 18/19 steps; its only failure is existing
  > ProviderSettingsTests.Caller_cancellation_of_a_late_factory_return_disposes_it_without_caching
  > (late adapter DisposeCalls expected 1, observed 0). Other native tests pass 523/524,
  > conformance 93/93, all Python/docs/profile/package gates pass. An isolated retry passes,
  > which does not close the possible parent-cancellation/factory handoff race. c708/ec8
  > are auditing that boundary and 04f the causal regression pattern before any checkpoint.
  > NOTE: Both audits confirm a real queued-proxy gap. A bounded prerequisite correction
  > is granted to c708 in ProviderPool, its GenerationCore call, StreamOperationLease and
  > AsyncStream forwarding: check ordered raw caller/iterator/close cancellation after a
  > factory successfully returns and before adopting its adapter. Await-dispose a cancelled
  > late result, retain original owned token and factory/source fault identity, and keep
  > Frozen/non-stream calls inert. 04f owns new LateFactoryCancellationTests.cs using the
  > real pool friend seam plus public iterator-only/close controls; no existing test weakens.
  > NOTE: The widened pool correction now checks ordered raw parents at every existing
  > pool-owned cancellation checkpoint, including gate wait and pre-factory preparation,
  > with no catch across resolver/factory/source awaits. Both independent reviews close;
  > focused late-factory/provider-settings controls pass 19/19 with zero warnings.
  > The second full gate again passes 18/19, including 42/42 shared accounting cases,
  > both native-only controls, 93 conformance tests, docs and isolated package consumption.
  > Its only failure is the old SyncClientTests result-not-ready assertion after TextDelta:
  > an ungated background pump can already have committed the PublicSdk result. The
  > accepted completion-callback readiness contract remains; 04f owns a terminal-gated
  > test correction in SyncClientTests.cs, retaining single-consumer and disposal checks.
  > Evidence: shell 1dc88909-9007-42f0-afaa-0cf12a165bab; native 529/530 before correction.
  > NOTE: That test correction has both review closures and passes the focused 42/42
  > sync/event lifecycle gate. The next full gate f7318546-cf5e-4af0-9207-b8ab0dfbc4dc
  > again passes 18/19, but its new direct-stream-close late-factory control exposes a
  > second queued-signal gap: BeginClose accepts disposal synchronously while the raw
  > close CTS is cancelled later by its worker. The pool must observe accepted close
  > intent before cache adoption, with an exact owned-cancellation classification so
  > its early OCE does not become a retained source-close fault. This prerequisite is
  > resolved by a bounded two-file marker/predicate correction under review; the strict
  > regression remains unchanged. Set lock-free close intent in both BeginCloseAsync and
  > NoteConsumerClosing before queued signalling. Supplier selection keeps caller/iterator/
  > close priority; classification matches any actually requested owned token, because
  > priority can change between throwing and catching. Retain unrelated source OCEs and
  > existing effective-token suppression; no CTS scheduling or Frozen behavior changes.
  > NOTE: Marker/predicate source and the two new causal regressions have both review
  > closures. The coordinated factory/provider-settings/sync/event/accounting lifecycle
  > gate passes 74/74 with zero warnings after a helper-only CS1998 correction. The new
  > full workspace run is f61da215-3fee-4581-ba54-5edb82b5538b; acceptance remains pending.
  > NOTE: That complete run passes all 19 steps in 127.8s: 532 native unit tests,
  > 93 conformance tests, 42 shared accounting observations and two separate native-only
  > boundaries, strict docs, compiled examples and isolated package consumption. All
  > bounded reviews close, compiler builds have zero warnings, and frozen observations/
  > released hashes are unchanged. The source checkpoint is the commit containing this
  > checked milestone; ACCT.7 records its exact hash and clean-revision proof next.

- [ ] **ACCT.7 — Clean-revision proof and handoff.** Root qualifies package/archive/
  dependency closure and fresh consumer from ACCT.6's exact clean source commit; does
  not publish or change version. Record commands/logs/counts and native profile limits;
  tick parent SDK.5b only after its gates actually pass. SDK.5c and broad root parity
  inventory stay unchecked. Gate: clean-revision consumer passes and exact SDK.5c resume
  point is written here and in the parent, with no active policy silently enabled.

## 6. Required adversarial vectors

Keep these causal; input fixture authors do not write expected values to fit output.

- Pricing: trusted/default/missing, missing input/output, explicit provider cost, free
  local zero, read<input/read==input/read>input, unknown/zero read and write rates,
  priced/unpriced/zero-use tools, map-order p28 discriminator, embedding input-vs-total,
  rerank SearchUnits, invalid/div0/overflow/underflow and concurrent culture isolation.
- Estimates/budgets: empty/30-byte/UTF-8 text, custom call order/JSON insertion order,
  4/message, multiplier1.5, invalid multiplier, envelope2x+50 floor unchanged, unpriced
  native wrapper, boolean sizing, default/trusted/unknown windows, headroom16384=>820,
  1000=>256, 1000000=>8192; reserve precedence, explicit negatives, planning-over/floor-under
  pass and floor-over trusted refusal; long overflow never wraps.
- Ledger: knownzero/null/nonfinite, labels and map snapshots, replacement rejection keeps
  previous, sum-then-subtract rounding order, concurrent reserve/record/release/reset,
  observer completion/failure, explicit client cancellation/early-close release and two
  clients sharing one state. Error partial-state behavior follows actual source order;
  do not advertise transactional rollback absent from Python.
- Store: exact bytes/decimal spellings, malformed/foreign/truncated file, per-bucket skip,
  unknown fields, checked native range, currency mismatch, 513th insertion and update-oldest,
  atomic readable replacement and cleanup failure. Do not test unsupported lossless
  cross-process RMW as a promise.
- Limiter: omitted/bare/inert distinction, comparison-only nonfinite edges, semaphore
  bound across held leases, queued cancellation and callback fault, RPM/min-gap competition,
  equal-delay reason, header missing-limit/reserve, partial updates, 429 observation as pure
  Observe input, 60s cumulative ceiling, supplied dialect case handling, unsupported response
  visibility and repeated read-only ObservedWaitS. Virtual time owns timing assertions.
- Real integration: raw unadvanced stream no work, winning retry/correction only, final
  CostUsd same across result/completion/manifest, partial manifests stay incomplete on
  OCE/close, no ledger disposal by client, no new native entry before ordinary generation,
  and preserved captured-sync/parent cancellation/source identity/cleanup rules from SDK.5a.

## 7. Resume and evidence

Current resume: **ACCT.7**. ACCT.0–6 are complete for their bounded gates.
The complete workspace gate passes all 19 steps in 127.8s under shell
f61da215-3fee-4581-ba54-5edb82b5538b, including 532 native unit tests, 93 conformance
tests, 42 shared accounting observations and two native-only controls, strict docs,
compiled examples and isolated package consumption. Compiler builds have zero warnings.
Shared-input builtin HTTP controls also pass in both runtimes. Clean-revision proof is next.
The winning-entry, tool-producer dependency and limiter clock/injection questions are
resolved in sections 2–4. Text codec is selected from actual observations and both cold
reviews are closed. Final accounting acceptance awaits clean-revision proof; no later
policy activation or publication is implied.
> NOTE: Cold math/protocol review identified the existing unchecked Usage.Normalized
> sum. Its minimal Models.cs change, direct tests and public winning-result overflow
> control were explicitly assigned; the pure checked change and direct controls now pass.
> NOTE: State/lifetime review added never-started stream reservation release, precise
> Waited callback-before-consumption ordering and same-instance store concurrency limits.
> Budget close semantics retain the actual Python async/sync distinction; the sync facade
> explicitly guards these helpers, so pure Resolve/Capabilities do not define their policy.
> NOTE: First root library compile passed with zero warnings after an ordinary parser-local
> rename. First focused runtime batch compiled: 25 passed, 3 failed; fixes are assigned for
> comparison-sign expectation, legitimate observed+waited event capture and Infinity overflow
> expectation. Root also observed actual Python Store raw CRLF on Windows that read_text
> normalized away; store/observer/literal-byte controls are being corrected explicitly.
> NOTE: Those failures and byte controls are corrected and reviewed; the revised batch
> passes. Observer envelopes bind runtime, compiled native source revision/dirty state
> and exact input SHA-256. Dirty development evidence is not clean-revision acceptance.
