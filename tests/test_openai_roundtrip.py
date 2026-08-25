"""Serve-invariant round-trip tests (T0.13, ADR-009).

These run from M0 even though the server ships in M5, because the four invariants they
enforce are *core* obligations. If a core type change breaks one of these, the serve
frontend would stop being a thin projection, which is the failure this suite exists to
catch early.
"""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer.serve.openai_codec import (
    chunk_from_event,
    completion_from_generation,
    final_chunk,
    request_from_openai,
    request_to_openai,
)
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_client

FULL_REQUEST = {
    "model": "anthropic:claude-sonnet-4-5",
    "messages": [
        {"role": "system", "content": "Be precise."},
        {"role": "user", "content": "What is 2+2?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "calc", "arguments": '{"expr": "2+2"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "4"},
    ],
    "temperature": 0.2,
    "top_p": 0.9,
    "max_tokens": 512,
    "stop": ["\n\n", "END"],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "calc",
                "description": "Evaluate arithmetic.",
                "parameters": {
                    "type": "object",
                    "properties": {"expr": {"type": "string"}},
                    "required": ["expr"],
                },
            },
        }
    ],
    "tool_choice": "auto",
    "reasoning_effort": "high",
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "Answer",
            "schema": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        },
    },
    "metadata": {"run": "42"},
}


# ---- invariant 1: request superset ---------------------------------------------------


def test_full_request_round_trips_losslessly() -> None:
    """Anything the OpenAI chat-completions surface expresses must survive the trip."""
    target, request, stream = request_from_openai(FULL_REQUEST)
    rebuilt = request_to_openai(target, request, stream=stream)

    assert rebuilt["model"] == FULL_REQUEST["model"]
    assert rebuilt["temperature"] == FULL_REQUEST["temperature"]
    assert rebuilt["top_p"] == FULL_REQUEST["top_p"]
    assert rebuilt["max_tokens"] == FULL_REQUEST["max_tokens"]
    assert rebuilt["stop"] == FULL_REQUEST["stop"]
    assert rebuilt["tool_choice"] == FULL_REQUEST["tool_choice"]
    assert rebuilt["reasoning_effort"] == FULL_REQUEST["reasoning_effort"]
    assert rebuilt["metadata"] == FULL_REQUEST["metadata"]
    assert rebuilt["tools"] == FULL_REQUEST["tools"]
    assert rebuilt["response_format"] == FULL_REQUEST["response_format"]


def test_reasoning_effort_decodes_to_the_typed_field_not_passthrough() -> None:
    """The one first-class generation parameter the codec used to lose.

    Unreserved, it fell into verbatim provider_options, so the core's cross-provider
    reasoning translation never engaged: an Anthropic or Gemini backend saw an OpenAI
    field name it does not speak, and a sidecar caller got no reasoning at all.
    """
    _, request, _ = request_from_openai(FULL_REQUEST)

    assert request.reasoning == "high"
    assert "reasoning_effort" not in request.provider_options.get("*", {})


def test_absent_reasoning_effort_stays_absent() -> None:
    body = {k: v for k, v in FULL_REQUEST.items() if k != "reasoning_effort"}
    target, request, _ = request_from_openai(body)

    assert request.reasoning is None
    assert "reasoning_effort" not in request_to_openai(target, request)


def test_an_unrecognized_reasoning_effort_is_refused() -> None:
    """Dropped silently, it would change what the model was asked to do in secret."""
    with pytest.raises(ValueError, match="reasoning_effort"):
        request_from_openai({**FULL_REQUEST, "reasoning_effort": "extreme"})


def test_messages_round_trip_including_tool_turns() -> None:
    target, request, _ = request_from_openai(FULL_REQUEST)
    rebuilt = request_to_openai(target, request)

    original = FULL_REQUEST["messages"]
    assert rebuilt["messages"] == original, "message array must survive verbatim"


def test_stream_flag_round_trips() -> None:
    _, _, stream = request_from_openai({**FULL_REQUEST, "stream": True})
    assert stream is True

    target, request, stream = request_from_openai(FULL_REQUEST)
    assert stream is False
    assert "stream" not in request_to_openai(target, request, stream=False)


def test_content_parts_are_flattened_to_text() -> None:
    _, request, _ = request_from_openai(
        {
            "model": "m",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hello "},
                        {"type": "text", "text": "world"},
                    ],
                }
            ],
        }
    )
    assert request.messages[0].text == "Hello world"


def test_max_completion_tokens_is_accepted() -> None:
    _, request, _ = request_from_openai(
        {"model": "m", "messages": [], "max_completion_tokens": 256}
    )
    assert request.sampling.max_output_tokens == 256


def test_named_tool_choice_round_trips() -> None:
    body = {
        **FULL_REQUEST,
        "tool_choice": {"type": "function", "function": {"name": "calc"}},
    }
    target, request, _ = request_from_openai(body)
    assert request.tool_choice == "calc"
    assert request_to_openai(target, request)["tool_choice"] == body["tool_choice"]


def test_unrecognized_fields_reach_provider_options() -> None:
    """OpenAI clients use extra-body passthrough; the codec must not swallow it."""
    _, request, _ = request_from_openai(
        {
            "model": "ollama:qwen3:8b",
            "messages": [],
            "provider_options": {"ollama": {"keep_alive": "10m"}},
        }
    )
    assert request.provider_options["ollama"] == {"keep_alive": "10m"}


def test_unknown_top_level_fields_are_preserved() -> None:
    _, request, _ = request_from_openai({"model": "m", "messages": [], "some_new_field": 7})
    assert request.provider_options["*"] == {"some_new_field": 7}


# ---- invariant 3: target representable in a model string -----------------------------


@pytest.mark.parametrize(
    "target",
    [
        "medium",
        "anthropic:claude-sonnet-4-5",
        "ollama:qwen3:8b",
        "llama-cpp:qwen2.5-7b-instruct-q4-k-m",
        "openai-compat:some/nested/model-name",
        "copilot:auto",
    ],
)
def test_every_target_spelling_survives_a_model_field(target: str) -> None:
    """A Target must carry no structure an OpenAI ``model`` string cannot hold."""
    decoded, request, _ = request_from_openai({"model": target, "messages": []})
    assert decoded == target
    assert request_to_openai(decoded, request)["model"] == target
    assert json.loads(json.dumps({"model": target}))["model"] == target


# ---- invariant 2: chunk reconstruction ----------------------------------------------


async def test_event_stream_reconstructs_a_chunk_sequence() -> None:
    """The event stream must be sufficient to rebuild a chat.completion.chunk sequence."""
    server = FakeOpenAIServer(FakeResponse(text="Hello, world!"))
    async with make_client(server) as client:
        stream = client.stream("hi", target="openai-compat:m")
        chunks: list[dict[str, object]] = []
        async for event in stream:
            chunk = chunk_from_event(event, model="openai-compat:m", created=0)
            if chunk is not None:
                chunks.append(chunk)
        result = stream.result
        chunks.extend(final_chunk(result, model="openai-compat:m", created=0))

    text = "".join(
        str(c["choices"][0]["delta"].get("content", ""))  # type: ignore[index,union-attr]
        for c in chunks
        if c["choices"] and "content" in c["choices"][0]["delta"]  # type: ignore[index,operator]
    )
    assert text == "Hello, world!", "chunks must reconstruct the full text"

    finish_chunks = [
        c
        for c in chunks
        if c["choices"] and c["choices"][0].get("finish_reason")  # type: ignore[index,union-attr]
    ]
    assert len(finish_chunks) == 1, "exactly one chunk carries the finish reason"

    usage_chunks = [c for c in chunks if "usage" in c]
    assert len(usage_chunks) == 1, "usage rides in its own trailing chunk"
    assert usage_chunks[-1] is chunks[-1], "the usage chunk is last"


async def test_tool_call_chunks_carry_index_and_fragments() -> None:
    server = FakeOpenAIServer(
        FakeResponse(
            text="",
            tool_calls=(("call_9", "calc", '{"expr": "2+2"}'),),
            finish_reason="tool_calls",
        )
    )
    async with make_client(server) as client:
        stream = client.stream("go", target="openai-compat:m")
        chunks = []
        async for event in stream:
            chunk = chunk_from_event(event, model="m", created=0)
            if chunk is not None:
                chunks.append(chunk)
        result = stream.result

    tool_chunks = [
        c
        for c in chunks
        if c["choices"] and "tool_calls" in c["choices"][0]["delta"]  # type: ignore[index,operator]
    ]
    assert tool_chunks, "tool calls must produce chunks"

    arguments = "".join(
        str(c["choices"][0]["delta"]["tool_calls"][0]["function"].get("arguments", ""))  # type: ignore[index]
        for c in tool_chunks
    )
    assert json.loads(arguments) == {"expr": "2+2"}
    assert all(
        "index" in c["choices"][0]["delta"]["tool_calls"][0]  # type: ignore[index,operator]
        for c in tool_chunks
    ), "every tool-call chunk must carry its slot index"
    assert result.tool_calls[0].name == "calc"


async def test_non_streaming_completion_shape() -> None:
    server = FakeOpenAIServer(FakeResponse(text="The answer."))
    async with make_client(server) as client:
        result = await client.generate("hi", target="openai-compat:m")

    body = completion_from_generation(result, model="openai-compat:m", created=0)
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "The answer."  # type: ignore[index]
    assert body["choices"][0]["finish_reason"] == "stop"  # type: ignore[index]
    assert body["usage"]["completion_tokens"] == 7  # type: ignore[index]


def test_anyinfer_only_events_have_no_openai_equivalent() -> None:
    """Timing marks and attempt records are ours; the OpenAI wire cannot carry them."""
    assert chunk_from_event(ai.TimingMark("first_token", 12.0), model="m") is None
    assert (
        chunk_from_event(
            ai.AttemptFailed(ai.AttemptRecord(ai.ResolvedTarget("p", "m"), "failed")),
            model="m",
        )
        is None
    )


def test_other_finish_reason_maps_into_openais_closed_set() -> None:
    """OpenAI has no 'other'; it must render as something a client can handle."""
    from anyinfer.serve.openai_codec import OPENAI_FINISH_REASONS

    assert set(OPENAI_FINISH_REASONS.values()) <= {
        "stop",
        "length",
        "tool_calls",
        "content_filter",
    }


# ---- invariant 4: concurrent streams -------------------------------------------------


async def test_many_concurrent_independent_streams() -> None:
    """The server makes concurrency load-bearing; the client must already support it."""
    import asyncio

    server = FakeOpenAIServer(FakeResponse(text="concurrent answer"))
    async with make_client(server) as client:

        async def one() -> str:
            stream = client.stream("hi", target="openai-compat:m")
            parts = [e.text async for e in stream if isinstance(e, ai.TextDelta)]
            return "".join(parts)

        results = await asyncio.gather(*(one() for _ in range(16)))

    assert results == ["concurrent answer"] * 16
