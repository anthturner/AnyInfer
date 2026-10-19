"""Synthetic false-pass controls for the request-policy evidence verifier."""

from __future__ import annotations

import copy
import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _checker() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "check_csharp_request_policy.py"
    spec = importlib.util.spec_from_file_location("check_csharp_request_policy", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


CHECKER = _checker()


def _case(*, procedure: str = "single", scripts: list[dict[str, object]] | None = None) -> object:
    return CHECKER.observation.Case(
        "case",
        "admission",
        {
            "id": "case",
            "kind": "admission",
            "procedure": {"name": procedure, "consume": "exact"},
            "scripts": scripts or [],
        },
    )


def _usage() -> dict[str, object]:
    return {
        "input_tokens": 1,
        "output_tokens": 0,
        "total_tokens": 1,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": "0",
        "search_units": None,
        "server_tool_uses": {},
    }


def _manifest_usage() -> dict[str, object]:
    return {key: value for key, value in _usage().items() if key != "server_tool_uses"}


def _value(*, operation_count: int = 1) -> dict[str, object]:
    operations: list[dict[str, object]] = []
    telemetry: list[dict[str, object]] = []
    for index in range(operation_count):
        usage = _usage()
        operations.append(
            {
                "index": index,
                "entry_point": "generate",
                "outcome": "ok",
                "result": {
                    "target": "alpha:model",
                    "text": "ok",
                    "structured": None,
                    "finish_reason": "stop",
                    "usage": usage,
                    "repair_attempts": 0,
                    "warnings": [],
                    "tool_calls": [],
                    "manifest": None,
                },
                "error": None,
                "attempts": [{"target": "alpha:model", "outcome": "ok", "error": None}],
                "relations": {
                    "request_id_relation": "all_present_same",
                    "send_count": 1,
                    "terminal_event": "completed",
                    "cleanup": "not_required",
                    "cancel_requested": False,
                    "cancelled_before_terminal": False,
                },
            }
        )
        telemetry.append(
            {
                "type": "AttemptStarted",
                "operation_index": index,
                "attempt": 1,
                "target": "alpha:model",
            }
        )
        telemetry.append(
            {
                "type": "AttemptCompleted",
                "operation_index": index,
                "outcome": "ok",
            }
        )
        telemetry.append(
            {
                "type": "RequestCompleted",
                "operation_index": index,
                "target": "alpha:model",
                "usage": usage,
                "repair_attempts": 0,
            }
        )
    return {
        "operations": operations,
        "ledger": None,
        "checkpoints": [],
        "telemetry": telemetry,
        "http": [],
        "adapter_wires": [],
        "stream_events": [],
        "resources": [],
        "configuration": None,
    }


def _record(value: dict[str, object]) -> dict[str, object]:
    return {"id": "case", "kind": "admission", "status": "ok", "value": value}


def _case_record(case: object, value: dict[str, object]) -> dict[str, object]:
    return {"id": case.identifier, "kind": case.kind, "status": "ok", "value": value}


def _cache_off_case(*, transport: str = "http") -> object:
    return CHECKER.observation.Case(
        "cache-off",
        "cache",
        {
            "id": "cache-off",
            "kind": "cache",
            "procedure": {"name": "single", "consume": "exact"},
            "scripts": [
                {
                    "id": "cache-off-script",
                    "transport": transport,
                    "instance": "alpha",
                    "status": 200,
                }
            ],
            "request": {"cache": {"mode": "off"}},
        },
    )


def _cache_off_value(*, recording: bool = False) -> dict[str, object]:
    value = _value()
    value["telemetry"] = [
        {"type": "RequestStarted", "operation_index": 0, "targets": ["alpha:model"]},
        {
            "type": "AttemptStarted",
            "operation_index": 0,
            "attempt": 1,
            "target": "alpha:model",
        },
        {"type": "AttemptCompleted", "operation_index": 0, "outcome": "ok"},
        {
            "type": "RequestCompleted",
            "operation_index": 0,
            "target": "alpha:model",
            "usage": _usage(),
            "repair_attempts": 0,
        },
    ]
    capture = {
        "script_id": "cache-off-script",
        "instance": "alpha",
        "operation_index": 0,
        "status": 200,
        "method": "POST",
        "path": "/v1/chat/completions",
        "query": "",
        "request_json": {"messages": []},
    }
    if recording:
        value["adapter_wires"] = [
            {
                "script_id": "cache-off-script",
                "instance": "alpha",
                "operation_index": 0,
                "descriptor": "recording",
                "target": "alpha:model",
                "messages": [],
                "tools": [],
                "tool_choice": None,
                "cache_marks": [],
            }
        ]
    else:
        value["http"] = [capture]
    return value


def _cache_off_record(value: dict[str, object]) -> dict[str, object]:
    return {"id": "cache-off", "kind": "cache", "status": "ok", "value": value}


def _direct_spend_case() -> object:
    case = _case()
    case.raw["policy"] = {"max_request_usd": "1"}
    return case


def _direct_spend_value(runtime: str) -> dict[str, object]:
    value = _value()
    operation = value["operations"][0]
    error = {
        "runtime_type": "SpendLimitError" if runtime == "python" else "SpendLimitException",
        "provider": None,
        "phase": "generate",
        "retryable": False,
        "http_status": None,
        "retry_after_s": None,
        "limit_usd": "1",
        "spent_usd": "0",
        "estimated_usd": "1",
    }
    operation["outcome"] = "error"
    operation["result"] = None
    operation["error"] = error
    operation["attempts"] = []
    operation["relations"] = {
        **operation["relations"],
        "send_count": 0,
        "terminal_event": "none" if runtime == "python" else "failed",
    }
    value["telemetry"] = [
        {"type": "AttemptStarted", "operation_index": 0, "attempt": 1, "target": "alpha:model"}
    ]
    if runtime == "csharp":
        value["telemetry"].append(
            {
                "type": "RequestFailed",
                "operation_index": 0,
                "error": {
                    key: error[key]
                    for key in ("runtime_type", "provider", "phase", "retryable", "http_status")
                },
            }
        )
    return value


def _manifest_suffix_case() -> object:
    case = _case(procedure="repair_no_recheck")
    case.raw["procedure"]["checkpoints"] = [
        "before_dispatch",
        "after_initial_reserve",
        "after_repair",
        "after_terminal_cleanup",
    ]
    case.raw["request"] = {
        "messages": [{"text": "first"}, {"text": "second"}],
        "tools": [{"name": "tool"}],
        "schema": {"type": "object"},
    }
    return case


def _manifest_suffix_value(runtime: str) -> dict[str, object]:
    value = _value()
    operation = value["operations"][0]
    operation["relations"]["send_count"] = 0
    operation["result"]["manifest"] = {
        "format": "1",
        "complete": True,
        "request_id_relation": "same_operation",
        "usage": _manifest_usage(),
        "payload": None,
    }
    initial = ["first", "second", "tool", "schema"]
    terminal = initial + (initial if runtime == "python" else [])
    value["ledger"] = {"totals": {}, "reserved": "0"}
    value["checkpoints"] = [
        {"name": "before_dispatch", "estimator_inputs": []},
        {"name": "after_initial_reserve", "estimator_inputs": initial},
        {"name": "after_repair", "estimator_inputs": initial},
        {"name": "after_terminal_cleanup", "estimator_inputs": terminal},
    ]
    return value


def _no_json_candidate_repair_values(
    runtime: str, *, typed_feedback: bool = False
) -> tuple[object, dict[str, object]]:
    """Build a complete one-operation/two-send repair record for comparator controls."""
    request_messages: list[dict[str, object]]
    first_wire_messages: list[dict[str, object]]
    if typed_feedback:
        request_messages = [
            {
                "role": "tool",
                "parts": [
                    {
                        "type": "tool_result",
                        "call_id": "tool-1",
                        "content": "feedback",
                        "is_error": False,
                    }
                ],
            }
        ]
        first_wire_messages = [{"role": "tool", "tool_call_id": "tool-1", "content": "feedback"}]
        kind = "tool_stream"
        procedure = {"name": "tool_stream", "consume": "exact"}
    else:
        request_messages = [{"role": "user", "content": "repair"}]
        first_wire_messages = [{"role": "user", "content": "repair"}]
        kind = "admission"
        procedure = {
            "name": "repair_no_recheck",
            "checkpoints": [
                "before_dispatch",
                "after_initial_reserve",
                "after_repair",
                "after_terminal_cleanup",
            ],
            "consume": "exact",
        }
    initial = "not json" if typed_feedback else "not-json"
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    scripts = [
        {
            "id": "invalid",
            "transport": "http",
            "instance": "alpha",
            "status": 200,
            "body": {"kind": "json", "value": {"choices": [{"message": {"content": initial}}]}},
        },
        {
            "id": "corrected",
            "transport": "http",
            "instance": "alpha",
            "status": 200,
            "body": {
                "kind": "json",
                "value": {"choices": [{"message": {"content": '{"answer":"fixed"}'}}]},
            },
        },
    ]
    case = CHECKER.observation.Case(
        "repair-no-json",
        kind,
        {
            "id": "repair-no-json",
            "kind": kind,
            "procedure": procedure,
            "request": {
                "target": "alpha:model",
                "schema": schema,
                "repair": {"max_attempts": 1},
                "messages": request_messages,
            },
            "scripts": scripts,
        },
    )
    value = _value()
    if typed_feedback:
        value["operations"][0]["entry_point"] = "stream"  # type: ignore[index]
    value["operations"][0]["relations"]["send_count"] = 2  # type: ignore[index]
    value["operations"][0]["result"]["structured"] = {"answer": "fixed"}  # type: ignore[index]
    value["operations"][0]["result"]["repair_attempts"] = 1  # type: ignore[index]
    value["telemetry"] = [  # type: ignore[index]
        value["telemetry"][0],  # type: ignore[index]
        {"type": "RepairAttempted", "operation_index": 0, "count": 1, "mechanism": "prompt"},
        value["telemetry"][1],  # type: ignore[index]
        {**value["telemetry"][2], "repair_attempts": 1},  # type: ignore[index]
    ]
    prefix = "Your previous response did not match the required JSON schema. Errors:\n- "
    diagnostic = (
        "response was not JSON and contained no JSON object or array"
        if runtime == "python"
        else "No balanced JSON object or array candidate was found."
    )
    suffix = (
        "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, "
        "no code fences."
    )
    correction_messages = [
        *copy.deepcopy(first_wire_messages),
        {"role": "assistant", "content": initial},
        {"role": "user", "content": prefix + diagnostic + suffix},
    ]
    response_format = {"type": "json_schema", "schema": schema}
    value["http"] = [  # type: ignore[index]
        {
            "script_id": "invalid",
            "instance": "alpha",
            "operation_index": 0,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "headers": {
                "content-type": "application/json",
                **({"accept": "text/event-stream"} if typed_feedback else {}),
            },
            "request_json": {
                "messages": copy.deepcopy(first_wire_messages),
                "response_format": response_format,
            },
        },
        {
            "script_id": "corrected",
            "instance": "alpha",
            "operation_index": 0,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "headers": {
                "content-type": "application/json",
                **({"accept": "text/event-stream"} if typed_feedback else {}),
            },
            "request_json": {
                "messages": correction_messages,
                "response_format": response_format,
            },
        },
    ]
    if typed_feedback:
        value["ledger"] = None
        value["checkpoints"] = []
    else:
        components = ["request", "schema"]
        value["ledger"] = {"totals": {}, "reserved": "0"}
        value["checkpoints"] = [  # type: ignore[index]
            {"name": "before_dispatch", "estimator_inputs": []},
            {"name": "after_initial_reserve", "estimator_inputs": components},
            {"name": "after_repair", "estimator_inputs": components},
            {"name": "after_terminal_cleanup", "estimator_inputs": components},
        ]
    return case, value


def _direct_spend_manifest_values() -> tuple[object, dict[str, object], dict[str, object]]:
    """Return a fully qualifying concurrent trace that composes both profiles."""
    scripts = [
        {"id": "held", "transport": "http", "instance": "alpha", "status": 200},
        {"id": "recovery", "transport": "http", "instance": "alpha", "status": 200},
    ]
    case = _case(procedure="concurrent_reservation_recovery", scripts=scripts)
    case.raw["policy"] = {"max_total_usd": "1"}
    case.raw["request"] = {"messages": [{"text": "first"}, {"text": "second"}]}
    case.raw["procedure"]["checkpoints"] = [
        "before_dispatch",
        "after_initial_reserve",
        "after_cancel",
        "after_terminal_cleanup",
    ]
    values: dict[str, dict[str, object]] = {}
    for runtime in ("python", "csharp"):
        value = _value(operation_count=3)
        middle = value["operations"][1]
        error = {
            "runtime_type": "SpendLimitError" if runtime == "python" else "SpendLimitException",
            "provider": None,
            "phase": "generate",
            "retryable": False,
            "http_status": None,
            "retry_after_s": None,
            "limit_usd": "1",
            "spent_usd": "0",
            "estimated_usd": "1",
        }
        middle.update({"outcome": "error", "result": None, "error": error, "attempts": []})
        middle["relations"] = {
            **middle["relations"],
            "send_count": 0,
            "terminal_event": "none" if runtime == "python" else "failed",
        }
        value["operations"][0]["relations"]["cancel_requested"] = True  # type: ignore[index]
        value["operations"][2]["result"]["manifest"] = {  # type: ignore[index]
            "format": "1",
            "complete": True,
            "request_id_relation": "same_operation",
            "usage": _manifest_usage(),
            "payload": None,
        }
        value["telemetry"] = [  # type: ignore[index]
            event
            for event in value["telemetry"]
            if event["operation_index"] != 1 or event["type"] == "AttemptStarted"
        ]
        if runtime == "csharp":
            value["telemetry"].insert(
                4,
                {  # type: ignore[index]
                    "type": "RequestFailed",
                    "operation_index": 1,
                    "error": {
                        key: error[key]
                        for key in (
                            "runtime_type",
                            "provider",
                            "phase",
                            "retryable",
                            "http_status",
                        )
                    },
                },
            )
        value["http"] = [  # type: ignore[index]
            {
                "script_id": script_id,
                "instance": "alpha",
                "operation_index": operation_index,
                "status": 200,
                "method": "POST",
                "path": "/v1/chat/completions",
                "query": "",
                "headers": {"content-type": "application/json"},
                "request_json": {"messages": []},
            }
            for script_id, operation_index in (("held", 0), ("recovery", 2))
        ]
        value["resources"] = [  # type: ignore[index]
            {
                "type": resource_type,
                "script_id": "held",
                "instance": "alpha",
                "operation_index": 0,
            }
            for resource_type in ("handler_entry", "cancel_requested", "body_closed")
        ]
        components = ["first", "second"]
        terminal = components * (5 if runtime == "python" else 4)
        value["ledger"] = {"totals": {}, "reserved": "0"}
        value["checkpoints"] = [  # type: ignore[index]
            {"name": "before_dispatch", "estimator_inputs": []},
            {"name": "after_initial_reserve", "estimator_inputs": components},
            {"name": "after_cancel", "estimator_inputs": components * 2},
            {"name": "after_terminal_cleanup", "estimator_inputs": terminal},
        ]
        values[runtime] = value
    return case, values["python"], values["csharp"]


def test_qualification_rejects_witness_free_success() -> None:
    with pytest.raises(
        CHECKER.ObservationError, match="send count does not match actual primary captures"
    ):
        CHECKER.qualify(_case(), _record(_value()), "python")


def test_qualification_requires_exact_checkpoint_order_and_contiguous_operations() -> None:
    case = _case(procedure="retry_replacement")
    value = _value()
    value["checkpoints"] = [
        {"name": "before_dispatch"},
        {"name": "after_terminal_cleanup"},
    ]
    with pytest.raises(CHECKER.ObservationError, match="checkpoint sequence"):
        CHECKER.qualify(case, _record(value), "python")
    value = _value(operation_count=2)
    value["operations"][1]["index"] = 4  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="contiguous"):
        CHECKER.qualify(_case(), _record(value), "python")


def test_procedure_keeps_outer_operations_distinct_from_sends_and_attempts() -> None:
    repair = _case(procedure="repair_no_recheck")
    repair.raw["procedure"]["checkpoints"] = [  # type: ignore[index]
        "before_dispatch",
        "after_initial_reserve",
        "after_repair",
        "after_terminal_cleanup",
    ]
    repair_value = _value()
    repair_value["ledger"] = {"totals": {}, "reserved": "0"}
    repair_value["checkpoints"] = [
        {"name": name, "estimator_inputs": ["actual"]}
        for name in repair.raw["procedure"]["checkpoints"]  # type: ignore[index]
    ]
    repair_value["operations"][0]["relations"]["send_count"] = 2  # type: ignore[index]
    CHECKER._check_operations(repair_value, repair)

    concurrent = _case(procedure="concurrent_reservation_recovery")
    concurrent.raw["procedure"]["checkpoints"] = [  # type: ignore[index]
        "before_dispatch",
        "after_initial_reserve",
        "after_cancel",
        "after_terminal_cleanup",
    ]
    value = _value(operation_count=3)
    value["operations"][1]["outcome"] = "error"  # type: ignore[index]
    value["operations"][1]["relations"]["terminal_event"] = "failed"  # type: ignore[index]
    value["operations"][1]["relations"]["send_count"] = 0  # type: ignore[index]
    value["operations"][0]["relations"]["send_count"] = 1  # type: ignore[index]
    value["operations"][2]["relations"]["send_count"] = 1  # type: ignore[index]
    CHECKER._check_operations(value, concurrent)


def test_primary_scripts_are_exactly_once_and_in_frozen_order() -> None:
    scripts = [
        {"id": "first", "transport": "http", "instance": "alpha", "status": 503},
        {"id": "second", "transport": "http", "instance": "alpha", "status": 200},
    ]
    case = _case(procedure="retry_replacement", scripts=scripts)
    value = _value()
    value["operations"][0]["relations"]["send_count"] = 2  # type: ignore[index]
    value["http"] = [
        {
            "script_id": "second",
            "instance": "alpha",
            "operation_index": 0,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "request_json": {"messages": []},
        },
        {
            "script_id": "first",
            "instance": "alpha",
            "operation_index": 0,
            "status": 503,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "request_json": {"messages": []},
        },
    ]
    with pytest.raises(CHECKER.ObservationError, match="script order"):
        CHECKER._check_primary_seams(case, value)
    value["http"].pop()
    with pytest.raises(CHECKER.ObservationError, match="exactly one"):
        CHECKER._check_primary_seams(case, value)


def test_checkpoint_baseline_is_empty_then_append_only_and_repair_does_not_recheck() -> None:
    case = _case(procedure="repair_no_recheck")
    case.raw["procedure"]["checkpoints"] = [  # type: ignore[index]
        "before_dispatch",
        "after_initial_reserve",
        "after_repair",
        "after_terminal_cleanup",
    ]
    value = _value()
    value["ledger"] = {"totals": {}, "reserved": "0"}
    value["checkpoints"] = [
        {"name": "before_dispatch", "estimator_inputs": []},
        {"name": "after_initial_reserve", "estimator_inputs": ["first"]},
        {"name": "after_repair", "estimator_inputs": ["first"]},
        {"name": "after_terminal_cleanup", "estimator_inputs": ["first"]},
    ]
    CHECKER._check_checkpoint_sequence(case, value)
    value["checkpoints"][0]["estimator_inputs"] = ["fabricated"]
    with pytest.raises(CHECKER.ObservationError, match="empty estimator history"):
        CHECKER._check_checkpoint_sequence(case, value)


def test_checkpoint_histories_preserve_truthful_stream_and_unknown_fallback_snapshots() -> None:
    stream = _case(procedure="stream_early_close")
    stream.raw["procedure"]["checkpoints"] = [  # type: ignore[index]
        "after_initial_reserve",
        "while_stream_open",
        "after_close",
        "after_terminal_cleanup",
    ]
    stream.raw["request"] = {"messages": [{"text": "admission"}]}
    value = _value()
    value["ledger"] = {"totals": {}, "reserved": "1"}
    value["checkpoints"] = [
        {"name": "after_initial_reserve", "estimator_inputs": ["admission"]},
        {"name": "while_stream_open", "estimator_inputs": ["admission"]},
        {"name": "after_close", "estimator_inputs": ["admission"]},
        {
            "name": "after_terminal_cleanup",
            "estimator_inputs": ["admission", "admission", "admission"],
        },
    ]
    CHECKER._check_checkpoint_sequence(stream, value)
    value["checkpoints"][3]["estimator_inputs"] = ["admission"]
    with pytest.raises(CHECKER.ObservationError, match="source recovery estimator components"):
        CHECKER._check_checkpoint_sequence(stream, value)
    value["checkpoints"][3]["estimator_inputs"] = ["admission", "admission", "admission"]
    value["checkpoints"][2]["estimator_inputs"] = ["rewritten"]
    with pytest.raises(CHECKER.ObservationError, match="rewrite"):
        CHECKER._check_checkpoint_sequence(stream, value)

    fallback = _case(procedure="fallback_handoff")
    fallback.raw["procedure"]["checkpoints"] = [  # type: ignore[index]
        "before_dispatch",
        "after_initial_reserve",
        "after_fallback_handoff",
        "after_terminal_cleanup",
    ]
    value["checkpoints"] = [
        {"name": "before_dispatch", "estimator_inputs": []},
        {"name": "after_initial_reserve", "estimator_inputs": ["known"]},
        {"name": "after_fallback_handoff", "estimator_inputs": ["known"]},
        {"name": "after_terminal_cleanup", "estimator_inputs": ["known"]},
    ]
    CHECKER._check_checkpoint_sequence(fallback, value)


def test_queued_governor_requires_three_operations_with_unsent_cancelled_middle() -> None:
    scripts = [
        {
            "id": "held",
            "transport": "http",
            "instance": "alpha",
            "status": 200,
            "gate": {"name": "queue"},
        },
        {"id": "recovery", "transport": "http", "instance": "alpha", "status": 200},
    ]
    case = _case(procedure="governor_body_gate", scripts=scripts)
    value = _value(operation_count=3)
    value["operations"][0]["relations"]["send_count"] = 1  # type: ignore[index]
    value["operations"][1]["outcome"] = "cancelled"  # type: ignore[index]
    value["operations"][1]["relations"] = {  # type: ignore[index]
        **value["operations"][1]["relations"],
        "send_count": 0,
        "terminal_event": "none",
        "cancel_requested": True,
        "cancelled_before_terminal": True,
    }
    value["operations"][2]["relations"]["send_count"] = 1  # type: ignore[index]
    CHECKER._check_operations(value, case)
    CHECKER._check_unsent_operations(case, value)
    value["operations"].pop()
    with pytest.raises(CHECKER.ObservationError, match="expected 3"):
        CHECKER._check_operations(value, case)


def test_queued_governor_unsent_cancellation_has_no_body_and_waits_for_held_cleanup() -> None:
    scripts = [
        {
            "id": "held",
            "transport": "http",
            "instance": "alpha",
            "status": 200,
            "gate": {"name": "queue"},
        },
        {"id": "recovery", "transport": "http", "instance": "alpha", "status": 200},
    ]
    value = _value(operation_count=3)
    value["operations"][1]["outcome"] = "cancelled"  # type: ignore[index]
    value["operations"][1]["result"] = None  # type: ignore[index]
    value["operations"][1]["attempts"] = []  # type: ignore[index]
    value["operations"][1]["relations"] = {  # type: ignore[index]
        **value["operations"][1]["relations"],
        "send_count": 0,
        "terminal_event": "none",
        "cancel_requested": True,
        "cancelled_before_terminal": True,
    }
    value["http"] = [
        {
            "script_id": "held",
            "instance": "alpha",
            "operation_index": 0,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "request_json": {"messages": []},
        },
        {
            "script_id": "recovery",
            "instance": "alpha",
            "operation_index": 2,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "request_json": {"messages": []},
        },
    ]
    value["resources"] = [
        {"type": "handler_entry", "script_id": "held", "instance": "alpha", "operation_index": 0},
        {"type": "body_ready", "script_id": "held", "instance": "alpha", "operation_index": 0},
        {"type": "cancel_requested", "script_id": None, "instance": None, "operation_index": 1},
        {"type": "pending_observed", "script_id": None, "instance": None, "operation_index": 1},
        {"type": "body_released", "script_id": "held", "instance": "alpha", "operation_index": 0},
        {"type": "body_closed", "script_id": "held", "instance": "alpha", "operation_index": 0},
        {
            "type": "handler_entry",
            "script_id": "recovery",
            "instance": "alpha",
            "operation_index": 2,
        },
    ]
    case = _case(procedure="governor_body_gate", scripts=scripts)
    CHECKER._check_resources(case, value)
    value["resources"].insert(0, value["resources"].pop(6))  # type: ignore[union-attr]
    with pytest.raises(CHECKER.ObservationError, match="cleanup"):
        CHECKER._check_resources(case, value)
    value["resources"].append(value["resources"].pop(0))  # type: ignore[union-attr]
    value["resources"] = [  # type: ignore[index]
        resource for resource in value["resources"] if resource["type"] != "pending_observed"
    ]
    with pytest.raises(CHECKER.ObservationError, match="lacks public evidence"):
        CHECKER._check_resources(case, value)
    value["resources"].append(  # type: ignore[union-attr]
        {"type": "pending_observed", "script_id": None, "instance": None, "operation_index": 1}
    )
    value["resources"].append(  # type: ignore[union-attr]
        {"type": "body_closed", "script_id": None, "instance": None, "operation_index": 1}
    )
    with pytest.raises(CHECKER.ObservationError, match="invents acquired"):
        CHECKER._check_resources(case, value)
    value["resources"].pop()  # type: ignore[union-attr]
    value["http"].append(  # type: ignore[union-attr]
        {
            "script_id": "held",
            "instance": "alpha",
            "operation_index": 1,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "request_json": {"messages": []},
        }
    )
    value["operations"][1]["relations"]["send_count"] = 1  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="exactly one"):
        CHECKER._check_primary_seams(case, value)


def test_cache_off_requires_absence_of_a_cache_plan() -> None:
    case = _cache_off_case()
    value = _cache_off_value()
    CHECKER._check_kind_witnesses(case, value)
    value["telemetry"].insert(  # type: ignore[union-attr]
        3,
        {
            "type": "CachePlanned",
            "operation_index": 0,
            "mechanism": "none",
            "count": 0,
            "estimated_tokens": None,
        },
    )
    with pytest.raises(CHECKER.ObservationError, match="Cache Off"):
        CHECKER._check_kind_witnesses(case, value)


def test_cache_off_complete_trace_allows_unrelated_diagnostics() -> None:
    case = _cache_off_case()
    value = _cache_off_value()
    value["telemetry"].insert(
        3,
        {  # type: ignore[union-attr]
            "type": "ProviderDiagnostic",
            "operation_index": None,
            "target": "alpha:model",
            "code": "transport.degraded",
            "severity": "warning",
        },
    )
    CHECKER.qualify(case, _cache_off_record(value), "python")


def test_cache_off_complete_trace_rejects_cache_plan() -> None:
    case = _cache_off_case()
    value = _cache_off_value()
    value["telemetry"].insert(
        3,
        {  # type: ignore[union-attr]
            "type": "CachePlanned",
            "operation_index": 0,
            "mechanism": "explicit",
            "count": 1,
            "estimated_tokens": 1,
        },
    )
    with pytest.raises(CHECKER.ObservationError, match="Cache Off"):
        CHECKER.qualify(case, _cache_off_record(value), "python")


def test_cache_off_complete_trace_rejects_marks() -> None:
    case = _cache_off_case(transport="recording")
    value = _cache_off_value(recording=True)
    value["adapter_wires"][0]["cache_marks"] = [0]  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="Cache Off"):
        CHECKER.qualify(case, _cache_off_record(value), "python")


def test_cache_off_complete_trace_rejects_cache_mode_drop() -> None:
    case = _cache_off_case()
    value = _cache_off_value()
    value["telemetry"].insert(
        3,
        {  # type: ignore[union-attr]
            "type": "ParameterDropped",
            "operation_index": 0,
            "parameter": "cache.mode",
            "reason": "cache was disabled",
        },
    )
    with pytest.raises(CHECKER.ObservationError, match=r"Cache Off must not drop cache\.mode"):
        CHECKER.qualify(case, _cache_off_record(value), "python")


def test_cache_off_complete_trace_rejects_cache_prefix_diagnostic() -> None:
    case = _cache_off_case()
    value = _cache_off_value()
    value["telemetry"].insert(
        3,
        {  # type: ignore[union-attr]
            "type": "ProviderDiagnostic",
            "operation_index": None,
            "target": "alpha:model",
            "code": "cache.prefix-unstable",
            "severity": "info",
        },
    )
    with pytest.raises(
        CHECKER.ObservationError, match="Cache Off must not emit a cache diagnostic"
    ):
        CHECKER.qualify(case, _cache_off_record(value), "python")


def test_implicit_cache_degradation_uses_declared_prefix_relations_and_order() -> None:
    case = CHECKER.observation.Case(
        "cache",
        "cache",
        {
            "id": "cache",
            "kind": "cache",
            "procedure": {"name": "cache_sequence", "consume": "exact"},
            "scripts": [],
            "request": {
                "cache": {"mode": "explicit"},
                "messages": [
                    {"role": "system", "content": "same"},
                    {"role": "user", "content": "a"},
                ],
                "calls": [
                    {
                        "messages": [
                            {"role": "system", "content": "same"},
                            {"role": "user", "content": "a"},
                        ]
                    },
                    {
                        "messages": [
                            {"role": "system", "content": "same"},
                            {"role": "user", "content": "b"},
                        ]
                    },
                    {
                        "messages": [
                            {"role": "system", "content": "changed"},
                            {"role": "user", "content": "c"},
                        ]
                    },
                ],
            },
            "descriptor": {"cache_mechanism": "implicit"},
        },
    )
    value = _value(operation_count=3)
    value["telemetry"] = [  # type: ignore[index]
        {"type": "RequestStarted", "operation_index": 0, "targets": ["alpha:model"]},
        {
            "type": "ParameterDropped",
            "operation_index": 0,
            "parameter": "cache.mode",
            "reason": "the target offers implicit caching, not explicit marks",
        },
        {
            "type": "CachePlanned",
            "operation_index": 0,
            "target": "alpha:model",
            "mechanism": "implicit",
            "count": 0,
            "estimated_tokens": 1,
        },
        {
            "type": "RequestCompleted",
            "operation_index": 0,
            "target": "alpha:model",
            "usage": _usage(),
            "repair_attempts": 0,
        },
        {"type": "RequestStarted", "operation_index": 1, "targets": ["alpha:model"]},
        {
            "type": "ParameterDropped",
            "operation_index": 1,
            "parameter": "cache.mode",
            "reason": "the target offers implicit caching, not explicit marks",
        },
        {
            "type": "CachePlanned",
            "operation_index": 1,
            "mechanism": "implicit",
            "count": 0,
            "estimated_tokens": 1,
        },
        {
            "type": "RequestCompleted",
            "operation_index": 1,
            "target": "alpha:model",
            "usage": _usage(),
            "repair_attempts": 0,
        },
        {"type": "RequestStarted", "operation_index": 2, "targets": ["alpha:model"]},
        {
            "type": "ProviderDiagnostic",
            "operation_index": None,
            "target": "alpha:model",
            "code": "cache.prefix-unstable",
            "severity": "info",
        },
        {
            "type": "ParameterDropped",
            "operation_index": 2,
            "parameter": "cache.mode",
            "reason": "the target offers implicit caching, not explicit marks",
        },
        {
            "type": "CachePlanned",
            "operation_index": 2,
            "mechanism": "implicit",
            "count": 0,
            "estimated_tokens": 1,
        },
        {
            "type": "RequestCompleted",
            "operation_index": 2,
            "target": "alpha:model",
            "usage": _usage(),
            "repair_attempts": 0,
        },
    ]
    value["adapter_wires"] = [  # type: ignore[index]
        {"operation_index": 0, "cache_marks": []},
        {"operation_index": 1, "cache_marks": []},
        {"operation_index": 2, "cache_marks": []},
    ]
    CHECKER._check_kind_witnesses(case, value)
    baseline = copy.deepcopy(value)
    value["telemetry"].pop(9)  # type: ignore[union-attr]
    with pytest.raises(CHECKER.ObservationError, match="stability diagnostic"):
        CHECKER._check_kind_witnesses(case, value)

    extra = copy.deepcopy(baseline)
    extra["telemetry"].insert(5, copy.deepcopy(baseline["telemetry"][9]))
    with pytest.raises(CHECKER.ObservationError, match="stable implicit prefix"):
        CHECKER._check_kind_witnesses(case, extra)

    wrong_drop = copy.deepcopy(baseline)
    wrong_drop["telemetry"][10]["reason"] = "arbitrary"  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="Explicit-to-Implicit"):
        CHECKER._check_kind_witnesses(case, wrong_drop)

    reversed_drop = copy.deepcopy(baseline)
    reversed_drop["telemetry"][10], reversed_drop["telemetry"][11] = (  # type: ignore[index]
        reversed_drop["telemetry"][11],
        reversed_drop["telemetry"][10],
    )
    with pytest.raises(CHECKER.ObservationError, match="Explicit-to-Implicit"):
        CHECKER._check_kind_witnesses(case, reversed_drop)

    marked = copy.deepcopy(baseline)
    marked["adapter_wires"][2]["cache_marks"] = [0]  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="explicit wire marks"):
        CHECKER._check_kind_witnesses(case, marked)


def test_runtime_pair_is_closed_and_preserves_bool_null_money_and_raw_strings() -> None:
    value = _value()
    python = {"case": _record(value)}
    native = {"case": _record(_value())}
    assert CHECKER.compare_observations((_case(),), python, native).status == "pass"
    native["case"]["value"]["operations"][0]["result"]["usage"]["cost_usd"] = "0.0"  # type: ignore[index]
    assert CHECKER.compare_observations((_case(),), python, native).status == "fail"
    native = {"case": _record(_value())}
    native["case"]["value"]["operations"][0]["relations"]["cancel_requested"] = 0  # type: ignore[index]
    assert CHECKER.compare_observations((_case(),), python, native).status == "fail"
    assert (
        CHECKER._difference_error(
            {"runtime_type": "ProviderError"},
            {"runtime_type": "ProviderException"},
            "value.operations[0].error",
        )
        is None
    )
    assert "approved" in CHECKER._difference_error(
        {"runtime_type": "ProviderError"},
        {"runtime_type": "ContextLengthException"},
        "value.operations[0].error",
    )
    assert (
        CHECKER._difference(
            {"structured": {"runtime_type": "ProviderError"}},
            {"structured": {"runtime_type": "ProviderException"}},
        )
        is not None
    )


def test_manifest_usage_compares_only_the_eight_public_common_fields() -> None:
    value = _value()
    result = value["operations"][0]["result"]  # type: ignore[index]
    result["manifest"] = {  # type: ignore[index]
        "format": "1",
        "complete": True,
        "request_id_relation": "same_operation",
        "usage": _manifest_usage(),
        "payload": None,
    }
    CHECKER._check_correlations(_case(), value)
    result["manifest"]["usage"]["cost_usd"] = "0.0"  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="common public usage facts"):
        CHECKER._check_correlations(_case(), value)


def test_attempt_completed_needs_a_preceding_public_attempt_started() -> None:
    value = _value()
    value["telemetry"] = [  # type: ignore[index]
        event
        for event in value["telemetry"]  # type: ignore[index]
        if event["type"] != "AttemptStarted"
    ]
    with pytest.raises(CHECKER.ObservationError, match="AttemptStarted"):
        CHECKER._check_correlations(_case(), value)


def test_attempt_joins_preserve_retry_ordinal_target_and_terminal_order() -> None:
    value = _value()
    operation = value["operations"][0]  # type: ignore[index]
    operation["attempts"] = [
        {"target": "alpha:model", "outcome": "retried", "error": None},
        {"target": "alpha:model", "outcome": "failed", "error": None},
        {"target": "beta:model", "outcome": "ok", "error": None},
    ]
    operation["result"]["target"] = "beta:model"
    value["telemetry"] = [  # type: ignore[index]
        {"type": "AttemptStarted", "operation_index": 0, "attempt": 1, "target": "alpha:model"},
        {"type": "RetryScheduled", "operation_index": 0, "attempt": 1, "error": None},
        {"type": "AttemptStarted", "operation_index": 0, "attempt": 2, "target": "alpha:model"},
        {"type": "AttemptStarted", "operation_index": 0, "attempt": 1, "target": "beta:model"},
        {"type": "UsageEstimated", "operation_index": 0, "field": "output", "method": "actual"},
        {"type": "AttemptCompleted", "operation_index": 0, "outcome": "ok"},
        {
            "type": "RequestCompleted",
            "operation_index": 0,
            "target": "beta:model",
            "usage": operation["result"]["usage"],
            "repair_attempts": 0,
        },
    ]
    CHECKER._check_correlations(_case(), value)
    value["telemetry"][3]["target"] = "wrong:model"  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="ordinal/target"):
        CHECKER._check_correlations(_case(), value)
    value["telemetry"][3]["target"] = "beta:model"  # type: ignore[index]
    value["telemetry"][3]["attempt"] = 7  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="ordinal/target"):
        CHECKER._check_correlations(_case(), value)
    value["telemetry"][3]["attempt"] = 1  # type: ignore[index]
    value["telemetry"].insert(  # type: ignore[union-attr]
        5,
        value["telemetry"].pop(6),  # type: ignore[index]
    )
    with pytest.raises(CHECKER.ObservationError, match="causally bound"):
        CHECKER._check_correlations(_case(), value)


def test_direct_spend_uses_its_finite_runtime_terminal_profiles() -> None:
    case = _direct_spend_case()
    python_value = _direct_spend_value("python")
    native_value = _direct_spend_value("csharp")
    CHECKER.qualify(case, _case_record(case, python_value), "python")
    CHECKER.qualify(case, _case_record(case, native_value), "csharp")
    comparison = CHECKER.compare_observations(
        (case,), {"case": _record(python_value)}, {"case": _record(native_value)}
    )
    assert comparison.status == "pass"
    assert comparison.runtime_specific == (
        {
            "id": "case",
            "kind": "direct_spend",
            "operation_index": 0,
            "python_terminal_event": "none",
            "native_terminal_event": "failed",
        },
    )

    python_failure = _direct_spend_value("python")
    python_failure["telemetry"].append(  # type: ignore[union-attr]
        {
            "type": "RequestFailed",
            "operation_index": 0,
            "error": python_failure["operations"][0]["error"],
        }  # type: ignore[index]
    )
    with pytest.raises(CHECKER.ObservationError, match="must not emit RequestFailed"):
        CHECKER.qualify(case, _record(python_failure), "python")

    native_missing = _direct_spend_value("csharp")
    native_missing["telemetry"].pop()  # type: ignore[union-attr]
    with pytest.raises(CHECKER.ObservationError, match="needs one post-start"):
        CHECKER.qualify(case, _record(native_missing), "csharp")

    native_duplicate = _direct_spend_value("csharp")
    native_duplicate["telemetry"].append(native_duplicate["telemetry"][1])  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="needs one post-start"):
        CHECKER.qualify(case, _record(native_duplicate), "csharp")

    native_wrong = _direct_spend_value("csharp")
    native_wrong["telemetry"][1]["error"] = {  # type: ignore[index]
        **native_wrong["telemetry"][1]["error"],  # type: ignore[index]
        "phase": "validate",
    }
    with pytest.raises(CHECKER.ObservationError, match="does not preserve its error"):
        CHECKER.qualify(case, _record(native_wrong), "csharp")

    inverted = _direct_spend_value("python")
    inverted["operations"][0]["relations"]["terminal_event"] = "failed"  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="terminal relation"):
        CHECKER.qualify(case, _record(inverted), "python")

    dispatched = _direct_spend_value("python")
    dispatched["operations"][0]["relations"]["send_count"] = 1  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="send count"):
        CHECKER.qualify(case, _record(dispatched), "python")

    money_mismatch = _direct_spend_value("csharp")
    money_mismatch["operations"][0]["error"]["limit_usd"] = "2"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(money_mismatch)}
        ).status
        == "fail"
    )


def test_request_failed_event_rejects_terminal_money_fields() -> None:
    root_schema = CHECKER._schema(CHECKER.OBSERVATION_SCHEMA).schema
    telemetry = CHECKER.Draft202012Validator(
        {"$defs": root_schema["$defs"], "$ref": "#/$defs/telemetry"}
    )
    event = {
        "type": "RequestFailed",
        "operation_index": 0,
        "error": {
            "runtime_type": "SpendLimitError",
            "provider": None,
            "phase": "generate",
            "retryable": False,
            "http_status": None,
        },
        "limit_usd": "1",
    }
    with pytest.raises(CHECKER.ValidationError):
        telemetry.validate(event)


def test_cancellation_keeps_its_actual_start_outside_an_empty_trail() -> None:
    value = _value()
    operation = value["operations"][0]
    operation["outcome"] = "cancelled"
    operation["result"] = None
    operation["attempts"] = []
    operation["relations"] = {
        **operation["relations"],
        "send_count": 0,
        "terminal_event": "none",
        "cancel_requested": True,
        "cancelled_before_terminal": True,
    }
    value["telemetry"] = [
        {"type": "AttemptStarted", "operation_index": 0, "attempt": 1, "target": "alpha:model"}
    ]
    value["resources"] = [
        {"type": "cancel_requested", "script_id": None, "instance": None, "operation_index": 0}
    ]
    CHECKER.qualify(_case(), _record(value), "python")
    value["telemetry"][0]["attempt"] = 2  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="direct cancellation"):
        CHECKER.qualify(_case(), _record(value), "python")

    completed = copy.deepcopy(value)
    completed["telemetry"][0]["attempt"] = 1  # type: ignore[index]
    completed["telemetry"].append(  # type: ignore[union-attr]
        {
            "type": "RequestCompleted",
            "operation_index": 0,
            "target": "alpha:model",
            "usage": _usage(),
            "repair_attempts": 0,
        }
    )
    with pytest.raises(CHECKER.ObservationError, match="must not complete a request"):
        CHECKER.qualify(_case(), _record(completed), "python")

    failed = copy.deepcopy(value)
    failed["telemetry"][0]["attempt"] = 1  # type: ignore[index]
    failed["telemetry"].append(  # type: ignore[union-attr]
        {
            "type": "RequestFailed",
            "operation_index": 0,
            "error": {
                "runtime_type": "ProviderError",
                "provider": None,
                "phase": "generate",
                "retryable": False,
                "http_status": None,
            },
        }
    )
    with pytest.raises(CHECKER.ObservationError, match="must not fail a request"):
        CHECKER.qualify(_case(), _record(failed), "python")

    post_dispatch = copy.deepcopy(value)
    post_dispatch["operations"][0]["relations"]["send_count"] = 1  # type: ignore[index]
    post_dispatch["telemetry"][0]["attempt"] = 1  # type: ignore[index]
    post_dispatch["http"] = [
        {
            "script_id": "sent",
            "instance": "alpha",
            "operation_index": 0,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "request_json": {"messages": []},
        }
    ]
    post_dispatch["resources"] = [
        {"type": "handler_entry", "script_id": "sent", "instance": "alpha", "operation_index": 0},
        {
            "type": "cancel_requested",
            "script_id": "sent",
            "instance": "alpha",
            "operation_index": 0,
        },
        {"type": "body_closed", "script_id": "sent", "instance": "alpha", "operation_index": 0},
    ]
    post_case = _case(
        scripts=[{"id": "sent", "transport": "http", "instance": "alpha", "status": 200}]
    )
    CHECKER.qualify(post_case, _record(post_dispatch), "python")


def test_terminal_manifest_estimator_suffix_is_the_only_admitted_history_difference() -> None:
    case = _manifest_suffix_case()
    python_value = _manifest_suffix_value("python")
    native_value = _manifest_suffix_value("csharp")
    CHECKER.qualify(case, _case_record(case, python_value), "python")
    CHECKER.qualify(case, _case_record(case, native_value), "csharp")
    comparison = CHECKER.compare_observations(
        (case,), {"case": _record(python_value)}, {"case": _record(native_value)}
    )
    assert comparison.status == "pass"
    assert comparison.runtime_specific == (
        {
            "id": "case",
            "kind": "python_terminal_manifest_estimate",
            "python_components": 4,
            "native_components": 0,
        },
    )

    premature = _manifest_suffix_value("python")
    premature["checkpoints"][2]["estimator_inputs"] = [  # type: ignore[index]
        "first",
        "second",
        "tool",
        "schema",
        "first",
        "second",
        "tool",
        "schema",
    ]
    with pytest.raises(CHECKER.ObservationError, match="invents an estimator call"):
        CHECKER.qualify(case, _record(premature), "python")

    extra = _manifest_suffix_value("python")
    extra["checkpoints"][3]["estimator_inputs"].append("extra")  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="unrelated estimator inputs"):
        CHECKER.qualify(case, _record(extra), "python")

    unrelated = _manifest_suffix_value("python")
    unrelated["checkpoints"][3]["estimator_inputs"][-1] = "unrelated"  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="unrelated estimator inputs"):
        CHECKER.qualify(case, _record(unrelated), "python")

    missing_manifest = _manifest_suffix_value("python")
    missing_manifest["operations"][0]["result"]["manifest"] = None  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="invents an estimator call"):
        CHECKER.qualify(case, _record(missing_manifest), "python")

    native_suffix = _manifest_suffix_value("csharp")
    native_suffix["checkpoints"][3]["estimator_inputs"] += [  # type: ignore[index]
        "first",
        "second",
        "tool",
        "schema",
    ]
    with pytest.raises(CHECKER.ObservationError, match="invents an estimator call"):
        CHECKER.qualify(case, _record(native_suffix), "csharp")


def test_comparison_composes_direct_spend_and_manifest_profiles_without_weakening_types() -> None:
    case, python_value, native_value = _direct_spend_manifest_values()
    CHECKER.qualify(case, _record(python_value), "python")
    CHECKER.qualify(case, _record(native_value), "csharp")
    comparison = CHECKER.compare_observations(
        (case,), {"case": _record(python_value)}, {"case": _record(native_value)}
    )
    assert comparison.status == "pass"
    assert comparison.runtime_specific == (
        {
            "id": "case",
            "kind": "direct_spend",
            "operation_index": 1,
            "python_terminal_event": "none",
            "native_terminal_event": "failed",
        },
        {
            "id": "case",
            "kind": "python_terminal_manifest_estimate",
            "python_components": 2,
            "native_components": 0,
        },
    )

    typed_python = copy.deepcopy(python_value)
    typed_native = copy.deepcopy(native_value)
    typed_python["operations"][2]["attempts"][0]["error"] = {  # type: ignore[index]
        "runtime_type": "ProviderError",
        "provider": None,
        "phase": "generate",
        "retryable": False,
        "http_status": 400,
    }
    typed_native["operations"][2]["attempts"][0]["error"] = {  # type: ignore[index]
        "runtime_type": "ProviderException",
        "provider": None,
        "phase": "generate",
        "retryable": False,
        "http_status": 400,
    }
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(typed_python)}, {"case": _record(typed_native)}
        ).status
        == "pass"
    )

    arbitrary_python = copy.deepcopy(python_value)
    arbitrary_native = copy.deepcopy(native_value)
    arbitrary_python["operations"][2]["result"]["structured"] = {  # type: ignore[index]
        "runtime_type": "ProviderError"
    }
    arbitrary_native["operations"][2]["result"]["structured"] = {  # type: ignore[index]
        "runtime_type": "ProviderException"
    }
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(arbitrary_python)}, {"case": _record(arbitrary_native)}
        ).status
        == "fail"
    )

    resources_python = copy.deepcopy(python_value)
    resources_native = copy.deepcopy(native_value)
    resources_python["resources"] += [  # type: ignore[operator]
        {"type": "client_closed", "script_id": None, "instance": None, "operation_index": None},
        {"type": "adapter_closed", "script_id": None, "instance": None, "operation_index": None},
    ]
    resources_native["resources"] += [  # type: ignore[operator]
        {"type": "adapter_closed", "script_id": None, "instance": None, "operation_index": None},
        {"type": "client_closed", "script_id": None, "instance": None, "operation_index": None},
    ]
    CHECKER.qualify(case, _record(resources_python), "python")
    CHECKER.qualify(case, _record(resources_native), "csharp")
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(resources_python)}, {"case": _record(resources_native)}
        ).status
        == "pass"
    )

    wrong_failure = copy.deepcopy(native_value)
    next(event for event in wrong_failure["telemetry"] if event["type"] == "RequestFailed")[
        "operation_index"
    ] = 2  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(wrong_failure)}
        ).status
        == "fail"
    )
    money_mismatch = copy.deepcopy(native_value)
    money_mismatch["operations"][1]["error"]["limit_usd"] = "2"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(money_mismatch)}
        ).status
        == "fail"
    )
    extra_failure = copy.deepcopy(native_value)
    extra_failure["telemetry"].append(  # type: ignore[union-attr]
        next(event for event in native_value["telemetry"] if event["type"] == "RequestFailed")
    )
    # Comparator-only mutation: qualification rejects the duplicate terminal fact first.
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(extra_failure)}
        ).status
        == "fail"
    )


def test_comparison_retains_raw_null_stream_delta_identity() -> None:
    case = _manifest_suffix_case()
    python_value = _manifest_suffix_value("python")
    native_value = _manifest_suffix_value("csharp")
    delta = {"type": "tool_delta", "index": 0, "id": None, "name": None, "arguments": ""}
    python_value["stream_events"] = [delta]
    native_value["stream_events"] = [copy.deepcopy(delta)]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(native_value)}
        ).status
        == "pass"
    )
    native_value["stream_events"][0]["name"] = ""  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(native_value)}
        ).status
        == "fail"
    )


def test_concurrent_comparison_preserves_local_event_order_but_allows_interleaving() -> None:
    case, python_value, native_value = _direct_spend_manifest_values()
    for value in (python_value, native_value):
        telemetry = value["telemetry"]  # type: ignore[assignment]
        for index in range(3):
            start = next(
                position
                for position, event in enumerate(telemetry)
                if event["type"] == "AttemptStarted" and event["operation_index"] == index
            )
            telemetry.insert(  # type: ignore[union-attr]
                start,
                {"type": "RequestStarted", "operation_index": index, "targets": ["alpha:model"]},
            )
    # Keep each operation's events ordered but complete operation zero after recovery.
    zero_terminal = [
        event
        for event in native_value["telemetry"]  # type: ignore[index]
        if event["operation_index"] == 0 and event["type"] != "RequestStarted"
    ]
    native_value["telemetry"] = [  # type: ignore[index]
        event
        for event in native_value["telemetry"]
        if not (event["operation_index"] == 0 and event["type"] != "RequestStarted")
    ]
    native_value["telemetry"].extend(zero_terminal)  # type: ignore[union-attr]
    CHECKER.qualify(case, _record(python_value), "python")
    CHECKER.qualify(case, _record(native_value), "csharp")
    comparison = CHECKER.compare_observations(
        (case,), {"case": _record(python_value)}, {"case": _record(native_value)}
    )
    assert comparison.status == "pass"
    assert any(
        item["kind"] == "concurrent_telemetry_interleaving" for item in comparison.runtime_specific
    )

    reordered_start = copy.deepcopy(native_value)
    start_indexes = [
        index
        for index, event in enumerate(reordered_start["telemetry"])
        if event["type"] == "RequestStarted"
    ]
    first, second = start_indexes[:2]
    reordered_start["telemetry"][first], reordered_start["telemetry"][second] = (  # type: ignore[index]
        reordered_start["telemetry"][second],
        reordered_start["telemetry"][first],
    )
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(reordered_start)}
        ).status
        == "fail"
    )

    provider_python = copy.deepcopy(python_value)
    provider_native = copy.deepcopy(native_value)
    provider_events = [
        {
            "type": "ProviderDiagnostic",
            "operation_index": None,
            "target": "alpha:model",
            "code": code,
            "severity": "warning",
        }
        for code in ("first", "second")
    ]
    provider_python["telemetry"].extend(provider_events)  # type: ignore[union-attr]
    provider_native["telemetry"].extend(reversed(provider_events))  # type: ignore[union-attr]
    # Comparator-only mutation: public provider diagnostics have no request association,
    # but their retained values and within-instance order must remain exact.
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(provider_python)}, {"case": _record(provider_native)}
        ).status
        == "fail"
    )


def test_transport_header_profile_is_narrow_and_redacted() -> None:
    case, python_value, native_value = _direct_spend_manifest_values()
    for capture in python_value["http"]:  # type: ignore[union-attr]
        capture["headers"] = {
            "content-type": "application/json",
            "user-agent": "python-http",
            "authorization": "Bearer [redacted]",
        }
    for capture in native_value["http"]:  # type: ignore[union-attr]
        capture["headers"] = {"Content-Type": "application/json", "User-Agent": "dotnet-http"}
    CHECKER.qualify(case, _record(python_value), "python")
    CHECKER.qualify(case, _record(native_value), "csharp")
    comparison = CHECKER.compare_observations(
        (case,), {"case": _record(python_value)}, {"case": _record(native_value)}
    )
    assert comparison.status == "pass"
    assert any(item["kind"] == "transport_default_headers" for item in comparison.runtime_specific)

    bare_marker_python = copy.deepcopy(python_value)
    bare_marker_native = copy.deepcopy(native_value)
    for capture in bare_marker_python["http"]:  # type: ignore[union-attr]
        capture["headers"]["authorization"] = "[redacted]"
    assert (
        CHECKER.compare_observations(
            (case,),
            {"case": _record(bare_marker_python)},
            {"case": _record(bare_marker_native)},
        ).status
        == "pass"
    )
    for capture in bare_marker_native["http"]:  # type: ignore[union-attr]
        capture["headers"]["authorization"] = "Bearer [redacted]"
    assert (
        CHECKER.compare_observations(
            (case,),
            {"case": _record(bare_marker_python)},
            {"case": _record(bare_marker_native)},
        ).status
        == "pass"
    )

    missing_content_python = copy.deepcopy(python_value)
    missing_content_native = copy.deepcopy(native_value)
    for value in (missing_content_python, missing_content_native):
        value["http"][0]["headers"].pop("content-type", None)  # type: ignore[index]
        value["http"][0]["headers"].pop("Content-Type", None)  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,),
            {"case": _record(missing_content_python)},
            {"case": _record(missing_content_native)},
        ).status
        == "fail"
    )

    content_type = copy.deepcopy(native_value)
    content_type["http"][0]["headers"]["Content-Type"] = "text/plain"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(content_type)}
        ).status
        == "fail"
    )

    custom = copy.deepcopy(native_value)
    custom["http"][0]["headers"]["x-policy"] = "different"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(custom)}
        ).status
        == "fail"
    )

    secret = copy.deepcopy(native_value)
    secret["http"][0]["headers"]["authorization"] = "Bearer fixture-token"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(secret)}
        ).status
        == "fail"
    )

    equal_secret_python = copy.deepcopy(python_value)
    equal_secret_native = copy.deepcopy(native_value)
    for value in (equal_secret_python, equal_secret_native):
        value["http"][0]["headers"]["authorization"] = "Bearer fixture-token"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,),
            {"case": _record(equal_secret_python)},
            {"case": _record(equal_secret_native)},
        ).status
        == "fail"
    )

    configured_case = copy.deepcopy(case)
    configured_case.raw["instances"] = [
        {
            "id": "alpha",
            "headers": {"User-Agent": "fixed-agent", "Accept": "application/json"},
        }
    ]
    configured_python = copy.deepcopy(python_value)
    configured_native = copy.deepcopy(native_value)
    for capture in configured_python["http"]:  # type: ignore[union-attr]
        capture["headers"] = {
            "content-type": "application/json",
            "user-agent": "fixed-agent",
            "accept": "application/json",
            "authorization": "Bearer [redacted]",
        }
    for capture in configured_native["http"]:  # type: ignore[union-attr]
        capture["headers"] = {
            "Content-Type": "application/json",
            "User-Agent": "fixed-agent",
            "Accept": "application/json",
        }
    CHECKER.qualify(configured_case, _record(configured_python), "python")
    CHECKER.qualify(configured_case, _record(configured_native), "csharp")
    assert (
        CHECKER.compare_observations(
            (configured_case,),
            {"case": _record(configured_python)},
            {"case": _record(configured_native)},
        ).status
        == "pass"
    )
    configured_mutant = copy.deepcopy(configured_native)
    configured_mutant["http"][0]["headers"]["Accept"] = "application/x-other"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (configured_case,),
            {"case": _record(configured_python)},
            {"case": _record(configured_mutant)},
        ).status
        == "fail"
    )

    # The frozen input grammar intentionally has no headers field yet.  This is a
    # comparator-only future-settings stimulus: only the matching literal provider
    # establishes a configured header, while an unmatched provider must not suppress the
    # closed transport-default profile.
    provider_config_case = copy.deepcopy(case)
    provider_config_case.raw["config"] = {
        "providers": [{"id": "alpha", "headers": {"Accept": "application/json"}}]
    }
    provider_config_python = copy.deepcopy(python_value)
    provider_config_native = copy.deepcopy(native_value)
    for capture in provider_config_python["http"]:  # type: ignore[union-attr]
        capture["headers"]["accept"] = "application/json"
    for capture in provider_config_native["http"]:  # type: ignore[union-attr]
        capture["headers"]["accept"] = "application/json"
    CHECKER.qualify(provider_config_case, _record(provider_config_python), "python")
    CHECKER.qualify(provider_config_case, _record(provider_config_native), "csharp")
    provider_config_mutant = copy.deepcopy(provider_config_native)
    provider_config_mutant["http"][0]["headers"]["accept"] = "application/x-other"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (provider_config_case,),
            {"case": _record(provider_config_python)},
            {"case": _record(provider_config_mutant)},
        ).status
        == "fail"
    )

    unmatched_provider_case = copy.deepcopy(case)
    unmatched_provider_case.raw["config"] = {
        "providers": [{"id": "beta", "headers": {"Accept": "application/json"}}]
    }
    unmatched_python = copy.deepcopy(python_value)
    unmatched_native = copy.deepcopy(native_value)
    for capture in unmatched_python["http"]:  # type: ignore[union-attr]
        capture["headers"]["accept"] = "application/x-python"
    for capture in unmatched_native["http"]:  # type: ignore[union-attr]
        capture["headers"]["accept"] = "application/x-native"
    CHECKER.qualify(unmatched_provider_case, _record(unmatched_python), "python")
    CHECKER.qualify(unmatched_provider_case, _record(unmatched_native), "csharp")
    assert (
        CHECKER.compare_observations(
            (unmatched_provider_case,),
            {"case": _record(unmatched_python)},
            {"case": _record(unmatched_native)},
        ).status
        == "pass"
    )

    duplicate_case = copy.deepcopy(case)
    duplicate_python = copy.deepcopy(python_value)
    duplicate_native = copy.deepcopy(native_value)
    duplicate_python["http"][0]["headers"]["Accept"] = "application/json"  # type: ignore[index]
    duplicate_python["http"][0]["headers"]["aCcEpT"] = "application/json"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (duplicate_case,),
            {"case": _record(duplicate_python)},
            {"case": _record(duplicate_native)},
        ).status
        == "fail"
    )

    streaming_python = copy.deepcopy(python_value)
    streaming_native = copy.deepcopy(native_value)
    for value in (streaming_python, streaming_native):
        value["operations"][0]["entry_point"] = "stream"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(streaming_python)}, {"case": _record(streaming_native)}
        ).status
        == "fail"
    )
    for value, accept in ((streaming_python, "text/event-stream"), (streaming_native, "*/*")):
        value["http"][0]["headers"]["accept"] = accept  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(streaming_python)}, {"case": _record(streaming_native)}
        ).status
        == "fail"
    )


def test_no_json_candidate_repair_feedback_is_a_single_typed_profile() -> None:
    case, python_value = _no_json_candidate_repair_values("python")
    _, native_value = _no_json_candidate_repair_values("csharp")
    CHECKER.qualify(case, _case_record(case, python_value), "python")
    CHECKER.qualify(case, _case_record(case, native_value), "csharp")
    comparison = CHECKER.compare_observations(
        (case,),
        {"repair-no-json": _case_record(case, python_value)},
        {"repair-no-json": _case_record(case, native_value)},
    )
    assert comparison.status == "pass"
    assert comparison.runtime_specific == (
        {
            "id": "repair-no-json",
            "kind": "no_json_candidate_repair_feedback",
            "operation_index": 0,
            "initial_script_id": "invalid",
            "correction_script_id": "corrected",
            "python_diagnostic": "response was not JSON and contained no JSON object or array",
            "csharp_diagnostic": "No balanced JSON object or array candidate was found.",
        },
    )

    unknown = copy.deepcopy(native_value)
    unknown["http"][1]["request_json"]["messages"][-1]["content"] = (  # type: ignore[index]
        "Your previous response did not match the required JSON schema. Errors:\n- unknown"
        "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, "
        "no code fences."
    )
    assert (
        CHECKER.compare_observations(
            (case,),
            {"repair-no-json": _case_record(case, python_value)},
            {"repair-no-json": _case_record(case, unknown)},
        ).status
        == "fail"
    )

    altered_wrapper = copy.deepcopy(native_value)
    altered_wrapper["http"][1]["request_json"]["messages"][-1]["content"] = (  # type: ignore[index]
        "Changed wrapper\n- No balanced JSON object or array candidate was found."
    )
    assert (
        CHECKER.compare_observations(
            (case,),
            {"repair-no-json": _case_record(case, python_value)},
            {"repair-no-json": _case_record(case, altered_wrapper)},
        ).status
        == "fail"
    )

    missing_repair = copy.deepcopy(native_value)
    missing_repair["telemetry"] = [  # type: ignore[index]
        event
        for event in missing_repair["telemetry"]
        if event["type"] != "RepairAttempted"  # type: ignore[index]
    ]
    assert (
        CHECKER.compare_observations(
            (case,),
            {"repair-no-json": _case_record(case, python_value)},
            {"repair-no-json": _case_record(case, missing_repair)},
        ).status
        == "fail"
    )

    reordered_repair = copy.deepcopy(native_value)
    reordered_repair["telemetry"][1], reordered_repair["telemetry"][2] = (  # type: ignore[index]
        reordered_repair["telemetry"][2],
        reordered_repair["telemetry"][1],
    )
    assert (
        CHECKER.compare_observations(
            (case,),
            {"repair-no-json": _case_record(case, python_value)},
            {"repair-no-json": _case_record(case, reordered_repair)},
        ).status
        == "fail"
    )

    changed_target = copy.deepcopy(native_value)
    changed_target["operations"][0]["result"]["target"] = "beta:model"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,),
            {"repair-no-json": _case_record(case, python_value)},
            {"repair-no-json": _case_record(case, changed_target)},
        ).status
        == "fail"
    )

    changed_schema = copy.deepcopy(native_value)
    changed_schema["http"][1]["request_json"]["response_format"]["schema"]["required"] = []  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,),
            {"repair-no-json": _case_record(case, python_value)},
            {"repair-no-json": _case_record(case, changed_schema)},
        ).status
        == "fail"
    )

    changed_script = copy.deepcopy(native_value)
    changed_script["http"][1]["script_id"] = "other"  # type: ignore[index]
    assert (
        CHECKER.compare_observations(
            (case,),
            {"repair-no-json": _case_record(case, python_value)},
            {"repair-no-json": _case_record(case, changed_script)},
        ).status
        == "fail"
    )

    valid_stimulus = copy.deepcopy(case)
    valid_stimulus.raw["scripts"][0]["body"]["value"]["choices"][0]["message"]["content"] = "{}"
    assert (
        CHECKER.compare_observations(
            (valid_stimulus,),
            {"repair-no-json": _case_record(valid_stimulus, python_value)},
            {"repair-no-json": _case_record(valid_stimulus, native_value)},
        ).status
        == "fail"
    )

    feedback_case, feedback_python = _no_json_candidate_repair_values(
        "python", typed_feedback=True
    )
    _, feedback_native = _no_json_candidate_repair_values("csharp", typed_feedback=True)
    assert feedback_case.kind == "tool_stream"
    assert feedback_case.raw["procedure"] == {"name": "tool_stream", "consume": "exact"}
    assert feedback_python["operations"][0]["entry_point"] == "stream"  # type: ignore[index]
    CHECKER.qualify(feedback_case, _case_record(feedback_case, feedback_python), "python")
    CHECKER.qualify(feedback_case, _case_record(feedback_case, feedback_native), "csharp")
    assert (
        CHECKER.compare_observations(
            (feedback_case,),
            {"repair-no-json": _case_record(feedback_case, feedback_python)},
            {"repair-no-json": _case_record(feedback_case, feedback_native)},
        ).status
        == "pass"
    )

    for mutate in (
        lambda stream_case: stream_case.raw["request"].pop("schema"),
        lambda stream_case: stream_case.raw["request"].pop("repair"),
        lambda stream_case: stream_case.raw["procedure"].__setitem__("name", "single"),
    ):
        nonrepair_stream = copy.deepcopy(feedback_case)
        mutate(nonrepair_stream)
        assert (
            CHECKER.compare_observations(
                (nonrepair_stream,),
                {"repair-no-json": _case_record(nonrepair_stream, feedback_python)},
                {"repair-no-json": _case_record(nonrepair_stream, feedback_native)},
            ).status
            == "fail"
        )

    stream_unknown = copy.deepcopy(feedback_native)
    stream_unknown["http"][1]["request_json"]["messages"][-1]["content"] = (  # type: ignore[index]
        "Your previous response did not match the required JSON schema. Errors:\n- unknown"
        "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, "
        "no code fences."
    )
    assert (
        CHECKER.compare_observations(
            (feedback_case,),
            {"repair-no-json": _case_record(feedback_case, feedback_python)},
            {"repair-no-json": _case_record(feedback_case, stream_unknown)},
        ).status
        == "fail"
    )

    stream_wrapper = copy.deepcopy(feedback_native)
    stream_wrapper["http"][1]["request_json"]["messages"][-1]["content"] = (  # type: ignore[index]
        "Changed wrapper\n- No balanced JSON object or array candidate was found."
    )
    assert (
        CHECKER.compare_observations(
            (feedback_case,),
            {"repair-no-json": _case_record(feedback_case, feedback_python)},
            {"repair-no-json": _case_record(feedback_case, stream_wrapper)},
        ).status
        == "fail"
    )

    altered_feedback = copy.deepcopy(feedback_native)
    altered_feedback["http"][1]["request_json"]["messages"][0]["content"] = "altered"  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="repair wire"):
        CHECKER.qualify(feedback_case, _case_record(feedback_case, altered_feedback), "csharp")

    dropped_feedback = copy.deepcopy(feedback_native)
    dropped_feedback["http"][1]["request_json"]["messages"].pop(0)  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="repair wire"):
        CHECKER.qualify(feedback_case, _case_record(feedback_case, dropped_feedback), "csharp")


def test_terminal_manifest_suffix_preserves_shared_recovery_work() -> None:
    case = _manifest_suffix_case()
    case.raw["procedure"] = {
        "name": "stream_early_close",
        "consume": "exact",
        "checkpoints": [
            "after_initial_reserve",
            "while_stream_open",
            "after_close",
            "after_terminal_cleanup",
        ],
    }
    python_value = _manifest_suffix_value("python")
    native_value = _manifest_suffix_value("csharp")
    components = ["first", "second", "tool", "schema"]
    initial = components + components
    recovery = components + components
    python_value["checkpoints"] = [
        {"name": "after_initial_reserve", "estimator_inputs": initial},
        {"name": "while_stream_open", "estimator_inputs": initial},
        {"name": "after_close", "estimator_inputs": initial},
        {
            "name": "after_terminal_cleanup",
            "estimator_inputs": initial + recovery + initial[:4],
        },
    ]
    native_value["checkpoints"] = [
        {"name": "after_initial_reserve", "estimator_inputs": initial},
        {"name": "while_stream_open", "estimator_inputs": initial},
        {"name": "after_close", "estimator_inputs": initial},
        {"name": "after_terminal_cleanup", "estimator_inputs": initial + recovery},
    ]
    CHECKER._check_checkpoint_sequence(case, python_value, "python")
    CHECKER._check_checkpoint_sequence(case, native_value, "csharp")
    assert (
        CHECKER.compare_observations(
            (case,), {"case": _record(python_value)}, {"case": _record(native_value)}
        ).status
        == "pass"
    )

    for baseline, runtime, suffix in (
        (python_value, "python", components),
        (native_value, "csharp", []),
    ):
        for replacement in (
            [],
            ["wrong", *recovery[1:]],
            recovery[:-1],
            [*recovery, "extra"],
            list(reversed(recovery)),
        ):
            wrong_recovery = copy.deepcopy(baseline)
            wrong_recovery["checkpoints"][3]["estimator_inputs"] = [  # type: ignore[index]
                *initial,
                *replacement,
                *suffix,
            ]
            with pytest.raises(
                CHECKER.ObservationError, match="source recovery estimator components"
            ):
                CHECKER._check_checkpoint_sequence(case, wrong_recovery, runtime)


@pytest.mark.parametrize("runtime", ("python", "csharp"))
def test_concurrent_refusal_adds_only_its_unsent_original_request_estimate(
    runtime: str,
) -> None:
    case = _case(procedure="concurrent_reservation_recovery")
    case.raw["policy"] = {"max_total_usd": "1"}
    case.raw["request"] = {"messages": [{"text": "first"}, {"text": "second"}]}
    value = _value(operation_count=3)
    middle = value["operations"][1]
    error = {
        "runtime_type": "SpendLimitError" if runtime == "python" else "SpendLimitException",
        "provider": None,
        "phase": "generate",
        "retryable": False,
        "http_status": None,
    }
    middle.update({"outcome": "error", "result": None, "error": error, "attempts": []})
    middle["relations"] = {
        **middle["relations"],
        "send_count": 0,
        "terminal_event": "none" if runtime == "python" else "failed",
    }
    value["ledger"] = {"totals": {}, "reserved": "0"}
    value["checkpoints"] = [
        {"name": "before_dispatch", "estimator_inputs": []},
        {"name": "after_initial_reserve", "estimator_inputs": ["first", "second"]},
        {
            "name": "after_cancel",
            "estimator_inputs": ["first", "second", "first", "second"],
        },
        {
            "name": "after_terminal_cleanup",
            "estimator_inputs": [
                "first",
                "second",
                "first",
                "second",
                "first",
                "second",
                "first",
                "second",
            ],
        },
    ]
    CHECKER._check_checkpoint_sequence(case, value, runtime)

    missing = copy.deepcopy(value)
    missing["checkpoints"][2]["estimator_inputs"] = ["first", "second"]  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="exactly the middle"):
        CHECKER._check_checkpoint_sequence(case, missing, runtime)

    wrong = copy.deepcopy(value)
    wrong["checkpoints"][2]["estimator_inputs"][-1] = "wrong"  # type: ignore[index]
    wrong["checkpoints"][3]["estimator_inputs"][3] = "wrong"  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="exactly the middle"):
        CHECKER._check_checkpoint_sequence(case, wrong, runtime)

    extra = copy.deepcopy(value)
    extra["checkpoints"][2]["estimator_inputs"].append("extra")  # type: ignore[index]
    extra["checkpoints"][3]["estimator_inputs"] = [  # type: ignore[index]
        *extra["checkpoints"][2]["estimator_inputs"],
        "first",
        "second",
    ]
    with pytest.raises(CHECKER.ObservationError, match="exactly the middle"):
        CHECKER._check_checkpoint_sequence(case, extra, runtime)

    sent = copy.deepcopy(value)
    sent["operations"][1]["relations"]["send_count"] = 1  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="unsent direct-spend"):
        CHECKER._check_checkpoint_sequence(case, sent, runtime)


def test_tool_repair_requires_exact_outbound_first_feedback_without_inbound_calls() -> None:
    case = CHECKER.observation.Case(
        "repair",
        "tool_stream",
        {
            "id": "repair",
            "kind": "tool_stream",
            "procedure": {"name": "tool_stream", "consume": "exact"},
            "scripts": [
                {"id": "invalid", "transport": "http", "instance": "alpha", "status": 200},
                {"id": "corrected", "transport": "http", "instance": "alpha", "status": 200},
            ],
            "request": {
                "repair": {"max_attempts": 1},
                "messages": [
                    {
                        "role": "tool",
                        "parts": [
                            {
                                "type": "tool_result",
                                "call_id": "first",
                                "content": "feedback-a",
                                "is_error": False,
                            },
                            {
                                "type": "tool_result",
                                "call_id": "later",
                                "content": "feedback-b",
                                "is_error": False,
                            },
                        ],
                    }
                ],
            },
        },
    )
    value = _value()
    value["operations"][0]["result"]["structured"] = {"answer": "fixed"}  # type: ignore[index]
    value["operations"][0]["result"]["repair_attempts"] = 1  # type: ignore[index]
    value["telemetry"].append(  # type: ignore[union-attr]
        {"type": "RepairAttempted", "operation_index": 0, "count": 1, "mechanism": "json"}
    )
    value["http"] = [  # type: ignore[index]
        {
            "script_id": "invalid",
            "operation_index": 0,
            "request_json": {
                "messages": [{"role": "tool", "tool_call_id": "first", "content": "feedback-a"}]
            },
        },
        {
            "script_id": "corrected",
            "operation_index": 0,
            "request_json": {
                "messages": [{"role": "tool", "tool_call_id": "first", "content": "feedback-a"}]
            },
        },
    ]
    CHECKER._check_kind_witnesses(case, value)

    wrong_feedback = copy.deepcopy(value)
    wrong_feedback["http"][1]["request_json"]["messages"][0]["tool_call_id"] = "later"  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="repair wire"):
        CHECKER._check_kind_witnesses(case, wrong_feedback)

    invented_delta = copy.deepcopy(value)
    invented_delta["stream_events"] = [  # type: ignore[index]
        {
            "type": "tool_call_delta",
            "operation_index": 0,
            "index": 0,
            "id": "call",
            "name": "tool",
            "arguments": "{}",
        }
    ]
    with pytest.raises(CHECKER.ObservationError, match="outbound-only repair"):
        CHECKER._check_kind_witnesses(case, invented_delta)

    missing_result = copy.deepcopy(value)
    missing_result["operations"][0]["result"]["structured"] = None  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="corrected structured result"):
        CHECKER._check_kind_witnesses(case, missing_result)


def test_malformed_tool_warnings_follow_terminal_index_order_not_delta_arrival() -> None:
    case = CHECKER.observation.Case(
        "fragments",
        "tool_stream",
        {
            "id": "fragments",
            "kind": "tool_stream",
            "procedure": {"name": "tool_stream", "consume": "exact"},
            "scripts": [
                {
                    "id": "fragments",
                    "events": [
                        {
                            "type": "tool_call_delta",
                            "index": 2,
                            "call_id": "two",
                            "name": "",
                            "arguments_fragment": '{"x":',
                        },
                        {
                            "type": "tool_call_delta",
                            "index": 0,
                            "call_id": "zero",
                            "name": "",
                            "arguments_fragment": "not-json",
                        },
                        {
                            "type": "tool_call_delta",
                            "index": 1,
                            "call_id": "one",
                            "name": "",
                            "arguments_fragment": "[]",
                        },
                        {
                            "type": "tool_call_delta",
                            "index": 3,
                            "call_id": "three",
                            "name": "",
                            "arguments_fragment": "",
                        },
                    ],
                }
            ],
            "request": {"messages": []},
        },
    )
    value = _value()
    value["adapter_wires"] = [{"script_id": "fragments", "operation_index": 0}]
    value["stream_events"] = [
        {
            "type": "tool_call_delta",
            "operation_index": 0,
            "index": index,
            "id": call_id,
            "name": name,
            "arguments": fragment,
        }
        for index, call_id, name, fragment in [
            (2, "two", "", '{"x":'),
            (0, "zero", "", "not-json"),
            (1, "one", "", "[]"),
            (3, "three", "", ""),
        ]
    ]
    value["operations"][0]["result"]["warnings"] = [  # type: ignore[index]
        "tool call 0 had unparseable arguments; using an empty argument object",
        "tool call 1 arguments were not a JSON object; using an empty argument object",
        "tool call 2 had unparseable arguments; using an empty argument object",
    ]
    CHECKER._check_tool_witnesses(case, value, {"messages": []})

    for warnings in (
        value["operations"][0]["result"]["warnings"][:-1],  # type: ignore[index]
        [
            "tool call 0 had unparseable arguments; using an empty argument object",
            "tool call 2 had unparseable arguments; using an empty argument object",
            "tool call 1 arguments were not a JSON object; using an empty argument object",
        ],
        value["operations"][0]["result"]["warnings"]
        + ["tool call 3 had unparseable arguments; using an empty argument object"],  # type: ignore[index]
    ):
        mutant = copy.deepcopy(value)
        mutant["operations"][0]["result"]["warnings"] = warnings  # type: ignore[index]
        with pytest.raises(CHECKER.ObservationError, match="source index order"):
            CHECKER._check_tool_witnesses(case, mutant, {"messages": []})


def test_null_tool_delta_name_is_retained_without_warning_normalization() -> None:
    case = CHECKER.observation.Case(
        "null-name",
        "tool_stream",
        {
            "id": "null-name",
            "kind": "tool_stream",
            "procedure": {"name": "tool_stream", "consume": "exact"},
            "scripts": [
                {
                    "id": "null-name-script",
                    "transport": "http",
                    "instance": "alpha",
                    "status": 200,
                    "events": [
                        {
                            "type": "tool_call_delta",
                            "index": 0,
                            "call_id": None,
                            "name": None,
                            "arguments_fragment": "",
                        }
                    ],
                }
            ],
            "request": {"messages": []},
        },
    )
    value = _value()
    value["http"] = [
        {
            "script_id": "null-name-script",
            "instance": "alpha",
            "operation_index": 0,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "request_json": {"messages": []},
        }
    ]
    value["stream_events"] = [
        {
            "type": "tool_call_delta",
            "operation_index": 0,
            "index": 0,
            "id": None,
            "name": None,
            "arguments": "",
        }
    ]
    record = {"id": "null-name", "kind": "tool_stream", "status": "ok", "value": value}
    CHECKER.qualify(case, record, "python")

    empty_name = copy.deepcopy(value)
    empty_name["stream_events"][0]["name"] = ""  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="ordered script subsequence"):
        CHECKER.qualify(
            case,
            {"id": "null-name", "kind": "tool_stream", "status": "ok", "value": empty_name},
            "python",
        )

    malformed_name = copy.deepcopy(case)
    malformed_name.raw["scripts"][0]["events"][0]["name"] = 1
    malformed_value = copy.deepcopy(value)
    malformed_value["stream_events"][0]["name"] = 1  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="non-string name or fragment"):
        CHECKER._check_tool_witnesses(malformed_name, malformed_value, {"messages": []})

    malformed_fragment = copy.deepcopy(case)
    malformed_fragment.raw["scripts"][0]["events"][0]["arguments_fragment"] = None
    malformed_value = copy.deepcopy(value)
    malformed_value["stream_events"][0]["arguments"] = None  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="non-string name or fragment"):
        CHECKER._check_tool_witnesses(malformed_fragment, malformed_value, {"messages": []})


def test_resource_comparison_ignores_unconstrained_cleanup_order() -> None:
    python = {"resources": [{"type": "client_closed"}, {"type": "adapter_closed"}]}
    native = {"resources": [{"type": "adapter_closed"}, {"type": "client_closed"}]}
    assert CHECKER._difference(python, native) is None
    nested_python = {
        "operations": [
            {
                "result": {
                    "structured": {"operations": [{"error": {"runtime_type": "ProviderError"}}]}
                }
            }
        ]
    }
    nested_native = {
        "operations": [
            {
                "result": {
                    "structured": {
                        "operations": [{"error": {"runtime_type": "ProviderException"}}]
                    }
                }
            }
        ]
    }
    assert CHECKER._difference(nested_python, nested_native) is not None


def test_primary_script_and_resource_partial_order_are_required() -> None:
    scripts = [
        {
            "id": "s",
            "transport": "http",
            "instance": "alpha",
            "status": 200,
            "gate": {"name": "body"},
        }
    ]
    value = _value()
    value["http"] = [
        {
            "script_id": "s",
            "instance": "alpha",
            "operation_index": 0,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "request_json": {"messages": []},
        },
    ]
    value["resources"] = [
        {"type": "handler_entry", "script_id": "s", "instance": "alpha", "operation_index": 0},
        {"type": "body_released", "script_id": "s", "instance": "alpha", "operation_index": 0},
        {"type": "body_ready", "script_id": "s", "instance": "alpha", "operation_index": 0},
        {"type": "body_closed", "script_id": "s", "instance": "alpha", "operation_index": 0},
    ]
    with pytest.raises(CHECKER.ObservationError, match="partial order"):
        CHECKER.qualify(_case(scripts=scripts), _record(value), "python")


def test_resource_must_stay_bound_to_its_primary_script_operation_and_instance() -> None:
    scripts = [{"id": "s", "transport": "http", "instance": "alpha", "status": 200}]
    value = _value()
    value["http"] = [
        {
            "script_id": "s",
            "instance": "alpha",
            "operation_index": 0,
            "status": 200,
            "method": "POST",
            "path": "/v1/chat/completions",
            "query": "",
            "request_json": {"messages": []},
        }
    ]
    value["resources"] = [
        {"type": "handler_entry", "script_id": "s", "instance": "other", "operation_index": 0}
    ]
    with pytest.raises(CHECKER.ObservationError, match="not bound"):
        CHECKER._check_resources(_case(scripts=scripts), value)
    value["resources"][0]["instance"] = "alpha"  # type: ignore[index]
    value["resources"][0]["operation_index"] = 1  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="not bound"):
        CHECKER._check_resources(_case(scripts=scripts), value)


def test_cache_marks_and_malformed_tool_warnings_are_actual_witnesses() -> None:
    cache_case = CHECKER.observation.Case(
        "cache",
        "cache",
        {
            "id": "cache",
            "kind": "cache",
            "procedure": {"name": "single", "consume": "exact"},
            "scripts": [],
            "request": {"cache": {"mode": "explicit"}},
            "descriptor": {"cache_mechanism": "explicit"},
            "capabilities": [{"features": ["CACHE_PLACEMENT"]}],
        },
    )
    cache_value = _value()
    cache_value["telemetry"].append(  # type: ignore[union-attr]
        {
            "type": "CachePlanned",
            "operation_index": 0,
            "mechanism": "explicit",
            "count": 2,
            "estimated_tokens": 1,
        }
    )
    cache_value["adapter_wires"] = [{"operation_index": 0, "cache_marks": [0, 1]}]
    CHECKER._check_kind_witnesses(cache_case, cache_value)
    cache_value["adapter_wires"][0]["cache_marks"] = [0]  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="cache marks"):
        CHECKER._check_kind_witnesses(cache_case, cache_value)

    refusal_case = CHECKER.observation.Case(
        "cache-refusal",
        "cache",
        {
            "id": "cache-refusal",
            "kind": "cache",
            "procedure": {"name": "single", "consume": "exact"},
            "scripts": [],
            "request": {"cache": {"mode": "explicit"}},
            "descriptor": {"cache_mechanism": "explicit"},
            "capabilities": [{"features": []}],
        },
    )
    refusal_value = _value()
    refusal_value["telemetry"].append(  # type: ignore[union-attr]
        {
            "type": "ParameterDropped",
            "operation_index": 0,
            "parameter": "cache.mode",
            "reason": "the target's capabilities do not include cache placement",
        }
    )
    refusal_value["adapter_wires"] = [{"operation_index": 0, "cache_marks": []}]
    CHECKER._check_kind_witnesses(refusal_case, refusal_value)
    refusal_value["telemetry"].append(  # type: ignore[union-attr]
        {
            "type": "CachePlanned",
            "operation_index": 0,
            "mechanism": "explicit",
            "count": 0,
            "estimated_tokens": 0,
        }
    )
    with pytest.raises(CHECKER.ObservationError, match="capability refusal"):
        CHECKER._check_kind_witnesses(refusal_case, refusal_value)

    tool_case = CHECKER.observation.Case(
        "tool",
        "tool_stream",
        {
            "id": "tool",
            "kind": "tool_stream",
            "procedure": {"name": "tool_stream", "consume": "exact"},
            "scripts": [
                {
                    "id": "tool-script",
                    "events": [
                        {
                            "type": "tool_call_delta",
                            "index": 0,
                            "call_id": "call",
                            "name": "",
                            "arguments_fragment": "not-json",
                        }
                    ],
                }
            ],
            "request": {"messages": []},
        },
    )
    tool_value = _value()
    tool_value["adapter_wires"] = [  # type: ignore[index]
        {"script_id": "tool-script", "operation_index": 0}
    ]
    tool_value["stream_events"] = [  # type: ignore[index]
        {
            "type": "tool_call_delta",
            "operation_index": 0,
            "index": 0,
            "id": "call",
            "name": "",
            "arguments": "not-json",
        }
    ]
    tool_value["operations"][0]["result"]["warnings"] = [  # type: ignore[index]
        "tool call 0 had unparseable arguments; using an empty argument object"
    ]
    CHECKER._check_kind_witnesses(tool_case, tool_value)
    tool_value["stream_events"].append(  # type: ignore[union-attr]
        {
            "type": "tool_call_delta",
            "operation_index": 0,
            "index": 1,
            "id": None,
            "name": None,
            "arguments": "extra",
        }
    )
    with pytest.raises(CHECKER.ObservationError, match="ordered script subsequence"):
        CHECKER._check_kind_witnesses(tool_case, tool_value)
    tool_value["stream_events"].pop()  # type: ignore[union-attr]
    tool_value["operations"][0]["result"]["warnings"] = []  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="source index order"):
        CHECKER._check_kind_witnesses(tool_case, tool_value)


def test_config_override_and_capture_privacy_need_distinct_actual_effects() -> None:
    config_case = CHECKER.observation.Case(
        "config",
        "config_policy",
        {
            "id": "config",
            "kind": "config_policy",
            "procedure": {"name": "config_consumer", "consume": "exact"},
            "scripts": [],
            "config": {"cache": {"mode": "auto"}, "providers": [{"id": "alpha"}]},
            "action": {"caller_cache": {"mode": "off"}},
        },
    )
    value = _value()
    value["configuration"] = {"provider_ids": ["alpha"]}
    value["adapter_wires"] = [
        {"cache_marks": []},
        {"cache_marks": []},
    ]
    value["telemetry"].append(  # type: ignore[union-attr]
        {
            "type": "ParameterDropped",
            "operation_index": 0,
            "parameter": "cache.mode",
            "reason": "the target's capabilities do not include cache placement",
        }
    )
    CHECKER._check_kind_witnesses(config_case, value)
    value["telemetry"][3]["reason"] = "arbitrary"  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="configured-Auto"):
        CHECKER._check_kind_witnesses(config_case, value)

    capture_case = CHECKER.observation.Case(
        "capture",
        "tool_stream",
        {
            "id": "capture",
            "kind": "tool_stream",
            "procedure": {
                "name": "tool_stream",
                "consume": "exact",
                "capture_modes": ["default", "explicit"],
            },
            "scripts": [],
            "request": {"messages": []},
        },
    )
    captures = _value(operation_count=2)
    for operation in captures["operations"]:  # type: ignore[union-attr]
        operation["result"]["tool_calls"] = [{"id": "call", "name": "", "arguments": {}}]
    captures["operations"][0]["result"]["manifest"] = {  # type: ignore[index]
        "payload": None
    }
    captures["operations"][1]["result"]["manifest"] = {  # type: ignore[index]
        "payload": {"tool_arguments": ["<redacted>"], "repair_texts": []}
    }
    CHECKER._check_kind_witnesses(capture_case, captures)
    captures["operations"][1]["result"]["manifest"]["payload"] = None  # type: ignore[index]
    with pytest.raises(CHECKER.ObservationError, match="distinct default/explicit"):
        CHECKER._check_kind_witnesses(capture_case, captures)


def test_runner_uses_positional_project_and_profile_stamps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(CHECKER, "_run", lambda command, cwd: calls.append((command, cwd)))
    CHECKER.run_observers(
        tmp_path / "inputs.json", tmp_path, source_revision="a" * 40, source_dirty=True
    )
    assert calls[0][0][:4] == [
        "dotnet",
        "build",
        "AnyInfer.RequestPolicy/AnyInfer.RequestPolicy.csproj",
        "--no-restore",
    ]
    assert "--project" not in calls[0][0]
    assert calls[0][0][-2:] == [
        "-p:SourceRevisionId=" + "a" * 40,
        "-p:RequestPolicySourceDirty=true",
    ]
    assert calls[2][0][:6] == [
        "dotnet",
        "run",
        "--no-build",
        "--no-restore",
        "--project",
        "AnyInfer.RequestPolicy",
    ]


def test_schema_rejects_unknown_fields_and_runtime_local_error_type() -> None:
    schema = CHECKER._schema(CHECKER.OBSERVATION_SCHEMA)
    envelope = {
        "profile": "request-policy-v1",
        "runtime": "python",
        "source_revision": "a" * 40,
        "source_dirty": True,
        "corpus_sha256": "b" * 64,
        "observations": [_record(_value())],
        "unexpected": True,
    }
    with pytest.raises(CHECKER.ObservationError, match="closed schema"):
        CHECKER._validate(schema, envelope, "test")


def test_alternate_input_must_still_be_the_exact_frozen_bytes(tmp_path: Path) -> None:
    copied = tmp_path / "inputs.json"
    shutil.copy2(CHECKER.DEFAULT_INPUT, copied)
    CHECKER.read_cases(copied)
    copied.write_bytes(copied.read_bytes() + b"\n")
    with pytest.raises(CHECKER.ObservationError, match="accepted SHA-256"):
        CHECKER.read_cases(copied)
