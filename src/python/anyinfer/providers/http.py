"""Shared httpx2 plumbing and HTTP error classification.

Every httpx2-based adapter maps transport and status failures the same way, so the mapping
lives here rather than being reimplemented (and diverging) in every adapter. Adapters classify;
the router decides what to do about it.
"""

from __future__ import annotations

import ssl
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx2

from ..errors import (
    AuthError,
    ConfigError,
    ContextLengthError,
    ModelNotFoundError,
    Phase,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
    StreamProtocolError,
    TransportError,
    is_retryable_status,
)

__all__ = [
    "build_client",
    "check_response_size",
    "classify_status",
    "map_transport_error",
    "parse_retry_after",
    "read_error_detail",
    "read_int",
    "tls_kwargs",
]


def check_response_size(content: bytes, max_bytes: int, *, provider: str) -> None:
    """Reject a buffered response body that exceeds its byte cap.

    A buffered (non-streaming) call has already paid for the whole body by the time this
    runs — ``httpx2`` read it all before returning ``response.content`` — so this cannot
    prevent the read itself. What it prevents is *parsing* an oversized body as if it were
    trustworthy: the same "reject rather than silently truncate" rule the streaming byte
    cap (`anyinfer.providers.sse`) and every generation adapter's buffered path already
    enforce, extended to embed()/rerank() so a response bomb on those paths gets refused
    with a typed error instead of overwhelming the JSON parser or the caller's memory.

    Raises:
        anyinfer.errors.StreamProtocolError: The body exceeds ``max_bytes``.
    """
    if len(content) > max_bytes:
        raise StreamProtocolError(
            f"response exceeded max_response_bytes ({max_bytes} bytes)",
            provider=provider,
        )


def build_client(
    *,
    base_url: str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = 120.0,
    transport: httpx2.AsyncBaseTransport | None = None,
    proxy: str | None = None,
    verify: str | bool | None = None,
    client_cert: str | tuple[str, str] | tuple[str, str, str] | None = None,
) -> httpx2.AsyncClient:
    """Create an ``httpx2.AsyncClient`` configured for provider traffic.

    Connection pooling matters here: the sync facade holds one background loop for the
    process, so a long-lived client amortizes TLS handshakes across every request.

    Args:
        base_url: Root URL for relative request paths.
        headers: Default headers applied to every request.
        timeout_s: Default timeout; per-request values override it.
        transport: Optional transport override, used by the fake and cassette test modes.
        proxy: Proxy URL for this client's traffic. ``None`` leaves httpx's own
            ``HTTPS_PROXY``/``NO_PROXY`` handling in place, which is the default.
        verify: CA-bundle path, or ``False`` to disable TLS verification, or ``None`` for
            the default trust store. A path is what an environment with a private or
            TLS-intercepting CA needs, and it is per instance, so one provider can trust a
            corporate CA while another keeps the public roots.
        client_cert: Client certificate for mTLS.

    Note:
        These are ignored when ``transport`` is supplied — a caller that brings its own
        transport has taken over connection handling entirely, which is exactly what the
        fake-server and cassette test modes do.
    """
    tls: dict[str, Any] = {}
    if transport is None:
        # Passed only when set: httpx distinguishes "not supplied" from an explicit
        # `None`/`False`, and forwarding a default would override its env-var behaviour.
        if proxy is not None:
            tls["proxy"] = proxy
        tls.update(tls_kwargs(verify, client_cert))
    return httpx2.AsyncClient(
        base_url=base_url or "",
        headers=dict(headers or {}),
        timeout=httpx2.Timeout(timeout_s),
        follow_redirects=True,
        transport=transport,
        **tls,
    )


def tls_kwargs(
    verify: str | bool | None,
    client_cert: str | tuple[str, str] | tuple[str, str, str] | None,
) -> dict[str, Any]:
    """Render this instance's TLS settings as keyword arguments for an httpx client.

    httpx once took a CA-bundle path as ``verify=<str>`` and a client certificate as
    ``cert=...``. Both spellings are now deprecated in favour of a single
    `ssl.SSLContext` passed as ``verify``, and — the reason this is not merely tidiness —
    **combining them raises `TypeError` outright**. That combination is exactly the
    corporate-CA-plus-mTLS case the configuration reference documents, so the settings
    are resolved into one context here instead of being forwarded as two.

    The conversion is confined to this function: `ProviderSettings` and the configuration
    file keep taking a path string and a certificate tuple, which is what an operator can
    write in JSON.

    Args:
        verify: CA-bundle path, ``False`` to disable verification, or ``None`` for the
            default trust store.
        client_cert: Combined PEM path, or ``(cert, key)`` / ``(cert, key, password)``.

    Returns:
        ``{"verify": ...}`` when anything is configured, or an empty mapping when nothing
        is — an empty mapping matters, because passing an explicit default would override
        httpx's own ``SSL_CERT_FILE``/``SSL_CERT_DIR`` handling.

    Raises:
        ConfigError: The CA bundle or certificate could not be read or parsed. Raised
            here rather than left to `ssl`, whose bare `FileNotFoundError` names no
            setting and offers no next step.
    """
    if not isinstance(verify, str) and client_cert is None:
        # Nothing needs constructing: `None` means "not supplied", and `True`/`False` are
        # both spellings httpx still accepts unchanged.
        return {} if verify is None else {"verify": verify}

    context = _ssl_context(verify)
    if client_cert is not None:
        parts = (client_cert,) if isinstance(client_cert, str) else tuple(client_cert)
        try:
            context.load_cert_chain(*parts)
        except (OSError, ssl.SSLError) as exc:
            raise ConfigError(
                f"cannot load the client certificate: {exc}",
                hint=(
                    "'client_cert' takes a combined PEM path, or [cert, key], or "
                    "[cert, key, password]; check the paths and the key's password"
                ),
            ) from exc
    return {"verify": context}


def _ssl_context(verify: str | bool | None) -> ssl.SSLContext:
    """Build the SSL context a `verify` setting describes."""
    if verify is None or verify is True:
        # Delegated rather than rebuilt: this is the branch that consults `truststore`
        # and the SSL_CERT_FILE/SSL_CERT_DIR environment variables, and reimplementing it
        # would mean tracking httpx's default trust behaviour by hand.
        return httpx2.create_ssl_context(verify=True)
    if verify is False:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    try:
        # A directory of hashed certificates is as valid as a bundle file, and an
        # operator pointing at either expects it to work.
        if Path(verify).is_dir():
            return ssl.create_default_context(capath=verify)
        return ssl.create_default_context(cafile=verify)
    except (OSError, ssl.SSLError) as exc:
        raise ConfigError(
            f"cannot load the CA bundle at {verify!r}: {exc}",
            hint="'verify' takes a path to a CA bundle file or a directory of them",
        ) from exc


def read_int(payload: Mapping[str, Any], name: str) -> int | None:
    """Read a field as a strict int, rejecting ``bool``.

    Every usage-block dialect across the adapters reads token counts the same defensive
    way: a present-but-wrong-typed field must not silently become a number. ``bool`` is a
    subclass of ``int`` in Python, so a naive ``isinstance(value, int)`` check would let a
    provider's stray ``true``/``false`` on a numeric-looking field pass through as ``1``/
    ``0`` — this excludes that case explicitly rather than by accident.
    """
    value = payload.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


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
    return TransportError(
        f"transport failure talking to {provider}: {exc}", provider=provider, phase=phase
    )
