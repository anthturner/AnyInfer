"""Qualify and compare independent public retrieval-v1 observations.

This profile intentionally consumes only frozen literal stimuli and public captures.  It
does not plan routes or chunks, calculate cost, or manufacture expected SDK results.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import _csharp_observation as observation
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from anyinfer.redaction import RedactionRegistry

PROFILE = "retrieval-v1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "tests" / "fixtures" / "retrieval-v1" / "inputs.json"
DEFAULT_OUTPUT_ROOT = ROOT / ".tmp-tests" / "retrieval"
PYTHON_OBSERVER = ROOT / "tests" / "test_retrieval_parity.py"
CSHARP_ROOT = ROOT / "src" / "csharp"
INPUT_SCHEMA = ROOT / "tests" / "fixtures" / PROFILE / "schema.json"
OBSERVATION_SCHEMA = ROOT / "tests" / "fixtures" / PROFILE / "observations.schema.json"
FROZEN_CORPUS_SHA256 = "cbf8640aa19920044e652d2a095563c480b8a5e7b18c16a2e471f89eb24a4750"
RUNTIME_TYPES = {
    "ConfigError": "ConfigException",
    "ProviderError": "ProviderException",
    "ProviderUnavailableError": "ProviderUnavailableException",
    "ContextLengthError": "ContextLengthException",
    "AllTargetsFailedError": "AllTargetsFailedException",
    "SpendLimitError": "SpendLimitException",
}
_TYPED_ERROR_PATH = re.compile(
    r"^value\.(?:operation\.error|operation\.attempts\[\d+\]\.error|"
    r"telemetry\[\d+\]\.error|manifest\.attempts\[\d+\]\.error|"
    r"wires\[\d+\]\.failure)$"
)
_TYPED_ERROR_RETRY_AFTER_PATH = re.compile(
    r"^value\.(?:operation\.error|operation\.attempts\[\d+\]\.error|"
    r"telemetry\[\d+\]\.error|manifest\.attempts\[\d+\]\.error|"
    r"wires\[\d+\]\.failure)\.retry_after_s$"
)
_MISSING = object()


@dataclass(frozen=True)
class Comparison:
    """One profile-local comparison result."""

    matched: tuple[str, ...]
    mismatches: tuple[dict[str, str], ...]
    runtime_specific: tuple[dict[str, Any], ...]

    @property
    def status(self) -> str:
        """Return the report-compatible aggregate profile outcome."""
        return "pass" if not self.mismatches else "fail"


def _fail(message: str) -> NoReturn:
    raise observation.ObservationError(message)


def _validate_schema(path: Path, value: Any, *, label: str) -> None:
    """Apply the frozen Draft 2020-12 profile schema without normalizing input."""
    try:
        schema = observation.read_json_bytes(path)
        validator = Draft202012Validator(schema)
        validator.validate(value)
    except (SchemaError, ValidationError):
        _fail(f"{label} does not satisfy its frozen schema")


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{where} must be an object")
    return value


def _list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{where} must be an array")
    return value


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str):
        _fail(f"{where} must be a string")
    return value


def _finite(value: Any, where: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        _fail(f"{where} must be a finite JSON number")


def _case_selectors(
    case: observation.Case,
) -> dict[tuple[str, str, str, tuple[Any, ...]], dict[str, Any]]:
    selectors: dict[tuple[str, str, str, tuple[Any, ...]], dict[str, Any]] = {}
    for selector in _list(case.raw.get("scripts"), f"{case.identifier}.scripts"):
        selector = _mapping(selector, f"{case.identifier}.selector")
        operation = _string(selector.get("operation"), "selector.operation")
        instance = _string(selector.get("instance"), "selector.instance")
        model = _string(selector.get("model"), "selector.model")
        slice_value = _mapping(selector.get("slice"), "selector.slice")
        if operation == "embedding":
            key_slice = tuple(_list(slice_value.get("inputs"), "selector.slice.inputs"))
        else:
            key_slice = tuple(
                (item["index"], item["text"])
                for item in _list(slice_value.get("documents"), "selector.slice.documents")
            )
        key = (operation, instance, model, key_slice)
        if key in selectors:
            _fail(f"{case.identifier} has duplicate full selector key")
        selectors[key] = selector
    return selectors


def _wire_key(wire: Mapping[str, Any]) -> tuple[str, str, str, tuple[Any, ...]]:
    request = _mapping(wire.get("request"), "wire.request")
    target = _mapping(wire.get("target"), "wire.target")
    operation = _string(wire.get("kind"), "wire.kind")
    instance = _string(wire.get("instance"), "wire.instance")
    model = _string(request.get("model"), "wire.request.model")
    if target.get("provider_id") != instance or target.get("model") != model:
        _fail("wire target must identify its selected instance and model")
    if operation == "embedding":
        values = tuple(_list(request.get("inputs"), "wire.request.inputs"))
    elif operation == "rerank":
        values = tuple(
            (entry["index"], entry["text"])
            for entry in _list(request.get("documents"), "wire.request.documents")
        )
    else:
        _fail("wire.kind must be embedding or rerank")
    return operation, instance, model, values


def _redactor(case: observation.Case) -> RedactionRegistry:
    """Create an isolated public redactor for this one frozen case."""
    registry = RedactionRegistry()
    for secret in _list(
        _mapping(case.raw.get("client"), "case.client").get("registered_secrets"),
        "registered_secrets",
    ):
        if isinstance(secret, str):
            registry.register(secret)
    return registry


def _redacted_literal(case: observation.Case, value: Any) -> Any:
    """Project frozen literals through the same public redactor as observer captures."""
    registry = _redactor(case)
    if isinstance(value, str):
        return registry.redact(value)
    if isinstance(value, list):
        return [_redacted_literal(case, item) for item in value]
    if isinstance(value, dict):
        return {
            registry.redact(key) if isinstance(key, str) else key: _redacted_literal(case, nested)
            for key, nested in value.items()
        }
    return value


def _failure_projection(case: observation.Case, failure: Mapping[str, Any]) -> dict[str, Any]:
    """Project a scripted public error through redaction and the bounded snapshot detail rule."""
    projected = _mapping(_redacted_literal(case, dict(failure)), "script failure")
    detail = projected.get("detail")
    if isinstance(detail, str):
        projected["detail"] = detail if len(detail) <= 512 else f"{detail[:511]}…"
    return projected


def _redacted_secret_check(case: observation.Case, value: Any) -> None:
    registry = _redactor(case)

    def visit(item: Any) -> None:
        if isinstance(item, str):
            if registry.redact(item) != item:
                _fail("observation exposes a registered secret")
        elif isinstance(item, dict):
            for key, nested in item.items():
                visit(key)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)


def _redacted_envelope_check(cases: Sequence[observation.Case], value: Any) -> None:
    """Fail closed before schema diagnostics can render an exposed secret-bearing value."""
    registry = RedactionRegistry()
    for case in cases:
        for secret in _list(
            _mapping(case.raw.get("client"), "case.client").get("registered_secrets"),
            "registered_secrets",
        ):
            if isinstance(secret, str):
                registry.register(secret)

    def visit(item: Any) -> None:
        if isinstance(item, str):
            if registry.redact(item) != item:
                _fail("observation envelope exposes a registered secret")
        elif isinstance(item, dict):
            for key, nested in item.items():
                visit(key)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)


def _finite_capture_check(value: Any) -> None:
    """Reject nonfinite captured floats without coercing arbitrary JSON integers."""
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("observation contains a nonfinite captured number")
    elif isinstance(value, dict):
        for nested in value.values():
            _finite_capture_check(nested)
    elif isinstance(value, list):
        for nested in value:
            _finite_capture_check(nested)


def _equal_literal(left: Any, right: Any, path: str = "") -> bool:
    """Compare raw JSON exactly, except approved typed finite number paths."""
    numeric = _typed_numeric_slot(path)
    if numeric and type(left) in (int, float) and type(right) in (int, float):
        return math.isfinite(left) and math.isfinite(right) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _equal_literal(left[key], right[key], f"{path}.{key}") for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _equal_literal(a, b, f"{path}[{index}]")
            for index, (a, b) in enumerate(zip(left, right, strict=True))
        )
    return left == right


def _equal_retry_after_literal(left: Any, right: Any) -> bool:
    """Compare the one typed scripted-error number without broadening literal joins."""
    if left is None or right is None:
        return left is right
    if type(left) not in (int, float) or type(right) not in (int, float):
        return False
    return math.isfinite(left) and math.isfinite(right) and left == right


def _typed_numeric_slot(path: str) -> bool:
    """Recognize only frozen structural numeric-equivalence slots, never raw JSON keys."""
    if ".raw" in path:
        return False
    return (
        ".operation.result.vectors[" in path
        or (".operation.result.items[" in path and path.endswith(".score"))
        or (".wires[" in path and ".response.phases." in path)
        or (".wires[" in path and path.endswith(".request.timeout_s"))
        or (".telemetry[" in path and path.endswith(".delay_s"))
        or _TYPED_ERROR_RETRY_AFTER_PATH.fullmatch(path) is not None
    )


def _typed_error_slot(path: str) -> bool:
    """Recognize known public exception/snapshot fields without key-name heuristics."""
    return _TYPED_ERROR_PATH.fullmatch(path) is not None


def _capture_order_slot(path: str) -> bool:
    """Recognize only recorder-local counters whose cross-runtime values are incidental."""
    if ".raw" in path:
        return False
    return (
        (path.startswith("value.factories[") and path.endswith(".order"))
        or (
            path.startswith("value.wires[")
            and (path.endswith(".entered_order") or path.endswith(".terminal_order"))
        )
        or (path.startswith("value.telemetry[") and path.endswith(".order"))
        or (path.startswith("value.resources[") and path.endswith(".order"))
    )


def _comparison_value(value: dict[str, Any]) -> dict[str, Any]:
    """Sort only unconstrained concurrent capture collections by their causal identity."""
    result = dict(value)
    for field, key in (
        ("factories", lambda item: (item["type"], item["instance"], item["model"])),
        ("wires", lambda item: (item["selector_id"], item["step_ordinal"], item["instance"])),
        (
            "resources",
            lambda item: (
                item["selector_id"] is None,
                item["selector_id"] or "",
                item["step_ordinal"] or 0,
                item["instance"] or "",
                item["type"],
            ),
        ),
    ):
        values = _list(result[field], f"value.{field}")
        result[field] = sorted(values, key=key)
    return result


def _difference(left: Any, right: Any, path: str = "value") -> str | None:
    if _equal_literal(left, right, path):
        return None
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return f"{path} keys differ"
        for key in left:
            difference = _difference(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return f"{path} lengths differ"
        for index, (item, other) in enumerate(zip(left, right, strict=True)):
            difference = _difference(item, other, f"{path}[{index}]")
            if difference:
                return difference
    return f"{path} differs"


def _error_matches_literal(
    failure: Mapping[str, Any], error: Mapping[str, Any], runtime: str
) -> None:
    detail = error.get("detail")
    if isinstance(detail, str) and len(detail) > 512:
        _fail("captured exception snapshot detail exceeds the public bounded-detail limit")
    expected = {
        "provider": failure["provider"],
        "phase": failure["phase"],
        "retryable": failure["retryable"],
        "http_status": failure["http_status"],
        "retry_after_s": failure["retry_after_s"],
        "detail": failure["detail"],
        "hint": failure["hint"],
    }
    for key, literal in expected.items():
        if key not in error:
            continue
        matches = (
            _equal_retry_after_literal(literal, error[key])
            if key == "retry_after_s"
            else _equal_literal(literal, error[key], f"error.{key}")
        )
        if not matches:
            _fail(f"script-origin provider failure {key} differs from its literal step")
    runtime_type = _string(error.get("runtime_type"), "error.runtime_type")
    permitted = {
        "provider": ("ProviderError", "ProviderException"),
        "provider_unavailable": ("ProviderUnavailableError", "ProviderUnavailableException"),
        "context_length": ("ContextLengthError", "ContextLengthException"),
    }[failure["kind"]]
    if runtime_type != permitted[0 if runtime == "python" else 1]:
        _fail("script provider failure has the wrong runtime type")


def _qualify_wire(
    case: observation.Case,
    wire: dict[str, Any],
    selector: dict[str, Any],
    step: dict[str, Any],
    runtime: str,
) -> None:
    if wire.get("selector_id") != selector.get("id") or wire.get("step_ordinal") != step.get(
        "ordinal"
    ):
        _fail("wire selector/step association differs from consumed literal step")
    outcome = wire.get("outcome")
    action = step.get("action")
    if action == "barrier":
        if outcome not in ("response", "provider_failure", "cancelled"):
            _fail("barrier wire must end in a public terminal outcome")
        if outcome != "cancelled":
            step = _mapping(step["continuation"], "barrier continuation")
            action = step["action"]
    if action.endswith("response"):
        if outcome != "response":
            _fail("literal response step did not produce a response wire")
        if not _equal_literal(
            _redacted_literal(case, step["response"]), wire.get("response"), "wire.response"
        ):
            _fail("wire response differs from its literal adapter response")
    elif action == "provider_failure":
        if outcome != "provider_failure":
            _fail("literal failure step did not produce a provider-failure wire")
        _error_matches_literal(
            _failure_projection(case, _mapping(step["failure"], "step.failure")),
            _mapping(wire.get("failure"), "wire.failure"),
            runtime,
        )


def _descriptors(case: observation.Case) -> dict[tuple[str, str], dict[str, Any]]:
    """Index frozen descriptor facts by their actual provider instance/model pair."""
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in _list(case.raw["descriptors"], "case.descriptors"):
        descriptor = _mapping(raw, "descriptor")
        key = (_string(descriptor["instance"], "descriptor.instance"), descriptor["model"])
        if key in result:
            _fail("frozen case has duplicate descriptor instance/model facts")
        result[key] = descriptor
    return result


def _wire_request_projection(
    case: observation.Case, wire: Mapping[str, Any], selector: Mapping[str, Any]
) -> None:
    """Join direct wire request fields to their frozen public request and selected options."""
    request = _mapping(case.raw["request"], "case.request")
    captured = _mapping(wire["request"], "wire.request")
    instance = _string(selector["instance"], "selector.instance")
    expected_options = _mapping(request["provider_options"], "request.provider_options").get(
        instance, {}
    )
    if captured.get("model") != selector["model"]:
        _fail("wire model differs from the matched selector model")
    if not _equal_literal(
        captured.get("extra_options"),
        _redacted_literal(case, expected_options),
        "wire.extra_options",
    ):
        _fail("wire extra options differ from the selected provider option map")
    if captured.get("timeout_s") != (request["timeout_s"] or 120):
        _fail("wire timeout does not preserve the request/default public value")
    if case.kind == "embedding":
        expected_cap = request.get("max_response_bytes")
        if expected_cap is None:
            expected_cap = 64 * 1024 * 1024
        expected = {
            "inputs": selector["slice"]["inputs"],
            "input_type": request["input_type"],
            "dimensions": request["dimensions"],
            "max_response_bytes": expected_cap,
        }
    else:
        expected_cap = request.get("max_response_bytes")
        if expected_cap is None:
            expected_cap = 8 * 1024 * 1024
        expected = {
            "query": request["query"],
            "documents": selector["slice"]["documents"],
            "top_n": request["top_n"],
            "max_response_bytes": expected_cap,
        }
    for field, literal in expected.items():
        if not _equal_literal(captured.get(field), literal, f"wire.request.{field}"):
            _fail(f"wire request {field} differs from frozen public input")


def _target_key(target: Mapping[str, Any]) -> tuple[str, str]:
    return _string(target["provider_id"], "target.provider_id"), _string(
        target["model"], "target.model"
    )


def _qualify_factories(case: observation.Case, factories: list[Any], wires: list[Any]) -> None:
    """Bind factory facts without requiring pre-start materialization."""
    descriptors = _descriptors(case)
    entered: dict[tuple[str, str], int] = {}
    returned: set[tuple[str, str]] = set()
    for raw in factories:
        factory = _mapping(raw, "factory")
        key = (_string(factory["instance"], "factory.instance"), factory["model"])
        descriptor = descriptors.get(key)
        if descriptor is None:
            _fail("factory capture is not a frozen descriptor")
        if not _equal_literal(factory["declared_operations"], descriptor["operations"]):
            _fail("factory declared operations differ from frozen descriptor facts")
        order = factory.get("order")
        if type(order) is not int:
            _fail("factory capture must retain its local order")
        if factory["type"] == "factory_entered":
            entered[key] = order
        elif factory["type"] == "factory_returned":
            if key not in entered:
                _fail("factory return has no prior capture for its frozen descriptor")
            if entered[key] >= order:
                _fail("factory return must follow entry in its local capture order")
            if not _equal_literal(
                factory.get("runtime_protocols"), descriptor["runtime_protocols"]
            ):
                _fail("factory runtime protocols differ from frozen descriptor facts")
            returned.add(key)
    for raw_wire in wires:
        wire = _mapping(raw_wire, "wire")
        if _target_key(_mapping(wire["target"], "wire.target")) not in returned:
            _fail("wire has no returned factory for its selected descriptor")


def _qualify_wire_orders(wires: list[Any]) -> None:
    """Require each recorder wire's local entry-to-terminal partial order."""
    for raw in wires:
        wire = _mapping(raw, "wire")
        entered = wire.get("entered_order")
        terminal = wire.get("terminal_order")
        if type(entered) is not int or type(terminal) is not int or entered >= terminal:
            _fail("wire terminal capture must follow its local entry capture")


def _literal_route_members(case: observation.Case) -> set[str]:
    """Return direct caller-declared route members without resolving route precedence."""
    client = _mapping(case.raw["client"], "case.client")
    members: set[str] = set()
    target = client.get("per_call_target")
    if isinstance(target, str):
        members.add(target)
    for field in ("default_route", "operation_route", "per_call_route"):
        route = client.get(field)
        if isinstance(route, dict):
            members.update(item for item in route.get("targets", []) if isinstance(item, str))
    return members


def _target_name(target: Mapping[str, Any]) -> str:
    """Render a captured public target in the manifest/route spelling."""
    instance, model = _target_key(target)
    return f"{instance}:{model}"


def _resource_order(
    resources: list[Any], *, selector_id: str | None = None, step_ordinal: int | None = None
) -> dict[str, int]:
    """Index one associated resource trace while retaining unrelated traces untouched."""
    selected: dict[str, int] = {}
    for raw in resources:
        resource = _mapping(raw, "resource")
        if selector_id is not None and resource.get("selector_id") != selector_id:
            continue
        if step_ordinal is not None and resource.get("step_ordinal") != step_ordinal:
            continue
        order = resource.get("order")
        if type(order) is not int:
            _fail("resource order must remain a public ordinal")
        kind = _string(resource.get("type"), "resource.type")
        if kind in selected:
            _fail("associated resource trace repeats a typed boundary")
        selected[kind] = order
    return selected


def _qualify_resource_joins(case: observation.Case, resources: list[Any]) -> None:
    """Require only the frozen procedure's public resource partial-order witnesses."""
    procedure = _mapping(case.raw["procedure"], "case.procedure")
    name = procedure["name"]
    if name == "caller_cancel_while_provider_held":
        barrier_selector = next(
            (
                selector
                for selector in _list(case.raw["scripts"], "case.scripts")
                if any(step.get("action") == "barrier" for step in selector["steps"])
            ),
            None,
        )
        if barrier_selector is None:
            _fail("held cancellation has no frozen barrier selector")
        step = next(step for step in barrier_selector["steps"] if step.get("action") == "barrier")
        trace = _resource_order(
            resources,
            selector_id=barrier_selector["id"],
            step_ordinal=step["ordinal"],
        )
        required = ("barrier_reached", "caller_cancel_requested", "operation_finally")
        if any(item not in trace for item in required):
            _fail("held caller cancellation lacks associated barrier/cancel/finally witnesses")
        if not (
            trace["barrier_reached"]
            < trace["caller_cancel_requested"]
            < trace["operation_finally"]
        ):
            _fail("held caller cancellation reverses its declared public resource order")
        for raw in resources:
            resource = _mapping(raw, "resource")
            if (
                resource.get("selector_id") == barrier_selector["id"]
                and resource.get("step_ordinal") == step["ordinal"]
                and resource.get("type") in required
                and resource.get("instance") != barrier_selector["instance"]
            ):
                _fail("held resource witness instance differs from its consumed selector")
    elif name == "normal_postoperation_close":
        trace = _resource_order(resources)
        required = ("normal_client_close_started", "normal_client_close_completed")
        if any(item not in trace for item in required):
            _fail("normal post-operation close lacks public close witnesses")
        if trace["normal_client_close_started"] >= trace["normal_client_close_completed"]:
            _fail("normal client close reverses its public close order")
        for raw in resources:
            resource = _mapping(raw, "resource")
            if resource.get("type") in required and any(
                resource.get(field) is not None
                for field in ("selector_id", "step_ordinal", "instance")
            ):
                _fail("normal client-close witness must not claim a provider association")
    known_instances = {
        descriptor["instance"] for descriptor in _list(case.raw["descriptors"], "case.descriptors")
    }
    adapter_traces: dict[str, dict[str, int]] = {}
    for raw in resources:
        resource = _mapping(raw, "resource")
        kind = resource.get("type")
        if kind not in {"adapter_close_started", "adapter_close_completed"}:
            continue
        instance = resource.get("instance")
        if (
            instance not in known_instances
            or resource.get("selector_id") is not None
            or resource.get("step_ordinal") is not None
        ):
            _fail("adapter-close witness has no literal known provider association")
        trace = adapter_traces.setdefault(instance, {})
        trace[kind] = resource["order"]
    for trace in adapter_traces.values():
        if set(trace) != {"adapter_close_started", "adapter_close_completed"}:
            _fail("adapter-close witness lacks its local paired boundary")
        if trace["adapter_close_started"] >= trace["adapter_close_completed"]:
            _fail("adapter-close witness reverses its local boundary order")


def _script_failures(
    case: observation.Case, wires: list[Any]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Associate literal provider failures with their actual selected targets."""
    selectors = _case_selectors(case)
    failures: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in wires:
        wire = _mapping(raw, "wire")
        if wire.get("outcome") != "provider_failure":
            continue
        selector = selectors.get(_wire_key(wire))
        if selector is None:
            _fail("provider-failure wire has no frozen selector")
        ordinal = wire["step_ordinal"]
        step = next(item for item in selector["steps"] if item["ordinal"] == ordinal)
        if step.get("action") == "barrier":
            step = _mapping(step["continuation"], "barrier continuation")
        if step.get("action") != "provider_failure":
            _fail("provider-failure wire did not consume a literal failure step")
        target = _target_key(_mapping(wire["target"], "wire.target"))
        failures.setdefault(target, []).append(
            {
                "selector_id": selector["id"],
                "ordinal": ordinal,
                "failure": _failure_projection(case, _mapping(step["failure"], "step.failure")),
            }
        )
    for entries in failures.values():
        entries.sort(key=lambda entry: (entry["selector_id"], entry["ordinal"]))
    return failures


def _qualify_script_error_joins(
    case: observation.Case, value: dict[str, Any], wires: list[Any], runtime: str
) -> None:
    """Keep literal scripted diagnostics strict wherever public captures retain them."""
    by_target = _script_failures(case, wires)
    if not by_target:
        return

    def consume_surface(
        records: list[tuple[tuple[str, str], Mapping[str, Any]]], name: str
    ) -> None:
        """Consume literal failures once per public surface, preserving concurrent ambiguity."""
        remaining = {target: list(entries) for target, entries in by_target.items()}
        for target, error in records:
            matches = remaining.get(target, [])
            for index, entry in enumerate(matches):
                try:
                    _error_matches_literal(entry["failure"], error, runtime)
                except observation.ObservationError:
                    continue
                matches.pop(index)
                break
            else:
                _fail(f"{name} reuses, substitutes, or omits a consumed script failure")

    def check(target: Any, error: Any, where: str) -> None:
        if target is None or error is None:
            return
        key = _target_key(_mapping(target, f"{where}.target"))
        for entry in by_target.get(key, []):
            try:
                _error_matches_literal(
                    entry["failure"], _mapping(error, f"{where}.error"), runtime
                )
                return
            except observation.ObservationError:
                continue
        _fail(f"{where} error does not retain a consumed literal provider failure")

    operation = _mapping(value["operation"], "operation")
    attempts_by_target: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for attempt in _list(operation["attempts"], "operation.attempts"):
        attempt = _mapping(attempt, "operation.attempt")
        check(attempt.get("target"), attempt.get("error"), "operation.attempt")
        if attempt.get("target") is not None and attempt.get("error") is not None:
            target = _target_key(_mapping(attempt["target"], "operation.attempt.target"))
            attempts_by_target.setdefault(target, []).append(attempt)
    for target, attempts in attempts_by_target.items():
        entries = by_target.get(target, [])
        if len({entry["selector_id"] for entry in entries}) != 1:
            continue
        for index, attempt in enumerate(attempts):
            literal_index = len(entries) - 1 if len(attempts) == 1 else index
            if literal_index < len(entries):
                _error_matches_literal(
                    entries[literal_index]["failure"],
                    _mapping(attempt["error"], "operation.attempt.error"),
                    runtime,
                )
    consume_surface(
        [
            (
                _target_key(_mapping(attempt["target"], "operation.attempt.target")),
                _mapping(attempt["error"], "operation.attempt.error"),
            )
            for attempts in attempts_by_target.values()
            for attempt in attempts
        ],
        "canonical attempts",
    )
    telemetry_errors: dict[str, list[tuple[tuple[str, str], Mapping[str, Any]]]] = {}
    for event in _list(value["telemetry"], "telemetry"):
        event = _mapping(event, "telemetry")
        check(event.get("target") or event.get("from_target"), event.get("error"), "telemetry")
        event_target = event.get("target") or event.get("from_target")
        if event_target is not None and event.get("error") is not None:
            telemetry_errors.setdefault(_string(event["type"], "telemetry.type"), []).append(
                (
                    _target_key(_mapping(event_target, "telemetry.target")),
                    _mapping(event["error"], "telemetry.error"),
                )
            )
        if event.get("type") == "RetryScheduled" and event.get("error") is not None:
            target = _target_key(_mapping(event["target"], "RetryScheduled.target"))
            entries = by_target.get(target, [])
            selectors = {entry["selector_id"] for entry in entries}
            index = event["attempt"] - 1
            if len(selectors) == 1 and index < len(entries):
                _error_matches_literal(
                    entries[index]["failure"],
                    _mapping(event["error"], "RetryScheduled.error"),
                    runtime,
                )
    for event_type, records in telemetry_errors.items():
        consume_surface(records, f"{event_type} telemetry")
    manifest = value.get("manifest")
    if isinstance(manifest, dict):
        manifest_errors: list[tuple[tuple[str, str], Mapping[str, Any]]] = []
        for facet in _list(manifest.get("attempts"), "manifest.attempts"):
            facet = _mapping(facet, "manifest.attempt")
            error = facet.get("error")
            target = facet.get("target")
            if error is None or not isinstance(target, str) or ":" not in target:
                continue
            instance, model = target.split(":", 1)
            manifest_errors.append(((instance, model), _mapping(error, "manifest.attempt.error")))
            for entry in by_target.get((instance, model), []):
                try:
                    _error_matches_literal(
                        entry["failure"], _mapping(error, "manifest.attempt.error"), runtime
                    )
                    break
                except observation.ObservationError:
                    continue
            else:
                _fail("manifest attempt error does not retain a literal provider failure")
        consume_surface(manifest_errors, "manifest attempts")


def _qualify_events(
    case: observation.Case,
    value: dict[str, Any],
    operation: dict[str, Any],
    wire_targets: set[tuple[str, str]],
    runtime: str,
) -> None:
    events = _list(value.get("telemetry"), "value.telemetry")
    candidate_targets = {
        (descriptor["instance"], descriptor["model"])
        for descriptor in _list(case.raw["descriptors"], "case.descriptors")
    }
    literal_candidates = _literal_route_members(case)
    prior = 0
    kinds = []
    started: list[tuple[tuple[str, str], int]] = []
    request_started: dict[str, Any] | None = None
    for event in events:
        event = _mapping(event, "telemetry event")
        if event.get("request_relation") != "operation":
            _fail("retrieval telemetry must carry the operation request relation")
        order = event.get("order")
        if type(order) is not int or order <= prior:
            _fail("telemetry order must be strictly increasing within the operation")
        prior = order
        kinds.append(event.get("type"))
        for target_field in ("target", "from_target"):
            if target_field in event and event[target_field] is not None:
                target = _mapping(event[target_field], f"telemetry.{target_field}")
                target_name = _target_name(target)
                if (
                    _target_key(target) not in candidate_targets
                    or target_name not in literal_candidates
                ):
                    _fail("typed telemetry target is not a literal caller route candidate")
        event_type = event.get("type")
        if event_type == "RequestStarted":
            if request_started is not None:
                _fail("operation has more than one RequestStarted capture")
            if event.get("operation") != operation.get("kind"):
                _fail("RequestStarted operation differs from the canonical operation kind")
            request_started = event
        elif event_type == "AttemptStarted":
            target = _target_key(_mapping(event["target"], "AttemptStarted.target"))
            if target not in wire_targets:
                _fail("AttemptStarted target has no actual selected wire")
            started.append((target, event["attempt"]))
        elif event_type == "RetryScheduled":
            target = _target_key(_mapping(event["target"], "RetryScheduled.target"))
            if (target, event["attempt"]) not in started:
                _fail("RetryScheduled has no public AttemptStarted for its target and ordinal")
        elif event_type == "AttemptCompleted":
            target = _target_key(_mapping(event["target"], "AttemptCompleted.target"))
            if target not in wire_targets:
                _fail("AttemptCompleted target has no actual selected wire")
            if not any(previous == target for previous, _ in started):
                _fail("AttemptCompleted has no preceding public AttemptStarted for its target")
        elif event_type == "FallbackTriggered":
            target = _string(event["to_target"], "FallbackTriggered.to_target")
            if (
                tuple(target.split(":", 1)) not in candidate_targets
                or target not in literal_candidates
            ):
                _fail("FallbackTriggered target is not a literal caller route candidate")
        elif event_type == "RequestCompleted" and operation.get("outcome") == "ok":
            winner = _target_key(_mapping(operation["result"]["target"], "result.target"))
            completed = _target_key(_mapping(event["target"], "RequestCompleted.target"))
            if completed != winner:
                _fail("RequestCompleted target differs from the successful public result")
    if operation.get("outcome") == "cancelled":
        if "RequestCompleted" in kinds or "RequestFailed" in kinds:
            _fail("caller cancellation must not manufacture a terminal telemetry event")
    elif operation.get("outcome") == "ok":
        if "RequestCompleted" not in kinds:
            _fail("successful operation lacks RequestCompleted")
        if "RequestFailed" in kinds:
            _fail("successful operation must not manufacture RequestFailed")
    elif operation.get("outcome") == "error" and kinds and "RequestFailed" not in kinds:
        error = _mapping(operation["error"], "operation.error")
        config_type = "ConfigError" if runtime == "python" else "ConfigException"
        if error.get("runtime_type") != config_type:
            _fail("dispatched non-config failure lacks RequestFailed")
    if wire_targets:
        if request_started is None:
            _fail("wire progress lacks its actual RequestStarted capture")
        observed_targets = _list(request_started["targets"], "RequestStarted.targets")
        expected_names = {
            name
            for name in literal_candidates
            if name in {f"{instance}:{model}" for instance, model in candidate_targets}
        }
        if not set(observed_targets).issubset(expected_names):
            _fail("RequestStarted targets are not actual selected wire targets")
        if not _equal_literal(
            request_started.get("metadata"),
            case.raw["request"]["metadata"],
            "RequestStarted.metadata",
        ):
            _fail("RequestStarted metadata differs from the direct public request input")
    canonical_by_target: dict[tuple[str, str], int] = {}
    for raw_attempt in _list(operation["attempts"], "operation.attempts"):
        attempt = _mapping(raw_attempt, "operation.attempt")
        target = attempt.get("target")
        if target is None or attempt.get("outcome") == "skipped_unhealthy":
            continue
        key = _target_key(_mapping(target, "operation.attempt.target"))
        canonical_by_target[key] = canonical_by_target.get(key, 0) + 1
        if not any(started_target == key for started_target, _ in started):
            _fail("canonical operation attempt lacks its public AttemptStarted capture")
    for target, count in canonical_by_target.items():
        if count > sum(started_target == target for started_target, _ in started):
            _fail("canonical attempts reuse one public AttemptStarted capture")
    failed_events = [event for event in events if event.get("type") == "RequestFailed"]
    if operation.get("outcome") == "error":
        final_error = _mapping(operation["error"], "operation.error")
        config_type = "ConfigError" if runtime == "python" else "ConfigException"
        if final_error.get("runtime_type") == config_type and failed_events:
            _fail("final local Config refusal must not manufacture RequestFailed")
    if failed_events:
        if len(failed_events) != 1:
            _fail("operation has more than one RequestFailed terminal capture")
        batch_failures = value.get("batch_failures")
        terminal = _mapping(failed_events[0]["error"], "RequestFailed.error")
        config_type = "ConfigError" if runtime == "python" else "ConfigException"
        if terminal.get("runtime_type") == config_type:
            _fail("local Config refusal must not manufacture RequestFailed")
        failed_attempts = [
            attempt
            for attempt in _list(operation["attempts"], "operation.attempts")
            if isinstance(attempt, dict)
            and attempt.get("outcome") == "failed"
            and attempt.get("error") is not None
        ]
        expected_error: Any = None
        if isinstance(batch_failures, list):
            if failed_attempts:
                expected_error = failed_attempts[0]["error"]
        elif failed_attempts:
            expected_error = failed_attempts[-1]["error"]
        if expected_error is None:
            _fail("RequestFailed has no canonical failed-provider snapshot")
        if not _equal_literal(
            _mapping(failed_events[0]["error"], "RequestFailed.error"),
            _mapping(expected_error, "terminal source error"),
            "RequestFailed.error",
        ):
            _fail("RequestFailed snapshot differs from its canonical provider failure")


def _qualify_manifest_usage(result: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    """Join manifest usage to the shared public result fields without calculating cost."""
    captured = _mapping(result["usage"], "result.usage")
    facet = _mapping(manifest["usage"], "manifest.usage")
    for field in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "cost_usd",
        "search_units",
    ):
        if not _equal_literal(captured[field], facet[field], f"usage.{field}"):
            _fail("manifest usage differs from the canonical public result usage")


def _qualify_attempt_manifest_joins(value: dict[str, Any], case: observation.Case) -> None:
    """Join canonical attempts, terminal event, and manifest facets without replaying policy."""
    operation = _mapping(value["operation"], "operation")
    wires = _list(value["wires"], "wires")
    wire_targets = {
        _target_key(_mapping(wire["target"], "wire.target"))
        for wire in wires
        if isinstance(wire, dict)
    }
    attempts = _list(operation["attempts"], "operation.attempts")
    for raw in attempts:
        attempt = _mapping(raw, "operation.attempt")
        target = attempt.get("target")
        if (
            target is not None
            and attempt.get("outcome") != "skipped_unhealthy"
            and _target_key(_mapping(target, "operation.attempt.target")) not in wire_targets
        ):
            _fail("canonical attempt target has no actual wire")
    telemetry = _list(value["telemetry"], "telemetry")
    if operation.get("outcome") == "ok":
        result = _mapping(operation["result"], "operation.result")
        completed = [event for event in telemetry if event.get("type") == "RequestCompleted"]
        if len(completed) != 1:
            _fail("successful operation must retain one RequestCompleted event")
        completed_event = _mapping(completed[0], "RequestCompleted")
        if not _equal_literal(completed_event["usage"], result["usage"], "RequestCompleted.usage"):
            _fail("RequestCompleted usage differs from the public result usage")
        if not _equal_literal(
            completed_event["timing"], result["timing"], "RequestCompleted.timing"
        ):
            _fail("RequestCompleted timing differs from the public result timing")
    manifest = value.get("manifest")
    if not isinstance(manifest, dict):
        return
    route = _mapping(manifest["route"], "manifest.route")
    requested = _list(route["requested"], "manifest.route.requested")
    descriptor_names = {
        f"{descriptor['instance']}:{descriptor['model']}"
        for descriptor in _list(case.raw["descriptors"], "case.descriptors")
    }
    if not set(requested).issubset(descriptor_names):
        _fail("manifest requested route contains no frozen descriptor target")
    literal_members = _literal_route_members(case)
    if literal_members and not literal_members.intersection(requested):
        _fail("manifest requested route omits every direct caller route member")
    facets = _list(manifest["attempts"], "manifest.attempts")
    if len(facets) != len(attempts):
        _fail("manifest attempt facets do not join the canonical operation attempts")
    for attempt, facet in zip(attempts, facets, strict=True):
        attempt = _mapping(attempt, "operation.attempt")
        facet = _mapping(facet, "manifest.attempt")
        target = attempt.get("target")
        expected_target = (
            None if target is None else _target_name(_mapping(target, "operation.attempt.target"))
        )
        if facet["target"] != expected_target or facet["outcome"] != attempt["outcome"]:
            _fail("manifest attempt target or outcome differs from its canonical attempt")
        if not _equal_literal(facet["error"], attempt["error"], "manifest.attempt.error"):
            _fail("manifest attempt error differs from its canonical attempt")
        timing = attempt.get("timing")
        for field in ("first_token_ms", "total_ms"):
            expected = None if timing is None else timing[field]
            if not _equal_literal(facet[field], expected, f"manifest.attempt.{field}"):
                _fail("manifest attempt timing differs from its canonical attempt")
    if operation.get("outcome") == "ok":
        result = _mapping(operation["result"], "operation.result")
        timing = _mapping(result["timing"], "result.timing")
        manifest_timing = _mapping(manifest["timing"], "manifest.timing")
        for field in ("first_token_ms", "total_ms", "output_tokens_per_s", "phases"):
            if not _equal_literal(
                timing[field], manifest_timing[field], f"manifest.timing.{field}"
            ):
                _fail("manifest timing differs from the public result timing")
        if case.kind == "embedding" and not _equal_literal(
            result["space"], manifest["embedding_space"], "manifest.embedding_space"
        ):
            _fail("manifest embedding space differs from the public result space")
        if not _equal_literal(result["warnings"], manifest["notes"], "manifest.notes"):
            _fail("manifest notes differ from the ordered public result warnings")


def qualify_observation(
    case: observation.Case, observation_record: dict[str, Any], *, runtime: str
) -> None:
    """Reject one observation that cannot be justified by frozen literal input and captures."""
    if (
        observation_record.get("id") != case.identifier
        or observation_record.get("kind") != case.kind
        or observation_record.get("status") != "ok"
    ):
        _fail("observation identity/kind/status does not match its frozen input case")
    value = _mapping(observation_record.get("value"), "observation.value")
    if set(value) != {
        "operation",
        "factories",
        "wires",
        "telemetry",
        "ledger",
        "manifest",
        "resources",
        "batch_failures",
    }:
        _fail("retrieval value has unknown or missing public capture fields")
    _redacted_secret_check(case, value)
    _finite_capture_check(value)
    operation = _mapping(value["operation"], "operation")
    if operation.get("kind") != case.kind or operation.get("request_relation") != "operation":
        _fail("operation does not identify the input kind/request relation")
    outcome = operation.get("outcome")
    if outcome not in ("ok", "error", "cancelled"):
        _fail("operation outcome is invalid")
    if (outcome == "ok") != (operation.get("result") is not None) or (
        outcome != "ok" and operation.get("result") is not None
    ):
        _fail("operation result/outcome combination is impossible")
    if (outcome == "error") != (operation.get("error") is not None):
        _fail("operation error/outcome combination is impossible")
    selectors = _case_selectors(case)
    factories = _list(value["factories"], "factories")
    wires = _list(value["wires"], "wires")
    consumed: set[tuple[str, int]] = set()
    for raw_wire in wires:
        wire = _mapping(raw_wire, "wire")
        key = _wire_key(wire)
        selector = selectors.get(key)
        if selector is None:
            _fail("wire does not match a complete literal selector key")
        ordinal = wire.get("step_ordinal")
        steps = _list(selector.get("steps"), "selector.steps")
        step = next(
            (candidate for candidate in steps if candidate.get("ordinal") == ordinal), None
        )
        if step is None or not isinstance(step, dict):
            _fail("wire identifies an unknown literal selector step")
        marker = (selector["id"], ordinal)
        if marker in consumed:
            _fail("literal selector step was consumed more than once")
        consumed.add(marker)
        _wire_request_projection(case, wire, selector)
        _qualify_wire(case, wire, selector, step, runtime)
    expected = {
        (selector["id"], step["ordinal"])
        for selector in selectors.values()
        for step in selector["steps"]
    }
    if consumed != expected:
        _fail("literal script steps were missing or unconsumed")
    wire_targets = {
        _target_key(_mapping(raw_wire["target"], "wire.target"))
        for raw_wire in wires
        if isinstance(raw_wire, dict)
    }
    _qualify_events(case, value, operation, wire_targets, runtime)
    if outcome == "ok":
        result = _mapping(operation["result"], "operation.result")
        if _target_key(_mapping(result["target"], "result.target")) not in wire_targets:
            _fail("successful result target is not an actual selected wire target")
    _qualify_factories(case, factories, wires)
    _qualify_wire_orders(wires)
    if case.raw["procedure"]["name"] == "requested_unsupported_operation":
        kinds = [factory.get("type") for factory in factories if isinstance(factory, dict)]
        if kinds[:2] != ["factory_entered", "factory_returned"] or value["wires"]:
            _fail("requested unsupported operation must materialize before refusal without a wire")
    _qualify_script_error_joins(case, value, wires, runtime)
    _qualify_attempt_manifest_joins(value, case)
    resources = _list(value["resources"], "resources")
    _qualify_resource_joins(case, resources)
    ledger = value["ledger"]
    if case.raw["ledger"]:
        snapshots = _list(ledger, "ledger")
        labels = [snapshot.get("label") for snapshot in snapshots]
        expected_labels = ["before_call"]
        if case.raw["procedure"]["name"] == "caller_cancel_while_provider_held":
            expected_labels.append("while_provider_held")
        expected_labels.extend(("after_operation", "after_client_close"))
        if labels != expected_labels:
            _fail("ledger snapshots do not retain the declared local checkpoint order")
        before = _mapping(snapshots[0], "ledger.before_call")
        terminal = _mapping(snapshots[-2], "ledger.after_operation")
        closed = _mapping(snapshots[-1], "ledger.after_client_close")
        empty_totals = {
            "cost": "0",
            "currency": "USD",
            "requests": 0,
            "unknown_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
        }
        if before["reserved"] != "0" or not _equal_literal(
            before["totals"], empty_totals, "ledger.before_call.totals"
        ):
            _fail("fresh ledger before_call must retain public empty totals and zero reservation")
        if "while_provider_held" in labels:
            held = _mapping(snapshots[1], "ledger.while_provider_held")
            if not _equal_literal(
                held["totals"], empty_totals, "ledger.while_provider_held.totals"
            ):
                _fail("held ledger checkpoint must retain public empty totals")
        if (
            terminal["reserved"] != closed["reserved"]
            or terminal["reserved"] != before["reserved"]
        ):
            _fail("terminal ledger reservation does not return to its public baseline")
        if not _equal_literal(
            closed["totals"], terminal["totals"], "ledger.after_client_close.totals"
        ):
            _fail("ledger client close totals differ from the terminal operation totals")
        expected_totals = empty_totals
        if outcome == "ok":
            usage = _mapping(operation["result"]["usage"], "operation.result.usage")
            cost = usage["cost_usd"]
            expected_totals = {
                "cost": "0" if cost is None else cost,
                "currency": "USD",
                "requests": 1,
                "unknown_requests": 1 if cost is None else 0,
                "input_tokens": usage["input_tokens"] or 0,
                "output_tokens": usage["output_tokens"] or 0,
                "cache_read_tokens": usage["cache_read_tokens"] or 0,
            }
        if not _equal_literal(
            terminal["totals"], expected_totals, "ledger.after_operation.totals"
        ):
            _fail("terminal ledger totals do not causally project the public operation result")
    elif ledger is not None:
        _fail("non-ledger input case produced ledger evidence")
    manifest = value["manifest"]
    if manifest is not None:
        manifest = _mapping(manifest, "manifest")
        if manifest.get("request_relation") != "operation" or manifest.get("payloads") is not None:
            _fail("retrieval manifest violates request relation or null-payload boundary")
        if manifest.get("operation") != case.kind:
            _fail("manifest operation differs from the canonical retrieval operation")
        if outcome == "ok":
            resolved = _mapping(manifest["route"], "manifest.route").get("resolved")
            result = _mapping(operation["result"], "operation.result")
            winner = result["target"]
            if resolved != f"{winner['provider_id']}:{winner['model']}":
                _fail("successful manifest route does not resolve to the winning public target")
            _qualify_manifest_usage(result, manifest)


def _error_pair(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    python_type = left.get("runtime_type")
    native_type = right.get("runtime_type")
    return RUNTIME_TYPES.get(python_type) == native_type


def _compare_errors(left: Any, right: Any, path: str) -> str | None:
    if left is None or right is None:
        return None if left is right else f"{path} nullability differs"
    left = _mapping(left, path)
    right = _mapping(right, path)
    if not _error_pair(left, right):
        return f"{path}.runtime_type is not a finite runtime pair"
    for key in ("provider", "phase", "retryable", "http_status", "retry_after_s"):
        if (key in left or key in right) and not _equal_literal(
            left.get(key), right.get(key), f"{path}.{key}"
        ):
            return f"{path}.{key} differs"
    return None


def _compare_value(left: Any, right: Any, path: str = "value") -> str | None:
    local_timing = {"started_at", "first_token_ms", "total_ms", "output_tokens_per_s"}
    leaf = path.rsplit(".", 1)[-1]
    if _capture_order_slot(path):
        if type(left) is not int or type(right) is not int:
            return f"{path} must remain an integer capture counter"
        return None
    if (
        (leaf in local_timing and (".timing" in path or ".timing_facet" in path))
        or (path.startswith("value.manifest.attempts[") and leaf in {"first_token_ms", "total_ms"})
    ) and ".raw" not in path:
        if (left is None) != (right is None):
            return f"{path} presence differs"
        if left is not None:
            _finite(left, f"python {path}")
            _finite(right, f"native {path}")
        return None
    if _typed_error_slot(path) and isinstance(left, dict) and isinstance(right, dict):
        paired = _compare_errors(left, right, path)
        if paired:
            return paired
        ignored = {"runtime_type", "message", "detail", "hint", "category", "native_inner"}
        left = {key: value for key, value in left.items() if key not in ignored}
        right = {key: value for key, value in right.items() if key not in ignored}
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return f"{path} keys differ"
        for key in left:
            difference = _compare_value(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return f"{path} lengths differ"
        for index, (item, other) in enumerate(zip(left, right, strict=True)):
            difference = _compare_value(item, other, f"{path}[{index}]")
            if difference:
                return difference
        return None
    return _difference(left, right, path)


def compare_case(
    case: observation.Case, python: dict[str, Any], native: dict[str, Any]
) -> list[dict[str, Any]]:
    """Qualify both runtime records, then return bounded profile-local differences."""
    qualify_observation(case, python, runtime="python")
    qualify_observation(case, native, runtime="csharp")
    difference = _compare_value(
        _comparison_value(_mapping(python["value"], "python.value")),
        _comparison_value(_mapping(native["value"], "native.value")),
    )
    return [] if difference is None else [{"id": case.identifier, "difference": difference}]


def _run(command: list[str], *, cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def run_observers(
    inputs: Path, directory: Path, *, source_revision: str, source_dirty: bool
) -> tuple[Path, Path]:
    """Build a stamped native recorder and invoke both independent producers."""
    python_output, native_output = directory / "python.json", directory / "native.json"
    _run(
        [
            "dotnet",
            "build",
            "AnyInfer.Retrieval/AnyInfer.Retrieval.csproj",
            "--no-restore",
            f"-p:SourceRevisionId={source_revision}",
            f"-p:RetrievalSourceDirty={str(source_dirty).lower()}",
        ],
        cwd=CSHARP_ROOT,
    )
    _run(
        [sys.executable, str(PYTHON_OBSERVER), "--observe", str(inputs), str(python_output)],
        cwd=ROOT,
    )
    _run(
        [
            "dotnet",
            "run",
            "--no-build",
            "--no-restore",
            "--project",
            "AnyInfer.Retrieval",
            "--",
            str(inputs),
            str(native_output),
        ],
        cwd=CSHARP_ROOT,
    )
    return python_output, native_output


def read_observations(
    path: Path, *, cases: Sequence[observation.Case], runtime: str, digest: str
) -> observation.ObserverRun:
    """Schema-check and provenance-index one runtime's raw observation envelope."""
    raw_envelope = observation.read_json_bytes(path)
    _redacted_envelope_check(cases, raw_envelope)
    _validate_schema(
        path=OBSERVATION_SCHEMA,
        value=raw_envelope,
        label=f"{runtime} observation",
    )
    return observation.read_observations(
        path,
        profile=PROFILE,
        expected_cases=cases,
        expected_runtime=runtime,
        expected_corpus_sha256=digest,
        validate_observation=lambda record, _where: qualify_observation(
            next(case for case in cases if case.identifier == record["id"]),
            record,
            runtime=runtime,
        ),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse default orchestration or byte-preserving evidence comparison arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("PYTHON", "NATIVE"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Write a provenance-bound retrieval comparison report and return its status."""
    options = parse_args(sys.argv[1:] if argv is None else argv)
    input_path = options.input.resolve()
    raw_input = observation.read_json_bytes(input_path)
    _validate_schema(path=INPUT_SCHEMA, value=raw_input, label="retrieval input")
    _, cases = observation.read_cases(input_path, profile=PROFILE)
    digest = observation.corpus_sha256(input_path)
    if digest != FROZEN_CORPUS_SHA256:
        _fail("retrieval-v1 input bytes do not match the frozen corpus SHA-256")
    directory = observation.fresh_run_directory(options.output_root.resolve())
    identity: tuple[str, bool] | None = None
    if options.compare is None:
        identity = observation.source_identity()
        python_path, native_path = run_observers(
            input_path, directory, source_revision=identity[0], source_dirty=identity[1]
        )
    else:
        python_path, native_path = observation.copy_comparison_evidence(
            directory, *(path.resolve() for path in options.compare)
        )
    python = read_observations(python_path, cases=cases, runtime="python", digest=digest)
    native = read_observations(native_path, cases=cases, runtime="csharp", digest=digest)
    observation.validate_handshake(python, native, stamped_identity=identity)
    mismatches: list[dict[str, Any]] = []
    matched: list[str] = []
    for case in cases:
        differences = compare_case(
            case, python.observations[case.identifier], native.observations[case.identifier]
        )
        if differences:
            mismatches.extend(differences)
        else:
            matched.append(case.identifier)
    report = {
        "profile": PROFILE,
        "status": "pass" if not mismatches else "fail",
        "corpus_sha256": digest,
        "observers": {
            "python": {
                key: getattr(python, key)
                for key in ("runtime", "source_revision", "source_dirty", "corpus_sha256")
            },
            "native": {
                key: getattr(native, key)
                for key in ("runtime", "source_revision", "source_dirty", "corpus_sha256")
            },
        },
        "python_observation": str(python_path),
        "native_observation": str(native_path),
        "shared": {"matched": matched, "mismatches": mismatches},
        "runtime_specific": [],
        "native_only": [],
    }
    report_path = directory / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{report['status']}: {report_path}")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, observation.ObservationError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
