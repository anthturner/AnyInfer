"""Ready-made telemetry sinks: structured lines to `logging`, or JSONL to a file.

`observers.py` ships the protocol and the dispatcher and stops there, which left every
consumer writing the same forty lines to get events onto disk or into their log stream.
These are those forty lines, once.

Both sinks are **content-free by default**, and not by their own effort: the dispatcher
strips payload-carrying fields per subscription before an observer ever sees them, so a
sink registered without ``payloads=True`` cannot emit prompt or response text even if it
tried. Every string that does go out passes through `anyinfer.redaction.redact`, so a
credential that reached an event field cannot reach the file.

Neither sink is a substitute for the OpenTelemetry bridge (`anyinfer.otel`), which
produces spans and metrics a backend can aggregate. These produce a record you can `tail`,
`grep`, and ship — the thing you want at three in the morning.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..redaction import redact
from .telemetry import TelemetryEvent

__all__ = [
    "DEFAULT_LOGGER_NAME",
    "JsonlObserver",
    "LoggingObserver",
    "event_to_dict",
]

DEFAULT_LOGGER_NAME = "anyinfer.telemetry"
"""Logger `LoggingObserver` uses when the caller does not supply one."""


def _json_safe(value: Any) -> Any:
    """Convert one event field into something `json.dumps` accepts.

    Redaction is applied to every string on the way through, including strings nested in
    tuples, mappings, and sub-dataclasses like `ResolvedTarget` — a secret that reached a
    field is a secret wherever in the structure it sits.
    """
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Decimal):
        # Serialized as a string, not a float: these are money, and a float would quietly
        # round a value the ledger tracks exactly.
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_safe(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Path):
        return redact(str(value))
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_safe(v) for v in value]
    return redact(str(value))


def event_to_dict(event: TelemetryEvent) -> dict[str, Any]:
    """Render one event as a JSON-safe mapping, redacted.

    The event's type name lands under ``event``; every field keeps its own name. Shared by
    both sinks, and useful on its own for a caller writing a third one.
    """
    payload: dict[str, Any] = {"event": type(event).__name__}
    for field in dataclasses.fields(event):
        payload[field.name] = _json_safe(getattr(event, field.name))
    return payload


class LoggingObserver:
    """Emit each event as a structured record on a stdlib `logging.Logger`.

    The message is the event name; the full mapping is attached as an ``anyinfer_event``
    record attribute, so a JSON log formatter can render it while a plain formatter still
    prints something readable.

    Args:
        logger: Where to log. Defaults to a logger named `DEFAULT_LOGGER_NAME`.
        level: Level to log every event at. One level for all of them on purpose —
            severity is the *application's* judgement, and a library that logs some events
            at ``WARNING`` decides that for you.

    Example:
        >>> import logging
        >>> logging.basicConfig(level=logging.INFO)
        >>> observer = LoggingObserver()
        >>> client.subscribe(observer)  # doctest: +SKIP
    """

    def __init__(self, logger: logging.Logger | None = None, *, level: int = logging.INFO):
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)
        self._level = level

    def on_event(self, event: TelemetryEvent) -> None:
        """Log one event. Never raises."""
        if not self._logger.isEnabledFor(self._level):
            return
        payload = event_to_dict(event)
        self._logger.log(
            self._level,
            "%s",
            payload["event"],
            extra={"anyinfer_event": payload},
        )


class JsonlObserver:
    """Append each event to a file as one JSON object per line.

    Opened once and held open, because reopening per event turns a telemetry sink into
    the slowest thing on the request path. Writes are locked: the sync facade dispatches
    from its background loop thread while the caller's own thread may be subscribing.

    Args:
        path: File to append to. Parent directories are created. Created at mode 0600 —
            even payload-free telemetry names targets, models, and spend.
        flush: Flush after every line. The default (`True`) costs a syscall per event and
            is what makes the file useful for `tail -f` and for a crash post-mortem, which
            is most of why this exists. Set `False` for high-volume runs where the file is
            only read afterwards.

    Example:
        >>> with JsonlObserver("telemetry.jsonl") as observer:  # doctest: +SKIP
        ...     client.subscribe(observer)
    """

    def __init__(self, path: str | Path, *, flush: bool = True):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._flush = flush
        self._lock = threading.Lock()
        # Created 0600 before the first byte, the same pattern the sidecar's token file
        # and the confidential CLI's key material use.
        descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self._handle = os.fdopen(descriptor, "a", encoding="utf-8")

    def on_event(self, event: TelemetryEvent) -> None:
        """Append one event. Never raises for a serialization problem."""
        line = json.dumps(event_to_dict(event), separators=(",", ":"), default=str)
        with self._lock:
            if self._handle.closed:
                return
            self._handle.write(line + "\n")
            if self._flush:
                self._handle.flush()

    def close(self) -> None:
        """Close the file. Further events are dropped rather than raising."""
        with self._lock:
            if not self._handle.closed:
                self._handle.close()

    def __enter__(self) -> JsonlObserver:
        """Enter a context that closes the file on exit."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the file."""
        self.close()
