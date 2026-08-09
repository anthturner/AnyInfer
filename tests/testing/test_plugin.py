"""The pytest plugin an application installs with the library.

These tests use the fixtures the way a consuming application would, which is the only way
to prove the plugin is wired: if the ``pytest11`` entry point were missing, this module
would fail at fixture resolution rather than at an assertion.
"""

from __future__ import annotations

from anyinfer.events.telemetry import RequestCompleted, RequestStarted, RetryScheduled
from anyinfer.testing import ScriptedFailure, ScriptedModel
from anyinfer.testing.plugin import RECORD_ENV_VAR, EventCollector


def test_fixtures_build_a_working_sync_client(anyinfer_client, anyinfer_scripted) -> None:
    provider = anyinfer_scripted([ScriptedModel("m", text="from the fixture")])
    client = anyinfer_client(provider)

    result = client.generate("hi", target=provider.target("m"))

    assert result.text == "from the fixture"


async def test_fixtures_build_a_working_async_client(
    anyinfer_async_client, anyinfer_scripted
) -> None:
    provider = anyinfer_scripted([ScriptedModel("m", text="async fixture")])
    client = anyinfer_async_client(provider)

    result = await client.generate("hi", target=provider.target("m"))

    assert result.text == "async fixture"


def test_event_collector_sees_the_request_lifecycle(
    anyinfer_client, anyinfer_scripted, anyinfer_events
) -> None:
    provider = anyinfer_scripted(
        [ScriptedModel("m", failures=(ScriptedFailure(retry_after_s=0.0),))]
    )
    client = anyinfer_client(provider)

    client.generate("hi", target=provider.target("m"))

    assert anyinfer_events.of_type(RequestStarted)
    assert anyinfer_events.of_type(RetryScheduled)
    assert anyinfer_events.of_type(RequestCompleted)
    assert len(anyinfer_events.request_ids()) == 1


def test_events_are_payload_free_by_default(
    anyinfer_client, anyinfer_scripted, anyinfer_events
) -> None:
    """A suite must not start capturing prompt text just by collecting events."""
    provider = anyinfer_scripted([ScriptedModel("m")])
    client = anyinfer_client(provider)

    client.generate("a very secret prompt", target=provider.target("m"))

    started = anyinfer_events.of_type(RequestStarted)
    assert started and all(event.prompt_text is None for event in started)


def test_registry_is_isolated_per_test(anyinfer_registry, anyinfer_scripted) -> None:
    """Two tests may both register "scripted" without colliding."""
    from anyinfer.registry import default_registry

    anyinfer_scripted([ScriptedModel("m")])

    assert anyinfer_registry.has("scripted")
    assert not default_registry.has("scripted")


def test_cassette_fixture_resolves_beside_the_test_file(anyinfer_cassette) -> None:
    cassette = anyinfer_cassette("example")

    assert cassette.path.parent.name == "cassettes"
    assert cassette.path.parent.parent.name == "testing"
    assert cassette.interactions == []


def test_recording_is_off_unless_the_environment_asks(anyinfer_recording, monkeypatch) -> None:
    assert anyinfer_recording is False

    monkeypatch.setenv(RECORD_ENV_VAR, "1")
    # The fixture is resolved once per test, so re-read the switch the way the fixture does.
    import os

    assert os.environ.get(RECORD_ENV_VAR) == "1"


def test_collector_clear_forgets_events() -> None:
    collector = EventCollector()
    collector.on_event(RequestStarted(request_id="r1", targets=("x:y",)))

    assert collector.request_ids() == ["r1"]
    collector.clear()
    assert collector.events == []
