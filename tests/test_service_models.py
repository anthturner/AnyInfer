"""Model acquisition for engines that own their own store."""

from __future__ import annotations

from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.local.services import PullRequest, pull_ollama_model
from anyinfer.testing.fakes import FakeOllamaServer
from support import make_client

MODEL = "qwen3:8b"


def _ollama_client(server: FakeOllamaServer) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama", base_url="http://127.0.0.1:11434", transport=server.transport()
            )
        ]
    )


class _Recorder:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def on_event(self, event: Any) -> None:
        self.events.append(event)


# ---- the puller ----------------------------------------------------------------------


async def test_a_pull_reports_what_it_transferred() -> None:
    server = FakeOllamaServer()
    report = await pull_ollama_model(
        PullRequest(model=MODEL, base_url="http://127.0.0.1:11434", transport=server.transport())
    )

    assert server.pulled == [MODEL]
    assert report.model == MODEL
    assert report.already_present is False
    assert report.bytes_transferred == 8_000_000
    assert report.detail == "success"


async def test_layer_counts_accumulate_into_aggregate_progress() -> None:
    """Ollama counts per layer; DownloadProgress promises the whole acquisition."""
    server = FakeOllamaServer()
    server.pull_lines = [
        {"status": "pulling manifest"},
        {"status": "pulling a", "digest": "a", "total": 6_000_000, "completed": 6_000_000},
        {"status": "pulling b", "digest": "b", "total": 4_000_000, "completed": 4_000_000},
        {"status": "success"},
    ]
    seen: list[Any] = []
    report = await pull_ollama_model(
        PullRequest(
            model=MODEL,
            base_url="http://127.0.0.1:11434",
            transport=server.transport(),
            progress=seen.append,
        )
    )

    assert report.bytes_transferred == 10_000_000, "not just the last layer"
    assert seen[-1].done is True
    assert seen[-1].downloaded_bytes == 10_000_000
    assert seen[-1].total_bytes == 10_000_000
    assert all(e.artifact_id == MODEL for e in seen)


async def test_an_already_present_model_is_distinguished_from_a_transfer() -> None:
    """Distinguish a cache hit from a transfer that happened to finish quickly."""
    server = FakeOllamaServer()
    server.pull_lines = [{"status": "success"}]
    report = await pull_ollama_model(
        PullRequest(model=MODEL, base_url="http://127.0.0.1:11434", transport=server.transport())
    )

    assert report.already_present is True
    assert report.bytes_transferred == 0


async def test_a_missing_model_is_a_model_not_found_error() -> None:
    server = FakeOllamaServer()
    server.pull_lines = [{"error": "pull model manifest: file does not exist"}]
    with pytest.raises(ai.ModelNotFoundError) as excinfo:
        await pull_ollama_model(
            PullRequest(
                model="nope:1b", base_url="http://127.0.0.1:11434", transport=server.transport()
            )
        )

    assert excinfo.value.hint is not None
    assert "ollama.com" in excinfo.value.hint


async def test_a_midstream_failure_surfaces_as_a_local_runtime_error() -> None:
    """Ollama reports these in the body, not the status, so both shapes must land here."""
    server = FakeOllamaServer()
    server.pull_lines = [
        {"status": "pulling a", "digest": "a", "total": 10, "completed": 5},
        {"error": "max retries exceeded"},
    ]
    with pytest.raises(ai.LocalRuntimeError) as excinfo:
        await pull_ollama_model(
            PullRequest(
                model=MODEL, base_url="http://127.0.0.1:11434", transport=server.transport()
            )
        )

    assert "partway through" in excinfo.value.detail
    assert excinfo.value.hint is not None


async def test_an_unreachable_server_is_actionable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(ai.LocalRuntimeError) as excinfo:
        await pull_ollama_model(
            PullRequest(
                model=MODEL,
                base_url="http://127.0.0.1:11434",
                transport=httpx2.MockTransport(refuse),
            )
        )

    assert excinfo.value.hint is not None
    assert "Ollama is running" in excinfo.value.hint


async def test_a_raising_progress_sink_is_disabled_not_fatal() -> None:
    def explode(event: Any) -> None:
        raise RuntimeError("the UI fell over")

    server = FakeOllamaServer()
    report = await pull_ollama_model(
        PullRequest(
            model=MODEL,
            base_url="http://127.0.0.1:11434",
            transport=server.transport(),
            progress=explode,
        )
    )

    assert report.detail == "success", "a broken sink must not fail the transfer"


# ---- the client surface --------------------------------------------------------------


async def test_client_pull_emits_progress_as_ordinary_telemetry() -> None:
    recorder = _Recorder()
    server = FakeOllamaServer()
    client = _ollama_client(server)
    client.subscribe(recorder)
    async with client:
        report = await client.pull_model("ollama", MODEL)

    assert report.model == MODEL
    progress = [e for e in recorder.events if isinstance(e, ai.DownloadProgress)]
    assert progress and progress[-1].done is True


async def test_client_pull_also_feeds_an_explicit_sink() -> None:
    seen: list[Any] = []
    server = FakeOllamaServer()
    async with _ollama_client(server) as client:
        await client.pull_model("ollama", MODEL, progress=seen.append)

    assert seen and seen[-1].artifact_id == MODEL


async def test_a_provider_that_owns_no_store_says_so() -> None:
    from anyinfer.testing.fakes import FakeOpenAIServer

    async with make_client(FakeOpenAIServer()) as client:
        with pytest.raises(ai.ConfigError) as excinfo:
            await client.pull_model("openai-compat", "m")

    assert excinfo.value.hint is not None
    assert "acquire_model" in excinfo.value.hint


def test_only_providers_that_can_pull_declare_a_puller() -> None:
    """Readable from the registry rather than from engine checks in the core."""
    from anyinfer import default_registry

    can_pull = {d.id for d in default_registry if d.model_puller is not None}
    assert can_pull == {"ollama"}


def test_sync_client_pull() -> None:
    server = FakeOllamaServer()
    client = ai.Client(
        [
            ai.ProviderSettings.of(
                "ollama", base_url="http://127.0.0.1:11434", transport=server.transport()
            )
        ]
    )
    try:
        assert client.pull_model("ollama", MODEL).model == MODEL
    finally:
        client.close()
