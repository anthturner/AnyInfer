"""Lifecycle proofs for real OpenAI-compatible transport execution."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import httpx2
import pytest

from anyinfer.providers.openai_compat import OpenAICompatAdapter

from . import transport

ROOT = Path(__file__).parents[3]
_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "portable_transport_lifecycle_validator", ROOT / "scripts" / "validate_fixtures.py"
)
assert _VALIDATOR_SPEC is not None and _VALIDATOR_SPEC.loader is not None
validate_fixtures = importlib.util.module_from_spec(_VALIDATOR_SPEC)
_VALIDATOR_SPEC.loader.exec_module(validate_fixtures)


class _ObservedByteFactsStream(httpx2.AsyncByteStream):
    """Delegate-compatible transport byte stream with observable native cleanup."""

    block_before: ClassVar[int | None] = None
    instances: ClassVar[list[_ObservedByteFactsStream]] = []

    def __init__(self, chunks: tuple[bytes, ...], delivered: list[bytes]) -> None:
        self._chunks = chunks
        self._delivered = delivered
        self.entered = asyncio.Event()
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()
        self.iterator_closed = False
        self.aclose_calls = 0
        type(self).instances.append(self)

    @classmethod
    def reset(cls, *, block_before: int | None) -> None:
        cls.block_before = block_before
        cls.instances = []

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.entered.set()
        try:
            for index, chunk in enumerate(self._chunks):
                if self.block_before == index:
                    self.blocked.set()
                    await self.release.wait()
                self._delivered.append(chunk)
                yield chunk
        finally:
            self.iterator_closed = True

    async def aclose(self) -> None:
        self.aclose_calls += 1
        self.release.set()


def _pending_fixture(kind: str) -> dict[str, Any]:
    adapter_config = {
        "provider_id": "openai-compat",
        "base_url": "https://fixture.invalid/v1",
        "api_key": "fixture-token",
        "headers": {"x-fixture": "lifecycle"},
        "timeout_s": 120,
    }
    input_value: dict[str, Any] = {"adapter_config": adapter_config}
    if kind == "adapter":
        input_value["wire"] = {
            "model": "fixture-model",
            "messages": [{"role": "user", "text": "hello"}],
            "sampling": {},
            "mechanism": None,
            "stream": True,
            "timeout_s": 17,
            "max_response_bytes": 4096,
        }
        slug = "adapter"
    else:
        input_value["operation"] = {
            "request": {
                "messages": [{"role": "user", "text": "hello"}],
                "sampling": {},
                "consume": "stream",
                "timeout_s": 17,
                "max_response_bytes": 4096,
            },
            "route": {"targets": ["openai-compat:fixture-model"], "retry": {"max_attempts": 1}},
        }
        slug = "core-http"
    return {
        "fixture_version": "0",
        "id": f"transport/openai-chat/lifecycle-{slug}",
        "family": "transport/openai-chat",
        "profile": "core-generation",
        "description": "pending native lifecycle observation",
        "kind": kind,
        "input": input_value,
        "responses": [
            {
                "status": 200,
                "headers": {"content-type": "text/event-stream"},
                "byte_chunks": [{"bytes": base64.b64encode(b"data: [DONE]\n\n").decode()}],
            }
        ],
        "expected": {"status": "to_be_observed"},
    }


def _validate_pending(tmp_path: Path, fixture: dict[str, Any]) -> None:
    path = tmp_path / "transport" / "fixture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture), encoding="utf-8")
    assert validate_fixtures.validate(tmp_path) == []


def _install_native_spies(
    monkeypatch: pytest.MonkeyPatch, *, block_before: int | None
) -> list[OpenAICompatAdapter]:
    _ObservedByteFactsStream.reset(block_before=block_before)
    monkeypatch.setattr(transport, "_ByteFactsStream", _ObservedByteFactsStream)
    closed: list[OpenAICompatAdapter] = []
    original_aclose = OpenAICompatAdapter.aclose

    async def observed_aclose(adapter: OpenAICompatAdapter) -> None:
        closed.append(adapter)
        await original_aclose(adapter)

    monkeypatch.setattr(OpenAICompatAdapter, "aclose", observed_aclose)
    return closed


def _normal_fixture(kind: str) -> dict[str, Any]:
    fixture = _pending_fixture(kind)
    fixture["responses"] = [
        {
            "status": 200,
            "headers": {"content-type": "text/event-stream"},
            "byte_chunks": [
                {
                    "bytes": base64.b64encode(
                        b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                    ).decode()
                },
                {"bytes": base64.b64encode(b"data: [DONE]\n\n").decode()},
            ],
        }
    ]
    return fixture


async def _wait_until_blocked() -> _ObservedByteFactsStream:
    for _ in range(500):
        if _ObservedByteFactsStream.instances:
            stream = _ObservedByteFactsStream.instances[0]
            if stream.blocked.is_set():
                return stream
        await asyncio.sleep(0.01)
    raise AssertionError("native HTTP byte stream did not reach the readiness gate")


def _error_fixture(kind: str) -> dict[str, Any]:
    fixture = _pending_fixture(kind)
    fixture["responses"] = [
        {
            "status": 503,
            "headers": {"content-type": "application/json"},
            "byte_chunks": [
                {"bytes": base64.b64encode(b'{"error":"fixture failure"}').decode()}
            ],
        }
    ]
    return fixture


@pytest.mark.parametrize("kind", ["adapter", "core_http"])
async def test_real_runner_cancellation_closes_native_http_and_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    fixture = _normal_fixture(kind)
    _validate_pending(tmp_path, fixture)
    closed = _install_native_spies(monkeypatch, block_before=1)

    task = asyncio.create_task(transport.run_transport_fixture(fixture))
    await _wait_until_blocked()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    stream = _ObservedByteFactsStream.instances[0]
    assert stream.entered.is_set() and stream.blocked.is_set()
    assert stream.iterator_closed and stream.aclose_calls >= 1
    assert len(closed) == 1


@pytest.mark.parametrize("kind", ["adapter", "core_http"])
async def test_real_runner_normal_and_error_completion_close_native_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    normal = _normal_fixture(kind)
    _validate_pending(tmp_path, normal)
    closed = _install_native_spies(monkeypatch, block_before=None)

    normal_run = await transport.run_transport_fixture(normal)
    normal_stream = _ObservedByteFactsStream.instances[0]
    assert normal_run.error is None
    if kind == "adapter":
        assert any(
            getattr(event, "text", None) == "first" for event in normal_run.adapter_events
        )
    else:
        assert normal_run.core is not None
        assert any(getattr(event, "text", None) == "first" for event in normal_run.core.events)
    assert normal_stream.iterator_closed and normal_stream.aclose_calls >= 1
    assert len(closed) == 1

    error = _error_fixture(kind)
    _validate_pending(tmp_path, error)
    closed = _install_native_spies(monkeypatch, block_before=None)

    error_run = await transport.run_transport_fixture(error)
    error_stream = _ObservedByteFactsStream.instances[0]
    assert error_run.error is not None and error_run.error_stage == "operation"
    assert error_stream.iterator_closed and error_stream.aclose_calls >= 1
    assert len(closed) == 1
