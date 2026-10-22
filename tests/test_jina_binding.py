"""Public-client controls for the Jina retrieval binding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.providers.base import EmbeddingWireRequest, ProviderConfig
from anyinfer.providers.jina import JinaAdapter
from anyinfer.types.operations import EmbeddingInputIntent

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jina-wire-v1" / "inputs.json"


def _cases() -> dict[str, dict[str, Any]]:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    return {case["id"]: case for case in payload["cases"]}


def _client(handler: Any, *, headers: dict[str, str] | None = None) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings(
                provider_id="jina",
                api_key="jina-test-key",
                headers=headers or {},
                transport=httpx2.MockTransport(handler),
            )
        ],
        retain_raw=True,
        use_default_catalog=False,
    )


def _assert_content_free_manifest(result: Any, *content: str) -> None:
    assert result.manifest is not None
    manifest = json.loads(result.manifest.to_json())
    assert result.manifest.route.resolved == str(result.target)
    for value in content:
        assert value not in _string_values(manifest)


def _string_values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_string_values(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_string_values(item) for item in value))
    return set()


async def test_jina_fixture_v3_embedding_through_public_client() -> None:
    case = _cases()["embedding-v3-indexed"]
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=case["response"])

    client = _client(handler)
    try:
        result = await client.embed(**case["request"], target=case["target"])
    finally:
        await client.aclose()

    assert seen["path"] == "/v1/embeddings"
    assert seen["headers"]["authorization"] == "Bearer jina-test-key"
    assert seen["headers"]["content-type"] == "application/json"
    assert seen["headers"]["accept"] == "application/json"
    assert seen["body"] == {
        "model": "jina-embeddings-v3",
        "input": ["alpha", "beta"],
        "task": "retrieval.query",
        "dimensions": 2,
    }
    assert [vector.values for vector in result.vectors] == [(0.1, 0.2), (0.3, 0.4)]
    assert result.raw == case["response"]
    assert result.usage.total_tokens == 7
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    _assert_content_free_manifest(result, "alpha", "beta")


async def test_jina_fixture_v5_clustering_keeps_raw_usage_details() -> None:
    case = _cases()["embedding-v5-clustering"]
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=case["response"])

    client = _client(handler)
    try:
        result = await client.embed(**case["request"], target=case["target"])
    finally:
        await client.aclose()

    assert seen["body"] == {
        "model": "jina-embeddings-v5-text-small",
        "input": ["cluster input"],
        "task": "clustering",
    }
    assert result.raw == case["response"]
    assert result.raw["usage"] == {"total_tokens": 9, "prompt_tokens": 8, "image_tokens": 1}
    assert result.usage.total_tokens == 9
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    _assert_content_free_manifest(result, "cluster input")


async def test_jina_fixture_rerank_through_public_client() -> None:
    case = _cases()["rerank-positional-results"]
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=case["response"])

    client = _client(handler)
    try:
        documents = [ai.RerankDocument(**document) for document in case["request"]["documents"]]
        result = await client.rerank(
            case["request"]["query"],
            documents,
            target=case["target"],
            top_n=case["request"]["top_n"],
        )
    finally:
        await client.aclose()

    assert seen == {
        "path": "/v1/rerank",
        "body": {
            "model": "jina-reranker-v3",
            "query": "question",
            "documents": ["first", "second"],
            "top_n": 1,
        },
    }
    assert [(item.index, item.document_id, item.score) for item in result.items] == [
        (1, "doc-a", 0.9),
    ]
    assert result.raw == case["response"]
    assert result.usage.total_tokens == 11
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    _assert_content_free_manifest(result, "question", "first", "second", "doc-z", "doc-a")


@pytest.mark.parametrize(
    ("model", "input_type", "task"),
    [
        ("jina-embeddings-v3", "query", "retrieval.query"),
        ("jina-embeddings-v3", "document", "retrieval.passage"),
        ("jina-embeddings-v3", "classification", "classification"),
        ("jina-embeddings-v3", "clustering", "separation"),
        ("jina-embeddings-v4", "query", "retrieval.query"),
        ("jina-embeddings-v4", "document", "retrieval.passage"),
        ("jina-embeddings-v4", "classification", None),
        ("jina-embeddings-v4", "clustering", None),
        ("jina-embeddings-v5-text-small", "query", "retrieval.query"),
        ("jina-embeddings-v5-text-small", "document", "retrieval.passage"),
        ("jina-embeddings-v5-text-small", "classification", "classification"),
        ("jina-embeddings-v5-text-small", "clustering", "clustering"),
        ("jina-embeddings-v5-text-nano", "query", "retrieval.query"),
        ("jina-embeddings-v5-text-nano", "document", "retrieval.passage"),
        ("jina-embeddings-v5-text-nano", "classification", "classification"),
        ("jina-embeddings-v5-text-nano", "clustering", "clustering"),
        ("jina-embeddings-v5-omni-small", "query", "retrieval.query"),
        ("jina-embeddings-v5-omni-small", "document", "retrieval.passage"),
        ("jina-embeddings-v5-omni-small", "classification", "classification"),
        ("jina-embeddings-v5-omni-small", "clustering", "clustering"),
        ("jina-embeddings-v5-omni-nano", "query", "retrieval.query"),
        ("jina-embeddings-v5-omni-nano", "document", "retrieval.passage"),
        ("jina-embeddings-v5-omni-nano", "classification", "classification"),
        ("jina-embeddings-v5-omni-nano", "clustering", "clustering"),
        ("future-jina-model", "query", "retrieval.query"),
        ("future-jina-model", "document", "retrieval.passage"),
        ("future-jina-model", "classification", "classification"),
        ("future-jina-model", "clustering", "separation"),
        ("jina-embeddings-v5-future", "query", "retrieval.query"),
        ("jina-embeddings-v5-future", "document", "retrieval.passage"),
        ("jina-embeddings-v5-future", "classification", "classification"),
        ("jina-embeddings-v5-future", "clustering", "separation"),
    ],
)
async def test_jina_model_specific_task_vocabulary(
    model: str, input_type: EmbeddingInputIntent, task: str | None
) -> None:
    adapter = JinaAdapter(ProviderConfig(provider_id="jina", api_key="test-key"))
    try:
        payload = adapter._build_embedding_payload(
            EmbeddingWireRequest(model=model, inputs=("input",), input_type=input_type)
        )
    finally:
        await adapter.aclose()
    if task is None:
        assert "task" not in payload
    else:
        assert payload["task"] == task


async def test_jina_provider_options_overlay_task_last() -> None:
    adapter = JinaAdapter(ProviderConfig(provider_id="jina", api_key="test-key"))
    try:
        payload = adapter._build_embedding_payload(
            EmbeddingWireRequest(
                model="jina-embeddings-v5-text-small",
                inputs=("input",),
                input_type="clustering",
                dimensions=512,
                extra_options={"task": "caller-task", "dimensions": 64},
            )
        )
    finally:
        await adapter.aclose()
    assert payload["task"] == "caller-task"
    assert payload["dimensions"] == 64


@pytest.mark.parametrize("input_type", ["classification", "clustering"])
async def test_jina_v4_unsupported_intent_warns_and_omits_task(
    input_type: EmbeddingInputIntent,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})

    client = _client(handler)
    try:
        result = await client.embed(
            ["input"], target="jina:jina-embeddings-v4", input_type=input_type
        )
    finally:
        await client.aclose()

    assert "task" not in seen["body"]
    assert result.warnings == (
        f"jina:jina-embeddings-v4 does not support input_type='{input_type}' "
        "(supported: query, document); the provider's own handling applies",
    )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({"data": [{"index": True, "embedding": [0.1]}]}, "integer 'index'"),
        ({"data": []}, "returned 0 vectors for 1 inputs"),
    ],
)
async def test_jina_public_client_rejects_invalid_embedding_indexes(
    response: dict[str, Any], message: str
) -> None:
    client = _client(lambda request: httpx2.Response(200, json=response))
    try:
        with pytest.raises(ai.AllTargetsFailedError) as raised:
            await client.embed(["input"], target="jina:jina-embeddings-v3")
    finally:
        await client.aclose()
    assert raised.value.attempts[0].error is not None
    assert message in raised.value.attempts[0].error.detail
