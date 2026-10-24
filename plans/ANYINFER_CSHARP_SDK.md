# Python-aligned AnyInfer C# SDK

**Resume from the first unchecked box in the bounded
[foundation and SDK alignment leaf](SDK_FOUNDATION_ALIGNMENT.md).** On 2026-10-24 the user
requested a fresh parity/foundation audit, accurate multi-SDK documentation, gap tracking,
and an initial burn-down. This supersedes the branch-handoff pause for that bounded work.
SDK.8a remains the provider implementation resume point and requires a researched binding
brief; no next provider is selected. The completed language-neutral foundation work remains
historical evidence for the frozen core-generation profile. The coordinator alone owns Git
and shared build/test execution.

> NOTE: The user subsequently authorized autonomous continuation through the remaining
> burn-down until Python and C# are both usable SDKs with matching features and strategies
> under predominantly similar native conventions. After ALIGN.3, proceed to the next
> evidence-backed remaining SDK slices without a per-slice implementation prompt. Existing
> explicit semantic differences stay visible for resolution/qualification; no missing
> feature or unverified behavior is silently counted as parity. Separate publication,
> immutable-release and data-authority gates remain in force.

**Retired execution leaves:** completed child-plan names in historical notes below identify
their retired records at source checkpoint
[`015d09341df6dfd6bb1850578f71e4996f73a99b`](https://github.com/anthturner/AnyInfer/blob/015d09341df6dfd6bb1850578f71e4996f73a99b/plans/ANYINFER_CSHARP_SDK.md).
They are historical evidence, not local files or current execution instructions.

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
  and explicit-vs-default precedence must have tests. A constructed route wins over target
  when both are supplied, matching the actual Python client.

### SDK foundations

- Start from the proven native core and BCL HTTP adapter. Do not replace it with a Python
  process, sidecar dependency, or official vendor SDK abstraction.
- Provider descriptors and `ProviderSettings` own construction/configuration. The client
  owns cached adapter instances; aliases identify instances independently of engine IDs.
  Custom adapters remain supported. The first configured builtin is explicit
  OpenAI-compatible chat, exercised with deterministic offline HTTP fixtures; other existing
  Python providers follow the provider milestone. Python's core has no builtin `fake`
  descriptor: its fake OpenAI server is testing infrastructure, not a provider identity.
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
  > NOTE: On 2026-10-23, after trust/callback experiments exposed concrete differences,
  > the user selected native .NET TLS: use platform certificate validation, document custom-
  > trust differences from Python, and reject unsupported active settings. Do not reproduce
  > the selected Python/OpenSSL verifier or add a separate crypto runtime for this slice.
  > This permits a documented TLS semantic exception; it does not permit ignoring requested
  > policy, accepting unrelated/invalid certificates, disabling hostname/EKU checks during
  > enabled verification, or claiming new OS support without evidence. Python and frozen v0
  > behavior remain unchanged. The bounded connection contract and implementation gates
  > remain open; the earlier scratch probes are feasibility evidence only.
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
  defaults and explicit override precedence; validate argument shapes.
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

- [x] **SDK.2a** Introduce immutable `ProviderSettings`, `ProviderDescriptor`, public
  collision-safe `ProviderRegistry`, setup metadata, canonical provider/instance identity and
  lazy lifetime-owned adapter construction. Reference `_client/providers.py`, `registry.py`,
  `providers/base.py`; keep low-level custom registration available. Add the existing
  OpenAI-compatible builtin through descriptors, with injectable fake HTTP handler tests. Gate:
  duplicate/alias/laziness/concurrency/disposal/unknown-provider tests and real fake HTTP calls.
  > NOTE: Initial settings/metadata/pool source and independent public tests are saved.
  > Accepted after bounded source/lifetime reviews and the full 18-step workspace gate:
  > SDK 8.0.425, 222 native unit tests and 93 conformance tests passed. Lazy construction,
  > alias binding, cancellation/waiter ownership and disposal use actual native controls.
- [x] **SDK.2b** Implement `Credentials` resolver interfaces/chain, env/literal/custom forms,
  redaction registry and bounded diagnostic snapshots. Reference `credentials/`, `redaction.py`,
  `errors.py`. Add structured C# configuration/credential/auth/rate-limit/transport/protocol
  error types with preserved native-inner/cancellation semantics. Gate: planted secrets never
  appear in errors, object string representations, telemetry or failed-config output; missing
  credentials cause no dispatch and external cancellation still propagates.
  > NOTE: Corrected source review closed typed classification, Unicode scalar bounds,
  > Python/.NET JSON redaction forms, exact schemes and meaningful safe snapshots.
  > Independent native tests passed, including original cancellation/native-inner identity,
  > scalar redaction bounds, error classification and safe diagnostic snapshots. Platform
  > keyring integration and credential refresh remain explicitly outside this slice.
- [x] **SDK.2c** Add inert `AnyInferConfig` load/loads/dump/dumps equivalents under `Config`,
  with shared format v1 JSON spelling and explicit unsupported-setting handling. Reference
  `config/__init__.py`, `config/`, schema and Python configuration tests. Implement providers,
  headers/options, default route/retry/repair and descriptor field validation first; handle
  identity aliases, disabled entries and no-side-effect parsing. Gate: shared JSON examples
  round-trip in both languages and invalid/unknown/oversize/credential-shaped fields fail.
  Use counting credential resolvers, adapter factories and HTTP handlers attached to the
  real client path: load/loads/dump/dumps, client construction and unadvanced stream creation
  must leave all counts at zero. A positive actual iteration must increment those same spies,
  proving that the inertness test did not merely observe disconnected doubles.
  > Accepted with the supported active v1 subset and explicit refusal of unimplemented
  > policies. Connected parse/serialize/client/stream controls and bounded file/error tests
  > passed; no full Python configuration or connection-policy parity is claimed.
- [x] **SDK.2d** Connect settings/config to `AsyncClient` defaults and instance pools. Keep
  file I/O outside client construction unless a caller explicitly invokes the config loader.
  Gate: one equivalent Python/C# configured generation app runs against local fake servers,
  including credential references, instance aliases, repair, fallback and cleanup.
  Include the positive iteration control for resolver/factory/transport counts and assert
  lazy cancellation/configuration failures occur before any unintended HTTP dispatch.
  > The shared input-only configured generation app passed independently in Python and
  > C#: two primary failures, fallback, invalid backup response, schema correction, final
  > result/usage and owned resource cleanup. Both replay the same raw HTTP response bytes.

#### SDK.2 implementation contract

> NOTE: Python source inspection corrected two illustrative assumptions: no core `fake`
> descriptor exists, and `default_route` serializes only a target list, never a retry block.
> Use native fake HTTP fixtures and preserve the shared JSON shape. This changes no frozen
> case, Python behavior or user scope. SDK.1 checkpoint: `c40fbba1369866960599e193041d8ffc6b37f860`.
> A further source audit corrects SDK.1's both-arguments rejection: Python honours an explicit
> Route over target. SDK.2 must migrate the convenience-call oracle and inherit client policy
> for a target override; the earlier checkpoint's stricter provisional rule is not parity.

The following contracts settle routine implementation choices for SDK.2. Source owners
must report a real conflict rather than silently changing a dependent public signature.

**Public construction and metadata (SDK.2a/2d)**

- `ProviderSettings` lives in root `AnyInfer`, with constructor arguments in this order:
  `string providerId, string? baseUrl = null, string? apiKey = null,
  string? apiVersion = null, IReadOnlyDictionary<string,string>? headers = null,
  JsonObject? options = null, double timeoutS = 120,
  HttpMessageHandler? transport = null, string? alias = null`.
  Provide matching readonly PascalCase properties, `InstanceId`, and `Of` with the same
  arguments. Normalize provider/alias IDs by trim, invariant lowercase and underscore to
  hyphen. Reject blank IDs/aliases and nonpositive/nonfinite timeout. Copy dictionaries;
  tagged JSON values are already immutable. Safe `ToString` never includes credential,
  header or option values. `Transport` is an explicit nonserialized test seam, like Python;
  the caller owns it until a successfully constructed adapter adopts it. Never instantiate
  a handler during parsing/client construction just to prove laziness.
- In `AnyInfer.Providers`, `ProviderConfig` carries resolved adapter-facing settings:
  `ProviderId` (the instance identity), `EngineId`, `BaseUrl`, resolved `ApiKey`, `ApiVersion`,
  immutable `Headers`/`Options`, `TimeoutS`, `Transport`. Its public constructor accepts
  `ProviderSettings settings, string engineId, string? resolvedApiKey,
  JsonObject? resolvedOptions = null`; safe `ToString` excludes all values above.
- `ProviderDescriptor(string id, string displayName,
  Func<ProviderConfig,CancellationToken,ValueTask<IProviderAdapter>> factory,
  IEnumerable<string>? aliases = null, ProviderSetupSpec? setup = null,
  string? defaultBaseUrl = null, bool requiresBaseUrl = false,
  IReadOnlyDictionary<string,StructuredOutputProfile>? modelCapabilities = null,
  int? maxRepairAttempts = null)` defensively copies metadata. Public properties use
  `Id`, `DisplayName`, `Factory`, `Aliases`, `Setup`, `DefaultBaseUrl`, `RequiresBaseUrl`,
  `ModelCapabilities`, `MaxRepairAttempts`. Capabilities remain honest v0 subsets here;
  broader provenance/operations follow SDK.4/6/8.
- `SetupField(string key, string label, string kind = "text", bool required = false,
  string? helpText = null, string? placeholder = null, string? envVar = null,
  bool advanced = false, string? defaultValue = null, IEnumerable<string>? choices = null)` and
  `ProviderSetupSpec(IEnumerable<SetupField>? fields = null,
  string modelSelection = "manual-only")` are immutable declarative metadata. Reject
  duplicate field keys, invalid kinds and contradictory required/advanced/default facts.
  Use Python's actual kind spellings and choice invariants from registry.py, never `select`
  as a new JSON/setup dialect; no callback runs for validation.
  Secret setup options are resolved through the same central chain before factory use.
- `ProviderRegistry(IEnumerable<ProviderDescriptor>? descriptors = null)` is a descriptor
  registry, not a client pool. Expose `Register`, `Get`, `Has`, `Descriptors`,
  `NormalizeProviderId`, and static `CreateDefault()`. Canonical IDs and aliases share one
  collision namespace. Register atomically or fail without partial alias installation.
  A client snapshots descriptors, so later registry mutation cannot alter existing clients.
- The default registry initially contains only `openai-compat`, aliases
  `openai-compatible`/`oai-compat`, no default URL, required `base_url`, optional secret
  `api_key`, manual model selection, and no claimed structured capabilities/repair ceiling.
  Supplied `api_version` or unsupported construction options fail clearly for this builtin;
  custom descriptor factories may support their own declared settings. No provider-specific
  `if` chain in the core or config parser. No catalog alias or other provider is invented.
- The configured OpenAI-compatible path uses the provided API base exactly, appending only
  `/chat/completions`; `/v1` belongs to the caller's base URL, not a heuristic. Existing
  frozen fixtures already supply `/v1` and stay unchanged. Require an absolute HTTP(S) base
  without userinfo/query/fragment in this bounded builtin. Optional API key means omit auth;
  nonempty resolved key means bearer auth. Case-insensitive custom headers override defaults,
  including Authorization and Content-Type, matching Python. Header/type validation happens
  without logging values; real errors attribute `Provider` to the configured instance ID.
  Preserve raw-byte caps, incremental SSE/DONE, narrow native exception mapping and cleanup.
- Main public client constructor:
  `AsyncClient(IEnumerable<ProviderSettings>? providers = null,
  ProviderRegistry? registry = null, ResolverChain? resolver = null,
  Route? route = null, Repair? repair = null)`.
  `AsyncClient.FromAdapters(IEnumerable<ProviderRegistration> providers)` preserves the
  public low-level custom-adapter entry point. Keep only the existing **two-argument**
  internal registration/clock constructor for frozen execution; migrate all one-argument
  registration callers, including the package consumer and public migration tests, to
  `FromAdapters` in this checkpoint. Do not introduce ambiguous `new AsyncClient([])`
  overloads. `AsyncClient.FromConfig(AnyInferConfig config, ProviderRegistry? registry = null,
  ResolverChain? resolver = null)` forwards its providers/route/repair without I/O.
- A constructed per-call Route wins, including when target is supplied. Otherwise a target
  replaces only targets and inherits the client's Retry/HealthGate/HealthTtlS; otherwise use
  the default route. Missing all three is a configuration error during StreamAsync call
  construction, matching Python's eager request coercion. Explicit `Repair(0)` disables a
  client repair default; nullable repair inherits.
  Explicit typed request routes remain authoritative. Keep one normalized execution path.

**Lazy pool and ownership (SDK.2a/2d)**

- Rename internal `Core.ProviderRegistry` to `ProviderPool` to disambiguate the public
  descriptor registry. Preserve a prebuilt-registration mode for frozen callers.
- Configured instance IDs are normalized alias or provider ID. Reject duplicate instance
  IDs and an instance alias that shadows any registered engine/descriptor alias. Same-engine
  distinct instances have separate credentials, adapters and health identity. Explicit
  `instance:model` keeps `ResolvedTarget.ViaAlias == null`; catalog provenance comes later.
  Parse at the first colon and preserve the current explicit-target model trim/suffix.
  Resolve descriptor spelling **before** indexing settings: without a distinct explicit
  instance alias, the key is the canonical descriptor ID. Thus settings supplied as
  `oai-compat` retain their base URL/credentials when targeted as `openai-compat`, and two
  such spellings cannot configure the same engine twice. Preserve an explicit distinct
  instance alias; an alias equal to its own canonical engine is the no-alias case.
  ProviderSettings.InstanceId itself is the normalized declarative spelling, like Python;
  the pool's canonical bound settings/ProviderConfig/ResolvedTarget carry execution identity.
  This deliberately avoids Python's observed engine-alias settings-loss edge, rather than
  duplicating that bug. Add a causal alias-spelled-settings/base-URL-survival test.
  Reject reuse of one non-null Transport handler reference by multiple configured instances
  at construction, before adopting any handler; no shared-handler lease is promised.
- Descriptor lookup/default settings are inert. A known unconfigured engine can use default
  settings lazily, like Python; a required missing base URL fails only when reached. Invalid
  duplicate/collision metadata can fail during construction without invoking user factories.
- Separate target resolution from adapter construction so deduplication and health skips
  never create unused adapters. Await the adapter only for an actual selected attempt,
  before `AdapterInvocationBoundary` creates a native entry. Missing credentials/config
  produce no fabricated adapter call/capture entry/HTTP send.
- Per-instance async gates serialize first construction. Do not share a `Lazy<Task>` bound
  to the first caller's cancellation or detach background factory tasks. The gate owner
  awaits the factory with linked caller/client-lifetime cancellation; failed/cancelled builds
  are not cached. A waiting uncancelled caller can build after the owner releases. A
  cooperative factory cancelled by client disposal must be joined; an adapter returned
  despite cancellation is disposed without adoption. No semaphore disposal races.
  A waiter's gate wait uses **its own** caller/client-lifetime token: cancelling that waiter
  detaches only that wait and cannot cancel, adopt, dispose or poison another caller's
  construction. Add readiness-gated tests for blocked owner plus cancelled waiter (owner
  succeeds/cache remains), and cancelled owner plus uncancelled waiter (fresh build succeeds).
- Client disposal first signals lifetime cancellation, closes/joins active streams/builds,
  then disposes each adopted adapter exactly once by reference identity. Construction after
  closing is rejected. Unused settings do not fabricate resources or assume ownership of
  an unadopted external handler. A custom factory owns cleanup of resources it creates if
  it throws before returning; the builtin cleans its own partial-construction failures.
- Preserve timeout override presence through request normalization. Choose actual per-entry
  `request.TimeoutS ?? settings.TimeoutS ?? 120` before the entry boundary is created.
  Keep the existing 1 MiB default response cap and explicit request override; do not invent
  a ProviderSettings response-cap field absent from Python. Retries and correction entries
  get fresh existing per-entry limits. Frozen prebuilt mode keeps prior limits/error fields.

**Credentials, redaction and errors (SDK.2b)**

- `AnyInfer.Credentials.ICredentialResolver` exposes `bool Handles(string reference)` and
  `ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default)`.
  `Handles` is a side-effect-free scheme query; resolution is async-first for native vaults.
  `ResolverChain(IEnumerable<ICredentialResolver> resolvers)` exposes `Handles`, thread-safe
  `Add(resolver, bool first = true)`, `ResolveAsync(string? reference, CancellationToken = default)`
  returning `ValueTask<string?>`, and `CreateDefault()`. The chain centrally registers every
  returned secret before factory/diagnostic use. Its default order is keyring, env, literal;
  explicit custom resolvers can precede these. No assembly/plugin discovery in this slice.
- `EnvResolver`, `LiteralResolver`, `KeyringResolver` implement that interface. Empty/blank
  reference means null; trim the reference like Python. Missing/empty env and unhandled URI
  schemes raise `CredentialException`; they never become a bearer token. Keyring recognizes
  `credential://` but raises an actionable unavailable-in-this-build exception until SDK.11b.
  Caller cancellation and existing `AnyInferException` propagate without remapping a native
  cancellation into configuration/provider failure. No credential TTL/refresh API yet;
  record it as outstanding parity work rather than claiming cache semantics implement it.
- Root `RedactionRegistry` has `Register`, `Redact`, `Count`, `Clear`; root static `Redaction`
  exposes process-global `Registry`, `RegisterSecret`, `Redact`. Thread-safe longest-first
  exact replacement uses `[redacted]`, minimum length six Unicode scalar values,
  raw/JSON escaped/percent/plus/
  base64/colon-basic/base64url forms from Python `redaction.py`. Do not globally redact
  generation text; sanitize library diagnostics/snapshots and secret-bearing object repr.
- Preserve the existing base exception constructor/fields and `NativeInner` identity.
  Make `ProviderException` extensible. Add `ConfigException`, `CredentialException`,
  `AuthException`, `RateLimitException`, `ModelNotFoundException`, `ContextLengthException`,
  `TransportException`, `StreamProtocolException`, `ProviderUnavailableException` and
  `UnsupportedInputException` with shallow semantic inheritance. Config/credential default
  to phase configure; provider subclasses preserve category/retry/status/phase facts.
  A central internal classifier may map existing native categories, including timeout as a
  transport subtype, without changing released JSON observations. Do not catch arbitrary
  fatal/native exceptions or lose caller OCE identity to obtain a nicer class name.
  Config/Credential constructors take `string message, string? provider = null,
  string? detail = null, string? hint = null, Exception? nativeInner = null`.
  Provider subtype constructors take `string message, string? provider = null,
  string? phase = null, bool? retryable = null, double? retryAfterS = null,
  int? httpStatus = null, string? detail = null, string? hint = null,
  Exception? nativeInner = null`; omitted phase/retry use their Python semantic defaults.
  Credential owner supplies `internal static ProviderException Create(...)` on ProviderException
  with the existing full base-constructor signature for runtime/adapter classification;
  its category/status/native-inner arguments remain authoritative, including timeout.
- Library-created messages/details pass redaction; detail is bounded to 512 Unicode scalar values,
  hints are redacted, exception ToString redacts the rendered native chain. `Snapshot()`
  returns immutable `ErrorInfo(TypeName, Provider, Phase, Retryable, HttpStatus, Detail)`
  using bounded/redacted `Detail ?? Message`; the legacy Detail property retains null when
  absent. Provider/Phase/Category diagnostic fields are redacted while preserving nulls.
  The snapshot carries no exception/credential object. An explicitly accessed NativeInner remains
  the original native exception, not a claim that third-party exceptions can be rewritten.
  Settings/ProviderConfig/AnyInferConfig ToString never dumps credentials, headers/options.

**Configuration (SDK.2c)**

- `AnyInfer.Config.AnyInferConfig(IEnumerable<ProviderSettings>? providers = null,
  Route? route = null, Repair? repair = null, int formatVersion = 1)` exposes copied
  `Providers`, `Route`, `Repair`, `FormatVersion`. Static `Loads(string text,
  ProviderRegistry? registry = null, ResolverChain? resolver = null, string source = "<string>")`
  and `Load(string path, ProviderRegistry? registry = null, ResolverChain? resolver = null)`;
  instance `Dumps(bool comments = false)` and `Dump(string path, bool force = false)`.
  Load is explicit caller-requested file I/O; client construction never opens a config path.
- Strict UTF-8 and at most 1 MiB (bound file reads before whole-file allocation); JSON root
  object; format_version absent defaults to integer 1, bool/float/other versions fail.
  Preserve Python's ordinary JSON last-property-wins behavior, including duplicate object
  keys; reject duplicate normalized **provider instances**, not a new JSON dialect.
- Supported active root keys: `providers`, `default_route`, `repair`, `format_version`.
  `_comment` and Python's five demo-owned keys are accepted and ignored without invented
  type checks. Known unimplemented active blocks (`operation_routes`, `context`, `history`,
  `cache`, `observers`, `arena`, `arenas`, `mcp`) raise actionable unsupported configuration
  errors when supplied; unknown keys fail. Do not emit or silently apply future policies.
- Provider `enabled` defaults true and must be bool; false skips the entire entry before
  id/engine/setup/unknown-field processing, like Python. Active id must be nonblank.
  Engine is adapter, legacy provider_id, or id; explicit adapter/provider_id conflicts fail;
  alias must normalize equal to id. Use actual Python truthiness/empty/null rules from
  `_parse_provider`, not guessed aliases. Resolve descriptor metadata only, never its factory.
- `values`/`options` null normalize to empty objects. Allowed values keys are declared setup
  fields plus base_url/api_key/api_version. Root direct fields override values, including
  explicit null/empty suppression. Explicit options win over promoted non-direct setup
  fields. Headers are string maps, timeout positive finite numeric (not bool). Unknown root
  provider/values fields fail with a bounded path-only diagnostic, never dump input values.
  Recognize but explicitly refuse supplied active limits/proxy/CA/mTLS policies in this
  initial slice; default verify:true and null absent-equivalent connection values may remain
  inert exactly as the Python loader normalizes them. Do not claim connection parity yet.
- Validate credential-reference schemes using side-effect-free Handles only; never call
  ResolveAsync. Builtin env/keyring references are syntactically accepted; an unknown scheme
  needs an explicitly supplied handler or is rejected. Never inspect the environment during
  parsing. An explicitly requested Dumps/Dump preserves literal credentials and references
  verbatim, as Python does; safe repr/errors must not conflate serialization with logging.
- default_route is null/empty array for none or an ordered nonempty-string list -> Route.
  There is no JSON retry block. repair is null for absent or a closed object max_attempts
  with Python's integer/nonnegative rules. Preserve presence of an explicit default repair
  block. Runtime custom retry/health policy is passed to AsyncClient; Dumps must explicitly
  refuse a programmatically supplied nondefault route policy instead of silently losing it.
- Dumps emits canonical shared provider identity/adapter/direct/header/options/timeout fields,
  two-space indented UTF-8 text ending newline; comments uses root _comment, never JSONC.
  Dump uses CreateNew unless force and never creates parent directories. Classify known
  JSON/UTF-8/config-file failures as bounded ConfigException, preserving native inner facts;
  no broad exception catch over custom callbacks/cancellation/fatal failures.

**Ownership and acceptance sequence**

- [x] **SDK.2 foundation wave:** runtime owner c708 owns ProviderSettings, Providers metadata/
  OpenAI adapter, Core pool/default integration and existing native callers; credential owner
  c16 owns Credentials/, Redaction.cs, Errors.cs, and package consumer migration. Independent
  tests owner 04f owns new ProviderSettingsTests/CredentialsTests plus its existing
  SdkMigrationTests FromAdapters migration. No shared plan lease while another owner edits.
  Gate: saved signatures agree, cold source/test reviews, guarded solution build and focused
  settings/credential/migration tests, then all frozen conformance and package consumer.
- [x] **SDK.2 configuration wave:** after the foundation handoff, c16 owns Config/; 04f owns
  ConfigTests and connected configured-app/lifetime tests. Add language-neutral JSON input
  controls separately from the frozen release corpus; native Python and C# each observe
  actual parsed configuration/generation. Do not use expected data to drive either runtime.
  Gate: shared subset round-trips, same connected spies prove zero parse/construct/unadvanced
  work and positive actual HTTP dispatch, cancellation/disposal/secret negatives pass.
  Use shared input-only `tests/fixtures/sdk-configuration-v1/configured-generation.json`
  (configuration, request/schema and per-instance raw HTTP scripts; no expected verdict).
  c16 owns that fixture and native Python `tests/test_sdk_configuration_parity.py`; 04f
  consumes it independently in ConfigTests.cs. Both must observe the same configured
  primary-failure/fallback/repair flow and resource closure without invoking the other runtime.
  > NOTE: Config review confirmed Python defers declared choice/generic secret-option
  > validation to use; only direct api_key reference admission belongs at parse time.
  > The first compile-only solution check used SDK 8.0.425 and stopped at five compiler
  > errors (nullable category and adapter yielding-catch/static context); no tests ran.
  > Owners have exact correction briefs. File reads remain bounded before allocation,
  > and arbitrary custom Handles faults must retain their original exception identity.
  > The corrected source has clean bounded reviews; native execution is still pending.
  > The first Python configured-app run stopped before generation on a test oracle:
  > default `Repair(1)` serializes as a present empty object. Correct that oracle and replay
  > real raw SSE response bytes for the streaming app in both runtimes before rerunning.
  > Those stimulus/oracle changes are saved. Whole-solution compilation found three
  > remaining direct-registration caller migrations; the exact internal-clock/public
  > FromAdapters fixes are saved, pending the next guarded solution build.
  > Final acceptance supersedes the intermediate failures above: the corrected solution
  > and complete native tests passed. Root inspected the 96.0s full workspace log
  > (`ab758585-c1eb-41eb-9cd4-79f666dd6ce9`): all 18 steps passed, including strict site
  > build, 222 native unit tests, 93 conformance tests, isolated NuGet consumption and six
  > executable example methods. Seven rendered C# blocks across six pages exactly match
  > their compiled source. Frozen release/report SHA-256 values remain unchanged.
- [x] **SDK.2 checkpoint:** update achieved syntax/docs, inventory limitations and exact
  execution evidence; root full workspace gate, commit explicit paths and repack clean
  revision. Update resume to SDK.3 only when SDK.2a–2d and these nested gates actually pass.
  > NOTE: Pull forward the implemented async portion of SDK.3b for this checkpoint:
  > source-controlled public examples under `examples/csharp-sdk/`, included verbatim by
  > MkDocs snippets in C# SDK/porting/reference pages and common-task language tabs. A
  > dedicated net8 executable invokes those same methods against offline HTTP stimuli;
  > append its execution to the SDK-pinned C# workspace phase (18 total workspace steps).
  > Keep package consumption as a separate existing check. Python source distributions
  > carry only the displayed `.cs` files for docs rendering, not a .NET developer checkout.
  > SDK.3b stays open for sync syntax and complete first-milestone documentation.
  > Committed explicit source paths as `b50459bc644cff95e9e50f97ba6dd61ae3e1ef46`.
  > The clean-revision NuGet verifier then packed, inspected, restored, built and ran its
  > isolated consumer successfully. Its package metadata binds that revision; no registry
  > upload or replacement of the historical frozen reports occurred.

### SDK.3 — Sync facade and first SDK migration milestone

- [x] **SDK.3a** Add `Client` and `SyncStream` wrapping the async implementation with one
  lifetime-owned execution context. Support concurrent callers and early stream disposal,
  propagate original exceptions/cancellation and prevent synchronization-context deadlocks.
  Reference `_client/sync_client.py`; do not port asyncio mechanics literally. Gate: bounded
  concurrency tests under a hostile synchronization context, early-close and lifetime checks.
  > NOTE: Initial source/test/docs handoffs are held, not accepted. The first library-only
  > compile stopped at a property-as-out compiler error. Cold reviews require correctly
  > scoped callback ownership, buffered wire-mode preservation, cancellable queue/Collect
  > waits, cancel-all-before-join cleanup and complete creation reservations before runtime.
  > The corrected solution builds with zero warnings/errors. The first focused run passed
  > 7/13 tests; remaining controls exposed incorrect timing-prefix/queue-capacity test
  > assumptions and one existing async missing-route exception mismatch. Python returns
  > ConfigError, so narrowly align the shared async refusal to ConfigException and migrate
  > its old native oracle; do not add facade-only error translation. Cancellation broadcast
  > must start lifetime and per-stream signals before awaiting any callback completion.
  > Final acceptance: zero-warning SDK 8.0.425 solution build and 24/24 focused sync/migration
  > tests passed. All cancellation signals are completed before token disposal; actual
  > UnsafeRegister callbacks also refuse self-disposal without blocking external close.
- [x] **SDK.3b** Add public consumer examples and a Python-to-C# migration guide covering
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
  > NOTE: Eight tracked source methods execute offline. Root verified all 11 rendered C#
  > blocks across six pages equal those exact source files; async/sync syntax and disposal
  > mappings are discoverable in SDK, migration, task and language-labeled reference pages.
- [x] **SDK.3c** Review the complete first SDK milestone, run full workspace plus package
  consumer, and checkpoint. Gate: SDK.1–3 boxes complete, all existing conformance preserved,
  baseline parity inventory updated; no blanket full-library parity claim.
  > NOTE: Final root workspace gate passed all 18 steps in 99.2s, including 238 native unit
  > tests, 93 conformance tests, strict docs rendering, package-only async/sync consumption
  > and the eight offline example methods. Retained log: `f52eb067-c941-466b-a00b-73e43a98456b`.
  > Bounded public/lifetime reviews are closed; frozen release/report digests are unchanged.

#### SDK.3 implementation contract

- Root accepted the native sync mechanism after the separate lifetime review at Traycer
  `foundation-execution/csharp-sdk/sdk-three-sync-mechanism-review`. Add root public
  `Client : IDisposable`, `SyncStream : IEnumerable<StreamEvent>, IDisposable`, and an
  internal client-owned execution/lifetime helper if needed. Only these new wrapper files
  belong to the initial source wave; async core/router behavior stays authoritative.
- `Client` has the same settings/registry/resolver/route/repair constructor as AsyncClient,
  static `FromAdapters(IEnumerable<ProviderRegistration>)`, and static
  `FromConfig(AnyInferConfig, ProviderRegistry? = null, ResolverChain? = null)`. It owns one
  AsyncClient for its entire lifetime. Add request, prompt and messages `Generate` and
  `Stream` overloads mirroring AsyncClient's exact optional parameter order/names, with
  synchronous Generation and SyncStream returns. Keep cancellation parameters. IDisposable
  is the native equivalent of Python close/context management; no obsolete proof aliases.
- All async execution and async cleanup dispatch on Task.Run/default TaskScheduler, then
  wait through GetAwaiter().GetResult at the synchronous boundary. Never run an async client
  per call, capture the caller's SynchronizationContext, duplicate routing, wrap native
  exceptions in AggregateException, or pass the caller token to the Task.Run wrapper so it
  can substitute its own cancellation before the real core runs.
  Generate overloads dispatch their matching AsyncClient.GenerateAsync overloads: prompt
  and messages use buffered wire mode, while explicit request.Stream remains authoritative
  exactly as in the async API. Do not implement convenience Generate through Stream(true).
- Preserve eager synchronous request/route validation: call inner StreamAsync before
  publishing a SyncStream. Reserve creation/operation ownership under the Client gate
  before doing caller enumeration, scheduling or publication; do not hold that gate over
  caller callbacks or blocking waits. Close marks/snapshots reservations atomically, signals
  cancellation outside locks and joins creation, active operations, streams and inner cleanup.
  If closing wins before publication, dispose the newly returned inner stream and refuse
  publication. No detached construction or late ownership adoption.
  Keep a creation reservation registered until its late cleanup/completion has finished;
  removing it before DisposeInner would let a concurrent close snapshot miss the join.
- SyncStream starts one async pump over that actual inner stream, using a bounded Channel
  of 256 events with FullMode.Wait. Every channel write is cancellation-aware. Cancel before
  joining on early stream/client disposal so an unconsumed full queue cannot deadlock. The
  pump finally closes the inner stream; disposal joins real cleanup and is idempotent.
  Link pump iteration/writes to stream close, actual caller cancellation and client lifetime.
  Client close signals every operation/stream before joining any, retaining cancellation
  callback failures while unconditionally completing all pump/inner/resource cleanup.
  Retain one consumer atomically (enumeration or Collect); Reset/second/concurrent consumers
  are unsupported. C# foreach disposal on an early break closes the underlying stream.
- Result is unavailable until the consumer receives StreamEnded, even if the producer has
  already completed. Collect drains the same single-consumer path. Preserve queued events
  before rethrowing an original terminal exception through ExceptionDispatchInfo; never
  expose ChannelClosedException or a Task-generated AggregateException in its place.
  Collect(token) must interrupt a blocked queue read and close/join on cancellation, not
  merely check the token after an event arrives. Explicit stream/client disposal ends
  subsequent MoveNext calls without leaking buffered events to the closed consumer.
  Intentional close cancellation is suppressed by close, ordinary reads preserve original
  failure identity, and actual cleanup failures propagate after all owned cleanup is joined.
  Do not rethrow a previously observed generation error as an unrelated client-disposal fault.
- Detect synchronous self-disposal from that client's active callback/execution context and
  refuse it before blocking on its own reservation; external/concurrent disposal still joins.
  A synchronous foreach consumer body after MoveNext returns is ordinary external caller
  code: disposing the parent client there must work normally. Do not retain the callback
  marker across returned consumer events or mistake consumer ownership for producer work.
  Do not introduce a shutdown timeout that abandons owned async work. Keep original external
  OCE identity and finish all other cleanup when one close/cancellation callback fails.
- Runtime owner c708 owns new `Client.cs`, `SyncStream.cs` and optional
  `Internal/SyncExecutionContext.cs`. Independent tests owner 04f owns new SyncClientTests.cs
  only. Public-only tests cover hostile SynchronizationContext, overlapping callers/streams,
  eager invalid arguments, result readiness, queued-prefix error identity, cancellation,
  257-plus unconsumed events then close, readiness-gated close-versus-creation, early iterator
  close/reuse, self-disposal refusal and exactly-once adapter disposal after all joins.
  No wall-clock sleeps or manufactured hook booleans; use real adapter/caller readiness.
- After the saved API handoff, c16 owns the package-consumer sync check plus tracked sync
  documentation methods and guide/tab updates. Execute the exact added source in the same
  offline example project; retain existing async methods and package/archive isolation.
  The full workspace remains 18 steps because the existing native examples command expands.
  Gate this wave with cold source/lifetime/test reviews, guarded solution/focused sync tests,
  exact native example execution, full workspace, explicit commit and clean-revision pack.

### SDK.4 — Catalog, capability provenance, discovery and general schema support

- [x] **SDK.4a** Port `Sourced`, provenance ranks, `ModelCapabilities`/operation capabilities,
  catalog/default assets, alias resolution and model discovery/health lifecycle using
  `types/capabilities.py`, `catalog/`, `capabilities/`, `providers/base.py`. Reuse shared data
  assets through build inputs without importing Python runtime code. Gate: alias resolution,
  unknown-vs-false facts, overrides and model-kind filtering match Python on shared fixtures.
  > NOTE: Detailed source ownership and gates are in `ANYINFER_CSHARP_SDK_CATALOG.md`.
  > CAT.0's bounded contract reviews are closed; CAT.1 pure capability types passed the
  > zero-warning solution build and all 7 focused tests. CAT.2 then passed 8 Python bridge
  > tests, 22 focused native tests, solution compilation and isolated package validation.
  > CAT.3 assembly/query integration passed its reviewed native and isolated-package gates:
  > zero-warning solution build, 274 native unit tests, 93 conformance tests including all
  > 102 cases, and 12 focused packaging tests. CAT.4a lifecycle contract/mechanism critiques
  > are closed; resume CAT.4b implementation.
  > SDK.4a remains unchecked until
  > the complete catalog, assembly, lifecycle, documentation and checkpoint gates pass.
  > Final acceptance supersedes the intermediate holds: all 18 workspace steps pass in
  > 106.7s, including 304 native unit/93 conformance tests and all 102 frozen cases.
  > The 15 rendered C# blocks match executed source; frozen manifest/reports are unchanged.
  > Source checkpoint `aca24ddf2097ca9a33ff33039a2285f0b0b0bdb7` is committed and its
  > clean-revision isolated package proof passes at `.tmp-tests/nuget/run-7xx9guja/`.
- [x] **SDK.4b** Select/test a native general JSON Schema implementation against Python's
  modern dialects and schema coercion/ref/format/error behavior. C# resolves internal and
  caller-registered schema references by default; external URL/file retrieval requires
  explicit opt-in. Preserve frozen v0 validation exactly through an explicit profile boundary where
  necessary. Add `SchemaSpec`, richer result validation and typed-result deserialization
  conveniences without a new wire contract. Gate: common-schema corpus plus malformed,
  recursive/ref, numeric and extraction/repair controls in both runtimes, plus C# default
  zero-retrieval and explicit-opt-in controls. Record the authorized default-policy difference.
  > NOTE: Source discovery found that the baseline Python validator does not configure a
  > local-only reference policy. The observed jsonschema 4.26.0 default can retrieve external
  > references through urllib before warning; the project dependency is jsonschema>=4.21,
  > not a fixed 4.26.0 pin. On 2026-10-17 the user selected explicit retrieval in C#:
  > internal/caller-registered references work by default; external URL/file retrieval
  > requires opt-in. Document this deliberate difference from Python. Do not change Python's
  > behavior. The dependency, exact opt-in API and semantic qualification remain open.
  > Dependency research is also open: current JsonSchema.Net binary releases carry a
  > maintenance-fee EULA, while NuGet lists the older net8-compatible 8.0.5 package as MIT.
  > Inspect versioned licenses/transitive dependencies and actual semantic fixes before
  > selection; no dependency has been added. Research is retained in Traycer
  > `csharp-sdk/sdk-four-schema-research`.
  > NOTE: After isolated native/Python probes exposed the dependency and semantic tradeoffs,
  > the user selected modern drafts first: Draft 6, 7, 2019-09 and 2020-12. Draft 3/4 remain
  > explicitly deferred and unfinished parity work for SDK.11c; do not claim their support.
  > The user also selected qualified native numeric/regex semantics with documented limits,
  > rather than reproducing Python floating arithmetic and regex syntax. Frozen v0 remains
  > exact. JsonSchema.Net 8.0.5 is the small MIT candidate being qualified; registry isolation,
  > full schema meta-validation, reference retrieval and diagnostics must pass before
  > production selection. No production dependency has yet been added.
  > The executable source/test/package ownership and remaining qualification gates are in
  > `ANYINFER_CSHARP_SDK_SCHEMA.md`. Requested/canonical resource aliases are proven in the
  > isolated bridge. Native regex handlers have no timeout; a bounded per-build extension
  > must be qualified or its limitation explicitly settled before production handoff.
  > Final qualification is accepted in that child plan: JsonSchema.Net 8.0.5 and its
  > four-package MIT graph are selected. Fresh owned compiled-metadata preprocessing
  > preserves native handlers and bounds regex matches without global mutation; all ten
  > final probe observations and independent contract/lifetime reviews pass. Begin SIG.1;
  > SDK.4b remains unchecked until production source/tests/docs/package gates pass.
  > Production gates now pass: 39 focused schema cases, 24 independent Python bridge cases,
  > 343 native unit/93 conformance tests and all 18 workspace steps in 114.6s. All 15
  > rendered C# source blocks match executed files; released hashes stay unchanged. Native
  > decimal comparison limits are controlled and documented. Source commit and clean-revision
  > package proof remain the final checkpoint before this box is checked.
  > Final acceptance supersedes the intermediate holds: source
  > `dbf82a949fca6ee7321b921233c0cda198b3a506` is committed and the clean-revision archive,
  > exact four-package/license/hash validation and isolated consumer restore/build/run
  > pass at `.tmp-tests/nuget/run-cgy2od91/`. Frozen assets and Python behavior are unchanged.
  > This checks only the user-approved modern/native scope; Draft 3/4 remain SDK.11c.
- [x] **SDK.4c** Port model/token discovery, capability probes and configuration setup metadata
  incrementally from `capabilities/probes*`, `registry.py`, catalog APIs. Probe/network work
  remains explicit opt-in. Gate: fake/cassette discovery/probe conformance, no probing during
  ordinary config parse, full workspace/package validation.
  > NOTE: Execution detail is in `ANYINFER_CSHARP_SDK_PROBES.md`. Python's four-feature
  > default includes TOOLS, so pull forward only the raw tool declaration/wire/delta
  > prerequisite from SDK.7a before publishing generation probes; do not reduce defaults.
  > Full rich generation/tool loops remain SDK.7, tokenizer/accounting SDK.5/11 and
  > embedding/rerank probes SDK.6. Setup metadata completes independently of execution.
  > Working-tree acceptance gates pass: all 18 workspace steps in 117.8s, 386 native
  > unit/93 conformance tests, three additional parallel native runs, exact 19 rendered
  > C# blocks and isolated package consumption. Required close/concurrency corrections
  > preserve source exception identity and prevent post-close publication. Final source
  > review closure, commit and clean-revision package proof precede checking this box.
  > Final independent source/lifetime reviews are closed; the clean-revision package
  > checkpoint is the remaining acceptance step.
  > Final acceptance: source `0fd3fb47cd08295537674aa23571dffcc9482888` is committed;
  > the clean-revision archive, exact dependency/license/hash graph and isolated consumer
  > restore/build/run pass at `.tmp-tests/nuget/run-m3_ozrcb/`. SDK.4c is complete for
  > generation probes/setup; the stated SDK.5/6/7/11 dependencies remain unfinished.

### SDK.5 — Events, manifest, accounting and request policies

- [x] **SDK.5a** Port payload-private typed observer events and dispatch, logging/JSONL sinks
  as explicit opt-in, immutable `RunManifest` projections and versioned serialization from
  `events/`, `manifest.py` and `manifest/` if present. Gate: observer and manifest facts agree,
  redaction/privacy tests pass and default execution performs no telemetry I/O.
  > NOTE: Detailed execution begins in `ANYINFER_CSHARP_SDK_EVENTS.md`. Native decimal
  > values and manifest JSON formatting are independently qualified before source work;
  > only the minimum Usage/Pricing value prerequisite is pulled forward from SDK.5b.
  > Accounting, ledgers and request policies remain unchecked until their own gates pass.
  > Acceptance: source `68d2cc06914aaa8539eb3cc5ee8d20acdbd2a906` passes all 18 workspace
  > steps in 108.1s, including 474 native unit tests, 93 frozen conformance tests, strict
  > docs, executable examples and isolated package consumption. The exact source revision's
  > five-archive/license/hash package closure and fresh consumer restore/build/run pass at
  > `.tmp-tests/sdk-five-clean-package/run-ybv82fp9/` with zero compiler warnings. All 102
  > frozen observations and released hashes remain unchanged. Accounting/request policies
  > are qualified separately below.
- [x] **SDK.5b** Define a separate shared accounting profile (the previously deferred M3),
  preserving unknown usage, failed/cancelled attempts, repairs and aggregate operation cost.
  Port `Usage` merge/normalization, pricing/estimation, token-estimator interfaces, budgets,
  `SpendLedger`, `SpendStore`, `SpendPolicy`, pacing and reservation concurrency from current
  Python modules/tests. Gate: native Python/C# accounting corpus and concurrent reservation,
  cancellation/release, precision/unknown-price controls; never infer unknown spend as zero.
  > Acceptance: `ANYINFER_CSHARP_SDK_ACCOUNTING.md` is complete at source checkpoint
  > cc989e84069f09cb985e4f82fa40514f1aad5ffe. The complete gate passes
  > all 19 steps in 127.8s, including 532 native unit tests, 93 conformance tests and
  > 42/42 shared accounting cases plus two native-only controls, with zero warnings.
  > Shared builtin HTTP controls pass in both runtimes. Clean-revision observations record
  > source_dirty=false at .tmp-tests/sdk-five-accounting-clean-observations/run-le4vrqx5/;
  > isolated package/dependency proof and fresh consumer pass with zero warnings at
  > .tmp-tests/sdk-five-accounting-clean-package/run-3ffa5_3w/. No version/publication change.
  > Python final usage and
  > ledger charges are winning-entry/completed-request only; failed retries and discarded
  > repair responses remain separate attempt facts. Pure policy/limiter foundations and
  > explicit accounting helpers precede SDK.5c automatic admission/transport wiring.
- [x] **SDK.5c** Connect shared timeout, cache/spend/rate/context policies to the native
  request path without duplicating provider orchestration. Gate: precise policy precedence,
  pre-dispatch refusal, retry/repair budget and ledger/manifest consistency tests.
  > NOTE: Source discovery confirmed a same-client transport ownership prerequisite:
  > discarding a late built-in adapter disposed the supplied handler reused by
  > a later build. `ANYINFER_CSHARP_SDK_TRANSPORT_OWNERSHIP.md` is now complete at source
  > `c7dc295d680fe51b39309fa7e17d65bf2cd7e307`: all 19 workspace steps, 538 native unit/
  > 93 conformance tests, then clean-revision accounting and isolated package proofs pass.
  > The request-policy execution checklist is `ANYINFER_CSHARP_SDK_POLICIES.md`; POL.0
  > contract reviews and POL.1–POL.4 raw-tool/cache/governor/admission/config gates are
  > clean (657 unit, 93 conformance, 70 focused policy/config/HTTP controls; Python
  > reference gates: four tool, 28 cache, 57 limiter/timeout and four admission controls).
  > Independent request-policy proof now passes 29/29 from fresh stamped public observers
  > with matching provenance and clean cold reviews. The coherent source and compiled
  > docs/package gates are closed. Root accepted source
  > `97e8937c281063582c282f313a35b91761293500` after all 20 workspace steps in 147.6s,
  > 681 native unit/93 conformance tests, preserved FrozenV0 102, then clean-revision
  > policy 29/29, accounting 42+2 and isolated package consumption with matching full
  > source metadata and source_dirty=false. The child plan records exact reports and
  > the cache-only environmental retry. No package publication/version bump. Resume SDK.6a.

### SDK.6 — Embedding, reranking and operation-neutral routing

- [x] **SDK.6a** Port `EmbeddingRequest`, `EmbeddingResult`, `EmbeddingVector`, `EmbeddingSpace`,
  `RerankRequest`, `RerankDocument`, `RerankResult`, `RankedItem` and their operation protocols
  from `types/operations.py`, `_client/async_client.py`, `_client/sync_client.py`. Lifecycle
  is shared, operation interfaces optional; no fake generation method on retrieval providers.
  Gate: fake adapters implement independent operations and async/sync API examples agree.
  > NOTE: The execution leaf is `ANYINFER_CSHARP_SDK_RETRIEVAL.md`. Its source-contract,
  > optional-protocol/ownership and raw-retention prerequisite maps have bounded cold
  > review closure. Domain/protocol and common-pool foundation now pass the zero-warning
  > solution build and all existing comparison profiles. The shared raw prerequisite
  > also passes (708 native unit/93 conformance). Connected public async/sync operations,
  > routing/batching, safety, accounting, manifests and joined lifecycle/deadline behavior
  > passed 55 focused controls, 780 unit and 93 conformance tests with all prior
  > Frozen/policy/accounting comparisons preserved. Public-seam mapping then found untested
  > response-cap, embedding-phase and error-projection gaps. Their bounded corrections and
  > independent controls now pass 63 connected / 788 unit / 93 conformance tests with prior
  > profiles preserved. The execution leaf's 6.0.3 profile is frozen after 32 literal cases,
  > 31 pure tests and closed source/oracle reviews. Resume independent observers and the
  > verifier; no actual retrieval comparison has run. SDK.6a stays
  > unchecked pending independent qualification and executed public consumer examples.
  > Recorder source authoring then found 24 cases with no literal target/route; both SDKs
  > refuse that construction. Leaf 6.0.3d reopens the input-byte freeze for explicit targets,
  > source review and pure validation. Generic observer/checker authoring continues, while
  > runtime acceptance is held; observers must not infer missing routing inputs.
  > Closure: source review, exact 24-field delta, unchanged schemas and all 32 pure tests
  > pass. Leaf 6.0.3d and the replacement input-byte freeze are accepted. Resume observer
  > authoring and checker corrections; runtime/consumer acceptance remains open.
  > A later source-found boundary contradiction requires exactly five literal input
  > changes: nullable unknown limits in four ceiling cases and explicit rerank cross-batch
  > opt-in in the upper-bound case. Source/saved-byte review, exact delta, unchanged schemas
  > and all 36 pure tests pass. Leaf 6.0.3e and its replacement byte freeze are accepted;
  > observer/checker runtime acceptance remains open.
  > Three missing literal second-failure steps in the split-failure corpus are also
  > corrected after source/saved-byte review, exact delta and all 39 pure tests. Leaf
  > 6.0.3f restores the byte freeze; SDK retry/defaults and equality are unchanged.
  > Retrieval shared proof now passes32/32 with zero mismatches after source-only
  > correction review, all78 focused Python controls and791 native unit/93 conformance
  > tests. Source/dirty/corpus stamps agree; profile bytes/equality policy remain frozen.
  > The native retrieval project and workspace step are registered; all68 workspace
  > controls pass. Public docs/examples and isolated package-consumer sources are held
  > for execution/review. Resume leaf6a.5D; parent SDK.6a/b remain unchecked until delivery
  > and clean-revision gates. SDK.6c provider research/bindings remain separate and open.
  > This evidence is dirty-worktree based on 2820ef2, not clean-revision acceptance. The shared
  > raw-retention default requires the minimal Generation.Raw prerequisite from SDK.7;
  > this does not complete the rich-generation milestone.
  > Public delivery review, examples and isolated package consumer now pass. Root's final
  > workspace run passes all21 steps in161.1s, with791 native unit/93 conformance cases,
  > accounting 42+2, policy 29 and retrieval 32 shared matches. An earlier stalled unit run
  > and separately reproduced factory-test ordering race are retained; the test-only
  > cancellation barrier passes independent review and20 repetitions. Resume source commit
  > and isolated clean-revision proof in the retrieval leaf before checking SDK.6a/b.
  > Source commit131c7aa is saved. Fresh Windows checkout finds4 existing manifest-golden
  > tests depend on raw-literal source endings; Render emits LF. A reviewed file-specific
  > LF checkout rule preserves their exact assertions. Clean acceptance waits for the
  > follow-up source checkpoint and fresh clean21-step gate; no product behavior changes.
  > a54f096 clean native/profile/package/docs gates pass; the Python suite finds one
  > generated manifest-schema LF byte contract also needing a file-specific checkout rule.
  > That canonical-generator repair changes no asset/assertion/runtime bytes in Git.
  > Final acceptance: clean checkpoint03f26fc88c7c96ff8272e99dadee8c6a26fa0616 passes all 21
  > workspace gates in 167.6s, 791 unit/93 conformance, 102 Frozen development observations,
  > retrieval 32, policy 29 and accounting 42+2. Observer source/dirty/corpus metadata agree
  > at source_dirty=false; package-only consumer, compiled examples and strict docs pass.
  > The retrieval leaf holds exact evidence and preserved failures; no publication/version
  > bump or SDK.6c provider-binding claim follows. Root records plan-only acceptance.
- [x] **SDK.6b** Port per-operation defaults, retry/health, batching of embedding inputs,
  usage and embedding-space fallback refusal. Never mix rerank scores across attempts.
  Gate: shared operation corpus covers order/indices/dimensions/unknown metadata and unsafe
  cross-space fallback rejection before the backup request.
- [ ] **SDK.6c** Add supported embedding/rerank wire adapters only where
  existing Python contracts define them, following the provider procedure. Gate: cassette/
  fake-server tests, public consumers, manifest/accounting consistency, full workspace.
  > NOTE: On 2026-10-22 the user authorized implementation of the reviewed TEI and
  > provider-propagation plans in parallel. `ANYINFER_CSHARP_SDK_TEI.md` owns native TEI
  > retrieval and Python requalification against pinned CPU 1.9.4 and exact model revisions.
  > The TEI leaf is complete at clean verified source
  > `af5d0d64840cb8ec81ecdcb92acb9a457958d814`: all 22 gates, preserved profiles,
  > public live calls and packed consumers pass. Other SDK.6c providers remain open.
  > On 2026-10-22 the user requested continued parity work. The next bounded lane is
  > `ANYINFER_CSHARP_SDK_VOYAGE.md`: a complete native Voyage embedding/rerank binding,
  > current documented wire facts, independent Python/native controls, and public
  > consumers. No released foundational asset changes; hosted live evidence is unverified.
  > Voyage is complete at accepted source `289f8427b29fd769110ad669bf44b86efcaeb623`:
  > all 22 primary gates, 844 unit/93 conformance tests, clean registered Python/C#
  > producers/aggregation, preserved shared profiles, Frozen 102 and packaged consumers.
  > Hosted Voyage traffic remains unverified; other SDK.6c providers remain open.
  > Continued on 2026-10-22 with `ANYINFER_CSHARP_SDK_JINA.md`: native text retrieval
  > plus evidence-backed v4/v5 task corrections in both SDKs. Current-schema research
  > is complete; all 22 primary gates and independent source/control reviews pass.
  > Jina is accepted at `a3b0cc785c723616d5e724f7f7b7b20f432ce647`: clean registered producers,
  > aggregation, prior shared profiles, source-stamped packages/examples and Frozen 102 pass.
  > All standalone retrieval-only descriptors are now ported. Remaining SDK.6c bindings
  > also require generation/batch; execute SDK.7a and relevant SDK.8 prerequisites before
  > returning to those bindings. SDK.6c remains unchecked; parity scope is unchanged.

### SDK.7 — Rich generation, tools and multimodal input

- [x] **SDK.7a** Port typed image/document/audio/video, tool calls/results/specs, reasoning,
  citations/server-tool events, logprobs and provider-option passthrough from `types/` and
  provider wire contracts. Keep visible answer text separate from reasoning and tool data.
  Gate: streaming reconstruction, first-content timing, unsupported-input and bounded/private
  payload tests; ordinary text flows remain unchanged.
  > NOTE: Accepted clean source b315ef73173b81ace643c41e95f4e6339db636b6 implements the
  > typed rich contract and generic chat media/logprob projection, including the documented
  > no-send document-URL/video refusals. The rich-generation leaf records independent
  > reviews, all 24 workspace steps, clean registered propagation, 43 rich matches,
  > preserved prior profiles and Frozen 102, source-stamped package consumers/examples
  > and strict docs. Dedicated provider dialects remain SDK.8; C# remains prerelease.
- [x] **SDK.7b** Port bounded `RunToolsAsync`/sync facade, typed function registration and
  callable argument binding, cancellation and tool-error behavior from `_client/tools*`.
  Tools are caller-approved functions, not an agent planner. Gate: shared tool-loop traces,
  round limits, malicious/invalid args and once-per-returned-entry execution controls.
  > NOTE: The rich-generation leaf records the actual Python baseline: callable argument
  > binding, max_rounds=8, sequential once-per-returned-entry dispatch, and final-round-only
  > results. Python has no separate total-call setting, arbitrary argument-schema enforcement
  > or ordinary-loop deduplication. Those parent gate phrases must not be used to claim
  > absent Python policies or introduce C#-only policies. The native API/reflection,
  > lifecycle and loop reviews are closed. Accepted source b315ef7... passes 21 focused
  > foundation/binding/loop/lifecycle controls and ten actual paired tool traces with
  > source_dirty=false. The final returned generation retains final-round accounting;
  > arena memoization and later integrations remain SDK.11a.

### SDK.8 — Provider breadth and reusable adapter certification

- [ ] **SDK.8a** Inventory every builtin descriptor and `CompatPreset` in `providers/` into
  the parity matrix, including aliases, discovery, operations, auth and connection settings.
  Port compatible preset data once through a reviewed data-generation boundary, then dedicated
  dialects in contract-sized batches. Gate each batch on `contracts/NEW-PROVIDER.md` and
  existing contract snapshots; no provider marked complete solely because chat text works.
  > NOTE: The first bounded execution leaf is `ANYINFER_CSHARP_SDK_PROVIDER_INVENTORY.md`:
  > complete deterministic declaration inventory before native preset runtime changes.
  > Actual Python graph has 106 descriptors and 129 operation bindings (103 generation,
  > 16 embedding, 5 rerank, 5 batch). All declared operations remain visible; completing
  > the inventory alone does not check SDK.8a or waive mixed-operation SDK.6c work.
  > Inventory-only acceptance is complete at source
  > 830673e56437a695ae26f579d7ca264139b7b0ba: 106 rows/129 bindings/49 source hashes,
  > all 24 held-source workspace steps, fresh clean --check plus 20 focused controls,
  > and independent bounded review pass. The prerequisite
  > `ANYINFER_CSHARP_SDK_PRESET_AUTH.md` is accepted at clean source
  > c3d0e9a0d26bd253d58620f4bca623c02fac3d85: researched Reka Bearer and Lemonade
  > optional-Bearer setup metadata, all five registered gates/aggregation, prior native
  > profile/package/example continuity and Frozen 102 pass with bounded independent review.
  > Native preset bindings and live verification remain absent. Resume the reviewed native
  > preset runtime/data boundary without checking SDK.8a or waiving mixed operations.
  > NOTE: Connection qualification and its plan-only reconciliation are now complete.
  > Shared redirect hardening is qualified at source4faf9ecb22206715e01f8bd2faff8a39defe5565,
  > tree44f6f2499762f11280badf16039034e35604fc4d. RDIR.8 plan-only reconciliation in
  > `ANYINFER_CSHARP_SDK_REDIRECTS.md` is independently reviewed and complete. Resume
  > SDK.8a researched registration from that qualified source.
  > NOTE: The first default-registration tranche is Cerebras only, tracked in
  > `ANYINFER_CSHARP_SDK_PRESET_REGISTRATION.md`. Its source checkpoint
  > `a51f58461416ed869a2f7d8699deb04903be0086`, tree
  > `094f2d6f19dcf7607d9b675c26f7f641c239728f`, passes all25 held-source checks and
  > the registered12-step clean C# gate with1113unit/93conformance, Cerebras4/redirect56,
  > five paired profiles, package/examples and Frozen102. Independent source, full and
  > clean reviews are bounded clean. Native registration is five/eight,121 memberships
  > pending; Python106/129 and86 generated rows are unchanged. CPR.6 plan-only
  > reconciliation is complete; this does not check SDK.8a or admit other presets.
  > Current/minimum controls, all25 held workspace steps and the clean12-step C# gate plus56
  > redirect controls pass with bounded independent review. Provider breadth remains open.
  > NOTE: The next bounded tranche, `ANYINFER_CSHARP_SDK_HYPERBOLIC.md`, is qualified at
  > executable `b4456054d0d3f6d79113d04714b5c8baf99f2518`, tree
  > `9fcf09fe47641d58d683466beadbabc29155055b`. It adopts only Hyperbolic's documented
  > endpoint migration and existing generation-row selection. Full25/4532 Python plus10
  > documented skips/1117 native unit/93 conformance and clean12 C# steps pass; actual
  > registered Python/C# producers and aggregate pass on the same clean source. Independent
  > receipt admission `add9cbb6...17e4e8` preserves wrapper-invalid evidence and proves the
  > exact root-only user-file boundary without rerunning gates or changing policy.
  > Native defaults are now6 descriptors/9 bindings/120 pending memberships; Python106/129
  > and86 generated rows stay unchanged. HYP.6 plan-only reconciliation is complete;
  > SDK.8a and all broader completeness gates remain open. Hosted traffic is unverified.
  > NOTE: The native SSE completion prerequisite in `ANYINFER_CSHARP_SDK_SSE_COMPLETION.md`
  > is qualified at executable `d388e6832c0436d9aae3f884ca753cff3837bf0e`, tree
  > `faf3154e8091a617902dfc1c97d4482886d4d881`. Clean EOF now follows existing Python
  > completion behavior; DONE still terminates early. This explicitly supersedes only
  > the historical native DONE-only proof choice, preserving all released assets.
  > Full25 passes 4,536 Python cases plus 10 documented skips, 1,130 native unit and
  > 93 conformance cases. Clean12 plus 134 focused cases (13 EOF completion), all five
  > paired profiles 42/29/32/43/10 and Frozen DEVELOPMENT102/0/0/0 pass with independent
  > actual evidence review. Root's 1,275 and selected checkout's 1,272 input maps are
  > individually stable; nine normalized functional bodies agree across checkouts.
  > The first clean attempt remains invalid after its extra Frozen output-path refusal;
  > a separate reviewed launcher fixes only that proof output location for the accepted
  > second run. Native6/9/120, Python106/129 and86 generated rows are unchanged.
  > SSE.6 plan-only reconciliation is independently reviewed and complete; no provider or upstream behavior claim
  > follows, and SDK.8a and all broader completeness gates remain open.
  > NOTE: Nscale's existing Python generation-row admission in
  > `ANYINFER_CSHARP_SDK_NSCALE.md` is independently qualified at executable
  > `952b678d2dc020075c09bc6f8d11e2879fc992bd`, tree
  > `f5ddbe6d8f12bb9c04ee2b84bb393800908593f8`, with exactly16 functional paths.
  > Full25 passes4,536 Python cases plus10 documented platform skips,1,135 native
  > unit/93 conformance; clean12 plus67 focused controls, package/examples, five
  > paired profiles42/29/32/43/10 and Frozen DEVELOPMENT102/0/0/0 pass. Actual
  > full/clean evidence reviews are bounded clean. Root1,278/selected1,275 maps
  > are individually stable; all16 normalized source bodies cross-match. Native
  > defaults are7 descriptors/10 bindings/119 pending memberships; Python106/129
  > and86 generated rows are unchanged. The metadata delta is provenance-only.
  > NSC.6 plan-only reconciliation is independently reviewed and complete. Exact upstream streaming, reasoning
  > values/history and hosted behavior remain unverified; no broader milestone closes.
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
  > NOTE: Standalone native context tuning is accepted at
  > `146fbabed9e1b9fbbd90fb8242c7ea1109e333a9`: 24 targeted native controls, 57 shared
  > observations plus one separate native boundary, full 27-step workspace and clean
  > 14-step native/package qualification pass. ALIGN.5c records the completion receipt;
  > the completed source checklist is pinned by `git show 146fbab:plans/SDK_CONTEXT_TUNING.md`.
  > Settings alone do not implement reducers, history, request policy or shared config.
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
  > NOTE: The 2026-10-24 audit is tracked in
  > [SDK/foundation alignment](SDK_FOUNDATION_ALIGNMENT.md). ALIGN.3 owns the executable
  > per-export evidence ledger; ALIGN.4 distinguishes frozen normative coverage from later
  > development profiles and existing build-time data ownership. All 235 root completion
  > rows remain open until their full assigned semantics pass.
  > NOTE: Explicit remaining schema work includes legacy Draft 3/4, deferred by the user
  > during SDK.4b qualification. Modern-schema support must not tick those semantics or
  > imply Python-identical numeric/regex behavior; the user approved documented native
  > differences for those semantics while preserving frozen v0.
  > Credential TTL/rotation/refresh left outstanding by SDK.2 is assigned here; the
  > SDK.6 retrieval contract explicitly excludes rotating-credential parity until then.
  > NOTE: Rich-generation review found both current Python Usage.merge/sum and native
  > counterparts omit server_tool_uses. Terminal generation separately attaches the
  > winning map after merge. Audit and settle the public merge/sum map contract in
  > both languages before final readiness; do not count the terminal fix as that work.
  > NOTE: The narrow Python object-representation correction is qualified at executable
  > 474a65e4e25541db3232c60c6d7c5c1b3df77837, tree
  > 605e229b948106e675384981a38b32398ffe2249. ProviderSettings/ProviderConfig repr now
  > includes only raw identity fields; stored values and literal config roundtrips remain
  > unchanged. All 25 held workspace steps, five clean-source Python controls, the exact
  > registered 12-step C# gate (1016 unit/93 conformance), five source-clean pairs,
  > package/examples and Frozen DEVELOPMENT102 pass. Independent evidence review is clean.
  > Proxy userinfo/client-certificate password registration and exception paths remain open;
  > native connection value types must preserve their existing identifier-only formatting.
  > This closes only object display, not SDK.11c, connection support or the broader audit.

### SDK.12 — SDK qualification and delivery

- [ ] **SDK.12a** Publish a compiled C# API reference and executable Python-to-C# cookbook
  for every core integration journey. Update DESIGN/product/docs boundaries only to the
  achieved support level; no plan links in public docs. Audit earlier milestones' language
  tabs, SDK entry, migration guide and reference against the final API rather than deferring
  all C# syntax documentation to this stage. Gate: doc coverage/links/site build, all examples
  offline runnable and actual parity inventory agrees with published claims.
  > NOTE: ALIGN.2 in [SDK/foundation alignment](SDK_FOUNDATION_ALIGNMENT.md) pulls forward
  > the stale overview/architecture correction and shared-foundation explanation. It does
  > not complete the compiled reference, full cookbook, platform qualification or this box.
- [ ] **SDK.12b** Qualify target frameworks, OS/runtime matrix, dependency licenses, package
  and symbols payload, source metadata and external consumers. Extend native CI deliberately
  for SDK support, preserving Python packaging and release behavior. Gate: full workspace,
  cross-platform native suites, shared profiles and fresh package-only consumer pass.
- [ ] **SDK.12c** Independently review SDK completeness against the pinned Python baseline
  and obtain any separate release/publication authorization. Gate: all prior boxes complete
  or explicitly renegotiated; clean source checkpoints and qualified evidence retained.

## 5. Resume and evidence log

**Current resume:** the user's 2026-10-24 parity/foundation request authorizes the bounded
[alignment leaf](SDK_FOUNDATION_ALIGNMENT.md), starting at its first unchecked box.
ALIGN.1–4 and ALIGN.5a–c are complete: docs, the executable 235-export ledger, evidence
map, catalog vocabulary and standalone context tuning are reconciled. ALIGN.5d next closes
the additive cache result projection; broader context ports remain open. Provider work still resumes
at SDK.8a with a separately researched binding. Existing SDK completion and release gates
remain open. The paragraph below records the superseded branch-preparation pause.

**Historical branch-preparation pause:** On 2026-10-24, branch preparation overrode the
first-unchecked-box convention. The committed plan-only baseline before that maintenance was B
`552abd2dde65217ca8b2fb35277270ba567167d6`, tree
`b736e72a820fff400cb464eebbda63a85fe3f815`; the last qualified source is A
`952b678d2dc020075c09bc6f8d11e2879fc992bd`, tree
`f5ddbe6d8f12bb9c04ee2b84bb393800908593f8`. That pause held further provider and SDK
implementation pending a separate resumption starting at
**SDK.8a further researched provider registration**. Inactive scratch/cache/build
cleanup is complete except the access-denied root `.pytest_cache`; all 22 individually
approved ancillary worktree entries were removed through Traycer. Git now lists only the
current checkout. The final pre-commit `workspace check` passed all 25 steps again:
4,536 Python passes plus 10 documented skips, 1,135 native unit passes and 93 conformance
passes. `plans/README.md` records the handoff state; this maintenance leaves the accepted
clean-source qualification and all open milestones unchanged.
NSC.6's plan-only reconciliation in `ANYINFER_CSHARP_SDK_NSCALE.md` is independently
reviewed and complete.
Nscale is independently qualified at executable
`952b678d2dc020075c09bc6f8d11e2879fc992bd`, tree
`f5ddbe6d8f12bb9c04ee2b84bb393800908593f8`: full25/4,536 Python plus10 documented
skips/1,135 native unit/93 conformance; clean12/67 focused; five paired profiles
and Frozen102 pass. Native defaults are7 descriptors/10 bindings/119 pending source
memberships. Python106/129 and86 generated rows are unchanged. Source qualification
is separate from the two-plan reconciliation record. Hosted behavior and the explicit
streaming/reasoning watchlists remain unverified. Inception and Upstage are research
only; no next provider is selected. SDK.8a, SDK.6c, SDK.8b–c, SDK.9–12 and235 API rows
remain open.

The earlier native SSE prerequisite is independently qualified at executable
`d388e6832c0436d9aae3f884ca753cff3837bf0e`, tree
`faf3154e8091a617902dfc1c97d4482886d4d881`: full25/4,536 Python plus10 documented skips,
1,130 unit/93 conformance; clean12/134 focused cases; five paired profiles and Frozen102
pass. The accepted second clean run preserves the first invalid output-path attempt.
That checkpoint aligns existing Python EOF behavior and registered no new provider.
Its native counts were6/9/120; Python106/129 and86 generated rows are unchanged. Exact upstream
framing/final-usage unknowns and typed reasoning-history gaps remain separate research
limits. HYP.6 plan-only reconciliation is complete.
Hyperbolic's endpoint migration and native generation registration
are qualified at executable `b4456054d0d3f6d79113d04714b5c8baf99f2518`, tree
`9fcf09fe47641d58d683466beadbabc29155055b`. All25 held-source checks, actual clean12-step
C# gate and registered Python/C# producers/aggregate pass; independent actual evidence
review and the separate root-file-boundary receipt are bounded clean. That checkpoint's native defaults were
6 descriptors/9 bindings/120 pending memberships. Python106/129 and86 generated rows remain
unchanged. The leaf `ANYINFER_CSHARP_SDK_HYPERBOLIC.md` is complete with bounded independent
consistency review; qualified executable identity stays separate from its two-plan record.
The earlier Cerebras source `a51f584` / tree `094f2d6` and CPR.6 reconciliation remain
historical accepted checkpoints. Baseten/Inference.net remain research only; hosted traffic
is unverified.
`ANYINFER_CSHARP_SDK_REDIRECTS.md` and its independently reviewed plan-only
reconciliation are complete. Remaining mixed-operation SDK.6c bindings stay separately unchecked. NCON.8 connection plan-only
reconciliation is complete; its executable qualification remains the separate source below. The inventory leaf
is complete at source 830673e56437a695ae26f579d7ca264139b7b0ba (tree
35f35ca6a6a76291c0fe0fdf82affa6e4499cd88), with full held-source gate and clean focused
qualification. Further preset registrations, dedicated adapters and mixed operations remain open.
The auth prerequisite is accepted at clean source c3d0e9a0d26bd253d58620f4bca623c02fac3d85,
with full held-source workspace, registered clean propagation and Frozen preservation;
it corrects Python metadata before native porting and creates no native preset binding.
The private dialect leaf, `ANYINFER_CSHARP_SDK_COMPAT_DIALECT.md`, is complete at clean
source 1f5e821ad0a4e4fd8e387af5005975ad4fbe387c, tree
b3524b491b9c12796740e7f15e07fa27d1c4a211: all 24 held workspace steps, fresh exact C#
registered gate, five source-stamped prior pairs, package/examples and Frozen 102 pass.
It preserves generic defaults and registers no new preset/public API/operation.
The inert data leaf, `ANYINFER_CSHARP_SDK_PRESET_DATA.md`, is accepted at executable clean
source `60e39c9ef011d9cbc3a03a61f330e3366e964558`, tree
`a451153446bc4798c0b2e31a4d0c804109f3abaf`: all 25 held workspace steps, fresh registered
12-step C# gate, 1014 native unit/93 conformance controls, five clean source-stamped pairs,
generator byte equality, package/examples and Frozen 102 pass. That inert-data checkpoint
did not register table rows; source operations remain separate from implemented Generation.
The descriptive metadata leaf, `ANYINFER_CSHARP_SDK_MODEL_INVENTORY.md`, is qualified at
executable source `afb3f86acfefd5a15f80de2389d4b0e0396e3a2b`, tree
`d47d9a135207d335411c06609bda58dd95cba9f1`: all 25 held workspace steps, fresh registered
12-step C# gate, 1016 native unit/93 conformance controls, five clean source-stamped pairs,
generator byte equality, package/examples and Frozen DEVELOPMENT102 pass. Independent
evidence review is bounded clean; plan-only reconciliation is a separate later commit.
The public default category is Served; inert rows explicitly project the source category
without filtering discovery. At that checkpoint connection settings remained pending; the
native connection qualification below now closes that approved scope, with redirects and
registration still open.
The bounded native connection implementation is in `ANYINFER_CSHARP_SDK_CONNECTION.md`.
The user selected native .NET TLS with documented custom-trust limits on 2026-10-23.
NCON.0 contract critique and NCON.1-5 source/control/docs reviews are bounded clean.
Focused195/0/0 and full-third all25 pass:4492 Python passes/10 explicit platform skips,
1051 native unit/93 conformance with zero skips, five paired profiles, strict docs,
package/examples and explicit Frozen DEVELOPMENT102. All1260 protected inputs and Git
identity stayed unchanged. Failed earlier attempts and capture-only corrections remain
retained in the leaf. Executable checkpoint8758b0eedf9f69077274a666da3919e9f83380a0 (tree
1f20c9fa0f95142a28f7713b6de9ebfb12a424b5) contains the explicit39-path slice;
clean qualification now passes the exact registered12-step gate,1051unit/93conformance,
173focused connection/config/ownership cases, five source-clean paired profiles, package/
examples and explicit Frozen102. All1255tracked inputs and initial/final clean identity match;
independent qualification review is bounded clean. A prior clean attempt's existing external-
close5s timeout remains retained/unexplained; isolated and full retry passed without source or
timeout changes. Independent parent/leaf critique is bounded clean. This later plan-only
reconciliation record preserves `8758b0e` as the qualified executable identity.
The generated v3 source clears the approved-scope row pending list without registering
providers. The user-selected shared redirect hardening is now qualified at source
4faf9ecb22206715e01f8bd2faff8a39defe5565, tree44f6f2499762f11280badf16039034e35604fc4d.
Corrected current Python80/0/0, isolated actualhttpx2 2.0.0 controls48/0/0, expanded native134/0/0
and all25 full held-source steps pass. Full Python has4531 passes/10 documented platform skips;
native1109/93 and Frozen DEVELOPMENT102 have zero native skips. Clean checkout
`.tmp-tests/local-redirect-4faf9ecb-20261023T172122Z/` passes the registered12 C# steps,
1109unit/93conformance,56 Redirect cases, five paired reports,package/examples andFrozen102.
All1263 selected inputs and independent root source/Git guards match; external root user inputs
and reviewed proof helpers are unchanged. Independent full and clean evidence critiques are
bounded clean. This redirect executable is separate from the completed plan-only reconciliation.
Python simultaneous read/cleanup behavior and opaque injected-handler hidden hops/cookies remain
qualified limits; the historical connection external-close5s diagnostic remains unexplained.
RDIR.8 parent/leaf/ticket reconciliation has bounded-clean independent critique. Resume
SDK.8a researched registration; no broader SDK completion follows.
At the pre-Nscale Hyperbolic checkpoint `b445605`, the default registry had six
descriptors/nine bindings, with 120 operation memberships pending. Compiling data
does not certify a provider or complete SDK.8a; SDK.6c/8b-c/9–12
and all 235 root API rows remain open.
SDK.7a/b are
accepted at clean source `b315ef73173b81ace643c41e95f4e6339db636b6`, tree
`7e00ab8f148f255b94c77b5c8673370a04ad2833`: all 24 workspace steps, clean registered
Python/C# propagation and pure aggregation, 947 unit/93 conformance cases, rich 43/tool 10
matches, preserved accounting/policy/retrieval profiles and Frozen 102, package-only
consumption/examples and strict docs pass. Independent qualification review is bounded
clean. Failed-first logs and actual hashes are retained in the rich-generation leaf and
task artifacts. All 235 root API inventory rows remain unchecked for final completeness.
SDK.6c remains unchecked; its standalone retrieval-only tranches
are complete. SDK.6a/b are complete at clean source checkpoint
`03f26fc88c7c96ff8272e99dadee8c6a26fa0616`: all 21 workspace gates in 167.6s, 791 native unit
and 93 conformance cases, 32 shared retrieval matches, 29 policy matches, accounting 42+2,
102 Frozen observations, strict docs, compiled examples and clean-revision package-only
consumption. Observer source/dirty/corpus metadata agree with source_dirty=false; frozen
fixture hashes and comparison policy are unchanged. The retrieval leaf records exact paths,
independent reviews and preserved failures. SDK.6c requires current provider research and
a separate accepted binding plan before implementation; generic compatibility stays chat-only.

The TEI lane `ANYINFER_CSHARP_SDK_TEI.md` is complete at
`af5d0d64840cb8ec81ecdcb92acb9a457958d814`. The next lane,
`ANYINFER_CSHARP_SDK_VOYAGE.md`, is complete at accepted source
`289f8427b29fd769110ad669bf44b86efcaeb623`: native embeddings/rerank, independent
Python/native wire controls, all 22 primary gates and clean registered maintenance
aggregation pass. Existing shared profiles and Frozen 102 remain unchanged. Hosted
Voyage traffic is unverified. The Jina leaf is now accepted at `a3b0cc785c723616d5e724f7f7b7b20f432ce647`
with all 22 primary gates,872 unit/93 conformance, clean registered aggregation and
Frozen 102 preservation. Hosted Jina traffic is also unverified. SDK.7 prerequisites now
pass; resume SDK.8a before the remaining mixed-operation SDK.6c bindings.

SDK.5c is complete at source checkpoint
`97e8937c281063582c282f313a35b91761293500`: all 20 workspace steps in 147.6s,
681 native unit and 93 conformance tests, 29 request-policy matches, 42 shared accounting
observations plus two observed native boundaries, FrozenV0 102 preservation, compiled
examples/strict docs and clean-revision package consumption. Observer source/dirty/corpus
metadata agree; released assets and frozen fixture hashes are unchanged. The acceptance
record changes only these checklists. `ANYINFER_CSHARP_SDK_POLICIES.md` records exact paths.
SDK.6a/b implementation starts at 131c7aa; subsequent file-specific checkout rules preserve
the existing LF manifest golden/source-resource contracts. The final clean checkpoint and
acceptance are recorded above. SDK.6c provider research/bindings remain unchecked.

SDK.5b is complete at source checkpoint
`cc989e84069f09cb985e4f82fa40514f1aad5ffe`: all 19 workspace steps in 127.8s,
532 native unit tests, 93 conformance tests, 42 shared accounting observations plus two
separate native-only controls, strict docs, compiled examples and clean-revision package
consumption. `ANYINFER_CSHARP_SDK_ACCOUNTING.md` records the exact gates and scope.
The request-policy source, independent proof and docs/package phase gates are closed in
`ANYINFER_CSHARP_SDK_POLICIES.md`: fresh policy comparison is 29/29, the current native
suite is 681 unit and 93 conformance tests, and accounting/Frozen preservation remains
42+2/102. All 20 full-workspace steps pass in 147.6s with a fresh isolated cache after the
first run's shared-cache ACL shutdown failure; clean-revision acceptance is recorded above.
No later milestone or complete-library parity claim follows from this bounded checkpoint.

SDK.5a is complete at source checkpoint
`68d2cc06914aaa8539eb3cc5ee8d20acdbd2a906`, recorded by acceptance commit
`417d53fd1cfe07ccc81f669e4e8d1093fe88d912`: all 18 workspace steps, 474 native unit tests,
93 conformance tests including all 102 frozen cases, 50 combined sync/lifecycle/HTTP controls,
compiled offline examples, strict documentation and clean-revision package consumption.
Request policies are next; no later milestone/root-export completion is implied.

SDK.5a's contract, ownership, reviews and gates are in `ANYINFER_CSHARP_SDK_EVENTS.md`.
The final full workspace log is `3943a70f-811b-4b78-a40f-18029754dd6a` (18 steps, 108.1s);
the clean source package proof is `.tmp-tests/sdk-five-clean-package/run-ybv82fp9/`.
The three frozen release/report hashes remain unchanged. Preserve the accepted distinction
between owned caller-cancellation checkpoints and source OCE identity, and between a client-
reported stream-close failure and other stream failures that remain independently observable.

SDK.4c's complete ownership, reviews and gate chronology are in
`ANYINFER_CSHARP_SDK_PROBES.md`. The final workspace log is
`d7e0fd10-6c0b-4222-8d64-56ddf5530746` (18 steps, 117.8s); the clean-source package proof
is `.tmp-tests/nuget/run-m3_ozrcb/`. Generation probes retain Python's four-feature default
and usage overlays. Raw tool translation does not complete normal generation tools/loops;
tokenizer/accounting and embedding/rerank remain in their stated later milestones.

SDK.4a's complete ownership, reviews and gate chronology are retained in
`ANYINFER_CSHARP_SDK_CATALOG.md`; that child plan is complete. The final workspace log is
root command `4f5ead1c-4a73-4190-9ba0-d3746b62ed2c` (18 steps, 106.7s); the clean source
package proof is `.tmp-tests/nuget/run-7xx9guja/`. All 235 root inventory rows remain
unchecked until their full assigned semantics and final audit pass.

SDK.4b's complete contract, source ownership and gate chronology are retained in
`ANYINFER_CSHARP_SDK_SCHEMA.md`; that child plan is complete. The final workspace log is
`cb367dce-c8f6-471c-843a-43376e1d8a69` (18 steps, 114.6s); the clean-source package proof is
`.tmp-tests/nuget/run-cgy2od91/`. The explicit-retrieval default, four modern dialects and
documented native numeric/regex limits are accepted. Preserve Python/frozen behavior;
legacy Draft 3/4 remain SDK.11c. Keep ownership disjoint and serialize shared gates.

Earlier clean qualified checkpoints: SDK.3 `04dfa37231f26f5c72b7215afd747c47de4e6d19`,
SDK.2 `b50459bc644cff95e9e50f97ba6dd61ae3e1ef46`, and SDK.1
`c40fbba1369866960599e193041d8ffc6b37f860`. Publish no updated conformance report from a
dirty working tree.
