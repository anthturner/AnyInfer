"""Discovery: what this machine can already use, and nothing it cannot (IN.2).

Every probe here goes through an in-process transport. No test may open a socket to a real
port — including 127.0.0.1:11434 — because a developer machine running Ollama would
otherwise make the suite non-deterministic, and a machine behind a proxy would make it
slow.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx2
import pytest

from anyinfer.errors import ConfigError
from anyinfer.local.discovery import discover, endpoint_candidates
from anyinfer.registry import ProviderRegistry
from anyinfer.testing import ScriptedModel, ScriptedProvider


def _registry(*providers: ScriptedProvider) -> ProviderRegistry:
    """A registry holding only the scripted providers a test declared."""
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    for provider in providers:
        provider.register(registry)
    return registry


def _local(provider_id: str, port: int, *models: str) -> ScriptedProvider:
    """A scripted provider that looks, to discovery, like a local engine on loopback."""
    return ScriptedProvider(
        provider_id,
        [ScriptedModel(model) for model in (models or ("m",))],
        base_url=f"http://127.0.0.1:{port}/v1",
    )


# ---- endpoints -----------------------------------------------------------------------


async def test_a_running_endpoint_is_found() -> None:
    provider = _local("acme", 9101, "fast", "slow")
    found = await discover(
        _registry(provider), transports={"acme": provider.transport()}
    )

    assert [e.provider_id for e in found] == ["acme"]
    assert found[0].evidence == "endpoint"
    assert found[0].base_url == "http://127.0.0.1:9101/v1"
    assert found[0].models == ("fast", "slow")
    assert "2 models" in found[0].detail


async def test_a_refused_endpoint_is_absent() -> None:
    """A connection error means "not available here", never a reported provider."""
    provider = _local("acme", 9102)

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    found = await discover(
        _registry(provider), transports={"acme": httpx2.MockTransport(refuse)}
    )
    assert found == ()


async def test_a_slow_endpoint_times_out_rather_than_hanging() -> None:
    """The bound is the point: two dozen dead ports must not become a two-minute wait."""
    provider = _local("acme", 9103)

    async def crawl(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(30)
        raise AssertionError("the probe should have been cancelled long before this")

    found = await asyncio.wait_for(
        discover(
            _registry(provider),
            timeout_s=0.05,
            transports={"acme": httpx2.MockTransport(crawl)},
        ),
        timeout=10,
    )
    assert found == ()


async def test_an_endpoint_serving_nothing_is_not_reported() -> None:
    """A live HTTP server with an empty listing is not a usable provider."""
    provider = _local("acme", 9104)

    def empty(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"object": "list", "data": []}, request=request)

    found = await discover(
        _registry(provider), transports={"acme": httpx2.MockTransport(empty)}
    )
    assert found == ()


async def test_probing_can_be_declined_entirely() -> None:
    """``probe=False`` contacts nothing, which is what ``--no-probe`` is for."""
    contacted: list[str] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        contacted.append(str(request.url))
        return httpx2.Response(200, json={"object": "list", "data": []}, request=request)

    provider = _local("acme", 9105)
    found = await discover(
        _registry(provider),
        probe=False,
        transports={"acme": httpx2.MockTransport(record)},
    )
    assert found == ()
    assert contacted == []


async def test_only_loopback_endpoints_are_candidates() -> None:
    """Reaching off-machine on an inspection command is the surprise R-IN2 forbids."""
    remote = ScriptedProvider(
        "remote-engine", [ScriptedModel("m")], base_url="http://192.168.1.50:1234/v1"
    )
    near = _local("near-engine", 9106)
    candidates = endpoint_candidates(_registry(remote, near))

    assert [group[0] for group in candidates] == ["http://127.0.0.1:9106/v1"]


async def test_a_hosted_provider_is_never_probed() -> None:
    """Only engines that claim to run here are inspected."""
    hosted = ScriptedProvider(
        "cloudy", [ScriptedModel("m")], locality="hosted", base_url="http://127.0.0.1:9107/v1"
    )
    assert endpoint_candidates(_registry(hosted)) == ()


async def test_a_shared_port_reports_once_and_names_the_alternatives() -> None:
    """Four engines default to 8080; a port that answers cannot be attributed by probing."""
    first = _local("engine-a", 9108, "m")
    second = _local("engine-b", 9108, "m")
    registry = _registry(first, second)

    assert endpoint_candidates(registry) == (
        ("http://127.0.0.1:9108/v1", "engine-a", "engine-b"),
    )

    found = await discover(registry, transports={"engine-a": first.transport()})
    assert len(found) == 1
    assert found[0].provider_id == "engine-a"
    assert "engine-b" in found[0].detail


# ---- credentials ---------------------------------------------------------------------


async def test_an_environment_variable_is_reported_without_being_read() -> None:
    """The single most important property: no value ever enters a discovery result."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField

    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="keyed",
            display_name="Keyed",
            factory=OpenAICompatAdapter,
            default_base_url="https://api.keyed.invalid/v1",
            setup=ProviderSetupSpec(
                fields=(
                    SetupField(
                        key="api_key",
                        label="API key",
                        kind="secret",
                        placeholder="env://KEYED_API_KEY or a literal key",
                        env_var="KEYED_API_KEY",
                    ),
                )
            ),
        )
    )

    secret = "sk-do-not-leak-this-anywhere"
    found = await discover(registry, probe=False, environ={"KEYED_API_KEY": secret})

    assert len(found) == 1
    entry = found[0]
    assert entry.evidence == "environment"
    assert entry.credential_key == "api_key"
    assert entry.credential_ref == "env://KEYED_API_KEY"
    assert secret not in repr(entry)


async def test_a_blank_variable_is_not_evidence() -> None:
    """"Set to empty" is how a shell unsets a variable it cannot delete."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField

    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="keyed",
            display_name="Keyed",
            factory=OpenAICompatAdapter,
            setup=ProviderSetupSpec(
                fields=(
                    SetupField(
                        key="api_key",
                        label="API key",
                        kind="secret",
                        placeholder="env://KEYED_API_KEY or a literal key",
                        env_var="KEYED_API_KEY",
                    ),
                )
            ),
        )
    )
    assert await discover(registry, probe=False, environ={"KEYED_API_KEY": "   "}) == ()


async def test_a_running_endpoint_wins_over_a_key_for_the_same_provider() -> None:
    """One entry per provider, and the stronger observation is the one that ran."""
    provider = _local("acme", 9109, "m")
    registry = _registry(provider)
    # The scripted descriptor declares only a base URL, so an env hit for it is
    # impossible; the assertion that matters is that nothing is reported twice.
    found = await discover(
        registry,
        transports={"acme": provider.transport()},
        environ={"ACME_API_KEY": "sk-x"},
    )
    assert [e.provider_id for e in found] == ["acme"]


async def test_asking_for_the_vault_without_the_extra_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Answering "nothing found" to a caller who asked for the vault is a lie by omission."""
    import builtins

    real_import = builtins.__import__

    def refuse(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "keyring":
            raise ImportError("no module named keyring")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ConfigError, match="keyring extra"):
        await discover(_registry(_local("acme", 9110)), probe=False, keyring=True)


async def test_vault_evidence_records_a_reference_not_a_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from anyinfer.local import discovery as discover_module
    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField

    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="vaulted",
            display_name="Vaulted",
            factory=OpenAICompatAdapter,
            setup=ProviderSetupSpec(
                fields=(SetupField(key="api_key", label="API key", kind="secret"),)
            ),
        )
    )
    monkeypatch.setattr(
        discover_module,
        "_keyring_reader",
        lambda: (lambda identifier: identifier == "vaulted-api-key"),
    )

    found = await discover(registry, probe=False, keyring=True)
    assert [e.credential_ref for e in found] == ["credential://system/vaulted-api-key"]
    assert found[0].evidence == "credential-store"
