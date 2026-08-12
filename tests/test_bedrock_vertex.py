"""The Bedrock and Vertex adapters: Converse framing, cloud auth, and addressing."""

from __future__ import annotations

import binascii
import json
import struct
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.errors import ConfigError
from anyinfer.providers.base import AdapterFinal, EmbeddingWireRequest, ProviderConfig, WireRequest
from anyinfer.providers.bedrock import BedrockAdapter
from anyinfer.providers.vertex import VertexAdapter
from anyinfer.types.requests import Sampling, ToolSpec

AWS_OPTIONS = {
    "region": "us-east-1",
    "aws_access_key_id": "AKIDEXAMPLE",
    "aws_secret_access_key": "secret",
}


def _bedrock(handler: Any, **options: Any) -> BedrockAdapter:
    return BedrockAdapter(
        ProviderConfig(
            provider_id="bedrock",
            options={**AWS_OPTIONS, **options},
            transport=httpx2.MockTransport(handler),
        )
    )


def _bedrock_client(handler: Any, **settings: Any) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "bedrock",
                options={**AWS_OPTIONS, **settings.pop("options", {})},
                transport=httpx2.MockTransport(handler),
                **settings,
            )
        ]
    )


def _frame(event_type: str, payload: dict[str, Any]) -> bytes:
    """Build one vnd.amazon.eventstream frame."""
    body = json.dumps(payload).encode("utf-8")
    headers = b""
    for name, value in ((":event-type", event_type), (":message-type", "event")):
        encoded = value.encode("utf-8")
        headers += bytes([len(name)]) + name.encode("ascii")
        headers += bytes([7]) + struct.pack(">H", len(encoded)) + encoded
    total = 12 + len(headers) + len(body) + 4
    prelude = struct.pack(">II", total, len(headers))
    prelude += struct.pack(">I", binascii.crc32(prelude) & 0xFFFFFFFF)
    frame = prelude + headers + body
    return frame + struct.pack(">I", binascii.crc32(frame) & 0xFFFFFFFF)


def _converse_stream(*frames: bytes) -> httpx2.Response:
    return httpx2.Response(
        200,
        content=b"".join(frames),
        headers={"content-type": "application/vnd.amazon.eventstream"},
    )


def _dual(buffered: dict[str, Any], *frames: bytes) -> Any:
    """Answer converse-stream with binary frames and converse with JSON.

    `generate()` streams by default, so a fake that only serves one path would test the
    wrong one.
    """

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("converse-stream"):
            return _converse_stream(*frames)
        return httpx2.Response(200, json=buffered)

    return handler


_TEXT_RESPONSE = {
    "output": {"message": {"role": "assistant", "content": [{"text": "Hello."}]}},
    "stopReason": "end_turn",
    "usage": {"inputTokens": 12, "outputTokens": 5, "totalTokens": 17},
    "metrics": {"latencyMs": 340},
}


# ---- bedrock: auth -------------------------------------------------------------------


async def test_requests_are_sigv4_signed() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_TEXT_RESPONSE)

    adapter = _bedrock(handler)
    try:
        async for _ in adapter.generate(
            WireRequest(model="amazon.nova-pro-v1:0", messages=(ai.user("hi"),), stream=False)
        ):
            pass
    finally:
        await adapter.aclose()

    auth = seen[0].headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 ")
    assert "/us-east-1/bedrock/aws4_request" in auth
    assert "x-amz-date" in seen[0].headers


async def test_a_bedrock_api_key_replaces_signing() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_TEXT_RESPONSE)

    adapter = BedrockAdapter(
        ProviderConfig(
            provider_id="bedrock",
            api_key="bedrock-api-key",
            options={"region": "us-east-1"},
            transport=httpx2.MockTransport(handler),
        )
    )
    try:
        async for _ in adapter.generate(
            WireRequest(model="m", messages=(ai.user("hi"),), stream=False)
        ):
            pass
    finally:
        await adapter.aclose()

    assert seen[0].headers["authorization"] == "Bearer bedrock-api-key"
    assert "x-amz-date" not in seen[0].headers, "a bearer key is not signed"


def test_no_credentials_is_actionable(monkeypatch) -> None:
    monkeypatch.setattr(
        "anyinfer.providers.cloud_auth._aws_credentials_from_boto3", lambda options: None
    )
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    with pytest.raises(ConfigError) as excinfo:
        BedrockAdapter(ProviderConfig(provider_id="bedrock", options={}))

    assert excinfo.value.hint is not None
    assert "Bedrock API key" in excinfo.value.hint


async def test_aws_secret_access_key_is_resolved_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AWS credentials ride in options, and must still go through the resolver.

    Unresolved, ``env://VAR`` would be signed with as the literal string — every request
    would 403 with nothing to explain it, and a literal key would never be registered
    for redaction, so it could surface in a log line.
    """
    from anyinfer._client.providers import AdapterPool
    from anyinfer.redaction import redact

    monkeypatch.setenv("DEMO_AWS_SECRET", "a-real-aws-secret")
    pool = AdapterPool(
        [
            ai.ProviderSettings.of(
                "bedrock",
                options={
                    "aws_access_key_id": "AKIAEXAMPLE",
                    "aws_secret_access_key": "env://DEMO_AWS_SECRET",
                },
            )
        ],
        registry=ai.default_registry,
    )
    adapter = await pool.get("bedrock")
    assert isinstance(adapter, BedrockAdapter)

    credentials = adapter._credentials
    assert credentials is not None
    assert credentials.secret_access_key == "a-real-aws-secret"
    # An access key id is an identifier, not a secret: resolving it would corrupt any
    # value that merely looked like a reference.
    assert credentials.access_key_id == "AKIAEXAMPLE"
    assert "a-real-aws-secret" not in redact("logged: a-real-aws-secret")


def test_bedrock_declares_the_credentials_its_adapter_reads() -> None:
    """An option the adapter honours but never declares is invisible and unresolved."""
    from anyinfer.providers.bedrock import descriptor

    declared = {f.key: f.kind for f in descriptor.setup.fields}
    assert declared["aws_secret_access_key"] == "secret"
    assert declared["aws_session_token"] == "secret"
    # Not secrets — masking them in a UI would help nobody and resolving them would break
    # any literal value shaped like a reference.
    assert declared["aws_access_key_id"] == "text"
    assert declared["profile"] == "host-profile"


# ---- bedrock: the Converse shape -----------------------------------------------------


async def test_system_prompts_become_top_level_blocks() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        if request.url.path.endswith("converse-stream"):
            return _converse_stream(
                _frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "Hello."}}),
                _frame("messageStop", {"stopReason": "end_turn"}),
                _frame("metadata", {"usage": {"inputTokens": 12, "outputTokens": 5}}),
            )
        return httpx2.Response(200, json=_TEXT_RESPONSE)

    async with _bedrock_client(handler) as client:
        await client.generate(
            [ai.system("Be terse."), ai.user("hi")], target="bedrock:amazon.nova-pro-v1:0"
        )

    assert seen[0]["system"] == [{"text": "Be terse."}]
    assert [m["role"] for m in seen[0]["messages"]] == ["user"]


async def test_sampling_lives_under_inference_config() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        if request.url.path.endswith("converse-stream"):
            return _converse_stream(
                _frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "Hello."}}),
                _frame("messageStop", {"stopReason": "end_turn"}),
                _frame("metadata", {"usage": {"inputTokens": 12, "outputTokens": 5}}),
            )
        return httpx2.Response(200, json=_TEXT_RESPONSE)

    async with _bedrock_client(handler) as client:
        await client.generate(
            "hi",
            target="bedrock:m",
            sampling=Sampling(temperature=0.2, top_p=0.9, max_output_tokens=64, stop=("X",)),
        )

    config = seen[0]["inferenceConfig"]
    assert config == {
        "temperature": 0.2,
        "topP": 0.9,
        "maxTokens": 64,
        "stopSequences": ["X"],
    }
    assert "temperature" not in seen[0], "sampling is nested, not top-level"


async def test_a_buffered_response_yields_text_usage_and_latency() -> None:
    adapter = _bedrock(lambda r: httpx2.Response(200, json=_TEXT_RESPONSE))
    try:
        events = [
            e
            async for e in adapter.generate(
                WireRequest(model="m", messages=(ai.user("hi"),), stream=False)
            )
        ]
    finally:
        await adapter.aclose()

    text = "".join(e.text for e in events if isinstance(e, ai.TextDelta))
    final = events[-1]
    assert text == "Hello."
    assert isinstance(final, AdapterFinal)
    assert final.finish_reason == "stop"
    assert final.usage is not None and final.usage.input_tokens == 12
    assert final.phases["provider_latency"] == 340.0


async def test_tool_results_ride_on_a_user_turn() -> None:
    from anyinfer.types.messages import Message, ToolCall, ToolResult

    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        if request.url.path.endswith("converse-stream"):
            return _converse_stream(
                _frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "Hello."}}),
                _frame("messageStop", {"stopReason": "end_turn"}),
                _frame("metadata", {"usage": {"inputTokens": 12, "outputTokens": 5}}),
            )
        return httpx2.Response(200, json=_TEXT_RESPONSE)

    conversation = [
        ai.user("look it up"),
        Message(
            role="assistant",
            content=(ToolCall(id="tu_1", name="lookup", arguments={"key": "a"}),),
        ),
        Message(role="tool", content=(ToolResult(call_id="tu_1", content="found"),)),
    ]
    async with _bedrock_client(handler) as client:
        await client.generate(conversation, target="bedrock:m")

    messages = seen[0]["messages"]
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"][0]["toolUse"]["toolUseId"] == "tu_1"
    assert messages[2]["role"] == "user", "tool results are a user turn in Converse"
    assert messages[2]["content"][0]["toolResult"]["toolUseId"] == "tu_1"


async def test_a_schema_becomes_a_forced_tool() -> None:
    seen: list[dict[str, Any]] = []
    answer = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": "t1", "name": "response", "input": {"answer": "ok"}}}
                ],
            }
        },
        "stopReason": "tool_use",
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=answer)

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    async with _bedrock_client(handler) as client:
        result = await client.generate("answer", target="bedrock:m", schema=schema)

    config = seen[0]["toolConfig"]
    assert config["toolChoice"] == {"tool": {"name": "response"}}
    assert config["tools"][0]["toolSpec"]["inputSchema"]["json"]["required"] == ["answer"]
    assert result.structured == {"answer": "ok"}


async def test_reasoning_effort_becomes_an_additional_model_field() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        if request.url.path.endswith("converse-stream"):
            return _converse_stream(
                _frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "Hello."}}),
                _frame("messageStop", {"stopReason": "end_turn"}),
                _frame("metadata", {"usage": {"inputTokens": 12, "outputTokens": 5}}),
            )
        return httpx2.Response(200, json=_TEXT_RESPONSE)

    async with _bedrock_client(handler) as client:
        await client.generate("hi", target="bedrock:m", reasoning="high")

    thinking = seen[0]["additionalModelRequestFields"]["thinking"]
    assert thinking == {"type": "enabled", "budget_tokens": 16384}


# ---- bedrock: the binary stream ------------------------------------------------------


async def test_streaming_decodes_binary_frames() -> None:
    frames = (
        _frame("messageStart", {"role": "assistant"}),
        _frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "Hello"}}),
        _frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": " there"}}),
        _frame("contentBlockStop", {"contentBlockIndex": 0}),
        _frame("messageStop", {"stopReason": "end_turn"}),
        _frame(
            "metadata",
            {"usage": {"inputTokens": 9, "outputTokens": 4, "totalTokens": 13}},
        ),
    )

    async with _bedrock_client(lambda r: _converse_stream(*frames)) as client:
        stream = client.stream("hi", target="bedrock:m")
        deltas = [e.text async for e in stream if isinstance(e, ai.TextDelta)]
        result = stream.result

    assert "".join(deltas) == "Hello there"
    assert result.text == "Hello there"
    assert result.usage.input_tokens == 9, "usage arrives only in the metadata frame"
    assert result.usage.output_tokens == 4


async def test_streaming_tool_calls_reassemble_by_block_index() -> None:
    frames = (
        _frame("messageStart", {"role": "assistant"}),
        _frame(
            "contentBlockStart",
            {"contentBlockIndex": 0, "start": {"toolUse": {"toolUseId": "t1", "name": "lookup"}}},
        ),
        _frame(
            "contentBlockDelta",
            {"contentBlockIndex": 0, "delta": {"toolUse": {"input": '{"key":'}}},
        ),
        _frame(
            "contentBlockDelta",
            {"contentBlockIndex": 0, "delta": {"toolUse": {"input": '"alpha"}'}}},
        ),
        _frame("messageStop", {"stopReason": "tool_use"}),
        _frame("metadata", {"usage": {"inputTokens": 5, "outputTokens": 2}}),
    )

    tool = ToolSpec(name="lookup", description="d", parameters={"type": "object"})
    async with _bedrock_client(lambda r: _converse_stream(*frames)) as client:
        stream = client.stream("look it up", target="bedrock:m", tools=[tool])
        async for _ in stream:
            pass
        result = stream.result

    assert result.finish_reason == "tool_calls"
    call = result.tool_calls[0]
    assert call.name == "lookup"
    assert call.arguments == {"key": "alpha"}


async def test_reasoning_frames_are_a_separate_channel() -> None:
    frames = (
        _frame(
            "contentBlockDelta",
            {"contentBlockIndex": 0, "delta": {"reasoningContent": {"text": "Let me think."}}},
        ),
        _frame("contentBlockDelta", {"contentBlockIndex": 1, "delta": {"text": "42"}}),
        _frame("messageStop", {"stopReason": "end_turn"}),
        _frame("metadata", {"usage": {"inputTokens": 3, "outputTokens": 1}}),
    )

    async with _bedrock_client(lambda r: _converse_stream(*frames)) as client:
        stream = client.stream("hard", target="bedrock:m")
        events = [e async for e in stream]
        result = stream.result

    reasoning = [e for e in events if isinstance(e, ai.ReasoningDelta)]
    assert reasoning and reasoning[0].text == "Let me think."
    assert result.text == "42", "reasoning stays out of the answer"


async def test_an_in_stream_throttle_maps_to_a_rate_limit_error() -> None:
    body = json.dumps({"message": "slow down"}).encode()
    headers = b""
    for name, value in (
        (":event-type", "throttlingException"),
        (":message-type", "exception"),
    ):
        encoded = value.encode()
        headers += bytes([len(name)]) + name.encode()
        headers += bytes([7]) + struct.pack(">H", len(encoded)) + encoded
    total = 12 + len(headers) + len(body) + 4
    prelude = struct.pack(">II", total, len(headers))
    prelude += struct.pack(">I", binascii.crc32(prelude) & 0xFFFFFFFF)
    frame = prelude + headers + body
    frame += struct.pack(">I", binascii.crc32(frame) & 0xFFFFFFFF)

    async with _bedrock_client(lambda r: _converse_stream(frame)) as client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            stream = client.stream(
                "hi",
                route=ai.Route(targets=("bedrock:m",), retry=ai.Retry(max_attempts=1)),
            )
            async for _ in stream:
                pass

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.type_name == "RateLimitError"
    assert error.retryable is True


async def test_health_does_not_spend_a_generation() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("health must not issue a request")

    adapter = _bedrock(handler)
    try:
        health = await adapter.health()
    finally:
        await adapter.aclose()

    assert health.ok is True
    assert "us-east-1" in health.detail


# ---- bedrock: embeddings ---------------------------------------------------------------

_TITAN_RESPONSE = {
    "embedding": [0.1, 0.2, 0.3],
    "inputTextTokenCount": 5,
}


async def test_embeds_against_invoke_model_not_converse() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_TITAN_RESPONSE)

    adapter = _bedrock(handler)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="amazon.titan-embed-text-v2:0", inputs=("hi",))
        )
    finally:
        await adapter.aclose()

    assert seen[0].url.path == "/model/amazon.titan-embed-text-v2:0/invoke"
    body = json.loads(seen[0].content)
    assert body == {"inputText": "hi"}
    assert result.vectors == ((0.1, 0.2, 0.3),)
    assert result.usage is not None
    assert result.usage.input_tokens == 5


async def test_embed_forwards_dimensions() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_TITAN_RESPONSE)

    adapter = _bedrock(handler)
    try:
        await adapter.embed(
            EmbeddingWireRequest(
                model="amazon.titan-embed-text-v2:0", inputs=("hi",), dimensions=256
            )
        )
    finally:
        await adapter.aclose()

    body = json.loads(seen[0].content)
    assert body == {"inputText": "hi", "dimensions": 256}


async def test_embed_issues_one_invoke_per_input_and_sums_tokens() -> None:
    """Titan has no batch field — one inputText per call is the only shape it accepts."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_TITAN_RESPONSE)

    adapter = _bedrock(handler)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(
                model="amazon.titan-embed-text-v2:0", inputs=("hi", "there")
            )
        )
    finally:
        await adapter.aclose()

    assert len(seen) == 2
    assert result.vectors == ((0.1, 0.2, 0.3), (0.1, 0.2, 0.3))
    assert result.usage is not None
    assert result.usage.input_tokens == 10


async def test_embed_rejects_a_response_over_the_byte_cap() -> None:
    from anyinfer.errors import StreamProtocolError

    adapter = _bedrock(
        lambda request: httpx2.Response(
            200, json={"embedding": [0.1], "padding": "x" * 200}
        )
    )
    try:
        with pytest.raises(StreamProtocolError, match="max_response_bytes"):
            await adapter.embed(
                EmbeddingWireRequest(
                    model="amazon.titan-embed-text-v2:0",
                    inputs=("hi",),
                    max_response_bytes=32,
                )
            )
    finally:
        await adapter.aclose()


# ---- vertex --------------------------------------------------------------------------


def _vertex(handler: Any, **options: Any) -> VertexAdapter:
    return VertexAdapter(
        ProviderConfig(
            provider_id="vertex",
            api_key="ya29.test-token",
            options={"project": "my-project", "location": "global", **options},
            transport=httpx2.MockTransport(handler),
        )
    )


_GEMINI_RESPONSE = {
    "candidates": [
        {
            "content": {"role": "model", "parts": [{"text": "Hi from Vertex."}]},
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 4},
}


def test_a_missing_project_is_actionable() -> None:
    with pytest.raises(ConfigError) as excinfo:
        VertexAdapter(ProviderConfig(provider_id="vertex", api_key="t", options={}))
    assert excinfo.value.hint is not None
    assert "project" in excinfo.value.hint


async def test_the_path_carries_project_and_location() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_GEMINI_RESPONSE)

    adapter = _vertex(handler)
    try:
        async for _ in adapter.generate(
            WireRequest(model="gemini-2.5-flash", messages=(ai.user("hi"),), stream=False)
        ):
            pass
    finally:
        await adapter.aclose()

    path = seen[0].url.path
    assert "/projects/my-project/locations/global/publishers/google/models/" in path
    assert path.endswith("gemini-2.5-flash:generateContent")


async def test_requests_carry_an_oauth_bearer_token() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_GEMINI_RESPONSE)

    adapter = _vertex(handler)
    try:
        async for _ in adapter.generate(
            WireRequest(model="gemini-2.5-flash", messages=(ai.user("hi"),), stream=False)
        ):
            pass
    finally:
        await adapter.aclose()

    assert seen[0].headers["authorization"] == "Bearer ya29.test-token"
    assert "x-goog-api-key" not in seen[0].headers, "Vertex is not API-key authenticated"


async def test_the_gemini_protocol_translation_is_reused() -> None:
    """Vertex changes addressing and auth, not the wire shape."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=_GEMINI_RESPONSE)

    adapter = _vertex(handler)
    try:
        events = [
            e
            async for e in adapter.generate(
                WireRequest(
                    model="gemini-2.5-flash",
                    messages=(ai.system("Be terse."), ai.user("hi")),
                    sampling=Sampling(temperature=0.3),
                    stream=False,
                )
            )
        ]
    finally:
        await adapter.aclose()

    body = seen[0]
    assert body["systemInstruction"]["parts"][0]["text"] == "Be terse."
    assert body["generationConfig"]["temperature"] == 0.3
    text = "".join(e.text for e in events if isinstance(e, ai.TextDelta))
    assert text == "Hi from Vertex."


def test_a_regional_location_uses_a_regional_host() -> None:
    adapter = _vertex(lambda r: httpx2.Response(200, json={}), location="us-central1")
    assert "us-central1-aiplatform.googleapis.com" in str(adapter._client.base_url)


async def test_discovery_reports_nothing_rather_than_guessing() -> None:
    """Vertex has no comparable listing endpoint; an invented one would be a lie."""
    adapter = _vertex(lambda r: httpx2.Response(200, json={}))
    try:
        assert await adapter.list_models() == []
    finally:
        await adapter.aclose()


async def test_health_reports_the_project_without_generating() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("health must not issue a request")

    adapter = _vertex(handler)
    try:
        health = await adapter.health()
    finally:
        await adapter.aclose()

    assert health.ok is True
    assert "my-project/global" in health.detail


_PREDICT_RESPONSE = {
    "predictions": [
        {
            "embeddings": {
                "values": [0.1, 0.2, 0.3],
                "statistics": {"truncated": False, "token_count": 4},
            }
        }
    ]
}


async def test_embeds_against_the_predict_endpoint_not_batch_embed_contents() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_PREDICT_RESPONSE)

    adapter = _vertex(handler)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="gemini-embedding-001", inputs=("hi",))
        )
    finally:
        await adapter.aclose()

    assert seen[0].url.path.endswith("gemini-embedding-001:predict")
    body = json.loads(seen[0].content)
    assert body["instances"] == [{"content": "hi"}]
    assert result.vectors == ((0.1, 0.2, 0.3),)
    assert result.usage is not None
    assert result.usage.input_tokens == 4


async def test_embed_maps_input_type_to_task_type() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_PREDICT_RESPONSE)

    adapter = _vertex(handler)
    try:
        await adapter.embed(
            EmbeddingWireRequest(
                model="gemini-embedding-001", inputs=("hi",), input_type="document"
            )
        )
    finally:
        await adapter.aclose()

    body = json.loads(seen[0].content)
    assert body["instances"][0]["task_type"] == "RETRIEVAL_DOCUMENT"


_PREDICT_RESPONSE_TWO = {
    "predictions": [
        {"embeddings": {"values": [0.1, 0.2], "statistics": {"token_count": 1}}},
        {"embeddings": {"values": [0.3, 0.4], "statistics": {"token_count": 1}}},
    ]
}


async def test_embed_forwards_output_dimensionality() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_PREDICT_RESPONSE_TWO)

    adapter = _vertex(handler)
    try:
        await adapter.embed(
            EmbeddingWireRequest(
                model="text-embedding-005", inputs=("hi", "there"), dimensions=256
            )
        )
    finally:
        await adapter.aclose()

    body = json.loads(seen[0].content)
    assert body["instances"] == [{"content": "hi"}, {"content": "there"}]
    assert body["parameters"] == {"outputDimensionality": 256}


async def test_vertex_embed_rejects_a_response_over_the_byte_cap() -> None:
    from anyinfer.errors import StreamProtocolError

    adapter = _vertex(
        lambda request: httpx2.Response(
            200,
            json={
                "predictions": [{"embeddings": {"values": [0.1]}}],
                "padding": "x" * 200,
            },
        )
    )
    try:
        with pytest.raises(StreamProtocolError, match="max_response_bytes"):
            await adapter.embed(
                EmbeddingWireRequest(
                    model="gemini-embedding-001", inputs=("hi",), max_response_bytes=32
                )
            )
    finally:
        await adapter.aclose()
