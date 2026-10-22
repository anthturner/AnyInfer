"""Focused contract checks for the local C# package verifier."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_csharp_package.py"
SPEC = importlib.util.spec_from_file_location("check_csharp_package", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


REVISION = "a" * 40


def _container(archive: zipfile.ZipFile) -> None:
    archive.writestr("[Content_Types].xml", b"types")
    archive.writestr("_rels/.rels", b"rels")
    archive.writestr("package/services/metadata/core-properties/abcdef.psmdcp", b"metadata")


def _package(
    path: Path,
    *,
    description: str = "A bounded .NET 8 inference core for application-owned provider adapters.",
    unexpected: str | None = None,
    license_type: str = "expression",
    dependency_group: str = "",
    namespace: str = "http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd",
) -> None:
    version = CHECKER.package_version()
    nuspec = f'''<?xml version="1.0"?>
<package xmlns="{namespace}">
  <metadata>
    <id>AnyInfer</id><version>{version}</version><authors>Anthony Turner</authors>
    <description>{description}</description><license type="{license_type}">MIT</license><readme>README.md</readme>
    <repository type="git" url="https://github.com/anthturner/AnyInfer" commit="{REVISION}" />
    {dependency_group}
  </metadata>
</package>'''
    with zipfile.ZipFile(path, "w") as archive:
        _container(archive)
        archive.writestr("AnyInfer.nuspec", nuspec)
        archive.writestr("lib/net8.0/AnyInfer.dll", b"core")
        archive.writestr("README.md", b"readme")
        archive.writestr("LICENSE", b"MIT")
        if unexpected is not None:
            archive.writestr(unexpected, b"unexpected")


def _symbols(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        _container(archive)
        archive.writestr("AnyInfer.nuspec", b"nuspec")
        archive.writestr("lib/net8.0/AnyInfer.pdb", b"symbols")


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    version = CHECKER.package_version()
    return (
        tmp_path / f"AnyInfer.{version}.nupkg",
        tmp_path / f"AnyInfer.{version}.snupkg",
    )


QUALIFIED_DEPENDENCY_GROUP = (
    '<dependencies><group targetFramework="net8.0">'
    '<dependency id="JsonSchema.Net" version="[8.0.5]" />'
    '<dependency id="PeterO.Numbers" version="[1.8.2]" />'
    "</group></dependencies>"
)


def test_validate_package_accepts_closed_payload(tmp_path: Path) -> None:
    package, symbols = _paths(tmp_path)
    _package(package, dependency_group=QUALIFIED_DEPENDENCY_GROUP)
    _symbols(symbols)

    CHECKER.validate_package(package, symbols, REVISION)


def test_validate_package_accepts_sdk_2012_nuspec_namespace(tmp_path: Path) -> None:
    package, symbols = _paths(tmp_path)
    _package(
        package,
        namespace="http://schemas.microsoft.com/packaging/2012/06/nuspec.xsd",
        dependency_group=QUALIFIED_DEPENDENCY_GROUP,
    )
    _symbols(symbols)

    CHECKER.validate_package(package, symbols, REVISION)


def test_validate_package_rejects_foreign_nuspec_namespace(tmp_path: Path) -> None:
    package, symbols = _paths(tmp_path)
    _package(package, namespace="urn:foreign-nuspec")
    _symbols(symbols)

    with pytest.raises(RuntimeError, match="namespace"):
        CHECKER.validate_package(package, symbols, REVISION)


def test_validate_package_rejects_metadata_drift(tmp_path: Path) -> None:
    package, symbols = _paths(tmp_path)
    _package(package, description="wrong")
    _symbols(symbols)

    with pytest.raises(RuntimeError, match="description"):
        CHECKER.validate_package(package, symbols, REVISION)


@pytest.mark.parametrize(
    "unexpected", ["lib/net8.0/Other.dll", "runtimes/win-x64/native/other.dll"]
)
def test_validate_package_rejects_unexpected_payload(tmp_path: Path, unexpected: str) -> None:
    package, symbols = _paths(tmp_path)
    _package(package, unexpected=unexpected)
    _symbols(symbols)

    with pytest.raises(RuntimeError, match="unexpected member"):
        CHECKER.validate_package(package, symbols, REVISION)


@pytest.mark.parametrize(
    "dependency_group",
    [
        "",
        '<dependencies><group targetFramework="net8.0" /></dependencies>',
        '<dependencies><group targetFramework="net8.0"><dependency id="JsonSchema.Net" version="[8.0.5]" /></group></dependencies>',
        '<dependencies><group targetFramework="net8.0"><dependency id="JsonSchema.Net" version="8.0.5" /><dependency id="PeterO.Numbers" version="[1.8.2]" /></group></dependencies>',
        '<dependencies><group targetFramework="net8.0"><dependency id="JsonSchema.Net" version="[8.0.5]" /><dependency id="PeterO.Numbers" version="[1.8.1]" /></group></dependencies>',
        '<dependencies><group targetFramework="net8.0"><dependency id="JsonSchema.Net" version="[8.0.5]" /><dependency id="PeterO.Numbers" version="[1.8.2]" /><dependency id="extra" version="1" /></group></dependencies>',
        '<dependencies><group targetFramework="net7.0"><dependency id="JsonSchema.Net" version="[8.0.5]" /><dependency id="PeterO.Numbers" version="[1.8.2]" /></group></dependencies>',
    ],
)
def test_validate_package_rejects_schema_dependency_drift(
    tmp_path: Path, dependency_group: str
) -> None:
    package, symbols = _paths(tmp_path)
    _package(package, dependency_group=dependency_group)
    _symbols(symbols)

    with pytest.raises(RuntimeError, match="dependency"):
        CHECKER.validate_package(package, symbols, REVISION)


@pytest.mark.parametrize(
    ("license_type", "dependency_group", "message"),
    [
        ("file", "", "license"),
        (
            "expression",
            '<dependencies><group targetFramework="net8.0"><dependency id="x" version="1" /></group></dependencies>',
            "dependency",
        ),
    ],
)
def test_validate_package_rejects_invalid_license_or_dependencies(
    tmp_path: Path,
    license_type: str,
    dependency_group: str,
    message: str,
) -> None:
    package, symbols = _paths(tmp_path)
    _package(package, license_type=license_type, dependency_group=dependency_group)
    _symbols(symbols)

    with pytest.raises(RuntimeError, match=message):
        CHECKER.validate_package(package, symbols, REVISION)


def test_default_output_is_the_declared_ci_artifact_directory() -> None:
    options = CHECKER.parse_args([])

    assert options.output == ROOT / ".tmp-tests" / "nuget"


def test_main_preserves_preexisting_output_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "artifacts"
    sentinel = output / "run" / "keep.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep", encoding="utf-8")
    version = CHECKER.package_version()

    def fake_run(command: list[str], *, cwd: Path) -> None:
        if command[:2] == ["dotnet", "pack"]:
            packages = Path(command[command.index("-o") + 1])
            packages.mkdir(parents=True)
            _package(
                packages / f"AnyInfer.{version}.nupkg", dependency_group=QUALIFIED_DEPENDENCY_GROUP
            )
            _symbols(packages / f"AnyInfer.{version}.snupkg")

    monkeypatch.setattr(CHECKER, "run", fake_run)
    monkeypatch.setattr(CHECKER, "git_revision", lambda: REVISION)
    monkeypatch.setattr(CHECKER, "stage_schema_dependencies", lambda feed: None)

    assert CHECKER.main(["--output", str(output)]) == 0
    assert sentinel.read_text(encoding="utf-8") == "keep"
    copied_pins = list(output.glob("run-*/global.json"))
    assert len(copied_pins) == 1
    assert copied_pins[0].read_bytes() == (ROOT / "src" / "csharp" / "global.json").read_bytes()


def _dependency_package(path: Path, package_id: str, version: str, license_text: str) -> str:
    nuspec = f"""<?xml version="1.0"?>
<package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd">
  <metadata><id>{package_id}</id><version>{version}</version>
  <license type="expression">{license_text}</license></metadata>
</package>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{package_id}.nuspec", nuspec)
    return base64.b64encode(hashlib.sha512(path.read_bytes()).digest()).decode("ascii")


def test_stage_schema_dependencies_requires_exact_resolved_graph_and_verified_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_folder = tmp_path / "cache"
    expected_hashes: dict[str, tuple[str, str]] = {}
    target: dict[str, object] = {}
    for name, (version, _, license_text) in CHECKER.QUALIFIED_DEPENDENCIES.items():
        package = package_folder / name.lower() / version / f"{name.lower()}.{version}.nupkg"
        package.parent.mkdir(parents=True)
        expected_hashes[name] = (
            version,
            _dependency_package(package, name, version, license_text),
            license_text,
        )
        target[f"{name}/{version}"] = {"type": "package", "dependencies": {}}
    target["JsonSchema.Net/8.0.5"] = {
        "type": "package",
        "dependencies": {
            "JsonPointer.Net": "6.0.1",
            "Json.More.Net": "2.2.0",
            "Humanizer.Core": "2.14.1",
        },
    }
    target["PeterO.Numbers/1.8.2"] = {"type": "package", "dependencies": {}}
    assets = tmp_path / "project.assets.json"
    assets.write_text(
        json.dumps(
            {"packageFolders": {str(package_folder) + "/": {}}, "targets": {"net8.0": target}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(CHECKER, "QUALIFIED_DEPENDENCIES", expected_hashes)
    feed = tmp_path / "feed"

    CHECKER.stage_schema_dependencies(feed, assets)

    assert sorted(item.name for item in feed.glob("*.nupkg")) == sorted(
        f"{name.lower()}.{version}.nupkg" for name, (version, _, _) in expected_hashes.items()
    )


def test_stage_schema_dependencies_rejects_unqualified_graph_before_archive_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_folder = tmp_path / "cache"
    expected_hashes: dict[str, tuple[str, str]] = {}
    target: dict[str, object] = {}
    for name, (version, _, license_text) in CHECKER.QUALIFIED_DEPENDENCIES.items():
        package = package_folder / name.lower() / version / f"{name.lower()}.{version}.nupkg"
        package.parent.mkdir(parents=True)
        expected_hashes[name] = (
            version,
            _dependency_package(package, name, version, license_text),
            license_text,
        )
        target[f"{name}/{version}"] = {"type": "package", "dependencies": {}}
    target["JsonSchema.Net/8.0.5"] = {"type": "package", "dependencies": {}}
    assets = tmp_path / "project.assets.json"
    assets.write_text(
        json.dumps(
            {"packageFolders": {str(package_folder) + "/": {}}, "targets": {"net8.0": target}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(CHECKER, "QUALIFIED_DEPENDENCIES", expected_hashes)

    with pytest.raises(RuntimeError, match="graph"):
        CHECKER.stage_schema_dependencies(tmp_path / "feed", assets)


@pytest.mark.parametrize(
    ("mutate", "package_to_mutate", "message"),
    [
        ("hash", "Json.More.Net", "hash"),
        ("license", "Json.More.Net", "license"),
        ("license", "PeterO.Numbers", "license"),
    ],
)
def test_stage_schema_dependencies_rejects_archive_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: str,
    package_to_mutate: str,
    message: str,
) -> None:
    package_folder = tmp_path / "cache"
    expected_hashes: dict[str, tuple[str, str]] = {}
    target: dict[str, object] = {}
    for name, (version, _, license_text) in CHECKER.QUALIFIED_DEPENDENCIES.items():
        package = package_folder / name.lower() / version / f"{name.lower()}.{version}.nupkg"
        package.parent.mkdir(parents=True)
        actual_hash = _dependency_package(
            package,
            name,
            version,
            "Apache-2.0" if mutate == "license" and name == package_to_mutate else license_text,
        )
        expected_hashes[name] = (
            version,
            "different" if mutate == "hash" and name == package_to_mutate else actual_hash,
            license_text,
        )
        target[f"{name}/{version}"] = {"type": "package", "dependencies": {}}
    target["JsonSchema.Net/8.0.5"] = {
        "type": "package",
        "dependencies": {
            "JsonPointer.Net": "6.0.1",
            "Json.More.Net": "2.2.0",
            "Humanizer.Core": "2.14.1",
        },
    }
    target["PeterO.Numbers/1.8.2"] = {"type": "package", "dependencies": {}}
    assets = tmp_path / "project.assets.json"
    assets.write_text(
        json.dumps(
            {"packageFolders": {str(package_folder) + "/": {}}, "targets": {"net8.0": target}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(CHECKER, "QUALIFIED_DEPENDENCIES", expected_hashes)

    with pytest.raises(RuntimeError, match=message):
        CHECKER.stage_schema_dependencies(tmp_path / "feed", assets)


def test_external_consumer_uses_public_sdk_catalog_capability_pricing_and_lifecycle_vocabulary(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "consumer"
    CHECKER.write_consumer(
        consumer, tmp_path / "feed", tmp_path / "cache", CHECKER.package_version()
    )

    source = (consumer / "Program.cs").read_text(encoding="utf-8")
    assert 'new Text("hello")' in source
    assert 'AsyncClient.FromAdapters([new ProviderRegistration("demo", adapter)])' in source
    assert 'GenerateAsync(messages, target: "demo:model")' in source
    assert 'StreamAsync("hello", target: "demo:model")' in source
    assert "TextDelta delta" in source
    assert 'Client.FromAdapters([new ProviderRegistration("sync-demo", syncAdapter)])' in source
    assert 'client.Generate("hello", target: "sync-demo:model")' in source
    assert 'client.Stream("hello", target: "sync-demo:model")' in source
    assert "foreach (var item in stream)" in source
    assert "synchronous adapter disposal failed" in source
    assert "operations: [InferenceOperation.Embedding, InferenceOperation.Rerank]" in source
    assert "operationRoutes: new Dictionary<InferenceOperation, Route>" in source
    assert "AsyncClient.FromConfig(retrievalConfig, retrievalRegistry)" in source
    assert 'new EmbeddingRequest(\n            ["second", "third"],' in source
    assert 'new RerankDocument("second-id", "second document")' in source
    assert (
        'retained.Manifest is not { Complete: true, Operation: "embedding", Payloads: null }'
        in source
    )
    assert (
        'reranked.Manifest is not { Complete: true, Operation: "rerank", Payloads: null }'
        in source
    )
    assert "retained.Attempts.Single().Timing is null" in source
    assert "reranked.Attempts.Single().Timing is null" in source
    assert "sealed class RetrievalAdapter : IEmbedsText, IReranksText, IAsyncDisposable" in source
    assert "synchronous retrieval adapter disposal failed" in source
    assert "sealed class RetrievalAdapter : IProviderAdapter" not in source
    assert (
        'ProviderSettings.Of(\n    "tei", "https://tei-embed.offline/v1", transport: teiEmbedHandler, alias: "tei-embed")'
        in source
    )
    assert (
        'target: "tei-rerank:rerank-model", returnDocuments: true, retainRaw: true, manifest: true)'
        in source
    )
    assert "default TEI builtin retrieval witness failed" in source
    assert "embedded.Usage.OutputTokens is not null" in source
    assert "embedded.Raw is null" in source
    assert "reranked.Usage.OutputTokens is not null" in source
    assert "reranked.Raw is null" in source
    assert "sealed class TeiHandler(bool reranker) : HttpMessageHandler" in source
    assert "sealed class TeiHandler : IEmbedsText" not in source
    assert '"voyage", apiKey: "offline-voyage-key", transport: voyageAsyncHandler,' in source
    assert 'alias: "voyage-retrieval");' in source
    assert 'target: "voyage-retrieval:voyage-3.5-lite"' in source
    assert "inputType: EmbeddingInputIntent.Document, retainRaw: true" in source
    assert "inputType: EmbeddingInputIntent.Query, retainRaw: true" in source
    assert 'target: "voyage-retrieval:rerank-2.5", topN: 1, returnDocuments: true,' in source
    assert "retainRaw: true, manifest: true);" in source
    assert "default Voyage builtin retrieval witness failed" in source
    assert "default Voyage sync builtin retrieval witness failed" in source
    assert "embedded.Usage.TotalTokens != 7" in source
    assert "reranked.Usage.TotalTokens != 7" in source
    assert "sealed class VoyageHandler : HttpMessageHandler" in source
    assert "sealed class VoyageHandler : IEmbedsText" not in source
    assert 'request.Headers.Accept.Single().MediaType != "application/json"' in source
    assert "TextPart" not in source
    assert "TextDeltaEvent" not in source
    assert "GenerationResult" not in source
    assert "new AsyncClient([settings], registry, catalog: catalog," in source
    assert "new Client([settings], registry, catalog: catalog," in source
    assert "using AnyInfer.Capabilities;" in source
    assert "using AnyInfer.Routing;" in source
    assert "using AnyInfer.Catalog;" in source
    assert "using AnyInfer.Schema;" in source
    assert 'ProviderSettings.Of("demo", alias: "demo-instance")' in source
    assert "new global::AnyInfer.Catalog.Catalog(" in source
    assert "new PricingTable(" in source
    assert 'new PricingEntry(\n            "demo-model",\n            new Pricing(' in source
    assert 'EDecimal.FromString("3.25")' in source
    assert "new Sourced<Pricing>(\n                new Pricing(" in source
    assert 'EDecimal.FromString("5.75")' in source
    assert "new ProviderSetupSpec(" in source
    assert 'new HostShorthand("https", 443)' in source
    assert 'anyOf: [["api_key", "access_token"]]' in source
    assert 'client.Resolve("tier")' in source
    assert 'client.Capabilities("tier")' in source
    assert 'pricingTable.Lookup("demo-instance", "demo-model")' in source
    assert "factoryCalls != 0" in source
    assert "new SpendLedger()" in source
    assert "PricingCalculator.WithCost(quotedUsage, trustedAccounting)" in source
    assert "PricingCalculator.ComputeCost(quotedUsage, defaultAccounting)" in source
    assert (
        'client.Budget("accounting", "accounting-demo:model", outputReserveTokens: 32)' in source
    )
    assert "var spend = client.Spend();" in source
    assert "new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false))" in source
    assert "sealed class AccountingAdapter : IProviderAdapter" in source
    assert "using AnyInfer.Config;" in source
    assert 'new ProviderRegistration("policy-demo", policyAdapter)' in source
    assert "spendPolicy: new SpendPolicy()" in source
    assert "cachePolicy: new CachePolicy()" in source
    assert (
        'new Route(["policy-demo:model"], contextWindowTargets: ["policy-demo:model"])' in source
    )
    assert "new ToolSpec(" in source
    assert (
        'new Message("assistant", [new ToolCall("call-1", rawTool.Name, new JsonObject([' in source
    )
    assert 'new JsonProperty("properties", new JsonObject([' in source
    assert 'new JsonProperty("city", new JsonObject([' in source
    assert 'new JsonProperty("city", new JsonString("Boston"))' in source
    assert 'new Message("tool", [new ToolResult("call-1", "clear")])' in source
    assert "await using var stream = client.StreamAsync(policyRequest);" in source
    assert "ToolCallDelta? delta = null;" in source
    assert 'generation.Text != ""' in source
    assert 'generation.FinishReason != "tool_calls"' in source
    assert 'inboundCall.Id != "inbound-call"' in source
    assert 'inboundCall.Name != "lookup_weather"' in source
    assert 'inboundCity is not JsonString { Value: "Boston" }' in source
    assert 'const string expectedArguments = """{"city":"Boston"}""";' in source
    assert "Index: 0," in source
    assert "ArgumentsFragment: expectedArguments" in source
    assert "sealed class PolicyAdapter : IProviderAdapter" in source
    assert "new AdapterToolCallDelta(" in source
    assert "var captured = policyAdapter.Captured" in source
    assert 'outboundCall.Id != "call-1"' in source
    assert 'outboundCall.Name != "lookup_weather"' in source
    assert 'outboundCity is not JsonString { Value: "Boston" }' in source
    assert 'outboundResult.CallId != "call-1"' in source
    assert 'outboundResult.Content != "clear"' in source
    assert "outboundResult.IsError" in source
    assert 'parameterType is not JsonString { Value: "object" }' in source
    assert 'cityType is not JsonString { Value: "string" }' in source
    assert "cache: new CachePolicy(CacheMode.Off)" in source
    assert "new AnyInferConfig(" in source
    assert "AsyncClient.FromConfig(" in source
    assert "configured policy adapter disposal failed" in source
    assert "policy adapter disposal failed" in source
    assert "SchemaSpec.FromJson" in source
    assert "SchemaValidator.ValidateAsync" in source
    assert ".DeserializeStructured<SchemaAnswer>()" in source
    assert 'JsonPropertyName("answer")' in source
    assert '"https://json-schema.org/draft/2020-12/schema"' in source
    assert '"$defs"' in source
    assert '"$ref":"#/$defs/answer"' in source
    assert "sealed class SchemaAdapter : IProviderAdapter" in source
    assert 'new ProviderRegistration("schema-demo", schemaAdapter)' in source
    assert "schema: schema" in source
    assert "using AnyInfer.Events;" in source
    assert "using AnyInfer.Manifest;" in source
    assert 'new ProviderRegistration("telemetry-demo", telemetryAdapter)' in source
    assert "manifest: false" in source
    assert "var partial = stream.Manifest" in source
    assert "RunManifest.FromJson(serialized)" in source
    assert "ManifestUtilities.JsonSchema()" in source
    assert "ManifestUtilities.Render(terminal)" in source
    assert "sealed class CollectingObserver : IObserver, IDisposable" in source
    assert "asyncObserver.DisposeCount != 0" in source
    assert 'new ProviderRegistration("sync-telemetry-demo", syncTelemetryAdapter)' in source
    assert "syncObserver.DisposeCount != 0" in source
    assert 'request.Schema is null || request.SchemaName != "response"' in source
    assert "schemaAdapter.SchemaRequests != 1" in source
    assert "schemaAdapter.DisposeCount != 1" in source
    assert (
        'AsyncClient.FromAdapters(\n        [new ProviderRegistration("lifecycle-demo", lifecycleAdapter)])'
        in source
    )
    assert 'await client.ModelsAsync("lifecycle-demo")' in source
    assert 'await client.HealthAsync("lifecycle-demo")' in source
    assert 'client.Capabilities("lifecycle-demo:lifecycle-model")' in source
    assert (
        'Client.FromAdapters(\n        [new ProviderRegistration("sync-lifecycle-demo", syncLifecycleAdapter)])'
        in source
    )
    assert 'client.Models("sync-lifecycle-demo")' in source
    assert 'client.Health("sync-lifecycle-demo")' in source
    assert 'client.Capabilities("sync-lifecycle-demo:lifecycle-model")' in source
    assert "sealed class LifecycleAdapter : IProviderAdapter, IProviderLifecycle" in source
    assert "new Sourced<int>(2048, Provenance.Discovered)" in source
    assert "lifecycleAdapter.DisposeCount != 1" in source
    assert "syncLifecycleAdapter.DisposeCount != 1" in source
    assert (
        'AsyncClient.FromAdapters(\n        [new ProviderRegistration("probe-demo", probeAdapter)])'
        in source
    )
    assert 'await client.ProbeAsync("probe-demo:model")' in source
    assert 'client.Capabilities("probe-demo:model")' in source
    assert (
        'Client.FromAdapters(\n        [new ProviderRegistration("sync-probe-demo", syncProbeAdapter)])'
        in source
    )
    assert 'client.Probe("sync-probe-demo:model", record: false)' in source
    assert "sealed class ProbeAdapter : IProviderAdapter" in source
    assert (
        "new AdapterToolCallDelta(\n"
        '                    0, "probe-call", "record_colour", """{"colour":"blue"}""")'
    ) in source
    assert 'new AdapterTextDelta("""{"colour":"blue"}""")' in source
    assert 'new AdapterTextDelta("""{"anything":true}""")' in source
    assert 'request.SchemaName == "capability_probe"' in source
