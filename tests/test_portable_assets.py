"""Black-box checks for the portable asset validator's authoring safeguards."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.request
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
        "input": {
            "adapter_config": {
                "provider_id": "openai-compat",
                "base_url": "https://fixture.invalid/v1",
                "api_key": "fixture-token",
                "headers": {},
                "timeout_s": 120,
            },
            "wire": {
                "model": "fixture-model",
                "messages": [{"role": "user", "text": "hello"}],
                "sampling": {},
                "mechanism": None,
                "stream": True,
                "timeout_s": 120,
                "max_response_bytes": 1024,
            },
        },
        "responses": [
            {"status": 200, "headers": {}, "byte_chunks": chunks or [{"bytes": "AA=="}]}
        ],
        "expected": {
            "status": "observed",
            "http_requests": [],
            "wire_limits": [],
            "adapter_outcome": {"events": []},
        },
    }


def _copy_validation_schemas(specification: Path) -> None:
    schemas = specification / "schemas"
    schemas.mkdir(parents=True, exist_ok=True)
    for name in ("fixture-v0.schema.json", "transport-v0.schema.json", "inventory-v0.schema.json"):
        shutil.copy2(ROOT / "specification" / "schemas" / name, schemas / name)


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
    nested_model = _core_fixture({"none": True})
    nested_model["adapter"]["models"] = {
        "fixture:alpha": {
            "capabilities": {"grammar": False, "json_schema": False, "json_mode": False}
        }
    }
    assert not list(fixture_validator.iter_errors(nested_model))
    nested_model["adapter"]["models"] = {
        "fixture:alpha": {"grammar": False, "json_schema": False, "json_mode": False}
    }
    assert list(fixture_validator.iter_errors(nested_model))
    nested_model["adapter"]["models"] = {
        "fixture:alpha": {"capabilities": {"grammar": False, "json_schema": False}}
    }
    assert list(fixture_validator.iter_errors(nested_model))
    nested_model["adapter"]["models"] = {
        "fixture:alpha": {
            "capabilities": {
                "grammar": False,
                "json_schema": False,
                "json_mode": False,
                "unknown": False,
            }
        }
    }
    assert list(fixture_validator.iter_errors(nested_model))
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

    transport_validator = validate_fixtures._schema(
        "transport-v0.schema.json", specification_root=ROOT / "specification"
    )
    assert not list(transport_validator.iter_errors(_transport_fixture()))

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


def _core_http_marker_fixture() -> dict[str, object]:
    repair = [
        "Your previous response did not match the required JSON schema. Errors:\n",
        {"$repair_feedback": True},
        "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.",
    ]
    messages = [
        {"role": "system", "text": ["caller", "\n\n", {"$schema_prompt": True}]},
        {"role": "user", "text": "hello"},
        {"role": "assistant", "text": "not-json"},
        {"role": "user", "text": repair},
    ]
    core = _core_fixture({"none": True})["expected"]
    assert isinstance(core, dict)
    core["calls"] = [
        {
            "model": "fixture-model",
            "role": "correction",
            "mechanism": "prompt",
            "timeout_s": 17,
            "max_response_bytes": 1024,
            "messages": messages,
            "issues": [],
        }
    ]
    fixture = _transport_fixture()
    fixture["kind"] = "core_http"
    fixture["input"] = {
        "adapter_config": fixture["input"]["adapter_config"],
        "operation": {
            "request": {
                "messages": [{"role": "system", "text": "caller"}, {"role": "user", "text": "hello"}],
                "schema": {"type": "object"},
                "sampling": {},
                "consume": "stream",
                "timeout_s": 17,
                "max_response_bytes": 1024,
            },
            "route": {"targets": ["openai-compat:fixture-model"], "retry": {"max_attempts": 1}},
        },
    }
    fixture["expected"] = {
        "status": "observed",
        "http_requests": [
            {
                "method": "POST",
                "path": "/v1/chat/completions",
                "headers": {"content-type": "application/json", "authorization": "Bearer fixture-token"},
                "body": {
                    "messages": [
                        {"role": message["role"], "content": message["text"]} for message in messages
                    ]
                },
                "stream": True,
            }
        ],
        "wire_limits": [{"timeout_s": 17, "max_response_bytes": 1024}],
        "core": core,
    }
    return fixture


def test_core_http_expected_message_markers_are_causal_and_typed() -> None:
    fixture = _core_http_marker_fixture()
    validator = validate_fixtures._schema(
        "transport-v0.schema.json", specification_root=ROOT / "specification"
    )
    assert not list(validator.iter_errors(fixture))
    assert not validate_fixtures._expected_message_problems(fixture)

    def mutated() -> dict[str, object]:
        return json.loads(json.dumps(fixture))

    wrong_role = mutated()
    wrong_role["expected"]["http_requests"][0]["body"]["messages"][3]["role"] = "assistant"
    assert any("role does not align" in item for item in validate_fixtures._expected_message_problems(wrong_role))

    missing_row = mutated()
    missing_row["expected"]["http_requests"] = []
    assert any("one-to-one" in item for item in validate_fixtures._expected_message_problems(missing_row))

    misaligned = mutated()
    misaligned["expected"]["http_requests"][0]["body"]["messages"].pop()
    assert any("messages must align" in item for item in validate_fixtures._expected_message_problems(misaligned))

    malformed = mutated()
    malformed["expected"]["http_requests"][0]["body"]["messages"][3]["content"][1] = {"$repair_feedback": 1}
    assert any("correction needs exactly one $repair_feedback" in item for item in validate_fixtures._expected_message_problems(malformed))

    adapter_literal = _transport_fixture()
    adapter_literal["expected"]["http_requests"] = [
        {"method": "POST", "path": "/x", "headers": {}, "body": {"marker": {"$repair_feedback": True}}, "stream": True}
    ]
    assert not validate_fixtures._expected_message_problems(adapter_literal)

    other_position = mutated()
    other_position["expected"]["http_requests"][0]["body"]["metadata"] = {"$repair_feedback": True}
    assert not validate_fixtures._expected_message_problems(other_position)

    multipart = mutated()
    part = [{"type": "text", "text": "literal {$repair_feedback}"}]
    multipart["expected"]["http_requests"][0]["body"]["messages"][1]["content"] = part
    assert not list(validator.iter_errors(multipart))
    assert not validate_fixtures._expected_message_problems(multipart)

    split_literals = mutated()
    split_literals["expected"]["http_requests"][0]["body"]["messages"][0]["content"] = [
        "cal",
        "ler",
        "\n\n",
        {"$schema_prompt": True},
    ]
    assert not list(validator.iter_errors(split_literals))
    assert not validate_fixtures._expected_message_problems(split_literals)


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


def test_transport_expected_status_distinguishes_pending_and_observed() -> None:
    validator = validate_fixtures._schema(
        "transport-v0.schema.json", specification_root=ROOT / "specification"
    )
    observed = _transport_fixture()
    assert not list(validator.iter_errors(observed))

    pending = _transport_fixture()
    pending["expected"] = {"status": "to_be_observed"}
    assert not list(validator.iter_errors(pending))

    unknown = _transport_fixture()
    unknown_expected = unknown["expected"]
    assert isinstance(unknown_expected, dict)
    unknown_expected["status"] = "unknown"
    assert list(validator.iter_errors(unknown))

    missing = _transport_fixture()
    missing_expected = missing["expected"]
    assert isinstance(missing_expected, dict)
    missing_expected.pop("status")
    assert list(validator.iter_errors(missing))

    pending_extra = _transport_fixture()
    pending_extra["expected"] = {"status": "to_be_observed", "http_requests": []}
    assert list(validator.iter_errors(pending_extra))

    missing_outcome = _transport_fixture()
    missing_outcome_expected = missing_outcome["expected"]
    assert isinstance(missing_outcome_expected, dict)
    missing_outcome_expected.pop("adapter_outcome")
    assert list(validator.iter_errors(missing_outcome))

    core_observed = _transport_fixture()
    core_observed["kind"] = "core_http"
    core_observed["input"] = {
        "adapter_config": _transport_fixture()["input"]["adapter_config"],
        "operation": {
            "request": {
                "messages": [{"role": "user", "text": "hello"}],
                "consume": "buffered",
            },
            "route": {"targets": ["openai-compat:fixture-model"]},
        },
    }
    core_observed["expected"] = {
        "status": "observed",
        "http_requests": [],
        "wire_limits": [],
        "core": _core_fixture({"none": True})["expected"],
    }
    assert not list(validator.iter_errors(core_observed))

    core_pending = _transport_fixture()
    core_pending["kind"] = "core_http"
    core_pending["input"] = core_observed["input"]
    core_pending["expected"] = {"status": "to_be_observed"}
    assert not list(validator.iter_errors(core_pending))

    core_with_adapter_outcome = _transport_fixture()
    core_with_adapter_outcome["kind"] = "core_http"
    core_with_adapter_outcome["input"] = core_observed["input"]
    core_with_adapter_outcome_expected = core_with_adapter_outcome["expected"]
    assert isinstance(core_with_adapter_outcome_expected, dict)
    core_with_adapter_outcome_expected.pop("adapter_outcome")
    core_with_adapter_outcome_expected["core"] = _core_fixture({"none": True})["expected"]
    core_with_adapter_outcome_expected["adapter_outcome"] = {"events": []}
    assert list(validator.iter_errors(core_with_adapter_outcome))

    adapter_with_core_outcome = _transport_fixture()
    adapter_with_core_outcome_expected = adapter_with_core_outcome["expected"]
    assert isinstance(adapter_with_core_outcome_expected, dict)
    adapter_with_core_outcome_expected["core"] = _core_fixture({"none": True})["expected"]
    assert list(validator.iter_errors(adapter_with_core_outcome))


def test_transport_schema_closes_config_wire_headers_and_outcome() -> None:
    validator = validate_fixtures._schema(
        "transport-v0.schema.json", specification_root=ROOT / "specification"
    )

    missing_config = _transport_fixture()
    missing_input = missing_config["input"]
    assert isinstance(missing_input, dict)
    config = missing_input["adapter_config"]
    assert isinstance(config, dict)
    config.pop("api_key")
    assert list(validator.iter_errors(missing_config))

    reserved_header = _transport_fixture()
    reserved_input = reserved_header["input"]
    assert isinstance(reserved_input, dict)
    headers = reserved_input["adapter_config"]["headers"]
    assert isinstance(headers, dict)
    headers["authorization"] = "Bearer override"
    assert list(validator.iter_errors(reserved_header))

    unsupported_mechanism = _transport_fixture()
    unsupported_input = unsupported_mechanism["input"]
    assert isinstance(unsupported_input, dict)
    wire = unsupported_input["wire"]
    assert isinstance(wire, dict)
    wire["mechanism"] = "json_schema"
    assert list(validator.iter_errors(unsupported_mechanism))

    upper_case_header = _transport_fixture()
    upper_case_expected = upper_case_header["expected"]
    assert isinstance(upper_case_expected, dict)
    upper_case_expected["http_requests"] = [
        {"method": "POST", "path": "/chat/completions", "headers": {"X-Trace": "1"}, "body": {}, "stream": True}
    ]
    assert list(validator.iter_errors(upper_case_header))

    invalid_event = _transport_fixture()
    invalid_expected = invalid_event["expected"]
    assert isinstance(invalid_expected, dict)
    invalid_expected["adapter_outcome"] = {"events": [{"tool_call": {}}]}
    assert list(validator.iter_errors(invalid_event))

    invalid_consume = _transport_fixture()
    invalid_consume["kind"] = "core_http"
    invalid_consume["input"] = {
        "adapter_config": _transport_fixture()["input"]["adapter_config"],
        "operation": {
            "request": {
                "messages": [{"role": "user", "text": "hello"}],
                "consume": "close_without_advance",
            },
            "route": {"targets": ["openai-compat:fixture-model"]},
        },
    }
    invalid_consume["expected"] = {
        "status": "observed",
        "http_requests": [],
        "wire_limits": [],
        "core": _core_fixture({"none": True})["expected"],
    }
    assert list(validator.iter_errors(invalid_consume))


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
    _copy_validation_schemas(specification)
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
    _copy_validation_schemas(specification)
    (specification / "inventories").mkdir(parents=True)
    normative = specification / "core-generation.md"
    normative.write_text("# Supplied anchor\n", encoding="utf-8", newline="\n")
    inventory = specification / "inventories" / "core-generation-v0.json"

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
        return validate_fixtures.validate(root, specification_root=specification)

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


def test_explicit_arbitrary_specification_root_resolves_canonical_refs_within_it(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "chosen-root"
    fixtures = selected / "fixtures"
    _copy_validation_schemas(selected)
    (selected / "inventories").mkdir(parents=True)
    (selected / "core-generation.md").write_text(
        "# Selected anchor\n", encoding="utf-8", newline="\n"
    )
    inventory = selected / "inventories" / "core-generation-v0.json"

    def problems_for(reference: str) -> list[str]:
        inventory.write_text(
            json.dumps(
                {
                    "profile": "core-generation",
                    "profile_revision": "v0",
                    "requirements": [
                        {
                            "id": "proof",
                            "spec_ref": reference,
                            "case_ids": ["normalization/roles-ordered-text"],
                        }
                    ],
                    "cases": [],
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        return validate_fixtures.validate(fixtures, specification_root=selected)

    valid = problems_for("specification/core-generation.md#selected-anchor")
    assert not any("spec_ref" in problem for problem in valid)
    missing = problems_for("specification/core-generation.md#checkout-only-anchor")
    assert any("missing fragment" in problem for problem in missing)
    (tmp_path / "specification").mkdir()
    (tmp_path / "specification" / "core-generation.md").write_text(
        "# Checkout only anchor\n", encoding="utf-8", newline="\n"
    )
    checkout_only = problems_for("specification/core-generation.md#checkout-only-anchor")
    assert any("missing fragment" in problem for problem in checkout_only)
    assert any(
        "has invalid spec_ref" in problem
        for problem in problems_for("specification/missing.md#selected-anchor")
    )


def test_selected_specification_root_controls_fixture_schema_and_leaves_globals_intact(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "specification"
    schemas = selected / "schemas"
    schemas.mkdir(parents=True)
    for name in ("fixture-v0.schema.json", "transport-v0.schema.json", "inventory-v0.schema.json"):
        shutil.copy2(ROOT / "specification" / "schemas" / name, schemas / name)
    fixture_schema = json.loads((schemas / "fixture-v0.schema.json").read_text(encoding="utf-8"))
    fixture_schema["allOf"] = [False]
    (schemas / "fixture-v0.schema.json").write_text(json.dumps(fixture_schema), encoding="utf-8")
    fixtures = selected / "fixtures"
    target = fixtures / "core-generation" / "fixture.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(_core_fixture({"none": True})), encoding="utf-8")

    global_specification = validate_fixtures.SPECIFICATION
    assert not validate_fixtures.validate(fixtures)
    assert validate_fixtures.validate(fixtures, specification_root=selected)
    assert global_specification == validate_fixtures.SPECIFICATION


def test_selected_specification_root_controls_report_schema(tmp_path: Path) -> None:
    selected = tmp_path / "specification"
    schemas = selected / "schemas"
    schemas.mkdir(parents=True)
    report_schema = json.loads(
        (ROOT / "specification" / "schemas" / "report-v0.schema.json").read_text(encoding="utf-8")
    )
    report_schema["allOf"] = [False]
    (schemas / "report-v0.schema.json").write_text(json.dumps(report_schema), encoding="utf-8")
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
        "cases": [
            {
                "id": "normalization/unsupported-image-part",
                "verdict": "extension",
                "detail": None,
                "evidence": {"native_outcome": {"none": True}, "adapter_entries": []},
            }
        ],
        "counts": {"pass": 0, "fail": 0, "error": 0, "extension": 1},
    }
    assert not validate_fixtures.validate_report(report)
    assert validate_fixtures.validate_report(report, specification_root=selected)


def test_explicit_specification_root_never_falls_back_to_fixture_tree_inventory(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "selected-specification"
    _copy_validation_schemas(selected)
    fixture_root = tmp_path / "other-fixtures"
    fallback_inventory = fixture_root / "inventories" / "core-generation-v0.json"
    fallback_inventory.parent.mkdir(parents=True)
    fallback_inventory.write_text("{ broken", encoding="utf-8")

    assert not validate_fixtures.validate(fixture_root, specification_root=selected)


def test_explicit_fixture_paths_reject_intermediate_link_or_reparse_directory(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "fixtures"
    target = root / "core-generation"
    target.mkdir(parents=True)
    fixture = target / "selected.json"
    fixture.write_text(json.dumps(_core_fixture({"none": True})), encoding="utf-8")
    linked = root / "linked"
    selected = linked / "selected.json"
    try:
        linked.symlink_to(target, target_is_directory=True)
    except OSError:
        monkeypatch.setattr(
            validate_fixtures,
            "_is_link_or_reparse",
            lambda path: path == linked,
        )
    problems = validate_fixtures.validate(root, fixture_paths=[selected])
    assert any("unsafe selected fixture path" in problem for problem in problems)


def test_missing_explicit_specification_root_returns_validation_diagnostics(tmp_path: Path) -> None:
    missing = tmp_path / "missing-specification"
    root = tmp_path / "fixtures"
    problems = validate_fixtures.validate(root, specification_root=missing)
    assert len(problems) == 1
    assert "selected schema is unavailable or invalid" in problems[0]
    report_problems = validate_fixtures.validate_report({}, specification_root=missing)
    assert len(report_problems) == 1
    assert "report schema is unavailable or invalid" in report_problems[0]


def test_explicit_fixture_paths_ignore_unlisted_future_fixture(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    selected = root / "core-generation" / "selected.json"
    extra = root / "core-generation" / "future.json"
    selected.parent.mkdir(parents=True)
    selected.write_text(
        json.dumps(_core_fixture({"none": True}, case_id="normalization/other")),
        encoding="utf-8",
    )
    extra.write_text("{ not JSON", encoding="utf-8")

    assert not validate_fixtures.validate(root, fixture_paths=[selected])
    assert validate_fixtures.validate(root)


def test_explicit_fixture_paths_reject_missing_unsafe_duplicate_and_inventory_mismatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fixtures"
    selected = root / "core-generation" / "selected.json"
    selected.parent.mkdir(parents=True)
    selected.write_text(
        json.dumps(_core_fixture({"none": True}, case_id="normalization/other")),
        encoding="utf-8",
    )
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_core_fixture({"none": True})), encoding="utf-8")

    path_problems = validate_fixtures.validate(
        root,
        fixture_paths=[selected, selected, root / "core-generation" / "missing.json", outside],
    )
    assert any("unsafe or duplicate selected" in problem for problem in path_problems)
    assert any("selected fixture is missing" in problem for problem in path_problems)
    assert any("unsafe selected fixture" in problem for problem in path_problems)

    inventory = root / "inventories" / "core-generation-v0.json"
    inventory.parent.mkdir()
    inventory.write_text(
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
                        "path": "specification/fixtures/core-generation/selected.json",
                        "family": "normalization",
                        "extension": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    mismatch = validate_fixtures.validate(
        root,
        coverage=True,
        family="core-generation",
        fixture_paths=[selected],
    )
    assert any("fixture ID is absent from fixture tree" in problem for problem in mismatch)


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

def test_selected_schema_unresolved_references_are_diagnostics_without_network(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "specification"
    fixtures = selected / "fixtures"
    _copy_validation_schemas(selected)
    fixture_path = fixtures / "core-generation" / "case.json"
    fixture_path.parent.mkdir(parents=True)
    fixture_path.write_text(json.dumps(_core_fixture({"none": True})), encoding="utf-8")

    retrieval_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def unexpected_network(*args: object, **kwargs: object) -> object:
        retrieval_calls.append((args, kwargs))
        raise AssertionError(f"schema evaluation attempted network retrieval: {args!r} {kwargs!r}")

    monkeypatch.setattr(urllib.request, "urlopen", unexpected_network)
    fixture_schema = selected / "schemas" / "fixture-v0.schema.json"
    fixture_schema.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$ref": "https://example.invalid/missing",
            }
        ),
        encoding="utf-8",
    )
    fixture_problems = validate_fixtures.validate(fixtures, specification_root=selected)
    assert any("selected schema reference is unavailable" in problem for problem in fixture_problems)

    report_schema = selected / "schemas" / "report-v0.schema.json"
    report_schema.write_text(json.dumps({"$ref": "https://example.invalid/missing"}), encoding="utf-8")
    report_problems = validate_fixtures.validate_report({}, specification_root=selected)
    assert any("selected schema reference is unavailable" in problem for problem in report_problems)
    assert retrieval_calls == []

    fixture_schema.write_text(json.dumps({"type": 3}), encoding="utf-8")
    malformed_fixture = validate_fixtures.validate(fixtures, specification_root=selected)
    assert len(malformed_fixture) == 1
    assert "selected schema is unavailable or invalid" in malformed_fixture[0]

    report_schema.write_text(json.dumps({"type": 3}), encoding="utf-8")
    malformed_report = validate_fixtures.validate_report({}, specification_root=selected)
    assert len(malformed_report) == 1
    assert "report schema is unavailable or invalid" in malformed_report[0]


def test_selected_transport_schema_uses_only_its_registered_fixture_sibling(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "selected-specification"
    schemas = selected / "schemas"
    fixtures = tmp_path / "corpus"
    transport = fixtures / "transport" / "case.json"
    schemas.mkdir(parents=True)
    transport.parent.mkdir(parents=True)
    fixture_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "fixture-v0.schema.json",
        "$defs": {"value": {"type": "string"}},
    }
    transport_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "transport-v0.schema.json",
        "type": "object",
        "required": ["value"],
        "properties": {"value": {"$ref": "fixture-v0.schema.json#/$defs/value"}},
    }
    (schemas / "fixture-v0.schema.json").write_text(json.dumps(fixture_schema), encoding="utf-8")
    (schemas / "transport-v0.schema.json").write_text(
        json.dumps(transport_schema), encoding="utf-8"
    )
    (schemas / "inventory-v0.schema.json").write_text("{}", encoding="utf-8")
    transport.write_text(json.dumps({"value": "selected"}), encoding="utf-8")

    retrieval_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def unexpected_network(*args: object, **kwargs: object) -> object:
        retrieval_calls.append((args, kwargs))
        raise AssertionError(f"schema evaluation attempted network retrieval: {args!r} {kwargs!r}")

    monkeypatch.setattr(urllib.request, "urlopen", unexpected_network)
    assert not validate_fixtures.validate(fixtures, specification_root=selected)
    assert retrieval_calls == []

    fixture_schema["$defs"]["value"] = {"type": "integer"}
    (schemas / "fixture-v0.schema.json").write_text(json.dumps(fixture_schema), encoding="utf-8")
    assert any(
        "is not of type 'integer'" in problem
        for problem in validate_fixtures.validate(fixtures, specification_root=selected)
    )

    (schemas / "fixture-v0.schema.json").unlink()
    assert any(
        "selected schema is unavailable or invalid" in problem
        for problem in validate_fixtures.validate(fixtures, specification_root=selected)
    )


def test_selected_transport_fixture_resource_requires_draft_2020_12(tmp_path: Path) -> None:
    selected = tmp_path / "selected-specification"
    schemas = selected / "schemas"
    fixtures = tmp_path / "corpus"
    transport = fixtures / "transport" / "case.json"
    schemas.mkdir(parents=True)
    transport.parent.mkdir(parents=True)
    transport_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "transport-v0.schema.json",
        "type": "object",
        "properties": {"value": {"$ref": "fixture-v0.schema.json#/$defs/value"}},
    }
    (schemas / "transport-v0.schema.json").write_text(
        json.dumps(transport_schema), encoding="utf-8"
    )
    (schemas / "inventory-v0.schema.json").write_text("{}", encoding="utf-8")
    transport.write_text(json.dumps({"value": "selected"}), encoding="utf-8")

    for sibling, detail in (
        ({"$defs": {"value": {"type": "string"}}}, "must declare the Draft 2020-12"),
        (
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "$defs": {"value": {"type": "string"}},
            },
            "must declare the Draft 2020-12",
        ),
        (
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": 3,
            },
            "selected schema is unavailable or invalid",
        ),
    ):
        (schemas / "fixture-v0.schema.json").write_text(json.dumps(sibling), encoding="utf-8")
        problems = validate_fixtures.validate(fixtures, specification_root=selected)
        assert len(problems) == 1
        assert "selected schema is unavailable or invalid" in problems[0]
        assert detail in problems[0]


def test_default_custom_fixture_tree_uses_adjacent_normative_markdown(tmp_path: Path) -> None:
    fixture_root = tmp_path / "specification" / "fixtures"
    inventory = fixture_root / "inventories" / "core-generation-v0.json"
    inventory.parent.mkdir(parents=True)
    normative = tmp_path / "specification" / "core-generation.md"

    def problems_for(reference: str, heading: str) -> list[str]:
        normative.write_text(f"# {heading}\n", encoding="utf-8", newline="\n")
        inventory.write_text(
            json.dumps(
                {
                    "profile": "core-generation",
                    "profile_revision": "v0",
                    "requirements": [
                        {
                            "id": "adjacent",
                            "spec_ref": reference,
                            "case_ids": [],
                        }
                    ],
                    "cases": [],
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        return validate_fixtures.validate(fixture_root)

    valid = problems_for("specification/core-generation.md#adjacent-only", "Adjacent only")
    assert not any("spec_ref" in problem or "missing fragment" in problem for problem in valid)
    altered = problems_for("specification/core-generation.md#adjacent-only", "Altered")
    assert any("missing fragment" in problem for problem in altered)
    missing = problems_for("specification/missing.md#adjacent-only", "Adjacent only")
    assert any("has invalid spec_ref" in problem for problem in missing)
