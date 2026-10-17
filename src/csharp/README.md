# AnyInfer for .NET

`AnyInfer` is a bounded prerelease .NET 8 core for applications that supply their own
provider adapters. It exposes `AsyncClient`, typed requests and events, routing, and
structured-output enforcement. The package does not include provider credentials or a
hosted provider configuration.

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

## Use a custom adapter

Register an implementation of `AnyInfer.Providers.IProviderAdapter` with a
`ProviderRegistration`, then create an `AsyncClient`. The adapter translates its provider's
wire protocol into `AdapterEvent` values; retries, routing, validation, and repair stay in
the client core.
