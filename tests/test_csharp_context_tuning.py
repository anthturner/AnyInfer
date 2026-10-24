"""Independent, pure controls for context-tuning paired-observation evidence."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).parents[1]
_CHECKER = _ROOT / "scripts" / "check_csharp_context_tuning.py"


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("context_tuning_checker", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checker_help_launches_from_repository_root_without_native_execution() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_csharp_context_tuning.py", "--help"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert "--input" in result.stdout
    assert result.stderr == ""


def _mapping() -> dict[str, Any]:
    return {
        "collapse_duplicates": False,
        "near_duplicate_threshold": 0.1,
        "shingle_size": 2,
        "selection_order": "density",
        "diversity": 0.2,
        "split_identifiers": True,
        "query_expansion": True,
        "expansion_terms": 3,
        "feedback_documents": 4,
        "expansion_weight": 0.5,
        "salience_weight": 0.6,
        "salience_damping": 0.7,
        "salience_iterations": 8,
        "compact_fallback": True,
        "chunk_tokens": 9,
        "rollup_share": 0.8,
        "carry_over_bonus": 0.9,
    }


def _success(*, merge: bool = False) -> dict[str, Any]:
    mapping = _mapping()
    return {
        "mapping": mapping,
        "round_trip": mapping.copy(),
        "ranking_is_default": False,
        "negative_zero_fields": [],
        "reused_instance": False if merge else None,
        "base_after": mapping.copy() if merge else None,
        "constants": {"default_chunk_tokens": 512, "selection_orders": ["rank", "density"]},
    }


def _record(case: Any, *, runtime: str) -> dict[str, Any]:
    if case.identifier == "native-overflow-shingle" and runtime == "csharp":
        public = {"error": {"type": "ArgumentException", "stage": "operation"}}
    else:
        public = _success(merge=case.kind == "merge")
        if case.identifier == "native-overflow-shingle":
            public["mapping"]["shingle_size"] = 9_223_372_036_854_775_808
            public["round_trip"]["shingle_size"] = 9_223_372_036_854_775_808
    return {"id": case.identifier, "kind": case.kind, "public": public}


def _run(checker: ModuleType, cases: tuple[Any, ...], runtime: str) -> dict[str, Any]:
    return {
        "profile": checker.PROFILE,
        "runtime": runtime,
        "source_revision": "a" * 40,
        "source_dirty": False,
        "corpus_sha256": checker.FROZEN_CORPUS_SHA256,
        "observations": [_record(case, runtime=runtime) for case in cases],
    }


def _read_run(
    checker: ModuleType,
    tmp_path: Path,
    payload: dict[str, Any],
    cases: tuple[Any, ...],
    runtime: str,
) -> Any:
    path = tmp_path / f"{runtime}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return checker.read_run(
        path,
        cases=cases,
        expected_runtime=runtime,
        expected_corpus_sha256=checker.FROZEN_CORPUS_SHA256,
    )


def test_frozen_input_and_all_declared_asset_hashes_are_admitted() -> None:
    checker = _checker()

    document, cases = checker.load_profile(checker.DEFAULT_INPUT)

    assert document["profile"] == checker.PROFILE
    assert len(cases) == 58
    assert {case.raw["domain"] for case in cases} == {"shared", "native_range"}
    assert all(
        len(value) == 64
        for value in (
            checker.FROZEN_CORPUS_SHA256,
            checker.FROZEN_SCHEMA_SHA256,
            checker.FROZEN_OBSERVATION_SCHEMA_SHA256,
            checker.FROZEN_README_SHA256,
        )
    )


def test_load_profile_rejects_a_same_path_mutated_frozen_corpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _checker()
    mutated = tmp_path / "inputs.json"
    document = json.loads(checker.DEFAULT_INPUT.read_text(encoding="utf-8"))
    document["cases"][0]["id"] = "renamed-default"
    mutated.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(checker, "DEFAULT_INPUT", mutated)

    with pytest.raises(checker.ObservationError, match="SHA-256 differs"):
        checker.load_profile(mutated)


@pytest.mark.parametrize("bad_version", (1.0, True))
def test_input_rejects_decoded_noninteger_versions(bad_version: object) -> None:
    checker = _checker()
    document, _ = checker.load_profile(checker.DEFAULT_INPUT)
    altered = copy.deepcopy(document)
    altered["format_version"] = bad_version

    with pytest.raises(checker.ObservationError, match="decoded JSON integer"):
        checker.validate_input(altered)


def test_input_rejects_one_bad_kind_domain_duplicate_and_extra_key() -> None:
    checker = _checker()
    document, _ = checker.load_profile(checker.DEFAULT_INPUT)
    for mutate, diagnostic in (
        (lambda value: value["cases"][0].update(kind="bad"), "invalid kind or domain"),
        (lambda value: value["cases"][0].update(domain="bad"), "invalid kind or domain"),
        (
            lambda value: value["cases"].append(copy.deepcopy(value["cases"][0])),
            "nonempty and unique",
        ),
        (lambda value: value["cases"][0].update(extra=True), "keys must be exactly"),
    ):
        altered = copy.deepcopy(document)
        mutate(altered)
        with pytest.raises(checker.ObservationError, match=diagnostic):
            checker.validate_input(altered)


@pytest.mark.parametrize(
    ("path", "diagnostic"),
    (
        ("mapping.shingle_size", "decoded JSON integer"),
        ("constants.default_chunk_tokens", "decoded JSON integer"),
        ("ranking_is_default", "decoded JSON boolean"),
    ),
)
def test_observation_rejects_one_wrong_scalar_type_at_a_time(path: str, diagnostic: str) -> None:
    checker = _checker()
    record = {"id": "default", "kind": "default", "public": _success()}
    parent: Any = record["public"]
    parts = path.split(".")
    for part in parts[:-1]:
        parent = parent[part]
    parent[parts[-1]] = 1.0 if "integer" in diagnostic else 1

    with pytest.raises(checker.ObservationError, match=diagnostic):
        checker.validate_observation(record)


def test_observation_rejects_bool_count_illegal_float_and_nonfinite_wire_value() -> None:
    checker = _checker()
    for key, value, diagnostic in (
        ("shingle_size", True, "decoded JSON integer"),
        ("selection_order", 1.0, "must be a string"),
        ("diversity", math.nan, "finite JSON number"),
    ):
        record = {"id": "default", "kind": "default", "public": _success()}
        record["public"]["mapping"][key] = value
        with pytest.raises(checker.ObservationError, match=diagnostic):
            checker.validate_observation(record)


def test_observation_rejects_invalid_success_identity_and_base_shapes() -> None:
    checker = _checker()
    nonmerge = {"id": "default", "kind": "default", "public": _success()}
    nonmerge["public"]["reused_instance"] = True
    merge = {"id": "merge-valid", "kind": "merge", "public": _success(merge=True)}
    merge["public"]["base_after"] = None

    with pytest.raises(checker.ObservationError):
        checker.validate_observation(nonmerge)
    with pytest.raises(checker.ObservationError):
        checker.validate_observation(merge)


def test_full_synthetic_protocol_runs_compare_without_claiming_sdk_semantics(
    tmp_path: Path,
) -> None:
    checker = _checker()
    _, cases = checker.load_profile(checker.DEFAULT_INPUT)
    python_run = _read_run(checker, tmp_path, _run(checker, cases, "python"), cases, "python")
    native_run = _read_run(checker, tmp_path, _run(checker, cases, "csharp"), cases, "csharp")

    result = checker.compare_observations(python_run, native_run, cases)

    assert result["status"] == "passed"
    assert len(result["matched"]) == 57
    assert result["native_only"][0]["id"] == "native-overflow-shingle"
    assert result["native_only"][0]["csharp"] == {
        "error": {"type": "ArgumentException", "stage": "operation"}
    }


def test_read_run_rejects_nonstandard_nan_json_wire_value(tmp_path: Path) -> None:
    checker = _checker()
    _, cases = checker.load_profile(checker.DEFAULT_INPUT)
    payload = _run(checker, cases, "python")
    payload["observations"][0]["public"]["mapping"]["diversity"] = math.nan

    with pytest.raises(checker.ObservationError, match="nonstandard JSON numeric constant"):
        _read_run(checker, tmp_path, payload, cases, "python")


def test_comparison_rejects_negative_zero_sign_and_declared_sign_list_difference(
    tmp_path: Path,
) -> None:
    checker = _checker()
    _, cases = checker.load_profile(checker.DEFAULT_INPUT)
    python_payload = _run(checker, cases, "python")
    native_payload = _run(checker, cases, "csharp")
    python_default = python_payload["observations"][0]["public"]
    python_default["mapping"]["diversity"] = -0.0
    python_default["round_trip"]["diversity"] = -0.0
    python_default["negative_zero_fields"] = ["diversity"]
    native_default = native_payload["observations"][0]["public"]
    native_default["mapping"]["diversity"] = 0.0
    native_default["round_trip"]["diversity"] = 0.0

    python_run = _read_run(checker, tmp_path, python_payload, cases, "python")
    native_run = _read_run(checker, tmp_path, native_payload, cases, "csharp")
    result = checker.compare_observations(python_run, native_run, cases)

    assert result["status"] == "failed"
    assert any(entry["case"] == "default" for entry in result["mismatches"])


def test_validate_observation_accepts_mapping_and_round_trip_negative_zero() -> None:
    checker = _checker()
    public = _success()
    public["mapping"]["diversity"] = -0.0
    public["round_trip"]["diversity"] = -0.0
    public["negative_zero_fields"] = ["diversity"]

    checker.validate_observation({"id": "default", "kind": "default", "public": public})


@pytest.mark.parametrize(
    ("mapping_value", "round_trip_value", "zero_fields", "diagnostic"),
    (
        (-0.0, 0.0, [], "does not reflect mapping signed zeros"),
        (-0.0, 0.0, ["diversity"], "does not preserve the signed-zero bit"),
        (0.0, -0.0, [], "does not preserve the signed-zero bit"),
    ),
    ids=("negative-zero-loss-false-intersection", "negative-zero-loss", "negative-zero-gain"),
)
def test_validate_observation_rejects_one_sided_signed_zero_round_trip(
    mapping_value: float, round_trip_value: float, zero_fields: list[str], diagnostic: str
) -> None:
    checker = _checker()
    public = _success()
    public["mapping"]["diversity"] = mapping_value
    public["round_trip"]["diversity"] = round_trip_value
    public["negative_zero_fields"] = zero_fields

    with pytest.raises(checker.ObservationError, match=diagnostic):
        checker.validate_observation({"id": "default", "kind": "default", "public": public})


def test_comparison_rejects_signed_zero_difference_in_successful_merge_base_snapshot(
    tmp_path: Path,
) -> None:
    checker = _checker()
    _, cases = checker.load_profile(checker.DEFAULT_INPUT)
    python_payload = _run(checker, cases, "python")
    native_payload = _run(checker, cases, "csharp")
    python_merge = {record["id"]: record for record in python_payload["observations"]}[
        "merge-valid"
    ]
    native_merge = {record["id"]: record for record in native_payload["observations"]}[
        "merge-valid"
    ]
    python_merge["public"]["base_after"]["diversity"] = -0.0
    native_merge["public"]["base_after"]["diversity"] = 0.0

    python_run = _read_run(checker, tmp_path, python_payload, cases, "python")
    native_run = _read_run(checker, tmp_path, native_payload, cases, "csharp")
    result = checker.compare_observations(python_run, native_run, cases)

    assert result["status"] == "failed"
    assert any(entry["case"] == "merge-valid" for entry in result["mismatches"])


def test_comparison_allows_positive_zero_integer_and_float_at_float_field(tmp_path: Path) -> None:
    checker = _checker()
    _, cases = checker.load_profile(checker.DEFAULT_INPUT)
    python_payload = _run(checker, cases, "python")
    native_payload = _run(checker, cases, "csharp")
    python_merge = {record["id"]: record for record in python_payload["observations"]}[
        "merge-valid"
    ]
    native_merge = {record["id"]: record for record in native_payload["observations"]}[
        "merge-valid"
    ]
    python_merge["public"]["base_after"]["diversity"] = 0
    native_merge["public"]["base_after"]["diversity"] = 0.0

    python_run = _read_run(checker, tmp_path, python_payload, cases, "python")
    native_run = _read_run(checker, tmp_path, native_payload, cases, "csharp")
    result = checker.compare_observations(python_run, native_run, cases)

    assert result["status"] == "passed"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda run: run.update(source_revision="not-a-revision"),
        lambda run: run.update(source_dirty="false"),
        lambda run: run.update(corpus_sha256="0" * 64),
        lambda run: run["observations"].pop(),
        lambda run: run["observations"].append(copy.deepcopy(run["observations"][0])),
        lambda run: run["observations"][0].update(id="unknown"),
        lambda run: run["observations"][0].update(kind="merge"),
    ),
)
def test_read_run_rejects_one_provenance_or_coverage_failure_at_a_time(
    tmp_path: Path, mutate: Any
) -> None:
    checker = _checker()
    _, cases = checker.load_profile(checker.DEFAULT_INPUT)
    payload = _run(checker, cases, "python")
    mutate(payload)

    with pytest.raises(checker.ObservationError):
        _read_run(checker, tmp_path, payload, cases, "python")


def test_comparison_rejects_mapping_order_identity_base_and_narrow_error_differences(
    tmp_path: Path,
) -> None:
    checker = _checker()
    _, cases = checker.load_profile(checker.DEFAULT_INPUT)
    python_payload = _run(checker, cases, "python")
    native_payload = _run(checker, cases, "csharp")
    targets = {record["id"]: record for record in native_payload["observations"]}
    targets["default"]["public"]["mapping"]["diversity"] = 0.3
    targets["merge-valid"]["public"]["reused_instance"] = True
    targets["merge-same"]["public"]["base_after"]["chunk_tokens"] = 1
    targets["default"]["public"]["constants"]["selection_orders"] = ["density", "rank"]
    targets["unit-low-invalid"]["public"] = {"error": {"type": "OtherError", "stage": "operation"}}
    targets["merge-invalid-base"]["public"] = {
        "error": {"type": "ArgumentException", "stage": "base"}
    }
    py_targets = {record["id"]: record for record in python_payload["observations"]}
    py_targets["unit-low-invalid"]["public"] = {
        "error": {"type": "ValueError", "stage": "operation"}
    }
    py_targets["merge-invalid-base"]["public"] = {
        "error": {"type": "ValueError", "stage": "operation"}
    }

    python_run = _read_run(checker, tmp_path, python_payload, cases, "python")
    native_run = _read_run(checker, tmp_path, native_payload, cases, "csharp")
    result = checker.compare_observations(python_run, native_run, cases)

    assert result["status"] == "failed"
    assert {entry["case"] for entry in result["mismatches"]} >= {
        "default",
        "merge-valid",
        "merge-same",
        "unit-low-invalid",
        "merge-invalid-base",
    }
