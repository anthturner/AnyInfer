"""Independent Python observations for the input-only native schema qualification corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from anyinfer.schema.repair import build_repair_messages
from anyinfer.schema.validate import extract_json, validate
from anyinfer.types import user

_FIXTURE = Path(__file__).parent / "fixtures" / "sdk-schema-v1" / "common-input.json"


def _input() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _case(case_id: str) -> dict[str, Any]:
    return next(case for case in _input()["cases"] if case["id"] == case_id)


@pytest.mark.parametrize(
    "case_id",
    [
        "draft3-property-required",
        "draft4-boolean-exclusive-minimum",
        "draft6-numeric-exclusive-minimum",
        "draft7-if-then-else",
        "draft2019-recursive-reference",
        "draft2020-dynamic-reference",
    ],
)
def test_shared_dialect_inputs_select_python_reachable_validation_semantics(case_id: str) -> None:
    """The fixture carries input only; each syntax boundary must reject its supplied instance."""
    case = _case(case_id)
    assert validate(case["instance"], case["schema"])


@pytest.mark.parametrize("case_id", ["invalid-type-schema", "invalid-required-schema"])
def test_shared_invalid_schema_inputs_are_controlled_late_validation(case_id: str) -> None:
    case = _case(case_id)
    messages = validate(case["instance"], case["schema"])
    assert len(messages) == 1
    assert "supplied JSON Schema is itself invalid" in messages[0]


@pytest.mark.parametrize(
    ("case_id", "valid"),
    [
        ("format-is-disabled-by-default", True),
        ("local-definitions-reference", False),
        ("boolean-is-not-integer", False),
        ("integral-float-is-integer", True),
        ("large-integer-const", True),
        ("multiple-of-binary-float", False),
        ("unicode-scalar-length-valid", True),
        ("unicode-scalar-length-invalid", False),
        ("unicode-dot-pattern", True),
        ("unicode-word-pattern", True),
        ("python-named-group-pattern", True),
        ("nested-instance-paths", False),
        ("required-over-five", False),
        ("additional-properties-unicode-order", False),
    ],
)
def test_shared_general_validator_inputs_observe_python_baseline(case_id: str, valid: bool) -> None:
    case = _case(case_id)
    messages = validate(case["instance"], case["schema"])
    assert (not messages) is valid


def test_shared_input_extraction_preserves_first_candidate_and_null_boundaries() -> None:
    observations = {entry["id"]: extract_json(entry["text"]) for entry in _input()["extraction_inputs"]}
    assert observations["whole-null"] == (None, None)
    assert observations["fenced-object"] == ({"ok": True}, None)
    assert observations["quoted-brace"] == ({"text": "a } brace", "n": 1}, None)
    assert observations["first-malformed-not-rescued"][0] is None
    assert "malformed JSON" in observations["first-malformed-not-rescued"][1]
    assert observations["empty"] == (None, "response was empty")


def test_shared_input_repair_extends_the_same_conversation_after_real_validation() -> None:
    repair = _input()["repair_inputs"]
    errors = validate(json.loads(repair["invalid_response"]), repair["schema"])
    original = tuple(user(entry["text"]) for entry in repair["messages"])

    messages = build_repair_messages(original, repair["invalid_response"], errors)

    assert len(messages) == len(original) + 2
    assert messages[:-2] == original
    assert messages[-2].role == "assistant"
    assert messages[-2].text == repair["invalid_response"]
    assert messages[-1].role == "user"
    assert errors[0] in messages[-1].text
    assert not validate(json.loads(repair["corrected_response"]), repair["schema"])
