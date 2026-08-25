"""The ready-made telemetry sinks: structured logging and JSONL."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer.events.sinks import event_to_dict
from anyinfer.events.telemetry import RequestStarted
from anyinfer.redaction import REDACTED, register_secret, registry
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse


def _started(**overrides: object) -> RequestStarted:
    fields: dict[str, object] = {
        "request_id": "r1",
        "targets": ("openai:gpt-5",),
        "metadata": {"tenant": "acme"},
        "prompt_text": None,
    }
    fields.update(overrides)
    return RequestStarted(**fields)  # type: ignore[arg-type]


# ---- serialization -------------------------------------------------------------------


def test_event_to_dict_names_the_event_and_keeps_every_field() -> None:
    payload = event_to_dict(_started())
    assert payload["event"] == "RequestStarted"
    assert payload["request_id"] == "r1"
    assert payload["targets"] == ["openai:gpt-5"], "tuples become JSON arrays"
    assert payload["metadata"] == {"tenant": "acme"}


def test_event_to_dict_output_is_json_serializable() -> None:
    json.dumps(event_to_dict(_started()))


def test_a_registered_secret_is_redacted_even_nested() -> None:
    """A credential that reached an event field must not reach the sink."""
    registry.clear()
    try:
        register_secret("sk-a-very-secret-value")
        payload = event_to_dict(_started(metadata={"key": "sk-a-very-secret-value"}))
        assert "sk-a-very-secret-value" not in json.dumps(payload)
        assert payload["metadata"]["key"] == REDACTED
    finally:
        registry.clear()


def test_a_secret_in_a_mapping_key_is_redacted_too() -> None:
    """A key is caller-supplied as often as a value, and nothing else on this path checks it."""
    registry.clear()
    try:
        register_secret("sk-a-very-secret-value")
        payload = event_to_dict(_started(metadata={"sk-a-very-secret-value": "whose"}))
        assert "sk-a-very-secret-value" not in json.dumps(payload)
        assert payload["metadata"] == {REDACTED: "whose"}
    finally:
        registry.clear()


# ---- JsonlObserver -------------------------------------------------------------------


def test_jsonl_observer_writes_one_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"
    with ai.JsonlObserver(path) as observer:
        observer.on_event(_started())
        observer.on_event(_started(request_id="r2"))

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["request_id"] for line in lines] == ["r1", "r2"]


def test_jsonl_observer_appends_rather_than_truncating(tmp_path: Path) -> None:
    """A restarted process must not erase the previous run's telemetry."""
    path = tmp_path / "telemetry.jsonl"
    with ai.JsonlObserver(path) as observer:
        observer.on_event(_started())
    with ai.JsonlObserver(path) as observer:
        observer.on_event(_started(request_id="r2"))

    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_jsonl_file_is_not_readable_by_other_local_users(tmp_path: Path) -> None:
    """Payload-free telemetry still names targets, models, and spend."""
    path = tmp_path / "telemetry.jsonl"
    with ai.JsonlObserver(path):
        pass
    assert path.stat().st_mode & 0o777 == 0o600


def test_the_jsonl_file_is_owner_restricted_where_the_platform_allows_it(
    tmp_path: Path,
) -> None:
    """Pins what actually happens on each platform rather than skipping one of them."""
    from anyinfer._private_files import OWNER_ONLY_IS_ENFORCED

    path = tmp_path / "telemetry.jsonl"
    with ai.JsonlObserver(path):
        pass

    if OWNER_ONLY_IS_ENFORCED:
        assert path.stat().st_mode & 0o777 == 0o600
    else:
        # Windows reports a mode the call did not really set; the sink documents that it
        # cannot restrict there, and this asserts the file is at least created.
        assert path.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_jsonl_observer_tightens_an_existing_wider_mode_file(tmp_path: Path) -> None:
    """`os.open`'s mode argument applies only on creation; an existing file keeps its own."""
    path = tmp_path / "telemetry.jsonl"
    path.write_text("")
    path.chmod(0o644)

    with ai.JsonlObserver(path):
        pass

    assert path.stat().st_mode & 0o777 == 0o600


def test_jsonl_observer_creates_missing_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "telemetry.jsonl"
    with ai.JsonlObserver(path) as observer:
        observer.on_event(_started())
    assert path.exists()


def test_events_after_close_are_dropped_not_raised(tmp_path: Path) -> None:
    """A telemetry sink must never be the thing that fails a generation."""
    observer = ai.JsonlObserver(tmp_path / "t.jsonl")
    observer.close()
    observer.on_event(_started())  # must not raise
    observer.close()  # idempotent


# ---- LoggingObserver -----------------------------------------------------------------


def test_logging_observer_emits_the_event_name_and_attaches_the_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observer = ai.LoggingObserver()
    with caplog.at_level(logging.INFO, logger="anyinfer.telemetry"):
        observer.on_event(_started())

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "RequestStarted"
    assert record.anyinfer_event["request_id"] == "r1"  # type: ignore[attr-defined]


def test_logging_observer_respects_a_disabled_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observer = ai.LoggingObserver(level=logging.DEBUG)
    with caplog.at_level(logging.WARNING, logger="anyinfer.telemetry"):
        observer.on_event(_started())
    assert caplog.records == []


def test_logging_observer_accepts_a_caller_supplied_logger(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observer = ai.LoggingObserver(logging.getLogger("my.app.telemetry"))
    with caplog.at_level(logging.INFO, logger="my.app.telemetry"):
        observer.on_event(_started())
    assert [r.name for r in caplog.records] == ["my.app.telemetry"]


def test_logging_observer_accepts_a_level_name(caplog: pytest.LogCaptureFixture) -> None:
    """A config file can only carry scalars, so ``"DEBUG"`` has to mean `logging.DEBUG`."""
    observer = ai.LoggingObserver(level="debug")
    with caplog.at_level(logging.DEBUG, logger="anyinfer.telemetry"):
        observer.on_event(_started())
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]


def test_logging_observer_accepts_a_logger_name(caplog: pytest.LogCaptureFixture) -> None:
    observer = ai.LoggingObserver("my.app.telemetry")
    with caplog.at_level(logging.INFO, logger="my.app.telemetry"):
        observer.on_event(_started())
    assert [r.name for r in caplog.records] == ["my.app.telemetry"]


def test_an_unknown_level_name_is_rejected_at_construction() -> None:
    """The alternative is `isEnabledFor` raising on every event and logging nothing."""
    with pytest.raises(ValueError, match="unknown logging level"):
        ai.LoggingObserver(level="LOUD")


# ---- end to end ----------------------------------------------------------------------


async def test_a_sink_subscribed_to_a_real_client_sees_no_prompt_text(
    tmp_path: Path,
) -> None:
    """The payload-free default is enforced by the dispatcher, not by the sink."""
    path = tmp_path / "telemetry.jsonl"
    server = FakeOpenAIServer(FakeResponse(text="the answer"))
    with ai.JsonlObserver(path) as observer:
        client = ai.AsyncClient(
            [
                ai.ProviderSettings.of(
                    "openai-compat",
                    base_url="https://fake.invalid/v1",
                    transport=server.transport(),
                )
            ],
            observers=[observer],
        )
        async with client:
            await client.generate("a private prompt", target="openai-compat:m")

    written = path.read_text(encoding="utf-8")
    assert "a private prompt" not in written
    assert "the answer" not in written
    names = [json.loads(line)["event"] for line in written.strip().splitlines()]
    assert "RequestStarted" in names and "RequestCompleted" in names
