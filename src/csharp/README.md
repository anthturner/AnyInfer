# AnyInfer for .NET

`AnyInfer` is a bounded prerelease .NET 8 core. It exposes `AsyncClient`, typed requests and
events, routing, structured-output enforcement, a chat-only built-in OpenAI-compatible adapter,
and built-in TEI and Voyage adapters for buffered text embeddings and reranking. Applications
configure these adapters with `ProviderSettings` and credential references such as
`env://ANYINFER_API_KEY`, `env://TEI_API_KEY`, or `env://VOYAGE_API_KEY`; custom adapters remain available for
application-owned protocols.

This package is a proof artifact at version `0.1.0-proof`. It is not a claim of parity
with the Python runtime or of a published NuGet availability.

## Build a local package

From `src/csharp`, pack the core project with the repository revision supplied by the
build environment:

```powershell
dotnet pack AnyInfer/AnyInfer.csproj -c Release -p:SourceRevisionId=<40-character-git-revision>
```

The package targets `net8.0`, carries the qualified `JsonSchema.Net` `8.0.5` and `PeterO.Numbers`
`1.8.2` runtime dependencies for modern JSON Schema validation and exact public accounting values,
and includes a portable symbol package. The proof supports
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
configuration, fallback, built-in TEI and Voyage embedding and reranking, explicit capability probes,
declarative setup metadata, bounded
winning-request pricing, explicit budgeting, caller-owned ledger/store helpers, standalone pacing,
explicit request-policy inputs, and the synchronous `Client`/`SyncStream` facade. Their source is linked from the documentation site.
Capability probes can send up to four requests by default; the raw tool declaration used by that
measurement does not provide normal tool execution. The examples are a bounded proof surface, not
a released NuGet package or a provider-parity promise. Accounting values do not represent provider
invoices or all-wire totals, and the helpers do not activate automatic tool execution, rich-media
input breadth, context/history reduction, or transactional cross-process store
updates. Spend policy, cache planning, specialized context fallback, and raw tool values are
explicit caller inputs; the generic OpenAI-compatible descriptor declares no cache mechanism, and
raw tool values do not execute a tool. Configured `RateLimits` pace normal provider HTTP inside the
generation entry deadline; own-transport descriptors and opaque prebuilt registrations with active
injected limiters use an outer slot before entry.

The TEI and Voyage adapters are the bounded built-in native retrieval bindings. The TEI example
uses separate loopback instances for embedding and reranking because a TEI process serves one
model. Buffered C# embedding and reranking were exercised against the pinned TEI 1.9.4 CPU
deployment on 2026-10-22. The Voyage example is an offline scripted-handler witness and does not
live-verify hosted Voyage traffic. The OpenAI-compatible adapter remains chat-only, and Jina has
no C# built-in adapter in this proof.

## Use a custom adapter

Register an implementation of `AnyInfer.Providers.IProviderAdapter` with a
`ProviderRegistration`, then create an `AsyncClient`. The adapter translates its provider's
wire protocol into `AdapterEvent` values; retries, routing, validation, and repair stay in
the client core.
