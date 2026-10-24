# C# Core-Generation Proof

The native C# SDK under `src/csharp/` is an independent .NET 8 implementation in
development. Its conformance driver reads the frozen shared `core-generation` corpus, runs
fixtures against the SDK, and compares observations; expectations do not drive execution.
Ordinary SDK calls use public requests and execute natively without reading the corpus. The
SDK also consumes shared declarative assets. It is locally packaged as `0.1.0-proof`, not published to NuGet.
Python remains the supported published SDK, and C# does not claim full parity or provider
invoice/all-wire accounting. See the [foundation capability map](../concepts/foundation.md).

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
