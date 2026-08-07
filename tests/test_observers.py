"""Observer dispatch, payload privacy, and isolation from observer failures."""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer.events.observers import EventDispatcher
from anyinfer.events.telemetry import RequestCompleted, RequestStarted, strip_payloads
from anyinfer.registry import ProviderDescriptor, ProviderRegistry
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.results import Timing, Usage
from support import make_client, make_multi_client


class Recorder:
    """A minimal observer that keeps everything it receives."""

    def __init__(self) -> None:
        self.events: list[ai.TelemetryEvent] = []

    def on_event(self, event: ai.TelemetryEvent) -> None:
        self.events.append(event)

    def of_type(self, cls: type) -> list[ai.TelemetryEvent]:
        return [e for e in self.events if isinstance(e, cls)]


# ---- dispatch ------------------------------------------------------------------------


def test_events_reach_registered_observers() -> None:
    recorder = Recorder()
    dispatcher = EventDispatcher([recorder])
    dispatcher.emit(RequestStarted("r1", ("openai:gpt-5",)))

    assert len(recorder.events) == 1


def test_unsubscribe_stops_delivery() -> None:
    recorder = Recorder()
    dispatcher = EventDispatcher([recorder])
    dispatcher.unsubscribe(recorder)
    dispatcher.emit(RequestStarted("r1", ()))

    assert recorder.events == []


def test_a_failing_observer_does_not_break_the_others() -> None:
    class Exploding:
        def on_event(self, event: ai.TelemetryEvent) -> None:
            raise RuntimeError("observer is broken")

    good = Recorder()
    dispatcher = EventDispatcher([Exploding(), good])

    with pytest.warns(RuntimeWarning, match="observer is broken"):
        dispatcher.emit(RequestStarted("r1", ()))

    assert len(good.events) == 1, "a broken sink must not suppress a working one"


def test_observer_failure_warns_only_once() -> None:
    class Exploding:
        def on_event(self, event: ai.TelemetryEvent) -> None:
            raise RuntimeError("broken")

    dispatcher = EventDispatcher([Exploding()])
    with pytest.warns(RuntimeWarning):
        dispatcher.emit(RequestStarted("r1", ()))

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        dispatcher.emit(RequestStarted("r2", ()))


# ---- payload privacy -----------------------------------------------------------------


def test_payload_fields_are_stripped_by_default() -> None:
    event = RequestStarted("r1", (), prompt_text="secret prompt")
    assert strip_payloads(event).prompt_text is None


def test_stripping_leaves_payload_free_events_untouched() -> None:
    """Events with no payload fields pass through without being copied."""
    event = ai.AttemptStarted("r1", ai.ResolvedTarget("p", "m"), 1)
    assert strip_payloads(event) is event


def test_response_text_is_stripped_from_request_completed() -> None:
    event = RequestCompleted(
        "r1",
        ai.ResolvedTarget("p", "m"),
        Usage(),
        Timing(started_at=0.0),
        response_text="the answer",
    )
    stripped = strip_payloads(event)
    assert isinstance(stripped, RequestCompleted)
    assert stripped.response_text is None
    assert stripped.usage == event.usage, "non-payload fields survive"


def test_observers_without_opt_in_never_see_payloads() -> None:
    private = Recorder()
    trusted = Recorder()
    dispatcher = EventDispatcher()
    dispatcher.subscribe(private)
    dispatcher.subscribe(trusted, payloads=True)

    dispatcher.emit(RequestStarted("r1", (), prompt_text="the actual prompt"))

    private_event = private.events[0]
    trusted_event = trusted.events[0]
    assert isinstance(private_event, RequestStarted)
    assert isinstance(trusted_event, RequestStarted)
    assert private_event.prompt_text is None
    assert trusted_event.prompt_text == "the actual prompt"


def test_wants_payloads_reflects_subscriptions() -> None:
    dispatcher = EventDispatcher()
    assert dispatcher.has_observers is False
    dispatcher.subscribe(Recorder())
    assert dispatcher.has_observers is True
    assert dispatcher.wants_payloads is False
    dispatcher.subscribe(Recorder(), payloads=True)
    assert dispatcher.wants_payloads is True


# ---- end-to-end lifecycle ------------------------------------------------------------


async def test_lifecycle_events_for_a_successful_request() -> None:
    recorder = Recorder()
    server = FakeOpenAIServer(FakeResponse(text="hello"))
    async with make_client(server, observers=[recorder]) as client:
        await client.generate("hi", target="openai-compat:m")

    types = [type(e).__name__ for e in recorder.events]
    assert types[0] == "RequestStarted"
    assert "TargetResolved" in types
    assert "AttemptStarted" in types
    assert "FirstToken" in types
    assert "AttemptCompleted" in types
    assert types[-1] == "RequestCompleted"


async def test_retry_and_failure_events() -> None:
    recorder = Recorder()
    server = FakeOpenAIServer(
        [
            FakeResponse(status=503, error_message="down"),
            FakeResponse(text="recovered"),
        ]
    )
    async with make_client(server, observers=[recorder]) as client:
        await client.generate(
            "hi",
            route=ai.Route(
                targets=("openai-compat:m",),
                retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
            ),
        )

    retries = recorder.of_type(ai.RetryScheduled)
    assert len(retries) == 1


async def test_request_failed_event_on_exhaustion() -> None:
    recorder = Recorder()
    server = FakeOpenAIServer(FakeResponse(status=401, error_message="bad key"))
    async with make_client(server, observers=[recorder]) as client:
        with pytest.raises(ai.AllTargetsFailedError):
            await client.generate("hi", target="openai-compat:m")

    assert recorder.of_type(ai.RequestFailed)


async def test_repair_events_are_emitted() -> None:
    recorder = Recorder()
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    server = FakeOpenAIServer(
        [FakeResponse(text="{}"), FakeResponse(text=json.dumps({"n": 1}))]
    )
    async with make_client(server, observers=[recorder]) as client:
        await client.generate(
            "hi", target="openai-compat:m", schema=schema, repair=ai.Repair(max_attempts=1)
        )

    repairs = recorder.of_type(ai.RepairAttempted)
    assert len(repairs) == 1


async def test_payload_free_by_default_end_to_end() -> None:
    recorder = Recorder()
    server = FakeOpenAIServer(FakeResponse(text="the model's answer"))
    async with make_client(server, observers=[recorder]) as client:
        await client.generate("my private prompt", target="openai-compat:m")

    for event in recorder.events:
        if isinstance(event, RequestStarted):
            assert event.prompt_text is None
        if isinstance(event, RequestCompleted):
            assert event.response_text is None


async def test_opted_in_observer_receives_payloads_end_to_end() -> None:
    recorder = Recorder()
    server = FakeOpenAIServer(FakeResponse(text="the model's answer"))
    async with make_client(server) as client:
        client.subscribe(recorder, payloads=True)
        await client.generate("my private prompt", target="openai-compat:m")

    started = recorder.of_type(RequestStarted)[0]
    completed = recorder.of_type(RequestCompleted)[0]
    assert isinstance(started, RequestStarted)
    assert isinstance(completed, RequestCompleted)
    assert started.prompt_text == "my private prompt"
    assert completed.response_text == "the model's answer"


# ---- derived-usage and lifecycle telemetry -------------------------------------------


async def test_context_gate_estimation_emits_usage_estimated() -> None:
    """The pre-dispatch gate derives an input estimate; observers must see the derivation."""
    recorder = Recorder()
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(server, observers=[recorder]) as client:
        await client.generate("hello", target="openai-compat:m")

    estimated = recorder.of_type(ai.UsageEstimated)
    assert estimated, "the context gate must announce its estimate"
    event = estimated[0]
    assert event.field_name == "input_tokens"  # type: ignore[union-attr]


async def test_adapter_lifecycle_events_share_the_client_dispatcher() -> None:
    """ProviderConfig.events is wired to the same dispatcher request telemetry uses."""
    from anyinfer._client.providers import AdapterPool
    from anyinfer.providers.base import ProviderConfig
    from anyinfer.registry import ProviderRegistry

    captured: list[ai.TelemetryEvent] = []
    seen_config: list[ProviderConfig] = []

    class _Probe:
        def __init__(self, config: ProviderConfig) -> None:
            seen_config.append(config)

        async def aclose(self) -> None:
            return None

    from anyinfer.registry import ProviderDescriptor

    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    registry.register(
        ProviderDescriptor(id="probe", display_name="Probe", factory=_Probe)
    )
    pool = AdapterPool(
        [ai.ProviderSettings.of("probe")], registry=registry, events=captured.append
    )
    await pool.get("probe")

    assert seen_config and seen_config[0].events is not None
    seen_config[0].events(ai.ServerLifecycle(server_id="m", state="ready"))
    assert isinstance(captured[0], ai.ServerLifecycle)
    await pool.aclose()


# ---- fallback telemetry --------------------------------------------------------------


def _two_provider_registry() -> ProviderRegistry:
    """The openai-compat adapter under two ids, so a fallback chain crosses providers."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.providers.openai_compat import descriptor as base

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    for provider_id in ("primary", "secondary"):
        registry.register(
            ProviderDescriptor(
                id=provider_id,
                display_name=f"Fake {provider_id}",
                factory=OpenAICompatAdapter,
                requires_base_url=True,
                default_capabilities=base.default_capabilities,
            )
        )
    return registry


async def test_fallback_triggered_names_the_abandoned_and_next_targets() -> None:
    recorder = Recorder()
    failing = FakeOpenAIServer(FakeResponse(status=500, error_message="boom"))
    healthy = FakeOpenAIServer(FakeResponse(text="from the backup"))
    client = make_multi_client(
        [("primary", failing), ("secondary", healthy)],
        registry=_two_provider_registry(),
        observers=[recorder],
    )
    async with client:
        result = await client.generate(
            "hi",
            route=ai.Route(
                targets=("primary:m", "secondary:m"), retry=ai.Retry(max_attempts=1)
            ),
        )

    assert result.text == "from the backup"
    events = recorder.of_type(ai.FallbackTriggered)
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ai.FallbackTriggered)
    assert event.from_target == ai.ResolvedTarget("primary", "m")
    assert event.to_target == "secondary:m"
    assert event.error is not None
    assert event.error.type_name == "ProviderUnavailableError"
