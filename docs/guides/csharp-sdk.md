# C# SDK (prerelease)

The repository includes a bounded, prerelease C# SDK proof for .NET 8. Its runnable source
examples live in `examples/csharp-sdk/`; the proof uses the same shared contract checks as the
repository's native C# work, while the supported product SDK and published package remain
Python.

The examples use `ProviderSettings` and the built-in OpenAI-compatible provider. They do not
require an application-defined adapter. They are asynchronous, accept a cancellation token, and
use `await using` for client lifetime.

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

## Generate text

`GenerationExample.RunAsync` shows buffered text generation. It takes explicit settings, target,
and cancellation token so application code can supply its own configuration boundary.

```csharp
--8<-- "examples/csharp-sdk/GenerationExample.cs"
```

## Stream, validate, and route

The remaining examples are source-linked so the site stays aligned with the code the offline
verifier runs.

- [Streaming](streaming.md) uses `StreamingExample.RunAsync`.
- [Structured output](structured-output.md) uses `StructuredOutputExample.RunAsync`.
- [Fallback](fallback.md) uses `RoutingExample.RunAsync`.
- [Configuration](python-to-csharp.md) uses `ConfigurationExample.RunAsync`.

## Scope

This proof covers async text generation through the OpenAI-compatible adapter, structured JSON
validation and repair, configuration, routing, and reported token usage. It does not provide a
released NuGet package, a synchronous API, provider parity, aggregate usage accounting, tool
execution, embeddings, reranking, or production report publication.
