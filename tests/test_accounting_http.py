"""Public builtin HTTP accounting observations over input-only fixture traffic."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.capabilities import SpendLedger
from anyinfer.credentials import EnvResolver, ResolverChain
from anyinfer.registry import ProviderRegistry
from anyinfer.types.capabilities import Pricing

_FIXTURE = Path(__file__).parent / "fixtures" / "accounting-v1" / "openai-compat-accounting.json"


class _Collector:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def on_event(self, event: Any) -> None:
        self.events.append(event)


def _messages(raw: list[dict[str, str]]) -> tuple[Any, ...]:
    builders = {"system": ai.system, "user": ai.user, "assistant": ai.assistant}
    return tuple(builders[item["role"]](item["content"]) for item in raw)


def _overrides(source: dict[str, Any]) -> dict[str, Any]:
    instances = {item["id"]: item for item in source["instances"]}
    result: dict[str, Any] = {}
    for item in source["capability_overrides"]:
        alias, _ = item["target"].split(":", 1)
        features = ai.Feature(0)
        for name in item["features"]:
            features |= ai.Feature[name]
        prices = instances[alias]["pricing"]
        result[item["target"]] = ai.ModelCapabilities(
            features=ai.Sourced(features, "override"),
            pricing=ai.Sourced(
                Pricing(
                    input_per_1m=Decimal(prices["input_per_1m"]),
                    output_per_1m=Decimal(prices["output_per_1m"]),
                ),
                "override",
            ),
        )
    return result


@pytest.mark.asyncio
async def test_public_builtin_http_accounting_keeps_only_winning_usage_and_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real configured traffic ties result, completion, manifest, and caller ledger together."""
    source = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setenv("ANYINFER_ACCOUNTING_TEST_KEY", "accounting-fixture-token")
    pending = list(source["calls"])
    requests: list[dict[str, Any]] = []
    adapters: list[Any] = []
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    builtin = registry.get("openai-compat")

    def transport(instance: str) -> httpx2.MockTransport:
        def handle(request: httpx2.Request) -> httpx2.Response:
            script = pending.pop(0)
            assert script["instance"] == instance
            assert request.method == "POST"
            assert request.url.path == "/v1/chat/completions"
            assert request.url.query == b""
            assert request.headers["authorization"] == "Bearer accounting-fixture-token"
            assert request.headers["x-accounting"] == instance
            requests.append(
                {"id": script["id"], "instance": instance, "body": json.loads(request.content)}
            )
            return httpx2.Response(
                int(script["status"]),
                headers=script["headers"],
                content=script["body_utf8"].encode("utf-8"),
            )

        return httpx2.MockTransport(handle)

    def factory(config: Any) -> Any:
        adapter = builtin.factory(replace(config, transport=transport(config.provider_id)))
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
    ledger = SpendLedger()
    observer = _Collector()
    client = ai.AsyncClient(
        providers,
        registry=registry,
        resolver=ResolverChain([EnvResolver()]),
        use_default_catalog=False,
        capability_overrides=_overrides(source),
        observers=[observer],
        ledger=ledger,
    )
    request = source["request"]
    messages = _messages(request["messages"])
    schema = request["schema"]
    try:
        success = await client.generate(messages, target=request["success_target"], schema=schema)
        assert success.usage is not None
        assert success.usage.input_tokens == 2
        assert success.usage.output_tokens == 3
        assert success.usage.cost_usd == Decimal("8")
        assert success.manifest is not None
        assert success.manifest.usage.cost_usd == "8.000000"

        repaired = await client.generate(
            messages,
            target=request["success_target"],
            schema=schema,
            repair=ai.Repair(max_attempts=1),
        )
        assert repaired.structured == {"answer": "fixed"}
        assert repaired.repair_attempts == 1
        assert repaired.usage is not None
        assert (repaired.usage.input_tokens, repaired.usage.output_tokens) == (2, 3)
        assert repaired.usage.cost_usd == Decimal("8")
        assert repaired.manifest is not None
        assert repaired.manifest.usage.cost_usd == "8.000000"

        fallback = await client.generate(
            messages,
            route=ai.Route(
                targets=tuple(request["fallback_route"]),
                retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
            ),
        )
        assert fallback.text == "fallback"
        assert fallback.usage is not None
        assert fallback.usage.cost_usd == Decimal("7")
        assert fallback.manifest is not None
        assert fallback.manifest.usage.cost_usd == "7.000000"
        assert ledger.totals().requests == 3
        assert ledger.totals().cost == Decimal("23")
        completed = [event for event in observer.events if isinstance(event, ai.RequestCompleted)]
        assert len(completed) == 3
        assert all(event.usage is not None for event in completed)
        assert [str(event.target) for event in completed] == [
            "primary:model",
            "primary:model",
            "secondary:model",
        ]
        repaired_completion = next(event for event in completed if event.repair_attempts == 1)
        assert repaired_completion.target.provider_id == "primary"
        repair = next(event for event in observer.events if isinstance(event, ai.RepairAttempted))
        assert repair.request_id == repaired_completion.request_id
        assert str(repair.target) == "primary:model"
        fallback_completion = completed[-1]
        fallback_fact = next(
            event
            for event in observer.events
            if isinstance(event, ai.FallbackTriggered)
            and event.request_id == fallback_completion.request_id
        )
        assert str(fallback_fact.from_target) == "primary:model"
        assert str(fallback_fact.to_target) == "secondary:model"
        assert [entry["id"] for entry in requests] == [item["id"] for item in source["calls"]]
        assert pending == []
        assert requests[0]["body"]["response_format"]["type"] == "json_schema"
        assert requests[1]["body"]["response_format"]["type"] == "json_schema"
        assert requests[2]["body"]["response_format"]["type"] == "json_schema"
        assert "response_format" not in requests[-1]["body"]
        assert all("stream" not in entry["body"] for entry in requests)
    finally:
        await client.aclose()

    assert all(adapter._client.is_closed for adapter in adapters)
