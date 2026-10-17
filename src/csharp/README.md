# AnyInfer for .NET

`AnyInfer` is a bounded prerelease .NET 8 core. It exposes `AsyncClient`, typed requests and
events, routing, structured-output enforcement, and the built-in OpenAI-compatible adapter.
Applications configure that adapter with `ProviderSettings` and credential references such as
`env://ANYINFER_API_KEY`; custom adapters remain available for application-owned protocols.

This package is a proof artifact at version `0.1.0-proof`. It is not a claim of parity
with the Python runtime or of a published NuGet availability.

## Build a local package

From `src/csharp`, pack the core project with the repository revision supplied by the
build environment:

```powershell
dotnet pack AnyInfer/AnyInfer.csproj -c Release -p:SourceRevisionId=<40-character-git-revision>
```

The package targets `net8.0`, has no runtime NuGet dependencies, and includes a portable
symbol package. For a complete local pack, archive inspection, and isolated consumer check,
run this repository's `python scripts/check_csharp_package.py` command from the repository
root.

## Run the SDK proof examples

From `src/csharp`, run the repository's offline async examples after restoring the solution:

```powershell
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

The examples demonstrate settings, buffered generation, streaming, structured output,
configuration, and fallback. Their source is linked from the documentation site. They are a
bounded proof surface, not a released NuGet package or a provider-parity promise.

## Use a custom adapter

Register an implementation of `AnyInfer.Providers.IProviderAdapter` with a
`ProviderRegistration`, then create an `AsyncClient`. The adapter translates its provider's
wire protocol into `AdapterEvent` values; retries, routing, validation, and repair stay in
the client core.
