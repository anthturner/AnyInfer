"""Cassette record/replay, including its security guarantee (redaction before disk)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest

import anyinfer as ai
from anyinfer.redaction import REDACTED, register_secret
from anyinfer.testing.cassettes import Cassette, CassetteTransport, Interaction
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse


def _client(transport: httpx2.AsyncBaseTransport) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat", base_url="https://fake.invalid/v1", transport=transport
            )
        ]
    )


async def test_record_mode_captures_interactions_to_disk(tmp_path: Path) -> None:
    server = FakeOpenAIServer(FakeResponse(text="recorded answer"))
    cassette = Cassette(tmp_path / "openai_compat.json")
    transport = CassetteTransport(cassette, record=True, inner=server.transport())

    async with _client(transport) as client:
        result = await client.generate("hi", target="openai-compat:m")
    cassette.save()

    assert result.text == "recorded answer"
    saved = json.loads((tmp_path / "openai_compat.json").read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert len(saved["interactions"]) == 1
    interaction = saved["interactions"][0]
    assert interaction["method"] == "POST"
    assert interaction["url"].endswith("/chat/completions")
    assert "hi" in interaction["request_body"]
    assert "recorded answer" in interaction["body"]


async def test_replay_serves_recorded_traffic_without_a_network(tmp_path: Path) -> None:
    server = FakeOpenAIServer(FakeResponse(text="from the recording"))
    recording = Cassette(tmp_path / "c.json")
    async with _client(
        CassetteTransport(recording, record=True, inner=server.transport())
    ) as client:
        await client.generate("hi", target="openai-compat:m")
    recording.save()
    calls_at_record_time = server.call_count

    # A fresh cassette loaded from disk, with no inner transport: nothing to talk to but
    # the recording itself.
    async with _client(CassetteTransport(Cassette(tmp_path / "c.json"))) as client:
        replayed = await client.generate("hi", target="openai-compat:m")

    assert replayed.text == "from the recording"
    assert server.call_count == calls_at_record_time, "replay must never reach a server"


async def test_saved_cassettes_never_contain_registered_secrets(tmp_path: Path) -> None:
    """The security guarantee: a cassette committed to the repo cannot carry a key."""
    secret = "sk-cassette-secret-value"
    register_secret(secret)
    server = FakeOpenAIServer(FakeResponse(text=f"your key is {secret}, noted"))
    cassette = Cassette(tmp_path / "c.json")
    transport = CassetteTransport(cassette, record=True, inner=server.transport())

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                api_key=secret,
                transport=transport,
            )
        ]
    )
    async with client:
        await client.generate(f"my key is {secret}", target="openai-compat:m")
    cassette.save()

    text = (tmp_path / "c.json").read_text(encoding="utf-8")
    assert secret not in text, "a registered secret reached disk"
    assert REDACTED in text


def test_secret_headers_are_scrubbed_even_when_unregistered(tmp_path: Path) -> None:
    """Credential-bearing headers are stripped wholesale, not just by registered value."""
    cassette = Cassette(tmp_path / "c.json")
    cassette.append(
        Interaction(
            method="GET",
            url="https://host.invalid/v1/models",
            request_body="",
            status=200,
            headers={
                "Authorization": "Bearer sk-never-registered",
                "content-type": "application/json",
            },
            body="{}",
        )
    )
    cassette.save()

    saved = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    headers = saved["interactions"][0]["headers"]
    assert headers["Authorization"] == "[redacted]"
    assert headers["content-type"] == "application/json", "innocent headers survive"


async def test_replaying_an_unrecorded_request_fails_loudly(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "c.json")
    cassette.append(
        Interaction(
            method="POST",
            url="https://fake.invalid/v1/chat/completions",
            request_body="{}",
            status=200,
            headers={"content-type": "application/json"},
            body="{}",
        )
    )

    async with httpx2.AsyncClient(transport=CassetteTransport(cassette)) as http:
        with pytest.raises(RuntimeError, match="no cassette interaction matches"):
            await http.get("https://fake.invalid/v1/models")
