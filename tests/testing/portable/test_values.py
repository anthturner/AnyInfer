from __future__ import annotations

import math

import pytest

from .values import (
    MissingEvidenceError,
    ValueDomainError,
    coalesce_events,
    control_number_equal,
    ensure_value_domain,
    expand_segments,
    feedback_bullets,
    schema_equal,
    schema_prompt,
    type_aware_equal,
)


def test_values_domain_and_equality() -> None:
    ensure_value_domain({"x": [-(2**63), 2**63]})
    for value in (2**63 + 1, math.nan, "\ud800", {1: "x"}):
        with pytest.raises(ValueDomainError):
            ensure_value_domain(value)
    assert not type_aware_equal(True, 1)
    assert not type_aware_equal(-0.0, 0.0)
    assert schema_equal(-0.0, 0.0) and schema_equal(1, 1.0)
    assert not schema_equal(True, 1) and schema_equal({"a": 1, "b": 2}, {"b": 2, "a": 1})
    with pytest.raises(ValueDomainError):
        schema_equal(2**53 + 1, float(2**53 + 1))


def test_control_number_equality_is_numeric_only_at_declared_control_positions() -> None:
    assert not type_aware_equal(17, 17.0)
    assert control_number_equal(17, 17.0)
    assert control_number_equal(-0.0, 0.0)
    assert control_number_equal(2**63, 2**63)
    assert control_number_equal(None, None)
    assert not control_number_equal(None, 1)
    assert not control_number_equal(True, 1)
    with pytest.raises(ValueDomainError):
        control_number_equal(2**53 + 1, float(2**53 + 1))


def test_prompt_segments_and_events() -> None:
    prompt = schema_prompt({"z": "😀", "é": {"x": 0.001}})
    assert "\\u00e9" in prompt and "\\ud83d\\ude00" in prompt
    assert prompt.index('"z"') < prompt.index('"\\u00e9"')
    for schema in ({"x": 1.2345}, {"x": 1e-7}, {"x": -1e-7}, {"enum": [1.25e-4]}, {"const": 1e-7}):
        with pytest.raises(ValueDomainError):
            schema_prompt(schema)
    assert (
        expand_segments(["a", {"$repair_feedback": True}], native_messages=["native"])
        == "a- native"
    )
    with pytest.raises(MissingEvidenceError):
        expand_segments([{"$repair_feedback": True}])
    for marker in (
        {"$schema_prompt": False},
        {"$schema_prompt": 1},
        {"$repair_feedback": 1.0},
        {"$schema_prompt": True, "x": 1},
    ):
        with pytest.raises(ValueDomainError):
            expand_segments([marker])
    with pytest.raises(ValueDomainError):
        expand_segments({"$schema_prompt": True})
    assert coalesce_events([{"text": "a"}, {"text": "b"}, {"timing": {}}, {"text": "c"}]) == [
        {"text": "ab"},
        {"timing": {}},
        {"text": "c"},
    ]


def test_feedback_bullets_accept_tuple_evidence_with_order_and_multiplicity() -> None:
    assert feedback_bullets(("one", "one", "two")) == "- one\n- one\n- two"


def test_feedback_bullets_reject_scalar_evidence_through_direct_and_segment_calls() -> None:
    for evidence in ("native error", b"native error"):
        with pytest.raises(ValueDomainError):
            feedback_bullets(evidence)
    with pytest.raises(ValueDomainError):
        expand_segments([{"$repair_feedback": True}], native_messages="native error")
