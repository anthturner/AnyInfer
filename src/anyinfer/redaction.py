"""Secret redaction.

Every credential resolved through `anyinfer.credentials` is registered here. All error
``detail`` strings, event string fields, and log lines pass through `redact()` before
they leave the library, so a secret cannot reach a log file, an observer, or a traceback.

The registry is process-global by design: secrets are process-global facts, and redaction
must apply even to errors raised from code that never saw the client that resolved them.
"""

from __future__ import annotations

import base64
import json
import threading
import urllib.parse

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


def _encodings_of(secret: str) -> set[str]:
    """The secret plus the encoded forms it plausibly appears in on the request path.

    Deliberately a short, closed list. Every entry here is a form AnyInfer itself can
    produce — a JSON request body, a URL query, an HTTP Basic header — rather than a
    speculative catalogue, because each extra string is matched against every outbound
    string and a false match corrupts real output.
    """
    forms = {secret}

    # JSON string escaping: what a secret looks like inside a serialized request body.
    forms.add(json.dumps(secret)[1:-1])

    # Percent-encoding: a credential passed in a query string or path segment.
    forms.add(urllib.parse.quote(secret, safe=""))
    forms.add(urllib.parse.quote_plus(secret))

    # Base64: HTTP Basic auth, and the several providers that pack credentials this way.
    encoded = secret.encode("utf-8", errors="ignore")
    forms.add(base64.b64encode(encoded).decode("ascii"))
    forms.add(base64.b64encode(b":" + encoded).decode("ascii"))
    forms.add(base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("="))

    return forms


class RedactionRegistry:
    """A thread-safe set of secrets to strip from outbound strings."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()
        """Every string to strip: each registered secret plus its encoded forms."""
        self._registered: set[str] = set()
        """Only the secrets as registered, so `__len__` keeps meaning what it says."""
        self._lock = threading.Lock()

    def register(self, secret: str | None) -> None:
        """Register a secret for redaction, along with its common encodings.

        Redaction is exact-substring matching, so a secret that reaches a string in an
        encoded form — JSON-escaped inside a serialized body, percent-encoded in a URL,
        base64'd in an auth header — would not match the raw value and would survive.
        Each such form is registered alongside the original, which is cheap (a handful of
        extra strings per credential) and closes the gap for the encodings that actually
        occur on the request path.

        This is defense in depth, not a guarantee: an encoding nobody anticipated still
        slips through, which is exactly why the cassette audit exists as a second net.

        Values shorter than `MIN_SECRET_LEN` are ignored: redacting them would corrupt
        unrelated text far more often than it would protect anything. The same floor is
        applied to each derived form.
        """
        if not secret or len(secret) < MIN_SECRET_LEN:
            return
        with self._lock:
            self._registered.add(secret)
            for form in _encodings_of(secret):
                if len(form) >= MIN_SECRET_LEN:
                    self._secrets.add(form)

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
            self._registered.clear()

    def __len__(self) -> int:
        """Number of registered secrets — not the number of strings matched against.

        One registration also stores that secret's encoded forms; counting those would
        make this number an implementation detail of the encoding list.
        """
        with self._lock:
            return len(self._registered)


registry = RedactionRegistry()
"""The process-wide redaction registry."""


def register_secret(secret: str | None) -> None:
    """Register a secret with the process-wide registry."""
    registry.register(secret)


def redact(text: str) -> str:
    """Redact registered secrets from ``text`` using the process-wide registry."""
    return registry.redact(text)
