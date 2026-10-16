"""Focused publication and verification tests for release freezing."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).parents[1]


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


assets_module = _module("portable_release_assets", ROOT / "scripts" / "portable_release_assets.py")
freeze_module = _module("freeze_release_test", ROOT / "scripts" / "freeze_release.py")


def _ignore_generated_outputs(directory: str, names: list[str]) -> set[str]:
    if Path(directory) == ROOT / "specification":
        return {"releases", "reports"}.intersection(names)
    return set()


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "specification"
    shutil.copytree(ROOT / "specification", root, ignore=_ignore_generated_outputs)
    return root


def _read(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_freeze_writes_closed_manifest_and_verify_reloads_it(tmp_path: Path) -> None:
    root = _tree(tmp_path)

    assets = freeze_module.freeze_release(root, "reference/python-fc53787.json", "core-generation-v0")

    release = root / "releases" / "core-generation-v0.json"
    document = _read(release)
    inventory = _read(root / "inventories" / "core-generation-v0.json")
    assert assets.release_path == release
    assert document["reference_manifest"] == "specification/reference/python-fc53787.json"
    assert len(document["files"]) == 106
    assert list(document["files"]) == sorted(document["files"])
    assert len(document["case_inventory"]) == 102
    assert document["case_inventory"] == inventory["cases"]
    for name, digest in document["files"].items():
        assert digest == _hash(root / Path(*name.split("/")[1:]))
    assert freeze_module.verify_release(root, "core-generation-v0").release_sha256 == _hash(release)


def test_freeze_derives_counts_from_selected_inventory_without_hardcoded_gates(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    inventory_path = root / "inventories" / "core-generation-v0.json"
    inventory = _read(inventory_path)
    cases = inventory["cases"]
    assert isinstance(cases, list)
    cases.append(
        {
            "id": "driver/selected-inventory-delta",
            "kind": "driver_assertion",
            "path": None,
            "family": "driver",
            "extension": None,
            "recipe_ref": "driver/selected-inventory-delta",
        }
    )
    _write(inventory_path, inventory)

    hashes, selected = freeze_module._input_paths(root, "reference/python-fc53787.json")

    assert len(selected) == 103
    assert len(hashes) == 106
    assert selected[-1]["id"] == "driver/selected-inventory-delta"


def test_freeze_uses_inventory_not_future_fixture_globs_or_reports(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    future = root / "fixtures" / "core-generation" / "future.json"
    future.write_text('{"expected":{"status":"observed"}}\n', encoding="utf-8")
    report = root / "reports" / "python-future.json"
    report.parent.mkdir()
    report.write_text("{}\n", encoding="utf-8")

    freeze_module.freeze_release(root, "reference/python-fc53787.json", "core-generation-v0")

    document = _read(root / "releases" / "core-generation-v0.json")
    assert "specification/fixtures/core-generation/future.json" not in document["files"]
    assert "specification/reports/python-future.json" not in document["files"]
    assert "specification/releases/core-generation-v0.json" not in document["files"]


@pytest.mark.parametrize("mutation", ("missing", "pending", "unsafe"))
def test_freeze_refuses_invalid_inputs_without_leaving_a_candidate(tmp_path: Path, mutation: str) -> None:
    root = _tree(tmp_path)
    if mutation == "missing":
        (root / "README.md").unlink()
        reference = "reference/python-fc53787.json"
    elif mutation == "pending":
        fixture = root / "fixtures" / "core-generation" / "repair" / "invalid-then-valid.json"
        document = _read(fixture)
        document["expected"]["status"] = "to_be_observed"
        _write(fixture, document)
        reference = "reference/python-fc53787.json"
    else:
        reference = "../reference/python-fc53787.json"

    with pytest.raises(assets_module.ReleaseBindingError):
        freeze_module.freeze_release(root, reference, "core-generation-v0")
    assert not (root / "releases" / "core-generation-v0.json").exists()


def test_verify_refuses_changed_bound_input(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    freeze_module.freeze_release(root, "reference/python-fc53787.json", "core-generation-v0")
    (root / "README.md").write_text("changed\n", encoding="utf-8")

    with pytest.raises(assets_module.ReleaseBindingError, match="hash mismatch"):
        freeze_module.verify_release(root, "core-generation-v0")


def test_freeze_preserves_existing_release_collision(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    existing = root / "releases" / "core-generation-v0.json"
    existing.parent.mkdir()
    existing.write_bytes(b"existing release bytes")

    with pytest.raises(FileExistsError):
        freeze_module.freeze_release(root, "reference/python-fc53787.json", "core-generation-v0")
    assert existing.read_bytes() == b"existing release bytes"


def test_failed_final_qualification_removes_owned_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tree(tmp_path)

    def fail_after_publish(*_args: object, **_kwargs: object) -> object:
        raise assets_module.ReleaseBindingError("controlled qualification failure")

    monkeypatch.setattr(freeze_module, "load_release_assets", fail_after_publish)
    with pytest.raises(assets_module.ReleaseBindingError, match="controlled qualification failure"):
        freeze_module.freeze_release(root, "reference/python-fc53787.json", "core-generation-v0")
    assert not (root / "releases" / "core-generation-v0.json").exists()


def test_failed_write_removes_owned_partial_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tree(tmp_path)

    def partial_write(descriptor: int, payload: bytes) -> None:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload[:17])
        raise OSError("controlled partial write failure")

    monkeypatch.setattr(freeze_module, "_write_payload", partial_write)
    with pytest.raises(OSError, match="controlled partial write failure"):
        freeze_module.freeze_release(root, "reference/python-fc53787.json", "core-generation-v0")
    assert not (root / "releases" / "core-generation-v0.json").exists()


def test_failed_qualification_preserves_same_byte_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tree(tmp_path)

    def replace_then_fail(_root: Path, output: Path) -> object:
        replacement = output.with_name("replacement.json")
        replacement.write_bytes(output.read_bytes())
        replacement.replace(output)
        raise assets_module.ReleaseBindingError("controlled qualification failure")

    monkeypatch.setattr(freeze_module, "load_release_assets", replace_then_fail)
    with pytest.raises(assets_module.ReleaseBindingError, match="controlled qualification failure"):
        freeze_module.freeze_release(root, "reference/python-fc53787.json", "core-generation-v0")
    replacement = root / "releases" / "core-generation-v0.json"
    assert replacement.exists()
    assert replacement.read_bytes()


def test_freeze_opens_portably_without_windows_binary_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tree(tmp_path)
    monkeypatch.delattr(freeze_module.os, "O_BINARY", raising=False)

    freeze_module.freeze_release(root, "reference/python-fc53787.json", "core-generation-v0")

    assert (root / "releases" / "core-generation-v0.json").is_file()
