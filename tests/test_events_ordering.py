"""The binding event-ordering guarantees (DESIGN.md §6).

These are a public contract, not an implementation detail: consumers rely on them to
measure TTFT, render deltas, and reconstruct OpenAI chunk sequences (ADR-009 invariant 2).
"""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_client

CONTENT_EVENTS = (ai.TextDelta, ai.ReasoningDelta, ai.ToolCallDelta)


async def _events(client: ai.AsyncClient, **kwargs: object) -> list[ai.StreamEvent]:
    stream = client.stream("hi", **kwargs)  # type: ignore[arg-type]
    return [event async for event in stream]


async def test_stream_ended_is_last_and_unique() -> None:
    server = FakeOpenAIServer(FakeResponse(text="some text"))
    async with make_client(server) as client:
        events = await _events(client, target="openai-compat:m")

    ends = [e for e in events if isinstance(e, ai.StreamEnded)]
    assert len(ends) == 1
    assert isinstance(events[-1], ai.StreamEnded)


async def test_attempt_start_precedes_first_token_which_precedes_content() -> None:
    server = FakeOpenAIServer(FakeResponse(text="abcdefgh"))
    async with make_client(server) as client:
        events = await _events(client, target="openai-compat:m")

    names = [e.name for e in events if isinstance(e, ai.TimingMark)]
    assert names == ["attempt_start", "first_token"]

    first_token_index = next(
        i for i, e in enumerate(events)
        if isinstance(e, ai.TimingMark) and e.name == "first_token"
    )
    first_content_index = next(
        i for i, e in enumerate(events) if isinstance(e, CONTENT_EVENTS)
    )
    assert first_token_index < first_content_index, "first_token marks the first content"

    attempt_start_index = next(
        i for i, e in enumerate(events)
        if isinstance(e, ai.TimingMark) and e.name == "attempt_start"
    )
    assert attempt_start_index < first_token_index


async def test_concatenated_text_deltas_equal_the_result_text() -> None:
    server = FakeOpenAIServer(FakeResponse(text="The quick brown fox jumps."))
    async with make_client(server) as client:
        events = await _events(client, target="openai-compat:m")

    joined = "".join(e.text for e in events if isinstance(e, ai.TextDelta))
    ended = events[-1]
    assert isinstance(ended, ai.StreamEnded)
    assert joined == ended.result.text


async def test_attempt_failed_events_precede_content_on_retry() -> None:
    server = FakeOpenAIServer(
        [
            FakeResponse(status=503, error_message="down"),
            FakeResponse(text="recovered"),
        ]
    )
    async with make_client(server) as client:
        events = await _events(
            client,
            route=ai.Route(
                targets=("openai-compat:m",),
                retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
            ),
        )

    failed_index = next(i for i, e in enumerate(events) if isinstance(e, ai.AttemptFailed))
    content_index = next(i for i, e in enumerate(events) if isinstance(e, CONTENT_EVENTS))
    assert failed_index < content_index


async def test_no_first_token_mark_when_there_is_no_content() -> None:
    server = FakeOpenAIServer(FakeResponse(text="", usage=None))
    async with make_client(server) as client:
        events = await _events(client, target="openai-compat:m")

    names = [e.name for e in events if isinstance(e, ai.TimingMark)]
    assert names == ["attempt_start"]
    ended = events[-1]
    assert isinstance(ended, ai.StreamEnded)
    assert ended.result.timing.first_token_ms is None


async def test_unrecoverable_failure_raises_instead_of_ending_the_stream() -> None:
    server = FakeOpenAIServer(FakeResponse(status=401, error_message="nope"))
    async with make_client(server) as client:
        stream = client.stream("hi", target="openai-compat:m")
        collected: list[ai.StreamEvent] = []
        with pytest.raises(ai.AllTargetsFailedError):
            async for event in stream:
                collected.append(event)

    assert not any(isinstance(e, ai.StreamEnded) for e in collected)


async def test_usage_may_arrive_late_and_still_reach_the_result() -> None:
    """Usage often arrives in a trailing chunk after the finish reason.

    Closing the stream on ``finish_reason`` instead of the terminal sentinel is a known way
    to lose it, and it silently undercounts tokens — so the parser drains to ``[DONE]``.
    """
    server = FakeOpenAIServer(FakeResponse(text="hello", usage={"prompt_tokens": 3,
                                                                "completion_tokens": 2,
                                                                "total_tokens": 5}))
    async with make_client(server) as client:
        events = await _events(client, target="openai-compat:m")

    ended = events[-1]
    assert isinstance(ended, ai.StreamEnded)
    assert ended.result.usage.output_tokens == 2
    assert any(isinstance(e, ai.UsageUpdate) for e in events)


async def test_unknown_finish_reason_degrades_to_other() -> None:
    """``finish_reason`` is an open enum; an unknown value must not crash reassembly."""
    server = FakeOpenAIServer(FakeResponse(text="hi", finish_reason="something_new"))
    async with make_client(server) as client:
        result = await client.generate("hi", target="openai-compat:m")

    assert result.finish_reason == "other"


async def test_repair_restarts_the_attempt_clock_and_the_delta_sequence() -> None:
    """Guarantees 2 and 4 are scoped per attempt (anyinfer.types.events docstring).

    A mid-stream schema repair re-runs the target inside the same stream: a fresh
    ``TimingMark("attempt_start")`` opens the re-run, and only the deltas after it
    reconstruct ``result.text``. A consumer rendering deltas treats each ``attempt_start``
    as "clear and start over".
    """
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    server = FakeOpenAIServer(
        [
            FakeResponse(text="not json at all"),
            FakeResponse(text='{"n": 7}'),
        ]
    )
    async with make_client(server) as client:
        stream = client.stream(
            "hi",
            target="openai-compat:m",
            schema=schema,
            repair=ai.Repair(max_attempts=1),
        )
        events = [event async for event in stream]
        result = stream.result

    starts = [
        i for i, e in enumerate(events)
        if isinstance(e, ai.TimingMark) and e.name == "attempt_start"
    ]
    assert len(starts) == 2, "the repair re-run must open with a fresh attempt_start"

    replayed = "".join(
        e.text for e in events[starts[1]:] if isinstance(e, ai.TextDelta)
    )
    assert replayed == result.text, "deltas after the last attempt_start rebuild the text"
    assert result.repair_attempts == 1
    assert result.structured == {"n": 7}
