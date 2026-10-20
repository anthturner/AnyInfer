"""Pure structural validation for the input-only retrieval-v1 corpus.

This module validates fixture shape and finite cross-field references.  It deliberately does
not select routes, derive batches, predict retries, invoke an SDK, or inspect results.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from _csharp_observation import fail, require_mapping
from jsonschema import Draft202012Validator, SchemaError
from referencing.exceptions import Unresolvable

_GENERIC_PROCEDURES = {
    "limit_boundary",
    "route_precedence",
    "requested_unsupported_operation",
    "caller_cancel_while_provider_held",
    "spend_and_manifest",
    "normal_postoperation_close",
}
_EMPTY_SCRIPT_PROCEDURES = {
    "limit_boundary",
    "rerank_cross_batch",
    "spend_and_manifest",
    "requested_unsupported_operation",
}
_REFERENCE_KEYWORDS = ("$ref", "$dynamicRef", "$recursiveRef")
_SINGLE_SUBSCHEMA_KEYWORDS = (
    "additionalItems",
    "additionalProperties",
    "contains",
    "contentSchema",
    "else",
    "if",
    "items",
    "not",
    "propertyNames",
    "then",
    "unevaluatedItems",
    "unevaluatedProperties",
)
_ARRAY_SUBSCHEMA_KEYWORDS = ("allOf", "anyOf", "oneOf", "prefixItems")
_MAP_SUBSCHEMA_KEYWORDS = (
    "$defs",
    "definitions",
    "dependentSchemas",
    "patternProperties",
    "properties",
)


def validate_inputs(source: Any, schema: dict[str, Any]) -> None:
    """Validate one decoded retrieval-v1 corpus without changing its input values.

    Schema failures and semantic input faults raise :class:`ObservationError`; no inferred
    routing, chunking, retry, pricing, or output behavior is introduced here.
    """
    _reject_nonlocal_references(schema, "$schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        _fail("schema", error.message)

    try:
        validator = Draft202012Validator(schema)
        error = next(iter(validator.iter_errors(source)), None)
    except Unresolvable as error:
        _fail("schema", str(error))
    if error is not None:
        _fail(_json_path(error.absolute_path), error.message)
    _ensure_finite(source, "$")

    envelope = require_mapping(source, "retrieval input envelope")
    cases = envelope["cases"]
    if not isinstance(cases, list):
        _fail("$.cases", "must be an array")

    case_ids: set[str] = set()
    for index, raw_case in enumerate(cases):
        case = require_mapping(raw_case, f"$.cases[{index}]")
        identifier = case["id"]
        if identifier in case_ids:
            _fail(f"$.cases[{index}].id", f"duplicate case id {identifier!r}")
        case_ids.add(identifier)
        _validate_case(case, f"$.cases[{index}]")


def _validate_case(case: dict[str, Any], path: str) -> None:
    kind = case["kind"]
    request = require_mapping(case["request"], f"{path}.request")
    descriptors = case["descriptors"]
    scripts = case["scripts"]
    procedure = require_mapping(case["procedure"], f"{path}.procedure")
    procedure_name = procedure["name"]

    descriptor_facts = _descriptors(descriptors, f"{path}.descriptors")
    _validate_routes(case, descriptor_facts, path)
    _validate_request_kind(kind, request, procedure_name, f"{path}.request")
    _validate_documents(request, kind, f"{path}.request")
    _validate_scripts(
        scripts,
        kind,
        request,
        descriptor_facts,
        procedure_name,
        f"{path}.scripts",
    )


def _descriptors(
    raw_descriptors: Any, path: str
) -> dict[tuple[str, str], tuple[set[str], set[str]]]:
    if not isinstance(raw_descriptors, list):
        _fail(path, "must be an array")

    identifiers: set[str] = set()
    instances: set[str] = set()
    facts: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
    for index, raw_descriptor in enumerate(raw_descriptors):
        descriptor = require_mapping(raw_descriptor, f"{path}[{index}]")
        identifier = descriptor["id"]
        instance = descriptor["instance"]
        model = descriptor["model"]
        if identifier in identifiers:
            _fail(f"{path}[{index}].id", f"duplicate descriptor id {identifier!r}")
        if instance in instances:
            _fail(f"{path}[{index}].instance", f"duplicate descriptor instance {instance!r}")
        identifiers.add(identifier)
        instances.add(instance)
        declared = set(descriptor["operations"])
        runtime = set(descriptor["runtime_protocols"])
        missing = declared.difference(runtime)
        if missing:
            _fail(
                f"{path}[{index}].runtime_protocols",
                f"must include every declared operation: {', '.join(sorted(missing))}",
            )
        facts[(instance, model)] = (declared, runtime)
    return facts


def _validate_routes(
    case: dict[str, Any],
    descriptor_facts: Mapping[tuple[str, str], tuple[set[str], set[str]]],
    path: str,
) -> None:
    client = require_mapping(case["client"], f"{path}.client")
    route_names = ("default_route", "operation_route", "per_call_route")
    for name in route_names:
        route = client[name]
        if route is None:
            continue
        route_mapping = require_mapping(route, f"{path}.client.{name}")
        for index, target in enumerate(route_mapping["targets"]):
            _validate_target_reference(
                target, descriptor_facts, f"{path}.client.{name}.targets[{index}]"
            )

    target = client["per_call_target"]
    if target is not None:
        _validate_target_reference(target, descriptor_facts, f"{path}.client.per_call_target")


def _validate_target_reference(
    target: Any,
    descriptor_facts: Mapping[tuple[str, str], tuple[set[str], set[str]]],
    path: str,
) -> None:
    if not isinstance(target, str) or ":" not in target:
        _fail(path, "must reference a declared instance:model target")
    instance, model = target.split(":", 1)
    if (instance, model) not in descriptor_facts:
        _fail(path, f"does not reference a declared instance:model pair {target!r}")


def _validate_request_kind(kind: str, request: dict[str, Any], procedure: str, path: str) -> None:
    entry_point = request["entry_point"]
    if kind == "embedding" and entry_point not in {"embed_scalar", "embed_many"}:
        _fail(f"{path}.entry_point", "must be an embedding entry point")
    if kind == "rerank" and entry_point != "rerank":
        _fail(f"{path}.entry_point", "must be 'rerank'")

    if (
        (procedure == "capability_intent" or procedure.startswith("embedding_"))
        and procedure not in _GENERIC_PROCEDURES
        and kind != "embedding"
    ):
        _fail(f"{path}.procedure", f"procedure {procedure!r} requires embedding")
    if procedure in {"rerank_integrity", "rerank_cross_batch"} and kind != "rerank":
        _fail(f"{path}.procedure", f"procedure {procedure!r} requires rerank")
    if procedure == "embedding_scalar_order" and entry_point != "embed_scalar":
        _fail(f"{path}.entry_point", "embedding_scalar_order requires embed_scalar")


def _validate_documents(request: dict[str, Any], kind: str, path: str) -> None:
    if kind != "rerank":
        return
    identifiers: set[str] = set()
    for index, document in enumerate(request["documents"]):
        identifier = document["id"]
        if identifier in identifiers:
            _fail(f"{path}.documents[{index}].id", f"duplicate caller document id {identifier!r}")
        identifiers.add(identifier)


def _validate_scripts(
    raw_scripts: Any,
    kind: str,
    request: dict[str, Any],
    descriptor_facts: Mapping[tuple[str, str], tuple[set[str], set[str]]],
    procedure: str,
    path: str,
) -> None:
    if not isinstance(raw_scripts, list):
        _fail(path, "must be an array")
    if procedure == "requested_unsupported_operation":
        if raw_scripts:
            _fail(path, "requested_unsupported_operation requires empty scripts")
    elif not raw_scripts and procedure not in _EMPTY_SCRIPT_PROCEDURES:
        _fail(path, f"procedure {procedure!r} requires at least one selector")

    selector_ids: set[str] = set()
    step_ids: set[str] = set()
    gate_ids: set[str] = set()
    selector_keys: set[str] = set()
    barriers = 0
    caller_inputs = _embedding_inputs(request) if kind == "embedding" else None
    caller_documents = request.get("documents") if kind == "rerank" else None

    for index, raw_selector in enumerate(raw_scripts):
        selector = require_mapping(raw_selector, f"{path}[{index}]")
        identifier = selector["id"]
        if identifier in selector_ids:
            _fail(f"{path}[{index}].id", f"duplicate selector id {identifier!r}")
        selector_ids.add(identifier)
        if selector["operation"] != kind:
            _fail(f"{path}[{index}].operation", "must match the case kind")
        descriptor = descriptor_facts.get((selector["instance"], selector["model"]))
        if descriptor is None:
            _fail(f"{path}[{index}]", "must reference a declared selector instance:model pair")
        declared, runtime = descriptor
        if selector["operation"] not in declared or selector["operation"] not in runtime:
            _fail(
                f"{path}[{index}].operation",
                "must be declared and implemented by its selector descriptor",
            )

        key = _selector_key(selector)
        if key in selector_keys:
            _fail(
                f"{path}[{index}]",
                "duplicates a selector operation/instance/model/literal-slice key",
            )
        selector_keys.add(key)

        if kind == "embedding":
            _validate_embedding_slice(selector["slice"], caller_inputs, f"{path}[{index}].slice")
        else:
            _validate_rerank_slice(selector["slice"], caller_documents, f"{path}[{index}].slice")

        steps = selector["steps"]
        for ordinal, raw_step in enumerate(steps, start=1):
            step = require_mapping(raw_step, f"{path}[{index}].steps[{ordinal - 1}]")
            if step["ordinal"] != ordinal:
                _fail(
                    f"{path}[{index}].steps[{ordinal - 1}].ordinal",
                    "must be contiguous and supplied in order",
                )
            step_id = step["id"]
            if step_id in step_ids:
                _fail(f"{path}[{index}].steps[{ordinal - 1}].id", f"duplicate step id {step_id!r}")
            step_ids.add(step_id)
            barriers += _validate_step_kind(
                step, kind, gate_ids, f"{path}[{index}].steps[{ordinal - 1}]"
            )

    if procedure == "caller_cancel_while_provider_held":
        if barriers != 1:
            _fail(path, "caller_cancel_while_provider_held requires exactly one barrier")
    elif barriers:
        _fail(path, "barriers are limited to caller_cancel_while_provider_held")


def _embedding_inputs(request: dict[str, Any]) -> list[str]:
    return [request["input"]] if request["entry_point"] == "embed_scalar" else request["inputs"]


def _validate_embedding_slice(slice_value: Any, inputs: list[str], path: str) -> None:
    slice_mapping = require_mapping(slice_value, path)
    values = slice_mapping["inputs"]
    size = len(values)
    if not any(inputs[start : start + size] == values for start in range(len(inputs) - size + 1)):
        _fail(path, "must be a contiguous ordered slice of caller embedding inputs")


def _validate_rerank_slice(slice_value: Any, documents: Any, path: str) -> None:
    slice_mapping = require_mapping(slice_value, path)
    previous = -1
    seen: set[int] = set()
    for index, item in enumerate(slice_mapping["documents"]):
        wire = require_mapping(item, f"{path}.documents[{index}]")
        original = wire["index"]
        if original in seen or original <= previous:
            _fail(
                f"{path}.documents[{index}].index",
                "must be unique and preserve caller document order",
            )
        if (
            original < 0
            or original >= len(documents)
            or documents[original]["text"] != wire["text"]
        ):
            _fail(
                f"{path}.documents[{index}]",
                "must reference its original caller document index and text",
            )
        seen.add(original)
        previous = original


def _validate_step_kind(step: dict[str, Any], kind: str, gates: set[str], path: str) -> int:
    action = step["action"]
    if action == "embedding_response" and kind != "embedding":
        _fail(f"{path}.action", "embedding_response requires an embedding selector")
    if action == "rerank_response" and kind != "rerank":
        _fail(f"{path}.action", "rerank_response requires a rerank selector")
    if action != "barrier":
        return 0

    continuation = require_mapping(step["continuation"], f"{path}.continuation")
    _validate_step_kind(continuation, kind, gates, f"{path}.continuation")
    gate = require_mapping(step["gate"], f"{path}.gate")
    local: set[str] = set()
    for name in ("readiness", "release", "finally_cleanup"):
        identifier = gate[name]
        if identifier in local or identifier in gates:
            _fail(f"{path}.gate.{name}", f"duplicate gate id {identifier!r}")
        local.add(identifier)
        gates.add(identifier)
    return 1


def _selector_key(selector: Mapping[str, Any]) -> str:
    return json.dumps(
        [selector["operation"], selector["instance"], selector["model"], selector["slice"]],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _reject_nonlocal_references(schema: Any, path: str) -> None:
    if not isinstance(schema, Mapping):
        return
    for keyword in _REFERENCE_KEYWORDS:
        if keyword in schema:
            reference = schema[keyword]
            if not isinstance(reference, str) or not reference.startswith("#"):
                _fail(f"{path}.{keyword}", "must be a local fragment reference")

    for keyword in _SINGLE_SUBSCHEMA_KEYWORDS:
        if keyword in schema:
            _reject_nonlocal_references(schema[keyword], f"{path}.{keyword}")
    for keyword in _ARRAY_SUBSCHEMA_KEYWORDS:
        if keyword in schema and isinstance(schema[keyword], list):
            for index, child in enumerate(schema[keyword]):
                _reject_nonlocal_references(child, f"{path}.{keyword}[{index}]")
    for keyword in _MAP_SUBSCHEMA_KEYWORDS:
        if keyword in schema and isinstance(schema[keyword], Mapping):
            for name, child in schema[keyword].items():
                _reject_nonlocal_references(child, f"{path}.{keyword}.{name}")

    dependencies = schema.get("dependencies")
    if isinstance(dependencies, Mapping):
        for name, child in dependencies.items():
            if isinstance(child, (Mapping, bool)):
                _reject_nonlocal_references(child, f"{path}.dependencies.{name}")


def _ensure_finite(value: Any, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _fail(path, "contains a non-finite JSON number")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _ensure_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _ensure_finite(child, f"{path}[{index}]")


def _json_path(parts: Iterable[Any]) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _fail(path: str, message: str) -> None:
    diagnostic = f"{path}: {message}"
    fail(diagnostic[:768])
