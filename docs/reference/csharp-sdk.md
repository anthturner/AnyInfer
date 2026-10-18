# C# SDK (prerelease) Reference

This page is a hand-written map of the bounded prerelease C# SDK proof. Python remains the
supported public SDK and its generated Python API reference remains under
[SDK reference](api/README.md).

| Surface | Purpose |
|---|---|
| `AsyncClient` | Async generation and streaming client. |
| `Client`, `SyncStream` | Disposable synchronous generation and enumerable stream facade. |
| `ProviderSettings` | Provider setup including an `env://` credential reference. |
| `Route`, `Retry`, `Repair` | Routing, retry, and structured-output repair controls. |
| `SchemaSpec`, `SchemaValidator`, `SchemaValidationOptions` | Modern schema specification, validation, and explicit resource controls. |
| `Generation`, `Timing`, `Usage` | Buffered result, timing, and reported token usage. |
| `AsyncStream`, `StreamEvent` | Streaming result and typed events. |
| `AnyInferConfig` | Restricted version 1 configuration reader and writer. |
| `Catalog`, `ResolvedTarget`, `PricingTable` | Pure target resolution and catalog-derived price facts. |
| `ModelCapabilities` | Provenance-bearing model facts; unknown values remain unknown. |
| `PricingCalculator`, `ContextBudget`, `SpendLedger`, `SpendStore` | Explicit winning-request pricing, planning, and caller-owned accounting helpers. |
| `RateLimits`, `RateLimiter` | Standalone pacing configuration and caller-disposed leases. |
| `ModelsAsync`, `HealthAsync` / `Models`, `Health` | Explicit asynchronous or synchronous lifecycle calls for one provider instance. |
| `ProbeAsync` / `Probe`, `ProbeReport` | Explicit ordered generation-capability measurements and their provenance-bearing report. |
| `ProviderSetupSpec`, `SetupField`, `HostShorthand` | Inert declarative setup metadata for application-owned configuration surfaces. |
| `IObserver`, `TelemetryEvent` | Synchronous typed in-process telemetry; observers and sinks remain caller-owned. |
| `RunManifest`, `ManifestUtilities` | Immutable per-call manifest values, serialization, schema, digest, and rendering helpers. |

The proof currently demonstrates text generation through the OpenAI-compatible adapter,
structured JSON validation, repair, configuration, routing, reported token usage, explicit
capability probes, payload-free telemetry, immutable manifests, setup metadata, bounded
winning-request pricing, explicit budgeting, caller-owned ledger and store helpers, and standalone
pacing. It has no released NuGet package, provider-parity guarantee, provider invoice or all-wire
accounting, automatic spend admission, transport pacing, tool execution, embedding, or reranking
surface.

Schema validation covers Draft 6, Draft 7, Draft 2019-09, and Draft 2020-12. Draft 3 and Draft 4
remain deferred. Numeric and regular-expression behavior is native to .NET, regular-expression
timeouts apply per match, and external resources require an explicit retrieval callback.
Modern schema input and generated values retain arbitrary-size integers, while native `const`,
`enum`, and `uniqueItems` numeric comparisons use .NET `decimal`. Values outside that comparison
range, such as `1e70`, raise a controlled schema-evaluation exception.

See the executable [C# SDK proof guide](../guides/csharp-sdk.md) for the exact source examples.
