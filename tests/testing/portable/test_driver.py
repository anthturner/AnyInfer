"""Focused tests for the UNRELEASED portable observation driver."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from . import driver


def test_observation_is_unreleased_and_does_not_validate_as_report_v0() -> None:
    report = asyncio.run(driver.observe_core(driver._DEFAULT_ROOT))
    assert report["development_observation"] == "UNRELEASED"
    assert report["report_v0_eligible"] is False
    assert report["counts"]["unexecuted"] == len(report["unexecuted"])
    schema = json.loads((driver._DEFAULT_ROOT / "schemas/report-v0.schema.json").read_text())
    assert list(Draft202012Validator(schema).iter_errors(report))


def test_selected_root_hashes_and_paths_are_isolated(tmp_path: Path) -> None:
    selected = tmp_path / "specification"
    for relative in driver._NORMATIVE_INPUTS:
        destination = selected / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((driver._DEFAULT_ROOT / relative).read_bytes())
    source_fixtures = driver._DEFAULT_ROOT / "fixtures/core-generation"
    for source in source_fixtures.rglob("*.json"):
        destination = selected / "fixtures/core-generation" / source.relative_to(source_fixtures)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    report = asyncio.run(driver.observe_core(selected))
    assert report["selected_root"] == str(selected.resolve())
    assert all(
        item["sha256"] is None for item in report["inputs"] if "fixtures/transport" in item["path"]
    )


def test_write_json_is_lf_and_preserves_member_order(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "report.json"
    driver.write_json(path, {"z": {"second": 2, "first": 1}, "a": [1, 2]})
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert list(json.loads(raw)) == ["z", "a"]
    assert list(json.loads(raw)["z"]) == ["second", "first"]


def test_write_reference_is_rejected_without_output(tmp_path: Path) -> None:
    output = tmp_path / "reference.json"
    with pytest.raises(SystemExit):
        driver.main(
            ["--portable-report", str(tmp_path / "report.json"), "--write-reference", str(output)]
        )
    assert not output.exists()


def test_absent_transport_entries_are_retained_as_honest_unexecuted_rows(tmp_path: Path) -> None:
    selected = _copy_selected_core(tmp_path)
    report = asyncio.run(driver.observe_core(selected))
    transport = [row for row in report["unexecuted"] if row["path"] is not None]
    assert transport and all(
        row["status"] == "missing" and row["sha256"] is None for row in transport
    )


def test_present_transport_hash_mutation_and_identity_are_bound(tmp_path: Path) -> None:
    selected = _copy_selected_core(tmp_path)
    inventory = json.loads((selected / "inventories/core-generation-v0.json").read_text())
    record = next(
        case
        for case in inventory["cases"]
        if str(case.get("path")).startswith("specification/fixtures/transport/")
    )
    destination = selected / str(record["path"]).removeprefix("specification/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "fixture_version": "0",
                "id": record["id"],
                "family": record["family"],
                "profile": "core-generation",
                "description": "synthetic selected-root transport identity test",
                "kind": "adapter",
                "input": {"adapter_config": {}, "wire": {}},
                "responses": [],
                "expected": {"http_requests": [], "wire_limits": [], "adapter_outcome": {}},
            }
        ),
        encoding="utf-8",
    )
    report = asyncio.run(driver.observe_core(selected))
    row = next(row for row in report["unexecuted"] if row["id"] == record["id"])
    assert row["status"] == "present" and row["sha256"] == driver._sha256(destination)
    document = json.loads(destination.read_text())
    document["id"] = "transport/openai-chat/wrong"
    destination.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(driver.DriverInputError, match="does not match inventory"):
        asyncio.run(driver.observe_core(selected))


def test_missing_selected_core_fixture_fails_closed(tmp_path: Path) -> None:
    selected = _copy_selected_core(tmp_path)
    (selected / "fixtures/core-generation/extraction/empty-response.json").unlink()
    with pytest.raises(driver.DriverInputError, match="missing from selected root"):
        asyncio.run(driver.observe_core(selected))


def test_proof_dispatcher_accepts_agreed_envelope() -> None:
    record = driver._check_recipe(
        {
            "id": "driver/assessment-completeness",
            "verdict": "pass",
            "detail": None,
            "evidence": {
                "recipe_ref": "driver/assessment-completeness",
                "observations": {"native": True},
            },
        },
        "driver/assessment-completeness",
        "driver/assessment-completeness",
    )
    assert record["evidence"]["recipe_ref"] == "driver/assessment-completeness"


def _copy_selected_core(tmp_path: Path) -> Path:
    selected = tmp_path / "specification"
    for relative in driver._NORMATIVE_INPUTS:
        destination = selected / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((driver._DEFAULT_ROOT / relative).read_bytes())
    source_fixtures = driver._DEFAULT_ROOT / "fixtures/core-generation"
    for source in source_fixtures.rglob("*.json"):
        destination = selected / "fixtures/core-generation" / source.relative_to(source_fixtures)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return selected
