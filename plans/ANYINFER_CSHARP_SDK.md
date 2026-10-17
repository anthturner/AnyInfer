# Python-aligned AnyInfer C# SDK

Resume from the first unchecked box. This is the active plan for SDK expansion; the
completed language-neutral foundation plans remain historical records for their frozen
core-generation proof. The coordinator alone owns Git and shared build/test execution.

## 1. Authorization and destination

On 2026-10-17 the user requested a C# SDK that a Python AnyInfer developer can readily
understand and port an application to. The user selected:

1. **Full Python library parity, delivered in phases.** CLI applications, the demo UI,
   sidecar deployment frontends, and the separate store/shared/confidential add-on packages
   require their own decisions; the core SDK's existing integrations with them still need
   explicit entries in the parity inventory.
2. **Same concepts and type names, normal C# conventions.** Preserve domain vocabulary,
   defaults, behavior, configuration keys and error meaning. Use PascalCase members,
   asynchronous `Task`/`ValueTask`, `IAsyncEnumerable`, `CancellationToken`, and deterministic
   disposal. Do not copy Python runtime mechanics into .NET.
3. **Draft the plan, then implement; align proof names now.** The unpublished proof API
   can change; do not accumulate forwarding aliases solely to preserve its incidental names.

Reference checkpoint: `199c3f833e568334b629edd7d89f41a3b76efe2a`. Python is under
`src/python/anyinfer/`; C# is under `src/csharp/AnyInfer/`. Python remains the supported
product implementation while SDK milestones are incomplete. The existing local NuGet
identity is `AnyInfer` / `0.1.0-proof`, with version in `src/csharp/Directory.Build.props`.
Neither this request nor this plan authorizes a registry upload, a versioned public release,
an upstream contract claim without evidence, or pretending that unported features work.

## 2. Governing decisions

### Behavioral authority

- Read `AGENTS.md` and the relevant sections of `DESIGN.md` before each subsystem.
- Use actual Python source, public documentation, and tests at the reference checkpoint
  for the SDK inventory. DESIGN's illustrative signatures can be older than code.
- `specification/core-generation.md`, its release manifest and existing corpus stay frozen.
  Preserve all 102 released case observations. C# type names may change without changing
  those JSON observations. Do not rewrite expected values to accommodate regressions.
- Broader equivalence requires new, versioned behavioral profiles and input-only native
  observations. Python and C# execute independently; neither calls the other to implement
  SDK semantics. Python can be used by repository build-time data generators and verifiers.
- Baseline updates are deliberate: record the new Python source revision and inventory
  diff. No claim of parity against an unspecified moving branch.

### Public API

- The public root namespace is `AnyInfer`; subordinate namespaces follow concepts
  (`Providers`, `Config`, `Credentials`, `Capabilities`, `Context`, `Local`, `Events`,
  `Testing`, etc.). Framework-specific integrations may use separate optional assemblies.
- Align `GenerationResult` -> `Generation`, `GenerationTiming` -> `Timing`,
  `RepairOptions` -> `Repair`, `RetryPolicy` -> `Retry`, and `GenerationStream` ->
  `AsyncStream`. The current C# `(providerId, model)` `Target` becomes `ResolvedTarget`;
  Python's unresolved `Target` is a string, not another incompatible object model.
- Preserve `provider:model` parsing at the first colon, case rules, model suffixes,
  instance aliases, and catalog aliases when the corresponding phase is implemented.
  `Route.Targets` remains an immutable sequence of unresolved strings. `ResolvedTarget`
  stores the exact resolved provider instance/model and nullable `ViaAlias`; explicit v0
  targets have `ViaAlias == null`. Do not change duplicate-target identity by confusing
  catalog provenance with provider-instance identity. Add `ToString()` -> `provider:model`.
- Model names alone do not establish parity. Include request defaults, unknown/null
  distinctions, immutable snapshots, validation/error timing, stream event ordering,
  retries, cleanup, and concurrent client behavior in migration tests.
- C# exceptions use the conventional `Exception` suffix with a documented one-to-one
  semantic mapping to Python `*Error`. Error categories and wire/config spellings remain
  shared. Do not flatten auth/rate-limit/protocol/transport failures into indistinguishable
  generic failures.
- Python `Text` cannot declare a C# property also named `Text`. Use the public type `Text`
  with `Value` for its literal text and document this language-required member mapping;
  other text-bearing types can retain their natural `Text` property. Do not introduce a
  redundant inheritance hierarchy merely to work around this naming restriction.
- Keep one lazy async execution path. Buffered generation drains the same stream. The sync
  `Client` is a facade with a lifetime-bound execution context and cannot fork orchestration.
- Common call shapes need equivalent convenience overloads: prompt or messages, target or
  route, request objects, schema/repair/sampling, and per-call cancellation. Overload ambiguity
  and explicit-vs-default precedence must have tests.

### SDK foundations

- Start from the proven native core and BCL HTTP adapter. Do not replace it with a Python
  process, sidecar dependency, or official vendor SDK abstraction.
- Provider descriptors and `ProviderSettings` own construction/configuration. The client
  owns cached adapter instances; aliases identify instances independently of engine IDs.
  Custom adapters remain supported. Initial built-ins are deterministic fake and explicit
  OpenAI-compatible chat; other existing Python providers follow the provider milestone.
- Config stays JSON format version `1`, with its existing snake_case field spellings,
  precedence, size/UTF-8/type/duplicate rules and secret hygiene. Loading config is inert.
  Until a feature is implemented, a supplied active setting for it must fail with an
  actionable unsupported/configuration error; never silently ignore requested policy.
  Demo-only inert keys follow Python's documented loader behavior.
- Credentials remain references (`env://`, literal, custom resolvers and later platform
  stores). Resolve lazily, keep secrets out of repr/errors/events, register redaction before
  any diagnostic can contain them. Loading config must not resolve secrets or open sockets.
- Retain `net8.0` and the existing pinned SDK for initial milestones. Do not promise new
  target frameworks or OS support without CI evidence. Package/runtime support policy is a
  distinct final SDK qualification decision, not an accidental metadata change.
- The proof's BCL-only limit is not an excuse to implement an incomplete general JSON
  Schema validator. When broader parity needs dependencies, select minimal native .NET
  libraries using official documentation, record license/size/semantic coverage, and update
  package validation deliberately. Keep optional integrations optional. Do not add vendor
  SDK dependencies simply to avoid translating a documented protocol.
- Preserve core ownership of routing, validation/repair, usage, telemetry, context and
  policies. Adapters translate. Context collection stays app-owned; local acquisition stays
  out of adapters; embedding fallback preserves embedding-space safety.

## 3. Execution and gates

Each implementer owns disjoint paths and the named checklist boxes, re-reads this plan
immediately before marking them, and records deviations as `> NOTE:` lines beside the box.
Do not edit another owner's work or any Git state. New API tests must use actual native
behavior rather than asserted booleans manufactured by the implementation.

Targeted checks run per coherent slice; only one owner runs builds, restore/pack or heavy
test suites at a time. Root runs `workspace check` before each completed source checkpoint.
Use a fresh ignored `.tmp-tests` pytest cache where the host's default cache has ACL issues.
Native commands run from `src/csharp` so `global.json` is effective. The package verifier
already copies that pin into its isolated consumer directory.

Public SDK docs describe implemented behavior and limitations; they never reference this
plan. The parity inventory records remaining work. Preserve previous conformance reports
as historical evidence, and qualify any new report against a clean committed executable.

**Documentation is part of each SDK milestone.** On 2026-10-17 the user explicitly required
the docs site to include the new C# syntax when the work is done. Use the existing MkDocs
language tabs to show Python and C# for the same task where both implementations support it.
Add a discoverable C# SDK entry, a porting guide and clearly language-labeled reference
coverage; a contributor-only packaging/proof page does not satisfy this requirement.
Examples must use actual current public APIs and explicit disposal/cancellation conventions.
Compile and run the same C# example text used by the site against offline fake providers in
CI; a separate hand-maintained test that merely resembles a snippet is insufficient.
Keep Python examples and generated Python API reference intact. Each new C# feature's
documentation ships with that feature rather than being deferred to the final parity audit;
clearly label features still unavailable in C# and avoid showing future APIs as working.

## 4. Milestones

### SDK.0 — Inventory and reviewed execution contract

- [x] **SDK.0a** Record the user's scope, naming and implementation decisions and immutable
  reference checkpoint. Gate: scope is explicit in sections 1–2 above.
- [x] **SDK.0b** Create `plans/CSHARP_SDK_API_PARITY.md`: inventory actual root exports and
  public subsystem entry points from `src/python/anyinfer/__init__.py`, public `__all__`
  modules and published API references. Map every group to the milestones below; list
  platform/optional integration dependencies and Python-only constructs with their native
  C# equivalent. Include a machine-auditable root export checklist to prevent silent omissions.
  Gate: no public root export is unassigned; excluded frontend/add-on surfaces are explicit.
  > NOTE: Completed against baseline `199c3f833e568334b629edd7d89f41a3b76efe2a`. Static AST verification found 235 literal root exports, 235 inventory entries, no missing/extra/duplicate names. All SDK feature entries remain planned; implementation status is unchanged.
- [x] **SDK.0c** Independent plan critique against current source/specification and all user
  decisions. Correct blockers before dependent edits. Gate: recorded bounded review closure.
  > NOTE: Cold review closed same-slice consumer migration, all-five-field timing semantics,
  > private frozen-event projection, target identity and connected lazy configuration spies.
  > Root verified the 235-export inventory independently; SDK.11c is a final audit, not a
  > substitute for assigning known features. Review: Traycer `csharp-sdk/sdk-plan-review`.

### SDK.1 — Public vocabulary and generation call shapes

- [x] **SDK.1a** Align public types in `src/csharp/AnyInfer/{Models,GenerationEvent,
  GenerationStream,AsyncClient}.cs` and all native dependents with section 2. Split oversized
  models into concept files if helpful. Migrate runtime, tests and conformance source uses;
  do not keep obsolete aliases. Give `Text` its `Value` member; keep message helper factories
  `Message.User`, `Message.System`, `Message.Assistant`. Add `ResolvedTarget.ViaAlias` with
  null for explicit targets. Gate: whole C# solution builds with zero warnings; no old public
  proof-only type names remain except historical documentation/fixtures.
  Migrate the embedded public consumer in `scripts/check_csharp_package.py` in this same
  slice, with focused `tests/test_csharp_packaging.py` updates where required. Do not leave
  the repository's mandatory package gate pointing at removed types between checkpoints.
- [x] **SDK.1b** Align public streams with Python's `StreamEvent`, `TextDelta`, `UsageUpdate`,
  `TimingMark`, `AttemptFailed`, `StreamEnded` vocabulary. Preserve real timing/entry capture,
  terminal result and lazy single-consumer/early-close/cancellation behavior. Timing marks
  are centrally observed, not fabricated from expected data. Extend `Timing` with actual
  monotonic `StartedAt`, nullable `FirstTokenMs`, actual `TotalMs`, nullable
  `OutputTokensPerS`, and defensively copied immutable `Phases` mapping names to milliseconds
  (`IReadOnlyDictionary<string, double>`), matching `types/results.py`. Phases are actual
  provider-reported sub-timings; the current adapter protocol supplies none, so an empty map
  is correct until that protocol expands. Do not invent phase facts from public timing marks.
  Unknown token counts or missing/zero decode intervals yield unknown
  throughput; never invent a rate. Preserve the released timing-presence projection.
  Gate: event-order/result/cancellation tests and the unchanged all-102 development run pass.
  Use this private conformance translation, with native capture supplying provenance:

  | Previous C# event | New public event | Unchanged released JSON observation |
  | --- | --- | --- |
  | `AttemptStartedEvent` | `TimingMark("attempt_start", actual AtMs)` | `timing_mark: attempt_start` |
  | `FirstTokenEvent` | `TimingMark("first_token", actual AtMs)` | `timing_mark: first_token` |
  | `TextDeltaEvent` | `TextDelta` | text/coalescing unchanged |
  | `UsageEvent` | `UsageUpdate` | usage_update unchanged |
  | `AttemptFailedEvent` | `AttemptFailed` with `Record` | attempt_failed unchanged |
  | `StreamEndedEvent` | `StreamEnded` | terminal result unchanged |

  Keep event `AtMs` relative to the current entry/attempt, not a previous route's elapsed
  time. Internal entry ordinals/roles can remain retained instrumentation; they are not a
  reason to expose a second set of public timing events. Migrate the package consumer's
  event pattern in the same slice.
- [x] **SDK.1c** Add prompt/message and target/route convenience overloads to `AsyncClient`
  over one request-normalization path; retain explicit request usage. Match Python's actual
  defaults and explicit override precedence; validate conflicting target/route arguments.
  `AsyncStream.Result` must throw an actionable `InvalidOperationException` until a successful
  terminal result exists, like Python's result property; internal observation can use a
  separate nullable accessor. Add `CollectAsync(CancellationToken)` to drain the same lazy
  source and return that terminal result; do not permit concurrent/double consumption.
  Gate: external
  public-API-only generation/stream/repair/fallback examples pass without direct core access.
  > NOTE: Accepted with SDK 8.0.425: zero-warning solution build, 8/8 focused migration tests,
  > 17/17 workspace steps, 172/172 unit tests, 93/93 conformance tests including all 102 cases,
  > and the isolated package consumer all passed; bounded source reviews closed.
- [x] **SDK.1d** Verify the already-migrated package consumer in
  `scripts/check_csharp_package.py`, its focused tests and C# migration tests for renamed
  types and terminal events. Update any existing documented C# syntax affected by these
  renames in this same checkpoint. Gate: fresh local-feed
  consumer, archive inspection and full workspace check pass; commit explicit paths.
  > NOTE: Root inspected the successful 17-step workspace log, including native solution
  > tests, all-102 observation coverage, strict docs build and the package-only consumer.
  > The existing contributor C# examples contain no removed SDK.1 symbols. The dedicated
  > SDK/porting pages and executable language tabs remain assigned to SDK.3b.

### SDK.2 — Provider settings, credentials and shared configuration

- [ ] **SDK.2a** Introduce immutable `ProviderSettings`, `ProviderDescriptor`, public
  collision-safe `ProviderRegistry`, setup metadata, canonical provider/instance identity and
  lazy lifetime-owned adapter construction. Reference `_client/providers.py`, `registry.py`,
  `providers/base.py`; keep low-level custom registration available. Add fake and existing
  OpenAI-compatible built-ins through descriptors, with injectable handler tests. Gate:
  duplicate/alias/laziness/concurrency/disposal/unknown-provider tests and real fake HTTP calls.
- [ ] **SDK.2b** Implement `Credentials` resolver interfaces/chain, env/literal/custom forms,
  redaction registry and bounded diagnostic snapshots. Reference `credentials/`, `redaction.py`,
  `errors.py`. Add structured C# configuration/credential/auth/rate-limit/transport/protocol
  error types with preserved native-inner/cancellation semantics. Gate: planted secrets never
  appear in errors, object string representations, telemetry or failed-config output; missing
  credentials cause no dispatch and external cancellation still propagates.
- [ ] **SDK.2c** Add inert `AnyInferConfig` load/loads/dump/dumps equivalents under `Config`,
  with shared format v1 JSON spelling and explicit unsupported-setting handling. Reference
  `config/__init__.py`, `config/`, schema and Python configuration tests. Implement providers,
  headers/options, default route/retry/repair and descriptor field validation first; handle
  identity aliases, disabled entries and no-side-effect parsing. Gate: shared JSON examples
  round-trip in both languages and invalid/unknown/oversize/credential-shaped fields fail.
  Use counting credential resolvers, adapter factories and HTTP handlers attached to the
  real client path: load/loads/dump/dumps, client construction and unadvanced stream creation
  must leave all counts at zero. A positive actual iteration must increment those same spies,
  proving that the inertness test did not merely observe disconnected doubles.
- [ ] **SDK.2d** Connect settings/config to `AsyncClient` defaults and instance pools. Keep
  file I/O outside client construction unless a caller explicitly invokes the config loader.
  Gate: one equivalent Python/C# configured generation app runs against local fake servers,
  including credential references, instance aliases, repair, fallback and cleanup.
  Include the positive iteration control for resolver/factory/transport counts and assert
  lazy cancellation/configuration failures occur before any unintended HTTP dispatch.

### SDK.3 — Sync facade and first SDK migration milestone

- [ ] **SDK.3a** Add `Client` and `SyncStream` wrapping the async implementation with one
  lifetime-owned execution context. Support concurrent callers and early stream disposal,
  propagate original exceptions/cancellation and prevent synchronization-context deadlocks.
  Reference `_client/sync_client.py`; do not port asyncio mechanics literally. Gate: bounded
  concurrency tests under a hostile synchronization context, early-close and lifetime checks.
- [ ] **SDK.3b** Add public consumer examples and a Python-to-C# migration guide covering
  construction, messages, generation/streaming, schemas, repair, routes, config, credentials,
  errors and disposal. Document implemented feature coverage, including JSON Schema subset
  until SDK.4. Add `docs/guides/csharp-sdk.md` and `docs/guides/python-to-csharp.md`, wire them
  into `mkdocs.yml`, and add Python/C# syntax tabs to affected existing quickstart/task guides
  and language-labeled reference pages. Wire the exact compiled/offline example source into
  CI and package readme. Put reusable public sample source under `examples/csharp-sdk/`;
  include that same source in the site and compile/execute it through the native C# phase
  or isolated package consumer. The current `tests/test_docs_examples.py` gate is Python-only
  and cannot by itself establish that C# snippets work. Keep generated Python mkdocstrings
  reference separate from C# reference generation. Gate: docs-check/strict docs-build and
  native snippet execution pass;
  no examples require a custom provider adapter or internals access for a supported built-in
  flow. Preserve documented Python syntax, configuration and install behavior.
- [ ] **SDK.3c** Review the complete first SDK milestone, run full workspace plus package
  consumer, and checkpoint. Gate: SDK.1–3 boxes complete, all existing conformance preserved,
  baseline parity inventory updated; no blanket full-library parity claim.

### SDK.4 — Catalog, capability provenance, discovery and general schema support

- [ ] **SDK.4a** Port `Sourced`, provenance ranks, `ModelCapabilities`/operation capabilities,
  catalog/default assets, alias resolution and model discovery/health lifecycle using
  `types/capabilities.py`, `catalog/`, `capabilities/`, `providers/base.py`. Reuse shared data
  assets through build inputs without importing Python runtime code. Gate: alias resolution,
  unknown-vs-false facts, overrides and model-kind filtering match Python on shared fixtures.
- [ ] **SDK.4b** Select/test a native general JSON Schema implementation against Python's
  supported dialect, schema coercion/ref/format/error behavior and local-only resolution
  policy. Preserve frozen v0 validation exactly through an explicit profile boundary where
  necessary. Add `SchemaSpec`, richer result validation and typed-result deserialization
  conveniences without a new wire contract. Gate: common-schema corpus plus malformed,
  recursive/ref, numeric, extraction/repair and remote-fetch refusal controls in both runtimes.
- [ ] **SDK.4c** Port model/token discovery, capability probes and configuration setup metadata
  incrementally from `capabilities/probes*`, `registry.py`, catalog APIs. Probe/network work
  remains explicit opt-in. Gate: fake/cassette discovery/probe conformance, no probing during
  ordinary config parse, full workspace/package validation.

### SDK.5 — Events, manifest, accounting and request policies

- [ ] **SDK.5a** Port payload-private typed observer events and dispatch, logging/JSONL sinks
  as explicit opt-in, immutable `RunManifest` projections and versioned serialization from
  `events/`, `manifest.py` and `manifest/` if present. Gate: observer and manifest facts agree,
  redaction/privacy tests pass and default execution performs no telemetry I/O.
- [ ] **SDK.5b** Define a separate shared accounting profile (the previously deferred M3),
  preserving unknown usage, failed/cancelled attempts, repairs and aggregate operation cost.
  Port `Usage` merge/normalization, pricing/estimation, token-estimator interfaces, budgets,
  `SpendLedger`, `SpendStore`, `SpendPolicy`, pacing and reservation concurrency from current
  Python modules/tests. Gate: native Python/C# accounting corpus and concurrent reservation,
  cancellation/release, precision/unknown-price controls; never infer unknown spend as zero.
- [ ] **SDK.5c** Connect shared timeout, cache/spend/rate/context policies to the native
  request path without duplicating provider orchestration. Gate: precise policy precedence,
  pre-dispatch refusal, retry/repair budget and ledger/manifest consistency tests.

### SDK.6 — Embedding, reranking and operation-neutral routing

- [ ] **SDK.6a** Port `EmbeddingRequest`, `EmbeddingResult`, `EmbeddingVector`, `EmbeddingSpace`,
  `RerankRequest`, `RerankDocument`, `RerankResult`, `RankedItem` and their operation protocols
  from `types/operations.py`, `_client/async_client.py`, `_client/sync_client.py`. Lifecycle
  is shared, operation interfaces optional; no fake generation method on retrieval providers.
  Gate: fake adapters implement independent operations and async/sync API examples agree.
- [ ] **SDK.6b** Port per-operation defaults, retry/health, batching of embedding inputs,
  usage and embedding-space fallback refusal. Never mix rerank scores across attempts.
  Gate: shared operation corpus covers order/indices/dimensions/unknown metadata and unsafe
  cross-space fallback rejection before the backup request.
- [ ] **SDK.6c** Add supported OpenAI-compatible embedding/rerank wire adapters only where
  existing Python contracts define them, following the provider procedure. Gate: cassette/
  fake-server tests, public consumers, manifest/accounting consistency, full workspace.

### SDK.7 — Rich generation, tools and multimodal input

- [ ] **SDK.7a** Port typed image/document/audio/video, tool calls/results/specs, reasoning,
  citations/server-tool events, logprobs and provider-option passthrough from `types/` and
  provider wire contracts. Keep visible answer text separate from reasoning and tool data.
  Gate: streaming reconstruction, first-content timing, unsupported-input and bounded/private
  payload tests; ordinary text flows remain unchanged.
- [ ] **SDK.7b** Port bounded `RunToolsAsync`/sync facade, typed function registration and
  JSON argument validation, cancellation and tool-error behavior from `_client/tools*`.
  Tools are caller-approved functions, not an agent planner. Gate: shared tool-loop traces,
  max-round/call limits, malicious/invalid args and no-double-execution controls.

### SDK.8 — Provider breadth and reusable adapter certification

- [ ] **SDK.8a** Inventory every builtin descriptor and `CompatPreset` in `providers/` into
  the parity matrix, including aliases, discovery, operations, auth and connection settings.
  Port compatible preset data once through a reviewed data-generation boundary, then dedicated
  dialects in contract-sized batches. Gate each batch on `contracts/NEW-PROVIDER.md` and
  existing contract snapshots; no provider marked complete solely because chat text works.
- [ ] **SDK.8b** Port dedicated adapters and optional auth bridges in the inventory, with
  declared-vs-implemented operation validation. Use optional assemblies for external identity/
  SDK requirements; fail clearly when unavailable. Gate: every supported operation passes
  cassette and fake-server certification, provider docs and no silent connection-setting drops.
- [ ] **SDK.8c** Expose `AnyInfer.Testing` conformance helpers for third-party adapters without
  shipping internal frozen-driver implementation or test-framework runtime dependencies in
  the core package. Gate: an external custom-adapter project certifies through public helpers.

### SDK.9 — Context preparation, cache and history

- [ ] **SDK.9a** Port pure context ranking/selection/representation/packing/history and
  tuning from `context/`, plus `ContextRequest`, estimates and fit gates. No filesystem walker
  in the reducer. Gate: common deterministic context-envelope/budget/selection corpus.
- [ ] **SDK.9b** Port opt-in distillation, semantic ranking, request-path compaction and
  cache placement using already-implemented operation/accounting surfaces. Gate: bounded
  call counts, cancellation, unknown cost, tool-pair integrity and exact input privacy.

### SDK.10 — Native local runtime lifecycle

- [ ] **SDK.10a** Port `local/` hardware/backends, tuning, recommendation and endpoint
  discovery with explicit platform support. Gate: mocked OS probes plus genuine supported
  host evidence; unavailable capabilities are not labeled passing platform support.
- [ ] **SDK.10b** Port catalog/runtime/model acquisition, pinned verification, resumable
  atomic/sharded downloads and app-owned stores. Keep binaries/weights out of NuGet. Gate:
  corruption/path containment/restart/cancellation controls and package-content validation.
- [ ] **SDK.10c** Port supervised loopback `llama-server`, process-tree termination,
  readiness/shutdown/reuse and public local APIs. Gate: bounded fake-child lifecycle tests
  on each supported CI OS and opt-in real-runtime integration evidence.

### SDK.11 — Remaining core library integration surfaces

- [ ] **SDK.11a** Port sessions/reuse, bounded arena/evaluate/compare, benchmark/verification,
  provider batch jobs and measurement stores from the inventory. Keep persisted evidence
  stores explicit, opt-in and separate from routing decisions. Gate: operation/fan-out ceilings,
  aggregate accounting, deterministic selection, persistence/version and cancellation tests.
- [ ] **SDK.11b** Port MCP tools/list+tools/call over stdio and streamable HTTP using the
  existing contract; maintain supervision and approval boundaries. Port optional OTel/keyring/
  tokenization integrations using explicit .NET counterparts or documented platform limits.
  Gate: protocol fixtures, disposal/secret handling, telemetry-union coverage, optional-assembly
  missing-dependency errors; no remote sampling/resources/prompts expansion.
- [ ] **SDK.11c** Reconcile every inventory entry, including ancillary exported helpers and
  platform-specific APIs. Add precise language-equivalent mappings for reflection/decorators,
  paths, exceptions and Python-only runtime constructs. Gate: no unassigned/deferred SDK item
  silently counted as implemented; remaining genuine platform exclusions are user-visible.

### SDK.12 — SDK qualification and delivery

- [ ] **SDK.12a** Publish a compiled C# API reference and executable Python-to-C# cookbook
  for every core integration journey. Update DESIGN/product/docs boundaries only to the
  achieved support level; no plan links in public docs. Audit earlier milestones' language
  tabs, SDK entry, migration guide and reference against the final API rather than deferring
  all C# syntax documentation to this stage. Gate: doc coverage/links/site build, all examples
  offline runnable and actual parity inventory agrees with published claims.
- [ ] **SDK.12b** Qualify target frameworks, OS/runtime matrix, dependency licenses, package
  and symbols payload, source metadata and external consumers. Extend native CI deliberately
  for SDK support, preserving Python packaging and release behavior. Gate: full workspace,
  cross-platform native suites, shared profiles and fresh package-only consumer pass.
- [ ] **SDK.12c** Independently review SDK completeness against the pinned Python baseline
  and obtain any separate release/publication authorization. Gate: all prior boxes complete
  or explicitly renegotiated; clean source checkpoints and qualified evidence retained.

## 5. Resume and evidence log

Current resume point: **SDK.2a–SDK.2d**, beginning with the provider/configuration/credential
API and ownership contract. SDK.1 passed the full 17-step workspace gate on 2026-10-17
(172 unit tests, 93 conformance tests including the all-102 development run, and an isolated
NuGet consumer). Checkpoint the explicit SDK.1 paths, then repack from that committed
revision before starting the next implementation wave. Keep source ownership disjoint
and serialize compilation; publish no updated conformance report from a dirty working tree.
