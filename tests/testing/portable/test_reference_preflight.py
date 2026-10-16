"""Direct fail-closed checks for private reference preflight helpers."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import is_dataclass
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from . import reference
from .reference import ReferencePreflight, ReferencePreflightError


def test_inventory_paths_binds_complete_nonpending_synthetic_corpus(tmp_path: Path) -> None:
    root = _complete_corpus(tmp_path)
    validator = reference._validator_module()

    fixtures, hashes = reference._inventory_paths(root, validator)

    inventory = validator.read_json(root / "inventories/core-generation-v0.json")
    expected = [
        (root / Path(*case["path"].split("/")[1:])).resolve()
        for case in inventory["cases"]
        if case["kind"] == "fixture"
    ]
    required = {
        "README.md",
        "core-generation.md",
        "MAINTENANCE.md",
        "inventories/core-generation-v0.json",
        *(f"schemas/{name}" for name in reference._SCHEMAS),
        *(path.relative_to(root).as_posix() for path in expected),
    }
    assert fixtures == expected
    assert set(hashes) == {f"specification/{path}" for path in required}
    assert all(
        digest == hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for key, digest in hashes.items()
        for relative in [Path(key).relative_to("specification")]
    )


def test_inventory_paths_refuses_pending_or_missing_selected_inputs(tmp_path: Path) -> None:
    root = _complete_corpus(tmp_path)
    validator = reference._validator_module()
    fixtures, _hashes = reference._inventory_paths(root, validator)
    pending = json.loads(fixtures[0].read_text(encoding="utf-8"))
    pending["expected"]["status"] = "to_be_observed"
    fixtures[0].write_text(json.dumps(pending) + "\n", encoding="utf-8")

    with pytest.raises(ReferencePreflightError, match="pending expectation"):
        reference._inventory_paths(root, validator)

    root = _complete_corpus(tmp_path / "missing-fixture")
    fixtures, _hashes = reference._inventory_paths(root, validator)
    fixtures[0].unlink()
    with pytest.raises(ReferencePreflightError):
        reference._inventory_paths(root, validator)

    root = _complete_corpus(tmp_path / "missing-schema")
    (root / "schemas/fixture-v0.schema.json").unlink()
    with pytest.raises(ReferencePreflightError):
        reference._inventory_paths(root, validator)


def test_real_git_helpers_reject_dirty_untracked_and_foreign_inputs(tmp_path: Path) -> None:
    repository, tracked = _repository(tmp_path)
    generated = repository / "specification/reference/python-aaaaaaa.json"
    foreign = tmp_path / "foreign.py"
    untracked = repository / "untracked.py"

    reference._require_tracked(repository, tracked, "tracked")
    reference._clean_status(repository, set())
    foreign.write_text("foreign\n", encoding="utf-8")
    with pytest.raises(ReferencePreflightError, match="outside"):
        reference._require_tracked(repository, foreign, "foreign")
    untracked.write_text("untracked\n", encoding="utf-8")
    with pytest.raises(ReferencePreflightError, match="cannot inspect"):
        reference._require_tracked(repository, untracked, "untracked")
    untracked.unlink()

    tracked.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ReferencePreflightError, match="dirty"):
        reference._clean_status(repository, set())
    tracked.write_text("tracked\n", encoding="utf-8")

    generated.write_text("generated\n", encoding="utf-8")
    reference._clean_status(repository, {generated})
    (repository / "specification/reference/other.json").write_text("other\n", encoding="utf-8")
    with pytest.raises(ReferencePreflightError, match="dirty"):
        reference._clean_status(repository, {generated})


def test_root_intermediate_and_output_links_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "specification"
    root.mkdir()
    root_alias = tmp_path / "specification-alias"
    _link_or_classify(monkeypatch, root_alias, root, directory=True)
    with pytest.raises(ReferencePreflightError, match="link"):
        reference._safe_root(root_alias, "selected specification root")


def test_intermediate_and_dangling_output_links_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "specification"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = root / "linked"
    _link_or_classify(monkeypatch, linked, outside, directory=True)
    with pytest.raises(ReferencePreflightError, match="link"):
        reference._inside(root, linked / "input.json", "selected input")

    reference_directory = root / "reference"
    reference_directory.mkdir()
    output = reference_directory / "python-aaaaaaa.json"
    _link_or_classify(monkeypatch, output, tmp_path / "missing-target", directory=False)
    with pytest.raises(ReferencePreflightError, match="link"):
        reference._output_path(root, output, output.name)


def test_selected_root_under_linked_parent_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_parent = tmp_path / "real-parent"
    selected = real_parent / "specification"
    selected.mkdir(parents=True)
    linked_parent = tmp_path / "linked-parent"
    _link_or_classify(monkeypatch, linked_parent, real_parent, directory=True)

    with pytest.raises(ReferencePreflightError, match="link"):
        reference._safe_root(linked_parent / "specification", "selected specification root")


def test_capture_refuses_foreign_and_untracked_driver_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, _tracked = _repository(tmp_path)
    package = repository / "src/python/anyinfer/__init__.py"
    package.parent.mkdir(parents=True)
    package.write_text("", encoding="utf-8")
    _git(repository, "add", "src/python/anyinfer/__init__.py")
    _git(repository, "commit", "-m", "track package")
    module = ModuleType("anyinfer")
    module.__file__ = str(package)
    preflight = ReferencePreflight(
        "a" * 40,
        repository,
        repository / "specification",
        repository / "specification/reference/python-aaaaaaa.json",
        repository / "specification/reference/python-aaaaaaa.environment.json",
        {},
    )
    foreign = tmp_path / "foreign-driver.py"
    foreign.write_text("", encoding="utf-8")
    untracked = repository / "tests/testing/portable/foreign-driver.py"
    untracked.parent.mkdir(parents=True)
    untracked.write_text("", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "anyinfer", module)

    monkeypatch.setattr(reference, "__file__", str(foreign))
    with pytest.raises(ReferencePreflightError, match="escapes"):
        reference.capture_reference_environment(preflight)

    monkeypatch.setattr(reference, "__file__", str(untracked))
    with pytest.raises(ReferencePreflightError, match="cannot inspect"):
        reference.capture_reference_environment(preflight)


def test_capture_refuses_tracked_anyinfer_outside_its_role_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, _tracked = _repository(tmp_path)
    _package, driver = _tracked_capture_paths(repository)
    substitute = repository / "other/tracked-anyinfer.py"
    substitute.parent.mkdir()
    substitute.write_text("", encoding="utf-8")
    _git(repository, "add", "other/tracked-anyinfer.py")
    _git(repository, "commit", "-m", "track misplaced import")
    module = ModuleType("anyinfer")
    module.__file__ = str(substitute)
    monkeypatch.setitem(sys.modules, "anyinfer", module)
    monkeypatch.setattr(reference, "__file__", str(driver))

    with pytest.raises(ReferencePreflightError, match="not under repository src/python"):
        reference.capture_reference_environment(_capture_preflight(repository))


def test_capture_refuses_tracked_driver_outside_its_role_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, _tracked = _repository(tmp_path)
    package, _driver = _tracked_capture_paths(repository)
    substitute = repository / "other/tracked-driver.py"
    substitute.parent.mkdir()
    substitute.write_text("", encoding="utf-8")
    _git(repository, "add", "other/tracked-driver.py")
    _git(repository, "commit", "-m", "track misplaced driver")
    module = ModuleType("anyinfer")
    module.__file__ = str(package)
    monkeypatch.setitem(sys.modules, "anyinfer", module)
    monkeypatch.setattr(reference, "__file__", str(substitute))

    with pytest.raises(ReferencePreflightError, match="not under repository portable tests"):
        reference.capture_reference_environment(_capture_preflight(repository))


@pytest.mark.parametrize("module_name", ("testing.portable.foreign", "tests.testing.portable.foreign"))
def test_capture_refuses_foreign_private_module_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module_name: str
) -> None:
    repository, _tracked = _repository(tmp_path)
    package, driver = _tracked_capture_paths(repository)
    foreign = tmp_path / "foreign-private.py"
    foreign.write_text("", encoding="utf-8")
    native = ModuleType("anyinfer")
    native.__file__ = str(package)
    injected = ModuleType(module_name)
    injected.__file__ = str(foreign)
    for name in tuple(sys.modules):
        if name.startswith("anyinfer.") or any(
            name == namespace or name.startswith(f"{namespace}.")
            for namespace in reference._PORTABLE_NAMESPACES
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "anyinfer", native)
    monkeypatch.setitem(sys.modules, module_name, injected)
    monkeypatch.setattr(reference, "__file__", str(driver))

    with pytest.raises(ReferencePreflightError, match="outside the committed checkout"):
        reference.capture_reference_environment(_capture_preflight(repository))


def test_release_assets_loader_registers_the_trusted_dataclass_module() -> None:
    module = reference._release_assets_module()

    assert module.__file__ == str(Path(__file__).parents[3] / "scripts/portable_release_assets.py")
    assert is_dataclass(module.ReleaseAssets)
    assert sys.modules["_portable_reference_release_assets"] is module


def _complete_corpus(tmp_path: Path) -> Path:
    builder = _trusted_corpus_builder()
    root, _release = builder._tree(tmp_path)
    return cast(Path, root)


def _trusted_corpus_builder() -> ModuleType:
    path = Path(__file__).parents[2] / "test_portable_release_assets.py"
    spec = importlib.util.spec_from_file_location("trusted_portable_release_assets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repository(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "test@example.invalid")
    _git(repository, "config", "user.name", "test")
    tracked = repository / "tracked.py"
    tracked.write_text("tracked\n", encoding="utf-8")
    keep = repository / "specification/reference/.keep"
    keep.parent.mkdir(parents=True)
    keep.write_text("\n", encoding="utf-8")
    _git(repository, "add", "tracked.py", "specification/reference/.keep")
    _git(repository, "commit", "-m", "initial")
    return repository, tracked


def _tracked_capture_paths(repository: Path) -> tuple[Path, Path]:
    package = repository / "src/python/anyinfer/__init__.py"
    driver = repository / "tests/testing/portable/reference.py"
    for path in (package, driver):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    _git(repository, "add", "src/python/anyinfer/__init__.py", "tests/testing/portable/reference.py")
    _git(repository, "commit", "-m", "track reference imports")
    return package, driver


def _capture_preflight(repository: Path) -> ReferencePreflight:
    return ReferencePreflight(
        "a" * 40,
        repository,
        repository / "specification",
        repository / "specification/reference/python-aaaaaaa.json",
        repository / "specification/reference/python-aaaaaaa.environment.json",
        {},
    )


def _git(repository: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True, text=True)


def _link_or_classify(
    monkeypatch: pytest.MonkeyPatch, path: Path, target: Path, *, directory: bool
) -> None:
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError:
        if directory:
            path.mkdir()
        else:
            path.touch()
        original = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda candidate: candidate == path or original(candidate),
        )
