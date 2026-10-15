"""Short-TTL health cache backing the router's health gate.

The gate exists to stop a dead endpoint from costing every request its full timeout before
falling through. It is deliberately memory-only and short-lived: a stale "unhealthy" verdict
is worse than an extra failed attempt, so entries expire quickly and a target is never
suppressed permanently.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..types.requests import ResolvedTarget

__all__ = ["HealthCache"]


@dataclass(frozen=True, slots=True)
class _Entry:
    failed_at: float
    detail: str


class HealthCache:
    """Records recent target failures, with a caller-supplied TTL."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._clock = clock or time.monotonic

    def mark_failed(self, target: ResolvedTarget, detail: str = "") -> None:
        """Record that a target just failed in a way that suggests it is unavailable."""
        with self._lock:
            self._entries[str(target)] = _Entry(self._clock(), detail)

    def mark_healthy(self, target: ResolvedTarget) -> None:
        """Clear any recorded failure for a target."""
        with self._lock:
            self._entries.pop(str(target), None)

    def recently_failed(self, target: ResolvedTarget, ttl_s: float) -> bool:
        """Whether this target failed within the last ``ttl_s`` seconds."""
        key = str(target)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if self._clock() - entry.failed_at >= ttl_s:
                del self._entries[key]
                return False
            return True

    def clear(self) -> None:
        """Forget every recorded failure."""
        with self._lock:
            self._entries.clear()
