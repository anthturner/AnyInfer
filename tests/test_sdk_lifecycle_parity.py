"""Input-only OpenAI-compatible lifecycle parity through the public Python SDK."""

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

_FIXTURE = Path(__file__).parent / "fixtures" / "sdk-lifecycle-v1" / "openai-compat-lifecycle.json"


class _CountingEnvResolver:
    """Count real environment resolution without changing EnvResolver behavior."""

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
async def test_openai_compatible_lifecycle_input_uses_real_public_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construction stays inert; explicit public lifecycle calls replay each raw response."""
    source = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setenv("ANYINFER_SDK_LIFECYCLE_TEST_KEY", "sdk-lifecycle-test-token")
    resolver = _CountingEnvResolver()
    expected_calls = list(source["calls"])
    sent: list[tuple[str, str, str, str]] = []
    adapters: list[Any] = []
    built: list[Any] = []

    def handle(instance: str) -> httpx2.MockTransport:
        def request_handler(request: httpx2.Request) -> httpx2.Response:
            script = expected_calls.pop(0)
            assert script["instance"] == instance
            assert request.method == "GET"
            assert request.url.path == "/v1/models"
            assert request.url.query == b""
            assert request.content == b""
            assert request.headers["authorization"] == "Bearer sdk-lifecycle-test-token"
            assert request.headers["content-type"] == "application/json"
            assert request.headers["x-lifecycle"] == instance
            sent.append((instance, script["operation"], request.method, request.url.path))
            return _response(script)

        return httpx2.MockTransport(request_handler)

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    builtin = registry.get("openai-compat")

    def factory(provider_config: Any) -> Any:
        built.append(provider_config)
        adapter = builtin.factory(
            replace(provider_config, transport=handle(provider_config.provider_id))
        )
        adapters.append(adapter)
        return adapter

    registry.register(replace(builtin, factory=factory), replace=True)
    providers = [
        ai.ProviderSettings.of(
            item["adapter"],
            base_url=item["base_url"],
            api_key=item["credential"],
            headers=item["headers"],
            timeout_s=item["timeout_s"],
            alias=item["id"],
        )
        for item in source["instances"]
    ]
    client = ai.AsyncClient(
        providers,
        registry=registry,
        resolver=ResolverChain([resolver]),
        use_default_catalog=False,
    )
    try:
        stream = client.stream("not advanced", target="primary:model")
        assert str(client.resolve("primary:model")) == "primary:model"
        assert resolver.resolve_count == 0
        assert built == []
        assert sent == []
        await stream.aclose()

        primary_models = await client.models("primary")
        primary_health = await client.health("primary")
        secondary_health = await client.health("secondary")
        secondary_models = await client.models("secondary")

        assert [model.id for model in primary_models] == ["alpha", "alpha", "9"]
        assert primary_health.ok is True
        assert secondary_health.ok is False
        assert secondary_health.detail == "HTTP 503"
        assert [model.id for model in secondary_models] == ["beta", "beta", "None"]
        assert [(instance, operation) for instance, operation, _, _ in sent] == [
            ("primary", "models"),
            ("primary", "health"),
            ("secondary", "health"),
            ("secondary", "models"),
        ]
        assert resolver.resolve_count == 2
        assert [item.provider_id for item in built] == ["primary", "secondary"]
        assert [item.timeout_s for item in built] == [0.25, 0.25]
        assert expected_calls == []
    finally:
        await client.aclose()

    assert all(adapter._client.is_closed for adapter in adapters)
