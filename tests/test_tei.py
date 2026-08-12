"""Text Embeddings Inference: native /embed and /rerank wire mapping (contracts/tei.md)."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.errors import ProviderError, RateLimitError
from anyinfer.providers.base import (
    EmbeddingWireRequest,
    ProviderConfig,
    RerankWireDocument,
    RerankWireRequest,
)
from anyinfer.providers.tei import TEIAdapter
from anyinfer.testing.conformance import Capabilities, ConformanceHarness, run_conformance

_INFO = {
    "model_id": "BAAI/bge-large-en-v1.5",
    "model_type": {"embedding": {}},
    "max_input_length": 512,
    "max_batch_tokens": 16384,
    "max_client_batch_size": 32,
    "version": "1.9.0",
}


def _adapter(handler: Any) -> TEIAdapter:
    return TEIAdapter(
        ProviderConfig(
            provider_id="tei",
            base_url="http://127.0.0.1:8080",
            transport=httpx2.MockTransport(handler),
        )
    )


def _server(scenario: str = "default") -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/info"):
            info = dict(_INFO)
            if scenario == "reranker":
                info["model_id"] = "BAAI/bge-reranker-large"
                info["model_type"] = {"reranker": {}}
            return httpx2.Response(200, json=info)
        if scenario == "rate_limited":
            return httpx2.Response(
                429,
                json={"error": "model is overloaded", "error_type": "overloaded"},
                headers={"retry-after": "1"},
            )
        if path.endswith("/embed"):
            inputs = json.loads(request.content)["inputs"]
            return httpx2.Response(
                200, json=[[0.1 * (i + 1), 0.2] for i in range(len(inputs))]
            )
        if path.endswith("/rerank"):
            body = json.loads(request.content)
            # Index order, deliberately not score order — the adapter must sort.
            return httpx2.Response(
                200,
                json=[
                    {"index": i, "score": 0.1 if i == 0 else 0.9 - 0.1 * i}
                    for i in range(len(body["texts"]))
                ],
            )
        return httpx2.Response(404, json={"error": "no route", "error_type": "not_found"})

    return handler


# ---- discovery ---------------------------------------------------------------------------


async def test_info_discovers_the_single_model_with_its_operation() -> None:
    adapter = _adapter(_server())
    try:
        models = await adapter.list_models()
        assert [m.id for m in models] == ["BAAI/bge-large-en-v1.5"]
        caps = models[0].capabilities
        assert caps is not None and caps.operations is not None
        assert caps.operations.value == frozenset({"embedding"})
        assert caps.operations.provenance == "discovered"
    finally:
        await adapter.aclose()


async def test_reranker_server_discovers_the_rerank_operation() -> None:
    adapter = _adapter(_server("reranker"))
    try:
        models = await adapter.list_models()
        caps = models[0].capabilities
        assert caps is not None and caps.operations is not None
        assert caps.operations.value == frozenset({"rerank"})
    finally:
        await adapter.aclose()


# ---- embed wire mapping --------------------------------------------------------------


async def test_embed_batch_maps_inputs_and_reports_normalized() -> None:
    adapter = _adapter(_server())
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(model="anything", inputs=("a", "b", "c"))
        )
        assert len(result.vectors) == 3
        assert result.vectors[0] == pytest.approx((0.1, 0.2))
        # normalize defaults true server-side (verified 2026-08-12); nothing overrode it.
        assert result.normalized is True
        assert result.usage is None
    finally:
        await adapter.aclose()


async def test_embed_normalize_override_is_reported_not_guessed() -> None:
    adapter = _adapter(_server())
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(
                model="anything", inputs=("a",), extra_options={"normalize": False}
            )
        )
        assert result.normalized is False
    finally:
        await adapter.aclose()


async def test_embed_forwards_dimensions() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return httpx2.Response(200, json=[[0.1, 0.2]])

    adapter = _adapter(handler)
    try:
        await adapter.embed(EmbeddingWireRequest(model="m", inputs=("x",), dimensions=256))
        assert seen["dimensions"] == 256
    finally:
        await adapter.aclose()


async def test_embed_vector_count_mismatch_is_rejected() -> None:
    adapter = _adapter(lambda request: httpx2.Response(200, json=[[0.1]]))
    try:
        with pytest.raises(ProviderError, match="returned 1 vectors for 2 inputs"):
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("a", "b")))
    finally:
        await adapter.aclose()


async def test_error_body_maps_with_retry_after() -> None:
    adapter = _adapter(_server("rate_limited"))
    try:
        with pytest.raises(RateLimitError) as excinfo:
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("x",)))
        assert excinfo.value.retry_after_s == 1.0
        assert "overloaded" in (excinfo.value.detail or "")
    finally:
        await adapter.aclose()


# ---- rerank wire mapping -------------------------------------------------------------


async def test_rerank_sorts_descending_and_maps_caller_indexes() -> None:
    adapter = _adapter(_server())
    try:
        result = await adapter.rerank(
            RerankWireRequest(
                model="anything",
                query="q",
                documents=(
                    RerankWireDocument(index=10, text="low score"),
                    RerankWireDocument(index=11, text="high score"),
                    RerankWireDocument(index=12, text="mid score"),
                ),
            )
        )
        # Server answered in index order with scores 0.1, 0.8, 0.7; adapter sorts.
        assert [(item.index, item.score) for item in result.items] == [
            (11, 0.8),
            (12, pytest.approx(0.7)),
            (10, 0.1),
        ]
    finally:
        await adapter.aclose()


async def test_rerank_applies_top_n_client_side() -> None:
    adapter = _adapter(_server())
    try:
        result = await adapter.rerank(
            RerankWireRequest(
                model="anything",
                query="q",
                documents=(
                    RerankWireDocument(index=0, text="a"),
                    RerankWireDocument(index=1, text="b"),
                    RerankWireDocument(index=2, text="c"),
                ),
                top_n=1,
            )
        )
        assert len(result.items) == 1
        assert result.items[0].index == 1
    finally:
        await adapter.aclose()


# ---- end to end + conformance ---------------------------------------------------------


async def _build_client(scenario: str) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "tei",
                base_url="http://127.0.0.1:8080",
                transport=httpx2.MockTransport(_server(scenario)),
            )
        ],
        route=ai.Route(
            targets=("tei:bge",), retry=ai.Retry(max_attempts=2, backoff_base_s=0.0)
        ),
        use_default_catalog=False,
    )


async def test_client_embed_end_to_end() -> None:
    client = await _build_client("default")
    try:
        result = await client.embed(["hello", "world"], target="tei:bge")
        assert len(result.vectors) == 2
        assert result.space.provider_id == "tei"
        assert result.space.normalized is True
    finally:
        await client.aclose()


HARNESS = ConformanceHarness(
    provider_id="tei",
    model="bge",
    build_client=_build_client,
    # Retrieval-only: every generation flag is off because there is no generate() at
    # all — the first harness where that is the honest declaration, not a limitation.
    supports=Capabilities(
        non_streaming=False,
        streaming=False,
        ttft=False,
        usage=False,
        tools=False,
        reasoning=False,
        structured_output=False,
        repair=False,
        retry_after=False,
        error_mapping=False,
        byte_cap=False,
        embedding=True,
        rerank=True,
    ),
)


async def test_tei_conformance() -> None:
    results = await run_conformance(HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"
