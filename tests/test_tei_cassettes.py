"""Sanitized live cassettes for Text Embeddings Inference's embed and rerank dialects.

Recorded against two real TEI servers (2026-10-22,
`text-embeddings-inference:cpu-1.9.4@sha256:8419f533857b503ebf6ec292a95d4f1cf9c0464ac8b8abeef39518cf110e5726`,
version 1.9.4): `BAAI/bge-small-en-v1.5` at revision
`5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` for embeddings on port 8080 and
`BAAI/bge-reranker-base` at revision `2cfc18c9415c912f9d8155881c133215df768a70`
for reranking on port 8081. TEI serves **one model per server**,
so a deployment that does both is two processes, and the cassettes mirror that rather than
pretending one endpoint answers both.

This is the wire-truth complement to `tests/test_tei.py`'s mock-transport suite.

To re-record, delete the cassette files first (recording *appends*), start both servers,
and run with `ANYINFER_RECORD_CASSETTES=1`:

    docker run -d --platform linux/amd64 -p 127.0.0.1:8080:80 \
        ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4@sha256:8419f533857b503ebf6ec292a95d4f1cf9c0464ac8b8abeef39518cf110e5726 \
        --model-id BAAI/bge-small-en-v1.5 --revision 5c38ec7c405ec4b44b94cc5a9bb96e735b38267a
    docker run -d --platform linux/amd64 -p 127.0.0.1:8081:80 \
        ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4@sha256:8419f533857b503ebf6ec292a95d4f1cf9c0464ac8b8abeef39518cf110e5726 \
        --model-id BAAI/bge-reranker-base --revision 2cfc18c9415c912f9d8155881c133215df768a70
"""

from __future__ import annotations

from collections.abc import Callable

import anyinfer as ai
from anyinfer.testing.cassettes import Cassette, CassetteTransport
from anyinfer.types.results import Usage


def _tei_client(cassette: Cassette, recording: bool, *, port: int) -> ai.AsyncClient:
    transport = CassetteTransport(cassette, record=recording)
    return ai.AsyncClient(
        [ai.ProviderSettings.of("tei", base_url=f"http://127.0.0.1:{port}", transport=transport)],
        use_default_catalog=False,
    )


def _assert_public_usage_is_unknown(usage: Usage | None) -> None:
    """Assert the public result's normalized unknown-accounting representation."""
    assert usage is not None
    assert (
        usage.input_tokens,
        usage.output_tokens,
        usage.total_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
        usage.reasoning_tokens,
        usage.cost_usd,
        usage.search_units,
    ) == (None, None, None, None, None, None, None, None)
    assert usage.server_tool_uses == {}


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
        # The adapter's raw usage is None; the public result normalizes that into an
        # explicit object whose accounting fields remain unknown rather than zero.
        _assert_public_usage_is_unknown(result.usage)
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
        _assert_public_usage_is_unknown(result.usage)
    finally:
        await client.aclose()
        if anyinfer_recording:
            cassette.save()
