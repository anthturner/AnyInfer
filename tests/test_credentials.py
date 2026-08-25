"""Credential resolution and its automatic redaction registration."""

from __future__ import annotations

import sys
from typing import Any

import pytest

import anyinfer as ai
from anyinfer.credentials import EnvResolver, KeyringResolver, LiteralResolver, default_resolver
from anyinfer.credentials.keyring_store import KEYRING_SERVICE
from anyinfer.redaction import redact, registry


def test_literal_reference_resolves_to_itself() -> None:
    assert default_resolver().resolve("sk-literal-key-value") == "sk-literal-key-value"


def test_env_reference_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANYINFER_TEST_KEY", "from-the-environment")
    assert default_resolver().resolve("env://ANYINFER_TEST_KEY") == "from-the-environment"


def test_missing_env_variable_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANYINFER_ABSENT_KEY", raising=False)
    with pytest.raises(ai.CredentialError) as excinfo:
        default_resolver().resolve("env://ANYINFER_ABSENT_KEY")

    assert excinfo.value.hint is not None
    assert "ANYINFER_ABSENT_KEY" in excinfo.value.hint


def test_env_reference_without_a_name_is_rejected() -> None:
    with pytest.raises(ai.CredentialError):
        default_resolver().resolve("env://")


def test_none_and_blank_resolve_to_none() -> None:
    resolver = default_resolver()
    assert resolver.resolve(None) is None
    assert resolver.resolve("   ") is None


def test_resolved_secrets_are_registered_for_redaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANYINFER_TEST_KEY", "auto-redacted-secret")
    default_resolver().resolve("env://ANYINFER_TEST_KEY")
    assert "auto-redacted-secret" not in redact("value auto-redacted-secret here")


def test_literal_resolver_declines_known_schemes() -> None:
    """A typo'd scheme must not silently become a literal secret."""
    literal = LiteralResolver()
    assert literal.handles("plain-value") is True
    assert literal.handles("env://NAME") is False
    assert literal.handles("credential://system/name") is False


def test_malformed_known_scheme_fails_loudly() -> None:
    """A single-slash typo fails resolution instead of becoming a literal secret."""
    assert LiteralResolver().handles("env:/OPENAI_KEY") is False
    assert LiteralResolver().handles("credential:system/name") is False
    with pytest.raises(ai.CredentialError):
        default_resolver().resolve("env:/OPENAI_KEY")


def test_env_resolver_only_handles_its_scheme() -> None:
    assert EnvResolver().handles("env://X") is True
    assert EnvResolver().handles("credential://system/x") is False


def test_an_unresolvable_scheme_fails_loudly_instead_of_becoming_the_secret() -> None:
    """The whole scheme *shape* is declined, not just the schemes this build knows.

    The `anyinfer.credential_stores` group makes the valid scheme set open-ended, so
    `vault://prod/openai` is legitimate when its plugin is installed. If it is missing or
    failed to import, the reference must not fall through to `LiteralResolver` and be
    accepted as the secret — that would put an internal vault path on the wire as a bearer
    token, which is exactly what the literal resolver exists to prevent.
    """
    with pytest.raises(ai.CredentialError, match="no credential resolver handles"):
        default_resolver().resolve("vault://prod/openai")


def test_a_bare_secret_is_still_treated_as_a_literal() -> None:
    """Declining the scheme shape must not decline the values that carry no scheme."""
    assert default_resolver().resolve("sk-a-literal-value") == "sk-a-literal-value"


# ---- keyring -------------------------------------------------------------------------


def test_keyring_resolver_handles_its_scheme() -> None:
    assert KeyringResolver().handles("credential://system/openai") is True
    assert KeyringResolver().handles("env://X") is False


def test_malformed_keyring_reference_is_rejected() -> None:
    with pytest.raises(ai.ConfigError) as excinfo:
        KeyringResolver().resolve("credential://system")
    assert excinfo.value.hint is not None
    assert "credential://system/" in excinfo.value.hint


def test_unknown_keyring_backend_is_rejected() -> None:
    with pytest.raises(ai.ConfigError, match="unknown credential backend"):
        KeyringResolver().resolve("credential://vault/secret")


def test_invalid_identifier_is_rejected() -> None:
    with pytest.raises(ai.ConfigError, match="invalid credential identifier"):
        KeyringResolver().resolve("credential://system/Bad Identifier!")


def test_missing_keyring_extra_gives_an_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(ai.ConfigError) as excinfo:
        KeyringResolver().resolve("credential://system/openai")

    assert excinfo.value.hint is not None
    assert "anyinfer[keyring]" in excinfo.value.hint


def test_keyring_lookup_reads_the_service_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeKeyring:
        @staticmethod
        def get_keyring() -> Any:
            class Backend:
                priority = 10

            return Backend()

        @staticmethod
        def get_password(service: str, identifier: str) -> str:
            calls.append((service, identifier))
            return "vault-stored-secret"

    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)
    secret = KeyringResolver().resolve("credential://system/openai-api-key")

    assert secret == "vault-stored-secret"
    assert calls == [(KEYRING_SERVICE, "openai-api-key")]


def test_unusable_keyring_backend_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeKeyring:
        @staticmethod
        def get_keyring() -> Any:
            class Backend:
                priority = 0

            return Backend()

    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)
    with pytest.raises(ai.CredentialError) as excinfo:
        KeyringResolver().resolve("credential://system/openai")

    assert excinfo.value.hint is not None
    assert "env://" in excinfo.value.hint


def test_absent_vault_entry_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeKeyring:
        @staticmethod
        def get_keyring() -> Any:
            class Backend:
                priority = 10

            return Backend()

        @staticmethod
        def get_password(service: str, identifier: str) -> None:
            return None

    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)
    with pytest.raises(ai.CredentialError, match="no credential stored"):
        KeyringResolver().resolve("credential://system/absent")


# ---- custom resolvers ----------------------------------------------------------------


def test_applications_can_register_their_own_resolver() -> None:
    class VaultResolver:
        def handles(self, reference: str) -> bool:
            return reference.startswith("vault://")

        def resolve(self, reference: str) -> str:
            return "secret-from-the-app-vault"

    chain = default_resolver()
    chain.add(VaultResolver())

    assert chain.resolve("vault://path/to/key") == "secret-from-the-app-vault"
    assert "secret-from-the-app-vault" not in redact("x secret-from-the-app-vault y")
    registry.clear()
