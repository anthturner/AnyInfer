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

from .._private_files import restrict_to_owner
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
        # Keys are redacted too. A mapping keyed by anything caller-supplied -- provider
        # options, HTTP headers, a `values` block -- can carry a secret in the key just as
        # easily as in the value, and a key is the half nothing else on this path checks.
        return {redact(str(k)): _json_safe(v) for k, v in value.items()}
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


def _resolve_level(level: int | str) -> int:
    """Resolve a logging level given as an int or a level name.

    `logging.getLevelName` is the stdlib's only name-to-number lookup and it answers an
    unknown name with the string ``"Level <name>"`` rather than raising, so the result is
    type-checked instead of trusted. Custom levels registered with
    `logging.addLevelName` resolve too, since the lookup is the live table.
    """
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(level.strip().upper())
    if not isinstance(resolved, int):
        raise ValueError(
            f"unknown logging level {level!r}; expected an int or one of "
            "CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET"
        )
    return resolved


class LoggingObserver:
    """Emit each event as a structured record on a stdlib `logging.Logger`.

    The message is the event name; the full mapping is attached as an ``anyinfer_event``
    record attribute, so a JSON log formatter can render it while a plain formatter still
    prints something readable.

    Both arguments accept the string forms a configuration file can express, because
    `observers` blocks in `anyinfer.toml` reach this constructor through
    `build_observers` and can only carry JSON/TOML scalars. A bad level is rejected here,
    at construction, so `build_observers`' promise that a typo fails at load rather than
    at the first event holds for the option values as well as the observer name — an
    unresolvable level would otherwise raise inside `isEnabledFor` on every single event,
    which the dispatcher suppresses after one warning, leaving a silently empty log.

    Args:
        logger: Where to log, as a `Logger` or a logger name to resolve. Defaults to a
            logger named `DEFAULT_LOGGER_NAME`.
        level: Level to log every event at, as an int or a level name such as ``"INFO"``
            (case-insensitive). One level for all of them on purpose — severity is the
            *application's* judgement, and a library that logs some events at ``WARNING``
            decides that for you.

    Raises:
        ValueError: If `level` is a string that names no known logging level.
            `build_observers` maps this to `ConfigError` for the config path.

    Example:
        >>> import logging
        >>> logging.basicConfig(level=logging.INFO)
        >>> observer = LoggingObserver()
        >>> client.subscribe(observer)  # doctest: +SKIP
    """

    def __init__(
        self,
        logger: logging.Logger | str | None = None,
        *,
        level: int | str = logging.INFO,
    ):
        self._logger = (
            logging.getLogger(logger)
            if isinstance(logger, str)
            else logger or logging.getLogger(DEFAULT_LOGGER_NAME)
        )
        self._level = _resolve_level(level)

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
        path: File to append to. Parent directories are created. Created at mode 0600 on
            POSIX — even payload-free telemetry names targets, models, and spend. Windows
            has no equivalent through `chmod`, so the file is *not* owner-restricted
            there; put it somewhere whose ACL already excludes other accounts.
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
        # The mode argument above applies only when `open` creates the file. Appending to
        # a file that already exists at 0644 would inherit that mode silently, so it is
        # re-applied unconditionally -- the same follow-up the demo config writer does.
        # On Windows this is a no-op and reports so; see `_private_files`.
        restrict_to_owner(self._path)

    def on_event(self, event: TelemetryEvent) -> None:
        """Append one event. Never raises for a serialization problem."""
        # No `default=` fallback: `_json_safe` already has a redacting catch-all for
        # every unrecognized leaf, so a `default=str` here could only ever fire on a value
        # that escaped redaction -- writing the one thing this sink must not write.
        line = json.dumps(event_to_dict(event), separators=(",", ":"))
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
