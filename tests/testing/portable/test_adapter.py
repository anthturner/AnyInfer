"""Focused proof that the portable fixture adapter delegates policy to AsyncClient."""

from __future__ import annotations

import asyncio

import pytest

from anyinfer._client.async_client import AsyncClient
from anyinfer.errors import AllTargetsFailedError, SchemaViolationError
from anyinfer.types.events import TextDelta
from anyinfer.types.requests import Repair

from .adapter import FixtureProvider, GateController, HarnessError, ScriptError, VirtualClock


def _config(*entries: dict[str, object], ceiling: int | None = None) -> dict[str, object]:
    return {
        "max_repair_attempts": ceiling,
        "models": {"alpha": {"capabilities": {"grammar": False, "json_schema": False, "json_mode": False}}},
        "health_preset": [],
        "script": list(entries),
    }


async def test_adapter_records_real_wire_request_and_usage() -> None:
    provider = FixtureProvider(
        _config(
            {"events": [{"text": "hello"}, {"usage": {"input_tokens": 2}}, {"final": {"usage": {"output_tokens": 3}}}]}
        )
    )
    async with AsyncClient([provider.settings], registry=provider.registry, use_default_catalog=False) as client:
        result = await client.generate("hi", target="fixture:alpha")

    assert result.text == "hello"
    assert result.usage.input_tokens == 2
    assert result.usage.output_tokens == 3
    assert provider.adapter is not None
    assert provider.adapter.requests[0].model == "alpha"


async def test_real_core_repairs_then_records_correction_wire() -> None:
    provider = FixtureProvider(
        _config(
            {"events": [{"text": '{"name":"x"}'}, {"final": {}}]},
            {"events": [{"text": '{"age":7}'}, {"final": {}}]},
        )
    )
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}
    async with AsyncClient([provider.settings], registry=provider.registry, use_default_catalog=False) as client:
        result = await client.generate(
            "person", target="fixture:alpha", schema=schema, repair=Repair(max_attempts=1)
        )

    assert result.structured == {"age": 7}
    assert provider.adapter is not None
    assert len(provider.adapter.requests) == 2
    assert provider.adapter.requests[1].mechanism == "prompt"


async def test_schema_failure_is_native_when_repair_budget_is_exhausted() -> None:
    provider = FixtureProvider(_config({"events": [{"text": "not json"}, {"final": {}}]}))
    async with AsyncClient([provider.settings], registry=provider.registry, use_default_catalog=False) as client:
        with pytest.raises(SchemaViolationError):
            await client.generate("person", target="fixture:alpha", schema={"type": "object"})


async def test_cleanup_failure_happens_after_final_and_is_recorded() -> None:
    provider = FixtureProvider(
        _config(
            {
                "events": [{"text": "hello"}, {"final": {}}],
                "fail_in_cleanup": {"category": "transport", "retryable": False, "phase": "cleanup"},
            }
        )
    )
    async with AsyncClient([provider.settings], registry=provider.registry, use_default_catalog=False) as client:
        with pytest.raises(AllTargetsFailedError):
            await client.generate("hi", target="fixture:alpha")

    assert provider.adapter is not None
    assert provider.adapter.cleanup_records[0].entry_ordinal == 0


def test_generate_records_invocation_before_returning_iterator() -> None:
    provider = FixtureProvider(_config({"events": []}))
    assert provider.adapter is None

    # Build via the registered descriptor, exactly as AdapterPool does.
    from anyinfer.providers.base import ProviderConfig, WireRequest

    adapter = provider.registry.get("fixture").factory(ProviderConfig(provider_id="fixture"))
    stream = adapter.generate(WireRequest(model="alpha", messages=()))
    assert adapter.requests[0].model == "alpha"
    assert hasattr(stream, "__anext__")


async def test_script_exhaustion_is_a_harness_error() -> None:
    provider = FixtureProvider(_config())
    from anyinfer.providers.base import ProviderConfig, WireRequest

    adapter = provider.registry.get("fixture").factory(ProviderConfig(provider_id="fixture"))
    with pytest.raises(ScriptError):
        adapter.generate(WireRequest(model="alpha", messages=()))


async def test_gate_readiness_release_and_cancellation_are_native() -> None:
    gates = GateController()
    provider = FixtureProvider(
        _config({"events": [{"await_release": "slow"}, {"text": "done"}, {"final": {}}]}),
        gates=gates,
    )
    async with AsyncClient([provider.settings], registry=provider.registry, use_default_catalog=False) as client:
        stream = client.stream("hi", target="fixture:alpha")

        async def consume() -> None:
            async for _ in stream:
                pass

        task = asyncio.create_task(consume())
        await gates.wait_ready("slow")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await stream.aclose()


async def test_gate_release_resumes_at_its_literal_script_position() -> None:
    gates = GateController()
    provider = FixtureProvider(
        _config(
            {"events": [{"text": "before"}, {"await_release": "go"}, {"text": "after"}, {"final": {}}]}
        ),
        gates=gates,
    )
    async with AsyncClient([provider.settings], registry=provider.registry, use_default_catalog=False) as client:
        stream = client.stream("hi", target="fixture:alpha")
        collected: list[object] = []

        async def collect() -> None:
            async for event in stream:
                collected.append(event)

        pending = asyncio.create_task(collect())
        await gates.wait_ready("go")
        gates.release("go")
        await pending

    assert [event.text for event in collected if isinstance(event, TextDelta)] == ["before", "after"]


async def test_gate_watchdog_is_not_a_provider_timeout() -> None:
    gates = GateController(watchdog_s=0.001)
    provider = FixtureProvider(_config({"events": [{"await_release": "never"}]}), gates=gates)
    from anyinfer.providers.base import ProviderConfig, WireRequest

    adapter = provider.registry.get("fixture").factory(ProviderConfig(provider_id="fixture"))
    with pytest.raises(HarnessError):
        await anext(adapter.generate(WireRequest(model="alpha", messages=())))


async def test_unreached_gate_readiness_is_a_harness_error() -> None:
    gates = GateController(watchdog_s=0.001)
    with pytest.raises(HarnessError, match="was not reached"):
        await gates.wait_ready("never")


async def test_virtual_clock_records_nonzero_delays_only() -> None:
    clock = VirtualClock(start_ms=1_250)
    assert clock() == 1.25
    await clock.sleep(0)
    await clock.sleep(0.5)
    assert clock.sleeps == [0.5]
    assert clock() == 1.75


def test_provider_ceiling_is_declared_on_the_descriptor() -> None:
    provider = FixtureProvider(_config({"events": []}, ceiling=2))
    assert provider.registry.get("fixture").max_repair_attempts == 2
