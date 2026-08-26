"""The sync facade (§C5, risk R1).

The facade is the riskiest part of the design: one background loop thread, streaming
iterators crossing a thread boundary, and cancellation semantics that must not hang. These
tests exercise all three, including under thread stress.
"""

from __future__ import annotations

import threading

import pytest

import anyinfer as ai
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_sync_client


def test_generate_returns_a_result() -> None:
    server = FakeOpenAIServer(FakeResponse(text="sync answer"))
    with make_sync_client(server) as client:
        result = client.generate("hi", target="openai-compat:m")

    assert result.text == "sync answer"


def test_generate_runs_an_arena_through_the_sync_facade() -> None:
    server = FakeOpenAIServer(FakeResponse(text="candidate"))
    with make_sync_client(server) as client:
        result = client.generate(
            "compare",
            arena=ai.ArenaPolicy(("openai-compat:a", "openai-compat:b")),
        )

    assert result.text == "candidate"
    assert result.arena is not None
    assert [item.target.model for item in result.arena.candidates] == ["a", "b"]
    assert len(server.requests) == 2


def test_stream_iterates_and_exposes_the_result() -> None:
    server = FakeOpenAIServer(FakeResponse(text="streamed answer"))
    with (
        make_sync_client(server) as client,
        client.stream("hi", target="openai-compat:m") as stream,
    ):
        text = "".join(e.text for e in stream if isinstance(e, ai.TextDelta))
        result = stream.result

    assert text == "streamed answer"
    assert result.text == "streamed answer"


def test_stream_collect_drains() -> None:
    server = FakeOpenAIServer(FakeResponse(text="drained"))
    with (
        make_sync_client(server) as client,
        client.stream("hi", target="openai-compat:m") as stream,
    ):
        result = stream.collect()

    assert result.text == "drained"


def test_result_before_consumption_is_an_error() -> None:
    server = FakeOpenAIServer(FakeResponse(text="x"))
    with (
        make_sync_client(server) as client,
        client.stream("hi", target="openai-compat:m") as stream,
    ):
        with pytest.raises(RuntimeError, match="not available until"):
            _ = stream.result


def test_early_close_does_not_hang() -> None:
    """Leaving the block after one event must cancel cleanly, not deadlock."""
    server = FakeOpenAIServer(FakeResponse(text="a long answer " * 50))
    with make_sync_client(server) as client:
        with client.stream("hi", target="openai-compat:m") as stream:
            for _ in stream:
                break
        result = client.generate("still works", target="openai-compat:m")

    assert result.text is not None


def test_errors_propagate_into_the_calling_thread() -> None:
    server = FakeOpenAIServer(FakeResponse(status=401, error_message="bad key"))
    with make_sync_client(server) as client:
        with pytest.raises(ai.AllTargetsFailedError):
            client.generate("hi", target="openai-compat:m")


def test_stream_errors_propagate_into_the_calling_thread() -> None:
    server = FakeOpenAIServer(FakeResponse(status=401, error_message="bad key"))
    with make_sync_client(server) as client:
        with pytest.raises(ai.AllTargetsFailedError):
            with client.stream("hi", target="openai-compat:m") as stream:
                for _ in stream:
                    pass


def test_client_is_reusable_across_calls() -> None:
    server = FakeOpenAIServer(FakeResponse(text="reused"))
    with make_sync_client(server) as client:
        for _ in range(5):
            assert client.generate("hi", target="openai-compat:m").text == "reused"

    assert server.call_count == 5


def test_close_is_idempotent() -> None:
    server = FakeOpenAIServer()
    client = make_sync_client(server)
    client.close()
    client.close()


def test_concurrent_requests_from_many_threads() -> None:
    """Thread stress: the facade must serialize onto one loop without corrupting results."""
    thread_count = 8
    per_thread = 50
    server = FakeOpenAIServer(FakeResponse(text="concurrent"))
    errors: list[BaseException] = []
    lock = threading.Lock()

    with make_sync_client(server) as client:

        def worker() -> None:
            try:
                for _ in range(per_thread):
                    result = client.generate("hi", target="openai-compat:m")
                    assert result.text == "concurrent"
            except BaseException as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            assert not thread.is_alive(), "a worker thread hung"

    assert not errors, f"worker failures: {errors[:3]}"
    assert server.call_count == thread_count * per_thread


def test_concurrent_streams_from_many_threads() -> None:
    """Concurrent independent streams are load-bearing for the serve frontend (ADR-009)."""
    thread_count = 8
    server = FakeOpenAIServer(FakeResponse(text="parallel stream"))
    results: list[str] = []
    lock = threading.Lock()

    with make_sync_client(server) as client:

        def worker() -> None:
            with client.stream("hi", target="openai-compat:m") as stream:
                text = "".join(e.text for e in stream if isinstance(e, ai.TextDelta))
            with lock:
                results.append(text)

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            assert not thread.is_alive()

    assert results == ["parallel stream"] * thread_count


def test_structured_output_through_the_facade() -> None:
    import json

    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"ok": True})))
    with make_sync_client(server) as client:
        result = client.generate("hi", target="openai-compat:m", schema=schema)

    assert result.structured == {"ok": True}


def test_models_and_health_through_the_facade() -> None:
    server = FakeOpenAIServer(models=("a", "b"))
    with make_sync_client(server) as client:
        assert [m.id for m in client.models("openai-compat")] == ["a", "b"]
        assert client.health("openai-compat").ok is True


def test_retain_raw_round_trips_through_the_facade() -> None:
    server = FakeOpenAIServer(FakeResponse(text="raw answer"))
    with make_sync_client(server, retain_raw=True) as client:
        kept = client.generate("hi", target="openai-compat:m")
    with make_sync_client(server) as client:
        dropped = client.generate("hi", target="openai-compat:m")

    assert isinstance(kept.raw, dict)
    assert kept.raw["id"] == "chatcmpl-fake"
    assert dropped.raw is None


def test_resolve_does_not_need_the_loop() -> None:
    server = FakeOpenAIServer()
    with make_sync_client(server) as client:
        resolved = client.resolve("openai-compat:some-model")

    assert resolved.provider_id == "openai-compat"
    assert resolved.model == "some-model"


def test_every_forwarded_method_keeps_the_async_signature() -> None:
    """The facade is logic-free, so its only real failure mode is silent drift.

    `Client` restates every async signature by hand, with no codegen and — until this
    test — nothing checking them. A keyword added to `AsyncClient.generate` simply never
    appeared on `Client.generate`, and the sync caller's first hint was a `TypeError` at
    runtime rather than a red test here.

    Only the keyword-only parameters are compared. Positional spelling is not part of the
    contract (the facade is free to name its first argument differently), but a missing or
    renamed keyword is exactly the drift this guards.
    """
    import inspect

    mismatches: list[str] = []
    for name in dir(ai.Client):
        if name.startswith("_"):
            continue
        sync_attr = getattr(ai.Client, name, None)
        async_attr = getattr(ai.AsyncClient, name, None)
        if not callable(sync_attr) or not callable(async_attr):
            continue
        try:
            sync_sig = inspect.signature(sync_attr)
            async_sig = inspect.signature(async_attr)
        except (TypeError, ValueError):  # pragma: no cover — C-level callables
            continue

        def keywords(signature: inspect.Signature) -> dict[str, object]:
            return {
                key: parameter.default
                for key, parameter in signature.parameters.items()
                if parameter.kind is inspect.Parameter.KEYWORD_ONLY
            }

        sync_keywords = keywords(sync_sig)
        async_keywords = keywords(async_sig)
        missing = set(async_keywords) - set(sync_keywords)
        extra = set(sync_keywords) - set(async_keywords)
        if missing:
            mismatches.append(f"Client.{name} is missing {sorted(missing)}")
        if extra:
            mismatches.append(f"Client.{name} has extra {sorted(extra)}")
        differing = {
            key
            for key in set(sync_keywords) & set(async_keywords)
            if sync_keywords[key] != async_keywords[key]
        }
        if differing:
            mismatches.append(f"Client.{name} defaults differ for {sorted(differing)}")

    assert not mismatches, "sync facade drifted from the async client:\n" + "\n".join(mismatches)
