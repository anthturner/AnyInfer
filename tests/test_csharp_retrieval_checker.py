"""Independent synthetic controls for retrieval-v1 qualification semantics.

These tests use frozen literal cases plus schema-valid observation records.  They do not
invoke either SDK observer or model any routing, chunking, retry, or pricing policy.
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _csharp_observation as observation  # noqa: E402
import check_csharp_retrieval as checker  # noqa: E402
from _csharp_retrieval_inputs import validate_inputs  # noqa: E402


def _cases() -> dict[str, observation.Case]:
    _, cases = observation.read_cases(
        ROOT / "tests" / "fixtures" / "retrieval-v1" / "inputs.json",
        profile="retrieval-v1",
    )
    return {case.identifier: case for case in cases}


def _case(identifier: str = "embedding-scalar-unknown-intent") -> observation.Case:
    return _cases()[identifier]


def _usage() -> dict[str, Any]:
    """Capture the literal ``usage: null`` response without inventing counts."""
    return {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": None,
        "search_units": None,
        "server_tool_uses": {},
    }


def _usage_facet() -> dict[str, Any]:
    """Project only fields the public manifest usage facet actually carries."""
    return {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": None,
        "estimated_fields": {},
        "search_units": None,
    }


def _attempt_facet(target: str, *, outcome: str = "ok", error: Any = None) -> dict[str, Any]:
    return {
        "target": target,
        "attempt_number": 1,
        "outcome": outcome,
        "error": error,
        "first_token_ms": None,
        "total_ms": 1.0,
        "queued_ms": None,
        "retry_reason": None,
        "retry_delay_s": None,
        "paced_s": {},
    }


def _timing() -> dict[str, Any]:
    return {
        "started_at": 0.0,
        "first_token_ms": None,
        "total_ms": 1.0,
        "output_tokens_per_s": None,
        "phases": {},
    }


def _target(selector: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_id": selector["instance"],
        "model": selector["model"],
        "via_alias": None,
    }


def _result(selector: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    dimensions = response["dimensions"] or len(response["vectors"][0])
    return {
        "target": _target(selector),
        "vectors": copy.deepcopy(response["vectors"]),
        "space": {
            "provider_id": selector["instance"],
            "model": response["model"] or selector["model"],
            "model_revision": None,
            "dimensions": dimensions,
            "input_intent_aware": False,
            "normalized": response["normalized"],
            "compatibility_id": None,
        },
        "usage": _usage(),
        "timing": _timing(),
        "warnings": [],
        "raw": None,
    }


def _wire(selector: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    response = copy.deepcopy(step["response"])
    return {
        "selector_id": selector["id"],
        "step_ordinal": step["ordinal"],
        "instance": selector["instance"],
        "target": _target(selector),
        "kind": "embedding",
        "entered_order": 1,
        "terminal_order": 2,
        "request": {
            "model": selector["model"],
            "inputs": copy.deepcopy(selector["slice"]["inputs"]),
            "input_type": None,
            "dimensions": None,
            "timeout_s": 120.0,
            "max_response_bytes": 64 * 1024 * 1024,
            "extra_options": {},
        },
        "outcome": "response",
        "response": response,
        "failure": None,
    }


def _factory(selector: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "factory_entered",
            "order": 1,
            "instance": selector["instance"],
            "model": selector["model"],
            "declared_operations": [selector["operation"]],
        },
        {
            "type": "factory_returned",
            "order": 2,
            "instance": selector["instance"],
            "model": selector["model"],
            "declared_operations": [selector["operation"]],
            "runtime_protocols": [selector["operation"]],
        },
    ]


def _record(case: observation.Case | None = None) -> dict[str, Any]:
    case = _case() if case is None else case
    selector = case.raw["scripts"][0]
    step = selector["steps"][0]
    assert step["action"] == "embedding_response"
    wire = _wire(selector, step)
    target = _target(selector)
    response = step["response"]
    return {
        "id": case.identifier,
        "kind": "embedding",
        "status": "ok",
        "value": {
            "operation": {
                "kind": "embedding",
                "outcome": "ok",
                "result": _result(selector, response),
                "error": None,
                "attempts": [
                    {"target": target, "outcome": "ok", "error": None, "timing": _timing()}
                ],
                "request_relation": "operation",
                "cancellation_relation": "none",
            },
            "factories": _factory(selector),
            "wires": [wire],
            "telemetry": [
                {
                    "type": "RequestStarted",
                    "order": 1,
                    "request_relation": "operation",
                    "targets": [f"{selector['instance']}:{selector['model']}"],
                    "metadata": {},
                    "operation": "embedding",
                },
                {
                    "type": "TargetResolved",
                    "order": 2,
                    "request_relation": "operation",
                    "target": target,
                },
                {
                    "type": "AttemptStarted",
                    "order": 3,
                    "request_relation": "operation",
                    "target": target,
                    "attempt": 1,
                },
                {
                    "type": "AttemptCompleted",
                    "order": 4,
                    "request_relation": "operation",
                    "target": target,
                    "usage": _usage(),
                    "timing": _timing(),
                    "finish_reason": "stop",
                },
                {
                    "type": "RequestCompleted",
                    "order": 5,
                    "request_relation": "operation",
                    "target": target,
                    "usage": _usage(),
                    "timing": _timing(),
                    "repair_attempts": 0,
                },
            ],
            "ledger": None,
            "manifest": None,
            "resources": [],
            "batch_failures": None,
        },
    }


def _rerank_wire(
    selector: dict[str, Any], step: dict[str, Any], *, entered: int, terminal: int
) -> dict[str, Any]:
    return {
        "selector_id": selector["id"],
        "step_ordinal": step["ordinal"],
        "instance": selector["instance"],
        "target": _target(selector),
        "kind": "rerank",
        "entered_order": entered,
        "terminal_order": terminal,
        "request": {
            "model": selector["model"],
            "query": "q",
            "documents": copy.deepcopy(selector["slice"]["documents"]),
            "top_n": 2,
            "timeout_s": 120.0,
            "max_response_bytes": 8 * 1024 * 1024,
            "extra_options": {},
        },
        "outcome": "response",
        "response": copy.deepcopy(step["response"]),
        "failure": None,
    }


def _rerank_record() -> tuple[observation.Case, dict[str, Any]]:
    """A complete literal split-rerank projection with no derived scoring policy."""
    case = _case("rerank-partial-returntext-topn")
    left, right = case.raw["scripts"]
    left_step, right_step = left["steps"][0], right["steps"][0]
    target = _target(left)
    wires = [
        _rerank_wire(left, left_step, entered=1, terminal=2),
        _rerank_wire(right, right_step, entered=3, terminal=4),
    ]
    items = [
        {"index": 1, "document_id": "b", "score": 0.9, "text": "B"},
        {"index": 2, "document_id": "c", "score": 0.8, "text": "C"},
    ]
    record = {
        "id": case.identifier,
        "kind": "rerank",
        "status": "ok",
        "value": {
            "operation": {
                "kind": "rerank",
                "outcome": "ok",
                "result": {
                    "target": target,
                    "items": items,
                    "usage": _usage(),
                    "timing": _timing(),
                    "warnings": [],
                    "raw": None,
                },
                "error": None,
                "attempts": [
                    {"target": target, "outcome": "ok", "error": None, "timing": _timing()},
                    {"target": target, "outcome": "ok", "error": None, "timing": _timing()},
                ],
                "request_relation": "operation",
                "cancellation_relation": "none",
            },
            "factories": _factory(left),
            "wires": wires,
            "telemetry": [
                {
                    "type": "RequestStarted",
                    "order": 1,
                    "request_relation": "operation",
                    "targets": ["partial:model"],
                    "metadata": {},
                    "operation": "rerank",
                },
                {
                    "type": "TargetResolved",
                    "order": 2,
                    "request_relation": "operation",
                    "target": target,
                },
                {
                    "type": "AttemptStarted",
                    "order": 3,
                    "request_relation": "operation",
                    "target": target,
                    "attempt": 1,
                },
                {
                    "type": "AttemptCompleted",
                    "order": 4,
                    "request_relation": "operation",
                    "target": target,
                    "usage": _usage(),
                    "timing": _timing(),
                    "finish_reason": "stop",
                },
                {
                    "type": "AttemptStarted",
                    "order": 5,
                    "request_relation": "operation",
                    "target": target,
                    "attempt": 1,
                },
                {
                    "type": "AttemptCompleted",
                    "order": 6,
                    "request_relation": "operation",
                    "target": target,
                    "usage": _usage(),
                    "timing": _timing(),
                    "finish_reason": "stop",
                },
                {
                    "type": "RequestCompleted",
                    "order": 7,
                    "request_relation": "operation",
                    "target": target,
                    "usage": _usage(),
                    "timing": _timing(),
                    "repair_attempts": 0,
                },
            ],
            "ledger": None,
            "manifest": None,
            "resources": [],
            "batch_failures": None,
        },
    }
    return case, record


def _spend_refusal(case: observation.Case) -> dict[str, Any]:
    totals = {
        "cost": "0",
        "currency": "USD",
        "requests": 0,
        "unknown_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
    }
    return {
        "id": case.identifier,
        "kind": "rerank",
        "status": "ok",
        "value": {
            "operation": {
                "kind": "rerank",
                "outcome": "error",
                "result": None,
                "error": {
                    "runtime_type": "SpendLimitError",
                    "message": "unknown cost refused",
                    "provider": None,
                    "phase": None,
                    "retryable": False,
                    "http_status": None,
                    "retry_after_s": None,
                    "detail": None,
                    "hint": None,
                    "limit_usd": "1.0",
                    "spent_usd": None,
                    "estimated_usd": None,
                },
                "attempts": [],
                "request_relation": "operation",
                "cancellation_relation": "none",
            },
            "factories": [],
            "wires": [],
            "telemetry": [],
            "ledger": [
                {"label": "before_call", "reserved": "0", "totals": totals},
                {"label": "after_operation", "reserved": "0", "totals": totals},
                {"label": "after_client_close", "reserved": "0", "totals": totals},
            ],
            "manifest": None,
            "resources": [],
            "batch_failures": None,
        },
    }


def _cancelled_ledger_record() -> tuple[observation.Case, dict[str, Any]]:
    """Build the held-caller cancellation shape without a terminal telemetry event."""
    case = _admitted_case("embedding-priced-caller-cancel")
    selector = case.raw["scripts"][0]
    barrier = selector["steps"][0]
    empty = {
        "cost": "0",
        "currency": "USD",
        "requests": 0,
        "unknown_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
    }
    record = _record()
    record["id"] = case.identifier
    record["value"]["operation"] = {
        "kind": "embedding",
        "outcome": "cancelled",
        "result": None,
        "error": None,
        "attempts": [],
        "request_relation": "operation",
        "cancellation_relation": "caller_cancelled",
    }
    record["value"]["factories"] = _factory(selector)
    record["value"]["wires"] = [
        {
            **_wire(
                selector,
                {"ordinal": barrier["ordinal"], "response": barrier["continuation"]["response"]},
            ),
            "outcome": "cancelled",
            "response": None,
        }
    ]
    record["value"]["telemetry"] = [
        {
            "type": "RequestStarted",
            "order": 1,
            "request_relation": "operation",
            "targets": ["held:model"],
            "metadata": {},
            "operation": "embedding",
        }
    ]
    record["value"]["resources"] = [
        {
            "type": "barrier_reached",
            "order": 1,
            "selector_id": selector["id"],
            "step_ordinal": 1,
            "instance": "held",
        },
        {
            "type": "caller_cancel_requested",
            "order": 2,
            "selector_id": selector["id"],
            "step_ordinal": 1,
            "instance": "held",
        },
        {
            "type": "operation_finally",
            "order": 3,
            "selector_id": selector["id"],
            "step_ordinal": 1,
            "instance": "held",
        },
    ]
    record["value"]["ledger"] = [
        {"label": "before_call", "reserved": "0", "totals": empty},
        {"label": "while_provider_held", "reserved": "0", "totals": empty},
        {"label": "after_operation", "reserved": "0", "totals": empty},
        {"label": "after_client_close", "reserved": "0", "totals": empty},
    ]
    return case, record


def _provider_error(
    *, detail: str = "script failure", retryable: bool = True, http_status: int = 503
) -> dict[str, Any]:
    return {
        "runtime_type": "ProviderError",
        "message": detail,
        "provider": "provider",
        "phase": "retrieve",
        "retryable": retryable,
        "http_status": http_status,
        "retry_after_s": None,
        "detail": detail,
        "hint": None,
    }


def _provider_snapshot(
    *, detail: str = "script failure", retryable: bool = True, http_status: int = 503
) -> dict[str, Any]:
    return {
        "runtime_type": "ProviderError",
        "provider": "provider",
        "phase": "retrieve",
        "retryable": retryable,
        "http_status": http_status,
        "detail": detail,
    }


def _retry_record(
    case: observation.Case | None = None,
) -> tuple[observation.Case, dict[str, Any]]:
    """Use two literal same-target steps without inventing a retry policy."""
    case = _case("embedding-retry-success") if case is None else case
    selector = case.raw["scripts"][0]
    *failures, succeeded = selector["steps"]
    target = _target(selector)
    failed_wires = [
        {
            "selector_id": selector["id"],
            "step_ordinal": failed["ordinal"],
            "instance": selector["instance"],
            "target": target,
            "kind": "embedding",
            "entered_order": index * 2 + 1,
            "terminal_order": index * 2 + 2,
            "request": {
                "model": selector["model"],
                "inputs": copy.deepcopy(selector["slice"]["inputs"]),
                "input_type": None,
                "dimensions": None,
                "timeout_s": 120.0,
                "max_response_bytes": 64 * 1024 * 1024,
                "extra_options": {},
            },
            "outcome": "provider_failure",
            "response": None,
            "failure": _provider_error(detail=failed["failure"]["detail"]),
        }
        for index, failed in enumerate(failures)
    ]
    succeeded_wire = _wire(selector, succeeded)
    succeeded_wire["entered_order"] = len(failures) * 2 + 1
    succeeded_wire["terminal_order"] = len(failures) * 2 + 2
    record = _record()
    record["id"] = case.identifier
    record["value"]["factories"] = _factory(selector)
    record["value"]["wires"] = [*failed_wires, succeeded_wire]
    record["value"]["operation"]["result"] = _result(selector, succeeded["response"])
    record["value"]["operation"]["attempts"] = [
        {
            "target": target,
            "outcome": "retried",
            "error": _provider_snapshot(detail=failed["failure"]["detail"]),
            "timing": _timing(),
        }
        for failed in failures
    ] + [{"target": target, "outcome": "ok", "error": None, "timing": _timing()}]
    record["value"]["telemetry"] = [
        {
            "type": "RequestStarted",
            "order": 1,
            "request_relation": "operation",
            "targets": [f"{selector['instance']}:{selector['model']}"],
            "metadata": {},
            "operation": "embedding",
        },
        {"type": "TargetResolved", "order": 2, "request_relation": "operation", "target": target},
        *[
            event
            for index, failed in enumerate(failures, start=1)
            for event in (
                {
                    "type": "AttemptStarted",
                    "order": index * 2 + 1,
                    "request_relation": "operation",
                    "target": target,
                    "attempt": index,
                },
                {
                    "type": "RetryScheduled",
                    "order": index * 2 + 2,
                    "request_relation": "operation",
                    "target": target,
                    "attempt": index,
                    "delay_s": 0.0,
                    "error": _provider_snapshot(detail=failed["failure"]["detail"]),
                },
            )
        ],
        {
            "type": "AttemptStarted",
            "order": len(failures) * 2 + 3,
            "request_relation": "operation",
            "target": target,
            "attempt": len(failures) + 1,
        },
        {
            "type": "AttemptCompleted",
            "order": len(failures) * 2 + 4,
            "request_relation": "operation",
            "target": target,
            "usage": _usage(),
            "timing": _timing(),
            "finish_reason": "stop",
        },
        {
            "type": "RequestCompleted",
            "order": len(failures) * 2 + 5,
            "request_relation": "operation",
            "target": target,
            "usage": _usage(),
            "timing": _timing(),
            "repair_attempts": 0,
        },
    ]
    return case, record


def _input_schema() -> dict[str, Any]:
    schema = observation.read_json_bytes(
        ROOT / "tests" / "fixtures" / "retrieval-v1" / "schema.json"
    )
    assert isinstance(schema, dict)
    return schema


def _distinct_failure_retry_case() -> observation.Case:
    """Construct a schema-validated unit-only selector with two distinct retries."""
    raw = copy.deepcopy(_case("embedding-retry-success").raw)
    raw["id"] = "synthetic-distinct-same-target-retry"
    raw["client"]["default_route"]["retry"]["max_attempts"] = 3
    selector = raw["scripts"][0]
    first, success = selector["steps"]
    second = copy.deepcopy(first)
    second["id"] = "retry-fail-distinct"
    second["ordinal"] = 2
    second["failure"]["detail"] = "second script failure"
    success["ordinal"] = 3
    selector["steps"] = [first, second, success]
    source = {"profile": "retrieval-v1", "cases": [raw]}
    schema = _input_schema()
    Draft202012Validator(schema).validate(source)
    validate_inputs(source, schema)
    return observation.Case(raw["id"], raw["kind"], raw)


def _case_from_raw(raw: dict[str, Any]) -> observation.Case:
    """Create a schema-checked synthetic case without changing the frozen corpus."""
    source = {"profile": "retrieval-v1", "cases": [raw]}
    schema = _input_schema()
    Draft202012Validator(schema).validate(source)
    validate_inputs(source, schema)
    return observation.Case(raw["id"], raw["kind"], raw)


def _admitted_case(identifier: str) -> observation.Case:
    """Re-admit one frozen literal case before constructing a synthetic observation."""
    return _case_from_raw(copy.deepcopy(_case(identifier).raw))


def _secret_projection_case() -> observation.Case:
    """One source-valid literal case whose response, options, and failure need redaction."""
    raw = copy.deepcopy(_case("embedding-retry-success").raw)
    raw["id"] = "synthetic-redacted-retrieval-projections"
    raw["client"]["registered_secrets"] = ["fixture-secret"]
    raw["request"]["provider_options"] = {"retry": {"authorization": "Bearer fixture-secret"}}
    selector = raw["scripts"][0]
    selector["steps"][0]["failure"]["detail"] = "fixture-secret failed"
    selector["steps"][1]["response"]["raw"] = {"token": "fixture-secret"}
    return _case_from_raw(raw)


def _redacted_secret_record() -> tuple[observation.Case, dict[str, Any]]:
    """Capture the public redacted projections of three literal secret-bearing surfaces."""
    case = _secret_projection_case()
    _, record = _retry_record(case)
    value = record["value"]
    for wire in value["wires"]:
        wire["request"]["extra_options"] = {"authorization": "Bearer [redacted]"}
    value["wires"][0]["failure"]["detail"] = "[redacted] failed"
    value["wires"][0]["failure"]["message"] = "[redacted] failed"
    value["operation"]["attempts"][0]["error"]["detail"] = "[redacted] failed"
    retry = next(event for event in value["telemetry"] if event["type"] == "RetryScheduled")
    retry["error"]["detail"] = "[redacted] failed"
    value["wires"][-1]["response"]["raw"] = {"token": "[redacted]"}
    value["operation"]["result"]["raw"] = {"token": "[redacted]"}
    return case, record


def _schema_valid(record: dict[str, Any]) -> None:
    schema = observation.read_json_bytes(
        ROOT / "tests" / "fixtures" / "retrieval-v1" / "observations.schema.json"
    )
    assert isinstance(schema, dict)
    Draft202012Validator(schema).validate(
        {
            "profile": "retrieval-v1",
            "runtime": "python",
            "source_revision": "a" * 40,
            "source_dirty": True,
            "corpus_sha256": "b" * 64,
            "observations": [record],
        }
    )


def _qualifies(case: observation.Case, record: dict[str, Any], runtime: str = "python") -> None:
    _schema_valid(record)
    checker.qualify_observation(case, record, runtime=runtime)


def _rejects(case: observation.Case, record: dict[str, Any], runtime: str = "python") -> None:
    _schema_valid(record)
    with pytest.raises(observation.ObservationError):
        checker.qualify_observation(case, record, runtime=runtime)


def test_literal_wire_consumption_selector_ordinal_and_response_are_exact() -> None:
    case = _admitted_case("embedding-scalar-unknown-intent")
    baseline = _record(case)
    _qualifies(case, baseline)

    missing = copy.deepcopy(baseline)
    missing["value"]["wires"] = []
    _rejects(case, missing)

    duplicate = copy.deepcopy(baseline)
    duplicate["value"]["wires"].append(copy.deepcopy(duplicate["value"]["wires"][0]))
    _rejects(case, duplicate)

    wrong_ordinal = copy.deepcopy(baseline)
    wrong_ordinal["value"]["wires"][0]["step_ordinal"] = 2
    _rejects(case, wrong_ordinal)

    wrong_response = copy.deepcopy(baseline)
    wrong_response["value"]["wires"][0]["response"]["vectors"][0][0] = 0.3
    _rejects(case, wrong_response)


def test_request_relation_factory_protocol_and_zero_wire_refusal_are_qualified() -> None:
    case = _case()
    baseline = _record(case)
    _qualifies(case, baseline)

    wrong_relation = copy.deepcopy(baseline)
    wrong_relation["value"]["operation"]["request_relation"] = "other"
    with pytest.raises(ValidationError):
        _schema_valid(wrong_relation)

    wrong_factory = copy.deepcopy(baseline)
    wrong_factory["value"]["factories"][1]["runtime_protocols"] = ["rerank"]
    _rejects(case, wrong_factory)

    unsupported = _case("embedding-requested-unsupported-operation")
    descriptor = unsupported.raw["descriptors"][0]
    error = {
        "runtime_type": "ConfigError",
        "message": "declared operation unsupported",
        "provider": None,
        "phase": "configure",
        "retryable": False,
        "http_status": None,
        "retry_after_s": None,
        "detail": None,
        "hint": None,
    }
    zero_wire = {
        "id": unsupported.identifier,
        "kind": "embedding",
        "status": "ok",
        "value": {
            "operation": {
                "kind": "embedding",
                "outcome": "error",
                "result": None,
                "error": error,
                "attempts": [],
                "request_relation": "operation",
                "cancellation_relation": "none",
            },
            "factories": [
                {
                    "type": "factory_entered",
                    "order": 1,
                    "instance": descriptor["instance"],
                    "model": descriptor["model"],
                    "declared_operations": descriptor["operations"],
                },
                {
                    "type": "factory_returned",
                    "order": 2,
                    "instance": descriptor["instance"],
                    "model": descriptor["model"],
                    "declared_operations": descriptor["operations"],
                    "runtime_protocols": descriptor["runtime_protocols"],
                },
            ],
            "wires": [],
            "telemetry": [],
            "ledger": None,
            "manifest": None,
            "resources": [],
            "batch_failures": None,
        },
    }
    _qualifies(unsupported, zero_wire)

    invented_terminal = copy.deepcopy(zero_wire)
    invented_terminal["value"]["telemetry"] = [
        {
            "type": "RequestFailed",
            "order": 1,
            "request_relation": "operation",
            "error": {
                key: error[key]
                for key in (
                    "runtime_type",
                    "provider",
                    "phase",
                    "retryable",
                    "http_status",
                    "detail",
                )
            },
        }
    ]
    _rejects(unsupported, invented_terminal)

    wire_added = copy.deepcopy(zero_wire)
    wire_added["value"]["wires"] = [copy.deepcopy(_record()["value"]["wires"][0])]
    _rejects(unsupported, wire_added)


def test_provider_failure_detail_uses_the_public_511_scalar_plus_ellipsis_bound() -> None:
    raw = copy.deepcopy(_case("embedding-retry-success").raw)
    raw["id"] = "synthetic-bounded-provider-detail"
    raw["scripts"][0]["steps"][0]["failure"]["detail"] = "x" * 513
    bounded_case = _case_from_raw(raw)
    _, bounded = _retry_record(bounded_case)
    expected = "x" * 511 + "…"
    for error in (
        bounded["value"]["wires"][0]["failure"],
        bounded["value"]["operation"]["attempts"][0]["error"],
        next(
            event["error"]
            for event in bounded["value"]["telemetry"]
            if event["type"] == "RetryScheduled"
        ),
    ):
        error["detail"] = expected
        if "message" in error:
            error["message"] = expected
    _qualifies(bounded_case, bounded)

    unbounded = copy.deepcopy(bounded)
    unbounded["value"]["operation"]["attempts"][0]["error"]["detail"] = "x" * 512
    _rejects(bounded_case, unbounded)


def test_embedding_wire_request_projects_literal_defaults_and_explicit_fields() -> None:
    case = _case("embedding-provider-phases")
    baseline = _record(case)
    request = baseline["value"]["wires"][0]["request"]
    request["timeout_s"] = case.raw["request"]["timeout_s"]
    request["max_response_bytes"] = case.raw["request"]["max_response_bytes"]
    _qualifies(case, baseline)

    for field, value in (
        ("input_type", "query"),
        ("dimensions", 7),
        ("timeout_s", 1.0),
        ("max_response_bytes", 64 * 1024 * 1024),
        ("extra_options", {"option": "wrong"}),
    ):
        wrong = copy.deepcopy(baseline)
        wrong["value"]["wires"][0]["request"][field] = value
        _rejects(case, wrong)


def test_rerank_wire_request_projects_literal_query_documents_and_limits() -> None:
    case, baseline = _rerank_record()
    _qualifies(case, baseline)

    mutations = (
        ("query", "other"),
        ("documents", [{"index": 0, "text": "wrong"}]),
        ("top_n", 3),
        ("timeout_s", 1.0),
        ("max_response_bytes", 1024 * 1024),
        ("extra_options", {"unexpected": "value"}),
    )
    accepted: list[str] = []
    for field, value in mutations:
        wrong = copy.deepcopy(baseline)
        wrong["value"]["wires"][0]["request"][field] = value
        assert (
            wrong["value"]["wires"][0]["request"][field]
            != baseline["value"]["wires"][0]["request"][field]
        )
        _schema_valid(wrong)
        try:
            checker.qualify_observation(case, wrong, runtime="python")
        except observation.ObservationError:
            continue
        accepted.append(field)
    assert not accepted, f"checker accepted rerank request mutations: {accepted}"

    wrong_index = copy.deepcopy(baseline)
    wrong_index["value"]["wires"][1]["request"]["documents"][0]["index"] = 0
    _rejects(case, wrong_index)


def test_request_started_factory_and_wire_causality_are_not_optional() -> None:
    case = _case()
    baseline = _record(case)
    _qualifies(case, baseline)

    missing_started = copy.deepcopy(baseline)
    missing_started["value"]["telemetry"] = missing_started["value"]["telemetry"][1:]
    _rejects(case, missing_started)

    wrong_operation = copy.deepcopy(baseline)
    wrong_operation["value"]["telemetry"][0]["operation"] = "rerank"
    _rejects(case, wrong_operation)

    wrong_targets = copy.deepcopy(baseline)
    wrong_targets["value"]["telemetry"][0]["targets"] = ["other:model"]
    _rejects(case, wrong_targets)

    wrong_metadata = copy.deepcopy(baseline)
    wrong_metadata["value"]["telemetry"][0]["metadata"] = {"changed": "true"}
    _rejects(case, wrong_metadata)

    duplicate_started = copy.deepcopy(baseline)
    duplicate = copy.deepcopy(duplicate_started["value"]["telemetry"][0])
    duplicate["order"] = 2
    for event in duplicate_started["value"]["telemetry"][1:]:
        event["order"] += 1
    duplicate_started["value"]["telemetry"].insert(1, duplicate)
    _rejects(case, duplicate_started)

    returned_before_entered = copy.deepcopy(baseline)
    returned_before_entered["value"]["factories"][0]["type"] = "factory_returned"
    returned_before_entered["value"]["factories"][0]["runtime_protocols"] = ["embedding"]
    returned_before_entered["value"]["factories"][1]["type"] = "factory_entered"
    del returned_before_entered["value"]["factories"][1]["runtime_protocols"]
    _rejects(case, returned_before_entered)

    reversed_wire = copy.deepcopy(baseline)
    reversed_wire["value"]["wires"][0]["entered_order"] = 3
    reversed_wire["value"]["wires"][0]["terminal_order"] = 2
    _rejects(case, reversed_wire)


def test_completion_and_manifest_join_canonical_result_attempt_and_route_facts() -> None:
    case = _case()
    baseline = _record(case)
    _qualifies(case, baseline)

    completion_usage = copy.deepcopy(baseline)
    completion_usage["value"]["telemetry"][-1]["usage"]["total_tokens"] = 7
    _rejects(case, completion_usage)

    completion_timing = copy.deepcopy(baseline)
    completion_timing["value"]["telemetry"][-1]["timing"]["total_ms"] = 2.0
    _rejects(case, completion_timing)

    manifest = copy.deepcopy(baseline)
    manifest["value"]["manifest"] = {
        "request_relation": "operation",
        "format": "1",
        "complete": True,
        "operation": "embedding",
        "route": {
            "requested": ["alpha:model"],
            "resolved": "alpha:model",
            "considered": [{"target": "alpha:model", "outcome": "ok", "reason": ""}],
        },
        "attempts": [_attempt_facet("alpha:model")],
        "usage": _usage_facet(),
        "timing": {
            "first_token_ms": None,
            "total_ms": 1.0,
            "output_tokens_per_s": None,
            "phases": {},
        },
        "notes": [],
        "embedding_space": baseline["value"]["operation"]["result"]["space"],
        "payloads": None,
    }
    _qualifies(case, manifest)

    mutations = (
        ("route.resolved", "other:model"),
        ("attempts[0].target", "other:model"),
        ("attempts[0].outcome", "failed"),
        ("attempts[0].total_ms", 2.0),
        ("embedding_space.dimensions", 99),
        ("timing.total_ms", 2.0),
        ("notes", ["invented"]),
    )
    accepted: list[str] = []
    for path, value in mutations:
        wrong = copy.deepcopy(manifest)
        if path == "route.resolved":
            wrong["value"]["manifest"]["route"]["resolved"] = value
        elif path.startswith("attempts[0]"):
            wrong["value"]["manifest"]["attempts"][0][path.rsplit(".", 1)[1]] = value
        elif path.startswith("embedding_space"):
            wrong["value"]["manifest"]["embedding_space"]["dimensions"] = value
        elif path.startswith("timing."):
            wrong["value"]["manifest"]["timing"][path.rsplit(".", 1)[1]] = value
        elif path == "notes":
            wrong["value"]["manifest"]["notes"] = value
        else:
            wrong["value"]["manifest"][path.rsplit(".", 1)[1]] = value
        _schema_valid(wrong)
        try:
            checker.qualify_observation(case, wrong, runtime="python")
        except observation.ObservationError:
            continue
        accepted.append(path)
    assert not accepted, f"checker accepted manifest mutations: {accepted}"


def test_telemetry_manifest_ledger_and_resource_joins_reject_one_cause_mutations() -> None:
    case = _case()
    baseline = _record(case)
    _qualifies(case, baseline)

    wrong_target = copy.deepcopy(baseline)
    wrong_target["value"]["telemetry"][1]["target"]["model"] = "other"
    _rejects(case, wrong_target)

    manifest = copy.deepcopy(baseline)
    manifest["value"]["manifest"] = {
        "request_relation": "operation",
        "format": "1",
        "complete": True,
        "operation": "embedding",
        "route": {
            "requested": ["alpha:model"],
            "resolved": "alpha:model",
            "considered": [{"target": "alpha:model", "outcome": "ok", "reason": ""}],
        },
        "attempts": [_attempt_facet("alpha:model")],
        "usage": _usage_facet(),
        "timing": {
            "first_token_ms": None,
            "total_ms": 1.0,
            "output_tokens_per_s": None,
            "phases": {},
        },
        "notes": [],
        "embedding_space": baseline["value"]["operation"]["result"]["space"],
        "payloads": None,
    }
    _qualifies(case, manifest)
    wrong_manifest = copy.deepcopy(manifest)
    wrong_manifest["value"]["manifest"]["route"]["resolved"] = "other:model"
    _rejects(case, wrong_manifest)

    cancel_case = _case("embedding-priced-caller-cancel")
    selector = cancel_case.raw["scripts"][0]
    barrier = selector["steps"][0]
    cancelled = _record()
    cancelled["id"] = cancel_case.identifier
    cancelled["value"]["operation"] = {
        "kind": "embedding",
        "outcome": "cancelled",
        "result": None,
        "error": None,
        "attempts": [],
        "request_relation": "operation",
        "cancellation_relation": "caller_cancelled",
    }
    cancelled["value"]["factories"] = _factory(selector)
    cancelled["value"]["wires"] = [
        {
            **_wire(
                selector,
                {"ordinal": barrier["ordinal"], "response": barrier["continuation"]["response"]},
            ),
            "outcome": "cancelled",
            "response": None,
        }
    ]
    cancelled["value"]["telemetry"] = [
        {
            "type": "RequestStarted",
            "order": 1,
            "request_relation": "operation",
            "targets": ["held:model"],
            "metadata": {},
            "operation": "embedding",
        }
    ]
    cancelled["value"]["resources"] = [
        {
            "type": "barrier_reached",
            "order": 1,
            "selector_id": selector["id"],
            "step_ordinal": 1,
            "instance": "held",
        },
        {
            "type": "caller_cancel_requested",
            "order": 2,
            "selector_id": selector["id"],
            "step_ordinal": 1,
            "instance": "held",
        },
        {
            "type": "operation_finally",
            "order": 3,
            "selector_id": selector["id"],
            "step_ordinal": 1,
            "instance": "held",
        },
    ]
    totals = {
        "cost": "0",
        "currency": "USD",
        "requests": 0,
        "unknown_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
    }
    cancelled["value"]["ledger"] = [
        {"label": "before_call", "reserved": "0", "totals": totals},
        {"label": "while_provider_held", "reserved": "0", "totals": totals},
        {"label": "after_operation", "reserved": "0", "totals": totals},
        {"label": "after_client_close", "reserved": "0", "totals": totals},
    ]
    _qualifies(cancel_case, cancelled)
    no_finally = copy.deepcopy(cancelled)
    no_finally["value"]["resources"] = no_finally["value"]["resources"][:-1]
    _rejects(cancel_case, no_finally)

    wrong_resource_instance = copy.deepcopy(cancelled)
    wrong_resource_instance["value"]["resources"][1]["instance"] = "other"
    _rejects(cancel_case, wrong_resource_instance)

    reversed_release = copy.deepcopy(cancelled)
    reversed_release["value"]["resources"][2]["order"] = 1
    _rejects(cancel_case, reversed_release)

    reordered_ledger = copy.deepcopy(cancelled)
    reordered_ledger["value"]["ledger"][0], reordered_ledger["value"]["ledger"][1] = (
        reordered_ledger["value"]["ledger"][1],
        reordered_ledger["value"]["ledger"][0],
    )
    _rejects(cancel_case, reordered_ledger)

    missing_release = copy.deepcopy(cancelled)
    missing_release["value"]["ledger"] = missing_release["value"]["ledger"][:-2]
    _rejects(cancel_case, missing_release)

    close_case = _case("embedding-normal-close")
    close = _record(close_case)
    close["value"]["resources"] = [
        {
            "type": "normal_client_close_started",
            "order": 1,
            "selector_id": None,
            "step_ordinal": None,
            "instance": None,
        },
        {
            "type": "normal_client_close_completed",
            "order": 2,
            "selector_id": None,
            "step_ordinal": None,
            "instance": None,
        },
    ]
    _qualifies(close_case, close)
    close["value"]["resources"].pop()
    _rejects(close_case, close)

    wrong_close_instance = _record(close_case)
    wrong_close_instance["value"]["resources"] = [
        {
            "type": "normal_client_close_started",
            "order": 1,
            "selector_id": None,
            "step_ordinal": None,
            "instance": "close",
        },
        {
            "type": "normal_client_close_completed",
            "order": 2,
            "selector_id": None,
            "step_ordinal": None,
            "instance": "close",
        },
    ]
    _rejects(close_case, wrong_close_instance)


def test_registered_secret_is_redacted_on_literal_raw_options_and_error_surfaces(
    tmp_path: Path,
) -> None:
    case, baseline = _redacted_secret_record()
    _qualifies(case, baseline)

    raw_exposed = copy.deepcopy(baseline)
    raw_exposed["value"]["operation"]["result"]["raw"] = {"token": "fixture-secret"}
    _rejects(case, raw_exposed)

    options_exposed = copy.deepcopy(baseline)
    options_exposed["value"]["wires"][0]["request"]["extra_options"] = {
        "authorization": "Bearer fixture-secret"
    }
    _rejects(case, options_exposed)

    failure_exposed = copy.deepcopy(baseline)
    failure_exposed["value"]["wires"][0]["failure"]["detail"] = "fixture-secret failed"
    _rejects(case, failure_exposed)

    for leaked in ("fixture-secret", "Zml4dHVyZS1zZWNyZXQ="):
        envelope = {
            "profile": "retrieval-v1",
            "runtime": "python",
            "source_revision": "a" * 40,
            "source_dirty": True,
            "corpus_sha256": "b" * 64,
            "observations": [baseline],
            "schema_invalid_" + leaked: True,
        }
        path = tmp_path / f"secret-{len(leaked)}.json"
        path.write_text(json.dumps(envelope), encoding="utf-8")
        with pytest.raises(observation.ObservationError) as caught:
            checker.read_observations(path, cases=[case], runtime="python", digest="b" * 64)
        message = str(caught.value)
        assert "fixture-secret" not in message
        assert "Zml4dHVyZS1zZWNyZXQ=" not in message


def test_route_position_and_chunk_attempt_ordinals_restart_at_one() -> None:
    """Each source retry/route-or-chunk invocation owns its own local attempt numbering."""
    repeated_case = _case("embedding-repeated-route-position")
    _, repeated = _retry_record(repeated_case)
    repeated["value"]["telemetry"][4]["attempt"] = 1
    _qualifies(repeated_case, repeated)

    chunk_case, chunked = _rerank_record()
    _qualifies(chunk_case, chunked)


def test_post_start_configuration_errors_keep_public_progress_without_request_failed() -> None:
    """Malformed provider output is a local configuration failure, not a script error."""
    case = _case("embedding-wrong-count")
    selector = case.raw["scripts"][0]
    step = selector["steps"][0]
    target = _target(selector)
    record = {
        "id": case.identifier,
        "kind": "embedding",
        "status": "ok",
        "value": {
            "operation": {
                "kind": "embedding",
                "outcome": "error",
                "result": None,
                "error": {
                    "runtime_type": "ConfigError",
                    "message": "embedding response has the wrong vector count",
                    "provider": None,
                    "phase": "configure",
                    "retryable": False,
                    "http_status": None,
                    "retry_after_s": None,
                    "detail": None,
                    "hint": None,
                },
                "attempts": [],
                "request_relation": "operation",
                "cancellation_relation": "none",
            },
            "factories": _factory(selector),
            "wires": [_wire(selector, step)],
            "telemetry": [
                {
                    "type": "RequestStarted",
                    "order": 1,
                    "request_relation": "operation",
                    "targets": [f"{selector['instance']}:{selector['model']}"],
                    "metadata": {},
                    "operation": "embedding",
                },
                {
                    "type": "TargetResolved",
                    "order": 2,
                    "request_relation": "operation",
                    "target": target,
                },
                {
                    "type": "AttemptStarted",
                    "order": 3,
                    "request_relation": "operation",
                    "target": target,
                    "attempt": 1,
                },
                {
                    "type": "AttemptCompleted",
                    "order": 4,
                    "request_relation": "operation",
                    "target": target,
                    "usage": _usage(),
                    "timing": _timing(),
                    "finish_reason": "stop",
                },
            ],
            "ledger": None,
            "manifest": None,
            "resources": [],
            "batch_failures": None,
        },
    }
    _schema_valid(record)
    _qualifies(case, record)


def test_same_target_retry_keeps_each_literal_failure_joined_to_its_public_attempt() -> None:
    case, baseline = _retry_record(_distinct_failure_retry_case())
    _qualifies(case, baseline)

    wrong_wire_error = copy.deepcopy(baseline)
    wrong_wire_error["value"]["wires"][0]["failure"]["detail"] = "other"
    _rejects(case, wrong_wire_error)

    wrong_retry_error = copy.deepcopy(baseline)
    wrong_retry_error["value"]["telemetry"][3]["error"]["http_status"] = 500
    _rejects(case, wrong_retry_error)

    wrong_attempt_error = copy.deepcopy(baseline)
    wrong_attempt_error["value"]["operation"]["attempts"][0]["error"]["provider"] = "other"
    _rejects(case, wrong_attempt_error)

    swapped_occurrences = copy.deepcopy(baseline)
    first = swapped_occurrences["value"]["operation"]["attempts"][0]["error"]
    second = swapped_occurrences["value"]["operation"]["attempts"][1]["error"]
    first["detail"], second["detail"] = second["detail"], first["detail"]
    _rejects(case, swapped_occurrences)


def test_one_literal_retry_failure_can_retain_all_source_emitted_public_views() -> None:
    """A retry snapshot legitimately appears in canonical, event, and manifest surfaces."""
    case, baseline = _retry_record()
    target = "retry:model"
    failure = _provider_snapshot()
    baseline["value"]["manifest"] = {
        "request_relation": "operation",
        "format": "1",
        "complete": True,
        "operation": "embedding",
        "route": {
            "requested": [target],
            "resolved": target,
            "considered": [{"target": target, "outcome": "ok", "reason": ""}],
        },
        "attempts": [
            {
                **_attempt_facet(target, outcome="retried", error=failure),
                "retry_reason": "script failure",
                "retry_delay_s": 0.0,
            },
            _attempt_facet(target),
        ],
        "usage": _usage_facet(),
        "timing": {
            "first_token_ms": None,
            "total_ms": 1.0,
            "output_tokens_per_s": None,
            "phases": {},
        },
        "notes": [],
        "embedding_space": baseline["value"]["operation"]["result"]["space"],
        "payloads": None,
    }
    _qualifies(case, baseline)

    changed = copy.deepcopy(baseline)
    changed["value"]["manifest"]["attempts"][0]["error"]["detail"] = "other"
    _rejects(case, changed)


def _fallback_record(
    case: observation.Case | None = None,
) -> tuple[observation.Case, dict[str, Any]]:
    """Project one source-shaped fallback wire pair."""
    case = _case("embedding-optin-fallback") if case is None else case
    failed, winner = case.raw["scripts"]
    failed_step = failed["steps"][0]
    winner_step = winner["steps"][0]
    failed_target = _target(failed)
    winner_target = _target(winner)
    failure = _provider_snapshot(
        detail=failed_step["failure"]["detail"],
        retryable=failed_step["failure"]["retryable"],
        http_status=failed_step["failure"]["http_status"],
    )
    record = _record()
    value = record["value"]
    record["id"] = case.identifier
    factories = _factory(failed) + _factory(winner)
    factories[2]["order"] = 3
    factories[3]["order"] = 4
    value["factories"] = factories
    value["wires"] = [
        {
            "selector_id": failed["id"],
            "step_ordinal": failed_step["ordinal"],
            "instance": failed["instance"],
            "target": failed_target,
            "kind": "embedding",
            "entered_order": 1,
            "terminal_order": 2,
            "request": {
                "model": failed["model"],
                "inputs": copy.deepcopy(failed["slice"]["inputs"]),
                "input_type": None,
                "dimensions": None,
                "timeout_s": 120.0,
                "max_response_bytes": 64 * 1024 * 1024,
                "extra_options": {},
            },
            "outcome": "provider_failure",
            "response": None,
            "failure": _provider_error(
                detail=failed_step["failure"]["detail"],
                retryable=failed_step["failure"]["retryable"],
                http_status=failed_step["failure"]["http_status"],
            ),
        },
        {**_wire(winner, winner_step), "entered_order": 3, "terminal_order": 4},
    ]
    value["operation"]["result"] = _result(winner, winner_step["response"])
    value["operation"]["attempts"] = [
        {"target": failed_target, "outcome": "failed", "error": failure, "timing": _timing()},
        {"target": winner_target, "outcome": "ok", "error": None, "timing": _timing()},
    ]
    value["telemetry"] = [
        {
            "type": "RequestStarted",
            "order": 1,
            "request_relation": "operation",
            "targets": ["optin-a:model-a", "optin-b:model-b"],
            "metadata": {},
            "operation": "embedding",
        },
        {
            "type": "TargetResolved",
            "order": 2,
            "request_relation": "operation",
            "target": failed_target,
        },
        {
            "type": "AttemptStarted",
            "order": 3,
            "request_relation": "operation",
            "target": failed_target,
            "attempt": 1,
        },
        {
            "type": "FallbackTriggered",
            "order": 4,
            "request_relation": "operation",
            "from_target": failed_target,
            "to_target": "optin-b:model-b",
            "error": failure,
        },
        {
            "type": "TargetResolved",
            "order": 5,
            "request_relation": "operation",
            "target": winner_target,
        },
        {
            "type": "AttemptStarted",
            "order": 6,
            "request_relation": "operation",
            "target": winner_target,
            "attempt": 1,
        },
        {
            "type": "AttemptCompleted",
            "order": 7,
            "request_relation": "operation",
            "target": winner_target,
            "usage": _usage(),
            "timing": _timing(),
            "finish_reason": "stop",
        },
        {
            "type": "RequestCompleted",
            "order": 8,
            "request_relation": "operation",
            "target": winner_target,
            "usage": _usage(),
            "timing": _timing(),
            "repair_attempts": 0,
        },
    ]
    return case, record


def test_fallback_retains_its_consumed_failure_in_canonical_and_event_views() -> None:
    """A failed target's source snapshot remains visible when the next target wins."""
    case, record = _fallback_record()
    _qualifies(case, record)

    altered = copy.deepcopy(record)
    altered["value"]["telemetry"][3]["error"]["detail"] = "other"
    _rejects(case, altered)


def test_post_fallback_malformed_response_is_config_error_without_terminal_provider_event() -> (
    None
):
    """The fallback wire completed; only post-result validation refuses the operation."""
    raw = copy.deepcopy(_case("embedding-optin-fallback").raw)
    raw["id"] = "synthetic-fallback-malformed-response"
    raw["scripts"][0]["steps"] = [raw["scripts"][0]["steps"][0]]
    raw["scripts"][0]["steps"][0]["failure"]["retryable"] = False
    raw["scripts"][0]["steps"][0]["failure"]["http_status"] = 400
    raw["scripts"][1]["steps"] = [raw["scripts"][1]["steps"][0]]
    raw["scripts"][1]["steps"][0]["response"]["vectors"] = []
    malformed_case = _case_from_raw(raw)
    _, fallback = _fallback_record(malformed_case)
    value = fallback["value"]
    winner = malformed_case.raw["scripts"][1]
    detail = "provider 'optin-b' returned 0 vectors for 1 inputs"
    value["operation"] = {
        "kind": "embedding",
        "outcome": "error",
        "result": None,
        "error": {
            "runtime_type": "ConfigError",
            "message": detail,
            "provider": "optin-b",
            "phase": "configure",
            "retryable": False,
            "http_status": None,
            "retry_after_s": None,
            "detail": detail,
            "hint": "this is a provider-side contract violation; report it upstream",
        },
        "attempts": [],
        "request_relation": "operation",
        "cancellation_relation": "none",
    }
    value["wires"][1]["response"] = copy.deepcopy(winner["steps"][0]["response"])
    value["telemetry"] = value["telemetry"][:-1]
    _qualifies(malformed_case, fallback)

    fabricated_terminal = copy.deepcopy(fallback)
    failure = malformed_case.raw["scripts"][0]["steps"][0]["failure"]
    forged_snapshot = _provider_snapshot(
        detail=failure["detail"], retryable=False, http_status=400
    )
    fabricated_terminal["value"]["operation"]["attempts"] = [
        {
            "target": _target(malformed_case.raw["scripts"][0]),
            "outcome": "failed",
            "error": forged_snapshot,
            "timing": _timing(),
        }
    ]
    fabricated_terminal["value"]["telemetry"].append(
        {
            "type": "RequestFailed",
            "order": 8,
            "request_relation": "operation",
            "error": forged_snapshot,
        }
    )
    _rejects(malformed_case, fabricated_terminal)


def test_concurrent_selector_failures_preserve_distinct_same_target_occurrences() -> None:
    """Concurrent chunks have separate literal failures even when their target is shared."""
    raw = copy.deepcopy(_case("embedding-split-all-failed").raw)
    raw["id"] = "synthetic-concurrent-distinct-failures"
    raw["scripts"][0]["steps"][0]["failure"]["detail"] = "left failure"
    raw["scripts"][1]["steps"][0]["failure"]["detail"] = "right failure"
    for selector in raw["scripts"]:
        selector["steps"] = [selector["steps"][0]]
        failure = selector["steps"][0]["failure"]
        failure["retryable"] = False
        failure["http_status"] = 400
    case = _case_from_raw(raw)
    left, right = case.raw["scripts"]
    target = _target(left)
    failures = [left["steps"][0], right["steps"][0]]
    detail = "2 of 2 internal batches failed for allfail:model"
    record = {
        "id": case.identifier,
        "kind": "embedding",
        "status": "ok",
        "value": {
            "operation": {
                "kind": "embedding",
                "outcome": "error",
                "result": None,
                "error": {
                    "runtime_type": "AllTargetsFailedError",
                    "message": detail,
                    "provider": None,
                    "phase": "generate",
                    "retryable": False,
                    "http_status": None,
                    "retry_after_s": None,
                    "detail": detail,
                    "hint": "batched requests are all-or-error; batch_failures records every chunk's outcome, including the spend of the ones that succeeded",
                },
                "attempts": [
                    {
                        "target": target,
                        "outcome": "failed",
                        "error": _provider_snapshot(
                            detail=failure["failure"]["detail"], retryable=False, http_status=400
                        ),
                        "timing": _timing(),
                    }
                    for failure in failures
                ],
                "request_relation": "operation",
                "cancellation_relation": "none",
            },
            "factories": _factory(left),
            "wires": [
                {
                    "selector_id": selector["id"],
                    "step_ordinal": step["ordinal"],
                    "instance": selector["instance"],
                    "target": target,
                    "kind": "embedding",
                    "entered_order": position * 2 + 1,
                    "terminal_order": position * 2 + 2,
                    "request": {
                        "model": selector["model"],
                        "inputs": copy.deepcopy(selector["slice"]["inputs"]),
                        "input_type": None,
                        "dimensions": None,
                        "timeout_s": 120.0,
                        "max_response_bytes": 64 * 1024 * 1024,
                        "extra_options": {},
                    },
                    "outcome": "provider_failure",
                    "response": None,
                    "failure": _provider_error(
                        detail=step["failure"]["detail"], retryable=False, http_status=400
                    ),
                }
                for position, (selector, step) in enumerate(
                    zip((left, right), failures, strict=True)
                )
            ],
            "telemetry": [
                {
                    "type": "RequestStarted",
                    "order": 1,
                    "request_relation": "operation",
                    "targets": ["allfail:model"],
                    "metadata": {},
                    "operation": "embedding",
                },
                {
                    "type": "TargetResolved",
                    "order": 2,
                    "request_relation": "operation",
                    "target": target,
                },
                {
                    "type": "AttemptStarted",
                    "order": 3,
                    "request_relation": "operation",
                    "target": target,
                    "attempt": 1,
                },
                {
                    "type": "AttemptStarted",
                    "order": 4,
                    "request_relation": "operation",
                    "target": target,
                    "attempt": 1,
                },
                {
                    "type": "RequestFailed",
                    "order": 5,
                    "request_relation": "operation",
                    "error": _provider_snapshot(
                        detail=failures[0]["failure"]["detail"], retryable=False, http_status=400
                    ),
                },
            ],
            "ledger": None,
            "manifest": None,
            "resources": [],
            "batch_failures": [
                {
                    "batch_index": index,
                    "item_count": len(selector["slice"]["inputs"]),
                    "succeeded": False,
                    "error": step["failure"]["detail"],
                }
                for index, (selector, step) in enumerate(zip((left, right), failures, strict=True))
            ],
        },
    }
    _qualifies(case, record)

    swapped = copy.deepcopy(record)
    swapped["value"]["operation"]["attempts"][0]["error"]["detail"] = "right failure"
    _rejects(case, swapped)


def test_spend_error_is_category_free_requires_all_money_and_pairs_runtime_locally() -> None:
    case = _case("rerank-unknown-spend-refusal")
    python = _spend_refusal(case)
    _qualifies(case, python)

    category = copy.deepcopy(python)
    category["value"]["operation"]["error"]["category"] = "spend_limit"
    with pytest.raises(ValidationError):
        _schema_valid(category)

    for field in ("limit_usd", "spent_usd", "estimated_usd"):
        incomplete = copy.deepcopy(python)
        del incomplete["value"]["operation"]["error"][field]
        with pytest.raises(ValidationError):
            _schema_valid(incomplete)

    native = copy.deepcopy(python)
    native["value"]["operation"]["error"]["runtime_type"] = "SpendLimitException"
    native["value"]["operation"]["error"]["message"] = "native local wording"
    _qualifies(case, native, runtime="csharp")
    assert checker.compare_case(case, python, native) == []


def test_comparison_keeps_raw_money_lists_and_types_exact_except_declared_numeric_slots() -> None:
    case = _case()
    python = _record(case)
    native = copy.deepcopy(python)
    _qualifies(case, python)
    _qualifies(case, native, runtime="csharp")
    assert checker.compare_case(case, python, native) == []

    typed_numeric = copy.deepcopy(native)
    typed_numeric["value"]["operation"]["result"]["vectors"][0][0] = 1
    python["value"]["operation"]["result"]["vectors"][0][0] = 1.0
    assert checker.compare_case(case, python, typed_numeric) == []

    python = _record(case)
    raw_type = copy.deepcopy(native)
    raw_type["value"]["operation"]["result"]["raw"] = {
        "items": [{"score": 1, "detail": "d"}],
        "phases": ["decode"],
        "timeout_s": 1,
    }
    python["value"]["operation"]["result"]["raw"] = {
        "items": [{"score": 1.0, "detail": "d"}],
        "phases": ["decode"],
        "timeout_s": 1.0,
    }
    assert checker.compare_case(case, python, raw_type)

    raw_bool = copy.deepcopy(native)
    raw_bool["value"]["operation"]["result"]["raw"] = {"items": [True]}
    assert checker.compare_case(case, python, raw_bool)

    wide = copy.deepcopy(native)
    wide["value"]["operation"]["result"]["vectors"][0][0] = math.nextafter(1.0, 2.0)
    assert checker.compare_case(case, python, wide)

    nonfinite = copy.deepcopy(native)
    nonfinite["value"]["operation"]["result"]["vectors"][0][0] = math.inf
    _schema_valid(nonfinite)
    with pytest.raises(observation.ObservationError):
        checker.qualify_observation(case, nonfinite, runtime="csharp")

    python_money = _record(case)
    native_money = _record(case)
    python_money["value"]["operation"]["result"]["usage"]["cost_usd"] = "1.00"
    python_money["value"]["telemetry"][-1]["usage"]["cost_usd"] = "1.00"
    native_money["value"]["operation"]["result"]["usage"]["cost_usd"] = "1.01"
    native_money["value"]["telemetry"][-1]["usage"]["cost_usd"] = "1.01"
    _qualifies(case, python_money)
    _qualifies(case, native_money, runtime="csharp")
    assert checker.compare_case(case, python_money, native_money)

    reordered = copy.deepcopy(native)
    reordered["value"]["operation"]["result"]["vectors"] = [[0.2, 0.1]]
    assert checker.compare_case(case, _record(case), reordered)


def test_manifest_attempt_timings_are_runtime_local_but_presence_and_raw_lookalikes_stay_strict() -> (
    None
):
    """Only the two flat manifest timing facets are local cross-runtime evidence."""
    case = _admitted_case("embedding-scalar-unknown-intent")
    python = _record(case)
    python["value"]["manifest"] = {
        "request_relation": "operation",
        "format": "1",
        "complete": True,
        "operation": "embedding",
        "route": {
            "requested": ["alpha:model"],
            "resolved": "alpha:model",
            "considered": [{"target": "alpha:model", "outcome": "ok", "reason": ""}],
        },
        "attempts": [_attempt_facet("alpha:model")],
        "usage": _usage_facet(),
        "timing": {
            "first_token_ms": None,
            "total_ms": 1.0,
            "output_tokens_per_s": None,
            "phases": {},
        },
        "notes": [],
        "embedding_space": python["value"]["operation"]["result"]["space"],
        "payloads": None,
    }
    native = copy.deepcopy(python)
    native["value"]["operation"]["attempts"][0]["timing"]["total_ms"] = 7.0
    native["value"]["manifest"]["attempts"][0]["total_ms"] = 7.0
    native["value"]["operation"]["result"]["timing"]["total_ms"] = 7.0
    native["value"]["telemetry"][-2]["timing"]["total_ms"] = 7.0
    native["value"]["telemetry"][-1]["timing"]["total_ms"] = 7.0
    native["value"]["manifest"]["timing"]["total_ms"] = 7.0
    _qualifies(case, python)
    _qualifies(case, native, runtime="csharp")
    assert checker.compare_case(case, python, native) == []

    missing = copy.deepcopy(native)
    missing["value"]["operation"]["attempts"][0]["timing"]["first_token_ms"] = 3.0
    missing["value"]["manifest"]["attempts"][0]["first_token_ms"] = 3.0
    _qualifies(case, missing, runtime="csharp")
    assert checker.compare_case(case, python, missing)

    nonfinite = copy.deepcopy(native)
    nonfinite["value"]["operation"]["attempts"][0]["timing"]["total_ms"] = math.inf
    nonfinite["value"]["manifest"]["attempts"][0]["total_ms"] = math.inf
    _schema_valid(nonfinite)
    with pytest.raises(observation.ObservationError):
        checker.qualify_observation(case, nonfinite, runtime="csharp")

    python_raw = copy.deepcopy(python)
    native_raw = copy.deepcopy(python)
    python_raw["value"]["operation"]["result"]["raw"] = {"total_ms": 1.0}
    native_raw["value"]["operation"]["result"]["raw"] = {"total_ms": 7.0}
    assert checker.compare_case(case, python_raw, native_raw)


def test_wire_provider_failure_uses_only_its_closed_runtime_type_pair() -> None:
    """Wire snapshots pair typed provider failures without normalizing raw lookalikes."""
    case, python = _retry_record(_admitted_case("embedding-retry-success"))
    native = copy.deepcopy(python)
    for wire in native["value"]["wires"]:
        if wire["failure"] is not None:
            wire["failure"]["runtime_type"] = "ProviderException"
    for attempt in native["value"]["operation"]["attempts"]:
        if attempt["error"] is not None:
            attempt["error"]["runtime_type"] = "ProviderException"
    for event in native["value"]["telemetry"]:
        if event.get("error") is not None:
            event["error"]["runtime_type"] = "ProviderException"
    _qualifies(case, python)
    _qualifies(case, native, runtime="csharp")
    assert checker.compare_case(case, python, native) == []

    wrong_pair = copy.deepcopy(native)
    wrong_pair["value"]["wires"][0]["failure"]["runtime_type"] = "ConfigException"
    _schema_valid(wrong_pair)
    with pytest.raises(observation.ObservationError):
        checker.qualify_observation(case, wrong_pair, runtime="csharp")

    raw_input = copy.deepcopy(_case("embedding-scalar-unknown-intent").raw)
    raw_input["id"] = "synthetic-wire-response-raw-error-lookalike"
    raw_input["scripts"][0]["steps"][0]["response"]["raw"] = {
        "failure": {"runtime_type": "ProviderError"},
        "error": {"runtime_type": "ProviderError", "retry_after_s": 1},
    }
    raw_case = _case_from_raw(raw_input)
    raw_python = _record(raw_case)
    raw_native = _record(raw_case)
    _qualifies(raw_case, raw_python)
    _qualifies(raw_case, raw_native, runtime="csharp")
    assert checker.compare_case(raw_case, raw_python, raw_native) == []

    changed_raw = copy.deepcopy(raw_native)
    changed_raw["value"]["wires"][0]["response"]["raw"]["failure"]["runtime_type"] = (
        "ProviderException"
    )
    _rejects(raw_case, changed_raw, runtime="csharp")

    changed_raw_retry_after = copy.deepcopy(raw_native)
    changed_raw_retry_after["value"]["wires"][0]["response"]["raw"]["error"]["retry_after_s"] = 1.0
    _rejects(raw_case, changed_raw_retry_after, runtime="csharp")

    retry_input = copy.deepcopy(_case("embedding-retry-success").raw)
    retry_input["id"] = "synthetic-retry-after-finite-pair"
    retry_input["scripts"][0]["steps"][0]["failure"]["retry_after_s"] = 1
    retry_case, retry_python = _retry_record(_case_from_raw(retry_input))
    retry_python["value"]["wires"][0]["failure"]["retry_after_s"] = 1
    retry_native = copy.deepcopy(retry_python)
    retry_native["value"]["wires"][0]["failure"]["runtime_type"] = "ProviderException"
    retry_native["value"]["wires"][0]["failure"]["retry_after_s"] = 1.0
    for attempt in retry_native["value"]["operation"]["attempts"]:
        if attempt["error"] is not None:
            attempt["error"]["runtime_type"] = "ProviderException"
    for event in retry_native["value"]["telemetry"]:
        if event.get("error") is not None:
            event["error"]["runtime_type"] = "ProviderException"
    _qualifies(retry_case, retry_python)
    _qualifies(retry_case, retry_native, runtime="csharp")
    assert checker.compare_case(retry_case, retry_python, retry_native) == []

    invalid_bool = copy.deepcopy(retry_native)
    invalid_bool["value"]["wires"][0]["failure"]["retry_after_s"] = True
    with pytest.raises(ValidationError):
        _schema_valid(invalid_bool)

    for invalid in (math.inf, 2.0):
        rejected = copy.deepcopy(retry_native)
        rejected["value"]["wires"][0]["failure"]["retry_after_s"] = invalid
        if invalid is math.inf:
            _schema_valid(rejected)
        _rejects(retry_case, rejected, runtime="csharp")


def test_ledger_totals_follow_one_completed_operation_and_remain_empty_otherwise() -> None:
    """Ledger snapshots project the sole public completion, never pricing policy or wires."""
    literal_usage = {
        "input_tokens": 3,
        "output_tokens": 5,
        "total_tokens": 8,
        "cache_read_tokens": 7,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": "9",
        "search_units": None,
        "server_tool_uses": {},
    }
    input_case = copy.deepcopy(_case("embedding-priced-provider-spend-manifest").raw)
    input_case["id"] = "synthetic-priced-ledger-usage"
    input_case["scripts"][0]["steps"][0]["response"]["usage"] = literal_usage
    case = _case_from_raw(input_case)
    known = _record(case)
    known["value"]["operation"]["result"]["usage"] = copy.deepcopy(literal_usage)
    known["value"]["telemetry"][-2]["usage"] = copy.deepcopy(literal_usage)
    known["value"]["telemetry"][-1]["usage"] = copy.deepcopy(literal_usage)
    known["value"]["manifest"] = {
        "request_relation": "operation",
        "format": "1",
        "complete": True,
        "operation": "embedding",
        "route": {
            "requested": ["paid:model"],
            "resolved": "paid:model",
            "considered": [{"target": "paid:model", "outcome": "ok", "reason": ""}],
        },
        "attempts": [_attempt_facet("paid:model")],
        "usage": {
            **_usage_facet(),
            **{key: value for key, value in literal_usage.items() if key != "server_tool_uses"},
            "estimated_fields": {},
        },
        "timing": {
            "first_token_ms": None,
            "total_ms": 1.0,
            "output_tokens_per_s": None,
            "phases": {},
        },
        "notes": [],
        "embedding_space": known["value"]["operation"]["result"]["space"],
        "payloads": None,
    }
    empty = {
        "cost": "0",
        "currency": "USD",
        "requests": 0,
        "unknown_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
    }
    terminal = {
        "cost": "9",
        "currency": "USD",
        "requests": 1,
        "unknown_requests": 0,
        "input_tokens": 3,
        "output_tokens": 5,
        "cache_read_tokens": 7,
    }
    known["value"]["ledger"] = [
        {"label": "before_call", "reserved": "0", "totals": empty},
        {"label": "after_operation", "reserved": "0", "totals": terminal},
        {"label": "after_client_close", "reserved": "0", "totals": terminal},
    ]
    _qualifies(case, known)

    for field, value in (
        ("cost", "8"),
        ("currency", "EUR"),
        ("requests", 2),
        ("unknown_requests", 1),
        ("input_tokens", 4),
        ("output_tokens", 6),
        ("cache_read_tokens", 8),
    ):
        mutated = copy.deepcopy(known)
        mutated["value"]["ledger"][1]["totals"][field] = value
        mutated["value"]["ledger"][2]["totals"][field] = value
        _rejects(case, mutated)

    wrong_before = copy.deepcopy(known)
    wrong_before["value"]["ledger"][0]["totals"]["requests"] = 1
    _rejects(case, wrong_before)

    wrong_reservation = copy.deepcopy(known)
    wrong_reservation["value"]["ledger"][1]["reserved"] = "1"
    wrong_reservation["value"]["ledger"][2]["reserved"] = "1"
    _rejects(case, wrong_reservation)

    wrong_close = copy.deepcopy(known)
    wrong_close["value"]["ledger"][2]["totals"]["requests"] = 2
    _rejects(case, wrong_close)

    unknown_case = _admitted_case("embedding-priced-provider-spend-manifest")
    unknown = _record(unknown_case)
    unknown_terminal = {
        "cost": "0",
        "currency": "USD",
        "requests": 1,
        "unknown_requests": 1,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
    }
    unknown["value"]["ledger"] = [
        {"label": "before_call", "reserved": "0", "totals": empty},
        {"label": "after_operation", "reserved": "0", "totals": unknown_terminal},
        {"label": "after_client_close", "reserved": "0", "totals": unknown_terminal},
    ]
    _qualifies(unknown_case, unknown)

    error_case = _admitted_case("rerank-unknown-spend-refusal")
    cancelled_case, cancelled = _cancelled_ledger_record()
    for terminal_case, record in (
        (error_case, _spend_refusal(error_case)),
        (cancelled_case, cancelled),
    ):
        _qualifies(terminal_case, record)
        nonempty = copy.deepcopy(record)
        nonempty["value"]["ledger"][1]["totals"]["requests"] = 1
        nonempty["value"]["ledger"][2]["totals"]["requests"] = 1
        _rejects(terminal_case, nonempty)

    held_nonempty = copy.deepcopy(cancelled)
    held_nonempty["value"]["ledger"][1]["totals"]["requests"] = 1
    _rejects(cancelled_case, held_nonempty)
