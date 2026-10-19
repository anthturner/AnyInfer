"""Local structural controls for the request-policy observation grammar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

SCHEMA_PATH = Path(__file__).parent / "fixtures" / "request-policy-v1" / "observations.schema.json"


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _usage() -> dict[str, object]:
    return {
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": "0.000001",
        "search_units": None,
        "server_tool_uses": {},
    }


def _manifest_usage() -> dict[str, object]:
    return {key: value for key, value in _usage().items() if key != "server_tool_uses"}


def _relations() -> dict[str, object]:
    return {
        "request_id_relation": "all_present_same",
        "send_count": 1,
        "terminal_event": "completed",
        "cleanup": "released",
        "cancel_requested": False,
        "cancelled_before_terminal": False,
    }


def _success_operation() -> dict[str, object]:
    return {
        "index": 0,
        "entry_point": "generate",
        "outcome": "ok",
        "result": {
            "target": "alpha:model",
            "text": "ok",
            "structured": None,
            "finish_reason": "stop",
            "usage": _usage(),
            "repair_attempts": 0,
            "warnings": [],
            "tool_calls": [{"id": "call-1", "name": "", "arguments": {}}],
            "manifest": {
                "format": "1",
                "complete": True,
                "request_id_relation": "same_operation",
                "usage": _manifest_usage(),
                "payload": None,
            },
        },
        "error": None,
        "attempts": [{"target": "alpha:model", "outcome": "ok", "error": None}],
        "relations": _relations(),
    }


def _envelope() -> dict[str, object]:
    return {
        "profile": "request-policy-v1",
        "runtime": "python",
        "source_revision": "a" * 40,
        "source_dirty": True,
        "corpus_sha256": "b" * 64,
        "observations": [
            {
                "id": "tool-case",
                "kind": "tool_stream",
                "status": "ok",
                "value": {
                    "operations": [_success_operation()],
                    "ledger": None,
                    "checkpoints": [],
                    "telemetry": [
                        {
                            "type": "RequestCompleted",
                            "operation_index": 0,
                            "target": "alpha:model",
                            "usage": _usage(),
                            "repair_attempts": 0,
                        }
                    ],
                    "http": [],
                    "adapter_wires": [
                        {
                            "operation_index": 0,
                            "script_id": "record-1",
                            "instance": "alpha",
                            "target": "alpha:model",
                            "descriptor": "recording",
                            "messages": [{"role": "user", "content": "redacted input"}],
                            "tools": [{"name": "tool", "description": "d", "parameters": {}}],
                            "tool_choice": None,
                            "cache_marks": [0, 2],
                        }
                    ],
                    "stream_events": [
                        {
                            "type": "tool_call_delta",
                            "operation_index": 0,
                            "index": 0,
                            "id": None,
                            "name": "",
                            "arguments": "{}",
                        }
                    ],
                    "resources": [
                        {
                            "type": "adapter_closed",
                            "operation_index": 0,
                            "script_id": "record-1",
                            "instance": "alpha",
                        }
                    ],
                    "configuration": None,
                },
            }
        ],
    }


def _spend_error() -> dict[str, object]:
    operation = _success_operation()
    operation.update(
        {
            "outcome": "error",
            "result": None,
            "error": {
                "runtime_type": "SpendLimitError",
                "provider": None,
                "phase": "generate",
                "retryable": False,
                "http_status": None,
                "retry_after_s": None,
                "limit_usd": "1",
                "spent_usd": "0",
                "estimated_usd": "1",
            },
            "attempts": [],
            "relations": _relations()
            | {"send_count": 0, "terminal_event": "failed", "cleanup": "not_required"},
        }
    )
    return operation


def test_schema_accepts_typed_empty_terminal_tool_name(validator: Draft202012Validator) -> None:
    validator.validate(_envelope())


def test_python_runtime_rejects_csharp_error_type(validator: Draft202012Validator) -> None:
    payload = _envelope()
    payload["observations"][0]["value"]["operations"] = [_spend_error()]  # type: ignore[index]
    payload["observations"][0]["value"]["operations"][0]["error"]["runtime_type"] = (
        "SpendLimitException"  # type: ignore[index]
    )
    with pytest.raises(ValidationError):
        validator.validate(payload)


@pytest.mark.parametrize(
    ("runtime", "runtime_type"),
    [
        ("python", "ProviderError"),
        ("python", "ProviderUnavailableError"),
        ("python", "ContextLengthError"),
        ("python", "SpendLimitError"),
        ("python", "AllTargetsFailedError"),
        ("csharp", "ProviderException"),
        ("csharp", "ProviderUnavailableException"),
        ("csharp", "ContextLengthException"),
        ("csharp", "SpendLimitException"),
        ("csharp", "AllTargetsFailedException"),
    ],
)
def test_request_failed_accepts_only_the_five_terminal_error_names(
    validator: Draft202012Validator, runtime: str, runtime_type: str
) -> None:
    payload = _envelope()
    payload["runtime"] = runtime
    payload["observations"][0]["value"]["telemetry"] = [  # type: ignore[index]
        {
            "type": "RequestFailed",
            "operation_index": 0,
            "error": {
                "runtime_type": runtime_type,
                "provider": None,
                "phase": "generate",
                "retryable": False,
                "http_status": None,
            },
        }
    ]
    validator.validate(payload)


def test_request_failed_rejects_foreign_amounts_and_retry_after(
    validator: Draft202012Validator,
) -> None:
    payload = _envelope()
    error = {
        "runtime_type": "SpendLimitError",
        "provider": None,
        "phase": "generate",
        "retryable": False,
        "http_status": None,
        "limit_usd": "1",
    }
    payload["observations"][0]["value"]["telemetry"] = [  # type: ignore[index]
        {"type": "RequestFailed", "operation_index": 0, "error": error}
    ]
    with pytest.raises(ValidationError):
        validator.validate(payload)
    error.pop("limit_usd")
    error["retry_after_s"] = 1
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_request_failed_rejects_the_foreign_runtime_family(
    validator: Draft202012Validator,
) -> None:
    payload = _envelope()
    payload["observations"][0]["value"]["telemetry"] = [  # type: ignore[index]
        {
            "type": "RequestFailed",
            "operation_index": 0,
            "error": {
                "runtime_type": "SpendLimitException",
                "provider": None,
                "phase": "generate",
                "retryable": False,
                "http_status": None,
            },
        }
    ]
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_schema_rejects_nonobject_terminal_arguments_and_string_marks(
    validator: Draft202012Validator,
) -> None:
    arguments_payload = _envelope()
    arguments_payload["observations"][0]["value"]["operations"][0]["result"]["tool_calls"][0][
        "arguments"
    ] = "{}"  # type: ignore[index]
    with pytest.raises(ValidationError):
        validator.validate(arguments_payload)

    marks_payload = _envelope()
    marks_payload["observations"][0]["value"]["adapter_wires"][0]["cache_marks"] = ["0"]  # type: ignore[index]
    with pytest.raises(ValidationError):
        validator.validate(marks_payload)


def test_schema_rejects_invented_manifest_server_tool_uses(
    validator: Draft202012Validator,
) -> None:
    payload = _envelope()
    payload["observations"][0]["value"]["operations"][0]["result"]["manifest"][  # type: ignore[index]
        "usage"
    ]["server_tool_uses"] = {}
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_attempt_completed_is_success_without_a_synthetic_attempt_number(
    validator: Draft202012Validator,
) -> None:
    payload = _envelope()
    telemetry = payload["observations"][0]["value"]["telemetry"]  # type: ignore[index]
    telemetry.insert(  # type: ignore[union-attr]
        0,
        {
            "type": "AttemptStarted",
            "operation_index": 0,
            "attempt": 0,
            "target": "alpha:model",
        },
    )
    telemetry.insert(  # type: ignore[union-attr]
        1,
        {"type": "AttemptCompleted", "operation_index": 0, "outcome": "ok"},
    )
    validator.validate(payload)

    telemetry[1]["outcome"] = "failed"  # type: ignore[index]
    with pytest.raises(ValidationError):
        validator.validate(payload)
    telemetry[1]["outcome"] = "ok"  # type: ignore[index]
    telemetry[1]["attempt"] = 0  # type: ignore[index]
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_schema_rejects_impossible_direct_spend_trail(validator: Draft202012Validator) -> None:
    payload = _envelope()
    error = _spend_error()
    error["attempts"] = [{"target": "alpha:model", "outcome": "failed", "error": None}]
    payload["observations"][0]["value"]["operations"] = [error]  # type: ignore[index]
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_schema_rejects_error_outcome_with_a_result(validator: Draft202012Validator) -> None:
    payload = _envelope()
    error = _spend_error()
    error["result"] = _success_operation()["result"]
    payload["observations"][0]["value"]["operations"] = [error]  # type: ignore[index]
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_schema_rejects_label_only_witness_free_and_unknown_capture_fields(
    validator: Draft202012Validator,
) -> None:
    witness_free = _envelope()
    witness_free["observations"][0]["value"]["telemetry"] = []  # type: ignore[index]
    with pytest.raises(ValidationError):
        validator.validate(witness_free)

    labels = _envelope()
    labels["observations"][0]["value"]["event_labels"] = ["RequestCompleted"]  # type: ignore[index]
    with pytest.raises(ValidationError):
        validator.validate(labels)
