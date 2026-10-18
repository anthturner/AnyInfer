# C# SDK (prerelease)

The repository includes a bounded, prerelease C# SDK proof for .NET 8. Its runnable source
examples live in `examples/csharp-sdk/`; the proof uses the same shared contract checks as the
repository's native C# work, while the supported product SDK and published package remain
Python.

The examples use `ProviderSettings` and the built-in OpenAI-compatible provider. They do not
require an application-defined adapter. The async calls accept a cancellation token and use
`await using`; the matching synchronous facade uses `using` and the .NET default task scheduler.

## Run the examples

The SDK is selected by `src/csharp/global.json`. From `src/csharp`, restore the solution and run
the offline examples:

```bash
cd src/csharp
dotnet --version
dotnet restore AnyInfer.sln
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

The example verifier uses local scripted HTTP responses. It does not contact a provider, publish
a package, or write a canonical conformance report.

## Create provider settings

`SettingsExample.Create` accepts an optional credential value or reference. Pass an `env://`
reference when that is how the application supplies credentials; the example does not create one
automatically. Resolution occurs only when the client first needs it.

```csharp
--8<-- "examples/csharp-sdk/SettingsExample.cs"
```

## Generate text

`GenerationExample.RunAsync` shows buffered text generation. It takes explicit settings, target,
and cancellation token so application code can supply its own configuration boundary.

```csharp
--8<-- "examples/csharp-sdk/GenerationExample.cs"
```

## Use the synchronous facade

`Client` drains the same core execution path through a synchronous facade. It is intended for a
synchronous .NET caller; it does not create or depend on Python's event-loop facade.

```csharp
--8<-- "examples/csharp-sdk/SyncGenerationExample.cs"
```

`SyncStream` is enumerable, exposes `Result` after `StreamEnded`, and is disposed with `using`.

```csharp
--8<-- "examples/csharp-sdk/SyncStreamingExample.cs"
```

## Inspect configured metadata

Catalog resolution and capability or pricing facts are pure client queries: they select from
the configured instance and return provenance-bearing values without constructing an adapter or
sending a request. Unknown facts stay unknown; a listed or catalog value is not an accounting
total.

```csharp
--8<-- "examples/csharp-sdk/CatalogExample.cs"
```

## Calculate explicit accounting facts

Pricing uses only trusted catalog, discovered, probed, or caller-override provenance. A
default price leaves calculated cost unknown; a trusted zero price remains a known free result.
`Budget` is a pure planning calculation for one explicit target. The request estimator currently
counts text only: nontext parts are reported as unpriced, and there is no offered-tools input yet.

The ledger, store, and limiter below are caller-selected helpers. They do not create default disk
output, refuse a request, pace client transport, or provide a provider invoice or all-wire total.
The caller owns the store path and explicitly acquires and disposes each standalone limiter lease.
Store accumulation is atomic for replacement readability, but it is not transactional read-modify-write
coordination across threads or processes.

```csharp
--8<-- "examples/csharp-sdk/AccountingExample.cs"
```

## List models and check health

Discovery and health are explicit I/O operations for one configured instance. The async and
synchronous methods both own their clients in the example and accept cancellation through the
source-linked methods.

```csharp
--8<-- "examples/csharp-sdk/LifecycleExample.cs"
```

## Measure generation capabilities

Probing is explicit I/O: the default selection sends up to four small requests in the fixed
JSON Schema, JSON mode, raw tool-call, and streaming order. The returned immutable report
records what the endpoint actually established at `Probed` provenance. The tool declaration
exists only for this raw probe translation; normal tool execution and tool loops are not part
of this proof.

```csharp
--8<-- "examples/csharp-sdk/ProbeExample.cs"
```

## Observe telemetry and manifests

Telemetry is an in-memory, synchronous observer callback by default. The observer in this
example receives payload-free typed events; callers explicitly own and dispose any sink they
choose to add. Inline callbacks run on the generation path.

```csharp
--8<-- "examples/csharp-sdk/TelemetryExample.cs"
```

Manifest capture is separate from observer payload delivery. A stream exposes an incomplete
manifest before consumption and the committed terminal manifest after completion. The helper
also provides schema, digest, JSON, and rendered forms for the immutable public value.

```csharp
--8<-- "examples/csharp-sdk/ManifestExample.cs"
```

## Describe provider setup

`ProviderSetupSpec` and its fields are declarative metadata for an application's setup UI.
Creating this metadata does not resolve credentials or construct a provider.

```csharp
--8<-- "examples/csharp-sdk/SetupExample.cs"
```

## Stream, validate, and route

The remaining examples are source-linked so the site stays aligned with the code the offline
verifier runs.

- [Streaming](streaming.md) uses `StreamingExample.RunAsync`.
- [Structured output](structured-output.md) uses `StructuredOutputExample.RunAsync`.
- [Fallback](fallback.md) uses `RoutingExample.RunAsync`.
- [Configuration](python-to-csharp.md) uses `ConfigurationExample.RunAsync`.

## Scope

This proof covers asynchronous text generation and a synchronous facade over that same core,
through the OpenAI-compatible adapter. It also covers structured JSON validation and repair,
configuration, routing, reported token usage, bounded winning-request pricing, explicit budgets,
caller-owned ledger and store helpers, standalone pacing, explicit capability probes, payload-free
typed telemetry, immutable manifests, and declarative setup metadata. It does not provide a
released NuGet package, provider parity, provider invoice or all-wire totals, automatic spend
admission, transport pacing, tool execution, embeddings, reranking, or production report publication.

For structured output, use `SchemaSpec` with Draft 6, Draft 7, Draft 2019-09, or Draft 2020-12.
Draft 3 and Draft 4 remain deferred. Native numeric and regular-expression behavior applies, with
a timeout for each regular-expression match. Registered schema resources are explicit, and external
resource retrieval requires an explicit opt-in retriever.

Modern schemas and generated values retain arbitrary-size integers at the input boundary. Numeric
comparisons in `const`, `enum`, and `uniqueItems` use the pinned native validator's .NET `decimal`
domain, so a value outside that range, such as `1e70`, produces a controlled schema-evaluation
exception.
