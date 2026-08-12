"""Voyage AI: embeddings and reranker wire mapping (contracts/voyage.md)."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.errors import ProviderError
from anyinfer.providers.base import (
    EmbeddingWireRequest,
    ProviderConfig,
    RerankWireDocument,
    RerankWireRequest,
)
from anyinfer.providers.voyage import VoyageAdapter


def _adapter(handler: Any) -> VoyageAdapter:
    return VoyageAdapter(
        ProviderConfig(
            provider_id="voyage",
            api_key="test-key",
            transport=httpx2.MockTransport(handler),
        )
    )


def _embed_response(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)
    inputs = body["input"]
    return httpx2.Response(
        200,
        json={
            "object": "list",
            # Deliberately out of order: entries carry their index and must be re-sorted.
            "data": [
                {"object": "embedding", "index": i, "embedding": [0.1 * (i + 1), 0.2]}
                for i in reversed(range(len(inputs)))
            ],
            "model": body["model"],
            "usage": {"total_tokens": len(inputs) * 2},
        },
    )


async def test_embed_orders_by_reported_index() -> None:
    adapter = _adapter(_embed_response)
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="voyage-3.5", inputs=("a", "b", "c"))
        )
        assert result.vectors[0] == pytest.approx((0.1, 0.2))
        assert result.vectors[2] == pytest.approx((0.3, 0.2))
        assert result.usage is not None and result.usage.total_tokens == 6
    finally:
        await adapter.aclose()


async def test_embed_sends_voyage_spellings() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return _embed_response(request)

    adapter = _adapter(handler)
    try:
        await adapter.embed(
            EmbeddingWireRequest(
                model="voyage-3.5", inputs=("x",), input_type="query", dimensions=512
            )
        )
        assert seen["input_type"] == "query"
        assert seen["output_dimension"] == 512
        assert "dimensions" not in seen
    finally:
        await adapter.aclose()


async def test_embed_unsupported_intent_is_never_sent() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return _embed_response(request)

    adapter = _adapter(handler)
    try:
        await adapter.embed(
            EmbeddingWireRequest(model="voyage-3.5", inputs=("x",), input_type="clustering")
        )
        assert "input_type" not in seen
    finally:
        await adapter.aclose()


async def test_embed_duplicate_index_is_rejected() -> None:
    adapter = _adapter(
        lambda request: httpx2.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [0.1]},
                    {"index": 0, "embedding": [0.2]},
                ]
            },
        )
    )
    try:
        with pytest.raises(ProviderError, match="out-of-range or duplicate index"):
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("a", "b")))
    finally:
        await adapter.aclose()


async def test_rerank_maps_top_k_and_caller_indexes() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [{"index": 1, "relevance_score": 0.9}],
                "model": "rerank-2.5",
                "usage": {"total_tokens": 12},
            },
        )

    adapter = _adapter(handler)
    try:
        result = await adapter.rerank(
            RerankWireRequest(
                model="rerank-2.5",
                query="q",
                documents=(
                    RerankWireDocument(index=10, text="a"),
                    RerankWireDocument(index=11, text="b"),
                ),
                top_n=1,
            )
        )
        assert seen["top_k"] == 1
        assert "top_n" not in seen
        assert result.items[0].index == 11
        assert result.usage is not None and result.usage.total_tokens == 12
    finally:
        await adapter.aclose()


async def test_health_is_a_reachability_probe() -> None:
    adapter = _adapter(lambda request: httpx2.Response(404, json={"detail": "no route"}))
    try:
        health = await adapter.health()
        assert health.ok is True
        assert "404" in (health.detail or "")
    finally:
        await adapter.aclose()


async def test_client_embed_and_rerank_end_to_end() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/embeddings"):
            return _embed_response(request)
        body = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "data": [
                    {"index": i, "relevance_score": 1.0 - 0.1 * i}
                    for i in range(len(body["documents"]))
                ],
                "usage": {"total_tokens": 5},
            },
        )

    client = ai.AsyncClient(
        [
            ai.ProviderSettings(
                provider_id="voyage", api_key="k", transport=httpx2.MockTransport(handler)
            )
        ],
        use_default_catalog=False,
    )
    try:
        embedded = await client.embed(
            ["hello"], target="voyage:voyage-3.5", input_type="query"
        )
        assert embedded.space.provider_id == "voyage"
        assert embedded.warnings == ()  # query is a supported intent: no warning

        ranked = await client.rerank("q", ["a", "b"], target="voyage:rerank-2.5")
        assert [item.index for item in ranked.items] == [0, 1]
    finally:
        await client.aclose()
