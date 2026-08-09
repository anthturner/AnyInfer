"""Supervised ``llama-server`` processes.

llama.cpp runs as a subprocess speaking the OpenAI-compatible dialect over loopback — never
in-process. This module owns those processes' whole lifecycle.

The semantics here are shaped by failure modes observed across comparable local
multiplexers, and each is deliberate:

- **Swaps are serialized.** Two requests for two unloaded models do not race: the first
  loads, the second waits. Racing them means two full model loads competing for the same
  VRAM, and both fail.
- **Requests block until ready.** A caller never receives a 503 because a model happened to
  be loading; they wait, bounded by a health-check timeout.
- **"Loading" and "failed" are distinguished.** Polling ``/health`` alone makes a
  genuinely-broken model look like a slow one for the full timeout, so the child's stderr is
  captured and surfaced in the error.
- **The idle timer keys on active streams, not last-request time.** A long generation with
  no *new* requests is not idle; keying on request arrival kills work mid-flight.
- **VRAM admission is checked before spawning.** Refusing up front with a clear message
  beats an out-of-memory crash inside the child.
- **Reaping is verified.** A process is not gone because we asked it to stop.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx2

from ..errors import LocalRuntimeError
from ..events.telemetry import ServerLifecycle
from .hardware import HardwareProfile
from .tuning import ServerPlan

__all__ = [
    "LOOPBACK_HOST",
    "LifecycleCallback",
    "ManagedServer",
    "ServerHandle",
    "ServerSupervisor",
    "allocate_port",
    "is_loopback",
]

LOOPBACK_HOST = "127.0.0.1"
"""Local servers bind loopback only, unless the caller explicitly opts out."""

_LOOPBACK_NAMES = frozenset({"localhost", "::1", "[::1]", "0:0:0:0:0:0:0:1"})


def is_loopback(base_url: str | None) -> bool:
    """Whether a base URL points at this machine.

    Used by two callers with the same underlying question — "is the thing at the other end
    of this URL running on hardware I can probe?". A remote Ollama daemon answers no, and
    everything downstream (hardware detection, fit classification, zero-cost pricing)
    depends on not pretending otherwise.

    A URL that cannot be parsed is treated as *not* loopback, because the safe default is to
    assume someone else's machine.
    """
    if not base_url:
        return False
    from urllib.parse import urlsplit

    try:
        host = (urlsplit(base_url).hostname or "").strip().lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in _LOOPBACK_NAMES:
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

_IS_WINDOWS = sys.platform == "win32"

_HEALTH_TIMEOUT_S = 120.0
"""Default readiness budget. Large models on slow storage genuinely take minutes."""

_HEALTH_MIN_TIMEOUT_S = 1.0
"""Floor on the readiness budget, so a caller cannot configure an unwinnable race."""

_HEALTH_POLL_INTERVAL_S = 0.25
_STOP_GRACE_S = 5.0
_LOG_TAIL_LINES = 40

LifecycleCallback = Callable[[ServerLifecycle], None]
"""Receives every lifecycle transition of a supervised server."""

_LifecycleState = Literal["starting", "ready", "stopping", "stopped", "crashed"]
"""Mirror of `ServerLifecycle.state`, so ``_emit`` call sites are checked."""


def allocate_port(host: str = LOOPBACK_HOST) -> int:
    """Reserve an ephemeral port by binding and immediately releasing it.

    Inherently racy, but the alternative — letting llama-server pick and then discovering
    which port it chose — requires parsing its log output, which is far more fragile.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


@dataclass(slots=True)
class ServerHandle:
    """A running llama-server and everything known about it."""

    model_key: str
    """The model this server serves; also its key in the supervisor's server table."""
    model_path: Path
    """The GGUF file the server was started with."""
    plan: ServerPlan
    """The tuned launch plan; its memory estimate is what admission control committed."""
    host: str
    """Interface the server is bound to — loopback unless exposure was explicitly allowed."""
    port: int
    """TCP port the server listens on, allocated just before spawning."""
    process: subprocess.Popen[bytes]
    """The supervised child, polled for liveness and terminated on stop."""
    started_at: float
    """Monotonic time the child was spawned."""
    log_tail: deque[str] = field(default_factory=lambda: deque(maxlen=_LOG_TAIL_LINES))
    """The child's most recent output lines, kept so failures can explain themselves."""
    active_streams: int = 0
    """Open response streams. Nonzero means busy: the idle clock and eviction ignore it."""
    last_activity: float = field(default_factory=time.monotonic)
    """Monotonic time of the last request or stream release; the idle clock's baseline."""
    persist: bool = False
    """Exempt this server from idle collection and capacity eviction."""
    stopping: bool = False
    """Set while the supervisor is tearing this server down."""

    @property
    def base_url(self) -> str:
        """The OpenAI-compatible base URL this server serves."""
        return f"http://{self.host}:{self.port}/v1"

    @property
    def is_running(self) -> bool:
        """Whether the child process is still alive."""
        return self.process.poll() is None

    @property
    def is_idle(self) -> bool:
        """Whether no request is currently streaming from this server."""
        return self.active_streams <= 0

    def idle_seconds(self) -> float:
        """How long this server has been idle. Zero while any stream is active."""
        if self.active_streams > 0:
            return 0.0
        return time.monotonic() - self.last_activity

    def touch(self) -> None:
        """Mark activity, resetting the idle clock."""
        self.last_activity = time.monotonic()


class ManagedServer:
    """A context manager marking a server busy for the duration of a request.

    This is what makes the idle timer honest: the server is busy while a stream is open,
    not merely while a request is arriving.
    """

    def __init__(self, handle: ServerHandle) -> None:
        self.handle = handle

    @property
    def base_url(self) -> str:
        """The server's base URL."""
        return self.handle.base_url

    def __enter__(self) -> ManagedServer:
        """Mark the server busy."""
        self.handle.active_streams += 1
        self.handle.touch()
        return self

    def __exit__(self, *exc: object) -> None:
        """Release the server and restart its idle clock."""
        self.handle.active_streams = max(0, self.handle.active_streams - 1)
        self.handle.touch()


class ServerSupervisor:
    """Owns the llama-server processes for one client.

    Args:
        binary: Path to the ``llama-server`` executable.
        hardware: Detected hardware, used for VRAM admission control.
        idle_ttl_s: Unload a server after this long with no active streams. ``None``
            keeps servers until the supervisor closes.
        max_resident: How many servers may run at once. Exceeding it evicts the
            least-recently-used idle server.
        allow_remote_exposure: Bind a non-loopback address. Off by default: a local
            model server is loopback-only unless deliberately exposed.
        on_lifecycle: Called with lifecycle events.
    """

    def __init__(
        self,
        *,
        binary: Path | str = "llama-server",
        hardware: HardwareProfile | None = None,
        idle_ttl_s: float | None = 900.0,
        max_resident: int = 1,
        allow_remote_exposure: bool = False,
        host: str = LOOPBACK_HOST,
        health_timeout_s: float = _HEALTH_TIMEOUT_S,
        on_lifecycle: LifecycleCallback | None = None,
    ) -> None:
        if not allow_remote_exposure and host != LOOPBACK_HOST:
            raise LocalRuntimeError(
                f"refusing to bind a local model server to {host!r}",
                hint=(
                    "local servers bind 127.0.0.1 by default; pass "
                    "allow_remote_exposure=True to override, and understand the exposure"
                ),
            )
        self._binary = Path(binary)
        self._hardware = hardware
        self._idle_ttl_s = idle_ttl_s
        self._max_resident = max(1, max_resident)
        self._host = host
        self._health_timeout_s = max(_HEALTH_MIN_TIMEOUT_S, health_timeout_s)
        self._on_lifecycle = on_lifecycle
        self._servers: dict[str, ServerHandle] = {}
        # One lock for *all* swaps: two simultaneous loads would compete for the same
        # memory and typically lose to each other.
        self._swap_lock = asyncio.Lock()

    # ---- acquisition -----------------------------------------------------------------

    async def acquire(
        self, model_key: str, model_path: Path, plan: ServerPlan, *, persist: bool = False
    ) -> ManagedServer:
        """Get a ready server for a model, starting or reusing one.

        Blocks until the server answers its health probe. Concurrent callers requesting
        different models are serialized, so loads never overlap.

        Raises:
            LocalRuntimeError: If the model cannot fit, the binary is missing, or the
                server fails to become ready.
        """
        existing = self._servers.get(model_key)
        if existing is not None and existing.is_running:
            existing.touch()
            return ManagedServer(existing)

        async with self._swap_lock:
            # Re-check: another caller may have started it while we waited.
            existing = self._servers.get(model_key)
            if existing is not None and existing.is_running:
                existing.touch()
                return ManagedServer(existing)

            await self._reap_dead()
            await self._enforce_capacity(model_key)
            self._check_admission(plan, model_key)
            handle = await self._spawn(model_key, model_path, plan, persist=persist)
            self._servers[model_key] = handle
            return ManagedServer(handle)

    def _check_admission(self, plan: ServerPlan, model_key: str) -> None:
        """Refuse a model that provably will not fit, before paying to find out.

        Only *known* memory figures gate admission: an unknown budget must not block a
        model that would have worked.
        """
        if self._hardware is None:
            return
        primary = self._hardware.primary_accelerator
        if primary is None or primary.unified_memory:
            budget = self._hardware.total_ram_bytes
            label = "system RAM"
        else:
            budget = primary.total_vram_bytes
            label = "VRAM"
        if not budget:
            return

        committed = sum(
            h.plan.estimated_total_bytes for h in self._servers.values() if h.is_running
        )
        required = plan.estimated_total_bytes
        if required and committed + required > budget:
            raise LocalRuntimeError(
                f"{model_key} needs about {_gib(required)} but only "
                f"{_gib(max(0, budget - committed))} of {label} is uncommitted",
                hint=(
                    "unload another model, choose a smaller tier, or use a more "
                    "conservative posture to shrink the context"
                ),
            )

    async def _enforce_capacity(self, incoming: str) -> None:
        """Evict least-recently-used idle servers to make room."""
        while len(self._servers) >= self._max_resident:
            evictable = [
                h for h in self._servers.values() if h.is_idle and not h.persist
            ]
            if not evictable:
                raise LocalRuntimeError(
                    f"cannot start a server for {incoming}: "
                    f"{len(self._servers)} server(s) are resident and all are busy",
                    hint="raise max_resident, or wait for in-flight requests to finish",
                )
            victim = min(evictable, key=lambda h: h.last_activity)
            await self._stop(victim, reason="evicted to make room")

    # ---- process lifecycle -----------------------------------------------------------

    async def _spawn(
        self, model_key: str, model_path: Path, plan: ServerPlan, *, persist: bool
    ) -> ServerHandle:
        """Start a server and wait for it to report healthy."""
        if not model_path.exists():
            raise LocalRuntimeError(
                f"model file not found: {model_path}",
                hint="download the artifact before starting a server",
            )

        binary = self.resolve_binary()
        port = allocate_port(self._host)
        args = [
            str(binary),
            *plan.server_arguments(str(model_path), host=self._host, port=port),
        ]

        self._emit(model_key, "starting", f"port {port}")
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                **_process_group_kwargs(),
            )
        except OSError as exc:
            raise LocalRuntimeError(
                f"could not start llama-server: {exc}",
                hint=f"check that {binary} is executable",
            ) from exc

        handle = ServerHandle(
            model_key=model_key,
            model_path=model_path,
            plan=plan,
            host=self._host,
            port=port,
            process=process,
            started_at=time.monotonic(),
            persist=persist,
        )
        _start_output_reader(handle)
        try:
            await self._await_ready(handle)
        except BaseException:
            await self._stop(handle, reason="failed to become ready")
            raise
        self._emit(model_key, "ready", f"port {port}")
        return handle

    def set_hardware(self, hardware: HardwareProfile) -> None:
        """Late-bind the detected hardware profile.

        Detection is deliberately lazy — probing at construction would tax clients that
        never run a local model — so the adapter hands the profile over once it has one.
        Admission control and backend fallback stay disabled until then.
        """
        self._hardware = hardware

    def resolve_binary(self) -> Path:
        """Locate the llama-server executable without starting anything.

        Public so a health probe can answer "could a server start?" cheaply.

        Falls back to the best installed backend variant for this hardware when the
        configured name is not on PATH (a CUDA build in a known runtime directory beats
        a missing PATH entry).

        Raises:
            LocalRuntimeError: When no usable binary exists anywhere.
        """
        if self._binary.is_absolute() or self._binary.exists():
            if not self._binary.exists():
                raise LocalRuntimeError(
                    f"llama-server not found at {self._binary}",
                    hint="install a llama.cpp runtime, or set the binary path explicitly",
                )
            return self._binary
        found = shutil.which(str(self._binary))
        if found is not None:
            return Path(found)
        if self._hardware is not None:
            from .backends import select_backend

            backend = select_backend(self._hardware)
            if backend is not None:
                return backend.binary
        raise LocalRuntimeError(
            f"could not find {self._binary} on PATH",
            hint=(
                "install llama.cpp's server binary and put it on PATH, or pass its "
                "path to the supervisor"
            ),
        )

    async def _await_ready(self, handle: ServerHandle) -> None:
        """Poll ``/health`` until ready, distinguishing "loading" from "crashed"."""
        deadline = time.monotonic() + self._health_timeout_s
        url = f"http://{handle.host}:{handle.port}/health"

        async with httpx2.AsyncClient(timeout=httpx2.Timeout(5.0)) as client:
            while time.monotonic() < deadline:
                exit_code = handle.process.poll()
                if exit_code is not None:
                    raise LocalRuntimeError(
                        f"llama-server exited with code {exit_code} while loading "
                        f"{handle.model_key}:\n{_format_tail(handle)}",
                        hint=(
                            "the model may be incompatible with this runtime build, or "
                            "the machine may have run out of memory"
                        ),
                    )
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        return
                except httpx2.HTTPError:
                    # Connection refused during startup is expected, not a failure.
                    pass
                await asyncio.sleep(_HEALTH_POLL_INTERVAL_S)

        raise LocalRuntimeError(
            f"llama-server did not become ready within {self._health_timeout_s:.0f}s "
            f"for {handle.model_key}:\n{_format_tail(handle)}",
            hint="a large model on slow storage may need a longer health_timeout_s",
        )

    async def _stop(self, handle: ServerHandle, *, reason: str = "") -> None:
        """Stop a server gracefully, then forcibly, and verify it is gone."""
        self._servers.pop(handle.model_key, None)
        if not handle.is_running:
            return

        self._emit(handle.model_key, "stopping", reason)
        handle.stopping = True
        with contextlib.suppress(OSError):
            handle.process.terminate()

        deadline = time.monotonic() + _STOP_GRACE_S
        while time.monotonic() < deadline:
            if handle.process.poll() is not None:
                break
            await asyncio.sleep(0.1)

        # Always kill the tree, even after a graceful parent exit: on Windows the launcher
        # a runtime is invoked through can exit while the server it spawned keeps running,
        # holding both the port and the GPU. Reaping is fallible, so it is verified below.
        _kill_tree(handle.process)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.to_thread(handle.process.wait), timeout=5.0)

        if handle.process.poll() is None:
            self._emit(
                handle.model_key,
                "crashed",
                "process could not be reaped; its memory may still be held",
            )
        else:
            self._emit(handle.model_key, "stopped", reason)

    async def _reap_dead(self) -> None:
        """Drop handles whose process has exited on its own."""
        for key, handle in list(self._servers.items()):
            if not handle.is_running:
                self._servers.pop(key, None)
                self._emit(key, "crashed", _format_tail(handle))

    # ---- idle management -------------------------------------------------------------

    async def collect_idle(self) -> int:
        """Stop servers idle beyond the TTL. Returns how many were stopped.

        Call periodically. Servers with active streams are never collected, however long
        the generation has been running.
        """
        if self._idle_ttl_s is None:
            return 0
        stopped = 0
        for handle in list(self._servers.values()):
            if handle.persist or not handle.is_idle:
                continue
            if handle.idle_seconds() >= self._idle_ttl_s:
                await self._stop(handle, reason=f"idle for {self._idle_ttl_s:.0f}s")
                stopped += 1
        return stopped

    @property
    def resident_models(self) -> tuple[str, ...]:
        """Model keys with a running server."""
        return tuple(k for k, h in self._servers.items() if h.is_running)

    @property
    def resident_plans(self) -> Mapping[str, ServerPlan]:
        """The launch plan each running server was started with.

        What the tuner *decided*, which is not always what the caller assumed: a plan that
        offloaded no layers explains a local model running an order of magnitude slower
        than the same weights did on the same machine last week.
        """
        return {k: h.plan for k, h in self._servers.items() if h.is_running}

    async def aclose(self) -> None:
        """Stop every supervised server."""
        for handle in list(self._servers.values()):
            await self._stop(handle, reason="supervisor shutting down")

    def _emit(self, model_key: str, state: _LifecycleState, detail: str = "") -> None:
        if self._on_lifecycle is None:
            return
        with contextlib.suppress(Exception):
            self._on_lifecycle(
                ServerLifecycle(server_id=model_key, state=state, detail=detail[:400])
            )


def _start_output_reader(handle: ServerHandle) -> None:
    """Capture the child's recent output so failures can explain themselves.

    A plain daemon thread rather than an asyncio task: ``readline`` on a pipe blocks
    uninterruptibly, so a non-daemon reader would keep the interpreter alive after the
    process it was reading from is gone.
    """
    stream = handle.process.stdout
    if stream is None:
        return

    def pump() -> None:
        """Own the pipe for its whole life.

        Only this thread ever touches the stream. Closing a buffered pipe from another
        thread while this one is blocked in ``readline`` deadlocks, and on Windows a
        grandchild process can keep the write end open after its parent exits — so the
        stream is closed here, on the way out, and nowhere else.
        """
        try:
            for line in iter(stream.readline, b""):
                handle.log_tail.append(line.decode("utf-8", errors="replace").rstrip())
                if handle.stopping:
                    break
        except (ValueError, OSError):
            # The pipe went away during shutdown; there is nothing left to read.
            pass
        finally:
            with contextlib.suppress(Exception):
                stream.close()

    thread = threading.Thread(
        target=pump, name=f"anyinfer-log-{handle.model_key}", daemon=True
    )
    thread.start()


def _format_tail(handle: ServerHandle) -> str:
    """Render the captured log tail for an error message."""
    if not handle.log_tail:
        return "(no output captured from llama-server)"
    return "\n".join(handle.log_tail)


def _process_group_kwargs() -> dict[str, Any]:
    """Start the child in its own group so the whole tree can be terminated.

    The Windows flag is looked up dynamically because it does not exist elsewhere, and this
    module must typecheck identically on every platform.
    """
    if not _IS_WINDOWS:
        return {"start_new_session": True}
    new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", None)
    return {"creationflags": new_group} if new_group is not None else {}


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Forcibly terminate a process and its whole tree.

    Killing only the direct child is not enough: a launcher (a shell script, a ``.bat``, or
    a runtime wrapper) can exit while the server it spawned keeps running — holding both the
    port and the GPU. POSIX process-group calls are looked up dynamically so this module
    typechecks identically on Windows.
    """
    if _IS_WINDOWS:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
                timeout=10,
            )
        with contextlib.suppress(Exception):
            process.kill()
        return

    killpg = getattr(os, "killpg", None)
    getpgid = getattr(os, "getpgid", None)
    sigkill = getattr(signal, "SIGKILL", None)
    if killpg is not None and getpgid is not None and sigkill is not None:
        with contextlib.suppress(Exception):
            killpg(getpgid(process.pid), sigkill)
    with contextlib.suppress(Exception):
        process.kill()


def _gib(value: int) -> str:
    return f"{value / 1024**3:.1f} GiB"
