"""Ollama's native `/api/embed` dialect: request/response wire mapping (contracts/ollama.md)."""

from __future__ import annotations

import json

import httpx2
import pytest

from anyinfer.errors import ModelNotFoundError, ProviderError
from anyinfer.providers.base import EmbeddingWireRequest, ProviderConfig
from anyinfer.providers.ollama import OllamaAdapter


def _adapter(handler: object) -> OllamaAdapter:
    transport = httpx2.MockTransport(handler)  # type: ignore[arg-type]
    config = ProviderConfig(provider_id="ollama", base_url="http://fake.invalid", transport=transport)
    return OllamaAdapter(config)


def _embed_response(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)
    assert request.url.path == "/api/embed"
    assert body["model"] == "nomic-embed-text"
    inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
    return httpx2.Response(
        200,
        json={
            "model": "nomic-embed-text",
            "embeddings": [[0.1 * (i + 1), 0.2 * (i + 1)] for i in range(len(inputs))],
            "total_duration": 14143917,
            "load_duration": 1019500,
            "prompt_eval_count": 8,
        },
    )


async def test_embed_scalar_input() -> None:
    adapter = _adapter(_embed_response)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="nomic-embed-text", inputs=("hello",))
        )
        assert result.vectors == ((0.1, 0.2),)
        assert result.model == "nomic-embed-text"
        assert result.usage is not None
        assert result.usage.input_tokens == 8
    finally:
        await adapter.aclose()


async def test_embed_batch_input_preserves_order() -> None:
    adapter = _adapter(_embed_response)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="nomic-embed-text", inputs=("a", "b", "c"))
        )
        assert result.vectors[0] == pytest.approx((0.1, 0.2))
        assert result.vectors[1] == pytest.approx((0.2, 0.4))
        assert result.vectors[2] == pytest.approx((0.3, 0.6))
    finally:
        await adapter.aclose()


def _dimensions_response(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)
    assert body.get("dimensions") == 256
    return httpx2.Response(
        200, json={"model": "m", "embeddings": [[0.0] * 256], "prompt_eval_count": 3}
    )


async def test_embed_forwards_requested_dimensions() -> None:
    adapter = _adapter(_dimensions_response)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="m", inputs=("x",), dimensions=256)
        )
        assert len(result.vectors[0]) == 256
    finally:
        await adapter.aclose()


def _vector_count_mismatch_response(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json={"model": "m", "embeddings": [[1.0]]})


async def test_embed_rejects_vector_count_mismatch() -> None:
    adapter = _adapter(_vector_count_mismatch_response)
    try:
        with pytest.raises(ProviderError, match="returned 1 vectors"):
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("a", "b")))
    finally:
        await adapter.aclose()


def _model_not_found_response(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(404, json={"error": "model 'missing-model' not found"})


async def test_embed_maps_model_not_found() -> None:
    adapter = _adapter(_model_not_found_response)
    try:
        with pytest.raises(ModelNotFoundError, match="pull it first"):
            await adapter.embed(EmbeddingWireRequest(model="missing-model", inputs=("a",)))
    finally:
        await adapter.aclose()


def _malformed_response(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json={"model": "m"})  # no 'embeddings' key


async def test_embed_rejects_missing_embeddings_key() -> None:
    adapter = _adapter(_malformed_response)
    try:
        with pytest.raises(ProviderError, match="missing an 'embeddings' array"):
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("a",)))
    finally:
        await adapter.aclose()
