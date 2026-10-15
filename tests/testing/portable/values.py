"""Literal JSON value and expected-message helpers for the portable driver."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any


class ValueDomainError(ValueError):
    """A value lies outside the portable ordinary-JSON domain."""


class MissingEvidenceError(RuntimeError):
    """A required native observation was not captured."""


_INT_LIMIT = 2**63
_MIXED_EXACT_LIMIT = 2**53
_PROMPT = "Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n"


def json_value(value: Any) -> Any:
    """Normalize immutable capture containers to literal JSON containers."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueDomainError("JSON object keys must be strings")
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    raise ValueDomainError(f"not an ordinary JSON value: {type(value).__name__}")


def ensure_value_domain(value: Any) -> None:
    """Require one ordinary JSON value in the bounded v0 decoding domain."""
    value = json_value(value)
    if isinstance(value, int) and not isinstance(value, bool):
        if not -_INT_LIMIT <= value <= _INT_LIMIT:
            raise ValueDomainError("integer outside ±2^63")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueDomainError("non-finite float")
    elif isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueDomainError("lone surrogate")
    elif isinstance(value, list):
        for item in value:
            ensure_value_domain(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            ensure_value_domain(key)
            ensure_value_domain(item)


def type_aware_equal(left: Any, right: Any) -> bool:
    """Compare ordinary JSON without erasing Python's bool, numeric, or zero types."""
    left, right = json_value(left), json_value(right)
    ensure_value_domain(left)
    ensure_value_domain(right)
    if type(left) is not type(right):
        return False
    if isinstance(left, float):
        return left == right and (
            left != 0.0 or math.copysign(1.0, left) == math.copysign(1.0, right)
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            type_aware_equal(a, b) for a, b in zip(left, right, strict=False)
        )
    if isinstance(left, dict):
        return bool(
            left.keys() == right.keys()
            and all(type_aware_equal(left[key], right[key]) for key in left)
        )
    return bool(left == right)


def schema_equal(left: Any, right: Any) -> bool:
    """Compare ordinary JSON using the numeric equality used by JSON Schema."""
    left, right = json_value(left), json_value(right)
    ensure_value_domain(left)
    ensure_value_domain(right)
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, int) != isinstance(right, int) and (
            abs(left) > _MIXED_EXACT_LIMIT or abs(right) > _MIXED_EXACT_LIMIT
        ):
            raise ValueDomainError("mixed integer/float equality beyond 2^53 is deferred")
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            schema_equal(a, b) for a, b in zip(left, right, strict=False)
        )
    if isinstance(left, dict):
        return bool(
            left.keys() == right.keys()
            and all(schema_equal(left[key], right[key]) for key in left)
        )
    return bool(left == right)


def control_number_equal(left: Any, right: Any) -> bool:
    """Compare values only at a runner-declared numeric control position."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    ensure_value_domain(left)
    ensure_value_domain(right)
    if isinstance(left, int) != isinstance(right, int) and (
        abs(left) > _MIXED_EXACT_LIMIT or abs(right) > _MIXED_EXACT_LIMIT
    ):
        raise ValueDomainError("mixed integer/float equality beyond 2^53 is deferred")
    return left == right


def schema_prompt(schema: Mapping[str, Any]) -> str:
    """Render the fixed v0 prompt instruction and canonical schema JSON."""
    literal = json_value(schema)
    if not isinstance(literal, dict):
        raise ValueDomainError("schema must be an object")
    ensure_value_domain(literal)
    _check_schema_numbers(literal)
    return _PROMPT + json.dumps(
        literal, ensure_ascii=True, sort_keys=True, indent=2, separators=(",", ": ")
    )


def _check_schema_numbers(value: Any) -> None:
    if isinstance(value, float):
        decimal = Decimal(str(value))
        if abs(value) >= 10**15 or (
            not value.is_integer() and -int(decimal.as_tuple().exponent) > 3
        ):
            raise ValueDomainError("schema number outside v0 rendering bound")
    elif isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 10**15:
        raise ValueDomainError("schema number outside v0 rendering bound")
    elif isinstance(value, list):
        for item in value:
            _check_schema_numbers(item)
    elif isinstance(value, dict):
        for item in value.values():
            _check_schema_numbers(item)


def feedback_bullets(messages: Sequence[str]) -> str:
    """Format native assessment messages without altering their text or multiplicity."""
    if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
        raise ValueDomainError("native messages must be a sequence of strings")
    if not all(isinstance(message, str) for message in messages):
        raise ValueDomainError("native messages must be strings")
    return "\n".join(f"- {message}" for message in messages)


def expand_segments(
    segments: str | list[Any],
    *,
    schema: Mapping[str, Any] | None = None,
    native_messages: Sequence[str] | None = None,
) -> str:
    """Expand explicitly typed expected-message placeholders only."""
    if isinstance(segments, str):
        return segments
    if not isinstance(segments, list):
        raise ValueDomainError("expected-message segments must be a string or list")
    result: list[str] = []
    for segment in segments:
        if isinstance(segment, str):
            result.append(segment)
        elif (
            isinstance(segment, dict)
            and len(segment) == 1
            and segment.get("$schema_prompt") is True
        ):
            if schema is None:
                raise MissingEvidenceError("schema prompt needs schema")
            result.append(schema_prompt(schema))
        elif (
            isinstance(segment, dict)
            and len(segment) == 1
            and segment.get("$repair_feedback") is True
        ):
            if not native_messages:
                raise MissingEvidenceError("repair feedback needs native messages")
            result.append(feedback_bullets(native_messages))
        else:
            raise ValueDomainError("unknown expected-message segment")
    return "".join(result)


def coalesce_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge only adjacent text events, copying all returned records."""
    result: list[dict[str, Any]] = []
    for event in events:
        copy = dict(event)
        if (
            set(copy) == {"text"}
            and isinstance(copy["text"], str)
            and result
            and set(result[-1]) == {"text"}
            and isinstance(result[-1]["text"], str)
        ):
            result[-1]["text"] += copy["text"]
        else:
            result.append(copy)
    return result
