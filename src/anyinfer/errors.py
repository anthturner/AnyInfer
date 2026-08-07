"""The AnyInfer exception hierarchy.

A shallow tree with rich structured fields, rather than a deep taxonomy: callers branch on
*fields* (``retryable``, ``http_status``, ``phase``) far more often than on exception class.
Every error carries an actionable `AnyInferError.hint` where one exists, and every
``detail`` is redacted and length-bounded at construction — an error object can never leak a
credential, no matter where it is logged.
"""

from __future__ import annotations

from typing import Literal

from .redaction import redact
from .types.results import DETAIL_MAX_CHARS, AttemptRecord, ErrorInfo

__all__ = [
    "RETRYABLE_STATUS_CODES",
    "AllTargetsFailedError",
    "AnyInferError",
    "AuthError",
    "ConfigError",
    "ContextLengthError",
    "CredentialError",
    "LocalRuntimeError",
    "ModelNotFoundError",
    "Phase",
    "ProviderError",
    "ProviderUnavailableError",
    "RateLimitError",
    "SchemaViolationError",
    "StreamProtocolError",
    "ToolLoopError",
    "TransportError",
    "is_retryable_status",
]

Phase = Literal["configure", "discover", "generate", "stream", "validate", "cleanup"]
"""Which stage of the request lifecycle produced an error."""

RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429})
"""Sub-500 statuses worth retrying; ``>= 500`` also retries."""


def is_retryable_status(status: int | None) -> bool:
    """Whether an HTTP status should be retried."""
    if status is None:
        return False
    return status in RETRYABLE_STATUS_CODES or status >= 500


def _bounded(detail: str) -> str:
    """Redact then truncate a detail string to `DETAIL_MAX_CHARS`."""
    cleaned = redact(detail)
    if len(cleaned) <= DETAIL_MAX_CHARS:
        return cleaned
    return cleaned[: DETAIL_MAX_CHARS - 1] + "…"


class AnyInferError(Exception):
    """Base class for everything this library raises.

    Attributes:
        detail: Human-readable description, redacted and truncated to 512 characters.
        provider: The provider id involved, when one is.
        phase: Lifecycle stage that failed.
        retryable: Whether retrying the identical request could plausibly succeed.
        retry_after_s: Server-advised delay before retrying, when supplied.
        http_status: Status code, for errors that came from an HTTP response.
        hint: The actionable next step to show a user, when one exists.
    """

    def __init__(
        self,
        detail: str,
        *,
        provider: str | None = None,
        phase: Phase = "generate",
        retryable: bool = False,
        retry_after_s: float | None = None,
        http_status: int | None = None,
        hint: str | None = None,
    ) -> None:
        self.detail = _bounded(detail)
        self.provider = provider
        self.phase: Phase = phase
        self.retryable = retryable
        self.retry_after_s = retry_after_s
        self.http_status = http_status
        self.hint = redact(hint) if hint else None
        super().__init__(self.detail)

    def __str__(self) -> str:
        """Render the detail, with the hint appended when present."""
        return f"{self.detail} (hint: {self.hint})" if self.hint else self.detail

    def snapshot(self) -> ErrorInfo:
        """Capture this error as a serializable `ErrorInfo`.

        Used to build attempt records, which travel in results and events long after the
        exception itself has been handled.
        """
        return ErrorInfo(
            type_name=type(self).__name__,
            provider=self.provider,
            phase=self.phase,
            retryable=self.retryable,
            http_status=self.http_status,
            detail=self.detail,
        )


class _ConfigurePhaseError(AnyInferError):
    """Shared base for errors that default to the ``configure`` phase."""

    def __init__(
        self,
        detail: str,
        *,
        provider: str | None = None,
        phase: Phase = "configure",
        retryable: bool = False,
        retry_after_s: float | None = None,
        http_status: int | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(
            detail,
            provider=provider,
            phase=phase,
            retryable=retryable,
            retry_after_s=retry_after_s,
            http_status=http_status,
            hint=hint,
        )


class ConfigError(_ConfigurePhaseError):
    """Invalid configuration, target string, catalog entry, or missing optional extra."""


class CredentialError(_ConfigurePhaseError):
    """A credential reference could not be resolved."""


class ProviderError(AnyInferError):
    """Base for anything a provider surfaced.

    Adapters raise only these; they never retry internally. The router decides
    what to do based on `retryable` and
    `retry_after_s`.
    """


class AuthError(ProviderError):
    """Authentication or authorization failed."""


class _RetryableProviderError(ProviderError):
    """Shared base for provider errors that are retryable unless stated otherwise."""

    def __init__(
        self,
        detail: str,
        *,
        provider: str | None = None,
        phase: Phase = "generate",
        retryable: bool = True,
        retry_after_s: float | None = None,
        http_status: int | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(
            detail,
            provider=provider,
            phase=phase,
            retryable=retryable,
            retry_after_s=retry_after_s,
            http_status=http_status,
            hint=hint,
        )


class RateLimitError(_RetryableProviderError):
    """The provider rate-limited the request."""


class ModelNotFoundError(ProviderError):
    """The requested model does not exist or is not available to this account."""


class ContextLengthError(ProviderError):
    """The prompt exceeds the resolved model's context window."""


class TransportError(_RetryableProviderError):
    """Connect, timeout, or TLS failure — no usable response was received."""


class StreamProtocolError(ProviderError):
    """Malformed SSE/NDJSON framing, or a response exceeding its byte cap."""

    def __init__(
        self,
        detail: str,
        *,
        provider: str | None = None,
        phase: Phase = "stream",
        retryable: bool = False,
        retry_after_s: float | None = None,
        http_status: int | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(
            detail,
            provider=provider,
            phase=phase,
            retryable=retryable,
            retry_after_s=retry_after_s,
            http_status=http_status,
            hint=hint,
        )


class ProviderUnavailableError(_RetryableProviderError):
    """The provider is down, unreachable, or failed its health probe."""


class SchemaViolationError(AnyInferError):
    """The response did not satisfy the requested schema, and the repair budget is spent.

    Attributes:
        raw_text: The model's raw output, so callers can inspect or salvage it.
        errors: Human-readable validation error messages.
    """

    def __init__(
        self,
        detail: str,
        *,
        raw_text: str = "",
        errors: tuple[str, ...] = (),
        provider: str | None = None,
        phase: Phase = "validate",
        hint: str | None = None,
    ) -> None:
        super().__init__(detail, provider=provider, phase=phase, hint=hint)
        self.raw_text = redact(raw_text)
        self.errors = errors


class ToolLoopError(AnyInferError):
    """A tool could not be dispatched, or the loop exceeded its round bound."""


class AllTargetsFailedError(AnyInferError):
    """Every target in the route failed.

    Attributes:
        attempts: The complete routing trail, in order, including skipped targets.
    """

    def __init__(
        self,
        detail: str = "all routing targets failed",
        *,
        attempts: tuple[AttemptRecord, ...] = (),
        hint: str | None = None,
    ) -> None:
        super().__init__(detail, hint=hint)
        self.attempts = attempts


class LocalRuntimeError(AnyInferError):
    """llama-server lifecycle failure, or runtime/model integrity problem."""
