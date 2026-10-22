"""Text Embeddings Inference: native /embed and /rerank wire mapping (contracts/tei.md)."""

from __future__ import annotations

import asyncio
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
    state = {"calls": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/info"):
            info = dict(_INFO)
            if scenario == "reranker":
                info["model_id"] = "BAAI/bge-reranker-large"
                info["model_type"] = {"reranker": {}}
            return httpx2.Response(200, json=info)
        if scenario == "rate_limited" and state["calls"] == 0:
            state["calls"] += 1
            return httpx2.Response(
                429,
                json={"error": "model is overloaded", "error_type": "overloaded"},
                headers={"retry-after": "1"},
            )
        if path.endswith("/embed"):
            if scenario == "oversized":
                inputs = json.loads(request.content)["inputs"]
                return httpx2.Response(200, json=[[0.1] * 20_000 for _ in inputs])
            inputs = json.loads(request.content)["inputs"]
            return httpx2.Response(200, json=[[0.1 * (i + 1), 0.2] for i in range(len(inputs))])
        if path.endswith("/rerank"):
            if scenario == "oversized":
                body = json.loads(request.content)
                return httpx2.Response(
                    200,
                    json=[
                        {"index": i, "score": 0.5, "padding": "x" * 20_000}
                        for i in range(len(body["texts"]))
                    ],
                )
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


@pytest.mark.parametrize(
    ("model_type", "operations"),
    [
        ("embedding", frozenset({"embedding"})),
        ({"unknown": {}}, frozenset()),
        (None, None),
    ],
)
async def test_discovery_preserves_unknown_operations_and_does_not_hydrate_limits(
    model_type: Any, operations: frozenset[str] | None
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "model_id": "model",
                "model_type": model_type,
                "max_input_length": 12,
                "max_batch_tokens": 34,
                "max_client_batch_size": 56,
            },
        )

    adapter = _adapter(handler)
    try:
        (model,) = await adapter.list_models()
        assert model.capabilities is not None
        discovered = model.capabilities.operations
        assert (discovered.value if discovered is not None else None) == operations
        assert model.capabilities.context_window is None
        assert model.capabilities.max_output_tokens is None
        assert model.capabilities.embedding is None
    finally:
        await adapter.aclose()


async def test_discovery_keeps_operations_unknown_when_model_type_is_absent() -> None:
    adapter = _adapter(
        lambda request: httpx2.Response(
            200,
            json={
                "model_id": "model-without-type",
                "max_input_length": 12,
                "max_batch_tokens": 34,
            },
        )
    )
    try:
        (model,) = await adapter.list_models()
        assert model.capabilities is not None
        assert model.capabilities.operations is None
        assert model.capabilities.context_window is None
        assert model.capabilities.embedding is None
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


async def test_embed_preserves_base_path_header_precedence_and_operation_overrides() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        seen["headers"] = dict(request.headers)
        seen["payload"] = json.loads(request.content)
        return httpx2.Response(200, json=[[True, "2.5"]])

    adapter = TEIAdapter(
        ProviderConfig(
            provider_id="tei-custom",
            base_url="http://tei.test/native/",
            api_key="adapter-key",
            api_version="ignored-version",
            headers={"Authorization": "Bearer configured", "X-TEI-Test": "present"},
            options={"must_not": "reach-wire"},
            transport=httpx2.MockTransport(handler),
        )
    )
    try:
        result = await adapter.embed(
            EmbeddingWireRequest(
                model="advisory-only",
                inputs=("original",),
                dimensions=64,
                extra_options={
                    "inputs": ["operation-wins"],
                    "dimensions": 7,
                    "normalize": "not-a-bool",
                },
            )
        )
        assert seen["path"] == "/native/embed"
        assert seen["headers"]["authorization"] == "Bearer configured"
        assert seen["headers"]["x-tei-test"] == "present"
        assert seen["payload"] == {
            "inputs": ["operation-wins"],
            "dimensions": 7,
            "normalize": "not-a-bool",
        }
        assert result.vectors == ((1.0, 2.5),)
        assert result.dimensions == 2
        assert result.normalized is None
        assert result.usage is None
        assert result.raw == [[True, "2.5"]]
    finally:
        await adapter.aclose()


async def test_compute_and_timing_headers_do_not_create_public_usage() -> None:
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "tei",
                base_url="http://tei.test",
                transport=httpx2.MockTransport(
                    lambda request: httpx2.Response(
                        200,
                        json=[[0.1, 0.2]],
                        headers={
                            "x-compute-type": "gpu+optimized",
                            "x-compute-time": "99",
                            "x-request-duration-ms": "123",
                        },
                    )
                ),
            )
        ],
        use_default_catalog=False,
    )
    try:
        result = await client.embed("input", target="tei:model")
        assert result.usage is not None
        assert (
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.usage.total_tokens,
            result.usage.cache_read_tokens,
            result.usage.cache_write_tokens,
            result.usage.reasoning_tokens,
            result.usage.cost_usd,
            result.usage.search_units,
        ) == (None, None, None, None, None, None, None, None)
        assert result.usage.server_tool_uses == {}
    finally:
        await client.aclose()


async def test_numeric_string_nonfinite_embedding_reaches_public_core_rejection() -> None:
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "tei",
                base_url="http://tei.test",
                transport=httpx2.MockTransport(
                    lambda request: httpx2.Response(200, json=[["NaN"]])
                ),
            )
        ],
        use_default_catalog=False,
    )
    try:
        with pytest.raises(ValueError, match="must not contain NaN or infinite values"):
            await client.embed("input", target="tei:model")
    finally:
        await client.aclose()


async def test_embed_vector_count_mismatch_is_rejected() -> None:
    adapter = _adapter(lambda request: httpx2.Response(200, json=[[0.1]]))
    try:
        with pytest.raises(ProviderError, match="returned 1 vectors for 2 inputs"):
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("a", "b")))
    finally:
        await adapter.aclose()


async def test_embed_rejects_a_response_over_the_byte_cap() -> None:
    from anyinfer.errors import StreamProtocolError

    adapter = _adapter(lambda request: httpx2.Response(200, json=[[0.1] + [0.0] * 50]))
    try:
        with pytest.raises(StreamProtocolError, match="max_response_bytes"):
            await adapter.embed(
                EmbeddingWireRequest(model="m", inputs=("a",), max_response_bytes=32)
            )
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


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [
        ("0.5", 0.5),
        ("-1", None),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
    ],
)
async def test_tei_rate_limit_accepts_only_numeric_nonnegative_retry_after(
    retry_after: str, expected: float | None
) -> None:
    detail = "é" * 350
    adapter = _adapter(
        lambda request: httpx2.Response(
            429, json={"error": detail}, headers={"retry-after": retry_after}
        )
    )
    try:
        with pytest.raises(RateLimitError) as excinfo:
            await adapter.embed(EmbeddingWireRequest(model="m", inputs=("x",)))
        assert excinfo.value.provider == "tei"
        assert excinfo.value.phase == "generate"
        assert excinfo.value.http_status == 429
        assert excinfo.value.retry_after_s == expected
        assert excinfo.value.detail == "é" * 300
    finally:
        await adapter.aclose()


async def test_health_bounds_provider_failure_detail() -> None:
    adapter = _adapter(lambda request: httpx2.Response(503, content=("x" * 250).encode()))
    try:
        health = await adapter.health()
        assert health.ok is False
        assert health.detail == "x" * 200
    finally:
        await adapter.aclose()


async def test_caller_cancellation_reaches_transport_and_adapter_close_closes_transport() -> None:
    transport = _HeldTransport()
    adapter = TEIAdapter(ProviderConfig(provider_id="tei", transport=transport, timeout_s=30.0))
    pending = asyncio.create_task(adapter.embed(EmbeddingWireRequest(model="m", inputs=("x",))))
    await transport.entered.wait()
    pending.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert transport.cancelled.is_set()
    finally:
        await adapter.aclose()
    assert transport.closed is True


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


async def test_rerank_stably_sorts_ties_and_maps_non_contiguous_indexes() -> None:
    body = [
        {"index": 2, "score": 0.8},
        {"index": 0, "score": 0.8},
        {"index": 1, "score": 0.1},
    ]
    adapter = _adapter(lambda request: httpx2.Response(200, json=body))
    try:
        result = await adapter.rerank(
            RerankWireRequest(
                model="m",
                query="q",
                documents=(
                    RerankWireDocument(index=10, text="a"),
                    RerankWireDocument(index=40, text="b"),
                    RerankWireDocument(index=90, text="c"),
                ),
                top_n=2,
            )
        )
        assert [(item.index, item.score) for item in result.items] == [(90, 0.8), (10, 0.8)]
        assert result.usage is None
        assert result.raw == body
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    "rank",
    [
        {"index": True, "score": 0.5},
        {"index": "0", "score": 0.5},
        {"index": 0, "score": True},
        {"index": 0, "score": "0.5"},
    ],
)
async def test_rerank_rejects_boolean_or_string_index_and_score(rank: dict[str, Any]) -> None:
    adapter = _adapter(lambda request: httpx2.Response(200, json=[rank]))
    try:
        with pytest.raises(ProviderError) as excinfo:
            await adapter.rerank(
                RerankWireRequest(
                    model="m",
                    query="q",
                    documents=(RerankWireDocument(index=7, text="d"),),
                )
            )
        assert excinfo.value.phase == "validate"
    finally:
        await adapter.aclose()


async def test_rerank_rejects_a_response_over_the_byte_cap() -> None:
    from anyinfer.errors import StreamProtocolError

    adapter = _adapter(
        lambda request: httpx2.Response(
            200, json=[{"index": 0, "score": 0.5, "padding": "x" * 200}]
        )
    )
    try:
        with pytest.raises(StreamProtocolError, match="max_response_bytes"):
            await adapter.rerank(
                RerankWireRequest(
                    model="m",
                    query="q",
                    documents=(RerankWireDocument(index=0, text="d"),),
                    max_response_bytes=32,
                )
            )
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
        route=ai.Route(targets=("tei:bge",), retry=ai.Retry(max_attempts=2, backoff_base_s=0.0)),
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


class _HeldTransport(httpx2.AsyncBaseTransport):
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.closed = False

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("held transport unexpectedly completed")

    async def aclose(self) -> None:
        self.closed = True
