"""JSON extraction and client-side validation.

Validation is always against the *original* schema, whatever mechanism produced the text,
even when a provider uses grammar-constrained decoding. Extraction is deliberately forgiving:
models wrap JSON in code fences and prose even when told not to, but validation is not.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import jsonschema

from ._capture import _ACTIVE, Issue, _freeze, record_assessment

__all__ = ["MAX_REPORTED_ERRORS", "extract_json", "format_errors", "validate"]
MAX_REPORTED_ERRORS = 5
"""Validation errors included in a repair prompt or raised error, most-relevant first."""
_OPENERS = {"{": "}", "[": "]"}


def _record_extraction(rule: str, message: str) -> None:
    operation = _ACTIVE.get()
    if operation is not None:
        try:
            issue = Issue(rule, None, None, _freeze({}))
            selected_native = ({"rule": rule, "message": message},)
        except Exception:  # noqa: BLE001 - observation construction is non-semantic
            operation.evidence_available = False
            return
        record_assessment(
            kind="extraction",
            issues=(issue,),
            native_messages=(message,),
            selected_native=selected_native,
        )


def extract_json(text: str) -> tuple[Any, str | None]:
    """Pull a JSON value out of model output.

    Tries, in order: the whole string; then the first balanced ``{...}`` or ``[...]``
    substring, scanning while respecting string literals and escapes so that a brace inside a
    string does not end the scan.

    Args:
        text: Raw model output, possibly fenced or surrounded by prose.

    Returns:
        A ``(value, error)`` pair. On success ``error`` is ``None``; on failure ``value`` is
        ``None`` and ``error`` describes why.
    """
    stripped = text.strip()
    if not stripped:
        error = "response was empty"
        _record_extraction("response_empty", error)
        return None, error
    try:
        return json.loads(stripped), None
    except ValueError:
        pass
    candidate = _first_balanced(stripped)
    if candidate is None:
        error = "response was not JSON and contained no JSON object or array"
        _record_extraction("no_json_candidate", error)
        return None, error
    try:
        return json.loads(candidate), None
    except ValueError as exc:
        error = f"response contained malformed JSON: {exc}"
        _record_extraction("malformed_json_candidate", error)
        return None, error


def _first_balanced(text: str) -> str | None:
    """Return the first balanced ``{...}``/``[...]`` region, or ``None``."""
    start = -1
    closer = ""
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if start == -1:
            if char in _OPENERS:
                start, closer, depth = index, _OPENERS[char], 1
            continue
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = in_string
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == text[start]:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def validate(value: Any, schema: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate ``value`` against ``schema``.

    Args:
        value: The parsed JSON value.
        schema: The canonical JSON Schema.

    Returns:
        A tuple of human-readable error messages, empty when the value is valid. At most
        `MAX_REPORTED_ERRORS` are returned, ordered by schema depth so the most
        specific problems come first.
    """
    validator_cls = jsonschema.validators.validator_for(dict(schema))
    try:
        validator_cls.check_schema(dict(schema))
    except jsonschema.SchemaError as exc:
        message = f"the supplied JSON Schema is itself invalid: {exc.message}"
        operation = _ACTIVE.get()
        if operation is not None:
            try:
                issue = Issue("invalid_schema", None, tuple(exc.path), _freeze({}))
                selected_native = ({"input_path": tuple(exc.path), "message": exc.message},)
            except Exception:  # noqa: BLE001 - observation construction is non-semantic
                operation.evidence_available = False
                return (message,)
            record_assessment(
                kind="invalid_schema",
                issues=(issue,),
                native_messages=(message,),
                selected_native=selected_native,
                schema_error_input_path=tuple(exc.path),
            )
        return (message,)
    validator = validator_cls(dict(schema))
    active = _ACTIVE.get()
    if active is None:
        errors = sorted(validator.iter_errors(value), key=jsonschema.exceptions.relevance)
        return tuple(_describe(error) for error in errors[:MAX_REPORTED_ERRORS])
    enumerated = list(enumerate(validator.iter_errors(value)))
    selected = sorted(enumerated, key=lambda item: jsonschema.exceptions.relevance(item[1]))[
        :MAX_REPORTED_ERRORS
    ]
    messages = tuple(_describe(error) for _, error in selected)
    try:
        required_properties = _required_properties(enumerated)
        issues = tuple(
            _issue(error, required_properties.get(ordinal)) for ordinal, error in selected
        )
        native = tuple(
            {
                "pre_sort_ordinal": ordinal,
                "group": (tuple(error.absolute_path), tuple(error.absolute_schema_path)),
                "selected_order": selected_order,
                "validator": error.validator,
                "validator_value": error.validator_value,
                "instance_path": tuple(error.absolute_path),
                "schema_path": tuple(error.absolute_schema_path),
            }
            for selected_order, (ordinal, error) in enumerate(selected)
        )
        record_assessment(
            kind="validation", issues=issues, native_messages=messages, selected_native=native
        )
    except Exception:  # noqa: BLE001 - portable projection is observation-only
        active.evidence_available = False
    return messages


def _required_properties(
    enumerated: list[tuple[int, jsonschema.ValidationError]],
) -> dict[int, str]:
    counters: dict[tuple[tuple[Any, ...], tuple[Any, ...], int], int] = {}
    associated: dict[int, str] = {}
    for ordinal, error in enumerated:
        if (
            error.validator != "required"
            or not isinstance(error.validator_value, list)
            or not isinstance(error.instance, Mapping)
        ):
            continue
        missing = [name for name in error.validator_value if name not in error.instance]
        group = (
            tuple(error.absolute_path),
            tuple(error.absolute_schema_path),
            id(error.validator_value),
        )
        index = counters.get(group, 0)
        if index < len(missing):
            associated[ordinal] = missing[index]
        counters[group] = index + 1
    return associated


def _actual_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "integer" if value.is_integer() else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _issue(error: jsonschema.ValidationError, required_property: str | None) -> Issue:
    rule = str(error.validator)
    if rule == "type":
        params: dict[str, Any] = {
            "expected": error.validator_value,
            "actual": _actual_type(error.instance),
        }
    elif rule == "required":
        params = {"property": required_property}
    elif rule == "additionalProperties":
        properties = (
            error.schema.get("properties", {}) if isinstance(error.schema, Mapping) else {}
        )
        params = {
            "unexpected": sorted(
                (key for key in error.instance if key not in properties),
                key=lambda name: [ord(char) for char in name],
            )
        }
    elif rule == "enum":
        params = {"allowed": error.validator_value}
    elif rule == "const":
        params = {"expected": error.validator_value}
    elif rule in {"minimum", "maximum"}:
        params = {"limit": error.validator_value, "actual": error.instance}
    elif rule in {"minLength", "maxLength", "minItems", "maxItems"}:
        params = {"limit": error.validator_value, "actual": len(error.instance)}
    else:
        params = {}
    return Issue(
        rule, tuple(error.absolute_path), tuple(error.absolute_schema_path), _freeze(params)
    )


def _describe(error: jsonschema.ValidationError) -> str:
    path = "".join(
        f"[{segment}]" if isinstance(segment, int) else f".{segment}"
        for segment in error.absolute_path
    )
    return f"{path.lstrip('.') or '<root>'}: {error.message}"


def format_errors(errors: tuple[str, ...]) -> str:
    """Render validation errors as a bulleted list for a repair prompt."""
    return "\n".join(f"- {error}" for error in errors)
