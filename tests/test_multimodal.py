"""Multimodal domain, budgeting, codec, and projection behavior."""

from __future__ import annotations

import base64
from decimal import Decimal

import pytest

import anyinfer as ai
from anyinfer.capabilities.budget import build_context_budget
from anyinfer.capabilities.gating import context_gate_error
from anyinfer.providers.anthropic import AnthropicAdapter
from anyinfer.providers.base import ProviderConfig
from anyinfer.providers.bedrock import BedrockAdapter
from anyinfer.providers.gemini import GeminiAdapter
from anyinfer.providers.ollama import OllamaAdapter
from anyinfer.providers.openai import _split_instructions
from anyinfer.serve.openai_codec import request_from_openai, request_to_openai
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.capabilities import ModelCapabilities, Sourced
from anyinfer.types.messages import Message, Text
from anyinfer.types.requests import GenerationRequest
from support import make_client


def _modal_request(*parts: ai.ContentPart) -> GenerationRequest:
    return GenerationRequest(messages=(Message("user", (Text("inspect"), *parts)),))


def test_multimodal_parts_require_one_valid_source() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ai.ImagePart()
    with pytest.raises(ValueError, match="exactly one"):
        ai.DocumentPart(data=b"pdf", url="https://example.invalid/a.pdf")
    with pytest.raises(ValueError, match="audio/"):
        ai.AudioPart(b"sound", "application/octet-stream")


def test_unpriced_parts_make_fit_and_cost_unknown_without_gating() -> None:
    request = _modal_request(ai.ImagePart(data=b"png", media_type="image/png"))
    capabilities = ModelCapabilities(
        context_window=Sourced(1, "catalog"),
        pricing=Sourced(ai.Pricing(Decimal("1"), Decimal("2")), "catalog"),
    )
    budget = build_context_budget(request, capabilities)

    assert budget.estimate.unpriced_parts == 1
    assert budget.remaining_tokens is None
    assert budget.fits is None
    assert budget.estimated_cost is None
    assert context_gate_error(budget, provider="test", model="tiny") is None


async def test_request_side_caps_reject_before_provider_dispatch() -> None:
    server = FakeOpenAIServer(FakeResponse(text="not called"))
    async with make_client(server) as client:
        with pytest.raises(ValueError, match="per-part limit"):
            await client.generate(
                Message("user", (ai.ImagePart(data=b"1234"),)),
                target="openai-compat:m",
                max_input_part_bytes=3,
            )
    assert server.call_count == 0


def test_openai_codec_round_trips_image_audio_and_file_parts() -> None:
    image = base64.b64encode(b"image").decode("ascii")
    audio = base64.b64encode(b"audio").decode("ascii")
    pdf = base64.b64encode(b"pdf").decode("ascii")
    body = {
        "model": "openai-compat:m",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image}",
                            "detail": "high",
                        },
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio, "format": "wav"},
                    },
                    {
                        "type": "file",
                        "file": {
                            "file_data": f"data:application/pdf;base64,{pdf}",
                            "filename": "report.pdf",
                        },
                    },
                ],
            }
        ],
    }

    target, request, stream = request_from_openai(body)
    encoded = request_to_openai(target, request, stream=stream)

    assert encoded == body
    assert request.messages[0].content[1] == ai.ImagePart(
        data=b"image", media_type="image/png", detail="high"
    )
    assert request.messages[0].content[2] == ai.AudioPart(b"audio", "audio/wav")
    assert request.messages[0].content[3] == ai.DocumentPart(
        data=b"pdf", media_type="application/pdf", filename="report.pdf"
    )


async def test_openai_compat_projects_multimodal_content_without_dropping_it() -> None:
    server = FakeOpenAIServer(FakeResponse(text="seen"))
    message = Message(
        "user",
        (
            Text("inspect"),
            ai.ImagePart(data=b"image", media_type="image/png", detail="low"),
            ai.DocumentPart(data=b"pdf", filename="report.pdf"),
            ai.AudioPart(b"audio"),
        ),
    )
    async with make_client(server) as client:
        result = await client.generate(message, target="openai-compat:m")

    assert result.text == "seen"
    content = server.requests[0]["messages"][0]["content"]
    assert [part["type"] for part in content] == [
        "text",
        "image_url",
        "file",
        "input_audio",
    ]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_codec_rejects_invalid_base64_without_echoing_payload() -> None:
    with pytest.raises(ValueError, match="invalid base64") as caught:
        request_from_openai(
            {
                "model": "openai-compat:m",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,SECRET%%%"},
                            }
                        ],
                    }
                ],
            }
        )
    assert "SECRET" not in str(caught.value)


async def test_dedicated_adapters_project_or_explicitly_refuse_modal_parts() -> None:
    message = Message(
        "user",
        (
            Text("inspect"),
            ai.ImagePart(data=b"image", media_type="image/png"),
            ai.DocumentPart(data=b"pdf", media_type="application/pdf", filename="r.pdf"),
        ),
    )
    _, openai_items = _split_instructions((message,))
    assert [item["type"] for item in openai_items[0]["content"]] == [
        "input_text",
        "input_image",
        "input_file",
    ]

    anthropic = AnthropicAdapter(ProviderConfig("anthropic", api_key="test-key"))
    gemini = GeminiAdapter(ProviderConfig("gemini", api_key="test-key"))
    bedrock = BedrockAdapter(
        ProviderConfig(
            "bedrock",
            options={
                "region": "us-east-1",
                "aws_access_key_id": "test-access",
                "aws_secret_access_key": "test-secret",
            },
        )
    )
    ollama = OllamaAdapter(ProviderConfig("ollama"))
    try:
        assert [block["type"] for block in anthropic._encode_message(message)["content"]] == [
            "text",
            "image",
            "document",
        ]
        assert [next(iter(part)) for part in gemini._encode_message(message)["parts"]] == [
            "text",
            "inlineData",
            "inlineData",
        ]
        assert [next(iter(block)) for block in bedrock._encode_message(message)["content"]] == [
            "text",
            "image",
            "document",
        ]
        with pytest.raises(ai.UnsupportedInputError, match="document"):
            ollama._encode_message(message)
        with pytest.raises(ai.UnsupportedInputError, match="audio"):
            anthropic._encode_message(Message("user", (ai.AudioPart(b"wav"),)))
    finally:
        await anthropic.aclose()
        await gemini.aclose()
        await bedrock.aclose()
        await ollama.aclose()
