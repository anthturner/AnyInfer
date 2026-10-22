"""Public-client controls for the native Voyage retrieval binding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

import anyinfer as ai

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "voyage-wire-v1" / "inputs.json"


def _cases() -> dict[str, dict[str, Any]]:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    return {case["id"]: case for case in payload["cases"]}


def _client(handler: Any, *, headers: dict[str, str] | None = None) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings(
                provider_id="voyage",
                api_key="voyage-test-key",
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


async def test_voyage_fixture_embedding_through_public_client() -> None:
    case = _cases()["embedding-indexed"]
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
    assert seen["headers"]["authorization"] == "Bearer voyage-test-key"
    assert seen["headers"]["content-type"] == "application/json"
    assert seen["headers"]["accept"] == "application/json"
    assert seen["body"] == {
        "model": "voyage-3.5",
        "input": ["alpha", "beta"],
        "input_type": "query",
        "output_dimension": 2,
    }
    assert [vector.values for vector in result.vectors] == [(0.1, 0.2), (0.3, 0.4)]
    assert result.raw == case["response"]
    assert result.usage.total_tokens == 7
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    _assert_content_free_manifest(result, "alpha", "beta")


async def test_voyage_fixture_rerank_through_public_client() -> None:
    case = _cases()["rerank-positional"]
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
            "model": "rerank-2.5",
            "query": "question",
            "documents": ["first", "second"],
            "top_k": 1,
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


async def test_voyage_headers_options_and_malformed_usage_remain_literal() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1]}], "usage": {"total_tokens": True}},
        )

    client = _client(handler, headers={"X-Voyage-Trace": "control"})
    try:
        result = await client.embed(
            ["input"],
            target="voyage:voyage-3.5",
            provider_options={"voyage": {"truncation": 32}},
        )
    finally:
        await client.aclose()

    assert seen["headers"]["authorization"] == "Bearer voyage-test-key"
    assert seen["headers"]["x-voyage-trace"] == "control"
    assert seen["body"] == {
        "model": "voyage-3.5",
        "input": ["input"],
        "truncation": 32,
    }
    assert result.usage.total_tokens is None
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({"data": [{"index": True, "embedding": [0.1]}]}, "integer 'index'"),
        ({"data": []}, "returned 0 vectors for 1 inputs"),
    ],
)
async def test_voyage_public_client_rejects_invalid_embedding_indexes(
    response: dict[str, Any], message: str
) -> None:
    client = _client(lambda request: httpx2.Response(200, json=response))
    try:
        with pytest.raises(ai.AllTargetsFailedError) as raised:
            await client.embed(["input"], target="voyage:voyage-3.5")
    finally:
        await client.aclose()
    assert raised.value.attempts[0].error is not None
    assert message in raised.value.attempts[0].error.detail
