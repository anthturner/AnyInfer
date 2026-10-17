# AnyInfer C# proof

**Resume from the first unchecked box.** This is the bounded `core-generation` v0
proof plan authorized by the existing M0–M2 execution request. Read the frozen release,
[shared profile](../../specification/core-generation.md), and
[maintenance contract](../../specification/MAINTENANCE.md) before executing a box. A box is
complete only after its named gate passes. The coordinator alone records M2.1's
**proceed / narrow / stop** decision, commits, tags, or writes a final report.

## 1. Frozen inputs and decision boundary

| Item | Immutable identity / required use |
|---|---|
| Retrieval tag | local annotated `corpus/core-generation-v0` at `4208172c432ba03166e4422c4e69ac18d24eab0e` |
| Release | `core-generation-v0`, SHA-256 `16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391` |
| Python qualified report | `specification/reports/python-a186458.json`, source C `a186458c750a50847c1785dd356ca9479f2dd53e`; 102 cases: 93 pass, 9 extension |
| Python reference input | `fc537872b4e419fa0a01c60e595288099924564b` |
| C# target | 102 passes and `extensions: []`; the 9 explicitly eligible cases enter their defined native `unsupported_input` path before inference. Python-extension/C#-pass is the only permitted asymmetry. |

The corpus is data, never a C# code dependency. The C# driver verifies the selected release
before execution, reads only the selected `--root` inputs, and does not use Python helpers or
expected data to execute a fixture. The comparator alone consumes expectations.

> **Decision status — PROCEED, coordinator gate accepted 2026-10-16.** The frozen corpus and
> independent critique support this bounded native proof within the existing M0–M2 execution
> authorization, reaffirmed by the user. Project/type ordering, invocation lifetime, selected-root
> execution and SDK resolution are settled below. A discovery that the frozen corpus requires
> a behavior outside this plan stops the
> relevant box and records `narrow` or `stop`; it does not silently grow scope.

## 2. Scope and layout

Included: async buffered and streaming generation; normalized events/results/errors; routing,
retry, health and repair; admitted schema subset and prompt injection; fixture and OpenAI chat
transport adapters; the independent driver, six native proofs, qualified-report comparison,
website documentation alignment, and the corresponding CI/CD audit and updates.

Excluded: sync API, accounting, provider breadth, packaging, publishing, general JSON Schema,
Python policy reuse, and any claim that C# is a supported product implementation.

Create the following under `src/csharp/` only when its owning box begins:

| Path | Owner | Responsibility |
|---|---|---|
| `global.json`, `Directory.Build.props`, `AnyInfer.sln`, C# entries in `.gitignore` | M2.2a | SDK and deterministic compiler settings; project graph and local C# build-output exclusions. |
| `AnyInfer/AnyInfer.csproj` | M2.2a | `net8.0` BCL-only class library. |
| `AnyInfer.Tests/AnyInfer.Tests.csproj` | M2.2a | xUnit unit project. |
| `AnyInfer.Conformance/AnyInfer.Conformance.csproj` | M2.2a | Empty xUnit project using its TestSDK-generated entry point until M2.4a. |
| `AnyInfer.Conformance/Program.cs` | M2.4a | BCL executable driver entry point; disables the generated entry point when added. |
| `AnyInfer/*.cs`, `AnyInfer/Json/*.cs`, `AnyInfer/Providers/*.cs`, `AnyInfer/Schema/*.cs` | M2.2a–d | immutable data/adapter contract, JSON codec, schema/extraction/prompt implementation. |
| `AnyInfer/Providers/*.cs`, `AnyInfer/Internal/*.cs`, `AnyInfer/Core/*.cs` | M2.3 | adapter boundary, lifecycle, core orchestration. |
| `AnyInfer.Tests/*.cs` | M2.2–M2.3 | focused native unit and lifecycle proof tests. |
| `AnyInfer.Conformance/*.cs` | M2.4–M2.5 | readers, adapters, runner, projection/comparison, proofs, report writer. |

`global.json` under `src/csharp/` pins SDK `8.0.425` with `rollForward: latestPatch`; it does
not apply when a command starts at the repository root. Every .NET gate therefore runs from
`D:\projects\AnyInfer\src\csharp` inside a PowerShell
`Push-Location` / `try` / `finally { Pop-Location }` wrapper and first records `dotnet --version`.
Commands below use paths relative to that directory. Common properties enable nullable and
implicit usings, deterministic builds, and warnings as errors. Runtime projects have no NuGet
dependencies. Test projects use `xunit` 2.9.3 ([release](https://xunit.net/releases/v2/2.9.3)),
`xunit.runner.visualstudio` 3.1.5 ([release](https://xunit.net/releases/visualstudio/3.1.5)), and
`Microsoft.NET.Test.Sdk` 17.14.1 ([NuGet](https://www.nuget.org/packages/Microsoft.NET.Test.Sdk/17.14.1)),
all private assets. Restore is expected because xUnit is not currently cached; the installed SDK
8.0.425 and runtime 8.0.31 make native `net8.0` execution feasible after restore.

## 3. Architecture constraints

### Public core

M2.2a establishes immutable domain and contract data: `GenerationRequest`, `Message` with an
immutable `ContentPart` list, `TextPart`, and opaque `UnsupportedContentPart(kind, original
JsonValue data)`, `Target`, `Sampling`, `RepairOptions`, `RetryPolicy`, `Route`, `Usage`,
`GenerationResult`, typed `GenerationEvent` variants, all immutable `JsonValue` domain variants,
`WireRequest` with typed optional schema, `AdapterEvent` variants,
and semantic error types. `AsyncClient` (`IAsyncDisposable`) and lazy `GenerationStream`
(`IAsyncEnumerable<GenerationEvent>`, `IAsyncDisposable`) are implemented only in M2.3 after the
invocation boundary exists; no throwaway or `NotImplementedException` scaffold substitutes for
their behavior. Zero advance and double close are then safe. Errors derive from
`AnyInferException` and retain typed fields; `ProviderException`, `SchemaViolationException`, and
`AllTargetsFailedException` are required.

`UnsupportedContentPart` represents raw excluded image/tool-like input only so the native client
can admit and reject it before entry; it does not implement multimodal behavior. Message roles
retain representable tool/unknown strings and route target strings remain raw until native
normalization/lazy resolution. Schemas are raw `JsonValue`, including excluded shapes. The driver
passes these raw inputs through the client and never manufactures `unsupported_input` from a
fixture expectation.

`AnyInfer.Json` uses immutable JSON variants. Integers use `BigInteger`; finite decimal values
retain binary64 category, lexical form, and signed zero. Ordered objects preserve duplicate-key
last value and first-key position. Decode through `Utf8JsonReader`; do not use `JsonNode` or
`dynamic`. Code-point ordering uses `Rune`. Ordinary data rejects nonfinite values and lone
surrogates. Implement separate schema, type-aware, and declared numeric-control equality;
reserved literal JSON keys remain literal except at explicitly typed marker locations.

`AnyInfer.Schema` owns the admitted 2020-12 subset, extraction, `SchemaValidator`, `Issue`,
`NativeAssessment`, and `SchemaPromptRenderer`. It preserves the late malformed-keyword path,
issue selection/order/parameters, and canonical ASCII prompt JSON (sorted keys, two-space
indent). A repair consumes the selected assessment's actual native feedback and causal identity;
it never recomputes selection. C# native wording may differ within the shared template.

### Invocation, routing, and lifetime

The exact provider contract is `AnyInfer.Providers.IProviderAdapter : IAsyncDisposable` with
`IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)`.
The iterator starts only on `MoveNext`; the boundary passes the linked entry token through both
`GenerateAsync` and `GetAsyncEnumerator`. `AdapterEvent` and `WireRequest` are the M2.2a typed
translation data. The fixture adapter is conformance-only; OpenAI chat translation belongs to
M2.5. No adapter owns routing, retry, validation, repair, or health policy.

`AnyInfer.Internal.AdapterInvocationBoundary.InvokeAsync` is the sole path for original,
correction, retry, and fallback entries. It creates one linked native CTS/`EntryTimeoutScope`
per actual entry, configures the effective timeout, and keeps it alive through actual iterator
`DisposeAsync` and entry cleanup. Cleanup/dispose failure after final remains part of that entry
and fails it before usage or validation. The shared adapter is client-owned, never disposed per
entry; `AsyncClient.DisposeAsync` closes it once. No virtual timer proves a timeout. Operation,
entry, and assessment captures
are explicit operation-scoped values, never global mutable state. An internal bounded
observation seam may be visible only to `AnyInfer.Tests` and `AnyInfer.Conformance`; it cannot
change execution or derive an assessment anew.

`IOperationClock` is limited to route health and backoff, defaulting to `Stopwatch` and
`Task.Delay`; the driver supplies a virtual clock only there. Buffered generation consumes the
same native stream as streaming. Preserve usage overlay, winner selection, attempt-local
post-content state across correction, fresh repair budget after retry, lazy target resolution,
health, duplicate-target, and cleanup semantics.

### Driver and report boundary

`AnyInfer.Conformance` is both an xUnit test project and a BCL executable. Its `Program.cs`
implements an async argument parser for `--root PATH`, `--release RELATIVE_FILE`, `--verify`,
`--development`, and `--write-report`. Development alone permits `--output PATH`, defaulting
to the executable repository's `.tmp-tests/csharp-development.json`; diagnostic output must
remain under that ignored directory. It has no fourth project or
runtime package. `--root` is mandatory for driver execution and never falls back to the checkout;
the release path is relative and containment-checked. Normal `dotnet test` never publishes.
`--write-report` refuses until M2.5's complete 102-case execution has succeeded.

The project independently implements `ReleaseAssetsReader`, `FixtureReader`,
`FixtureAdapter`, `NativeRunner`, `Projection`, `Comparison`, `TransportRunner`, `NativeProofs`,
and `ReportWriter`. It checks raw hashes, closed inventory, references, containment and reparse
points itself. Fixture execution never reads `expected`; comparison alone handles scoped typed
markers with real native assessment feedback. Core HTTP markers apply only in message content;
all other JSON remains literal. Mirrors must be fresh; duplicate-key ordering and typed controls
are preserved.

A complete C# report is prohibited until all released fixture, transport, and driver proof
requirements have run. M2.4 may write only a `.tmp-tests` DEVELOPMENT/UNRELEASED subset
observation. Final publication is new-only at
`specification/reports/csharp-<rev7>.json`, after a clean committed code checkpoint and release
verification both before execution and before output.

## 4. Implementation checklist

- [x] **M2.2a — solution, immutable data, and contract scaffold.** Owner: scaffold worker; files limited to
  `src/csharp/global.json`, `Directory.Build.props`, `AnyInfer.sln`, all three `.csproj` files,
  C#-scoped `.gitignore` entries for `src/csharp/**/bin/`, `src/csharp/**/obj/`, and
  `src/csharp/**/TestResults/`, `AnyInfer/` public type files,
  `AnyInfer/Json/JsonValue.cs`, `AnyInfer/Providers/IProviderAdapter.cs`,
  `AnyInfer/Providers/WireRequest.cs`, `AnyInfer/Providers/AdapterEvent.cs`, and matching
  `AnyInfer.Tests/` type tests. Create the
  net8.0/BCL-only graph, pinned private test packages, immutable public domain/error/event data,
  `WireRequest`, `AdapterEvent`, raw content/role/target admission data, the exact
  `IProviderAdapter` signature, project
  `InternalsVisibleTo`, and an empty test/executable Conformance graph. Do not implement
  `AsyncClient`, `GenerationStream`, routing, fixture policy, or the driver here. **Gate:** from
  `src/csharp`, record `dotnet --version`, run `dotnet restore AnyInfer.sln`, then
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~PublicModel`; restore/package
  failure records its exact source before any version substitution.
  > NOTE: Accepted: net8.0 BCL scaffold and pinned SDK are in place; copied model/error/event fields include nullable base and provider phases. PublicModel passed 11 tests under SDK 8.0.425, and cold review closed.

- [x] **M2.2b — lossless JSON and equality.** Owner: JSON worker; files limited to
  `AnyInfer/Json/JsonReader.cs`, `JsonWriter.cs`, `JsonEquality.cs`, and
  `AnyInfer.Tests/JsonValueTests.cs`. Decode duplicate keys with first-position/last-value,
  preserve binary64 lexical class/signed zero, `BigInteger`, order by code point, and distinguish
  schema/type-aware/numeric-control equality only at declared call sites. **Gate:**
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~Json`
  covers duplicate keys, ±2^63 including positive endpoint, signed zero, ordinary-data refusal,
  rune ordering, and literal reserved objects.
  > NOTE: JSON authoring began alongside the M2.2a domain-field correction because the
  > held `JsonValue` contract had compiled and the source files were disjoint. M2.2a is
  > now accepted. Shared builds/tests stay serialized against stable source, and both
  > boxes must pass before schema integration.
  > NOTE: Accepted after cold closure: ordinary escaped-backslash handling no longer
  > misclassifies literal Unicode-escape text, and integer-shaped numeric metadata cannot
  > erase binary64/signed-zero category. Direct malformed UTF-8 key/value and actual
  > lone UTF-16 entry controls now refuse as `FormatException`. The SDK 8.0.425 JSON
  > gate passed 23 tests, and bounded review closed clean.

- [x] **M2.2c — schema, extraction, and prompt.** Source owner: schema worker, limited to
  new `AnyInfer/Schema/NativeAssessment.cs`, `ResponseExtractor.cs`, `SchemaValidator.cs`, and
  `SchemaPromptRenderer.cs`. An independent test worker owns only
  `AnyInfer.Tests/SchemaTests.cs`; the existing `Issue.cs`, models and JSON codec stay held.
  Implement the frozen keyword subset, exact portable issues and ordering, late
  `invalid_schema`, extraction candidates, and canonical prompt rendering.
  `SchemaValidator.Assess(schema, instance, operationId, sourceEntryOrdinal)` and
  `AssessResponse(schema, text, operationId, sourceEntryOrdinal)` return an immutable
  `NativeAssessment` with a fresh assessment ID, actual operation/entry identity, original
  enumeration and selected native findings, their messages/metadata, and portable issues.
  `AssessResponse` extracts first and validates once; native findings and feedback are created
  during those checks and retained together. A later repair must never regenerate feedback
  from projected issues. `ResponseExtractor.Extract` distinguishes parsed `JsonNull.Instance`
  from missing value. `SchemaPromptRenderer.Render` returns the full instruction plus canonical
  schema; `InjectPrompt(messages, schema)` copies containers and appends to the last system
  message or prepends a new system message. Source-only library compilation may run while
  independent tests are authored; the focused test gate waits for both held snapshots. **Gate:**
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~Schema`
  covers every admitted keyword, extraction branches, nested/dotted paths, malformed `required`,
  and each JSON rendering kind.
  > NOTE: Accepted after cold closure: exact numeric controls retain tiny and large finite binary64 values, integral `1.0` limits, and nonnegative `2147483648` / `+2^63` length and item bounds. Native findings retain original constraint and tested-instance identities; selected findings are an identity-counted subset, and malformed-candidate diagnostics retain a `FormatException` plus an actual `JsonException` subtype cause. SDK 8.0.425 Schema gate passed 48 tests; the strengthened parser-cause node passed separately. Both bounded reviews closed clean.

- [x] **M2.2d — admission boundary.** Owner: schema worker after M2.2c; files limited to
  `AnyInfer/Schema/SchemaAdmission.cs`, related request validation, and focused tests. Refuse
  excluded features and expose no extension declaration. Unit tests call the actual library
  admission helper with raw excluded content parts, tool roles, aliases and excluded schemas.
  Full client integration and zero-entry evidence follow in M2.3b, after that client exists;
  fixture parsing may never manufacture the baseline. **Gate:**
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~Admission`
  proves native `unsupported_input` classification and preserves valid construction failures.
  > NOTE: Accepted after cold closure: request admission performs native construction checks
  > before profile admission, while schema scanning inspects only schema positions. Forwarding,
  > nested-child, and NaN construction controls supplement raw role/content/alias coverage.
  > The SDK 8.0.425 Admission gate passed 34 tests and review closed clean.

- [x] **M2.2e — phase boundary.** Owner: coordinator. Run the full unit project after M2.2a–d
  compile against concrete domain/codec/schema types. **Gate:** from `src/csharp`,
  `dotnet test AnyInfer.Tests --no-restore` passes before M2.3 starts.
  > NOTE: Root's complete unit gate passed 111 tests, zero failures/skips, under SDK
  > 8.0.425 after admission and the schema readability pass. Focused gates and independent
  > reviews are closed. The repository acceptance gate passed all 13 steps in 200.9 seconds,
  > exit 0, before the foundation checkpoint commit. Resume implementation at M2.3a.

- [x] **M2.3a — invocation boundary, capture, and native timeout lifecycle.** Owner: lifecycle
  worker; files limited to `AnyInfer/Internal/AdapterInvocationBoundary.cs`,
  `EntryTimeoutScope.cs`, operation/capture records, and lifecycle tests. Every entry has a fresh
  linked CTS that remains alive through iterator disposal/cleanup; observation records actual
  creation/configuration/enter/exit/expiry/disposal and causal operation-entry-assessment
  identities. Pass the linked token into the lazy adapter iterator; cancellation propagates and
  later cleanup failure remains entry failure. **Gate:** from `src/csharp`,
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~Lifecycle` proves
  cancellation propagation, cleanup disposal, capture isolation, no global collector, and
  no adapter disposal by an individual entry. Actual client-owned closure is tested in M2.3b.
  > NOTE: Source and independent tests have disjoint ownership. The pinned internal entry API
  > is `InvokeAsync(adapter, wireRequest, operation, EntryRole, repairAssessment = null,
  > cancellationToken = default)`, returning the lazy adapter event stream. `OperationContext`
  > owns a fresh operation ID, entry ordinals and the latest actual entry/assessment; an optional
  > `OperationCapture(capacity = 4096)` retains bounded evidence. `RecordAssessment` retains
  > the actual assessment reference and `Complete` closes the context. There is no ambient
  > collector, and capture overflow makes evidence unavailable without changing execution.
  > `EntryContext` exposes operation/ordinal/role, the actual wire request, correction assessment,
  > timeout scope, captured adapter events and native/terminal failure. `EntryTimeoutScope`
  > retains its actual timeout and linked CTS objects/tokens, effective duration and lifecycle
  > state. Capture exposes entries, assessments and ordered lifecycle observations with
  > sequence, entry ordinal and name (`created`, `configured`, `entered`, `expired`,
  > `cleanup_start`, `cleanup_end`, `exited`, `disposed`). Both CTS objects live through awaited
  > enumerator cleanup; the boundary never abandons cleanup through `WaitAsync` or closes the
  > shared adapter. An actual entry timeout maps to retryable `transport` with generate/stream
  > phase and its native cancellation cause; caller cancellation takes precedence and propagates.
  > The virtual health/backoff clock remains deferred to M2.3b. No build runs while a source
  > snapshot is being edited; the focused Lifecycle gate waits for source and tests to be held.
  > NOTE: Accepted after cold closure: optional capture retains bounded evidence and freezes on
  > overflow or reuse without affecting execution; corrections retain the latest actual assessment
  > from the immediate prior entry; terminal and prior failures preserve actual failure precedence.
  > Linked native timeout and CTS lifetime extends through awaited cleanup, with disposal recorded
  > only after actual CTS disposal. Lifecycle gate passed 14 tests under SDK 8.0.425; both cold
  > source and independent-test reviews closed.

- [x] **M2.3b — core integration and routing through the boundary.** Owner: core worker; files
  limited to `AnyInfer/Core/*.cs`, `AsyncClient.cs`, `GenerationStream.cs`, and routing tests.
  Implement buffered/streaming execution only through M2.3a's concrete boundary: target
  resolution, retry/backoff/health, repair, usage overlay, post-content behavior, and
  cancel/dispose rules. **Gate:** from `src/csharp`,
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~Routing` proves lazy
  targets, duplicate targets, health expiry, retries, repair-budget reset, event ordering, and
  stream close semantics, actual native admission of all excluded input forms with zero adapter
  entries, and client disposal closing each owned adapter exactly once.
  > NOTE: Implementation is split into disjoint helper, orchestration and independent test
  > slices. Helpers own `Providers/ProviderRegistration.cs` and `Core/ProviderRegistry.cs`,
  > `RequestNormalizer.cs`, `RepairBuilder.cs`, `RouteState.cs`, `IOperationClock.cs`.
  > Orchestration owns `AsyncClient.cs`, `GenerationStream.cs`, `Core/GenerationCore.cs`
  > and the minimal bounded telemetry/repair additions in `Internal/OperationCapture.cs`.
  > Independent tests own only `AnyInfer.Tests/RoutingTests.cs`. Earlier source/tests remain
  > held. No shared build runs until both source slices are stable.
  >
  > Registration is immutable `ProviderRegistration(providerId, adapter,
  > modelCapabilities = null, maxRepairAttempts = null)`, with copied ordinal model keys
  > and `StructuredOutputProfile(Grammar = false, JsonSchema = false, JsonMode = false)`.
  > Capability lookup is per resolved model and defaults to all false; the repair ceiling
  > belongs to the provider. This keeps fixture model metadata honest and translation-only
  > adapters unchanged. `ProviderRegistry.Resolve(rawTarget)` returns
  > `ResolvedProvider(Target, Registration, Capabilities)` using frozen first-colon/model-trim
  > rules lazily. The registry exposes distinct adapters by reference for client disposal.
  >
  > `RequestNormalizer.Normalize(request)` calls native admission once and returns
  > `NormalizedRequest(Messages, Sampling, Schema, RepairBudget, TimeoutS,
  > MaxResponseBytes, Stream)`: copied concatenated text, omitted empty stop, nonnegative
  > repair budget and effective limits. `CreateWireRequest(normalized, resolved,
  > messages = null)` selects mechanism from that model's flags and injects the schema once
  > into the supplied original/correction messages. The bounded profile does not introduce
  > a caller-forced mechanism override. `RepairBuilder.Build(originalMessages, rawResponse,
  > actualAssessment)` returns `RepairPreparation(Assessment, ResponseText,
  > OriginalMessages, Messages)` with copied containers and the exact native-message template;
  > it never reassesses or reconstructs feedback from issues.
  >
  > `IOperationClock` exposes `double NowSeconds` and
  > `ValueTask DelayAsync(double seconds, CancellationToken cancellationToken = default)`.
  > `SystemOperationClock` uses native monotonic time and delay. `RouteState(clock)` owns
  > thread-safe per-client health with `IsUnhealthy(target, ttl)`, `MarkFailed(target)`,
  > `Clear(target)`, `SeedFailure(target, failedAtSeconds)` and static
  > `BackoffSeconds(policy, attemptNumber, retryAfterS)`. It never controls entry timeouts.
  >
  > Public `AsyncClient(providers)` exposes `GenerateAsync(request, cancellationToken)`
  > and `StreamAsync(request, cancellationToken)`. Internal overloads accept an explicit
  > `OperationCapture`; an internal constructor accepts `IOperationClock`, and `Health`
  > exposes that client's route state to native tests/driver. `GenerationStream.Result` is
  > read-only/null until successful terminal publication; `Operation` is internally available
  > after actual first advance. Buffering consumes exactly this stream. No operation, entry,
  > timeout or adapter resource is created by a zero-advance close. Genuine caller cancellation
  > remains native `OperationCanceledException`; the later driver identifies its own deliberate
  > cancellation stimulus when projecting the normalized cancelled outcome.
  >
  > Capture gains bounded, operation-bound `Telemetry` and `Repairs` snapshots, recording only
  > actual core emissions and actual `RepairPreparation` references. Telemetry data is
  > `TelemetryObservation(Name, Parameter = null, Reason = null, AttemptNumber = null)`.
  > Both share the existing capacity/freeze rules. Start events must correspond to actual
  > boundary entry creation, not an invented ordinal; any pending native MoveNext is observed
  > before iterator disposal. Usage synthesis, assessment and success wait for boundary cleanup.
  > Client closure cancels/awaits active stream cleanup and disposes each distinct owned adapter
  > once. The focused Routing gate waits for all three held snapshots; the whole unit gate
  > remains M2.3c.
  > NOTE: The first helper slice has clean source review and the first complete library draft
  > compiled with zero warnings/errors under SDK 8.0.425. M2.3b is not accepted: cold review
  > found whole-entry buffering, retry/health misclassification, cleanup-before-usage ordering,
  > premature usage-total synthesis, missing clamp telemetry and incomplete client cleanup.
  > One coherent source correction and corresponding independent live-stream/branch controls
  > are in progress. No Routing runtime gate or corpus qualification has run yet.
  > NOTE: The first correction compiled but its channel bridge retained an unbounded event
  > queue and could skip awaiting the pump on early close. The coordinator therefore pins a
  > direct per-entry async iterator with a small non-yield provider-error read helper: start the
  > actual first read, publish the actual entry's start mark before awaiting that read, then
  > forward events directly. A nested finally observes any pending read and awaits native
  > disposal; no detached event pump remains. First-token state belongs to each entry, while
  > the route-attempt content flag persists across corrections. Effective repair budget/clamp
  > telemetry is evaluated once per reached target after health skips and before retries;
  > local repair counts still reset for each route attempt. Focused regression controls cover
  > these state/lifetime boundaries before the first Routing gate.
  > NOTE: The first completed Routing filter is 29 passed / 1 failed under SDK 8.0.425.
  > A test-only readiness deadlock was diagnosed and corrected without changing native
  > backpressure. The remaining semantic failure loses an active iterator cleanup exception
  > from client disposal. Source closure coordination and independent concurrent-close
  > completion controls are being corrected; the focused gate must pass before this box or
  > M2.3c is accepted. Resume at M2.3b on foundation commit `210cf0d` plus the held files.
  > Concurrent client and stream close calls must await the same actual cleanup completion
  > and retain its failure outcome. The gated cleanup control now checks every close caller
  > remains pending before native release; repeated close cannot report completion while the
  > entry CTS or adapter is still owned by an active cleanup. Deliberate close cancellation
  > remains distinct from a real cleanup failure or an earlier completed read failure.

> NOTE: Accepted after cold closure: direct per-entry backpressure and start/first-token marks, route-local repair with one reached-target clamp, retry/usage fidelity, and native cleanup with shared close-failure completion are in place. SDK 8.0.425 Routing gate passed 30 tests, zero failures/skips (2.3257s, retained `ebaaed44`); helper, orchestration, and independent test reviews closed.

- [x] **M2.3c — phase boundary.** Owner: coordinator. Run the whole unit project only after
  M2.3a–b compile against the earlier concrete types. **Gate:** from `src/csharp`,
  `dotnet test AnyInfer.Tests --no-restore` passes; no conformance driver work begins on a
  failing core project.

> NOTE: Accepted after the whole `AnyInfer.Tests` gate: SDK 8.0.425, 155 passed, zero failures/skips, exit 0. M2.3a–b source and independent reviews are closed; M2.4a is next.

- [x] **M2.4a — executable driver shell, closed release and fixture readers.** Owner: conformance
  reader worker; files limited to `AnyInfer.Conformance/Program.cs`, its `.csproj` minimal
  `GenerateProgramFile=false` edit, `ReleaseAssetsReader.cs`, `FixtureReader.cs`,
  `FixtureAdapter.cs`, and reader tests. The initial M2.2a Conformance test scaffold retains the
  TestSDK-generated entry point; this box adds the real async CLI, avoids a duplicate Main, and
  implements `--root`, relative `--release`, and the read-only `--verify` mode. Development
  execution follows in M2.4b when `NativeRunner` exists. Read frozen selected inputs as
  data; validate closed typed shapes, raw hashes, path/reparse containment, exact IDs, and
  release/reference binding. No fixture glob, Python helper, checkout fallback, or report write.
  **Gate:** from `src/csharp`, both
  `dotnet test AnyInfer.Conformance --no-restore --filter FullyQualifiedName~ReleaseAssets` and
  `dotnet run --project AnyInfer.Conformance --no-restore -- --help` succeed. Tests extract an
  alternate root and run `dotnet run --project AnyInfer.Conformance --no-restore -- --root
  <absolute-extracted-root> --release releases/core-generation-v0.json --verify`, proving it is
  used; missing root, unsafe release, and tampered selected data fail.
  > NOTE: Resume this box from core checkpoint `731cd968e9ade4cc0f8b369ae3fc11675137eb17`
  > (155 native tests and all 13 repository steps passed). Authoring has three disjoint owners:
  > release/CLI owns `ReleaseAssetsReader.cs`, `Program.cs` and the minimal Conformance project
  > entry-point setting; fixture source owns `FixtureReader.cs` and `FixtureAdapter.cs`;
  > independent tests own `ReleaseAssetsTests.cs` and `ReleaseAssetsFixtureAdapterTests.cs`.
  > Earlier core/library files are held. No build/test starts until both source snapshots are
  > stable, and no worker changes Git, frozen inputs, reports or the shared plan without a lease.
  >
  > All new APIs are internal in `AnyInfer.Conformance`. `ReleaseAssetsReader.ReadAndVerify(
  > string absoluteRoot, string relativeReleasePath)` returns `ReleaseAssets` with root/release
  > paths, raw release SHA, release/profile/revision strings, read-only `Files` and ordered
  > `Cases`, and `ReferenceBinding`. `ReleaseFile` retains its sealed relative path, SHA,
  > selected full path and owned verified bytes (`ReadOnlyMemory<byte> Bytes`); later parsing
  > uses this hashed snapshot. `InventoryCase` retains Id, FixtureKind (Fixture/DriverAssertion),
  > RelativePath, Family, literal Extension, and RecipeRef. `ReferenceBinding` retains manifest
  > and environment paths/hash plus reference and driver revisions/path. Derive the exact closed
  > raw file set from inventory plus normative/schema/reference inputs; current 106/102/96
  > counts are gate facts, not hard-coded cardinality policy. Preserve inventory order.
  >
  > The supplied root is the specification directory. Sealed keys retain their exact
  > `specification/` prefix, resolving below that selected root after removing exactly that
  > prefix; the CLI release argument is `releases/core-generation-v0.json`. Never fall back
  > to the checkout. Reject unsafe/aliased paths and every reparse component, including the
  > selected root and final file, using BCL attributes. Validate closed reader-owned release,
  > inventory, reference-binding and fixture execution envelopes; retain original arbitrary
  > schema/data and comparator expectations without interpreting their semantics here.
  >
  > `FixtureReader.ReadFixtures(ReleaseAssets)` returns ordered `FixtureDocument(Case, Input,
  > Expected)`, where abstract `FixtureInput` has `CoreFixtureInput(Request, Route, Adapter)`
  > as raw `JsonObject` fields plus optional raw `JsonObject Clock` (fourth constructor argument,
  > default null), or `TransportFixtureInput(Kind, Input, Responses)` preserving raw
  > typed values. Expected is a separate raw object consumed only by the later comparator.
  > `FixtureAdapter.Create(JsonArray script, FixtureGates? gates = null)` returns a fresh
  > internal adapter, with call/remaining-entry counts for driver controls. It accepts no
  > FixtureDocument/expected data. Named `FixtureGates.WaitAsync(name, token)` / `Release(name)`
  > are internal cancellation-aware test/runner controls; they add no public library API.
  > Parse/emit actual script fields, lazy events and immediate/terminal/cleanup failures from
  > the frozen schemas; exhausted script is a harness error, not a provider verdict. Adapter
  > disposal is client-owned, and health/backoff virtual time remains runner-owned.
  > Omitted script failure fields use category defaults: retryable for rate-limit, transport
  > and provider-unavailable; phase `generate` for the allowed categories except
  > `stream_protocol` (`stream`). Entry/terminal/cleanup location does not replace an omitted
  > phase. Explicit fields, including false and null, remain literal. This corrects the
  > coordinator's earlier transient terminal-phase instruction. Cancellation consumption
  > controls require the exact ASCII positive-decimal suffix from the fixture schema.
  >
  > `Program.RunAsync(string[] args, TextWriter output, TextWriter error)` is the testable CLI
  > seam. Help and successful verification return 0; argument/asset validation errors return 2
  > with bounded category plus selected-relative path, without raw exception prose. Genuine
  > cancellation/fatal failures propagate. Development/report production remains unavailable
  > until later boxes. Verification invokes both the release reader and fixture reader, so
  > self-consistent hashes
  > cannot bypass closed executable-envelope checks. The optional fixture clock is retained
  > for later native health/backoff execution; it is never inferred from observations.
  > Tests may locate source fixtures to make an alternate extraction, but executable
  > verification reads only its explicit selected root. The alternate-root subprocess
  > uses `dotnet run --no-build --no-restore` while its test host is loaded; root also runs the
  > normal CLI gates after tests exit, avoiding concurrent output rebuilding.
  > NOTE: The first native reader gate compiled under SDK 8.0.425 and completed with
  > 19 passes / 16 failures. A Windows-only internal separator conversion rejected valid
  > sealed asset paths before their checks; canonical forward slashes must remain intact
  > until the resolver combines individual segments. The root-normalization control must
  > supply an absolute volume root, while drive-relative roots remain rejected. Case aliases
  > retain the explicit `path_alias` diagnostic. CLI diagnostics preserve safe asset/fixture
  > relative paths; manifest/map errors retain the selected release path. Unsafe or oversized
  > diagnostic paths render as `.`. The initial failures were preserved until corrected.
  > Root-relative and drive-relative Windows paths are separate rejection controls. CLI
  > path formatting is shared by argument and asset errors and keeps each diagnostic on one
  > line, including rejection of Unicode line/paragraph separators U+2028/U+2029.
  > NOTE: Accepted after root inspected the final retained SDK 8.0.425 gate: 37 passed,
  > zero failures/skips (10.7960s, `ebaaed44`). Cross-read raw JSON controls use compact,
  > order-preserving writer output rather than container reference equality; actual adapter
  > execution remains independently compared. Standalone help and verification against both
  > canonical and copied selected roots passed in `269cf12d`. Source/test review findings
  > are corrected; root directly checked the final shared single-line diagnostic guard and
  > its executable Unicode controls. Frozen release/report hashes remain unchanged.
  > Resume at M2.4b from committed core `731cd968` plus the accepted uncommitted reader files.

- [x] **M2.4b — native runner, projection, comparison, and development subset.** Owner:
  conformance runner worker; files limited to `NativeRunner.cs`, `Projection.cs`,
  `Comparison.cs`, `ReportWriter.cs`, `VirtualClock.cs`, the minimal `Program.cs` development
  dispatch, and tests. Execute without expected
  input; compare with scoped markers only after capture. Emit DEVELOPMENT/UNRELEASED diagnostics
  under `.tmp-tests` via the executable `--development` mode for an explicitly available subset.
  `--write-report` remains refused before M2.5 completion. **Gate:** from `src/csharp`,
  `dotnet test AnyInfer.Conformance --no-restore --filter FullyQualifiedName~Development` proves
  fresh mirrors, typed marker scope, ordered objects, honest extension observation, and no
  report-v0 output. The executable alternate-root development run must use the same selected
  assets without checkout fallback.
  > NOTE: Accepted preparation lives in `foundation-execution/csharp-development-preparation`
  > and `csharp-comparison-preparation`. The subset is the 85 inventory-ordered core fixtures;
  > 11 transport fixtures and six driver assertions remain explicitly unavailable. C# declares
  > no extensions, so all nine eligible core fixtures execute native admission and compare to
  > the portable unsupported-input baseline. Eligibility alone never grants extension status.
  >
  > Disjoint source ownership: native execution worker owns `NativeRunner.cs` and
  > `VirtualClock.cs`; comparator worker owns `Projection.cs` and `Comparison.cs`; delivery
  > worker owns `ReportWriter.cs` and the minimal `Program.cs` development dispatch. An
  > independent worker then owns only `DevelopmentTests.cs`. No library/core, accepted reader,
  > project/package, Python, frozen corpus or canonical report changes are authorized here.
  > Source authoring is parallel; all shared compile/test/CLI processes stay serialized.
  > The coordinator alone closes this whole-box gate and grants any shared-plan edit lease.
  >
  > Pin the execution API as `NativeRunner.RunAsync(string caseId, CoreFixtureInput input,
  > CancellationToken cancellationToken = default) -> Task<NativeRun>`. It accepts neither
  > FixtureDocument nor expected data. The execution worker owns the immutable internal record
  > `NativeRun(CaseId, Input, ConsumeMode, Events, Result, TerminalException, TerminalStage,
  > DeliberateCancellation, Capture, Clock, AdapterCallCount, RemainingScriptEntries, Mirror)`.
  > Types are string, CoreFixtureInput, string, IReadOnlyList<GenerationEvent>, nullable
  > GenerationResult, nullable Exception, string, bool, OperationCapture, VirtualClock, int,
  > int, and nullable NativeRun respectively; Mirror defaults null. TerminalStage is actual
  > construction/stream/buffered/close context. Retain actual native objects, not rendered
  > substitutes. Core friend access already exists; do not introduce a new public API.
  >
  > Construct raw roles, text/image parts, targets, original schema, sampling, repair, retry,
  > provider per-model capabilities/ceiling and health seeds from input only. Native admission,
  > defaults, routing and repair stay in the library. `VirtualClock(double startSeconds)`
  > implements IOperationClock with NowSeconds, read-only DelaysSeconds, and cancellation-aware
  > DelayAsync; positive route delays advance it, zero delays do not. No virtual entry timeout.
  > Buffered consumption uses GenerateAsync, with no invented public events. Stream consumption
  > retains actual events and Stream.Result; no-advance and double-close use the actual stream.
  > Cancellation suffixes use BigInteger comparison. Only an actual OCE caused by the fixture's
  > own event-count cancellation is retained as DeliberateCancellation; external OCE and fatal
  > runtime exceptions propagate. Known ordinary harness faults become development errors,
  > never native outcomes. Remaining script entries are recorded, not universally rejected:
  > lazy/native rejection can legitimately leave scripts unused.
  >
  > Only `streaming/buffered-equals-streamed` triggers a fresh buffered mirror after its primary
  > stream, using a new adapter, client, clock and capture from the same raw input. Mirror
  > operation/capture identity and observations stay separate. No execution choice reads expected.
  > `Projection.Project(NativeRun) -> JsonObject` validates bounded available capture and actual
  > entry/assessment/preparation/wire identity before projecting native facts. Missing/inconsistent
  > evidence raises internal ObservationUnavailableException. Original/correction role comes
  > from entry capture, never message matching. Preserve duplicate-member observation order.
  > `Comparison.Compare(FixtureDocument, NativeRun) -> DevelopmentComparison` is the sole expected
  > reader; its record is `(string Verdict, JsonObject Observation, string? Detail = null)`.
  > Compare the frozen typed positions: selected native-feedback markers only in their causal
  > message positions, earlier same-as-call references, adjacent-text coalescing, timing markers,
  > omitted-null usage, schema equality for structured values, and numeric equality only for
  > declared controls. No arbitrary marker interpretation or expected-derived observations.
  >
  > Delivery pins: `ReportWriter.RunDevelopmentAsync(ReleaseAssets, CancellationToken = default)
  > -> Task<JsonObject>` runs only core inputs and compares afterward. `WriteDevelopmentAsync(
  > ReleaseAssets, string? outputPath, CancellationToken = default) -> Task<string>` writes its
  > DEVELOPMENT/UNRELEASED document and returns the full output path. The envelope has
  > development_version as numeric JsonInteger `0`, status `DEVELOPMENT/UNRELEASED`, release_input (id/sha256),
  > available_subset `core-fixtures`, ordered cases (id/verdict/detail/observation), unavailable
  > inventory IDs, and derived counts (pass/fail/error/unavailable). It has no report_version,
  > qualified implementation metadata, or extension verdict. Failures remain honest diagnostics.
  > Output defaults to the executable repository's `.tmp-tests/csharp-development.json`;
  > --output is accepted only with --development and must resolve under that same ignored tree.
  > Relative --output paths are relative to that .tmp-tests root. Validate output before
  > executing fixtures; create the default root if absent, but require a custom parent to
  > already exist. Write compact order-preserving JSON, UTF-8 without BOM plus LF; check
  > cancellation before writing. Known output argument/filesystem errors become controlled
  > CLI exit 2. Production --write-report stays unavailable before any asset execution.
  > Resolve containment by full path and reject reparse components; never create another output
  > directory or canonical report. Program verifies selected assets first, dispatches development
  > asynchronously, keeps --write-report unavailable, and returns nonzero for fail/error rows.
  > No other native/transport/proof execution is implied by unavailable inventory rows.
  > NOTE: Initial source review requires a fresh internal FixtureGates in every native run
  > and retains the actual caught fixture-cancellation OCE, not only a flag. Projection must
  > require that consistent native evidence before emitting cancelled. Comparator corrections
  > bind actual operation/capture/source/preparation/wire provenance; require and compare the
  > one fresh mirror; enforce full typed terminal envelopes and the duplicate-member-order
  > predicate; keep byte limits type-aware; and project route delay seconds as milliseconds
  > (integral milliseconds as JsonInteger). Independent tests preserve all these controls.
  > Native build/test remains held until the consolidated sources and tests are stable.
  > NOTE: First executable Development gate compiled cleanly under SDK 8.0.425 and ran
  > 12 tests: four passed, eight failed, no skip/hang. Root's separate compiled diagnostic
  > emitted only `.tmp-tests/m24b-first-diagnostic.json`, with 43 pass, 35 fail, seven error
  > and 17 unavailable. This is an incomplete development observation, not qualification.
  > The source correction preserves native unknown usage as six portable null counters,
  > honors timing null markers and event/result attempt shapes, and validates repair wire
  > injection after retained preparation. Independent test corrections fix core-only inventory
  > filtering, actual assessment selection and effective immutable upsert stimuli. External
  > OCE propagation remains required; expected byte equality is tested independently from
  > input parsing. The next gate waits for these disjoint held corrections and review.

  > NOTE: Accepted after bounded source/test closure and root-inspected retained gates:
  > SDK 8.0.425 build passed with zero warnings/errors; Development passed 14 tests
  > (4.7616s, `ebaaed44`), including all 85 core fixtures and typed-marker coincidence,
  > mirror identity, usage, numeric category, duplicate order and causal provenance controls.
  > Root's whole Conformance gate passed 51 tests (11.0299s, `bf68f944`). Standalone
  > canonical and copied-root development executions both exited 0 (`1ff720a6`), each
  > with 85 pass, zero fail/error and 17 explicitly unavailable transport/proof rows.
  > Output is DEVELOPMENT/UNRELEASED only under `.tmp-tests`; no report-v0 or extension
  > claim is made. Frozen release and Python report hashes remain unchanged. Resume at
  > M2.4c from core `731cd968` plus the accepted uncommitted conformance implementation.
  > Root's repository checkpoint rerun passed all 13 steps in 90.1 seconds (`5aa52d46`,
  > exit 0). A local inaccessible pytest cache required a scoped cache-directory override
  > under `.tmp-tests`; test selection, warning handling and source remained unchanged.

- [x] **M2.4c — first four native proof recipes.** Owner: native-proof worker; files limited to
  `NativeProofs.cs`, `ProofTimeouts.cs`, focused proof tests, and driver dispatch. Add these exact
  inventory IDs: `driver/concurrent-operations-independent`,
  `driver/assessment-completeness`, `driver/timeout-effective-default-explicit`, and
  `driver/timeout-reset-per-entry`. Their evidence must respectively prove: concurrent distinct
  operations/assessment/entry identities and cleared scoped context; actual assessment selection
  across no-candidate, late malformed required, exhaustion, nested ordering and repair; real
  120/default versus explicit limits plus a blocked native 0.05 timeout; and four fresh 7.25s
  entry contexts across original/correction/restarted-original/correction flow. **Gate:**
  `dotnet test AnyInfer.Conformance --no-restore --filter FullyQualifiedName~NativeProofs`
  distinguishes assertion failure from unavailable evidence and propagates cancellation/fatal
  execution.
  > NOTE: Preparation and bounded critique are accepted in
  > `foundation-execution/csharp-first-proofs-preparation` and its review sibling. No
  > production-library or fixture-adapter seam changes are needed. Disjoint ownership is
  > `NativeProofs.cs` (concurrency, assessment, exact dispatch and result record),
  > `ProofTimeouts.cs` (the two native timeout recipes), `ReportWriter.cs` (development
  > dispatch only), and independent `NativeProofsTests.cs` plus the minimal staged-count
  > changes in `DevelopmentTests.cs`. No source authoring starts before the accepted
  > M2.4a/b repository checkpoint is committed; heavy gates remain serialized.
  >
  > Pin `NativeProofResult(string Verdict, JsonObject Evidence, string? Detail = null)`
  > and `NativeProofs.RunAsync(string recipeRef, CancellationToken = default)` returning
  > `Task<NativeProofResult>`. Dispatch only the four exact inventory recipe refs; delegate
  > timeout methods to `ProofTimeouts`. Check actual native objects and reference/lifecycle
  > predicates before projecting nonempty ordinary JSON evidence. A complete observed
  > predicate mismatch yields `fail` with actual evidence; missing/unavailable capture or
  > instrumentation/harness faults yield `error`. Caller cancellation and fatal exceptions
  > propagate. ReportWriter only maps this result into staged case rows, never implements
  > proof policy or consumes expected data. The observer-only JsonObject proposal is replaced
  > because it cannot carry a live predicate failure to the driver.
  >
  > Concurrency uses actual iterator-entry barriers on one client with separate captures,
  > distinguishable native outcomes/assessments and actual overlap. After both finish, run a
  > fresh schema-free operation on that client and verify no residual assessment while
  > snapshots of the first captures remain unchanged. Assessment completeness uses native
  > extraction, late malformed required, exhaustion, nested/dotted path and repair branches.
  > Compare normal and real capacity/evidence-fault runs with the same native stimulus and
  > outcome before proving unavailable observation is rejected; no synthetic finding replaces
  > missing evidence. Testable guards stay internal to the proof files.
  >
  > Timeout evidence includes successful default `120` seconds / `1048576` bytes and
  > explicit `7.25` / `4096` entries, then a real unreleased native gate under `0.05` seconds
  > with actual expiry, typed transport mapping/trail and completed CTS disposal. Reset uses
  > four actual `7.25` contexts in original/correction/restarted-original/correction order,
  > with both correction assessment/preparation links and predecessor disposal before the
  > next entry. Virtual time remains route-only; watchdogs detect hangs and never manufacture
  > outcomes. After these four proofs execute, development output has 89 executable rows
  > and 13 unavailable rows (11 transport and the last two proofs), still unqualified and
  > confined to `.tmp-tests`; all 85 core fixture controls remain intact.
  > NOTE: Source authoring begins from clean committed checkpoint
  > `5deed7715ed9ff74afd2ee841fd3f15c2cb6f528`. `recipe_ref` is the literal `driver/...` ID
  > in the verified inventory. Add `NativeProofs.IsSupported(string recipeRef)` for the
  > staged writer branch; it supports exactly these four IDs. The staged `available_subset`
  > literal becomes `core-fixtures-and-first-four-proofs`. The independent test owner retains
  > the full core-fixture loop and only updates aggregate staged-count/envelope assertions.
  > NOTE: Accepted after source/test review closure and root-inspected SDK 8.0.425 gates:
  > clean build, NativeProofs 13/0/0 (0.8533s), Development 14/0/0 (4.3859s), retained
  > `ebaaed44`; whole Conformance 64/0/0 (10.4515s), plus canonical/copied-root standalone
  > development executions, retained `65d878f7`. Each executable output has 89 pass,
  > zero fail/error and 13 unavailable, with no report-v0 claim. Actual native expiry,
  > exception/attempt identities, four CTS contexts, assessments [1,3,4], repair-wire
  > causality and cap/fault outcome preservation are covered. Empty-set and collection
  > snapshot test oracles now use real captures and ordered native element identities.
  > Frozen release and Python report hashes remain unchanged. Resume at M2.5a from
  > `5deed7715ed9ff74afd2ee841fd3f15c2cb6f528` plus these accepted proof files until
  > the repository checkpoint gate and commit complete.
  > The root repository checkpoint gate passed all 13 steps in 87.3 seconds, exit 0
  > (`5aa52d46`), with the documented scoped fresh pytest-cache directory. No executable
  > source or assertion changed during these final gates.

- [x] **M2.5a — OpenAI chat transport adapter.** Owner: transport worker; files limited to
  `AnyInfer/Providers/OpenAIChatAdapter.cs`, transport helpers, and unit tests. Use `HttpClient`
  for native request encoding and streaming parse only. Do not read expected outcomes or place
  core policy in the adapter. **Gate:**
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~OpenAIChat`
  proves method/path, semantic headers, default stream mode, payload, effective wire limits,
  status/error mapping, SSE chunks, and disposal.
  > NOTE: Accepted transport preparation and critique are recorded in
  > `foundation-execution/csharp-http-preparation` and its review sibling. Pin an internal
  > `OpenAIChatAdapter(Uri baseUrl, string apiKey, IReadOnlyDictionary<string, string>? headers = null,
  > HttpMessageHandler? handler = null)` that always creates and owns its HttpClient and
  > optional injected handler; no borrowed-client path or public configuration carrier.
  > Configure the owned client with infinite timeout so the actual entry scope owns timing.
  > `WireRequest.Stream` is the sole effective mode; the frozen config has no stream_default.
  > Send with ResponseHeadersRead and count every response byte incrementally before decoding.
  > For SSE, retain finish/usage until a valid `[DONE]`; only then emit the final event.
  > Sentinel-only completion yields stop/null, while EOF or malformed input emits no final.
  > Keep caller cancellation and actual HTTP resource disposal within the entry iterator.
  > No source authoring starts before the accepted first-four-proof checkpoint is committed.
  > NOTE: Authoring starts from clean `86f96f3b6d53cffb705661765cdd05a9644ba469`.
  > Adapter source owns `OpenAIChatAdapter.cs` and optional `OpenAIChatProtocol.cs`;
  > independent unit tests own `AnyInfer.Tests/OpenAIChatTests.cs`. The Conformance-only
  > scripted HTTP recording harness may be authored in parallel against this stable BCL
  > seam, in disjoint files, while its M2.5b integration/acceptance waits for M2.5a's gate.
  > Buffered event order is text, usage, final with the retained usage; streaming finish
  > and trailing usage do not permit final before the valid DONE sentinel.

  > NOTE: Accepted after root inspected SDK 8.0.425 retained gates: OpenAIChat 9/0/0
  > (0.7232s, d745adcc), then whole unit 164/0/0 and Conformance harness compile with
  > zero warnings/errors (0.87s, a1994df6), exit 0. Source and independent test reviews
  > closed. Tests prove aggregate physical-chunk UTF-8 byte limits/no early final, exact
  > sampling omission and usage identity, original redirect status mapping, blocked-read
  > cancellation and actual response/stream cleanup. Production redirect disabling is
  > source-inspected; synchronous and async cleanup IO both retain typed native causes.
  > The first failed/stale-binary attempt is not evidence. Resume at M2.5b from committed
  > checkpoint 86f96f3 plus the accepted held adapter/test/harness and plan files.

- [x] **M2.5b — transport runner and final two native proofs.** Owner: transport proof worker;
  files limited to `TransportRunner.cs`, `ScriptedHttpMessageHandler.cs`, transport projection
  and comparison helpers, `ProofTransport.cs`, `NativeProofs.cs` additions, the minimal
  `NativeRunner.cs` input/consumption extraction, and proof tests. Implement
  `driver/timeout-cleanup-disposal` using a native adapter-final then
  blocked iterator cleanup whose actual entry timeout expires, and
  `driver/http-correction-byte-budget-reset` using original/correction raw bodies 78/74 under
  100 bytes, ordered linked capture/wire/HTTP evidence, and result `{age:7}` with repair 1.
  Direct buffered/SSE UTF-8 overflow must show per-chunk ≤80, code points ≤80 < raw bytes,
  stream-protocol error/no final; missing/surplus HTTP script is a harness error. **Gate:**
  `dotnet test AnyInfer.Conformance --no-restore --filter FullyQualifiedName~Transport`
  passes all six recipe dispatches and records nonempty ordinary evidence with exact recipe IDs.
  > NOTE: The accepted integration map is
  > `foundation-execution/csharp-http-integration-preparation`. Keep one raw-to-native
  > `NativeRunner.ReadOperationRequest(request, route, consumeMode)` mapping and one actual
  > consumption path. Generalize `NativeRun.Input` to the existing `FixtureInput` base so
  > each run retains its original CoreFixtureInput or TransportFixtureInput reference;
  > do not wrap/copy core input and break its established identity. A Conformance-only
  > `NativeExecutionSetup` supplies actual client/clock/request plus adapter-neutral count
  > callbacks to `RunPreparedAsync`. One owner serializes that extraction after M2.5a.
  > Actual adapter-entry counts come from an explicit per-run recording adapter, separately
  > from actual HTTP SendAsync counts. It binds each received WireRequest to the next
  > recorded exchange; no ambient state or synthetic wire limit is used. Core HTTP advertises
  > only prompt fallback (all native structured capabilities false), without a repair ceiling.
  > Transport projection/comparison composes the existing native core observation and retains
  > typed marker expansion only in core_http body.messages content. All other HTTP JSON stays
  > literal. Script exhaustion or surplus remains a harness error.

  > NOTE: M2.5b authoring starts with disjoint ownership: c708 changes only NativeRunner.cs
  > for the pinned extraction first; c16 adds TransportRunner.cs and its immutable raw carrier;
  > cab adds ProofTransport.cs and the minimal NativeProofs exact final-two dispatch. Stable
  > API handoffs precede comparison/report integration and independent Transport tests. No
  > author changes library/core policy, frozen inputs, Git or plans; root grants each process
  > gate after the relevant source/test snapshots are held.
  > NOTE: The common comparison seam is CoreComparisonContext(CaseId, Expected,
  > OriginalRequest) plus Comparison.CompareCore(context, NativeRun). The existing core
  > Compare wrapper retains its entry point. Context request identity is bound to the actual
  > core input or nested transport operation request. The shared typed-message expansion
  > requires the actual captured entry/message and preserves existing schema/repair topology;
  > only the core_http HTTP message-content path invokes it. c708 owns this Comparison
  > extraction, new TransportProjection/TransportComparison, and minimal ReportWriter
  > development dispatch after the saved runner carrier. Any existing Projection helper
  > visibility change is minimal and preserves semantics. Independent tests retain all prior
  > native controls and add transport/proof controls. Once integrated, available_subset is
  > all-released-cases with derived 102 executable rows and zero unavailable; the output
  > remains DEVELOPMENT/UNRELEASED under .tmp-tests and production reporting stays refused.
  > NOTE: Transport review pins the direct outcome projection to terminal error when an
  > actual terminal exists (prefix events stay raw), otherwise the actual events array,
  > including an empty array permitted by the frozen schema. Expected both/neither branches
  > are malformed. Typed usage/final.usage allow omission only of actual-null counters;
  > only typed error.retry_after_s uses numeric-control equality. Other direct fields remain
  > type-aware. HTTP exchange ordinals are zero-based [0,1]; native entry ordinals are
  > one-based [1,2], bound by actual request references/index rather than equal numbers.
  > Final-proof corrections require actual public-stream/schema suppression after cleanup
  > failure, OCE/provider/sole-failed-attempt identity, source-text/preparation/injected-wire/
  > second-body causality, and count-safe missing/surplus evidence handling before runtime.

  > NOTE: The first compiled transport census is DEVELOPMENT only: 99 pass, one fail,
  > two error, zero unavailable. Optional retry fields must use native RetryPolicy defaults;
  > scripted response headers must reach the actual BCL response header collections. For
  > the cleanup proof, the adapter finally begins during pending MoveNext before expiry,
  > whereas the boundary cleanup_start marker records the later Dispose after that read
  > faults. Observe native cleanup readiness with actual scope/token/reference and live
  > before-expiry snapshots; then require expiry and the later boundary-disposal order.
  > Do not relabel recorder events or loosen the proof without these native observations.
  > Native DONE still yields Final; the schema's valid empty-events representation is a
  > copied-carrier comparison test, not an invented native adapter execution outcome.
  > NOTE: Accepted after bounded source/test closure and root-inspected SDK 8.0.425 gates:
  > clean build, 15 focused Transport passes with zero failures/skips (3.0130s, retained
  > ebaaed44). All eleven released transport fixtures and both final native proofs execute
  > through actual C# adapters/captures. Header replay and unreturned-response disposal,
  > optional native retry defaults, actual cleanup-before-expiry snapshots, numeric retry
  > controls, and literal input identity are covered. The final custom 429 error oracle now
  > retains its actual HTTP status rather than the original fixture's 503. Root whole-project
  > and canonical/copied-root execution passed in cc11b834; M2.5c awaits the repository gate.

- [x] **M2.5c — complete native execution.** Owner: conformance integration worker after M2.5a–b;
  files limited to conformance runner/report tests. Execute all 102 released cases, including
  actual excluded-feature admission before inference, all transport fixtures, fresh buffered
  mirrors, and every native proof. **Gate:**
  `dotnet test AnyInfer.Conformance --no-restore` succeeds; then both C# projects pass and
  `workspace check` remains green before a complete report candidate is permitted, with 102
  unique IDs, 102 pass, zero extension/fail/error. Normal conformance tests never publish;
  development/subset observations remain under `.tmp-tests`.
  > NOTE: Accepted after root-inspected SDK 8.0.425 whole-project gates (cc11b834):
  > AnyInfer.Tests 164/0/0; AnyInfer.Conformance 81/0/0 (9.9800s). Standalone canonical
  > and copied selected-root executions each produced exactly 102 unique pass rows,
  > zero fail/error/unavailable, under .tmp-tests with DEVELOPMENT/UNRELEASED status.
  > The repository gate passed all 13 steps in 83.3s, exit 0 (8bd76aa8), with the
  > documented scoped pytest cache. Frozen release and Python report hashes are unchanged.
  > Final report/provenance, native CI, cross-language qualification and website/docs
  > remain M2.G-owned; master M2.5 stays open until its final-report requirement is met.

- [ ] **M2.Ga — clean compiled-code checkpoint and CI integration.** Owner: coordinator; no
  report output. Before implementation, re-read the current CI/workspace contract. The only
  CI integration files are `workspace.py`, `tests/test_workspace.py`,
  `docs/contributing/README.md`, `docs/contributing/testing.md`, and
  `.github/workflows/ci.yml`; C# project files remain owned by their native workstream.
  Add a default `csharp` `workspace check` phase with a standard-library-only bootstrap and an
  optional command cwd so every `dotnet` command runs from `src/csharp`: `dotnet --version`,
  `dotnet restore AnyInfer.sln`, then `dotnet test AnyInfer.sln --no-restore`. The local
  `src/csharp/global.json` controls SDK selection. The additive `native-csharp` CI job uses a
  verified immutable `actions/setup-dotnet` pin with its verified `global-json-file` support,
  then invokes `python workspace.py check --only=csharp`; SDK provisioning remains CI-owned.
  It adds only a docs-only-skippable `native-csharp` dependency to `ci-ok`; all existing Python
  jobs, Python matrices, and `success|skipped` aggregate behavior remain unchanged. It installs
  no Python SDK/dependencies, creates no report, and does not run cross-language comparison.
  Keep the workspace/docs claim that `check` reproduces CI truthful by including this phase in
  the registry, descriptions, and quality-gate documentation. Commit the complete C# proof
  implementation, then require a clean checkout before production execution. Rebuild library
  and driver with the full current revision supplied as MSBuild `SourceRevisionId`, embedding it
  in `AssemblyInformationalVersion` or dedicated `AssemblyMetadata`. **Gate:** focused workspace
  tests prove the C# commands, `src/csharp` cwd/global SDK selection, native workflow dependency,
  and unchanged aggregate policy; from `src/csharp`, both C# projects pass after clean build;
  `workspace check` passes; test negatives reject wrong, stale, or foreign assembly path/revision.

  > NOTE: CI integration is deliberately deferred until the proof solution exists. The future
  > verified action pin and action input support are selected at implementation time, not guessed
  > in this plan.
  > NOTE: Final-report/provenance code and no-write tests are authored in M2.Ga before
  > its clean code checkpoint; M2.Gb executes that committed code only. Use dedicated
  > AssemblyMetadata key AnyInferSourceRevision from full lowercase 40-hex SourceRevisionId.
  > Publication anchors to the independently verified executable repository, never --root;
  > selected roots are read-only inputs. Six passing driver rows use evidence =
  > {recipe_ref, observations: actual proof evidence}; other passing rows use evidence:null.
  > Validate the exact closed report-v0 shape before any canonical destination is created.
  > Complete execution, provenance/clean-HEAD checks, second release verification, and final
  > cancellation check precede a new-only owned same-directory staging file and no-replace
  > atomic publication. Failures remove only that verified owned staging file.
  > Dependency metadata merges resolved package entries from canonical driver and library
  > assets, lowercases package IDs, rejects version conflicts, and sorts names by code point;
  > project entries are excluded and runtime-library package dependencies must remain empty.
  > Root verified setup-dotnet v6.0.0 at a98b56852c35b8e3190ac28c8c2271da59106c68
  > from official tag/source; its action.yml declares global-json-file and node24. Use
  > global-json-file:src/csharp/global.json with existing checkout/Python pins unchanged.

- [ ] **M2.Gb — final native report production.** Owner: coordinator only. Keep no-write
  `FinalReport` xUnit tests for publication guards, but use the executable driver for production.
  From the clean M2.Ga checkpoint, run from `src/csharp` with a task-specific variable set from
  `git rev-parse HEAD`: `dotnet run --project AnyInfer.Conformance --no-restore
  -p:SourceRevisionId=$csharpProofRevision -- --root <selectedroot> --release
  releases/core-generation-v0.json --write-report`. `ReportWriter` verifies the
  release before execution and before new-only publication; reads the
  loaded library/driver `Assembly.Location` and embedded revision; requires expected current
  project output paths/current HEAD; and derives resolved driver/test dependency versions from
  `project.assets.json` plus the actual .NET runtime. It writes only
  `specification/reports/csharp-<rev7>.json` with implementation `anyinfer-dotnet` version
  `0.1.0-proof`, full source/driver binding, OS/runtime/dependency data, empty runtime deps, and
  complete evidence. Do not add report-v0 fields or reuse the Python reference lock/sidecar.
  **Gate:** final report has exact 102 unique IDs, 102 pass, zero extension/fail/error, and
  wrong/stale/foreign assembly path or revision negatives fail before publication.

- [ ] **M2.Gc — cross-language qualification.** Owner: coordinator. From `src/csharp`, run
  `dotnet test AnyInfer.Tests --no-restore`,
  `dotnet test AnyInfer.Conformance --no-restore`, and
  `dotnet run --project AnyInfer.Conformance --no-restore -p:SourceRevisionId=$csharpProofRevision
  -- --root <selectedroot> --release releases/core-generation-v0.json --verify`.
  Return to the repository root for the Python
  qualified-report validator and `.venv/Scripts/python.exe scripts/compare_reports.py
  specification/reports/python-a186458.json <csharp-report>`.
  The comparison permits only Python extension/C# pass for marked fixtures. **Gate:** every
  released case qualifies and comparison exits 0. No package, tag, publishing action, or
  supported-C# claim follows from this proof.

- [ ] **M2.Gd — website documentation and delivery alignment.** Owner: documentation worker,
  after M2.Ga has completed its shared contributor quality-gate edits. The accepted audit is
  `foundation-execution/csharp-docs-ci-preparation/index.md`. Re-read the M2.Ga-owned
  contributing files before authoring, then reconcile only this exact website/design/navigation
  set: `README.md`, `docs/README.md`, `docs/index.md`, `docs/contributing/csharp-proof.md`
  (new), `docs/contributing/README.md`, `docs/contributing/architecture.md`,
  `docs/contributing/testing.md`, `docs/contributing/releasing.md`,
  `docs/reference/README.md`, `mkdocs.yml`, and `DESIGN.md`. Add one contributor-oriented C#
  proof page that states the bounded shared-corpus scope and records the verified native commands
  from `src/csharp`: `dotnet --version`, `dotnet restore AnyInfer.sln`, and
  `dotnet test AnyInfer.sln --no-restore`. Keep product, installation, public API, guide, and
  download surfaces truthful: Python remains the supported runtime and the C# proof creates no
  package, NuGet artifact, release asset, or normal report. Keep generated API reference
  discovery Python-only and add the new page under Contributing navigation. The docs-site and
  release workflows need no .NET/NuGet provisioning or report production; the only planned CI
  change remains M2.Ga's additive `native-csharp` workspace/cwd lane. Do not change frozen
  specification/release bytes or link published docs to ephemeral plans. **Gate:**
  `python workspace.py check --only=docs-check` and
  `python workspace.py check --only=docs-build` pass; focused workspace/workflow tests prove
  the C# phase, `src/csharp` cwd/global SDK selection, the additive `native-csharp` dependency,
  and unchanged Python aggregate policy; from `src/csharp`, the documented restore/test commands
  pass; then the complete workspace gate passes. M2 is incomplete until this website/docs and
  CI/CD work is accepted.

  > NOTE: The documentation and delivery audit is accepted at clean proof checkpoint
  > `731cd968e9ade4cc0f8b369ae3fc11675137eb17`; it found no required docs-site or release
  > workflow .NET/NuGet/report-production change beyond M2.Ga's future native CI lane.

## 5. Failure, resume, and ownership rules

- Stop the affected box on a frozen release hash mismatch, asset containment failure, absent
  release/reference evidence, or a corpus rule that requires behavior outside this document.
  Record the exact command, input identity, and first failing case; resume only after a
  coordinator disposition.
- A NuGet restore failure is environmental evidence, not a reason to substitute package
  versions, dependencies, or target frameworks. Record the source and retry only when the
  environment changes.
- A proof watchdog detects hangs only. It may not manufacture cancellation, timeout, adapter
  error, cleanup, timer, assessment, HTTP, or evidence facts.
- Keep file ownership disjoint by box. Re-read shared files immediately before a minimal edit.
  The coordinator serializes solution files, report output, release inputs, heavy test runs,
  commits, and tags. No worker changes Python sources, frozen corpus assets, release files, or
  report files.
- Each box report names the frozen release SHA, command, exact result, changed paths, and next
  unchecked box. For execution boxes it also records case counts and any extension/failure
  classification. Resume at the first unchecked checklist item.
