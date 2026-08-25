"""The hosted adapters: openai (Responses), anthropic, azure-foundry, openrouter.

Each provider's *dialect* is what is tested here — the ways its wire format differs from
the OpenAI shape. Behavior they share with the core (routing, validation, timing) is
covered once, in the core's own tests.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.providers.anthropic import ANTHROPIC_VERSION
from anyinfer.providers.azure_foundry import AzureFoundryAdapter
from anyinfer.providers.base import ProviderConfig
from anyinfer.providers.openrouter import OpenRouterAdapter
from anyinfer.testing.conformance import (
    Capabilities,
    ConformanceHarness,
    run_conformance,
)
from anyinfer.testing.fakes import (
    FakeAnthropicServer,
    FakeOpenAIServer,
    FakeResponsesServer,
    scenario_responses,
    sse_lines,
)


def _client(provider: str, handler: Any, **settings: Any) -> ai.AsyncClient:
    return ai.AsyncClient(
        [ai.ProviderSettings.of(provider, transport=httpx2.MockTransport(handler), **settings)]
    )


def _capture(handler_body: Any) -> tuple[list[dict[str, Any]], Any]:
    """Wrap a response factory, recording every request body it receives."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.content:
            seen.append(json.loads(request.content))
        return handler_body(request)

    return seen, handler


# ---- anthropic -----------------------------------------------------------------------


def _anthropic_stream(*, text: str = "Hello", thinking: str = "") -> bytes:
    events: list[dict[str, Any]] = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
    ]
    if thinking:
        events.append(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": thinking},
            }
        )
    events.append(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text},
        }
    )
    events.append(
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 5},
        }
    )
    events.append({"type": "message_stop"})
    return sse_lines(events, done=False)


async def test_anthropic_streaming_and_usage() -> None:
    _, handler = _capture(
        lambda r: httpx2.Response(
            200,
            content=_anthropic_stream(text="Hello from Claude"),
            headers={"content-type": "text/event-stream"},
        )
    )
    async with _client("anthropic", handler, api_key="sk-test-key-value") as client:
        result = await client.generate("hi", target="anthropic:claude-sonnet-4-5")

    assert result.text == "Hello from Claude"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 5
    assert result.finish_reason == "stop"


async def test_anthropic_thinking_is_excluded_from_the_answer() -> None:
    handler = lambda r: httpx2.Response(  # noqa: E731
        200,
        content=_anthropic_stream(text="42", thinking="Let me work this out..."),
        headers={"content-type": "text/event-stream"},
    )
    async with _client("anthropic", handler, api_key="sk-test-key-value") as client:
        stream = client.stream("hi", target="anthropic:claude-sonnet-4-5")
        events = [e async for e in stream]
        result = stream.result

    reasoning = [e for e in events if isinstance(e, ai.ReasoningDelta)]
    assert reasoning and reasoning[0].text == "Let me work this out..."
    assert result.text == "42", "thinking must not contaminate the answer"
    assert result.timing.first_token_ms is not None, "thinking still starts the clock"


async def test_anthropic_system_prompt_is_a_top_level_field() -> None:
    seen, handler = _capture(
        lambda r: httpx2.Response(
            200, content=_anthropic_stream(), headers={"content-type": "text/event-stream"}
        )
    )
    async with _client("anthropic", handler, api_key="sk-test-key-value") as client:
        await client.generate(
            [ai.system("Be terse."), ai.user("hi")],
            target="anthropic:claude-sonnet-4-5",
        )

    body = seen[0]
    assert body["system"] == "Be terse."
    assert all(m["role"] != "system" for m in body["messages"])


async def test_anthropic_requires_max_tokens() -> None:
    """The API rejects a request without it, so a default is supplied rather than a 400."""
    seen, handler = _capture(
        lambda r: httpx2.Response(
            200, content=_anthropic_stream(), headers={"content-type": "text/event-stream"}
        )
    )
    async with _client("anthropic", handler, api_key="sk-test-key-value") as client:
        await client.generate("hi", target="anthropic:claude-sonnet-4-5")
        await client.generate(
            "hi",
            target="anthropic:claude-sonnet-4-5",
            sampling=ai.Sampling(max_output_tokens=99),
        )

    assert seen[0]["max_tokens"] == 4096
    assert seen[1]["max_tokens"] == 99


async def test_anthropic_sends_its_version_header() -> None:
    captured: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request.headers)
        return httpx2.Response(
            200, content=_anthropic_stream(), headers={"content-type": "text/event-stream"}
        )

    async with _client("anthropic", handler, api_key="sk-test-key-value") as client:
        await client.generate("hi", target="anthropic:claude-sonnet-4-5")

    assert captured[0]["anthropic-version"] == ANTHROPIC_VERSION
    assert captured[0]["x-api-key"] == "sk-test-key-value"
    assert "authorization" not in captured[0]


async def _anthropic_headers(**settings: Any) -> httpx2.Headers:
    """Run one generation and return the request headers it sent."""
    captured: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request.headers)
        return httpx2.Response(
            200, content=_anthropic_stream(), headers={"content-type": "text/event-stream"}
        )

    async with _client("anthropic", handler, **settings) as client:
        await client.generate("hi", target="anthropic:claude-sonnet-4-5")
    return captured[0]


async def test_anthropic_oauth_token_is_a_bearer_with_the_beta_flag() -> None:
    """A claude.ai token authenticates differently from an API key, not just by value."""
    headers = await _anthropic_headers(options={"oauth_token": "sk-ant-oat01-abc"})

    assert headers["authorization"] == "Bearer sk-ant-oat01-abc"
    assert headers["anthropic-beta"] == "oauth-2025-04-20"
    # x-api-key alongside a bearer token is what the API rejects.
    assert "x-api-key" not in headers


async def test_anthropic_oauth_token_wins_over_an_api_key() -> None:
    """Both set is a user error the descriptor warns about; it must resolve, not 401."""
    headers = await _anthropic_headers(
        api_key="sk-ant-api-key", options={"oauth_token": "sk-ant-oat01-abc"}
    )

    assert headers["authorization"] == "Bearer sk-ant-oat01-abc"
    assert "x-api-key" not in headers


async def test_anthropic_blank_oauth_token_falls_back_to_the_api_key() -> None:
    """An emptied field must not shadow the key the user still has configured."""
    headers = await _anthropic_headers(api_key="sk-ant-api-key", options={"oauth_token": "   "})

    assert headers["x-api-key"] == "sk-ant-api-key"
    assert "authorization" not in headers


async def test_anthropic_oauth_token_resolves_credential_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second credential goes through the resolver, like the first one does.

    Without this the adapter would send the literal string ``env://...`` as a token, and
    a real one would never be registered for redaction.
    """
    monkeypatch.setenv("DEMO_ANTHROPIC_OAUTH", "sk-ant-oat01-from-env")
    headers = await _anthropic_headers(options={"oauth_token": "env://DEMO_ANTHROPIC_OAUTH"})

    assert headers["authorization"] == "Bearer sk-ant-oat01-from-env"


async def test_anthropic_schema_becomes_a_forced_tool() -> None:
    """Anthropic has no response_format, so a schema is emulated as a forced tool call."""
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": json.dumps({"n": 7})},
        },
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
    ]
    seen, handler = _capture(
        lambda r: httpx2.Response(
            200,
            content=sse_lines(events, done=False),
            headers={"content-type": "text/event-stream"},
        )
    )
    async with _client("anthropic", handler, api_key="sk-test-key-value") as client:
        result = await client.generate("hi", target="anthropic:claude-sonnet-4-5", schema=schema)

    body = seen[0]
    assert body["tool_choice"]["type"] == "tool"
    assert any(t["name"] == body["tool_choice"]["name"] for t in body["tools"])
    assert result.structured == {"n": 7}


async def test_anthropic_reasoning_effort_becomes_a_thinking_budget() -> None:
    seen, handler = _capture(
        lambda r: httpx2.Response(
            200, content=_anthropic_stream(), headers={"content-type": "text/event-stream"}
        )
    )
    async with _client("anthropic", handler, api_key="sk-test-key-value") as client:
        await client.generate("hi", target="anthropic:c", reasoning="high")
        await client.generate("hi", target="anthropic:c", reasoning="minimal")

    assert seen[0]["thinking"] == {"type": "enabled", "budget_tokens": 16384}
    assert seen[1]["thinking"] == {"type": "disabled"}


async def test_anthropic_tool_calls_use_dense_slots() -> None:
    """Block indices count text blocks too, so tool slots must be renumbered."""
    events = [
        {"type": "message_start", "message": {"usage": {}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Let me look."},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "lookup"},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"key":'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": ' "alpha"}'},
        },
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ]
    handler = lambda r: httpx2.Response(  # noqa: E731
        200,
        content=sse_lines(events, done=False),
        headers={"content-type": "text/event-stream"},
    )
    async with _client("anthropic", handler, api_key="sk-test-key-value") as client:
        result = await client.generate("hi", target="anthropic:c")

    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "toolu_1"
    assert call.name == "lookup"
    assert call.arguments == {"key": "alpha"}


async def test_anthropic_mid_stream_error_event_is_a_provider_error() -> None:
    """An ``error`` SSE event mid-stream must become a typed failure the router sees."""
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 2}}},
        {"type": "error", "error": {"type": "overloaded_error", "message": "overloaded"}},
    ]
    handler = lambda r: httpx2.Response(  # noqa: E731
        200,
        content=sse_lines(events, done=False),
        headers={"content-type": "text/event-stream"},
    )
    async with _client("anthropic", handler, api_key="sk-test-key-value") as client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("hi", target="anthropic:claude-sonnet-4-5")

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.type_name == "ProviderError"
    assert "overloaded" in error.detail


# ---- openai (Responses) --------------------------------------------------------------


def _responses_stream(*, text: str = "Hi", reasoning: str = "") -> bytes:
    events: list[dict[str, Any]] = []
    if reasoning:
        events.append({"type": "response.reasoning_text.delta", "delta": reasoning})
    events.append({"type": "response.output_text.delta", "delta": text})
    events.append(
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "usage": {
                    "input_tokens": 9,
                    "output_tokens": 4,
                    "total_tokens": 13,
                    "output_tokens_details": {"reasoning_tokens": 2},
                },
            },
        }
    )
    return sse_lines(events, done=False)


async def test_openai_responses_streaming_and_usage() -> None:
    handler = lambda r: httpx2.Response(  # noqa: E731
        200,
        content=_responses_stream(text="Hi there"),
        headers={"content-type": "text/event-stream"},
    )
    async with _client("openai", handler, api_key="sk-test-key-value") as client:
        result = await client.generate("hi", target="openai:gpt-5")

    assert result.text == "Hi there"
    assert result.usage.input_tokens == 9
    assert result.usage.output_tokens == 4
    assert result.usage.reasoning_tokens == 2


async def test_openai_uses_instructions_and_input_items() -> None:
    seen, handler = _capture(
        lambda r: httpx2.Response(
            200, content=_responses_stream(), headers={"content-type": "text/event-stream"}
        )
    )
    async with _client("openai", handler, api_key="sk-test-key-value") as client:
        await client.generate([ai.system("Be brief."), ai.user("hi")], target="openai:gpt-5")

    body = seen[0]
    assert body["instructions"] == "Be brief."
    assert body["input"][0]["role"] == "user"
    assert body["input"][0]["content"][0]["type"] == "input_text"


async def test_openai_reasoning_effort_passes_through() -> None:
    seen, handler = _capture(
        lambda r: httpx2.Response(
            200, content=_responses_stream(), headers={"content-type": "text/event-stream"}
        )
    )
    async with _client("openai", handler, api_key="sk-test-key-value") as client:
        await client.generate("hi", target="openai:gpt-5", reasoning="high")

    assert seen[0]["reasoning"] == {"effort": "high"}


async def test_openai_max_output_tokens_field_name() -> None:
    seen, handler = _capture(
        lambda r: httpx2.Response(
            200, content=_responses_stream(), headers={"content-type": "text/event-stream"}
        )
    )
    async with _client("openai", handler, api_key="sk-test-key-value") as client:
        await client.generate(
            "hi", target="openai:gpt-5", sampling=ai.Sampling(max_output_tokens=256)
        )

    assert seen[0]["max_output_tokens"] == 256
    assert "max_tokens" not in seen[0]


async def test_openai_incomplete_response_maps_to_length() -> None:
    events = [
        {"type": "response.output_text.delta", "delta": "truncated"},
        {
            "type": "response.incomplete",
            "response": {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            },
        },
    ]
    handler = lambda r: httpx2.Response(  # noqa: E731
        200,
        content=sse_lines(events, done=False),
        headers={"content-type": "text/event-stream"},
    )
    async with _client("openai", handler, api_key="sk-test-key-value") as client:
        result = await client.generate("hi", target="openai:gpt-5")

    assert result.finish_reason == "length"


async def test_openai_tool_calls_stream_by_output_index() -> None:
    events = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"type": "function_call", "call_id": "fc_1", "name": "lookup"},
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "delta": '{"key": "alpha"}',
        },
        {"type": "response.completed", "response": {"status": "completed"}},
    ]
    handler = lambda r: httpx2.Response(  # noqa: E731
        200,
        content=sse_lines(events, done=False),
        headers={"content-type": "text/event-stream"},
    )
    async with _client("openai", handler, api_key="sk-test-key-value") as client:
        result = await client.generate("hi", target="openai:gpt-5")

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0].name == "lookup"
    assert result.tool_calls[0].arguments == {"key": "alpha"}


async def test_openai_schema_uses_text_format() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    events = [
        {"type": "response.output_text.delta", "delta": json.dumps({"n": 1})},
        {"type": "response.completed", "response": {"status": "completed"}},
    ]
    seen, handler = _capture(
        lambda r: httpx2.Response(
            200,
            content=sse_lines(events, done=False),
            headers={"content-type": "text/event-stream"},
        )
    )
    async with _client("openai", handler, api_key="sk-test-key-value") as client:
        result = await client.generate("hi", target="openai:gpt-5", schema=schema)

    assert seen[0]["text"]["format"]["type"] == "json_schema"
    assert result.structured == {"n": 1}
    assert result.structured_mechanism == "json_schema"


async def test_openai_failed_response_event_is_a_provider_error() -> None:
    """A ``response.failed`` event mid-stream must become a typed failure, not a result."""
    events = [
        {"type": "response.output_text.delta", "delta": "partial"},
        {
            "type": "response.failed",
            "response": {
                "status": "failed",
                "error": {"code": "server_error", "message": "server overloaded"},
            },
        },
    ]
    handler = lambda r: httpx2.Response(  # noqa: E731
        200,
        content=sse_lines(events, done=False),
        headers={"content-type": "text/event-stream"},
    )
    async with _client("openai", handler, api_key="sk-test-key-value") as client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("hi", target="openai:gpt-5")

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.type_name == "ProviderError"
    assert "server overloaded" in error.detail


# ---- azure foundry -------------------------------------------------------------------


def _openai_compat_body(text: str = "azure answer") -> dict[str, Any]:
    return {
        "id": "c",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }


async def test_azure_renames_the_output_token_parameter() -> None:
    """Azure rejects ``max_tokens``; the subclass must send ``max_completion_tokens``."""
    seen, handler = _capture(lambda r: httpx2.Response(200, json=_openai_compat_body()))
    client = _client(
        "azure-foundry",
        handler,
        base_url="https://res.services.ai.azure.com/openai/v1",
        api_key="azure-key-value",
    )
    async with client:
        await client.generate(
            "hi",
            target="azure-foundry:gpt-5",
            sampling=ai.Sampling(max_output_tokens=128),
        )

    assert seen[0]["max_completion_tokens"] == 128
    assert "max_tokens" not in seen[0]


async def test_azure_uses_the_api_key_header() -> None:
    captured: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request.headers)
        return httpx2.Response(200, json=_openai_compat_body())

    client = _client(
        "azure-foundry",
        handler,
        base_url="https://res.services.ai.azure.com/openai/v1",
        api_key="azure-key-value",
    )
    async with client:
        await client.generate("hi", target="azure-foundry:gpt-5")

    assert captured[0]["api-key"] == "azure-key-value"
    assert "authorization" not in captured[0]


async def test_azure_requires_a_base_url() -> None:
    with pytest.raises(ai.ConfigError) as excinfo:
        AzureFoundryAdapter(ProviderConfig(provider_id="azure-foundry"))
    assert excinfo.value.hint is not None


async def test_azure_api_version_is_appended_per_instance() -> None:
    """The query parameter must not leak onto other instances of the base dialect."""
    handler = lambda r: httpx2.Response(200, json=_openai_compat_body())  # noqa: E731
    versioned = AzureFoundryAdapter(
        ProviderConfig(
            provider_id="azure-foundry",
            base_url="https://res.services.ai.azure.com/openai/v1",
            api_key="k",
            api_version="2024-10-21",
            transport=httpx2.MockTransport(handler),
        )
    )
    plain = AzureFoundryAdapter(
        ProviderConfig(
            provider_id="azure-foundry",
            base_url="https://res.services.ai.azure.com/openai/v1",
            api_key="k",
            transport=httpx2.MockTransport(handler),
        )
    )
    try:
        assert "api-version=2024-10-21" in versioned.chat_path
        assert "api-version" not in plain.chat_path
    finally:
        await versioned.aclose()
        await plain.aclose()


def _azure_embedding_body() -> dict[str, Any]:
    return {
        "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    }


async def test_azure_embeds_against_the_v1_embeddings_path() -> None:
    seen, handler = _capture(lambda r: httpx2.Response(200, json=_azure_embedding_body()))
    client = _client(
        "azure-foundry",
        handler,
        base_url="https://res.services.ai.azure.com/openai/v1",
        api_key="azure-key-value",
    )
    async with client:
        result = await client.embed("hi", target="azure-foundry:text-embedding-3-small")

    assert seen[0]["model"] == "text-embedding-3-small"
    assert result.vectors[0].values == pytest.approx((0.1, 0.2, 0.3))


async def test_azure_embeddings_path_carries_the_api_version() -> None:
    handler = lambda r: httpx2.Response(200, json=_azure_embedding_body())  # noqa: E731
    versioned = AzureFoundryAdapter(
        ProviderConfig(
            provider_id="azure-foundry",
            base_url="https://res.services.ai.azure.com/openai/v1",
            api_key="k",
            api_version="2024-10-21",
            transport=httpx2.MockTransport(handler),
        )
    )
    plain = AzureFoundryAdapter(
        ProviderConfig(
            provider_id="azure-foundry",
            base_url="https://res.services.ai.azure.com/openai/v1",
            api_key="k",
            transport=httpx2.MockTransport(handler),
        )
    )
    try:
        assert "api-version=2024-10-21" in versioned.embeddings_path
        assert "api-version" not in plain.embeddings_path
    finally:
        await versioned.aclose()
        await plain.aclose()


async def test_azure_reasoning_effort_is_a_flat_field() -> None:
    seen, handler = _capture(lambda r: httpx2.Response(200, json=_openai_compat_body()))
    client = _client(
        "azure-foundry",
        handler,
        base_url="https://res.services.ai.azure.com/openai/v1",
        api_key="k",
    )
    async with client:
        await client.generate("hi", target="azure-foundry:gpt-5", reasoning="medium")

    assert seen[0]["reasoning_effort"] == "medium"


# ---- openrouter ----------------------------------------------------------------------


async def test_openrouter_listing_yields_discovered_pricing() -> None:
    """OpenRouter is the one provider that reports real prices, not catalogued estimates."""
    adapter = OpenRouterAdapter(ProviderConfig(provider_id="openrouter", api_key="k"))
    try:
        model = adapter._parse_model(
            {
                "id": "vendor/model-name",
                "context_length": 128000,
                "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                "supported_parameters": ["tools", "structured_outputs", "reasoning"],
                "top_provider": {"max_completion_tokens": 8192},
            }
        )
    finally:
        await adapter.aclose()

    caps = model.capabilities
    assert caps is not None
    assert caps.context_window == ai.Sourced(128000, "discovered")
    assert caps.max_output_tokens == ai.Sourced(8192, "discovered")
    assert caps.pricing is not None
    assert caps.pricing.value.input_per_1m == Decimal("3.000")
    assert caps.pricing.value.output_per_1m == Decimal("15.000000")
    assert caps.pricing.provenance == "discovered"
    assert ai.Feature.JSON_SCHEMA in caps.features.value
    assert ai.Feature.REASONING in caps.features.value


async def test_openrouter_absent_pricing_stays_unknown() -> None:
    """A missing price must never become a zero price."""
    adapter = OpenRouterAdapter(ProviderConfig(provider_id="openrouter", api_key="k"))
    try:
        model = adapter._parse_model({"id": "m", "context_length": 8192})
    finally:
        await adapter.aclose()

    assert model.capabilities is not None
    assert model.capabilities.pricing is None


async def test_openrouter_unsupported_parameters_are_not_claimed() -> None:
    adapter = OpenRouterAdapter(ProviderConfig(provider_id="openrouter", api_key="k"))
    try:
        model = adapter._parse_model({"id": "m", "supported_parameters": []})
    finally:
        await adapter.aclose()

    assert model.capabilities is not None
    features = model.capabilities.features.value
    assert ai.Feature.JSON_SCHEMA not in features
    assert ai.Feature.TOOLS not in features


async def test_openrouter_attribution_headers() -> None:
    captured: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request.headers)
        return httpx2.Response(200, json=_openai_compat_body("routed"))

    client = _client(
        "openrouter",
        handler,
        api_key="or-key-value",
        options={"http_referer": "https://example.test", "x_title": "AnyInfer"},
    )
    async with client:
        result = await client.generate("hi", target="openrouter:vendor/model")

    assert captured[0]["http-referer"] == "https://example.test"
    assert captured[0]["x-title"] == "AnyInfer"
    assert result.text == "routed"


async def test_openrouter_402_maps_to_auth_error() -> None:
    """contracts/openrouter.md — 402 is exhausted credits, an auth-shaped failure.

    The generic mapping would call 402 a plain ProviderError; OpenRouter's billing
    semantics make it non-retryable and actionable, so the adapter's classifier must win.
    """

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(402, json={"error": {"message": "Insufficient credits"}})

    client = _client("openrouter", handler, api_key="or-key-value")
    async with client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("hi", target="openrouter:vendor/model")

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.type_name == "AuthError"
    assert error.retryable is False


# ---- m365 copilot --------------------------------------------------------------------


async def test_m365_declares_the_parameters_it_ignores() -> None:
    """Silently-ignored parameters are the worst failure mode; these are declared."""
    from anyinfer.providers.m365_copilot import descriptor

    assert "temperature" in descriptor.ignored_parameters
    assert "tools" in descriptor.ignored_parameters


async def test_m365_emits_parameter_dropped_events() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.dropped: list[str] = []

        def on_event(self, event: ai.TelemetryEvent) -> None:
            if isinstance(event, ai.ParameterDropped):
                self.dropped.append(event.parameter)

    recorder = Recorder()
    handler = lambda r: httpx2.Response(200, json={"text": "answer"})  # noqa: E731
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "m365-copilot", api_key="token-value", transport=httpx2.MockTransport(handler)
            )
        ],
        observers=[recorder],
    )
    async with client:
        result = await client.generate(
            "hi",
            target="m365-copilot:m365-copilot",
            sampling=ai.Sampling(temperature=0.5),
        )

    assert result.text == "answer"
    assert "temperature" in recorder.dropped


async def test_m365_health_does_not_trigger_an_interactive_prompt() -> None:
    handler = lambda r: httpx2.Response(200, json={})  # noqa: E731
    client = _client("m365-copilot", handler)
    async with client:
        health = await client.health("m365-copilot")

    assert health.ok is False
    assert "interactive" in health.detail


# ---- conformance ---------------------------------------------------------------------
#
# The dialect tests above prove each adapter's divergences. These harnesses prove the
# shared contract on top of them, and are what the published conformance matrix reports.


async def _build_azure_client(scenario: str) -> ai.AsyncClient:
    server = FakeOpenAIServer(
        scenario_responses(scenario), models=("gpt-5-deployment", "text-embedding-3-small")
    )
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "azure-foundry",
                api_key="azure-key",
                base_url="https://fake.services.ai.azure.com/openai/v1",
                transport=server.transport(),
            )
        ],
        route=ai.Route(
            targets=("azure-foundry:gpt-5-deployment",),
            retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
        ),
    )


AZURE_HARNESS = ConformanceHarness(
    provider_id="azure-foundry",
    model="gpt-5-deployment",
    build_client=_build_azure_client,
    # Foundry deployments serve embeddings from the same resource, model-addressed by
    # deployment name. No rerank endpoint exists, and the compat dialect carries token
    # counts for reasoning but no reasoning channel.
    supports=Capabilities(reasoning=False, cancellation=True, embedding=True),
    embedding_model="text-embedding-3-small",
)


async def test_azure_foundry_conformance() -> None:
    results = await run_conformance(AZURE_HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"


async def _build_openrouter_client(scenario: str) -> ai.AsyncClient:
    server = FakeOpenAIServer(
        scenario_responses(scenario), models=("anthropic/claude-sonnet-4-5",)
    )
    return ai.AsyncClient(
        [ai.ProviderSettings.of("openrouter", api_key="or-key", transport=server.transport())],
        route=ai.Route(
            targets=("openrouter:anthropic/claude-sonnet-4-5",),
            retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
        ),
    )


OPENROUTER_HARNESS = ConformanceHarness(
    provider_id="openrouter",
    model="anthropic/claude-sonnet-4-5",
    build_client=_build_openrouter_client,
    # Reasoning availability is per-upstream-model and discovered, never a property of
    # the router itself; the dialect test above covers the translation.
    supports=Capabilities(reasoning=False, cancellation=True),
)


async def test_openrouter_conformance() -> None:
    results = await run_conformance(OPENROUTER_HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"


async def _build_anthropic_client(scenario: str) -> ai.AsyncClient:
    server = FakeAnthropicServer(scenario_responses(scenario))
    return ai.AsyncClient(
        [ai.ProviderSettings.of("anthropic", api_key="sk-ant-test", transport=server.transport())],
        route=ai.Route(
            targets=("anthropic:claude-sonnet-4-5",),
            retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
        ),
    )


ANTHROPIC_HARNESS = ConformanceHarness(
    provider_id="anthropic",
    model="claude-sonnet-4-5",
    build_client=_build_anthropic_client,
    supports=Capabilities(cancellation=True),
)


async def test_anthropic_conformance() -> None:
    results = await run_conformance(ANTHROPIC_HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"


async def _build_openai_client(scenario: str) -> ai.AsyncClient:
    server = FakeResponsesServer(
        scenario_responses(scenario), models=("gpt-5", "text-embedding-3-small")
    )
    return ai.AsyncClient(
        [ai.ProviderSettings.of("openai", api_key="sk-test", transport=server.transport())],
        route=ai.Route(
            targets=("openai:gpt-5",), retry=ai.Retry(max_attempts=2, backoff_base_s=0.0)
        ),
    )


OPENAI_HARNESS = ConformanceHarness(
    provider_id="openai",
    model="gpt-5",
    build_client=_build_openai_client,
    # The Responses API carries a real reasoning channel and a real response-format
    # field, so neither is emulated here. Embeddings share the resource; there is no
    # rerank endpoint.
    supports=Capabilities(cancellation=True, embedding=True),
    embedding_model="text-embedding-3-small",
)


async def test_openai_conformance() -> None:
    results = await run_conformance(OPENAI_HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"


async def test_openai_embedding_errors_are_typed_not_attribute_errors() -> None:
    """A failing embeddings call must raise a retryable provider error.

    `OpenAIAdapter` composes the embeddings mixin without inheriting the compat adapter,
    so it is the one adapter that has to supply `_classify` itself. When it did not, the
    mixin's error path raised `AttributeError` — which the router cannot retry, because
    what it caught was not a provider error at all. A 429 became a crash.
    """
    from anyinfer.errors import ProviderError
    from anyinfer.providers.base import EmbeddingWireRequest
    from anyinfer.providers.openai import OpenAIAdapter

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429, json={"error": {"message": "slow down"}}, headers={"retry-after": "3"}
        )

    adapter = OpenAIAdapter(
        ProviderConfig(
            provider_id="openai",
            api_key="sk-test",
            transport=httpx2.MockTransport(handler),
        )
    )
    try:
        with pytest.raises(ProviderError) as caught:
            await adapter.embed(
                EmbeddingWireRequest(model="text-embedding-3-small", inputs=("alpha",))
            )
    finally:
        await adapter.aclose()

    assert caught.value.retryable is True
    assert caught.value.retry_after_s == 3


# ---- m365-copilot conformance ----------------------------------------------------------
#
# The documented degraded case, and the reason it gets a row at all: a provider absent
# from the matrix looks untested, while a row of declared gaps says exactly what it does
# and does not do. Its authentication is interactive-only, so the live lane is exempt --
# but the *dialect* is a single buffered POST, which a fake models completely.


def _m365_server(scenario: str) -> Any:
    """One buffered endpoint: `POST /copilot/conversations` returning `{"text": ...}`."""
    responses = scenario_responses(scenario)
    state = {"call": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        index = min(state["call"], len(responses) - 1)
        response = responses[index]
        state["call"] += 1
        if response.status >= 400:
            return httpx2.Response(
                response.status,
                json={"error": {"message": response.error_message}},
                headers=dict(response.headers),
            )
        return httpx2.Response(
            200,
            json={
                "text": response.text,
                "usage": {"promptTokens": 11, "completionTokens": 7},
            },
            headers=dict(response.headers),
        )

    return handler


async def _build_m365_client(scenario: str) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "m365-copilot",
                # A pre-acquired token: the adapter only signs in interactively when it
                # has none, which is precisely what it must never do in a test.
                api_key="m365-test-token",
                transport=httpx2.MockTransport(_m365_server(scenario)),
            )
        ],
        route=ai.Route(
            targets=("m365-copilot:m365-copilot",),
            retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
        ),
    )


M365_HARNESS = ConformanceHarness(
    provider_id="m365-copilot",
    model="m365-copilot",
    build_client=_build_m365_client,
    # Every False here is a documented property of the service, not a gap in this fake.
    # The response arrives whole, so there is no incremental stream and no meaningful
    # first-token time; there are no tools, no reasoning channel, and no response-format
    # field. A schema is prompt-injected and validated client-side, which is why
    # structured output and repair stay on.
    supports=Capabilities(
        streaming=False,
        ttft=False,
        tools=False,
        reasoning=False,
        cancellation=False,
    ),
)


async def test_m365_copilot_conformance() -> None:
    results = await run_conformance(M365_HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"
