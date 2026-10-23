"""Controls for connection-safe provider configuration representations."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict, is_dataclass, replace

import pytest

import anyinfer as ai
from anyinfer.providers.base import ProviderConfig


class _ExplosiveRepresentation:
    """Fails if a supposedly omitted connection value is traversed."""

    def __repr__(self) -> str:
        raise AssertionError("connection value representation was traversed")

    def __str__(self) -> str:
        raise AssertionError("connection value string conversion was traversed")


_SENSITIVE_MARKERS = (
    "api-token-marker",
    "header-token-marker",
    "option-token-marker",
    "userinfo-marker",
    "proxy-marker",
    "ca-bundle-marker",
    "client-cert-marker",
    "client-key-marker",
    "client-password-marker",
)


def _assert_identifier_only(value: object, *identities: str) -> None:
    """Require safe representations without prescribing irrelevant punctuation."""
    representations = (repr(value), str(value), repr([value]), repr({"value": value}))
    for representation in representations:
        for identity in identities:
            assert identity in representation
        for marker in _SENSITIVE_MARKERS:
            assert marker not in representation


@pytest.mark.parametrize(
    ("factory", "identities"),
    [
        (
            lambda: ai.ProviderSettings(
                provider_id="safe-provider",
                alias="safe-alias",
                base_url="https://userinfo-marker@host.invalid",
                api_key="api-token-marker",
                api_version=_ExplosiveRepresentation(),
                headers={
                    "Authorization": "header-token-marker",
                    "opaque": _ExplosiveRepresentation(),
                },
                options={"token": "option-token-marker", "opaque": _ExplosiveRepresentation()},
                timeout_s=_ExplosiveRepresentation(),
                proxy="https://proxy-marker@proxy.invalid",
                verify="/private/ca-bundle-marker.pem",
                client_cert=(
                    "/private/client-cert-marker.pem",
                    "/private/client-key-marker.pem",
                    "client-password-marker",
                ),
                transport=_ExplosiveRepresentation(),
                limits=_ExplosiveRepresentation(),
            ),
            ("safe-provider", "safe-alias"),
        ),
        (
            lambda: ProviderConfig(
                provider_id="safe-provider",
                base_url="https://userinfo-marker@host.invalid",
                api_key="api-token-marker",
                api_version=_ExplosiveRepresentation(),
                headers={
                    "Authorization": "header-token-marker",
                    "opaque": _ExplosiveRepresentation(),
                },
                options={"token": "option-token-marker", "opaque": _ExplosiveRepresentation()},
                timeout_s=_ExplosiveRepresentation(),
                proxy="https://proxy-marker@proxy.invalid",
                verify="/private/ca-bundle-marker.pem",
                client_cert=(
                    "/private/client-cert-marker.pem",
                    "/private/client-key-marker.pem",
                    "client-password-marker",
                ),
                transport=_ExplosiveRepresentation(),
                events=_ExplosiveRepresentation(),
            ),
            ("safe-provider",),
        ),
    ],
)
def test_provider_connection_representations_are_identifier_only(factory, identities) -> None:
    """Connection values remain retained yet are never traversed for display."""
    _assert_identifier_only(factory(), *identities)


@pytest.mark.parametrize(
    ("factory", "replacement"),
    [
        (
            lambda: ai.ProviderSettings(
                provider_id="original-provider",
                alias="original-alias",
                api_key="api-token-marker",
                headers={"Authorization": "header-token-marker"},
                options={"token": "option-token-marker"},
            ),
            {"alias": "replacement-alias"},
        ),
        (
            lambda: ProviderConfig(
                provider_id="original-provider",
                api_key="api-token-marker",
                headers={"Authorization": "header-token-marker"},
                options={"token": "option-token-marker"},
            ),
            {"provider_id": "replacement-provider"},
        ),
    ],
)
def test_safe_repr_preserves_frozen_slots_and_field_data(factory, replacement) -> None:
    """A custom repr changes presentation only, not dataclass semantics or stored data."""
    original = factory()
    changed = replace(original, **replacement)

    assert is_dataclass(original)
    assert not hasattr(original, "__dict__")
    assert asdict(original)["api_key"] == "api-token-marker"
    assert asdict(original)["headers"] == {"Authorization": "header-token-marker"}
    assert asdict(original)["options"] == {"token": "option-token-marker"}
    with pytest.raises(FrozenInstanceError):
        original.provider_id = "mutated"  # type: ignore[misc]
    assert repr(changed) != repr(original)


def test_public_config_round_trip_retains_connection_values_without_resolving_them() -> None:
    """Config serialization remains lossless and is separate from safe object display."""
    document = {
        "format_version": 1,
        "providers": [
            {
                "id": "openai",
                "api_key": "api-token-marker",
                "headers": {"Authorization": "header-token-marker"},
                "options": {"token": "option-token-marker"},
                "proxy": "https://proxy-marker@proxy.invalid",
                "verify": "/private/ca-bundle-marker.pem",
                "client_cert": [
                    "/private/client-cert-marker.pem",
                    "/private/client-key-marker.pem",
                    "client-password-marker",
                ],
            }
        ],
    }

    loaded = ai.loads_config(json.dumps(document))
    rendered = ai.dumps_config(loaded)
    restored = ai.loads_config(rendered)

    assert restored == loaded
    assert json.loads(rendered)["providers"][0] == document["providers"][0]
    _assert_identifier_only(loaded.providers[0], "openai")
