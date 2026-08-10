"""End-to-end target verification: the probe behind a Test connection button."""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.verification import (
    VERIFY_MAX_OUTPUT_TOKENS,
    VERIFY_PROMPT,
    Verification,
    excerpt,
    judge_reply,
)
from support import make_client, make_sync_client

OK = json.dumps({"reply": "OK"})


# ---- grading -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    ["OK", "ok", "Ok!", "OK.", "  OK  ", "Ok, ready when you are"],
    ids=lambda r: repr(r),
)
def test_packaging_is_forgiven(reply: str) -> None:
    """A model that says "Ok!" has understood the request; punctuation is not the test."""
    passed, detail, _ = judge_reply({"reply": reply}, "")
    assert passed is True
    assert detail == ""


@pytest.mark.parametrize(
    "reply",
    ["I cannot help with that", "sure thing", "okay then", "", "   "],
)
def test_content_is_not_forgiven(reply: str) -> None:
    passed, detail, _ = judge_reply({"reply": reply}, "")
    assert passed is False
    assert detail


def test_grading_falls_back_to_the_raw_text() -> None:
    """A provider with no structured mode still answers; the text is what there is."""
    passed, _, shown = judge_reply(None, "OK")
    assert passed is True
    assert shown == "OK"


def test_excerpt_bounds_what_is_shown() -> None:
    shown = excerpt("word " * 200)
    assert len(shown) <= 161
    assert shown.endswith("…")


def test_summary_reads_as_a_status_line() -> None:
    target = ai.ResolvedTarget("openai", "gpt-5")
    assert "answered in" in Verification(target, ok=True, latency_ms=42.0).summary
    assert "failed: nope" in Verification(target, ok=False, detail="nope").summary


# ---- the probe -----------------------------------------------------------------------


async def test_a_working_target_verifies() -> None:
    server = FakeOpenAIServer(FakeResponse(text=OK))
    async with make_client(server) as client:
        result = await client.verify("openai-compat:m")

    assert result.ok is True
    assert result.reached is True
    assert result.detail == ""
    assert result.reply == "OK"
    assert result.target is not None and result.target.model == "m"
    assert result.latency_ms >= 0.0


async def test_the_probe_is_deliberately_tiny() -> None:
    server = FakeOpenAIServer(FakeResponse(text=OK))
    async with make_client(server) as client:
        await client.verify("openai-compat:m")

    sent = server.requests[0]
    assert sent["max_tokens"] == VERIFY_MAX_OUTPUT_TOKENS
    assert any(m["content"] == VERIFY_PROMPT for m in sent["messages"])


async def test_a_wrong_answer_is_reached_but_not_ok() -> None:
    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"reply": "I refuse"})))
    async with make_client(server) as client:
        result = await client.verify("openai-compat:m")

    assert result.reached is True, "the connection and credential are fine"
    assert result.ok is False
    assert "I refuse" in result.detail


async def test_an_answer_in_the_wrong_shape_is_reached_but_not_ok() -> None:
    """'Reachable but cannot hold a schema' needs a different fix from 'unreachable'."""
    server = FakeOpenAIServer(FakeResponse(text="OK, sure thing!"))
    async with make_client(server) as client:
        result = await client.verify("openai-compat:m")

    assert result.reached is True
    assert result.ok is False
    assert "not in the requested shape" in result.detail
    assert "OK, sure thing!" in result.reply


async def test_an_unreachable_target_reports_rather_than_raising() -> None:
    server = FakeOpenAIServer(FakeResponse(status=401, error_message="invalid api key"))
    async with make_client(server) as client:
        result = await client.verify("openai-compat:m")

    assert result.ok is False
    assert result.reached is False, "nothing answered, so nothing was reached"
    assert "invalid api key" in result.detail


async def test_the_probe_never_falls_back_to_another_target() -> None:
    """A chain that answered from elsewhere would report a connection you do not have."""
    from support import make_multi_client

    broken = FakeOpenAIServer(FakeResponse(status=500, error_message="down"))
    working = FakeOpenAIServer(FakeResponse(text=OK))
    async with make_multi_client(
        [("openai-compat", broken), ("openai", working)],
        route=ai.Route(targets=("openai-compat:m", "openai:gpt-5")),
    ) as client:
        result = await client.verify("openai-compat:m")

    assert result.ok is False
    assert working.call_count == 0, "the probe reports on the target it was given"
    assert broken.call_count == 1, "and does not retry it either"


async def test_a_bad_target_is_the_callers_mistake_and_raises() -> None:
    server = FakeOpenAIServer()
    async with make_client(server) as client:
        with pytest.raises(ai.ConfigError):
            await client.verify("no-such-provider:m")


async def test_verification_carries_runtime_diagnostics() -> None:
    """A target that works but is degraded is exactly what an operator wants told."""
    from collections.abc import Sequence

    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.types.results import Diagnostic
    from support import make_multi_client

    note = Diagnostic(code="fake.spill", severity="warning", message="running on the CPU")

    class Reporting(OpenAICompatAdapter):
        async def diagnostics(self) -> Sequence[Diagnostic]:
            return (note,)

    registry = ai.ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ai.ProviderDescriptor(
            id="noisy",
            display_name="Fake noisy",
            factory=Reporting,
            requires_base_url=True,
            reports_diagnostics=True,
        )
    )
    server = FakeOpenAIServer(FakeResponse(text=OK))
    async with make_multi_client([("noisy", server)], registry=registry) as client:
        result = await client.verify("noisy:m")

    assert result.ok is True
    assert result.diagnostics == (note,)


def test_sync_client_verify() -> None:
    server = FakeOpenAIServer(FakeResponse(text=OK))
    client = make_sync_client(server)
    try:
        assert client.verify("openai-compat:m").ok is True
    finally:
        client.close()


# ---- reasoning-aware probing (CS.4) -------------------------------------------------------


async def test_a_reasoning_model_gets_a_larger_probe_budget() -> None:
    """A thinking model spends the ordinary 64 tokens before it says anything at all."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.registry import ProviderDescriptor, ProviderRegistry
    from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
    from anyinfer.verification import VERIFY_REASONING_OUTPUT_TOKENS

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="thinker",
            display_name="Thinker",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            default_capabilities=ModelCapabilities(
                features=Sourced(
                    Feature.STREAMING | Feature.SYSTEM_PROMPT | Feature.REASONING,
                    "catalog",
                )
            ),
        )
    )
    server = FakeOpenAIServer(FakeResponse(text=OK))
    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "thinker", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        registry=registry,
    ) as client:
        result = await client.verify("thinker:m")

    assert result.ok
    assert server.requests[0]["max_tokens"] == VERIFY_REASONING_OUTPUT_TOKENS


async def test_a_non_reasoning_model_keeps_the_small_budget() -> None:
    """Quadrupling every probe to fix one misdiagnosis would be the wrong trade."""
    server = FakeOpenAIServer(FakeResponse(text=OK))
    async with make_client(server) as client:
        await client.verify("openai-compat:m")

    assert server.requests[0]["max_tokens"] == VERIFY_MAX_OUTPUT_TOKENS


async def test_a_descriptor_level_reasoning_flag_is_enough() -> None:
    """The gate is a ceiling, not a claim, so it does not wait for trusted provenance.

    Every real Ollama model reports its features at ``default``. A trusted-provenance gate
    read as the careful choice and would simply never have fired for the thinking models
    this exists for — confirmed against a live ``ollama:gpt-oss:20b``.
    """
    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.registry import ProviderDescriptor, ProviderRegistry
    from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
    from anyinfer.verification import VERIFY_REASONING_OUTPUT_TOKENS

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="maybe-thinker",
            display_name="Maybe Thinker",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            default_capabilities=ModelCapabilities(
                features=Sourced(Feature.STREAMING | Feature.REASONING, "default")
            ),
        )
    )
    server = FakeOpenAIServer(FakeResponse(text=OK))
    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "maybe-thinker",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        registry=registry,
    ) as client:
        await client.verify("maybe-thinker:m")

    assert server.requests[0]["max_tokens"] == VERIFY_REASONING_OUTPUT_TOKENS


async def test_a_real_ollama_model_would_get_the_larger_budget() -> None:
    """The reported bug, pinned: `ollama:qwen3:4b` must not be probed at 64 tokens."""
    from anyinfer.testing.fakes import FakeOllamaServer
    from anyinfer.verification import VERIFY_REASONING_OUTPUT_TOKENS

    server = FakeOllamaServer(FakeResponse(text=OK))
    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama", base_url="http://127.0.0.1:11434", transport=server.transport()
            )
        ]
    ) as client:
        await client.verify("ollama:qwen3:4b")

    assert server.requests[0]["options"]["num_predict"] == VERIFY_REASONING_OUTPUT_TOKENS
