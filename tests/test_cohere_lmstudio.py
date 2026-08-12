"""The Cohere and LM Studio adapters: uppercase enums, typed events, native discovery."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.providers.base import ProviderConfig
from anyinfer.providers.lm_studio import LMStudioAdapter
from anyinfer.testing.conformance import Capabilities, ConformanceHarness, run_conformance
from anyinfer.testing.fakes import sse_lines
from anyinfer.types.requests import Sampling, ToolSpec


def _client(provider: str, handler: Any, **settings: Any) -> ai.AsyncClient:
    return ai.AsyncClient(
        [ai.ProviderSettings.of(provider, transport=httpx2.MockTransport(handler), **settings)]
    )


def _capture(factory: Any) -> tuple[list[dict[str, Any]], Any]:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.content:
            seen.append(json.loads(request.content))
        return factory(request)

    return seen, handler


# ---- cohere: the v2 shape ------------------------------------------------------------

_COHERE_RESPONSE = {
    "id": "c1",
    "finish_reason": "COMPLETE",
    "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello."}]},
    "usage": {
        "billed_units": {"input_tokens": 10, "output_tokens": 4},
        "tokens": {"input_tokens": 12, "output_tokens": 5},
    },
}


async def test_uppercase_finish_reasons_normalize() -> None:
    async with _client(
        "cohere", lambda r: httpx2.Response(200, json=_COHERE_RESPONSE), api_key="co-key"
    ) as client:
        result = await client.generate("hi", target="cohere:command-a")

    assert result.text == "Hello."
    assert result.finish_reason == "stop", "COMPLETE is not an OpenAI finish reason"


async def test_an_unknown_finish_reason_normalizes_to_other() -> None:
    body = {**_COHERE_RESPONSE, "finish_reason": "SOMETHING_NEW"}
    async with _client(
        "cohere", lambda r: httpx2.Response(200, json=body), api_key="co-key"
    ) as client:
        result = await client.generate("hi", target="cohere:command-a")

    assert result.finish_reason == "other"


async def test_usage_follows_processed_tokens_not_billed_units() -> None:
    """A context window measures what was processed, not what was charged."""
    async with _client(
        "cohere", lambda r: httpx2.Response(200, json=_COHERE_RESPONSE), api_key="co-key"
    ) as client:
        result = await client.generate("hi", target="cohere:command-a")

    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 5


async def test_stream_is_always_sent() -> None:
    """The field is required by this API, not optional."""
    seen, handler = _capture(lambda r: httpx2.Response(200, json=_COHERE_RESPONSE))
    async with _client("cohere", handler, api_key="co-key") as client:
        await client.generate("hi", target="cohere:command-a")

    assert seen[0]["stream"] is False


async def test_sampling_uses_coheres_parameter_names() -> None:
    seen, handler = _capture(lambda r: httpx2.Response(200, json=_COHERE_RESPONSE))
    async with _client("cohere", handler, api_key="co-key") as client:
        await client.generate(
            "hi",
            target="cohere:command-a",
            sampling=Sampling(temperature=0.3, top_p=0.8, max_output_tokens=50, stop=("END",)),
        )

    body = seen[0]
    assert body["p"] == 0.8, "Cohere spells nucleus sampling `p`"
    assert "top_p" not in body
    assert body["temperature"] == 0.3
    assert body["max_tokens"] == 50
    assert body["stop_sequences"] == ["END"]


async def test_tool_choice_uses_the_uppercase_enum() -> None:
    seen, handler = _capture(lambda r: httpx2.Response(200, json=_COHERE_RESPONSE))
    tool = ToolSpec(name="lookup", description="d", parameters={"type": "object"})
    async with _client("cohere", handler, api_key="co-key") as client:
        await client.generate(
            "hi", target="cohere:command-a", tools=[tool], tool_choice="required"
        )
        await client.generate("hi", target="cohere:command-a", tools=[tool], tool_choice="auto")

    assert seen[0]["tool_choice"] == "REQUIRED"
    assert "tool_choice" not in seen[1], "omitting the field is how auto is expressed"


async def test_thinking_blocks_are_a_separate_channel() -> None:
    body = {
        "finish_reason": "COMPLETE",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "Let me think."},
                {"type": "text", "text": "42"},
            ],
        },
    }
    async with _client(
        "cohere", lambda r: httpx2.Response(200, json=body), api_key="co-key"
    ) as client:
        result = await client.generate("hard", target="cohere:command-a")

    assert result.text == "42", "thinking must stay out of the answer"


async def test_reasoning_effort_becomes_a_token_budget() -> None:
    seen, handler = _capture(lambda r: httpx2.Response(200, json=_COHERE_RESPONSE))
    async with _client("cohere", handler, api_key="co-key") as client:
        await client.generate("hi", target="cohere:command-a", reasoning="high")
        await client.generate("hi", target="cohere:command-a", reasoning="minimal")

    assert seen[0]["thinking"] == {"type": "enabled", "token_budget": 16384}
    assert seen[1]["thinking"] == {"type": "disabled"}


async def test_streaming_translates_typed_events() -> None:
    events = [
        {"type": "message-start", "delta": {"message": {"role": "assistant"}}},
        {"type": "content-start", "index": 0, "delta": {"message": {"content": {"type": "text"}}}},
        {
            "type": "content-delta",
            "index": 0,
            "delta": {"message": {"content": {"text": "Hello"}}},
        },
        {
            "type": "content-delta",
            "index": 0,
            "delta": {"message": {"content": {"text": " there"}}},
        },
        {"type": "content-end", "index": 0},
        {
            "type": "message-end",
            "delta": {
                "finish_reason": "COMPLETE",
                "usage": {"tokens": {"input_tokens": 7, "output_tokens": 3}},
            },
        },
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=sse_lines(events, done=False),
            headers={"content-type": "text/event-stream"},
        )

    async with _client("cohere", handler, api_key="co-key") as client:
        stream = client.stream("hi", target="cohere:command-a")
        deltas = [e.text async for e in stream if isinstance(e, ai.TextDelta)]
        result = stream.result

    assert "".join(deltas) == "Hello there"
    assert result.usage.input_tokens == 7, "usage arrives only in message-end"
    assert result.finish_reason == "stop"


async def test_streaming_tool_calls_reassemble() -> None:
    events = [
        {
            "type": "tool-call-start",
            "index": 0,
            "delta": {
                "message": {
                    "tool_calls": {"id": "t1", "type": "function", "function": {"name": "lookup"}}
                }
            },
        },
        {
            "type": "tool-call-delta",
            "index": 0,
            "delta": {"message": {"tool_calls": {"function": {"arguments": '{"key":'}}}},
        },
        {
            "type": "tool-call-delta",
            "index": 0,
            "delta": {"message": {"tool_calls": {"function": {"arguments": '"a"}'}}}},
        },
        {"type": "tool-call-end", "index": 0},
        {"type": "message-end", "delta": {"finish_reason": "TOOL_CALL"}},
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=sse_lines(events, done=False),
            headers={"content-type": "text/event-stream"},
        )

    tool = ToolSpec(name="lookup", description="d", parameters={"type": "object"})
    async with _client("cohere", handler, api_key="co-key") as client:
        stream = client.stream("look it up", target="cohere:command-a", tools=[tool])
        async for _ in stream:
            pass
        result = stream.result

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0].name == "lookup"
    assert result.tool_calls[0].arguments == {"key": "a"}


async def test_discovery_reports_context_lengths() -> None:
    listing = {
        "models": [
            {
                "name": "command-a-03-2025",
                "context_length": 256000,
                "endpoints": ["chat"],
                "features": ["tools"],
            }
        ]
    }
    async with _client(
        "cohere", lambda r: httpx2.Response(200, json=listing), api_key="co-key"
    ) as client:
        models = await client.models("cohere")

    caps = models[0].capabilities
    assert models[0].id == "command-a-03-2025"
    assert caps is not None and caps.context_window is not None
    assert caps.context_window.value == 256000
    assert caps.context_window.provenance == "discovered"


# ---- lm studio -----------------------------------------------------------------------

_NATIVE_LISTING = {
    "models": [
        {
            "key": "qwen3-8b",
            "type": "llm",
            "max_context_length": 32768,
            "params_string": "8B",
            "quantization": {"name": "Q4_K_M"},
            "size_bytes": 4_400_000_000,
            "capabilities": {"trained_for_tool_use": True, "reasoning": True},
            "loaded_instances": [{"id": "inst-1"}],
        },
        {
            "key": "nomic-embed",
            "type": "embedding",
            "max_context_length": 2048,
        },
    ]
}


def _lm_studio(handler: Any) -> LMStudioAdapter:
    return LMStudioAdapter(
        ProviderConfig(
            provider_id="lm-studio",
            base_url="http://127.0.0.1:1234/v1",
            transport=httpx2.MockTransport(handler),
        )
    )


async def test_native_discovery_reports_real_capabilities() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v1/models"
        return httpx2.Response(200, json=_NATIVE_LISTING)

    adapter = _lm_studio(handler)
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    # Embedding models are listed alongside chat models, each tagged with its
    # discovered operation — never filtered out as non-chat.
    assert [m.id for m in models] == ["qwen3-8b", "nomic-embed"]
    caps = models[0].capabilities
    assert caps is not None
    assert caps.context_window is not None and caps.context_window.value == 32768
    assert caps.features.value & ai.Feature.TOOLS
    assert caps.features.value & ai.Feature.REASONING
    assert caps.local is not None
    assert caps.local.quantization == "Q4_K_M"
    assert caps.local.parameter_size == "8B"
    assert caps.operations is not None
    assert caps.operations.value == frozenset({"generation"})

    embed_caps = models[1].capabilities
    assert embed_caps is not None
    assert embed_caps.operations is not None
    assert embed_caps.operations.value == frozenset({"embedding"})
    assert embed_caps.operations.provenance == "discovered"
    assert embed_caps.features.value == ai.Feature(0)  # no chat features invented


async def test_discovery_falls_back_to_the_openai_listing() -> None:
    """Older builds have no native API; ids alone beat failing outright."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/v1/models":
            return httpx2.Response(404, json={"error": "not found"})
        return httpx2.Response(200, json={"data": [{"id": "legacy-model"}]})

    adapter = _lm_studio(handler)
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    assert [m.id for m in models] == ["legacy-model"]


async def test_loaded_models_reports_residency() -> None:
    adapter = _lm_studio(lambda r: httpx2.Response(200, json=_NATIVE_LISTING))
    try:
        loaded = await adapter.loaded_models()
    finally:
        await adapter.aclose()

    assert loaded == {"qwen3-8b": 1}, "only resident models are reported"


async def test_health_names_the_loaded_model() -> None:
    adapter = _lm_studio(lambda r: httpx2.Response(200, json=_NATIVE_LISTING))
    try:
        health = await adapter.health()
    finally:
        await adapter.aclose()

    assert health.ok is True
    assert "qwen3-8b" in health.detail


async def test_health_says_so_when_nothing_is_loaded() -> None:
    listing = {"models": [{"key": "qwen3-8b", "type": "llm", "loaded_instances": []}]}
    adapter = _lm_studio(lambda r: httpx2.Response(200, json=listing))
    try:
        health = await adapter.health()
    finally:
        await adapter.aclose()

    assert health.ok is True
    assert "no model loaded" in health.detail


async def test_generation_uses_the_openai_dialect() -> None:
    """Chat is the shared dialect; only discovery is native."""
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "local answer"}, "finish_reason": "stop"}
        ]
    }
    async with _client("lm-studio", lambda r: httpx2.Response(200, json=body)) as client:
        result = await client.generate("hi", target="lm-studio:qwen3-8b")

    assert result.text == "local answer"


def test_a_bare_hostname_expands_to_the_conventional_port() -> None:
    registry = ai.default_registry
    shorthand = registry.get("lm-studio").setup.host_shorthand
    assert shorthand is not None
    assert shorthand.expand("gpu-box") == "http://gpu-box:1234"
    assert shorthand.expand("http://elsewhere:9999") == "http://elsewhere:9999"


def test_reasoning_effort_maps_to_the_native_levels() -> None:
    translate = ai.default_registry.get("lm-studio").reasoning_translator
    assert translate("high") == {"reasoning": "high"}
    assert translate("minimal") == {"reasoning": "low"}, "minimal reduces, never disables"
    assert translate(None) == {}


@pytest.mark.parametrize("provider_id", ["cohere", "lm-studio", "bedrock", "vertex"])
def test_every_new_provider_is_registered(provider_id: str) -> None:
    descriptor = ai.default_registry.get(provider_id)
    assert descriptor.display_name
    assert descriptor.setup.fields, "a config UI needs something to render"


# ---- conformance ---------------------------------------------------------------------

PROBE_ANSWER = json.dumps({"answer": "ok"})


def _cohere_server(scenario: str) -> Any:
    """Program a Cohere fake for one conformance scenario."""
    ok = {
        "finish_reason": "COMPLETE",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello from Cohere."}],
        },
        "usage": {"tokens": {"input_tokens": 11, "output_tokens": 7}},
    }
    state = {"calls": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/v1/models"):
            return httpx2.Response(
                200,
                json={
                    "models": [
                        {"name": "command-a", "endpoints": ["chat"], "context_length": 256000}
                    ]
                },
            )
        calls = state["calls"]
        state["calls"] += 1
        streaming = json.loads(request.content or b"{}").get("stream")

        if scenario == "auth_error":
            return httpx2.Response(401, json={"message": "invalid key"})
        if scenario == "rate_limited" and calls == 0:
            return httpx2.Response(
                429, json={"message": "slow down"}, headers={"retry-after": "0"}
            )

        body = dict(ok)
        if scenario == "tools":
            body = {
                "finish_reason": "TOOL_CALL",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "tool_calls": [
                        {
                            "id": "c0",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"key": "alpha"}'},
                        }
                    ],
                },
                "usage": {"tokens": {"input_tokens": 11, "output_tokens": 7}},
            }
        elif scenario == "structured":
            body = {
                **ok,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": PROBE_ANSWER}],
                },
            }
        elif scenario == "repair":
            text = '{"wrong": true}' if calls == 0 else PROBE_ANSWER
            body = {
                **ok,
                "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
            }
        elif scenario == "oversized":
            body = {
                **ok,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "x" * 20_000}],
                },
            }
        elif scenario == "odd_finish":
            body = {**ok, "finish_reason": "SOMETHING_NEW"}

        if not streaming:
            return httpx2.Response(200, json=body)

        message = body["message"]
        events: list[dict[str, Any]] = [
            {"type": "message-start", "delta": {"message": {"role": "assistant"}}}
        ]
        for block in message.get("content", []):
            events.append(
                {
                    "type": "content-delta",
                    "index": 0,
                    "delta": {"message": {"content": {"text": block["text"]}}},
                }
            )
        for index, call in enumerate(message.get("tool_calls", [])):
            events.append(
                {
                    "type": "tool-call-start",
                    "index": index,
                    "delta": {
                        "message": {
                            "tool_calls": {
                                "id": call["id"],
                                "type": "function",
                                "function": {"name": call["function"]["name"]},
                            }
                        }
                    },
                }
            )
            events.append(
                {
                    "type": "tool-call-delta",
                    "index": index,
                    "delta": {
                        "message": {
                            "tool_calls": {
                                "function": {"arguments": call["function"]["arguments"]}
                            }
                        }
                    },
                }
            )
        events.append(
            {
                "type": "message-end",
                "delta": {"finish_reason": body["finish_reason"], "usage": body.get("usage", {})},
            }
        )
        return httpx2.Response(
            200,
            content=sse_lines(events, done=False),
            headers={"content-type": "text/event-stream"},
        )

    return handler


async def _build_cohere_client(scenario: str) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "cohere",
                api_key="co-key",
                transport=httpx2.MockTransport(_cohere_server(scenario)),
            )
        ],
        route=ai.Route(
            targets=("cohere:command-a",), retry=ai.Retry(max_attempts=2, backoff_base_s=0.0)
        ),
    )


HARNESS = ConformanceHarness(
    provider_id="cohere",
    model="command-a",
    build_client=_build_cohere_client,
    # The fake has no thinking channel of its own; the dialect test above covers it.
    supports=Capabilities(reasoning=False),
)


async def test_cohere_conformance() -> None:
    results = await run_conformance(HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"


def _lm_studio_server(scenario: str) -> Any:
    """Program an LM Studio fake: native discovery plus the compatible chat endpoint."""
    from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

    if scenario == "tools":
        inner = FakeOpenAIServer(
            FakeResponse(
                text="",
                tool_calls=(("call_0", "lookup", '{"key": "alpha"}'),),
                finish_reason="tool_calls",
            )
        )
    elif scenario == "structured":
        inner = FakeOpenAIServer(FakeResponse(text=PROBE_ANSWER))
    elif scenario == "repair":
        inner = FakeOpenAIServer(
            [FakeResponse(text='{"wrong": true}'), FakeResponse(text=PROBE_ANSWER)]
        )
    elif scenario == "auth_error":
        inner = FakeOpenAIServer(FakeResponse(status=401, error_message="invalid token"))
    elif scenario == "rate_limited":
        inner = FakeOpenAIServer(
            [
                FakeResponse(status=429, error_message="busy", headers={"retry-after": "0"}),
                FakeResponse(text="recovered"),
            ]
        )
    elif scenario == "oversized":
        inner = FakeOpenAIServer(FakeResponse(text="x" * 20_000))
    elif scenario == "odd_finish":
        inner = FakeOpenAIServer(FakeResponse(text="hello", finish_reason="model_decided"))
    else:
        inner = FakeOpenAIServer(FakeResponse(text="Hello from LM Studio."))

    compat = inner.transport()

    def handler(request: httpx2.Request) -> httpx2.Response:
        # The native listing sits beside /v1; everything else is the shared dialect.
        if request.url.path == "/api/v1/models":
            return httpx2.Response(
                200,
                json={
                    "models": [
                        {
                            "key": "fake-model-small",
                            "type": "llm",
                            "max_context_length": 32768,
                            "loaded_instances": [{"id": "i1"}],
                        }
                    ]
                },
            )
        return compat.handler(request)

    return handler


async def _build_lm_studio_client(scenario: str) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "lm-studio",
                base_url="http://127.0.0.1:1234/v1",
                transport=httpx2.MockTransport(_lm_studio_server(scenario)),
            )
        ],
        route=ai.Route(
            targets=("lm-studio:fake-model-small",),
            retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
        ),
    )


LM_STUDIO_HARNESS = ConformanceHarness(
    provider_id="lm-studio",
    model="fake-model-small",
    build_client=_build_lm_studio_client,
    # The shared fake has no reasoning channel; the dialect tests above cover the
    # native reasoning translation.
    supports=Capabilities(reasoning=False),
)


async def test_lm_studio_conformance() -> None:
    results = await run_conformance(LM_STUDIO_HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"
