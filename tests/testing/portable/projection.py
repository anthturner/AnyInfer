"""Fail-closed projection of raw portable-driver observations."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from typing import Any, cast

from anyinfer.errors import (
    AllTargetsFailedError,
    AnyInferError,
    AuthError,
    ConfigError,
    ContextLengthError,
    CredentialError,
    ModelNotFoundError,
    ProviderUnavailableError,
    RateLimitError,
    SchemaViolationError,
    StreamProtocolError,
    TransportError,
    UnsupportedInputError,
)
from anyinfer.events.telemetry import ParameterDropped, RepairAttempted
from anyinfer.redaction import redact
from anyinfer.schema._capture import EnteredWire, NativeAssessment, RepairPreparation
from anyinfer.types.events import AttemptFailed, StreamEnded, TextDelta, TimingMark, UsageUpdate
from anyinfer.types.results import Generation, Usage

from .records import NativeRun
from .values import (
    MissingEvidenceError,
    ValueDomainError,
    control_number_equal,
    ensure_value_domain,
    feedback_bullets,
    json_value,
    schema_prompt,
    type_aware_equal,
)

__all__ = [
    "extension_evidence",
    "native_feedback_for_call",
    "project_run",
    "sampling_for_call",
    "validate_capture",
]


_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)


def _value(value: Any) -> Any:
    try:
        normalized = json_value(value)
        ensure_value_domain(normalized)
        return normalized
    except ValueDomainError as exc:
        raise MissingEvidenceError(str(exc)) from exc


def _equal(left: Any, right: Any, *, control: bool = False) -> bool:
    """Compare captured JSON facts without losing their Python JSON types."""
    try:
        return (
            control_number_equal(left, right)
            if control
            else type_aware_equal(left, right)
        )
    except ValueDomainError as exc:
        raise MissingEvidenceError(str(exc)) from exc


def _message_records(messages: Iterable[Any]) -> list[dict[str, str]]:
    """Project native text messages without interpreting their content."""
    records: list[dict[str, str]] = []
    for message in messages:
        role = getattr(message, "role", None)
        text = getattr(message, "text", None)
        if not isinstance(role, str) or not isinstance(text, str):
            raise MissingEvidenceError("captured message is not a text message")
        records.append({"role": role, "text": text})
    return records


def _inject_schema(messages: list[dict[str, str]], schema: Any, mechanism: Any) -> list[dict[str, str]]:
    """Apply only the v0 schema-prompt projection to caller message records."""
    if mechanism is None:
        if schema is not None:
            raise MissingEvidenceError("schema capture lacks a selected mechanism")
        return messages
    if mechanism != "prompt":
        raise MissingEvidenceError(f"unprojectable native mechanism {mechanism!r}")
    if not isinstance(schema, Mapping):
        raise MissingEvidenceError("prompt mechanism lacks original input schema")
    instruction = schema_prompt(schema)
    injected = [dict(message) for message in messages]
    last_system = max((i for i, message in enumerate(injected) if message["role"] == "system"), default=-1)
    if last_system == -1:
        return [{"role": "system", "text": instruction}, *injected]
    injected[last_system]["text"] += "\n\n" + instruction
    return injected


def _repair_messages(original: list[dict[str, str]], preparation: RepairPreparation) -> list[dict[str, str]]:
    if not isinstance(preparation.raw_text, str):
        raise MissingEvidenceError("repair preparation lacks raw response text")
    if not all(isinstance(message, str) for message in preparation.errors):
        raise MissingEvidenceError("repair preparation errors are not native messages")
    template = (
        "Your previous response did not match the required JSON schema. Errors:\n"
        f"{feedback_bullets(preparation.errors)}\n"
        "Respond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences."
    )
    return [*original, {"role": "assistant", "text": preparation.raw_text}, {"role": "user", "text": template}]


def _usage(usage: Usage) -> dict[str, int | None]:
    return cast(dict[str, int | None], _value({field: getattr(usage, field) for field in _USAGE_FIELDS}))


def _operations(run: NativeRun) -> tuple[Any, ...]:
    if len(run.operations) > 1:
        raise MissingEvidenceError("one portable run must retain one operation capture")
    return run.operations


def _capture_records(run: NativeRun) -> tuple[Any, tuple[EnteredWire, ...]]:
    operations = _operations(run)
    if not operations:
        if run.requests:
            raise MissingEvidenceError("adapter requests have no operation capture")
        return None, ()
    operation = operations[0]
    if not operation.evidence_available:
        raise MissingEvidenceError("operation capture reports unavailable evidence")
    entries = tuple(operation.entries)
    if entries and run.input_messages is None:
        raise MissingEvidenceError("entered core run lacks original input messages")
    if len(entries) != len(run.requests):
        raise MissingEvidenceError("captured entry count does not match actual adapter requests")
    if tuple(entry.entry_ordinal for entry in entries) != tuple(range(len(entries))):
        raise MissingEvidenceError("captured entry ordinals are not contiguous")
    for entry, request in zip(entries, run.requests, strict=True):
        if entry.wire_snapshot is None:
            raise MissingEvidenceError("entered wire has no snapshot")
        snapshot = entry.wire_snapshot
        actual_messages = _message_records(request.messages)
        checks = {
            "model": request.model,
            "messages": actual_messages,
            "sampling": asdict(request.sampling),
            "mechanism": request.mechanism,
            "stream": request.stream,
            "timeout_s": request.timeout_s,
            "max_response_bytes": request.max_response_bytes,
        }
        for field, actual in checks.items():
            if field not in snapshot:
                raise MissingEvidenceError(f"entered wire lacks {field}")
            control = field == "timeout_s"
            if field == "sampling":
                actual_sampling = cast(Mapping[str, Any], actual)
                observed_sampling = snapshot[field]
                if not isinstance(observed_sampling, Mapping):
                    raise MissingEvidenceError("entered wire sampling is not an object")
                for name, observed in observed_sampling.items():
                    if name not in actual_sampling:
                        raise MissingEvidenceError("entered wire has an unknown sampling field")
                    if not _equal(observed, actual_sampling[name], control=name in {"temperature", "top_p", "presence_penalty", "frequency_penalty"}):
                        raise MissingEvidenceError("entered wire sampling differs from actual request")
                if set(observed_sampling) != set(actual_sampling):
                    raise MissingEvidenceError("entered wire sampling fields differ from actual request")
            elif not _equal(snapshot[field], actual, control=control):
                raise MissingEvidenceError(f"entered wire {field} differs from actual request")
    assessment_ids: set[str] = set()
    for assessment in operation.assessments:
        if assessment.operation_id != operation.operation_id or assessment.assessment_id in assessment_ids:
            raise MissingEvidenceError("assessment identity is inconsistent")
        assessment_ids.add(assessment.assessment_id)
        if assessment.source_entry_ordinal is not None and not 0 <= assessment.source_entry_ordinal < len(entries):
            raise MissingEvidenceError("assessment source does not belong to an actual entry")
    return operation, entries


def _assessment(operation: Any, assessment_id: str) -> NativeAssessment:
    for item in operation.assessments:
        if item.assessment_id == assessment_id:
            return cast(NativeAssessment, item)
    raise MissingEvidenceError("repair refers to a missing native assessment")


def _preparation(operation: Any, assessment_id: str) -> RepairPreparation:
    matches = [item for item in operation.preparations if item.assessment_ref == assessment_id]
    if len(matches) != 1:
        raise MissingEvidenceError("repair assessment must have exactly one preparation")
    return cast(RepairPreparation, matches[0])


def _validate_correction(operation: Any, entry: EnteredWire) -> None:
    if entry.role not in {"original", "correction"}:
        raise MissingEvidenceError(f"unknown entered wire role {entry.role!r}")
    if entry.role != "correction":
        if entry.repair_assessment_ref is not None:
            raise MissingEvidenceError("original entry unexpectedly refers to an assessment")
        return
    if entry.repair_assessment_ref is None:
        raise MissingEvidenceError("correction entry lacks its assessment reference")
    assessment = _assessment(operation, entry.repair_assessment_ref)
    preparation = _preparation(operation, assessment.assessment_id)
    if assessment.source_entry_ordinal != preparation.source_entry_ordinal:
        raise MissingEvidenceError("repair preparation source differs from assessment source")
    if not _equal(preparation.errors, assessment.native_messages):
        raise MissingEvidenceError("repair feedback is not the retained native messages")
    if assessment.source_entry_ordinal != entry.entry_ordinal - 1:
        raise MissingEvidenceError("correction does not follow its assessed source entry")
    if not isinstance(entry.wire_snapshot, Mapping):
        raise MissingEvidenceError("correction has no wire snapshot")


def _validate_message_causality(
    run: NativeRun, operation: Any, entries: tuple[EnteredWire, ...], *, allow_unprojectable: bool
) -> None:
    """Connect repairs and injected wire messages to their captured native inputs."""
    if not entries:
        return
    assert run.input_messages is not None
    original = _message_records(run.input_messages)
    for entry in entries:
        snapshot = entry.wire_snapshot
        assert snapshot is not None
        mechanism = snapshot.get("mechanism")
        actual_wire = snapshot.get("messages")
        if mechanism not in (None, "prompt"):
            if allow_unprojectable:
                continue
            raise MissingEvidenceError(f"unprojectable native mechanism {mechanism!r}")
        if entry.role == "original":
            expected = _inject_schema(original, run.input_schema, mechanism)
        elif entry.role == "correction":
            assert entry.repair_assessment_ref is not None
            preparation = _preparation(operation, entry.repair_assessment_ref)
            if not _equal(preparation.original_messages, original):
                raise MissingEvidenceError("repair preparation original messages differ from run input")
            built = _repair_messages(original, preparation)
            if not _equal(preparation.built_messages, built):
                raise MissingEvidenceError("repair preparation built messages differ from native repair template")
            expected = _inject_schema(built, run.input_schema, mechanism)
        else:
            raise MissingEvidenceError(f"unknown entered wire role {entry.role!r}")
        if not _equal(actual_wire, expected):
            raise MissingEvidenceError("entered wire messages differ from actual causal message projection")


def validate_capture(run: NativeRun, allow_unprojectable: bool = False) -> dict[str, Any]:
    """Validate causal capture evidence, returning only native facts on success."""
    if run.error_stage == "harness":
        raise MissingEvidenceError("harness failure cannot be projected as a core outcome")
    operation, entries = _capture_records(run)
    if operation is None:
        return {"operations": 0, "entries": 0, "assessments": 0}
    for entry in entries:
        _validate_correction(operation, entry)
    _validate_message_causality(run, operation, entries, allow_unprojectable=allow_unprojectable)
    if not allow_unprojectable:
        for assessment in operation.assessments:
            if assessment.issues is None and assessment.kind not in {"invalid_schema", "extraction"}:
                raise MissingEvidenceError("assessment has no portable issue projection")
    return {
        "operations": 1,
        "entries": len(entries),
        "assessments": len(operation.assessments),
        "evidence_available": operation.evidence_available,
    }


def sampling_for_call(run: NativeRun, index: int) -> dict[str, Any]:
    """Return only sampling fields actually set on the entered native wire request."""
    _, entries = _capture_records(run)
    try:
        snapshot = entries[index].wire_snapshot
    except IndexError as exc:
        raise MissingEvidenceError("call index is outside captured entries") from exc
    assert snapshot is not None
    sampling = snapshot.get("sampling")
    if not isinstance(sampling, Mapping):
        raise MissingEvidenceError("entered wire sampling snapshot is missing")
    return cast(dict[str, Any], _value({
        key: _value(value)
        for key, value in sampling.items()
        if value is not None and not (key == "stop" and not value)
    }))


def native_feedback_for_call(run: NativeRun, index: int) -> tuple[str, ...]:
    """Return the actual selected native messages for one entered correction call."""
    operation, entries = _capture_records(run)
    if operation is None:
        raise MissingEvidenceError("call has no operation capture")
    try:
        entry = entries[index]
    except IndexError as exc:
        raise MissingEvidenceError("call index is outside captured entries") from exc
    _validate_correction(operation, entry)
    if entry.role != "correction" or entry.repair_assessment_ref is None:
        raise MissingEvidenceError("native feedback is defined only for correction calls")
    return _assessment(operation, entry.repair_assessment_ref).native_messages


def _error(
    error: BaseException, *, stage: str | None, construction_origin: str | None = None
) -> dict[str, Any]:
    if isinstance(error, asyncio.CancelledError):
        return {"category": "cancelled", "retryable": False, "retry_after_s": None, "http_status": None, "phase": None}
    if isinstance(error, ValueError) and stage == "construction" and construction_origin in {"sampling", "messages", "repair", "route"}:
        return {"category": "invalid_request", "retryable": False, "retry_after_s": None, "http_status": None, "phase": None}
    if isinstance(error, ConfigError | CredentialError):
        return {"category": "invalid_request", "retryable": False, "retry_after_s": error.retry_after_s, "http_status": error.http_status, "phase": "configure"}
    categories = (
        (AuthError, "auth"), (RateLimitError, "rate_limit"), (TransportError, "transport"),
        (ProviderUnavailableError, "provider_unavailable"), (ModelNotFoundError, "model_not_found"),
        (ContextLengthError, "context_length"), (StreamProtocolError, "stream_protocol"),
        (UnsupportedInputError, "unsupported_input"), (SchemaViolationError, "schema_violation"),
        (AllTargetsFailedError, "all_targets_failed"),
    )
    for error_type, category in categories:
        if isinstance(error, error_type):
            assert isinstance(error, AnyInferError)
            return {"category": category, "retryable": error.retryable, "retry_after_s": error.retry_after_s, "http_status": error.http_status, "phase": error.phase}
    raise MissingEvidenceError(f"unrecognized mandatory native error {type(error).__name__}")


def _issues(operation: Any) -> list[dict[str, Any]]:
    if operation is None or not operation.assessments:
        raise MissingEvidenceError("terminal schema failure lacks an assessment")
    assessment = operation.assessments[-1]
    entries = tuple(operation.entries)
    if not entries or assessment.operation_id != operation.operation_id:
        raise MissingEvidenceError("terminal schema failure lacks an actual operation entry")
    if assessment.source_entry_ordinal != entries[-1].entry_ordinal:
        raise MissingEvidenceError("terminal schema failure assessment is not from the final entry")
    if assessment.issues is None:
        raise MissingEvidenceError("terminal schema failure lacks portable issues")
    return [_value(issue.json()) for issue in assessment.issues]


def _calls(run: NativeRun) -> list[dict[str, Any]]:
    _, entries = _capture_records(run)
    calls: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        snapshot = entry.wire_snapshot
        assert snapshot is not None
        call = {
            "model": snapshot["model"], "role": entry.role, "mechanism": snapshot["mechanism"],
            "timeout_s": snapshot["timeout_s"], "max_response_bytes": snapshot["max_response_bytes"],
            "messages": _value(snapshot["messages"]),
        }
        if entry.role == "correction":
            call["issues"] = [_value(issue.json()) for issue in _assessment(_operations(run)[0], entry.repair_assessment_ref or "").issues or ()]
            native_feedback_for_call(run, index)
        calls.append(call)
    return calls


def _events(events: Iterable[Any]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for event in events:
        if isinstance(event, TextDelta):
            if projected and "text" in projected[-1]:
                projected[-1]["text"] += event.text
            else:
                projected.append({"text": event.text})
        elif isinstance(event, UsageUpdate):
            projected.append({"usage_update": _usage(event.usage)})
        elif isinstance(event, TimingMark):
            projected.append({"timing_mark": event.name})
        elif isinstance(event, AttemptFailed):
            item: dict[str, Any] = {"outcome": event.record.outcome}
            if event.record.error is not None:
                item["error"] = {"category": _error_type_name(event.record.error.type_name)}
            projected.append({"attempt_failed": item})
        elif isinstance(event, StreamEnded):
            projected.append({"stream_ended": True})
        else:
            raise MissingEvidenceError(f"unprojectable public event {type(event).__name__}")
    return cast(list[dict[str, Any]], _value(projected))


def _error_type_name(name: str) -> str:
    names = {"AuthError": "auth", "RateLimitError": "rate_limit", "TransportError": "transport", "ProviderUnavailableError": "provider_unavailable", "ModelNotFoundError": "model_not_found", "ContextLengthError": "context_length", "StreamProtocolError": "stream_protocol"}
    if name not in names:
        raise MissingEvidenceError(f"unrecognized attempt error type {name}")
    return names[name]


def _result(result: Generation) -> dict[str, Any]:
    return cast(dict[str, Any], _value({"text": result.text, "structured": _value(result.structured), "target": {"provider_id": result.target.provider_id, "model": result.target.model}, "finish_reason": result.finish_reason, "usage": _usage(result.usage), "timing": {"first_token_ms": "non_null" if result.timing.first_token_ms is not None else "null", "total_ms": "present"}, "structured_mechanism": result.structured_mechanism, "repair_attempts": result.repair_attempts, "attempts": [{"target": str(item.target), "outcome": item.outcome, **({"error": {"category": _error_type_name(item.error.type_name)}} if item.error else {})} for item in result.attempts], "warnings": list(result.warnings)}))


def project_run(run: NativeRun) -> dict[str, Any]:
    """Project observed native facts into the core fixture expectation shape."""
    validate_capture(run)
    if run.error is not None and run.result is not None:
        raise MissingEvidenceError("run cannot have both a result and terminal error")
    outcome: dict[str, Any]
    if run.result is not None:
        outcome = {"result": _result(run.result)}
    elif run.error is not None:
        error = _error(run.error, stage=run.error_stage, construction_origin=run.construction_origin)
        if error["category"] == "schema_violation":
            error["issues"] = _issues(_operations(run)[0] if run.operations else None)
        outcome = {"error": error}
    else:
        outcome = {"none": True}
    telemetry = {"repair_attempted": [{"attempt_number": event.attempt_number} for event in run.telemetry if isinstance(event, RepairAttempted)], "parameter_dropped": [{"parameter": event.parameter} for event in run.telemetry if isinstance(event, ParameterDropped)]}
    return cast(dict[str, Any], _value({"status": "observed", "calls": _calls(run), "clock_advances_ms": list(run.clock_advances_ms), "telemetry": telemetry, "events": _events(run.events), "outcome": outcome, "accounting": None}))


def extension_evidence(run: NativeRun) -> dict[str, Any]:
    """Return honest extension evidence without manufacturing a portable outcome."""
    validate_capture(run, allow_unprojectable=True)
    if run.error is not None and run.result is not None:
        raise MissingEvidenceError("run cannot have both a result and terminal error")
    error: dict[str, Any] | None = None
    if run.error is not None:
        try:
            portable = _error(run.error, stage=run.error_stage, construction_origin=run.construction_origin)
            category = portable["category"]
        except MissingEvidenceError:
            category = None
        error = {"native_type": type(run.error).__name__, "message": redact(str(run.error))[:4096], "category": category}
    _, captured = _capture_records(run)
    entries = [{"entry_ordinal": entry.entry_ordinal, "model": request.model, "role": entry.role, "timeout_s": request.timeout_s, "max_response_bytes": request.max_response_bytes} for entry, request in zip(captured, run.requests, strict=True)]
    if run.result is not None:
        outcome: dict[str, Any] = {"result": _result(run.result)}
    elif error is not None:
        outcome = {"error": error}
    else:
        outcome = {"none": True}
    evidence = _value({"native_outcome": outcome, "adapter_entries": entries})
    if not isinstance(evidence, dict):
        raise MissingEvidenceError("extension evidence is not an object")
    return evidence
