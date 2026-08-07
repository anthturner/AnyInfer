"""Distillation: map/reduce over the client, hierarchical reduce, and cost honesty."""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer.context import ContextDocument, distill, distill_sync
from anyinfer.errors import ConfigError
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

BIG_TEXT = "\n\n".join(f"Section {i}: facts about subject {i}." for i in range(400))


def _client(server: FakeOpenAIServer, **kwargs: object) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        **kwargs,  # type: ignore[arg-type]
    )


def _sync_client(server: FakeOpenAIServer) -> ai.Client:
    return ai.Client(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ]
    )


TARGET = "openai-compat:fake-model-small"


# ---- the protocol --------------------------------------------------------------------


def test_async_client_satisfies_the_structural_protocol():
    """Distill takes the client by protocol so the subpackage never imports it."""
    from anyinfer.context import SupportsGenerate

    assert isinstance(ai.AsyncClient(), SupportsGenerate)


def test_sync_client_satisfies_the_sync_protocol():
    from anyinfer.context.distill import SupportsGenerateSync

    client = ai.Client()
    try:
        assert isinstance(client, SupportsGenerateSync)
    finally:
        client.close()


# ---- map/reduce ----------------------------------------------------------------------


async def test_a_short_source_still_maps_and_reduces():
    server = FakeOpenAIServer(FakeResponse(text="a note"))
    async with _client(server) as client:
        result = await distill(
            "a little text", "summarize", client=client, target=TARGET, chunk_tokens=512
        )

    assert result.chunk_count == 1
    assert result.calls == 2, "one map call plus one reduce call"
    assert result.text == "a note"


async def test_a_long_source_splits_into_several_map_calls():
    server = FakeOpenAIServer(FakeResponse(text="note"))
    async with _client(server) as client:
        result = await distill(
            BIG_TEXT, "summarize", client=client, target=TARGET, chunk_tokens=128
        )

    assert result.chunk_count > 1
    assert result.calls == result.chunk_count + 1
    assert len(result.notes) == result.chunk_count


async def test_usage_sums_across_every_call():
    """Each call is a separate charge, so counts add rather than overlaying."""
    server = FakeOpenAIServer(FakeResponse(text="note"))
    async with _client(server) as client:
        result = await distill(
            BIG_TEXT, "summarize", client=client, target=TARGET, chunk_tokens=128
        )

    # The fake reports 11 input / 7 output per call.
    assert result.usage.input_tokens == 11 * result.calls
    assert result.usage.output_tokens == 7 * result.calls


async def test_documents_split_per_document():
    server = FakeOpenAIServer(FakeResponse(text="note"))
    documents = [
        ContextDocument.of("a.md", "content about alpha\n"),
        ContextDocument.of("b.md", "content about beta\n"),
    ]
    async with _client(server) as client:
        result = await distill(
            documents, "summarize", client=client, target=TARGET, chunk_tokens=512
        )

    assert result.chunk_count == 2, "a document boundary is a chunk boundary"
    assert "a.md" in server.requests[0]["messages"][0]["content"]


async def test_an_empty_source_spends_nothing():
    server = FakeOpenAIServer(FakeResponse(text="unused"))
    async with _client(server) as client:
        result = await distill(
            "   ", "summarize", client=client, target=TARGET, chunk_tokens=512
        )

    assert result.calls == 0
    assert result.chunk_count == 0
    assert server.call_count == 0


# ---- the deterministic reducer -------------------------------------------------------


async def test_a_reducer_replaces_the_reduce_call():
    server = FakeOpenAIServer(FakeResponse(text="note"))
    async with _client(server) as client:
        result = await distill(
            BIG_TEXT,
            "summarize",
            client=client,
            target=TARGET,
            chunk_tokens=128,
            reducer=lambda notes: f"{len(notes)} notes merged",
        )

    assert result.calls == result.chunk_count, "no reduce call was spent"
    assert result.text == f"{result.chunk_count} notes merged"
    assert result.reduce_depth == 1


# ---- hierarchical reduce -------------------------------------------------------------


async def test_many_notes_reduce_hierarchically():
    """A single-pass merge would overflow; batching and recursing does not."""
    server = FakeOpenAIServer(FakeResponse(text="x" * 4000))
    overrides = {
        "openai-compat:fake-model-small": ai.ModelCapabilities(
            context_window=ai.Sourced(2_000, "override")
        )
    }
    async with _client(server, capability_overrides=overrides) as client:
        result = await distill(
            BIG_TEXT,
            "summarize",
            client=client,
            target=TARGET,
            chunk_tokens=128,
            max_output_tokens=256,
        )

    assert result.reduce_depth > 1, "notes too large for one reduce must recurse"
    assert result.calls > result.chunk_count + 1


# ---- unknown windows -----------------------------------------------------------------


async def test_an_unknown_window_demands_an_explicit_chunk_size():
    """Unknown stays unknown: the library never invents a context window."""
    server = FakeOpenAIServer(FakeResponse(text="note"))
    async with _client(server) as client:
        with pytest.raises(ConfigError) as excinfo:
            await distill(BIG_TEXT, "summarize", client=client, target=TARGET)

    assert excinfo.value.hint is not None
    assert "chunk_tokens" in excinfo.value.hint


async def test_a_known_window_derives_the_chunk_size():
    server = FakeOpenAIServer(FakeResponse(text="note"))
    overrides = {
        "openai-compat:fake-model-small": ai.ModelCapabilities(
            context_window=ai.Sourced(16_000, "override")
        )
    }
    async with _client(server, capability_overrides=overrides) as client:
        result = await distill(BIG_TEXT, "summarize", client=client, target=TARGET)

    assert result.chunk_count >= 1
    assert result.calls >= 2


# ---- output hygiene ------------------------------------------------------------------


async def test_scaffolding_labels_are_stripped_from_the_answer():
    server = FakeOpenAIServer(
        FakeResponse(text="## Chunk 2\n\nThe real answer.\n\n\n\nMore answer.")
    )
    async with _client(server) as client:
        result = await distill(
            "text", "summarize", client=client, target=TARGET, chunk_tokens=512
        )

    assert "Chunk 2" not in result.text
    assert "The real answer." in result.text
    assert "\n\n\n" not in result.text, "blank runs collapse"


async def test_intermediate_notes_are_excluded_from_the_repr():
    """Notes are payload-bearing; only the final answer belongs in a log line."""
    server = FakeOpenAIServer(
        [FakeResponse(text="an intermediate note"), FakeResponse(text="the answer")]
    )
    async with _client(server) as client:
        result = await distill(
            "text", "summarize", client=client, target=TARGET, chunk_tokens=512
        )

    assert "intermediate note" not in repr(result), "notes stay out of the repr"
    assert result.notes[0] == "an intermediate note", "but remain available"
    assert result.text == "the answer"


async def test_summary_is_content_free():
    server = FakeOpenAIServer(FakeResponse(text="a note"))
    async with _client(server) as client:
        result = await distill(
            "text", "summarize", client=client, target=TARGET, chunk_tokens=512
        )

    assert "note" not in result.summary()
    assert "call(s)" in result.summary()


async def test_an_observer_sees_the_call_count():
    received: list[ai.TelemetryEvent] = []

    class Recorder:
        def on_event(self, event: ai.TelemetryEvent) -> None:
            received.append(event)

    server = FakeOpenAIServer(FakeResponse(text="note"))
    async with _client(server) as client:
        result = await distill(
            BIG_TEXT,
            "summarize",
            client=client,
            target=TARGET,
            chunk_tokens=128,
            observer=Recorder(),
        )

    assert len(received) == 1
    event = received[0]
    assert isinstance(event, ai.ContextReduced)
    assert event.strategy == "distill"
    assert event.calls == result.calls, "the multiplier is observable"


# ---- custom instructions -------------------------------------------------------------


async def test_instructions_can_be_replaced():
    server = FakeOpenAIServer(FakeResponse(text="note"))
    async with _client(server) as client:
        await distill(
            "text",
            "summarize",
            client=client,
            target=TARGET,
            chunk_tokens=512,
            map_instructions="EXTRACT ENTITIES ONLY.",
            reduce_instructions="MERGE AS JSON.",
        )

    assert "EXTRACT ENTITIES ONLY." in server.requests[0]["messages"][0]["content"]
    assert "MERGE AS JSON." in server.requests[1]["messages"][0]["content"]


# ---- the sync facade -----------------------------------------------------------------


def test_the_sync_facade_produces_the_same_shape():
    server = FakeOpenAIServer(FakeResponse(text="a note"))
    client = _sync_client(server)
    try:
        result = distill_sync(
            "a little text", "summarize", client=client, target=TARGET, chunk_tokens=512
        )
    finally:
        client.close()

    assert result.chunk_count == 1
    assert result.calls == 2
    assert result.text == "a note"


def test_the_sync_facade_honors_a_deterministic_reducer():
    server = FakeOpenAIServer(FakeResponse(text="note"))
    client = _sync_client(server)
    try:
        result = distill_sync(
            BIG_TEXT,
            "summarize",
            client=client,
            target=TARGET,
            chunk_tokens=128,
            reducer=lambda notes: json.dumps({"notes": len(notes)}),
        )
    finally:
        client.close()

    assert result.calls == result.chunk_count
    assert json.loads(result.text)["notes"] == result.chunk_count
