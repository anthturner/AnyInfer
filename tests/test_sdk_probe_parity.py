"""Input-only OpenAI-compatible capability-probe parity through the public Python SDK."""

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

_FIXTURE = Path(__file__).parent / "fixtures" / "sdk-probes-v1" / "openai-compat-probes.json"


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
async def test_openai_compatible_probes_use_real_public_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe traffic remains lazy until the explicit probe calls consume literal scripts."""
    source = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setenv("ANYINFER_SDK_PROBE_TEST_KEY", "sdk-probe-test-token")
    resolver = _CountingEnvResolver()
    expected_calls = list(source["calls"])
    sent: list[dict[str, Any]] = []
    adapters: list[Any] = []
    built: list[Any] = []

    def handle(instance: str) -> httpx2.MockTransport:
        def request_handler(request: httpx2.Request) -> httpx2.Response:
            script = expected_calls.pop(0)
            assert script["instance"] == instance
            assert request.method == "POST"
            assert request.url.path == "/v1/chat/completions"
            assert request.url.query == b""
            assert request.headers["authorization"] == "Bearer sdk-probe-test-token"
            assert request.headers["x-probe"] == instance
            body = json.loads(request.content)
            sent.append({"instance": instance, "body": body})
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
        stream = client.stream("not advanced", target=source["selectors"]["default_target"])
        assert str(client.resolve(source["selectors"]["default_target"])) == "primary:model"
        assert resolver.resolve_count == 0
        assert built == []
        assert sent == []
        await stream.aclose()

        empty = await client.probe(
            source["selectors"]["empty_target"],
            features=[ai.Feature[name] for name in source["selectors"]["empty_features"]],
        )
        assert empty.probes == ()
        assert empty.requests == 0
        assert resolver.resolve_count == 1
        assert [item.provider_id for item in built] == ["empty"]
        assert sent == []

        default = await client.probe(source["selectors"]["default_target"])
        assert [probe.feature for probe in default.probes] == list(ai.DEFAULT_PROBE_FEATURES)
        assert [probe.outcome for probe in default.probes] == [
            "supported",
            "supported",
            "supported",
            "supported",
        ]
        assert default.requests == 4
        assert default.capabilities is not None
        assert default.capabilities.features is not None
        assert default.capabilities.features.provenance == "probed"
        assert default.usage.input_tokens == 5
        assert default.usage.output_tokens == 8
        assert default.usage.total_tokens == 13

        assert [entry["instance"] for entry in sent[:4]] == ["primary"] * 4
        schema, json_mode, tools, streaming = [entry["body"] for entry in sent[:4]]
        for body in (schema, json_mode, tools, streaming):
            assert body["model"] == "model"
            assert body["max_tokens"] == 64
            assert body["temperature"] == 0.0
        assert schema["response_format"]["type"] == "json_schema"
        assert schema["response_format"]["json_schema"]["name"] == "capability_probe"
        assert schema["response_format"]["json_schema"]["schema"]["required"] == ["colour"]
        assert json_mode["response_format"] == {"type": "json_object"}
        assert tools["tool_choice"] == "required"
        assert tools["tools"][0]["function"]["name"] == "record_colour"
        assert streaming["stream"] is True
        assert streaming["stream_options"] == {"include_usage": True}
        recorded = await client.compare(
            "inspect recorded capability state",
            targets=[source["selectors"]["default_target"]],
        )
        assert recorded[0].capability_provenance["features"] == "probed"
        assert resolver.resolve_count == 3
        assert len(built) == 2
        assert len(sent) == 4

        rejection = await client.probe(
            source["selectors"]["rejection_target"], features=[ai.Feature.JSON_SCHEMA]
        )
        assert rejection.outcome_for(ai.Feature.JSON_SCHEMA) == "unsupported"
        assert sent[4]["instance"] == "secondary"

        inconclusive = await client.probe(
            source["selectors"]["inconclusive_target"], features=[ai.Feature.JSON_SCHEMA]
        )
        assert inconclusive.outcome_for(ai.Feature.JSON_SCHEMA) == "inconclusive"
        assert inconclusive.capabilities is None
        inconclusive_generation = await client.generate(
            "use the schema",
            target=source["selectors"]["inconclusive_target"],
            schema={"type": "object", "properties": {"colour": {"type": "string"}}},
        )
        assert inconclusive_generation.structured_mechanism == "prompt"
        assert "response_format" not in sent[-1]["body"]

        resolution_count = resolver.resolve_count
        factory_count = len(built)
        send_count = len(sent)
        before_no_record = await client.compare(
            "inspect unrecorded capability state",
            targets=[source["selectors"]["record_false_target"]],
        )
        assert resolver.resolve_count == resolution_count + 1
        assert len(built) == factory_count
        assert len(sent) == send_count
        no_record = await client.probe(
            source["selectors"]["record_false_target"],
            features=[ai.Feature.JSON_SCHEMA],
            record=False,
        )
        assert no_record.capabilities is not None
        assert no_record.capabilities.features is not None
        assert no_record.capabilities.features.provenance == "probed"
        resolution_count = resolver.resolve_count
        factory_count = len(built)
        send_count = len(sent)
        after_no_record = await client.compare(
            "inspect unrecorded capability state",
            targets=[source["selectors"]["record_false_target"]],
        )
        assert (
            after_no_record[0].capability_provenance
            == before_no_record[0].capability_provenance
        )
        assert resolver.resolve_count == resolution_count + 1
        assert len(built) == factory_count
        assert len(sent) == send_count
        no_record_generation = await client.generate(
            "use the schema",
            target=source["selectors"]["record_false_target"],
            schema={"type": "object", "properties": {"colour": {"type": "string"}}},
        )
        assert no_record_generation.structured_mechanism == "prompt"
        assert "response_format" not in sent[-1]["body"]

        duplicate = await client.probe(
            source["selectors"]["default_target"],
            features=[
                ai.Feature[name]
                for name in source["selectors"]["duplicate_features"]
            ],
        )
        assert [probe.feature for probe in duplicate.probes] == [
            ai.Feature.JSON_MODE,
            ai.Feature.JSON_MODE,
        ]
        assert [probe.outcome for probe in duplicate.probes] == ["supported", "supported"]
        assert duplicate.requests == 2
        assert [entry["instance"] for entry in sent] == [
            "primary",
            "primary",
            "primary",
            "primary",
            "secondary",
            "inconclusive",
            "inconclusive",
            "record-false",
            "record-false",
            "primary",
            "primary",
        ]
        assert resolver.resolve_count == 8
        assert [item.provider_id for item in built] == [
            "empty",
            "primary",
            "secondary",
            "inconclusive",
            "record-false",
        ]
        assert expected_calls == []
    finally:
        await client.aclose()

    assert all(adapter._client.is_closed for adapter in adapters)
