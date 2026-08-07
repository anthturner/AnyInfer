"""Shared httpx2 plumbing and HTTP error classification.

Every httpx2-based adapter maps transport and status failures the same way, so the mapping
lives here rather than being reimplemented (and diverging) nine times. Adapters classify;
the router decides what to do about it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx2

from ..errors import (
    AuthError,
    ContextLengthError,
    ModelNotFoundError,
    Phase,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
    TransportError,
    is_retryable_status,
)

__all__ = [
    "build_client",
    "classify_status",
    "map_transport_error",
    "parse_retry_after",
    "read_error_detail",
]


def build_client(
    *,
    base_url: str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = 120.0,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> httpx2.AsyncClient:
    """Create an ``httpx2.AsyncClient`` configured for provider traffic.

    Connection pooling matters here: the sync facade holds one background loop for the
    process, so a long-lived client amortizes TLS handshakes across every request.

    Args:
        base_url: Root URL for relative request paths.
        headers: Default headers applied to every request.
        timeout_s: Default timeout; per-request values override it.
        transport: Optional transport override, used by the fake and cassette test modes.
    """
    return httpx2.AsyncClient(
        base_url=base_url or "",
        headers=dict(headers or {}),
        timeout=httpx2.Timeout(timeout_s),
        follow_redirects=True,
        transport=transport,
    )


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """Read a ``Retry-After`` header as seconds.

    Only the delta-seconds form is honored; an HTTP-date form is ignored rather than
    guessed at, since clock skew makes date arithmetic unreliable for short backoffs.
    """
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def read_error_detail(body: bytes | str, *, limit: int = 400) -> str:
    """Extract a human-readable message from a provider error body.

    Understands the ``{"error": {"message": …}}`` and ``{"error": "…"}`` shapes used across
    the OpenAI and Ollama dialects, falling back to bounded raw text.
    """
    import json

    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    text = text.strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except ValueError:
        return text[:limit]
    if isinstance(parsed, Mapping):
        error = parsed.get("error", parsed)
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("detail") or error.get("type")
            if isinstance(message, str):
                return message[:limit]
        elif isinstance(error, str):
            return error[:limit]
    return text[:limit]


def classify_status(
    status: int,
    *,
    provider: str,
    detail: str = "",
    headers: Mapping[str, str] | None = None,
    phase: Phase = "generate",
) -> ProviderError:
    """Map an HTTP status to the right `ProviderError` subclass.

    Args:
        status: The response status code.
        provider: Provider id, for attribution.
        detail: Message read from the error body.
        headers: Response headers, consulted for ``Retry-After``.
        phase: Lifecycle phase that produced the failure.

    Returns:
        The error to raise. Retryability follows the shared classification
        (`RETRYABLE_STATUS_CODES` plus ``>= 500``).
    """
    retry_after = parse_retry_after(headers or {})
    message = detail or f"provider returned HTTP {status}"
    common: dict[str, Any] = {
        "provider": provider,
        "http_status": status,
        "phase": phase,
        "retry_after_s": retry_after,
    }

    if status in (401, 403):
        return AuthError(
            message,
            provider=provider,
            http_status=status,
            phase=phase,
            hint="check the configured API key or credential reference",
        )
    if status == 404:
        return ModelNotFoundError(
            message,
            provider=provider,
            http_status=status,
            phase=phase,
            hint="verify the model id, or list available models with client.models()",
        )
    if status == 429:
        return RateLimitError(message, **common)
    if status in (413, 422) and _looks_like_context_overflow(message):
        return ContextLengthError(
            message,
            provider=provider,
            http_status=status,
            phase=phase,
            hint="shorten the prompt or choose a model with a larger context window",
        )
    if status >= 500:
        return ProviderUnavailableError(message, **common)
    return ProviderError(
        message,
        provider=provider,
        http_status=status,
        phase=phase,
        retryable=is_retryable_status(status),
        retry_after_s=retry_after,
    )


_CONTEXT_MARKERS = ("context length", "context_length", "too many tokens", "maximum context")


def _looks_like_context_overflow(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _CONTEXT_MARKERS)


def map_transport_error(
    exc: Exception,
    *,
    provider: str,
    phase: Phase = "generate",
) -> ProviderError:
    """Map an httpx2 transport exception to a typed, retryable provider error."""
    if isinstance(exc, httpx2.TimeoutException):
        return TransportError(
            f"request to {provider} timed out",
            provider=provider,
            phase=phase,
            hint="raise timeout_s, or choose a faster model",
        )
    if isinstance(exc, httpx2.ConnectError):
        return ProviderUnavailableError(
            f"cannot connect to {provider}: {exc}",
            provider=provider,
            phase=phase,
            hint="check the base URL and that the server is running",
        )
    return TransportError(f"transport failure talking to {provider}: {exc}", provider=provider,
                         phase=phase)
