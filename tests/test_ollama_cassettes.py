"""Sanitized live cassettes for Ollama's NDJSON generate and embed dialects.

Recorded against a real local Ollama server (2026-08-14, `qwen3:0.6b` for generation,
`nomic-embed-text` for embedding) with ``ANYINFER_RECORD_CASSETTES=1``; replayed offline
in CI. This is the wire-truth complement to `tests/test_ollama.py`'s mock-transport
suite, and closed the embedding/reranking plan's Ollama live lane — a real Ollama server
was previously unavailable to verify against; its "verification" before this session was
documentation research only.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

import anyinfer as ai
from anyinfer.testing.cassettes import Cassette, CassetteTransport


def _ollama_client(cassette: Cassette, recording: bool) -> ai.AsyncClient:
    transport = CassetteTransport(cassette, record=recording)
    return ai.AsyncClient(
        [ai.ProviderSettings.of("ollama", base_url="http://127.0.0.1:11434", transport=transport)],
        use_default_catalog=False,
    )


async def test_generate_against_recorded_wire_traffic(
    anyinfer_cassette: Callable[[str], Cassette], anyinfer_recording: bool
) -> None:
    cassette = anyinfer_cassette("ollama_generate")
    client = _ollama_client(cassette, anyinfer_recording)
    try:
        result = await client.generate("Reply with exactly one word: hello.", target="ollama:qwen3:0.6b")
        assert result.text.strip()
        assert result.usage is not None
        assert result.usage.input_tokens is not None
        assert result.usage.output_tokens is not None
    finally:
        await client.aclose()
        if anyinfer_recording:
            cassette.save()


async def test_embed_against_recorded_wire_traffic(
    anyinfer_cassette: Callable[[str], Cassette], anyinfer_recording: bool
) -> None:
    cassette = anyinfer_cassette("ollama_embed")
    client = _ollama_client(cassette, anyinfer_recording)
    try:
        result = await client.embed(
            ["the moon landing happened in 1969", "a recipe for sourdough bread"],
            target="ollama:nomic-embed-text",
        )
        assert len(result.vectors) == 2
        assert len(result.vectors[0]) == len(result.vectors[1])
        assert result.vectors[0] != result.vectors[1]
    finally:
        await client.aclose()
        if anyinfer_recording:
            cassette.save()


def test_committed_cassettes_carry_no_authorization(  # defensive; recording redacts
    anyinfer_cassette: Callable[[str], Cassette],
) -> None:
    for name in ("ollama_generate", "ollama_embed"):
        cassette = anyinfer_cassette(name)
        if not cassette.path.exists():
            pytest.skip("cassette not recorded yet")
        text = cassette.path.read_text(encoding="utf-8")
        assert "Bearer " not in text
        assert "authorization" not in text.lower()
