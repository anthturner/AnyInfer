"""POST /v1/embeddings and POST /v1/anyinfer/rerank on the sidecar frontend.

Both are thin wire codecs over `AsyncClient.embed`/`AsyncClient.rerank`; these tests drive
them through Starlette's test client against an in-process fake provider, exercising the
real ASGI app without binding a port or a network call.
"""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.registry import ProviderRegistry
from anyinfer.testing import FakeEmbeddingRerankProvider, ScriptedEmbeddingFailure

starlette = pytest.importorskip("starlette", reason="requires the [serve] extra")
from starlette.testclient import TestClient  # noqa: E402

from anyinfer.serve.app import create_app  # noqa: E402


def _registry_with_fake(fake: FakeEmbeddingRerankProvider) -> ProviderRegistry:
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    fake.register(registry)
    return registry


def _client(fake: FakeEmbeddingRerankProvider, **app_kwargs: object) -> TestClient:
    registry = _registry_with_fake(fake)
    async_client = ai.AsyncClient(
        providers=[ai.ProviderSettings.of(fake.provider_id)],
        registry=registry,
        use_default_catalog=False,
    )
    app = create_app(async_client, **app_kwargs)  # type: ignore[arg-type]
    return TestClient(app)


# ---- embeddings ---------------------------------------------------------------------


def test_embeddings_scalar_input() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    http = _client(fake)

    response = http.post(
        "/v1/embeddings", json={"model": "fake-embed:small", "input": "hello"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert len(body["data"]) == 1
    assert len(body["data"][0]["embedding"]) == 4
    assert body["data"][0]["index"] == 0
    assert body["model"] == "fake-embed:small"


def test_embeddings_batch_input_preserves_order() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    http = _client(fake)

    response = http.post(
        "/v1/embeddings",
        json={"model": "fake-embed:small", "input": ["a", "b", "c"]},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [entry["index"] for entry in data] == [0, 1, 2]


def test_embeddings_missing_model_is_400() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    http = _client(fake)

    response = http.post("/v1/embeddings", json={"input": "hi"})

    assert response.status_code == 400
    assert "model" in response.json()["error"]["message"]


def test_embeddings_missing_input_is_400() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    http = _client(fake)

    response = http.post("/v1/embeddings", json={"model": "fake-embed:small"})

    assert response.status_code == 400


def test_embeddings_rejects_base64_encoding_format() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    http = _client(fake)

    response = http.post(
        "/v1/embeddings",
        json={"model": "fake-embed:small", "input": "hi", "encoding_format": "base64"},
    )

    assert response.status_code == 400


def test_embeddings_provider_error_maps_to_http_status() -> None:
    # The default route retries a single target twice; enough failures to exhaust that
    # budget are needed to actually observe the mapped error status rather than a
    # transparently-retried success.
    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        embedding_failures={
            "small": [ScriptedEmbeddingFailure(kind="rate-limit", retry_after_s=0.0)] * 5
        },
    )
    http = _client(fake)

    response = http.post("/v1/embeddings", json={"model": "fake-embed:small", "input": "hi"})

    # AllTargetsFailedError carries no http_status of its own, so the generic error
    # mapping's fallback applies.
    assert response.status_code == 502


def test_embeddings_requires_auth_when_token_configured() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    http = _client(fake, auth_token="secret")

    response = http.post("/v1/embeddings", json={"model": "fake-embed:small", "input": "hi"})
    assert response.status_code == 401

    authed = http.post(
        "/v1/embeddings",
        json={"model": "fake-embed:small", "input": "hi"},
        headers={"authorization": "Bearer secret"},
    )
    assert authed.status_code == 200


# ---- rerank -------------------------------------------------------------------------


def test_rerank_plain_string_documents() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    http = _client(fake)

    response = http.post(
        "/v1/anyinfer/rerank",
        json={
            "model": "fake-embed:ranker",
            "query": "capital of France",
            "documents": ["Paris is the capital of France.", "Berlin is in Germany."],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "anyinfer.rerank"
    assert len(body["results"]) == 2
    assert body["results"][0]["relevance_score"] >= body["results"][1]["relevance_score"]
    assert body["results"][0]["document_id"] == "0"


def test_rerank_object_documents_with_ids() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    http = _client(fake)

    response = http.post(
        "/v1/anyinfer/rerank",
        json={
            "model": "fake-embed:ranker",
            "query": "France",
            "documents": [
                {"id": "doc-a", "text": "Paris France"},
                {"id": "doc-b", "text": "Berlin Germany"},
            ],
        },
    )

    assert response.status_code == 200
    ids = {item["document_id"] for item in response.json()["results"]}
    assert ids == {"doc-a", "doc-b"}


def test_rerank_top_n() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    http = _client(fake)

    response = http.post(
        "/v1/anyinfer/rerank",
        json={
            "model": "fake-embed:ranker",
            "query": "France",
            "documents": ["Paris France", "Berlin Germany"],
            "top_n": 1,
        },
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


def test_rerank_return_documents() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    http = _client(fake)

    response = http.post(
        "/v1/anyinfer/rerank",
        json={
            "model": "fake-embed:ranker",
            "query": "France",
            "documents": ["Paris France"],
            "return_documents": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["document"]["text"] == "Paris France"


def test_rerank_missing_query_is_400() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    http = _client(fake)

    response = http.post(
        "/v1/anyinfer/rerank",
        json={"model": "fake-embed:ranker", "documents": ["a"]},
    )

    assert response.status_code == 400


def test_rerank_empty_documents_is_400() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    http = _client(fake)

    response = http.post(
        "/v1/anyinfer/rerank",
        json={"model": "fake-embed:ranker", "query": "q", "documents": []},
    )

    assert response.status_code == 400


def test_rerank_malformed_document_entry_is_400() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    http = _client(fake)

    response = http.post(
        "/v1/anyinfer/rerank",
        json={"model": "fake-embed:ranker", "query": "q", "documents": [123]},
    )

    assert response.status_code == 400


# ---- unaffected surfaces --------------------------------------------------------------


def test_unmodeled_v1_endpoint_still_404s() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    http = _client(fake)

    response = http.post("/v1/images/generations", json={})

    assert response.status_code == 404
