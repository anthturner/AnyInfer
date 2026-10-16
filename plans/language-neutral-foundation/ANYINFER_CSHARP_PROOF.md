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
transport adapters; the independent driver, six native proofs, and qualified-report comparison.

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

- [ ] **M2.3a — invocation boundary, capture, and native timeout lifecycle.** Owner: lifecycle
  worker; files limited to `AnyInfer/Internal/AdapterInvocationBoundary.cs`,
  `EntryTimeoutScope.cs`, operation/capture records, and lifecycle tests. Every entry has a fresh
  linked CTS that remains alive through iterator disposal/cleanup; observation records actual
  creation/configuration/enter/exit/expiry/disposal and causal operation-entry-assessment
  identities. Pass the linked token into the lazy adapter iterator; cancellation propagates and
  later cleanup failure remains entry failure. **Gate:** from `src/csharp`,
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~Lifecycle` proves
  cancellation propagation, cleanup disposal, capture isolation, no global collector, and
  no adapter disposal by an individual entry. Actual client-owned closure is tested in M2.3b.

- [ ] **M2.3b — core integration and routing through the boundary.** Owner: core worker; files
  limited to `AnyInfer/Core/*.cs`, `AsyncClient.cs`, `GenerationStream.cs`, and routing tests.
  Implement buffered/streaming execution only through M2.3a's concrete boundary: target
  resolution, retry/backoff/health, repair, usage overlay, post-content behavior, and
  cancel/dispose rules. **Gate:** from `src/csharp`,
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~Routing` proves lazy
  targets, duplicate targets, health expiry, retries, repair-budget reset, event ordering, and
  stream close semantics, actual native admission of all excluded input forms with zero adapter
  entries, and client disposal closing each owned adapter exactly once.

- [ ] **M2.3c — phase boundary.** Owner: coordinator. Run the whole unit project only after
  M2.3a–b compile against the earlier concrete types. **Gate:** from `src/csharp`,
  `dotnet test AnyInfer.Tests --no-restore` passes; no conformance driver work begins on a
  failing core project.

- [ ] **M2.4a — executable driver shell, closed release and fixture readers.** Owner: conformance
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

- [ ] **M2.4b — native runner, projection, comparison, and development subset.** Owner:
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

- [ ] **M2.4c — first four native proof recipes.** Owner: native-proof worker; files limited to
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

- [ ] **M2.5a — OpenAI chat transport adapter.** Owner: transport worker; files limited to
  `AnyInfer/Providers/OpenAIChatAdapter.cs`, transport helpers, and unit tests. Use `HttpClient`
  for native request encoding and streaming parse only. Do not read expected outcomes or place
  core policy in the adapter. **Gate:**
  `dotnet test AnyInfer.Tests --no-restore --filter FullyQualifiedName~OpenAIChat`
  proves method/path, semantic headers, default stream mode, payload, effective wire limits,
  status/error mapping, SSE chunks, and disposal.

- [ ] **M2.5b — transport runner and final two native proofs.** Owner: transport proof worker;
  files limited to `TransportRunner.cs`, `ProofTransport.cs`, `NativeProofs.cs` additions, and
  proof tests. Implement `driver/timeout-cleanup-disposal` using a native adapter-final then
  blocked iterator cleanup whose actual entry timeout expires, and
  `driver/http-correction-byte-budget-reset` using original/correction raw bodies 78/74 under
  100 bytes, ordered linked capture/wire/HTTP evidence, and result `{age:7}` with repair 1.
  Direct buffered/SSE UTF-8 overflow must show per-chunk ≤80, code points ≤80 < raw bytes,
  stream-protocol error/no final; missing/surplus HTTP script is a harness error. **Gate:**
  `dotnet test AnyInfer.Conformance --no-restore --filter FullyQualifiedName~Transport`
  passes all six recipe dispatches and records nonempty ordinary evidence with exact recipe IDs.

- [ ] **M2.5c — complete native execution.** Owner: conformance integration worker after M2.5a–b;
  files limited to conformance runner/report tests. Execute all 102 released cases, including
  actual excluded-feature admission before inference, all transport fixtures, fresh buffered
  mirrors, and every native proof. **Gate:**
  `dotnet test AnyInfer.Conformance --no-restore` succeeds; then both C# projects pass and
  `workspace check` remains green before a complete report candidate is permitted, with 102
  unique IDs, 102 pass, zero extension/fail/error. Normal conformance tests never publish;
  development/subset observations remain under `.tmp-tests`.

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
