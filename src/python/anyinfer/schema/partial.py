"""Deterministic recovery of complete top-level members from truncated JSON objects."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..redaction import redact

__all__ = ["partial_object"]


def partial_object(
    text: str, schema: Mapping[str, Any]
) -> tuple[Mapping[str, Any] | None, tuple[str, ...]]:
    """Return only fully received top-level members and required names still absent.

    Nothing is inferred and no model is called. An incomplete member is discarded; a
    complete member is decoded exactly as ordinary JSON would decode it. The returned
    mapping is deliberately not schema-validated, because it is evidence attached to an
    error rather than an answer.
    """
    start = text.find("{")
    if start < 0:
        return None, _required(schema)
    body = text[start + 1 :]
    segments: list[str] = []
    segment_start = 0
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(body):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            if char == "}" and depth == 0:
                segments.append(body[segment_start:index])
                break
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            segments.append(body[segment_start:index])
            segment_start = index + 1
    # With no comma or object close, the final member is never accepted: a scalar that
    # currently reads ``12`` may have been cut from ``1230``. There is no honest way to
    # distinguish those cases, so only delimiter-confirmed members survive.

    recovered: dict[str, Any] = {}
    for segment in segments:
        candidate = segment.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads("{" + candidate + "}")
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict) and len(parsed) == 1:
            key, value = next(iter(parsed.items()))
            recovered[str(key)] = _redact_value(value)
    missing = tuple(name for name in _required(schema) if name not in recovered)
    return (recovered or None), missing


def _required(schema: Mapping[str, Any]) -> tuple[str, ...]:
    raw = schema.get("required")
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw if isinstance(item, str))


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_value(item) for key, item in value.items()}
    return value
