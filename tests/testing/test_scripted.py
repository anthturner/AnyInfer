"""The scripted provider drives the real core, not a parallel one."""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.errors import AllTargetsFailedError, TransportError
from anyinfer.events.telemetry import RetryScheduled
from anyinfer.registry import ProviderRegistry
from anyinfer.testing import ScriptedFailure, ScriptedModel, ScriptedProvider


def _registry() -> ProviderRegistry:
    return ProviderRegistry(load_builtins=True, load_entry_points=False)


def _client(
    provider: ScriptedProvider, registry: ProviderRegistry, **kwargs: object
) -> ai.AsyncClient:
    return ai.AsyncClient(
        [provider.settings()],
        registry=registry,
        use_default_catalog=False,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_scripted_success_reports_usage_and_text() -> None:
    registry = _registry()
    provider = ScriptedProvider("acme", [ScriptedModel("fast", text="scripted hello")])
    provider.register(registry)

    client = _client(provider, registry)
    try:
        result = await client.generate("hi", target=provider.target("fast"))
    finally:
        await client.aclose()

    assert result.text == "scripted hello"
    assert result.usage.output_tokens == 7
    assert provider.call_count("fast") == 1


async def test_status_failure_is_retried_then_succeeds() -> None:
    """A scripted 503 produces a real retry, with the attempt trail to prove it."""
    registry = _registry()
    provider = ScriptedProvider(
        "acme",
        [ScriptedModel("flaky", failures=(ScriptedFailure(status=503, retry_after_s=0.0),))],
    )
    provider.register(registry)

    collected: list[object] = []

    class _Observer:
        def on_event(self, event: object) -> None:
            collected.append(event)

    client = _client(provider, registry, observers=[_Observer()])
    try:
        result = await client.generate("hi", target=provider.target("flaky"))
    finally:
        await client.aclose()

    assert [a.outcome for a in result.attempts] == ["retried", "ok"]
    assert any(isinstance(e, RetryScheduled) for e in collected)
    assert provider.call_count("flaky") == 2


async def test_failures_are_consumed_in_order_and_can_exhaust_the_budget() -> None:
    registry = _registry()
    provider = ScriptedProvider(
        "acme",
        [
            ScriptedModel(
                "doomed",
                failures=(
                    ScriptedFailure(status=503, retry_after_s=0.0),
                    ScriptedFailure(status=503, retry_after_s=0.0),
                ),
            )
        ],
    )
    provider.register(registry)

    client = _client(provider, registry)
    try:
        with pytest.raises((AllTargetsFailedError, TransportError)):
            await client.generate(
                "hi",
                route=ai.Route(
                    targets=(provider.target("doomed"),),
                    retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
                ),
            )
    finally:
        await client.aclose()

    assert provider.call_count("doomed") == 2


async def test_timeout_failure_maps_to_the_typed_timeout_error() -> None:
    registry = _registry()
    provider = ScriptedProvider(
        "acme", [ScriptedModel("slow", failures=(ScriptedFailure(kind="timeout"),))]
    )
    provider.register(registry)

    client = _client(provider, registry)
    try:
        with pytest.raises((AllTargetsFailedError, TransportError)):
            await client.generate(
                "hi",
                route=ai.Route(
                    targets=(provider.target("slow"),),
                    retry=ai.Retry(max_attempts=1, backoff_base_s=0.0),
                ),
            )
    finally:
        await client.aclose()


async def test_malformed_json_failure_drives_the_repair_loop() -> None:
    """The first answer fails validation; the repair round-trip supplies a valid one."""
    registry = _registry()
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    provider = ScriptedProvider(
        "acme",
        [
            ScriptedModel(
                "structured",
                structured={"answer": "eventually valid"},
                failures=(ScriptedFailure(kind="malformed-json"),),
            )
        ],
    )
    provider.register(registry)

    client = _client(provider, registry)
    try:
        result = await client.generate(
            "hi",
            target=provider.target("structured"),
            schema=schema,
            repair=ai.Repair(max_attempts=1),
        )
    finally:
        await client.aclose()

    assert result.structured == {"answer": "eventually valid"}
    assert result.repair_attempts == 1


async def test_refusal_reports_the_content_filter_finish_reason() -> None:
    registry = _registry()
    provider = ScriptedProvider(
        "acme", [ScriptedModel("guarded", failures=(ScriptedFailure(kind="refusal"),))]
    )
    provider.register(registry)

    client = _client(provider, registry)
    try:
        result = await client.generate("hi", target=provider.target("guarded"))
    finally:
        await client.aclose()

    assert result.finish_reason == "content_filter"


async def test_reset_rewinds_the_failure_script() -> None:
    registry = _registry()
    provider = ScriptedProvider(
        "acme", [ScriptedModel("flaky", failures=(ScriptedFailure(retry_after_s=0.0),))]
    )
    provider.register(registry)

    client = _client(provider, registry)
    try:
        await client.generate("first", target=provider.target("flaky"))
        assert provider.call_count("flaky") == 2

        provider.reset()
        assert provider.call_count("flaky") == 0
        assert provider.requests == []

        result = await client.generate("second", target=provider.target("flaky"))
    finally:
        await client.aclose()

    assert result.text
    assert provider.call_count("flaky") == 2


async def test_per_model_capabilities_are_declarable() -> None:
    """A model that declares no JSON support forces a weaker structured mechanism."""
    from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced

    registry = _registry()
    provider = ScriptedProvider(
        "acme",
        [
            ScriptedModel(
                "plain",
                structured={"answer": "ok"},
                capabilities=ModelCapabilities(
                    context_window=Sourced(8_192, "catalog"),
                    features=Sourced(Feature.STREAMING | Feature.SYSTEM_PROMPT, "catalog"),
                ),
            )
        ],
    )
    provider.register(registry)

    client = _client(provider, registry)
    try:
        result = await client.generate(
            "hi",
            target=provider.target("plain"),
            schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        )
    finally:
        await client.aclose()

    assert result.structured == {"answer": "ok"}
    assert result.structured_mechanism == "prompt"


def test_unknown_model_target_is_rejected_at_declaration_time() -> None:
    provider = ScriptedProvider("acme", [ScriptedModel("only")])
    with pytest.raises(KeyError):
        provider.target("missing")
