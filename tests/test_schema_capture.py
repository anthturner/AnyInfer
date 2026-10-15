"""Private native-schema assessment capture compatibility checks."""

from __future__ import annotations

import importlib

import pytest

import anyinfer.schema._capture as capture
from anyinfer.providers.base import WireRequest
from anyinfer.schema._capture import (
    Issue,
    capture_enabled,
    capture_scope,
    new_operation,
    record_assessment,
    record_entered_wire,
    record_preparation,
)
from anyinfer.schema.validate import extract_json, validate
from anyinfer.types import user

validation = importlib.import_module("anyinfer.schema.validate")


def test_disabled_capture_keeps_native_messages_byte_identical() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    assert validate({"x": "no"}, schema) == ("x: 'no' is not of type 'integer'",)
    assert extract_json("") == (None, "response was empty")
    assert extract_json("not json") == (
        None,
        "response was not JSON and contained no JSON object or array",
    )
    assert validate({}, {"required": 17}) == (
        "the supplied JSON Schema is itself invalid: 17 is not of type 'array'",
    )


def test_capture_records_selected_native_error_and_typed_path() -> None:
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 7):
            errors = validate(
                {"a.b": "no", "a": {"b": "also no"}},
                {
                    "type": "object",
                    "properties": {
                        "a.b": {"type": "integer"},
                        "a": {"type": "object", "properties": {"b": {"type": "integer"}}},
                    },
                },
            )
    assert errors == (
        "a.b: 'also no' is not of type 'integer'",
        "a.b: 'no' is not of type 'integer'",
    )
    assessment = operations[0].assessments[0]
    assert assessment.source_entry_ordinal == 7
    assert assessment.issues is not None
    assert assessment.issues[0].instance_path == ("a", "b")
    assert assessment.issues[1].instance_path == ("a.b",)
    assert assessment.native_messages[0] != assessment.native_messages[1]


def test_capture_observes_extraction_and_schema_error_paths() -> None:
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 2):
            _, extraction_error = extract_json("not json")
        with capture_scope(operation, 2):
            schema_errors = validate({}, {"properties": {"x": {"required": 17}}})
    assert extraction_error == "response was not JSON and contained no JSON object or array"
    assert extraction_error == "response was not JSON and contained no JSON object or array"
    assert [assessment.kind for assessment in operations[0].assessments] == [
        "extraction",
        "invalid_schema",
    ]
    assert operations[0].assessments[0].issues[0].rule == "no_json_candidate"
    assert operations[0].assessments[1].schema_error_input_path == ("properties", "x", "required")
    assert operations[0].assessments[1].native_messages == schema_errors


def test_required_errors_are_capped_in_native_order() -> None:
    required = ["a", "b", "c", "d", "e", "f"]
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            errors = validate({}, {"type": "object", "required": required})
    assert len(errors) == 5
    assessment = operations[0].assessments[0]
    assert assessment.issues is not None
    assert [issue.params["property"] for issue in assessment.issues] == required[:5]


def test_portable_issue_params_are_exact_and_native_messages_remain_distinct() -> None:
    schema = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "additionalProperties": False,
    }
    value = {
        "x": True,
        "y": "no",
        "z": 1,
    }
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            validate(value, schema)
    issues = operations[0].assessments[0].issues
    assert issues is not None
    type_params = [issue.params for issue in issues if issue.rule == "type"]
    assert {tuple(params.items()) for params in type_params} == {
        (("expected", "integer"), ("actual", "boolean")),
        (("expected", "integer"), ("actual", "string")),
    }
    assert next(
        issue.json()["params"] for issue in issues if issue.rule == "additionalProperties"
    ) == {"unexpected": ["z"]}
    assert (
        operations[0].assessments[0].native_messages[0]
        != operations[0].assessments[0].native_messages[1]
    )


def test_extraction_identities_and_immutable_snapshots() -> None:
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            for text in ("", "prose", "{bad}"):
                extract_json(text)
    assessment = operations[0].assessments
    assert [item.issues[0].rule for item in assessment] == [
        "response_empty",
        "no_json_candidate",
        "malformed_json_candidate",
    ]
    assert assessment[0].issues[0].params == {}
    try:
        assessment[0].selected_native[0]["rule"] = "changed"  # type: ignore[index]
    except TypeError:
        pass
    else:
        raise AssertionError("capture snapshots must be immutable")


@pytest.mark.parametrize(
    ("schema", "value", "rule", "params"),
    [
        ({"type": "integer"}, True, "type", {"expected": "integer", "actual": "boolean"}),
        ({"type": "string"}, 2.0, "type", {"expected": "string", "actual": "integer"}),
        ({"enum": ["b", "a"]}, "x", "enum", {"allowed": ["b", "a"]}),
        ({"const": "x"}, "y", "const", {"expected": "x"}),
        ({"minimum": 2}, 1, "minimum", {"limit": 2, "actual": 1}),
        ({"maximum": 2}, 3, "maximum", {"limit": 2, "actual": 3}),
        ({"minLength": 2}, "x", "minLength", {"limit": 2, "actual": 1}),
        ({"maxLength": 1}, "xy", "maxLength", {"limit": 1, "actual": 2}),
        ({"minItems": 2}, [1], "minItems", {"limit": 2, "actual": 1}),
        ({"maxItems": 1}, [1, 2], "maxItems", {"limit": 1, "actual": 2}),
    ],
)
def test_every_admitted_scalar_rule_has_portable_params(
    schema: dict[str, object], value: object, rule: str, params: dict[str, object]
) -> None:
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            validate(value, schema)
    issue = operations[0].assessments[0].issues[0]
    assert issue.rule == rule
    assert issue.json()["params"] == params


def test_required_and_additional_params_and_invalid_schema_index_are_exact() -> None:
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            validate({"z": 1, "A": 2}, {"required": ["a"], "additionalProperties": False})
        with capture_scope(operation, 1):
            validate({}, {"required": ["ok", 17]})
    issues = operations[0].assessments[0].issues
    assert issues is not None
    assert [issue.json()["params"] for issue in issues] == [
        {"property": "a"},
        {"unexpected": ["A", "z"]},
    ]
    invalid = operations[0].assessments[1]
    assert invalid.issues[0].json()["params"] == {}
    assert invalid.schema_error_input_path == ("required", 1)


def test_required_association_is_per_nested_array_instance_and_tied_order_is_recorded() -> None:
    schema = {"type": "array", "items": {"type": "object", "required": ["a", "b"]}}
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            validate([{"a": 1}, {}], schema)
    assessment = operations[0].assessments[0]
    assert [issue.params["property"] for issue in assessment.issues] == ["b", "a", "b"]
    assert [item["pre_sort_ordinal"] for item in assessment.selected_native] == [0, 1, 2]
    assert [item["selected_order"] for item in assessment.selected_native] == [0, 1, 2]
    assert [item["group"] for item in assessment.selected_native] == [
        ((0,), ("items", "required")),
        ((1,), ("items", "required")),
        ((1,), ("items", "required")),
    ]


def test_interleaved_tied_rules_keep_actual_ordinals_and_selected_order() -> None:
    schema = {
        "type": "object",
        "required": ["missing"],
        "properties": {"x": {"type": "integer", "enum": [1]}},
    }
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            validate({"x": "bad"}, schema)
    assessment = operations[0].assessments[0]
    assert [issue.rule for issue in assessment.issues] == ["type", "enum", "required"]
    assert [item["pre_sort_ordinal"] for item in assessment.selected_native] == [1, 2, 0]
    assert [item["selected_order"] for item in assessment.selected_native] == [0, 1, 2]
    assert [item["group"] for item in assessment.selected_native] == [
        (("x",), ("properties", "x", "type")),
        (("x",), ("properties", "x", "enum")),
        ((), ("required",)),
    ]


def test_disabled_capture_never_projects_or_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("observation must be off")

    monkeypatch.setattr(validation, "_issue", fail)
    monkeypatch.setattr(capture, "_freeze", fail)
    assert validate("x", {"type": "integer"}) == ("<root>: 'x' is not of type 'integer'",)


def test_extraction_freeze_fault_keeps_native_error_and_marks_evidence_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = extract_json("not json")
    monkeypatch.setattr(
        validation,
        "_freeze",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("capture fault")),
    )
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            assert extract_json("not json") == native
    assert operations[0].evidence_available is False
    assert operations[0].assessments == []


def test_invalid_schema_freeze_fault_keeps_native_error_and_marks_evidence_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = {"required": 17}
    native = validate({}, schema)
    monkeypatch.setattr(
        validation,
        "_freeze",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("capture fault")),
    )
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            assert validate({}, schema) == native
    assert operations[0].evidence_available is False
    assert operations[0].assessments == []


def test_broader_schema_keeps_native_feedback_and_projection_fault_is_nonsemantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = {"pattern": "^x$"}
    native = validate("y", schema)
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            assert validate("y", schema) == native
    assert operations[0].assessments[0].issues[0].params == {}
    monkeypatch.setattr(validation, "_issue", lambda *_args: (_ for _ in ()).throw(RuntimeError()))
    with capture_enabled() as faulted:
        operation = new_operation()
        with capture_scope(operation, 0):
            assert validate("y", schema) == native
    assert faulted[0].evidence_available is False


@pytest.mark.parametrize("invoke", ["validate", "extract"])
def test_append_fault_preserves_native_outcome(
    monkeypatch: pytest.MonkeyPatch, invoke: str
) -> None:
    expected = (
        validate("x", {"type": "integer"}) if invoke == "validate" else extract_json("not json")
    )
    monkeypatch.setattr(
        capture._OperationCapture,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()),
    )
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            actual = (
                validate("x", {"type": "integer"})
                if invoke == "validate"
                else extract_json("not json")
            )
    assert actual == expected
    assert operations[0].evidence_available is False


def test_entered_wire_append_fault_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        capture._OperationCapture,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("capture fault")),
    )
    with capture_enabled() as operations:
        operation = new_operation()
        record_entered_wire(
            operation,
            entry_ordinal=0,
            role="original",
            repair_assessment_ref=None,
            wire=WireRequest(model="m", messages=(user("x"),)),
        )
    assert operations[0].evidence_available is False
    assert operations[0].entries == []


def test_assessment_count_cap_retains_first_then_rejects_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capture, "_MAX_ASSESSMENTS", 1)
    with capture_enabled() as operations:
        operation = new_operation()
        with capture_scope(operation, 0):
            record_assessment(
                kind="validation",
                issues=(Issue("type", (), (), {}),),
                native_messages=("m",),
                selected_native=({},),
            )
            record_assessment(
                kind="validation",
                issues=(Issue("type", (), (), {}),),
                native_messages=("m",),
                selected_native=({},),
            )
    assert len(operations[0].assessments) == 1
    assert operations[0].evidence_available is False


def test_preparation_retention_status_tracks_append_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = user("x")
    with capture_enabled() as operations:
        operation = new_operation()
        assert record_preparation(
            operation,
            source_entry_ordinal=0,
            assessment_ref="a",
            original_messages=(message,),
            raw_text="x",
            errors=("e",),
            built_messages=(message,),
        )
        monkeypatch.setattr(capture, "_MAX_SNAPSHOT_BYTES", operations[0].snapshot_bytes)
        assert not record_preparation(
            operation,
            source_entry_ordinal=0,
            assessment_ref="a",
            original_messages=(message,),
            raw_text="x",
            errors=("e",),
            built_messages=(message,),
        )
    assert operations[0].evidence_available is False


@pytest.mark.parametrize("category", ["assessment", "preparation", "wire"])
def test_byte_cap_independently_bounds_each_record_category(
    monkeypatch: pytest.MonkeyPatch, category: str
) -> None:
    message = user("x")
    wire = WireRequest(model="m", messages=(message,))

    def record(operation: object) -> None:
        if category == "assessment":
            with capture_scope(operation, 0):
                record_assessment(
                    kind="validation",
                    issues=(Issue("type", (), (), {}),),
                    native_messages=("m",),
                    selected_native=({},),
                )
        elif category == "preparation":
            record_preparation(
                operation,
                source_entry_ordinal=0,
                assessment_ref="a",
                original_messages=(message,),
                raw_text="x",
                errors=("e",),
                built_messages=(message,),
            )
        else:
            record_entered_wire(
                operation,
                entry_ordinal=0,
                role="original",
                repair_assessment_ref=None,
                wire=wire,
            )

    with capture_enabled() as measured:
        measured_operation = new_operation()
        record(measured_operation)
    record_size = measured[0].snapshot_bytes
    assert record_size > 0
    monkeypatch.setattr(capture, "_MAX_SNAPSHOT_BYTES", record_size)
    with capture_enabled() as operations:
        operation = new_operation()
        record(operation)
        record(operation)
    assert operations[0].snapshot_bytes == record_size
    assert operations[0].evidence_available is False
