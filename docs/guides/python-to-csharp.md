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
| `Text.text` | `Text.Value` |
| `result.text` | `Generation.Text` |
| async stream | `AsyncStream` and `StreamEvent` |
| Python `Client` | .NET `Client` and `SyncStream` |
| `AnyInferError` | typed .NET `Exception` subclasses |
| `client.models(...)`, `client.health(...)` | `ModelsAsync` / `HealthAsync`, or `Models` / `Health` |
| catalog and capability queries | `Catalog`, `Resolve(...)`, and `Capabilities(...)` |

Python cancellation uses task cancellation; C# accepts a `CancellationToken` on each async call.
Python async clients and streams use `async with`; C# uses `await using` for the corresponding
client and stream lifetime. C# also has `Client`/`SyncStream` for synchronous callers, using the
.NET default task scheduler and `using`; it does not reproduce Python's loop facade.

## Shared configuration

`ConfigurationExample.RunAsync` accepts version 1 configuration JSON and creates a configured
client. Version 1 actively supports `providers`, `default_route`, and `repair`; unsupported
active policies are refused. Credential references remain references while configuration is read;
resolution belongs to the selected provider's first use. The schema mechanism is a bounded proof
subset, so port a schema only after checking its supported shape.

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

## What to use in an application

Use the [Python SDK](python-sdk.md), sidecar, or CLI for supported application integration. The
C# examples give .NET developers a concrete, source-linked async surface and synchronous facade
over the same core for porting generation code. The package and integration remain prerelease
proof work rather than a separate installation path, with no released NuGet package or full
provider parity.
