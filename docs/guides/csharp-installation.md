# Install the C# SDK (prerelease)

The native C# SDK is the `AnyInfer` library for .NET 8. It is an independent prerelease,
versioned `0.1.0-proof` in this repository and not published to NuGet, so an application uses
it from a checkout of this repository. It runs without Python and does not claim full parity
with the supported Python SDK; the [C# capability map](../concepts/foundation.md#c-capability-map)
lists what it covers.

## Requirements

An application needs:

- **The .NET 8 SDK** to build it and the .NET 8 runtime to run it. The library targets
  `net8.0`, and the steps below create a `net8.0` application.
- **A complete checkout of this repository.** Building the application builds
  `src/csharp/AnyInfer/AnyInfer.csproj` from the checkout, and that project embeds the shared
  catalog, model, and pricing data files under `src/python/anyinfer/` as resources. They are
  compiled in as data; nothing runs Python.
- **The library's NuGet dependencies** at restore time, from a package source or the local
  NuGet cache: `JsonSchema.Net` 8.0.5 and `PeterO.Numbers` 1.8.2, plus `JsonPointer.Net`
  6.0.1, `Json.More.Net` 2.2.0, and `Humanizer.Core` 2.14.1, which `JsonSchema.Net` brings in.

Working on the SDK itself also needs the SDK version pinned by `src/csharp/global.json`
(`8.0.425` with `rollForward: latestPatch`). Commands run from `src/csharp/` select it. An
application outside that directory builds with whichever installed .NET SDK the `dotnet` command
selects there; it does not need that exact version.

## Add a project reference

Replace `<checkout>` with the path of your clone of this repository and `<your-app>` with the
directory for the new application:

```bash
dotnet new console --framework net8.0 --output "<your-app>"
dotnet add "<your-app>" reference "<checkout>/src/csharp/AnyInfer/AnyInfer.csproj"
dotnet build "<your-app>"
```

For an existing application, run only the `dotnet add` line, naming your project file or its
directory. The project file records the reference as a relative path, and each build of the
application builds the library from the checkout, so updating the checkout and rebuilding is how
the application picks up a newer SDK.

The public API is in the `AnyInfer` namespace and its sub-namespaces, such as `AnyInfer.Events`
and `AnyInfer.Providers`; add `using AnyInfer;` where you call it. The
[quickstart](csharp-quickstart.md) continues from this application.

## The library and the example helpers {#library-and-example-helpers}

Reference only `src/csharp/AnyInfer/AnyInfer.csproj`. That project is the library: every public
type in the [C# API reference](/csharp/api/) comes from it.

`examples/csharp-sdk/` holds a separate console project, `AnyInfer.Examples`, which is not
packable. Its `*Example` classes, such as `QuickstartExample` and `GenerationExample`, are the
source the C# pages include, and its offline runner executes and checks each one against scripted
HTTP responses. They are not part of the library and are not meant to be referenced. Copy the
calls you need, or a whole example file, into your application; the files use the
`AnyInfer.Examples` namespace, which you can rename.

## What the library does not include

- **No Python runtime dependency.** Nothing in the library starts or calls Python.
- **No command-line tool, sidecar, or demo application.** `anyinfer run`, the OpenAI-compatible
  sidecar, and the demo app belong to the Python distribution. Any application, including a .NET
  one, can call the Python sidecar over HTTP; that is a separate path from this library.
- **No local runtime management.** The library calls servers that are already running, such as
  Ollama or LM Studio through the OpenAI-compatible descriptor, or TEI for retrieval.
- **No fake-provider test kit.** Offline tests pass a scripted `HttpMessageHandler` as the provider
  transport; the [quickstart](csharp-quickstart.md#test-without-a-network-or-key) shows one.

The rest of the native scope, including the Python features C# does not provide, is in the
[C# capability map](../concepts/foundation.md#c-capability-map).

## Build and check a local package {#local-package}

The library can also be packed as a NuGet package, `AnyInfer.0.1.0-proof.nupkg`, with a symbol
package beside it. The checked way to produce one is the repository's package check. Run it from
the root of a Git clone with Python and the .NET SDK available:

```bash
python scripts/check_csharp_package.py
```

The check packs `src/csharp/AnyInfer/AnyInfer.csproj` in Release configuration, stamped with the
current Git revision. It confirms that the package holds only `lib/net8.0/AnyInfer.dll`,
`README.md`, and `LICENSE`, that the separate `.snupkg` holds the symbols, and that the package
declares `JsonSchema.Net` and `PeterO.Numbers` as its only direct dependencies, whose resolved
graph is the five packages listed under [requirements](#requirements). It then checks the hashes
of those five packages, adds them to the same local folder, and restores, builds, and runs a
fresh `net8.0` console application from that folder alone, using a package cache created for the
run. The checked package and symbol package are copied to `.tmp-tests/nuget/`; `--output`
selects another folder.

This is a local verification, not a release: nothing is published, and every build carries the
same `0.1.0-proof` version. A NuGet cache keeps the first copy it restores of a given version,
which is why the check restores into a new cache folder each time. The project reference above
remains the way to use the SDK in an application. The
[C# development workflow](../contributing/csharp-proof.md#validate-the-local-prerelease-package)
shows the underlying `dotnet pack` command.

## Work on the SDK itself {#work-on-the-sdk}

To build and test the library and run the offline example runner in this repository, follow the
[C# development workflow](../contributing/csharp-proof.md#run-the-proof-locally) from
`src/csharp/`.

## See Also

<div class="anyinfer-see-also" markdown>

- [C# quickstart](csharp-quickstart.md): a first call, cancellation, disposal, and an offline test.
- [C# SDK overview](csharp-sdk.md): the native task guide index.
- [C# API reference](/csharp/api/): every public type in the library.
- [Python installation](installation.md): the supported Python SDK and its extras.

</div>
