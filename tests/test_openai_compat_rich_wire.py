"""Focused public controls for the OpenAI-compatible rich wire projection."""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.providers.base import ProviderConfig, WireRequest
from anyinfer.providers.openai_compat import OpenAICompatAdapter
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.messages import Message, Text, ToolCall, ToolResult
from support import make_client


async def test_rich_media_projects_in_order_with_inline_data_and_audio_subtype() -> None:
    server = FakeOpenAIServer(FakeResponse(text="seen"))
    message = Message(
        "user",
        (
            Text("before"),
            ai.ImagePart(url="https://images.invalid/a.png", detail="low"),
            Text("between"),
            ai.DocumentPart(data=b"pdf", filename="report.pdf"),
            ai.AudioPart(b"mp3", "audio/mpeg"),
            Text("after"),
        ),
    )
    async with make_client(server) as client:
        assert (await client.generate(message, target="openai-compat:m")).text == "seen"

    content = server.requests[0]["messages"][0]["content"]
    assert [item["type"] for item in content] == [
        "text",
        "image_url",
        "text",
        "file",
        "input_audio",
        "text",
    ]
    assert content[1]["image_url"] == {"url": "https://images.invalid/a.png", "detail": "low"}
    assert content[3]["file"] == {
        "file_data": "data:application/pdf;base64,cGRm",
        "filename": "report.pdf",
    }
    assert content[4]["input_audio"] == {"data": "bXAz", "format": "mp3"}


async def test_document_url_and_video_are_refused_before_http_dispatch() -> None:
    server = FakeOpenAIServer()
    async with make_client(server) as client:
        with pytest.raises(ai.AllTargetsFailedError, match="document URL"):
            await client.generate(
                Message("user", (ai.DocumentPart(url="https://files.invalid/a.pdf"),)),
                target="openai-compat:m",
            )
        with pytest.raises(ai.AllTargetsFailedError, match="video"):
            await client.generate(
                Message("user", (ai.VideoPart(url="https://video.invalid/a.mp4"),)),
                target="openai-compat:m",
            )
    assert server.call_count == 0


async def test_logprob_wire_forms_parse_buffered_and_streamed_entries() -> None:
    response = FakeResponse(
        text="ok",
        logprobs=(("o", -0.1), ("k", -0.2)),
        top_logprobs=(("x", -1.0),),
    )
    buffered = FakeOpenAIServer(response)
    async with make_client(buffered) as client:
        result = await client.generate("question", target="openai-compat:m", logprobs=2)
    assert buffered.requests[0]["logprobs"] is True
    assert buffered.requests[0]["top_logprobs"] == 2
    assert [entry.token for entry in result.logprobs] == ["o", "k"]
    assert result.logprobs[0].bytes == (111,)
    assert result.logprobs[0].top[0].token == "x"

    streamed = FakeOpenAIServer(response, chunk_size=1)
    async with make_client(streamed) as client:
        events = [
            event
            async for event in client.stream("question", target="openai-compat:m", logprobs=0)
        ]
    assert streamed.requests[0]["logprobs"] is True
    assert "top_logprobs" not in streamed.requests[0]
    ended = events[-1]
    assert isinstance(ended, ai.StreamEnded)
    assert [entry.token for entry in ended.result.logprobs] == ["o", "k"]


async def test_tool_history_uses_first_result_and_call_only_null_content() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    adapter = OpenAICompatAdapter(
        ProviderConfig(
            "openai-compat", base_url="https://fake.invalid/v1", transport=server.transport()
        )
    )
    try:
        request = WireRequest(
            model="m",
            messages=(
                Message(
                    "assistant",
                    (
                        Text("ignored"),
                        ToolResult("first", "first output"),
                        ToolResult("second", "second output"),
                    ),
                ),
                Message("assistant", (ToolCall("call-1", "weather", {"city": "Boston"}),)),
            ),
            stream=False,
        )
        _ = [event async for event in adapter.generate(request)]
    finally:
        await adapter.aclose()

    result, call = server.requests[0]["messages"]
    assert result == {"role": "tool", "tool_call_id": "first", "content": "first output"}
    assert call["content"] is None
    assert call["tool_calls"][0]["function"] == {
        "name": "weather",
        "arguments": '{"city": "Boston"}',
    }


async def test_extra_options_override_reasoning_then_buffered_payload_removes_stream_controls() -> (
    None
):
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    adapter = OpenAICompatAdapter(
        ProviderConfig(
            "openai-compat", base_url="https://fake.invalid/v1", transport=server.transport()
        )
    )
    try:
        events = [
            event
            async for event in adapter.generate(
                WireRequest(
                    model="m",
                    messages=(Message("user", (Text("question"),)),),
                    stream=False,
                    reasoning_wire={"collision": "reasoning", "stream": True},
                    extra_options={
                        "collision": "extra",
                        "stream": True,
                        "stream_options": {"include_usage": False},
                    },
                )
            )
        ]
    finally:
        await adapter.aclose()

    assert events[-1].raw is not None
    assert server.requests[0]["collision"] == "extra"
    assert "stream" not in server.requests[0]
    assert "stream_options" not in server.requests[0]
