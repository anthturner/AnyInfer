"""Carrying JSON-RPC to an MCP server, over a subprocess or over HTTP.

The stdio transport spawns and supervises a child process, which is the failure surface
`anyinfer.local.server` already learned the expensive way — three real concurrency defects,
all of them on Windows, all of them the kind that hang a test suite rather than fail it. The
rules it arrived at are reused verbatim rather than rediscovered:

- **The reader thread owns its stream for its whole life.** Closing a pipe from another
  thread deadlocks against a reader blocked in ``readline``, and on Windows an orphaned
  grandchild keeps the write end open so the close never returns.
- **The reader is a daemon.** ``readline`` on a pipe is uninterruptible, so a non-daemon
  reader blocks interpreter shutdown.
- **Termination kills the tree, always.** A launcher script can exit while the server it
  spawned keeps running.
- **Every wait is bounded.** ``Popen.wait`` on an unreaped tree hangs.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping
from typing import Any, Protocol

import httpx2

from ..errors import ToolLoopError
from .protocol import decode_message

__all__ = ["HTTPTransport", "MCPTransport", "StdioTransport"]

_IS_WINDOWS = sys.platform == "win32"

_TERMINATE_TIMEOUT_S = 5.0
"""How long a server gets to exit gracefully before its tree is killed."""


class MCPTransport(Protocol):
    """What a transport must do: send one payload, get one reply, and shut down."""

    async def request(self, payload: bytes, *, timeout_s: float) -> dict[str, Any]:
        """Send a JSON-RPC request and return the decoded reply."""
        ...

    async def notify(self, payload: bytes) -> None:
        """Send a JSON-RPC notification, which has no reply."""
        ...

    async def aclose(self) -> None:
        """Release whatever this transport holds."""
        ...


class StdioTransport:
    """Speaks newline-delimited JSON-RPC to a spawned server process.

    Args:
        command: argv to spawn.
        env: Extra environment for the child, merged over the current environment. Values
            are resolved and registered for redaction by the caller before they arrive.
        cwd: Working directory for the child.
    """

    def __init__(
        self,
        command: tuple[str, ...],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        if not command:
            raise ToolLoopError(
                "an MCP stdio server needs a command to run",
                hint="pass command=('my-mcp-server', '--flag')",
            )
        self._command = command
        self._env = {**os.environ, **dict(env or {})}
        self._cwd = cwd
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = asyncio.Lock()

    def _spawn(self) -> subprocess.Popen[bytes]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        try:
            process = subprocess.Popen(
                list(self._command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._env,
                cwd=self._cwd,
                **_spawn_flags(),
            )
        except OSError as exc:
            raise ToolLoopError(
                f"could not start the MCP server {self._command[0]!r}",
                hint="check that it is installed and on PATH",
            ) from exc
        self._process = process
        _start_stderr_drain(process, self._command[0])
        return process

    async def request(self, payload: bytes, *, timeout_s: float) -> dict[str, Any]:
        """Write one request and read until its reply arrives.

        Serialized by a lock: stdio is one stream, so two concurrent requests would
        interleave their writes and race for each other's replies.
        """
        async with self._lock:
            process = self._spawn()
            await asyncio.to_thread(self._write, process, payload)
            try:
                async with asyncio.timeout(timeout_s):
                    line = await asyncio.to_thread(self._read_line, process)
            except TimeoutError as exc:
                raise ToolLoopError(
                    f"the MCP server {self._command[0]!r} did not answer within {timeout_s:g}s",
                    hint="raise the server's timeout_s, or check whether it is wedged",
                ) from exc
            return decode_message(line)

    async def notify(self, payload: bytes) -> None:
        """Write one notification; nothing is read back."""
        async with self._lock:
            process = self._spawn()
            await asyncio.to_thread(self._write, process, payload)

    def _write(self, process: subprocess.Popen[bytes], payload: bytes) -> None:
        stdin = process.stdin
        if stdin is None:  # pragma: no cover — Popen was configured with a pipe
            raise ToolLoopError("the MCP server's input stream is not available")
        try:
            stdin.write(payload + b"\n")
            stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise ToolLoopError(
                f"the MCP server {self._command[0]!r} closed its input stream",
                hint="the server process probably exited; check its stderr",
            ) from exc

    def _read_line(self, process: subprocess.Popen[bytes]) -> bytes:
        stdout = process.stdout
        if stdout is None:  # pragma: no cover — Popen was configured with a pipe
            raise ToolLoopError("the MCP server's output stream is not available")
        while True:
            line = stdout.readline()
            if not line:
                raise ToolLoopError(
                    f"the MCP server {self._command[0]!r} exited without answering",
                    hint="check the server's stderr output for a crash",
                )
            stripped: bytes = line.strip()
            # Servers sometimes print banners on stdout. Skipping blank lines keeps one
            # stray newline from being read as a protocol error.
            if stripped:
                return stripped

    async def aclose(self) -> None:
        """Stop the server, killing its whole tree if it does not go quietly."""
        process = self._process
        self._process = None
        if process is None:
            return
        await asyncio.to_thread(_terminate, process)


class HTTPTransport:
    """Speaks JSON-RPC over streamable HTTP.

    Args:
        url: The server endpoint.
        headers: Extra request headers, including authentication when the server requires it.
        transport: Test seam; an ``httpx2`` transport that intercepts the traffic.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        transport: Any | None = None,
    ) -> None:
        self._url = url
        self._client = httpx2.AsyncClient(
            headers={
                "content-type": "application/json",
                # Either shape is acceptable per the transport spec; the server picks.
                "accept": "application/json, text/event-stream",
                **dict(headers or {}),
            },
            transport=transport,
        )

    async def request(self, payload: bytes, *, timeout_s: float) -> dict[str, Any]:
        """POST one request and decode the reply, from JSON or from an SSE frame."""
        try:
            response = await self._client.post(self._url, content=payload, timeout=timeout_s)
        except httpx2.HTTPError as exc:
            raise ToolLoopError(
                f"could not reach the MCP server at {self._url}",
                hint="check the URL and that the server is running",
            ) from exc

        if response.status_code >= 400:
            raise ToolLoopError(
                f"the MCP server at {self._url} answered {response.status_code}",
                hint="check authentication headers and the endpoint path",
            )

        content_type = response.headers.get("content-type", "")
        body = response.text
        if "text/event-stream" in content_type:
            body = _first_sse_data(body)
        return decode_message(body)

    async def notify(self, payload: bytes) -> None:
        """POST one notification, ignoring the (empty) reply."""
        with contextlib.suppress(httpx2.HTTPError):
            await self._client.post(self._url, content=payload, timeout=10.0)

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


def _first_sse_data(body: str) -> str:
    """Pull the first ``data:`` payload out of an SSE body.

    A tool call produces one reply; notifications the client does not implement are
    skipped rather than mistaken for it.
    """
    for line in body.splitlines():
        if line.startswith("data:"):
            candidate = line[5:].strip()
            if candidate:
                return candidate
    raise ToolLoopError("an MCP server sent an event stream carrying no data frame")


def _spawn_flags() -> dict[str, Any]:
    """Put the child in its own process group, so the whole tree can be signalled."""
    if not _IS_WINDOWS:
        return {"start_new_session": True}
    new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", None)
    return {"creationflags": new_group} if new_group is not None else {}


def _start_stderr_drain(process: subprocess.Popen[bytes], name: str) -> None:
    """Drain the child's stderr so a chatty server cannot fill its pipe and block.

    The thread owns the stream for its whole life and is a daemon, for the two reasons
    this module's docstring gives. Output is discarded rather than logged: it is the
    server's own diagnostic text, and this library does not write to a user's stderr
    uninvited.
    """

    def pump() -> None:
        stream = process.stderr
        if stream is None:  # pragma: no cover
            return
        try:
            for _ in iter(stream.readline, b""):
                pass
        except (ValueError, OSError):
            return

    thread = threading.Thread(target=pump, name=f"anyinfer-mcp-{name}", daemon=True)
    thread.start()


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """Ask a server to exit, then make sure its whole tree is gone."""
    if process.poll() is None:
        with contextlib.suppress(Exception):
            process.terminate()
        with contextlib.suppress(Exception):
            process.wait(timeout=_TERMINATE_TIMEOUT_S)

    # Always kill the tree, even after a graceful exit: reaping is fallible, and a
    # launcher that already exited may have left the real server running.
    _kill_tree(process)
    with contextlib.suppress(Exception):
        process.wait(timeout=_TERMINATE_TIMEOUT_S)

    for stream in (process.stdin, process.stdout, process.stderr):
        with contextlib.suppress(Exception):
            if stream is not None:
                stream.close()


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Forcibly terminate a process and everything it spawned."""
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
