from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyinfer as ai
import httpx2
import pytest
from anyinfer.types.operations import EmbeddingSpace

from anyinfer_store import query_and_rerank
from anyinfer_store.errors import VectorStoreError


def _space() -> EmbeddingSpace:
    return EmbeddingSpace(provider_id="ollama", model="nomic-embed-text", dimensions=4)


def _cohere_rerank_handler() -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/v2/rerank")
        body = json.loads(request.content)
        # Deliberately reverse the input order so the test can prove reranking actually
        # changed something rather than just passing coarse order through untouched.
        n = len(body["documents"])
        ranked = [{"index": n - 1 - i, "relevance_score": 1.0 - i * 0.1} for i in range(n)]
        return httpx2.Response(
            200,
            json={"results": ranked, "meta": {"billed_units": {"search_units": 1}}},
        )

    return handler


def _client() -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "cohere", api_key="co-key", transport=httpx2.MockTransport(_cohere_rerank_handler())
            )
        ]
    )


async def test_query_and_rerank_reorders_coarse_candidates(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    space = _space()
    store.add("a", [1.0, 0.0, 0.0, 0.0], space=space, text="alpha doc")
    store.add("b", [0.9, 0.1, 0.0, 0.0], space=space, text="beta doc")
    store.add("c", [0.8, 0.2, 0.0, 0.0], space=space, text="gamma doc")

    client = _client()
    try:
        items = await query_and_rerank(
            store,
            [1.0, 0.0, 0.0, 0.0],
            "find alpha",
            space=space,
            client=client,
            rerank_target="cohere:rerank-v3.5",
            candidate_k=3,
        )
    finally:
        await client.aclose()
        store.close()

    assert len(items) == 3
    scores = [item.score for item in items]
    assert scores == sorted(scores, reverse=True)


async def test_query_and_rerank_refuses_when_text_is_missing(tmp_path: Path, open_store) -> None:
    store = open_store(tmp_path / "s.db")
    space = _space()
    store.add("a", [1.0, 0.0, 0.0, 0.0], space=space)  # no text=

    client = _client()
    try:
        with pytest.raises(VectorStoreError):
            await query_and_rerank(
                store,
                [1.0, 0.0, 0.0, 0.0],
                "find alpha",
                space=space,
                client=client,
                rerank_target="cohere:rerank-v3.5",
            )
    finally:
        await client.aclose()
        store.close()
