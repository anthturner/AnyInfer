"""Independent public Python controls for raw tool request policy."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.credentials import LiteralResolver, ResolverChain
from anyinfer.registry import ProviderRegistry


def _completion(
    *,
    content: str | None = "ok",
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
) -> httpx2.Response:
    message: dict[str, Any] = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return httpx2.Response(
        200,
        json={
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


def _client(
    responses: Iterator[httpx2.Response], captured: list[dict[str, Any]]
) -> ai.AsyncClient:
    """Build the actual public builtin descriptor over literal offline responses."""
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    builtin = registry.get("openai-compat")

    def transport(_: str) -> httpx2.MockTransport:
        def handler(request: httpx2.Request) -> httpx2.Response:
            assert request.method == "POST"
            assert request.url.path == "/v1/chat/completions"
            assert request.url.query == b""
            captured.append(json.loads(request.content))
            return next(responses)

        return httpx2.MockTransport(handler)

    def factory(config: Any) -> Any:
        return builtin.factory(replace(config, transport=transport(config.provider_id)))

    registry.register(replace(builtin, factory=factory), replace=True)
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://tools.fixture.invalid/v1",
                api_key="fixture-token",
                alias="primary",
            )
        ],
        registry=registry,
        resolver=ResolverChain([LiteralResolver()]),
        use_default_catalog=False,
    )


def _tool() -> ai.ToolSpec:
    return ai.ToolSpec(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object", "properties": {"key": {"type": "string"}}},
    )


@pytest.mark.asyncio
async def test_public_openai_tool_wire_preserves_choice_feedback_and_arguments() -> None:
    """Public typed parts produce the one documented OpenAI-compatible wire projection."""
    captured: list[dict[str, Any]] = []
    client = _client(
        iter([_completion(), _completion(), _completion()]),
        captured,
    )
    try:
        await client.generate(
            "tools", target="primary:model", tools=[_tool()], tool_choice="lookup"
        )
        await client.generate(
            [
                ai.Message(
                    role="assistant",
                    content=(
                        ai.Text("ignored alongside result"),
                        ai.ToolResult("first", "first result", is_error=True),
                        ai.ToolResult("later", "later result"),
                    ),
                )
            ],
            target="primary:model",
            tools=[],
            tool_choice="none",
        )
        await client.generate(
            [
                ai.Message(
                    role="assistant",
                    content=(ai.ToolCall("call-1", "lookup", {"café": "✓", "n": 1}),),
                )
            ],
            target="primary:model",
        )
    finally:
        await client.aclose()

    declared, feedback, call_only = captured
    assert declared["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up a value.",
                "parameters": {"type": "object", "properties": {"key": {"type": "string"}}},
            },
        }
    ]
    assert declared["tool_choice"] == {"type": "function", "function": {"name": "lookup"}}
    assert "tools" not in feedback and "tool_choice" not in feedback
    assert feedback["messages"] == [
        {"role": "tool", "tool_call_id": "first", "content": "first result"}
    ]
    assert call_only["messages"] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"caf\\u00e9": "\\u2713", "n": 1}',
                    },
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_public_openai_stream_assembles_fragmented_out_of_order_and_invalid_tool_calls() -> (
    None
):
    """Actual SSE parsing preserves content timing and reports malformed call arguments."""
    sse = "".join(
        [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":3}]}}]}\n\n',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"late","function":{"arguments":"{\\"b\\":"}}]}}]}\n\n',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"first","arguments":"[1]"}},{"index":2,"function":{"arguments":"{bad"}}]}}]}\n\n',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"function":{"name":"second","arguments":"2}"}}]},"finish_reason":"stop"}]}\n\n',
            "data: [DONE]\n\n",
        ]
    )
    captured: list[dict[str, Any]] = []
    client = _client(
        iter(
            [
                httpx2.Response(
                    200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8")
                )
            ]
        ),
        captured,
    )
    try:
        stream = client.stream("tools", target="primary:model")
        events = [event async for event in stream]
    finally:
        await client.aclose()

    deltas = [event for event in events if isinstance(event, ai.ToolCallDelta)]
    first_delta = events.index(deltas[0])
    assert isinstance(events[first_delta - 1], ai.TimingMark)
    assert events[first_delta - 1].name == "first_token"
    result = stream.result
    assert result.finish_reason == "tool_calls"
    assert [(call.id, call.name, dict(call.arguments)) for call in result.tool_calls] == [
        ("call_0", "first", {}),
        ("late", "second", {"b": 2}),
        ("call_2", "", {}),
        ("call_3", "", {}),
    ]
    assert any("not a JSON object" in warning for warning in result.warnings)
    assert any("unparseable arguments" in warning for warning in result.warnings)
    assert captured[0]["stream"] is True


@pytest.mark.asyncio
async def test_repair_preserves_typed_feedback_and_keeps_only_winning_tool_calls() -> None:
    """Correction traffic retains feedback while discarded call data never reaches the result."""
    discarded = [{"id": "discarded", "function": {"name": "lookup", "arguments": "{}"}}]
    winner = [{"id": "winner", "function": {"name": "lookup", "arguments": '{"ok": true}'}}]
    captured: list[dict[str, Any]] = []
    client = _client(
        iter(
            [
                _completion(content="not json", tool_calls=discarded),
                _completion(content='{"answer":"ok"}', tool_calls=winner),
            ]
        ),
        captured,
    )
    try:
        result = await client.generate(
            [
                ai.Message(
                    role="tool", content=(ai.ToolResult("tool-1", "feedback", is_error=True),)
                )
            ],
            target="primary:model",
            schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
            repair=ai.Repair(max_attempts=1),
        )
    finally:
        await client.aclose()

    assert result.repair_attempts == 1
    assert [(call.id, call.name, dict(call.arguments)) for call in result.tool_calls] == [
        ("winner", "lookup", {"ok": True})
    ]
    assert len(captured) == 2
    assert all(
        [message for message in body["messages"] if message["role"] == "tool"]
        == [{"role": "tool", "tool_call_id": "tool-1", "content": "feedback"}]
        for body in captured
    )


def test_public_estimator_receives_typed_tool_parts_and_declarations_in_source_order() -> None:
    """The public estimator observes message parts, tools, then schema without a second calculator."""
    calls: list[str] = []

    class RecordingEstimator:
        def estimate(self, text: str) -> ai.TokenEstimate:
            calls.append(text)
            return ai.TokenEstimate(len(text), 0)

    request = ai.GenerationRequest(
        messages=(
            ai.Message(
                role="assistant",
                content=(
                    ai.Text("prefix:"),
                    ai.ToolCall("c", "lookup", {"n": 1}),
                    ai.ToolResult("c", "result"),
                ),
            ),
        ),
        tools=(_tool(),),
        schema=ai.SchemaSpec({"type": "object"}),
    )

    ai.estimate_request(request, estimator=RecordingEstimator())

    assert calls == [
        'prefix:lookup{"n": 1}result',
        '{"name": "lookup", "description": "Look up a value.", "parameters": {"type": "object", "properties": {"key": {"type": "string"}}}}',
        '{"type": "object"}',
    ]
