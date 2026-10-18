# Move from Python to C# SDK (prerelease)

The Python SDK remains the supported AnyInfer runtime and the source for installation,
integration, and release guidance. The C# surface is a bounded prerelease SDK proof for .NET 8
developers porting supported async text generation concepts. It has no released NuGet package and
does not claim provider or feature parity with Python.

| Python concept | C# SDK proof |
|---|---|
| `AsyncClient` | `AsyncClient` |
| `ProviderSettings.of(...)` | `ProviderSettings.Of(...)` |
| `Target` string | `target` string passed to each async call |
| `Route` and `Retry` | `Route` and `Retry` |
| `Repair(max_attempts=...)` | `Repair(MaxAttempts: ...)` |
| JSON Schema mapping | `SchemaSpec` and typed `Generation.DeserializeStructured<T>()` |
| `Text.text` | `Text.Value` |
| `result.text` | `Generation.Text` |
| async stream | `AsyncStream` and `StreamEvent` |
| Python `Client` | .NET `Client` and `SyncStream` |
| `AnyInferError` | typed .NET `Exception` subclasses |
| `client.models(...)`, `client.health(...)` | `ModelsAsync` / `HealthAsync`, or `Models` / `Health` |
| catalog and capability queries | `Catalog`, `Resolve(...)`, and `Capabilities(...)` |
| `client.probe(...)` | `ProbeAsync(...)` or `Probe(...)`, returning `ProbeReport` |
| telemetry observer | `IObserver` supplied to or subscribed on `AsyncClient` / `Client` |
| result manifest | `AsyncStream.Manifest`, `SyncStream.Manifest`, or `Generation.Manifest` |
| `ProviderSetupSpec` metadata | `ProviderSetupSpec`, `SetupField`, `HostShorthand`, and `AnyOf` |
| explicit pricing, budgets, and ledger snapshots | `PricingCalculator`, `Budget(...)`, `SpendLedger`, and `SpendStore` |

Python cancellation uses task cancellation; C# accepts a `CancellationToken` on each async call.
Python async clients and streams use `async with`; C# uses `await using` for the corresponding
client and stream lifetime. C# also has `Client`/`SyncStream` for synchronous callers, using the
.NET default task scheduler and `using`; it does not reproduce Python's loop facade.

## Shared configuration

`ConfigurationExample.RunAsync` accepts version 1 configuration JSON and creates a configured
client. Version 1 actively supports `providers`, `default_route`, and `repair`; unsupported
active policies are refused. Credential references remain references while configuration is read;
resolution belongs to the selected provider's first use. The schema mechanism is a bounded proof
subset, so port a schema only after checking its supported shape. The C# proof evaluates Draft 6,
Draft 7, Draft 2019-09, and Draft 2020-12; Draft 3 and Draft 4 remain deferred. Native numeric
and regular-expression behavior applies, with a timeout per regular-expression match. Registered
resources are explicit and external schema retrieval requires an explicit retriever.

Modern C# schema input and generated values retain arbitrary-size integers. The native validator's
numeric comparisons for `const`, `enum`, and `uniqueItems` use .NET `decimal`, so a value outside
that range, such as `1e70`, raises a controlled schema-evaluation exception.

```csharp
--8<-- "examples/csharp-sdk/ConfigurationExample.cs"
```

## Metadata and lifecycle calls

Catalog resolution and capability or pricing metadata are pure queries over configured inputs;
their values can remain unknown and carry provenance. Model listing and health are separate,
explicit instance I/O calls. The executable examples show both the async and synchronous forms.

```csharp
--8<-- "examples/csharp-sdk/CatalogExample.cs"
```

```csharp
--8<-- "examples/csharp-sdk/LifecycleExample.cs"
```

## Capability probes and setup metadata

Probe calls are explicit and may spend up to four requests by default. The async and sync
facades return an immutable `ProbeReport`; `record: false` returns evidence without storing a
new measured capability record. The raw tool declaration used by the tools probe is a transport
translation detail, not a normal C# tool-execution API.

```csharp
--8<-- "examples/csharp-sdk/ProbeExample.cs"
```

Provider setup metadata is inert. It describes fields, host shorthand, and alternatives for an
application-owned setup surface without resolving a secret or constructing an adapter.

```csharp
--8<-- "examples/csharp-sdk/SetupExample.cs"
```

## Telemetry and manifests

C# observers receive typed events synchronously. They are payload-free unless a subscription
explicitly requests payloads, and caller-owned sinks are disposed by the caller. Manifests are
immutable call records: a stream exposes an incomplete one before it is consumed and a terminal
one after completion. They do not calculate account totals or create automatic pricing.

```csharp
--8<-- "examples/csharp-sdk/TelemetryExample.cs"
```

```csharp
--8<-- "examples/csharp-sdk/ManifestExample.cs"
```

## Explicit accounting helpers

`AsyncClient.Budget(...)` and `Client.Budget(...)` calculate a planning budget without choosing a
route winner, resolving credentials, constructing an adapter, or sending a request. Pricing applies
only when its provenance is catalog, discovered, probed, or caller override; default facts leave a
calculated cost unknown, while a trusted zero price is free. The current request extractor counts
text, reports other content as unpriced, and has no offered-tools input.

`SpendLedger`, `SpendStore`, and `RateLimiter` are explicit caller-owned helpers. They do not make
client admission decisions, persist automatically, pace client transport, or represent a provider
invoice or all-wire total. Dispose every standalone limiter lease, and serialize store updates when
you need transactional read-modify-write behavior.

```csharp
--8<-- "examples/csharp-sdk/AccountingExample.cs"
```

## What to use in an application

Use the [Python SDK](python-sdk.md), sidecar, or CLI for supported application integration. The
C# examples give .NET developers a concrete, source-linked async surface and synchronous facade
over the same core for porting generation code. The package and integration remain prerelease
proof work rather than a separate installation path, with no released NuGet package or full
provider parity.
