# C# Core-Generation Proof

This repository contains a bounded native C# proof under `src/csharp/`. It independently reads
the frozen shared `core-generation` corpus, executes the supported proof surface from fixture
inputs, and compares the resulting observations afterward. Fixture expectations are comparison
data; they do not drive native execution.

The proof exists to check the shared contract from another runtime. It does not provide a
supported AnyInfer C# SDK, a NuGet package, a production integration path, provider parity, a
sync API, or usage-accounting support. The supported runtime, public SDK, installation guidance,
and downloads remain Python surfaces.

## Run the proof locally

Use the SDK selected by `src/csharp/global.json`. Start in the C# root so the SDK resolver sees
that file:

```bash
cd src/csharp
dotnet --version
dotnet restore AnyInfer.sln
dotnet test AnyInfer.sln --no-restore
```

`workspace check` runs the same bounded phase after the repository's Python gates. The C# phase
records the selected SDK version, restores the solution, then runs the solution tests without a
second restore.

## Outputs and report boundary

Normal C# test runs do not publish a package or write a canonical conformance report. Qualified
report production is a separate coordinator gate that requires a clean committed executable,
release verification before execution and publication, and the complete proof. It is not part of
ordinary contributor testing or CI package delivery.

The site build and release workflow do not provision .NET, publish NuGet content, or attach C#
proof output to a release. The repository's [release guide](releasing.md) lists the artifacts that
are actually published.
