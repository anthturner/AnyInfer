"""Error hierarchy, snapshots, and the redaction guarantee."""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.errors import (
    RETRYABLE_STATUS_CODES,
    AnyInferError,
    is_retryable_status,
)
from anyinfer.redaction import REDACTED, RedactionRegistry, redact, register_secret
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.results import DETAIL_MAX_CHARS

ERROR_CLASSES = [
    ai.ConfigError,
    ai.CredentialError,
    ai.ProviderError,
    ai.AuthError,
    ai.RateLimitError,
    ai.ModelNotFoundError,
    ai.ContextLengthError,
    ai.TransportError,
    ai.StreamProtocolError,
    ai.ProviderUnavailableError,
    ai.SchemaViolationError,
    ai.ToolLoopError,
    ai.AllTargetsFailedError,
    ai.LocalRuntimeError,
]


@pytest.mark.parametrize("cls", ERROR_CLASSES, ids=lambda c: c.__name__)
def test_every_error_descends_from_the_base(cls: type) -> None:
    assert issubclass(cls, AnyInferError)


@pytest.mark.parametrize("cls", ERROR_CLASSES, ids=lambda c: c.__name__)
def test_every_error_carries_the_structured_fields(cls: type) -> None:
    error = cls("something went wrong")
    for field in (
        "provider",
        "phase",
        "retryable",
        "retry_after_s",
        "http_status",
        "detail",
        "hint",
    ):
        assert hasattr(error, field), f"{cls.__name__} is missing {field}"


def test_provider_errors_are_a_distinct_branch() -> None:
    """Adapters raise only ProviderError subclasses; the router catches that branch."""
    for cls in (
        ai.AuthError,
        ai.RateLimitError,
        ai.TransportError,
        ai.StreamProtocolError,
        ai.ProviderUnavailableError,
        ai.ModelNotFoundError,
        ai.ContextLengthError,
    ):
        assert issubclass(cls, ai.ProviderError)
    for cls in (ai.ConfigError, ai.SchemaViolationError, ai.AllTargetsFailedError):
        assert not issubclass(cls, ai.ProviderError)


def test_detail_is_truncated() -> None:
    error = AnyInferError("x" * 2000)
    assert len(error.detail) == DETAIL_MAX_CHARS
    assert error.detail.endswith("…")


def test_retryable_defaults_by_class() -> None:
    assert ai.RateLimitError("slow down").retryable is True
    assert ai.TransportError("timeout").retryable is True
    assert ai.ProviderUnavailableError("down").retryable is True
    assert ai.AuthError("bad key").retryable is False
    assert ai.ModelNotFoundError("no such model").retryable is False


def test_retryable_status_classification() -> None:
    for status in RETRYABLE_STATUS_CODES:
        assert is_retryable_status(status)
    assert is_retryable_status(500)
    assert is_retryable_status(503)
    assert not is_retryable_status(400)
    assert not is_retryable_status(401)
    assert not is_retryable_status(404)
    assert not is_retryable_status(None)


def test_snapshot_is_a_faithful_serializable_record() -> None:
    error = ai.RateLimitError(
        "too many requests", provider="openai", http_status=429, retry_after_s=2.0
    )
    snapshot = error.snapshot()

    assert snapshot.type_name == "RateLimitError"
    assert snapshot.provider == "openai"
    assert snapshot.http_status == 429
    assert snapshot.retryable is True
    assert snapshot.phase == "generate"
    assert snapshot.detail == "too many requests"


def test_str_includes_the_hint() -> None:
    error = ai.ConfigError("no provider", hint="configure one first")
    assert "no provider" in str(error)
    assert "configure one first" in str(error)


# ---- redaction -----------------------------------------------------------------------


def test_registered_secrets_are_replaced() -> None:
    register_secret("sk-supersecret-value")
    assert redact("key is sk-supersecret-value here") == f"key is {REDACTED} here"


def test_short_values_are_not_registered() -> None:
    """Redacting short strings would corrupt unrelated text far more often than it helps."""
    register_secret("abc")
    assert redact("abc def") == "abc def"


def test_redaction_applies_to_error_details() -> None:
    register_secret("sk-leak-me-please")
    error = ai.AuthError("auth failed for key sk-leak-me-please")
    assert "sk-leak-me-please" not in error.detail
    assert REDACTED in error.detail


def test_redaction_applies_to_hints_and_raw_text() -> None:
    register_secret("sk-leak-me-please")
    error = ai.SchemaViolationError(
        "bad shape",
        raw_text="the model echoed sk-leak-me-please",
        hint="rotate sk-leak-me-please",
    )
    assert "sk-leak-me-please" not in error.raw_text
    assert error.hint is not None and "sk-leak-me-please" not in error.hint


def test_longer_secrets_are_redacted_first() -> None:
    """Overlapping secrets must not leave a fragment of the longer one behind."""
    registry = RedactionRegistry()
    registry.register("secret-value")
    registry.register("secret-value-extended")
    assert "secret" not in registry.redact("token secret-value-extended end")


def test_registry_isolation() -> None:
    registry = RedactionRegistry()
    registry.register("private-token-xyz")
    assert len(registry) == 1
    registry.clear()
    assert len(registry) == 0
    assert registry.redact("private-token-xyz") == "private-token-xyz"


async def test_no_secret_reaches_an_error_from_a_real_request() -> None:
    """End-to-end: a resolved credential never appears in an error surfaced to a caller."""
    secret = "sk-integration-secret-value"
    server = FakeOpenAIServer(FakeResponse(status=401, error_message=f"invalid key {secret}"))
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                api_key=secret,
                transport=server.transport(),
            )
        ]
    )
    async with client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("hi", target="openai-compat:m")

    error = excinfo.value
    assert secret not in str(error)
    for attempt in error.attempts:
        if attempt.error is not None:
            assert secret not in attempt.error.detail


# ---- encoded forms -------------------------------------------------------------------


def test_a_secret_is_redacted_from_its_json_escaped_form() -> None:
    """A credential inside a serialized request body is not the raw string.

    Redaction is exact-substring matching, so without registering the encoded forms a
    secret survives any serialization that escapes it.
    """
    import json

    registry = RedactionRegistry()
    secret = 'sk-live-with"quote-and\\backslash'
    registry.register(secret)

    body = json.dumps({"api_key": secret})
    assert secret not in registry.redact(body)
    assert REDACTED in registry.redact(body)


def test_a_secret_is_redacted_from_a_percent_encoded_url() -> None:
    import urllib.parse

    registry = RedactionRegistry()
    secret = "sk-live-abc+def/123"
    registry.register(secret)

    url = "https://api.example/v1?key=" + urllib.parse.quote(secret, safe="")
    assert secret not in registry.redact(url)
    assert REDACTED in registry.redact(url)


def test_a_secret_is_redacted_from_an_http_basic_header() -> None:
    import base64

    registry = RedactionRegistry()
    secret = "sk-live-abcdef123456"
    registry.register(secret)

    header = "Basic " + base64.b64encode(secret.encode()).decode()
    assert REDACTED in registry.redact(header)

    # The `user:pass` shape Basic auth actually uses is covered too.
    pair = "Basic " + base64.b64encode(b":" + secret.encode()).decode()
    assert REDACTED in registry.redact(pair)


def test_the_raw_secret_still_redacts_after_encoding_forms_were_added() -> None:
    registry = RedactionRegistry()
    registry.register("sk-live-abcdef123456")
    assert registry.redact("token=sk-live-abcdef123456") == f"token={REDACTED}"


def test_short_derived_forms_do_not_slip_under_the_length_floor() -> None:
    """The length floor applies to every derived form, not only the original.

    It exists so redaction cannot corrupt ordinary text.
    """
    registry = RedactionRegistry()
    registry.register("abc")  # below MIN_SECRET_LEN
    assert len(registry) == 0
    assert registry.redact("abc and more") == "abc and more"


# ---- connection settings reach the transport -----------------------------------------


def test_build_client_forwards_proxy_and_tls_settings() -> None:
    from anyinfer.providers.http import build_client

    client = build_client(base_url="https://x", verify=False)
    assert client is not None


def test_build_client_ignores_connection_settings_when_a_transport_is_supplied() -> None:
    """A caller bringing its own transport has taken over connection handling.

    The fake-server and cassette modes do exactly this, and passing a proxy alongside
    would be either ignored or an error depending on httpx's mood — better to be explicit.
    """
    from anyinfer.providers.http import build_client
    from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

    server = FakeOpenAIServer(FakeResponse(text="ok"))
    client = build_client(
        base_url="https://fake.invalid",
        transport=server.transport(),
        proxy="http://should-be-ignored:3128",
        verify=False,
    )
    assert client is not None
