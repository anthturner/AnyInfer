"""Getting model weights onto this disk: plan → preflight → fetch → verify → place.

One engine for both artifact shapes. A GGUF variant is a file set whose handle is the first
shard; a Hugging Face snapshot is a directory whose handle is the directory. The *file list*
and the *handle* differ; the machinery — resume, digest verification, locking, cancellation,
and progress accounting — does not, and those are exactly the things that are expensive to
get right twice.

Progress is reported **for the whole acquisition**, not per file. A sharded artifact whose
byte counter restarts at zero on every shard is worse than no progress bar, because a user
cannot tell a restart from a stall. `AcquisitionProgress` therefore carries aggregate
totals, counts bytes that were already on disk, and knows its full size before the first
byte arrives — the payoff for pinning sizes in the catalog.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from urllib.request import url2pathname

import httpx2

from ..errors import LocalRuntimeError
from .downloads import FileLock, _read_and_hash, license_allowed
from .sources import RemoteFile, ResolvedArtifact, SourceRef, get_resolver
from .store import ModelStore, StoredFile, StoreEntry, entry_id_for, placement_for

__all__ = [
    "AcquisitionPhase",
    "AcquisitionPlan",
    "AcquisitionProgress",
    "AcquisitionReport",
    "AcquisitionRequest",
    "ProgressSink",
    "acquire",
    "acquire_sync",
    "launch_hints_for",
    "plan_acquisition",
]

AcquisitionPhase = Literal["resolving", "planning", "downloading", "verifying", "placing", "done"]
"""Where an acquisition is. Every transition produces a callback, unthrottled."""

_CHUNK_BYTES = 1024 * 1024
_PROGRESS_INTERVAL_S = 0.25
_PROGRESS_BYTES = 4 * 1024 * 1024
_RATE_MIN_SECONDS = 2.0
_RATE_MIN_BYTES = 4 * 1024 * 1024
_DISK_MARGIN = 1.10
"""Refuse to start without ten percent slack over the remaining transfer."""


@dataclass(frozen=True, slots=True)
class AcquisitionProgress:
    """One progress report for a whole acquisition.

    The sink may be invoked from a worker thread. It **must not block, must not raise, and
    must not re-enter the client** — a progress bar that can deadlock a download is a bug
    with no upside. A sink that raises anyway is caught, recorded once as a warning on the
    report, and then dropped for the rest of the run.

    Attributes:
        model_id: The catalog model being acquired.
        variant_id: The variant being acquired.
        phase: Which stage this report came from.
        file_index: 1-based index of the file that most recently advanced.
        file_count: How many files this acquisition covers.
        filename: Name of the file that most recently advanced.
        file_downloaded_bytes: Bytes present for that file, including a resumed prefix.
        file_total_bytes: Expected size of that file, when known.
        total_downloaded_bytes: Bytes present across every file — **including what was
            already on disk**, so resuming a 90%-complete transfer reports 90%, not 0%.
        total_bytes: Total expected bytes, known before the first byte arrives whenever the
            catalog or the listing API supplied sizes.
        total_is_estimate: True when any file's size came from a guess rather than a
            pinned or reported figure.
        session_bytes: Bytes this run actually transferred, which is what rate and ETA are
            derived from.
        bytes_per_second: Transfer rate, or ``None`` until there is a real sample.
        eta_seconds: Seconds remaining, or ``None`` on the same condition. A wildly wrong
            ETA in the first second is worse than no ETA.
    """

    model_id: str
    variant_id: str
    phase: AcquisitionPhase
    file_index: int = 0
    file_count: int = 0
    filename: str = ""
    file_downloaded_bytes: int = 0
    file_total_bytes: int | None = None
    total_downloaded_bytes: int = 0
    total_bytes: int | None = None
    total_is_estimate: bool = False
    session_bytes: int = 0
    bytes_per_second: float | None = None
    eta_seconds: float | None = None

    @property
    def fraction(self) -> float | None:
        """Completion as a fraction, or ``None`` when the total is unknown."""
        if not self.total_bytes:
            return None
        return min(1.0, self.total_downloaded_bytes / self.total_bytes)


ProgressSink = Callable[[AcquisitionProgress], None]
"""Receives `AcquisitionProgress`. See its docstring for the threading contract."""


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    """What an acquisition will do, before it does any of it.

    Attributes:
        entry_id: The store entry that will be written.
        model_id: The catalog model.
        variant_id: The catalog variant.
        kind: ``"gguf"`` or ``"hf_repo"``.
        engine: Which engine the result is for.
        quantization: What will be on disk.
        directory: Store-relative destination.
        handle: Store-relative engine handle.
        files: Every file, resolved.
        already_have_bytes: Bytes already on disk — verified files plus resumable
            ``.part`` prefixes.
        total_bytes: Total size, or ``None`` when any file's size is unknown.
        warnings: Notes from resolution.
        satisfied: True when everything is already present and verified.
    """

    entry_id: str
    model_id: str
    variant_id: str
    kind: str
    engine: str
    quantization: str
    directory: str
    handle: str
    files: tuple[RemoteFile, ...]
    already_have_bytes: int = 0
    total_bytes: int | None = None
    warnings: tuple[str, ...] = ()
    satisfied: bool = False
    revision: str | None = None
    repo: str | None = None
    license: str = ""

    @property
    def remaining_bytes(self) -> int | None:
        """Bytes still to transfer, or ``None`` when the total is unknown."""
        if self.total_bytes is None:
            return None
        return max(0, self.total_bytes - self.already_have_bytes)

    @property
    def total_is_estimate(self) -> bool:
        """Whether any file's size was unknown, making the total a floor."""
        return any(f.size_bytes is None for f in self.files)


@dataclass(frozen=True, slots=True)
class AcquisitionReport:
    """The outcome of an acquisition.

    Attributes:
        plan: What was planned.
        entry: The registered store entry, or ``None`` for a dry run or a cancellation.
        downloaded_bytes: Bytes transferred by this run.
        reused: True when nothing had to be transferred.
        cancelled: True when the caller stopped it. Partial transfers are kept.
        dry_run: True when nothing was written.
        warnings: Everything the caller should know.
    """

    plan: AcquisitionPlan
    entry: StoreEntry | None = None
    downloaded_bytes: int = 0
    reused: bool = False
    cancelled: bool = False
    dry_run: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def path(self) -> Path | None:
        """The engine handle, when one was registered."""
        return None if self.entry is None else Path(self.entry.handle)


@dataclass(frozen=True, slots=True)
class AcquisitionRequest:
    """Everything one acquisition needs.

    Attributes:
        ref: Where the bytes come from.
        model_id: Catalog model id, for the index and for progress reports.
        variant_id: Catalog variant id.
        kind: ``"gguf"`` or ``"hf_repo"``.
        engine: Which engine the result is for.
        quantization: What will be on disk.
        license: License id, checked when ``enforce_license`` is set.
        token: Credential for the source, when it needs one.
        max_concurrent_files: How many transfers may run at once.
        allow_unverified: Accept files no digest can check.
        enforce_license: Refuse licenses outside the allowlist.
        launch_hints: Advisory engine arguments to attach to the result.
    """

    ref: SourceRef
    model_id: str
    variant_id: str = ""
    kind: str = "gguf"
    engine: str = "llama.cpp"
    quantization: str = ""
    license: str = ""
    token: str | None = None
    max_concurrent_files: int = 3
    allow_unverified: bool = False
    enforce_license: bool = False
    launch_hints: Mapping[str, Any] = field(default_factory=dict)


# ---- planning -----------------------------------------------------------------------------


async def plan_acquisition(
    request: AcquisitionRequest,
    *,
    store: ModelStore | None = None,
    client: httpx2.AsyncClient | None = None,
) -> AcquisitionPlan:
    """Resolve a source and work out exactly what would be transferred.

    Separated from the transfer so an application can put a real confirmation dialog in
    front of a forty-gigabyte download instead of discovering the size afterwards.
    """
    target = store or ModelStore()
    resolver = get_resolver(request.ref.resolver)
    resolved: ResolvedArtifact = await resolver.resolve(
        request.ref, token=request.token, client=client
    )

    if not resolved.files:
        raise LocalRuntimeError(
            f"the source for {request.model_id!r} resolved to no files",
            hint="check the repository, revision, and include patterns",
        )

    revision = resolved.revision or request.ref.revision
    directory = placement_for(
        request.kind, request.ref, revision=revision, variant_id=request.variant_id
    )
    entry_id = entry_id_for(
        request.kind,
        repo=resolved.repo or request.ref.repo,
        revision=revision,
        variant_id=request.variant_id or request.model_id,
        filename=resolved.files[0].path,
    )
    handle = f"{directory}/{resolved.files[0].path}" if request.kind == "gguf" else directory

    entry_dir = target.root / directory
    staging = target.staging_dir(entry_id)
    already = 0
    all_present = True
    for remote in resolved.files:
        destination = entry_dir / remote.path
        if destination.exists() and destination.stat().st_size == (remote.size_bytes or -1):
            already += destination.stat().st_size
            continue
        all_present = False
        partial = staging / f"{remote.path}.part"
        if partial.exists():
            already += partial.stat().st_size

    warnings = list(resolved.warnings)
    unverifiable = [f.path for f in resolved.files if f.digest_kind == "none"]
    if unverifiable and not request.allow_unverified:
        raise LocalRuntimeError(
            f"{len(unverifiable)} file(s) carry no digest and cannot be verified: "
            f"{', '.join(unverifiable[:3])}",
            hint=(
                "pin digests in the source reference, or pass allow_unverified=True to "
                "accept files whose bytes cannot be checked"
            ),
        )
    if unverifiable:
        warnings.append(f"{len(unverifiable)} file(s) will be stored without verification")

    if request.enforce_license and request.license and not license_allowed(request.license):
        raise LocalRuntimeError(
            f"model {request.model_id!r} is licensed {request.license!r}, which is not in "
            "the allowed set",
            hint="add it through a catalog overlay if you have accepted its terms",
        )

    return AcquisitionPlan(
        entry_id=entry_id,
        model_id=request.model_id,
        variant_id=request.variant_id,
        kind=request.kind,
        engine=request.engine,
        quantization=request.quantization,
        directory=directory,
        handle=handle,
        files=resolved.files,
        already_have_bytes=already,
        total_bytes=resolved.total_bytes,
        warnings=tuple(warnings),
        satisfied=all_present,
        revision=revision,
        repo=resolved.repo or request.ref.repo,
        license=request.license,
    )


# ---- the engine ------------------------------------------------------------------------------


class _Aggregate:
    """Aggregate byte accounting and callback throttling for one acquisition.

    Throttled to at most one callback per 250 ms *or* per 4 MB, whichever comes first, so a
    forty-gigabyte download cannot generate forty thousand UI updates — plus an
    unconditional callback on every phase change, every file completion, and the terminal
    ``done``, so a UI can never miss a state change.
    """

    def __init__(
        self,
        plan: AcquisitionPlan,
        sink: ProgressSink | None,
        *,
        already: int,
    ) -> None:
        self._plan = plan
        self._sink = sink
        self._lock = asyncio.Lock()
        self._total_downloaded = already
        self._session = 0
        self._started = time.monotonic()
        self._last_emit = 0.0
        self._last_bytes = 0
        self._sink_failed = False
        self.warnings: list[str] = []

    async def advance(
        self,
        *,
        phase: AcquisitionPhase,
        index: int,
        remote: RemoteFile,
        file_bytes: int,
        delta: int,
        force: bool = False,
    ) -> None:
        """Record progress on one file and emit if the throttle allows."""
        async with self._lock:
            self._total_downloaded += delta
            self._session += delta
            now = time.monotonic()
            due = (
                force
                or now - self._last_emit >= _PROGRESS_INTERVAL_S
                or self._total_downloaded - self._last_bytes >= _PROGRESS_BYTES
            )
            if not due:
                return
            self._last_emit = now
            self._last_bytes = self._total_downloaded
            snapshot = self._snapshot(phase, index, remote, file_bytes, now)
        self._emit(snapshot)

    async def phase(self, phase: AcquisitionPhase, *, filename: str = "") -> None:
        """Emit an unconditional report for a phase transition."""
        async with self._lock:
            now = time.monotonic()
            self._last_emit = now
            snapshot = self._snapshot(
                phase,
                0,
                RemoteFile(path=filename, url=""),
                0,
                now,
            )
        self._emit(snapshot)

    def _snapshot(
        self,
        phase: AcquisitionPhase,
        index: int,
        remote: RemoteFile,
        file_bytes: int,
        now: float,
    ) -> AcquisitionProgress:
        elapsed = now - self._started
        rate: float | None = None
        eta: float | None = None
        if elapsed >= _RATE_MIN_SECONDS and self._session >= _RATE_MIN_BYTES:
            rate = self._session / elapsed
            remaining = self._plan.total_bytes
            if remaining is not None and rate > 0:
                eta = max(0.0, (remaining - self._total_downloaded) / rate)
        return AcquisitionProgress(
            model_id=self._plan.model_id,
            variant_id=self._plan.variant_id,
            phase=phase,
            file_index=index,
            file_count=len(self._plan.files),
            filename=remote.filename or remote.path,
            file_downloaded_bytes=file_bytes,
            file_total_bytes=remote.size_bytes,
            total_downloaded_bytes=self._total_downloaded,
            total_bytes=self._plan.total_bytes,
            total_is_estimate=self._plan.total_is_estimate,
            session_bytes=self._session,
            bytes_per_second=rate,
            eta_seconds=eta,
        )

    def _emit(self, progress: AcquisitionProgress) -> None:
        """Call the sink, disabling it permanently if it raises."""
        if self._sink is None or self._sink_failed:
            return
        try:
            self._sink(progress)
        except Exception as exc:  # noqa: BLE001 — a broken sink must not fail a download
            self._sink_failed = True
            self.warnings.append(
                f"the progress callback raised {type(exc).__name__} and was disabled for "
                "the rest of this acquisition"
            )

    @property
    def session_bytes(self) -> int:
        """Bytes this run transferred."""
        return self._session


async def acquire(
    request: AcquisitionRequest,
    *,
    store: ModelStore | None = None,
    client: httpx2.AsyncClient | None = None,
    progress: ProgressSink | None = None,
    plan: AcquisitionPlan | None = None,
    dry_run: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> AcquisitionReport:
    """Acquire a model variant into the store.

    Args:
        request: What to acquire and from where.
        store: The destination store; defaults to the standard root.
        client: An ``httpx2.AsyncClient``, for tests or custom transports.
        progress: Aggregate progress sink.
        plan: A plan from `plan_acquisition`, to avoid resolving twice.
        dry_run: Resolve and report sizes without writing anything.
        cancel_check: Polled between chunks; returning ``True`` stops the acquisition
            cooperatively. Task cancellation works too and is the primary mechanism —
            this exists for the synchronous facade.

    Returns:
        The report, naming the registered entry.

    Raises:
        LocalRuntimeError: On a transfer failure, a digest mismatch, or insufficient disk.
    """
    target = store or ModelStore()
    resolved_plan = plan or await plan_acquisition(request, store=target, client=client)
    aggregate = _Aggregate(resolved_plan, progress, already=resolved_plan.already_have_bytes)

    await aggregate.phase("planning")
    if dry_run:
        await aggregate.phase("done")
        return AcquisitionReport(
            plan=resolved_plan,
            dry_run=True,
            warnings=(*resolved_plan.warnings, *aggregate.warnings),
        )

    existing = target.get(resolved_plan.entry_id)
    if existing is not None and not target.check(existing):
        await aggregate.phase("done")
        return AcquisitionReport(
            plan=resolved_plan,
            entry=existing,
            reused=True,
            warnings=(*resolved_plan.warnings, *aggregate.warnings),
        )

    entry_dir = target.root / resolved_plan.directory
    staging = target.staging_dir(resolved_plan.entry_id)
    _preflight_disk(target.root, resolved_plan)

    owns_client = client is None
    http = client or httpx2.AsyncClient(timeout=httpx2.Timeout(60.0))
    cancelled = False
    try:
        async with FileLock(target.lock_path(resolved_plan.entry_id)):
            # Re-check under the lock: a sibling process may have finished the same entry
            # while this one waited, and transferring it twice would be pure waste.
            existing = target.get(resolved_plan.entry_id)
            if existing is not None and not target.check(existing):
                await aggregate.phase("done")
                return AcquisitionReport(
                    plan=resolved_plan,
                    entry=existing,
                    reused=True,
                    warnings=(*resolved_plan.warnings, *aggregate.warnings),
                )

            staging.mkdir(parents=True, exist_ok=True)
            await aggregate.phase("downloading")

            semaphore = asyncio.Semaphore(max(1, request.max_concurrent_files))
            stored: list[StoredFile | None] = [None] * len(resolved_plan.files)

            async def fetch(index: int, remote: RemoteFile) -> None:
                async with semaphore:
                    stored[index] = await _fetch_one(
                        http,
                        remote,
                        index=index + 1,
                        entry_dir=entry_dir,
                        staging=staging,
                        aggregate=aggregate,
                        token=request.token,
                        cancel_check=cancel_check,
                    )

            try:
                await asyncio.gather(*(fetch(i, f) for i, f in enumerate(resolved_plan.files)))
            except _Cancelled:
                cancelled = True
            except asyncio.CancelledError:
                # Partial transfers are deliberately kept: cancelling is not deleting, and
                # the next run resumes from the .part files.
                raise

            if cancelled:
                await aggregate.phase("done")
                return AcquisitionReport(
                    plan=resolved_plan,
                    cancelled=True,
                    downloaded_bytes=aggregate.session_bytes,
                    warnings=(*resolved_plan.warnings, *aggregate.warnings),
                )

            await aggregate.phase("placing")
            files = tuple(f for f in stored if f is not None)
            entry = StoreEntry(
                id=resolved_plan.entry_id,
                kind=resolved_plan.kind,
                model_id=resolved_plan.model_id,
                variant_id=resolved_plan.variant_id,
                quantization=resolved_plan.quantization,
                engine=resolved_plan.engine,
                source={
                    **request.ref.to_json(),
                    "revision": resolved_plan.revision or "",
                    "repo": resolved_plan.repo or "",
                },
                directory=resolved_plan.directory,
                handle=resolved_plan.handle,
                files=files,
                license=resolved_plan.license,
                warnings=resolved_plan.warnings,
            )
            # Registered only after every file verified: a half-complete snapshot must be
            # invisible to locate(), never a partially-usable directory.
            registered = target.register(entry)
            target.clear_staging(resolved_plan.entry_id)
    finally:
        if owns_client:
            await http.aclose()

    await aggregate.phase("done")
    return AcquisitionReport(
        plan=resolved_plan,
        entry=registered,
        downloaded_bytes=aggregate.session_bytes,
        reused=aggregate.session_bytes == 0,
        warnings=(*resolved_plan.warnings, *aggregate.warnings),
    )


class _Cancelled(Exception):  # noqa: N818 — control flow, not a failure
    """Raised internally when a cooperative cancel check fires."""


async def _fetch_one(
    client: httpx2.AsyncClient,
    remote: RemoteFile,
    *,
    index: int,
    entry_dir: Path,
    staging: Path,
    aggregate: _Aggregate,
    token: str | None,
    cancel_check: Callable[[], bool] | None,
) -> StoredFile:
    """Fetch, verify, and place one file.

    The file-level primitive: atomic ``.part``, ``Range`` resume, digest verification, then
    rename into place. Lifted from the synchronous downloader rather than rewritten,
    because a rewrite here is where a data-loss bug would come from.
    """
    destination = entry_dir / remote.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = staging / f"{remote.path}.part"
    partial.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and _matches(destination, remote):
        stat = destination.stat()
        return StoredFile(
            path=remote.path,
            size_bytes=stat.st_size,
            digest=remote.digest,
            digest_kind=remote.digest_kind,
            verified=remote.digest_kind != "none",
            mtime=stat.st_mtime,
        )

    if urlsplit(remote.url).scheme == "file":
        return _place_local(remote)

    existing = partial.stat().st_size if partial.exists() else 0
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if existing:
        headers["Range"] = f"bytes={existing}-"

    written = existing
    try:
        async with client.stream(
            "GET", remote.url, headers=headers, follow_redirects=True
        ) as response:
            if existing and response.status_code == 200:
                # The server ignored the range request, so the partial file is not a prefix
                # of this body; start over rather than concatenating garbage.
                await aggregate.advance(
                    phase="downloading",
                    index=index,
                    remote=remote,
                    file_bytes=0,
                    delta=-existing,
                    force=True,
                )
                existing = 0
                written = 0
                with contextlib.suppress(OSError):
                    partial.unlink()
            elif response.status_code == 416:
                # The range was unsatisfiable: the .part is at least as long as the body.
                with contextlib.suppress(OSError):
                    partial.unlink()
                raise LocalRuntimeError(
                    f"resuming {remote.filename} failed; the partial file was discarded",
                    hint="retry — the transfer will start from the beginning",
                )
            elif response.status_code in (401, 403):
                raise LocalRuntimeError(
                    f"access to {remote.filename} was refused (HTTP {response.status_code})",
                    hint="the repository may be gated; set HF_TOKEN and accept its terms",
                    http_status=response.status_code,
                )
            elif response.status_code not in (200, 206):
                raise LocalRuntimeError(
                    f"download of {remote.filename} failed with HTTP {response.status_code}",
                    hint="check the source URL, or your network connection",
                    http_status=response.status_code,
                )

            mode = "ab" if existing else "wb"
            with partial.open(mode) as handle:
                async for chunk in response.aiter_bytes(_CHUNK_BYTES):
                    if cancel_check is not None and cancel_check():
                        raise _Cancelled
                    handle.write(chunk)
                    written += len(chunk)
                    await aggregate.advance(
                        phase="downloading",
                        index=index,
                        remote=remote,
                        file_bytes=written,
                        delta=len(chunk),
                    )
    except httpx2.HTTPError as exc:
        raise LocalRuntimeError(
            f"download of {remote.filename} failed: {exc}",
            hint="check your network connection and retry; partial progress is kept",
        ) from exc

    await aggregate.phase("verifying", filename=remote.filename)
    if remote.digest_kind != "none" and not _verify(partial, remote):
        with contextlib.suppress(OSError):
            partial.unlink()
        raise LocalRuntimeError(
            f"{remote.filename} failed {remote.digest_kind} verification after download",
            hint=(
                "the file may be corrupt, or the source may have changed since it was "
                "pinned; nothing was registered"
            ),
        )

    partial.replace(destination)
    stat = destination.stat()
    await aggregate.advance(
        phase="downloading",
        index=index,
        remote=remote,
        file_bytes=stat.st_size,
        delta=0,
        force=True,
    )
    return StoredFile(
        path=remote.path,
        size_bytes=stat.st_size,
        digest=remote.digest,
        digest_kind=remote.digest_kind,
        verified=remote.digest_kind != "none",
        mtime=stat.st_mtime,
    )


def _place_local(remote: RemoteFile) -> StoredFile:
    """Register an already-local file without copying it.

    The local resolver's files are already where they belong; copying them would double a
    user's disk usage for no benefit.

    The URL was built by ``Path.as_uri()``, so ``url2pathname`` is its exact inverse on
    both platform shapes: it keeps the leading slash of a POSIX path while dropping the
    one that precedes a Windows drive letter, and it undoes the percent-encoding that
    ``as_uri`` applies to spaces and other reserved characters.
    """
    source = Path(url2pathname(urlsplit(remote.url).path))
    stat = source.stat()
    return StoredFile(
        path=remote.path,
        size_bytes=stat.st_size,
        digest=remote.digest,
        digest_kind=remote.digest_kind,
        verified=remote.digest_kind != "none" and _verify(source, remote),
        mtime=stat.st_mtime,
    )


def _matches(path: Path, remote: RemoteFile) -> bool:
    """Whether an on-disk file is already the one we would fetch."""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if remote.size_bytes is not None and size != remote.size_bytes:
        return False
    return remote.digest_kind == "none" or _verify(path, remote)


def _verify(path: Path, remote: RemoteFile) -> bool:
    """Check a file against its expected digest, in whichever form the source gave."""
    if remote.digest_kind == "sha256":
        return _sha256(path) == remote.digest.lower()
    if remote.digest_kind == "git-sha1":
        return _git_blob_sha1(path) == remote.digest.lower()
    return True


def _sha256(path: Path) -> str:
    return _read_and_hash(path, hashlib.sha256)


def _git_blob_sha1(path: Path) -> str:
    """Compute the git blob hash small Hugging Face files are identified by."""
    size = path.stat().st_size
    return _read_and_hash(
        path, lambda: hashlib.sha1(f"blob {size}\0".encode(), usedforsecurity=False)
    )


def _preflight_disk(root: Path, plan: AcquisitionPlan) -> None:
    """Refuse to start a transfer that cannot finish.

    Filling a user's disk with a sixty-gigabyte download that fails at 98% is the worst
    available outcome, and it is entirely avoidable with one ``statvfs``.
    """
    remaining = plan.remaining_bytes
    if not remaining:
        return
    root.mkdir(parents=True, exist_ok=True)
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        return
    needed = int(remaining * _DISK_MARGIN)
    if free < needed:
        raise LocalRuntimeError(
            f"{plan.model_id} needs about {needed / 1024**3:.1f} GiB of free space but only "
            f"{free / 1024**3:.1f} GiB is available at {root}",
            hint="free space, or set ANYINFER_MODEL_DIR to a larger volume",
        )


def acquire_sync(
    request: AcquisitionRequest,
    *,
    store: ModelStore | None = None,
    progress: ProgressSink | None = None,
    dry_run: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> AcquisitionReport:
    """Blocking wrapper around `acquire`, for callers with no event loop.

    Raises:
        RuntimeError: If called from inside a running event loop, where it would deadlock.
            Use `acquire` there.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "acquire_sync() cannot be called from a running event loop; await acquire()"
        )
    return asyncio.run(
        acquire(
            request,
            store=store,
            progress=progress,
            dry_run=dry_run,
            cancel_check=cancel_check,
        )
    )


def launch_hints_for(
    entry: StoreEntry,
    *,
    path: Path,
    context_size: int | None = None,
    gpu_layers: int | None = None,
    tensor_parallel_size: int | None = None,
    gpu_memory_utilization: float | None = None,
) -> dict[str, Any]:
    """Build the advisory engine arguments that accompany a located model.

    **Data, not process control.** These are keys a caller — the llama.cpp supervisor, a
    future vLLM launcher, or a user pasting a command line — turns into arguments. Producing
    them from numbers already computed is translation; launching is not, and nothing here
    starts a process.
    """
    if entry.engine == "vllm":
        hints: dict[str, Any] = {"engine": "vllm", "model": str(path)}
        if entry.quantization:
            hints["quantization"] = entry.quantization
        if context_size:
            hints["max_model_len"] = context_size
        if tensor_parallel_size and tensor_parallel_size > 1:
            hints["tensor_parallel_size"] = tensor_parallel_size
        if gpu_memory_utilization:
            hints["gpu_memory_utilization"] = gpu_memory_utilization
        return hints

    hints = {"engine": "llama.cpp", "model": str(path)}
    if gpu_layers is not None:
        hints["n_gpu_layers"] = gpu_layers
    if context_size:
        hints["ctx_size"] = context_size
    return hints
