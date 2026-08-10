"""Bounded standard-library JSON retrieval for pricing maintenance sources."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Protocol, cast

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
TIMEOUT_SECONDS = 30
USER_AGENT = "AnyInfer-pricing-drift/1 (+https://github.com/anthropics/AnyInfer)"


class _Opener(Protocol):
    def open(self, request: urllib.request.Request, *, timeout: int) -> Any: ...


def fetch_json(
    url: str,
    *,
    opener: _Opener | None = None,
    max_bytes: int = MAX_RESPONSE_BYTES,
    timeout: int = TIMEOUT_SECONDS,
) -> Mapping[str, Any]:
    """Fetch one hard-coded HTTPS source with a strict response bound and exact decimals."""
    if not url.startswith("https://"):
        raise ValueError("pricing source URL must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    active_opener = opener or cast(_Opener, urllib.request.build_opener())
    try:
        with active_opener.open(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > max_bytes:
                raise ValueError(f"pricing source response exceeds {max_bytes} bytes")
            body = response.read(max_bytes + 1)
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as error:
        raise RuntimeError(f"pricing source request failed: {error}") from error
    if len(body) > max_bytes:
        raise ValueError(f"pricing source response exceeds {max_bytes} bytes")
    try:
        decoded = json.loads(body, parse_float=Decimal, parse_int=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("pricing source returned malformed JSON") from error
    if not isinstance(decoded, Mapping):
        raise ValueError("pricing source JSON root must be an object")
    return decoded
