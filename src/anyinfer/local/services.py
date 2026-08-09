"""Model acquisition for engines that own their own store.

`local.acquire` fetches weights *we* then place and index. This module covers the other
kind of local engine: one that already has a store, a registry, and a downloader of its
own, and simply needs to be told to use them. Ollama is the case in the shipped registry.

Acquisition lives here rather than in an adapter for the reason it always has — fetching
gigabytes is not protocol translation — and a provider that can do it points at this
module from its descriptor rather than implementing it. Which providers *can* is therefore
readable from the registry rather than from a chain of engine checks in the core.

What this deliberately does not do is duplicate the engine's store. The bytes land wherever
the engine keeps them, under whatever name the engine uses; nothing is written to
AnyInfer's own model store, nothing is indexed, and `locate_model()` will not find it —
because it is not ours to find. The honest description of this operation is *make the
engine ready*, not *download a model*.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx2

from ..errors import LocalRuntimeError, ModelNotFoundError
from ..events.telemetry import DownloadProgress
from ..providers.http import build_client, read_error_detail
from ..providers.sse import iter_ndjson

__all__ = [
    "PULL_TIMEOUT_S",
    "PullReport",
    "PullRequest",
    "pull_ollama_model",
]

PULL_TIMEOUT_S = 3_600.0
"""Wall clock for a pull.

Generous on purpose: this is a multi-gigabyte transfer over whatever connection the user
has, and a timeout that fires mid-download turns a slow link into a failure the user cannot
do anything about. Progress is reported throughout, so a stuck transfer is visible long
before this expires.
"""

_PROGRESS_INTERVAL_BYTES = 4 * 1024 * 1024
"""Minimum advance between progress reports, so a fast local transfer does not flood the
observer with one event per chunk. A phase change always reports regardless."""


@dataclass(frozen=True, slots=True)
class PullRequest:
    """What a puller needs to make one model available on one engine.

    Attributes:
        model: The model name in the engine's own namespace (``"qwen3:8b"``).
        base_url: The engine's endpoint, after defaults and shorthand expansion.
        timeout_s: Wall clock for the whole transfer.
        transport: Optional ``httpx2`` transport override, for tests.
        progress: Sink for `DownloadProgress` events, or ``None`` for a silent pull.
    """

    model: str
    base_url: str
    timeout_s: float = PULL_TIMEOUT_S
    transport: Any | None = None
    progress: Callable[[DownloadProgress], None] | None = None


@dataclass(frozen=True, slots=True)
class PullReport:
    """What a pull did.

    Attributes:
        model: The model that is now available.
        already_present: Whether the engine reported it was already there, so nothing was
            transferred. Worth distinguishing: "took two seconds" is reassuring when it
            means *already installed* and alarming when it means *downloaded 8 GB*.
        bytes_transferred: Bytes the engine reported pulling, when it reported any.
        detail: The engine's final status line.
    """

    model: str
    already_present: bool = False
    bytes_transferred: int = 0
    detail: str = ""


async def pull_ollama_model(request: PullRequest) -> PullReport:
    """Make a model available on an Ollama server, streaming its progress.

    Speaks ``POST /api/pull``, whose NDJSON stream reports a status line per phase and byte
    counts per layer. The counts are per-layer, so they are accumulated here into the
    aggregate figures `DownloadProgress` promises — a
    per-layer counter restarting at zero is exactly the defect that field's contract was
    rewritten to prevent.

    Args:
        request: What to pull, from where, and where to report progress.

    Returns:
        The `PullReport`.

    Raises:
        anyinfer.errors.ModelNotFoundError: If the registry has no such model.
        anyinfer.errors.LocalRuntimeError: If the server is unreachable, or the pull fails
            partway through — Ollama reports mid-stream failures as a status field rather
            than an HTTP status, so both shapes surface identically here.
    """
    client = build_client(
        base_url=request.base_url.rstrip("/"),
        headers={"content-type": "application/json"},
        timeout_s=request.timeout_s,
        transport=request.transport,
    )
    tracker = _PullTracker(request)
    try:
        async with client.stream(
            "POST",
            "/api/pull",
            json={"model": request.model, "stream": True},
            timeout=request.timeout_s,
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise _classify(response.status_code, body, request.model)
            async for message in iter_ndjson(
                response.aiter_bytes(),
                # A pull stream is long but every line is small; the cap guards against a
                # server that streams unbounded garbage, not against a large model.
                max_bytes=64 * 1024 * 1024,
                provider="ollama",
            ):
                tracker.absorb(message)
    except (ModelNotFoundError, LocalRuntimeError):
        raise
    except httpx2.HTTPError as exc:
        raise LocalRuntimeError(
            f"could not reach the Ollama server to pull {request.model!r}: {exc}",
            provider="ollama",
            hint="check that Ollama is running and the base URL is right",
        ) from exc
    finally:
        await client.aclose()

    return tracker.finish()


class _PullTracker:
    """Accumulates per-layer counts into the aggregate progress contract."""

    def __init__(self, request: PullRequest) -> None:
        self._request = request
        self._sink = request.progress
        self._per_layer: dict[str, int] = {}
        self._totals: dict[str, int] = {}
        self._status = ""
        self._reported_bytes = -1
        self._saw_transfer = False

    def absorb(self, message: Mapping[str, Any]) -> None:
        """Read one NDJSON line, emitting progress when it moved something."""
        error = message.get("error")
        if error:
            raise _pull_failed(str(error), self._request.model)

        status = str(message.get("status") or "")
        phase_changed = bool(status) and status != self._status
        self._status = status or self._status

        digest = str(message.get("digest") or "")
        completed = message.get("completed")
        total = message.get("total")
        if digest:
            if isinstance(completed, int):
                self._per_layer[digest] = completed
                self._saw_transfer = True
            if isinstance(total, int):
                self._totals[digest] = total

        downloaded = sum(self._per_layer.values())
        advanced = downloaded - self._reported_bytes >= _PROGRESS_INTERVAL_BYTES
        if phase_changed or advanced:
            self._reported_bytes = downloaded
            self._emit(done=False)

    def finish(self) -> PullReport:
        """Emit the terminal progress event and build the report."""
        self._emit(done=True)
        return PullReport(
            model=self._request.model,
            # Ollama answers an already-present model in milliseconds with no layer
            # counts at all, which is the only signal it gives that nothing moved.
            already_present=not self._saw_transfer,
            bytes_transferred=sum(self._per_layer.values()),
            detail=self._status,
        )

    def _emit(self, *, done: bool) -> None:
        """Report aggregate progress, disabling a sink that raises rather than failing."""
        if self._sink is None:
            return
        total = sum(self._totals.values()) or None
        try:
            self._sink(
                DownloadProgress(
                    artifact_id=self._request.model,
                    downloaded_bytes=sum(self._per_layer.values()),
                    total_bytes=total,
                    done=done,
                    phase=self._status,
                    file_count=len(self._totals),
                    session_bytes=sum(self._per_layer.values()),
                )
            )
        except Exception:  # noqa: BLE001 — a reporting sink must never fail a transfer
            self._sink = None


def _classify(status: int, body: bytes, model: str) -> Exception:
    """Map a pull's HTTP failure onto the typed hierarchy."""
    detail = read_error_detail(body)
    lowered = detail.lower()
    if status == 404 or any(marker in lowered for marker in _MISSING_MODEL_MARKERS):
        return ModelNotFoundError(
            f"the Ollama registry has no model named {model!r}: {detail}",
            provider="ollama",
            hint="check the name at ollama.com/library, including its tag",
        )
    return LocalRuntimeError(
        f"pulling {model!r} failed: {detail}",
        provider="ollama",
        http_status=status,
    )


_MISSING_MODEL_MARKERS = ("not found", "no such", "does not exist", "unknown model")
"""What Ollama says when the name is wrong.

More than one spelling because the registry answers a missing manifest with
``pull model manifest: file does not exist`` — which reads like a disk error and is
actually a typo in the model name, and telling a user to check their disk would send them
somewhere there is nothing to find.
"""


def _pull_failed(detail: str, model: str) -> Exception:
    """Map a mid-stream failure, which Ollama reports in the body rather than the status."""
    lowered = detail.lower()
    if any(marker in lowered for marker in _MISSING_MODEL_MARKERS):
        return ModelNotFoundError(
            f"the Ollama registry has no model named {model!r}: {detail}",
            provider="ollama",
            hint="check the name at ollama.com/library, including its tag",
        )
    return LocalRuntimeError(
        f"pulling {model!r} failed partway through: {detail}",
        provider="ollama",
        hint="retry the pull; Ollama resumes from the layers it already has",
    )
