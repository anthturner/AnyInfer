"""Gemini's batchEmbedContents dialect: request/response wire mapping (contracts/gemini.md)."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.errors import ProviderError
from anyinfer.providers.base import EmbeddingWireRequest, ProviderConfig
from anyinfer.providers.gemini import GeminiAdapter


def _adapter(handler: Any) -> GeminiAdapter:
    return GeminiAdapter(
        ProviderConfig(
            provider_id="gemini",
            api_key="test-key",
            transport=httpx2.MockTransport(handler),
        )
    )


def _embed_response(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)
    count = len(body["requests"])
    return httpx2.Response(
        200,
        json={
            "embeddings": [{"values": [0.1 * (i + 1), 0.2]} for i in range(count)],
            "usageMetadata": {"promptTokenCount": count * 3},
        },
    )


async def test_embed_batches_through_batch_embed_contents() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return _embed_response(request)

    adapter = _adapter(handler)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="gemini-embedding-2", inputs=("a", "b"))
        )
        assert seen["path"].endswith("models/gemini-embedding-2:batchEmbedContents")
        entry = seen["body"]["requests"][0]
        assert entry["model"] == "models/gemini-embedding-2"
        assert entry["content"] == {"parts": [{"text": "a"}]}
        assert len(result.vectors) == 2
        assert result.vectors[1] == pytest.approx((0.2, 0.2))
        assert result.usage is not None and result.usage.input_tokens == 6
    finally:
        await adapter.aclose()


async def test_legacy_model_receives_the_mapped_task_type() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return _embed_response(request)

    adapter = _adapter(handler)
    try:
        await adapter.embed(
            EmbeddingWireRequest(
                model="gemini-embedding-001", inputs=("x",), input_type="query"
            )
        )
        assert seen["body"]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    finally:
        await adapter.aclose()


async def test_current_model_never_receives_task_type() -> None:
    """gemini-embedding-2 documents no taskType support; sending one would 400."""
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return _embed_response(request)

    adapter = _adapter(handler)
    try:
        await adapter.embed(
            EmbeddingWireRequest(
                model="gemini-embedding-2", inputs=("x",), input_type="query"
            )
        )
        assert "taskType" not in seen["body"]["requests"][0]
    finally:
        await adapter.aclose()


async def test_dimensions_forward_as_output_dimensionality() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return _embed_response(request)

    adapter = _adapter(handler)
    try:
        await adapter.embed(
            EmbeddingWireRequest(model="gemini-embedding-2", inputs=("x",), dimensions=768)
        )
        assert seen["body"]["requests"][0]["output_dimensionality"] == 768
    finally:
        await adapter.aclose()


async def test_vector_count_mismatch_is_rejected() -> None:
    adapter = _adapter(
        lambda request: httpx2.Response(200, json={"embeddings": [{"values": [0.1]}]})
    )
    try:
        with pytest.raises(ProviderError, match="returned 1 vectors for 2 inputs"):
            await adapter.embed(
                EmbeddingWireRequest(model="gemini-embedding-2", inputs=("a", "b"))
            )
    finally:
        await adapter.aclose()


async def test_missing_values_array_is_rejected() -> None:
    adapter = _adapter(
        lambda request: httpx2.Response(200, json={"embeddings": [{"nope": True}]})
    )
    try:
        with pytest.raises(ProviderError, match="'values' array"):
            await adapter.embed(
                EmbeddingWireRequest(model="gemini-embedding-2", inputs=("a",))
            )
    finally:
        await adapter.aclose()


async def test_client_embed_end_to_end_with_intent_warning() -> None:
    client = ai.AsyncClient(
        [
            ai.ProviderSettings(
                provider_id="gemini",
                api_key="test-key",
                transport=httpx2.MockTransport(_embed_response),
            )
        ],
        use_default_catalog=False,
    )
    try:
        result = await client.embed(
            ["hello"], target="gemini:gemini-embedding-2", input_type="query"
        )
        assert len(result.vectors) == 1
        assert result.space.provider_id == "gemini"
        # Declared-empty intents on gemini-embedding-2 -> the caller's intent is
        # recorded as having no effect, and the adapter never sent it.
        assert any("does not distinguish" in w for w in result.warnings)
    finally:
        await client.aclose()


async def test_embed_rejects_a_response_over_the_byte_cap() -> None:
    from anyinfer.errors import StreamProtocolError

    adapter = _adapter(
        lambda request: httpx2.Response(
            200,
            json={"embeddings": [{"values": [0.1]}], "padding": "x" * 200},
        )
    )
    try:
        with pytest.raises(StreamProtocolError, match="max_response_bytes"):
            await adapter.embed(
                EmbeddingWireRequest(model="m", inputs=("a",), max_response_bytes=32)
            )
    finally:
        await adapter.aclose()
