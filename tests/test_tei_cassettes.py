"""Sanitized live cassettes for Text Embeddings Inference's embed and rerank dialects.

Recorded against two real TEI servers (2026-08-24, `text-embeddings-inference:cpu-1.8`,
version 1.8.3): `BAAI/bge-small-en-v1.5` for embeddings on port 8080 and
`BAAI/bge-reranker-base` for reranking on port 8081. TEI serves **one model per server**,
so a deployment that does both is two processes, and the cassettes mirror that rather than
pretending one endpoint answers both.

This is the wire-truth complement to `tests/test_tei.py`'s mock-transport suite. Until
this recording, every TEI assertion in this repository came from reading the published
OpenAPI document -- the adapter had never exchanged a byte with the software it
translates.

To re-record, delete the cassette files first (recording *appends*), start both servers,
and run with `ANYINFER_RECORD_CASSETTES=1`:

    docker run -d -p 8080:80 ghcr.io/huggingface/text-embeddings-inference:cpu-1.8 \
        --model-id BAAI/bge-small-en-v1.5
    docker run -d -p 8081:80 ghcr.io/huggingface/text-embeddings-inference:cpu-1.8 \
        --model-id BAAI/bge-reranker-base
"""

from __future__ import annotations

from collections.abc import Callable

import anyinfer as ai
from anyinfer.testing.cassettes import Cassette, CassetteTransport


def _tei_client(cassette: Cassette, recording: bool, *, port: int) -> ai.AsyncClient:
    transport = CassetteTransport(cassette, record=recording)
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "tei", base_url=f"http://127.0.0.1:{port}", transport=transport
            )
        ],
        use_default_catalog=False,
    )


async def test_embed_against_recorded_wire_traffic(
    anyinfer_cassette: Callable[[str], Cassette], anyinfer_recording: bool
) -> None:
    """A bare array of arrays, in input order, with no usage block anywhere."""
    cassette = anyinfer_cassette("tei_embed")
    client = _tei_client(cassette, anyinfer_recording, port=8080)
    try:
        result = await client.embed(
            ["the moon landing happened in 1969", "a recipe for sourdough bread"],
            target="tei:bge-small-en-v1.5",
        )
        assert len(result.vectors) == 2
        assert len(result.vectors[0]) == len(result.vectors[1]) == 384
        assert result.vectors[0] != result.vectors[1]
        # TEI reports no token accounting at all. The contract says usage stays None
        # rather than zero, and a real response is what proves it.
        assert result.usage is None or result.usage.input_tokens is None
        assert result.space.provider_id == "tei"
        # Not measured from the vectors: it reports the `normalize` the request left in
        # force, which is the server's documented default.
        assert result.space.normalized is True
    finally:
        await client.aclose()
        if anyinfer_recording:
            cassette.save()


async def test_discovery_against_recorded_wire_traffic(
    anyinfer_cassette: Callable[[str], Cassette], anyinfer_recording: bool
) -> None:
    """`/info` carries the identity and the per-deployment limits, in a tagged object."""
    cassette = anyinfer_cassette("tei_info")
    client = _tei_client(cassette, anyinfer_recording, port=8080)
    try:
        models = await client.models("tei")
        assert [m.id for m in models] == ["BAAI/bge-small-en-v1.5"]
        capabilities = models[0].capabilities
        assert capabilities is not None
        assert capabilities.operations is not None
        assert capabilities.operations.value == frozenset({"embedding"})
    finally:
        await client.aclose()
        if anyinfer_recording:
            cassette.save()


async def test_rerank_against_recorded_wire_traffic(
    anyinfer_cassette: Callable[[str], Cassette], anyinfer_recording: bool
) -> None:
    """A second server, because a TEI deployment serves exactly one model."""
    cassette = anyinfer_cassette("tei_rerank")
    client = _tei_client(cassette, anyinfer_recording, port=8081)
    try:
        result = await client.rerank(
            "which text is about the moon landing",
            [
                "a recipe for sourdough bread",
                "apollo 11 landed on the moon in july 1969",
                "the rules of association football",
            ],
            target="tei:bge-reranker-base",
        )
        assert result.items[0].index == 1, (
            "the moon-landing document must rank first, and its caller-side index must "
            "survive TEI's positional `index` field"
        )
        scores = [item.score for item in result.items]
        assert scores == sorted(scores, reverse=True), (
            "TEI's OpenAPI document states no result order; the adapter sorts, and this "
            "asserts the sort rather than the server's happenstance ordering"
        )
    finally:
        await client.aclose()
        if anyinfer_recording:
            cassette.save()
