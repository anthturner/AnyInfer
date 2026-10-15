"""Private bounded observation records for the conformance driver."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4

__all__ = [
    "EnteredWire",
    "Issue",
    "NativeAssessment",
    "RepairPreparation",
    "allocate_entry",
    "capture_enabled",
    "capture_scope",
    "new_operation",
    "record_assessment",
    "record_entered_wire",
    "record_preparation",
]
_MAX_ASSESSMENTS = 128
_MAX_SNAPSHOT_BYTES = 1_048_576


def _freeze(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    raise TypeError(f"capture cannot snapshot {type(value).__name__}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Issue:
    rule: str
    instance_path: tuple[str | int, ...] | None
    schema_path: tuple[str | int, ...] | None
    params: Mapping[str, Any]

    def json(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "rule": self.rule,
                "instance_path": _jsonable(self.instance_path),
                "schema_path": _jsonable(self.schema_path),
                "params": _jsonable(self.params),
            }
        )


@dataclass(frozen=True, slots=True)
class NativeAssessment:
    operation_id: str
    assessment_id: str
    source_entry_ordinal: int | None
    kind: str
    issues: tuple[Issue, ...] | None
    native_messages: tuple[str, ...]
    selected_native: tuple[Mapping[str, Any], ...]
    schema_error_input_path: tuple[str | int, ...] | None = None


@dataclass(frozen=True, slots=True)
class RepairPreparation:
    source_entry_ordinal: int
    assessment_ref: str
    original_messages: tuple[Mapping[str, Any], ...]
    raw_text: str
    errors: tuple[str, ...]
    built_messages: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class EnteredWire:
    entry_ordinal: int
    role: str
    repair_assessment_ref: str | None
    wire_snapshot: Mapping[str, Any] | None


def _record_json(record: Any) -> Mapping[str, Any]:
    if isinstance(record, NativeAssessment):
        return {
            "operation_id": record.operation_id,
            "assessment_id": record.assessment_id,
            "source_entry_ordinal": record.source_entry_ordinal,
            "kind": record.kind,
            "issues": None
            if record.issues is None
            else tuple(issue.json() for issue in record.issues),
            "native_messages": record.native_messages,
            "selected_native": record.selected_native,
            "schema_error_input_path": record.schema_error_input_path,
        }
    if isinstance(record, RepairPreparation):
        return {
            "source_entry_ordinal": record.source_entry_ordinal,
            "assessment_ref": record.assessment_ref,
            "original_messages": record.original_messages,
            "raw_text": record.raw_text,
            "errors": record.errors,
            "built_messages": record.built_messages,
        }
    if isinstance(record, EnteredWire):
        return {
            "entry_ordinal": record.entry_ordinal,
            "role": record.role,
            "repair_assessment_ref": record.repair_assessment_ref,
            "wire_snapshot": record.wire_snapshot,
        }
    raise TypeError(f"unknown capture record {type(record).__name__}")


@dataclass(slots=True)
class _OperationCapture:
    operation_id: str = field(default_factory=lambda: uuid4().hex)
    assessments: list[NativeAssessment] = field(default_factory=list)
    preparations: list[RepairPreparation] = field(default_factory=list)
    entries: list[EnteredWire] = field(default_factory=list)
    next_entry_ordinal: int = 0
    snapshot_bytes: int = 0
    evidence_available: bool = True
    current_entry_ordinal: int | None = None
    latest_assessment_id: str | None = None

    def append(self, target: list[Any], record: Any, *, assessment: bool = False) -> bool:
        try:
            size = len(
                json.dumps(
                    _jsonable(_record_json(record)), sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            )
            if (
                assessment and len(self.assessments) >= _MAX_ASSESSMENTS
            ) or self.snapshot_bytes + size > _MAX_SNAPSHOT_BYTES:
                self.evidence_available = False
                return False
            target.append(record)
            self.snapshot_bytes += size
            return True
        except Exception:  # noqa: BLE001 - controlled observation faults fail evidence only
            self.evidence_available = False
            return False


_HARNESS: ContextVar[list[_OperationCapture] | None] = ContextVar(
    "anyinfer_schema_capture", default=None
)
_ACTIVE: ContextVar[_OperationCapture | None] = ContextVar(
    "anyinfer_schema_capture_active", default=None
)


@contextmanager
def capture_enabled() -> Iterator[list[_OperationCapture]]:
    operations: list[_OperationCapture] = []
    token = _HARNESS.set(operations)
    try:
        yield operations
    finally:
        _HARNESS.reset(token)


def new_operation() -> _OperationCapture | None:
    operations = _HARNESS.get()
    if operations is None:
        return None
    try:
        operation = _OperationCapture()
        operations.append(operation)
        return operation
    except Exception:  # noqa: BLE001 - enabled-harness startup is observation only
        return None


@contextmanager
def capture_scope(
    operation: _OperationCapture | None, entry_ordinal: int | None
) -> Iterator[None]:
    if operation is None:
        yield
        return
    prior = operation.current_entry_ordinal
    operation.current_entry_ordinal = entry_ordinal
    token = _ACTIVE.set(operation)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
        operation.current_entry_ordinal = prior


def allocate_entry(operation: _OperationCapture | None) -> int | None:
    if operation is None:
        return None
    try:
        operation.latest_assessment_id = None
        ordinal = operation.next_entry_ordinal
        operation.next_entry_ordinal += 1
        return ordinal
    except Exception:  # noqa: BLE001 - allocation failures are unavailable evidence
        operation.evidence_available = False
        return None


def _snapshot_issue(issue: Issue) -> Issue:
    return Issue(
        str(issue.rule),
        None if issue.instance_path is None else tuple(issue.instance_path),
        None if issue.schema_path is None else tuple(issue.schema_path),
        _freeze(issue.params),
    )


def record_assessment(
    *,
    kind: str,
    issues: Sequence[Issue] | None,
    native_messages: Sequence[str],
    selected_native: Sequence[Mapping[str, Any]],
    schema_error_input_path: Sequence[str | int] | None = None,
) -> None:
    operation = _ACTIVE.get()
    if operation is None:
        return
    try:
        record = NativeAssessment(
            operation.operation_id,
            uuid4().hex,
            operation.current_entry_ordinal,
            kind,
            None if issues is None else tuple(_snapshot_issue(issue) for issue in issues),
            tuple(str(message) for message in native_messages),
            tuple(_freeze(item) for item in selected_native),
            None if schema_error_input_path is None else tuple(schema_error_input_path),
        )
        if operation.append(operation.assessments, record, assessment=True):
            operation.latest_assessment_id = record.assessment_id
    except Exception:  # noqa: BLE001 - snapshot failures must not change native behavior
        operation.evidence_available = False


def _message(message: Any) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], _freeze({"role": message.role, "text": message.text}))


def record_preparation(
    operation: _OperationCapture | None,
    *,
    source_entry_ordinal: int,
    assessment_ref: str,
    original_messages: Sequence[Any],
    raw_text: str,
    errors: Sequence[str],
    built_messages: Sequence[Any],
) -> bool:
    if operation is None:
        return False
    try:
        return operation.append(
            operation.preparations,
            RepairPreparation(
                source_entry_ordinal,
                assessment_ref,
                tuple(_message(message) for message in original_messages),
                str(raw_text),
                tuple(str(error) for error in errors),
                tuple(_message(message) for message in built_messages),
            ),
        )
    except Exception:  # noqa: BLE001 - snapshot failures must not change native behavior
        operation.evidence_available = False
        return False


def record_entered_wire(
    operation: _OperationCapture | None,
    *,
    entry_ordinal: int | None,
    role: str,
    repair_assessment_ref: str | None,
    wire: Any,
) -> None:
    if operation is None or entry_ordinal is None:
        return
    try:
        snapshot = _freeze(
            {
                "model": wire.model,
                "messages": [_message(message) for message in wire.messages],
                "sampling": asdict(wire.sampling),
                "mechanism": wire.mechanism,
                "timeout_s": wire.timeout_s,
                "max_response_bytes": wire.max_response_bytes,
                "stream": wire.stream,
            }
        )
    except Exception:  # noqa: BLE001 - wire snapshot failures retain the native entry
        operation.evidence_available = False
        snapshot = None
    try:
        operation.append(
            operation.entries,
            EnteredWire(entry_ordinal, str(role), repair_assessment_ref, snapshot),
        )
    except Exception:  # noqa: BLE001 - entry observation sinks are non-semantic
        operation.evidence_available = False
