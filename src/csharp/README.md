# AnyInfer for .NET

`AnyInfer` is the native .NET 8 SDK of [AnyInfer](https://anyinfer.dev/), an application-owned
inference runtime with a shared language-neutral foundation. This package is an independent
prerelease, versioned `0.1.0-proof`. It is not published to NuGet, has no runtime Python
dependency, and makes no full-parity or support-matrix claim; the Python SDK remains the
supported published SDK.

## Documentation

- [C# SDK guide](https://anyinfer.dev/csharp/): setting up a .NET application, the first call,
  and source-linked examples for each feature.
- [C# API reference](https://anyinfer.dev/csharp/api/): every public type, constructor,
  overload, and member.
- [C# reference notes](https://anyinfer.dev/csharp/reference/): behavior and limits the
  signatures do not show, including the native schema and TLS differences.
- [C# capability map](https://anyinfer.dev/concepts/foundation/#c-capability-map): what the
  native SDK covers and what it does not.

## What It Provides

- `AsyncClient` and its synchronous `Client` facade: buffered and streamed generation
  (`AsyncStream`, `SyncStream`), routing with retry and fallback (`Route`, `Retry`), and
  structured output validated client-side with bounded repair (`Repair`).
- Rich generation inputs and outputs, and `RunToolsAsync` / `RunTools`, a bounded loop over
  registered tool handlers.
- Buffered text embedding and reranking, with input batching.
- Catalog and capability queries, `AnyInferConfig` (a restricted subset of the shared
  version 1 configuration format), `env://` credential references, typed in-process telemetry
  and run manifests, and explicit pricing, budgeting, and accounting helpers.

The default provider registry contains:

| Provider | Operations |
|---|---|
| `openai-compat` | Chat generation against any OpenAI-compatible endpoint; a base URL is required. Accepts text, images, inline documents, and inline audio; rejects video and document URLs. |
| `cerebras`, `hyperbolic`, `nscale` | Generation through the same chat adapter, with each service's endpoint preconfigured. |
| `tei`, `voyage`, `jina` | Embedding and reranking. |

The other OpenAI-compatible preset rows bundled in the assembly are inert data and are not
registered. An application can register its own adapters (see below).

Not provided: context or history reduction, local model and runtime management, sessions, arena
runs, evaluation and benchmarks, batch inference jobs, MCP, OpenTelemetry, OS keyring
credentials, a command-line tool, or an HTTP sidecar. Accounting values are not provider
invoices or all-wire totals.

Buffered embedding and reranking were exercised against a pinned TEI 1.9.4 CPU deployment on
2026-10-22. The Voyage, Jina, Cerebras, Hyperbolic, and Nscale adapters have offline
scripted-response evidence only; their hosted traffic has not been live-verified.

## Reference the Package

Target `net8.0`. The package is not on NuGet, so reference it in one of two ways:

- From a checkout of the repository, add a project reference:

  ```bash
  dotnet add "<your-app.csproj>" reference "<checkout>/src/csharp/AnyInfer/AnyInfer.csproj"
  ```

- From a locally packed `AnyInfer.0.1.0-proof.nupkg`, add the folder that holds it as a NuGet
  package source and reference package `AnyInfer` version `0.1.0-proof`.

The package depends on `JsonSchema.Net` 8.0.5 and `PeterO.Numbers` 1.8.2, ships its XML
documentation beside the assembly, and is packed with a portable symbol package (`.snupkg`).
Schema validation covers Draft 6, Draft 7, Draft 2019-09, and Draft 2020-12; Draft 3 and
Draft 4 are not supported.

## Build It from Source

From `src/csharp` in a checkout, pack the library with the repository revision:

```bash
dotnet pack AnyInfer/AnyInfer.csproj -c Release -p:SourceRevisionId=<40-character-git-revision>
```

`python scripts/check_csharp_package.py`, run from the repository root, performs the complete
local pack, inspects the archive, and builds and runs a fresh consumer against an isolated local
feed. The offline examples run with:

```bash
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

## Use a Custom Adapter

Implement `AnyInfer.Providers.IProviderAdapter`, adding `IProviderLifecycle`, `IEmbedsText`, or
`IReranksText` for discovery, embedding, or reranking. Then either describe it with a
`ProviderDescriptor` and add that to a `ProviderRegistry`, or pass constructed adapters to
`AsyncClient.FromAdapters` as `ProviderRegistration` values. The adapter translates its
provider's wire protocol into `AdapterEvent` values; retries, routing, validation, and repair
stay in the client core.
