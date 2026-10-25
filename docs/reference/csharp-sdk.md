# C# SDK (prerelease) Reference

This page describes the native .NET 8 C# SDK in development, locally packaged as
`0.1.0-proof`. Python remains the supported published SDK; its generated reference is the
[Python API reference](api/README.md).

Every public C# type, constructor, overload, property, and operator has a generated page in
the [C# API reference](/csharp/api/). This page covers what those signatures do not show:
behavior, limits, and the places where the C# SDK differs from Python. Which concepts the
C# SDK implements at all is in the [foundation capability map](../concepts/foundation.md),
and the executable examples are in the [C# SDK guide](../guides/csharp-sdk.md).

## API Map {#api-map}

Types are in the `AnyInfer` namespace unless the link names another. Member names are
generally PascalCase forms of the Python names; one rename worth knowing is that C#
`Text.Value` is Python `Text.text`.

| Area | Start with |
|---|---|
| Clients and streams | [`AsyncClient`](/csharp/api/anyinfer.asyncclient/), [`Client`](/csharp/api/anyinfer.client/), [`AsyncStream`](/csharp/api/anyinfer.asyncstream/), [`SyncStream`](/csharp/api/anyinfer.syncstream/) |
| Requests and results | [`GenerationRequest`](/csharp/api/anyinfer.generationrequest/), [`Message`](/csharp/api/anyinfer.message/), [`ContentPart`](/csharp/api/anyinfer.contentpart/), [`Generation`](/csharp/api/anyinfer.generation/), [`StreamEvent`](/csharp/api/anyinfer.streamevent/) |
| Routing and pacing | [`Route`](/csharp/api/anyinfer.route/), [`Retry`](/csharp/api/anyinfer.retry/), [`Repair`](/csharp/api/anyinfer.repair/), [`RateLimits`](/csharp/api/anyinfer.ratelimits/), [`AnyInfer.Routing.RateLimiter`](/csharp/api/anyinfer.routing.ratelimiter/) |
| Structured output | [`SchemaSpec`](/csharp/api/anyinfer.schemaspec/), [`AnyInfer.Schema.SchemaValidator`](/csharp/api/anyinfer.schema.schemavalidator/), [`AnyInfer.Schema.SchemaValidationOptions`](/csharp/api/anyinfer.schema.schemavalidationoptions/) |
| Embedding and reranking | [`EmbeddingResult`](/csharp/api/anyinfer.embeddingresult/), [`EmbeddingSpace`](/csharp/api/anyinfer.embeddingspace/), [`RerankDocument`](/csharp/api/anyinfer.rerankdocument/), [`RerankResult`](/csharp/api/anyinfer.rerankresult/), [`BatchPolicy`](/csharp/api/anyinfer.batchpolicy/) |
| Tools | [`ToolRegistry`](/csharp/api/anyinfer.toolregistry/), [`Tool`](/csharp/api/anyinfer.tool/), [`ToolSpec`](/csharp/api/anyinfer.toolspec/); the loop is `AsyncClient.RunToolsAsync` / `Client.RunTools` |
| Providers and connections | [`ProviderSettings`](/csharp/api/anyinfer.providersettings/), [`AnyInfer.Providers.ProviderRegistry`](/csharp/api/anyinfer.providers.providerregistry/), [`AnyInfer.Providers.ProviderDescriptor`](/csharp/api/anyinfer.providers.providerdescriptor/), [`ProviderProxy`](/csharp/api/anyinfer.providerproxy/), [`TlsVerification`](/csharp/api/anyinfer.tlsverification/), [`ClientCertificate`](/csharp/api/anyinfer.clientcertificate/) |
| Configuration and credentials | [`AnyInfer.Config.AnyInferConfig`](/csharp/api/anyinfer.config.anyinferconfig/), [`AnyInfer.Credentials.ResolverChain`](/csharp/api/anyinfer.credentials.resolverchain/), [`Redaction`](/csharp/api/anyinfer.redaction/) |
| Catalog and capabilities | [`AnyInfer.Catalog.Catalog`](/csharp/api/anyinfer.catalog.catalog/), [`AnyInfer.Capabilities.ModelCapabilities`](/csharp/api/anyinfer.capabilities.modelcapabilities/), [`AnyInfer.Capabilities.ProbeReport`](/csharp/api/anyinfer.capabilities.probereport/) |
| Accounting | [`SpendPolicy`](/csharp/api/anyinfer.spendpolicy/), [`AnyInfer.Capabilities.SpendLedger`](/csharp/api/anyinfer.capabilities.spendledger/), [`AnyInfer.Capabilities.SpendStore`](/csharp/api/anyinfer.capabilities.spendstore/), [`AnyInfer.Capabilities.PricingCalculator`](/csharp/api/anyinfer.capabilities.pricingcalculator/), [`AnyInfer.Capabilities.ContextBudget`](/csharp/api/anyinfer.capabilities.contextbudget/) |
| Telemetry and manifests | [`AnyInfer.Events.IObserver`](/csharp/api/anyinfer.events.iobserver/), [`AnyInfer.Events.TelemetryEvent`](/csharp/api/anyinfer.events.telemetryevent/), [`AnyInfer.Manifest.RunManifest`](/csharp/api/anyinfer.manifest.runmanifest/), [`AnyInfer.Manifest.ManifestUtilities`](/csharp/api/anyinfer.manifest.manifestutilities/) |
| Errors | [`AnyInferException`](/csharp/api/anyinfer.anyinferexception/) and the types derived from it |
| Context settings | [`AnyInfer.Context.ContextTuning`](/csharp/api/anyinfer.context.contexttuning/) |

## Providers {#providers}

`ProviderRegistry.CreateDefault()` registers seven descriptors with ten operation
bindings:

| Provider | Operations | Default endpoint |
|---|---|---|
| `openai-compat` | Generation, chat only | None; `base_url` is required |
| `cerebras` | Generation | `https://api.cerebras.ai/v1` |
| `hyperbolic` | Generation | `https://api.hyperbolic.ai/inference/v1` |
| `nscale` | Generation | `https://inference.api.nscale.com/v1` |
| [`tei`](../providers/tei.md) | Embedding, rerank | `http://127.0.0.1:8080` |
| [`voyage`](../providers/retrieval.md) | Embedding, rerank | `https://api.voyageai.com/v1` |
| [`jina`](../providers/retrieval.md) | Embedding, rerank | `https://api.jina.ai/v1` |

Buffered embedding and reranking were exercised against the pinned TEI 1.9.4 CPU
deployment on 2026-10-22. Cerebras, Hyperbolic, Nscale, Voyage, and Jina have offline
scripted-handler evidence only; their hosted traffic has not been live-verified.
Cerebras, Hyperbolic, and Nscale are reviewed presets served through the
shared chat adapter: use ordinary `ProviderSettings` with their conventional `env://`
credential (`CEREBRAS_API_KEY`, `HYPERBOLIC_API_KEY`, `NSCALE_API_KEY`) and a
provider-prefixed target such as `cerebras:<model>`. Hyperbolic's former
`https://api.hyperbolic.xyz/v1` endpoint is decommissioned, and its endpoint keeps the full
`/inference/v1` prefix. Every other compatibility-preset row bundled in the assembly is inert
data and is not registered. Choose a model available to the configured account through
discovery; no provider here comes with a static model guarantee. For Nscale, exact SSE
framing, terminal usage timing, and the accepted reasoning-effort values remain unverified.

The chat adapter, and so the Cerebras, Hyperbolic, and Nscale presets, never emits
`ReasoningDelta`, `CitationDelta`, or `ServerToolDelta`, and generic message history does not
retain a provider's `reasoning_content`. Those events, and the citations and server-tool uses
on `Generation`, come only from an application-owned adapter registered through
`AsyncClient.FromAdapters` or a custom descriptor; the chat adapter does return token
logprobs. Generic OpenAI-compatible embedding and reranking are not implemented.

`ProviderDescriptor.ModelInventory` (default `ModelInventoryKind.Served`) is descriptive
metadata: `Served` describes models an already-running engine exposes, `Available` a
catalog of models that could be run, and `Installed` a provider-owned on-disk store.
Choosing one does not filter discovered models, start a runtime, download models, or
register a provider. `HonorsConnectionSettings` (default `true`) says whether the provider
accepts configured proxy, TLS, and client-certificate settings.

## Configuration {#configuration}

`AnyInferConfig.Load` and `Loads` read version 1 of the
[shared configuration format](configuration.md#what-each-sdk-accepts). The root may contain
`providers`, `default_route`, `operation_routes` (only `embedding` and `rerank`), `cache`,
and `repair` (only `max_attempts`), plus `format_version`, `_comment`, and the demo
application's UI keys. The `context`, `history`, `observers`, `arena`, `arenas`, and `mcp`
blocks are rejected as not implemented, and any other key is rejected. A provider entry may
set `id`, `adapter` (or `provider_id`), `alias`, `enabled`, `base_url`, `api_key`,
`api_version`, `headers`, `options`, `timeout_s`, `limits`, `proxy`, `verify`, and
`client_cert`, plus the provider's declared setup fields directly or under `values`.

Loading resolves no credential, constructs no adapter, and opens no CA bundle or
certificate file. An `api_key` is only checked with `ResolverChain.Handles`, so a reference
whose scheme no resolver accepts fails at load; pass your own `ResolverChain` to admit a
custom scheme. `Dumps` writes configured values literally, including proxy credentials and
certificate paths and passwords, so protect its output. `Dump` refuses to replace an
existing file unless `force` is `true`, and writes in place rather than through a
temporary file, so an interrupted write can leave a partial file.

## Credentials and Redaction {#credentials}

`ResolverChain.CreateDefault()` tries the keyring, environment, and literal resolvers in
that order. The keyring resolver accepts `credential://` references so configuration
loading admits them and a literal resolver never sends one as a key, but resolving one
always fails with `CredentialException`: this SDK has no OS keyring integration. The setup
metadata of the Voyage, Jina, and compatibility-preset descriptors still describes
`credential://` as an accepted form; in C#, use `env://`, a literal, or your own resolver.

The chain registers every credential it resolves, literal values included, with the
process-global `Redaction` registry. SDK-created connections also register a configured
proxy user name and password and a client-certificate password. Header values and options
that a provider does not declare as secret are sent as given and are never registered; call
`Redaction.RegisterSecret` for any secret you place there. Values shorter than six Unicode
scalar values are ignored.

## Streams {#streams}

`AsyncClient.StreamAsync` is lazy: the generation starts on the first `MoveNextAsync` and
the stream has one consumer. `Client.Stream` is not: its `SyncStream` starts the
generation when it is created and buffers up to 256 events ahead of the consumer, so
create it when you are ready to consume it, and dispose it to cancel.

For native SSE streams, `[DONE]` ends reading immediately and later records are ignored.
Clean body EOF also finalizes the stream: a final usable record is processed even without a
trailing blank-line delimiter, and a missing finish reason defaults to `stop`. Empty,
content-only, and comment-only streams are valid when they end cleanly. If usage is omitted,
it remains unknown. A finish reason does not end an open stream, so reading continues for
trailing usage and later errors until `[DONE]` or EOF. Malformed trailing JSON, invalid
UTF-8, limit failures, and thrown body-read errors still fail. A normal zero-byte read is
EOF; this does not mean every network truncation is reported as a read error.

`Generation.FinishReason` is the provider's own string, apart from `tool_calls` when the
model stopped to call tools; unlike Python, an unrecognized value is not normalized to
`other`.

## Structured Output {#structured-output}

Schema validation covers Draft 6, Draft 7, Draft 2019-09, and Draft 2020-12. Draft 3 and
Draft 4 are not supported. Numeric and regular-expression behavior is native to .NET,
regular-expression timeouts apply per match, and an external resource must be registered
in `SchemaValidationOptions.Resources` or returned by its `Retrieve` callback. Modern
schema input and generated values retain arbitrary-size integers, while native `const`,
`enum`, and `uniqueItems` numeric comparisons use .NET `decimal`; values outside that
range, such as `1e70`, raise `SchemaEvaluationException`. An unresolvable schema resource
raises `SchemaReferenceException`.

`SchemaViolationException` carries at most five validation `Issues`, without Python's raw
response text, partial members, or missing-required list. The request's `SchemaMechanism`
is carried but not consulted: the mechanism is selected from the target's capabilities, and
the chat adapter has no `grammar` mechanism.

## Embedding and Reranking {#retrieval}

Buffered embedding and reranking run through the built-in TEI, Voyage, and Jina adapters or
an application-owned `IEmbedsText` / `IReranksText` adapter. Results carry reported usage,
timing, attempts, warnings, optional raw payloads, and manifests as their operation permits.
`operationRoutes` supplies embedding or rerank defaults without changing the generation
route.

Each provider call's deadline is the call's `timeoutS`, 120 seconds when omitted; unlike
generation, it does not fall back to `ProviderSettings.TimeoutS`. A call that runs out of
time fails as a retryable plain `ProviderException` whose `Category` is `timeout`, not as a
`TransportException`.

The TEI descriptor does not hydrate deployment limits, so an unknown provider batch ceiling
never causes guessed splitting; `BatchPolicy.MaxItemsOverride` supplies a limit the
application has verified. The default `BatchPolicy` splits embedding inputs into up to four
concurrent batches but does not let reranking cross a batch boundary, so a rerank request
over a known document limit fails with `ConfigException` unless `RerankCrossBatch` is set.
Retrieval input batching is supported; batch inference jobs are not.

## Connection Settings {#connection-settings}

Connection settings apply to SDK-created handlers. With no `verify` value, platform
certificate verification remains in effect; `TlsVerification.Disabled` turns it off, while a
PEM bundle selects custom roots. Native .NET does not load OpenSSL CA directories, so a
directory is refused, and intermediate or leaf trust-anchor chain building can vary by
platform. Client certificate factories accept combined unencrypted PEM, separate unencrypted
certificate and key PEM, or encrypted-key PEM (including a same-path combined file).
Material is loaded when a selected provider first creates its handler, and a file that
cannot be loaded fails then with a `ConfigException` naming the provider instance. A
supplied handler owns its transport behavior and bypasses SDK proxy, TLS, and material
loading. `ToString()` on connection objects omits values.

Provider redirects follow the shared [redirect policy](configuration.md#provider-http-redirects)
when the handler returns each hop; redirects or cookies handled inside a supplied handler
remain caller-controlled. On Windows, native TLS may use a temporary OS-managed user-key file
for PEM client keys; this does not add the certificate to the system certificate store.
Native references can defer normal cleanup after the handler and certificate are released,
so the SDK does not promise immediate deletion or memory-only storage.

## Pacing {#pacing}

Configured `RateLimits` pace normal provider HTTP inside the generation entry deadline. An
own-transport descriptor, or an opaque prebuilt registration with an active injected
limiter, uses an outer slot before entry; this is not a universal provider transport
guarantee. No built-in descriptor declares a rate-limit header dialect, so `RespectHeaders`
cannot read allowance headers on them; pacing follows the configured bounds, and a
generation request reports the unread setting as a `ParameterDropped` event.

## Accounting {#accounting}

Pricing, budgets, and spend are explicit helpers and caller-owned policies; the SDK does
not provide provider invoice or all-wire accounting. Money is a PeterO `EDecimal`, and an
unknown cost is `null`. `ContextBudget.InputAllowanceTokens`, `RemainingTokens`, and `Fits`
are computed from whatever window the budget carries, including a `default`-provenance
one; only the pre-dispatch gate requires trusted provenance. `SpendStore` does not expand
`~`, does not reset a ledger it accumulates (accumulating the same ledger twice counts it
twice), keeps at most 512 buckets, and does not coordinate concurrent writers.

`Generation.CacheMechanism` reports the cache plan that applied to the winning attempt:
`CacheMechanism.Explicit`, `CacheMechanism.Implicit`, or `null` when no mechanism engaged.
It is not a provider-reported cache hit, a cache saving, or a placement policy;
provider-reported cache reads and writes stay in `Usage`. No built-in descriptor declares
a cache mechanism, so a cache policy engages only on a custom descriptor.

## Telemetry and Manifests {#telemetry}

Observers are synchronous, run on the emitting thread, and may be called concurrently by
concurrent requests; an observer exception is suppressed, and the first one per
subscription is traced as a warning. `ArenaCompleted`, `ContextReduced`,
`CredentialRotated`, `BatchSubmitted`, `BatchCompleted`, `ServerLifecycle`, and
`DownloadProgress` exist for format parity but are never emitted. The
`cache.prefix-unstable` `ProviderDiagnostic` carries no request ID. `LoggingObserver`
constructed without a `TraceSource` writes to an `AnyInfer.Telemetry` source whose switch is
off, so it records nothing until that source is configured.

Manifests use the shared format. A C# manifest's context facet is always empty,
`request.estimated_tokens` is always `null`, and embedding and rerank manifests number every
attempt `1`, even after a retry.

## Context Tuning {#context-tuning}

`ContextTuning` is a standalone, immutable settings record with the same 17 settings as
Python's, under PascalCase names and native types. `FromMapping` accepts the exact Python
snake_case keys, rejects unknown keys, wrong JSON types, and invalid values, and returns a
validated instance; `ToMapping` returns all 17 settings; `Merged` ignores null-valued
overrides, applies the rest with the same validation, and never modifies the original.
These are settings only: the C# SDK has no context reducer, history reduction,
request-path context handling, or configuration `context` block, so nothing in the SDK
consumes them.
