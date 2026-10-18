# C# SDK typed events and manifests

Resume from the first unchecked box. This child plan executes SDK.5a of
`ANYINFER_CSHARP_SDK.md`, including the minimum monetary value foundation needed by
the complete Usage/event/manifest shapes. It does not complete SDK.5b accounting or
SDK.5c request policies. The coordinator owns Git and all shared execution gates.

## 1. Baseline, authorization and scope

The user authorized the full Python-aligned SDK, a plan followed by implementation,
normal C# conventions, compiled source-linked documentation and independent native
proof. Continue that authorization; do not introduce a new publication or release step.

Start from clean acceptance HEAD `1affab3ed9baf147907f464c178e752534d361d2`.
SDK.4c source is `0fd3fb47cd08295537674aa23571dffcc9482888`. Parent SDK.5a is the
first unchecked milestone. Read the parent plan, AGENTS.md and DESIGN.md's event,
manifest and ownership rules before implementation. Actual Python source is the
behavioral authority; illustrative architecture signatures are not substitutes.

Deliver typed telemetry, per-observer privacy, inline dispatch, opt-in sinks, immutable
partial/final manifests, version-1 serialization/schema/rendering and generation-path
producers. Preserve the existing router, schemas/repair, lazy async path, sync facade,
source exception identities, close linearization and all 102 frozen observations.
`OperationCapture` remains private proof instrumentation; it is not a telemetry source.

No release, registry upload, version bump, extra runtime, Python execution inside the
SDK, or official provider SDK is authorized. Probes retain their accepted direct raw
execution and do not acquire normal generation attempt telemetry/manifests.

## 2. Settled technical decisions

### Numeric values needed by complete Usage shapes

- Select exact native `PeterO.Numbers [1.8.2]` as the decimal implementation. Its actual
  archive is 602245 bytes, CC0-1.0, with no declared dependencies; net8 isolated restore
  selected only `PeterO.Numbers/1.8.2`. The repository signature verifies with the pinned
  SDK. Tag `v1.8.2` resolves to `26b7571292aca5037430227a223dac1702b43b80`.
  This is package/signature/tag-metadata evidence, not reproducible binary/source proof.
- Expose immutable `PeterO.Numbers.EDecimal` as the counterpart to Python's
  `decimal.Decimal` in Pricing and Usage money fields. Do not add a second numeric
  wrapper, decimal/double overloads, implicit float conversions or JSON-number money.
  The unpublished API may migrate; migrate every caller in the same source wave.
- Construction from valid decimal text is exact without rounding. Owned accounting
  arithmetic uses one immutable, flag-free context: precision 28 significant digits,
  HalfEven, Emin=-999999, Emax=999999, exponent clamp false, traps for Invalid,
  DivideByZero and Overflow. Never mutate ambient/global arithmetic settings or share
  mutable flag-recording contexts. This pins the Python default-context baseline;
  it does not emulate a Python host changing its ambient Decimal context.
- Retain each Python arithmetic boundary and operation order. Generation pricing is
  `(tokens / 1_000_000) * rate`. Native `ETrapException` signal categories are the
  documented counterparts to Python decimal traps; do not blanket-wrap callback,
  factory, parser or provider arithmetic exceptions as owned accounting errors.
- Use numeric decimal equality/hash for SDK records/maps, including `1.0` versus
  `1.00` and signed zeros; representation equality is insufficient. Qualify nonfinite
  values separately and preserve supplied known values, never turn them into null/zero.
  Do not impose new finite/nonnegative constructor or ledger rules absent in Python.
  Keep validation at actual source boundaries: negative catalog rates and negative
  spend ceilings reject where Python rejects them.
- Append Usage `CostUsd`, `SearchUnits`, `ServerToolUses` after its existing six token
  fields. Snapshot maps with ordinal keys. Currency belongs to Pricing/CostEstimate/
  ledger, not Usage. Reported costs remain authoritative when later SDK.5b adds pricing.
- Port pure Usage.Normalized/Merge/Sum now so event/sink/manifest values have one model.
  Normalized derives total only when both components exist; Merge overlays later known
  fields; Sum keeps a dimension unknown when any component is unknown. This does not
  switch the frozen route's current attempt aggregation to the new accounting profile.
  Pin the source's non-obvious map behavior: Normalized preserves ServerToolUses;
  Merge and Sum currently construct new Usage without that argument, so their result
  has an empty map. Preserve that baseline rather than inventing a per-key merge/sum.
  Direct Usage equality/hash includes the map by ordinal key/value, independent of
  insertion order. Events/sinks serialize it, but format-1 UsageFacet has SearchUnits
  and no ServerToolUses field; do not add one to the manifest schema implicitly.
  On PublicSdk adapter-usage boundaries, carry the newly admitted reported CostUsd and
  SearchUnits through the existing later-known overlay to result/events; do not drop
  known values merely because automatic pricing remains SDK.5b. Pin server-tool map
  behavior to the actual Python helper used at each boundary. Frozen six-field projection
  and retry/repair aggregate accounting remain unchanged; no new computed cost is added.

Root qualification records 28 numeric mechanism observations, one input-only fact,
one intentional System.Decimal overflow contrast, and 24 mixed precision/rounding/
culture observations. Native/Python numeric text, signs, trap categories and flags
agree. The real operation-order discriminator uses counts outside the current long
token-count domain; it proves the rounding-order rule, not new count-range support.
Production equality, string persistence and true Usage/core unknown handling remain
required gates rather than inferred from this library probe.

### One native JSON traversal with explicit manifest policies

- Extend `Json/JsonWriter.cs` with private policy data over the same traversal. Preserve
  public frozen Write/WriteCanonical and existing modern schema/wire writers exactly.
- Add internal compact, sorted, ASCII-escaped manifest-digest output with no separator
  whitespace, arbitrary JsonInteger values, finite JsonNumber values and Python float
  spelling. Apply fixed notation only for scientific exponent -4 <= e < 16; otherwise
  lowercase e, explicit sign and at least two exponent digits. Preserve signed zero and
  integer-versus-floating type. Ignore a JsonNumber source lexeme for digest output.
- Sort string keys by Unicode scalar value, with proper-prefix ordering. Escape ASCII
  controls, quote/backslash and every unit >= U+007F using lowercase escapes. The native
  JSON domain remains finite-number and valid-surrogate text; do not silently broaden
  other writer modes to accept nonfinite values or malformed Unicode.
- Add an internal manifest JSON policy for sorted ASCII output with Python-compatible
  pretty indentation, and default separators when indent is null. Digest separators
  and ToJson(indent:null) separators are distinct. Integer indentation <=0 means
  newlines without indentation, matching Python's integer-indent behavior.
- The independent scratch candidate's expanded 4122 records matched: 4117 finite JSON
  byte/digest observations and five separate nonfinite records. This only qualifies a
  candidate algorithm. Direct native JsonObject/JsonInteger/JsonNumber/JsonString
  production-route tests must pass before declaring the writer qualified.

### Typed telemetry and privacy

- Put telemetry under `AnyInfer.Events`: an abstract TelemetryEvent family and the
  23 Python event concepts, using native type-safe fields and immutable snapshots.
  Port source field names/defaults from `events/telemetry.py:53-562`; use ordinary
  PascalCase APIs and snake_case serialized members. Do not invent producer facts.
- Preserve RequestStarted.PromptText, RepairAttempted.RawText and
  RequestCompleted.ResponseText as the only event payload fields. Strip them separately
  per subscription. A payload opt-in for one observer never exposes them to siblings.
  Credential-shaped data always follows existing redaction; sink errors and warnings
  must not serialize unbounded observer exceptions or raw request/provider options.
  Event payload construction is needed when dispatcher.WantsPayloads is true. Private
  manifest capture is independently needed when a builder exists and manifestPayloads
  is true, even with no observers. Feed/redact those private facts before fanout; do not
  rely on an observer's payload event to populate the manifest. Disabled manifests
  capture no manifest payload despite a true client manifestPayloads setting. Test all
  four observer-payload/manifest-payload combinations with ordinary sibling observers.
  > NOTE: Preserve the actual Python generation builder's current payload multiplicity:
  > each repair is explicitly noted before emission, and a payload-bearing RepairAttempted
  > is noted again during the fold. RepairTexts therefore has 0/1/0/2 entries per repair
  > for manifest/observer payload opt-ins FF/TF/FT/TT. This source behavior is intentional
  > compatibility here, not a new deduplication policy. Generation's builder also leaves
  > UsageFacet.SearchUnits null, although reported Usage/result/events retain SearchUnits;
  > the later operation builder supplies that facet field. Test these boundaries directly.
- Public `IObserver.OnEvent(TelemetryEvent)` is synchronous. EventDispatcher snapshots
  subscriptions under its lock and invokes outside it. Subscribe appends duplicates;
  Unsubscribe removes all reference-identical subscriptions; unknown is a no-op.
  Reentrant changes affect later emissions. Atomically claim warn-once per subscription.
  Callback exceptions are isolated; warnings are best-effort bounded/redacted diagnostics.
- LoggingObserver uses BCL TraceSource/TraceEventType, with a documented native logging
  mapping and no logging dependency. JsonlObserver opens only when explicitly created,
  appends locked JSONL, optionally flushes each event (default true), and is caller-owned.
  Client disposal must not dispose shared caller observers. No default disk/network I/O.
  Apply restrictive file mode where supported; do not promise Windows ACL privacy.
  The native logging-level parameter accepts defined TraceEventType values and rejects
  undefined enum values at construction; it does not expose Python's custom integer levels.
- Dispatch stays inside actual AsyncExecutionContext and captured SyncExecutionContext
  scopes. Same-client disposal from an observer must refuse before state mutation.
  Inline callbacks consume caller time; do not add queues/background dispatch to hide it.
  PublicSdk also refuses same-stream disposal from that stream's active owned execution,
  including observer, adapter cleanup and cancellation callbacks, before any close mutation.
  Track exact stream identity so unrelated stream/external disposal remains allowed.
  Parent cancellation only publishes a shared signal; actual adapter-visible child CTS
  cancellation runs under stream/client/caller-identity scopes. Join registrations and
  the published signal before disposing the source. Keep frozen cancellation unchanged.
  The pull-serialization lease remains held during inline execution so external close
  joins the callback and native pull; state locks never surround observer fanout.
  Public SyncStream disposal after its client has joined and selected that stream's close
  failure as the reported parent outcome is complete. Record this handoff only
  after the parent's actual close await/catch, never from a canceled lifetime token.
  Before that handoff, repeated direct stream disposal replays the shared close failure;
  repeated client disposal retains its parent failure. A different stream failure observed
  after the parent's first selected error stays replayable. Frozen disposal stays unchanged.

### Manifests, loading and later producers

- Put RunManifest/facets/serialization under `AnyInfer.Manifest`. Preserve format "1",
  all source facet fields/defaults and immutable maps/sequences. Source:
  `manifest.py:95-518`. Monetary facets serialize EDecimal using invariant strings.
  Pure prerequisites Diagnostic, MechanismRung and EmbeddingSpace may be pulled forward
  with full value semantics; this does not implement later operation/tool/context APIs.
- RunManifest has ToDictionary() returning immutable JsonObject, FromDictionary(JsonObject),
  ToJson(int? indent=2), FromJson(string). Use a strict typed native boundary: missing fields
  use defaults, nullable fields accept null, wrong known types/null nonnullable fields
  raise bounded value-free FormatException. Ignore unknown fields at every facet level.
  Preserve unknown data inside declared arbitrary JSON values. JSON text duplicate keys
  use the existing native last-wins rule. Do not emulate Python dict(iterable) accidents.
  A present JsonNull is a valid arbitrary SourcedFact value; only a missing required
  member fails. Double-valued fields accept finite representable JSON integer spellings
  as numbers, while integer-valued fields reject floating spellings and booleans.
- `ManifestUtilities.SchemaDigest(JsonObject)` hashes the qualified compact ASCII bytes
  with SHA256 and returns lowercase `sha256:`. Schema unknown keywords stay in digest
  input; this differs intentionally from ignoring unknown manifest serialization fields.
  `ManifestUtilities.Render(RunManifest,int width=80)` follows source fixed section order,
  formatting and no trailing newline. `ManifestUtilities.JsonSchema()` returns the v1
  schema generated from the Python public helper as embedded data, not a runtime bridge.
  A small build-time generator/check must make source derivation reproducible.
- Builder allocation and request ID occur when the lazy stream is created, before any
  target resolve/credential/factory/transport work. UUID correlation is unrelated to
  request text. Native version comes from build informational version/package metadata,
  never a hard-coded Python version or new filesystem query at request time.
  Preserve the accepted native boolean-schema domain and late invalid-schema assessment
  order: manifest allocation must not cast every SchemaSpec root to JsonObject, validate
  schemas early, or throw from optional fingerprint/payload preparation before extraction.
  Boolean roots use the same qualified internal value writer for their digest; malformed
  schema roots retain their existing controlled assessment path. Add causal generation
  controls with default manifests enabled before accepting the builder/runtime wave.
- The stream owns its builder/context. Expose immutable partial AsyncStream.Manifest
  (and SyncStream.Manifest) before enumeration, with Complete=false. Generation.Manifest
  is the terminal snapshot, nullable when disabled. No client-wide builder dictionary.
- Add client constructor/factory tails `observers`, `manifests=true`,
  `manifestPayloads=false`; invocation-only `bool? manifest=null` tails on generation
  and stream overloads. Keep all current positional parameters, including cancellation,
  in their existing order. Forward the same values through the sync facade. Do not add
  a GenerationRequest.Manifest field or a second generation path.
- Core emits from actual request/target/entry/first-token/retry/fallback/repair/terminal
  facts. Fold builder before observer fanout. Enrich it only with actual normalized
  request, resolved capabilities and result facts not carried in events, as Python does.
  Keep a single request ID across attempts. Event callbacks execute outside all locks.
- A stream-owned terminal commit must atomically check close/cancellation, fold terminal
  facts, freeze one manifest and install the exact Generation carrying it. Only after
  successful commit may RequestCompleted fan out and StreamEnded be yielded. An observer
  handling completion can inspect the committed stream result and matching manifest.
  If close won, neither completion nor a complete manifest is published. Do not execute
  user callbacks or sinks under the stream/client/builder gate.
  Use one committed result source, not two synchronized result copies: add an internal
  AsyncStream committed-result accessor protected by its gate. Public-SDK SyncStream.Result
  forwards that source (without holding the sync gate), and SyncStream.Manifest forwards
  the inner view. This makes completion callback readiness independent of foreground
  consumption of the channel's StreamEnded. Retain the old observed-terminal path for
  the frozen profile; update public XML docs to describe committed-result readiness.
  No sync-gate acquisition occurs inside the async terminal commit.
  Prepare a terminal manifest without publishing it; only the successful stream-gated
  commit installs both result and terminal manifest. Manifest getters follow the same
  stream-gate then builder-gate order; no path holds builder-gate while acquiring the
  stream gate. Close-losing preparation cannot expose Complete=true through a getter.
- OCE propagates with existing source/owned identity and leaves an incomplete manifest;
  it emits neither RequestFailed nor RequestCompleted. Genuine terminal routed/config/
  validation failures emit RequestFailed at one terminal boundary. Never turn every
  retry into request failure. Unadvanced/abandoned streams do not fabricate completion.
- SDK.5b/c supplies estimates, costs, spend, pacing, cache/context policy producers;
  SDK.6 operation producers; SDK.7 rich tools; SDK.9 reductions; SDK.10 acquisition;
  SDK.11 arena/batch and optional bridges. Complete DTOs can exist before these producers;
  unavailable facts stay absent/unknown. Public helpers requiring those implementations
  remain explicitly assigned to their phase, not stubbed with claimed working behavior.

## 3. Ownership and execution protocol

Workers are not alone: edit only assigned paths, preserve other workers' changes, re-read
shared files before minimal edits and never touch Git. Every brief names its boxes and
definition of done. Shared plan edits are serialized: after root supplies a passing named
gate, the owner re-reads this file and ticks only its box in one minimal edit. Root owns
parent/inventory changes. No child starts builds, restore, packaging, imports, Python
tests or full gates unless root explicitly hands it a named execution lease.

Ownership waves (the exact brief is authoritative):

| Wave | Owner and exclusive paths | Dependency |
| --- | --- | --- |
| Foundation money/Usage | c16: AnyInfer.csproj, new Internal/AccountingDecimal.cs, Capabilities/CapabilityMetadata.cs/PricingTable.cs/CapabilityAssembler.cs, Models.cs Usage only; listed mechanical callers with a serialized explicit grant | Qualification accepted; no runtime integration yet |
| Writer/digest | c708: Json/JsonWriter.cs plus new Manifest/ManifestUtilities.cs digest portion; no other writer mode changes | Fixed writer policy; can author in parallel with numeric foundation |
| Pure event/manifest values | 2ff: new Events/TelemetryEvent.cs, Events/IObserver.cs, Manifest/ManifestFacets.cs, Manifest/RunManifest.cs; pure prerequisite files | Exact saved Usage/EDecimal handoff before consumer code |
| Dispatcher/sinks/builder | 2ff continued, new Events/EventDispatcher.cs/EventSinks.cs and Internal/RequestTelemetry.cs, Manifest/ManifestBuilder.cs/ManifestSerialization.cs/ManifestUtilities.cs after writer handoff | Frozen public value/serializer signatures |
| Client/stream integration | c708: AsyncClient.cs, Client.cs, GenerationStream.cs, SyncStream.cs, Models.cs Generation only, version helper | Coherent context/builder API; writer released |
| Core fact producers | cab: Core/GenerationCore.cs/EntrySession hooks only | Coherent context API; preserve router/frozen gates |
| Independent tests | 04f: new TelemetryTests.cs/ManifestTests.cs/EventLifecycleTests.cs and pure-value baseline migrations by explicit path; 1e: shared fixture/Python bridge + new OpenAIEventTests.cs | Saved coherent public/runtime handoff |
| Docs/package/examples | c16 after foundation release: checker/package tests, exact graph staging, example program and source-linked docs, generator/schema resource by explicit grant | Stable public source; no temporary bridge documented |
| Reviews | 500e contract/value/protocol; ec8 lifetime/publication | Joint coherent saved waves, not isolated partial patches |

Models.cs, ManifestUtilities.cs and the package checker are serialized shared files. Hand
off ownership explicitly before a new owner edits. Root handles unassigned mechanical
call sites or assigns a bounded disjoint lease. No independently invented parallel API.

## 4. Checklist and gates

- [x] **EVT.0** Record qualification and independently critique this executable contract.
  Gate: root numerical/package evidence, cold writer/money critique and lifecycle pins
  agree; unresolved blockers corrected before production. Exact-version license/hash
  evidence is recorded and all deferred producers are explicit.
  > NOTE: Root inspected numeric/package execution and the fresh cold plan critique.
  > Its sync publication P1 and map/payload P2s are corrected; independent contract and
  > lifetime rechecks are clean. Begin the disjoint EVT.1a/1b/1c source wave. Production
  > implementation gates remain unrun; qualification alone does not tick those boxes.
- [x] **EVT.1a** Save one coherent EDecimal/Pricing/Usage foundation, exact package pin and
  mechanical caller migration. Gate: zero-warning solution compilation, focused existing
  capabilities/pricing plus new Usage/equality tests; 1E-29 and >decimal-max price strings
  retain values; 1.0/1.00 and signed-zero record hash/equality agree; source reported cost
  and null are distinct. No premature pricing/ledger integration or frozen aggregation change.
  > NOTE: Root's 2026-10-18 gate compiled library, tests and conformance with zero warnings;
  > 48/48 focused tests and 93/93 conformance cases passed. Exact numeric equality and
  > unknown-value controls passed, including raw exponent and nonfinite catalog boundaries.
  > This foundation does not implement accounting or ledger behavior.
- [x] **EVT.1b** Save complete immutable event/facet values and strict versioned serializer.
  Gate: all 23 event shapes/defaults, defensive map/list snapshots, ordinal identity,
  nullable/default loading, unknown-field behavior, monetary string preservation and
  malformed typed data controls. Pure later-phase values pass tests without fake producers.
  > NOTE: Root's 2026-10-18 focused gate passed 118/118 with zero warnings, covering
  > values, serializer, render/schema, telemetry, modern schema/wire and probe controls;
  > prior 93/93 conformance plus 4117 digest and 30 JSON/30 render comparisons also passed.
- [x] **EVT.1c** Integrate qualified manifest writer/digest into shared native traversal.
  Gate: direct native value vectors reproduce real Python schema_digest/ToJson bytes,
  including 4096 raw-double inputs, thresholds, signed zero, BigInteger, Unicode prefixes,
  escaping and nested values. Schema unknown-key changes affect digest; reordered keys
  do not; manifest unknown keys ignore; duplicate text keys retain last. Frozen writers
  and schema/wire examples retain their prior observations.
  > NOTE: Root's 2026-10-18 unchanged production gate passed with zero warnings and
  > 118/118 focused controls. Public `SchemaDigest` matched all 4117 finite Python corpus
  > records; all 30 `ToJson` and all 30 `Render` comparisons matched after the scalar-aware
  > writer and renderer corrections. The existing 93/93 frozen conformance gate remains
  > passing.
- [x] **EVT.2a** Save dispatcher, sinks and builder/context against frozen value signatures.
  Gate: duplicate/reference unsubscribe, reentrancy snapshot, concurrent warn-once,
  per-observer payload isolation, registered-secret redaction, append/flush/close JSONL,
  logging mapping and no default I/O. Builder ignores other request IDs and snapshots
  cannot be changed by later events or caller-owned collections.
  > NOTE: Root's focused builder/dispatcher/sink/privacy/correlation gate passed 128/128
  > with zero compiler warnings; package/schema-focused Python controls passed 25/25 and
  > Ruff passed. Builder/context APIs are frozen for the integration wave.
- [x] **EVT.2b** Integrate actual client/stream/core facts and atomic terminal commit.
  Gate: async/sync public tests cover one request ID, real retry/fallback/repair facts,
  observer-versus-manifest equality, partial before drain, disabled/client/per-call override,
  incomplete cancellation/close/failure, completion callback result readiness and identical
  Generation/Manifest snapshots. Same-client async/captured-sync observer disposal refuses;
  external close joins real callback/adapter cleanup and permits no late completion.
  Async and sync completion callbacks must read their own public stream.Result/Manifest
  before StreamEnded consumption; a close race distinguishes a committed complete result
  from an incomplete close-losing stream. Both paths preserve the frozen readiness profile.
  > NOTE: Source comparison pins fallback to the next raw route label before that label
  > is resolved or deduplicated; an unhealthy, duplicate or unresolvable next label must
  > not move the fallback event to a later target. TargetResolved remains after successful
  > unique resolution and before health handling. RequestStarted belongs to the first
  > owned MoveNext, after enumerator installation, so obtaining an unadvanced enumerator
  > remains inert and concurrent close can join every installed operation.
  > NOTE: The recovered coherent public lifecycle/HTTP gate passes 31/31 with zero compiler
  > warnings, including entered-callback/native-cleanup joins, async/captured-sync disposal
  > refusals, actual adapter UnsafeRegister cancellation, source identity, opaque schemas,
  > unhealthy/duplicate fallback ordering and committed-result visibility. Caller cancellation
  > before a new pull may win ahead of a prefetched adapter OCE; its original caller token
  > is required, while source-object identity is proved in separate noncompeting controls.
  > The full workspace gate reopened this box: 470/471 native unit tests and 93/93 frozen
  > conformance passed, but the existing sync callback-failure cleanup control reports the
  > already-reported cancellation callback failure again on subsequent stream disposal.
  > Preserve the old test and source/cleanup fault semantics while fixing signal ownership.
  > The explicit parent-reporting handoff now passes all 50 combined sync-client,
  > lifecycle and HTTP controls with zero compiler warnings. Direct close failures retain
  > exact replay; only the stream whose error becomes the client's reported failure is
  > marked complete for later child disposal. Other stream failures remain observable.
- [x] **EVT.3** Add input-only cross-language event/manifest profile and independent native
  and Python observations, plus real builtin offline HTTP controls. Gate: neither runtime
  calls the other; no expected verdicts in fixture data; actual public generation produces
  wire/event/result evidence; payload privacy and positive sink opt-in are causal. Native
  timing/version/exception spelling differences have explicit profile mappings, not fake
  values. Source callback/OCE identity remains exact and no queue/second router appears.
  > NOTE: Actual public Python fixture observations passed 2/2 and the coherent native
  > lifecycle/HTTP gate passed 31/31. Shared buffered/SSE repair, real retry/fallback,
  > four-way payload privacy, builtin send/read cancellation and native cleanup are causal.
  > Native modern streamed requests now accept buffered JSON replies using the existing
  > decoder, matching Python; the frozen SSE profile and its source assets are unchanged.
- [x] **EVT.4** Ship source-linked compiled TelemetryExample/ManifestExample and native API
  reference/porting docs; update package-only consumer and generator/schema resource.
  Gate: exact rendered source equals executed files, public async/sync observer/manifest
  consumer runs from isolated local feed/cache, setup remains inert, and archive staging
  accepts exactly JsonSchema.Net8.0.5's four MIT packages plus PeterO.Numbers1.8.2 CC0-1.0
  using individually pinned hashes/licenses. Root nuspec direct pins are exactly the two
  selected dependencies; main AnyInfer license/payload/revision rules stay unchanged.
  > NOTE: Working-tree proof on 2026-10-18 passed: the compiled example executable,
  > strict docs build, rendered-source verifier (23 blocks across 14 compiled files and
  > 6 pages), package/schema Python controls (25/25), touched Ruff checks, and isolated
  > local-feed package consumer all succeeded with zero compiler warnings and the exact
  > five-archive closure. Clean-revision package proof remains EVT.5.
- [x] **EVT.5** Close independent contract/lifetime reviews and run the full workspace gate.
  Gate: all required steps, frozen 102 observations/hashes, native concurrency/cancellation,
  Python baseline, docs and isolated package checks pass. Only repeat gates when changed
  source/failure justifies it; one heavy gate at a time. Commit finished explicit paths,
  run clean-revision package proof, then reconcile this child, parent SDK.5a and inventory
  scope notes. Leave SDK.5b/5c and unfinished root-export rows unchecked.
  > NOTE: The final coherent workspace run passes all 18 steps in 108.1s: 474 native unit
  > tests, 93 frozen conformance tests, Python/core/frontend checks, strict documentation,
  > compiled examples and isolated package consumption. Compiler warnings are zero and
  > the three frozen release/report hashes remain unchanged. Source is committed as
  > `68d2cc06914aaa8539eb3cc5ee8d20acdbd2a906`; its clean-revision package, exact five-archive
  > dependency/license/hash closure and isolated consumer restore/build/run pass at
  > `.tmp-tests/sdk-five-clean-package/run-ybv82fp9/` with zero warnings. SDK.5a is accepted;
  > SDK.5b/5c accounting and policies remain unfinished.

## 5. Resume and evidence

This child plan is complete. Resume the parent at SDK.5b from accepted source checkpoint
`68d2cc06914aaa8539eb3cc5ee8d20acdbd2a906`. No accounting, ledger or policy completion is
implied by the minimum EDecimal/Usage prerequisite included here.
> NOTE: Crash recovery continues from HEAD `1affab3ed9baf147907f464c178e752534d361d2`
> with the SDK.5 working tree intact. The dedicated lifecycle/HTTP gate compiled and
> initially passed 19/22 before the modern entry-token identity and buffered-stream-response
> corrections. The expanded corrected run now passes 31/31 using
> `dotnet test AnyInfer.Tests/AnyInfer.Tests.csproj --no-restore --filter "EventLifecycleTests|OpenAIEventTests" --blame-hang-timeout 60s`
> from `src/csharp`. The expanded 50-case sync/lifecycle/HTTP gate and corrected full
> 18-step gate pass; source and clean-revision package acceptance are recorded above.
No SDK.5 production edits existed at plan creation; EVT.0 is now closed.
Native monetary qualification and independent manifest prototype are under
ignored `.tmp-tests/accounting-qualification/` and `.tmp-tests/manifest-qualification/`.
The exact package archive/signature audit is `.tmp-tests/sdk-five-package-audit/`.
Root execution details and independent reviews are in Traycer artifacts
`csharp-sdk/sdk-five-qualification`, `sdk-five-decimal-research`,
`sdk-five-money-contract-review`, `sdk-five-manifest-qualification-review` and
`foundation-execution/csharp-sdk/sdk-five-event-mechanism-review`.

Accepted money archive SHA-512 (hex):
`45ce5abe7c1df6fe43bb206b2e2f09f3bbd5f5dc89fc176048e84d7cbcf1ce360610ed0673f5fe0335b0b72dd5c4d3a78c48e4eebe8d641b74312475b1d84746`.
Convert to base64 mechanically when extending the package checker; never hand-invent a
hash or broaden its graph acceptance to arbitrary packages.
