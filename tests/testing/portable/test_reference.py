"""Private preflight and environment evidence checks for reference observation."""

from __future__ import annotations

import subprocess
import sys
import warnings
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from . import reference
from .reference import ReferencePreflightError, strict_reference_warnings


def test_strict_warning_context_restores_ambient_policy_after_exception() -> None:
    before = list(warnings.filters)
    with pytest.raises(RuntimeError):
        with strict_reference_warnings() as policy:
            assert policy["mode"] == "error" and len(warnings.filters) == 1
            raise RuntimeError("checked restoration")
    assert warnings.filters == before


def test_strict_warning_context_promotes_warning() -> None:
    with strict_reference_warnings():
        with pytest.raises(UserWarning):
            warnings.warn("reference warning", UserWarning, stacklevel=2)


def test_reference_preflight_error_is_a_value_error() -> None:
    assert issubclass(ReferencePreflightError, ValueError)


def test_preflight_rejects_wrong_revision_before_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, selected, outputs = _synthetic_paths(tmp_path)
    monkeypatch.setattr(reference, "_git", lambda *_args: "b" * 40)
    with pytest.raises(ReferencePreflightError, match="does not match"):
        reference.preflight_reference(
            selected, expected_revision="a" * 40, repository_root=repository, **outputs
        )


def test_preflight_clean_synthetic_binds_immutable_hashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, selected, outputs = _synthetic_paths(tmp_path)
    _install_clean_preflight(
        monkeypatch, repository, {"specification/core-generation.md": "1" * 64}
    )
    result = reference.preflight_reference(
        selected, expected_revision="a" * 40, repository_root=repository, **outputs
    )
    assert result.manifest_path.parent == repository / "specification/reference"
    assert type(result.input_hashes).__name__ == "mappingproxy"


def test_preflight_rejects_dirty_wrong_import_and_incomplete_corpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, selected, outputs = _synthetic_paths(tmp_path)
    _install_clean_preflight(
        monkeypatch, repository, {"specification/core-generation.md": "1" * 64}
    )
    monkeypatch.setattr(
        reference,
        "_clean_status",
        lambda *_args: (_ for _ in ()).throw(ReferencePreflightError("dirty")),
    )
    with pytest.raises(ReferencePreflightError, match="dirty"):
        reference.preflight_reference(
            selected, expected_revision="a" * 40, repository_root=repository, **outputs
        )
    monkeypatch.setattr(reference, "_clean_status", lambda *_args: None)
    monkeypatch.setattr(
        reference,
        "_inventory_paths",
        lambda *_args: (_ for _ in ()).throw(ReferencePreflightError("incomplete corpus")),
    )
    with pytest.raises(ReferencePreflightError, match="incomplete corpus"):
        reference.preflight_reference(
            selected, expected_revision="a" * 40, repository_root=repository, **outputs
        )


def test_output_path_rejects_wrong_prefix_existing_or_external_root(tmp_path: Path) -> None:
    root = tmp_path / "a/specification"
    (root / "reference").mkdir(parents=True)
    with pytest.raises(ReferencePreflightError, match="exact canonical"):
        reference._output_path(root, tmp_path / "b.json", "python-aaaaaaa.json")
    output = root / "reference/python-aaaaaaa.json"
    output.write_text("sealed")
    with pytest.raises(ReferencePreflightError, match="overwrite"):
        reference._output_path(root, output, "python-aaaaaaa.json")


def test_actual_distribution_and_resource_observations_are_complete() -> None:
    lock = reference._distribution_lock()
    validator = reference._validator_identity()
    assert set(lock) >= reference._REQUIRED_PACKAGES
    assert all(row["metadata_sha256"] for row in lock.values())
    assert validator["resource_identities"] and validator["selected"]
    assert validator["defaults"]["format_checker"] == "none"


def test_loaded_dependency_bytes_change_environment_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preflight, dependency = _controlled_environment(monkeypatch, tmp_path)
    first = reference.capture_reference_environment(preflight)
    dependency.write_text("changed", encoding="utf-8")
    second = reference.capture_reference_environment(preflight)
    assert (
        first["loaded_modules"]["httpx._reference_capture_probe"]["sha256"]
        != second["loaded_modules"]["httpx._reference_capture_probe"]["sha256"]
    )


def test_foreign_anyinfer_module_refuses_environment_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preflight, _ = _controlled_environment(monkeypatch, tmp_path)
    foreign = tmp_path / "foreign.py"
    foreign.write_text("foreign", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "anyinfer", _module("anyinfer", foreign))
    with pytest.raises(ReferencePreflightError, match="escapes its root"):
        reference.capture_reference_environment(preflight)


def test_real_git_status_and_tracking_fail_closed(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    for args in (
        ("init",),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "test"),
    ):
        subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True)
    tracked = repository / "tracked.py"
    tracked.write_text("one", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repository, check=True, capture_output=True
    )
    reference._clean_status(repository, set())
    tracked.write_text("two", encoding="utf-8")
    with pytest.raises(ReferencePreflightError, match="dirty"):
        reference._clean_status(repository, set())
    tracked.write_text("one", encoding="utf-8")
    untracked = repository / "untracked.py"
    untracked.write_text("x", encoding="utf-8")
    with pytest.raises(ReferencePreflightError, match="dirty"):
        reference._clean_status(repository, set())
    with pytest.raises(ReferencePreflightError, match="cannot inspect"):
        reference._require_tracked(repository, untracked, "untracked")


def test_real_output_links_refuse_when_supported(tmp_path: Path) -> None:
    root = tmp_path / "specification"
    (root / "reference").mkdir(parents=True)
    output = root / "reference/python-aaaaaaa.json"
    try:
        output.symlink_to(tmp_path / "missing-target")
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(ReferencePreflightError, match="link"):
        reference._output_path(root, output, "python-aaaaaaa.json")


def test_external_release_binding_requires_matching_reference_and_hashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = SimpleNamespace(
        reference_manifest={"reference_run_revision": "a" * 40},
        file_hashes={"specification/core-generation.md": "1" * 64},
    )
    module = SimpleNamespace(load_release_assets=lambda *_args: assets)
    monkeypatch.setattr(reference, "_release_assets_module", lambda: module)
    reference._bind_external_assets(
        tmp_path, "a" * 40, {"specification/core-generation.md": "1" * 64}
    )
    assets.reference_manifest["reference_run_revision"] = "b" * 40
    with pytest.raises(ReferencePreflightError, match="revision"):
        reference._bind_external_assets(
            tmp_path, "a" * 40, {"specification/core-generation.md": "1" * 64}
        )


def _synthetic_paths(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    repository = tmp_path / "repository"
    selected = repository / "specification"
    (selected / "reference").mkdir(parents=True)
    return (
        repository,
        selected,
        {
            "output_manifest": selected / "reference/python-aaaaaaa.json",
            "output_environment": selected / "reference/python-aaaaaaa.environment.json",
        },
    )


def _install_clean_preflight(
    monkeypatch: pytest.MonkeyPatch, repository: Path, hashes: dict[str, str]
) -> None:
    package = repository / "src/python/anyinfer/__init__.py"
    driver = repository / "tests/testing/portable/reference.py"
    package.parent.mkdir(parents=True)
    driver.parent.mkdir(parents=True)
    package.write_text("", encoding="utf-8")
    driver.write_text("", encoding="utf-8")
    monkeypatch.setitem(
        __import__("sys").modules, "anyinfer", SimpleNamespace(__file__=str(package))
    )
    monkeypatch.setattr(reference, "__file__", str(driver))
    monkeypatch.setattr(reference, "_inventory_paths", lambda *_args: ([], hashes))
    monkeypatch.setattr(reference, "_validator_module", lambda: SimpleNamespace())
    monkeypatch.setattr(reference, "_require_tracked", lambda *_args: None)
    monkeypatch.setattr(
        reference,
        "_git",
        lambda _root, *args: "a" * 40 if args[:2] == ("rev-parse", "HEAD") else "",
    )


def _controlled_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[reference.ReferencePreflight, Path]:
    repository = Path(__file__).parents[3].resolve()
    dependency = tmp_path / "httpx" / "_reference_capture_probe.py"
    dependency.parent.mkdir()
    dependency.write_text("initial", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "httpx._reference_capture_probe",
        _module("httpx._reference_capture_probe", dependency),
    )
    monkeypatch.setattr(reference, "_require_tracked", lambda *_args: None)
    return (
        reference.ReferencePreflight(
            "a" * 40,
            repository,
            repository / "specification",
            repository / "specification/reference/python-aaaaaaa.json",
            repository / "specification/reference/python-aaaaaaa.environment.json",
            {},
        ),
        dependency,
    )


def _module(name: str, path: Path) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(path)
    return module
