# Move from Python to C# SDK (prerelease)

Python remains the supported published SDK. The native .NET 8 C# SDK is in development as
a prerelease local package (`0.1.0-proof`) and does not claim full parity. See the [shared
foundation](../concepts/foundation.md) for its current capabilities and limits.

| Python concept | C# SDK (development) |
|---|---|
| `AsyncClient` | `AsyncClient` |
| `ProviderSettings.of(...)` | `ProviderSettings.Of(...)` |
| `Target` string | `target` string passed to each async call |
| `Route` and `Retry` | `Route` and `Retry` |
| `Repair(max_attempts=...)` | `Repair(MaxAttempts: ...)` |
| JSON Schema mapping | `SchemaSpec` and typed `Generation.DeserializeStructured<T>()` |
| `Text.text` | `Text.Value` |
| `ImagePart`, `DocumentPart`, `AudioPart`, `VideoPart` | Same public names; C# properties use PascalCase, and byte inputs are defensively copied. |
| `result.text` | `Generation.Text` |
| `result.logprobs`, `result.citations`, provider tool-use counts | `Generation.Logprobs`, `Generation.Citations`, `Generation.ServerToolUses`; reasoning is a separate event. |
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
| request policy | `SpendPolicy`, `Route.ContextWindowTargets`, `CachePolicy`, and `ToolSpec` values |
| `client.run_tools(...)` / `async_client.run_tools(...)` | `Client.RunTools(...)` / `AsyncClient.RunToolsAsync(...)` |
| Provider proxy, TLS verification, and client certificate settings | `ProviderProxy`, `TlsVerification`, and `ClientCertificate` on `ProviderSettings` |

Python cancellation uses task cancellation; C# accepts a `CancellationToken` on each async call.
Python async clients and streams use `async with`; C# uses `await using` for the corresponding
client and stream lifetime. C# also has `Client`/`SyncStream` for synchronous callers, using the
.NET default task scheduler and `using`; it does not reproduce Python's loop facade.

## Registered Cerebras generation

The C# default registry includes the Cerebras generation descriptor. Configure it directly with
an `env://CEREBRAS_API_KEY` credential reference and use a `cerebras:model` target. The
[registered Cerebras provider example](csharp-sdk.md#use-the-registered-cerebras-provider) is
the source-linked executable example.

Its verifier uses a scripted handler, not hosted Cerebras traffic. Hosted behavior remains
unverified; Hyperbolic and Nscale are the other provider-specific presets selected in the default registry.
Choose a model available to the configured account through discovery; the example's
`gpt-oss-120b` is not a static catalog guarantee.

## Registered Hyperbolic generation

The C# default registry also includes Hyperbolic generation. Configure the ordinary
`ProviderSettings.Of("hyperbolic", apiKey: "env://HYPERBOLIC_API_KEY")` and target
`hyperbolic:model`; see the [source-linked Hyperbolic example](csharp-sdk.md#use-the-registered-hyperbolic-provider).
Its default endpoint migrated from the decommissioned `https://api.hyperbolic.xyz/v1` to
`https://api.hyperbolic.ai/inference/v1`. The included example checks the default request path
offline; hosted Hyperbolic traffic remains unverified. Choose a model available to the account
through discovery; `glm-5.3-flash` is an example identifier, not a static catalog guarantee.

## Registered Nscale generation

The C# default registry includes Nscale generation. Configure ordinary
`ProviderSettings.Of("nscale", apiKey: "env://NSCALE_API_KEY")` and target `nscale:model`; see
the [source-linked Nscale example](csharp-sdk.md#use-the-registered-nscale-provider). Nscale's
official examples use `NSCALE_SERVICE_TOKEN`, which callers can supply as their explicit
credential reference. The included handler is scripted and checks the default request offline;
hosted Nscale traffic remains unverified. The example's
`meta-llama/Llama-3.1-8B-Instruct` target is not an account catalog guarantee. Exact SSE framing,
terminal usage timing, and the accepted reasoning-effort enum remain unverified; generic typed
history does not retain `reasoning_content`.

Cerebras, Hyperbolic, and Nscale are the reviewed registered generation presets selected in this
C# proof; all other generated compatibility-preset rows remain inert and are not default
registrations. Broader SDK work remains open.

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

Connection settings can be serialized in version 1 configuration, including literal proxy
credentials and client-key passwords. `ToString()` on the typed settings omits those values, but
`Dumps()` preserves them. Treat the JSON as secret-bearing. The source-shared construction and
round-trip example is deliberately inert and does not exercise TLS or load its illustrative PEM
paths:

```csharp
--8<-- "examples/csharp-sdk/ConnectionExample.cs"
```

For SDK-created handlers, C# accepts an explicit HTTP(S) proxy; omitted verification uses platform
defaults, `TlsVerification.Disabled` disables validation, and a PEM bundle replaces platform trust
with custom roots. OpenSSL CA directories are unsupported. Native .NET chain building has
platform-specific intermediate and explicit leaf-anchor behavior. A supplied handler controls its
own proxy and TLS behavior, and the SDK does not load configured connection files for it. Automatic
redirects use the shared [provider redirect
policy](../reference/configuration.md#provider-http-redirects) when each hop is returned to the
SDK; redirects or cookies handled inside a supplied handler remain caller-controlled. On Windows,
native TLS may use a temporary OS-managed user-key file for PEM client keys; the certificate is not
added to the system store, and native references can defer normal cleanup after the SDK releases
its handler and certificate.

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

## Request policy inputs

`SpendPolicy`, `Route.ContextWindowTargets`, and `CachePolicy` are explicit request-policy
inputs. A client commits only its winning request to a client-local or caller-supplied ledger.
Version 1 configuration keeps `default_route` as an ordinary target list; it has no specialized
context-chain encoding. The generic OpenAI-compatible descriptor declares no cache mechanism.
`ToolSpec`, `ToolCall`, and `ToolResult` are also available as typed raw values. The C#
proof provides a separate bounded loop over explicitly registered `Tool` handlers.

```csharp
--8<-- "examples/csharp-sdk/RequestPolicyExample.cs"
```

Callers own supplied ledgers, estimators, limiters, and stores. Normal configured HTTP, including
a supplied handler for a normal configured descriptor, is paced inside the entry deadline when
`RateLimits` are active. An own-transport descriptor, or an opaque prebuilt registration with an
active injected limiter, uses an outer slot before entry. This proof does not claim provider-invoice
or all-wire accounting, context reduction, history reduction, or universal provider transport parity.

## What to use in an application

Use the [Python SDK](python-sdk.md), sidecar, or CLI for supported application integration. The native C# SDK gives .NET developers a source-linked async API and synchronous facade
implemented by its own C# core. Rich inputs and bounded tool execution are available in that
prerelease SDK. Python remains the supported published SDK; the local C# package is not published
to NuGet and makes no full-parity claim.
