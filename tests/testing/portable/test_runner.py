"""Smoke coverage for raw portable fixture execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from anyinfer._client.stream import AsyncStream
from anyinfer.events.telemetry import ParameterDropped, RepairAttempted
from anyinfer.schema._capture import _ACTIVE

from . import runner
from .adapter import FixtureProvider, GateController, HarnessError, ScriptError
from .runner import run_fixture

FIXTURES = sorted(Path("specification/fixtures/core-generation").rglob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
async def test_runner_executes_fixture_without_harness_fault(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    run = await run_fixture(fixture)
    assert run.error_stage != "harness"
    if run.requests:
        assert len(run.operations) == 1
        assert run.operations[0].evidence_available
    else:
        assert all(operation.evidence_available for operation in run.operations)


async def test_runner_observes_stream_close_cancel_mirror_and_native_facts() -> None:
    def load(family: str, name: str) -> dict[str, object]:
        return json.loads((Path("specification/fixtures/core-generation") / family / f"{name}.json").read_text())

    buffered = await run_fixture(load("normalization", "sampling-supplied-fields"))
    streamed = await run_fixture(load("streaming", "failed-attempt-deltas-visible"))
    zero = await run_fixture(load("streaming", "zero-advance-close"))
    twice = await run_fixture(load("lifecycle", "repeated-close-idempotent"))
    cancelled = await run_fixture(load("streaming", "cancel-mid-stream"))
    mirror = await run_fixture(load("streaming", "buffered-equals-streamed"))

    assert buffered.consumption_mode == "buffered" and buffered.requests[0].sampling.seed == 7
    assert streamed.consumption_mode == "stream" and streamed.events and streamed.requests
    assert zero.requests == () and zero.events == () and zero.result is None
    assert twice.consumption_mode == "stream" and twice.result is not None
    assert isinstance(cancelled.error, asyncio.CancelledError)
    assert cancelled.error_stage == "operation" and len(cancelled.events) == 3
    assert mirror.mirror is not None
    assert mirror.consumption_mode == "stream" and mirror.mirror.consumption_mode == "buffered"
    assert mirror.operations[0] is not mirror.mirror.operations[0]


async def test_runner_marks_sampling_and_lazy_target_construction_boundaries() -> None:
    seed = await run_fixture(json.loads((Path("specification/fixtures/core-generation/normalization/invalid-sampling-negative-seed.json")).read_text()))
    lazy = await run_fixture(json.loads((Path("specification/fixtures/core-generation/routing/lazy-invalid-second-target.json")).read_text()))
    assert seed.construction_origin == "sampling" and seed.error_stage == "construction"
    assert lazy.error_stage == "operation" and lazy.error is not None


async def test_runner_records_supplied_wire_controls_and_repair_drop_telemetry() -> None:
    controls = load_fixture("normalization", "sampling-supplied-fields")
    controls["request"]["timeout_s"] = 17
    controls["request"]["max_response_bytes"] = 321
    clamped = load_fixture("repair", "provider-ceiling-clamp-parameter-dropped")

    supplied = await run_fixture(controls)
    dropped = await run_fixture(clamped)

    wire = supplied.requests[0]
    assert wire.sampling.seed == 7
    assert wire.sampling.stop == ["END", "STOP"]
    assert wire.timeout_s == 17 and wire.max_response_bytes == 321
    assert [type(event) for event in dropped.telemetry] == [ParameterDropped, RepairAttempted]
    parameter_dropped, repair_attempted = dropped.telemetry
    assert parameter_dropped.parameter == "repair.max_attempts"
    assert repair_attempted.attempt_number == 1


async def test_runner_observes_health_skip_and_expiry_from_native_requests() -> None:
    skipped = await run_fixture(load_fixture("routing", "health-skip-in-trail"))
    expired = await run_fixture(load_fixture("routing", "health-recovery-after-ttl"))

    assert skipped.result is not None and skipped.result.target.model == "beta"
    assert skipped.requests[0].model == "beta"
    assert expired.result is not None and expired.result.target.model == "alpha"
    assert expired.requests[0].model == "alpha"


async def test_runner_preserves_multipart_input_messages_in_the_raw_record() -> None:
    run = await run_fixture(load_fixture("normalization", "multi-part-text-concatenated"))

    assert run.input_messages is not None
    assert [part.text for part in run.input_messages[1].content] == ["first ", "second", " third"]


async def test_runner_keeps_native_message_construction_separate_from_driver_codec_faults() -> None:
    image = load_fixture("normalization", "sampling-omitted-when-unset")
    image["request"]["messages"] = [
        {"role": "user", "parts": [{"kind": "image_url", "url": "https://example.invalid/image", "media_type": "text/plain"}]}
    ]
    malformed = load_fixture("normalization", "sampling-omitted-when-unset")
    malformed["request"]["messages"] = "not-an-array"

    native = await run_fixture(image)
    driver = await run_fixture(malformed)

    assert isinstance(native.error, ValueError)
    assert native.error_stage == "construction"
    assert native.construction_origin == "messages"
    assert isinstance(driver.error, HarnessError)
    assert driver.error_stage == "harness"
    assert driver.construction_origin is None


@pytest.mark.parametrize("threshold", [2, 4])
async def test_runner_rejects_cancellation_gates_that_do_not_prove_the_exact_threshold(
    threshold: int,
) -> None:
    fixture = load_fixture("streaming", "cancel-mid-stream")
    fixture["request"]["consume"] = f"stream_cancel_after_events:{threshold}"

    run = await run_fixture(fixture)

    assert isinstance(run.error, HarnessError)
    assert run.error_stage == "harness"
    assert run.events and len(run.events) == 3


@pytest.mark.parametrize(
    ("script", "expected_error"),
    [
        ([], ScriptError),
        ([{"events": [{"not_an_event": "bad"}]}], ScriptError),
    ],
    ids=["exhausted", "malformed-action"],
)
async def test_runner_classifies_script_faults_as_harness_faults(
    script: list[object], expected_error: type[ScriptError]
) -> None:
    fixture = load_fixture("normalization", "sampling-omitted-when-unset")
    fixture["adapter"]["script"] = script

    run = await run_fixture(fixture)

    assert isinstance(run.error, expected_error)
    assert run.error_stage == "harness"


class _ParentCancellationGate(GateController):
    def __init__(self) -> None:
        super().__init__()
        self.driver_waiting = asyncio.Event()
        self.allow_driver = asyncio.Event()

    async def wait_ready(self, gate_id: str) -> None:
        await super().wait_ready(gate_id)
        self.driver_waiting.set()
        await self.allow_driver.wait()


class _ReadinessWatchdogGate(GateController):
    async def wait_ready(self, gate_id: str) -> None:
        await super().wait_ready(gate_id)
        raise HarnessError("controlled gate watchdog failure")


def load_fixture(family: str, name: str) -> dict[str, object]:
    return json.loads(
        (Path("specification/fixtures/core-generation") / family / f"{name}.json").read_text()
    )


def install_tracking_provider(
    monkeypatch: pytest.MonkeyPatch, gate: GateController
) -> list[FixtureProvider]:
    providers: list[FixtureProvider] = []

    class TrackingProvider(FixtureProvider):
        def __init__(self, adapter_config: object) -> None:
            assert isinstance(adapter_config, dict)
            super().__init__(adapter_config, gates=gate)
            providers.append(self)

    monkeypatch.setattr(runner, "FixtureProvider", TrackingProvider)
    return providers


def track_runner_children(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Task[object]]:
    children: list[asyncio.Task[object]] = []
    original = runner.asyncio.create_task

    def create_task(coro: object) -> asyncio.Task[object]:
        task = original(coro)
        if getattr(coro, "__qualname__", "").endswith(".drain"):
            children.append(task)
        return task

    monkeypatch.setattr(runner.asyncio, "create_task", create_task)
    return children


async def test_runner_parent_cancellation_cleans_up_gated_sdk_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _ParentCancellationGate()
    providers = install_tracking_provider(monkeypatch, gate)
    children = track_runner_children(monkeypatch)
    closes: list[AsyncStream] = []
    original_aclose = AsyncStream.aclose

    async def record_close(stream: AsyncStream) -> None:
        closes.append(stream)
        await original_aclose(stream)

    monkeypatch.setattr(AsyncStream, "aclose", record_close)
    parent = asyncio.create_task(run_fixture(load_fixture("streaming", "cancel-mid-stream")))

    await gate.driver_waiting.wait()
    parent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await parent

    assert len(children) == 1 and children[0].done() and children[0].cancelled()
    assert len(closes) == 1
    assert providers[0].adapter is not None and providers[0].adapter._closed
    assert _ACTIVE.get() is None


async def test_runner_watchdog_fault_cleans_up_gated_sdk_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = install_tracking_provider(monkeypatch, _ReadinessWatchdogGate())
    children = track_runner_children(monkeypatch)
    closes: list[AsyncStream] = []
    original_aclose = AsyncStream.aclose

    async def record_close(stream: AsyncStream) -> None:
        closes.append(stream)
        await original_aclose(stream)

    monkeypatch.setattr(AsyncStream, "aclose", record_close)

    run = await run_fixture(load_fixture("streaming", "cancel-mid-stream"))

    assert isinstance(run.error, HarnessError)
    assert run.error_stage == "harness"
    assert len(children) == 1 and children[0].done() and children[0].cancelled()
    assert len(closes) == 1
    assert providers[0].adapter is not None and providers[0].adapter._closed
    assert _ACTIVE.get() is None
