"""End-to-end tests for the openai-compat adapter against the fake server."""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_client


async def test_streaming_generation_reconstructs_text() -> None:
    server = FakeOpenAIServer(FakeResponse(text="Hello, world!"))
    async with make_client(server) as client:
        stream = client.stream("hi", target="openai-compat:fake-model-small")
        deltas: list[str] = []
        async for event in stream:
            if isinstance(event, ai.TextDelta):
                deltas.append(event.text)
        result = stream.result

    assert "".join(deltas) == "Hello, world!"
    assert result.text == "Hello, world!"
    assert result.finish_reason == "stop"


async def test_non_streaming_generation() -> None:
    server = FakeOpenAIServer(FakeResponse(text="Buffered answer."))
    async with make_client(server) as client:
        result = await client.generate("hi", target="openai-compat:fake-model-small")

    assert result.text == "Buffered answer."
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7
    assert result.usage.total_tokens == 18
    assert server.requests[0].get("stream") is not True


async def test_timing_marks_and_ttft() -> None:
    server = FakeOpenAIServer(FakeResponse(text="abcdefgh"))
    async with make_client(server) as client:
        stream = client.stream("hi", target="openai-compat:fake-model-small")
        marks: list[ai.TimingMark] = []
        async for event in stream:
            if isinstance(event, ai.TimingMark):
                marks.append(event)
        result = stream.result

    assert [m.name for m in marks] == ["attempt_start", "first_token"]
    assert result.timing.first_token_ms is not None
    assert result.timing.total_ms >= result.timing.first_token_ms


async def test_tool_calls_are_assembled_from_indexed_fragments() -> None:
    server = FakeOpenAIServer(
        FakeResponse(
            text="",
            tool_calls=(("call_abc", "read_file", '{"path": "README.md"}'),),
            finish_reason="tool_calls",
        )
    )
    async with make_client(server) as client:
        result = await client.generate(
            "read it",
            target="openai-compat:fake-model-small",
            tools=[
                ai.ToolSpec(
                    name="read_file",
                    description="Read a file",
                    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                )
            ],
        )

    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "call_abc"
    assert call.name == "read_file"
    assert call.arguments == {"path": "README.md"}


async def test_streaming_tool_calls_merge_by_index() -> None:
    server = FakeOpenAIServer(
        FakeResponse(
            text="",
            tool_calls=(("call_1", "search", '{"query": "anyinfer"}'),),
            finish_reason="tool_calls",
        )
    )
    async with make_client(server) as client:
        stream = client.stream("go", target="openai-compat:fake-model-small")
        fragments = 0
        async for event in stream:
            if isinstance(event, ai.ToolCallDelta):
                fragments += 1
        result = stream.result

    assert fragments > 1, "arguments should stream as multiple fragments"
    assert result.tool_calls[0].arguments == {"query": "anyinfer"}


async def test_malformed_tool_arguments_warn_rather_than_fail() -> None:
    server = FakeOpenAIServer(
        FakeResponse(
            text="",
            tool_calls=(("call_1", "broken", "{not json"),),
            finish_reason="tool_calls",
        )
    )
    async with make_client(server) as client:
        result = await client.generate("go", target="openai-compat:fake-model-small")

    assert result.tool_calls[0].arguments == {}
    assert any("unparseable arguments" in w for w in result.warnings)


async def test_list_models() -> None:
    server = FakeOpenAIServer(models=("m1", "m2"))
    async with make_client(server) as client:
        models = await client.models("openai-compat")

    assert [m.id for m in models] == ["m1", "m2"]


async def test_health_probe() -> None:
    server = FakeOpenAIServer()
    async with make_client(server) as client:
        health = await client.health("openai-compat")

    assert health.ok is True


async def test_error_status_maps_to_typed_error() -> None:
    server = FakeOpenAIServer(FakeResponse(status=401, error_message="bad key"))
    async with make_client(server) as client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("hi", target="openai-compat:fake-model-small")

    attempts = excinfo.value.attempts
    assert attempts[-1].error is not None
    assert attempts[-1].error.type_name == "AuthError"
    assert attempts[-1].error.retryable is False


async def test_server_that_ignores_stream_still_produces_a_result() -> None:
    server = FakeOpenAIServer(FakeResponse(text="buffered anyway", ignore_stream=True))
    async with make_client(server) as client:
        stream = client.stream("hi", target="openai-compat:fake-model-small")
        result = await stream.collect()

    assert result.text == "buffered anyway"


async def test_response_byte_cap_is_enforced() -> None:
    server = FakeOpenAIServer(FakeResponse(text="x" * 5000))
    async with make_client(server) as client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate(
                "hi", target="openai-compat:fake-model-small", max_response_bytes=200
            )

    assert excinfo.value.attempts[-1].error is not None
    assert excinfo.value.attempts[-1].error.type_name == "StreamProtocolError"


async def test_malformed_sse_is_a_typed_stream_protocol_error() -> None:
    """A server emitting unparseable SSE must surface a typed, attributable failure."""
    server = FakeOpenAIServer(FakeResponse(malformed_sse=True))
    async with make_client(server) as client:
        stream = client.stream("hi", target="openai-compat:fake-model-small")
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            async for _ in stream:
                pass

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.type_name == "StreamProtocolError"


async def test_omitted_usage_chunk_yields_a_result_with_unknown_usage() -> None:
    """A stream without a terminal usage chunk reports unknown, never a guess of zero."""
    server = FakeOpenAIServer(FakeResponse(text="fine anyway", omit_usage_chunk=True))
    async with make_client(server) as client:
        stream = client.stream("hi", target="openai-compat:fake-model-small")
        result = await stream.collect()

    assert result.text == "fine anyway"
    assert result.usage.output_tokens is None


async def test_retain_raw_keeps_the_provider_payload() -> None:
    server = FakeOpenAIServer(FakeResponse(text="raw kept"))
    async with make_client(server, retain_raw=True) as client:
        result = await client.generate("hi", target="openai-compat:fake-model-small")

    assert isinstance(result.raw, dict)
    assert result.raw["id"] == "chatcmpl-fake"


async def test_raw_is_dropped_by_default() -> None:
    """Raw payloads carry response text that payload-free telemetry deliberately omits."""
    server = FakeOpenAIServer(FakeResponse(text="raw dropped"))
    async with make_client(server) as client:
        result = await client.generate("hi", target="openai-compat:fake-model-small")

    assert result.raw is None
