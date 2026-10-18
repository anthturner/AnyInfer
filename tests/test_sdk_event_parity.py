"""Input-only OpenAI-compatible event and manifest observations through public Python APIs."""

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

_FIXTURE = Path(__file__).parent / "fixtures" / "sdk-events-v1" / "openai-compat-events.json"
_SECRET = "SYNTHETIC-EVENT-SECRET"


class _Observer:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def on_event(self, event: Any) -> None:
        self.events.append(event)


def _event_names(events: list[Any], request_id: str) -> list[str]:
    """Return the public telemetry sequence for one correlated request."""
    return [
        type(event).__name__
        for event in events
        if getattr(event, "request_id", None) == request_id
    ]


def _contains_subsequence(values: list[str], expected: list[str]) -> bool:
    """Avoid pinning unrelated telemetry while retaining causal ordering."""
    cursor = 0
    for value in values:
        if cursor < len(expected) and value == expected[cursor]:
            cursor += 1
    return cursor == len(expected)


def _typed_messages(raw_messages: list[dict[str, Any]]) -> tuple[Any, ...]:
    """Project input-only role/content fixture values through public constructors."""
    builders = {"system": ai.system, "user": ai.user, "assistant": ai.assistant}
    return tuple(builders[str(message["role"])](str(message["content"])) for message in raw_messages)


def _capability_overrides(source: dict[str, Any]) -> dict[str, Any]:
    """Build public override values from the fixture's declared capability premise."""
    overrides: dict[str, Any] = {}
    for entry in source["capability_overrides"]:
        features = ai.Feature(0)
        for name in entry["features"]:
            features |= ai.Feature[str(name)]
        overrides[str(entry["target"])] = ai.ModelCapabilities(
            features=ai.Sourced(features, "override")
        )
    return overrides


@pytest.mark.asyncio
async def test_public_builtin_event_and_manifest_projections_are_causal_and_payload_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real public calls keep the fixture to traffic while assertions own the oracle."""
    source = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setenv("ANYINFER_SDK_EVENT_TEST_KEY", "event-fixture-token")
    ai.register_secret(_SECRET)
    scripts = [script for script in source["calls"] if not script["id"].startswith("matrix-")]
    sent: list[dict[str, Any]] = []
    adapters: list[Any] = []
    builtin = ProviderRegistry(load_builtins=True, load_entry_points=False).get("openai-compat")

    def transport(instance: str) -> httpx2.MockTransport:
        def handle(request: httpx2.Request) -> httpx2.Response:
            script = scripts.pop(0)
            assert script["instance"] == instance
            assert request.method == "POST"
            assert request.url.path == "/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer event-fixture-token"
            assert request.headers["x-event"] == instance
            sent.append({"id": script["id"], "instance": instance, "body": json.loads(request.content)})
            return httpx2.Response(int(script["status"]), headers=script["headers"], content=script["body_utf8"].encode("utf-8"))
        return httpx2.MockTransport(handle)

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    def factory(config: Any) -> Any:
        adapter = builtin.factory(replace(config, transport=transport(config.provider_id)))
        adapters.append(adapter)
        return adapter
    registry.register(replace(builtin, factory=factory), replace=True)
    providers = [
        ai.ProviderSettings.of(item["adapter"], base_url=item["base_url"], api_key=item["credential"], headers=item["headers"], timeout_s=item["timeout_s"], alias=item["id"])
        for item in source["instances"]
    ]
    observer = _Observer()
    client = ai.AsyncClient(
        providers,
        registry=registry,
        resolver=ResolverChain([EnvResolver()]),
        use_default_catalog=False,
        capability_overrides=_capability_overrides(source),
    )
    client.subscribe(observer)
    request = source["request"]
    messages = _typed_messages(request["messages"])
    try:
        success = await client.generate(messages, target=request["success_target"], schema=request["schema"])
        assert success.text == '{"answer":"café 𐀀"}'
        assert success.manifest is not None
        assert success.manifest.payloads is None
        assert success.manifest.usage.search_units is None
        assert _SECRET not in repr(observer.events)
        assert sent[0]["body"]["model"] == "model"
        assert sent[0]["body"]["response_format"]["type"] == "json_schema"

        repair_events = [event async for event in client.stream(messages, target=request["success_target"], schema=request["schema"], repair=ai.Repair(max_attempts=1))]
        assert [event.name for event in repair_events if isinstance(event, ai.TimingMark)] == ["attempt_start", "first_token", "attempt_start", "first_token"]
        ended = repair_events[-1]
        assert isinstance(ended, ai.StreamEnded)
        assert ended.result.repair_attempts == 1
        assert ended.result.structured == {"answer": "fixed"}
        repair_event = next(
            event for event in observer.events if isinstance(event, ai.RepairAttempted)
        )
        assert repair_event.raw_text is None
        assert _contains_subsequence(
            _event_names(observer.events, repair_event.request_id),
            ["RequestStarted", "RepairAttempted", "RequestCompleted"],
        )

        fallback = await client.generate(messages, route=ai.Route(targets=tuple(request["fallback_route"]), retry=ai.Retry(max_attempts=2, backoff_base_s=0.0)))
        assert fallback.text == "fallback ok"
        fallback_completed = [
            event for event in observer.events if isinstance(event, ai.RequestCompleted)
        ][-1]
        assert _contains_subsequence(
            _event_names(observer.events, fallback_completed.request_id),
            ["RequestStarted", "RetryScheduled", "FallbackTriggered", "RequestCompleted"],
        )
        assert [entry["id"] for entry in sent] == ["success", "repair-invalid", "repair-corrected", "retryable-primary", "retryable-primary-again", "fallback-secondary"]
        assert scripts == []
        assert all(adapter._client.is_closed is False for adapter in adapters)
    finally:
        await client.aclose()

    assert all(adapter._client.is_closed for adapter in adapters)


@pytest.mark.asyncio
async def test_public_repair_payload_privacy_matrix_inherits_manifest_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manifest and observer payload capture remain separate public opt-ins."""
    source = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setenv("ANYINFER_SDK_EVENT_TEST_KEY", "event-fixture-token")
    calls_by_id = {script["id"]: script for script in source["calls"]}
    builtin = ProviderRegistry(load_builtins=True, load_entry_points=False).get("openai-compat")
    request = source["request"]
    messages = _typed_messages(request["messages"])

    async def run_repair(
        case: str,
        *,
        manifest_payloads: bool,
        observer_payloads: bool,
        manifests: bool = True,
    ) -> tuple[Any, _Observer, _Observer, list[dict[str, Any]]]:
        scripts = [calls_by_id[f"matrix-{case}-invalid"], calls_by_id[f"matrix-{case}-corrected"]]
        sent: list[dict[str, Any]] = []
        adapters: list[Any] = []

        def transport(instance: str) -> httpx2.MockTransport:
            def handle(http_request: httpx2.Request) -> httpx2.Response:
                script = scripts.pop(0)
                assert script["instance"] == instance == "primary"
                assert http_request.method == "POST"
                assert http_request.url.path == "/v1/chat/completions"
                assert http_request.headers["authorization"] == "Bearer event-fixture-token"
                sent.append(json.loads(http_request.content))
                return httpx2.Response(
                    int(script["status"]),
                    headers=script["headers"],
                    content=script["body_utf8"].encode("utf-8"),
                )

            return httpx2.MockTransport(handle)

        registry = ProviderRegistry(load_builtins=True, load_entry_points=False)

        def factory(config: Any) -> Any:
            adapter = builtin.factory(replace(config, transport=transport(config.provider_id)))
            adapters.append(adapter)
            return adapter

        registry.register(replace(builtin, factory=factory), replace=True)
        primary = next(item for item in source["instances"] if item["id"] == "primary")
        client = ai.AsyncClient(
            [
                ai.ProviderSettings.of(
                    primary["adapter"],
                    base_url=primary["base_url"],
                    api_key=primary["credential"],
                    headers=primary["headers"],
                    timeout_s=primary["timeout_s"],
                    alias=primary["id"],
                )
            ],
            registry=registry,
            resolver=ResolverChain([EnvResolver()]),
            use_default_catalog=False,
            manifests=manifests,
            manifest_payloads=manifest_payloads,
            capability_overrides={
                request["success_target"]: _capability_overrides(source)[request["success_target"]]
            },
        )
        payload_observer = _Observer()
        sibling = _Observer()
        client.subscribe(payload_observer, payloads=observer_payloads)
        client.subscribe(sibling, payloads=False)
        try:
            result = await client.generate(
                messages,
                target=request["success_target"],
                schema=request["schema"],
                repair=ai.Repair(max_attempts=1),
                manifest=None,
            )
            assert scripts == []
            assert len(sent) == 2
            assert result.text == '{"answer":"fixed"}'
            assert result.structured == {"answer": "fixed"}
            assert result.repair_attempts == 1
            return result, payload_observer, sibling, sent
        finally:
            await client.aclose()
            assert all(adapter._client.is_closed for adapter in adapters)

    for case, manifest_payloads, observer_payloads, expected_repair_texts in (
        ("ff", False, False, 0),
        ("tf", True, False, 1),
        ("ft", False, True, 0),
        ("tt", True, True, 2),
    ):
        result, payload_observer, sibling, sent = await run_repair(
            case,
            manifest_payloads=manifest_payloads,
            observer_payloads=observer_payloads,
        )
        assert [body["model"] for body in sent] == ["model", "model"]
        assert result.manifest is not None
        repair_texts = () if result.manifest.payloads is None else result.manifest.payloads.repair_texts
        assert len(repair_texts) == expected_repair_texts
        payload_repairs = [
            event for event in payload_observer.events if isinstance(event, ai.RepairAttempted)
        ]
        sibling_repairs = [event for event in sibling.events if isinstance(event, ai.RepairAttempted)]
        assert len(payload_repairs) == len(sibling_repairs) == 1
        assert payload_repairs[0].raw_text == ("not json" if observer_payloads else None)
        assert sibling_repairs[0].raw_text is None
        assert payload_repairs[0].request_id == sibling_repairs[0].request_id

    disabled, disabled_payload_observer, disabled_sibling, _ = await run_repair(
        "disabled",
        manifest_payloads=True,
        observer_payloads=False,
        manifests=False,
    )
    assert disabled.manifest is None
    assert [
        event.raw_text
        for event in disabled_payload_observer.events
        if isinstance(event, ai.RepairAttempted)
    ] == [None]
    assert [event.raw_text for event in disabled_sibling.events if isinstance(event, ai.RepairAttempted)] == [None]
