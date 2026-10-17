# C# Core-Generation Proof

This repository contains a bounded native C# proof under `src/csharp/`. It independently reads
the frozen shared `core-generation` corpus, executes the supported proof surface from fixture
inputs, and compares the resulting observations afterward. Fixture expectations are comparison
data; they do not drive native execution. The repository also carries source-linked async SDK
proof examples under `examples/csharp-sdk/`.

The proof exists to check the shared contract from another runtime. It does not provide a
supported AnyInfer C# SDK, a registry-published NuGet package, a production integration path,
provider parity, a sync API, or usage-accounting support. The supported runtime, public SDK,
installation guidance, and downloads remain Python surfaces.

## Run the proof locally

Use the SDK selected by `src/csharp/global.json`. Start in the C# root so the SDK resolver sees
that file:

```bash
cd src/csharp
dotnet --version
dotnet restore AnyInfer.sln
dotnet test AnyInfer.sln --no-restore
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

`workspace check` runs the same bounded phase after the repository's Python gates. The C# phase
records the selected SDK version, restores the solution, runs the solution tests without a second
restore, validates a local prerelease package, then runs the offline SDK proof examples.

The [C# SDK proof guide](../guides/csharp-sdk.md) links its snippets directly to those source
files. The examples are not an application installation path or a release promise.

## Validate the local prerelease package

Normal C# test runs stop after the solution tests. The full workspace phase invokes this helper
from the repository root:

```bash
python scripts/check_csharp_package.py
```

The helper packs `AnyInfer/AnyInfer.csproj` in Release configuration with symbols into
`.tmp-tests/nuget`, inspects its contents and dependencies, then restores, builds, and runs a
fresh external consumer against an isolated local feed. The C# proof version is `0.1.0-proof`
and is independent of the Python package version. To inspect the pack command directly, start in
`src/csharp` and run:

```bash
dotnet pack AnyInfer/AnyInfer.csproj -c Release -o ../../.tmp-tests/nuget -p:SourceRevisionId="$(git rev-parse HEAD)"
```

This validation never publishes to NuGet or attaches artifacts to a GitHub Release.

## Outputs and report boundary

Normal C# test runs do not write a canonical conformance report. Qualified report production is a
separate coordinator gate that requires a clean committed executable, release verification before
execution and publication, and the complete proof. It is not part of ordinary contributor testing
or CI package delivery.

The site build and release workflow do not provision .NET, publish NuGet content, or attach C#
proof output to a release. The native CI lane retains local prerelease package artifacts for its
own validation. The repository's [release guide](releasing.md) lists the artifacts that are
actually published.
