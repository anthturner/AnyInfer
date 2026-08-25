"""Entry-point discovery for the non-provider extension points."""

from __future__ import annotations

from typing import Any

import pytest

from anyinfer.plugins import (
    CREDENTIAL_STORE_GROUP,
    OBSERVER_GROUP,
    load_credential_stores,
    load_observers,
)


class _FakePoint:
    def __init__(self, name: str, value: Any, *, raises: bool = False):
        self.name = name
        self._value = value
        self._raises = raises

    def load(self) -> Any:
        if self._raises:
            raise ImportError("no module named 'definitely_absent'")
        return self._value


def _patch_points(
    monkeypatch: pytest.MonkeyPatch, target_group: str, points: list[_FakePoint]
) -> None:
    """Serve `points` for one group only, so a test cannot pass on the wrong group."""
    import anyinfer.plugins as plugins

    def fake_entry_points(*, group: str) -> list[_FakePoint]:
        return points if group == target_group else []

    monkeypatch.setattr(plugins, "entry_points", fake_entry_points)


class _GoodResolver:
    def handles(self, reference: str) -> bool:
        return reference.startswith("vault://")

    def resolve(self, reference: str) -> str:
        return "resolved-secret"


def test_groups_are_named_under_the_anyinfer_namespace() -> None:
    assert OBSERVER_GROUP == "anyinfer.observers"
    assert CREDENTIAL_STORE_GROUP == "anyinfer.credential_stores"


def test_no_installed_plugins_is_not_an_error() -> None:
    observers, issues = load_observers()
    assert isinstance(observers, dict)
    assert issues == []


def test_observers_are_discovered_but_not_instantiated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sink that opens a file must not do so merely because it is installed."""
    built: list[str] = []

    def factory(**options: Any) -> Any:
        built.append("called")
        return object()

    _patch_points(monkeypatch, OBSERVER_GROUP, [_FakePoint("mysink", factory)])
    discovered, issues = load_observers()

    assert "mysink" in discovered
    assert issues == []
    assert built == [], "discovery must not call the factory"


def test_a_plugin_that_fails_to_import_is_recorded_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken third-party package must not stop the client from starting."""
    _patch_points(monkeypatch, OBSERVER_GROUP, [_FakePoint("broken", None, raises=True)])
    discovered, issues = load_observers()

    assert discovered == {}
    assert [i.entry_point for i in issues] == ["broken"]
    assert issues[0].reason == "import-failed"


def test_a_credential_store_is_constructed_and_protocol_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_points(monkeypatch, CREDENTIAL_STORE_GROUP, [_FakePoint("vault", _GoodResolver)])
    resolvers, issues = load_credential_stores()

    assert issues == []
    assert resolvers["vault"].handles("vault://x") is True


def test_a_credential_store_of_the_wrong_shape_is_dropped_with_a_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anything failing the protocol must never reach the resolver chain."""

    class _NotAResolver:
        pass

    _patch_points(monkeypatch, CREDENTIAL_STORE_GROUP, [_FakePoint("bogus", _NotAResolver)])
    resolvers, issues = load_credential_stores()

    assert resolvers == {}
    assert issues[0].reason == "not-a-descriptor"
    assert "CredentialResolver" in issues[0].detail


def test_a_credential_store_that_raises_while_constructing_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Explodes:
        def __init__(self) -> None:
            raise RuntimeError("vault unreachable")

    _patch_points(monkeypatch, CREDENTIAL_STORE_GROUP, [_FakePoint("vault", _Explodes)])
    resolvers, issues = load_credential_stores()

    assert resolvers == {}
    assert "vault unreachable" in issues[0].detail


def test_the_default_resolver_chain_still_works_with_no_plugins() -> None:
    """The ordinary path pays nothing for the plugin hook."""
    import os

    from anyinfer.credentials.resolver import default_resolver

    os.environ["ANYINFER_TEST_PLUGIN_KEY"] = "value"
    try:
        assert default_resolver().resolve("env://ANYINFER_TEST_PLUGIN_KEY") == "value"
    finally:
        del os.environ["ANYINFER_TEST_PLUGIN_KEY"]


def test_a_plugin_in_one_group_is_invisible_to_the_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the test helper as much as the code: groups must not leak into each other."""
    _patch_points(monkeypatch, OBSERVER_GROUP, [_FakePoint("mysink", lambda **_: object())])

    assert "mysink" in load_observers()[0]
    assert load_credential_stores()[0] == {}
