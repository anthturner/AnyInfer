"""Focused behavior tests for portable fixture comparison."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from anyinfer.schema._capture import _OperationCapture

from . import comparison
from .projection import MissingEvidenceError
from .records import NativeRun
from .runner import run_fixture


def _fixture(*, expected: dict[str, Any], extension: str | None = None, case_id: str = "routing/basic") -> dict[str, Any]:
    fixture: dict[str, Any] = {
        "id": case_id,
        "request": {"sampling": {"temperature": 0.5}},
        "expected": expected,
    }
    if extension is not None:
        fixture["extension"] = extension
    return fixture


def _actual(*, calls: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "status": "observed",
        "calls": calls or [],
        "clock_advances_ms": [],
        "telemetry": {"repair_attempted": [], "parameter_dropped": []},
        "events": [],
        "outcome": {"none": True},
        "accounting": None,
    }
    value.update(extra)
    return value


def _result(**changes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "text": "answer",
        "structured": {"n": 17},
        "target": {"provider_id": "fixture", "model": "alpha"},
        "finish_reason": "stop",
        "usage": {"input_tokens": None, "output_tokens": None},
        "timing": {"first_token_ms": "non_null", "total_ms": "present"},
        "structured_mechanism": None,
        "repair_attempts": 0,
        "attempts": [],
        "warnings": [],
    }
    result.update(changes)
    return result


def _install(monkeypatch: pytest.MonkeyPatch, observation: dict[str, Any]) -> None:
    monkeypatch.setattr(comparison, "project_run", lambda run: observation)
    monkeypatch.setattr(
        comparison,
        "validate_capture",
        lambda run, allow_unprojectable=False: {"entries": len(run.requests)},
    )
    monkeypatch.setattr(comparison, "sampling_for_call", lambda run, index: {"temperature": 0.5})


def test_pending_retains_observations_without_passing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _actual())
    answer = comparison.compare_fixture(_fixture(expected={"status": "to_be_observed"}), NativeRun("routing/basic"))
    assert answer["verdict"] is None
    assert answer["observations"]["status"] == "observed"


def test_pending_harness_capture_failure_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(comparison, "project_run", lambda run: (_ for _ in ()).throw(MissingEvidenceError("harness")))
    answer = comparison.compare_fixture(_fixture(expected={"status": "to_be_observed"}), NativeRun("routing/basic"))
    assert answer["verdict"] == "error"
    assert "harness" in answer["detail"]


def test_call_expands_schema_and_feedback_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_messages = [{"role": "user", "text": ["Fix: ", {"$repair_feedback": True}]}]
    actual = _actual(calls=[{"model": "m", "role": "correction", "mechanism": None, "timeout_s": 1, "max_response_bytes": 2, "messages": expected_messages}])
    _install(monkeypatch, actual)
    monkeypatch.setattr(comparison, "native_feedback_for_call", lambda run, index: ("bad", "worse"))
    actual["calls"][0]["messages"][0]["role"] = "user"
    actual["calls"][0]["messages"][0]["text"] = "Fix: - bad\n- worse"
    fixture = _fixture(expected={"status": "observed", "calls": [{"model": "m", "role": "correction", "mechanism": None, "timeout_s": 1.0, "max_response_bytes": 2, "messages": expected_messages}], "outcome": {"none": True}})
    assert comparison.compare_fixture(fixture, NativeRun("routing/basic"))["verdict"] == "pass"


def test_same_as_call_uses_earlier_one_based_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = [
        {"model": "m", "role": "original", "mechanism": None, "timeout_s": 1, "max_response_bytes": 2, "messages": [{"role": "user", "text": "hi"}]},
        {"model": "m", "role": "original", "mechanism": None, "timeout_s": 1, "max_response_bytes": 2, "messages": [{"role": "user", "text": "hi"}]},
    ]
    _install(monkeypatch, _actual(calls=calls))
    fixture = _fixture(expected={"status": "observed", "calls": [{"messages": [{"role": "user", "text": "hi"}]}, {"messages": "same_as_call_1"}], "outcome": {"none": True}})
    assert comparison.compare_fixture(fixture, NativeRun("routing/basic"))["verdict"] == "pass"
    fixture["expected"]["calls"][1]["messages"] = "same_as_call_2"
    assert comparison.compare_fixture(fixture, NativeRun("routing/basic"))["verdict"] == "error"


def test_control_numbers_are_numeric_but_structured_values_stay_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    actual = _actual(outcome={"result": _result(structured={"n": 17.0})})
    _install(monkeypatch, actual)
    fixture = _fixture(expected={"status": "observed", "outcome": {"result": _result(structured={"n": 17})}})
    assert comparison.compare_fixture(fixture, NativeRun("routing/basic"))["verdict"] == "pass"
    fixture["expected"]["outcome"] = {"result": _result(text=0.0)}
    actual["outcome"] = {"result": _result(text=-0.0)}
    assert comparison.compare_fixture(fixture, NativeRun("routing/basic"))["verdict"] == "fail"


def test_usage_null_may_be_omitted_but_zero_may_not(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _actual(outcome={"result": _result(usage={"input_tokens": 0, "output_tokens": None})}))
    expected: dict[str, Any] = {"status": "observed", "outcome": {"result": _result(usage={"input_tokens": 0})}}
    assert comparison.compare_fixture(_fixture(expected=expected), NativeRun("routing/basic"))["verdict"] == "pass"
    expected["outcome"]["result"]["usage"] = {}
    assert comparison.compare_fixture(_fixture(expected=expected), NativeRun("routing/basic"))["verdict"] == "fail"


def test_event_barrier_is_not_coalesced(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _actual(events=[{"text": "a"}, {"timing_mark": "first"}, {"text": "b"}]))
    expected = {"status": "observed", "events": [{"text": "ab"}], "outcome": {"none": True}}
    assert comparison.compare_fixture(_fixture(expected=expected), NativeRun("routing/basic"))["verdict"] == "fail"


def test_timing_compares_presence_markers_not_elapsed_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _actual(outcome={"result": _result()}))
    expected: dict[str, Any] = {"status": "observed", "outcome": {"result": _result()}}
    assert comparison.compare_fixture(_fixture(expected=expected), NativeRun("routing/basic"))["verdict"] == "pass"
    expected["outcome"]["result"]["timing"]["first_token_ms"] = "null"
    assert comparison.compare_fixture(_fixture(expected=expected), NativeRun("routing/basic"))["verdict"] == "fail"


def test_result_requires_full_shape_and_values(monkeypatch: pytest.MonkeyPatch) -> None:
    actual = _actual(outcome={"result": _result()})
    _install(monkeypatch, actual)
    assert comparison.compare_fixture(_fixture(expected={"status": "observed", "outcome": {"result": {}}}), NativeRun("routing/basic"))["verdict"] == "fail"
    partial = _result()
    partial.pop("warnings")
    assert comparison.compare_fixture(_fixture(expected={"status": "observed", "outcome": {"result": partial}}), NativeRun("routing/basic"))["verdict"] == "fail"
    actual["outcome"] = {"result": _result(text="wrong")}
    assert comparison.compare_fixture(_fixture(expected={"status": "observed", "outcome": {"result": _result()}}), NativeRun("routing/basic"))["verdict"] == "fail"


def test_eligible_extension_requires_normative_evidence_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _actual())
    monkeypatch.setattr(comparison, "extension_evidence", lambda run: {"native_outcome": {"none": True}, "adapter_entries": []})
    answer = comparison.compare_fixture(_fixture(expected={"status": "observed"}, extension="targets.alias"), NativeRun("routing/basic"), extensions=("targets.alias",))
    assert answer["verdict"] == "extension"
    monkeypatch.setattr(comparison, "extension_evidence", lambda run: {"native_outcome": {"result": True}, "adapter_entries": []})
    assert comparison.compare_fixture(_fixture(expected={"status": "observed"}, extension="targets.alias"), NativeRun("routing/basic"), extensions=("targets.alias",))["verdict"] == "error"


def test_extension_dispatch_precedes_portable_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(comparison, "project_run", lambda run: (_ for _ in ()).throw(MissingEvidenceError("unprojectable")))
    monkeypatch.setattr(comparison, "validate_capture", lambda run, allow_unprojectable=False: {"entries": 0})
    monkeypatch.setattr(comparison, "extension_evidence", lambda run: {"native_outcome": {"none": True}, "adapter_entries": []})
    answer = comparison.compare_fixture(_fixture(expected={"status": "observed"}, extension="targets.alias"), NativeRun("routing/basic"), extensions=("targets.alias",))
    assert answer["verdict"] == "extension"


def test_extension_harness_or_missing_capture_remains_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(comparison, "validate_capture", lambda run, allow_unprojectable=False: (_ for _ in ()).throw(MissingEvidenceError("missing capture")))
    answer = comparison.compare_fixture(_fixture(expected={"status": "observed"}, extension="targets.alias"), NativeRun("routing/basic", error=RuntimeError("harness"), error_stage="harness"), extensions=("targets.alias",))
    assert answer["verdict"] == "error"
    assert answer["detail"] == "missing capture"


@pytest.mark.parametrize(
    "error",
    (asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(), GeneratorExit()),
)
def test_extension_never_claims_cancellation_or_fatal_failure(error: BaseException) -> None:
    answer = comparison.compare_fixture(
        _fixture(expected={"status": "observed"}, extension="targets.alias"),
        NativeRun("routing/basic", error=error, error_stage="operation"),
        extensions=("targets.alias",),
    )
    assert answer["verdict"] == "error"


async def test_explicit_cancellation_remains_an_ordinary_pending_observation() -> None:
    path = Path(__file__).parents[3] / "specification/fixtures/core-generation/streaming/cancel-mid-stream.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    run = await run_fixture(fixture)
    answer = comparison.compare_fixture(fixture, run, extensions=("targets.alias",))
    assert fixture.get("extension") is None
    assert answer["verdict"] is None, answer


@pytest.mark.parametrize(
    "family, name",
    (("schema-admission", "unsupported-boolean-subschema"), ("schema-admission", "unsupported-dialect-null")),
)
async def test_native_extension_boundary_records_honest_extension(family: str, name: str) -> None:
    path = Path(__file__).parents[3] / "specification/fixtures/core-generation" / family / f"{name}.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    run = await run_fixture(fixture)
    answer = comparison.compare_fixture(fixture, run, extensions=(str(fixture["extension"]),))
    assert answer["verdict"] == "extension", answer
    assert answer["observations"] is None
    assert answer["evidence"] is not None


def test_unapproved_extension_compares_portable_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _actual(outcome={"error": {"category": "unsupported_input"}}))
    fixture = _fixture(expected={"status": "observed", "outcome": {"none": True}}, extension="targets.alias")
    assert comparison.compare_fixture(fixture, NativeRun("routing/basic"), extensions=())["verdict"] == "fail"


def test_buffered_mirror_requires_fresh_captured_buffered_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _actual())
    fixture = _fixture(expected={"status": "to_be_observed"}, case_id="streaming/buffered-equals-streamed")
    assert comparison.compare_fixture(fixture, NativeRun("streaming/buffered-equals-streamed"))["verdict"] == "error"
    streamed = NativeRun("streaming/buffered-equals-streamed", consumption_mode="stream")
    assert comparison.compare_fixture(fixture, replace(streamed, mirror=streamed))["verdict"] == "error"
    operation = _OperationCapture()
    copied = replace(streamed, operations=(operation,))
    copied_mirror = replace(copied, consumption_mode="buffered")
    assert comparison.compare_fixture(fixture, replace(copied, mirror=copied_mirror))["verdict"] == "error"
    same_id_mirror = NativeRun(
        "streaming/buffered-equals-streamed",
        operations=(_OperationCapture(operation_id=operation.operation_id),),
        consumption_mode="buffered",
    )
    assert comparison.compare_fixture(fixture, replace(copied, mirror=same_id_mirror))["verdict"] == "error"
    primary = NativeRun("streaming/buffered-equals-streamed", operations=(_OperationCapture(),), consumption_mode="stream")
    mirror = NativeRun("streaming/buffered-equals-streamed", operations=(_OperationCapture(),), consumption_mode="buffered")
    paired = replace(primary, mirror=mirror)
    assert comparison.compare_fixture(fixture, paired)["verdict"] is None
    monkeypatch.setattr(comparison, "project_run", lambda run: _actual(calls=[{"model": "other"}]) if run is mirror else _actual())
    assert comparison.compare_fixture(fixture, paired)["verdict"] == "fail"
