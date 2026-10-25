# C# SDK (prerelease)

The repository includes an independent native .NET 8 SDK in development. Its runnable
source examples live in `examples/csharp-sdk/`. Python remains the supported published SDK;
C# is locally packaged as `0.1.0-proof` and runs without a Python runtime. It is not published
to NuGet and does not claim full parity or a support matrix. See the
[foundation capability map](../concepts/foundation.md).

The generation examples use `ProviderSettings` and the built-in OpenAI-compatible, Cerebras,
Hyperbolic, and Nscale providers.
The C# SDK also includes built-in TEI, Voyage, and Jina adapters for buffered embeddings and
reranking; other provider-specific retrieval remains application-owned. The async calls accept
a cancellation token and use `await using`; the matching synchronous facade uses `using` and
the .NET default task scheduler.

## Start here

If you are new to the C# SDK, start with these two pages:

- [Install the C# SDK](csharp-installation.md): the .NET 8 requirements and the project reference
  an application adds to a checkout of this repository.
- [C# quickstart](csharp-quickstart.md): a first buffered call, cancellation and deadlines,
  asynchronous and synchronous disposal, and an application test that needs no network or key.

This page then indexes the native tasks, in the order an application usually needs them:

- [Create provider settings](#create-provider-settings) for the destination and credential
  boundary, then [Generate text](#generate-text).
- [Stream, validate, and route](#stream-validate-and-route) for the compiled streaming,
  structured-output, and fallback examples.
- [Run the tool loop](tool-loop.md) for registered .NET tool handlers, the
  [C# reference](../reference/csharp-sdk.md) for native behavior and limits, or the
  [C# API reference](/csharp/api/) for every public type.
- The operational recipes, grouped by task: [connect to providers](#connect-to-providers),
  [generate](#generate), [embed and rerank](#embed-and-rerank),
  [inspect metadata and providers](#inspect-metadata-and-providers),
  [observe requests](#observe-requests), and
  [account for spend and apply policy](#account-for-spend-and-apply-policy).

Each recipe includes source that the offline example runner executes and checks, then links
the concept page that explains the behavior and the generated pages for the types it uses.

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

## Use in a .NET application

The native SDK is a local prerelease, not a public NuGet package. A .NET 8 application references
`src/csharp/AnyInfer/AnyInfer.csproj` from a checkout of this repository:
[installation](csharp-installation.md#add-a-project-reference) gives the requirements and the
exact commands, and the [quickstart](csharp-quickstart.md) continues to a first call. The core SDK
namespace is `AnyInfer`.

`SettingsExample`, `GenerationExample`, and the other `*Example` classes on this page are helper
classes in the examples project, rather than SDK exports; see
[the library and the example helpers](csharp-installation.md#library-and-example-helpers). Use the
`ProviderSettings`, `AsyncClient`, and `GenerateAsync` calls shown inside them in your own
application, starting with [provider settings](#create-provider-settings) for the endpoint and
credential reference.

## Connect to providers

Settings describe one provider instance. Creating settings, loading configuration, and
constructing a client resolve no credential, build no adapter, and send nothing; the first
operation that needs an instance resolves its credential and builds its adapter.

### Create provider settings

`SettingsExample.Create` accepts an optional credential value or reference. Pass an `env://`
reference when that is how the application supplies credentials; the example does not create one
automatically. Resolution occurs only when the client first needs it.

```csharp
--8<-- "examples/csharp-sdk/SettingsExample.cs"
```

Types: [`ProviderSettings`](/csharp/api/anyinfer.providersettings/),
[`AsyncClient`](/csharp/api/anyinfer.asyncclient/).

### Use the registered Cerebras provider

The default C# registry includes Cerebras for generation. Configure it with ordinary
`ProviderSettings`, retain the credential as an explicit environment reference, and target the
provider with `cerebras:model`; no generic OpenAI-compatible provider setup is needed.

```csharp
--8<-- "examples/csharp-sdk/CerebrasExample.cs"
```

The included executable example substitutes a scripted HTTP handler and checks its request and
result offline. It does not make hosted Cerebras traffic live-verified. Hyperbolic and Nscale
are the other provider-specific generation presets selected in the C# default registry; remaining
generated compatibility-preset rows are inert there.
Choose a model available to the configured account through discovery; this example's
`gpt-oss-120b` target is not a static catalog guarantee.

### Use the registered Hyperbolic provider

The default C# registry also includes Hyperbolic for generation through the shared chat adapter.
Use ordinary `ProviderSettings` with an explicit `env://HYPERBOLIC_API_KEY` credential reference
and a `hyperbolic:model` target. The default endpoint is
`https://api.hyperbolic.ai/inference/v1`; Hyperbolic has decommissioned its former
`https://api.hyperbolic.xyz/v1` endpoint. The adapter appends routes beneath the full new prefix.

```csharp
--8<-- "examples/csharp-sdk/HyperbolicExample.cs"
```

The executable example uses a scripted handler to check the implicit default URI, Bearer header,
request model and body, returned text and usage, and disposal without contacting Hyperbolic.
Hosted Hyperbolic traffic remains unverified. Choose a model available to the configured account
through discovery; `glm-5.3-flash` is the documentation example identifier, not a static catalog
guarantee. Cerebras, Hyperbolic, and Nscale are the reviewed registered generation presets in
this C# registry; all other generated preset rows remain inert.

### Use the registered Nscale provider

The default C# registry includes Nscale for generation through the shared chat adapter. Use
ordinary `ProviderSettings` with an explicit `env://NSCALE_API_KEY` credential reference and an
`nscale:model` target; no base URL override is needed. Nscale's official examples use
`NSCALE_SERVICE_TOKEN`, which callers can use by supplying that explicit environment reference.

```csharp
--8<-- "examples/csharp-sdk/NscaleExample.cs"
```

The executable example injects a literal offline key and uses a scripted handler to check the
default HTTPS URI, Bearer header, model and request body, returned text and usage, and handler
disposal. It does not make hosted Nscale traffic live-verified. The
`meta-llama/Llama-3.1-8B-Instruct` target is a scripted documentation example, not an account
catalog guarantee; discover models available to the configured account. Exact SSE framing and
terminal usage timing remain unverified. Only the `medium` reasoning value is shown; the accepted
effort enum remains unverified. Generic typed history does not retain `reasoning_content`.
The current capability map and exclusions are maintained in the [shared foundation](../concepts/foundation.md).

### Load a configuration file

`AnyInferConfig.Loads` reads configuration text and `AnyInferConfig.Load` reads an explicit path;
no default location is searched, and a document may be at most 1 MiB. The native reader accepts
the bounded version 1 format: `format_version` (only `1`), `providers`, `default_route`,
`operation_routes` (only `embedding` and `rerank`), `repair` (only `max_attempts`), `cache`, and a
root `_comment`. The demo application's interface keys are accepted and ignored. The `context`,
`history`, `observers`, `arena`, `arenas`, and `mcp` blocks are Python features: the native
reader rejects them, and any other unknown key, with a `ConfigException` whose message names the
source.

```csharp
--8<-- "examples/csharp-sdk/ConfigurationFileExample.cs:document"
```

Loading validates provider identifiers against the registry and checks each `api_key` against the
resolver chain, but resolves no credential, builds no adapter, and opens no certificate file.
`AsyncClient.FromConfig` then uses `default_route` for generation and `operation_routes` for
embedding and reranking, so this application code names no target:

```csharp
--8<-- "examples/csharp-sdk/ConfigurationFileExample.cs:use"
```

The offline runner loads this exact document, checks every accepted block, and confirms that the
answer sends one rerank request and one chat request and that each unimplemented block, a
`generation` operation route, and `format_version` 2 are rejected at load. `Dumps()` and
`Dump(path)` write configuration back exactly as configured: an `env://` reference stays a
reference, while a literal key, proxy credentials, and certificate paths and passwords are written
as literal text, so protect the output (see
[Configure provider connections](#configure-provider-connections)). `Dump` refuses to replace an
existing file unless `force` is true.

Concept: [Shared configuration](../reference/configuration.md#file-format). Types:
[`AnyInferConfig`](/csharp/api/anyinfer.config.anyinferconfig/),
[`ConfigException`](/csharp/api/anyinfer.configexception/).

### Resolve credential references

An `api_key` is a literal or a reference. The default
[`ResolverChain`](/csharp/api/anyinfer.credentials.resolverchain/) tries three resolvers in order:
`KeyringResolver` claims `credential://` references, `EnvResolver` reads `env://NAME`, and
`LiteralResolver` accepts any value that is not reference-shaped. Configuration loading asks the
chain only whether it handles each key, so a reference whose scheme no resolver handles fails
at load with `ConfigException`.

Resolution happens when the first operation needs that provider instance, before its request is
sent. An `env://` variable is read then, so a variable set after loading is seen, and an unset or
empty variable fails with `CredentialException` with nothing sent. Pure queries such as `Resolve`
and `Capabilities` resolve nothing. Each resolved value is registered for redaction.

This build has no operating-system keyring integration. A `credential://` reference passes
loading, so that it is never sent as a literal key, but resolving it always fails with
`CredentialException`. Use `env://`, a literal, or a resolver of your own:

```csharp
--8<-- "examples/csharp-sdk/CredentialReferenceExample.cs:load"
```

```csharp
--8<-- "examples/csharp-sdk/CredentialReferenceExample.cs:resolver"
```

Pass the same chain to `AnyInferConfig.Loads` and to the client: loading uses it to admit
`app-secret://` references, and the client uses it to resolve them. The offline runner checks
the `env://` timing, the `credential://` failure, the load-time rejection of an unhandled scheme,
and a missing application secret, each failing before any request.

Concept: [Credentials and redaction](../concepts/credentials.md#custom-resolvers); the operating-system
keyring described there is Python-only. Types:
[`ICredentialResolver`](/csharp/api/anyinfer.credentials.icredentialresolver/),
[`EnvResolver`](/csharp/api/anyinfer.credentials.envresolver/),
[`KeyringResolver`](/csharp/api/anyinfer.credentials.keyringresolver/),
[`LiteralResolver`](/csharp/api/anyinfer.credentials.literalresolver/),
[`CredentialException`](/csharp/api/anyinfer.credentialexception/).

### Configure provider connections

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

The offline runner also checks both sides of that boundary: a missing PEM file fails with
`ConfigException` at the first call, not when settings or the client are created, and a supplied
handler with the same settings answers normally.

On Windows, native TLS may back a PEM client private key with a temporary OS-managed user-key
file; the SDK does not add the certificate to the system certificate store. Releasing the handler
and certificate releases SDK references, but native references can defer normal key-file cleanup.
The SDK does not promise memory-only storage or immediate file deletion.

Concept: [Proxies, private CAs, and mTLS](../reference/configuration.md#proxies-private-cas-and-mtls).
Types: [`ProviderProxy`](/csharp/api/anyinfer.providerproxy/),
[`TlsVerification`](/csharp/api/anyinfer.tlsverification/),
[`ClientCertificate`](/csharp/api/anyinfer.clientcertificate/).

## Generate

### Generate text

`GenerationExample.RunAsync` shows buffered text generation. It takes explicit settings, target,
and cancellation token so application code can supply its own configuration boundary. The
[quickstart](csharp-quickstart.md#make-the-first-call) reads the result's text and usage, and
covers [cancellation](csharp-quickstart.md#cancel-a-call-or-set-a-deadline) and
[disposal](csharp-quickstart.md#dispose-the-client).

```csharp
--8<-- "examples/csharp-sdk/GenerationExample.cs"
```

Types: [`AsyncClient`](/csharp/api/anyinfer.asyncclient/),
[`Generation`](/csharp/api/anyinfer.generation/).

### Rich generation inputs and outputs

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

Concept: [Multimodal inputs](../concepts/multimodal-inputs.md). Types:
[`GenerationRequest`](/csharp/api/anyinfer.generationrequest/),
[`Message`](/csharp/api/anyinfer.message/), [`ImagePart`](/csharp/api/anyinfer.imagepart/),
[`DocumentPart`](/csharp/api/anyinfer.documentpart/), [`AudioPart`](/csharp/api/anyinfer.audiopart/),
[`VideoPart`](/csharp/api/anyinfer.videopart/), [`TokenLogprob`](/csharp/api/anyinfer.tokenlogprob/).

### Request provider-run tools

`ServerToolSpec` asks the provider to run a tool inside one request: `web_search` or
`code_execution`, with an optional `maxUses` ceiling. Nothing comes back for your application to
run; for tools your application runs, see [Run the tool loop](tool-loop.md). A target whose
descriptor has no wire form for the requested kind, or whose trusted capabilities exclude it,
fails its attempt with `UnsupportedInputException` before its provider is called. When every
target refuses, the call throws `AllTargetsFailedException` and each attempt carries that error.

None of the built-in C# descriptors declares a provider-run tool, so with the built-in chat,
Cerebras, Hyperbolic, and Nscale providers this request is always refused before anything is
sent. The recipe then makes a deliberate application decision: it asks again without the search
and records that the search was not offered, rather than presenting an answer without search as
if it had searched.

```csharp
--8<-- "examples/csharp-sdk/ServerToolExample.cs:ask"
```

A descriptor that an application registers for its own adapter can declare the kinds that
adapter places on the wire (`serverTools`). Its adapter receives the request's `ServerTools`
and reports what ran as `ServerToolUse` counts, which the result exposes as
`Generation.ServerToolUses`. The offline runner checks both paths: the built-in chat adapter
sends one plain request and no tool field, and an application descriptor that declares
`web_search` receives the `maxUses` ceiling and reports two searches.

Concept: [Let the provider run its own tools](python-sdk.md#let-the-provider-run-its-own-tools)
(Python examples). Types: [`ServerToolSpec`](/csharp/api/anyinfer.servertoolspec/),
[`ServerToolUse`](/csharp/api/anyinfer.servertooluse/),
[`UnsupportedInputException`](/csharp/api/anyinfer.unsupportedinputexception/),
[`AllTargetsFailedException`](/csharp/api/anyinfer.alltargetsfailedexception/),
[`ProviderDescriptor`](/csharp/api/anyinfer.providers.providerdescriptor/).

### Use the synchronous facade

`Client` drains the same core execution path through a synchronous facade. It is intended for a
synchronous .NET caller; it does not create or depend on Python's event-loop facade.

```csharp
--8<-- "examples/csharp-sdk/SyncGenerationExample.cs"
```

`SyncStream` is enumerable, exposes `Result` after `StreamEnded`, and is disposed with `using`.

```csharp
--8<-- "examples/csharp-sdk/SyncStreamingExample.cs"
```

Types: [`Client`](/csharp/api/anyinfer.client/), [`SyncStream`](/csharp/api/anyinfer.syncstream/).

### Stream, validate, and route

The remaining examples are source-linked so the site stays aligned with the code the offline
verifier runs.

- [Streaming](streaming.md) uses `StreamingExample.RunAsync`.
- [Structured output](structured-output.md) uses `StructuredOutputExample.RunAsync`.
- [Fallback](fallback.md) uses `RoutingExample.RunAsync`.
- [Configuration](python-to-csharp.md) uses `ConfigurationExample.RunAsync`; the
  [configuration-file recipe](#load-a-configuration-file) shows every accepted block.

## Embed and rerank

### Embed and rerank text

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
The [TEI page](../providers/tei.md#use-tei-from-c) shows the matching settings for the two local
server processes and model discovery.

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

An application-owned retrieval adapter implements `IEmbedsText` and `IReranksText` and is
registered with a `ProviderDescriptor` that declares both operations. `RetrievalExample` runs the
same two calls through such a registry, with the asynchronous and the synchronous client:

```csharp
--8<-- "examples/csharp-sdk/RetrievalExample.cs"
```

Reranking takes `RerankDocument` values whose IDs your application owns; each `RankedItem`
returns that ID, the document's original index in your list, and its score, so results map back
to your records without relying on response order. Usage stays unknown when a provider reports
none: TEI reports no token counts, and Voyage and Jina report a total only.

`BatchPolicy` is opt-in core policy. An unknown provider limit remains one bounded request;
splitting needs a declared, discovered, probed, or caller-supplied ceiling. Reranking does not
split and combine scores by default because results from separate batches may not share a score
scale. `EmbeddingResult` records its `EmbeddingSpace`, so applications should compare or store
vectors only when their spaces are compatible. The next two recipes cover both.

Both calls request a content-free manifest. Raw provider payload retention remains off unless a
caller explicitly enables it, so the result's `Raw` is normally `null` and the manifest has no
payload facet.

Concept: [Embeddings and reranking](../concepts/embeddings.md#reranking-and-document-identity).
Types: [`EmbeddingResult`](/csharp/api/anyinfer.embeddingresult/),
[`RerankResult`](/csharp/api/anyinfer.rerankresult/),
[`RerankDocument`](/csharp/api/anyinfer.rerankdocument/),
[`RankedItem`](/csharp/api/anyinfer.rankeditem/),
[`IEmbedsText`](/csharp/api/anyinfer.providers.iembedstext/),
[`IReranksText`](/csharp/api/anyinfer.providers.irerankstext/).

### Batch large retrieval requests

Retrieval batching splits one embedding or rerank call into several provider requests; it is not
a batch inference job, which C# does not provide. Splitting needs a ceiling. Voyage's descriptor
declares 1,000 embedding inputs and 1,000 rerank documents per request for its listed models.
TEI and Jina declare none: an unknown ceiling is never guessed, so the call is sent as one
bounded request. With no ceiling at all, more than 2,048 embedding inputs or more than 1,000
rerank documents fail locally with `ConfigException`. When your deployment has a limit you have verified, such as the
`max_client_batch_size` a TEI server reports, pass it as `BatchPolicy.MaxItemsOverride`:

```csharp
--8<-- "examples/csharp-sdk/RetrievalBatchingExample.cs:embed"
```

The core sends ordered batches, at most `MaxConcurrency` at a time, and returns one vector per
input in input order. The call is all-or-error: when a batch fails, it throws
`AllTargetsFailedException`, whose `BatchFailures` lists each batch's index, item count, and
outcome. With `AllowSplit` false, a request over the ceiling fails with `ConfigException` before
anything is sent.

Reranking is stricter. A rerank request over the ceiling fails with `ConfigException` unless
`RerankCrossBatch` is true, because scores from separate requests may not share a scale. With
the opt-in, the result concatenates chunk-local rankings, keeps each document's ID and original
index, and carries a warning that says so; a `topN` is then applied within each batch.

```csharp
--8<-- "examples/csharp-sdk/RetrievalBatchingExample.cs:rerank"
```

The offline runner checks that an unknown TEI ceiling sends five inputs as one request, that a
verified ceiling of two sends three batches and returns vectors in input order, that a failed
batch is reported in `BatchFailures`, and that both refusals happen before any request. It also
checks Voyage's declared ceiling splitting 1,001 inputs into batches of 1,000 and 1, and the
local refusals of 1,001 Voyage rerank documents and of 2,049 inputs or 1,001 documents for Jina.

Concept: [Batching](../concepts/embeddings.md#batching). Types:
[`BatchPolicy`](/csharp/api/anyinfer.batchpolicy/),
[`BatchFailure`](/csharp/api/anyinfer.batchfailure/),
[`AllTargetsFailedException`](/csharp/api/anyinfer.alltargetsfailedexception/).

### Route retrieval and keep vectors comparable

`operationRoutes` gives embedding and rerank calls their own default routes, separate from the
generation route; a call that names neither a target nor a route uses its operation route, then
the client's default route. Only `Embedding` and `Rerank` keys are accepted, and
[configuration files](#load-a-configuration-file) can supply the same routes.

```csharp
--8<-- "examples/csharp-sdk/EmbeddingSpaceExample.cs:client"
```

Every `EmbeddingResult` records the `EmbeddingSpace` its vectors live in: provider instance,
model, revision, dimensions, and normalization. Store it beside the vectors. Two spaces are
compatible when they share a caller-asserted `CompatibilityId`, or when provider instance, model,
and revision all match, with two unknown revisions counting as equal; dimensions and
normalization are not compared. Passing the stored space as `expectedSpace` makes the call fail
with `ConfigException` when the returned vectors are in another space. The check runs on the
result, so that request has already been sent. A route that would fall back to a different
instance or model is refused with `ConfigException` before the fallback request unless
`allowIncompatibleFallback` is set, and an allowed fallback result carries a warning.

```csharp
--8<-- "examples/csharp-sdk/EmbeddingSpaceExample.cs:space"
```

```csharp
--8<-- "examples/csharp-sdk/EmbeddingSpaceExample.cs:rerank"
```

The offline runner checks that both operation routes reach their own TEI instance, that a
generation call without a route does not borrow them, that an incompatible stored space fails,
that fallback to another instance is refused unless allowed, and that a `Generation` operation
route is rejected with `ArgumentException`.

Concept: [The embedding-space safety rule](../concepts/embeddings.md#the-embedding-space-safety-rule).
Types: [`EmbeddingSpace`](/csharp/api/anyinfer.embeddingspace/),
[`InferenceOperation`](/csharp/api/anyinfer.capabilities.inferenceoperation/),
[`Route`](/csharp/api/anyinfer.route/).

## Inspect metadata and providers

Some client queries are pure: they read configured settings, the catalog, the pricing table, and
facts already recorded on the client, and never resolve a credential, build an adapter, or send a
request. Others are explicit I/O for one provider instance.

| Pure queries | Calls the provider |
|---|---|
| `Resolve`, `Capabilities`, `Budget`, `Spend`, and `ProviderSetupSpec` metadata | `ModelsAsync`/`Models`, `HealthAsync`/`Health`, and `ProbeAsync`/`Probe` |

### Inspect configured metadata

Catalog resolution and capability or pricing facts are pure client queries: they select from
the configured instance and return provenance-bearing values without constructing an adapter or
sending a request. Unknown facts stay unknown; a listed or catalog value is not an accounting
total.

```csharp
--8<-- "examples/csharp-sdk/CatalogExample.cs"
```

The offline runner checks that this query builds no adapter even when the instance's `env://`
key is unset, while model discovery for an instance with an unset key fails with
`CredentialException` before sending.

Concept: [Capabilities and provenance](../concepts/capabilities.md#inspecting-capabilities). Types:
[`Catalog`](/csharp/api/anyinfer.catalog.catalog/),
[`PricingTable`](/csharp/api/anyinfer.capabilities.pricingtable/),
[`ModelCapabilities`](/csharp/api/anyinfer.capabilities.modelcapabilities/),
[`Provenance`](/csharp/api/anyinfer.capabilities.provenance/).

### Describe provider setup

`ProviderSetupSpec` and its fields are declarative metadata for an application's setup UI.
Creating this metadata does not resolve credentials or construct a provider.

```csharp
--8<-- "examples/csharp-sdk/SetupExample.cs"
```

Types: [`ProviderSetupSpec`](/csharp/api/anyinfer.providers.providersetupspec/),
[`SetupField`](/csharp/api/anyinfer.providers.setupfield/),
[`HostShorthand`](/csharp/api/anyinfer.providers.hostshorthand/).

### List models and check health

Discovery and health are explicit I/O operations for one configured instance. The async and
synchronous methods both own their clients in the example and accept cancellation through the
source-linked methods.

```csharp
--8<-- "examples/csharp-sdk/LifecycleExample.cs"
```

Building the instance's adapter for discovery resolves its credential first. Capabilities in a
model listing are recorded on the client and feed later pure capability queries.

Types: [`DiscoveredModel`](/csharp/api/anyinfer.capabilities.discoveredmodel/),
[`Health`](/csharp/api/anyinfer.capabilities.health/).

### Measure generation capabilities

Probing is explicit I/O: the default selection sends up to four small requests in the fixed
JSON Schema, JSON mode, raw tool-call, and streaming order. The returned immutable report
records what the endpoint actually established at `Probed` provenance. The raw tool declaration
here is only the probe input. Normal registered-tool execution uses the separate bounded loop
documented in [Run the tool loop](tool-loop.md).

```csharp
--8<-- "examples/csharp-sdk/ProbeExample.cs"
```

Probe requests go straight to the target's adapter without routing, retries, repair, or spend
admission. By default the measured features are recorded on the client for later capability
queries and structured-output mechanism choices.

Concept: [Proving a target works](../concepts/capabilities.md#proving-a-target-works). Types:
[`ProbeReport`](/csharp/api/anyinfer.capabilities.probereport/).

## Observe requests

### Observe telemetry and manifests

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

The offline runner checks that the stream's manifest is incomplete before consumption, that the
completed result carries the committed terminal manifest, and that the embedded manifest schema
digest begins with `sha256:` and renders. Generation manifests capture redacted prompt and
response text only when the client is created with `manifestPayloads: true`; embedding and
rerank manifests never carry payloads. A further case checks both halves of that rule.

Concept: [Telemetry](../concepts/telemetry.md) and [run manifests](../concepts/run-manifests.md).
Types: [`IObserver`](/csharp/api/anyinfer.events.iobserver/),
[`TelemetryEvent`](/csharp/api/anyinfer.events.telemetryevent/),
[`RunManifest`](/csharp/api/anyinfer.manifest.runmanifest/),
[`ManifestUtilities`](/csharp/api/anyinfer.manifest.manifestutilities/).

### Write telemetry to a trace source or file

`LoggingObserver` writes each event as one compact, redacted JSON line through a
`System.Diagnostics.TraceSource`. Created without a source, it makes its own
`AnyInfer.Telemetry` source whose switch is off, so it writes nothing unless that source is
configured from outside the observer. The direct path is to pass a source whose switch level and
listeners your application sets:

```csharp
--8<-- "examples/csharp-sdk/TelemetrySinksExample.cs:trace"
```

`JsonlObserver` appends one redacted JSON line per event to a file you choose, creating missing
directories; on platforms other than Windows the file is restricted to owner read and write.
The application owns it: dispose it after the client.

Observers passed to the client constructor receive payload-free events: prompt text, response
text, and repair text are `null`. `Subscribe(observer, payloads: true)` opts one observer in to
redacted payloads.

```csharp
--8<-- "examples/csharp-sdk/TelemetrySinksExample.cs:observe"
```

Observers run synchronously on the request path. An observer that throws does not fail the
request; the first exception from each subscription is reported as a warning on the
`AnyInfer.Events` trace source, whose switch is also off by default, and later ones are
suppressed. Version 1 configuration rejects an `observers` block, so C# sinks are always
created in code, and there is no OpenTelemetry bridge. The offline runner checks that the trace
and JSONL sinks carry no prompt or response text while the opted-in observer does, that a switch
set to `Off` writes nothing until it is raised, and that a throwing observer leaves the request
and later observers unaffected.

Concept: [Payloads are off by default](../concepts/telemetry.md#payloads-are-off-by-default) and
the [observability guide](observability.md#in-process-observers). Types:
[`LoggingObserver`](/csharp/api/anyinfer.events.loggingobserver/),
[`JsonlObserver`](/csharp/api/anyinfer.events.jsonlobserver/),
[`IObserver`](/csharp/api/anyinfer.events.iobserver/).

## Account for spend and apply policy

### Calculate explicit accounting facts

Pricing uses only trusted catalog, discovered, probed, or caller-override provenance. A
default price leaves calculated cost unknown; a trusted zero price remains a known free result.
`Budget` is a pure planning calculation for one explicit target. The request estimator currently counts text only: nontext parts are reported as unpriced, and it has no offered-tools input.

The ledger, store, and limiter below are caller-selected helpers. They do not create default disk
output, refuse a request, pace client transport, or provide a provider invoice or all-wire total.
The caller owns the store path and explicitly acquires and disposes each standalone limiter lease.
Store accumulation is atomic for replacement readability, but it is not transactional read-modify-write
coordination across threads or processes.

```csharp
--8<-- "examples/csharp-sdk/AccountingExample.cs"
```

Concept: [Cost is tri-state](../concepts/cost.md#cost-is-tri-state) and
[estimated cost](../concepts/budgeting.md#estimated-cost). Types:
[`PricingCalculator`](/csharp/api/anyinfer.capabilities.pricingcalculator/),
[`ContextBudget`](/csharp/api/anyinfer.capabilities.contextbudget/),
[`SpendLedger`](/csharp/api/anyinfer.capabilities.spendledger/),
[`SpendStore`](/csharp/api/anyinfer.capabilities.spendstore/),
[`RateLimiter`](/csharp/api/anyinfer.routing.ratelimiter/).

### Share a ledger and persist spend

A `SpendLedger` is accounting for the clients it is given to, in this process only. A client
constructed with a ledger records each completed request into it; two clients share a total only
when they are given the same ledger, and the client never disposes or persists it. A request
whose cost cannot be priced is counted in `UnknownRequests` and never added as zero, so
`SpendTotals.Complete` is false while any are present. Request `metadata` labels group spend with
`ByLabel` and are never sent to the provider.

```csharp
--8<-- "examples/csharp-sdk/SpendStoreExample.cs:record"
```

A `SpendStore` writes only when you call `Accumulate`, to the path you give it, used as given:
unlike the Python store, it does not expand `~`. `Accumulate` adds the ledger's current totals to
one named bucket without resetting the ledger, so the recipe resets it after each period. Run it
while no request is in flight, because the two steps are not one atomic operation.

```csharp
--8<-- "examples/csharp-sdk/SpendStoreExample.cs:period"
```

The file is replaced through a temporary file in the same directory, so readers never see a
partial write, and it keeps at most 512 buckets: adding one more drops the earliest in file
order. Nothing coordinates writers across threads or processes, so concurrent writers to one path
can lose updates; give each process its own store or serialize the writes yourself. A store whose
bucket uses a different currency rejects the ledger with `ArgumentException`. The offline runner
checks the shared and labeled totals, the unknown count, period accumulation, the 513th bucket,
the literal `~` path, and the currency refusal.

Concept: [Keeping a total across restarts](../concepts/cost.md#keeping-a-total-across-restarts).
Types: [`SpendLedger`](/csharp/api/anyinfer.capabilities.spendledger/),
[`SpendStore`](/csharp/api/anyinfer.capabilities.spendstore/),
[`SpendTotals`](/csharp/api/anyinfer.capabilities.spendtotals/).

### Apply request policy explicitly

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

Types: [`SpendPolicy`](/csharp/api/anyinfer.spendpolicy/),
[`CachePolicy`](/csharp/api/anyinfer.cachepolicy/), [`ToolSpec`](/csharp/api/anyinfer.toolspec/),
[`ToolCall`](/csharp/api/anyinfer.toolcall/), [`ToolResult`](/csharp/api/anyinfer.toolresult/),
[`RateLimits`](/csharp/api/anyinfer.ratelimits/).

### Refuse requests over a spend ceiling

A `SpendPolicy` is checked before each attempt is dispatched. It takes the high end of the
request's preflight cost estimate from trusted pricing, here a price the application asserts
with `capabilityOverrides`, and refuses with `SpendLimitException` when that estimate exceeds
`maxRequestUsd`, or when recorded spend plus outstanding reservations plus the estimate exceeds
`maxTotalUsd`. With `onUnknown: "refuse"`, a request whose cost cannot be estimated is refused
too; the default, `"allow"`, sends it. A refused request sends nothing and is not retryable, and the exception is
thrown directly rather than as a routing failure: a ceiling is client-wide, so another target
would not satisfy it.

```csharp
--8<-- "examples/csharp-sdk/SpendAdmissionExample.cs:client"
```

```csharp
--8<-- "examples/csharp-sdk/SpendAdmissionExample.cs:admit"
```

`SpendLimitException` carries the crossed ceiling, the spend already recorded, and the refused
estimate, which is `null` when it could not be estimated. Rerank cost is not estimated before
dispatch, so a policy that refuses unknown costs refuses rerank calls. Capability probes bypass
spend admission. The offline runner checks a priced request within both ceilings, a second
request refused after recorded spend crossed `maxTotalUsd`, a prompt whose own estimate exceeds
`maxRequestUsd`, and an unpriced target refused, all without a request for any refused call.

Concept: [Stopping before you spend too much](../concepts/cost.md#stopping-before-you-spend-too-much).
Types: [`SpendPolicy`](/csharp/api/anyinfer.spendpolicy/),
[`SpendLimitException`](/csharp/api/anyinfer.spendlimitexception/),
[`Pricing`](/csharp/api/anyinfer.capabilities.pricing/),
[`Sourced<T>`](/csharp/api/anyinfer.capabilities.sourced-1/).

### Fall back to a larger context window

A client checks each generation attempt against the target's context window before dispatch
when that window has trusted provenance. An attempt whose estimated input provably exceeds it
fails with `ContextLengthException` without a request, and the route switches to its
`ContextWindowTargets` instead of continuing down the ordinary targets. A provider's own
context-length error redirects the same way.

```csharp
--8<-- "examples/csharp-sdk/ContextWindowRouteExample.cs:route"
```

The offline runner checks that a short prompt stays on the usual target, that a long prompt is
never sent to it and is served by the large-context target with the refused attempt recorded,
and that when neither window fits the call throws `AllTargetsFailedException` without any
request. Only the estimate's lower bound is compared with the whole window, a default-provenance
window never blocks a request, and neither does a request with nontext parts, which the
estimator cannot size; pass `contextGate: false` to the client to turn the check off. Context reduction, which would shorten the prompt instead, is
Python-only.

Concept: [The pre-dispatch gate](../concepts/budgeting.md#the-pre-dispatch-gate) and
[failure-specific fallback chains](../concepts/routing.md#failure-specific-fallback-chains).
Types: [`Route`](/csharp/api/anyinfer.route/),
[`ContextLengthException`](/csharp/api/anyinfer.contextlengthexception/),
[`ModelCapabilities`](/csharp/api/anyinfer.capabilities.modelcapabilities/).

## Scope

The native C# SDK currently covers asynchronous and synchronous text generation, typed rich-input
generation through the OpenAI-compatible adapter, and an explicit bounded loop over registered
tools. It also supports buffered text embeddings and reranking through built-in TEI, Voyage, and
Jina adapters and application-owned retrieval adapters. The
OpenAI-compatible adapter remains chat-only. It also covers structured JSON validation and repair,
configuration, routing, reported token usage, bounded winning-request pricing, explicit budgets,
caller-owned ledger and store helpers, standalone pacing, request-policy inputs, explicit capability probes, payload-free typed telemetry, immutable manifests, and declarative setup
metadata. The local package is not published to NuGet and does not claim full provider parity,
provider invoice or all-wire totals, context reduction, history reduction, or production report
publication. Built-in retrieval coverage is limited to TEI, Voyage, and Jina; generic
OpenAI-compatible retrieval is not implemented.

For structured output, use `SchemaSpec` with Draft 6, Draft 7, Draft 2019-09, or Draft 2020-12.
Draft 3 and Draft 4 remain deferred. Native numeric and regular-expression behavior applies, with
a timeout for each regular-expression match. Registered schema resources are explicit, and external
resource retrieval requires an explicit opt-in retriever.

Modern schemas and generated values retain arbitrary-size integers at the input boundary. Numeric
comparisons in `const`, `enum`, and `uniqueItems` use the pinned native validator's .NET `decimal`
domain, so a value outside that range, such as `1e70`, produces a controlled schema-evaluation
exception.
