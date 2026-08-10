"""Stateless per-request corpus reduction across client and sidecar surfaces."""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer.context import ContextDocument, ContextRequest, ContextSummary, ContextTuning
from anyinfer.registry import ProviderRegistry
from anyinfer.serve.openai_codec import (
    CONTEXT_FIELD,
    completion_from_generation,
    request_from_openai,
    request_to_openai,
)
from anyinfer.testing import ScriptedModel, ScriptedProvider


def _provider(
    capabilities: ai.ModelCapabilities | None = None,
) -> tuple[ai.AsyncClient, ScriptedProvider]:
    model = ScriptedModel(
        "m", text="ok", capabilities=capabilities or ScriptedModel("x").capabilities
    )
    provider = ScriptedProvider("corpus", [model])
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    if capabilities is None:
        provider.register(registry)
    else:
        registry.register(
            replace(
                provider.descriptor(),
                default_capabilities=capabilities,
                static_capabilities={"m": capabilities},
            )
        )
    return ai.AsyncClient(
        [provider.settings()], registry=registry, use_default_catalog=False
    ), provider


async def test_reduction_precedes_gate_and_honors_placement_and_pinning() -> None:
    client, provider = _provider()
    documents = (
        ContextDocument.of("irrelevant.py", "x = 1\n" * 20, pinned=True),
        ContextDocument.of("auth.py", "def refresh_token(): return token\n" * 100),
    )
    request = ContextRequest(
        documents,
        query="refresh token",
        strategy="ranked",
        max_tokens=170,
        placement="prepend_user",
    )
    async with client:
        result = await client.generate("why refresh?", target="corpus:m", context=request)

    assert result.context_reduction is not None
    assert result.context_reduction.candidate_count == 2
    envelope = provider.requests[0]["messages"][0]["content"]
    assert "irrelevant.py" in envelope, "pinned documents are admitted first"
    assert provider.requests[0]["messages"][0]["role"] == "user"


async def test_unknown_window_requires_an_explicit_document_budget() -> None:
    capabilities = ai.ModelCapabilities(features=ai.Sourced(ai.Feature.STREAMING, "default"))
    client, provider = _provider(capabilities)
    request = ContextRequest((ContextDocument.of("a.txt", "hello"),))
    async with client:
        with pytest.raises(ai.ConfigError, match="no known remaining context budget"):
            await client.generate("question", target="corpus:m", context=request)
    assert provider.call_count() == 0


async def test_default_provenance_window_is_not_used_as_a_document_budget() -> None:
    capabilities = ai.ModelCapabilities(
        features=ai.Sourced(ai.Feature.STREAMING, "default"),
        context_window=ai.Sourced(32_000, "default"),
    )
    client, provider = _provider(capabilities)
    request = ContextRequest((ContextDocument.of("a.txt", "hello"),))
    async with client:
        with pytest.raises(ai.ConfigError, match="no known remaining context budget"):
            await client.generate("question", target="corpus:m", context=request)
    assert provider.call_count() == 0


def test_codec_round_trips_every_context_request_field() -> None:
    request = ContextRequest(
        (ContextDocument.of("a.py", "print('a')", pinned=True),),
        query="print",
        strategy="packed",
        max_tokens=123,
        placement="prepend_user",
        tuning=ContextTuning(compact_fallback=True),
        max_request_documents=7,
        max_request_bytes=2048,
    )
    wire = request_to_openai("corpus:m", ai.GenerationRequest((ai.user("hi"),), context=request))
    _, decoded, _ = request_from_openai(wire)
    assert decoded.context == request
    assert {item.name for item in fields(ContextRequest)} == set(wire[CONTEXT_FIELD])


def test_context_summary_is_returned_without_document_content() -> None:
    result = ai.Generation(
        text="answer",
        structured=None,
        tool_calls=(),
        target=ai.ResolvedTarget("corpus", "m"),
        finish_reason="stop",
        usage=ai.Usage(),
        timing=ai.Timing(0.0),
        context_reduction=ContextSummary("auto", "ranked", 20, 3, 17, 800, False),
    )
    body = completion_from_generation(result, model="corpus:m")
    assert body[CONTEXT_FIELD] == {
        "strategy": "auto",
        "representation": "ranked",
        "candidate_count": 20,
        "selected_count": 3,
        "omitted_count": 17,
        "estimated_tokens": 800,
        "complete": False,
    }


def test_context_request_rejects_distill_and_payload_overflow() -> None:
    document = ContextDocument.of("a.txt", "abcdef")
    with pytest.raises(ValueError, match="distill"):
        ContextRequest((document,), strategy="distill")
    with pytest.raises(ValueError, match="request limit"):
        ContextRequest((document,), max_request_bytes=1)


def test_serve_frontend_does_not_import_context_implementation() -> None:
    serve = Path(ai.__file__).parent / "serve"
    for path in serve.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "..context" not in source
        assert "anyinfer.context" not in source
