"""Secret redaction.

Every credential resolved through `anyinfer.credentials` is registered here. All error
``detail`` strings, event string fields, and log lines pass through `redact()` before
they leave the library, so a secret cannot reach a log file, an observer, or a traceback.

The registry is process-global by design: secrets are process-global facts, and redaction
must apply even to errors raised from code that never saw the client that resolved them.
"""

from __future__ import annotations

import threading

__all__ = [
    "MIN_SECRET_LEN",
    "REDACTED",
    "RedactionRegistry",
    "redact",
    "register_secret",
    "registry",
]

REDACTED = "[redacted]"
"""Replacement text. Deliberately carries no fragment of the original secret."""

MIN_SECRET_LEN = 6
"""Shorter values are too likely to be substrings of ordinary text to redact safely."""


class RedactionRegistry:
    """A thread-safe set of secrets to strip from outbound strings."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()
        self._lock = threading.Lock()

    def register(self, secret: str | None) -> None:
        """Register a secret for redaction.

        Values shorter than `MIN_SECRET_LEN` are ignored: redacting them would corrupt
        unrelated text far more often than it would protect anything.
        """
        if not secret or len(secret) < MIN_SECRET_LEN:
            return
        with self._lock:
            self._secrets.add(secret)

    def redact(self, text: str) -> str:
        """Replace every registered secret in ``text`` with `REDACTED`."""
        if not text:
            return text
        with self._lock:
            secrets = sorted(self._secrets, key=len, reverse=True)
        for secret in secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        return text

    def clear(self) -> None:
        """Forget all registered secrets. Intended for tests."""
        with self._lock:
            self._secrets.clear()

    def __len__(self) -> int:
        """Number of registered secrets."""
        with self._lock:
            return len(self._secrets)


registry = RedactionRegistry()
"""The process-wide redaction registry."""


def register_secret(secret: str | None) -> None:
    """Register a secret with the process-wide registry."""
    registry.register(secret)


def redact(text: str) -> str:
    """Redact registered secrets from ``text`` using the process-wide registry."""
    return registry.redact(text)
