"""History compaction: shrinking a transcript without invalidating it."""

from __future__ import annotations

import pytest

from anyinfer import Message, Text, ToolCall, ToolResult, assistant, system, user
from anyinfer.context import compact_history
from anyinfer.events.observers import Observer

BIG = "x" * 4_000


def _transcript(turns: int = 12) -> list[Message]:
    messages: list[Message] = [system("You are helpful.")]
    for index in range(turns):
        messages.append(user(f"Question {index}. {BIG}"))
        messages.append(assistant(f"Answer {index}. {BIG}"))
    return messages


def _tool_exchange() -> list[Message]:
    return [
        system("You are helpful."),
        user("Read the file."),
        Message(role="assistant", content=(ToolCall("call_0", "read_file", {"path": "a.py"}),)),
        Message(role="tool", content=(ToolResult("call_0", BIG),)),
        assistant("Here is what it said."),
        user("And the next one?"),
        Message(role="assistant", content=(ToolCall("call_1", "read_file", {"path": "b.py"}),)),
        Message(role="tool", content=(ToolResult("call_1", BIG),)),
        assistant("Done."),
    ]


def test_a_conversation_that_fits_is_returned_untouched():
    messages = [system("Be brief."), user("Hello.")]
    result = compact_history(messages, max_tokens=10_000)
    assert result.messages == tuple(messages)
    assert result.complete
    assert not result.changed
    assert result.fits


def test_an_oversized_conversation_is_brought_under_budget():
    # The budget has to clear the protected floor — the system prompt plus the recent
    # window — because compaction will not touch those to make room.
    messages = _transcript()
    result = compact_history(messages, max_tokens=6_000, keep_recent=2)
    assert result.fits
    assert result.estimated_tokens <= 6_000
    assert result.changed
    assert result.saved_tokens > 0


def test_the_protected_floor_is_what_a_budget_has_to_clear():
    messages = _transcript()
    tight = compact_history(messages, max_tokens=6_000, keep_recent=8)
    roomy = compact_history(messages, max_tokens=6_000, keep_recent=2)
    assert not tight.fits, "eight full turns do not fit, and nothing else can be given up"
    assert roomy.fits


def test_system_messages_survive():
    messages = _transcript()
    result = compact_history(messages, max_tokens=2_000)
    kept = [message for message in result.messages if message.role == "system"]
    assert len(kept) == 1
    assert kept[0].text == "You are helpful."


def test_system_messages_can_be_given_up_explicitly():
    messages = [system(BIG), *[user(f"{index}. {BIG}") for index in range(6)]]
    protected = compact_history(messages, max_tokens=1_500, keep_system=True)
    unprotected = compact_history(messages, max_tokens=1_500, keep_system=False)
    assert protected.estimated_tokens >= unprotected.estimated_tokens


def test_the_recent_window_survives_intact():
    messages = _transcript()
    result = compact_history(messages, max_tokens=3_000, keep_recent=4)
    assert result.messages[-4:] == tuple(messages[-4:])


def test_tool_call_and_result_pairing_is_never_broken():
    messages = _tool_exchange()
    result = compact_history(messages, max_tokens=200, keep_recent=1)

    calls = {
        part.id
        for message in result.messages
        for part in message.content
        if isinstance(part, ToolCall)
    }
    results = {
        part.call_id
        for message in result.messages
        for part in message.content
        if isinstance(part, ToolResult)
    }
    assert calls == results, "a call without its result is rejected by providers"
    assert calls == {"call_0", "call_1"}


def test_tool_results_are_emptied_before_anything_else_is_touched():
    messages = _tool_exchange()
    result = compact_history(messages, max_tokens=1_000, keep_recent=1)
    assert result.elided_results >= 1
    assert result.dropped_count == 0, "eliding a payload is cheaper than losing a turn"


def test_an_elided_payload_says_how_much_went():
    messages = _tool_exchange()
    result = compact_history(messages, max_tokens=1_000, keep_recent=1)
    payloads = [
        part.content
        for message in result.messages
        for part in message.content
        if isinstance(part, ToolResult)
    ]
    assert any(payload.startswith("[elided ") for payload in payloads)
    assert any(str(len(BIG)) in payload for payload in payloads)


def test_short_payloads_are_left_alone():
    messages = [
        system("Be brief."),
        Message(role="tool", content=(ToolResult("call_0", "ok"),)),
        *[user(f"{index}. {BIG}") for index in range(4)],
    ]
    result = compact_history(messages, max_tokens=1_500, keep_recent=2)
    survivors = [
        part.content
        for message in result.messages
        for part in message.content
        if isinstance(part, ToolResult)
    ]
    assert survivors == ["ok"], "the marker would cost more than the payload"


def test_a_conversation_that_cannot_fit_says_so_rather_than_mutilating_itself():
    messages = [system(BIG), user(BIG)]
    result = compact_history(messages, max_tokens=10, keep_recent=1)
    assert not result.fits
    assert not result.complete
    assert result.messages, "the protected messages are still returned"
    assert "still over budget" in result.summary()


def test_the_summary_and_metadata_are_content_free():
    messages = _transcript()
    result = compact_history(messages, max_tokens=3_000)
    assert BIG not in result.summary()
    assert "Question" not in result.summary()
    record = result.metadata()
    assert BIG not in repr(record)
    assert record["original_count"] == len(messages)
    assert record["kept_count"] == len(result.messages)


def test_an_observer_receives_a_content_free_event():
    seen = []

    class Recorder(Observer):
        def on_event(self, event):
            seen.append(event)

    messages = _transcript()
    result = compact_history(messages, max_tokens=3_000, observer=Recorder())
    assert len(seen) == 1
    event = seen[0]
    assert event.strategy == "history"
    assert event.representation == "compacted"
    assert event.candidate_count == len(messages)
    assert event.selected_count == len(result.messages)
    assert BIG not in repr(event)


@pytest.mark.parametrize(("budget", "recent"), [(0, 4), (-1, 4)])
def test_a_nonsense_budget_is_rejected(budget, recent):
    with pytest.raises(ValueError, match="max_tokens"):
        compact_history(_transcript(), max_tokens=budget, keep_recent=recent)


def test_a_negative_recent_window_is_rejected():
    with pytest.raises(ValueError, match="keep_recent"):
        compact_history(_transcript(), max_tokens=1_000, keep_recent=-1)


def test_compaction_is_deterministic():
    messages = _transcript()
    first = compact_history(messages, max_tokens=3_000)
    second = compact_history(messages, max_tokens=3_000)
    assert first.messages == second.messages
    assert first.metadata() == second.metadata()


def test_the_input_is_not_mutated():
    messages = _tool_exchange()
    before = [message.content for message in messages]
    compact_history(messages, max_tokens=200, keep_recent=1)
    assert [message.content for message in messages] == before


def test_text_parts_are_elided_before_messages_are_dropped():
    messages = _transcript(turns=8)
    result = compact_history(messages, max_tokens=5_000, keep_recent=2)
    assert result.fits
    assert result.elided_texts > 0
    assert result.dropped_count == 0, "eliding is tried to exhaustion before dropping"
    assert any(
        isinstance(part, Text) and part.text.startswith("[elided ")
        for message in result.messages
        for part in message.content
    )
