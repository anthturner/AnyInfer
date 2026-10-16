"""Compare a portable fixture expectation with one native execution."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from .projection import (
    extension_evidence,
    native_feedback_for_call,
    project_run,
    sampling_for_call,
    validate_capture,
)
from .records import NativeRun
from .values import (
    MissingEvidenceError,
    ValueDomainError,
    coalesce_events,
    control_number_equal,
    expand_segments,
    schema_equal,
    type_aware_equal,
)

_EXTENSIONS = frozenset(
    {
        "targets.alias",
        "messages.non_text_parts",
        "messages.tool_role",
        "schema.unknown_keywords_ignored",
        "schema.combinators",
        "schema.boolean_subschema",
        "schema.other_dialects",
        "schema.ref",
    }
)
_CONTROL_SAMPLING = frozenset(
    {"temperature", "top_p", "presence_penalty", "frequency_penalty"}
)
_SAME_AS_CALL = re.compile(r"same_as_call_([1-9][0-9]*)$")
_RESULT_FIELDS = frozenset(
    {
        "text",
        "structured",
        "target",
        "finish_reason",
        "usage",
        "timing",
        "structured_mechanism",
        "repair_attempts",
        "attempts",
        "warnings",
    }
)


def compare_fixture(
    fixture: Mapping[str, Any], run: NativeRun, *, extensions: Sequence[str] = ()
) -> dict[str, Any]:
    """Return a development result for one observed portable fixture run."""
    case_id = fixture.get("id")
    result: dict[str, Any] = {
        "id": case_id,
        "verdict": "error",
        "detail": None,
        "observations": None,
        "evidence": None,
    }
    extension = fixture.get("extension")
    if isinstance(extension, str) and extension in _EXTENSIONS and extension in extensions:
        if isinstance(
            run.error,
            asyncio.CancelledError | KeyboardInterrupt | SystemExit | GeneratorExit,
        ):
            result["detail"] = "cancellation or fatal native failure cannot be an extension"
            return result
        try:
            validate_capture(run, allow_unprojectable=True)
            evidence = extension_evidence(run)
            _validate_extension_evidence(evidence)
        except (MissingEvidenceError, ValueDomainError) as exc:
            result["detail"] = str(exc)
            return result
        result.update(
            verdict="extension",
            detail=f"eligible extension: {extension}",
            evidence=evidence,
        )
        return result
    try:
        observations = project_run(run)
        result["observations"] = observations
        result["evidence"] = validate_capture(run)
        special_differences = _special_capture_differences(case_id, run, observations)
    except (MissingEvidenceError, ValueDomainError) as exc:
        result["detail"] = str(exc)
        return result

    expected = fixture.get("expected")
    if not isinstance(expected, Mapping):
        result["detail"] = "fixture expected value is missing"
        return result
    if special_differences:
        result.update(verdict="fail", detail="; ".join(special_differences))
        return result
    if expected.get("status") == "to_be_observed":
        result.update(verdict=None, detail="pending native observation")
        return result
    try:
        differences = _differences(fixture, expected, observations, run)
    except (MissingEvidenceError, ValueDomainError) as exc:
        result["detail"] = str(exc)
        return result
    if differences:
        result.update(verdict="fail", detail="; ".join(differences))
    else:
        result.update(verdict="pass", detail=None)
    return result


def _special_capture_differences(case_id: Any, run: NativeRun, actual: Mapping[str, Any]) -> list[str]:
    differences: list[str] = []
    if case_id == "streaming/buffered-equals-streamed":
        if run.mirror is None:
            raise MissingEvidenceError("buffered mirror is missing")
        if run.mirror is run or run.mirror.case_id != run.case_id:
            raise MissingEvidenceError("buffered mirror is not a fresh run for this case")
        if getattr(run, "consumption_mode", None) != "stream" or getattr(
            run.mirror, "consumption_mode", None
        ) != "buffered":
            raise MissingEvidenceError("stream/buffered mirror modes are not captured")
        if not run.operations or not run.mirror.operations:
            raise MissingEvidenceError("buffered mirror operation capture is missing")
        if any(left is right for left in run.operations for right in run.mirror.operations):
            raise MissingEvidenceError("buffered mirror reuses native operation capture")
        primary_ids = _operation_ids(run.operations)
        mirror_ids = _operation_ids(run.mirror.operations)
        if not primary_ids.isdisjoint(mirror_ids):
            raise MissingEvidenceError("buffered mirror reuses native operation identity")
        mirror = project_run(run.mirror)
        for field in ("calls", "telemetry", "outcome"):
            if not type_aware_equal(actual[field], mirror[field]):
                differences.append(f"buffered mirror {field}")
    if case_id == "extraction/duplicate-key-last-value-first-position" and (
        run.result is None or not isinstance(run.result.structured, dict)
    ):
        raise MissingEvidenceError("duplicate-key case lacks native structured object")
    return differences


def _operation_ids(operations: Sequence[Any]) -> set[str]:
    ids: set[str] = set()
    for operation in operations:
        operation_id = getattr(operation, "operation_id", None)
        if not isinstance(operation_id, str) or not operation_id:
            raise MissingEvidenceError("operation capture has no operation identity")
        try:
            UUID(operation_id)
        except ValueError as exc:
            raise MissingEvidenceError("operation capture identity is not a UUID") from exc
        if operation_id in ids:
            raise MissingEvidenceError("run repeats a native operation identity")
        ids.add(operation_id)
    return ids


def _differences(
    fixture: Mapping[str, Any], expected: Mapping[str, Any], actual: Mapping[str, Any], run: NativeRun
) -> list[str]:
    differences: list[str] = []
    for key in ("status", "clock_advances_ms", "telemetry", "accounting"):
        if key in expected and not type_aware_equal(expected[key], actual.get(key)):
            differences.append(key)
    if "events" in expected:
        wanted_events = coalesce_events(_as_event_list(expected["events"], "expected events"))
        actual_events = coalesce_events(_as_event_list(actual.get("events"), "actual events"))
        if not type_aware_equal(wanted_events, actual_events):
            differences.append("events")
    if "calls" in expected:
        differences.extend(_call_differences(fixture, expected["calls"], actual.get("calls"), run))
    if "outcome" in expected and not _outcome_equal(expected["outcome"], actual.get("outcome")):
        differences.append("outcome")
    if fixture.get("id") == "extraction/duplicate-key-last-value-first-position":
        wanted = _expected_structured(expected.get("outcome"))
        assert run.result is not None
        assert isinstance(run.result.structured, dict)
        if wanted is not None and list(wanted) != list(run.result.structured):
            differences.append("structured key order")
    return differences


def _as_event_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueDomainError(f"{label} must be event objects")
    return value


def _call_differences(fixture: Mapping[str, Any], wanted: Any, actual: Any, run: NativeRun) -> list[str]:
    if not isinstance(wanted, list) or not isinstance(actual, list):
        return ["calls"]
    if len(wanted) != len(actual):
        return ["call count"]
    differences: list[str] = []
    for index, (expected_call, actual_call) in enumerate(zip(wanted, actual, strict=True)):
        if not isinstance(expected_call, Mapping) or not isinstance(actual_call, Mapping):
            differences.append(f"call {index}")
            continue
        for field in ("model", "role", "mechanism", "max_response_bytes", "issues"):
            if field in expected_call and not type_aware_equal(expected_call[field], actual_call.get(field)):
                differences.append(f"call {index} {field}")
        if "timeout_s" in expected_call and not control_number_equal(
            expected_call["timeout_s"], actual_call.get("timeout_s")
        ):
            differences.append(f"call {index} timeout_s")
        if "messages" in expected_call and not _messages_equal(fixture, wanted, index, expected_call["messages"], actual_call.get("messages"), run):
            differences.append(f"call {index} messages")
        actual_sampling = sampling_for_call(run, index)
        expected_sampling = _request_sampling(fixture)
        if not _sampling_equal(expected_sampling, actual_sampling):
            differences.append(f"call {index} sampling")
    return differences


def _messages_equal(
    fixture: Mapping[str, Any], calls: list[Any], index: int, wanted: Any, actual: Any, run: NativeRun
) -> bool:
    if isinstance(wanted, str):
        match = _SAME_AS_CALL.fullmatch(wanted)
        if match is None:
            raise ValueDomainError("messages reference must use same_as_call_<n>")
        reference = int(match.group(1)) - 1
        if reference >= index or reference >= len(calls) or not isinstance(calls[reference], Mapping):
            raise ValueDomainError("same_as_call reference must refer to an earlier call")
        return _messages_equal(fixture, calls, reference, calls[reference].get("messages"), actual, run)
    if not isinstance(wanted, list) or not isinstance(actual, list) or len(wanted) != len(actual):
        return False
    schema = fixture.get("request", {}).get("schema") if isinstance(fixture.get("request"), Mapping) else None
    for expected_message, actual_message in zip(wanted, actual, strict=True):
        if not isinstance(expected_message, Mapping) or not isinstance(actual_message, Mapping):
            return False
        if expected_message.get("role") != actual_message.get("role"):
            return False
        expected_text = expected_message.get("text", "")
        native = (
            native_feedback_for_call(run, index)
            if _has_repair_feedback_marker(expected_text)
            else None
        )
        try:
            text = expand_segments(expected_text, schema=schema, native_messages=native)
        except (ValueDomainError, MissingEvidenceError):
            raise
        actual_text = actual_message.get("text")
        if not isinstance(actual_text, str) or text != actual_text:
            return False
    return True


def _has_repair_feedback_marker(value: Any) -> bool:
    return isinstance(value, list) and any(
        isinstance(segment, Mapping)
        and len(segment) == 1
        and segment.get("$repair_feedback") is True
        for segment in value
    )


def _request_sampling(fixture: Mapping[str, Any]) -> dict[str, Any]:
    request = fixture.get("request")
    sampling = request.get("sampling", {}) if isinstance(request, Mapping) else {}
    if not isinstance(sampling, Mapping):
        raise ValueDomainError("fixture sampling must be an object")
    return {key: value for key, value in sampling.items() if value is not None and not (key == "stop" and not value)}


def _sampling_equal(wanted: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    if wanted.keys() != actual.keys():
        return False
    for key in wanted:
        equal = control_number_equal(wanted[key], actual[key]) if key in _CONTROL_SAMPLING else type_aware_equal(wanted[key], actual[key])
        if not equal:
            return False
    return True


def _outcome_equal(wanted: Any, actual: Any) -> bool:
    if not isinstance(wanted, Mapping) or not isinstance(actual, Mapping):
        return False
    if set(wanted) != set(actual):
        return False
    if "result" not in wanted:
        return bool(type_aware_equal(wanted, actual))
    return _result_equal(wanted["result"], actual["result"])


def _result_equal(wanted: Any, actual: Any) -> bool:
    if not isinstance(wanted, Mapping) or not isinstance(actual, Mapping):
        return False
    if set(wanted) != _RESULT_FIELDS or set(actual) != _RESULT_FIELDS:
        return False
    for key, value in wanted.items():
        observed = actual.get(key)
        if key == "structured":
            if not schema_equal(value, observed):
                return False
        elif key == "timing" and isinstance(value, Mapping) and isinstance(observed, Mapping):
            if any(observed.get(name) != marker for name, marker in value.items()):
                return False
        elif key == "usage" and isinstance(value, Mapping) and isinstance(observed, Mapping):
            for name, item in value.items():
                if not type_aware_equal(item, observed.get(name)):
                    return False
            if any(name not in value and item is not None for name, item in observed.items()):
                return False
        elif not type_aware_equal(value, observed):
            return False
    return True


def _expected_structured(outcome: Any) -> Mapping[str, Any] | None:
    if not isinstance(outcome, Mapping) or not isinstance(outcome.get("result"), Mapping):
        return None
    value = outcome["result"].get("structured")
    return value if isinstance(value, Mapping) else None


def _validate_extension_evidence(evidence: Any) -> None:
    if not isinstance(evidence, Mapping) or set(evidence) != {"native_outcome", "adapter_entries"}:
        raise MissingEvidenceError("extension evidence has an invalid shape")
    outcome, entries = evidence["native_outcome"], evidence["adapter_entries"]
    if not isinstance(outcome, Mapping) or len(outcome) != 1 or not isinstance(entries, list):
        raise MissingEvidenceError("extension evidence lacks outcome or entries")
    if set(outcome) == {"error"}:
        error = outcome["error"]
        if not isinstance(error, Mapping) or set(error) != {"category", "native_type", "message"}:
            raise MissingEvidenceError("extension error evidence is invalid")
    elif set(outcome) == {"result"}:
        if not isinstance(outcome["result"], Mapping):
            raise MissingEvidenceError("extension result evidence is invalid")
    elif not (set(outcome) == {"none"} and outcome["none"] is True):
        raise MissingEvidenceError("extension outcome evidence is invalid")
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or entry.get("entry_ordinal") != ordinal or set(entry) != {"entry_ordinal", "model", "role", "timeout_s", "max_response_bytes"}:
            raise MissingEvidenceError("extension adapter entries are invalid")
