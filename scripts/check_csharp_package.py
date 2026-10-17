"""Pack and consume the local C# NuGet proof without touching user NuGet caches."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
CSHARP_ROOT = ROOT / "src" / "csharp"
PROJECT = CSHARP_ROOT / "AnyInfer" / "AnyInfer.csproj"
PROPS = CSHARP_ROOT / "Directory.Build.props"
PACKAGE_ID = "AnyInfer"
NUSPEC_NAMESPACES = {
    "{http://schemas.microsoft.com/packaging/2012/06/nuspec.xsd}",
    "{http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd}",
}
CORE_PROPERTIES = re.compile(r"package/services/metadata/core-properties/[0-9a-fA-F-]+\.psmdcp")


def run(command: list[str], *, cwd: Path) -> None:
    """Run a checked subprocess and echo its exact command."""
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def package_version() -> str:
    """Read the single C# package version from the shared props file."""
    root = ElementTree.parse(PROPS).getroot()
    values = [node.text for node in root.findall(".//Version") if node.text]
    if len(values) != 1:
        raise RuntimeError("Directory.Build.props must contain exactly one Version value")
    return values[0]


def git_revision() -> str:
    """Return the current full lowercase repository revision."""
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise RuntimeError("git HEAD is not a lowercase 40-character revision")
    return revision


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the bounded package-checker command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp-tests" / "nuget")
    return parser.parse_args(argv)


def package_paths(output: Path, version: str) -> tuple[Path, Path]:
    """Require the fresh pack directory to contain one package pair."""
    packages = sorted(output.glob("*.nupkg"))
    symbols = sorted(output.glob("*.snupkg"))
    package = output / f"{PACKAGE_ID}.{version}.nupkg"
    symbol = output / f"{PACKAGE_ID}.{version}.snupkg"
    if packages != [package] or symbols != [symbol]:
        raise RuntimeError("pack did not produce exactly the expected package and symbols package")
    return package, symbol


def _names(archive: zipfile.ZipFile) -> set[str]:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise RuntimeError("NuGet archive contains duplicate entries")
    return set(names)


def _container_records(names: set[str], *, nuspec: str) -> set[str]:
    expected = {"[Content_Types].xml", "_rels/.rels", nuspec}
    core = [name for name in names if CORE_PROPERTIES.fullmatch(name)]
    if len(core) != 1:
        raise RuntimeError("NuGet archive has invalid core-properties records")
    return expected | set(core)


def _read_nuspec(archive: zipfile.ZipFile, name: str) -> tuple[ElementTree.Element, str]:
    root = ElementTree.fromstring(archive.read(name))
    for namespace in NUSPEC_NAMESPACES:
        if root.tag == namespace + "package":
            return root, namespace
    raise RuntimeError("nuspec namespace is unsupported")


def _text(metadata: ElementTree.Element, namespace: str, name: str) -> str:
    value = metadata.findtext(namespace + name)
    if value is None:
        raise RuntimeError(f"nuspec metadata is missing {name}")
    return value


def _validate_dependencies(metadata: ElementTree.Element, namespace: str) -> None:
    dependencies = metadata.find(namespace + "dependencies")
    if dependencies is None:
        return
    for child in dependencies:
        if (
            child.tag != namespace + "group"
            or child.get("targetFramework") not in (None, "net8.0")
        ):
            raise RuntimeError("nuspec dependency metadata is malformed")
        if list(child):
            raise RuntimeError("core package must not declare runtime dependencies")


def validate_package(
    package: Path,
    symbols: Path,
    revision: str,
    version: str | None = None,
) -> None:
    """Validate exact package containers, payloads, and bounded nuspec metadata."""
    version = package_version() if version is None else version
    nuspec_name = f"{PACKAGE_ID}.nuspec"
    with zipfile.ZipFile(package) as archive:
        names = _names(archive)
        allowed = _container_records(names, nuspec=nuspec_name) | {
            "lib/net8.0/AnyInfer.dll", "README.md", "LICENSE",
        }
        if names != allowed:
            raise RuntimeError("package payload contains an unexpected member")
        root, namespace = _read_nuspec(archive, nuspec_name)
        metadata = root.find(namespace + "metadata")
        if metadata is None:
            raise RuntimeError("nuspec metadata is missing")
        expected = {
            "id": PACKAGE_ID,
            "version": version,
            "authors": "Anthony Turner",
            "description": (
                "A bounded .NET 8 inference core for application-owned provider adapters."
            ),
            "readme": "README.md",
        }
        for name, value in expected.items():
            if _text(metadata, namespace, name) != value:
                raise RuntimeError(f"nuspec {name} is not the expected value")
        license_node = metadata.find(namespace + "license")
        if (
            license_node is None
            or license_node.get("type") != "expression"
            or license_node.text != "MIT"
        ):
            raise RuntimeError("nuspec license is not the expected expression")
        repository = metadata.find(namespace + "repository")
        if (
            repository is None
            or repository.get("type") != "git"
            or repository.get("url") != "https://github.com/anthturner/AnyInfer"
            or repository.get("commit") != revision
        ):
            raise RuntimeError("nuspec repository metadata is not bound to the current revision")
        _validate_dependencies(metadata, namespace)

    with zipfile.ZipFile(symbols) as archive:
        names = _names(archive)
        allowed = _container_records(names, nuspec=nuspec_name) | {"lib/net8.0/AnyInfer.pdb"}
        if names != allowed:
            raise RuntimeError("symbols package contains an unexpected member")


def write_consumer(consumer: Path, feed: Path, cache: Path, version: str) -> None:
    """Write an external net8 consumer pinned to the fresh local feed."""
    consumer.mkdir(parents=True)
    configuration = ElementTree.Element("configuration")
    sources = ElementTree.SubElement(configuration, "packageSources")
    ElementTree.SubElement(sources, "clear")
    ElementTree.SubElement(sources, "add", key="local", value=str(feed))
    config = ElementTree.SubElement(configuration, "config")
    ElementTree.SubElement(config, "add", key="globalPackagesFolder", value=str(cache))
    ElementTree.ElementTree(configuration).write(
        consumer / "NuGet.Config", encoding="utf-8", xml_declaration=True
    )
    (consumer / "Consumer.csproj").write_text(
        f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings></PropertyGroup>
  <ItemGroup><PackageReference Include="AnyInfer" Version="{version}" /></ItemGroup>
</Project>
''', encoding="utf-8")
    (consumer / "Program.cs").write_text(
        """using AnyInfer;
using AnyInfer.Providers;

var adapter = new DemoAdapter();
{
    await using var client = AsyncClient.FromAdapters([new ProviderRegistration("demo", adapter)]);
    var messages = new[] { new Message("user", [new Text("hello")]) };
    var buffered = await client.GenerateAsync(messages, target: "demo:model");
    if (buffered.Text != "buffered")
        throw new InvalidOperationException("buffered result failed");
    await using var stream = client.StreamAsync("hello", target: "demo:model");
    var text = "";
    await foreach (var item in stream)
    {
        if (item is TextDelta delta) text += delta.Text;
    }
    if (text != "streamed" || stream.Result.Text != "streamed")
        throw new InvalidOperationException("stream result failed");
}
if (adapter.DisposeCount != 1)
    throw new InvalidOperationException("adapter disposal failed");

sealed class DemoAdapter : IProviderAdapter
{
    private int _calls;
    public int DisposeCount { get; private set; }
    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        [System.Runtime.CompilerServices.EnumeratorCancellation]
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        yield return new AdapterTextDelta(_calls++ == 0 ? "buffered" : "streamed");
        yield return new AdapterFinal("stop");
        await Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        DisposeCount++;
        return ValueTask.CompletedTask;
    }
}
""", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Pack, inspect, and consume a package from an isolated local feed."""
    options = parse_args(sys.argv[1:] if argv is None else argv)
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    version = package_version()
    revision = git_revision()
    run_root = Path(tempfile.mkdtemp(prefix="run-", dir=output))
    shutil.copy2(CSHARP_ROOT / "global.json", run_root / "global.json")
    packages = run_root / "packages"
    consumer = run_root / "consumer"
    cache = run_root / "nuget-cache"
    run(
        [
            "dotnet",
            "pack",
            str(PROJECT),
            "-c",
            "Release",
            "-o",
            str(packages),
            f"-p:SourceRevisionId={revision}",
        ],
        cwd=CSHARP_ROOT,
    )
    package, symbols = package_paths(packages, version)
    validate_package(package, symbols, revision, version)
    write_consumer(consumer, packages, cache, version)
    run(
        ["dotnet", "restore", "--configfile", "NuGet.Config", "--packages", str(cache)],
        cwd=consumer,
    )
    run(["dotnet", "build", "--no-restore"], cwd=consumer)
    run(["dotnet", "run", "--no-build", "--no-restore"], cwd=consumer)
    for artifact in (package, symbols):
        shutil.copy2(artifact, output / artifact.name)
    print(f"validated {package.name} and {symbols.name} in {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exception:
        print(f"error: {exception}", file=sys.stderr)
        raise SystemExit(1) from None
