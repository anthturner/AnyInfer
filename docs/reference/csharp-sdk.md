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
| `Generation`, `Timing`, `Usage` | Buffered result, timing, and reported token usage. |
| `AsyncStream`, `StreamEvent` | Streaming result and typed events. |
| `AnyInferConfig` | Restricted version 1 configuration reader and writer. |
| `Catalog`, `ResolvedTarget`, `PricingTable` | Pure target resolution and catalog-derived price facts. |
| `ModelCapabilities` | Provenance-bearing model facts; unknown values remain unknown. |
| `ModelsAsync`, `HealthAsync` / `Models`, `Health` | Explicit asynchronous or synchronous lifecycle calls for one provider instance. |

The proof currently demonstrates text generation through the OpenAI-compatible adapter,
structured JSON validation, repair, configuration, routing, and reported token usage. It has no
released NuGet package, provider-parity guarantee, aggregate usage accounting, tool execution,
embedding, or reranking surface.

See the executable [C# SDK proof guide](../guides/csharp-sdk.md) for the exact source examples.
