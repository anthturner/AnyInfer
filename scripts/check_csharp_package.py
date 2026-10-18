"""Pack and consume the local C# NuGet proof without touching user NuGet caches."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
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
SCHEMA_DEPENDENCIES = {
    "JsonSchema.Net": (
        "8.0.5",
        "EdVVe5ButZXkUIEgbah16Dm8soiwzs6OxsJBMTdoLNbjQPtkBAsH0uaF8BFnuYDWKDq9Zh6chUHSvbaSqq2VFA==",
    ),
    "JsonPointer.Net": (
        "6.0.1",
        "i7602ZUaqhhD3oapQvTjI1ZLbY2OhD71dt7JznEbtThyB56oU8SSpfj1ai8v1F4jvFl7k2BnYO1ULB1a5jPvUg==",
    ),
    "Json.More.Net": (
        "2.2.0",
        "8U88Wu/98+fPS1jlvCQWtADilO3zCi9To1wQvt/UXJK+i7f5hK8s31vhCSfI5U8Wr5aHyMh0h4WuCiRH48daeQ==",
    ),
    "Humanizer.Core": (
        "2.14.1",
        "yzqGU/HKNLZ9Uvr6kvSc3wYV/S5O/IvklIUW5WF7MuivGLY8wS5IZnLPkt7D1KW8Et2Enl0I3Lzg2vGWM24Xsw==",
    ),
}


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
    if dependencies is None or len(dependencies) != 1:
        raise RuntimeError("nuspec must declare the exact schema dependency")
    group = dependencies[0]
    if group.tag != namespace + "group" or group.get("targetFramework") != "net8.0":
        raise RuntimeError("nuspec dependency metadata is malformed")
    children = list(group)
    if len(children) != 1:
        raise RuntimeError("nuspec must declare exactly one direct dependency")
    dependency = children[0]
    if (
        dependency.tag != namespace + "dependency"
        or dependency.get("id") != "JsonSchema.Net"
        or dependency.get("version") != "[8.0.5]"
    ):
        raise RuntimeError("nuspec schema dependency is not the qualified exact range")


def _read_dependency_metadata(package: Path) -> tuple[str, str]:
    with zipfile.ZipFile(package) as archive:
        names = [entry for entry in archive.namelist() if entry.endswith(".nuspec")]
        if len(names) != 1:
            raise RuntimeError("dependency package must contain exactly one nuspec")
        root, namespace = _read_nuspec(archive, names[0])
        metadata = root.find(namespace + "metadata")
        if metadata is None:
            raise RuntimeError("dependency package nuspec metadata is missing")
        license_node = metadata.find(namespace + "license")
        if (
            license_node is None
            or license_node.get("type") != "expression"
            or license_node.text != "MIT"
        ):
            raise RuntimeError("dependency package license is not MIT")
        return _text(metadata, namespace, "id"), _text(metadata, namespace, "version")


def _schema_dependency_closure(assets: dict[str, object]) -> None:
    targets = assets.get("targets")
    if not isinstance(targets, dict):
        raise RuntimeError("root restore assets do not contain targets")
    candidates = [value for key, value in targets.items() if key.startswith("net8.0")]
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise RuntimeError("root restore assets must contain one net8.0 target")
    target = candidates[0]
    pending = ["JsonSchema.Net/8.0.5"]
    closure: set[str] = set()
    while pending:
        identity = pending.pop()
        if identity in closure:
            continue
        entry = target.get(identity)
        if not isinstance(entry, dict) or entry.get("type") != "package":
            raise RuntimeError(f"root restore is missing qualified dependency {identity}")
        closure.add(identity)
        dependencies = entry.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise RuntimeError(f"dependency metadata is malformed for {identity}")
        pending.extend(f"{name}/{version}" for name, version in dependencies.items())
    expected = {f"{name}/{version}" for name, (version, _) in SCHEMA_DEPENDENCIES.items()}
    if closure != expected:
        raise RuntimeError("resolved schema dependency graph is not the qualified exact graph")


def stage_schema_dependencies(feed: Path, assets_path: Path | None = None) -> None:
    """Copy only hash- and license-verified schema dependencies from the root restore."""
    assets_path = assets_path or PROJECT.parent / "obj" / "project.assets.json"
    try:
        assets = json.loads(assets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exception:
        raise RuntimeError("root restore provenance is unavailable") from exception
    if not isinstance(assets, dict):
        raise RuntimeError("root restore provenance is malformed")
    _schema_dependency_closure(assets)
    folders = assets.get("packageFolders")
    if not isinstance(folders, dict) or len(folders) != 1:
        raise RuntimeError("root restore must identify one controlled package folder")
    package_folder = Path(next(iter(folders))).resolve()
    feed.mkdir(parents=True, exist_ok=True)
    for name, (version, expected_hash) in SCHEMA_DEPENDENCIES.items():
        filename = f"{name.lower()}.{version}.nupkg"
        package = package_folder / name.lower() / version / filename
        if not package.is_file():
            raise RuntimeError(f"qualified dependency archive is missing: {name}/{version}")
        actual_hash = base64.b64encode(
            hashlib.sha512(package.read_bytes()).digest()
        ).decode("ascii")
        if actual_hash != expected_hash:
            raise RuntimeError(f"qualified dependency archive hash drifted: {name}/{version}")
        package_id, package_version = _read_dependency_metadata(package)
        if package_id != name or package_version != version:
            raise RuntimeError(f"qualified dependency archive metadata drifted: {name}/{version}")
        shutil.copy2(package, feed / filename)


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
        '''using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;

var factoryCalls = 0;
var descriptor = new ProviderDescriptor(
    "demo",
    "Demo",
    (_, _) =>
    {
        factoryCalls++;
        throw new InvalidOperationException("pure catalog queries must not construct an adapter");
    });
var registry = new ProviderRegistry([descriptor]);
var settings = ProviderSettings.Of("demo", alias: "demo-instance");
var catalog = new global::AnyInfer.Catalog.Catalog(
    aliases: new Dictionary<string, AliasEntry>
    {
        ["tier"] = new AliasEntry("tier", targets: new Dictionary<string, TargetEntry>
        {
            ["demo-instance"] = new TargetEntry("demo-instance", Model: "demo-model"),
        }),
    });
var pricingTable = new PricingTable(new Dictionary<string, IReadOnlyList<PricingEntry>>
{
    ["demo-instance"] =
    [
        new PricingEntry("demo-model", new Pricing(3.25m, 4.5m), "2026-10-17", "package proof"),
    ],
});
var overrides = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>
{
    ["demo-instance"] = new Dictionary<string, ModelCapabilities>
    {
        ["demo-model"] = new ModelCapabilities(
            pricing: new Sourced<Pricing>(new Pricing(5.75m, 6.25m), Provenance.Catalog)),
    },
};
{
    await using var client = new AsyncClient([settings], registry, catalog: catalog,
        pricingTable: pricingTable, capabilityOverrides: overrides);
    var resolved = client.Resolve("tier");
    var capability = client.Capabilities("tier");
    var capabilityPricing = capability.Pricing;
    var quoted = pricingTable.Lookup("demo-instance", "demo-model");
    if (resolved.ProviderId != "demo-instance"
        || resolved.Model != "demo-model"
        || resolved.ViaAlias != "tier"
        || !ReferenceEquals(client.Catalog, catalog)
        || capabilityPricing is null
        || capabilityPricing.Value.InputPer1M != 5.75m
        || capabilityPricing.Provenance != Provenance.Override
        || quoted is null
        || quoted.Value.InputPer1M != 3.25m
        || quoted.Provenance != Provenance.Catalog)
        throw new InvalidOperationException(
            "asynchronous pure catalog or capability query failed");
}
{
    using var client = new Client([settings], registry, catalog: catalog,
        pricingTable: pricingTable, capabilityOverrides: overrides);
    var resolved = client.Resolve("tier");
    var capability = client.Capabilities("tier");
    var capabilityPricing = capability.Pricing;
    if (resolved.ProviderId != "demo-instance"
        || resolved.ViaAlias != "tier"
        || !ReferenceEquals(client.Catalog, catalog)
        || capabilityPricing is null
        || capabilityPricing.Value.OutputPer1M != 6.25m
        || capabilityPricing.Provenance != Provenance.Override)
        throw new InvalidOperationException(
            "synchronous pure catalog or capability query failed");
}
if (factoryCalls != 0)
    throw new InvalidOperationException("pure catalog queries constructed an adapter");

var schema = SchemaSpec.FromJson("""
    {"$schema":"https://json-schema.org/draft/2020-12/schema","$defs":{"answer":{"type":"string"}},"type":"object","properties":{"answer":{"$ref":"#/$defs/answer"}},"required":["answer"]}
    """);
var validation = await SchemaValidator.ValidateAsync(
    JsonReader.Read("""{"answer":"schema"}"""), schema);
if (!validation.IsValid)
    throw new InvalidOperationException("standalone modern schema validation failed");

var schemaAdapter = new SchemaAdapter();
{
    await using var client = AsyncClient.FromAdapters(
        [new ProviderRegistration("schema-demo", schemaAdapter)]);
    var generation = await client.GenerateAsync(
        "Return a schema object.", target: "schema-demo:model", schema: schema);
    var typed = generation.DeserializeStructured<SchemaAnswer>();
    if (typed?.Answer != "schema" || schemaAdapter.SchemaRequests != 1)
        throw new InvalidOperationException(
            "client schema request or typed structured result failed");
}
if (schemaAdapter.DisposeCount != 1)
    throw new InvalidOperationException("schema adapter disposal failed");

var lifecycleAdapter = new LifecycleAdapter();
{
    await using var client = AsyncClient.FromAdapters(
        [new ProviderRegistration("lifecycle-demo", lifecycleAdapter)]);
    var models = await client.ModelsAsync("lifecycle-demo");
    var health = await client.HealthAsync("lifecycle-demo");
    var discoveredCapabilities = client.Capabilities("lifecycle-demo:lifecycle-model");
    if (models.Count != 1
        || models[0].Id != "lifecycle-model"
        || !health.Ok
        || discoveredCapabilities.ContextWindow?.Value != 2048
        || lifecycleAdapter.ModelCalls != 1
        || lifecycleAdapter.HealthCalls != 1)
        throw new InvalidOperationException("asynchronous public lifecycle query failed");
}
if (lifecycleAdapter.DisposeCount != 1)
    throw new InvalidOperationException("asynchronous lifecycle adapter disposal failed");

var syncLifecycleAdapter = new LifecycleAdapter();
{
    using var client = Client.FromAdapters(
        [new ProviderRegistration("sync-lifecycle-demo", syncLifecycleAdapter)]);
    var models = client.Models("sync-lifecycle-demo");
    var health = client.Health("sync-lifecycle-demo");
    var discoveredCapabilities = client.Capabilities("sync-lifecycle-demo:lifecycle-model");
    if (models.Count != 1
        || models[0].Id != "lifecycle-model"
        || !health.Ok
        || discoveredCapabilities.ContextWindow?.Value != 2048
        || syncLifecycleAdapter.ModelCalls != 1
        || syncLifecycleAdapter.HealthCalls != 1)
        throw new InvalidOperationException("synchronous public lifecycle query failed");
}
if (syncLifecycleAdapter.DisposeCount != 1)
    throw new InvalidOperationException("synchronous lifecycle adapter disposal failed");

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

var syncAdapter = new DemoAdapter();
{
    using var client = Client.FromAdapters([new ProviderRegistration("sync-demo", syncAdapter)]);
    var buffered = client.Generate("hello", target: "sync-demo:model");
    if (buffered.Text != "buffered")
        throw new InvalidOperationException("synchronous buffered result failed");
    using var stream = client.Stream("hello", target: "sync-demo:model");
    var text = "";
    foreach (var item in stream)
    {
        if (item is TextDelta delta) text += delta.Text;
    }
    if (text != "streamed" || stream.Result.Text != "streamed")
        throw new InvalidOperationException("synchronous stream result failed");
}
if (syncAdapter.DisposeCount != 1)
    throw new InvalidOperationException("synchronous adapter disposal failed");

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

sealed record SchemaAnswer(
    [property: System.Text.Json.Serialization.JsonPropertyName("answer")] string Answer);

sealed class SchemaAdapter : IProviderAdapter
{
    public int SchemaRequests { get; private set; }
    public int DisposeCount { get; private set; }

    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        [System.Runtime.CompilerServices.EnumeratorCancellation]
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (request.Schema is null || request.SchemaName != "response")
            throw new InvalidOperationException("SchemaSpec was not forwarded to the adapter.");
        SchemaRequests++;
        yield return new AdapterTextDelta("""{"answer":"schema"}""");
        yield return new AdapterFinal("stop");
        await Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        DisposeCount++;
        return ValueTask.CompletedTask;
    }
}

sealed class LifecycleAdapter : IProviderAdapter, IProviderLifecycle
{
    public int ModelCalls { get; private set; }
    public int HealthCalls { get; private set; }
    public int DisposeCount { get; private set; }

    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        [System.Runtime.CompilerServices.EnumeratorCancellation]
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        await Task.CompletedTask;
        yield break;
    }

    public ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ModelCalls++;
        IReadOnlyList<DiscoveredModel> models = Array.AsReadOnly(
        [
            new DiscoveredModel("lifecycle-model", new ModelCapabilities(
                contextWindow: new Sourced<int>(2048, Provenance.Discovered))),
        ]);
        return ValueTask.FromResult(models);
    }

    public ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        HealthCalls++;
        return ValueTask.FromResult(new Health(true));
    }

    public ValueTask DisposeAsync()
    {
        DisposeCount++;
        return ValueTask.CompletedTask;
    }
}
''', encoding="utf-8")


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
    stage_schema_dependencies(packages)
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
