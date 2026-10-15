"""Black-box checks for the portable asset validator's authoring safeguards."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate_fixtures.py"
_VALIDATOR_SPEC = importlib.util.spec_from_file_location("portable_asset_validator", VALIDATOR)
assert _VALIDATOR_SPEC is not None and _VALIDATOR_SPEC.loader is not None
validate_fixtures = importlib.util.module_from_spec(_VALIDATOR_SPEC)
_VALIDATOR_SPEC.loader.exec_module(validate_fixtures)


def test_schema_assets_are_utf8_lf_without_a_bom() -> None:
    for path in (ROOT / "specification" / "schemas").glob("*.json"):
        data = path.read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in data


def _core_fixture(
    outcome: object, *, case_id: str = "normalization/roles-ordered-text"
) -> dict[str, object]:
    return {
        "fixture_version": "0",
        "id": case_id,
        "family": "normalization",
        "profile": "core-generation",
        "description": "minimal valid core fixture",
        "request": {"messages": [{"role": "user", "text": "hello"}]},
        "route": {"targets": ["fake/model"]},
        "adapter": {"max_repair_attempts": None, "models": {}, "health_preset": [], "script": []},
        "expected": {
            "status": "observed",
            "calls": [],
            "clock_advances_ms": [],
            "telemetry": {"repair_attempted": [], "parameter_dropped": []},
            "events": [],
            "outcome": outcome,
            "accounting": None,
        },
    }


def _transport_fixture(*, chunks: list[dict[str, str]] | None = None) -> dict[str, object]:
    return {
        "fixture_version": "0",
        "id": "transport/openai-chat/single-frame",
        "family": "transport/openai-chat",
        "profile": "core-generation",
        "description": "minimal valid transport fixture",
        "kind": "adapter",
        "input": {"adapter_config": {}, "wire": {}},
        "responses": [
            {"status": 200, "headers": {}, "byte_chunks": chunks or [{"bytes": "AA=="}]}
        ],
        "expected": {"http_requests": [], "wire_limits": [], "adapter_outcome": {}},
    }


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(VALIDATOR), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=os.environ | {"PYTHONUTF8": "1"},
        check=False,
    )


def test_empty_authoring_tree_is_valid_but_coverage_requires_an_inventory(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    assert _run("--root", str(root)).returncode == 0
    coverage = _run("--root", str(root), "--check-coverage", "--family", "core-generation")
    assert coverage.returncode != 0
    assert "coverage requires an inventory" in coverage.stderr


def test_deliberately_broken_fixture_is_rejected() -> None:
    result = _run("--root", "tests/testing/portable/bad_fixtures")
    assert result.returncode != 0
    assert "'expected' is a required property" in result.stderr


def test_every_schema_accepts_a_minimal_valid_document_and_core_outcomes_are_closed() -> None:
    fixture_schema = json.loads(
        (ROOT / "specification" / "schemas" / "fixture-v0.schema.json").read_text(encoding="utf-8")
    )
    fixture_validator = Draft202012Validator(fixture_schema)
    for outcome in ({"result": {}}, {"error": {"category": "transport"}}, {"none": True}):
        assert not list(fixture_validator.iter_errors(_core_fixture(outcome)))
    assert list(fixture_validator.iter_errors(_core_fixture({"result": {}, "none": True})))
    scripted = _core_fixture({"none": True})
    scripted["request"]["sampling"] = {"temperature": 0.5, "seed": -1, "stop": ["END"]}
    scripted["adapter"]["script"] = [
        {"events": [{"text": "x"}, {"usage": None}, {"final": {"usage": None}}]},
        {"events": [{"await_release": "gate"}], "fail": {"category": "transport"}},
        {"events": [{"final": {}}], "fail_in_cleanup": {"category": "transport"}},
        {"fail": {"category": "transport"}},
    ]
    assert not list(fixture_validator.iter_errors(scripted))
    scripted["request"]["sampling"] = {"unknown": 1}
    assert list(fixture_validator.iter_errors(scripted))
    scripted["request"]["sampling"] = {"seed": -1}
    scripted["adapter"]["script"] = [{"events": [{"text": "x", "usage": None}]}]
    assert list(fixture_validator.iter_errors(scripted))


def test_script_failures_admit_only_native_adapter_categories_and_fields() -> None:
    fixture_schema = json.loads(
        (ROOT / "specification" / "schemas" / "fixture-v0.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(fixture_schema)
    fixture = _core_fixture({"none": True})
    fixture["adapter"]["script"] = [
        {
            "events": [{"text": "x"}],
            "fail": {
                "category": "stream_protocol",
                "retryable": False,
                "retry_after_s": None,
                "http_status": 503,
                "phase": "stream",
            },
        }
    ]
    assert not list(validator.iter_errors(fixture))
    fixture["adapter"]["script"][0]["fail"]["category"] = "protocol"
    assert list(validator.iter_errors(fixture))
    fixture["adapter"]["script"][0]["fail"] = {"category": "transport", "extra": True}
    assert list(validator.iter_errors(fixture))
    fixture["adapter"]["script"][0]["fail"] = {"category": "schema_violation"}
    assert list(validator.iter_errors(fixture))
    fixture["adapter"]["script"][0]["fail"] = {"category": "cancelled"}
    assert list(validator.iter_errors(fixture))

    transport_schema = json.loads(
        (ROOT / "specification" / "schemas" / "transport-v0.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert not list(Draft202012Validator(transport_schema).iter_errors(_transport_fixture()))

    inventory_schema = json.loads(
        (ROOT / "specification" / "schemas" / "inventory-v0.schema.json").read_text(
            encoding="utf-8"
        )
    )
    inventory = {
        "profile": "core-generation",
        "profile_revision": "v0",
        "requirements": [
            {
                "id": "normalization",
                "spec_ref": "section-17",
                "case_ids": ["normalization/roles-ordered-text"],
            }
        ],
        "cases": [
            {
                "id": "normalization/roles-ordered-text",
                "kind": "fixture",
                "path": "specification/fixtures/core-generation/roles.json",
                "family": "normalization",
                "extension": None,
            }
        ],
    }
    assert not list(Draft202012Validator(inventory_schema).iter_errors(inventory))


def test_core_fixture_encodes_extraction_invalid_schema_and_no_schema_calls() -> None:
    schema = json.loads(
        (ROOT / "specification" / "schemas" / "fixture-v0.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    fixture = _core_fixture({"none": True})
    calls = fixture["expected"]["calls"]
    assert isinstance(calls, list)
    calls.extend(
        [
            {
                "model": "test/model",
                "role": "correction",
                "mechanism": "prompt",
                "timeout_s": 1,
                "max_response_bytes": 1,
                "messages": [
                    {
                        "role": "user",
                        "text": [
                            "Your previous response did not match the required JSON schema. Errors:\n",
                            {"$repair_feedback": True},
                            "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.",
                        ],
                    }
                ],
                "issues": [
                    {
                        "rule": "no_json_candidate",
                        "instance_path": None,
                        "schema_path": None,
                        "params": {},
                    },
                    {
                        "rule": "invalid_schema",
                        "instance_path": None,
                        "schema_path": ["required"],
                        "params": {},
                    },
                ],
            },
            {
                "model": "test/model",
                "role": "original",
                "mechanism": None,
                "timeout_s": 1,
                "max_response_bytes": 1,
                "messages": [{"role": "user", "text": "plain text"}],
            },
        ]
    )
    assert not list(validator.iter_errors(fixture))
    assert not validate_fixtures._expected_message_problems(fixture)
    correction = calls[0]
    assert isinstance(correction, dict)
    correction["messages"][0]["text"].append({"$repair_feedback": True})
    assert any(
        "exactly one $repair_feedback" in problem
        for problem in validate_fixtures._expected_message_problems(fixture)
    )


def test_transport_rejects_opposite_input_variant_and_non_base64_chunks(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    transport = root / "transport" / "wrong-input.json"
    transport.parent.mkdir(parents=True)
    wrong_variant = _transport_fixture()
    wrong_variant["input"] = {"adapter_config": {}, "wire": {}, "operation": {}}
    transport.write_text(json.dumps(wrong_variant), encoding="utf-8")
    result = _run("--root", str(root))
    assert result.returncode != 0
    assert "should not be valid under {'required': ['operation']}" in result.stderr

    transport.write_text(
        json.dumps(_transport_fixture(chunks=[{"bytes": "%%%%"}])), encoding="utf-8"
    )
    corrupt = _run("--root", str(root))
    assert corrupt.returncode != 0
    assert "is not strict base64" in corrupt.stderr


def test_custom_corpus_paths_never_resolve_against_the_checkout(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    (root / "core-generation").mkdir(parents=True)
    (root / "inventories").mkdir()
    (root / "core-generation" / "roles.json").write_text(
        json.dumps(_core_fixture({"none": True}, case_id="normalization/altered")),
        encoding="utf-8",
    )
    (root / "inventories" / "core-generation-v0.json").write_text(
        json.dumps(
            {
                "profile": "core-generation",
                "profile_revision": "v0",
                "requirements": [
                    {
                        "id": "normalization",
                        "spec_ref": "section-17",
                        "case_ids": ["normalization/roles-ordered-text"],
                    }
                ],
                "cases": [
                    {
                        "id": "normalization/roles-ordered-text",
                        "kind": "fixture",
                        "path": "specification/fixtures/core-generation/roles.json",
                        "family": "normalization",
                        "extension": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = _run("--root", str(root), "--check-coverage", "--family", "core-generation")
    assert result.returncode != 0
    assert (
        "normalization/roles-ordered-text: fixture ID is absent from fixture tree" in result.stderr
    )


def test_coverage_rejects_an_inventory_path_when_its_id_exists_elsewhere(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    (root / "core-generation").mkdir(parents=True)
    (root / "inventories").mkdir()
    (root / "core-generation" / "declared.json").write_text(
        json.dumps(_core_fixture({"none": True}, case_id="normalization/other")), encoding="utf-8"
    )
    (root / "core-generation" / "other.json").write_text(
        json.dumps(_core_fixture({"none": True})), encoding="utf-8"
    )
    (root / "inventories" / "core-generation-v0.json").write_text(
        json.dumps(
            {
                "profile": "core-generation",
                "profile_revision": "v0",
                "requirements": [
                    {
                        "id": "normalization",
                        "spec_ref": "section-17",
                        "case_ids": ["normalization/roles-ordered-text"],
                    }
                ],
                "cases": [
                    {
                        "id": "normalization/roles-ordered-text",
                        "kind": "fixture",
                        "path": "specification/fixtures/core-generation/declared.json",
                        "family": "normalization",
                        "extension": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = _run("--root", str(root), "--check-coverage", "--family", "core-generation")
    assert result.returncode != 0
    assert "inventory path does not name its fixture ID" in result.stderr


def test_default_root_inventory_path_rejects_family_mismatch(tmp_path: Path, monkeypatch) -> None:
    specification = tmp_path / "specification"
    root = specification / "fixtures"
    (root / "core-generation").mkdir(parents=True)
    (specification / "inventories").mkdir()
    (root / "core-generation" / "roles.json").write_text(
        json.dumps(_core_fixture({"none": True}, case_id="normalization/roles-ordered-text")),
        encoding="utf-8",
    )
    (specification / "inventories" / "core-generation-v0.json").write_text(
        json.dumps(
            {
                "profile": "core-generation",
                "profile_revision": "v0",
                "requirements": [
                    {
                        "id": "normalization",
                        "spec_ref": "section-17",
                        "case_ids": ["normalization/roles-ordered-text"],
                    }
                ],
                "cases": [
                    {
                        "id": "normalization/roles-ordered-text",
                        "kind": "fixture",
                        "path": "specification/fixtures/core-generation/roles.json",
                        "family": "routing",
                        "extension": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(validate_fixtures, "FIXTURES", root)
    monkeypatch.setattr(validate_fixtures, "SPECIFICATION", specification)
    problems = validate_fixtures.validate(root, coverage=True, family="core-generation")
    assert any("fixture family does not match inventory family" in problem for problem in problems)


def test_inventory_spec_refs_use_the_supplied_normative_tree_and_reject_missing_targets(
    tmp_path: Path,
) -> None:
    specification = tmp_path / "specification"
    root = specification / "fixtures"
    (root / "inventories").mkdir(parents=True)
    normative = specification / "core-generation.md"
    normative.write_text("# Supplied anchor\n", encoding="utf-8", newline="\n")
    inventory = root / "inventories" / "core-generation-v0.json"

    def problems_for(spec_ref: str) -> list[str]:
        inventory.write_text(
            json.dumps(
                {
                    "profile": "core-generation",
                    "profile_revision": "v0",
                    "requirements": [
                        {
                            "id": "proof",
                            "spec_ref": spec_ref,
                            "case_ids": ["normalization/roles-ordered-text"],
                        }
                    ],
                    "cases": [],
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        return validate_fixtures.validate(root)

    valid = problems_for("specification/core-generation.md#supplied-anchor")
    assert not any(
        "has invalid spec_ref" in problem or "missing fragment" in problem for problem in valid
    )
    missing_fragment = problems_for("specification/core-generation.md#checkout-only-anchor")
    assert any("missing fragment" in problem for problem in missing_fragment)
    missing_path = problems_for("specification/missing.md#supplied-anchor")
    assert any("has invalid spec_ref" in problem for problem in missing_path)
    (tmp_path / "outside.md").write_text("# Supplied anchor\n", encoding="utf-8", newline="\n")
    for escaped in (
        "../outside.md#supplied-anchor",
        "specification/../outside.md#supplied-anchor",
        str(tmp_path / "outside.md") + "#supplied-anchor",
        "specification\\core-generation.md#supplied-anchor",
    ):
        assert any("has invalid spec_ref" in problem for problem in problems_for(escaped))


def test_inventory_named_ids_cannot_swap_driver_recipes_or_kinds(tmp_path: Path) -> None:
    inventory = json.loads(
        (ROOT / "specification" / "inventories" / "core-generation-v0.json").read_text(
            encoding="utf-8"
        )
    )
    path = tmp_path / "inventory.json"
    validator = validate_fixtures._schema("inventory-v0.schema.json")

    def problems_for(document: dict[str, object]) -> list[str]:
        path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
        return validate_fixtures._validate_inventory(
            path, validator, {}, tmp_path, coverage=False, family=None
        )

    assert not any("canonical" in problem for problem in problems_for(inventory))
    swapped = json.loads(json.dumps(inventory))
    driver = next(
        case for case in swapped["cases"] if case["id"] == "driver/timeout-cleanup-disposal"
    )
    driver["recipe_ref"] = "driver/concurrent-operations-independent"
    assert any("canonical driver_assertion" in problem for problem in problems_for(swapped))
    wrong_kind = json.loads(json.dumps(inventory))
    fixture = next(case for case in wrong_kind["cases"] if case["id"] == "routing/backoff-cap")
    fixture.update(
        {
            "kind": "driver_assertion",
            "path": None,
            "family": "driver",
            "recipe_ref": "driver/backoff-cap",
        }
    )
    assert any("canonical fixture" in problem for problem in problems_for(wrong_kind))


def test_json_integer_bounds_are_inclusive_at_plus_or_minus_two_to_the_63rd(
    tmp_path: Path,
) -> None:
    path = tmp_path / "number.json"
    path.write_text(str(2**63), encoding="utf-8")
    assert validate_fixtures._read_json(path) == 2**63
    path.write_text(str(-(2**63)), encoding="utf-8")
    assert validate_fixtures._read_json(path) == -(2**63)
    path.write_text(str(2**63 + 1), encoding="utf-8")
    try:
        validate_fixtures._read_json(path)
    except ValueError as error:
        assert "±2^63" in str(error)
    else:
        raise AssertionError("an integer above the v0 bound was accepted")


def test_inventory_and_transport_discriminator_fail_before_driver_execution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assets"
    inventory = root / "inventories" / "core-generation-v0.json"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(
        json.dumps(
            {
                "profile": "core-generation",
                "profile_revision": "v0",
                "requirements": [{"id": "bad", "spec_ref": "§17", "case_ids": []}],
                "cases": [
                    {
                        "id": "missing",
                        "kind": "fixture",
                        "path": None,
                        "family": "x",
                        "extension": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    invalid_inventory = _run("--root", str(root))
    assert invalid_inventory.returncode != 0
    assert "is not valid under any of the given schemas" in invalid_inventory.stderr
    missing_mapping = _run("--root", str(root), "--check-coverage", "--family", "core-generation")
    assert missing_mapping.returncode != 0
    assert "missing requirement mapping" in missing_mapping.stderr

    transport = root / "transport" / "wrong-kind.json"
    transport.parent.mkdir(parents=True)
    transport.write_text(
        json.dumps(
            {
                "fixture_version": "0",
                "id": "transport/openai-chat/wrong-kind",
                "family": "transport/openai-chat",
                "profile": "core-generation",
                "description": "core outcome cannot be an adapter case",
                "kind": "adapter",
                "input": {"adapter_config": {}, "operation": {}},
                "responses": [],
                "expected": {"http_requests": [], "wire_limits": [], "core": {}},
            }
        ),
        encoding="utf-8",
    )
    wrong_kind = _run("--root", str(root))
    assert wrong_kind.returncode != 0
    assert "'wire' is a required property" in wrong_kind.stderr


def test_report_evidence_conditions_preserve_honest_driver_and_extension_results() -> None:
    schema = json.loads(
        (ROOT / "specification" / "schemas" / "report-v0.schema.json").read_text(encoding="utf-8")
    )
    report = {
        "report_version": "0",
        "release": "core-generation-v0",
        "release_sha256": "0" * 64,
        "implementation": {
            "name": "test",
            "version": "0",
            "source_revision": "x",
            "driver_revision": "x",
            "runtime": "test",
            "os": "test",
            "dependencies": {},
            "extensions": [],
        },
        "cases": [{"id": "driver/assessment-completeness", "verdict": "pass", "detail": None}],
        "counts": {"pass": 1, "fail": 0, "error": 0, "extension": 0},
    }
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(report))
    report["cases"][0]["evidence"] = {
        "recipe_ref": "driver/assessment-completeness",
        "observations": {},
    }
    assert list(validator.iter_errors(report))
    report["cases"][0]["evidence"]["observations"] = {"native": "captured"}
    assert not list(validator.iter_errors(report))
    report["cases"][0] = {
        "id": "driver/assessment-completeness",
        "verdict": "error",
        "detail": None,
    }
    report["counts"] = {"pass": 0, "fail": 0, "error": 1, "extension": 0}
    assert not list(validator.iter_errors(report))
    report["cases"][0] = {
        "id": "normalization/unsupported-image-part",
        "verdict": "extension",
        "detail": None,
    }
    report["counts"] = {"pass": 0, "fail": 0, "error": 0, "extension": 1}
    assert list(validator.iter_errors(report))
    report["cases"][0]["evidence"] = {"native_outcome": {"none": True}, "adapter_entries": []}
    assert not list(validator.iter_errors(report))
    assert not validate_fixtures.validate_report(report)
    report["cases"][0]["evidence"]["adapter_entries"] = [
        {
            "entry_ordinal": 1,
            "model": "test/model",
            "role": "original",
            "timeout_s": 1,
            "max_response_bytes": 1,
        }
    ]
    assert any(
        "consecutive zero-based" in problem
        for problem in validate_fixtures.validate_report(report)
    )
