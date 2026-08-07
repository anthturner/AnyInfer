"""The shared HTTP classification helpers every httpx2 adapter leans on."""

from __future__ import annotations

import httpx2

import anyinfer as ai
from anyinfer.providers.http import classify_status, map_transport_error, parse_retry_after

# ---- parse_retry_after ---------------------------------------------------------------


def test_delta_seconds_are_honored() -> None:
    assert parse_retry_after({"retry-after": "2"}) == 2.0
    assert parse_retry_after({"Retry-After": "1.5"}) == 1.5


def test_http_dates_are_ignored_rather_than_guessed_at() -> None:
    assert parse_retry_after({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}) is None


def test_negative_values_are_ignored() -> None:
    assert parse_retry_after({"retry-after": "-3"}) is None


def test_absent_header_is_none() -> None:
    assert parse_retry_after({}) is None


# ---- classify_status -----------------------------------------------------------------


def test_429_carries_retry_after_onto_the_error() -> None:
    error = classify_status(429, provider="p", headers={"retry-after": "7"})
    assert isinstance(error, ai.RateLimitError)
    assert error.retry_after_s == 7.0
    assert error.retryable is True
    assert error.http_status == 429


# ---- map_transport_error -------------------------------------------------------------


def test_timeouts_map_to_a_retryable_transport_error_with_a_hint() -> None:
    error = map_transport_error(httpx2.ReadTimeout("too slow"), provider="p")
    assert isinstance(error, ai.TransportError)
    assert error.retryable is True
    assert error.hint is not None and "timeout_s" in error.hint


def test_connect_failures_map_to_provider_unavailable() -> None:
    error = map_transport_error(httpx2.ConnectError("connection refused"), provider="p")
    assert isinstance(error, ai.ProviderUnavailableError)
    assert error.retryable is True
    assert error.hint is not None
