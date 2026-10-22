# C# SDK (prerelease) Reference

This page is a hand-written map of the bounded prerelease C# SDK proof. Python remains the
supported public SDK and its generated Python API reference remains under
[SDK reference](api/README.md).

| Surface | Purpose |
|---|---|
| `AsyncClient` | Async generation and streaming client. |
| `Client`, `SyncStream` | Disposable synchronous generation and enumerable stream facade. |
| `EmbeddingRequest`, `EmbeddingResult`, `EmbeddingSpace` | Buffered ordered text embedding, its vectors, and their compatibility identity. |
| `RerankRequest`, `RerankDocument`, `RerankResult`, `RankedItem` | Buffered query-to-document ranking with caller-owned document IDs and original indices. |
| `BatchPolicy`, `BatchFailure` | Core-managed bounded batching controls and the failures retained when a batch operation fails. |
| `IEmbedsText`, `IReranksText`, `InferenceOperation` | Optional retrieval adapter protocols; the built-in TEI adapter declares embedding and rerank operations. |
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
| `SpendPolicy`, `Route.ContextWindowTargets`, `CachePolicy` | Explicit spend admission, specialized context fallback, and cache planning inputs. |
| `ToolSpec`, `ToolCall`, `ToolResult` | Typed raw tool declarations and feedback; no callable tool loop. |
| `ModelsAsync`, `HealthAsync` / `Models`, `Health` | Explicit asynchronous or synchronous lifecycle calls for one provider instance. |
| `ProbeAsync` / `Probe`, `ProbeReport` | Explicit ordered generation-capability measurements and their provenance-bearing report. |
| `ProviderSetupSpec`, `SetupField`, `HostShorthand` | Inert declarative setup metadata for application-owned configuration surfaces. |
| `IObserver`, `TelemetryEvent` | Synchronous typed in-process telemetry; observers and sinks remain caller-owned. |
| `RunManifest`, `ManifestUtilities` | Immutable per-call manifest values, serialization, schema, digest, and rendering helpers. |
| `AttemptRecord.Timing`, `operationRoutes` | Per-attempt timing and optional retrieval-specific default routes on either client. |

Configured `RateLimits` can pace normal provider HTTP inside the generation entry deadline. An
own-transport descriptor, or an opaque prebuilt registration with an active injected limiter, uses
an outer slot before entry; this is not a universal provider transport guarantee.

The proof demonstrates text generation through the chat-only OpenAI-compatible adapter and
buffered text embedding and reranking through the built-in TEI adapter or optional
application-owned retrieval adapters. Retrieval results
carry normalized usage, timing, attempts, warnings, optional raw payloads, and manifests just as
their operation permits. `operationRoutes` can provide embedding or rerank defaults without
changing a generation route. The TEI descriptor does not hydrate deployment limits, so unknown
provider batch ceilings do not cause guessed splitting;
`BatchPolicy` supplies an explicit override when the application has verified a limit. It has no
released NuGet package, full provider-parity guarantee, provider invoice or all-wire accounting,
automatic tool execution, rich-media input breadth, context/history reduction, or production
report publication. Generic OpenAI-compatible retrieval remains unimplemented. Buffered C# embedding and reranking were exercised against the pinned TEI 1.9.4 CPU deployment on 2026-10-22.

Schema validation covers Draft 6, Draft 7, Draft 2019-09, and Draft 2020-12. Draft 3 and Draft 4
remain deferred. Numeric and regular-expression behavior is native to .NET, regular-expression
timeouts apply per match, and external resources require an explicit retrieval callback.
Modern schema input and generated values retain arbitrary-size integers, while native `const`,
`enum`, and `uniqueItems` numeric comparisons use .NET `decimal`. Values outside that comparison
range, such as `1e70`, raise a controlled schema-evaluation exception.

See the executable [C# SDK proof guide](../guides/csharp-sdk.md) for the exact source examples.
