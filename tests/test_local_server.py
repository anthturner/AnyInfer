"""The llama-server supervisor.

Real subprocesses would make this suite slow and platform-dependent, so a fake
``llama-server`` script stands in: a Python process that serves ``/health`` and can be told
to fail, hang, or crash. That exercises the supervisor's actual contract — spawn, poll,
distinguish loading from failed, reap — without depending on a llama.cpp build.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from anyinfer.errors import LocalRuntimeError
from anyinfer.events.telemetry import ServerLifecycle
from anyinfer.local.hardware import Accelerator, HardwareProfile
from anyinfer.local.server import LOOPBACK_HOST, ServerSupervisor, allocate_port
from anyinfer.local.tuning import ServerPlan

GIB = 1024**3

FAKE_SERVER = '''
import http.server, sys, threading, time

mode = "ok"
port = 8080
args = sys.argv[1:]
for i, a in enumerate(args):
    if a == "--port":
        port = int(args[i + 1])
    if a == "--model" and "crash" in args[i + 1]:
        mode = "crash"
    if a == "--model" and "hang" in args[i + 1]:
        mode = "hang"

if mode == "crash":
    print("fatal: unable to load model", flush=True)
    sys.exit(3)

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health" and mode != "hang":
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(503)
            self.end_headers()
    def log_message(self, *a):
        pass

print("server listening", flush=True)
http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


@pytest.fixture
def fake_binary(tmp_path: Path) -> Path:
    """A stand-in llama-server: a Python script wrapped in a platform-appropriate shim."""
    script = tmp_path / "fake_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")

    if sys.platform == "win32":
        shim = tmp_path / "llama-server.bat"
        shim.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        shim = tmp_path / "llama-server"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
                        encoding="utf-8")
        shim.chmod(0o755)
    return shim


def _plan(**overrides: object) -> ServerPlan:
    base: dict[str, object] = {"context_size": 8192, "estimated_total_bytes": 4 * GIB}
    base.update(overrides)
    return ServerPlan(**base)  # type: ignore[arg-type]


def _model(tmp_path: Path, name: str = "model.gguf") -> Path:
    path = tmp_path / name
    path.write_bytes(b"gguf")
    return path


# ---- binding safety ------------------------------------------------------------------


def test_non_loopback_binding_is_refused_by_default() -> None:
    """Local servers must not be exposed to the network by accident (D20)."""
    with pytest.raises(LocalRuntimeError, match="refusing to bind"):
        ServerSupervisor(host="0.0.0.0")


def test_non_loopback_binding_requires_an_explicit_opt_in() -> None:
    supervisor = ServerSupervisor(host="0.0.0.0", allow_remote_exposure=True)
    assert supervisor is not None


def test_allocate_port_returns_a_usable_loopback_port() -> None:
    port = allocate_port()
    assert 1024 < port < 65536


# ---- lifecycle -----------------------------------------------------------------------


async def test_server_starts_and_becomes_ready(fake_binary: Path, tmp_path: Path) -> None:
    events: list[ServerLifecycle] = []
    supervisor = ServerSupervisor(binary=fake_binary, on_lifecycle=events.append)
    try:
        managed = await supervisor.acquire("m", _model(tmp_path), _plan())
        assert managed.base_url.startswith(f"http://{LOOPBACK_HOST}:")
        assert managed.base_url.endswith("/v1")
        assert supervisor.resident_models == ("m",)
    finally:
        await supervisor.aclose()

    states = [e.state for e in events]
    assert "starting" in states and "ready" in states


async def test_a_second_request_reuses_the_running_server(
    fake_binary: Path, tmp_path: Path
) -> None:
    supervisor = ServerSupervisor(binary=fake_binary)
    try:
        first = await supervisor.acquire("m", _model(tmp_path), _plan())
        second = await supervisor.acquire("m", _model(tmp_path), _plan())
        assert first.base_url == second.base_url
    finally:
        await supervisor.aclose()


async def test_concurrent_acquires_do_not_start_two_servers(
    fake_binary: Path, tmp_path: Path
) -> None:
    """Swaps are serialized: racing loads compete for the same memory and both lose."""
    supervisor = ServerSupervisor(binary=fake_binary)
    try:
        results = await asyncio.gather(
            *(supervisor.acquire("m", _model(tmp_path), _plan()) for _ in range(4))
        )
        assert len({r.base_url for r in results}) == 1
        assert len(supervisor.resident_models) == 1
    finally:
        await supervisor.aclose()


async def test_crashed_server_reports_its_log_tail(fake_binary: Path, tmp_path: Path) -> None:
    """Polling /health alone makes a broken model look slow; the child's output explains."""
    supervisor = ServerSupervisor(binary=fake_binary, health_timeout_s=15.0)
    try:
        with pytest.raises(LocalRuntimeError) as excinfo:
            await supervisor.acquire("bad", _model(tmp_path, "crash.gguf"), _plan())
    finally:
        await supervisor.aclose()

    assert "unable to load model" in str(excinfo.value)
    assert excinfo.value.hint is not None


async def test_server_that_never_reports_healthy_times_out(
    fake_binary: Path, tmp_path: Path
) -> None:
    supervisor = ServerSupervisor(binary=fake_binary, health_timeout_s=1.0)
    try:
        with pytest.raises(LocalRuntimeError, match="did not become ready"):
            await supervisor.acquire("slow", _model(tmp_path, "hang.gguf"), _plan())
    finally:
        await supervisor.aclose()

    assert supervisor.resident_models == (), "a failed start must not leave a handle"


async def test_missing_model_file_is_actionable(fake_binary: Path, tmp_path: Path) -> None:
    supervisor = ServerSupervisor(binary=fake_binary)
    try:
        with pytest.raises(LocalRuntimeError, match="model file not found"):
            await supervisor.acquire("m", tmp_path / "absent.gguf", _plan())
    finally:
        await supervisor.aclose()


async def test_missing_binary_is_actionable(tmp_path: Path) -> None:
    supervisor = ServerSupervisor(binary=tmp_path / "definitely-not-here")
    try:
        with pytest.raises(LocalRuntimeError) as excinfo:
            await supervisor.acquire("m", _model(tmp_path), _plan())
    finally:
        await supervisor.aclose()

    assert excinfo.value.hint is not None


async def test_close_stops_every_server(fake_binary: Path, tmp_path: Path) -> None:
    supervisor = ServerSupervisor(binary=fake_binary)
    managed = await supervisor.acquire("m", _model(tmp_path), _plan())
    handle = managed.handle

    await supervisor.aclose()

    assert supervisor.resident_models == ()
    assert not handle.is_running, "the process must actually be gone"


# ---- admission control ---------------------------------------------------------------


async def test_a_model_that_cannot_fit_is_refused_before_spawning(
    fake_binary: Path, tmp_path: Path
) -> None:
    """Refusing with a clear message beats an out-of-memory crash inside the child."""
    hardware = HardwareProfile(
        os_name="linux",
        arch="x86_64",
        accelerators=(Accelerator(kind="cuda", total_vram_bytes=8 * GIB),),
    )
    supervisor = ServerSupervisor(binary=fake_binary, hardware=hardware)
    try:
        with pytest.raises(LocalRuntimeError) as excinfo:
            await supervisor.acquire(
                "huge", _model(tmp_path), _plan(estimated_total_bytes=40 * GIB)
            )
    finally:
        await supervisor.aclose()

    assert "uncommitted" in str(excinfo.value)
    assert excinfo.value.hint is not None


async def test_unknown_memory_does_not_block_admission(
    fake_binary: Path, tmp_path: Path
) -> None:
    """An unknown budget must not refuse a model that would have worked."""
    hardware = HardwareProfile(os_name="linux", arch="x86_64", total_ram_bytes=None)
    supervisor = ServerSupervisor(binary=fake_binary, hardware=hardware)
    try:
        managed = await supervisor.acquire(
            "m", _model(tmp_path), _plan(estimated_total_bytes=999 * GIB)
        )
        assert managed.base_url
    finally:
        await supervisor.aclose()


# ---- idle collection -----------------------------------------------------------------


async def test_idle_server_is_collected(fake_binary: Path, tmp_path: Path) -> None:
    supervisor = ServerSupervisor(binary=fake_binary, idle_ttl_s=0.0)
    try:
        await supervisor.acquire("m", _model(tmp_path), _plan())
        assert await supervisor.collect_idle() == 1
        assert supervisor.resident_models == ()
    finally:
        await supervisor.aclose()


async def test_an_active_stream_is_never_collected(
    fake_binary: Path, tmp_path: Path
) -> None:
    """A long generation with no *new* requests is not idle — the classic false-idle kill."""
    supervisor = ServerSupervisor(binary=fake_binary, idle_ttl_s=0.0)
    try:
        managed = await supervisor.acquire("m", _model(tmp_path), _plan())
        with managed:
            assert await supervisor.collect_idle() == 0
            assert supervisor.resident_models == ("m",)
        assert await supervisor.collect_idle() == 1
    finally:
        await supervisor.aclose()


async def test_persisted_server_survives_collection(
    fake_binary: Path, tmp_path: Path
) -> None:
    supervisor = ServerSupervisor(binary=fake_binary, idle_ttl_s=0.0)
    try:
        await supervisor.acquire("m", _model(tmp_path), _plan(), persist=True)
        assert await supervisor.collect_idle() == 0
        assert supervisor.resident_models == ("m",)
    finally:
        await supervisor.aclose()


async def test_disabled_ttl_never_collects(fake_binary: Path, tmp_path: Path) -> None:
    supervisor = ServerSupervisor(binary=fake_binary, idle_ttl_s=None)
    try:
        await supervisor.acquire("m", _model(tmp_path), _plan())
        assert await supervisor.collect_idle() == 0
    finally:
        await supervisor.aclose()


# ---- capacity ------------------------------------------------------------------------


async def test_exceeding_capacity_evicts_the_least_recently_used(
    fake_binary: Path, tmp_path: Path
) -> None:
    supervisor = ServerSupervisor(binary=fake_binary, max_resident=1)
    try:
        await supervisor.acquire("first", _model(tmp_path, "a.gguf"), _plan())
        await supervisor.acquire("second", _model(tmp_path, "b.gguf"), _plan())
        assert supervisor.resident_models == ("second",)
    finally:
        await supervisor.aclose()


async def test_busy_servers_are_not_evicted(fake_binary: Path, tmp_path: Path) -> None:
    supervisor = ServerSupervisor(binary=fake_binary, max_resident=1)
    try:
        managed = await supervisor.acquire("first", _model(tmp_path, "a.gguf"), _plan())
        with managed, pytest.raises(LocalRuntimeError, match="all are busy"):
            await supervisor.acquire("second", _model(tmp_path, "b.gguf"), _plan())
    finally:
        await supervisor.aclose()


async def test_managed_server_tracks_active_streams(
    fake_binary: Path, tmp_path: Path
) -> None:
    supervisor = ServerSupervisor(binary=fake_binary)
    try:
        managed = await supervisor.acquire("m", _model(tmp_path), _plan())
        handle = managed.handle

        assert handle.is_idle
        with managed:
            assert not handle.is_idle
            assert handle.idle_seconds() == 0.0
        assert handle.is_idle
    finally:
        await supervisor.aclose()
