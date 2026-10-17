"""Focused contract checks for the local C# package verifier."""

from __future__ import annotations

import importlib.util
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


def test_validate_package_accepts_closed_payload(tmp_path: Path) -> None:
    package, symbols = _paths(tmp_path)
    _package(package)
    _symbols(symbols)

    CHECKER.validate_package(package, symbols, REVISION)


def test_validate_package_accepts_sdk_2012_nuspec_namespace(tmp_path: Path) -> None:
    package, symbols = _paths(tmp_path)
    _package(package, namespace="http://schemas.microsoft.com/packaging/2012/06/nuspec.xsd")
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


@pytest.mark.parametrize("unexpected", ["lib/net8.0/Other.dll", "runtimes/win-x64/native/other.dll"])
def test_validate_package_rejects_unexpected_payload(tmp_path: Path, unexpected: str) -> None:
    package, symbols = _paths(tmp_path)
    _package(package, unexpected=unexpected)
    _symbols(symbols)

    with pytest.raises(RuntimeError, match="unexpected member"):
        CHECKER.validate_package(package, symbols, REVISION)


def test_validate_package_allows_empty_net8_dependency_group(tmp_path: Path) -> None:
    package, symbols = _paths(tmp_path)
    _package(
        package,
        dependency_group='<dependencies><group targetFramework="net8.0" /></dependencies>',
    )
    _symbols(symbols)

    CHECKER.validate_package(package, symbols, REVISION)


@pytest.mark.parametrize(
    ("license_type", "dependency_group", "message"),
    [
        ("file", "", "license"),
        (
            "expression",
            '<dependencies><group targetFramework="net8.0"><dependency id="x" version="1" /></group></dependencies>',
            "runtime dependencies",
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


def test_main_preserves_preexisting_output_run_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "artifacts"
    sentinel = output / "run" / "keep.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep", encoding="utf-8")
    version = CHECKER.package_version()

    def fake_run(command: list[str], *, cwd: Path) -> None:
        if command[:2] == ["dotnet", "pack"]:
            packages = Path(command[command.index("-o") + 1])
            packages.mkdir(parents=True)
            _package(packages / f"AnyInfer.{version}.nupkg")
            _symbols(packages / f"AnyInfer.{version}.snupkg")

    monkeypatch.setattr(CHECKER, "run", fake_run)
    monkeypatch.setattr(CHECKER, "git_revision", lambda: REVISION)

    assert CHECKER.main(["--output", str(output)]) == 0
    assert sentinel.read_text(encoding="utf-8") == "keep"
    copied_pins = list(output.glob("run-*/global.json"))
    assert len(copied_pins) == 1
    assert copied_pins[0].read_bytes() == (ROOT / "src" / "csharp" / "global.json").read_bytes()
