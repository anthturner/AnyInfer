"""Cassettes an application records are safe to commit."""

from __future__ import annotations

from pathlib import Path

import httpx2

from anyinfer.redaction import register_secret
from anyinfer.testing import Cassette, CassetteTransport, Interaction


def test_recorded_secrets_never_reach_disk(tmp_path: Path) -> None:
    """A registered credential is scrubbed from every part of the interaction."""
    secret = "sk-test-cassette-should-never-store-this"
    register_secret(secret)

    cassette = Cassette(tmp_path / "recorded.json")
    cassette.append(
        Interaction(
            method="POST",
            url=f"https://api.invalid/v1/chat?key={secret}",
            request_body=f'{{"api_key": "{secret}"}}',
            status=200,
            headers={"authorization": f"Bearer {secret}", "x-trace": secret},
            body=f'{{"echo": "{secret}"}}',
        )
    )
    cassette.save()

    written = (tmp_path / "recorded.json").read_text(encoding="utf-8")
    assert secret not in written
    assert "[redacted]" in written


def test_replay_serves_recorded_traffic(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "replay.json")
    cassette.append(
        Interaction(
            method="GET",
            url="https://api.invalid/v1/models",
            request_body="",
            status=200,
            headers={"content-type": "application/json"},
            body='{"object": "list", "data": []}',
        )
    )
    cassette.save()

    transport = CassetteTransport(Cassette(tmp_path / "replay.json"))
    with httpx2.Client(transport=_sync(transport)) as client:
        response = client.get("https://api.invalid/v1/models")

    assert response.status_code == 200
    assert response.json() == {"object": "list", "data": []}


def test_unmatched_request_names_the_cassette_to_rerecord(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "empty.json")
    cassette.save()

    transport = CassetteTransport(Cassette(tmp_path / "empty.json"))
    try:
        with httpx2.Client(transport=_sync(transport)) as client:
            client.get("https://api.invalid/v1/models")
    except RuntimeError as exc:
        assert "empty.json" in str(exc)
    else:  # pragma: no cover — the transport must refuse an unmatched request
        raise AssertionError("an unmatched request must not silently succeed")


class _SyncBridge(httpx2.BaseTransport):
    """Drive the async cassette transport from a sync client, for a terse test."""

    def __init__(self, inner: CassetteTransport) -> None:
        self._inner = inner

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        import asyncio

        return asyncio.run(self._inner.handle_async_request(request))


def _sync(transport: CassetteTransport) -> httpx2.BaseTransport:
    return _SyncBridge(transport)
