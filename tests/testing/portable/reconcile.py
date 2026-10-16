"""Pure causal expectation staging for portable fixture observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from .comparison import _EXTENSIONS, compare_fixture
from .projection import native_feedback_for_call, project_run, validate_capture
from .records import NativeRun
from .transport import TransportRun, _observation, compare_transport_fixture
from .values import (
    MissingEvidenceError,
    ValueDomainError,
    ensure_value_domain,
    expand_segments,
    feedback_bullets,
    json_value,
    schema_prompt,
)

__all__ = ["ReconciledFixture", "reconcile_fixture"]

_REPAIR_PREFIX = "Your previous response did not match the required JSON schema. Errors:\n"
_REPAIR_SUFFIX = "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences."


@dataclass(frozen=True, slots=True)
class ReconciledFixture:
    """A fresh expectation-stage document and its native comparison audit."""

    fixture: dict[str, Any]
    audit: dict[str, Any]


def reconcile_fixture(
    fixture: Mapping[str, Any],
    run: NativeRun | TransportRun,
    *,
    extensions: Sequence[str] = (),
) -> ReconciledFixture:
    """Stage only ``expected`` from an observed native portable execution."""
    staged = _copy_fixture(fixture)
    _validate_identity(staged, run)
    if isinstance(run, TransportRun):
        return _reconcile_transport(staged, run, extensions=extensions)
    return _reconcile_core(staged, run, extensions=extensions)


def _copy_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    value = json_value(fixture)
    ensure_value_domain(value)
    if not isinstance(value, dict):
        raise ValueDomainError("fixture must be a JSON object")
    return cast(dict[str, Any], value)


def _validate_identity(fixture: Mapping[str, Any], run: NativeRun | TransportRun) -> None:
    case_id = fixture.get("id")
    if not isinstance(case_id, str) or case_id != run.case_id:
        raise MissingEvidenceError("fixture and native run identities differ")
    kind = fixture.get("kind")
    if isinstance(run, TransportRun):
        if kind not in {"adapter", "core_http"}:
            raise ValueDomainError("transport run requires an adapter or core_http fixture")
        if (kind == "core_http") is not (run.core is not None):
            raise ValueDomainError("transport fixture kind does not match its native core run")
        if run.core is not None and run.core.case_id != case_id:
            raise MissingEvidenceError("transport core run identity differs from its outer run")
    elif kind in {"adapter", "core_http"}:
        raise ValueDomainError("core run cannot stage a transport fixture")


def _reconcile_core(
    fixture: dict[str, Any], run: NativeRun, *, extensions: Sequence[str]
) -> ReconciledFixture:
    declared = fixture.get("extension")
    if declared is not None and (
        not isinstance(declared, str) or declared not in _EXTENSIONS or declared not in extensions
    ):
        raise ValueDomainError("fixture extension is not an eligible declared extension")
    extension = compare_fixture(fixture, run, extensions=extensions)
    if extension.get("verdict") == "extension":
        return _reconcile_extension(fixture, run, extension)
    if declared is not None:
        detail = extension.get("detail")
        raise MissingEvidenceError(
            f"eligible extension lacks a usable native observation: {detail or extension.get('verdict')}"
        )
    validate_capture(run)
    expected = project_run(run)
    _markerize_core_expected(fixture, expected, run)
    fixture["expected"] = expected
    audit = compare_fixture(fixture, run, extensions=extensions)
    _require_pass(audit)
    return ReconciledFixture(fixture=_fresh(fixture), audit=_fresh(audit))


def _reconcile_transport(
    fixture: dict[str, Any], run: TransportRun, *, extensions: Sequence[str]
) -> ReconciledFixture:
    if fixture.get("extension") is not None:
        raise ValueDomainError("transport reconciliation does not stage extension baselines")
    if run.case_id != fixture.get("id"):
        raise MissingEvidenceError("fixture and transport run identities differ")
    expected = _observation(run)
    if run.core is not None:
        core = expected.get("core")
        if not isinstance(core, dict):
            raise MissingEvidenceError("core HTTP observation lacks a core expectation")
        _markerize_core_expected(_transport_core_source(fixture), core, run.core)
        _markerize_transport_http(fixture, expected, run)
    fixture["expected"] = expected
    audit = compare_transport_fixture(fixture, run)
    _require_pass(audit)
    return ReconciledFixture(fixture=_fresh(fixture), audit=_fresh(audit))


def _transport_core_source(fixture: Mapping[str, Any]) -> Mapping[str, Any]:
    expected = fixture.get("expected")
    if not isinstance(expected, Mapping) or expected.get("status") == "to_be_observed":
        return {"expected": {"status": "to_be_observed"}}
    core = expected.get("core")
    if core is None:
        return {"expected": {"status": "to_be_observed"}}
    if not isinstance(core, Mapping):
        raise ValueDomainError("existing transport core expectation must be an object")
    return {"expected": core}


def _reconcile_extension(
    fixture: dict[str, Any], run: NativeRun, extension: Mapping[str, Any]
) -> ReconciledFixture:
    fixture["expected"] = {
        "status": "observed",
        "calls": [],
        "clock_advances_ms": [],
        "telemetry": {"repair_attempted": [], "parameter_dropped": []},
        "events": [],
        "outcome": {
            "error": {
                "category": "unsupported_input",
                "retryable": False,
                "retry_after_s": None,
                "http_status": None,
                "phase": "generate",
            }
        },
        "accounting": None,
    }
    # The staged baseline is for nondeclaring implementations.  Python remains the
    # declaring implementation and its comparator audit must retain the honest
    # extension observation rather than fabricate a rejection.
    ensure_value_domain(fixture["expected"])
    return ReconciledFixture(fixture=_fresh(fixture), audit=_fresh(dict(extension)))


def _markerize_core_expected(
    source_fixture: Mapping[str, Any], expected: dict[str, Any], run: NativeRun
) -> None:
    calls = expected.get("calls")
    if not isinstance(calls, list):
        raise MissingEvidenceError("native projection lacks calls")
    prior_calls = _prior_calls(source_fixture)
    operation = _operation_entries(run)
    if len(calls) != len(operation):
        raise MissingEvidenceError("native projection call count differs from capture entries")
    if prior_calls is not None and len(prior_calls) != len(calls):
        raise ValueDomainError("existing expected calls do not match captured calls")
    schema = run.input_schema
    for ordinal, (call, entry) in enumerate(zip(calls, operation, strict=True)):
        messages = call.get("messages") if isinstance(call, Mapping) else None
        if not isinstance(messages, list):
            raise MissingEvidenceError("native projection call lacks messages")
        prior_messages = _prior_messages(prior_calls, ordinal, len(messages))
        schema_index = _schema_message_index(run, entry, messages)
        feedback_index = _feedback_message_index(run, entry, messages, ordinal)
        for index, message in enumerate(messages):
            if not isinstance(message, dict) or not isinstance(message.get("text"), str):
                raise MissingEvidenceError("native projection message is not text")
            actual = message["text"]
            existing = prior_messages[index] if prior_messages is not None else None
            if index == schema_index:
                message["text"] = _preserve_or_expand(
                    existing, actual, schema=schema, native_messages=None, generated=_schema_segments(actual, schema)
                )
            elif index == feedback_index:
                feedback = native_feedback_for_call(run, ordinal)
                message["text"] = _preserve_or_expand(
                    existing,
                    actual,
                    schema=schema,
                    native_messages=feedback,
                    generated=_feedback_segments(actual, feedback),
                )
            elif _contains_marker(existing):
                raise ValueDomainError("existing marker is not at a causal native position")


def _operation_entries(run: NativeRun) -> tuple[Any, ...]:
    validate_capture(run)
    if not run.operations:
        if run.requests:
            raise MissingEvidenceError("uncaptured native requests have no operation capture")
        return ()
    if len(run.operations) != 1:
        raise MissingEvidenceError("native run lacks one operation capture")
    entries = tuple(run.operations[0].entries)
    if len(entries) != len(run.requests):
        raise MissingEvidenceError("native operation entry count differs from requests")
    return entries


def _prior_calls(fixture: Mapping[str, Any]) -> list[Any] | None:
    expected = fixture.get("expected")
    if not isinstance(expected, Mapping) or expected.get("status") == "to_be_observed":
        return None
    calls = expected.get("calls")
    if calls is None:
        return None
    if not isinstance(calls, list):
        raise ValueDomainError("existing expected calls must be a list")
    return calls


def _prior_messages(calls: list[Any] | None, ordinal: int, count: int) -> list[Any] | None:
    if calls is None:
        return None
    if ordinal >= len(calls):
        return None
    call = calls[ordinal]
    messages = call.get("messages") if isinstance(call, Mapping) else None
    if not isinstance(messages, list) or len(messages) != count:
        raise ValueDomainError("existing expected messages do not match captured call")
    return messages


def _schema_message_index(run: NativeRun, entry: Any, messages: list[Any]) -> int | None:
    snapshot = getattr(entry, "wire_snapshot", None)
    mechanism = snapshot.get("mechanism") if isinstance(snapshot, Mapping) else None
    if mechanism is None:
        if run.input_schema is not None:
            raise MissingEvidenceError("schema input has no selected native mechanism")
        return None
    if mechanism != "prompt" or not isinstance(run.input_schema, Mapping):
        raise MissingEvidenceError("schema prompt provenance is unavailable")
    if run.input_messages is None:
        raise MissingEvidenceError("schema prompt lacks original input messages")
    original = [
        {"role": getattr(message, "role", None), "text": getattr(message, "text", None)}
        for message in run.input_messages
    ]
    if not all(isinstance(message["role"], str) and isinstance(message["text"], str) for message in original):
        raise MissingEvidenceError("schema prompt input is not text messages")
    prompt = schema_prompt(run.input_schema)
    last_system = max(
        (index for index, message in enumerate(original) if message["role"] == "system"), default=-1
    )
    index = last_system if last_system >= 0 else 0
    if index >= len(messages) or not isinstance(messages[index], Mapping):
        raise MissingEvidenceError("schema prompt lacks its causal captured message")
    expected_text = prompt if last_system < 0 else f"{original[index]['text']}\n\n{prompt}"
    if messages[index].get("role") != "system" or messages[index].get("text") != expected_text:
        raise MissingEvidenceError("schema prompt capture differs from causal input position")
    return index


def _feedback_message_index(run: NativeRun, entry: Any, messages: list[Any], ordinal: int) -> int | None:
    if getattr(entry, "role", None) != "correction":
        return None
    if not messages or not isinstance(messages[-1], Mapping):
        raise MissingEvidenceError("repair feedback lacks its causal captured message")
    feedback = feedback_bullets(native_feedback_for_call(run, ordinal))
    expected = f"{_REPAIR_PREFIX}{feedback}{_REPAIR_SUFFIX}"
    if messages[-1].get("role") != "user" or messages[-1].get("text") != expected:
        raise MissingEvidenceError("repair feedback capture differs from native preparation")
    return len(messages) - 1


def _schema_segments(actual: str, schema: Any) -> list[Any]:
    if not isinstance(schema, Mapping):
        raise MissingEvidenceError("schema prompt lacks original schema")
    prompt = schema_prompt(schema)
    if not actual.endswith(prompt):
        raise MissingEvidenceError("captured schema prompt does not match native text")
    return [actual[: -len(prompt)], {"$schema_prompt": True}]


def _feedback_segments(actual: str, native_messages: Sequence[str]) -> list[Any]:
    feedback = feedback_bullets(native_messages)
    if actual != f"{_REPAIR_PREFIX}{feedback}{_REPAIR_SUFFIX}":
        raise MissingEvidenceError("captured repair feedback differs from native preparation")
    return [_REPAIR_PREFIX, {"$repair_feedback": True}, _REPAIR_SUFFIX]


def _preserve_or_expand(
    existing: Any,
    actual: str,
    *,
    schema: Any,
    native_messages: Sequence[str] | None,
    generated: list[Any],
) -> str | list[Any]:
    if isinstance(existing, Mapping):
        existing = existing.get("text")
    if isinstance(existing, list):
        _validate_marker_layout(existing, generated)
        expanded = expand_segments(existing, schema=schema if isinstance(schema, Mapping) else None, native_messages=native_messages)
        if expanded != actual:
            raise MissingEvidenceError("existing expected marker does not match captured native text")
        preserved = json_value(existing)
        if not isinstance(preserved, list):
            raise ValueDomainError("existing expected segments are invalid")
        return preserved
    if existing is not None and not isinstance(existing, str):
        raise ValueDomainError("existing expected message text is invalid")
    expanded = expand_segments(generated, schema=schema if isinstance(schema, Mapping) else None, native_messages=native_messages)
    if expanded != actual:
        raise MissingEvidenceError("generated marker does not match captured native text")
    return generated


def _validate_marker_layout(existing: list[Any], generated: list[Any]) -> None:
    kind = _single_marker_kind(generated)
    marker_indexes = [
        index
        for index, item in enumerate(existing)
        if isinstance(item, Mapping) and ("$schema_prompt" in item or "$repair_feedback" in item)
    ]
    if len(marker_indexes) != 1:
        raise ValueDomainError("existing expected segments need one causal marker")
    index = marker_indexes[0]
    marker = existing[index]
    if not isinstance(marker, Mapping) or marker != ({"$schema_prompt": True} if kind == "schema" else {"$repair_feedback": True}):
        raise ValueDomainError("existing expected marker has an invalid causal shape")
    if any(not isinstance(item, str | Mapping) for item in existing):
        raise ValueDomainError("existing expected segments are invalid")
    if any(isinstance(item, Mapping) for position, item in enumerate(existing) if position != index):
        raise ValueDomainError("existing expected segments contain an unknown marker")
    before = "".join(cast(str, item) for item in existing[:index])
    after = "".join(cast(str, item) for item in existing[index + 1 :])
    generated_index = next(
        position for position, item in enumerate(generated) if isinstance(item, Mapping)
    )
    generated_before = "".join(cast(str, item) for item in generated[:generated_index])
    generated_after = "".join(cast(str, item) for item in generated[generated_index + 1 :])
    if before != generated_before or after != generated_after:
        raise MissingEvidenceError("existing marker does not occupy the causal native span")
    if kind == "schema" and index != len(existing) - 1:
        raise ValueDomainError("schema prompt marker must be the final segment")


def _single_marker_kind(segments: list[Any]) -> str:
    markers = [item for item in segments if isinstance(item, Mapping)]
    if markers == [{"$schema_prompt": True}]:
        return "schema"
    if markers == [{"$repair_feedback": True}]:
        return "repair"
    raise MissingEvidenceError("generated causal marker has an invalid shape")


def _contains_marker(message: Any) -> bool:
    if not isinstance(message, Mapping):
        return False
    text = message.get("text")
    return isinstance(text, list) and any(
        isinstance(item, Mapping) and ("$schema_prompt" in item or "$repair_feedback" in item)
        for item in text
    )


def _markerize_transport_http(
    source_fixture: Mapping[str, Any], expected: dict[str, Any], run: TransportRun
) -> None:
    if run.core is None:
        return
    rows = expected.get("http_requests")
    calls = expected.get("core", {}).get("calls") if isinstance(expected.get("core"), Mapping) else None
    if not isinstance(rows, list) or not isinstance(calls, list) or len(rows) != len(calls):
        raise MissingEvidenceError("core HTTP observation lacks ordered rows")
    entries = _operation_entries(run.core)
    if (
        len(rows) != len(entries)
        or len(run.http_requests) != len(rows)
        or len(run.requests) != len(rows)
        or len(run.core.requests) != len(rows)
    ):
        raise MissingEvidenceError("core HTTP row cardinality is inconsistent")
    prior_rows = _prior_http_rows(source_fixture, len(rows))
    for ordinal, (row, actual, _entry, request, call) in enumerate(
        zip(rows, run.http_requests, entries, run.requests, calls, strict=True)
    ):
        body = row.get("body") if isinstance(row, Mapping) else None
        actual_body = actual.get("body") if isinstance(actual, Mapping) else None
        call_messages = call.get("messages") if isinstance(call, Mapping) else None
        messages = body.get("messages") if isinstance(body, Mapping) else None
        actual_messages = actual_body.get("messages") if isinstance(actual_body, Mapping) else None
        if request is not run.core.requests[ordinal] or not isinstance(messages, list) or not isinstance(actual_messages, list) or not isinstance(call_messages, list) or len(messages) != len(actual_messages) or len(messages) != len(call_messages):
            raise MissingEvidenceError("core HTTP message provenance is inconsistent")
        prior_messages = _prior_http_messages(prior_rows, ordinal, len(messages))
        for index, (message, actual_message, core_message) in enumerate(
            zip(messages, actual_messages, call_messages, strict=True)
        ):
            if not isinstance(message, dict) or not isinstance(actual_message, Mapping) or not isinstance(core_message, Mapping):
                raise MissingEvidenceError("core HTTP message facts are unavailable")
            if message.get("role") != actual_message.get("role") or message.get("content") != actual_message.get("content"):
                raise MissingEvidenceError("core HTTP projection differs from captured HTTP row")
            core_text = core_message.get("text")
            if isinstance(core_text, list):
                actual_content = actual_message.get("content")
                if not isinstance(actual_content, str):
                    raise MissingEvidenceError("core HTTP marker text is not an actual string")
                existing = prior_messages[index] if prior_messages is not None else None
                message["content"] = _preserve_transport_segments(
                    existing, core_text, actual_content, run.core, ordinal
                )


def _prior_http_rows(fixture: Mapping[str, Any], count: int) -> list[Any] | None:
    expected = fixture.get("expected")
    if not isinstance(expected, Mapping) or expected.get("status") == "to_be_observed":
        return None
    rows = expected.get("http_requests")
    if rows is None:
        return None
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueDomainError("existing expected HTTP rows do not match captured rows")
    return rows


def _prior_http_messages(rows: list[Any] | None, ordinal: int, count: int) -> list[Any] | None:
    if rows is None:
        return None
    row = rows[ordinal]
    body = row.get("body") if isinstance(row, Mapping) else None
    messages = body.get("messages") if isinstance(body, Mapping) else None
    if not isinstance(messages, list) or len(messages) != count:
        raise ValueDomainError("existing expected HTTP messages do not match captured rows")
    return messages


def _preserve_transport_segments(
    existing: Any, generated: list[Any], actual: str, run: NativeRun, ordinal: int
) -> list[Any]:
    if isinstance(existing, Mapping):
        existing = existing.get("content")
    if isinstance(existing, list) and _contains_segment_marker(existing):
        _validate_marker_layout(existing, generated)
        kind = _single_marker_kind(generated)
        native_messages = native_feedback_for_call(run, ordinal) if kind == "repair" else None
        expanded = expand_segments(
            existing,
            schema=run.input_schema if isinstance(run.input_schema, Mapping) else None,
            native_messages=native_messages,
        )
        if expanded != actual:
            raise MissingEvidenceError("existing HTTP marker does not match captured native text")
        value = json_value(existing)
        if not isinstance(value, list):
            raise ValueDomainError("existing HTTP marker segments are invalid")
        return value
    kind = _single_marker_kind(generated)
    expanded = expand_segments(
        generated,
        schema=run.input_schema if isinstance(run.input_schema, Mapping) else None,
        native_messages=native_feedback_for_call(run, ordinal) if kind == "repair" else None,
    )
    if expanded != actual:
        raise MissingEvidenceError("generated HTTP marker does not match captured native text")
    return generated


def _contains_segment_marker(value: object) -> bool:
    return isinstance(value, list) and any(
        isinstance(item, Mapping) and ("$schema_prompt" in item or "$repair_feedback" in item)
        for item in value
    )


def _require_pass(audit: Mapping[str, Any]) -> None:
    if audit.get("verdict") != "pass":
        detail = audit.get("detail")
        raise MissingEvidenceError(f"reconciled expectation does not compare: {detail or audit.get('verdict')}")


def _fresh(value: Mapping[str, Any]) -> dict[str, Any]:
    copied = json_value(value)
    if not isinstance(copied, dict):
        raise MissingEvidenceError("reconciliation result is not an object")
    return cast(dict[str, Any], copied)
