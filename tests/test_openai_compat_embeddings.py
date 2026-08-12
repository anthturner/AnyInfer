"""The shared OpenAI-compatible /v1/embeddings dialect: request/response wire mapping."""

from __future__ import annotations

import base64
import json
import struct

import httpx2
import pytest

from anyinfer.errors import ProviderError
from anyinfer.providers.base import EmbeddingWireRequest, ProviderConfig
from anyinfer.providers.openai_compat import OpenAICompatAdapter
from anyinfer.providers.openai_compat_embeddings import (
    OpenAICompatEmbeddingsMixin,
    decode_embedding_value,
)


class _EmbeddingAdapter(OpenAICompatEmbeddingsMixin, OpenAICompatAdapter):
    """A minimal composition proving the mixin works when mixed into a real adapter."""


def _adapter(handler: object) -> _EmbeddingAdapter:
    transport = httpx2.MockTransport(handler)  # type: ignore[arg-type]
    config = ProviderConfig(
        provider_id="test-openai-compat",
        base_url="http://fake.invalid/v1",
        transport=transport,
    )
    return _EmbeddingAdapter(config)


def _float_response(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)
    assert body["model"] == "embed-small"
    inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
    return httpx2.Response(
        200,
        json={
            "data": [
                {"index": i, "embedding": [0.1 * (i + 1), 0.2 * (i + 1)]}
                for i in range(len(inputs))
            ],
            "model": "embed-small",
            "usage": {"prompt_tokens": 7, "total_tokens": 7},
        },
    )


async def test_embed_scalar_input_and_parses_float_response() -> None:
    adapter = _adapter(_float_response)
    try:
        result = await adapter.embed(EmbeddingWireRequest(model="embed-small", inputs=("hi",)))
        assert result.vectors == ((0.1, 0.2),)
        assert result.model == "embed-small"
        assert result.usage is not None
        assert result.usage.input_tokens == 7
    finally:
        await adapter.aclose()


async def test_embed_batch_input_preserves_order() -> None:
    adapter = _adapter(_float_response)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="embed-small", inputs=("a", "b", "c"))
        )
        assert result.vectors[0] == pytest.approx((0.1, 0.2))
        assert result.vectors[1] == pytest.approx((0.2, 0.4))
        assert result.vectors[2] == pytest.approx((0.3, 0.6))
    finally:
        await adapter.aclose()


def _base64_response(request: httpx2.Request) -> httpx2.Response:
    values = (0.5, -0.25, 1.0)
    packed = struct.pack(f"<{len(values)}f", *values)
    encoded = base64.b64encode(packed).decode("ascii")
    return httpx2.Response(
        200, json={"data": [{"index": 0, "embedding": encoded}], "model": "embed-b64"}
    )


async def test_embed_decodes_base64_encoded_vectors() -> None:
    adapter = _adapter(_base64_response)
    try:
        result = await adapter.embed(EmbeddingWireRequest(model="embed-b64", inputs=("x",)))
        assert result.vectors[0] == pytest.approx((0.5, -0.25, 1.0))
    finally:
        await adapter.aclose()


def _out_of_order_response(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "data": [
                {"index": 1, "embedding": [9.0]},
                {"index": 0, "embedding": [1.0]},
            ],
            "model": "m",
        },
    )


async def test_embed_reorders_response_by_index() -> None:
    adapter = _adapter(_out_of_order_response)
    try:
        result = await adapter.embed(EmbeddingWireRequest(model="m", inputs=("a", "b")))
        assert result.vectors == ((1.0,), (9.0,))
    finally:
        await adapter.aclose()


def _missing_index_response(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}], "model": "m"})


async def test_embed_missing_vector_raises_provider_error() -> None:
    adapter = _adapter(_missing_index_response)
    try:
        with pytest.raises(ProviderError, match="missing vector"):
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("a", "b")))
    finally:
        await adapter.aclose()


def _error_response(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(401, json={"error": {"message": "bad key"}})


async def test_embed_maps_http_error_status() -> None:
    from anyinfer.errors import AuthError

    adapter = _adapter(_error_response)
    try:
        with pytest.raises(AuthError):
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("a",)))
    finally:
        await adapter.aclose()


def test_decode_embedding_value_rejects_bad_type() -> None:
    with pytest.raises(ProviderError, match="unsupported type"):
        decode_embedding_value(123)


def test_decode_embedding_value_rejects_malformed_base64() -> None:
    with pytest.raises(ProviderError, match="not valid base64"):
        decode_embedding_value("not-valid-base64!!!")


def test_decode_embedding_value_rejects_wrong_length() -> None:
    # 3 bytes is not a multiple of 4 (one float32).
    bad = base64.b64encode(b"\x00\x01\x02").decode("ascii")
    with pytest.raises(ProviderError, match="whole number"):
        decode_embedding_value(bad)


# ---- the concrete OpenAI adapter serves the dialect --------------------------------------


async def test_openai_adapter_embeds_end_to_end_with_batching() -> None:
    """The dedicated adapter composes the dialect, and core batching splits at 2,048."""
    import anyinfer as ai

    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
        calls.append(len(inputs))
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": i, "embedding": [0.1, 0.2]}
                    for i in range(len(inputs))
                ],
                "model": body["model"],
                "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
            },
        )

    client = ai.AsyncClient(
        [
            ai.ProviderSettings(
                provider_id="openai",
                api_key="test-key",
                transport=httpx2.MockTransport(handler),
            )
        ],
        use_default_catalog=False,
    )
    try:
        result = await client.embed(
            [f"t{i}" for i in range(2_500)], target="openai:text-embedding-3-small"
        )
        assert len(result.vectors) == 2_500
        assert calls == [2_048, 452]
        assert result.usage.input_tokens == 2_500
        assert result.space.model == "text-embedding-3-small"
    finally:
        await client.aclose()
