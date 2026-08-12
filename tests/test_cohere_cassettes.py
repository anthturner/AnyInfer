"""Sanitized live cassettes for Cohere's embed and rerank dialects.

Recorded against the real API (2026-08-12) with ``ANYINFER_RECORD_CASSETTES=1`` and a
real ``CO_API_KEY``; replayed offline in CI. The committed cassettes carry no secrets —
recording passes every body through the redaction registry and strikes auth headers
wholesale — which makes these the wire-truth complement to the mock-transport suite:
the mocks assert what we *believe* the dialect is, these assert what it actually was.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest

import anyinfer as ai
from anyinfer.testing.cassettes import Cassette, CassetteTransport


def _cohere_client(cassette: Cassette, recording: bool) -> ai.AsyncClient:
    api_key = os.environ.get("CO_API_KEY", "cassette-replay-key")
    transport = CassetteTransport(cassette, record=recording)
    return ai.AsyncClient(
        [ai.ProviderSettings.of("cohere", api_key=api_key, transport=transport)],
        use_default_catalog=False,
    )


async def test_embed_against_recorded_wire_traffic(
    anyinfer_cassette: Callable[[str], Cassette], anyinfer_recording: bool
) -> None:
    cassette = anyinfer_cassette("cohere_embed")
    client = _cohere_client(cassette, anyinfer_recording)
    try:
        result = await client.embed(
            ["the moon landing happened in 1969", "a recipe for sourdough bread"],
            target="cohere:embed-english-light-v3.0",
            input_type="document",
        )
        assert len(result.vectors) == 2
        assert all(len(v) == 384 for v in result.vectors)
        assert result.usage.input_tokens is not None
        assert result.space.model == "embed-english-light-v3.0"
    finally:
        await client.aclose()
        if anyinfer_recording:
            cassette.save()


async def test_rerank_against_recorded_wire_traffic(
    anyinfer_cassette: Callable[[str], Cassette], anyinfer_recording: bool
) -> None:
    cassette = anyinfer_cassette("cohere_rerank")
    client = _cohere_client(cassette, anyinfer_recording)
    try:
        result = await client.rerank(
            "which text is about the moon landing",
            ["a recipe for sourdough bread", "the moon landing happened in 1969"],
            target="cohere:rerank-v3.5",
            top_n=2,
        )
        assert result.items[0].document_id == "1"
        scores = [item.score for item in result.items]
        assert scores == sorted(scores, reverse=True)
        # Live rerank bills search units, never tokens (contracts/cohere.md).
        assert result.usage.search_units == 1
        assert result.usage.input_tokens is None
    finally:
        await client.aclose()
        if anyinfer_recording:
            cassette.save()


def test_committed_cassettes_carry_no_authorization(  # defensive; recording redacts
    anyinfer_cassette: Callable[[str], Cassette],
) -> None:
    for name in ("cohere_embed", "cohere_rerank"):
        cassette = anyinfer_cassette(name)
        if not cassette.path.exists():
            pytest.skip("cassette not recorded yet")
        text = cassette.path.read_text(encoding="utf-8")
        # Request headers are never stored at all, and stored response bodies pass the
        # redaction registry — so no credential shape may survive into the file.
        assert "Bearer " not in text
        assert "authorization" not in text.lower()
