# C# SDK retrieval operations — SDK.6a and SDK.6b

Resume from the first unchecked box. Foundation work requires 6.0.1 and 6.0.2; raw
retention requires 6.0.4; connected client/core work requires 6b.1–3; observers require
6.0.3. It starts from accepted SDK.5c source
`97e8937c281063582c282f313a35b91761293500`, plan acceptance `2820ef2`, and Python
authority `199c3f833e568334b629edd7d89f41a3b76efe2a`. Python source remains the
behavioral authority. Root owns Git, solution/workspace registration, cold reviews,
serialized builds and full gates. A source save never checks a parent SDK.6 box.

## 1. Settled architecture and literal contract

### 1.1 Provider ownership and optional protocols

Keep the legacy public generation composition:

```csharp
public interface IGeneratesText
{
    IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        CancellationToken cancellationToken = default);
}

public interface IProviderAdapter : IAsyncDisposable, IGeneratesText { }

public interface IEmbedsText
{
    ValueTask<EmbeddingWireResult> EmbedAsync(
        EmbeddingWireRequest request,
        CancellationToken cancellationToken = default);
}

public interface IReranksText
{
    ValueTask<RerankWireResult> RerankAsync(
        RerankWireRequest request,
        CancellationToken cancellationToken = default);
}
```

Common factory, registration, pool state, adoption and teardown ownership widens to
`IAsyncDisposable`. `ProviderDescriptor.Factory`, `ProviderRegistration.Adapter`,
`ProviderPool.InstanceState`, build/adoption collections and every explicit factory call
migrate in the same source slice. There are no legacy aliases or parallel factory paths.
`IProviderLifecycle` stays optional for models and health.

Generation checks `IGeneratesText` at its current invocation boundary. Retrieval dispatch
checks both the descriptor's declared operation and the acquired object's optional runtime
protocol. The pool validates every declared protocol only **after** a factory returns and
before adoption. It must not add a requested-operation gate to every `GetAdapterAsync`:
models and health remain general acquisition calls. An invalid newly returned, unadopted
object is disposed once, then dispatch receives `ConfigException`; a disposal failure takes
the existing cleanup-failure precedence. A previously adopted shared object is never
discarded or disposed by a later invalid binding. Null factory results receive the same
configured-instance validation without leaking or double-disposing a pool-created wrapper or
its raw supplied handler. A valid later binding returning an already adopted reference must
dispose that invocation's unused temporary wrapper before publishing the binding, while
keeping the shared adapter alive. Retain SDK.5c `PoolOwnsConfiguredTransport` transfer rules:
an invalid wrapper borrowing a pool-owned raw handler may be rebuilt with that reusable
handler, while an invalid wrapper that consumed a transferred handler leaves later rebuilds
to fail through the established configuration refusal. Do not add another ownership layer.

### 1.2 Buffered operation lifecycle and ordering

`AsyncClient.ReserveLifecycle` / `CompleteLifecycleAsync` and `Client.RunOperation` are
the lifecycle seam for buffered calls. Reserve before target resolution, factory work or
provider invocation; complete in `finally`; retain the current client-close joins,
async/sync/cancellation identity scopes, source exception identity and late-factory
disposal semantics. Do not make an `AsyncStream`, generation event stream, repair loop or
fake `GenerateAsync` path.

For each actual adapter call, add a small operation-neutral deadline scope only after
spend/admission and successful adapter acquisition. It runs through provider await and
provider body cleanup. It consumes the reservation's existing effective lifecycle token and
retains the original caller identity separately; it adds only deadline cancellation rather
than recreating caller/client ownership. It owns timer callback capture,
timer/registration/CTS disposal and join. A source/provider/body-cleanup failure stays
authoritative; only a sole deferred owned timer-worker cleanup failure is replayed by exact
EDI. Required order is provider/body cleanup, deadline-scope join/disposal, then
`CompleteLifecycleAsync`. This scope has no generation capture or repair state, and Frozen
entry capture remains unchanged.

Dispatch order is literal Python order: resolve without deduplicating route positions; target and health checks;
embedding cross-space or unused-fallback safety before materialization; general pool
acquisition; descriptor/runtime operation validation; attempt work. Spend admission occurs
before dispatch telemetry. Explicit per-call target or route wins; only absent target and
route may use the configured operation route for that operation, then the ordinary default.
Repeated target positions remain repeated candidates subject to the normal health gate; a
same-target route with `healthGate = false` must retain its second candidate.

### 1.3 Public and wire types

All sequences and dictionaries are copied into read-only snapshots. Nested provider option
maps are copied at both levels. `JsonValue` below is the existing AnyInfer JSON DOM, never
an `object` escape hatch.

| Type and exact constructor surface | Literal default, copy, and validation contract |
| --- | --- |
| `BatchPolicy(int maxConcurrency = 4, int? maxItemsOverride = null, bool allowSplit = true, bool rerankCrossBatch = false)` | Copy-free scalar value. `maxConcurrency <= 0` and a non-null `maxItemsOverride <= 0` throw `ArgumentOutOfRangeException`. Its positional default is exactly `(4, null, true, false)`. |
| Existing `EmbeddingSpace(string providerId, string model, string? modelRevision = null, int? dimensions = null, bool inputIntentAware = false, bool? normalized = null, string? compatibilityId = null)` | Preserve existing `ModelRevision` / `InputIntentAware` names. Null provider/model are ordinary `ArgumentNullException`. Compatibility is equal non-null IDs or equal provider/model/modelRevision, never dimensions alone. Do not create a duplicate space model. |
| `EmbeddingVector(IEnumerable<double> values)` | Copies a nonempty finite vector. Empty values and NaN/infinities are ordinary `ArgumentException`; no inferred dimensions. |
| `EmbeddingRequest(IEnumerable<string> inputs, EmbeddingInputIntent? inputType = null, int? dimensions = null, EmbeddingSpace? expectedSpace = null, double? timeoutS = null, int maxResponseBytes = 64 * 1024 * 1024, IReadOnlyDictionary<string, string>? metadata = null, IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null, BatchPolicy? batch = null, bool retainRaw = false, bool allowIncompatibleFallback = false)` | Uses the existing closed nullable `EmbeddingInputIntent` vocabulary with `InputType` naming, not a parallel string. Copies input order/maps. Direct Python validation is narrow: only an empty input sequence fails, as ordinary `ArgumentException`. Do not add dimensions, timeout, whitespace, response-cap or input-string validation absent from source. `EffectiveTimeoutS` is `timeoutS ?? 120d`; per-call response cap is exactly 64 MiB. |
| `RerankDocument(string id, string text, IReadOnlyDictionary<string, string>? metadata = null)` | Copies metadata. Null arguments are ordinary `ArgumentNullException`; Python adds no empty-ID/text rule here. |
| `RerankRequest(string query, IEnumerable<RerankDocument> documents, int? topN = null, double? timeoutS = null, int maxResponseBytes = 8 * 1024 * 1024, IReadOnlyDictionary<string, string>? metadata = null, IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null, BatchPolicy? batch = null, bool returnDocuments = false, bool retainRaw = false)` | Copies documents/maps. Falsey query, empty documents, duplicate IDs and `topN < 1` are ordinary `ArgumentException` / `ArgumentOutOfRangeException`. Preserve Python falsey versus whitespace behavior: do not trim or reject whitespace-only values merely because they are whitespace. `EffectiveTimeoutS` is `timeoutS ?? 120d`; per-call cap is exactly 8 MiB. |
| `EmbeddingWireRequest(string model, IEnumerable<string> inputs, EmbeddingInputIntent? inputType = null, int? dimensions = null, double timeoutS = 120d, int maxResponseBytes = 1 * 1024 * 1024, IReadOnlyDictionary<string, JsonValue>? extraOptions = null)`; `EmbeddingWireResult(IEnumerable<IEnumerable<double>> vectors, string? model = null, int? dimensions = null, bool? normalized = null, Usage? usage = null, IReadOnlyDictionary<string, double>? phases = null, JsonValue? raw = null)` | One provider batch. The public nested `ProviderOptions` map selects the actual resolved provider instance; wire `ExtraOptions` is the resulting flat copied map and defaults empty. Vectors are copied but deliberately permissive until core validates count, rectangularity and finite components with target context. `Phases` accepts nullable input then copies/defaults to an empty map. The 1 MiB wire cap is separate from public response caps. |
| `RerankWireDocument(int index, string text)`; `RerankWireRequest(string model, string query, IEnumerable<RerankWireDocument> documents, int? topN = null, double timeoutS = 120d, int maxResponseBytes = 1 * 1024 * 1024, IReadOnlyDictionary<string, JsonValue>? extraOptions = null)`; `WireRankedItem(int index, double score)`; `RerankWireResult(IEnumerable<WireRankedItem> items, string? model = null, Usage? usage = null, JsonValue? raw = null)` | One provider batch only. Every wire-document index is the original `RerankRequest.Documents` index across all chunks. Adapters may translate provider-local positions through that batch's wire-document mapping. Decoded wire indexes and scores remain representable until core validation has resolved target/chunk context; core rejects nonfinite scores and original-index range, chunk-membership, or duplicate faults as `ConfigException`. Public `RankedItem` keeps its ordinary constructor invariants after that validation. `TopN` is forwarded to each provider wire request; core never post-truncates or re-sorts provider order. |
| `EmbeddingResult(IEnumerable<EmbeddingVector> vectors, ResolvedTarget target, EmbeddingSpace space, Usage usage, Timing timing, IEnumerable<AttemptRecord>? attempts = null, IEnumerable<string>? warnings = null, JsonValue? raw = null, RunManifest? manifest = null)`; `RankedItem(int index, string documentId, double score, string? text = null)`; `RerankResult(IEnumerable<RankedItem> items, ResolvedTarget target, Usage usage, Timing timing, IEnumerable<AttemptRecord>? attempts = null, IEnumerable<string>? warnings = null, JsonValue? raw = null, RunManifest? manifest = null)` | Immutable public result snapshots. Public `RankedItem` rejects nonfinite score, negative index and empty document ID with ordinary argument exceptions; whitespace is retained. Produced embedding space uses actual provider/model and reported dimensions or first vector length, with `ModelRevision = null`, `InputIntentAware = false`, `CompatibilityId = null`. `ExpectedSpace` is only a post-result compatibility assertion and never hydrates returned space. Only a future source-backed wire/result contract can change those fields. Rerank documents are echoed only when requested. |

Input constructors use normal argument exceptions for Python `ValueError` equivalents. Core
result, protocol, safety, provider-index, expected-space and operation-declaration failures
use `ConfigException`. Do not validate a null timeout, dimensions or a source-permitted
falsey/whitespace distinction beyond the source contract.

Freeze the supplied-request family in 6.0.1. A supplied-request overload accepts
only the immutable request plus routing, manifest and cancellation controls; it never accepts
or reconstructs request fields. Scalar/typed convenience overloads alone construct a request
once with table defaults before routing. Explicit target/route precedence stays dispatch-level.
Scalar embed input becomes a one-item copied sequence; convenience rerank strings become
ordered `RerankDocument` values with IDs `"0"`, `"1"`, and so on. Retrieval may add a
client-level `retainRaw` default: a per-call nullable override selects it, while an explicit
request's `RetainRaw` remains supplied. Per-call caps stay per-call or operation constants,
never inherited from a client generation cap.

```csharp
// Request overloads: no request-field overrides.
Task<EmbeddingResult> EmbedAsync(
    EmbeddingRequest request, string? target = null, Route? route = null,
    CancellationToken cancellationToken = default, bool? manifest = null);
Task<RerankResult> RerankAsync(
    RerankRequest request, string? target = null, Route? route = null,
    CancellationToken cancellationToken = default, bool? manifest = null);
```

Matching `Client.Embed` and `Client.Rerank` retain these parameter positions through
`RunOperation`. The separate convenience families take scalar/typed inputs and only the
fields needed to construct their corresponding request once, plus `target`, `route`,
nullable `retainRaw`, cancellation and nullable `manifest`; 6b.1 freezes their complete
appended parameter order before core implementation.

### 1.4 SDK.6b source facts already settled

- Config permits operation routes only for `embedding` and `rerank`. An explicit call route
  or target wins; otherwise the operation route wins before the generation default.
- Retry catches `ProviderError` only. Cancellation and non-provider source faults escape.
- Unknown provider batch limits do not get guessed: embedding makes one request subject only
  to the 2,048 sanity ceiling; rerank's unknown ceiling is 1,000 documents.
- Embedding split is ordered bounded concurrency and all-or-error. Cross-target fallback
  before a response requires identical `provider:model`, unless the request opts in.
  `ExpectedSpace` is a post-result check.
- Rerank over-limit splitting requires `rerankCrossBatch`; it concatenates chunk-local
  provider order, forwards and applies `topN` per chunk, and emits a warning. Empty and
  partial valid rankings are allowed; core does not re-sort, post-truncate, or require every
  document to appear.
- Rerank estimator cost is always unknown. Embedding response space comes from the actual
  provider/model; unsupported input intent warns. Duplicate source inputs remain duplicates.
- TEI and every retrieval-only wire adapter remain SDK.6c research. Generic OpenAI
  compatibility stays chat-only.

## 2. Exact ownership cuts

### SDK.6b accepted implementation contract

Root accepted the following 6b.1–3 implementation details after independent source and
lifecycle critiques and targeted rereview. It does not authorize a new provider binding
or a credential-refresh implementation. Execute the support gate before connected core.

**Public entry points.** Retain the supplied-request signatures in section 1.3. Add two
embedding convenience overloads, taking `string input` or `IEnumerable<string> inputs`,
with this identical remaining parameter order:

```csharp
string? target = null, Route? route = null,
EmbeddingInputIntent? inputType = null, int? dimensions = null,
EmbeddingSpace? expectedSpace = null, bool allowIncompatibleFallback = false,
BatchPolicy? batch = null, double? timeoutS = null,
IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null,
IReadOnlyDictionary<string, string>? metadata = null,
int? maxResponseBytes = null, bool? retainRaw = null,
CancellationToken cancellationToken = default, bool? manifest = null
```

Add two rerank convenience overloads, beginning `string query` and either
`IEnumerable<string> documents` or `IEnumerable<RerankDocument> documents`, then:

```csharp
string? target = null, Route? route = null, int? topN = null,
BatchPolicy? batch = null, double? timeoutS = null,
IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null,
IReadOnlyDictionary<string, string>? metadata = null,
int? maxResponseBytes = null, bool returnDocuments = false, bool? retainRaw = null,
CancellationToken cancellationToken = default, bool? manifest = null
```

Return `Task<EmbeddingResult>` / `Task<RerankResult>` asynchronously and the corresponding
result synchronously through `Client.RunOperation`. Convenience overloads construct exactly
one immutable request, use their operation's response-cap constant when null, and resolve
nullable raw retention against the client default. Supplied requests retain every supplied
field, including their nonnullable `RetainRaw`; the client default does not rewrite them.
String rerank documents receive original positional IDs using invariant decimal spelling.

**Operation routes and inert configuration.** Append
`IReadOnlyDictionary<InferenceOperation, Route>? operationRoutes = null` after retainRaw on
the async/sync constructors and factories. Copy the dictionary, reject unsupported keys
(only Embedding and Rerank), and retain supplied Route objects as immutable values.
Append the same map to `AnyInferConfig` after cache and expose copied `OperationRoutes`.
FromConfig uses an explicitly supplied map when present, otherwise the parsed map.
Generation never consults it. Retrieval uses a per-call target/route first; absent both,
the operation map wins, then the ordinary default. Reuse the existing explicit target
versus Route conflict/default-policy rules and never deduplicate retrieval candidates.

Remove only operation_routes from the config unimplemented-key set. JSON null or absence
means an empty map; an object accepts exactly embedding/rerank keys with nonempty arrays
of nonblank strings. Preserve target positions. Dump emits those source-spelled keys and
arrays, refusing unrepresentable Route retry/health/context policy just as the existing
default-route dumper does. Loading, construction, dumping and unadvanced generation remain
inert. No Python config or new top-level key is needed.

**Capabilities: use the source's operation seams.** Do not add a ModelCapabilities.Rerank
facet or merge separate static operation maps into the generic CapabilityAssembler.
Python also obtains rerank limits directly from StaticRerankCapabilities. For embedding,
add the operation getter equivalent to async_client.py `_embedding_capabilities_of`:
descriptor static embedding row, assembled ModelCapabilities.Embedding, then actual typed
embedding probe facts if present, overlaying only fields the source overlay knows. Do not
invent probe evidence. Existing generic probe records carrying embedding facts may be read
at their actual layer; absent support stays absent. Preserve the source quirk that generic
configured capability overrides do not replace the embedding facet. No catalog schema
expansion is part of this slice. The public configured/discovered metadata is enough to
exercise verified limits; unknown limits stay unknown.

**Minimal result/error support.** Add public immutable `BatchFailure(int batchIndex,
int itemCount, bool succeeded, string? error = null)` with the four corresponding getters.
Do not add monetary amounts, usage, wire slices or provider exceptions to this source DTO.
Append optional `Timing? timing = null` to AttemptRecord and expose Timing, leaving existing
generation attempts unchanged. Append optional `IEnumerable<BatchFailure>? batchFailures
= null` after nativeInner in AllTargetsFailedException and expose a copied read-only
BatchFailures list. Preserve all existing argument positions, error structure and its
generate lifecycle phase: Python AnyInferError/AllTargetsFailedError uses that phase for
retrieval too. Core-created BatchFailure.Error comes from the real bounded/redacted provider
detail. Native source exceptions/OCEs remain unchanged outside typed provider failure paths.

**Admission, retry and lifecycle.** ReserveLifecycle/RunOperation owns each logical request
before resolution, factories and provider calls. Source request construction/validation
precedes dispatch. Port `_check_operation_spend` literally: inactive policy does no work;
embedding resolves only the first route target and sums the actual configured estimator's
tokens when operation capabilities are available, then calls the existing trusted
PricingCalculator.ComputeOperationCost; rerank admission is always unknown. Do not reuse
generation's missing-price short circuit here: the Python operation path estimates before
the pricing helper reports unknown. Resolve/capability errors caught by the source become
unknown cost; an estimator's unrelated native failure does not. Reuse SpendPolicy and
SpendLedger admission/replacement primitives, not a second cost calculator.

The buffered outer runner in AsyncClient creates exactly one request ID immediately after
ReserveLifecycle. Pass that same ID to admission, RequestStarted, every target/attempt
event, terminal telemetry, ledger cleanup and OperationManifestBuilder. Neither dispatch
helpers nor manifest projection allocate another ID. Keep one local terminal transition:
not-started -> started -> completed or released; a pre-start refusal ends released.
Only completed emits one RequestCompleted. A source-required RequestFailed is emitted
only by its literal routed/batch failure branch, never by a blanket outer catch.

Admission precedes RequestStarted. Add internal SpendLedger.Abandon(requestId), atomically
removing that ID's metadata and reservation under the existing ledger lock. Keep public
Release semantics unchanged and introduce no event or second accounting path. In the outer
finally, every operation that did not commit success calls this idempotent primitive once
before CompleteLifecycleAsync, including pre-start refusal and post-start cancellation or
ConfigException. A preceding real RequestFailed may already have removed the same entries;
the final cleanup then safely finds nothing. Success commits final aggregated/priced usage
through the existing RequestCompleted ledger observer. Never create per-chunk ledger
commits or fabricate usage for a failed all-or-error request. Tests must verify reservation
and metadata removal after actual post-start cancellation and post-acquisition ConfigException.

For each resolved candidate, retain Python order: TargetResolved, health skip, embedding
space guard, general pool acquisition, declared/runtime operation check, capabilities and
attempt work. Retry only ProviderException paths according to Route.Retry; reuse clocks,
health/backoff primitives and target-local attempt numbers. Read `_pending_attempts` and
`_batch_failure_report` as well as `_attempt_with_retry`: retrieval's terminal trail is
not assumed to equal generation's trail. Preserve repeated route positions and literal
source exhaustion, fallback and terminal-event shapes. Local operation/contract/space
ConfigException and arbitrary source failures must not become ordinary routed failures.

Credential TTL/rotation/refresh remains the previously deferred SDK.2 parity item assigned
to SDK.11c, alongside platform credential integration in SDK.11b. SDK.6 introduces no fake
refresh hook and claims no rotating-credential parity. The shared retrieval profile must
exclude that unimplemented branch explicitly. Keep the source fact that unsplit Python
passes refresh_credential while split closures do not, and its call closure retains the
old adapter, available for that later implementation; do not claim a successful refresh
from generation-only tests.

The operation-neutral buffered deadline starts only after acquisition/admission, applies
per actual adapter invocation (including each retried chunk), and uses reservation effective
token plus original caller identity. Keep it alive through provider buffered-body cleanup;
then join/dispose its callback/timer resources before lifecycle completion. Retain source
fault/cleanup priority and map only owned cancellation. No AsyncStream, EntryContext,
generation event capture or fabricated text request is used. After all started provider
work and deadline scopes join, perform the reservation close-won check, then the original
caller check before the success publication/accounting decision. Use the existing client
publication arbitration so a close winner cannot commit; no observer callback or adapter
call runs under the client lock. Terminal cleanup precedes lifecycle completion in the
outer finally. Preserve source timing selection: the winning attempt for unsplit calls,
the actual joined batch interval for split calls; do not substitute an invented timing.

**Batching and result validation.** Follow operations.py's literal helpers: caller max-item
override before verified limits; unknown embedding/rerank sends one bounded call through
the 2048/1000 sanity ceiling; split refusal and rerank cross-batch opt-in remain explicit.
Create an indexed worker/outcome slot for every planned chunk, with provider entry bounded
by MaxConcurrency. Each worker captures its exact result or exception, including a failure
while awaiting its slot, and releases its slot/deadline resources. Join all workers before
scanning slots in ascending chunk index. The first non-provider exception (including OCE)
is rethrown by EDI unchanged, even if another slot has ProviderException. Otherwise, any
ProviderException invokes the batch-failure branch once: mark health and emit RequestFailed
using the first failing slot's error, record all BatchFailure entries in chunk order, and
throw AllTargetsFailedException. This is route-terminal even if every chunk failed; never
fall through to another target. Do not expose Task.WhenAll's incidental exception choice,
cancel siblings merely because a provider chunk failed, or replay successful chunks.

Successful chunks contribute their returned attempt lists. A failed provider chunk
contributes exactly one final failed AttemptRecord with its target/error and no timing,
matching _pending_attempts; its earlier retry records are not recovered into the aggregate.
The same final-only trail rule applies to an exhausted unsplit target. Raw attempt/retry
telemetry still reports actual attempts. Non-provider failure/cancellation produces no
BatchFailure aggregate. Telemetry has no invented batch ordinal; actual adapter wire
slices and BatchFailure carry batch facts.

Embedding preserves duplicate input order, validates vector count/finite rectangular shape
in core, enforces cross-chunk actual-space equality and post-result ExpectedSpace, and keeps
revision/intent-aware/compatibility fields at their source defaults. Pre-response fallback
requires identical provider:model unless opted in. Input-intent warnings require both a
non-null requested intent and known embedding facts: unknown facts are silent; declared
empty intents use the source no-effect warning; a nonempty set missing the request uses
the source unsupported/provider-handling warning; supported intent is silent. Use source
lowercase intent spelling and literal warning templates, and still forward caller InputType
unchanged in every case.
Rerank wire indexes remain original document indexes; validate range, chunk membership,
uniqueness and finite scores with target context before constructing RankedItem. Empty and
partial rankings are valid. Preserve provider order and caller ID/text mapping. Forward
TopN per chunk without core sorting or truncation. Retain literal cross-batch and TopN
warnings. Sum actual usage with the existing operation-cost helper. When raw retention is
off, Raw is null. Unsplit retention returns the original JsonValue reference (or null).
For multiple embedding wire results and the rerank split path, retain a JsonArray in exact
chunk order, using JsonNull.Instance for each absent chunk raw. Preserve all positions,
including an array of nulls when every chunk lacks raw, and retain each supplied immutable
node. This array is the native projection of the source tuple, with no response envelope,
flattening or omission. Tests cover mixed/absent/all-absent raw, order, unsplit identity
and the default-off branch.

**Manifests.** Add a result-built operation manifest helper equivalent to
manifest.py build_operation_manifest, using RunManifest directly. Fill actual request ID,
requested/resolved route, returned attempt/timing/error facts, final usage (including search
units), total timing/phases, warnings/notes, Operation and actual EmbeddingSpace. Leave
generation-only facets at existing empty defaults. Do not add retrieval request fields the
Python helper does not provide, fabricate Generation/ManifestBuilder inputs, copy Raw into
manifests, or change default payload privacy. Per-call nullable manifest overrides the
client setting. Publication remains subject to lifecycle close/cancellation checkpoints.

**Implementation ownership additions.** Support DTOs own new `BatchFailure.cs`,
`Models.cs` AttemptRecord and `Errors.cs` AllTargetsFailedException only; config owns
`Config/AnyInferConfig.cs` and focused new config tests. After those handoffs, the connected
core owner has AsyncClient.cs, Client.cs, new Core/RetrievalCore.cs,
Internal/BufferedOperationDeadlineScope.cs and Core/OperationManifestBuilder.cs; the
internal SpendLedger.Abandon primitive; narrow
CapabilityStore operation getters only when the source map requires them. No generic
capability rewrite is granted. Independent tests use new domain/error, operation-route,
deadline/lifecycle and dispatch/batching test files with disjoint ownership. Root owns
plan/solution/workspace, native gates and cross-runtime qualification.

| Lane | Exact owned files and responsibilities | Exclusions |
| --- | --- | --- |
| Domain/protocols | Existing `EmbeddingSpace.cs` only if source-backed tests require a change; new `BatchPolicy.cs`, `EmbeddingVector.cs`, `EmbeddingRequest.cs`, `EmbeddingResult.cs`, `RerankDocument.cs`, `RerankRequest.cs`, `RankedItem.cs`, `RerankResult.cs`; new `Providers/IGeneratesText.cs`, `IEmbedsText.cs`, `IReranksText.cs`, `EmbeddingWire.cs`, `RerankWire.cs`; `Providers/IProviderAdapter.cs` | No routing, provider binding or pool migration. |
| Pool and callsite migration | `Providers/ProviderDescriptor.cs`, `Providers/ProviderRegistration.cs`, `Core/ProviderRegistry.cs`, `Providers/ProviderConfig.cs` only where signatures require it; mechanical generation-boundary files `Core/GenerationCore.cs`, `Internal/AdapterInvocationBoundary.cs`, `Core/CapabilityProbeRunner.cs`; mechanical `AsyncClient.cs` models/filter-models/supports-operation protocol types; `AnyInfer.RequestPolicy/PolicyCase.cs` and its test callsites; named descriptor/factory registrations in `AnyInfer`, `AnyInfer.Tests`, `AnyInfer.Conformance`, `AnyInfer.Accounting`, examples and embedded package source; `scripts/check_csharp_package.py` mechanical type migration | No retrieval behavior or independent test assertions. The pool owner may change the package checker before the docs/package lane receives exclusive ownership. |
| Buffered operations/core | After pool handoff, exclusively `AsyncClient.cs`, `Client.cs`, new `Core/RetrievalCore.cs` and `Internal/BufferedOperationDeadlineScope.cs`; only source-proven additions to existing manifest/event fact files | No `AsyncStream`, `GenerationStream`, repair or adapter wire implementation. |
| Config/routes | `Config/AnyInferConfig.cs`, config parser/dumper and route resolution files after source-contract acceptance | No new shared-config key beyond source-backed operation routes. |
| Tests | New distinct `AnyInfer.Tests` files for domain/protocols, lifecycle, routing/batching and literal fake adapters; existing generation tests only for named factory-type migration allowlist | No production edits. |
| Retrieval qualification | `tests/fixtures/retrieval-v1/`; `tests/test_retrieval_parity.py`; new `src/csharp/AnyInfer.Retrieval/AnyInfer.Retrieval.csproj` and `Program.cs`; `scripts/check_csharp_retrieval.py` | Profile/comparator remain local; no calculator, expected-output lookup, or production changes. |
| Docs/package | C# docs, executed examples and package-consumer material only after root workspace registration | No provider contract or pool source. |
| Root | Parent plan, solution/workspace registration, baseline evidence, cold reviews, serialized gates and parent SDK.6 completion | Concurrent lane implementation files. |

## 3. Prerequisite closure — SDK.6.0

- [x] **6.0.1 — Freeze source contracts and public vocabulary.** Record a source-line matrix
  for Python request defaults/validation, operation route precedence, retries, health,
  batching, safety, usage, ledger and manifest outcomes; reconcile the literal signatures in
  section 1.3 with existing C# public naming and nullable conventions. Freeze the two
  non-overlapping public overload families and retrieval-level retain-raw precedence here.
  Gate: root accepts the matrix and an independent cold architecture critique.
  > NOTE: Root accepted the pinned source matrix in Traycer `csharp-sdk/sdk-six-source-contract`
  > and the bounded execution/architecture reviews. Root applied the final requested
  > correction: ExpectedSpace never supplies result-space revision, intent awareness or
  > compatibility ID. Literal foundation constructors and request-overload families are
  > frozen; full convenience parameter order remains a 6b.1 gate before client/core work.

- [x] **6.0.2 — Freeze common ownership migration and validation order.** Specify the exact
  `IAsyncDisposable` factory/registration/pool migration allowlist, the protocol-validation
  sequence in section 1.1, invalid returned-instance disposal precedence, and the buffered
  deadline helper's callback/timer cleanup order. Gate: root accepts the migration and
  lifecycle source contract before any code lane starts.
  > NOTE: The cold architecture rereview closed generation-boundary ownership, the
  > AsyncClient mechanical-to-core handoff, invalid-return cleanup precedence, retained
  > versus transferred handler rules, and lifecycle-token/deadline cleanup order.
  > This accepts the source contract only; native builds and runtime gates remain open.

Prepare the `retrieval-v1` input/obligation proposal early: an input-only fixture shape
under `tests/fixtures/retrieval-v1/`, a mechanical Python `_csharp_observation` helper in
`tests/test_retrieval_parity.py`, native `AnyInfer.Retrieval` observer envelope, and local
comparison ownership in `scripts/check_csharp_retrieval.py`. It must enumerate malformed,
missing, duplicate, provenance, type, order and causal false-pass obligations without an
expected table or verdict lookup. This preparation does not block foundation work after
6.0.1/6.0.2; the executable schema/public-seam freeze is the 6.0.3 gate directly before
observer implementation.

- [x] **6.0.4 — Source-map shared raw retention before exposing a client default.** Map
  Python generation `_retain_raw`, terminal raw payload handling and result copying alongside
  embed/rerank retention. Freeze the minimal prerequisite: modern
  `AdapterFinal.Raw -> Generation.Raw` for a winning terminal result, preserved by
  `WithManifest`; generation reads the client-level `retainRaw = false` default only,
  while retrieval resolves its nullable per-call override against that default. Buffered
  OpenAI payloads may retain their actual raw payload; streaming retains raw only when its
  source supplies one and never fabricates an SSE aggregate. Gate: source map accepted
  before a raw implementation lane or public client flag is exposed.
  > NOTE: Python generation.py:980–982 consumes the client default; async_client.py:1723–1724
  > and :1816–1817 apply retrieval overrides. The native AdapterFinal/Generation raw fields
  > are absent and are an explicit 6a.2R prerequisite, including WithManifest copying.
  > OpenAI-compatible buffered final raw is the actual parsed payload; no streaming raw
  > aggregate is invented. Raw implementation and all runtime evidence remain unchecked.

## 4. SDK.6a vocabulary and migration

- [x] **6a.1 — Domain records and optional protocols.** Implement exactly the section 1.3
  types and section 1.1 interfaces in the domain/protocol lane. Preserve copied nested
  snapshots and ordinary input exception categories. Gate: focused domain/protocol tests
  cover literal defaults, 64 MiB/8 MiB public caps, 1 MiB wire caps, 120-second timeout,
  `BatchPolicy (4,null,true,false)`, narrow validation, finite vectors, spaces and snapshots.
  > NOTE: Domain/protocol source is saved and held in the assigned new files plus
  > `Providers/IProviderAdapter.cs`; existing EmbeddingSpace is unchanged. Independent
  > `RetrievalDomainTests.cs` and `RetrievalProviderOwnershipTests.cs` are saved and held.
  > Author lanes ran no build or test. Root accepted the cold domain/test review and the
  > final 19-test foundation gate; the full native suite also passes all 700 tests.
  > Root's first stamped solution compile stopped at CS0019 in the empty option-map
  > fallbacks in `EmbeddingRequest.cs` and `RerankRequest.cs` (zero warnings, two errors).
  > No tests ran. Narrow typed-empty fixes are assigned; log:
  > `.tmp-tests/sdk-six-foundation-build-d2f60ab6b41c491588addf09c1635ce3/build.stdout.log`.

- [x] **6a.2 — Common pool ownership migration.** Migrate the exact allowlist from 6.0.2 to
  `IAsyncDisposable`, including `Providers/ProviderRegistration.cs` and package checker
  mechanics; add generation `IGeneratesText` invocation validation and operation protocol
  validation at the accepted post-acquisition boundary. Gate: zero-warning solution build;
  focused retrieval-only lifecycle, invalid-return cleanup-fault, shared-adoption, borrowed
  governed-handler rebuild, transferred-handler consumed refusal, and existing
  generation/Frozen regression controls pass.
  > NOTE: Root extended the mechanical ownership/factory-signature allowlist after a
  > source audit: `AnyInfer.Conformance/NativeProofs.cs` and existing test files
  > `CachePlanningTests.cs`, `LimiterDiagnosticTests.cs`, `PolicyContextTests.cs`,
  > `UnknownSpendEstimationTests.cs`. Assertions, scripts and generation semantics stay
  > outside this migration. The independent new retrieval test files remain separately owned.
  > The same narrow allowance includes `ConfigTests.cs` and `OpenAILifecycleTests.cs`
  > for target-typed factory lambdas whose generic ValueTask return needs widening.
  > Final factory audit adds existing `AccountingLifecycleTests.cs`,
  > `CapabilityAssemblyTests.cs`, `CatalogTests.cs`, `EntryPacingTests.cs`,
  > `LateFactoryCancellationTests.cs`, `ProbeLifecycleTests.cs`, `ProviderSettingsTests.cs`.
  > The same signature-only migration is allowed in other HEAD-tracked native test files;
  > report every changed path and preserve assertions/stimuli. Newly owned retrieval tests
  > remain excluded. Audit generic factory expressions as well as explicit delegate types.
  > Cold review found three ownership/dispatch defects: invalid later bindings must not
  > dispose adopted shared objects; pool-created governed wrappers need cleanup on every
  > non-adoption path; generation must require its descriptor declaration after acquisition.
  > The same correction wave makes configured model filtering honor operation declarations.
  > Production and independent regression changes are assigned to separate owners; root
  > will compile the coherent held slice. The domain map-mutation oracle is also being
  > corrected to allow a read-only-only implementation rather than require IDictionary.
  > The next stamped compile built AnyInfer, Accounting, RequestPolicy and Conformance,
  > then stopped on test-only compilation errors: three legacy builtin-factory conversions,
  > missing explicit IAsyncDisposable on two lifecycle fakes, and an iterator cancellation
  > annotation. Narrow fixes are assigned; no tests ran. Log:
  > `.tmp-tests/sdk-six-foundation-build-4dc346d724834607b16aa47984c066fc/build.stdout.log`.
  > The corrected solution builds with zero warnings/errors at
  > `.tmp-tests/sdk-six-foundation-build-420daef3b1f5492394469d34ad038711/build.stdout.log`.
  > Focused runtime gate: 14/17 passed; three test assumptions need correction (optional
  > IList backing, discovered generation metadata, and active limits to create the governed
  > transport). Production remains held. Test log:
  > `.tmp-tests/sdk-six-foundation-tests-071121a475374e42935084ecb26b1478/tests.stdout.log`.
  > Closure: cold pool review includes invalid and valid shared bindings, unused-wrapper
  > cleanup and cancellation during that cleanup. Legacy fixture review preserves explicit
  > operation declarations and generation-only prebuilt classification. Root's final
  > zero-warning build and 700/700 native unit tests pass at
  > `.tmp-tests/sdk-six-foundation-final-native-8a5e169410f348b39fe7c95dafc4de5d/`.
  > Preservation passes: conformance 93/93, Frozen 102/102, request-policy 29/29,
  > accounting 42 shared plus two observed native cases. These are dirty-worktree gates
  > against source revision 2820ef2, not a new clean commit or parent SDK.6 acceptance.

- [x] **6a.2R — Minimal shared raw-retention prerequisite.** After pool migration and before
  connected retrieval core, implement only the accepted raw seam in
  `Providers/AdapterEvent.cs`, `Models.cs`, `Core/GenerationCore.cs`,
  `GenerationStream.cs`, `Providers/OpenAIChatAdapter.cs`, `AsyncClient.cs` and
  `Client.cs`. It must carry actual modern terminal raw data through winning fallback and
  repair results, preserve it in `WithManifest`, leave streaming absent when no source raw
  exists, and expose no default telemetry/manifest payload. Generation reads only the client
  default; retrieval alone accepts the nullable per-call override. Raw remains caller-opted
  data, not automatically redacted; a later observer projection applies registered-secret
  redaction separately. Gate: default-null and opt-in fallback/repair/buffered-builtin/SSE
  absence controls pass with Frozen behavior preserved.
  > NOTE: Implementation is assigned under disjoint ownership: core/public types and
  > client forwarding, buffered OpenAI terminal projection, and new independent
  > `AnyInfer.Tests/RawRetentionTests.cs`. Root retains plan edits and all native gates.
  > Literal surface appends `JsonValue? Raw = null` to AdapterFinal, `JsonValue? raw = null`
  > after Generation's existing toolCalls parameter, and `bool retainRaw = false` after
  > cachePolicy in public async/sync constructors, FromAdapters and FromConfig. Internal
  > Frozen construction forces false. Generation has no request/per-call raw override.
  > True SSE remains raw-absent; a buffered JSON response to a stream request can retain
  > its actual parsed root. Source save alone does not complete this box.
  > Core/public, adapter and independent tests are saved. Adapter cold review is clean;
  > core review remains in progress. Root's first raw compile built the production and
  > observer projects, then stopped on two CS9007 test literal errors; no tests ran.
  > Test corrections also add omitted-default constructor/config async/sync controls.
  > Log: `.tmp-tests/sdk-six-raw-gate-35c1b48663fe4e88ac26691e523e1adc/build.stdout.log`.
  > Closure: core, adapter and test cold reviews are clean. Root corrected the SSE test
  > fixture's terminating blank line; zero-warning build and 8/8 raw controls pass at
  > `.tmp-tests/sdk-six-raw-gate-af0fca97b78f4a3ea6037391feda1729/`. Full serialized
  > native gate passes 708 unit plus 93 conformance tests at
  > `.tmp-tests/sdk-six-raw-preservation-13182f74270d462fb1627604d66eb917/`.
  > Fresh preservation: Frozen 102/102, request-policy 29/29, accounting 42 shared plus
  > two observed native cases. SDK.7 rich-generation and parent SDK.6 remain unchecked.

## 5. SDK.6b contracts that block client/core implementation

No public buffered operation surface, routing core or convenience overload is implemented
until all three source contracts below are accepted. This prevents a one-call API from
accepting batch, routes, retention or manifest options it cannot honor.

- [x] **6b.1 — Route/default/health/retry and config contract.** Map
  `async_client.py:2679-2697`, config operation-route parse/dump, and
  `operations.py:96-173,343-378,423-446,638-715` to exact C# resolver/health/retry seams.
  Settle explicit target/route precedence, embedding/rerank-only config keys, operation
  declaration/runtime refusal placement, health, retry clocks and aggregate errors. Map
  Python's credential-refresh callback behavior against actual native pool support before
  core implementation; do not assume an auth-refresh hook exists. Freeze the complete
  appended convenience-overload parameter order here, after request-family signatures are
  already fixed. Gate: source map plus cold critique accepted.
  > NOTE: Accepted contract in section 2 freezes convenience overload order, operation
  > route configuration and precedence, per-target retries, request-ID/terminal ownership,
  > silent ledger abandon and final publication checkpoints. Credential refresh remains
  > explicitly assigned to SDK.11c. Source and lifecycle rereviews are closed.

- [x] **6b.2 — Embedding safety, batching and result contract.** Map source chunking,
  bounded concurrency, cancellation, all-or-error outcomes, successful-chunk accounting,
  target identity safety, expected-space/post-result validation, response-space construction,
  raw retention and manifest behavior. Record only actual wire, `BatchFailure`, attempt and
  logical completion/release facts: successful chunks in an all-or-error failure do not
  create per-chunk ledger commits or costs. Gate: failure/cancellation/result table accepted
  by root and cold review.
  > NOTE: Accepted indexed joined outcomes, EDI exception selection, route-terminal split
  > failure even when every chunk fails, final-only failed trails, space/intent rules and
  > ordered JsonArray/JsonNull split raw projection. No generic capability rewrite.

- [x] **6b.3 — Rerank batching, integrity and accounting contract.** Map source local index
  validation, original-index wire mapping, empty/partial ranking acceptance, per-chunk
  forwarded `topN`, split opt-in warning, unsupported cross-batch score comparison,
  usage/cost-unknown behavior, raw retention and manifest facts. Gate: adversarial
  index/score/order source contract accepted.
  > NOTE: Accepted original-index integrity, partial/empty rankings, provider order,
  > per-chunk TopN, static descriptor limits, unknown admission and result-built manifests.

## 6. Connected buffered-operation semantic slice

- [x] **6b.support — DTO and operation-route support.** After 6b.1–3 acceptance, add only
  BatchFailure, AttemptRecord.Timing, AllTargetsFailedException.BatchFailures and inert
  AnyInferConfig.OperationRoutes from the accepted contract. Support DTO and config lanes
  own disjoint production files; independent new tests cover snapshots, unchanged legacy
  constructor positions/phase, exact operation keys, null/empty/invalid route input,
  repeated targets, parse/dump equivalence and resolver/factory inertness. Client forwarding
  remains in the connected slice. Gate: root's zero-warning solution build plus focused
  support/config tests and existing native regressions pass before client/core handoff.
  > NOTE: Root dispatched three disjoint source-only lanes: BatchFailure/attempt/error
  > DTOs, inert AnyInferConfig operation routes, and independent new support/config tests.
  > Root retains this checklist and serialized build/test gates. Client forwarding is not
  > part of this support save.
  > The first stamped support build compiled production but stopped at the new config
  > tests' missing AnyInfer.Capabilities import (zero warnings); root added that import
  > only. No tests ran. Log: `.tmp-tests/sdk-six-support-gate-a76dd6e175934a3a8b2376284226bf54/build.stdout.log`.
  > Closure: independent DTO, config and test reviews are clean. Root's zero-warning
  > solution build and 18 focused cases pass at
  > `.tmp-tests/sdk-six-support-gate-4fae927dc1ab4a7599cc3942dce09f47/`.
  > Full serialized native regressions pass 725 unit and 93 conformance tests at
  > `.tmp-tests/sdk-six-support-native-c20365713b3540f7af49ef20f2ca7973/`.
  > Evidence remains dirty-worktree source based on 2820ef2; no client/core or parent
  > SDK.6 acceptance is implied.

- [x] **6a.3 + 6a.4 + 6b.4 + 6b.5 — Implement public buffered operations, routing,
  batching and terminal projection as one slice.** Add `AsyncClient.EmbedAsync` /
  `RerankAsync` request and convenience overloads, matching `Client.Embed` / `Rerank`
  facades through `RunOperation`; route, batch, retry, safety, deadline, usage, existing
  ledger release and manifest behavior exactly as 6b.1–3 specify. Use the operation-specific
  constants whenever a per-call cap is null. Do not silently ignore `BatchPolicy`, operation
  routes, retain-raw, `manifest`, expected space, incompatible-fallback or return-documents.
  Publish only while open, always complete the lifecycle reservation, and never fabricate
  generation streams or a second event/ledger path. Gate: focused public async/sync fake
  adapter tests cover close/factory/provider cancellation identity, route precedence,
  health/retry/fallback, batching/cancellation/order, safety, return projection, usage,
  ledger and manifests.
  > NOTE: Root dispatched the connected implementation under disjoint ownership:
  > AsyncClient/Client/RetrievalCore/OperationManifestBuilder and internal ledger abandon;
  > a separate operation-neutral deadline helper; and independent public dispatch/batching
  > tests. Root owns plan edits and serialized gates. Source saves alone do not tick this box.
  > Deadline handoff is internal BufferedOperationDeadlineScope(timeoutS, lifecycleToken,
  > callerIdentity, TimeProvider? = null), with Token/IsExpired/DeferredFailure and joined
  > IAsyncDisposable cleanup. It captures no generation entry or stream state.
  > The deadline helper is saved/held; source review and native evidence remain open.
  > A separate independent owner has new RetrievalLifecycleTests.cs and
  > BufferedOperationDeadlineTests.cs. Dispatch/batch tests proceed against the frozen
  > overloads and existing ProviderRegistration/ProviderDescriptor surfaces, without
  > waiting for implementation-selected fixture conventions. Capability getter allowance
  > refers to the actual `Capabilities/CapabilityStore.cs` path only.
  > The first lifecycle/deadline test handoff ended without saved files. Root revoked
  > that grant and reassigned the same two new files to a different implementer; no
  > partial test source or production change was carried over.
  > The replacement's initial lifecycle/deadline tests are saved but need stronger causal
  > witnesses before acceptance: retrieval-only fakes, cancellation-held cleanup and
  > finally-safe joins, public terminal telemetry, silent ledger-abandon state, overlapping
  > timer callback disposal and competing cleanup faults. Root returned those bounded
  > revisions to the test owner; connected source remains mutable and unbuilt.
  > Independent RetrievalDispatchTests.cs and RetrievalRoutingBatchTests.cs are saved/held
  > with 16 source-only facts. A cold test-oracle/coverage review is in progress; no compile
  > or runtime acceptance of these tests or the connected core is claimed.
  > The lifecycle revision now proves noncancellable cleanup holding and captures actual
  > public terminal events. Root retained explicit factory/source-OCE and silent-abandon
  > tests as required remaining work; public SpendLedger.Record with the captured request
  > ID is an authorized state probe for stale metadata. Deadline tests are held separately
  > and still need overlapping-callback, context and competing-failure controls.
  > Root supplied the existing trusted-pricing test seam: descriptor static ModelCapabilities
  > with catalog-sourced Pricing, known EmbeddingCapabilities, public ITokenEstimator,
  > SpendPolicy and SpendLedger. This requires no new product hook or mutable-core fixture.
  > Cold dispatch-test review retained the sound existing controls but required four
  > false-pass closures: split-provider failures must not reach a second target (including
  > all chunks failing), repeated route occurrences must actually dispatch, retry exhaustion
  > must retain the source's final-only failure trail, and malformed wire values must fail
  > in core after real provider entry. The two-file test owner is completing these cases.
  > The first connected production snapshot is saved, but its chunk loop was sequential.
  > Root rejected that limitation against the accepted bounded-concurrency contract and
  > reopened only RetrievalCore.cs for indexed concurrent workers, full joins and ordered
  > source-exception selection. Other connected production files remain held; no build
  > or connected-slice acceptance has occurred.
  > First connected compile required mechanical method-brace, tuple-name, type-flow and
  > argument-name fixes, then two explicit fake IAsyncDisposable declarations and a private
  > test-delegate setter. Root's resulting solution build has zero warnings/errors at
  > `.tmp-tests/sdk-six-connected-gate-32a1595d98434adcbbb0ec78776c3ec0/`.
  > The actual dispatch collection is 27 cases: 21 pass, six fail (split-terminal fallback,
  > repeated-target telemetry, failed-attempt trails and rerank warning behavior).
  > Lifecycle/deadline collection is 11 cases: seven pass, four fail at
  > `.tmp-tests/sdk-six-connected-lifecycle-5394a354deaa43d598b625e786fe9608/`.
  > These include real provider-join/caller-identity/admission defects plus a config-test
  > readiness race; its factory must stay held while the positive reservation is checked.
  > Cold reviews additionally require atomic publication versus close, pre-cancelled
  > pre-start refusal, exact result-built manifest route/attempt projection, once-only
  > pre-start admission and actual provider-task joining before deadline disposal.
  > Connected production is held while the remaining dispatch review completes; root
  > will batch source corrections. Deadline callback tests are now exclusively reassigned
  > to the independent dispatch-test author; the lifecycle owner only fixes its factory gate.
  > All three cold reviews are complete. Root assigned one consolidated correction to
  > the original six-file connected source owner, covering admission/publication, actual
  > provider joins and owned cancellation, split terminal failures, unknown-limit ceilings,
  > per-chunk space/count safety, embedding overlays, source attempt/timing/telemetry and
  > literal warning/manifest projection. The accepted contract and test expectations stand.
  > Three causal callback tests and the held config-factory readiness fix are saved;
  > targeted test closure reviews are running separately. Do not build mutable production.
  > Dispatch oracle rereview closed the four required failure-path witnesses. Callback
  > join/first-fault and config factory-readiness controls are also source-clean; the final
  > same-owner refusal test now invokes both public disposal guards and observes outcomes
  > outside the callback. Its last bounded review remains pending.
  > Root assigned independent new RetrievalSafetyAccountingTests.cs for remaining limit /
  > capability-overlay / intent, per-chunk space/count, trusted operation accounting and
  > full manifest/privacy witnesses. It owns no production or other test files. This is
  > required coverage before connected acceptance, not a reason to change source contracts.
  > The consolidated six-file correction is saved/held and source rereviews are running.
  > Root fixed two health-recovery call names to the existing RouteState.Clear plus one
  > nullable-flow annotation. Production-only compilation now passes with zero warnings
  > at `.tmp-tests/sdk-six-corrected-production-f61022c0b2cf491ea1ba618f09ea4970/`.
  > This is not a solution/test gate: the safety/accounting test file remains mutable;
  > prior focused failures have not yet been rerun against this corrected snapshot.
  > Client/admission/manifest rereview is clean. Dispatch rereview closed most structure
  > but still requires complete successful/failed chunk trails and first-provider terminal
  > telemetry, per-chunk count/common actual-space validation, exact warnings and ordinary
  > fallback telemetry. Root reopened only those RetrievalCore methods plus the outer
  > RequestFailed catch; deadline invocation/mapping stays held for its independent review.
  > Safety/accounting tests have an initial ten-control save. Before freezing that file,
  > root requested two direct witnesses: successful-chunk retries alongside multiple failed
  > chunks, and full result-built manifest trail/default-attempt/warning/privacy projection.
  > Deadline boundary rereview closes original-provider joining and deferred-failure
  > precedence but retains one caller-identity P1: a framework WaitAsync cancellation still
  > carries the actual attempt deadline token. Root extended the same source owner's narrow
  > grant to map only that owned cancellation after all joins, preserving unrelated source
  > OCE identity and joined close-before-caller priority. No test assertion is weakened.
  > The 12-control safety/accounting file is saved/held and in cold oracle review; all test
  > files are now held. Root's test-only compile against the last built public API passes
  > with zero warnings at `.tmp-tests/sdk-six-test-source-build-9d28171451c547c2a48111c1dbcfb813/`.
  > The unchanged neutral helper's seven focused controls also pass at
  > `.tmp-tests/sdk-six-deadline-helper-7ab60732920d4a309ac75231b80d6e7e/` after correcting
  > a test-only nested AggregateException leaf inspection; the retained outer exception's
  > identity is still asserted unchanged. This is not a corrected connected-core runtime gate.
  > Closure: client/admission/manifest, dispatch/source, deadline/lifecycle and independent
  > test reviews are clean. Root's corrected focused collection passes all 55 cases at
  > `.tmp-tests/sdk-six-connected-focused-b5f1dcfa5ace4723a50b7f04c56b8c05/`.
  > The first full native run passed 779/780 unit and 93 conformance tests; the sole failure
  > was an existing probe test's unsupported assertion that its 20 ms timer cannot expire
  > before adapter entry. The timer is armed before invocation, unchanged by this slice.
  > An isolated reproduction passed; root removed only the scheduling assertion and its
  > capture, retaining timeout outcome, iterator cleanup and source-OCE identity checks.
  > Independent cold review accepted that test-oracle correction. Final zero-warning
  > solution build and all 780 unit / 93 conformance tests pass at
  > `.tmp-tests/sdk-six-connected-native-final-9d0970d26916489c8c87c02d72141b21/`.
  > Fresh preservation passes Frozen 102, request-policy 29/29 and accounting 42 shared
  > plus two observed native cases under
  > `.tmp-tests/sdk-six-connected-preservation-228f09d6b06d492bbc0afaef4601361c/`
  > (policy `run-shmznciw`, accounting `run-52u5b8b_`). BatchFailure retains nullable
  > provider detail exactly. Evidence is the dirty worktree based on 2820ef2; parent
  > SDK.6, retrieval profile, docs/package and clean-revision acceptance remain open.
  > Reopened during the 6.0.3 public-seam map: the 55 controls did not cover response caps
  > above 1 MiB or provider-owned embedding timing phases. Python forwards the public
  > request cap unchanged and copies embedding wire phases into successful attempt timing;
  > native core currently clamps the former and drops the latter. Root assigned minimal
  > core corrections plus independent new RetrievalForwardingTests.cs. A possible manifest
  > route-reason/snapshot mismatch is under bounded source review. Prior passing evidence
  > remains valid for its snapshot, but this box requires the corrected gate before closure.
  > The bounded review confirmed all three: caps must pass unchanged; successful embedding
  > timings retain provider-owned phases while split aggregate timing stays wall-time-only;
  > manifest considered reasons must use the same bounded ErrorInfo snapshot as AttemptFacet,
  > including the native missing-Detail message fallback. No nullable RouteStep migration is
  > needed because Python ErrorInfo.detail is a required bounded string. Minimal corrections
  > are saved/held in RetrievalCore.cs and OperationManifestBuilder.cs; new public forwarding
  > controls and targeted cold rereview remain in progress. No corrected runtime gate yet.
  > The six new controls pass after root corrected their missing capability import,
  > xUnit predicate overloads, route-only retry invocation and bounded snapshot-detail oracle
  > (`Snapshot` falls back to the message; it is not null). Evidence:
  > `.tmp-tests/sdk-six-forwarding-corrected-fd0c2534b4ae40a1bea6ef97e77ed7b6/`.
  > A full run then passed 786 unit / 93 conformance tests at
  > `.tmp-tests/sdk-six-forwarding-preservation-91f00b88900a47fcaf20a856b99b29cd/`.
  > Cold review required all four explicit-cap overload quadrants; root restored the final
  > sync-convenience pair after an author revision replaced it. A repeat full run at
  > `.tmp-tests/sdk-six-forwarding-final-9b69d97e59aa46c88bfdb21736fb487e/` passed
  > 785/786 unit and 93 conformance: unchanged SpendStore atomic replacement received a
  > Windows UnauthorizedAccessException. The isolated failing test passed at
  > `.tmp-tests/sdk-six-spend-store-repro-619fa4fd2c0247f08b3e2d31dd8f5cc0/`;
  > no SpendStore source or test was changed and no environmental cause is asserted.
  > Structured-error mapping also exposed an unsplit aggregate provider mismatch: Python
  > AllTargetsFailed has provider=null while native copied the last provider. Root assigned
  > removal of that aggregate provider only, preserving RequestFailed's real snapshot and
  > native inner exception, plus two public exhaustion controls. The corrected final gate
  > and preservation profiles remain required before rechecking this box.
  > Final closure: cap/phase/reason and unsplit aggregate-provider corrections have clean
  > bounded source and independent test reviews. All four explicit-cap overload quadrants
  > and both unsplit failure operations are covered. Root's zero-warning solution build
  > passes all 788 unit / 93 conformance tests, including all 63 connected controls, at
  > `.tmp-tests/sdk-six-forwarding-closure-80bf01f6133c4e92b81b23ae769d7603/`.
  > Fresh profiles pass Frozen 102, policy 29/29 and accounting 42 shared plus two observed
  > native cases under `.tmp-tests/sdk-six-forwarding-profiles-3f5cfc2b81474634a294ed1766872160/`
  > (policy `run-uq9zrvtq`, accounting `run-9hp2mwxi`). No SpendStore source/test change.
  > Connected acceptance is restored for this dirty-worktree snapshot based on 2820ef2.

- [x] **6.0.3 — Freeze executable `retrieval-v1` schema and public seams.** After foundation
  and connected-core handoff, bind the early input/obligation proposal to actual public
  request/result/exception/manifest seams before either observer or comparator is written.
  The input-only profile uses `tests/fixtures/retrieval-v1/`, mechanical
  `_csharp_observation` only in `tests/test_retrieval_parity.py`, native
  `AnyInfer.Retrieval`, and local `scripts/check_csharp_retrieval.py` comparison. Fixture
  matching identifies unique actual input slices and permits partial orders where source
  ordering permits them; it assumes neither FIFO matching nor expected-output lookup. Gate:
  root accepts schema, provenance/revision evidence and public-seam mapping.
  > NOTE: The public-seam artifact and cold critique are saved. Root settled unique,
  > disjoint selectors with finite ordered per-selector steps for retries/repeated calls;
  > one logical public operation per case; case-scoped aggregate ledger snapshots without
  > an invented request-ID balance join; and no dispatched_batches field. Shared lifecycle
  > evidence covers caller cancellation only. Native active client-close joining remains
  > local evidence because Python aclose has no operation registry/join guarantee.
  > Retrieval manifests have Payloads=null even with retained result raw. Concrete schema
  > authoring still waits for source-gap corrections and the remaining projection decisions.
  > The proposal author now owns an artifact-only concrete draft: finite case/procedure and
  > checkpoint tables, ordered per-selector steps, precise public output fields and typed
  > numeric paths. Core-generated diagnostic prose/hint comparison remains explicitly open;
  > scripted provider diagnostics must remain literal, and raw JSON never inherits an error
  > text exemption. No schema, input fixture, observer or comparator code is granted yet.
  > The coherent rewritten draft has bounded cold review closure. Its final P2 is settled:
  > every ledger-bearing case creates a fresh empty SpendLedger; no seeds or prior-case
  > balances are permitted. Root now grants authoring only of
  > `tests/fixtures/retrieval-v1/{schema.json,inputs.json,observations.schema.json}` and
  > the proposal artifact. Each case owns fresh clients/adapters/registry/barriers and one
  > logical retrieval operation. Root pins fixture LF bytes in .gitattributes. Actual closed
  > schemas/literal scripts still require independent review, strict pure validation and
  > root hash freeze before observers or comparator implementation. This box stays unchecked.
  > The first schema/input save has 17 unique cases and correct UTF-8/no-BOM/LF bytes.
  > Strict parsing rejects both schema files' unescaped money-regex backslashes
  > (`schema.json:14:78`, `observations.schema.json:20:78`), so meta-schema and input-schema
  > validation have not run. Literal adapter response/error/barrier geometry is also absent
  > from steps, and output capture fields are incomplete. Root holds all three files for
  > separate cold input/coverage and output/public-field reviews, then one consolidated
  > correction. No hash is frozen and no observer/comparator grant is implied.
  > Both cold reviews are complete. Input P1s require literal provider response/error/barrier
  > continuations, absent-versus-present operation metadata, truthful pricing provenance and
  > semantic selector/reference rules. Output P1s require actual wire payloads/caps/intents,
  > the typed telemetry family, manifest route/attempt/request joins, TimingFacet rather than
  > full Timing, and separate exception/snapshot error shapes. Format "1", estimated-fields
  > string maps and null retrieval payloads were validated, not defects.
  > Correction ownership is now disjoint: the original author owns only schema.json,
  > inputs.json and the proposal; a second author exclusively owns observations.schema.json.
  > Public embedding/rerank metadata records are optional and unsourced; nullable whole
  > records preserve unknown versus declared-empty. Pricing is separate sourced data;
  > initial literal overrides use the actual public client override seam, not a fabricated
  > static probe/catalog label. Caller Batch.max_items_override is independent.
  > Root's causal-capture decision adds observer-local order metadata to actual factory,
  > telemetry and resource captures, and entered/terminal order to wires. These counters
  > encode relative public capture order only: they are not SDK batch IDs, timestamps,
  > expected event order or cross-runtime equality targets. Canonical operation attempts
  > and batch-failure lists avoid invented duplicated facts. Actual script DTO continuations
  > are input stimuli; they are never deferred to hidden observer defaults.

- [x] **6.0.3a — Correct and hold literal inputs and typed schemas.** Complete the disjoint
  three-file revision and source-faithful inventory, including omitted API defaults,
  unknown/known/override limits, intent distinctions, terminal retry/batch cases and real
  malformed finite geometry. Gate: strict UTF-8/LF/JSON/meta-schema checks, input-schema
  validation and independent input/output public-field reviews pass with no response defaults.
  > NOTE: The revised output schema is saved/held. Root's strict UTF-8/no-BOM/LF JSON
  > parse and Draft 2020-12 meta-schema check pass for its 25,704-byte snapshot, SHA-256
  > `84f31ab0f0d796d2d801aa3f41f23e0049dbb76dcae620f151b0ae4fea713f59`.
  > This identifies an unfrozen validation snapshot, not profile acceptance. Targeted cold
  > output-field rereview is assigned; input schema/corpus correction remains in progress.
  > The bounded output-field rereview is clean. The revised input schema also passes strict
  > JSON and Draft 2020-12 meta-schema checks. The 32-case corpus has unique IDs and strict
  > JSON, but root validation finds 21 schema errors from flattened embedding vector arrays
  > (including the held continuation and large success case), plus a missing final LF.
  > Input coverage/setup rereview remains in progress before one consolidated correction;
  > do not weaken the nested wire-vector schema to admit a generator defect.
  > The correction restores literal nested vectors and final LF; root's strict raw-byte,
  > meta-schema and input-schema gate now passes all 32 unique cases, including the exact
  > ceiling arrays and deliberate wrong-count/ragged inputs. Coverage/setup rereview is
  > otherwise clean. A final narrow source-nullability check remains before acceptance:
  > required pricing rates/tool prices, native-top-N boolean and provider failure detail.
  > The source check confirms those three construction defects. The input owner has a
  > schema-only correction grant: required price/tool values are non-null decimal strings,
  > NativeTopN is a non-null boolean, and provider detail is a string. Optional money fields
  > retain null support. Corpus/output geometry stays held; root must rerun the pure gate.
  > The corrected schema passes raw/meta checks. Its corpus validation exposes two old
  > null output rates in the priced embedding fixtures; the input owner is replacing each
  > unused required output rate with the explicit literal decimal string "0". Other rates
  > stay unchanged. Root has not accepted the stricter corpus or run the pending controls.
  > Closure: bounded input/output source reviews and root strict raw/meta/input validation
  > pass for all 32 unique cases; seven targeted nullability controls also pass. Evidence:
  > `.tmp-tests/sdk-six-schema-hold-864810725971497796ca72130d02188c/validation.json`.
  > The two required output rates are explicit "0"; optional nullable fields stay nullable.
  > This accepts held structural/source shapes only. Semantic validation and the overall
  > 6.0.3 hash freeze remain open; no observer/comparator implementation is granted.
  > Reopened at final freeze cross-check: exception_error still requires category:string,
  > but Python AnyInferError exposes no category. Remove that native-only field from the
  > shared exception shape and synthetic baselines; keep native Category as local unit
  > evidence. This is a source-field correction, not a diagnostic normalizer. No freeze
  > or observer grant occurred; the bounded output-schema/test correction is assigned.
  > Both exception definitions now omit Category. The generic branch excludes the two
  > SpendLimit runtime type names so dropping all monetary fields cannot bypass the
  > dedicated three-money-field shape. Source rereview and synthetic spend-shape controls
  > are assigned before the final coherent gate. Money values are never computed here.
  > Bounded source rereview is clean for both exception branches and the spend-type
  > discriminator. Updated synthetic spend-shape tests and the fresh root gate remain.
  > Final closure: source and independent oracle reviews are clean, including category
  > exclusion and mandatory spend fields. Root's strict raw/meta/semantic validation and
  > all 31 pure tests pass at
  > `.tmp-tests/sdk-six-retrieval-schema-final-092836deee024b76b91a9aaa38881ed9/`.

- [x] **6.0.3b — Validate semantic input identities and schema controls.** Once the revised
  literal shapes are held, add profile-local `scripts/_csharp_retrieval_inputs.py` and
  independent `tests/test_retrieval_profile_schema.py`. Reuse strict observation mechanics;
  validate only grammar, unique IDs/selectors, descriptor references, contiguous local steps,
  kind/slice/action compatibility and finite literal data. Do not resolve routes, plan chunks,
  price requests, predict SDK outcomes or compare observers. Gate: targeted pure validators
  and malformed/unknown/duplicate/order/type/refusal mutation controls pass; root reviews
  their output. This authoring is a prerequisite, not an observer/checker implementation.
  > NOTE: Static validation checks declared grammar and identities only. Actual missing,
  > extra, ordered and once-only script consumption belongs to qualification of real
  > observer calls. The validator must not infer dispatch to prove consumption.
  > Freeze the pure entry point as `validate_inputs(source: Any, schema: dict[str, Any])
  > -> None`, raising the existing `ObservationError` through `fail` on refusal. It neither
  > mutates inputs nor reads/writes files, invokes SDKs, resolves routes or computes results.
  > Callers use the existing strict JSON loader; recursively reject non-finite decoded
  > numbers, including overflowed floats. Validate the schema before semantic checks.
  > Identity scopes are explicit: case IDs across the corpus; descriptor IDs and instance
  > names separately within a case; selector IDs, step IDs and barrier gate IDs separately
  > within a case. Selector match identity is the complete operation/instance/model/ordered
  > literal slice, so retries use the same selector's contiguous one-based step list.
  > Check literal descriptor target references without choosing an effective route; selector
  > instance/model references; case/selector/action kinds; declared protocols against the
  > supplied runtime protocols; and slice text/original-index references to caller input.
  > Preserve intentional malformed response counts/vectors/indices as finite wire stimuli.
  > Procedure checks concern kind and barrier/empty-script structure only. They may allow
  > a declared zero-wire procedure without predicting whether the SDK will refuse it.
  > Independent tests own schema/meta-schema, nullability, identities/references/ordinals,
  > type/finite-number and malformed-input controls, including positive malformed wire
  > stimuli. Implementation and test authors own disjoint new files; root owns the gate.
  > Assigned: the implementation owner has only `scripts/_csharp_retrieval_inputs.py`;
  > the independent test owner has only `tests/test_retrieval_profile_schema.py`. Fixtures
  > stay held. Each may run Ruff on its own file; root runs pytest only after both handoffs,
  > inspects the results, coordinates cold review and updates this shared checklist.
  > The module and independent test file are saved/held. The first real semantic corpus
  > check correctly refused three sequence cases mislabeled embedding_scalar_order; their
  > procedure is now embedding_validation, with requests/responses unchanged. Root's
  > combined gate passes Ruff check/format-check and all 24 pure tests, including all 32
  > cases, at `.tmp-tests/sdk-six-input-validator-a3e09038d0134f4098fddb507659f738/`.
  > Independent code/purity and test-oracle reviews remain in progress; this box and the
  > overall profile freeze stay unchecked pending those reviews and any required controls.
  > Cold review requires two code corrections: forbid external schema references before
  > any resolver can perform I/O, and bind each consumed selector to both declared and
  > actual descriptor operation protocols. Test review requires schema-valid single-cause
  > action/result/wire mutants, exact input inventory/procedure controls and real duplicate
  > ID controls. The same disjoint file owners have bounded correction grants.
  > Root clarified selector disjointness: one actual wire must not match two complete
  > operation/instance/model/ordered-slice keys. Different slices sharing caller positions
  > cannot match the same full request. Do not add static claimed-position allocation;
  > actual wire partition and exact consumption remain runtime qualification obligations.
  > The two source corrections are saved/held and in bounded cold rereview. The independent
  > test owner is completing the stronger oracles and direct reference/protocol controls;
  > root will rerun the coherent pair after that handoff. The earlier 24-test result applies
  > to the preceding snapshot and does not accept this corrected module yet.
  > Targeted source rereview is clean: external references cannot reach retrieval, local
  > resolution faults become bounded ObservationError, and selectors require both declared
  > and runtime operation support. Revised test-oracle review and the fresh pure gate remain.
  > The revised oracles have clean bounded review and root's 31-test gate passes at
  > `.tmp-tests/sdk-six-input-validator-accepted-1ecc4bd4949f481d9d8124c7f4f63b73/`.
  > Root corrected only the stale caller-cancel lookup and isolated barrier-count/selector-ID
  > controls. The final shared-category source-field correction above now requires a fresh
  > coherent schema/test gate; input-validator code remains accepted by cold review.
  > Final closure uses the 31-test schema-final gate recorded above. Input-validator,
  > output-source and test-oracle reviews are clean; no SDK policy or cost engine was added.

- [x] **6.0.3c — Root freezes the executable profile.** Reconcile the proposal/public seam
  map with actual held input and output schemas, record exact raw-byte hashes and source
  evidence, and issue bounded independent observer/checker briefs only after 6.0.3a/b.
  Gate: no open source/schema/qualification blockers; parent 6.0.3 changes only at this freeze.
  > NOTE: Frozen raw bytes and exact source/review/gate evidence are recorded in Traycer
  > `csharp-sdk/sdk-six-retrieval-profile-freeze`. The contract authoring is complete;
  > neither observer nor the comparator has executed retrieval-v1. Root now releases only
  > the disjoint 6a.5P/6a.5N/6a.5V source lanes. Parent SDK.6 remains unchecked.

- [x] **6.0.3d — Amend absent literal targets and replace the input-byte freeze.** Recorder
  source authoring found 24 cases with all four target/route sources absent. Both public
  SDKs refuse this construction. Apply only the 24 explicit per-call targets recorded in
  Traycer `csharp-sdk/sdk-six-retrieval-target-amendment`; preserve the eight routed cases
  and all other input fields. Neither observer may infer targets or resolve routing.
  Gate: cold source review, exact 24-field delta, strict raw/schema/semantic checks,
  independent no-absent-route regression and prior schema tests pass; root replaces input
  SHA/byte evidence and only then permits checker hash migration and runtime acceptance.
  > NOTE: Original 6.0.3c bytes and 31-test evidence remain historical. Parent 6.0.3 is
  > reopened for this source-found input defect. Generic proof source authoring continues;
  > actual observer acceptance is held. No actual producer output motivated the amendment.
  > Cold source review accepts all 24 literal references and the eight unchanged routed
  > cases. The input-only author is applying that field list; root added a pure literal
  > routing-presence regression. Exact saved-byte delta and the fresh pure gate remain.
  > Saved-byte validation passes at
  > `.tmp-tests/sdk-six-target-amendment-3e00177455b644dd8f0cd82d4a456317/`: exact 24-field
  > delta, eight identical routed cases, strict encoding/meta/semantic checks and all 32
  > pure tests, with Ruff check/format clean. Input is 817,076 bytes, SHA
  > `a8edaa8ba3b8c16e3331e8f80fa6e8b4405f1c9779bb5c8b1a285d65039b1c1a`.
  > Both schema hashes are unchanged. Final saved-byte/regression cold closure and root's
  > replacement freeze remain pending; the checker hash is not yet migrated.
  > Closure: bounded saved-byte/regression review is clean and root accepts the replacement
  > freeze in Traycer `csharp-sdk/sdk-six-retrieval-profile-freeze`. Parent 6.0.3 is restored.
  > Checker digest migration is now permitted with its qualification corrections; neither
  > observer nor actual comparison has run. Historical validation reports stay unchanged.

- [x] **6.0.3e — Correct unknown-limit boundary stimuli and replace the byte freeze.**
  Source review must adjudicate the exact five fields proposed in Traycer
  `csharp-sdk/sdk-six-retrieval-ceiling-amendment`. Existing boundary cases declare known
  maxima, masking unknown-ceiling coverage; embedding 2,049 with splitting enabled actually
  requires unscripted calls. Preserve prior bytes, all other fields and both schemas.
  Gate: source-only cold review, exact five-field delta, literal-input regression, strict
  encoding/meta/semantic validation and all pure tests; root records replacement SHA before
  producer/checker pin migration and accepted runtime evidence.
  > NOTE: Parent 6.0.3 is reopened for this source-found input contradiction. No fixture
  > edit is yet authorized. Earlier accepted hashes and failed observations remain evidence.
  > Source-only review approves all five fields. The input-only author saves exactly those
  > changes, and root's pure gate at
  > `.tmp-tests/sdk-six-ceiling-amendment-e315007991a140dfa8d48072b63e9b5c/` passes exact
  > delta, 28 unchanged cases, unchanged schemas, encoding/meta/semantic checks, all 36 pure
  > tests and Ruff. Held input is 817,075 bytes, SHA
  > `096c0c192ed2e97d1386923102c992c51c6242b954e992e4355be29ec23aa720`.
  > Saved-byte/literal-regression cold closure and replacement freeze remain pending.
  > Closure: saved-byte/regression review is clean. Root accepts the replacement freeze
  > in Traycer `csharp-sdk/sdk-six-retrieval-profile-freeze`; parent 6.0.3 is restored.
  > Consumer hash migration is now released. Earlier aborted native runs remain historical,
  > and no actual qualified profile or comparison is accepted by this input decision.

- [x] **6.0.3f — Complete split-failure literal retry actions.** Source review must
  adjudicate the three appended second failure actions proposed in Traycer
  `csharp-sdk/sdk-six-retrieval-retry-script-amendment`. Both split-failure cases use
  the public default two attempts but supply only one retryable failure per failing
  selector. Preserve retryability/defaults; add finite literal actions only after review.
  Gate: exact three-step-addition delta, 30 untouched cases and unchanged schemas,
  input-only regression, strict/meta/semantic/full pure tests, saved-byte closure and
  root replacement freeze before consumer pin migration or accepted runtime evidence.
  > NOTE: Parent 6.0.3 is reopened. No fixture edit is yet authorized for this proposal.
  > Source-only review approves exactly three ordinal-2 failure copies. The input-only
  > author saves those additions; root proves exact delta, 30 untouched cases, unchanged
  > schemas, strict/meta/semantic validity and all 39 pure tests with clean Ruff at
  > `.tmp-tests/sdk-six-retry-script-amendment-55b87e9810254b6a98e1563eb834d5f5/`.
  > Held input is 818,524 bytes, SHA
  > `cbf8640aa19920044e652d2a095563c480b8a5e7b18c16a2e471f89eb24a4750`.
  > Saved-byte/literal-regression closure remains before root replacement freeze/pin release.
  > Closure: saved-byte/regression review is clean. Root accepts the replacement freeze
  > at the hash above and restores parent 6.0.3. Consumer pin migration is released;
  > no native operation output, checker comparison or parent SDK.6 acceptance is implied.

- [x] **6.0.3g — Correct the non-null usage input record.** The independent producer
  control exposes required `estimated`, absent from both public Usage constructors, while
  the grammar forbids the actual cost field. Source-review the exact proposal in Traycer
  `sdk-six-retrieval-usage-schema-amendment`: replace `estimated` with required nullable
  decimal-string `cost_usd` in usage.required/properties only. Preserve the other eight
  required fields, all 32 corpus bytes, output schema and exact comparison semantics.
  Gate: source review; preserved old bytes; exact schema delta and unchanged corpus/output
  hashes; strict/meta/semantic checks; positive null/literal cost and negative missing-cost /
  estimated controls plus all prior pure controls; saved-byte review and root schema freeze.
  > NOTE: Parent 6.0.3 reopens. Root traverses all literal response/barrier continuations
  > and finds zero non-null usage records in the frozen corpus. No actual Python profile
  > or comparison triggered this source-construction correction. All proof execution and
  > schema/producer/test edits remain held pending the source-only amendment review.
  > Source review approves the exact complete-record field replacement. Root saves only
  > schema.json and preserves all previous fixture bytes at
  > `.tmp-tests/sdk-six-usage-amendment-eb54f1e10b514930a6ede44abdfef1d5/`.
  > Exact raw delta, unchanged corpus/output hashes, strict/meta/semantic checks pass32.
  > Schema is 16,286 bytes, SHA
  > `db8a6c122102bf23cf542ffd47d62f7bb6996e7ffd1f27d56877bfa16eb37f08`.
  > Independent new pure input controls and the unit-only producer usage-key migration
  > are assigned only to test files. Saved-byte/oracle review, full pure gate and root
  > schema freeze remain before restoring parent 6.0.3; no decoder/SDK/checker change.
  > Closure: source, saved-byte and independent oracle reviews are clean. Root's coherent
  > gate passes all 74 focused cases and Ruff; JUnit identities preserve the prior 39 schema
  > and 18 checker controls. Root accepts the replacement schema freeze at the hash above,
  > restores parent 6.0.3 and releases actual Python execution. Corpus/output bytes and
  > exact comparison rules remain unchanged. No Python/shared runtime result is implied.

- [ ] **6a.5 — Retrieval qualification and package consumers.** Implement the frozen
  `retrieval-v1` profile only after the connected slice is stable; qualify actual public
  typed results with literal adapters. Root registers `AnyInfer.Retrieval` in the workspace
  after policy acceptance and before package work. Add executed docs examples and package
  consumer compilation against the packaged public surface. Gate: profile/checker,
  executed examples, package consumer and every prior profile pass; root records the
  required 21 workspace steps, explicit commit and clean-revision evidence.

  After 6.0.3c, execute these disjoint proof lanes; a save alone does not accept a lane:
  > NOTE: The Python observer, native observer and verifier source owners are assigned
  > disjoint files under the frozen contract. They may read public source and mechanical
  > prior-profile conventions, but not each other's producer/checker implementation or
  > actual output. Source-only authoring is active; root has not run retrieval-v1.

  - [x] **6a.5P — Independent Python observer.** Own only
    `tests/test_retrieval_parity.py`, using public Python clients, descriptors, optional
    protocols, telemetry, results, manifests, ledger and redaction. Expose the same
    `--observe INPUT OUTPUT` CLI convention as the existing profiles. Use the strict mechanical loader
    and the frozen semantic validator; call the SDK once per case with literal input.
    Capture actual wire/factory/resource facts and finite request relations only after
    checking the actual SDK IDs. Do not read native observer code/output or comparator
    output, predict SDK outcomes, resolve routes or calculate cost. Gate: focused public
    producer controls, fresh 32-record schema-valid output and matching raw input SHA.
    > NOTE: The original author's final handoff confirms that factory/telemetry/manifest/
    > ledger projection and FromConfig/caller-cancellation orchestration remain incomplete.
    > Root froze that partial draft and revoked its edit grant. A fresh Terra implementer
    > (76cc3c5c) exclusively owns the same file for coherent completion plus focused producer
    > controls, preserving independence from native/checker source and actual outputs.
    > Only own-file Ruff is authorized; root retains review, pytest and actual CLI gates.
    > The replacement's first partial repair exposed a public construction ambiguity:
    > Python has AnyInferConfig but no AsyncClient.from_config. Root settles the frozen
    > source label through the documented public config-object-to-constructor path;
    > exact mapping is recorded in Traycer sdk-six-retrieval-operations. The same author
    > continues the sole-file grant through full captures, overrides and producer controls.
    > No fixture or SDK change is required, and this partial save does not pass the gate.
    > The second Python snapshot is saved/held with three focused controls. Root's first
    > collection fails because the standalone observer has no shared-helper import path;
    > a diagnostic run with explicit scripts PYTHONPATH and isolated cache passes two of
    > three, while the config control fails on its unregistered fake descriptor. Evidence:
    > `.tmp-tests/sdk-six-python-producer-controls-43f39d432bff4f51b24676b9ab629814/`.
    > A fresh independent cold review (09030f43) now owns source/schema/control critique.
    > No actual Python observation or paired comparison has run. The owner stays held
    > pending one consolidated source and meaningful-control correction.
    > Cold review confirms five P1 groups: standalone imports; actual typed wire/error/
    > cancellation capture and complete evidence redaction; truthful Python 3.12+ optional
    > protocols; shared occurrence ordering and finally-safe joins/consumption; meaningful
    > public producer controls. Root returns one consolidated sole-file correction to the
    > same owner. Its own focused pytest is now authorized with fresh cache/temp paths,
    > alongside Ruff; full corpus/CLI and paired execution remain root-only and held.
    > Close-completed must reflect successful close. An SDK primary retains precedence
    > over only close cleanup; harness/correlation/consumption faults invalidate evidence.
    > The corrected source is saved/held. Root's standalone collection and Ruff now pass
    > all three existing controls without PYTHONPATH assistance at
    > `.tmp-tests/sdk-six-python-source-controls-fa78f1cd801b456e8f8e26babdf277c8/`.
    > This small collection does not cover the required high-risk producer paths. Root
    > assigns a fresh independent owner (671b635d) only new tests/test_retrieval_producer.py,
    > while the existing reviewer checks the held implementation. The test owner may run
    > only that new focused file and Ruff; producer/core/fixture changes remain excluded.
    > 6a.5P stays open until source and expanded public-control gates close.
    > Source rereview closes the major protocol/wire/redaction/order corrections but
    > retains three P1s: nested tool-rate Decimal conversion, cancellation/early-terminal
    > finalization with unconditional cleanup waits and bypassed global validation, and
    > nonfinite generated evidence. Root releases only those producer corrections; the
    > independent test owner continues authoring but holds execution until source re-freezes.
    > Finalization must join all started tasks and attempt close despite unrelated observer
    > cancellation, validate global correlation/consumption, then restore original failure
    > precedence. No SDK, schema, fixture or checker changes are authorized.
    > The three residual producer corrections are saved/held. Author's own-file run
    > passes three controls and Ruff at
    > `.tmp-tests/retrieval-observer-6f4735d990174bd3858441a6311e510a/`.
    > Root requests bounded source rereview and releases the separate expanded control
    > file's focused pytest/Ruff now that producer writes have stopped. No actual corpus
    > or paired execution is released until both gates close.
    > Expanded controls expose a further pricing-construction defect: currency "USD"
    > was included in Decimal coercion. Root restricts conversion to the five public
    > rate fields; the nested tool-rate conversion remains separate. Rereview closes
    > numeric validation and early no-entry cleanup waits but retains cancellable inner
    > joins and discarded task errors. Root assigns only that boundary/helper to a fresh
    > Sol worker (3e2b2a96), under the single-task escalation recorded in Traycer
    > sdk-six-retrieval-operations. Original producer author stays frozen, and expanded
    > pytest reruns pause until this narrow source correction is saved/held.
    > The narrow join correction is saved/held. Root's combined gate at
    > `.tmp-tests/sdk-six-python-combined-74cbb1f12c5d4bff91a04e159ec8df15/`
    > passes 11/14 focused cases. Three failures need public-source oracle adjudication:
    > completion cost asserted with null reported usage, a total barrier cleanup/release
    > order, and a terminal-provider-type expectation on a Config-producing fallback.
    > Root applies Ruff's formatting-only two-line wrap; format-check now passes for both
    > files. Source join and cold oracle review remain required before another gate.
    > Bounded source review is now clean, including the narrow repeated-cancellation join
    > correction and currency/rate typing. Cold oracle review confirms four test P1s:
    > null-usage pricing/nonempty-map assumptions; successful retry/fallback treated as
    > terminal failure; invented cleanup-before-release order; wrong primary terminal
    > type. Root releases only those test fixes plus deterministic repeated-cancellation
    > and non-brittle finite-refusal controls. Producer remains held; no actual corpus run.
    > First actual Python gate emits all32 schema/privacy/provenance-valid records at
    > `.tmp-tests/sdk-six-python-observer-86af3f964bb4471999d221186bc9e8c9/`
    > (314,771 bytes). Behavioral qualification passes31/32: the held cancellation case
    > lacks the associated operation_finally capture. Root adds only that record at the
    > actual wrapper finally after owned joins and before close, with original literal
    > selector/step/instance. No checker/equality/SDK change. Bounded source and exact
    > witness-control closure plus fresh focused/CLI/qualification gates remain.
    > Corrected Python closure: associated-finally source/control review is clean. Fresh
    > CLI, strict schema/privacy/provenance and behavioral qualification pass all 32 at
    > `.tmp-tests/sdk-six-python-finally-capture-cafa8f148b8f47aeb50466ba4adbd95e/`
    > (314,872 bytes). The first paired comparison then matches 4/32; public-source
    > adjudication is active for comparator structural slots, Python capability tuple
    > construction, native fallback warning and recorder subscription/resource captures.
    > 6a.5P runtime evidence is clean, but source-faithful construction acceptance stays
    > open for these paired findings. No comparison rule is changed to fit output.
  - [x] **6a.5PT — Independent Python producer controls.** Own only new
    `tests/test_retrieval_producer.py`, reading the held Python producer and public SDK
    without native/checker source or output access. Cover actual registered config and
    direct operation construction, optional protocol truth and requested-op refusal,
    public pricing overrides, typed wire/error projections, capture correlation/order,
    full evidence redaction, held caller-cancellation joins and all-path consumption /
    cleanup precedence. Use source-valid literal synthetic controls, not expected corpus
    outputs or SDK policy simulation. Gate: strict positive baselines plus meaningful
    refusal controls pass under root's focused pytest and cold oracle review before P.
    > NOTE: The independent 330-line control file is saved/held with eight coverage
    > groups. Its r2 JUnit at
    > `.tmp-tests/retrieval-producer-controls-20261019-r2/pytest.xml` records 8 passing /
    > 3 failing cases before source-backed oracle corrections and the added outer-cancel
    > control. Those saved bytes have not been rerun while producer joins are mutable.
    > Root assigns cold oracle review against public source only; neither that historical
    > run nor clean Ruff accepts this box.
    > Closure: the source-validated oracle corrections and deterministic repeated-cancel
    > control have clean cold review. All 11 independent producer controls pass in root's
    > coherent 74-test gate above, alongside 42 schema/3 local/18 checker controls. No policy
    > calculator, expected-answer table or actual producer-output fitting was introduced.
    > Reopened only for the actual-run capture gap above: add exactly one associated
    > operation_finally witness and its actual reached/cancel/finally/close partial order
    > to the held cancellation control. Existing cleanup/release ordering stays partial.
    > The exact associated witness control is saved/held. Root's focused gate passes all
    > 14 local/independent producer cases and Ruff at
    > `.tmp-tests/sdk-six-python-finally-capture-cafa8f148b8f47aeb50466ba4adbd95e/`.
    > Bounded source/control closure remains before a fresh Python CLI and qualification.
    > Bounded associated-finally source/control closure is clean and the fresh Python
    > observation/qualification passes 32/32. Root restores this focused-control gate;
    > additional paired-proof findings retain their own correction obligations.
  - [x] **6a.5N — Independent native observer.** Own only new
    `src/csharp/AnyInfer.Retrieval/` project/source files. Use the same public native
    surfaces with retrieval-only adapter compositions, literal DTO responses and actual
    typed captures; preserve zero-wire refusals, concurrency and finally-safe caller
    cancellation cleanup. Stamp assembly revision/dirty provenance as the existing native
    profiles do; accept positional `INPUT OUTPUT` after `dotnet run --project
    AnyInfer.Retrieval --`, matching the unchanged common runner. Do not read Python observer
    code/output or comparator output. Root owns
    builds, restore and later solution/workspace/test-project registration. Gate: zero-warning
    isolated project build and fresh 32-record schema-valid output with matching input SHA.
    > NOTE: Root resolved the raw-number construction question through existing public
    > JsonInteger/JsonNumber and container constructors. The recorder may own a mechanical
    > JSON bridge without internal SDK access or v0 reader/writer changes; the settled
    > boundary is recorded in Traycer `csharp-sdk/sdk-six-retrieval-operations`. Its numeric
    > preservation controls and native runtime gate remain open.
    > The native recorder is saved/held in its new project. Root's isolated restore passes.
    > The first build stops at a missing parenthesis in Projection.EmbeddingResponse; root
    > fixes only that syntax error, exposing 16 compile errors (missing JSON/capability
    > imports and duplicate RerankAsync). Evidence:
    > `.tmp-tests/sdk-six-native-recorder-initial-bbb0c11527e74f96a44ba201d4dad39b/`.
    > No recorder has run. Cold source/bridge/lifecycle review is in progress; compile and
    > semantic corrections will return to the project owner as one bounded batch.
    > Initial cold review confirms dropped ExpectedSpace, success-only script-consumption
    > validation and unverified constant request relations. Root's follow-up read identifies
    > further candidate gaps in scalar overload selection, ledger/close capture, spend-error
    > fields, public redaction, literal failure/usage construction and harness-error handling.
    > The same reviewer is verifying these before the consolidated correction is released.
    > Extended review confirms the additional construction/capture/privacy gaps. Root now
    > releases one consolidated correction only within AnyInfer.Retrieval, covering all
    > validated findings plus compiler mechanics. Actual overload selection, full literal
    > DTO fields, public override/redaction/correlation, all-path exact consumption, real
    > ledger/close checkpoints and harness-failure separation are mandatory. No SDK, schema
    > or fixture change is authorized; root rebuilds and rereviews only after a coherent hold.
    > The consolidated recorder snapshot is saved/held. Root's next isolated build finds
    > JsonProperty ambiguity and a BOM byte-array inference error; root fixes only those
    > mechanics. The build then passes with zero warnings/errors at
    > `.tmp-tests/sdk-six-native-recorder-corrected-6b9bca7135cd46b29ded2fe686a15c1d/`.
    > A temporary root unit probe invokes the compiled recorder's own bridge, not internal
    > SDK methods or the observer CLI: 13 of 17 controls pass. It confirms four remaining
    > defects in unpaired source UTF-16 rejection, constructed floating-kind preservation,
    > and invalid/inconsistent source-lexeme handling. Only FixtureJson.cs is reopened for
    > those bounded corrections. Probe source/logs are in that gate's bridge-controls/.
    > No actual SDK operation observation has run; full semantic cold closure remains open.
    > Bridge closure: the bounded source fix is saved/held. Root's build again passes with
    > zero warnings/errors, and all 17 compiled-recorder bridge controls pass in the same
    > gate (probe-after-fix.stdout.log). Full source rereview is now active, including all
    > prior capture/construction findings and actual public default/overload witnesses.
    > Consolidated cold rereview closes most original findings but retains four P1s:
    > terminal SDK errors still hide failed script-consumption validation; sequence/rerank
    > calls substitute recorder cap constants instead of exercising public nullable defaults;
    > normal close lacks an actual adapter-disposal capture; and unrelated OCEs are labeled
    > caller cancellation. Root reopened only the recorder project for these bounded fixes.
    > Existing resource kinds suffice; actual adapter disposal is captured inside DisposeAsync,
    > with literal instance and no fabricated selector/batch identity. No observer has run.
    > Those four recorder corrections are saved/held. Root's isolated build passes with
    > zero warnings/errors at
    > `.tmp-tests/sdk-six-native-recorder-closure-1197ad774bb34884a444ab82c1c633f0/`.
    > Targeted cold closure is active; no actual operation observation is yet authorized.
    > Targeted cold closure is clean. The first root native operation run aborts before
    > output because omitted max_response_bytes used GetProperty. Root fixes only that
    > optional parser path to forward null. The next zero-warning run reaches the 2,049
    > embedding case and aborts on an unscripted known-limit split. Evidence:
    > `.tmp-tests/sdk-six-native-observation-0c3c381da603438aae1ae90cd784d971/` and
    > `.tmp-tests/sdk-six-native-observation-cap-e325f04831074d86b7b31e6f6898ed77/`.
    > Root pauses runtime acceptance for source-only boundary-input amendment 6.0.3e.
    > After accepted ceiling freeze and parser closure, root's next zero-warning native
    > run aborts on over-consumption in a split-failure case. A recorder-case diagnostic
    > completes 30 cases; only the mixed/all-failed split cases lack their second literal
    > retryable failure action under the public default two attempts. Evidence:
    > `.tmp-tests/sdk-six-native-observation-ceiling-0763d2a462294294a1569fb9f5b692e9/`.
    > No 32-record output or schema/parity pass exists. Proposed amendment 6.0.3f awaits
    > source review; SDK retry and exact script-consumption behavior stay unchanged.
    > Native observer source/schema gate closure: after the accepted retry-script freeze,
    > root's fresh CLI completes all 32 observations. Strict UTF-8/no-BOM/JSON/schema,
    > exact IDs/kinds, corpus hash, revision/dirty provenance and registered-secret checks
    > pass at `.tmp-tests/sdk-six-native-observation-final-input-1c3112eb58fd4f3aa25096bd4404df74/`.
    > Output is 308,610 bytes. All recorder cold findings and the optional-cap parser have
    > bounded clean closure; prior zero-warning build and 17 bridge controls remain valid.
    > Root removed an overstrict temporary final-LF assertion: LF/final-LF is a fixture-byte
    > rule, while observation envelopes require strict UTF-8/no BOM. No producer was changed.
    > This accepts only 6a.5N's source/schema/provenance gate. Behavioral qualification,
    > Python producer, cross-runtime comparison and parent SDK.6 remain open.
    > Reopened by the first actual behavioral qualification: reviewed checker qualifies
    > 31/32 native records; split-all-failed has out-of-order telemetry capture counters.
    > Source diagnosis confirms RecordingObserver reserves order/builds outside its append
    > lock, allowing concurrent callbacks to append in reverse reservation order. Root
    > reopens only RecordingObserver.cs for atomic capture/append under its own gate; no
    > sorting, renumbering, checker waiver or SDK change is authorized. Evidence is the
    > same native gate's qualification.json. Fresh cold/build/schema/qualification follows.
    > Atomic observer capture/append is saved/held in RecordingObserver.cs only. Root's
    > new isolated build passes with zero warnings/errors at
    > `.tmp-tests/sdk-six-native-capture-closure-139ef42c36e74c58b88f08f094094e0f/`.
    > Bounded locking/correlation review is active before the fresh full observation run.
    > Corrected closure: bounded capture-lock review is clean. The fresh native CLI,
    > schema/provenance/privacy checks and behavioral qualification all pass for 32/32 at
    > `.tmp-tests/sdk-six-native-capture-closure-139ef42c36e74c58b88f08f094094e0f/`.
    > qualification.json has no failures; current input hash is unchanged. Root restores
    > 6a.5N acceptance. Python and paired comparison remain separate, open gates.
    > Reopened after independent first-pair source review: the recorder supplies its ledger
    > both as an observer and through ledger:, which subscribes it twice. It also lacks
    > actual call_entered and held-provider cleanup resource captures. Worker7e4c4794 owns
    > only the recorder correction, with capture synchronization and no SDK/schema changes.
    > Zero-warning build, bounded review and fresh 32-record qualification remain required.
  - [x] **6a.5V — Qualification and comparison.** Own only new
    `scripts/check_csharp_retrieval.py` until an independent test handoff. Reuse common
    mechanics without editing them; keep qualification, exact typed numeric comparison,
    raw/money rules, causal joins and finite error pairs profile-local. Freeze pure entry
    points `qualify_observation(case: Case, observation: dict[str, Any], *, runtime: str)
    -> None` and `compare_case(case: Case, python: dict[str, Any], native: dict[str, Any])
    -> list[dict[str, Any]]`; the latter qualifies both sides first. Refuse via existing
    ObservationError. CLI follows prior `--output-root` observer/report conventions and
    stamps exact provided corpus bytes. No output reads or execution before the pure
    qualification/mutation gate; no SDK policy/cost calculator or expected-answer table.
    Gate: independent synthetic positives qualify before missing/type/order/association/
    raw/money/error/privacy mutations; root runs the actual comparison only after that.
    > NOTE: Checker source is saved/held. Independent synthetic tests now own only
    > tests/test_csharp_retrieval_checker.py and cannot read producer code or actual output.
    > Root's first checker Ruff check finds 39 issues and formatting differences; this is
    > an initial lint failure, not a qualification or comparison result. Mechanical cleanup
    > and the independent pure gate are required before acceptance.
    > Mechanical closure: the owner removed the unused import, supplied public docstrings
    > and formatted/wrapped source without changing the frozen APIs or behavior. Root's
    > independent Ruff check and format-check both pass. Synthetic qualification/mutation
    > tests and cold review remain pending; this does not accept 6a.5V.
    > First root pure run at `.tmp-tests/sdk-six-checker-pure-fe0cdac4c57d4a27b69ac5ac87601e28/`
    > collects five tests: three pass, two fail. One failure is an invalid test mutation
    > rejected by schema before semantic qualification; the other confirms acceptance of
    > a wrong-model TargetResolved capture. Cold checker review and source-valid synthetic
    > baseline/coverage corrections remain open; no actual comparison has run.
    > Cold review confirms four P1 groups: incomplete direct wire request qualification,
    > absent causal joins across public captures, path-spelling waivers affecting raw and
    > scripted diagnostics, and false blanket terminal-event/factory requirements for
    > silent source refusals. One consolidated correction is prepared for the checker
    > owner, after the independently reviewed target amendment receives its new byte freeze.
    > The target amendment is accepted and the same checker owner now has the consolidated
    > correction grant plus exact digest migration. The synthetic test file remains held
    > pending source-valid baseline/coverage revisions; pure and actual profile gates remain
    > open. Producer source lanes continue independently under the amended literal corpus.
    > The checker correction snapshot is saved/held with clean author Ruff gates. The
    > independent test owner is now repairing schema-invalid/private-helper oracles and
    > adding full source-valid causal, numeric/raw, diagnostic/privacy and refusal controls.
    > Root has not run the corrected pure collection or actual comparison.
    > Root's next coherent checker gate passes lint/format and six of seven compound
    > tests at `.tmp-tests/sdk-six-checker-corrected-b17e0c021650419bb895f4f5f2d5e7f6/`.
    > The remaining failure is a schema-invalid synthetic manifest positive: it includes
    > server_tool_uses in the closed UsageFacet, so no semantic qualification is reached.
    > Cold correction/oracle review remains active, including required source-valid full
    > manifest and rerank/event/error/resource coverage. This is not checker acceptance.
    > Phase-B cold rereview closes direct wire forwarding and structural raw/error waiver
    > fixes, but confirms remaining capture partial-order/canonical-fact joins and repeated
    > same-target failure-occurrence association gaps. The independent test owner is now
    > repairing the full source-valid manifest positive and adding all causal/rerank/error
    > controls against the held checker. No green partial suite will close this box.
    > The expanded root run at
    > `.tmp-tests/sdk-six-checker-expanded-ebd7f19b626d4c1297dc8b2772429152/` collects
    > twelve compound tests: five pass, seven fail. Missing joins are confirmed alongside
    > four further baseline/oracle defects. The checker owner now has the causal/occurrence
    > and silent post-start Config correction; the test owner has repaired the wrong rerank
    > cap, full-exception/snapshot distinction, Config error fields/public trail and false
    > assumption that JSON Schema alone rejects nonfinite values. A schema-valid unit-only
    > distinct same-target failure case now tests occurrence swaps without changing fixtures.
    > Tests are held; root waits for the coherent checker source before rerunning the pair.
    > Phase-C source is held; root's next run at
    > `.tmp-tests/sdk-six-checker-phase-c-01f0e6377ad6475494c9d40500253be0/` passes eight
    > of twelve compound tests. Remaining findings include nonfinite-result acceptance and
    > wrong normal-close instance acceptance, plus no-op/misaddressed test mutations and
    > incomplete manifest positives. Root corrects direct requested-route/reason baselines;
    > the independent test owner now has permission to run only its pure file to finish
    > schema-valid one-cause controls. Root retains final acceptance; cold rereview continues.
    > The test owner's repaired isolated collection reports 10/13 passing; the remaining
    > negatives confirm invented manifest notes, a wrongly associated normal-close witness
    > and an infinite result vector are accepted. Cold Phase-C review also retains privacy
    > before schema diagnostics, source-exact redacted literal projection, Config-only silent
    > post-start errors, capture uniqueness and concurrent failure multiplicity. Root assigned
    > one Phase-D checker-only correction. An isolated public RedactionRegistry is allowed
    > solely for deterministic evidence projection/scanning, without global registration or
    > SDK inference/policy work. Frozen fixture bytes and equality rules remain unchanged.
    > Test source is held until that correction; root's next coherent pure gate remains open.
    > Phase-D root gate at `.tmp-tests/sdk-six-checker-phase-d-12ae9232d9a348059253d0ac0c8f1553/`
    > passes 11/12 compound tests; its remaining money mutation violates a newly enforced
    > result/completion join. Independent repair then exposes a real false refusal of
    > same-target chunk attempt=1. Cold source review also retains route candidates without
    > wires, per-event-kind diagnostic multiplicity, RequestFailed snapshot joining and
    > source-exact ellipsis bounding. Generic corrections await a consolidated grant; pins
    > stay on the accepted historical bytes until 6.0.3e freezes a replacement.
    > Phase-E checker pin migrated after accepted ceiling freeze. Root's coherent expanded
    > pure gate passes 15/17 at
    > `.tmp-tests/sdk-six-checker-phase-e-d801849673e4457f9d60396418a07179/`, Ruff clean.
    > A genuine source bug treats BatchFailure.Error (string) as ErrorInfo. The other
    > negative assumes a ConfigException RequestFailed event that retrieval does not emit;
    > source/oracle adjudication is active, along with a masked stale detail-bound positive.
    > Source and test files remain held until that review; no actual comparator has run.
    > Phase-F held source plus repaired independent oracles pass all 17 compound pure
    > tests and Ruff at `.tmp-tests/sdk-six-checker-phase-f-635fe2027ac24ea39a00b8870fec762b/`.
    > Final cold source/oracle closure is active; actual observation qualification is held
    > until that review. This does not accept 6a.5V or a cross-runtime result.
    > Cold Phase-F rereview closes the prior repairs but retains one terminal guard P1:
    > RequestFailed checks its event error type, allowing a provider-typed forged terminal
    > after the operation ultimately fails with Config. Root assigns a checker-only final
    > operation-type guard and a separate source-valid malformed-fallback control with
    > no invented public Config attempt trail. Actual qualification remains held.
    > The final-operation guard is saved/held. The independent test retains an actual
    > Config positive with no public attempts and separately exercises both a lone forged
    > failure event and the reviewer's forged matching event/attempt bundle. Coherent
    > pure gate and bounded closure remain before actual qualification.
    > Phase-G held checker and the new source-valid malformed-fallback control now pass
    > all 18 compound pure tests and Ruff in root's gate at
    > `.tmp-tests/sdk-six-checker-phase-g-1c36067ae7da43f49070f37ffe52fcb5/`.
    > Bounded guard/oracle closure is active; the actual native observations remain
    > schema/provenance-validated but not yet behaviorally qualified.
    > Bounded Phase-G guard/oracle closure is clean. Root releases actual native
    > qualification: 31/32 pass, with the sole failure traced to a recorder capture race.
    > Checker pure/source gate remains clean; 6a.5V shared-runtime/comparison acceptance
    > is still open while the native correction and Python observer complete.
    > Checker implementation gate closure: final bounded guard/oracle review is clean,
    > all 18 independent pure controls pass and all 32 corrected native observations now
    > qualify through the public entry point. Root accepts this checker/source gate only.
    > The actual Python/native comparison is explicitly 6a.5G and remains blocked on
    > the independent Python observer; no shared parity or parent SDK.6 acceptance is claimed.
    > Reopened after independent structural review: flat manifest AttemptFacet timing and
    > typed wire.failure exceptions miss their existing closed comparison rules, while ledger
    > qualification proves reservation release but not fresh/once-only completed totals.
    > Workerfe197789 owns only these checker corrections. Narrow timing/type slots retain
    > strict raw/script/money rules; ledger joins use the sole public completion/result,
    > never route/batch/pricing simulation. Independent controls and cold closure precede
    > fresh qualification/comparison. Prior 18-test evidence remains historical.
  - [x] **6a.5G — Root integrates actual proof.** Serialize producer/checker reviews and
    runs; inspect actual differences against pinned source before proposing any correction.
    Never weaken equality to fit observed results. Register the native project in solution
    and workspace only after profile acceptance, then preserve all existing profiles.
    Gate: 32 qualified shared cases, zero mismatches and accurate provenance; full native
    and workspace preservation remains required before final milestone acceptance.
    > NOTE: First actual comparison uses independently qualified 32-record envelopes with
    > identical corpus/revision/dirty metadata and matches 4/32. Evidence:
    > `.tmp-tests/sdk-six-retrieval-first-compare-05f569b8334e46f094840dbe386cb035/run-_plb6xdh/report.json`.
    > Report records the first differing path per case, not an exhaustive difference list.
    > Root assigns three source-only reviews, all barred from producer outputs: comparator
    > typed timing/error/ledger joins; public capability/warning semantics; and native
    > recorder subscription/actual resource capture. No edits or output-fitting waivers
    > are granted before those findings are adjudicated.
    > Public-source review confirms two corrections: Python observer capability arrays
    > must construct the public tuple fields (especially empty intent tuples), and native
    > successful opted-in different-target embedding fallback lacks the literal source
    > incomparability warning. Root grants only _capabilities in the Python observer and
    > successful EmbedAsync warnings in Core/RetrievalCore.cs to worker3641ff4a. No
    > native-observer/checker/output access is granted to that implementation lane.
    > Independent constructor/warning controls and cold review precede the coherent gate.
    > Both source corrections are now saved/held. Independent test owner671b635d owns
    > only expanded Python producer controls and new RetrievalFallbackWarningTests.cs;
    > producer/core sources stay held. The native recorder and checker structural reviews
    > separately confirm their narrow corrections above. Root reopens PT/N/V for those
    > grants; all actual paired proof remains open. Frozen fixture/schema bytes and equality
    > policy are unchanged. No shared acceptance follows from either earlier 32/32 envelope.
    > The constructor/warning sources and independent controls are held. Root's focused
    > gate passes all 15 Python producer cases and both native public warning controls at
    > `.tmp-tests/sdk-six-first-pair-source-controls-a674bff3a21d4ba0a3942d2dce64e44a/`.
    > Initial native compilation stopped on a missing test namespace import; root added
    > only AnyInfer.Capabilities and preserved the first failure log before the passing run.
    > Bounded source/oracle rereview remains. Recorder/checker corrections are saved/held;
    > independent checker controls and native capture rereview remain in progress.
    > Bounded source rereview closes both product/constructor fixes. Its P2 test gap now
    > has a held same-provider/different-model warning control. The coherent native suite
    > passes 791 unit and 93 conformance cases at
    > `.tmp-tests/sdk-six-first-pair-native-regressions-e3f9e5600ac7481aae70b4be904d42a6/`.
    > Accepted evidence is the two serial project runs with distinct TRX files. The first
    > solution invocation ran projects together and reused its TRX name; its logs remain
    > historical. Recorder review retains only the barrier-only cleanup capture condition;
    > that narrow correction is now held for closure. Checker source/control reviews remain.
    > The model-only warning control and both source fixes now have clean bounded review;
    > root restores PT after its 15 passing producer controls. Native capture closure also
    > confirms barrier-only cleanup emission. Root's fresh stamped zero-warning observer
    > build and serial Python/native captures each pass all 32 schema/privacy/provenance
    > checks at `.tmp-tests/sdk-six-first-pair-corrected-observers-4ff68b76a7974233bc6d4da393c74d02/`.
    > Behavioral qualification/comparison stays held. The coherent pure gate passes77/78
    > at `.tmp-tests/sdk-six-first-pair-pure-d3d5f997321b4dfe8aadd8464adb5c6a/`;
    > the new timing positive changes null presence and requires an oracle correction.
    > Cold checker review separately confirms two code P1s: a descendant wire.raw.failure
    > is classified as typed error, and typed retry_after_s checks its leaf as an object.
    > Both exact-path source corrections are saved/held for review; independent controls
    > remain held until current oracle critique returns. No equality/fixture change occurs.
    > The direct error/retry-after comparison paths have clean source review. Independent
    > oracle critique requires source-null first-token timing, literal wire raw lookalikes
    > and complete literal usage for ledger controls; those corrections are now held.
    > Root's fresh gate remains77/78 with all six Python files lint/format clean at
    > `.tmp-tests/sdk-six-first-pair-pure-closure-42443522ff154551a32eda94403ed2f5/`.
    > Timing/raw/ledger controls now pass; typed retry-after1/1.0 exposes a separate
    > qualification bug in _error_matches_literal's diagnostic-only path. Only that known
    > typed field's existing finite numeric-value rule is released for correction. Exact
    > raw/script values, frozen bytes and comparison policy stay unchanged. Fresh actual
    > envelopes remain schema-valid but behaviorally unqualified until the pure gate closes.
    > Closure: source and independent oracle reviews are clean, including the narrowly typed
    > retry-after qualification rule. Root's coherent gate passes all78 focused cases and
    > Ruff at `.tmp-tests/sdk-six-first-pair-pure-final-e6008fcb1724425cbef7b1981a81253c/`;
    > JUnit identities retain all74 prior controls with no failures/skips. Both corrected
    > envelopes independently qualify32/32. Fresh paired report matches all32 with zero
    > mismatches at `.tmp-tests/sdk-six-first-pair-corrected-compare-71379db012924db18d7198aa21dd40ff/run-tm71p636/report.json`.
    > Corpus, source revision and dirty stamps agree; frozen schema/input hashes are unchanged.
    > Root accepts P/N/V/G, registers the nonpackable retrieval project in AnyInfer.sln and
    > adds its workspace profile step. The solution test step uses -m:1; matching argv/count
    > controls pass all68 tests at `.tmp-tests/sdk-six-retrieval-registration-8fcaebb3033d4f1d82c372c553ad3fdc/`.
    > This is dirty-worktree shared-proof acceptance, not parent SDK.6 or clean-revision acceptance.
  - [ ] **6a.5D — Public consumers and delivery.** After registration, add executed docs
    examples and packaged consumers using the accepted public retrieval surface. Use docs
    in their own terms without plan links. Gate: examples, reference, package, all 21
    workspace steps and clean-revision evidence; root alone commits explicit paths.
    > NOTE: After accepted G, worker5f5b4ce4 owns only the two C# docs pages and runnable
    > retrieval example/verifier. Worker5318fd0f owns only isolated package-consumer source
    > and packaging controls. Root retains manifests/workspace/plans and serialized gates.
    > The example slice compiles, but its first execution fails because the verifier calls
    > Single on a literal two-item rerank result. Its assertion-only correction is now held;
    > SDK/fake response semantics stay fixed. Evidence:
    > `.tmp-tests/sdk-six-retrieval-delivery-4bf2728f98764206821f8940ea0dd494/`.
    > The package consumer slice is also held. Public delivery review and root serial
    > examples/package/strict-docs and full21-step workspace gates remain.
    > Delivery closure is clean at source/oracle review. Corrected examples execute,
    > all23 packaging controls pass, and the isolated local-feed NuGet consumer builds
    > with zero warnings and executes retrieval async/sync witnesses at
    > `.tmp-tests/sdk-six-retrieval-delivery-4bf2728f98764206821f8940ea0dd494/package-after-factory/run-a12xe2_p/`.
    > The first consumer build exposed one old generation factory's invariant ValueTask
    > generic return; only its IAsyncDisposable factory type is widened, preserving its
    > object and assertions. Its compile failure remains in package/run-ep8d4i4g/.
    > Strict site build, links and docstrings pass. The first doc-example gate encounters
    > WinError5 on the old pytest cache; the fresh-cache canonical docs-check passes all50
    > examples. Both logs remain in that delivery directory. Root now runs the full21-step
    > workspace gate with a fresh cache; explicit commit/clean-revision proof still follow.
    > The full gate at `.tmp-tests/sdk-six-full-workspace-e0188f8a15204cdd9341c00232e29398/`
    > passes20/21 steps. Native unit execution stalls without a result; root records the
    > owned process tree and stops that test subtree after210 seconds. Remaining profiles,
    > package and examples pass. The shell wrapper's null exit-code capture is not success;
    > the workspace summary records the failure. Fresh per-test hang diagnostics are next.
    > Diagnostic unit and solution reruns pass791/93. A bounded repetition then fails
    > Close_joins_a_held_factory_and_discards_its_late_retrieval_object_once at its close
    > wait. Evidence `.tmp-tests/sdk-six-native-hang-repeat-20261019/run-1/` is retained;
    > source/oracle diagnosis must settle its factory-release versus owned-cancel ordering.
    > Root/scout diagnosis confirms a test synchronization race: cancellation is queued,
    > so close invocation alone cannot order the factory's return after token cancellation.
    > The test now observes that actual token, asserts close is pending before release,
    > and releases every fixture hold during teardown. All7 lifecycle controls and20
    > bounded factory repetitions pass at `.tmp-tests/sdk-six-factory-barrier-20261019/`.
    > Fresh full21 execution is `.tmp-tests/sdk-six-full-workspace-20261019-r2/`;
    > independent review and final acceptance are still required. Product behavior is unchanged.
    > Closure: independent barrier review is clean. All21 canonical workspace steps pass
    > in161.1s at `.tmp-tests/sdk-six-full-workspace-20261019-r2/`, including791 unit,
    > 93 conformance, accounting42+2, policy29, retrieval32, isolated package and examples.
    > Root stages exactly99 reviewed SDK.6a/b paths; unrelated uv.lock and v/cache remain
    > untouched. An isolated clean checkout of the source commit will bind the final
    > profile/package proof without removing those unrelated files. Acceptance boxes wait
    > for that clean-revision evidence; SDK.6c is still separate.
    > Source is committed at131c7aa. Its first fresh Windows checkout exposes4 existing
    > manifest-rendering goldens compiled with CRLF from raw C# literals, while Render
    > correctly emits LF. Main/clean source differs only by checkout endings. A narrowly
    > reviewed .gitattributes rule pins that one golden-source file to LF, changing no
    > product/assertion logic. Failed clean evidence remains `.tmp-tests/sdk-six-clean-131c7aa/`.
    > Resume a fresh checkout of the follow-up commit and all21 clean workspace gates.

## 7. SDK.6c research boundary

- [ ] **6c.0 — Retrieval provider research preflight.** Follow `contracts/NEW-PROVIDER.md`
  against current upstream material for TEI or any later retrieval provider. Produce a new
  concrete wire contract, response/cancellation/error mapping and disjoint binding brief.
  Generic OpenAI compatibility remains chat-only. Gate: root accepts research and a separate
  implementation plan. This is not a completed wire plan and authorizes no adapter edit.

## 8. Preservation and final evidence

- [ ] **6.final — Integrate and preserve.** After every implementation lane is held, root
  runs serialized cold reviews, the registered retrieval project, explicit package and docs
  gates, all existing SDK5 profiles, full workspace and conformance gates. Evidence includes
  an explicit commit and clean revision. Parent SDK.6 boxes change only after these gates.

Non-goals: vector databases, persistence, ANN indexing, automatic context embedding,
model training, multimodal vectors, streaming vector/rerank output, a fake generation
adapter, guessed provider limits, a generic OpenAI retrieval extension, or global ordering
of unapproved rerank batch scores.

## 9. Resume state

Resume **6a.5D — public consumers and delivery**, then the separately scoped provider
research/final gates. Source is committed at `131c7aa5535633b62e9758b497c70400e6c953ee`;
clean-revision acceptance remains open pending the checkout-only golden-LF repair below.

Foundation, connected dispatch and P/PT/N/V/G proof gates are accepted. The corrected
shared proof independently qualifies32/32 in each runtime and matches all32 with zero
mismatches. Source/dirty/corpus metadata agree. Frozen schema/input bytes and equality
policy are unchanged. Earlier failed captures/comparisons and exact source corrections
remain in the phase notes and Traycer evidence.

The coherent focused gate passes78 cases and preserves all74 prior controls. Serial native
regressions pass791 unit and93 conformance cases. Root registered AnyInfer.Retrieval in
the solution and added the retrieval workspace step, with serial native test scheduling;
all68 workspace controls pass. The dirty-worktree full21-step gate passes below.

Public examples/docs and isolated package-consumer sources are saved/held with clean
delivery review. Corrected examples, all23 packaging controls, the warning-free isolated
consumer, strict docs and all50 doc examples now pass. The verifier's first Single failure,
one old generic factory compile failure and old-cache doc-test failure remain preserved.
All21 fresh-cache workspace steps pass in161.1s at
`.tmp-tests/sdk-six-full-workspace-20261019-r2/`, including791 unit and93 conformance cases.
The earlier20/21 run, unit stall and reproduced factory-test race remain preserved. Its
test-only token barrier has clean independent review, all7 lifecycle controls and20 passing
factory repetitions. Exactly99 reviewed SDK.6a/b paths are committed. The first clean
checkout exposes4 CRLF raw-string manifest-golden failures; its source is otherwise identical.
The reviewed narrow LF checkout rule preserves those exact assertions. Resume a fresh
checkout after its follow-up commit, all21 clean workspace gates and plan-only acceptance.
SDK.6c remains unstarted:
new retrieval providers require current upstream research and a separate accepted binding
plan before adapter edits. Parent SDK.6 boxes remain unchecked.
