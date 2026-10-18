# C# SDK catalog and capability milestone

Resume from the first unchecked box. This is the SDK.4a execution checklist under
`ANYINFER_CSHARP_SDK.md`; it does not replace the main SDK plan or broaden the frozen
core-generation profile. SDK.3 source checkpoint:
`04dfa37231f26f5c72b7215afd747c47de4e6d19`.

## Destination and boundaries

Port the Python library's capability facts, provenance, catalog metadata, target resolution
and explicit model/health queries. Preserve domain names with native C# casing, immutable
snapshots and asynchronous lifecycle ownership. A metadata type does not claim an inference
operation, download manager, probe or accounting implementation.

Behavioral baseline remains `199c3f833e568334b629edd7d89f41a3b76efe2a`. Read the actual
Python definitions and tests; DESIGN signatures are illustrative. Governing source:

- `src/python/anyinfer/types/capabilities.py` and metadata types in `types/operations.py`.
- `src/python/anyinfer/capabilities/assemble.py` and the pricing-table reader.
- `src/python/anyinfer/catalog/{model,resolve}.py`, `catalog/{default,models}.json`.
- `src/python/anyinfer/local/artifacts.py` and `local/sources/__init__.py` for pure artifact
  and SourceRef records only; no resolver execution or acquisition in this milestone.
- `src/python/anyinfer/providers/base.py`, `providers/openai_compat.py`, registry and the
  client `models`, `health`, `resolve` and capability-query implementations.

Root alone owns Git, the shared build/test slot and this checklist. Authors re-read shared
files immediately before minimal edits, preserve other owners' work, run only explicitly
granted checks, and report saved API signatures before dependent tests or code are authored.
No source implementation starts until the contract critique below is closed.

## Native contract

### Facts and precedence

- Use `AnyInfer.Capabilities` for `Provenance`, `Sourced<T>`, `Feature`, `Pricing`,
  `TokenizerKind`, `TokenCalibration`, `RateLimitHeaders`, `LocalModelInfo`,
  `ModelCapabilities`, `DiscoveredModel`, `Health`
  and pure operation capability metadata. Preserve every current Python field/default;
  defensively copy mappings, sequences and operation sets. Do not invent extra claims.
  These immutable fact records retain logical value equality for SDK-owned collections:
  pricing maps compare by key/value independent of insertion order, embedding lists compare
  in order, and operation sets compare by membership plus their provenance. Equal facts
  have equal hashes. Do not add reflection-based equality or change arbitrary user T
  behavior in generic Sourced<T>.
- Provenance ranks are Default=0, Catalog=1, Discovered=2, Probed=3, Override=4.
  `Sourced<T>.Outranks` uses greater-than-or-equal rank: an incoming equal-ranked field
  replaces the previous value. Numeric zero and false remain distinct from absent/null.
  Feature.None/Default is the unknown baseline; provenance remains part of its meaning.
  Validate closed Provenance membership at Sourced<T> and TokenCalibration construction;
  a cast integer outside the declared domain cannot outrank Override.
- Port `ModelCapabilities.Overlay` and `Conjunction` from actual Python. Missing numeric
  constraints in any conjunction member yield unknown; known constraints use minimum and
  weakest contributing provenance. Features/known operation sets intersect. Omitted pricing,
  sampling, embedding and local facts stay omitted rather than being guessed.
- Bring `InferenceOperation`, `EmbeddingCapabilities`, `RerankCapabilities` and operation
  capability facts forward as pure metadata so
  model filtering works now. Embedding/rerank requests and execution remain SDK.6.
  Pricing value facts and read-only table contributions are allowed here; cost estimation,
  aggregate usage, ledgers, reservations and pricing refresh remain SDK.5.
  Pricing amounts, including per-server-tool values, use C# decimal rather than double.
  Keep TokenCalibration's nullable TokenizerKind and tokenizer provenance. RateLimitHeaders
  contains declared header names and its Declared predicate, not measured counters or a
  pacing implementation; token counting and rate-limit enforcement remain later work.
- Capability assembly layers real descriptor defaults, static model metadata, pricing data,
  discovery, separately stored probe facts, local-zero pricing only when applicable and
  still unknown, then application overrides. Probe execution remains SDK.4c; do not expose
  an inert public API that promises an unimplemented probe.
  Effective locality is derived by the pool from descriptor locality and the effective
  endpoint. ProviderSettings has no locality field in Python; add no settings/config/catalog
  key for it. A non-Local descriptor retains its declared locality; a Local descriptor is
  Local with no endpoint or a loopback endpoint, otherwise Remote. This is a pure URI/metadata
  query, never DNS, credentials or a factory call. Only effective Local with absent pricing gains known zero input/output decimal
  prices at Catalog provenance. Preserve any prior pricing; Hosted/Remote without pricing
  stays unknown. A normally local engine used remotely must not be declared free.
- Match the baseline's override edge explicitly: `_apply_override` ignores Feature(0)
  because its feature branch is truthy-only, although supplied numeric zero fields apply.
  Plain ModelCapabilities.Overlay still follows provenance. Do not silently fix Python or
  claim a different feature-clear behavior is equivalent.

### Catalog and resolution

- Use `AnyInfer.Catalog` for the actual Python catalog names: Catalog, TargetEntry,
  AliasEntry, OllamaChannel, ModelVariant, ModelEntry and the model/artifact kind vocabulary.
  Pure GgufFile/GgufArtifact and SourceRef metadata may live alongside these catalog types;
  document the native namespace mapping. SourceRef execution/resolvers remain SDK.10.
- Preserve full record defaults and parser behavior, including model kinds, best_at filters,
  artifact roles, embedding metadata and overlays. General unknown catalog keys are ignored
  where Python ignores them; do not invent a globally closed JSON dialect. The embedding
  subobject is closed as in Python. Parse bundled artifact/variant rows without implying
  that native acquisition or local-runtime management exists.
  TargetEntry accepts simultaneous model and GGUF values as the actual parser does;
  ModelRef prefers a nonempty model, then GGUF, and fails only if neither is usable. Test
  model-only, GGUF-only, both and neither. Do not copy the stricter illustrative docstring.
  Catalog parsing also derives/registers GGUF artifacts from usable variant SourceRefs,
  including roles, digests, sizes and artifact IDs, without fetching anything. Explicit
  gguf_artifacts win over derived rows with the same ID (setdefault semantics). Preserve
  the baseline's Hugging Face and explicit-URL derivation paths and model metadata fallback.
- Embed the existing Python JSON files directly through C# build inputs. Do not copy and
  maintain a second pinned catalog, edit generated hashes, read the source checkout at
  runtime, or put loose internal data trees into the NuGet payload. Use the existing
  pricing asset similarly where assembly needs a table contribution.
- Reuse the current trusted JsonReader unchanged for native Load/Loads conveniences.
  Its portable integer magnitude, finite-number, depth and valid-Unicode limits remain
  explicit native input boundaries; no arbitrary-integer or unpaired-surrogate acceptance
  claim is made. Do not broaden the frozen reader or introduce another JSON codec here.
  Typed numeric overflow fails actionably without truncation or rounding. FromMapping uses
  the existing tagged JsonObject representation. Public stored DisplayName and derived
  ModelEntry.Name follow the Python definitions.
  Within that native domain, preserve Python field conversions: legacy boolean catalog
  versions normalize to 0/1; source sizes accept boolean 0/1 where Python accepts int;
  optional-int fields continue to exclude booleans. A catalog-private compatibility helper
  handles Python-style str(...) conversions, including None/True/False spellings, rather
  than substituting JSON text. Pin meaningful float/container vectors and report any remaining
  lexical mismatch explicitly. SourceRef metadata has no native resolver execution yet.
- Explicit targets split at the first colon, preserve model suffix/edge trim, normalize
  provider spelling and retain ViaAlias=null. A bare catalog alias chooses the first
  configured **instance ID** present in its target mapping, retaining ViaAlias. Do not add
  an engine-based fallback for arbitrary instance aliases: Python requires corresponding
  instance keys in the catalog. Empty, unknown or unrealizable aliases fail actionably.
- Reuse a pure snapshot of bound instance metadata/order from ProviderPool. The public
  engine-only registry cannot infer primary->openai-compat from an ID list alone. Derived
  descriptor views or an equivalent pure binding view may carry that identity; never resolve
  credentials or invoke a factory merely to resolve a target or inspect capabilities.
  CAT.2's pure native entry point is Catalog.ResolveTarget(string target,
  ProviderRegistry registry, IReadOnlyList<CatalogProviderBinding> configured), where
  CatalogProviderBinding snapshots InstanceId and ProviderId. An explicit configured
  instance selects its own identity; otherwise descriptor spelling resolves to its
  canonical engine/default instance. A bare alias matches configured instance keys only.
- Public AsyncClient.Resolve and Capabilities queries and generation use the same target
  resolution path. Generation resolves each target only when the existing route loop reaches
  it, before dedup/health/construction, preserving instance identity and actual ViaAlias in
  results. Do not resolve or validate the complete route eagerly: a successful first target
  must not fail because an unused fallback alias/provider is unknown or malformed. Explicit
  Resolve/Capabilities queries resolve their single requested target immediately. No
  alternate generation/router implementation.
- CAT.3 settings constructors append symmetric optional catalog, pricingTable and
  capabilityOverrides arguments to AsyncClient and Client, preserving the existing argument
  order. Overrides use IReadOnlyDictionary<string, IReadOnlyDictionary<string,
  ModelCapabilities>> and are defensively snapshotted by normalized configured instance ID,
  then exact model ID. Reject duplicate outer keys after normalization rather than silently
  overwriting requested policy. Existing FromAdapters and internal clock
  constructors remain valid: explicit direct targets resolve normally, and capability fields
  without declared or layered evidence remain unknown rather than being invented or refused.

### Provider and client lifecycle

- Rename ProviderDescriptor and ProviderRegistration's old StructuredOutputProfile mappings to
  StructuredOutputProfiles, including its constructor argument and every current caller
  in the same wave. New descriptor DefaultCapabilities and StaticCapabilities use ModelCapabilities,
  matching the Python concepts. Keep frozen prebuilt ProviderRegistration observations
  unchanged. No obsolete aliases or two meanings of ModelCapabilities.
  Include descriptor Operations and static embedding/rerank capability tables as facts;
  this does not add operation execution. Use actual Python defaults and validation.
- Add optional public IProviderLifecycle with these exact asynchronous signatures:
  `ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default)`
  and `ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default)`.
  Existing
  generation-only custom adapters remain valid and explicitly refuse unsupported lifecycle
  queries; never fabricate empty discovery or a healthy/unhealthy result for a nonparticipant.
  Use UnsupportedInputException with discover phase and the actual configured instance.
- AsyncClient exposes `Task<IReadOnlyList<DiscoveredModel>> ModelsAsync(string providerId,
  InferenceOperation? operation = null, CancellationToken cancellationToken = default)` and
  `Task<Health> HealthAsync(string providerId, CancellationToken cancellationToken = default)`.
  Client exposes matching Models/Health signatures returning the values synchronously.
  Snapshot the adapter's returned list before recording/filtering/returning; caller mutation
  of an adapter-owned list cannot mutate the client result. Add pure Resolve/Capabilities.
- A lifecycle providerId selects exactly one normalized bound pool instance. An explicit
  instance alias selects that instance; a descriptor spelling/alias selects its canonical
  engine instance, using the existing generation default-state rule if not configured.
  It never chooses another same-engine configured alias, follows a route, fans out or
  interprets the selector as a model/catalog alias. Unknown selectors fail before factory
  work. Preserve the actual instance ID in cache keys and failures. Test two same-engine
  instances and an unconfigured engine/default-state request without crossing their settings.
- Discovery/health is explicit caller-requested work. Reserve it before construction or
  callbacks; link caller/client cancellation, join it on close, preserve original errors,
  dispose late resources exactly once, and reuse the client-owned adapter pool. Extend the
  existing lifetime mechanism for non-generation operations rather than dispatching an
  untracked adapter call. Sync mirrors retain default-scheduler execution and callback
  self-dispose refusal; external disposal still cancels and joins.
  Implement one internal AsyncClient lifecycle-operation reservation used by Models and
  Health before pool acquisition or caller callbacks. Reserve atomically against closing,
  retain a completion task and caller+client linked token through all construction/dispatch/
  cleanup, and complete/remove it in finally. AsyncClient close marks/snapshots under its
  gate, starts cancellation for every stream and lifecycle operation off-lock before any
  join, retains callback failures, joins all reservations/stream cleanup, then tears down
  the pool. No caller callbacks or blocking waits under the client gate. Sync wrappers use
  the same async operations via their existing reserved default-scheduler boundary.
- Lifecycle adapter invocations may overlap with each other and generation, matching the
  Python call path. Document that participating adapters must support concurrent calls;
  the construction gate protects creation only and is never held across adapter I/O.
  CapabilityStore commits immutable snapshot updates atomically. Prove overlapping calls
  and close joining every active call using real adapter readiness, not an invented gate.
- Keep router health gating separate from a provider Health response. No background probes,
  implicit discovery on config parse/client construction/unadvanced stream, credentials
  inspection during pure resolution, or synthetic capability facts after a failed listing.
- Model filtering includes known operation membership; unknown operations are compatible
  with embedding/rerank only if the model ID is in the corresponding descriptor static
  capability table; otherwise only generation on a generation-capable descriptor is admitted.
  An explicitly known Operations set is authoritative, including an empty set. Record the
  complete successful listing before filtering; never replace it with the filtered result.
  Invalidation, successful-empty discovery and id-only listings need explicit source-backed
  cache controls before the lifecycle wave is implemented.
  > NOTE: The baseline models method queries on every explicit call; CapabilityStore is
  > a capability layer, not a response cache. RecordDiscovery creates a provider layer with
  > setdefault and inserts/updates only non-null capability rows. Thus never-queried means
  > DiscoveredHasModel=null; a fresh empty or ID-only listing means false for those IDs;
  > existing capability rows persist until invalidation. Match this documented baseline edge
  > rather than treating an ID-only result as a discovered capability fact. Models still
  > returns the actual ID-only listing. Invalidation removes the layer and restores unknown.

### CAT.3 exact implementation handoff

- Add public ProviderLocality (Hosted, Local, Remote) in AnyInfer.Providers. Descriptor
  locality defaults to Hosted; invalid enum casts fail at construction. Add descriptor
  DefaultCapabilities, StaticCapabilities, Operations (default Generation),
  StaticEmbeddingCapabilities, StaticRerankCapabilities, TokenCalibration and RateLimitHeaders
  with copied immutable metadata and actual Python defaults. Rename both proof structured
  profile maps/constructor arguments to StructuredOutputProfiles/structuredOutputProfiles;
  migrate every caller without keeping obsolete aliases or altering frozen observations.
- Extend ProviderDescriptor by appending the new optional metadata arguments after the
  existing repair ceiling, in this exact order: ProviderLocality locality = Hosted,
  ModelCapabilities? defaultCapabilities = null,
  IReadOnlyDictionary<string, ModelCapabilities>? staticCapabilities = null,
  IEnumerable<InferenceOperation>? operations = null,
  IReadOnlyDictionary<string, EmbeddingCapabilities>? staticEmbeddingCapabilities = null,
  IReadOnlyDictionary<string, RerankCapabilities>? staticRerankCapabilities = null,
  TokenCalibration? tokenCalibration = null, RateLimitHeaders? rateLimitHeaders = null.
  Send exact argument order/types to dependent owners before edits.
  Main AsyncClient/Client constructors append catalog, pricingTable, capabilityOverrides,
  preserving all existing argument order; FromConfig mirrors those tails. FromAdapters keeps
  its existing one-argument public call shape and uses embedded default catalog/pricing;
  the internal registrations+clock path remains frozen. Expose immutable Catalog plus pure Resolve(string target)
  and Capabilities(string target) on both clients. Pure metadata queries need no async pump,
  operation reservation, credential/factory work or HTTP; retain metadata after close.
- Public PricingEntry has Model, Pricing, required LastVerified/Source, and OpenRouterId
  defaulting to empty. Public PricingTable snapshots an
  IReadOnlyDictionary<string, IReadOnlyList<PricingEntry>> and exposes Providers (sorted),
  EntriesFor(string providerId), Lookup(string providerId, string model),
  FromMapping(JsonObject), LoadDefault(). Keep ordinal provider/model spellings: no invented
  lowercasing. Lookup is exact first, then longest prefix followed by -, ., : or @;
  unknown means null, known prices carry Catalog provenance. Port the actual entry/tool-rate
  parsing and errors from capabilities/pricing_table.py; decimal values are not binary-double
  arithmetic. C# decimal's representable range/precision is an explicit native boundary:
  fail with ConfigException rather than silently rounding, underflowing or overflowing a
  rate. Reuse the catalog's qualified Python scalar/container spelling through a narrow
  internal bridge; do not add a second partial repr/float formatter or alter catalog parsing.
  Embed the existing pricing.json asset as AnyInfer.Capabilities.pricing.json;
  no source-tree access, refresh/fetch API, cost calculations or accounting in this wave.
- CapabilityStore and CapabilityAssembler stay internal during CAT.3. Python exports the
  store, but its complete public probe surface is deferred explicitly to SDK.4c; do not expose
  no-op probe promises or check the full export inventory row now. Keep immutable atomic
  discovered/probed snapshot updates available internally for CAT.4/4c, preserving the
  already-pinned successful-empty/ID-only/invalidation behavior.
- Store discovery/probe/application overrides by bound configured instance ID. Descriptor
  defaults/static facts remain the engine's copied metadata. Pricing uses the effective
  descriptor identity (the instance alias for a derived instance), as Python does; do not
  silently use another engine's pricing for a custom alias. Pin separate alias prices and
  unknown prices. Supply one immutable capability identity to the assembler: the resolved
  concrete provider/instance ID for configured aliases, and canonical descriptor ID for an
  unconfigured default. Use it consistently for discovery/probe/override/pricing lookup;
  the engine descriptor's original Id supplies metadata, not an alias's layer identity.
  Apply the table as a pricing-only replacement so default feature fields
  cannot clobber existing evidence. Preserve the complete layer order and local-zero rule.
  Application overrides re-tag precisely Python's supported supplied fields as Override:
  zero numeric values apply, Feature.None remains ignored, and the baseline does not apply
  an embedding override through _apply_override. Auto candidates come only from static,
  discovered and probed names; no candidates returns descriptor defaults. Do not invent
  candidates from pricing, overrides or logical catalog entries.
- ProviderPool supplies immutable configured binding order and a private descriptor-registry
  snapshot captured at construction. Pure queries never read mutable runtime _instances as
  the configured preference source or add unconfigured defaults to configured alias preference.
  Prebuilt registrations use their actual bindings and an empty descriptor registry for
  unresolved names, without fake factories/descriptors or synthetic capabilities. Exact
  direct targets remain valid; absent capability evidence remains unknown.
- Public SDK generation resolves each reached catalog target through the same pure path
  inside the existing route loop before target deduplication/health/construction and retains
  ViaAlias in results. Do not materialize a prevalidated route of ResolvedTargets. Deduplicate
  by concrete provider/model identity independently of ViaAlias, retaining the first resolved
  target's provenance. Route health state uses that same concrete identity for failure,
  lookup, clearing and seeded observations: changing the alias spelling cannot bypass a
  recent failure. Python's routing/health.py keys by str(target), which excludes ViaAlias.
  A reached unknown alias fails before its adapter construction or a
  fabricated attempt; an unreached invalid fallback is inert. Existing Route retry/health
  policy and lifetime rules remain authoritative. Pin first-target success with unused invalid
  fallbacks, reached invalid-alias refusal, and two aliases to one target deduplicating once.
  Also pin cross-request health gating through a different alias for the same concrete target.
- Preserve frozen admission explicitly. RequestAdmission.Validate and the internal
  registrations+clock constructor retain v0's alias refusal. Add one narrow internal
  admission/profile selection for the public SDK path, including public FromAdapters;
  defer only target-spelling/alias resolution to the reached-target resolver. Do not check
  every bare target against Catalog during normalization, which would eagerly reject an
  unused fallback. Keep every schema/message/sampling admission rule and the default
  Normalize/Validate behavior unchanged; the profile must reach the same core loop's resolver,
  not merely bypass admission and leave aliases unexecutable. No second router. All 102
  frozen observations must remain unchanged.
  The accepted mechanism is an internal pure TargetMetadataResolver shared by public
  Resolve/Capabilities and the public per-reached-target generation path. A private profile
  selects this path versus the existing frozen raw-target metadata lookup. Both paths
  feed the same concrete pool metadata lookup and existing retry/repair loop. No public
  request flag or normalization-time target resolution is added.

### CAT.4 exact lifecycle/protocol handoff

- IProviderLifecycle is an independent optional public interface, not a base interface or
  new required member of IProviderAdapter. Keep the exact ValueTask/Task/CT signatures above.
  Provider selection and shared acquisition use provider-instance metadata/state, never a
  fabricated generation model or ResolvedTarget. Exact prebuilt registrations remain valid
  lifecycle participants when their actual adapter implements the optional interface.
  Models rejects an undefined InferenceOperation cast with ArgumentOutOfRangeException
  (operation) before lifecycle reservation, selection or dispatch. Null remains unfiltered.
  Prove zero resolver/factory/adapter/send calls and continued client usability after refusal.
- Reserve every lifecycle operation atomically against close before selection/acquisition
  or callbacks. Ownership scope covers resolver/factory execution as well as lifecycle
  dispatch, snapshot/store work and cleanup, and restores before caller continuations.
  Use ordinary async/ConfigureAwait(false) for lifecycle I/O rather than Task.Run; the
  sync facade retains its existing default-scheduler boundary. AsyncClient.DisposeAsync
  checks the active owning AsyncClient marker and throws InvalidOperationException before
  marking close state when called from its own factory/resolver/adapter/cancel callback.
  Establish ownership at actual AsyncStream producer MoveNext and cleanup boundaries too,
  restoring it before an event is returned to external consumer code. Existing generation
  factories/adapter callbacks cannot acquire an unmarked self-join path through the new
  general client-close mechanism; normal external await-foreach disposal remains allowed.
  Actual cancellation executions explicitly establish both owning AsyncClient and any
  captured owning Client context, including UnsafeRegister callbacks. External consumer
  code stays unmarked. Cancellation signals are shared, one-shot, off-lock and initiated
  for every stream/reservation/lifetime before any signal or cleanup join; CTS disposal
  follows signal completion and all cleanup. No callback or wait runs under client gates.
- Preserve factory/resolver/adapter OCE and exception identity. A caller-token remap is
  permitted only at a narrowly identified client-owned wait/check that generated the linked
  token OCE; never blanket-catch acquisition/dispatch or remap exceptions from Cancel's
  registered callbacks. Distinguish caller cancellation from client close. Check cancellation
  after a cancellation-ignoring successful lifecycle return and before committing discovery
  or publishing a result, so late success cannot become a post-cancel capability update.
  Preserve original caller identity separately from linked cancellation signals through
  internal CancellationIdentityContext scopes: Client.RunOperation maps its effective token
  to the original caller, AsyncClient lifecycle scopes normalize that identity for owned
  waits/checks, and builtin lifecycle HTTP cancellation resolves it only when the original
  caller is actually cancelled. Close-only cancellation retains the effective token.
  Scopes restore before external continuations; custom provider exceptions are never
  intercepted or reconstructed. This adds no public API or cancellation/lifetime resource.
- The store remains internal; no public invalidation/probe API or inspection hook is added
  for tests. Returned real capability facts from prebuilt lifecycle adapters must still
  contribute even without a descriptor; absent default/static metadata remains unknown,
  without synthesizing a ProviderDescriptor/factory. Generation filtering of an unknown
  prebuilt model may use actual IProviderAdapter participation as evidence of generation
  support; declared descriptor operation sets remain authoritative when present.
- OpenAI-compatible list and health both perform GET of the same configured base plus
  `/models`, with no body/query or distinct health endpoint. Optional bearer/custom-header
  precedence stays as generation. List statuses >=400 use existing redacted/bounded typed
  status failures with phase discover; all statuses below400 proceed to JSON decoding.
  Mapping payload selects data, bare list is accepted, other valid shapes return empty;
  preserve row order/duplicates and Python str coercion of id (missing => empty), ignoring
  nonmapping rows. Do not invent discovered capabilities for ID-only rows.
  Here no body means empty wire bytes: .NET may own zero-byte HttpContent solely to carry
  Content-Type in its required content-header collection. Do not place Content-Type in
  HttpRequestHeaders or assert a null Content object. Keep configured header precedence.
- Preserve the baseline listing read semantics without a new fixed byte ceiling or public
  limit flag; retain the native trusted JsonReader finite/depth/Unicode/integer domain.
  Successful malformed listing JSON propagates that reader's original FormatException,
  the native counterpart of Python's unwrapped decoder error. Health never decodes the
  body: status<400 => Health(true), otherwise Health(false, "HTTP <status>"). Both operations
  complete the HTTP body read before status classification, matching Python's eager get.
  Health drains raw bytes without JSON decoding; a body-read timeout/transport failure
  precedes status classification even for an error status. ResponseHeadersRead is valid
  only with that explicit full read/drain under the lifecycle cancellation/timeout token.
- Capture immutable ProviderConfig instance timeout for lifecycle send/read and apply it
  through a linked per-call CTS, while preserving generation's existing timeout path.
  Supplied caller/client cancellation propagates unchanged; instance timeout alone maps
  Models to typed retryable transport timeout at discover, and Health to false with
  "The provider request timed out.". Other HTTP transport health failures use existing
  redaction then a 200-Unicode-scalar message bound. No raw headers/credentials in detail.
  HTTP helper phase parameters must leave every generation error/observation unchanged.
- Own and dispose the HTTP request, response, content and obtained response stream on every
  Models/Health success, status failure, malformed decode, transport failure and cancellation
  path. A failed send has no response to dispose; existing response/content ownership must
  still release any acquired stream. Prove real per-response/handler cleanup with counted
  resources, including successful body-ignored health and malformed successful listing.

## Execution checklist

- [x] **CAT.0 — Contract critique.** Root settles remaining source details and a fresh
  reviewer checks the contract against Python and current pool/client ownership. Gate:
  actionable identity, metadata and lifecycle contradictions are closed before edits.
  > NOTE: Independent metadata/catalog and lifecycle reviews are closed. Pins include
  > actual parser model/GGUF preference, derived artifacts, decimal/local-zero semantics,
  > complete calibration/header metadata, exact cancellation-aware lifecycle signatures,
  > instance selection, concurrent invocation and signal-all/join ownership. No runtime
  > or SDK.4 implementation claim follows from this source-only closure.
- [x] **CAT.1 — Pure capability types.** c708 owns new `src/csharp/AnyInfer/Capabilities/`
  value types and pure operation metadata only. Do not change client/pool/transport yet.
  Send exact saved constructors/properties to 04f. 04f owns new CapabilityTests.cs for rank
  ties, snapshots, null-vs-zero/false, overlays and conjunction. Gate: cold review,
  zero-warning library/solution build and focused native capability tests.
  > NOTE: Source/test static reviews closed provenance validation, logical map/list/set
  > equality/hash and public XML documentation. The first root SDK 8.0.425 solution build
  > stopped at CS0019 in Pricing's null dictionary initialization; no tests ran. The author
  > applied the one-hunk compile correction. The guarded retry passed: zero-warning solution
  > build and all 7 CapabilityTests, with TRX at
  > `.tmp-tests/cat1-capability-focused-02/capabilities.trx`. This accepts pure types only;
  > the parent SDK.4a and catalog/client/lifecycle gates remain incomplete.
- [x] **CAT.2 — Catalog data and resolution.** After the type handoff, c16 owns new
  `src/csharp/AnyInfer/Catalog/`, resource entries in AnyInfer.csproj and pure catalog
  serialization/resolution. 04f owns CatalogTests.cs after the saved API handoff. c708 owns
  the disjoint input-only `tests/fixtures/sdk-catalog-v1/` data and independent Python
  `tests/test_sdk_catalog_parity.py` bridge. Preserve full bundled metadata and
  actual parser/default/overlay/filter behavior; no local execution. Gate: bundled assets
  load from the built assembly, shared input-only catalog controls run independently in
  Python/C#, invalid/unknown/alias-order cases pass and package payload remains closed.
  > NOTE: The first shared Python bridge passed all 4 tests; retained XML is
  > `.tmp-tests/cat2-catalog-python-01.xml`. Native source/tests remain held. Cold review
  > requires missing-vs-null/default distinctions, full supported scalar/container conversion,
  > HF basename/model-name derivation, empty multi-file refusal and exact filter semantics.
  > Expanded shared/native regression controls are assigned before the guarded native gate.
  > Final acceptance supersedes the held status: 8/8 Python bridge tests, zero-warning
  > SDK 8.0.425 solution build and 22/22 focused Catalog/Capability tests pass. TRX:
  > `.tmp-tests/cat2-catalog-focused-04/catalog-capabilities.trx`; Python XML:
  > `.tmp-tests/cat2-catalog-python-02.xml`. Source/completeness/test reviews closed,
  > including raw target-key preservation. Archive inspection and isolated async/sync NuGet
  > consumer pass under `.tmp-tests/nuget/run-wdzkyifm/`. This is a dirty-tree development
  > package check; clean-revision checkpoint qualification remains CAT.5.
- [x] **CAT.3 — Assembly and pure client integration.** c708 owns descriptor migration,
  CapabilityStore and pure pool/client binding, resolution and capability queries. c16 owns
  mechanical descriptor-property migrations in examples/package consumer where needed.
  04f owns their independent tests after exact saved API handoff. Gate: real layer/override
  behavior, instance aliases and identity, zero resolver/factory/HTTP counts for pure queries,
  unchanged all-102 native observations and an isolated package consumer.
  - [x] CAT.3a: root's exact handoff/profile/locality contract receives bounded source critique.
    > NOTE: Independent assembly and admission/profile rereviews closed the identity,
    > immutable snapshot, executable profile and concrete-dedup gaps. Eager full-route
    > resolution was rejected against Python's per-pending-target loop; unknown unreached
    > fallbacks remain inert. This accepts the implementation handoff, not source/runtime.
  - [x] CAT.3b: c708 saves runtime/metadata/pricing/store/query integration and exact signatures;
    c16 migrates disjoint existing callers; 04f saves independent public tests. Gate: cold review.
    > NOTE: c16's caller lease is exactly the builtin property read in ConfigTests.cs and
    > examples/csharp-sdk/Program.cs after the saved API handoff. The positional proof map
    > in NativeRunner and frozen JSON spelling do not require edits. 04f owns new
    > PricingTableTests.cs/ProviderCapabilityTests.cs and, where real internal layer tests
    > require it, a separate friend-boundary file without production inspection hooks.
    > The first held integration snapshot is not accepted: static review found full-overlay
    > feature loss, mutable pure-query/default-state resolution, a public admission bypass,
    > incorrect descriptor defaults/operation admission, and incomplete pricing/tool parsing.
    > A consolidated source correction is assigned while independent baseline-backed tests
    > are authored. No CAT.3 build or runtime result has been claimed.
    > The corrected resolution/profile source scope is now statically closed. All three
    > independent test files are saved; final pricing/helper and test review remain pending,
    > including exact decimal refusal across token and tool paths without exponent-sized
    > allocations. Root verified the caller delta is exactly the two property reads above.
    > Final source reviews closed. Root's first narrow library build stopped at three
    > CS0118 Catalog namespace/type ambiguities in Client.cs (zero warnings); a mechanical
    > qualification correction is assigned. Independent test review remains in progress;
    > no CAT.3 behavioral test result exists yet.
    > Library compilation now passes with zero warnings/errors after type qualifications.
    > Whole-solution compilation reached independent-test syntax/type qualifications, which
    > are assigned without changing oracles. c16 additionally owns the embedded public
    > package-consumer metadata scenario in scripts/check_csharp_package.py and its focused
    > tests/test_csharp_packaging.py expectations; new catalog/capability APIs must execute
    > from the isolated package rather than being covered only by project-reference tests.
    > First native batch: 269/273 unit tests and 93/93 conformance tests passed; four
    > baseline-backed setup/oracle corrections preserved strict assertions. Second batch:
    > 272/273 units and 93/93 conformance passed. Its one real source failure exposed the
    > shared catalog repr helper escaping ASCII space; the narrow Python-printability fix
    > and public Unicode regression are assigned. Evidence directories are
    > `.tmp-tests/cat3-native-01/` and `.tmp-tests/cat3-native-02/`. The focused Python
    > packaging checks pass 12/12 (`.tmp-tests/cat3-package-python-01.xml`); actual new
    > isolated package execution still waits for the corrected native snapshot.
    > Final acceptance supersedes the intermediate held/failure notes above. All source,
    > test and package-consumer static reviews are closed. The shared repr correction
    > preserves ASCII space and Python nonprintable Unicode escapes; no strict oracle was
    > relaxed. Native frozen-admission coverage uses its retained internal clock constructor.
  - [x] CAT.3c: root solution/focused tests, frozen all-102 regression and isolated package
    consumer pass; record evidence before accepting CAT.3.
    > NOTE: Zero-warning solution build, 274/274 native unit tests and 93/93 conformance
    > tests pass, including every inventory-ordered case in the frozen 102-case proof.
    > Retained TRX files are under `.tmp-tests/cat3-native-03/`. Focused packaging tests
    > pass 12/12 (`.tmp-tests/cat3-package-python-01.xml`). Archive inspection plus fresh
    > local-feed restore/build/run of async/sync generation and pure catalog/capability/
    > pricing APIs pass under `.tmp-tests/nuget/run-4pqi19ex/`. This is a dirty-tree
    > development package; clean-revision checkpoint qualification remains CAT.5.
- [x] **CAT.4 — Explicit discovery/health.** c708 owns lifecycle interface, pool/client
  operation reservations and sync mirrors. After the interface handoff, c16 owns native
  OpenAI-compatible lifecycle translation using the existing contract snapshot; research
  any genuinely new wire behavior before coding it. 04f owns public lifecycle tests and a
  shared input-only HTTP fixture bridge. Gate: cancellation/waiter/close/re-entry ownership,
  real bounded HTTP list/health calls, operation filtering, cache/invalidation semantics,
  unsupported custom adapters and independent Python/C# fixture observations.
  - [x] CAT.4a: review the concrete lifecycle reservation/close/re-entry mechanism and
    existing OpenAI-compatible list/health protocol before dependent implementation.
    Gate: exact public signatures remain as pinned, async/sync close cancels and joins all
    selected operations without callback self-join or serialization of adapter I/O; wire
    semantics derive from current Python and its existing contract snapshot.
    > NOTE: Contract and mechanism rereviews are closed. Pins include provider-only state
    > acquisition, full async/sync callback ownership, off-lock one-shot signal-all/join,
    > source-OCE identity, late-success discard, real prebuilt discovery facts, invalid-op
    > refusal and complete HTTP resource cleanup. Local source confirms eager GET body
    > read before status (including Health), configured timeout and no health JSON parse.
  - [x] CAT.4b: save lifecycle runtime and exact API handoff, then disjoint HTTP binding,
    input-only fixture/independent Python bridge and native public tests. Gate: cold source,
    lifetime, protocol and causal-test reviews close without manufactured result hooks.
    > NOTE: The coherent interface/client/reservation snapshot is saved and its actual
    > ModelsAsync/HealthAsync, synchronous mirrors and internal BeginCloseAsync signatures
    > are visible. Runtime contract/lifetime reviews are pending. Independent native tests
    > are unblocked on that snapshot; HTTP tests still follow the saved adapter/fixture
    > handoff. No lifecycle build, behavioral test or acceptance result is claimed.
    > The coherent OpenAI-compatible adapter and input-only lifecycle fixture/Python bridge
    > are also saved; both native test files are now unblocked. c16 additionally owns only
    > scripts/check_csharp_package.py and tests/test_csharp_packaging.py for the isolated
    > public async/sync lifecycle consumer, preserving existing generation/metadata controls.
    > All new source/test/package scopes remain subject to cold review and root execution.
    > Root inspected the first native snapshot (five provider and two HTTP tests): it
    > establishes basic selection/filtering/overlap/fixture behavior but omits the pinned
    > cancellation, late-success/factory, close-broadcast, callback re-entry and timeout/
    > drain-fault controls. The full readiness-driven expansion is assigned in the same two
    > test files before acceptance; these requirements are not deferred pending findings.
    > Root's integration inspection found request Content-Type inserted into the wrong
    > .NET header collection and IsSuccessStatusCode rejecting valid 300–399 outcomes.
    > Empty-content header storage and the exact >=400 predicate are assigned with native
    > regression controls. Focused packaging checks passed 11/12; their one new source-shape
    > assertion mismatched a line break (`.tmp-tests/cat4-package-python-01.xml`). A bounded
    > formatting-only correction is assigned; no native lifecycle gate has run.
    > The focused packaging retry now passes 12/12 after that source-shape correction
    > (`.tmp-tests/cat4-package-python-02.xml`). Empty-content header storage and <400
    > status handling are saved and await bounded review/native execution. This Python
    > check does not compile or execute the package consumer.
    > Runtime/protocol static rereviews are closed, including atomic reservation rejection.
    > Root's narrow library build passes with zero warnings/errors. The first independent
    > Python bridge run failed before HTTP because the test used instance IDs as descriptor
    > IDs; the bounded fix uses fixture adapter plus alias without changing stimuli/oracles
    > (`.tmp-tests/cat4-lifecycle-python-01.xml`). Expanded native lifetime review remains
    > pending, so CAT.4b/CAT.4c stay unchecked.
    > Status audit found the expanded test assignment had ended after partial updates.
    > Completion is resumed with disjoint ownership: 04f owns only
    > ProviderLifecycleTests.cs; the independent HTTP test owner owns only
    > OpenAILifecycleTests.cs. Each must return one complete held snapshot and request
    > causal review before root runs the native gate. No source or assertion is relaxed.
    > Expanded-test rereview exposed a source cancellation-identity gap at the pool's
    > construction semaphore: its linked token can escape instead of the original public
    > caller token. A bounded internal identity-forwarding/wait-check correction is granted
    > in ProviderRegistry.cs and lifecycle AsyncClient call sites only; source callbacks'
    > OCE identities and existing generation defaults remain unchanged. Native execution
    > waits for this correction plus final sync/resolver re-entry and connected HTTP
    > inertness controls and their cold reviews.
    > The bounded identity correction is saved and the narrow library compile passes with
    > zero warnings/errors. ProviderLifecycleTests now includes the final resolver/captured-
    > Client re-entry, throwing-callback broadcast and client-close late-factory controls;
    > its final cold reviews are pending. Native behavior has not run yet.
    > The nested post-secret-option checkpoint now receives caller identity too; the source
    > owner audited gate, post-build and every post-resolver/before-factory owned check,
    > leaving callback awaits uncaught. HTTP tests are coherently held with exact public
    > token assertions, connected zero-to-positive spies and active-close read cleanup.
    > A final secret-option positive/negative identity regression and cold reviews precede
    > native compilation/execution.
    > Root's first whole-solution compile reached six test-only errors: ResolverChain
    > wrapping, ConcurrentQueue.Enqueue calls, an async handler return expression and
    > collection-empty analyzer assertions. The library and conformance projects compile;
    > both test owners have bounded mechanics-only corrections assigned. No native tests
    > ran and no behavioral assertion is relaxed.
    > Final source/lifetime/protocol/causal reviews are closed. The corrected solution
    > builds with zero warnings/errors and all 30 focused lifecycle tests pass
    > (`.tmp-tests/cat4-lifecycle-native-02/lifecycle.trx`). The strict original-token,
    > source-OCE identity and callback/disposal assertions remain unchanged.
  - [x] CAT.4c: root native/Python/package gates pass, retaining original cancellation and
    exception facts, immutable result snapshots and unchanged all-102 observations.
    > NOTE: The corrected whole solution compiles with zero warnings/errors. The first
    > focused native lifecycle batch passes 27/29; retained TRX is
    > `.tmp-tests/cat4-lifecycle-native-01/lifecycle.trx`. One test incorrectly awaited
    > cancellation callbacks before initiating close; readiness is now signalled after
    > registration while callback-result assertions remain strict. The other exposed a
    > real public HTTP caller-token leak through the reservation link. Scoped identity
    > propagation plus native catch adaptation and async/sync token regressions are
    > assigned without blanket source-OCE remapping. Broader native regression waits.
    > The final full native regression now passes 304/304 unit tests and 93/93 conformance
    > tests, including every frozen inventory-ordered case. TRX files are under
    > `.tmp-tests/cat4-native-01/`. Release-manifest and both published report SHA-256 values
    > remain unchanged. Full workspace/fresh package verification is running before CAT.4c
    > acceptance; no clean-revision checkpoint is claimed yet.
    > Final acceptance supersedes intermediate holds: all 18 full workspace steps pass in
    > 106.7s, including 304 unit/93 conformance tests and fresh isolated package execution at
    > `.tmp-tests/nuget/run-_8oysfi6/`. Gate log: root command
    > `4f5ead1c-4a73-4190-9ba0-d3746b62ed2c`. CAT.4 is accepted; the clean committed
    > revision checkpoint remains CAT.5.
    > NOTE: Independent Python lifecycle bridge now passes 1/1 with unchanged fixture and
    > assertions (`.tmp-tests/cat4-lifecycle-python-02.xml`); focused packaging checks pass
    > 12/12. Archive validation and fresh isolated local-feed consumer restore/build/run
    > pass under `.tmp-tests/nuget/run-_j7boxpj/`, including public async/sync Models/Health
    > and actual prebuilt discovery facts. This is dirty-tree development evidence, not a
    > clean-revision checkpoint. Expanded native lifetime tests/reviews and full regression
    > remain required before accepting CAT.4.
- [ ] **CAT.5 — Docs and checkpoint.** c16 updates the C# SDK/porting/reference/task guides
  and exact compiled offline examples for implemented catalog/capability/lifecycle APIs.
  Root reconciles inventory status and both execution plans after reviews. Gate: strict
  docs build, exact displayed-source execution, full workspace, unchanged frozen assets,
  explicit source commit and clean-revision NuGet consumer; only then check SDK.4a.
  > NOTE: The stable saved public API permits disjoint docs/example authoring while CAT.4
  > reviews and native test expansion finish. c16 owns new CatalogExample.cs and
  > LifecycleExample.cs, the existing Program.cs runner and existing guide/reference pages.
  > No new navigation, workspace command, duplicated C# snippets or support-policy claim
  > is needed. All displayed source must execute through the existing offline example
  > command; CAT.4/CAT.5 acceptance and the source commit remain gated on root validation.
  > The held docs/example snapshot passed static review. Root's first exact example command
  > stopped at CatalogExample.cs:13 with a Catalog namespace/type ambiguity before running
  > any example; a type-qualification-only correction is assigned.
  > The corrected exact offline example command now passes. Strict MkDocs build passes at
  > `.tmp-tests/cat5-site-01/`; root verified all 15 rendered C# blocks across six pages
  > match their executed source files (line-ending/final-newline normalization only).
  > Full workspace, frozen-asset verification, source commit and clean-revision package
  > qualification remain pending; CAT.5 is not accepted yet.
  > Full workspace, fresh dirty-tree package and frozen-asset hash verification now pass.
  > Only the explicit source commit and clean-revision package qualification remain.

## Resume

Current resume point: CAT.4c/CAT.5 full workspace and checkpoint qualification. All source,
lifetime/protocol/causal reviews are closed; the solution builds without warnings, all 30
focused lifecycle tests and the full 304-unit/93-conformance regression pass. The frozen
manifest and published reports are unchanged. Python lifecycle bridge, focused
packaging checks, exact offline examples, strict docs/rendered-source comparison and the
dirty-tree isolated package consumer pass. All 18 workspace steps passed; resume CAT.5
source commit/clean-revision qualification. Accepted source checkpoint remains SDK.3 at
`04dfa37231f26f5c72b7215afd747c47de4e6d19`, with the clean-revision NuGet consumer passing.
SDK.4b's user-approved explicit external retrieval in C# remains separate from these
metadata steps; dependency selection and the exact opt-in API are still open in the main plan.
