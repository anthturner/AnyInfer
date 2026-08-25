"""The Ollama adapter: NDJSON framing, grammar schemas, phase timings, discovery."""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer.providers.base import ProviderConfig
from anyinfer.providers.ollama import OllamaAdapter
from anyinfer.testing.conformance import (
    CONFORMANCE_CASES,
    Capabilities,
    ConformanceHarness,
    run_conformance,
)
from anyinfer.testing.fakes import FakeOllamaServer, FakeResponse

PROBE_ANSWER = json.dumps({"answer": "ok"})


def make_ollama_client(server: FakeOllamaServer, **kwargs: object) -> ai.AsyncClient:
    """Build a client wired to a fake Ollama server."""
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama",
                base_url="http://127.0.0.1:11434",
                transport=server.transport(),
            )
        ],
        **kwargs,  # type: ignore[arg-type]
    )


# ---- generation ----------------------------------------------------------------------


async def test_streaming_ndjson_generation() -> None:
    server = FakeOllamaServer(FakeResponse(text="Hello from Ollama."))
    async with make_ollama_client(server) as client:
        stream = client.stream("hi", target="ollama:qwen3:8b")
        deltas = [e.text async for e in stream if isinstance(e, ai.TextDelta)]
        result = stream.result

    assert "".join(deltas) == "Hello from Ollama."
    assert result.text == "Hello from Ollama."


async def test_model_ids_with_colons_reach_the_wire_intact() -> None:
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with make_ollama_client(server) as client:
        await client.generate("hi", target="ollama:qwen3:8b")

    assert server.requests[0]["model"] == "qwen3:8b"


async def test_phase_timings_are_converted_from_nanoseconds() -> None:
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with make_ollama_client(server) as client:
        result = await client.generate("hi", target="ollama:qwen3:8b")

    phases = result.timing.phases
    assert phases["model_load_ms"] == pytest.approx(300.0)
    assert phases["prefill_ms"] == pytest.approx(200.0)
    assert phases["decode_ms"] == pytest.approx(1000.0)
    assert phases["provider_total_ms"] == pytest.approx(1500.0)


async def test_usage_comes_from_the_terminal_object() -> None:
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with make_ollama_client(server) as client:
        result = await client.generate("hi", target="ollama:qwen3:8b")

    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7
    assert result.usage.total_tokens == 18


async def test_reasoning_is_a_separate_channel_from_the_answer() -> None:
    """``thinking`` starts the TTFT clock but must not contaminate the answer text."""
    import httpx2

    from anyinfer.testing.fakes import ndjson_lines

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/api/chat"):
            return httpx2.Response(
                200,
                content=ndjson_lines(
                    [
                        {
                            "message": {"role": "assistant", "thinking": "Let me think..."},
                            "done": False,
                        },
                        {"message": {"role": "assistant", "content": "42"}, "done": False},
                        {
                            "message": {"role": "assistant", "content": ""},
                            "done": True,
                            "done_reason": "stop",
                            "eval_count": 3,
                        },
                    ]
                ),
                headers={"content-type": "application/x-ndjson"},
            )
        return httpx2.Response(404, json={"error": "nope"})

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama",
                base_url="http://127.0.0.1:11434",
                transport=httpx2.MockTransport(handler),
            )
        ]
    )
    async with client:
        stream = client.stream("hi", target="ollama:qwen3:8b")
        events = [e async for e in stream]
        result = stream.result

    reasoning = [e for e in events if isinstance(e, ai.ReasoningDelta)]
    assert reasoning and reasoning[0].text == "Let me think..."
    assert result.text == "42", "thinking must be excluded from the answer"
    assert result.timing.first_token_ms is not None, "thinking still starts the clock"


# ---- structured output ---------------------------------------------------------------


async def test_schema_is_sent_as_format_and_injected_into_the_prompt() -> None:
    """Ollama's ``format`` constrains decoding but does not tell the model the shape.

    Without prompt injection the model emits schema-shaped nonsense, so the core must do
    both.
    """
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    server = FakeOllamaServer(FakeResponse(text=PROBE_ANSWER))
    async with make_ollama_client(server) as client:
        result = await client.generate("q", target="ollama:qwen3:8b", schema=schema)

    body = server.requests[0]
    assert body["format"]["type"] == "object", "the schema must go on the wire as `format`"
    assert result.structured_mechanism == "grammar"

    system_messages = [m for m in body["messages"] if m["role"] == "system"]
    assert system_messages, "the schema must also be described in the prompt"
    assert "Respond with ONLY a JSON value" in system_messages[0]["content"]
    assert result.structured == {"answer": "ok"}


async def test_grammar_hostile_constraints_are_stripped_from_the_wire_schema() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 2, "maxLength": 40},
            "tags": {"type": "array", "maxItems": 9999},
        },
        "required": ["name"],
    }
    server = FakeOllamaServer(FakeResponse(text=json.dumps({"name": "Ada"})))
    async with make_ollama_client(server) as client:
        result = await client.generate("q", target="ollama:qwen3:8b", schema=schema)

    wire_schema = server.requests[0]["format"]
    assert "minLength" not in wire_schema["properties"]["name"]
    assert "maxItems" not in wire_schema["properties"]["tags"]
    assert result.structured == {"name": "Ada"}, "the original schema still validates"


# ---- sampling and options ------------------------------------------------------------


async def test_sampling_maps_onto_the_options_block() -> None:
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with make_ollama_client(server) as client:
        await client.generate(
            "hi",
            target="ollama:qwen3:8b",
            sampling=ai.Sampling(temperature=0.4, top_p=0.8, max_output_tokens=256, stop=("END",)),
        )

    options = server.requests[0]["options"]
    assert options == {
        "temperature": 0.4,
        "top_p": 0.8,
        "num_predict": 256,
        "stop": ["END"],
    }


async def test_unset_sampling_sends_no_options() -> None:
    """An unset knob must be omitted, never defaulted to an invented value."""
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with make_ollama_client(server) as client:
        await client.generate("hi", target="ollama:qwen3:8b")

    assert "options" not in server.requests[0]


async def test_reasoning_effort_maps_to_think() -> None:
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with make_ollama_client(server) as client:
        await client.generate("hi", target="ollama:qwen3:8b", reasoning="high")
        await client.generate("hi", target="ollama:qwen3:8b", reasoning="minimal")

    assert server.requests[0]["think"] == "high"
    assert server.requests[1]["think"] is False


async def test_provider_options_pass_through_verbatim() -> None:
    server = FakeOllamaServer(FakeResponse(text="ok"))
    async with make_ollama_client(server) as client:
        await client.generate(
            "hi",
            target="ollama:qwen3:8b",
            provider_options={"ollama": {"keep_alive": "10m"}},
        )

    assert server.requests[0]["keep_alive"] == "10m"


# ---- tools ---------------------------------------------------------------------------


async def test_tool_calls_are_surfaced() -> None:
    server = FakeOllamaServer(
        FakeResponse(
            text="",
            tool_calls=(("ignored", "lookup", '{"key": "alpha"}'),),
            finish_reason="stop",
        )
    )
    async with make_ollama_client(server) as client:
        result = await client.generate(
            "look it up",
            target="ollama:qwen3:8b",
            tools=[ai.ToolSpec("lookup", "Look up a key", {"type": "object"})],
        )

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0].name == "lookup"
    assert result.tool_calls[0].arguments == {"key": "alpha"}
    assert result.tool_calls[0].id, "an id is synthesized when the provider omits one"


# ---- discovery -----------------------------------------------------------------------


async def test_list_models_reports_artifact_metadata() -> None:
    server = FakeOllamaServer(models=("qwen3:8b",))
    async with make_ollama_client(server) as client:
        models = await client.models("ollama")

    assert [m.id for m in models] == ["qwen3:8b"]
    caps = models[0].capabilities
    assert caps is not None and caps.local is not None
    assert caps.local.parameter_size == "8B"
    assert caps.local.quantization == "Q4_K_M"
    assert caps.features.provenance == "discovered"


async def test_health_probe() -> None:
    server = FakeOllamaServer()
    async with make_ollama_client(server) as client:
        assert (await client.health("ollama")).ok is True


async def test_unreachable_server_is_unhealthy_not_an_exception() -> None:
    import httpx2

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama",
                base_url="http://127.0.0.1:11434",
                transport=httpx2.MockTransport(refuse),
            )
        ]
    )
    async with client:
        health = await client.health("ollama")

    assert health.ok is False
    assert "cannot reach" in health.detail


async def test_loaded_models_reports_vram_residency() -> None:
    """``/api/ps`` drives GPU-spill detection: resident VRAM below artifact size."""
    server = FakeOllamaServer(loaded={"qwen3:8b": 2_000_000_000})
    adapter = OllamaAdapter(
        ProviderConfig(
            provider_id="ollama", base_url="http://127.0.0.1:11434", transport=server.transport()
        )
    )
    try:
        loaded = await adapter.loaded_models()
    finally:
        await adapter.aclose()

    assert loaded == {"qwen3:8b": 2_000_000_000}


async def _ollama_diagnostics(loaded: dict[str, int]) -> tuple[ai.Diagnostic, ...]:
    server = FakeOllamaServer(loaded=loaded)
    adapter = OllamaAdapter(
        ProviderConfig(
            provider_id="ollama", base_url="http://127.0.0.1:11434", transport=server.transport()
        )
    )
    try:
        return tuple(await adapter.diagnostics())
    finally:
        await adapter.aclose()


async def test_diagnostics_report_a_spilled_model() -> None:
    """The fake reports 4.4 GB of weights; 2 GB resident is 45% on the GPU."""
    reported = await _ollama_diagnostics({"qwen3:8b": 2_000_000_000})

    assert len(reported) == 1
    assert reported[0].code == "ollama.gpu-spill"
    assert reported[0].severity == "warning"
    assert "45%" in reported[0].message


async def test_diagnostics_stay_quiet_for_a_fully_resident_model() -> None:
    assert await _ollama_diagnostics({"qwen3:8b": 4_400_000_000}) == ()


async def test_diagnostics_tolerate_a_near_miss() -> None:
    """Reported sizes wobble by a few megabytes; a warning on every load is noise."""
    assert await _ollama_diagnostics({"qwen3:8b": 4_390_000_000}) == ()


async def test_diagnostics_stay_quiet_when_nothing_is_loaded() -> None:
    assert await _ollama_diagnostics({}) == ()


async def test_diagnostics_stay_quiet_when_the_server_is_unreachable() -> None:
    import httpx2

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    adapter = OllamaAdapter(
        ProviderConfig(
            provider_id="ollama",
            base_url="http://127.0.0.1:11434",
            transport=httpx2.MockTransport(refuse),
        )
    )
    try:
        assert tuple(await adapter.diagnostics()) == ()
    finally:
        await adapter.aclose()


# ---- errors --------------------------------------------------------------------------


async def test_missing_model_suggests_pulling_it() -> None:
    server = FakeOllamaServer(FakeResponse(status=404, error_message='model "x" not found'))
    async with make_ollama_client(server) as client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("hi", target="ollama:x")

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.type_name == "ModelNotFoundError"


# ---- conformance ---------------------------------------------------------------------


def _server_for(scenario: str) -> FakeOllamaServer:
    if scenario == "tools":
        return FakeOllamaServer(
            FakeResponse(text="", tool_calls=(("c", "lookup", '{"key": "alpha"}'),))
        )
    if scenario == "reasoning":
        return FakeOllamaServer(FakeResponse(text="42", reasoning="Let me think."))
    if scenario == "structured":
        return FakeOllamaServer(FakeResponse(text=PROBE_ANSWER))
    if scenario == "repair":
        return FakeOllamaServer(
            [FakeResponse(text='{"wrong": true}'), FakeResponse(text=PROBE_ANSWER)]
        )
    if scenario == "auth_error":
        return FakeOllamaServer(FakeResponse(status=401, error_message="unauthorized"))
    if scenario == "rate_limited":
        return FakeOllamaServer(
            [
                FakeResponse(status=429, error_message="busy", headers={"retry-after": "0"}),
                FakeResponse(text="recovered"),
            ],
            embed_scenario=scenario,
        )
    if scenario == "oversized":
        return FakeOllamaServer(FakeResponse(text="x" * 20_000), embed_scenario=scenario)
    if scenario == "odd_finish":
        return FakeOllamaServer(FakeResponse(text="hello", finish_reason="unexpected"))
    return FakeOllamaServer(FakeResponse(text="Hello from Ollama."))


async def _build_client(scenario: str) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama",
                base_url="http://127.0.0.1:11434",
                transport=_server_for(scenario).transport(),
            )
        ],
        route=ai.Route(
            targets=("ollama:qwen3:8b",),
            retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
        ),
    )


HARNESS = ConformanceHarness(
    provider_id="ollama",
    model="qwen3:8b",
    build_client=_build_client,
    # Rerank stays off: Ollama documents no rerank endpoint (contracts/ollama.md).
    supports=Capabilities(embedding=True, cancellation=True),
    embedding_model="nomic-embed-text",
)


@pytest.mark.parametrize("case", CONFORMANCE_CASES, ids=lambda c: c.name)
async def test_ollama_conformance(case: object) -> None:
    name = case.name  # type: ignore[attr-defined]
    results = await run_conformance(HARNESS, only=[name])
    result = results[0]
    assert result.passed or result.skipped, f"{name} failed: {result.detail}"
