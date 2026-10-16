"""CLI and API tests for sealed portable report comparison."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
COMPARE = ROOT / "scripts" / "compare_reports.py"
ASSETS = ROOT / "scripts" / "portable_release_assets.py"
ASSETS_SPEC = importlib.util.spec_from_file_location("portable_release_assets", ASSETS)
assert ASSETS_SPEC and ASSETS_SPEC.loader
assets_support = importlib.util.module_from_spec(ASSETS_SPEC)
sys.modules[ASSETS_SPEC.name] = assets_support
ASSETS_SPEC.loader.exec_module(assets_support)
SPEC = importlib.util.spec_from_file_location("compare_reports_test", COMPARE)
assert SPEC and SPEC.loader
compare_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare_module)

# This existing synthetic builder is the release-binding test oracle. It creates a
# sealed selected specification tree without reimplementing binding policy here.
SUPPORT = importlib.util.spec_from_file_location(
    "portable_release_support", ROOT / "tests" / "test_portable_release_assets.py"
)
assert SUPPORT and SUPPORT.loader
support = importlib.util.module_from_spec(SUPPORT)
sys.modules[SUPPORT.name] = support
SUPPORT.loader.exec_module(support)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _reports(tmp_path: Path) -> tuple[Path, Path, Any]:
    root, release = support._tree(tmp_path, name="chosen-specification")
    assets = compare_module.load_release_assets(root, release)
    left = support._report(assets)
    right = support._report(assets, implementation="native")
    left_path, right_path = tmp_path / "left.json", tmp_path / "right.json"
    _write(left_path, left)
    _write(right_path, right)
    return left_path, right_path, assets


def test_compare_reports_api_accepts_qualified_reports(tmp_path: Path) -> None:
    left, right, assets = _reports(tmp_path)
    for path in (left, right):
        report = json.loads(path.read_text(encoding="utf-8"))
        report["implementation"]["driver_revision"] = report["implementation"][
            "source_revision"
        ]
        _write(path, report)
    loaded, _left, _right, allowed = compare_module.compare_reports(
        left, right, specification_root=assets.specification_root, release_path=assets.release_path
    )
    assert loaded.release_sha256 == assets.release_sha256
    assert allowed == []


def test_compare_reports_cli_accepts_real_helper_binding(tmp_path: Path) -> None:
    left, right, assets = _reports(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(COMPARE),
            str(left),
            str(right),
            "--root",
            str(assets.specification_root),
            "--release",
            str(assets.release_path),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert f"release={assets.release['release']}" in result.stdout
    assert f"sha256={assets.release_sha256}" in result.stdout
    assert f"cases={len(assets.cases_by_id)}" in result.stdout


def test_compare_reports_cli_rejects_wrong_hash(tmp_path: Path) -> None:
    left, right, assets = _reports(tmp_path)
    report = json.loads(left.read_text(encoding="utf-8"))
    report["release_sha256"] = "0" * 64
    _write(left, report)
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(COMPARE),
            str(left),
            str(right),
            "--root",
            str(assets.specification_root),
            "--release",
            str(assets.release_path),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 1
    assert "untrusted" in result.stderr


@pytest.mark.parametrize(
    "mutation", ["empty", "missing", "extra", "duplicate", "stale", "fail", "error"]
)
def test_compare_reports_rejects_report_case_qualification_failures(
    tmp_path: Path, mutation: str
) -> None:
    left_path, right_path, assets = _reports(tmp_path)
    left = json.loads(left_path.read_text(encoding="utf-8"))
    if mutation == "empty":
        left["cases"] = []
    elif mutation == "missing":
        left["cases"].pop()
    elif mutation == "extra":
        left["cases"][0]["id"] = "extra/case"
    elif mutation == "duplicate":
        left["cases"].append(copy.deepcopy(left["cases"][0]))
    elif mutation == "stale":
        left["counts"]["pass"] -= 1
    else:
        left["cases"][0]["verdict"] = mutation
        left["counts"] = {
            verdict: sum(row["verdict"] == verdict for row in left["cases"])
            for verdict in ("pass", "fail", "error", "extension")
        }
    _write(left_path, left)
    with pytest.raises(compare_module.ReleaseBindingError):
        compare_module.compare_reports(
            left_path,
            right_path,
            specification_root=assets.specification_root,
            release_path=assets.release_path,
        )


@pytest.mark.parametrize("mutation", ["release", "driver", "undeclared", "ineligible"])
def test_compare_reports_rejects_identity_and_extension_qualification_failures(
    tmp_path: Path, mutation: str
) -> None:
    left_path, right_path, assets = _reports(tmp_path)
    left = json.loads(left_path.read_text(encoding="utf-8"))
    if mutation == "release":
        left["release"] = "other"
    elif mutation == "driver":
        driver = next(row for row in left["cases"] if row["id"].startswith("driver/"))
        driver["evidence"] = None
    else:
        eligible = next(
            case for case in assets.cases_by_id.values() if case["extension"] is not None
        )
        selected = (
            eligible
            if mutation == "undeclared"
            else next(case for case in assets.cases_by_id.values() if case["extension"] is None)
        )
        row = next(row for row in left["cases"] if row["id"] == selected["id"])
        row["verdict"] = "extension"
        row["evidence"] = {"native_outcome": {"none": True}, "adapter_entries": []}
        left["implementation"]["extensions"] = (
            [] if mutation == "undeclared" else [eligible["extension"]]
        )
        left["counts"] = {
            verdict: sum(row["verdict"] == verdict for row in left["cases"])
            for verdict in ("pass", "fail", "error", "extension")
        }
    _write(left_path, left)
    with pytest.raises(compare_module.ReleaseBindingError):
        compare_module.compare_reports(
            left_path,
            right_path,
            specification_root=assets.specification_root,
            release_path=assets.release_path,
        )


def test_compare_reports_accepts_only_reference_extension_to_other_pass_and_rejects_reverse(
    tmp_path: Path,
) -> None:
    left_path, right_path, assets = _reports(tmp_path)
    reference = support._report(assets, extension=True)
    other = support._report(assets, implementation="native")
    _write(left_path, reference)
    _write(right_path, other)
    _assets, _left, _right, allowed = compare_module.compare_reports(
        left_path,
        right_path,
        specification_root=assets.specification_root,
        release_path=assets.release_path,
    )
    expected = sorted(
        case["id"] for case in assets.cases_by_id.values() if case["extension"] is not None
    )
    assert allowed == expected

    _write(left_path, other)
    _write(right_path, reference)
    _assets, _left, _right, reversed_allowed = compare_module.compare_reports(
        left_path,
        right_path,
        specification_root=assets.specification_root,
        release_path=assets.release_path,
    )
    assert reversed_allowed == expected

    forbidden = support._report(assets)
    native_extension = support._report(assets, implementation="native", extension=True)
    _write(left_path, forbidden)
    _write(right_path, native_extension)
    with pytest.raises(compare_module.ReleaseBindingError):
        compare_module.compare_reports(
            left_path,
            right_path,
            specification_root=assets.specification_root,
            release_path=assets.release_path,
        )


@pytest.mark.parametrize("asset", ["normative", "reference"])
def test_compare_reports_rejects_changed_bound_assets(tmp_path: Path, asset: str) -> None:
    left, right, assets = _reports(tmp_path)
    target = (
        assets.specification_root / "core-generation.md"
        if asset == "normative"
        else assets.specification_root / "reference" / "python-aaaaaaa.json"
    )
    target.write_text(target.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    with pytest.raises(compare_module.ReleaseBindingError):
        compare_module.compare_reports(
            left,
            right,
            specification_root=assets.specification_root,
            release_path=assets.release_path,
        )
