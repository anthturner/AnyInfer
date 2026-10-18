# C# SDK generation probes and setup metadata

Resume from the first unchecked box. This child execution plan implements SDK.4c of
`ANYINFER_CSHARP_SDK.md`; it does not replace the parent scope or authorize publication.
The coordinator owns this plan, Git, shared manifests, and all build/test/package gates.

## 1. Baseline and dependency order

- Start at clean checkpoint `06353e21c59f8f3dca31b38c02752e5d214b5c7c` (SDK.4b accepted).
  Python behavior remains pinned by the parent plan; inspect actual source, not illustrative
  DESIGN signatures. Preserve Python, all frozen v0 inputs/observations and released hashes.
- Model listing/health, descriptor capabilities and pure query assembly already exist.
  SDK.4c completes declarative setup metadata and explicit **generation** capability probes.
- The default feature sequence is exactly `JsonSchema, JsonMode, Tools, Streaming`.
  Probeable features additionally include `Grammar`. Never reduce the default or report
  tools unsupported merely because the SDK has not implemented its transport.
- Pull forward the minimal **raw adapter tool protocol** prerequisite from SDK.7a:
  immutable declarations, raw wire tools/choice and decoded tool fragments. Do not add
  GenerationRequest tools, rich messages, public tool StreamEvents, assembly of tool calls,
  execution, or tool loops in this prerequisite. SDK.7a/7b remain unchecked.
- Token estimators/counting/prewarm remain SDK.5/11; embedding/rerank operations and their
  probes remain SDK.6. Record these dependencies explicitly instead of claiming that a
  generation probe implements them. Do not invent richer OpenAI model-list facts.

## 2. Setup metadata contract (independent of probe execution)

Reference `src/python/anyinfer/registry.py` SetupField, HostShorthand, ProviderSetupSpec.
Own `src/csharp/AnyInfer/Providers/ProviderSetupSpec.cs` plus new
`src/csharp/AnyInfer.Tests/ProviderSetupTests.cs`; no other runtime or test files.

- Retain SetupField's existing optional argument order and known kind validation.
  Normalize omitted/null optional descriptive strings to empty strings, including
  HelpText, Placeholder, EnvVar and DefaultValue. Empty default means no default and must
  not require advanced=true; empty EnvVar means no hint. Nonempty defaults retain the
  existing advanced/choice checks. Preserve immutable choices and prior collision checks.
- Add public immutable `HostShorthand(string scheme, int defaultPort)` with Scheme,
  DefaultPort and `Expand(string host)`. Match the actual Python trim/contains-`://`/
  colon-before-first-slash/string concatenation algorithm exactly. No DNS, sockets,
  environment lookup, URI rewriting, or new implicit expansion in config/client code.
- ProviderSetupSpec appends `HostShorthand? hostShorthand = null`,
  `IEnumerable<IEnumerable<string>>? anyOf = null`, `string requirementNote = ""` after
  fields/modelSelection. ModelSelection defaults to `"discover-or-manual"`; accept only
  that spelling and `"manual-only"`. Existing builtin can use its real explicit listing.
- Expose immutable HostShorthand, AnyOf (copy outer and inner sequences), RequirementNote,
  EssentialFields and AdvancedFields preserving field order. Add
  `UnsatisfiedGroups(IReadOnlyDictionary<string,string> values)` using nonblank values and
  `LabelFor(string key)` with exact ordinal key lookup/fallback.
- Preserve existing duplicate-field rejection. Reject advanced fields that occur in AnyOf
  groups, like Python. Do not add rejection of empty/unknown-key groups that Python does
  not impose, or make declarative metadata execute runtime credential policy.
- XML-document every new public type/member. Tests cover defaults, modes, nested snapshots,
  visible groups/labels, advanced-group refusal and literal shorthand expansion, including
  full URLs, explicit ports, trimming and the baseline path concatenation behavior.
  Integration: Core/ProviderRegistry.cs must test nonempty DefaultValue, rather than
  non-null, before supplying an advanced default. No other production default/env/help
  presence consumer was found in the bounded audit.

## 3. Raw tool protocol prerequisite

Reference Python `types/requests.py` ToolSpec/ToolAnnotations, `providers/base.py`
function-tool encoding, and `providers/openai_compat.py` tool-choice/delta decoding.

- Root `ToolAnnotations(string? title = null, bool? readOnly = null,
  bool? destructive = null, bool? idempotent = null, bool? openWorld = null)` is immutable;
  `Stated` means at least one non-null value (false and empty title count). These hints
  are untrusted metadata and confer no permissions.
- Root `ToolSpec(string name, string description, JsonObject parameters,
  ToolAnnotations? annotations = null)` exposes immutable properties, with empty default
  annotations. Tagged JSON is already immutable. Do not validate the argument schema or
  match a named tool choice eagerly. Normal native null guards apply.
- Append `IEnumerable<ToolSpec>? tools = null, string toolChoice = "auto"` after all current
  **public** WireRequest constructor arguments; copy the sequence. Thread matching args
  through the internal constructor without changing the existing schema-profile marker.
- Reject non-auto choice with an empty tools sequence; it cannot be accepted then omitted.
  A nonempty Tools snapshot independently enables raw tool encoding and decoding.
  `UsesModernSchema` remains exclusively the existing schema-profile flag.
- `AdapterToolCallDelta(int Index, string? CallId, string? Name,
  string ArgumentsFragment) : AdapterEvent` is raw provider output, not a StreamEvent.
- OpenAI payload encodes `{type:function,function:{name,description,parameters}}` and
  tool_choice strings auto/none/required, otherwise specific-name function object. Emit
  these fields only for nonempty tools. Annotations are not sent in this dialect.
- Buffered and SSE decoding only emits tool deltas for tool-enabled raw requests. Preserve
  text->tool deltas->usage->final order. Follow the existing Python list/mapping/string
  coercion rules, position fallback for missing/noninteger index, null id/name and empty
  argument fragment; do not assemble arguments or synthesize final ToolCall objects.
  Native Index is signed 32-bit: preserve Python's boolean integer branch as 1/0; an
  explicit integer outside native range is a value-free, instance-attributed nonretryable
  StreamProtocolException, never a fabricated positional identity. Tool-enabled payloads
  use the modern tagged-JSON writer even when the legacy schema-profile marker is false;
  no-tools frozen payloads retain their existing writer.
- Default/frozen requests retain existing bytes and events, including ignoring unsolicited
  tool fields. No change to normal generation, frozen parser, schema projection, timing,
  routing, retry, response bounds, SSE termination, native error mapping or cleanup.
- A forced `grammar` schema on the modern SDK/probe path cannot be translated by the
  generic OpenAI adapter: reject in CreatePayload before HTTP as instance-attributed,
  nonretryable UnsupportedInputException. Apply this only when UsesModernSchema=true;
  frozen-v0 grammar selection/codec behavior stays unchanged. Custom raw adapters still
  receive the forced mechanism/schema. Do not invent a generic grammar wire field.
- Independent real builtin-factory HTTP controls must cover exact request fields, named
  choice, buffered tool-only content, fragmented SSE deltas, malformed entries and preserved
  default/frozen behavior. Update the existing contract's C# coverage note without changing
  last-verified/upstream claims.

## 4. Probe API and execution handoff (contract closure required before authoring)

The following source-backed behavior is settled; remaining mechanism details must be
closed by the bounded contract/lifetime review and recorded here before implementation.

- New immutable Capabilities `ProbeOutcome`, `FeatureProbe`, `ProbeReport` mirror Python
  outcomes, ordered results, resolved target, nullable measured capabilities, request count,
  usage, OutcomeFor and summary. Helpers expose the literal probeable/default sequences,
  64-token ceiling, schema/tool prompts, forced mechanism and conclusive-bit merge.
- Exact public value API, in new `Capabilities/Probes.cs`:
  `enum ProbeOutcome { Supported, Unsupported, Inconclusive }`;
  `FeatureProbe(Feature feature, ProbeOutcome outcome, string detail = "")` with get-only
  Feature/Outcome/Detail/Conclusive; `ProbeReport(ResolvedTarget target,
  IEnumerable<FeatureProbe>? probes = null, ModelCapabilities? capabilities = null,
  int requests = 0, Usage? usage = null)` with copied Probes, Target/Capabilities/Requests/
  Usage, nullable `OutcomeFor(Feature)` (first matching probe) and Summary. Summary uses
  native C# enum names while retaining Python's ordered supports/does-not-support/
  nothing-conclusive structure. No all-inconclusive bit is named as a conclusion.
- Static public `CapabilityProbes` exposes immutable ProbeableFeatures and
  DefaultProbeFeatures, const ProbeMaxOutputTokens=64, JsonObject ProbeSchema, ToolSpec
  ProbeTool, `string? MechanismFor(Feature)`, `string ProbePrompt(Feature)` and
  `Sourced<Feature>? ProbedFeatures(Sourced<Feature>? known, IEnumerable<FeatureProbe> probes)`.
  Literal schema/tool/prompt values come from Python capabilities/probes.py. Preserve
  nullable/false annotations, no mutable shared collection, no schema validation or I/O.
- Planned native calls are AsyncClient.ProbeAsync / Client.Probe with target, nullable
  ordered features, timeoutS=30, record=true and CancellationToken. Preserve caller order
  and duplicate/empty selection behavior from the actual Python loop.
  Exact signatures are `Task<ProbeReport> ProbeAsync(string target,
  IEnumerable<Feature>? features = null, double timeoutS = 30, bool record = true,
  CancellationToken cancellationToken = default)` and synchronous `ProbeReport Probe`
  with matching argument names/order. Empty selection resolves/acquires an adapter but
  calls Generate zero times; duplicates repeat in supplied order, and later conclusive
  duplicate outcomes win their own bit. Invalid/nonprobeable selections reject before
  pool acquisition, after pure target resolution as in Python.
- Validate feature choices before pool acquisition. Resolve exactly one alias-aware target;
  use the concrete instance/model for acquisition and recording. No router, health gate,
  retry, repair, fallback or generation-attempt telemetry. Force the mechanism being tested,
  temperature=0 and maxOutputTokens=64; streaming only for the streaming probe.
- Tools require an actual decoded tool delta. Streaming requires more than one content
  event. JSON mode requires extracted JSON; schema/grammar require probe schema conformance.
  Accepted wrong output/owned timeout is inconclusive. Provider errors thrown during the
  raw feature call yield unsupported, as Python; acquisition and arbitrary source errors
  retain identity and record nothing.
- Actual Python `Usage.merge` overlays later known fields; the probe loop calls merge both
  within and across features. Preserve that observed behavior and normalization here;
  do not implement addition merely because ProbeReport's prose says "summed". Broader
  billing fields/accounting are assigned to SDK.5.
  Return raw per-feature usage; derive Total once only after all features are overlaid.
  Deriving an early total would retain a stale value when a later feature reports only
  input or output. Control: input2/output3 then input7/no output => final total10.
- Merge conclusive results into current known features, preserving untested bits; record
  one Probed record only after the run finishes successfully and record=true. Override
  remains outermost. Inconclusive-only runs do not change the store.
- Reuse/generalize the existing owned lifecycle reservation, including full callback scope,
  original caller identity, off-lock signal-all/join cleanup and self-disposal refusal.
  No token-ignoring late success can publish report/store. No timeout may abandon an owned
  adapter iterator or dispose resources while its cancellation callbacks are still running.

### Owned execution and publication

- The client reserves/tracks one operation under its existing gate before target resolution,
  caller feature enumeration, materialization, factories or callbacks; owner async/captured
  Client and effective-to-original token scopes span acquisition, iteration, disposal and
  commit. Sync uses the existing RunOperation boundary. Preserve lifecycle/generation close
  signal-all-before-join and late factory cleanup; no new background inference task.
- Resolve metadata first, then snapshot/validate feature selection, then refuse a descriptor
  explicitly lacking Generation before factory acquisition. Prebuilt IProviderAdapter is
  generation evidence when no descriptor exists. Acquire once even for an empty selection;
  run the selected features sequentially and return only after every owned iterator closes.
- The raw runner reuses RequestNormalizer.CreateWireRequest with a synthetic NormalizedRequest
  and forced StructuredOutputProfile. Append optional tools/toolChoice only to that internal
  wire-builder helper; normal generation calls retain empty defaults. Do not create another
  schema prompt renderer or mechanism ladder. Fixed probe schema uses name capability_probe.
- Capture raw text/tool content events, adapter usage and final usage; content-event count
  includes empty text and tool fragments, like Python's isinstance-based is_content_event.
  Held ProviderException conversion is limited to Generate/GetAsyncEnumerator/MoveNext.
  Iterator DisposeAsync is outside that conversion, so cleanup faults retain exact identity.
  A held ProviderException remains Unsupported even if the adapter suppressed deadline
  cancellation before raising it; an expired timer cannot replace an actual provider error.
- Each FeatureLease owns an effective cancellation token and a finite per-feature timer.
  Owned timeout becomes Inconclusive only for an OCE bearing that exact feature token, after
  iterator and timer cleanup, while original caller/operation cancellation is absent. All
  other source OCEs/failures remain unchanged. A cleanup or cancellation-callback fault wins
  over a held timeout. A token-ignoring late successful return after timeout is inconclusive,
  and caller/close cancellation still prevents report/store publication.
- Actual timeout and parent-cancellation signaling must execute under the owner async and
  captured Client context, including UnsafeRegister. Gate-publish one shared signal task;
  finalization stops new initiation and joins all published work before CTS disposal. No
  cancellation callbacks execute under client/store locks. The exact proxy-linkage shape is
  under final mechanism review; do not rely on ExecutionContext flowing through a timer.
- Final report/store publication linearizes under AsyncClient._gate after an owned
  cancellation check. If close marked first, leave the lock, await the reservation's shared
  cancellation signal and throw owned original/effective cancellation; publish nothing.
- CapabilityStore adds one store-gated merge/optional-record method: read latest assembled
  facts, apply only this run's conclusive bits, record once when requested, return the
  measured snapshot. Do not compose separate CapabilitiesFor + RecordProbe calls, which
  could erase another completed partial probe. record=false reads/merges without writing.
  Match Python's _capabilities_for input: latest known features include application
  overrides. Only the resulting feature measurement is stored/returned, never copied
  pricing/discovery/default records; all-inconclusive reports contain null capabilities.
  When latest Features is the unknown None@Default sentinel, seed only legacy profile
  Grammar/JsonSchema/JsonMode bits before the conclusive merge, so a streaming-only probe
  cannot erase an untested legacy schema claim. Stronger modern facts, including Probed
  None, never receive that fallback. The report contains the measured record; an outer
  configured override can still deliberately win in subsequent assembled capabilities.
- Connect measured features to later normal **PublicSdk** generation through the existing
  TargetMetadataResolver. Resolve both explicit-colon and catalog targets using existing
  logic first, then assemble facts using descriptor/concrete instance/model/effective locality.
  Replace all three StructuredOutputProfile flags when Features is not exactly None@Default.
  That sentinel retains legacy descriptor/registration profiles; Probed None clears them.
  Pricing-only records must not erase a legacy profile. FrozenV0 returns before any store
  lookup. Wire the optional store into both public settings and FromAdapters construction.
  This is one existing selector/wire builder, not a second router or profile API.

Final mechanism pin is closed: FeatureLease owns one effective CTS, with owner-proxied
logical linkage. Parent registration and timer callbacks only gate-publish the same
one-shot signal Task; they never synchronously invoke adapter callbacks or wait on them.
SignalCore pushes AsyncExecutionContext, captured SyncExecutionContext and
CancellationIdentityContext(feature token, original caller token) before actual Cancel.
Finalization gates off new signal initiation, joins timer disposal, parent registration
disposal and any published signal, then disposes CTS. Keep the feature token cached so
identity remains inspectable after cleanup. An actual source cleanup/signal fault wins
over a held timeout, while all cleanup is still joined.
Timeout origin is set only after winning gate admission; a timer rejected during
finalization cannot change a completed result. Builtin modern HTTP send/open/body/SSE
awaits restore caller identity narrowly for actual effective-token cancellation; cleanup,
custom adapter OCEs and frozen HTTP behavior remain outside that mapping.

An owned feature cancellation-signal fault must also be retained by its parent lifecycle
reservation. The runner passes a reservation-local `Action<Exception>` sink into the lease;
only actual SignalCore cancellation-callback failures use it. After joining operation
Completion, client close reads those retained faults, finishes adapter cleanup and rethrows
the first exact fault. Completed operations leave no historical client fault. Ordinary
adapter/iteration failures are never reported through this sink. Lease finalization awaits
its published signal unconditionally even if earlier cleanup already failed.

Custom adapter cancellation exceptions remain source exceptions, including a cooperative
await's OCE carrying the feature token. Tests assert that exact object/token. Original
public token checks belong to owned post-success checkpoints and builtin HTTP boundaries;
there is no universal raw-adapter OCE rewrite.

Native close diagnostics additionally pin the shared ownership boundaries: a Collect call
already active when close wins reports owned cancellation if no terminal result exists;
a new Collect call after close retains established readiness behavior. Cache close-token
identity before CTS disposal. The private managed iterator semaphore remains valid for
late/queued pulls, which may still release it after close; no kernel handle is created.
Lifecycle success checkpoints synchronize the client close mark with the shared
reservation signal outside locks before dispatch/result processing. Final Models discovery
and Health publication linearize under the client gate. A privately acquired late adapter
may be owned solely for exactly-once teardown, with no use or public fact after close.
Actual source failures remain outside these success-only checks.

Native timeoutS must be positive/finite and fit the managed timer's finite due-time range
(at most `(uint.MaxValue - 1) / 1000d` seconds); validate before pool acquisition. The
deadline is cooperative, with owned cleanup joined even if an adapter ignores its token.

The disjoint runner API is fixed:
`internal static Task<(FeatureProbe Probe, Usage Usage)> CapabilityProbeRunner.RunAsync(
IProviderAdapter adapter, ResolvedProvider resolved, Feature feature, double timeoutS,
AsyncClient owner, Client? syncOwner, CancellationToken operationToken,
CancellationToken callerIdentity, Action<Exception> onSignalFailure)` in Core/CapabilityProbeRunner.cs, with a private/internal
FeatureLease helper in Internal/ProbeFeatureLease.cs. Only the runner owner edits these
and the optional tools tail in RequestNormalizer.CreateWireRequest. Client/store/resolver
integration belongs to the separate runtime owner; no compiler gate on an incomplete wave.

## 5. Checklist and disjoint waves

- [x] **PRB.0** Close raw tool prerequisite and probe contract/mechanism reviews. Gate:
  exact saved handoff, source-backed outcomes/usage/grammar and original-token/timeout/
  cleanup/publication rules, no new user-facing product choice silently inferred.
  > NOTE: Cold contract and lifetime reviews close raw tools/profile isolation, exact
  > defaults/usage/sequence behavior, modern grammar refusal, owned timer/parent proxy,
  > cancellation identity, cleanup and atomic latest-fact publication. Review artifacts:
  > csharp-sdk/sdk-four-tools-translation-contract-review and
  > foundation-execution/csharp-sdk/sdk-four-probe-mechanism-review.
- [x] **PRB.1** Complete setup metadata in the two paths from section 2. Gate: cold source
  review, zero-warning guarded build and focused ProviderSetupTests; declarative inertness.
  > NOTE: Source review is clean; integration checks nonempty default. All 18 combined
  > setup/tool targeted tests pass, including colon-before/after-first-slash controls.
- [x] **PRB.2** Implement raw tool values/WireRequest and adapter translation in disjoint
  leases, then independent HTTP tests. Gate: saved API agreement, cold review, zero-warning
  build, targeted protocol tests and unchanged frozen conformance.
  > NOTE: Guarded Release library build has zero warnings/errors; all 18 combined
  > targeted tests and 93 native conformance tests pass. An instance/static compiler
  > mechanic and test method-name/JSON-escape/null-exception mechanics were corrected
  > without relaxing assertions or changing frozen inputs/observations.
- [x] **PRB.3** Implement probe values/helpers and direct async execution/sync mirror with
  reviewed reservation ownership. Gate: saved coherent API/runtime handoff, source and
  independent lifetime review before dependent native test authoring.
  > NOTE: Both disjoint runtime halves and modern HTTP identity integration are saved;
  > guarded Release library compilation passes with zero warnings/errors. Source
  > rereviews and complete independent test snapshots remain the next gate. Prior review
  > corrections preserve nullable/no-publication inconclusive reports, feature-only
  > recording, full latest known flags, final-only usage normalization and unconditional
  > cancellation-resource cleanup; no frozen/Python source was changed.
  > Final joint contract/lifetime reviews close the owned child-signal sink and complete
  > cleanup ordering. The coherent focused suite passes all 24 native probe cases.
- [x] **PRB.4** Add shared input-only probe fixture/Python bridge and independent native
  tests. Gate: literal defaults, direct instance/no fallback, conclusive recording/layers,
  usage overlays, timeout/caller/close/OCE identity, self-dispose and inertness controls.
  > NOTE: The input-only OpenAI fixture and independent Python public-API replay are saved;
  > Ruff/py_compile and the focused replay pass. The replay covers default four, real tool
  > and SSE payloads, empty acquisition, duplicates, record=false, inconclusive and usage
  > overlays. Python compare readiness performs three explicit credential resolutions
  > without factories/sends; the test distinguishes these from five pool acquisitions.
  > Native helper tests are saved; native execution/HTTP tests await coherent PRB.3 runtime.
  > Runtime and native snapshots are now coherent. The first focused execution compiled
  > after three bounded test mechanics and passed 21/24 cases. The HTTP header oracle is
  > corrected; two cancellation controls remain under causal triage before acceptance.
  > Triage distinguishes source OCE preservation from owned original-token checks. The
  > custom-adapter oracle is being corrected; an actual feature-signal failure reporting
  > gap is being fixed through the reservation-local sink described above. The sentinel
  > test will prove callback entry and fault retention in both probe and close paths.
  > Final acceptance of this focused slice supersedes those intermediate holds: all 24
  > native cases pass, including exact source OCE identity, callback entry, close/pending
  > sentinel retention, feature-token disposal and original-caller builtin HTTP boundaries.
  > Both independent reviewers close the causal/lifetime controls. Ruff and all 21 focused
  > Python bridge/package tests also pass; the full workspace checkpoint remains PRB.6.
- [x] **PRB.5** Add compiled source-linked opt-in probe/setup example and public-only
  isolated package consumer. Gate: exact rendered source, actual HTTP/default-four calls,
  metadata/result/provenance and exactly-once cleanup; no dependency graph/payload drift.
  > NOTE: Compiled offline examples pass. After correcting embedded C# JSON literal
  > mechanics, the actual isolated archive/restore/build/run succeeds at
  > `.tmp-tests/nuget/run-ygv1wntt/`; this is working-tree evidence, not a clean-revision proof.
  > Exact rendered-source verification remains part of the final workspace gate.
  > Rendered verification now passes: all 19 C# blocks across six guide pages equal the
  > 12 compiled source files. Offline examples and the isolated consumer pass in the
  > workspace run as well. No dependency or payload allowance was broadened.
- [ ] **PRB.6** Run full workspace/package/frozen gates, reconcile parent/inventory scope,
  commit explicit paths and qualify clean revision. Gate: clean native/package evidence,
  remaining SDK.5/6/7/11 dependencies explicit and no release/publication claim.
  > NOTE: First complete run passed 17/18 steps, including 93 conformance tests, strict
  > docs, isolated package and examples. The only failure was a self-dispose test's
  > UnsafeRegister-before-delay cancellation race. The helper ordering correction and
  > final full rerun remain; no acceptance is inferred from the other passing steps.
  > The exact helper ordering correction has both causal/lifetime review closures and
  > passes 10/10 repeated Debug executions. Final workspace rerun:
  > `3b246379-c50c-44a9-bb2d-667580edfe32` (in progress).
  > That workspace rerun was stopped after native unit execution stalled; 93 conformance
  > cases had passed. Eleven subsequent 385-case unit runs with hang diagnostics pass.
  > Parallel solution diagnostics then expose an existing late-factory-close race:
  > active buffered generation can reach unavailable Result after close instead of OCE
  > (`.tmp-tests/probe-solution-hang-2.log`). A narrow owned buffered cancellation
  > checkpoint is assigned to c708, with cold lifetime review before retry. Keep manual
  > iterator close behavior and actual source exception identity; do not relax the oracle.
  > Further parallel diagnostics (`probe-solution-close-fix-1.log`) identify a pending
  > pull releasing an already disposed iterator semaphore and lifecycle late-success
  > completion beating queued close cancellation. The buffered checkpoint is restricted
  > to Collect calls active before close; new post-close Collect calls retain established
  > readiness behavior. Cache the close token before CTS disposal, retain the private
  > managed iterator gate for late pulls, and review the lifecycle close-linearization
  > correction before another full gate. These are required native ownership corrections,
  > not added SDK feature scope.
  > Those corrections are saved. Three repeated parallel solution runs now each pass
  > 386 native unit and 93 conformance cases with hang diagnostics. Final complete gate:
  > `d7e0fd10-6c0b-4222-8d64-56ddf5530746` (in progress); source reviews and the
  > clean-revision package proof still precede acceptance.
  > Final complete gate passes all 18 steps in 117.8s: 386 unit and 93 conformance
  > cases, strict docs, isolated package and offline examples. Root rechecked all 19
  > rendered source blocks and the unchanged frozen manifest/report digests. Source
  > review closure, explicit commit and clean-revision package qualification remain.
  > Final contract and lifetime artifacts close the active-collection, managed-gate and
  > close-linearized lifecycle/probe checkpoints with no residual static finding. Root
  > inspected both final closures against the passing snapshot; proceed to source commit
  > and clean-revision package qualification.

## 6. Resume log

Resume PRB.6 at explicit source commit and clean-revision
package qualification. The complete workspace passes all 18 steps, including 386 unit
and 93 conformance cases. Repeated parallel native runs, independent Python replay,
examples, rendered source, released hashes and working-tree package consumption pass.
Check SDK.4c only after the clean revision qualifies. No publication is authorized.
