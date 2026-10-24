# C# SDK (prerelease)

The repository includes a bounded, prerelease C# SDK proof for .NET 8. Its runnable source
examples live in `examples/csharp-sdk/`; the proof uses the same shared contract checks as the
repository's native C# work, while the supported product SDK and published package remain
Python.

The generation examples use `ProviderSettings` and the built-in OpenAI-compatible and Cerebras
providers.
The C# proof also includes built-in TEI, Voyage, and Jina adapters for buffered embeddings and
reranking; other provider-specific retrieval remains application-owned. The async calls accept
a cancellation token and use `await using`; the matching synchronous facade uses `using` and
the .NET default task scheduler.

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

## Use the registered Cerebras provider

The default C# registry includes Cerebras for generation. Configure it with ordinary
`ProviderSettings`, retain the credential as an explicit environment reference, and target the
provider with `cerebras:model`; no generic OpenAI-compatible provider setup is needed.

```csharp
--8<-- "examples/csharp-sdk/CerebrasExample.cs"
```

The included executable example substitutes a scripted HTTP handler and checks its request and
result offline. It does not make hosted Cerebras traffic live-verified. Other generated
OpenAI-compatible presets remain unavailable through the C# default registry.
Choose a model available to the configured account through discovery; this example's
`gpt-oss-120b` target is not a static catalog guarantee.

## Configure provider connections

`ProviderSettings` can carry an explicit HTTP(S) proxy, TLS verification mode, and PEM client
certificate for SDK-created handlers. The example below demonstrates immutable construction and
version 1 JSON round-tripping only; its illustrative paths are not loaded. `ToString()` omits
connection values, while `AnyInferConfig.Dumps()` preserves configured literals, including proxy
credentials and a client-key password. Protect that JSON as a secret-bearing configuration file.
In version 1 JSON, `proxy` is the literal proxy URI, `verify` is omitted or `true` for platform
defaults, `false` to disable verification, or a PEM bundle path; `client_cert` is a combined PEM
path or a two/three-item array for certificate path, key path, and optional key password.

```csharp
--8<-- "examples/csharp-sdk/ConnectionExample.cs"
```

An omitted `verify` setting uses the platform default trust behavior. `TlsVerification.Disabled`
explicitly disables server certificate verification. `TlsVerification.FromPemBundle(path)` uses
that PEM file as custom trust roots; it does not augment the platform roots. Configure root CA
certificates in the bundle. The native .NET implementation does not accept OpenSSL CA directories;
the platform chain engine determines intermediate-certificate and leaf-anchor handling. C# does
not reproduce Python/OpenSSL partial-chain behavior.

`ClientCertificate.FromPemFile` reads a combined unencrypted certificate/key PEM. `FromPemPair`
reads separate unencrypted certificate and key files. `FromEncryptedPemPair` reads a certificate
file and encrypted private-key file with its password; the two paths may name the same combined
file. File access and parsing occur only when the selected provider first needs an SDK-created
handler, and failures are reported then. A caller-supplied `HttpMessageHandler` takes ownership
of connection behavior: SDK proxy/TLS settings are bypassed, and the SDK does not load their
configured files. Provider redirects follow the shared
[redirect policy](../reference/configuration.md#provider-http-redirects). A supplied handler
must return each hop for the SDK to apply that policy; redirects or cookies handled inside the
handler remain caller-controlled.

On Windows, native TLS may back a PEM client private key with a temporary OS-managed user-key
file; the SDK does not add the certificate to the system certificate store. Releasing the handler
and certificate releases SDK references, but native references can defer normal key-file cleanup.
The SDK does not promise memory-only storage or immediate file deletion.

## Generate text

`GenerationExample.RunAsync` shows buffered text generation. It takes explicit settings, target,
and cancellation token so application code can supply its own configuration boundary.

```csharp
--8<-- "examples/csharp-sdk/GenerationExample.cs"
```

## Rich generation inputs and outputs

Generation can combine `Text` with typed `ImagePart`, `DocumentPart`, `AudioPart`, and
`VideoPart` inputs. Inline bytes are copied into read-only values. Image, document, and video
parts take exactly one inline byte source or URL reference; audio is inline-only. The core
does not fetch URL references. Inline input defaults to 20 MiB per part and 50 MiB total.
The built-in C# chat-completions adapter supports images, inline documents, and inline audio;
it refuses video and document URL inputs before sending a request. Other adapters may define
their own rich-input translation.

The executed example below sends typed inline image, document, and audio input and requests
token log-probabilities. Its scripted transport is checked by the offline example runner.

```csharp
--8<-- "examples/csharp-sdk/RichGenerationExample.cs"
```

`Generation.Text` contains visible answer text. Reasoning remains a separate stream event;
log-probabilities, citations, and provider-run tool usage are exposed through separate typed
result fields or events. Rich custom adapters can provide those normalized values. The built-in
chat-completions adapter currently projects log-probability requests and responses; it does not
invent reasoning, citation, or provider-run tool support.

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

## Embed and rerank text

Embedding and reranking are buffered retrieval operations, not generation prompts. The built-in
TEI descriptor provides both operations for a local TEI server, and the built-in Voyage and Jina
descriptors provide them for a configured hosted instance. The public protocols also let an
application register its own retrieval adapter. The TEI example uses separate embedding and
rerank instances because each TEI server process serves one model. It demonstrates async
disposal and the synchronous facade with caller-owned document IDs.

```csharp
--8<-- "examples/csharp-sdk/TeiExample.cs"
```

The offline example verifier uses scripted HTTP responses. Buffered C# embedding and reranking were exercised against the pinned TEI 1.9.4 CPU deployment on 2026-10-22.

The Voyage example accepts a caller-provided credential value or `env://VOYAGE_API_KEY`
reference, configures an instance alias, and requests raw payload retention explicitly. Its
scripted handler demonstrates the built-in descriptor's array input, `query` and `document`
input intents, and native `top_k`. It makes no hosted Voyage
request and does not provide live-verification evidence.

```csharp
--8<-- "examples/csharp-sdk/VoyageExample.cs"
```

The Jina example uses a caller-provided credential value or `env://JINA_API_KEY` reference,
an instance alias, raw retention, and scripted responses. It exercises text query/document
requests and does not live-verify hosted Jina traffic.

```csharp
--8<-- "examples/csharp-sdk/JinaExample.cs"
```

```csharp
--8<-- "examples/csharp-sdk/RetrievalExample.cs"
```

`BatchPolicy` is opt-in core policy. An unknown provider limit remains one bounded request;
splitting needs a declared, discovered, probed, or caller-supplied ceiling. Reranking does not
split and combine scores by default because results from separate batches may not share a score
scale. `EmbeddingResult` records its `EmbeddingSpace`, so applications should compare or store
vectors only when their spaces are compatible.

Both calls request a content-free manifest. Raw provider payload retention remains off unless a
caller explicitly enables it, so the result's `Raw` is normally `null` and the manifest has no
payload facet.

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
records what the endpoint actually established at `Probed` provenance. The raw tool declaration
here is only the probe input. Normal registered-tool execution uses the separate bounded loop
documented in [Run the tool loop](tool-loop.md).

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

## Apply request policy explicitly

Spend policy, context-window routes, cache placement, and raw tool declarations are explicit
client or request inputs. A supplied ledger remains caller-owned; a spend policy without one
creates a client-local ledger. The generic OpenAI-compatible descriptor declares no cache
mechanism. `ToolSpec`, `ToolCall`, and `ToolResult` remain available as raw values; the bounded
registered-tool loop is documented in [Run the tool loop](tool-loop.md).

```csharp
--8<-- "examples/csharp-sdk/RequestPolicyExample.cs"
```

Normal configured HTTP, including a supplied handler for a normal configured descriptor, is paced
inside the generation entry deadline when `RateLimits` are active. Only an own-transport
descriptor, or an opaque prebuilt registration with an active injected limiter, uses an outer slot
before that deadline. Callers retain ownership of injected estimators, ledgers, limiters, and
stores. Pool-owned raw transport differs from wrapper ownership, and transferred raw transport
cannot rebuild through the wrapper path.

## Stream, validate, and route

The remaining examples are source-linked so the site stays aligned with the code the offline
verifier runs.

- [Streaming](streaming.md) uses `StreamingExample.RunAsync`.
- [Structured output](structured-output.md) uses `StructuredOutputExample.RunAsync`.
- [Fallback](fallback.md) uses `RoutingExample.RunAsync`.
- [Configuration](python-to-csharp.md) uses `ConfigurationExample.RunAsync`.

## Scope

This proof covers asynchronous text generation and typed rich-input generation through the
OpenAI-compatible adapter, plus a bounded registered-tool loop and a synchronous facade over
that same core. It also covers buffered text embeddings and reranking through the
built-in TEI, Voyage, and Jina adapters and application-owned retrieval adapters. The
OpenAI-compatible adapter remains chat-only. It also covers structured JSON validation and repair,
configuration, routing, reported token usage, bounded winning-request pricing, explicit budgets,
caller-owned ledger and store helpers, standalone pacing, request-policy inputs, explicit capability probes, payload-free
typed telemetry, immutable manifests, and declarative setup metadata. It does not provide a
released NuGet package, full provider parity, provider invoice or all-wire totals, context/history
reduction, or production report publication. Built-in retrieval coverage is limited to TEI, Voyage, and Jina; generic
OpenAI-compatible retrieval is not implemented in this proof.

For structured output, use `SchemaSpec` with Draft 6, Draft 7, Draft 2019-09, or Draft 2020-12.
Draft 3 and Draft 4 remain deferred. Native numeric and regular-expression behavior applies, with
a timeout for each regular-expression match. Registered schema resources are explicit, and external
resource retrieval requires an explicit opt-in retriever.

Modern schemas and generated values retain arbitrary-size integers at the input boundary. Numeric
comparisons in `const`, `enum`, and `uniqueItems` use the pinned native validator's .NET `decimal`
domain, so a value outside that range, such as `1e70`, produces a controlled schema-evaluation
exception.
