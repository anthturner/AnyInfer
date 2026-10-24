# C# SDK (prerelease) Reference

This page is a hand-written map of the bounded prerelease C# SDK proof. Python remains the
supported public SDK and its generated Python API reference remains under
[SDK reference](api/README.md).

The listed C# types are in the `AnyInfer` namespace unless otherwise noted. The C# `Text.Value`
property corresponds to Python `Text.text`.

| Surface | Purpose |
|---|---|
| `AsyncClient` | Async generation and streaming client. |
| `Client`, `SyncStream` | Disposable synchronous generation and enumerable stream facade. |
| `EmbeddingRequest`, `EmbeddingResult`, `EmbeddingSpace` | Buffered ordered text embedding, its vectors, and their compatibility identity. |
| `RerankRequest`, `RerankDocument`, `RerankResult`, `RankedItem` | Buffered query-to-document ranking with caller-owned document IDs and original indices. |
| `BatchPolicy`, `BatchFailure` | Core-managed bounded batching controls and the failures retained when a batch operation fails. |
| `IEmbedsText`, `IReranksText`, `InferenceOperation` | Optional retrieval adapter protocols; the built-in TEI, Voyage, and Jina adapters declare embedding and rerank operations. |
| `ProviderSettings` | Provider setup including an `env://` credential reference. |
| `cerebras:model` | Default-registry generation target for a configured Cerebras instance; use `ProviderSettings.Of("cerebras", apiKey: "env://CEREBRAS_API_KEY")`. |
| `ProviderProxy`, `TlsVerification`, `ClientCertificate` | Explicit HTTP(S) proxy, SDK-handler TLS verification, and PEM client-certificate settings attached to `ProviderSettings`. |
| `AnyInfer.Providers.ProviderDescriptor.HonorsConnectionSettings` | Descriptor metadata, defaulting to `true`, indicating whether the provider supports configured proxy, TLS, and client-certificate settings. |
| `AnyInferConfig.Loads`, `AnyInferConfig.Dumps` | Parse and render bounded version 1 JSON; configured proxy credentials and certificate paths/passwords remain literal configuration values. |
| `Route`, `Retry`, `Repair` | Routing, retry, and structured-output repair controls. |
| `SchemaSpec`, `SchemaValidator`, `SchemaValidationOptions` | Modern schema specification, validation, and explicit resource controls. |
| `Generation`, `Timing`, `Usage` | Buffered result, timing, and reported token usage. |
| `ContentPart`, `Text`, `ImagePart`, `DocumentPart`, `AudioPart`, `VideoPart` | Typed text and media inputs; URL values are references and are never fetched by the core. |
| `Citation`, `TokenLogprob`, `ServerToolUse`, `ServerToolSpec`, `ServerToolSource` | Normalized rich-generation output facts and provider-run tool declarations. |
| `ReasoningDelta`, `CitationDelta`, `ServerToolDelta` | Separate typed stream events for reasoning, citations, and provider-run tools. |
| `AsyncStream`, `StreamEvent` | Streaming result and typed events. |
| `AnyInferConfig` | Restricted version 1 configuration reader and writer. |
| `Catalog`, `ResolvedTarget`, `PricingTable` | Pure target resolution and catalog-derived price facts. |
| `ModelCapabilities` | Provenance-bearing model facts; unknown values remain unknown. |
| `AnyInfer.Providers.ModelInventoryKind`, `AnyInfer.Providers.ProviderDescriptor.ModelInventory` | Descriptive metadata for the category of model inventory a provider exposes. |
| `PricingCalculator`, `ContextBudget`, `SpendLedger`, `SpendStore` | Explicit winning-request pricing, planning, and caller-owned accounting helpers. |
| `RateLimits`, `RateLimiter` | Standalone pacing configuration and caller-disposed leases. |
| `SpendPolicy`, `Route.ContextWindowTargets`, `CachePolicy` | Explicit spend admission, specialized context fallback, and cache planning inputs. |
| `ToolSpec`, `ToolCall`, `ToolResult`, `Tool`, `ToolRegistry` | Raw tool values, caller-authorized handlers, and ordered registration for a bounded loop; `Dispatched` counts known-name dispatches. |
| `AsyncClient.RunToolsAsync`, `Client.RunTools` | Bounded sequential execution of registered tools, returning the final generation round. |
| `ModelsAsync`, `HealthAsync` / `Models`, `Health` | Explicit asynchronous or synchronous lifecycle calls for one provider instance. |
| `ProbeAsync` / `Probe`, `ProbeReport` | Explicit ordered generation-capability measurements and their provenance-bearing report. |
| `ProviderSetupSpec`, `SetupField`, `HostShorthand` | Inert declarative setup metadata for application-owned configuration surfaces. |
| `IObserver`, `TelemetryEvent` | Synchronous typed in-process telemetry; observers and sinks remain caller-owned. |
| `RunManifest`, `ManifestUtilities` | Immutable per-call manifest values, serialization, schema, digest, and rendering helpers. |
| `AttemptRecord.Timing`, `operationRoutes` | Per-attempt timing and optional retrieval-specific default routes on either client. |

`AnyInfer.Providers.ProviderDescriptor` exposes get-only `ModelInventory`; its optional `modelInventory` constructor argument defaults to `ModelInventoryKind.Served`. `Served` describes models exposed by an already-running engine; `Available` describes a catalog of models that could be run; `Installed` describes a provider-owned on-disk model store. This category is descriptive metadata, separate from model-listing support and the descriptor's implemented inference operations. Choosing a category does not filter discovered models, start a runtime, download models, or register a provider. The descriptor's get-only `HonorsConnectionSettings` value defaults to `true` and describes whether that provider supports configured connection settings.

Connection settings apply to SDK-created handlers. With no `verify` value, platform certificate
verification remains in effect; `TlsVerification.Disabled` turns it off, while a PEM bundle selects
custom roots. Native .NET does not load OpenSSL CA directories, and intermediate or leaf trust
anchor chain building can vary by platform. Client certificate factories accept combined
unencrypted PEM, separate unencrypted certificate/key PEM, or encrypted-key PEM (including a
same-path combined file). Material is loaded when a selected provider first creates its handler.
A supplied handler owns its transport behavior and bypasses SDK proxy/TLS setup and material
loading. `ToString()` on connection objects omits values; version 1 `Dumps()` keeps configured
literal values, so protect that output. Provider redirects follow the shared [redirect
policy](configuration.md#provider-http-redirects) when the handler returns each hop; redirects or
cookies handled inside a supplied handler remain caller-controlled.
On Windows, native TLS may use a temporary OS-managed user-key file for PEM client keys; this does
not add the certificate to the system certificate store. Native references can defer normal cleanup
after the handler and certificate are released, so the SDK does not promise immediate deletion or
memory-only storage.

Configured `RateLimits` can pace normal provider HTTP inside the generation entry deadline. An
own-transport descriptor, or an opaque prebuilt registration with an active injected limiter, uses
an outer slot before entry; this is not a universal provider transport guarantee.

The proof demonstrates text generation through the chat-only OpenAI-compatible adapter and the
registered Cerebras descriptor, plus buffered text embedding and reranking through the built-in
TEI, Voyage, or Jina adapter or optional application-owned retrieval adapters. Retrieval results
carry reported usage, timing, attempts, warnings, optional raw payloads, and manifests just as
their operation permits. `operationRoutes` can provide embedding or rerank defaults without
changing a generation route. The TEI descriptor does not hydrate deployment limits, so unknown
provider batch ceilings do not cause guessed splitting;
`BatchPolicy` supplies an explicit override when the application has verified a limit. It has no
released NuGet package, full provider-parity guarantee, provider invoice or all-wire accounting,
context/history reduction, or production
report publication. Generic OpenAI-compatible retrieval remains unimplemented in this
proof. Buffered C# embedding and reranking were exercised against the pinned TEI 1.9.4 CPU
deployment on 2026-10-22. Voyage's built-in adapter has offline scripted-handler evidence only;
hosted Voyage traffic has not been live-verified. Jina's built-in adapter has offline scripted-handler evidence only; hosted Jina traffic has not been live-verified.

The default registry also includes Cerebras for generation through its existing shared chat
adapter. Use ordinary `ProviderSettings` and a `cerebras:model` target. Its executable evidence
uses a scripted handler only: hosted Cerebras traffic is not live-verified, and other generated
OpenAI-compatible presets are not registered in this C# proof. Choose a model available to the
configured account through discovery; the examples do not provide a static Cerebras catalog.

Schema validation covers Draft 6, Draft 7, Draft 2019-09, and Draft 2020-12. Draft 3 and Draft 4
remain deferred. Numeric and regular-expression behavior is native to .NET, regular-expression
timeouts apply per match, and external resources require an explicit retrieval callback.
Modern schema input and generated values retain arbitrary-size integers, while native `const`,
`enum`, and `uniqueItems` numeric comparisons use .NET `decimal`. Values outside that comparison
range, such as `1e70`, raise a controlled schema-evaluation exception.

See the executable [C# SDK proof guide](../guides/csharp-sdk.md) for the exact source examples.
