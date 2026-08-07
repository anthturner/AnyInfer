"""The DeepSeek and xAI adapters, plus the Anthropic-compatible base-URL pattern.

Each provider's *dialect* is what is tested — how it diverges from the OpenAI shape.
Shared behavior is covered once, in the core's own tests.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.providers.base import ProviderConfig, WireRequest
from anyinfer.providers.deepseek import DeepSeekAdapter
from anyinfer.testing.fakes import sse_lines
from anyinfer.types.requests import Sampling


def _client(provider: str, handler: Any, **settings: Any) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                provider, api_key="test-key", transport=httpx2.MockTransport(handler),
                **settings,
            )
        ]
    )


def _capture(response_factory: Any) -> tuple[list[dict[str, Any]], Any]:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.content:
            seen.append(json.loads(request.content))
        return response_factory(request)

    return seen, handler


def _compat_stream(chunks: list[dict[str, Any]]) -> httpx2.Response:
    return httpx2.Response(
        200,
        content=sse_lines(chunks),
        headers={"content-type": "text/event-stream"},
    )


def _delta(delta: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "id": "c",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        **extra,
    }


# ---- deepseek ------------------------------------------------------------------------


async def test_deepseek_reasoning_content_is_a_separate_channel() -> None:
    """Chain-of-thought streams beside content and must not join the answer text."""
    chunks = [
        _delta({"reasoning_content": "Let me "}),
        _delta({"reasoning_content": "think."}),
        _delta({"content": "42"}),
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]
    async with _client("deepseek", lambda r: _compat_stream(chunks)) as client:
        stream = client.stream("hard question", target="deepseek:deepseek-v4-pro")
        events = [event async for event in stream]
        result = stream.result

    reasoning = [e for e in events if isinstance(e, ai.ReasoningDelta)]
    assert "".join(e.text for e in reasoning) == "Let me think."
    assert result.text == "42", "reasoning must be excluded from the answer"
    assert result.timing.first_token_ms is not None, "reasoning still starts the clock"


async def test_deepseek_buffered_reasoning_content_is_surfaced() -> None:
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "42",
                    "reasoning_content": "Thinking...",
                },
                "finish_reason": "stop",
            }
        ]
    }
    adapter = DeepSeekAdapter(
        ProviderConfig(
            provider_id="deepseek",
            api_key="k",
            base_url="https://api.deepseek.com",
            transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=body)),
        )
    )
    try:
        events = [
            e
            async for e in adapter.generate(
                WireRequest(model="deepseek-v4-pro", messages=(ai.user("hi"),),
                            stream=False)
            )
        ]
    finally:
        await adapter.aclose()

    reasoning = [e for e in events if isinstance(e, ai.ReasoningDelta)]
    assert reasoning and reasoning[0].text == "Thinking..."


async def test_deepseek_cache_hit_tokens_become_cache_reads() -> None:
    """prompt_tokens = hits + misses, and only hits change the bill."""
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "total_tokens": 110,
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 20,
        },
    }
    async with _client("deepseek", lambda r: httpx2.Response(200, json=body)) as client:
        result = await client.generate("hi", target="deepseek:deepseek-v4-flash")

    assert result.usage.input_tokens == 100
    assert result.usage.cache_read_tokens == 80


async def test_deepseek_reasoning_effort_enables_thinking() -> None:
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ]
    }
    seen, handler = _capture(lambda r: httpx2.Response(200, json=body))
    async with _client("deepseek", handler) as client:
        await client.generate("hi", target="deepseek:deepseek-v4-pro", reasoning="high")
        await client.generate("hi", target="deepseek:deepseek-v4-pro", reasoning="minimal")

    assert seen[0]["thinking"] == {"type": "enabled"}
    assert seen[0]["reasoning_effort"] == "high"
    assert seen[1]["reasoning_effort"] == "low", "minimal clamps to the lowest level"


async def test_deepseek_declares_silently_ignored_sampling() -> None:
    """Thinking mode discards temperature and top_p, so a caller must be told."""
    recorded: list[ai.TelemetryEvent] = []

    class Recorder:
        def on_event(self, event: ai.TelemetryEvent) -> None:
            recorded.append(event)

    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ]
    }
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "deepseek",
                api_key="k",
                transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=body)),
            )
        ],
        observers=[Recorder()],
    )
    async with client:
        await client.generate(
            "hi",
            target="deepseek:deepseek-v4-pro",
            sampling=Sampling(temperature=0.5),
        )

    dropped = [e for e in recorded if isinstance(e, ai.ParameterDropped)]
    assert [e.parameter for e in dropped] == ["temperature"]


# ---- xai -----------------------------------------------------------------------------


async def test_xai_renames_the_output_token_parameter() -> None:
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ]
    }
    seen, handler = _capture(lambda r: httpx2.Response(200, json=body))
    async with _client("xai", handler) as client:
        await client.generate(
            "hi", target="xai:grok-4.5", sampling=Sampling(max_output_tokens=128)
        )

    assert seen[0]["max_completion_tokens"] == 128
    assert "max_tokens" not in seen[0]


async def test_xai_reported_cost_wins_over_computed_pricing() -> None:
    """A provider-reported cost already includes tiering and tool fees."""
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "total_tokens": 1100,
            "cost_in_usd_ticks": 12_500_000_000,
        },
    }
    async with _client("xai", lambda r: httpx2.Response(200, json=body)) as client:
        result = await client.generate("hi", target="xai:grok-4.5")

    assert result.usage.cost_usd == Decimal("1.25")


async def test_xai_language_model_listing_yields_discovered_pricing() -> None:
    listing = {
        "models": [
            {
                "id": "grok-4.5",
                "max_prompt_length": 2_000_000,
                "prompt_text_token_price": 20000,
                "completion_text_token_price": 100000,
                "input_modalities": ["text", "image"],
            }
        ]
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/language-models")
        return httpx2.Response(200, json=listing)

    async with _client("xai", handler) as client:
        models = await client.models("xai")

    caps = models[0].capabilities
    assert caps is not None
    assert caps.context_window is not None
    assert caps.context_window.value == 2_000_000
    assert caps.pricing is not None
    assert caps.pricing.provenance == "discovered"
    # cents per 100M tokens -> USD per 1M tokens
    assert caps.pricing.value.input_per_1m == Decimal("2")
    assert caps.pricing.value.output_per_1m == Decimal("10")


async def test_xai_listing_falls_back_when_the_rich_endpoint_is_absent() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/language-models"):
            return httpx2.Response(404, json={"error": {"message": "not found"}})
        return httpx2.Response(200, json={"data": [{"id": "grok-4.5"}]})

    async with _client("xai", handler) as client:
        models = await client.models("xai")

    assert [m.id for m in models] == ["grok-4.5"]


async def test_xai_reasoning_effort_passes_through() -> None:
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ]
    }
    seen, handler = _capture(lambda r: httpx2.Response(200, json=body))
    async with _client("xai", handler) as client:
        await client.generate("hi", target="xai:grok-4.5", reasoning="medium")

    assert seen[0]["reasoning_effort"] == "medium"


# ---- the Anthropic-compatible endpoint pattern ---------------------------------------


async def test_anthropic_adapter_serves_a_compatible_endpoint_by_base_url() -> None:
    """Moonshot, Z.ai, DeepSeek and others expose Messages endpoints; a URL is enough."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "hi from kimi"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
             "usage": {"output_tokens": 3}},
            {"type": "message_stop"},
        ]
        return httpx2.Response(
            200, content=sse_lines(events, done=False),
            headers={"content-type": "text/event-stream"},
        )

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "anthropic",
                base_url="https://api.moonshot.ai/anthropic",
                api_key="moonshot-key",
                transport=httpx2.MockTransport(handler),
            )
        ]
    )
    async with client:
        result = await client.generate("hi", target="anthropic:kimi-k2")

    assert result.text == "hi from kimi"
    assert str(seen[0].url).startswith("https://api.moonshot.ai/anthropic/v1/messages")
    assert seen[0].headers["x-api-key"] == "moonshot-key"


async def test_a_compatible_endpoint_can_register_under_its_own_id() -> None:
    """Registered separately, errors attribute to that provider, not to anthropic."""
    from anyinfer.providers.anthropic import AnthropicAdapter
    from anyinfer.providers.anthropic import descriptor as anthropic_descriptor
    from anyinfer.registry import ProviderDescriptor, ProviderRegistry

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="kimi-messages",
            display_name="Moonshot (Anthropic-compatible)",
            factory=AnthropicAdapter,
            default_base_url="https://api.moonshot.ai/anthropic",
            default_capabilities=anthropic_descriptor.default_capabilities,
        )
    )

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "kimi-messages",
                api_key="k",
                transport=httpx2.MockTransport(
                    lambda r: httpx2.Response(
                        401, json={"error": {"message": "bad key"}}
                    )
                ),
            )
        ],
        registry=registry,
    )
    async with client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("hi", target="kimi-messages:kimi-k2")

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.provider == "kimi-messages"
