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
QUALIFIED_DEPENDENCIES = {
    "JsonSchema.Net": (
        "8.0.5",
        "EdVVe5ButZXkUIEgbah16Dm8soiwzs6OxsJBMTdoLNbjQPtkBAsH0uaF8BFnuYDWKDq9Zh6chUHSvbaSqq2VFA==",
        "MIT",
    ),
    "JsonPointer.Net": (
        "6.0.1",
        "i7602ZUaqhhD3oapQvTjI1ZLbY2OhD71dt7JznEbtThyB56oU8SSpfj1ai8v1F4jvFl7k2BnYO1ULB1a5jPvUg==",
        "MIT",
    ),
    "Json.More.Net": (
        "2.2.0",
        "8U88Wu/98+fPS1jlvCQWtADilO3zCi9To1wQvt/UXJK+i7f5hK8s31vhCSfI5U8Wr5aHyMh0h4WuCiRH48daeQ==",
        "MIT",
    ),
    "Humanizer.Core": (
        "2.14.1",
        "yzqGU/HKNLZ9Uvr6kvSc3wYV/S5O/IvklIUW5WF7MuivGLY8wS5IZnLPkt7D1KW8Et2Enl0I3Lzg2vGWM24Xsw==",
        "MIT",
    ),
    "PeterO.Numbers": (
        "1.8.2",
        "Rc5avnwd9v5DuyBrLi8J87vV9dyJ/BdgSOhNfLzxzjYGEO0Gc/X+AzWwty3VxNOnjEjk7r6NZBt0MSR1sdhHRg==",
        "CC0-1.0",
    ),
}

DIRECT_DEPENDENCIES = {"JsonSchema.Net": "8.0.5", "PeterO.Numbers": "1.8.2"}


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
        raise RuntimeError("nuspec must declare the exact qualified direct dependency set")
    group = dependencies[0]
    if group.tag != namespace + "group" or group.get("targetFramework") != "net8.0":
        raise RuntimeError("nuspec dependency metadata is malformed")
    children = list(group)
    declared = {
        (child.get("id"), child.get("version"))
        for child in children
        if child.tag == namespace + "dependency"
    }
    expected = {(name, f"[{version}]") for name, version in DIRECT_DEPENDENCIES.items()}
    if len(children) != len(expected) or declared != expected:
        raise RuntimeError("nuspec dependency declarations are not the qualified exact ranges")


def _read_dependency_metadata(package: Path, expected_license: str) -> tuple[str, str]:
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
            or license_node.text != expected_license
        ):
            raise RuntimeError("dependency package license is not qualified")
        return _text(metadata, namespace, "id"), _text(metadata, namespace, "version")


def _schema_dependency_closure(assets: dict[str, object]) -> None:
    targets = assets.get("targets")
    if not isinstance(targets, dict):
        raise RuntimeError("root restore assets do not contain targets")
    candidates = [value for key, value in targets.items() if key.startswith("net8.0")]
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise RuntimeError("root restore assets must contain one net8.0 target")
    target = candidates[0]
    pending = [f"{name}/{version}" for name, version in DIRECT_DEPENDENCIES.items()]
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
    expected = {f"{name}/{version}" for name, (version, _, _) in QUALIFIED_DEPENDENCIES.items()}
    if closure != expected:
        raise RuntimeError("resolved dependency graph is not the qualified exact graph")


def stage_schema_dependencies(feed: Path, assets_path: Path | None = None) -> None:
    """Copy only hash- and license-verified qualified dependencies from the root restore."""
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
    for name, (version, expected_hash, expected_license) in QUALIFIED_DEPENDENCIES.items():
        filename = f"{name.lower()}.{version}.nupkg"
        package = package_folder / name.lower() / version / filename
        if not package.is_file():
            raise RuntimeError(f"qualified dependency archive is missing: {name}/{version}")
        actual_hash = base64.b64encode(hashlib.sha512(package.read_bytes()).digest()).decode(
            "ascii"
        )
        if actual_hash != expected_hash:
            raise RuntimeError(f"qualified dependency archive hash drifted: {name}/{version}")
        package_id, package_version = _read_dependency_metadata(package, expected_license)
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
            "lib/net8.0/AnyInfer.dll",
            "README.md",
            "LICENSE",
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
''',
        encoding="utf-8",
    )
    (consumer / "Program.cs").write_text(
        '''using System.Net;
using System.Numerics;
using System.Text;
using System.Text.Json;
using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Config;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Providers;
using AnyInfer.Routing;
using AnyInfer.Schema;
using PeterO.Numbers;
using JsonProperty = AnyInfer.Json.JsonProperty;

var factoryCalls = 0;
var descriptor = new ProviderDescriptor(
    "demo",
    "Demo",
    (_, _) =>
    {
        factoryCalls++;
        throw new InvalidOperationException("pure catalog queries must not construct an adapter");
    });
var availableInventoryDescriptor = new ProviderDescriptor(
    "available-inventory",
    "Available inventory",
    (_, _) => throw new InvalidOperationException("metadata must not construct an adapter"),
    modelInventory: ModelInventoryKind.Available);
var installedInventoryDescriptor = new ProviderDescriptor(
    "installed-inventory",
    "Installed inventory",
    (_, _) => throw new InvalidOperationException("metadata must not construct an adapter"),
    modelInventory: ModelInventoryKind.Installed);
var connectionDisabledDescriptor = new ProviderDescriptor(
    "connection-disabled",
    "Connection disabled",
    (_, _) => throw new InvalidOperationException("metadata must not construct an adapter"),
    honorsConnectionSettings: false);
if (descriptor.ModelInventory != ModelInventoryKind.Served
    || availableInventoryDescriptor.ModelInventory != ModelInventoryKind.Available
    || installedInventoryDescriptor.ModelInventory != ModelInventoryKind.Installed
    || !descriptor.HonorsConnectionSettings
    || connectionDisabledDescriptor.HonorsConnectionSettings)
    throw new InvalidOperationException("public model-inventory metadata failed");
var registry = new ProviderRegistry([descriptor]);
var parsedProxyLiteral = "  https://user%20name:shortpw@Proxy.Example:443/  ";
var parsedProxy = ProviderProxy.Parse(parsedProxyLiteral);
var encryptedCertificate = ClientCertificate.FromEncryptedPemPair(
    " non-existent-cert.pem ", " non-existent-key.pem ", "shortpw");
var pairCertificate = ClientCertificate.FromPemPair(" pair-cert.pem ", " pair-key.pem ");
var settings = ProviderSettings.Of(
    "demo",
    alias: "demo-instance",
    proxy: parsedProxy,
    verify: TlsVerification.FromPemBundle(" non-existent-ca.pem "),
    clientCertificate: encryptedCertificate);
var connectionConfig = new ProviderConfig(settings, "demo", null);
var connectionDump = new AnyInferConfig([settings]).Dumps();
var roundTrippedConnection = AnyInferConfig.Loads(connectionDump, registry).Providers.Single();
if (parsedProxy.Address.UserInfo.Length != 0
    || parsedProxy.UserName != "user name"
    || parsedProxy.Password != "shortpw"
    || settings.Proxy != parsedProxy
    || settings.Verify?.PemBundlePath != "non-existent-ca.pem"
    || settings.ClientCertificate?.CertificatePath != " non-existent-cert.pem "
    || settings.ClientCertificate?.PrivateKeyPath != " non-existent-key.pem "
    || settings.ClientCertificate?.Password != "shortpw"
    || pairCertificate.CertificatePath != " pair-cert.pem "
    || pairCertificate.PrivateKeyPath != " pair-key.pem "
    || connectionConfig.Proxy != parsedProxy
    || connectionConfig.Verify != settings.Verify
    || connectionConfig.ClientCertificate != encryptedCertificate
    || roundTrippedConnection.Proxy?.Address.Host != "proxy.example"
    || roundTrippedConnection.ClientCertificate?.Password != "shortpw"
    || !connectionDump.Contains(
        "https://user%20name:shortpw@Proxy.Example:443/", StringComparison.Ordinal)
    || !connectionDump.Contains("non-existent-key.pem", StringComparison.Ordinal)
    || parsedProxy.ToString().Contains("shortpw", StringComparison.Ordinal)
    || encryptedCertificate.ToString().Contains("shortpw", StringComparison.Ordinal)
    || connectionConfig.ToString().Contains("shortpw", StringComparison.Ordinal))
    throw new InvalidOperationException("public connection configuration projection failed");
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
        new PricingEntry(
            "demo-model",
            new Pricing(EDecimal.FromString("3.25"), EDecimal.FromString("4.5")),
            "2026-10-17",
            "package proof"),
    ],
});
var overrides = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>
{
    ["demo-instance"] = new Dictionary<string, ModelCapabilities>
    {
        ["demo-model"] = new ModelCapabilities(
            pricing: new Sourced<Pricing>(
                new Pricing(EDecimal.FromString("5.75"), EDecimal.FromString("6.25")),
                Provenance.Catalog)),
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
        || capabilityPricing.Value.InputPer1M.CompareTo(EDecimal.FromString("5.75")) != 0
        || capabilityPricing.Provenance != Provenance.Override
        || quoted is null
        || quoted.Value.InputPer1M.CompareTo(EDecimal.FromString("3.25")) != 0
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
        || capabilityPricing.Value.OutputPer1M.CompareTo(EDecimal.FromString("6.25")) != 0
        || capabilityPricing.Provenance != Provenance.Override)
        throw new InvalidOperationException(
            "synchronous pure catalog or capability query failed");
}
if (factoryCalls != 0)
    throw new InvalidOperationException("pure catalog queries constructed an adapter");

var cerebrasHandler = new CerebrasHandler();
var cerebrasSettings = ProviderSettings.Of(
    "cerebras", apiKey: "offline-cerebras-key", transport: cerebrasHandler);
{
    await using var client = new AsyncClient([cerebrasSettings]);
    var generated = await client.GenerateAsync(
        "package Cerebras witness", target: "cerebras:gpt-oss-120b");
    if (generated.Text != "package cerebras"
        || generated.Usage is not { InputTokens: 1, OutputTokens: 1, TotalTokens: 2 })
        throw new InvalidOperationException("default Cerebras registration witness failed");
}
if (cerebrasHandler.RequestCount != 1 || cerebrasHandler.DisposeCount != 1)
    throw new InvalidOperationException("default Cerebras transport ownership failed");

var hyperbolicHandler = new HyperbolicHandler();
var hyperbolicSettings = ProviderSettings.Of(
    "hyperbolic", apiKey: "offline-hyperbolic-key", transport: hyperbolicHandler);
{
    await using var client = new AsyncClient([hyperbolicSettings]);
    var generated = await client.GenerateAsync(
        "package Hyperbolic witness", target: "hyperbolic:glm-5.3-flash");
    if (generated.Text != "package hyperbolic"
        || generated.Usage is not { InputTokens: 1, OutputTokens: 1, TotalTokens: 2 })
        throw new InvalidOperationException("default Hyperbolic registration witness failed");
}
if (hyperbolicHandler.RequestCount != 1 || hyperbolicHandler.DisposeCount != 1)
    throw new InvalidOperationException("default Hyperbolic transport ownership failed");

var teiEmbedHandler = new TeiHandler(reranker: false);
var teiRerankHandler = new TeiHandler(reranker: true);
var teiEmbedSettings = ProviderSettings.Of(
    "tei", "https://tei-embed.offline/v1", transport: teiEmbedHandler, alias: "tei-embed");
var teiRerankSettings = ProviderSettings.Of(
    "tei", "https://tei-rerank.offline/v1", transport: teiRerankHandler, alias: "tei-rerank");
{
    await using var client = new AsyncClient(
        [teiEmbedSettings, teiRerankSettings], manifests: true);
    var embedded = await client.EmbedAsync(
        ["first", "second"], target: "tei-embed:embed-model", retainRaw: true, manifest: true);
    var reranked = await client.RerankAsync(
        "find first",
        [new RerankDocument("first-id", "first"), new RerankDocument("second-id", "second")],
        target: "tei-rerank:rerank-model", returnDocuments: true, retainRaw: true, manifest: true);
    if (embedded.Vectors.Count != 2
        || embedded.Vectors[0].Values[0] != 0.1
        || embedded.Usage.InputTokens is not null
        || embedded.Usage.OutputTokens is not null
        || embedded.Raw is null
        || embedded.Manifest is not { Complete: true, Operation: "embedding", Payloads: null }
        || reranked.Items.Count != 2
        || reranked.Items[0] is not { Index: 0, DocumentId: "first-id", Score: 0.9 }
        || reranked.Usage.InputTokens is not null
        || reranked.Usage.OutputTokens is not null
        || reranked.Raw is null
        || reranked.Manifest is not { Complete: true, Operation: "rerank", Payloads: null })
        throw new InvalidOperationException("default TEI builtin retrieval witness failed");
}
if (teiEmbedHandler.RequestCount != 1 || teiRerankHandler.RequestCount != 1
    || teiEmbedHandler.DisposeCount != 1 || teiRerankHandler.DisposeCount != 1)
    throw new InvalidOperationException("default TEI builtin transport ownership failed");

var voyageAsyncHandler = new VoyageHandler();
var voyageAsyncSettings = ProviderSettings.Of(
    "voyage", apiKey: "offline-voyage-key", transport: voyageAsyncHandler,
    alias: "voyage-retrieval");
{
    await using var client = new AsyncClient([voyageAsyncSettings], manifests: true);
    var embedded = await client.EmbedAsync(
        ["first", "second"], target: "voyage-retrieval:voyage-3.5-lite",
        inputType: EmbeddingInputIntent.Document, retainRaw: true, manifest: true);
    var reranked = await client.RerankAsync(
        "find first",
        [new RerankDocument("first-id", "first"), new RerankDocument("second-id", "second")],
        target: "voyage-retrieval:rerank-2.5", topN: 1, returnDocuments: true,
        retainRaw: true, manifest: true);
    if (embedded.Vectors.Count != 2
        || !embedded.Vectors[0].Values.SequenceEqual([0.1, 0.2])
        || embedded.Usage.InputTokens is not null
        || embedded.Usage.OutputTokens is not null
        || embedded.Usage.TotalTokens != 7
        || embedded.Raw is null
        || embedded.Manifest is not { Complete: true, Operation: "embedding", Payloads: null }
        || reranked.Items.Count != 1
        || reranked.Items[0] is not { Index: 1, DocumentId: "second-id", Score: 0.1 }
        || reranked.Usage.InputTokens is not null
        || reranked.Usage.OutputTokens is not null
        || reranked.Usage.TotalTokens != 7
        || reranked.Raw is null
        || reranked.Manifest is not { Complete: true, Operation: "rerank", Payloads: null })
        throw new InvalidOperationException("default Voyage builtin retrieval witness failed");
}
if (voyageAsyncHandler.RequestCount != 2 || voyageAsyncHandler.DisposeCount != 1)
    throw new InvalidOperationException("default Voyage async builtin transport ownership failed");

var voyageSyncHandler = new VoyageHandler();
var voyageSyncSettings = ProviderSettings.Of(
    "voyage", apiKey: "offline-voyage-key", transport: voyageSyncHandler,
    alias: "voyage-retrieval");
{
    using var client = new Client([voyageSyncSettings], manifests: true);
    var embedded = client.Embed(
        ["find first"], target: "voyage-retrieval:voyage-3.5-lite",
        inputType: EmbeddingInputIntent.Query, retainRaw: true, manifest: true);
    var reranked = client.Rerank(
        "find first",
        [new RerankDocument("first-id", "first"), new RerankDocument("second-id", "second")],
        target: "voyage-retrieval:rerank-2.5", topN: 1, returnDocuments: true,
        retainRaw: true, manifest: true);
    if (embedded.Vectors.Count != 1
        || !embedded.Vectors[0].Values.SequenceEqual([0.5, 0.6])
        || embedded.Usage.InputTokens is not null
        || embedded.Usage.OutputTokens is not null
        || embedded.Usage.TotalTokens != 7
        || embedded.Raw is null
        || reranked.Items.Count != 1
        || reranked.Items[0] is not { Index: 1, DocumentId: "second-id", Score: 0.1 }
        || reranked.Usage.InputTokens is not null
        || reranked.Usage.OutputTokens is not null
        || reranked.Usage.TotalTokens != 7
        || reranked.Raw is null)
        throw new InvalidOperationException(
            "default Voyage sync builtin retrieval witness failed");
}
if (voyageSyncHandler.RequestCount != 2 || voyageSyncHandler.DisposeCount != 1)
    throw new InvalidOperationException("default Voyage sync builtin transport ownership failed");

var jinaHandler = new JinaHandler();
var jinaSettings = ProviderSettings.Of("jina", apiKey: "offline-jina-key", transport: jinaHandler,
    alias: "jina-retrieval");
{
    await using var client = new AsyncClient([jinaSettings], manifests: true);
    var embedded = await client.EmbedAsync(
        ["first", "second"],
        target: "jina-retrieval:jina-embeddings-v5-text-small",
        inputType: EmbeddingInputIntent.Document,
        retainRaw: true, manifest: true);
    var reranked = await client.RerankAsync("find first",
        [new RerankDocument("first-id", "first"), new RerankDocument("second-id", "second")],
        target: "jina-retrieval:jina-reranker-v3", topN: 1,
        returnDocuments: true, retainRaw: true, manifest: true);
    if (embedded.Vectors.Count != 2 || !embedded.Vectors[0].Values.SequenceEqual([0.1, 0.2])
        || embedded.Usage.InputTokens is not null
        || embedded.Usage.OutputTokens is not null
        || embedded.Usage.TotalTokens != 7
        || embedded.Raw is null
        || !HasPromptTokens(embedded.Raw)
        || embedded.Manifest is not { Complete: true, Operation: "embedding", Payloads: null }
        || reranked.Items.Count != 1
        || reranked.Items[0] is not { Index: 1, DocumentId: "second-id", Score: 0.1 }
        || reranked.Usage.InputTokens is not null
        || reranked.Usage.OutputTokens is not null
        || reranked.Usage.TotalTokens != 7
        || reranked.Raw is null
        || !HasPromptTokens(reranked.Raw)
        || reranked.Manifest is not { Complete: true, Operation: "rerank", Payloads: null })
        throw new InvalidOperationException("default Jina builtin retrieval witness failed");
}
if (jinaHandler.RequestCount != 2 || jinaHandler.DisposeCount != 1)
    throw new InvalidOperationException("default Jina builtin transport ownership failed");

var trustedAccounting = new ModelCapabilities(
    pricing: new Sourced<Pricing>(
        new Pricing(EDecimal.FromString("2"), EDecimal.FromString("4")),
        Provenance.Catalog));
var defaultAccounting = new ModelCapabilities(
    pricing: new Sourced<Pricing>(
        new Pricing(EDecimal.FromString("2"), EDecimal.FromString("4")),
        Provenance.Default));
var freeAccounting = new ModelCapabilities(
    pricing: new Sourced<Pricing>(
        new Pricing(EDecimal.Zero, EDecimal.Zero),
        Provenance.Catalog));
var quotedUsage = new Usage(InputTokens: 1000, OutputTokens: 500);
var pricedUsage = PricingCalculator.WithCost(quotedUsage, trustedAccounting);
var unknownCost = PricingCalculator.ComputeCost(quotedUsage, defaultAccounting);
var freeUsage = PricingCalculator.WithCost(quotedUsage, freeAccounting);
if (pricedUsage.CostUsd?.CompareTo(EDecimal.FromString("0.004")) != 0
    || unknownCost is not null
    || freeUsage.CostUsd?.CompareTo(EDecimal.Zero) != 0)
    throw new InvalidOperationException("public pricing provenance behavior failed");

var accountingAdapter = new AccountingAdapter();
var accountingLedger = new SpendLedger();
{
    await using var client = AsyncClient.FromAdapters(
        [new ProviderRegistration("accounting-demo", accountingAdapter)],
        ledger: accountingLedger);
    var budget = client.Budget("accounting", "accounting-demo:model", outputReserveTokens: 32);
    var generation = await client.GenerateAsync("accounting", target: "accounting-demo:model");
    var spend = client.Spend();
    if (budget.OutputReserveTokens != 32
        || generation.Usage?.InputTokens != 1
        || spend.Requests != 1
        || spend.UnknownRequests != 1)
        throw new InvalidOperationException("public client budget or caller-owned ledger failed");
}
if (accountingAdapter.DisposeCount != 1)
    throw new InvalidOperationException("accounting adapter disposal failed");

var policyAdapter = new PolicyAdapter();
var policyLedger = new SpendLedger();
var rawTool = new ToolSpec(
    "lookup_weather",
    "Reads a weather observation.",
    new JsonObject([
        new JsonProperty("type", new JsonString("object")),
        new JsonProperty("properties", new JsonObject([
            new JsonProperty("city", new JsonObject([
                new JsonProperty("type", new JsonString("string")),
            ])),
        ])),
    ]));
var policyRequest = new GenerationRequest(
    [
        Message.System("Answer concisely."),
        new Message("assistant", [new ToolCall("call-1", rawTool.Name, new JsonObject([
            new JsonProperty("city", new JsonString("Boston")),
        ]))]),
        new Message("tool", [new ToolResult("call-1", "clear")]),
        Message.User("weather"),
    ],
    new Route(["policy-demo:model"], contextWindowTargets: ["policy-demo:model"]),
    stream: true,
    tools: [rawTool],
    cache: new CachePolicy(CacheMode.Off));
{
    await using var client = AsyncClient.FromAdapters(
        [new ProviderRegistration("policy-demo", policyAdapter)],
        ledger: policyLedger,
        spendPolicy: new SpendPolicy(),
        cachePolicy: new CachePolicy());
    await using var stream = client.StreamAsync(policyRequest);
    ToolCallDelta? delta = null;
    await foreach (var item in stream)
    {
        if (item is ToolCallDelta observed)
            delta = observed;
    }
    var generation = stream.Result;
    var captured = policyAdapter.Captured
        ?? throw new InvalidOperationException("policy adapter did not receive a wire request");
    var outboundCall = captured.Messages[1].Content.Single() as ToolCall;
    var outboundResult = captured.Messages[2].Content.Single() as ToolResult;
    var inboundCall = generation.ToolCalls.Single();
    const string expectedArguments = """{"city":"Boston"}""";
    var capturedTool = captured.Tools.Single();
    if (generation.Text != ""
        || generation.FinishReason != "tool_calls"
        || inboundCall.Id != "inbound-call"
        || inboundCall.Name != "lookup_weather"
        || !inboundCall.Arguments.TryGetValue("city", out var inboundCity)
        || inboundCity is not JsonString { Value: "Boston" }
        || delta is not
        {
            Index: 0,
            CallId: "inbound-call",
            Name: "lookup_weather",
            ArgumentsFragment: expectedArguments,
        }
        || captured.Messages.Count != 4
        || outboundCall is null
        || outboundCall.Id != "call-1"
        || outboundCall.Name != "lookup_weather"
        || !outboundCall.Arguments.TryGetValue("city", out var outboundCity)
        || outboundCity is not JsonString { Value: "Boston" }
        || outboundResult is null
        || outboundResult.CallId != "call-1"
        || outboundResult.Content != "clear"
        || outboundResult.IsError
        || client.Spend().Requests != 1
        || policyRequest.Route.ContextWindowTargets.Count != 1
        || policyRequest.Cache?.Mode != CacheMode.Off
        || rawTool.Annotations.Stated
        || capturedTool.Name != "lookup_weather"
        || !capturedTool.Parameters.TryGetValue("type", out var parameterType)
        || parameterType is not JsonString { Value: "object" }
        || !capturedTool.Parameters.TryGetValue("properties", out var parameterProperties)
        || parameterProperties is not JsonObject properties
        || !properties.TryGetValue("city", out var citySchema)
        || citySchema is not JsonObject city
        || !city.TryGetValue("type", out var cityType)
        || cityType is not JsonString { Value: "string" })
        throw new InvalidOperationException("public request policy or raw tool values failed");
}
if (policyAdapter.DisposeCount != 1)
    throw new InvalidOperationException("policy adapter disposal failed");

var policyConfig = new AnyInferConfig(
    [ProviderSettings.Of("policy-config")],
    cache: new CachePolicy(CacheMode.Off));
var configuredPolicyAdapter = new DemoAdapter();
var configuredPolicyRegistry = new ProviderRegistry([
    new ProviderDescriptor(
        "policy-config",
        "Policy config",
        (_, _) => ValueTask.FromResult<IAsyncDisposable>(configuredPolicyAdapter)),
]);
{
    await using var client = AsyncClient.FromConfig(
        policyConfig,
        configuredPolicyRegistry,
        cachePolicy: new CachePolicy(CacheMode.Off));
    var configured = await client.GenerateAsync("configured", target: "policy-config:model");
    if (configured.Text != "buffered" || policyConfig.Cache?.Mode != CacheMode.Off)
        throw new InvalidOperationException("public configured policy client failed");
}
if (configuredPolicyAdapter.DisposeCount != 1)
    throw new InvalidOperationException("configured policy adapter disposal failed");

var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false));
await using (var firstLease = await limiter.AcquireAsync())
{
}
await using (var secondLease = await limiter.AcquireAsync())
{
}

var setup = new ProviderSetupSpec(
    fields:
    [
        new SetupField("base_url", "API base URL", kind: "endpoint", required: true),
        new SetupField("api_key", "API key", kind: "secret", envVar: "ANYINFER_API_KEY"),
        new SetupField("access_token", "Access token", kind: "secret"),
    ],
    hostShorthand: new HostShorthand("https", 443),
    anyOf: [["api_key", "access_token"]],
    requirementNote: "Supply one credential.");
if (setup.HostShorthand?.Expand("offline.example") != "https://offline.example:443"
    || setup.AnyOf.Count != 1
    || setup.UnsatisfiedGroups(
        new Dictionary<string, string> { ["api_key"] = "configured" }).Count != 0)
    throw new InvalidOperationException("public setup metadata snapshot failed");

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

var probeAdapter = new ProbeAdapter();
{
    await using var client = AsyncClient.FromAdapters(
        [new ProviderRegistration("probe-demo", probeAdapter)]);
    var report = await client.ProbeAsync("probe-demo:model");
    var stored = client.Capabilities("probe-demo:model");
    if (report.Requests != 4
        || report.Probes.Count != 4
        || report.Probes.Any(static probe => probe.Outcome != ProbeOutcome.Supported)
        || report.Capabilities?.Features?.Provenance != Provenance.Probed
        || stored.Features?.Provenance != Provenance.Probed
        || probeAdapter.Calls != 4)
        throw new InvalidOperationException(
            "asynchronous public probe report or stored capability failed");
}
if (probeAdapter.DisposeCount != 1)
    throw new InvalidOperationException("asynchronous probe adapter disposal failed");

var syncProbeAdapter = new ProbeAdapter();
{
    using var client = Client.FromAdapters(
        [new ProviderRegistration("sync-probe-demo", syncProbeAdapter)]);
    var report = client.Probe("sync-probe-demo:model", record: false);
    var stored = client.Capabilities("sync-probe-demo:model");
    if (report.Requests != 4
        || report.Probes.Count != 4
        || report.Probes.Any(static probe => probe.Outcome != ProbeOutcome.Supported)
        || report.Capabilities?.Features?.Provenance != Provenance.Probed
        || stored.Features?.Provenance == Provenance.Probed
        || syncProbeAdapter.Calls != 4)
        throw new InvalidOperationException("synchronous record-false probe report failed");
}
if (syncProbeAdapter.DisposeCount != 1)
    throw new InvalidOperationException("synchronous probe adapter disposal failed");

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

var richAsyncAdapter = new RichLoopAdapter(includeStreamWitness: true);
var richDescriptor = new ProviderDescriptor(
    "rich-loop",
    "Rich package loop",
    (_, _) => ValueTask.FromResult<IAsyncDisposable>(richAsyncAdapter),
    reasoningTranslator: effort => new JsonObject([
        new JsonProperty("effort", new JsonString(effort ?? "default")),
    ]),
    serverTools: ["web_search"]);
var staleTool = new ToolSpec("stale", "Replaced by registered tools.", new JsonObject([
    new JsonProperty("type", new JsonString("object")),
]));
var richRequest = new GenerationRequest(
    [new Message("user", [
        new Text("inspect this rich package input"),
        new ImagePart(data: [1, 2], detail: "low"),
        new DocumentPart(data: [3, 4], filename: "source.pdf"),
        new AudioPart([5, 6], mediaType: "audio/mpeg"),
        new VideoPart(data: [7, 8], startOffsetS: 0, endOffsetS: 1, fps: 2),
    ])],
    new Route(["rich-loop:model"]),
    tools: [staleTool],
    reasoning: "careful",
    providerOptions: new Dictionary<string, JsonObject>
    {
        ["rich-loop"] = new JsonObject([
            new JsonProperty("package_option", new JsonString("kept")),
        ]),
    },
    metadata: new Dictionary<string, string> { ["consumer"] = "package" },
    logprobs: 1,
    citeDocuments: true,
    serverTools: [new ServerToolSpec("web_search", maxUses: 2)]);
var observedAsyncBigInteger = BigInteger.Zero;
var asyncHandlerCalls = 0;
var asyncIncrement = Tool.From((Func<BigInteger, BigInteger>)(value =>
{
    asyncHandlerCalls++;
    observedAsyncBigInteger = value;
    return value + BigInteger.One;
}), name: "increment");
{
    await using var client = new AsyncClient(
        [ProviderSettings.Of("rich-loop")], new ProviderRegistry([richDescriptor]),
        manifests: true, retainRaw: true);
    await using var stream = client.StreamAsync(richRequest);
    var sawReasoning = false;
    var sawCitation = false;
    var sawServerTool = false;
    var sawUsage = false;
    await foreach (var item in stream)
    {
        sawReasoning |= item is ReasoningDelta { Text: "stream reasoning" };
        sawCitation |= item is CitationDelta { Citation.QuotedText: "stream quote" };
        sawServerTool |= item is ServerToolDelta { Kind: "web_search", Status: "completed" };
        sawUsage |= item is UsageUpdate { Usage.OutputTokens: 4 };
    }
    var streamed = stream.Result;
    var final = await client.RunToolsAsync(richRequest, [asyncIncrement], maxRounds: 2);
    var streamWire = richAsyncAdapter.Requests[0];
    var toolWire = richAsyncAdapter.Requests[1];
    var finalWire = richAsyncAdapter.Requests[2];
    var parts = toolWire.Messages[0].Content;
    var returnedTool = finalWire.Messages[2].Content.Single() as ToolResult;
    if (!sawReasoning
        || !sawCitation
        || !sawServerTool
        || !sawUsage
        || streamed.Text != "stream rich result"
        || streamed.Citations.Single().QuotedText != "stream quote"
        || streamed.ServerToolUses.Single() is not { Kind: "web_search", Uses: 1 }
        || streamed.Logprobs.Single() is not { Token: "stream", Bytes.Count: 1 }
        || streamed.Raw is not JsonObject streamedRaw
        || !streamedRaw.TryGetValue("marker", out var streamedMarker)
        || streamedMarker is not JsonString { Value: "stream-raw" }
        || final.Text != "rich final"
        || final.Usage is not { InputTokens: 5, OutputTokens: 8 }
        || final.Citations.Single().QuotedText != "final quote"
        || final.ServerToolUses.Single() is not { Kind: "web_search", Uses: 2 }
        || final.Logprobs.Single() is not { Token: "final", Bytes.Count: 1 }
        || final.Manifest is not { Complete: true }
        || final.Raw is not JsonObject finalRaw
        || !finalRaw.TryGetValue("marker", out var finalMarker)
        || finalMarker is not JsonString { Value: "final-raw" }
        || richAsyncAdapter.Requests.Count != 3
        || streamWire.Tools.Single().Name != "stale"
        || asyncHandlerCalls != 1
        || observedAsyncBigInteger != new BigInteger(17)
        || parts.Count != 5
        || parts[0] is not Text { Value: "inspect this rich package input" }
        || parts[1] is not ImagePart { Data.Count: 2, Url: null, Detail: "low" }
        || parts[2] is not DocumentPart { Data.Count: 2, Filename: "source.pdf" }
        || parts[3] is not AudioPart { Data.Count: 2, MediaType: "audio/mpeg" }
        || parts[4] is not VideoPart { Data.Count: 2, StartOffsetS: 0, EndOffsetS: 1, Fps: 2 }
        || toolWire.Tools.Single().Name != "increment"
        || finalWire.Tools.Single().Name != "increment"
        || toolWire.ReasoningWire.TryGetValue("effort", out var effort) is false
        || effort is not JsonString { Value: "careful" }
        || toolWire.ExtraOptions.TryGetValue("package_option", out var option) is false
        || option is not JsonString { Value: "kept" }
        || toolWire.ServerTools.Single() is not { Kind: "web_search", MaxUses: 2 }
        || !toolWire.CiteDocuments
        || toolWire.Logprobs != 1
        || finalWire.Messages.Count != 3
        || returnedTool is not { CallId: "rich-call", Content: "18", IsError: false })
        throw new InvalidOperationException("public rich package async tool-loop witness failed");
}
if (richAsyncAdapter.DisposeCount != 1)
    throw new InvalidOperationException("public rich package async adapter disposal failed");

var richSyncAdapter = new RichLoopAdapter();
var richSyncDescriptor = new ProviderDescriptor(
    "rich-loop",
    "Rich package loop",
    (_, _) => ValueTask.FromResult<IAsyncDisposable>(richSyncAdapter),
    reasoningTranslator: effort => new JsonObject([
        new JsonProperty("effort", new JsonString(effort ?? "default")),
    ]),
    serverTools: ["web_search"]);
var observedSyncBigInteger = BigInteger.Zero;
var syncHandlerCalls = 0;
var syncIncrement = Tool.From((Func<BigInteger, BigInteger>)(value =>
{
    syncHandlerCalls++;
    observedSyncBigInteger = value;
    return value + BigInteger.One;
}), name: "increment");
{
    using var client = new Client(
        [ProviderSettings.Of("rich-loop")], new ProviderRegistry([richSyncDescriptor]),
        manifests: true, retainRaw: true);
    var final = client.RunTools(richRequest, [syncIncrement], maxRounds: 2);
    var returnedTool = richSyncAdapter.Requests[1].Messages[2].Content.Single() as ToolResult;
    if (final.Text != "rich final"
        || final.Usage is not { InputTokens: 5, OutputTokens: 8 }
        || final.Citations.Single().QuotedText != "final quote"
        || final.ServerToolUses.Single() is not { Kind: "web_search", Uses: 2 }
        || final.Logprobs.Single().Token != "final"
        || final.Raw is not JsonObject raw
        || !raw.TryGetValue("marker", out var marker)
        || marker is not JsonString { Value: "final-raw" }
        || richSyncAdapter.Requests.Count != 2
        || syncHandlerCalls != 1
        || observedSyncBigInteger != new BigInteger(17)
        || richSyncAdapter.Requests[0].Tools.Single().Name != "increment"
        || returnedTool is not { CallId: "rich-call", Content: "18", IsError: false })
        throw new InvalidOperationException("public rich package sync tool-loop witness failed");
}
if (richSyncAdapter.DisposeCount != 1)
    throw new InvalidOperationException("public rich package sync adapter disposal failed");

var retrievalAdapter = new RetrievalAdapter();
var retrievalRegistry = new ProviderRegistry([
    new ProviderDescriptor(
        "retrieval-demo",
        "Retrieval demo",
        (_, _) => ValueTask.FromResult<IAsyncDisposable>(retrievalAdapter),
        operations: [InferenceOperation.Embedding, InferenceOperation.Rerank]),
]);
var retrievalConfig = new AnyInferConfig(
    [ProviderSettings.Of("retrieval-demo")],
    operationRoutes: new Dictionary<InferenceOperation, Route>
    {
        [InferenceOperation.Embedding] = new Route(["retrieval-demo:embedding-model"]),
        [InferenceOperation.Rerank] = new Route(["retrieval-demo:rerank-model"]),
    });
{
    await using var client = AsyncClient.FromConfig(retrievalConfig, retrievalRegistry);
    var withoutRaw = await client.EmbedAsync("first", manifest: true);
    var retained = await client.EmbedAsync(
        new EmbeddingRequest(
            ["second", "third"],
            batch: new BatchPolicy(maxConcurrency: 1, maxItemsOverride: 2),
            retainRaw: true),
        manifest: true);
    var reranked = await client.RerankAsync(
        new RerankRequest(
            "query",
            [
                new RerankDocument("first-id", "first document"),
                new RerankDocument("second-id", "second document"),
            ],
            topN: 1,
            batch: new BatchPolicy(maxConcurrency: 1, maxItemsOverride: 2),
            returnDocuments: true,
            retainRaw: true),
        manifest: true);
    if (withoutRaw.Raw is not null
        || retained.Vectors.Count != 2
        || retained.Target.ToString() != "retrieval-demo:embedding-model"
        || retained.Raw is not JsonString { Value: "embedding-raw" }
        || retained.Attempts.Single().Timing is null
        || retained.Manifest is not { Complete: true, Operation: "embedding", Payloads: null }
        || reranked.Items.Single() is not
            { Index: 1, DocumentId: "second-id", Text: "second document" }
        || reranked.Target.ToString() != "retrieval-demo:rerank-model"
        || reranked.Raw is not JsonString { Value: "rerank-raw" }
        || reranked.Attempts.Single().Timing is null
        || reranked.Manifest is not { Complete: true, Operation: "rerank", Payloads: null }
        || retrievalAdapter.EmbeddingCalls != 2
        || retrievalAdapter.RerankCalls != 1)
        throw new InvalidOperationException("configured retrieval public contract failed");
}
if (retrievalAdapter.DisposeCount != 1)
    throw new InvalidOperationException("retrieval adapter disposal failed");

var syncRetrievalAdapter = new RetrievalAdapter();
{
    using var client = Client.FromAdapters(
        [new ProviderRegistration("sync-retrieval-demo", syncRetrievalAdapter)],
        operationRoutes: new Dictionary<InferenceOperation, Route>
        {
            [InferenceOperation.Embedding] = new Route(["sync-retrieval-demo:embedding-model"]),
            [InferenceOperation.Rerank] = new Route(["sync-retrieval-demo:rerank-model"]),
        });
    var embedded = client.Embed("sync", batch: new BatchPolicy(maxConcurrency: 1));
    var reranked = client.Rerank(
        "query",
        [new RerankDocument("sync-id", "sync document")],
        topN: 1,
        returnDocuments: true);
    if (embedded.Vectors.Single().Values.Count != 2
        || reranked.Items.Single() is not
            { Index: 0, DocumentId: "sync-id", Text: "sync document" }
        || syncRetrievalAdapter.EmbeddingCalls != 1
        || syncRetrievalAdapter.RerankCalls != 1)
        throw new InvalidOperationException("synchronous retrieval public contract failed");
}
if (syncRetrievalAdapter.DisposeCount != 1)
    throw new InvalidOperationException("synchronous retrieval adapter disposal failed");

var telemetryAdapter = new DemoAdapter();
var asyncObserver = new CollectingObserver();
{
    await using var client = AsyncClient.FromAdapters(
        [new ProviderRegistration("telemetry-demo", telemetryAdapter)],
        observers: [asyncObserver]);
    var disabled = await client.GenerateAsync(
        "disabled", target: "telemetry-demo:model", manifest: false);
    await using var stream = client.StreamAsync("hello", target: "telemetry-demo:model");
    var partial = stream.Manifest
        ?? throw new InvalidOperationException("missing partial manifest");
    await stream.CollectAsync();
    var terminal = stream.Result.Manifest
        ?? throw new InvalidOperationException("missing terminal manifest");
    var serialized = terminal.ToJson();
    var restored = RunManifest.FromJson(serialized);
    if (disabled.Manifest is not null
        || partial.Complete
        || !terminal.Complete
        || stream.Result.Manifest != terminal
        || restored.ToJson() != serialized
        || !ManifestUtilities.SchemaDigest(ManifestUtilities.JsonSchema())
            .StartsWith("sha256:")
        || ManifestUtilities.Render(terminal).Length == 0
        || asyncObserver.Events.OfType<RequestStarted>()
            .Any(static item => item.PromptText is not null)
        || asyncObserver.Events.OfType<RequestCompleted>()
            .Any(static item => item.ResponseText is not null))
        throw new InvalidOperationException("async telemetry or manifest public contract failed");
}
if (telemetryAdapter.DisposeCount != 1 || asyncObserver.DisposeCount != 0)
    throw new InvalidOperationException("async telemetry ownership or adapter disposal failed");
asyncObserver.Dispose();

var syncTelemetryAdapter = new DemoAdapter();
var syncObserver = new CollectingObserver();
{
    using var client = Client.FromAdapters(
        [new ProviderRegistration("sync-telemetry-demo", syncTelemetryAdapter)],
        observers: [syncObserver]);
    var disabled = client.Generate(
        "disabled", target: "sync-telemetry-demo:model", manifest: false);
    using var stream = client.Stream("hello", target: "sync-telemetry-demo:model");
    var partial = stream.Manifest
        ?? throw new InvalidOperationException("missing sync partial manifest");
    foreach (var _ in stream)
    {
    }
    var terminal = stream.Result.Manifest
        ?? throw new InvalidOperationException("missing sync terminal manifest");
    if (disabled.Manifest is not null
        || partial.Complete
        || !terminal.Complete
        || stream.Result.Manifest != terminal
        || syncObserver.Events.OfType<RequestCompleted>()
            .Any(static item => item.ResponseText is not null))
        throw new InvalidOperationException("sync telemetry or manifest public contract failed");
}
if (syncTelemetryAdapter.DisposeCount != 1 || syncObserver.DisposeCount != 0)
    throw new InvalidOperationException("sync telemetry ownership or adapter disposal failed");
syncObserver.Dispose();

static bool HasPromptTokens(JsonValue? raw) => raw is JsonObject payload
    && payload.TryGetValue("usage", out var usageValue)
    && usageValue is JsonObject usage
    && usage.TryGetValue("prompt_tokens", out var promptTokens)
    && promptTokens is JsonInteger integer
    && integer.Value == 7;

sealed class CerebrasHandler : HttpMessageHandler
{
    public int RequestCount { get; private set; }
    public int DisposeCount { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        var body = request.Content is null
            ? ""
            : await request.Content.ReadAsStringAsync(cancellationToken);
        using var document = JsonDocument.Parse(body);
        if (request.Method != HttpMethod.Post
            || request.RequestUri?.AbsolutePath != "/v1/chat/completions"
            || request.Headers.Authorization?.Scheme != "Bearer"
            || request.Headers.Authorization.Parameter != "offline-cerebras-key"
            || document.RootElement.GetProperty("model").GetString() != "gpt-oss-120b"
            || document.RootElement.GetProperty("messages")[0].GetProperty("content").GetString()
                != "package Cerebras witness")
            throw new InvalidOperationException(
                "default Cerebras registration lost the configured request");

        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(
                """
                {"choices":[{"message":{"content":"package cerebras"},"finish_reason":"stop"}],
                "usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}
                """,
                Encoding.UTF8,
                "application/json"),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }
}

sealed class HyperbolicHandler : HttpMessageHandler
{
    public int RequestCount { get; private set; }
    public int DisposeCount { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        var body = request.Content is null
            ? ""
            : await request.Content.ReadAsStringAsync(cancellationToken);
        using var document = JsonDocument.Parse(body);
        if (request.Method != HttpMethod.Post
            || request.RequestUri is not
            {
                Scheme: "https",
                Host: "api.hyperbolic.ai",
                AbsolutePath: "/inference/v1/chat/completions",
            }
            || request.Headers.Authorization?.Scheme != "Bearer"
            || request.Headers.Authorization.Parameter != "offline-hyperbolic-key"
            || document.RootElement.GetProperty("model").GetString() != "glm-5.3-flash"
            || document.RootElement.GetProperty("messages")[0].GetProperty("content").GetString()
                != "package Hyperbolic witness")
            throw new InvalidOperationException(
                "default Hyperbolic registration lost the configured request");

        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(
                """
                {"choices":[{"message":{"content":"package hyperbolic"},"finish_reason":"stop"}],
                "usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}
                """,
                Encoding.UTF8,
                "application/json"),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }
}

sealed class RichLoopAdapter(bool includeStreamWitness = false) : IProviderAdapter
{
    public List<WireRequest> Requests { get; } = [];
    public int DisposeCount { get; private set; }

    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        [System.Runtime.CompilerServices.EnumeratorCancellation]
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        Requests.Add(request);
        var call = Requests.Count;
        if (includeStreamWitness && call == 1)
        {
            yield return new AdapterReasoningDelta("stream reasoning");
            yield return new AdapterCitationDelta(
                new Citation(0, 6, "stream quote", title: "stream source"));
            yield return new AdapterServerToolDelta("web_search", "completed", [
                new ServerToolSource("https://example.invalid/stream", "stream source"),
            ]);
            yield return new AdapterTextDelta("stream rich result");
            yield return new AdapterUsage(new Usage(InputTokens: 2, OutputTokens: 4));
            yield return new AdapterFinal("stop", new Usage(InputTokens: 2, OutputTokens: 4),
                Raw: new JsonObject([new JsonProperty("marker", new JsonString("stream-raw"))]),
                logprobs: [new TokenLogprob("stream", -0.1, bytes: [115])],
                serverToolUses: [new ServerToolUse("web_search", 1)]);
            await Task.CompletedTask;
            yield break;
        }

        var toolRound = includeStreamWitness ? 2 : 1;
        if (call == toolRound)
        {
            yield return new AdapterToolCallDelta(0, "rich-call", "increment", """{"value":17}""");
            yield return new AdapterFinal("tool_calls", new Usage(InputTokens: 1, OutputTokens: 1),
                Raw: new JsonObject([new JsonProperty("marker", new JsonString("tool-raw"))]));
            await Task.CompletedTask;
            yield break;
        }

        if (call == toolRound + 1)
        {
            yield return new AdapterReasoningDelta("final reasoning");
            yield return new AdapterCitationDelta(
                new Citation(0, 5, "final quote", title: "final source"));
            yield return new AdapterServerToolDelta("web_search", "completed", [
                new ServerToolSource("https://example.invalid/final", "final source"),
            ]);
            yield return new AdapterTextDelta("rich final");
            yield return new AdapterUsage(new Usage(InputTokens: 5, OutputTokens: 8));
            yield return new AdapterFinal("stop", new Usage(InputTokens: 5, OutputTokens: 8),
                Raw: new JsonObject([new JsonProperty("marker", new JsonString("final-raw"))]),
                logprobs: [new TokenLogprob("final", -0.2, bytes: [102])],
                serverToolUses: [new ServerToolUse("web_search", 2)]);
            await Task.CompletedTask;
            yield break;
        }

        throw new InvalidOperationException("Rich loop made an unexpected provider call.");
    }

    public ValueTask DisposeAsync()
    {
        DisposeCount++;
        return ValueTask.CompletedTask;
    }
}

sealed class RetrievalAdapter : IEmbedsText, IReranksText, IAsyncDisposable
{
    public int EmbeddingCalls { get; private set; }
    public int RerankCalls { get; private set; }
    public int DisposeCount { get; private set; }

    public ValueTask<EmbeddingWireResult> EmbedAsync(
        EmbeddingWireRequest request,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        EmbeddingCalls++;
        return ValueTask.FromResult(new EmbeddingWireResult(
            request.Inputs.Select((_, index) => new[] { (double)(index + 1), 2d }),
            model: request.Model,
            raw: new JsonString("embedding-raw")));
    }

    public ValueTask<RerankWireResult> RerankAsync(
        RerankWireRequest request,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        RerankCalls++;
        return ValueTask.FromResult(new RerankWireResult(
            request.Documents.Reverse()
                .Take(request.TopN ?? int.MaxValue)
                .Select(document => new WireRankedItem(document.Index, document.Index + 0.5d)),
            model: request.Model,
            raw: new JsonString("rerank-raw")));
    }

    public ValueTask DisposeAsync()
    {
        DisposeCount++;
        return ValueTask.CompletedTask;
    }
}

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

sealed class AccountingAdapter : IProviderAdapter
{
    public int DisposeCount { get; private set; }

    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        [System.Runtime.CompilerServices.EnumeratorCancellation]
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        yield return new AdapterTextDelta("accounting");
        yield return new AdapterFinal("stop", new Usage(InputTokens: 1, OutputTokens: 1));
        await Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        DisposeCount++;
        return ValueTask.CompletedTask;
    }
}

sealed class PolicyAdapter : IProviderAdapter
{
    public WireRequest? Captured { get; private set; }
    public int DisposeCount { get; private set; }

    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        [System.Runtime.CompilerServices.EnumeratorCancellation]
        CancellationToken cancellationToken = default)
    {
        Captured = request;
        cancellationToken.ThrowIfCancellationRequested();
        yield return new AdapterToolCallDelta(
            0,
            "inbound-call",
            "lookup_weather",
            """{"city":"Boston"}""");
        yield return new AdapterFinal("tool_calls", new Usage(InputTokens: 1, OutputTokens: 1));
        await Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        DisposeCount++;
        return ValueTask.CompletedTask;
    }
}

sealed class CollectingObserver : IObserver, IDisposable
{
    public List<TelemetryEvent> Events { get; } = [];
    public int DisposeCount { get; private set; }

    public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);

    public void Dispose() => DisposeCount++;
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
        if (request.Mechanism != "prompt"
            || request.Schema is not null
            || request.SchemaName != "response"
            || request.Messages.Count != 2
            || request.Messages[0].Role != "system"
            || !request.Messages[0].Text.StartsWith(
                "Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\\n",
                StringComparison.Ordinal)
            || !request.Messages[0].Text.Contains("\\\"$defs\\\"", StringComparison.Ordinal)
            || request.Messages[1].Text != "Return a schema object.")
            throw new InvalidOperationException(
                "Modern prompt schema wire boundary was not preserved.");
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

sealed class ProbeAdapter : IProviderAdapter
{
    public int Calls { get; private set; }
    public int DisposeCount { get; private set; }

    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        [System.Runtime.CompilerServices.EnumeratorCancellation]
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (request.Sampling.MaxOutputTokens != 64 || request.Sampling.Temperature != 0)
            throw new InvalidOperationException("probe request lost forced sampling controls");

        Calls++;
        switch (Calls)
        {
            case 1 when request.Mechanism == "json_schema"
                && request.Schema is not null
                && request.SchemaName == "capability_probe":
                yield return new AdapterTextDelta("""{"colour":"blue"}""");
                break;
            case 2 when request.Mechanism == "json_mode":
                yield return new AdapterTextDelta("""{"anything":true}""");
                break;
            case 3 when request.Tools.Count == 1
                && request.Tools[0].Name == "record_colour"
                && request.ToolChoice == "required":
                yield return new AdapterToolCallDelta(
                    0, "probe-call", "record_colour", """{"colour":"blue"}""");
                break;
            case 4 when request.Stream:
                yield return new AdapterTextDelta("one, ");
                yield return new AdapterTextDelta("two");
                break;
            default:
                throw new InvalidOperationException(
                    "probe call order or forced wire request was incorrect");
        }

        yield return new AdapterFinal("stop");
        await Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        DisposeCount++;
        return ValueTask.CompletedTask;
    }
}

sealed class TeiHandler(bool reranker) : HttpMessageHandler
{
    public int RequestCount { get; private set; }
    public int DisposeCount { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        var body = request.Content is null
            ? ""
            : await request.Content.ReadAsStringAsync(cancellationToken);
        using var json = JsonDocument.Parse(body);
        if (request.Method != HttpMethod.Post
            || request.RequestUri?.AbsolutePath != (reranker ? "/v1/rerank" : "/v1/embed")
            || request.Content?.Headers.ContentType?.MediaType != "application/json")
            throw new InvalidOperationException("TEI builtin used unexpected HTTP fields");
        if (!reranker)
        {
            var inputs = json.RootElement.GetProperty("inputs").EnumerateArray()
                .Select(static item => item.GetString());
            if (!inputs.SequenceEqual(["first", "second"]))
                throw new InvalidOperationException("TEI builtin lost embedding order");
            return Json("[[0.1,0.2],[0.3,0.4]]");
        }
        if (json.RootElement.GetProperty("query").GetString() != "find first"
            || !json.RootElement.GetProperty("texts").EnumerateArray()
                .Select(static item => item.GetString()).SequenceEqual(["first", "second"])
            || json.RootElement.GetProperty("return_text").GetBoolean())
            throw new InvalidOperationException("TEI builtin lost rerank caller values");
        return Json("[{\\"index\\":1,\\"score\\":0.1},{\\"index\\":0,\\"score\\":0.9}]");
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }

    private static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };
}

sealed class VoyageHandler : HttpMessageHandler
{
    public int RequestCount { get; private set; }
    public int DisposeCount { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        var body = request.Content is null
            ? ""
            : await request.Content.ReadAsStringAsync(cancellationToken);
        using var json = JsonDocument.Parse(body);
        if (request.Method != HttpMethod.Post
            || request.Headers.Authorization?.Scheme != "Bearer"
            || request.Headers.Authorization.Parameter != "offline-voyage-key"
            || request.Headers.Accept.Single().MediaType != "application/json"
            || request.Content?.Headers.ContentType?.MediaType != "application/json")
            throw new InvalidOperationException("Voyage builtin used unexpected HTTP fields");

        return request.RequestUri?.AbsolutePath switch
        {
            "/v1/embeddings" => Embeddings(json.RootElement),
            "/v1/rerank" => Rerank(json.RootElement),
            _ => throw new InvalidOperationException(
                "Voyage builtin used an unexpected request path"),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }

    private static HttpResponseMessage Embeddings(JsonElement request)
    {
        var input = request.GetProperty("input").EnumerateArray()
            .Select(static item => item.GetString()).ToArray();
        var inputType = request.GetProperty("input_type").GetString();
        if (request.GetProperty("model").GetString() != "voyage-3.5-lite"
            || (inputType != "document" && inputType != "query")
            || (inputType == "document" && !input.SequenceEqual(["first", "second"]))
            || (inputType == "query" && !input.SequenceEqual(["find first"])))
            throw new InvalidOperationException(
                "Voyage builtin lost embedding values or array input shape");
        return Json(inputType == "document"
            ? "{\\"data\\":[{\\"index\\":1,\\"embedding\\":[0.3,0.4]},"
                + "{\\"index\\":0,\\"embedding\\":[0.1,0.2]}],\\"usage\\":{\\"total_tokens\\":7}}"
            : "{\\"data\\":[{\\"index\\":0,\\"embedding\\":[0.5,0.6]}],"
                + "\\"usage\\":{\\"total_tokens\\":7}}");
    }

    private static HttpResponseMessage Rerank(JsonElement request)
    {
        if (request.GetProperty("model").GetString() != "rerank-2.5"
            || request.GetProperty("query").GetString() != "find first"
            || request.GetProperty("top_k").GetInt32() != 1
            || !request.GetProperty("documents").EnumerateArray()
                .Select(static item => item.GetString()).SequenceEqual(["first", "second"]))
            throw new InvalidOperationException(
                "Voyage builtin lost rerank values or native top_k");
        return Json("{\\"data\\":[{\\"index\\":1,\\"relevance_score\\":0.1}],"
            + "\\"usage\\":{\\"total_tokens\\":7}}");
    }

    private static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };
}
sealed class JinaHandler : HttpMessageHandler
{
    public int RequestCount { get; private set; }
    public int DisposeCount { get; private set; }
    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        var body = request.Content is null
            ? ""
            : await request.Content.ReadAsStringAsync(cancellationToken);
        using var json = JsonDocument.Parse(body);
        if (request.Method != HttpMethod.Post || request.Headers.Authorization?.Scheme != "Bearer"
            || request.Headers.Authorization.Parameter != "offline-jina-key"
            || request.Headers.Accept.Single().MediaType != "application/json"
            || request.Content?.Headers.ContentType?.MediaType != "application/json")
            throw new InvalidOperationException("Jina builtin used unexpected HTTP fields");
        return request.RequestUri?.AbsolutePath switch
        {
            "/v1/embeddings" => Embeddings(json.RootElement),
            "/v1/rerank" => Rerank(json.RootElement),
            _ => throw new InvalidOperationException(
                "Jina builtin used an unexpected request path"),
        };
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing) DisposeCount++;
        base.Dispose(disposing);
    }
    private static HttpResponseMessage Embeddings(JsonElement request)
    {
        if (request.GetProperty("model").GetString() != "jina-embeddings-v5-text-small"
            || request.GetProperty("task").GetString() != "retrieval.passage"
            || !request.GetProperty("input").EnumerateArray()
                .Select(static item => item.GetString())
                .SequenceEqual(["first", "second"]))
            throw new InvalidOperationException(
                "Jina builtin lost embedding values or task mapping");
        return Json("{\\\"data\\\":[{\\\"index\\\":1,\\\"embedding\\\":[0.3,0.4]},"
            + "{\\\"index\\\":0,\\\"embedding\\\":[0.1,0.2]}],"
            + "\\\"usage\\\":{\\\"total_tokens\\\":7,\\\"prompt_tokens\\\":7}}");
    }
    private static HttpResponseMessage Rerank(JsonElement request)
    {
        if (request.GetProperty("model").GetString() != "jina-reranker-v3"
            || request.GetProperty("query").GetString() != "find first"
            || request.GetProperty("top_n").GetInt32() != 1
            || !request.GetProperty("documents").EnumerateArray()
                .Select(static item => item.GetString())
                .SequenceEqual(["first", "second"]))
            throw new InvalidOperationException("Jina builtin lost rerank values or native top_n");
        return Json("{\\\"results\\\":[{\\\"index\\\":1,\\\"relevance_score\\\":0.1}],"
            + "\\\"usage\\\":{\\\"total_tokens\\\":7,\\\"prompt_tokens\\\":7}}");
    }
    private static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };
}
''',
        encoding="utf-8",
    )


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
