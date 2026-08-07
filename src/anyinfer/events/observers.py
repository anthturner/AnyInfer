"""Observer protocol and dispatch.

Observers are synchronous and must not block: dispatch happens inline on the request path.
An observer that raises is isolated — the exception is swallowed and warned about once per
observer, because a broken telemetry sink must never fail a generation.
"""

from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .telemetry import TelemetryEvent, strip_payloads

__all__ = ["EventDispatcher", "Observer", "Subscription"]


@runtime_checkable
class Observer(Protocol):
    """A telemetry sink.

    Implementations receive every event the client emits. Keep ``on_event`` fast and
    non-blocking; queue work elsewhere if it might be slow.
    """

    def on_event(self, event: TelemetryEvent) -> None:
        """Handle one telemetry event."""
        ...


@dataclass(slots=True)
class Subscription:
    """A registered observer and its privacy setting."""

    observer: Observer
    payloads: bool = False
    _warned: bool = False


class EventDispatcher:
    """Fan-out of telemetry events to registered observers.

    Thread-safe: the sync facade dispatches from a background loop thread while callers
    subscribe from their own.
    """

    def __init__(self, observers: list[Observer] | None = None) -> None:
        self._subs: list[Subscription] = [Subscription(o) for o in (observers or [])]
        self._lock = threading.Lock()

    def subscribe(self, observer: Observer, *, payloads: bool = False) -> None:
        """Register an observer.

        Args:
            observer: The sink to receive events.
            payloads: When ``True``, this observer receives prompt and response text.
                Defaults to ``False`` — telemetry is payload-free unless an observer
                explicitly opts in.
        """
        with self._lock:
            self._subs.append(Subscription(observer, payloads=payloads))

    def unsubscribe(self, observer: Observer) -> None:
        """Remove an observer. Unknown observers are ignored."""
        with self._lock:
            self._subs = [s for s in self._subs if s.observer is not observer]

    @property
    def has_observers(self) -> bool:
        """Whether any observer is registered, so callers can skip building events."""
        with self._lock:
            return bool(self._subs)

    @property
    def wants_payloads(self) -> bool:
        """Whether any observer opted into payloads, so callers can skip capturing text."""
        with self._lock:
            return any(s.payloads for s in self._subs)

    def emit(self, event: TelemetryEvent) -> None:
        """Deliver ``event`` to every observer, stripping payloads per subscription."""
        with self._lock:
            subs = list(self._subs)
        if not subs:
            return
        stripped: TelemetryEvent | None = None
        for sub in subs:
            if sub.payloads:
                payload = event
            else:
                if stripped is None:
                    stripped = strip_payloads(event)
                payload = stripped
            try:
                sub.observer.on_event(payload)
            except Exception as exc:  # noqa: BLE001 — observers must never break generation
                if not sub._warned:
                    sub._warned = True
                    warnings.warn(
                        f"observer {type(sub.observer).__name__} raised "
                        f"{type(exc).__name__}: {exc}; further errors from this observer "
                        "will be suppressed",
                        RuntimeWarning,
                        stacklevel=2,
                    )
