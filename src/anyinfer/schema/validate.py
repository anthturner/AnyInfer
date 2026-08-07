"""JSON extraction and client-side validation.

Validation is always against the *original* schema, whatever mechanism produced the text,
even when a provider uses grammar-constrained decoding. Extraction is deliberately forgiving:
models wrap JSON in code fences and prose even when told not to — but validation is not.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import jsonschema

__all__ = [
    "MAX_REPORTED_ERRORS",
    "extract_json",
    "format_errors",
    "validate",
]

MAX_REPORTED_ERRORS = 5
"""Validation errors included in a repair prompt or raised error, most-relevant first."""

_OPENERS = {"{": "}", "[": "]"}


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
        return None, "response was empty"

    try:
        return json.loads(stripped), None
    except ValueError:
        pass

    candidate = _first_balanced(stripped)
    if candidate is None:
        return None, "response was not JSON and contained no JSON object or array"
    try:
        return json.loads(candidate), None
    except ValueError as exc:
        return None, f"response contained malformed JSON: {exc}"


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
                start = index
                closer = _OPENERS[char]
                depth = 1
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
        return (f"the supplied JSON Schema is itself invalid: {exc.message}",)

    validator = validator_cls(dict(schema))
    errors = sorted(validator.iter_errors(value), key=jsonschema.exceptions.relevance)
    return tuple(_describe(e) for e in errors[:MAX_REPORTED_ERRORS])


def _describe(error: jsonschema.ValidationError) -> str:
    path = "".join(
        f"[{p}]" if isinstance(p, int) else f".{p}" for p in error.absolute_path
    )
    location = path.lstrip(".") or "<root>"
    return f"{location}: {error.message}"


def format_errors(errors: tuple[str, ...]) -> str:
    """Render validation errors as a bulleted list for a repair prompt."""
    return "\n".join(f"- {e}" for e in errors)
