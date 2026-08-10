"""Shared arithmetic for usage from distinct paid calls."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .types.results import Usage

__all__ = ["merge_usage"]


def merge_usage(usages: Iterable[Usage]) -> Usage:
    """Sum distinct calls, preserving ``None`` when neither side reported a field."""
    total = Usage()
    for usage in usages:
        total = Usage(
            input_tokens=_add(total.input_tokens, usage.input_tokens),
            output_tokens=_add(total.output_tokens, usage.output_tokens),
            total_tokens=_add(total.total_tokens, usage.total_tokens),
            cache_read_tokens=_add(total.cache_read_tokens, usage.cache_read_tokens),
            cache_write_tokens=_add(total.cache_write_tokens, usage.cache_write_tokens),
            reasoning_tokens=_add(total.reasoning_tokens, usage.reasoning_tokens),
            cost_usd=_add(total.cost_usd, usage.cost_usd),
        )
    return total


def _add(current: Any, incoming: Any) -> Any:
    """Add optional numbers, keeping ``None`` when neither side reported."""
    if current is None:
        return incoming
    if incoming is None:
        return current
    return current + incoming
