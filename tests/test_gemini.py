"""The Gemini adapter: native protocol translation, thinking, and conformance.

What is tested here is the *dialect* — the ways Gemini's generateContent protocol differs
from the OpenAI shape. Behavior shared with the core is covered once, in the core's tests.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.providers.base import AdapterFinal, ProviderConfig, WireRequest
from anyinfer.providers.gemini import GeminiAdapter
from anyinfer.testing.conformance import (
    Capabilities,
    ConformanceHarness,
    run_conformance,
)
from anyinfer.testing.fakes import FakeGeminiServer, FakeResponse
from anyinfer.types.messages import Message, ToolCall, ToolResult
from anyinfer.types.requests import Sampling, ToolSpec

PROBE_ANSWER = json.dumps({"answer": "ok"})


def _client(server: FakeGeminiServer, **settings: Any) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "gemini", api_key="test-key", transport=server.transport(), **settings
            )
        ]
    )


def _adapter(handler: Any) -> GeminiAdapter:
    return GeminiAdapter(
        ProviderConfig(
            provider_id="gemini",
            api_key="test-key",
            transport=httpx2.MockTransport(handler),
        )
    )


# ---- wire shape ----------------------------------------------------------------------


async def test_system_prompt_becomes_a_top_level_instruction() -> None:
    server = FakeGeminiServer(FakeResponse(text="hi"))
    async with _client(server) as client:
        await client.generate(
            [ai.system("Be terse."), ai.user("hello")],
            target="gemini:gemini-2.5-flash",
        )

    body = server.requests[0]
    assert body["systemInstruction"]["parts"][0]["text"] == "Be terse."
    assert [c["role"] for c in body["contents"]] == ["user"]


async def test_assistant_turns_use_the_model_role() -> None:
    server = FakeGeminiServer(FakeResponse(text="hi"))
    async with _client(server) as client:
        await client.generate(
            [ai.user("one"), ai.assistant("two"), ai.user("three")],
            target="gemini:gemini-2.5-flash",
        )

    assert [c["role"] for c in server.requests[0]["contents"]] == ["user", "model", "user"]


async def test_sampling_lives_under_generation_config() -> None:
    server = FakeGeminiServer(FakeResponse(text="hi"))
    async with _client(server) as client:
        await client.generate(
            "hello",
            target="gemini:gemini-2.5-flash",
            sampling=Sampling(temperature=0.2, top_p=0.9, max_output_tokens=64, stop=("END",)),
        )

    config = server.requests[0]["generationConfig"]
    assert config["temperature"] == 0.2
    assert config["topP"] == 0.9
    assert config["maxOutputTokens"] == 64
    assert config["stopSequences"] == ["END"]
    assert "temperature" not in server.requests[0], "sampling is nested, not top-level"


async def test_api_key_is_sent_as_the_goog_header() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"models": []})

    adapter = _adapter(handler)
    try:
        await adapter.list_models()
    finally:
        await adapter.aclose()

    assert seen[0].headers["x-goog-api-key"] == "test-key"
    assert "authorization" not in seen[0].headers


# ---- thinking ------------------------------------------------------------------------


async def test_thought_parts_are_reasoning_not_answer_text() -> None:
    """A `thought`-flagged part starts the clock but must not contaminate the answer."""
    server = FakeGeminiServer(FakeResponse(text="42", reasoning="Let me think."))
    async with _client(server) as client:
        stream = client.stream("hard question", target="gemini:gemini-2.5-flash")
        events = [event async for event in stream]
        result = stream.result

    reasoning = [e for e in events if isinstance(e, ai.ReasoningDelta)]
    assert reasoning, "thought parts must surface as ReasoningDelta"
    assert "".join(e.text for e in reasoning) == "Let me think."
    assert result.text == "42", "thinking must be excluded from the answer"
    assert result.timing.first_token_ms is not None, "thinking still starts the clock"


async def test_reasoning_effort_becomes_a_thinking_level() -> None:
    server = FakeGeminiServer(FakeResponse(text="hi"))
    async with _client(server) as client:
        await client.generate("hi", target="gemini:gemini-2.5-flash", reasoning="high")
        await client.generate("hi", target="gemini:gemini-2.5-flash", reasoning="minimal")

    assert server.requests[0]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "high"}
    assert server.requests[1]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}


async def test_thinking_tokens_are_counted_as_output_and_reported_separately() -> None:
    """Thoughts bill at the output rate but are excluded from candidatesTokenCount."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "ok"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 30,
                    "cachedContentTokenCount": 40,
                },
            },
        )

    adapter = _adapter(handler)
    try:
        events = [
            e
            async for e in adapter.generate(
                WireRequest(model="gemini-2.5-pro", messages=(ai.user("hi"),), stream=False)
            )
        ]
    finally:
        await adapter.aclose()

    final = events[-1]
    assert isinstance(final, AdapterFinal)
    usage = final.usage
    assert usage is not None
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50, "candidates + thoughts, since both bill as output"
    assert usage.reasoning_tokens == 30
    assert usage.cache_read_tokens == 40


# ---- structured output ---------------------------------------------------------------


async def test_schema_becomes_a_response_schema_with_json_mime_type() -> None:
    server = FakeGeminiServer(FakeResponse(text=PROBE_ANSWER))
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    async with _client(server) as client:
        result = await client.generate("answer", target="gemini:gemini-2.5-flash", schema=schema)

    config = server.requests[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["properties"]["answer"] == {"type": "string"}
    assert result.structured == {"answer": "ok"}
    assert result.structured_mechanism == "json_schema"


def test_schema_projection_drops_keywords_gemini_rejects() -> None:
    """Unsupported keywords are dropped, not sent: Gemini 400s on an unknown field."""
    projected = GeminiAdapter.project_schema(
        {
            "type": "object",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "properties": {
                "name": {"type": "string", "pattern": "^[a-z]+$", "description": "kept"},
                "tags": {"type": "array", "items": {"type": "string", "$comment": "no"}},
            },
            "required": ["name"],
            "unevaluatedProperties": False,
        }
    )

    assert "$schema" not in projected
    assert "unevaluatedProperties" not in projected
    assert projected["properties"]["name"] == {"type": "string", "description": "kept"}
    assert projected["properties"]["tags"]["items"] == {"type": "string"}
    assert projected["required"] == ["name"]


# ---- tools ---------------------------------------------------------------------------


async def test_tool_calls_arrive_whole_and_reassemble() -> None:
    server = FakeGeminiServer(
        FakeResponse(
            text="",
            tool_calls=(("fc_1", "lookup", '{"key": "alpha"}'),),
            finish_reason="tool_calls",
        )
    )
    async with _client(server) as client:
        result = await client.generate(
            "look up alpha",
            target="gemini:gemini-2.5-flash",
            tools=[
                ToolSpec(
                    name="lookup",
                    description="Look up a value.",
                    parameters={"type": "object", "properties": {"key": {"type": "string"}}},
                )
            ],
        )

    assert result.finish_reason == "tool_calls"
    call = result.tool_calls[0]
    assert call.name == "lookup"
    assert call.arguments == {"key": "alpha"}

    declarations = server.requests[0]["tools"][0]["functionDeclarations"]
    assert declarations[0]["name"] == "lookup"


async def test_tool_results_ride_on_a_user_turn_as_function_responses() -> None:
    server = FakeGeminiServer(FakeResponse(text="done"))
    conversation = [
        ai.user("look up alpha"),
        Message(
            role="assistant",
            content=(ToolCall(id="fc_1", name="lookup", arguments={"key": "alpha"}),),
        ),
        Message(role="tool", content=(ToolResult(call_id="lookup", content='{"v": 1}'),)),
    ]
    async with _client(server) as client:
        await client.generate(conversation, target="gemini:gemini-2.5-flash")

    contents = server.requests[0]["contents"]
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][0]["functionCall"]["name"] == "lookup"
    assert contents[2]["role"] == "user", "tool results are a user turn in this dialect"
    assert contents[2]["parts"][0]["functionResponse"]["response"] == {"v": 1}


async def test_tool_choice_maps_onto_function_calling_mode() -> None:
    server = FakeGeminiServer(FakeResponse(text="hi"))
    tool = ToolSpec(name="lookup", description="d", parameters={"type": "object"})
    async with _client(server) as client:
        await client.generate(
            "hi", target="gemini:gemini-2.5-flash", tools=[tool], tool_choice="required"
        )
        await client.generate(
            "hi", target="gemini:gemini-2.5-flash", tools=[tool], tool_choice="lookup"
        )

    assert server.requests[0]["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    assert server.requests[1]["toolConfig"]["functionCallingConfig"] == {
        "mode": "ANY",
        "allowedFunctionNames": ["lookup"],
    }


# ---- discovery and errors ------------------------------------------------------------


async def test_listing_reports_discovered_context_windows() -> None:
    server = FakeGeminiServer(FakeResponse(text="hi"))
    async with _client(server) as client:
        models = await client.models("gemini")

    assert models[0].id == "gemini-2.5-flash", "the models/ prefix is stripped"
    caps = models[0].capabilities
    assert caps is not None and caps.context_window is not None
    assert caps.context_window.value == 1_048_576
    assert caps.context_window.provenance == "discovered"
    assert caps.features.value & ai.Feature.REASONING


async def test_blocked_prompt_finishes_as_content_filter() -> None:
    """A blocked prompt returns no candidates, so promptFeedback carries the verdict."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []},
        )

    adapter = _adapter(handler)
    try:
        events = [
            e
            async for e in adapter.generate(
                WireRequest(model="gemini-2.5-flash", messages=(ai.user("hi"),), stream=False)
            )
        ]
    finally:
        await adapter.aclose()

    final = events[-1]
    assert isinstance(final, AdapterFinal)
    assert final.finish_reason == "content_filter"


async def test_google_error_shape_is_classified() -> None:
    server = FakeGeminiServer(FakeResponse(status=429, error_message="quota exhausted"))
    async with _client(server) as client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate(
                "hi",
                route=ai.Route(
                    targets=("gemini:gemini-2.5-flash",),
                    retry=ai.Retry(max_attempts=1),
                ),
            )

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.type_name == "RateLimitError"
    assert error.provider == "gemini"
    assert "quota" in error.detail


async def test_unknown_finish_reasons_normalize() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "hi"}]},
                        "finishReason": "SOME_NEW_REASON",
                    }
                ]
            },
        )

    adapter = _adapter(handler)
    try:
        events = [
            e
            async for e in adapter.generate(
                WireRequest(model="gemini-2.5-flash", messages=(ai.user("hi"),), stream=False)
            )
        ]
    finally:
        await adapter.aclose()

    final = events[-1]
    assert isinstance(final, AdapterFinal)
    assert final.finish_reason == "other"


# ---- conformance ---------------------------------------------------------------------


def _server_for(scenario: str) -> FakeGeminiServer:
    if scenario == "tools":
        return FakeGeminiServer(
            FakeResponse(
                text="",
                tool_calls=(("fc_1", "lookup", '{"key": "alpha"}'),),
                finish_reason="tool_calls",
            )
        )
    if scenario == "reasoning":
        return FakeGeminiServer(FakeResponse(text="42", reasoning="Let me think."))
    if scenario == "structured":
        return FakeGeminiServer(FakeResponse(text=PROBE_ANSWER))
    if scenario == "repair":
        return FakeGeminiServer(
            [FakeResponse(text='{"wrong": true}'), FakeResponse(text=PROBE_ANSWER)]
        )
    if scenario == "auth_error":
        return FakeGeminiServer(FakeResponse(status=401, error_message="invalid key"))
    if scenario == "rate_limited":
        return FakeGeminiServer(
            [
                FakeResponse(status=429, error_message="slow down", headers={"retry-after": "0"}),
                FakeResponse(text="recovered"),
            ]
        )
    if scenario == "oversized":
        return FakeGeminiServer(FakeResponse(text="x" * 20_000))
    if scenario == "odd_finish":
        return FakeGeminiServer(FakeResponse(text="hello", finish_reason="model_decided"))
    return FakeGeminiServer(FakeResponse(text="Hello from Gemini."))


async def _build_client(scenario: str) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "gemini", api_key="test-key", transport=_server_for(scenario).transport()
            )
        ],
        route=ai.Route(
            targets=("gemini:gemini-2.5-flash",),
            retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
        ),
    )


HARNESS = ConformanceHarness(
    provider_id="gemini",
    model="gemini-2.5-flash",
    build_client=_build_client,
    supports=Capabilities(cancellation=True),
)


async def test_gemini_conformance() -> None:
    results = await run_conformance(HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"
