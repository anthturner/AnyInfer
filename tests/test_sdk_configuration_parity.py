"""Input-only configuration parity against the public Python SDK surface."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.credentials import EnvResolver, ResolverChain
from anyinfer.registry import ProviderRegistry

_FIXTURE = Path(__file__).parent / "fixtures" / "sdk-configuration-v1" / "configured-generation.json"


class _CountingEnvResolver:
    """Record real environment resolution without changing its behavior."""

    def __init__(self) -> None:
        self._inner = EnvResolver()
        self.resolve_count = 0

    def handles(self, reference: str) -> bool:
        return self._inner.handles(reference)

    def resolve(self, reference: str) -> str:
        self.resolve_count += 1
        return self._inner.resolve(reference)


def _response(script: dict[str, Any]) -> httpx2.Response:
    return httpx2.Response(
        int(script["status"]),
        headers=dict(script["headers"]),
        content=str(script["body_utf8"]).encode("utf-8"),
    )


@pytest.mark.asyncio
async def test_configured_generation_input_is_lazy_and_uses_real_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shared input drives fallback and repair only after its stream advances."""
    source = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    config = ai.loads_config(json.dumps(source["config"]), source=str(_FIXTURE))
    assert config.repair is not None
    assert config.repair.max_attempts == 1
    reloaded = ai.loads_config(ai.dumps_config(config), source="round-trip")
    assert reloaded.repair is not None
    assert reloaded.repair.max_attempts == 1

    monkeypatch.setenv("ANYINFER_SDK_CONFIG_TEST_KEY", "sdk-configuration-test-secret")
    resolver = _CountingEnvResolver()
    sent: list[tuple[str, int, dict[str, Any]]] = []
    remaining = {
        instance: list(scripts)
        for instance, scripts in source["scripts"].items()
    }
    transports: dict[str, httpx2.MockTransport] = {}

    def transport_for(instance: str) -> httpx2.MockTransport:
        def handle(request: httpx2.Request) -> httpx2.Response:
            entry = len(source["scripts"][instance]) - len(remaining[instance])
            sent.append((instance, entry, json.loads(request.content)))
            assert request.headers["x-app"] == "sdk-configuration-parity"
            return _response(remaining[instance].pop(0))

        transport = httpx2.MockTransport(handle)
        transports[instance] = transport
        return transport

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    builtin = registry.get("openai-compat")
    built: list[Any] = []
    adapters: list[Any] = []

    def factory(provider_config: Any) -> Any:
        built.append(provider_config)
        adapter = builtin.factory(
            replace(
                provider_config,
                transport=transport_for(provider_config.provider_id),
            )
        )
        adapters.append(adapter)
        return adapter

    registry.register(replace(builtin, factory=factory), replace=True)
    client = ai.AsyncClient(
        config.providers,
        registry=registry,
        route=config.route,
        repair=config.repair,
        resolver=ResolverChain([resolver]),
        use_default_catalog=False,
    )
    try:
        stream = client.stream(source["request"]["prompt"], schema=source["request"]["schema"])
        assert resolver.resolve_count == 0
        assert built == []
        assert sent == []

        result = await stream.collect()

        assert result.text == '{"answer":"ok"}'
        assert result.structured == {"answer": "ok"}
        assert [(instance, entry) for instance, entry, _ in sent] == [
            ("primary", 0),
            ("primary", 1),
            ("backup", 0),
            ("backup", 1),
        ]
        assert resolver.resolve_count == 2
        assert [provider.provider_id for provider in built] == ["primary", "backup"]
        assert remaining == {"primary": [], "backup": []}

        first_backup = sent[2][2]["messages"]
        correction = sent[3][2]["messages"]
        assert correction[: len(first_backup)] == first_backup
        assert correction[-2]["role"] == "assistant"
        assert correction[-2]["content"] == "not-json"
        assert correction[-1]["role"] == "user"
        assert "response was not JSON and contained no JSON object or array" in correction[-1]["content"]
        assert "Respond again with ONLY a corrected JSON value" in correction[-1]["content"]
    finally:
        await client.aclose()

    assert len(transports) == 2
    assert all(adapter._client.is_closed for adapter in adapters)
