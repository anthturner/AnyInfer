"""Re-resolving a credential underneath a long-running process.

Credentials were resolved once, at adapter build, and never again — so rotating a key
meant restarting the installed sidecar. The two triggers here are a TTL and a provider
saying 401, and both share one rule that most of these tests are about: **the adapter is
rebuilt only when the resolved value actually changed**. An adapter owns a connection pool
and, for the supervised local engine, a running process; rebuilding one on a timer rather
than on a rotation would trade a restart-free rotation for a periodic connection storm.
"""

from __future__ import annotations

from typing import Any

import pytest

import anyinfer as ai
from anyinfer._client.providers import AdapterPool
from anyinfer.credentials.resolver import ResolverChain
from anyinfer.errors import AuthError, CredentialError
from anyinfer.registry import default_registry
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse


class _RotatingResolver:
    """A resolver whose answer for ``rotating://key`` the test can change at will."""

    scheme = "rotating://"

    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0
        self.fail = False

    def handles(self, reference: str) -> bool:
        return reference.startswith(self.scheme)

    def resolve(self, reference: str) -> str:
        self.calls += 1
        if self.fail:
            raise CredentialError("the vault is unreachable")
        return self.value


class _CountingAdapter:
    """Minimal adapter that records how many were built and closed."""

    builds = 0
    closes = 0

    def __init__(self, config: Any) -> None:
        type(self).builds += 1
        self.api_key = config.api_key

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ai.Health:
        return ai.Health(ok=True)

    async def aclose(self) -> None:
        type(self).closes += 1


@pytest.fixture
def pool_parts(monkeypatch: pytest.MonkeyPatch) -> tuple[_RotatingResolver, Any]:
    """A registry holding one throwaway descriptor, plus the resolver behind its key."""
    from anyinfer.registry import ProviderDescriptor, ProviderRegistry

    _CountingAdapter.builds = 0
    _CountingAdapter.closes = 0
    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            id="rotating-provider",
            display_name="Rotating",
            factory=_CountingAdapter,
            operations=frozenset(),
        )
    )
    resolver = _RotatingResolver("key-v1")
    return resolver, registry


def _pool(resolver: _RotatingResolver, registry: Any, **kwargs: Any) -> AdapterPool:
    chain = ResolverChain([resolver])
    return AdapterPool(
        [ai.ProviderSettings.of("rotating-provider", api_key="rotating://key")],
        registry=registry,
        resolver=chain,
        **kwargs,
    )


async def test_without_a_ttl_the_credential_is_resolved_once_and_never_again(
    pool_parts: tuple[_RotatingResolver, Any],
) -> None:
    """The default. A client holding literal keys must take no clock reading at all."""
    resolver, registry = pool_parts
    pool = _pool(resolver, registry)

    for _ in range(5):
        await pool.get("rotating-provider")

    assert resolver.calls == 1
    assert _CountingAdapter.builds == 1


async def test_an_expired_ttl_re_resolves_but_keeps_the_adapter_when_nothing_changed(
    pool_parts: tuple[_RotatingResolver, Any],
) -> None:
    """The whole design: a stable credential costs a resolver call, not a connection pool."""
    resolver, registry = pool_parts
    pool = _pool(resolver, registry, credential_ttl_s=10.0)
    clock = [1000.0]
    pool._clock = lambda: clock[0]

    await pool.get("rotating-provider")
    clock[0] += 11
    adapter = await pool.get("rotating-provider")

    assert resolver.calls == 2, "the reference was re-resolved"
    assert _CountingAdapter.builds == 1, "but nothing changed, so nothing was rebuilt"
    assert _CountingAdapter.closes == 0
    assert adapter.api_key == "key-v1"  # type: ignore[attr-defined]


async def test_a_rotated_credential_rebuilds_the_adapter_and_closes_the_old_one(
    pool_parts: tuple[_RotatingResolver, Any],
) -> None:
    resolver, registry = pool_parts
    events: list[Any] = []
    pool = _pool(resolver, registry, credential_ttl_s=10.0, events=events.append)
    clock = [1000.0]
    pool._clock = lambda: clock[0]

    first = await pool.get("rotating-provider")
    resolver.value = "key-v2"
    clock[0] += 11
    second = await pool.get("rotating-provider")

    assert first is not second
    assert second.api_key == "key-v2"  # type: ignore[attr-defined]
    assert _CountingAdapter.builds == 2
    assert _CountingAdapter.closes == 1, "the superseded connection pool is released"

    rotations = [e for e in events if isinstance(e, ai.CredentialRotated)]
    assert [(e.provider, e.trigger) for e in rotations] == [("rotating-provider", "ttl")]


async def test_the_rotation_event_carries_no_credential_and_no_digest(
    pool_parts: tuple[_RotatingResolver, Any],
) -> None:
    """Payload-free by construction, like every other event in the union."""
    resolver, registry = pool_parts
    events: list[Any] = []
    pool = _pool(resolver, registry, credential_ttl_s=10.0, events=events.append)
    clock = [1000.0]
    pool._clock = lambda: clock[0]

    await pool.get("rotating-provider")
    resolver.value = "super-secret-v2"
    clock[0] += 11
    await pool.get("rotating-provider")

    flat = repr(events)
    assert "super-secret-v2" not in flat
    assert "key-v1" not in flat
    assert len(flat) < 500, "no digest or opaque blob rides along either"


async def test_a_resolver_that_has_gone_away_does_not_tear_down_a_working_adapter(
    pool_parts: tuple[_RotatingResolver, Any],
) -> None:
    """An unreadable vault is not evidence the live credential stopped working.

    If it did stop working, the provider says 401 and the ordinary auth path reports it —
    which is a better failure than a client that stops working because a keychain locked.
    """
    resolver, registry = pool_parts
    pool = _pool(resolver, registry, credential_ttl_s=10.0)
    clock = [1000.0]
    pool._clock = lambda: clock[0]

    first = await pool.get("rotating-provider")
    resolver.fail = True
    clock[0] += 11
    second = await pool.get("rotating-provider")

    assert first is second
    assert _CountingAdapter.closes == 0

    clock[0] += 11
    resolver.fail = False
    resolver.value = "key-v2"
    third = await pool.get("rotating-provider")
    assert third is not first, "the next TTL re-check picks up the rotation"


async def test_refresh_reports_whether_anything_actually_moved(
    pool_parts: tuple[_RotatingResolver, Any],
) -> None:
    """The 401 path's whole contract: retry on True, stop on False."""
    resolver, registry = pool_parts
    pool = _pool(resolver, registry)
    await pool.get("rotating-provider")

    assert await pool.refresh_credential("rotating-provider") is False
    resolver.value = "key-v2"
    assert await pool.refresh_credential("rotating-provider") is True
    assert await pool.refresh_credential("rotating-provider") is False


async def test_refresh_on_an_unbuilt_provider_is_a_no_op(
    pool_parts: tuple[_RotatingResolver, Any],
) -> None:
    """Nothing is cached, so nothing rotated; building one here would be a surprise."""
    resolver, registry = pool_parts
    pool = _pool(resolver, registry)
    assert await pool.refresh_credential("rotating-provider") is False
    assert _CountingAdapter.builds == 0


# ---- end to end, through the router ------------------------------------------------------


class _RotatingKeyServer(FakeOpenAIServer):
    """Rejects every request whose bearer token is not the one currently accepted."""

    def __init__(self, accepted: str) -> None:
        super().__init__(FakeResponse(text="authorized"))
        self.accepted = accepted
        self.seen_tokens: list[str] = []

    def _handle(self, request: Any) -> Any:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        self.seen_tokens.append(token)
        if token != self.accepted:
            import httpx2

            return httpx2.Response(401, json={"error": {"message": "invalid api key"}})
        return super()._handle(request)


def _client(server: _RotatingKeyServer, resolver: _RotatingResolver) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                api_key="rotating://key",
                transport=server.transport(),
            )
        ],
        registry=default_registry,
        resolver=ResolverChain([resolver]),
        use_default_catalog=False,
    )


async def test_a_401_after_a_rotation_re_resolves_and_succeeds() -> None:
    """The strongest possible signal that a key moved underneath us."""
    resolver = _RotatingResolver("key-v1")
    server = _RotatingKeyServer("key-v1")
    client = _client(server, resolver)
    try:
        assert (await client.generate("hi", target="openai-compat:m")).text == "authorized"

        server.accepted = "key-v2"
        resolver.value = "key-v2"
        result = await client.generate("hi", target="openai-compat:m")
    finally:
        await client.aclose()

    assert result.text == "authorized"
    assert server.seen_tokens == ["key-v1", "key-v1", "key-v2"], (
        "one rejected attempt, then a re-resolved retry — not a blind second try"
    )


async def test_a_genuinely_wrong_key_still_fails_on_the_first_attempt() -> None:
    """Re-sending an unchanged credential would only buy a second identical failure."""
    resolver = _RotatingResolver("wrong-key")
    server = _RotatingKeyServer("right-key")
    client = _client(server, resolver)
    try:
        with pytest.raises(ai.AnyInferError) as caught:
            await client.generate("hi", target="openai-compat:m")
    finally:
        await client.aclose()

    assert isinstance(caught.value.__cause__ or caught.value, ai.AnyInferError)
    assert server.seen_tokens == ["wrong-key"], "the same rejected key is never re-sent"


async def test_a_401_is_reported_when_the_credential_cannot_be_re_read() -> None:
    """A vault that has gone away leaves the auth failure to surface as itself."""
    resolver = _RotatingResolver("key-v1")
    server = _RotatingKeyServer("key-v1")
    client = _client(server, resolver)
    try:
        await client.generate("hi", target="openai-compat:m")

        server.accepted = "key-v2"
        resolver.fail = True
        with pytest.raises(ai.AnyInferError):
            await client.generate("hi", target="openai-compat:m")
    finally:
        await client.aclose()

    assert server.seen_tokens == ["key-v1", "key-v1"], "no retry without a new credential"


def test_the_auth_error_class_is_what_triggers_this_at_all() -> None:
    """Pins the coupling: the hook keys on `AuthError`, not on a status number."""
    assert issubclass(AuthError, ai.ProviderError)
