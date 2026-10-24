# AnyInfer for .NET

`AnyInfer` is an independent native .NET 8 SDK in development. It provides sync and async generation,
structured-output enforcement, rich generation inputs, and an explicit registered-tool loop. The
built-in OpenAI-compatible adapter supports text, images, inline documents, and inline audio; it
rejects video and document URL inputs. Built-in TEI, Voyage, and Jina adapters support buffered
text embeddings and reranking. Applications configure adapters with `ProviderSettings` and
credential references such as `env://ANYINFER_API_KEY`, `env://TEI_API_KEY`, or
`env://VOYAGE_API_KEY`; custom adapters remain available for application-owned protocols.

This package is locally versioned `0.1.0-proof`, is not published to NuGet, and makes no full-parity or support-matrix claim. Python remains the supported published SDK. See the [shared foundation](https://anyinfer.dev/concepts/foundation/) for current capabilities and limits.

## Build a local package

From `src/csharp`, pack the core project with the repository revision supplied by the
build environment:

```powershell
dotnet pack AnyInfer/AnyInfer.csproj -c Release -p:SourceRevisionId=<40-character-git-revision>
```

The package targets `net8.0`, carries the qualified `JsonSchema.Net` `8.0.5` and `PeterO.Numbers`
`1.8.2` runtime dependencies for modern JSON Schema validation and exact public accounting values,
and includes a portable symbol package. The SDK supports
Draft 6, Draft 7, Draft 2019-09, and Draft 2020-12; legacy Draft 3 and Draft 4 remain deferred.
Modern schema input and generated values can retain arbitrary-size integers, but the pinned native
validator compares numeric values for `const`, `enum`, and `uniqueItems` through .NET `decimal`.
Values outside that range, such as `1e70`, raise a controlled schema-evaluation exception.
For a complete local pack, archive inspection, and isolated consumer check, run this repository's
`python scripts/check_csharp_package.py` command from the repository root.

## Run the SDK proof examples

From `src/csharp`, run the repository's offline async examples after restoring the solution:

```powershell
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

The examples demonstrate settings, buffered generation, streaming, structured output,
configuration, fallback, built-in TEI, Voyage, and Jina embedding and reranking, explicit capability probes,
declarative setup metadata, bounded
winning-request pricing, explicit budgeting, caller-owned ledger/store helpers, standalone pacing,
explicit request-policy inputs, and the synchronous `Client`/`SyncStream` facade. Their source is linked from the documentation site.
Capability probes can send up to four requests by default; a raw tool declaration in that probe
measures provider behavior and is separate from `RunTools`, the explicit loop over registered
handlers. Rich inputs and tool execution are bounded native capabilities, not provider-wide
coverage promises. Accounting values do not represent provider invoices or all-wire totals.
Context and history reduction and transactional cross-process store updates are not provided.
Retrieval input batching is supported; batch inference jobs are not. Spend policy, cache planning,
specialized context fallback, and raw tool values remain explicit caller inputs. The generic
OpenAI-compatible descriptor declares no cache mechanism. Configured `RateLimits` pace normal provider HTTP inside the
generation entry deadline; own-transport descriptors and opaque prebuilt registrations with active
injected limiters use an outer slot before entry.

The TEI, Voyage, and Jina adapters are the bounded built-in native retrieval bindings. The TEI example
uses separate loopback instances for embedding and reranking because a TEI process serves one
model. Buffered C# embedding and reranking were exercised against the pinned TEI 1.9.4 CPU
deployment on 2026-10-22. The Voyage and Jina examples use offline scripted responses. Hosted
Voyage and Jina traffic has not been live-verified. The OpenAI-compatible adapter remains chat-only.

## Use a custom adapter

Register an implementation of `AnyInfer.Providers.IProviderAdapter` with a
`ProviderRegistration`, then create an `AsyncClient`. The adapter translates its provider's
wire protocol into `AdapterEvent` values; retries, routing, validation, and repair stay in
the client core.
