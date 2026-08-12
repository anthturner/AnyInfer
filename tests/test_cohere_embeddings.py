"""Cohere's v2 embed and rerank dialects: wire mapping and end-to-end (contracts/cohere.md)."""

from __future__ import annotations

import json

import httpx2
import pytest

import anyinfer as ai
from anyinfer.errors import ConfigError, ProviderError, RateLimitError
from anyinfer.providers.base import (
    EmbeddingWireRequest,
    ProviderConfig,
    RerankWireDocument,
    RerankWireRequest,
)
from anyinfer.providers.cohere import CohereAdapter


def _adapter(handler: object) -> CohereAdapter:
    transport = httpx2.MockTransport(handler)  # type: ignore[arg-type]
    config = ProviderConfig(
        provider_id="cohere",
        base_url="http://fake.invalid",
        api_key="test-key",
        transport=transport,
    )
    return CohereAdapter(config)


def _embed_response(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)
    assert request.url.path == "/v2/embed"
    assert body["embedding_types"] == ["float"]
    texts = body["texts"]
    return httpx2.Response(
        200,
        json={
            "id": "resp-1",
            "embeddings": {
                "float": [[0.1 * (i + 1), 0.2 * (i + 1)] for i in range(len(texts))]
            },
            "texts": texts,
            "meta": {
                "api_version": {"version": "2"},
                "billed_units": {"input_tokens": 99, "search_units": 1},
                "tokens": {"input_tokens": 7},
            },
        },
    )


# ---- embed wire mapping -----------------------------------------------------------------


async def test_embed_scalar_input_maps_fields() -> None:
    adapter = _adapter(_embed_response)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="embed-v4.0", inputs=("hello",), input_type="document")
        )
        assert result.vectors == ((0.1, 0.2),)
        assert result.dimensions == 2
        assert result.usage is not None
        # Normalized usage follows meta.tokens, never billed_units (99 would be wrong).
        assert result.usage.input_tokens == 7
    finally:
        await adapter.aclose()


async def test_embed_batch_preserves_order() -> None:
    adapter = _adapter(_embed_response)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(
                model="embed-v4.0", inputs=("a", "b", "c"), input_type="document"
            )
        )
        assert result.vectors[0] == pytest.approx((0.1, 0.2))
        assert result.vectors[1] == pytest.approx((0.2, 0.4))
        assert result.vectors[2] == pytest.approx((0.3, 0.6))
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    ("intent", "wire_value"),
    [
        ("query", "search_query"),
        ("document", "search_document"),
        ("classification", "classification"),
        ("clustering", "clustering"),
    ],
)
async def test_embed_translates_every_input_intent(intent: str, wire_value: str) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["input_type"] = json.loads(request.content)["input_type"]
        return httpx2.Response(
            200, json={"embeddings": {"float": [[0.1, 0.2]]}, "meta": {}}
        )

    adapter = _adapter(handler)
    try:
        await adapter.embed(
            EmbeddingWireRequest(model="m", inputs=("x",), input_type=intent)  # type: ignore[arg-type]
        )
        assert seen["input_type"] == wire_value
    finally:
        await adapter.aclose()


async def test_embed_without_intent_is_refused_before_any_call() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no HTTP request may be sent for an intent-less embed")

    adapter = _adapter(handler)
    try:
        with pytest.raises(ConfigError, match="requires an input type"):
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("x",)))
    finally:
        await adapter.aclose()


async def test_embed_forwards_requested_dimensions() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        assert body["output_dimension"] == 256
        return httpx2.Response(
            200, json={"embeddings": {"float": [[0.0] * 256]}, "meta": {}}
        )

    adapter = _adapter(handler)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="embed-v4.0", inputs=("x",), input_type="query", dimensions=256)
        )
        assert len(result.vectors[0]) == 256
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    "payload",
    [
        {"embeddings": {"int8": [[1, 2]]}},
        {"embeddings": "not-an-object"},
        {},
    ],
)
async def test_embed_rejects_malformed_response(payload: dict[str, object]) -> None:
    adapter = _adapter(lambda request: httpx2.Response(200, json=payload))
    try:
        with pytest.raises(ProviderError, match=r"embeddings\.float"):
            await adapter.embed(
                EmbeddingWireRequest(model="m", inputs=("x",), input_type="query")
            )
    finally:
        await adapter.aclose()


async def test_embed_rejects_vector_count_mismatch() -> None:
    adapter = _adapter(
        lambda request: httpx2.Response(200, json={"embeddings": {"float": [[0.1]]}})
    )
    try:
        with pytest.raises(ProviderError, match="returned 1 vectors for 2 inputs"):
            await adapter.embed(
                EmbeddingWireRequest(model="m", inputs=("a", "b"), input_type="query")
            )
    finally:
        await adapter.aclose()


async def test_embed_maps_rate_limit_with_retry_after() -> None:
    adapter = _adapter(
        lambda request: httpx2.Response(
            429, headers={"retry-after": "2"}, json={"message": "slow down"}
        )
    )
    try:
        with pytest.raises(RateLimitError) as excinfo:
            await adapter.embed(
                EmbeddingWireRequest(model="m", inputs=("x",), input_type="query")
            )
        assert excinfo.value.retry_after_s == 2.0
    finally:
        await adapter.aclose()


async def test_embed_maps_auth_failure() -> None:
    adapter = _adapter(
        lambda request: httpx2.Response(401, json={"message": "invalid api token"})
    )
    try:
        with pytest.raises(ProviderError) as excinfo:
            await adapter.embed(
                EmbeddingWireRequest(model="m", inputs=("x",), input_type="query")
            )
        assert excinfo.value.http_status == 401
        assert excinfo.value.retryable is False
    finally:
        await adapter.aclose()


# ---- rerank wire mapping ----------------------------------------------------------------


def _rerank_response(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)
    assert request.url.path == "/v2/rerank"
    assert isinstance(body["documents"], list)
    assert all(isinstance(d, str) for d in body["documents"])
    # Positional indexes into the submitted array, best score first.
    return httpx2.Response(
        200,
        json={
            "id": "rr-1",
            "results": [
                {"index": 2, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.4},
            ],
            "meta": {
                "billed_units": {"search_units": 1},
                "tokens": {"input_tokens": 12},
            },
        },
    )


async def test_rerank_maps_positional_indexes_to_caller_indexes() -> None:
    adapter = _adapter(_rerank_response)
    try:
        result = await adapter.rerank(
            RerankWireRequest(
                model="rerank-v3.5",
                query="q",
                documents=(
                    RerankWireDocument(index=10, text="alpha"),
                    RerankWireDocument(index=11, text="beta"),
                    RerankWireDocument(index=12, text="gamma"),
                ),
            )
        )
        assert [(item.index, item.score) for item in result.items] == [(12, 0.9), (10, 0.4)]
        assert result.usage is not None
        assert result.usage.input_tokens == 12
    finally:
        await adapter.aclose()


async def test_rerank_forwards_top_n() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert json.loads(request.content)["top_n"] == 2
        return httpx2.Response(200, json={"results": []})

    adapter = _adapter(handler)
    try:
        result = await adapter.rerank(
            RerankWireRequest(
                model="m",
                query="q",
                documents=(RerankWireDocument(index=0, text="d"),),
                top_n=2,
            )
        )
        assert result.items == ()
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "missing a 'results' array"),
        ({"results": [{"relevance_score": 0.5}]}, "integer 'index'"),
        ({"results": [{"index": 0}]}, "numeric 'relevance_score'"),
        ({"results": [{"index": True, "relevance_score": 0.5}]}, "integer 'index'"),
    ],
)
async def test_rerank_rejects_malformed_response(payload: dict[str, object], message: str) -> None:
    adapter = _adapter(lambda request: httpx2.Response(200, json=payload))
    try:
        with pytest.raises(ProviderError, match=message):
            await adapter.rerank(
                RerankWireRequest(
                    model="m", query="q", documents=(RerankWireDocument(index=0, text="d"),)
                )
            )
    finally:
        await adapter.aclose()


async def test_rerank_out_of_range_positional_index_passes_through_untranslated() -> None:
    adapter = _adapter(
        lambda request: httpx2.Response(
            200, json={"results": [{"index": 7, "relevance_score": 0.5}]}
        )
    )
    try:
        result = await adapter.rerank(
            RerankWireRequest(
                model="m", query="q", documents=(RerankWireDocument(index=3, text="d"),)
            )
        )
        # The core's index validation rejects it downstream; the adapter must not guess.
        assert result.items[0].index == 7
    finally:
        await adapter.aclose()


# ---- end to end through the client ------------------------------------------------------


def _client_with_mock(handler: object) -> ai.AsyncClient:
    transport = httpx2.MockTransport(handler)  # type: ignore[arg-type]
    return ai.AsyncClient(
        providers=[
            ai.ProviderSettings(provider_id="cohere", api_key="test-key", transport=transport)
        ],
        use_default_catalog=False,
    )


async def test_client_embed_end_to_end() -> None:
    client = _client_with_mock(_embed_response)
    try:
        result = await client.embed(
            ["hello", "world"], target="cohere:embed-v4.0", input_type="document"
        )
        assert len(result.vectors) == 2
        assert result.space.provider_id == "cohere"
        assert result.space.model == "embed-v4.0"
        assert result.usage.input_tokens == 7
    finally:
        await client.aclose()


async def test_client_embed_batches_against_declared_96_limit() -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        texts = json.loads(request.content)["texts"]
        calls.append(len(texts))
        return httpx2.Response(
            200,
            json={
                "embeddings": {"float": [[0.1, 0.2] for _ in texts]},
                "meta": {"tokens": {"input_tokens": len(texts)}},
            },
        )

    client = _client_with_mock(handler)
    try:
        result = await client.embed(
            [f"t{i}" for i in range(100)], target="cohere:embed-v4.0", input_type="document"
        )
        assert len(result.vectors) == 100
        assert calls == [96, 4]
        assert result.usage.input_tokens == 100
    finally:
        await client.aclose()


async def test_client_rerank_end_to_end() -> None:
    client = _client_with_mock(_rerank_response)
    try:
        result = await client.rerank(
            "q", ["alpha", "beta", "gamma"], target="cohere:rerank-v3.5"
        )
        assert [item.index for item in result.items] == [2, 0]
        assert result.items[0].document_id == "2"
    finally:
        await client.aclose()
