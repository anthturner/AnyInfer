"""Synthetic sealed-tree tests for portable release binding."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "portable_release_assets_test", ROOT / "scripts" / "portable_release_assets.py"
)
assert SPEC and SPEC.loader
assets_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = assets_module
SPEC.loader.exec_module(assets_module)


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(
    tmp_path: Path, *, name: str = "specification", extra_lock: bool = False
) -> tuple[Path, Path]:
    root = tmp_path / name
    shutil.copytree(ROOT / "specification", root)
    inventory = json.loads((root / "inventories" / "core-generation-v0.json").read_text())
    for fixture in (root / "fixtures" / "core-generation").rglob("*.json"):
        doc = json.loads(fixture.read_text())
        doc["expected"]["status"] = "observed"
        _write(fixture, doc)
    for case in inventory["cases"]:
        if case["kind"] == "fixture" and case["path"].startswith(
            "specification/fixtures/transport/"
        ):
            _write(
                root / Path(*case["path"].split("/")[1:]),
                {
                    "fixture_version": "0",
                    "id": case["id"],
                    "family": "transport/openai-chat",
                    "profile": "core-generation",
                    "description": "synthetic",
                    "kind": "adapter",
                    "input": {
                        "adapter_config": {
                            "provider_id": "openai-compat",
                            "base_url": "https://fixture.invalid/v1",
                            "api_key": "fixture-token",
                            "headers": {},
                            "timeout_s": 120,
                        },
                        "wire": {
                            "model": "synthetic",
                            "messages": [{"role": "user", "text": "hello"}],
                            "sampling": {},
                            "mechanism": None,
                            "stream": True,
                            "timeout_s": 120,
                            "max_response_bytes": 1024,
                        },
                    },
                    "responses": [],
                    "expected": {
                        "status": "observed",
                        "http_requests": [],
                        "wire_limits": [],
                        "adapter_outcome": {"events": []},
                    },
                },
            )
    names = [
        "anyinfer",
        "httpx2",
        "jsonschema",
        "jsonschema-specifications",
        "referencing",
        "attrs",
        "rpds-py",
    ]
    if extra_lock:
        names.append("extra-package")
    lock: dict[str, dict[str, object]] = {
        item: {
            "version": "1",
            "requires": [],
            "metadata_sha256": "b" * 64,
            "record_sha256": None,
            "direct_url_sha256": None,
        }
        for item in names
    }
    revision = "a" * 40
    validator = {
        "selected": "synthetic",
        "defaults": "synthetic",
        "resource_identities": [{"uri": "synthetic://validator", "sha256": "e" * 64}],
    }
    environment = {
        "environment_version": "0",
        "reference_run_revision": revision,
        "interpreter": {"implementation": "CPython", "version": "3.13"},
        "dependency_lock": lock,
        "imports": {
            "anyinfer": {"path": "src", "sha256": "c" * 64},
            "driver": {"path": "tests", "sha256": "d" * 64},
        },
        "loaded_modules": {"anyinfer": {"path": "src", "sha256": "c" * 64}},
        "validator": validator,
        "warning_policy": {
            "mode": "error",
            "filters": [
                {
                    "action": "error",
                    "message": None,
                    "category": "builtins.Warning",
                    "module": None,
                    "lineno": 0,
                }
            ],
        },
    }
    env = root / "reference" / "python-aaaaaaa.environment.json"
    _write(env, environment)
    ref = root / "reference" / "python-aaaaaaa.json"
    _write(
        ref,
        {
            "implementation": "anyinfer-python",
            "reference_run_revision": revision,
            "source_tree": {"clean": True},
            "driver": {"path": "tests/testing/portable/", "git_revision": revision},
            "interpreter": "CPython 3.13",
            "environment": {
                "path": "specification/reference/python-aaaaaaa.environment.json",
                "sha256": _hash(env),
            },
            "packages": {key: row["version"] for key, row in lock.items()},
            "validator": validator,
            "warning_policy": "error",
            "produced_at": "2026-01-01T00:00:00Z",
        },
    )
    files = [
        "specification/README.md",
        "specification/core-generation.md",
        "specification/MAINTENANCE.md",
        "specification/inventories/core-generation-v0.json",
        "specification/reference/python-aaaaaaa.json",
        "specification/reference/python-aaaaaaa.environment.json",
    ]
    files += [
        f"specification/schemas/{item}"
        for item in (
            "fixture-v0.schema.json",
            "transport-v0.schema.json",
            "inventory-v0.schema.json",
            "report-v0.schema.json",
        )
    ]
    files += [case["path"] for case in inventory["cases"] if case["kind"] == "fixture"]
    release = {
        "release": "core-generation-v0",
        "profile": "core-generation",
        "profile_revision": "v0",
        "created_at": "2026-01-01T00:00:00Z",
        "reference_manifest": "specification/reference/python-aaaaaaa.json",
        "files": {path: _hash(root / Path(*path.split("/")[1:])) for path in sorted(files)},
        "case_inventory": inventory["cases"],
    }
    release_path = root / "releases" / "core-generation-v0.json"
    _write(release_path, release)
    return root, release_path


def _result() -> dict[str, Any]:
    return {
        "text": "extension",
        "structured": None,
        "target": {"provider_id": "synthetic", "model": "synthetic"},
        "finish_reason": "stop",
        "usage": {
            "input_tokens": 1,
            "output_tokens": None,
            "total_tokens": None,
            "cache_read_tokens": None,
            "cache_write_tokens": None,
            "reasoning_tokens": None,
        },
        "timing": {"first_token_ms": "null", "total_ms": "present"},
        "structured_mechanism": None,
        "repair_attempts": 0,
        "attempts": [],
        "warnings": [],
    }


def _report(
    assets: Any, *, implementation: str = "anyinfer-python", extension: bool = False
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in assets.cases_by_id.values():
        row: dict[str, Any] = {
            "id": case["id"],
            "verdict": "pass",
            "detail": None,
            "evidence": None,
        }
        if case["kind"] == "driver_assertion":
            row["evidence"] = {"recipe_ref": case["recipe_ref"], "observations": {"native": True}}
        if extension and case["extension"]:
            row.update(
                {
                    "verdict": "extension",
                    "evidence": {"native_outcome": {"result": _result()}, "adapter_entries": []},
                }
            )
        rows.append(row)
    return {
        "report_version": "0",
        "release": assets.release["release"],
        "release_sha256": assets.release_sha256,
        "implementation": {
            "name": implementation,
            "version": "1",
            "source_revision": "e" * 40,
            "driver_revision": "f" * 40,
            "runtime": "synthetic",
            "os": "synthetic",
            "dependencies": {},
            "extensions": sorted(
                assets_module._EXTENSIONS
                if implementation == "anyinfer-python"
                else {
                    case["extension"]
                    for case in assets.cases_by_id.values()
                    if extension and case["extension"]
                }
            ),
        },
        "cases": rows,
        "counts": {
            name: sum(row["verdict"] == name for row in rows)
            for name in ("pass", "fail", "error", "extension")
        },
    }


def _assets(tmp_path: Path, **kwargs: Any) -> Any:
    root, release = _tree(tmp_path, **kwargs)
    return assets_module.load_release_assets(root, release)


def test_positive_arbitrary_root_immutable_assets_and_future_file(tmp_path: Path) -> None:
    root, release = _tree(tmp_path, name="chosen-root", extra_lock=True)
    (root / "fixtures" / "core-generation" / "future.json").write_text("{}", encoding="utf-8")
    assets = assets_module.load_release_assets(root, release)
    assert assets.environment["dependency_lock"]["extra-package"]["version"] == "1"
    nested = next(iter(assets.cases_by_id.values()))
    with pytest.raises(TypeError):
        nested["id"] = "changed"
    report = _report(assets)
    report["implementation"]["driver_revision"] = report["implementation"]["source_revision"]
    assets_module.require_comparable_reports(report, copy.deepcopy(report), assets)


@pytest.mark.parametrize(
    "mutation",
    ["hash", "missing", "extra", "inventory", "pending", "reference", "environment", "normative"],
)
def test_closed_release_negative_matrix(tmp_path: Path, mutation: str) -> None:
    root, release = _tree(tmp_path)
    data = json.loads(release.read_text())
    if mutation == "hash":
        data["files"]["specification/README.md"] = "0" * 64
    elif mutation == "missing":
        data["files"].pop("specification/README.md")
    elif mutation == "extra":
        data["files"]["specification/extra.json"] = "0" * 64
    elif mutation == "inventory":
        data["case_inventory"].pop()
    elif mutation == "pending":
        case = next(item for item in data["case_inventory"] if item["kind"] == "fixture")
        path = root / Path(*case["path"].split("/")[1:])
        doc = json.loads(path.read_text())
        doc["expected"]["status"] = "to_be_observed"
        _write(path, doc)
    elif mutation == "reference":
        path = root / "reference" / "python-aaaaaaa.json"
        doc = json.loads(path.read_text())
        doc["source_tree"] = {"clean": False}
        _write(path, doc)
        data["files"]["specification/reference/python-aaaaaaa.json"] = _hash(path)
    elif mutation == "environment":
        path = root / "reference" / "python-aaaaaaa.environment.json"
        doc = json.loads(path.read_text())
        doc["dependency_lock"].pop("anyinfer")
        _write(path, doc)
    else:
        (root / "README.md").write_text("changed", encoding="utf-8")
    _write(release, data)
    with pytest.raises(assets_module.ReleaseBindingError):
        assets_module.load_release_assets(root, release)


def test_release_binding_rejects_pending_transport_before_qualification(tmp_path: Path) -> None:
    root, release = _tree(tmp_path)
    data = json.loads(release.read_text())
    record = next(
        item
        for item in data["case_inventory"]
        if item["kind"] == "fixture" and item["id"].startswith("transport/")
    )
    fixture = root / Path(*record["path"].split("/")[1:])
    document = json.loads(fixture.read_text())
    document["expected"] = {"status": "to_be_observed"}
    _write(fixture, document)
    data["files"][record["path"]] = _hash(fixture)
    _write(release, data)

    with pytest.raises(assets_module.ReleaseBindingError, match="pending expectation"):
        assets_module.load_release_assets(root, release)


def test_unbound_requirement_markdown_target_is_rejected(tmp_path: Path) -> None:
    root, release = _tree(tmp_path)
    future = root / "future.md"
    future.write_text("## Request normalization\n", encoding="utf-8")
    inventory_path = root / "inventories" / "core-generation-v0.json"
    inventory = json.loads(inventory_path.read_text())
    inventory["requirements"][0]["spec_ref"] = "specification/future.md#request-normalization"
    _write(inventory_path, inventory)
    release_data = json.loads(release.read_text())
    release_data["files"]["specification/inventories/core-generation-v0.json"] = _hash(
        inventory_path
    )
    _write(release, release_data)
    with pytest.raises(assets_module.ReleaseBindingError):
        assets_module.load_release_assets(root, release)


@pytest.mark.parametrize(
    "mutation",
    [
        "environment-selected",
        "environment-defaults",
        "manifest-selected",
        "manifest-defaults",
        "empty-resources",
        "duplicate-resource-uri",
        "reference-prefix",
        "environment-prefix",
    ],
)
def test_reference_identity_and_validator_shape_fail_closed(tmp_path: Path, mutation: str) -> None:
    root, release = _tree(tmp_path)
    environment_path = root / "reference" / "python-aaaaaaa.environment.json"
    reference_path = root / "reference" / "python-aaaaaaa.json"
    environment = json.loads(environment_path.read_text())
    reference = json.loads(reference_path.read_text())
    if mutation == "environment-selected":
        environment["validator"].pop("selected")
    elif mutation == "environment-defaults":
        environment["validator"].pop("defaults")
    elif mutation == "manifest-selected":
        reference["validator"].pop("selected")
    elif mutation == "manifest-defaults":
        reference["validator"].pop("defaults")
    elif mutation == "empty-resources":
        environment["validator"]["resource_identities"] = []
        reference["validator"]["resource_identities"] = []
    elif mutation == "duplicate-resource-uri":
        row = environment["validator"]["resource_identities"][0]
        environment["validator"]["resource_identities"].append(
            {"uri": row["uri"], "sha256": "f" * 64}
        )
        reference["validator"]["resource_identities"] = environment["validator"][
            "resource_identities"
        ]
    elif mutation == "reference-prefix":
        reference["reference_run_revision"] = "b" * 40
        reference["driver"]["git_revision"] = "b" * 40
    else:
        reference["environment"]["path"] = (
            "specification/reference/python-bbbbbbb.environment.json"
        )
    _write(environment_path, environment)
    reference["environment"]["sha256"] = _hash(environment_path)
    _write(reference_path, reference)
    release_data = json.loads(release.read_text())
    release_data["files"]["specification/reference/python-aaaaaaa.environment.json"] = _hash(
        environment_path
    )
    release_data["files"]["specification/reference/python-aaaaaaa.json"] = _hash(reference_path)
    _write(release, release_data)
    with pytest.raises(assets_module.ReleaseBindingError):
        assets_module.load_release_assets(root, release)


def test_path_aliases_and_link_root_fail_closed(tmp_path: Path) -> None:
    root, release = _tree(tmp_path)
    for path in (
        Path("releases/../releases/core-generation-v0.json"),
        Path("core-generation-v0.json"),
    ):
        with pytest.raises(assets_module.ReleaseBindingError):
            assets_module.load_release_assets(root, path)
    link = tmp_path / "linked"
    try:
        link.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("links unavailable")
    with pytest.raises(assets_module.ReleaseBindingError):
        assets_module.load_release_assets(link, release)


def test_direct_mapping_cannot_bypass_qualification(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    good = _report(assets)
    bads: list[dict[str, Any]] = []
    duplicate = copy.deepcopy(good)
    duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
    bads.append(duplicate)
    missing = copy.deepcopy(good)
    missing["cases"].pop()
    bads.append(missing)
    extra = copy.deepcopy(good)
    extra["cases"][0]["id"] = "extra"
    bads.append(extra)
    stale = copy.deepcopy(good)
    stale["counts"]["pass"] -= 1
    bads.append(stale)
    failed = copy.deepcopy(good)
    failed["cases"][0]["verdict"] = "fail"
    failed["counts"] = {
        key: sum(row["verdict"] == key for row in failed["cases"]) for key in failed["counts"]
    }
    bads.append(failed)
    zero = copy.deepcopy(good)
    zero["implementation"]["source_revision"] = "0" * 40
    bads.append(zero)
    driver = copy.deepcopy(good)
    next(row for row in driver["cases"] if row["id"].startswith("driver/"))["evidence"] = {
        "recipe_ref": "wrong",
        "observations": {},
    }
    bads.append(driver)
    for bad in bads:
        with pytest.raises(assets_module.ReleaseBindingError):
            assets_module.require_comparable_reports(bad, good, assets)


@pytest.mark.parametrize(
    "outcome",
    [
        "undeclared",
        "ineligible",
        "cancelled",
        "CancelledError",
        "KeyboardInterrupt",
        "SystemExit",
        "GeneratorExit",
        "empty-result",
        "bad-target",
    ],
)
def test_extension_evidence_negative_matrix(tmp_path: Path, outcome: str) -> None:
    assets = _assets(tmp_path)
    report = _report(assets, extension=True)
    row = next(item for item in report["cases"] if item["verdict"] == "extension")
    if outcome == "undeclared":
        report["implementation"]["extensions"] = []
    elif outcome == "ineligible":
        row["id"] = next(
            case_id for case_id, case in assets.cases_by_id.items() if not case["extension"]
        )
    elif outcome in {
        "cancelled",
        "CancelledError",
        "KeyboardInterrupt",
        "SystemExit",
        "GeneratorExit",
    }:
        row["evidence"]["native_outcome"] = {
            "error": {
                "category": "cancelled" if outcome == "cancelled" else None,
                "native_type": outcome,
                "message": "x",
            }
        }
    elif outcome == "empty-result":
        row["evidence"]["native_outcome"] = {"result": {}}
    else:
        row["evidence"]["native_outcome"]["result"]["target"] = {"provider_id": "x"}
    report["counts"] = {
        key: sum(item["verdict"] == key for item in report["cases"]) for key in report["counts"]
    }
    with pytest.raises(assets_module.ReleaseBindingError):
        assets_module.require_comparable_reports(report, report, assets)


@pytest.mark.parametrize(
    "field",
    [
        "text",
        "structured",
        "finish_reason",
        "usage",
        "timing",
        "structured_mechanism",
        "repair_attempts",
        "attempts",
        "warnings",
    ],
)
def test_extension_result_named_field_validation(tmp_path: Path, field: str) -> None:
    assets = _assets(tmp_path)
    report = _report(assets, extension=True)
    row = next(item for item in report["cases"] if item["verdict"] == "extension")
    result = row["evidence"]["native_outcome"]["result"]
    invalid = {
        "text": 1,
        "structured": {"bad": float("nan")},
        "finish_reason": "unknown",
        "usage": {"input_tokens": True},
        "timing": {"first_token_ms": "present", "total_ms": None},
        "structured_mechanism": "unknown",
        "repair_attempts": -1,
        "attempts": [{"target": "x", "outcome": "failed"}],
        "warnings": [1],
    }
    result[field] = invalid[field]
    with pytest.raises(assets_module.ReleaseBindingError):
        assets_module.require_comparable_reports(report, report, assets)


def test_extension_none_and_bounded_json_domain(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    report = _report(assets, extension=True)
    row = next(item for item in report["cases"] if item["verdict"] == "extension")
    row["evidence"]["native_outcome"] = {"none": True}
    assets_module.require_comparable_reports(report, copy.deepcopy(report), assets)
    for endpoint in (-(2**63), 2**63):
        endpoint_report = copy.deepcopy(report)
        driver = next(row for row in endpoint_report["cases"] if row["id"].startswith("driver/"))
        driver["evidence"]["observations"] = {"endpoint": endpoint}
        assets_module.require_comparable_reports(endpoint_report, report, assets)
    for invalid in (-(2**63) - 1, 2**63 + 1, float("inf"), "\ud800"):
        bad = copy.deepcopy(report)
        driver = next(row for row in bad["cases"] if row["id"].startswith("driver/"))
        driver["evidence"]["observations"] = {"invalid": invalid}
        with pytest.raises(assets_module.ReleaseBindingError):
            assets_module.require_comparable_reports(bad, report, assets)
    bad_key = copy.deepcopy(report)
    bad_key["implementation"]["dependencies"] = {"\ud800": "x"}
    with pytest.raises(assets_module.ReleaseBindingError):
        assets_module.require_comparable_reports(bad_key, report, assets)


def test_extension_comparison_positive_asymmetry_and_reverse(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    reference_ext, other_pass = (
        _report(assets, extension=True),
        _report(assets, implementation="native"),
    )
    assets_module.require_comparable_reports(reference_ext, other_pass, assets)
    assets_module.require_comparable_reports(other_pass, reference_ext, assets)
    assets_module.require_comparable_reports(
        _report(assets, extension=True),
        _report(assets, implementation="native", extension=True),
        assets,
    )
    with pytest.raises(assets_module.ReleaseBindingError):
        assets_module.require_comparable_reports(
            _report(assets), _report(assets, implementation="native", extension=True), assets
        )


def test_successful_case_validation_accepts_development_view_and_refuses_fatal_extension(
    tmp_path: Path,
) -> None:
    assets = _assets(tmp_path)
    development_rows = copy.deepcopy(_report(assets)["cases"])
    for row in development_rows:
        if assets.cases_by_id[row["id"]]["kind"] == "fixture":
            row["observations"] = {}
    validated = assets_module.validate_successful_cases(
        development_rows,
        assets.cases_by_id,
        declared_extensions=sorted(assets_module._EXTENSIONS),
        specification_root=assets.specification_root,
        require_python_extensions=True,
        development_observation=True,
    )
    assert set(validated) == set(assets.cases_by_id)

    extension_rows = _report(assets, extension=True)["cases"]
    extension = next(row for row in extension_rows if row["verdict"] == "extension")
    extension["evidence"]["native_outcome"] = {
        "error": {"category": None, "native_type": "KeyboardInterrupt", "message": "stop"}
    }
    with pytest.raises(assets_module.ReleaseBindingError, match="cancellation/fatal"):
        assets_module.validate_successful_cases(
            extension_rows,
            assets.cases_by_id,
            declared_extensions=sorted(assets_module._EXTENSIONS),
            specification_root=assets.specification_root,
            require_python_extensions=True,
        )

def test_successful_case_development_shapes_distinguish_fixture_and_driver(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    rows = copy.deepcopy(_report(assets)["cases"])
    fixture = next(row for row in rows if assets.cases_by_id[row["id"]]["kind"] == "fixture")
    driver = next(
        row for row in rows if assets.cases_by_id[row["id"]]["kind"] == "driver_assertion"
    )
    fixture["observations"] = {}
    driver["observations"] = {}
    with pytest.raises(assets_module.ReleaseBindingError, match="development driver observation"):
        assets_module.validate_successful_cases(
            rows,
            assets.cases_by_id,
            declared_extensions=sorted(assets_module._EXTENSIONS),
            specification_root=assets.specification_root,
            require_python_extensions=True,
            development_observation=True,
        )

    driver.pop("observations")
    fixture.pop("observations")
    with pytest.raises(assets_module.ReleaseBindingError, match="development fixture observation"):
        assets_module.validate_successful_cases(
            rows,
            assets.cases_by_id,
            declared_extensions=sorted(assets_module._EXTENSIONS),
            specification_root=assets.specification_root,
            require_python_extensions=True,
            development_observation=True,
        )

def _development_rows(assets: Any, *, extension: bool = False) -> list[dict[str, Any]]:
    rows = cast(list[dict[str, Any]], copy.deepcopy(_report(assets, extension=extension)["cases"]))
    for row in rows:
        if assets.cases_by_id[row["id"]]["kind"] == "fixture":
            row["observations"] = {}
    return rows


@pytest.mark.parametrize("value", [float("nan"), "\ud800", 2**63 + 1])
def test_successful_case_development_evidence_rejects_non_ordinary_json(
    tmp_path: Path, value: object
) -> None:
    assets = _assets(tmp_path)
    rows = _development_rows(assets)
    driver = next(
        row for row in rows if assets.cases_by_id[row["id"]]["kind"] == "driver_assertion"
    )
    driver["evidence"]["observations"]["nested"] = value
    with pytest.raises(assets_module.ReleaseBindingError, match="bounded ordinary JSON"):
        assets_module.validate_successful_cases(
            rows,
            assets.cases_by_id,
            declared_extensions=sorted(assets_module._EXTENSIONS),
            specification_root=assets.specification_root,
            require_python_extensions=True,
            development_observation=True,
        )


def test_successful_case_development_accepts_bounded_nested_evidence(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    rows = _development_rows(assets, extension=True)
    driver = next(
        row for row in rows if assets.cases_by_id[row["id"]]["kind"] == "driver_assertion"
    )
    driver["evidence"]["observations"]["bounds"] = {"low": -(2**63), "high": 2**63}
    extension = next(row for row in rows if row["verdict"] == "extension")
    extension["evidence"]["native_outcome"]["result"]["warnings"] = ["nested-control"]
    validated = assets_module.validate_successful_cases(
        rows,
        assets.cases_by_id,
        declared_extensions=sorted(assets_module._EXTENSIONS),
        specification_root=assets.specification_root,
        require_python_extensions=True,
        development_observation=True,
    )
    assert set(validated) == set(assets.cases_by_id)

def test_successful_case_selected_schema_unresolved_ref_has_binding_cause(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    schema_path = assets.specification_root / "schemas" / "report-v0.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["$defs"]["case"] = {"$ref": "missing"}
    _write(schema_path, schema)
    with pytest.raises(assets_module.ReleaseBindingError, match="schema evaluation failed") as error:
        assets_module.validate_successful_cases(
            _report(assets)["cases"],
            assets.cases_by_id,
            declared_extensions=sorted(assets_module._EXTENSIONS),
            specification_root=assets.specification_root,
            require_python_extensions=True,
        )
    assert error.value.__cause__ is not None
