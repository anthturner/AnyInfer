"""Per-provider schema projection.

Some engines compile JSON Schema to a constrained grammar and choke on constructs that are
cheap for a validator but expensive for a grammar — notably string length bounds and very
large array bounds, which become enormous repetition rules. Projection strips those *for the
wire only*: the original schema always validates the response client-side, so stripping a
constraint here never weakens the contract the caller gets.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

__all__ = ["ITEM_LIMIT_THRESHOLD", "identity_projection", "repetition_safe_projection"]

ITEM_LIMIT_THRESHOLD = 2000
"""``minItems``/``maxItems`` at or above this are dropped — grammar repetition blows up."""

_LENGTH_KEYS = ("minLength", "maxLength")
_ITEM_KEYS = ("minItems", "maxItems")


def identity_projection(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Send the schema unchanged. The default for providers with a real validator."""
    return schema


def repetition_safe_projection(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Strip grammar-hostile constraints.

    Drops ``minLength``/``maxLength`` everywhere, and ``minItems``/``maxItems`` whose value is
    at least `ITEM_LIMIT_THRESHOLD`. Used by the Ollama and llama.cpp adapters, whose
    structured output is grammar-compiled.

    Args:
        schema: The canonical schema.

    Returns:
        A deep copy with the offending keywords removed.
    """
    stripped = copy.deepcopy(dict(schema))
    _strip(stripped)
    return stripped


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        for key in _LENGTH_KEYS:
            node.pop(key, None)
        for key in _ITEM_KEYS:
            value = node.get(key)
            if isinstance(value, int) and value >= ITEM_LIMIT_THRESHOLD:
                node.pop(key, None)
        for key, value in list(node.items()):
            node[key] = _strip(value)
        return node
    if isinstance(node, list):
        return [_strip(item) for item in node]
    return node
