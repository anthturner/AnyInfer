from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from anyinfer.errors import ConfidentialExecutionError
from anyinfer.local import attestation as attest
from anyinfer.local.backends import Backend
from anyinfer.providers.base import AdapterEvent, AdapterFinal, WireRequest
from anyinfer.providers.confidential_execution import ConfidentialExecutionAdapter
from anyinfer.types.capabilities import DiscoveredModel, Health

_REQ = WireRequest(model="m", messages=())


class _InnerAdapter:
    """Records whether `generate` was ever actually invoked."""

    def __init__(self) -> None:
        self.generate_calls = 0

    async def list_models(self) -> Sequence[DiscoveredModel]:
        return [DiscoveredModel(id="m")]

    async def health(self) -> Health:
        return Health(ok=True)

    async def aclose(self) -> None:
        pass

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        self.generate_calls += 1
        yield AdapterFinal(finish_reason="stop")


def _attested_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Backend:
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "sev-guest").touch()
    monkeypatch.setattr(attest, "_DEV_ROOT", dev)
    monkeypatch.setattr(attest, "_run", lambda command: None)
    monkeypatch.setattr(attest, "cache_path", lambda: tmp_path / "attestation.json")
    return Backend(kind="cpu", binary=Path("/usr/bin/llama-server"))


def _unattested_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Backend:
    dev = tmp_path / "dev"
    dev.mkdir()
    monkeypatch.setattr(attest, "_DEV_ROOT", dev)
    monkeypatch.setattr(attest, "_run", lambda command: None)
    monkeypatch.setattr(attest, "cache_path", lambda: tmp_path / "attestation.json")
    return Backend(kind="cpu", binary=Path("/usr/bin/llama-server"))


async def test_generation_proceeds_when_attestation_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _attested_backend(tmp_path, monkeypatch)
    inner = _InnerAdapter()
    adapter = ConfidentialExecutionAdapter(inner, backend=backend)

    events = [event async for event in adapter.generate(_REQ)]

    assert inner.generate_calls == 1
    assert any(isinstance(e, AdapterFinal) for e in events)


async def test_generation_is_refused_and_inner_adapter_never_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _unattested_backend(tmp_path, monkeypatch)
    inner = _InnerAdapter()
    adapter = ConfidentialExecutionAdapter(inner, backend=backend)

    with pytest.raises(ConfidentialExecutionError):
        async for _ in adapter.generate(_REQ):
            pass

    assert inner.generate_calls == 0, "the inner adapter must never be touched on refusal"


async def test_the_error_carries_the_status_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _unattested_backend(tmp_path, monkeypatch)
    adapter = ConfidentialExecutionAdapter(_InnerAdapter(), backend=backend)

    with pytest.raises(ConfidentialExecutionError, match="no attestable CPU TEE detected"):
        async for _ in adapter.generate(_REQ):
            pass


async def test_discovery_and_health_pass_through_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _unattested_backend(tmp_path, monkeypatch)
    inner = _InnerAdapter()
    adapter = ConfidentialExecutionAdapter(inner, backend=backend)

    models = await adapter.list_models()
    health = await adapter.health()

    assert [m.id for m in models] == ["m"]
    assert health.ok is True
    await adapter.aclose()
