"""Verified, resumable model-artifact downloads.

Model files are large, slow to fetch, and catastrophic to get subtly wrong: a truncated or
corrupted GGUF fails at load time with an error that says nothing about the download. So
every artifact is:

- **pinned** — the URL and SHA-256 come from the catalog, not from the network;
- **verified** — the hash is checked before the file is ever considered present;
- **atomic** — bytes land in a ``.part`` file and are renamed only after verification, so a
  crash can never leave a half-file that looks complete;
- **resumable** — an interrupted transfer continues with a range request;
- **lock-guarded** — concurrent processes cooperate rather than corrupt each other.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx2

from ..errors import LocalRuntimeError
from .artifacts import GgufArtifact, GgufFile

__all__ = [
    "ALLOWED_LICENSES",
    "DownloadReport",
    "FileLock",
    "ProgressCallback",
    "artifact_paths",
    "default_model_dir",
    "download_artifact",
    "iter_missing",
    "license_allowed",
    "verify_file",
]

ALLOWED_LICENSES = frozenset(
    {
        "apache-2.0",
        "falcon-llm-2.0",
        "gemma-terms",
        "llama-3.1-community",
        "llama-3.2-community",
        "llama-3.3-community",
        "mit",
        "openrail-m",
    }
)
"""Licenses permitted for catalog entries, compared case-insensitively.

The bundled catalog is curated; entries an application adds are checked so that a
convenience feature cannot quietly redistribute weights under terms the user has not seen.
Non-commercial and research-only terms are deliberately absent — an application that has
accepted those terms adds the model through a catalog overlay, which is an explicit act.
"""


def license_allowed(license_id: str) -> bool:
    """Whether a license id is in `ALLOWED_LICENSES`, ignoring case."""
    return license_id.strip().lower() in ALLOWED_LICENSES


_CHUNK_BYTES = 1024 * 1024
_LOCK_STALE_S = 3600.0
_LOCK_WAIT_S = 300.0
_LOCK_POLL_S = 0.25

ProgressCallback = Callable[[str, int, int | None], None]
"""``(artifact_id, downloaded_bytes, total_bytes_or_None)``."""


@dataclass(frozen=True, slots=True)
class DownloadReport:
    """The outcome of ensuring an artifact is present.

    Attributes:
        artifact_id: The artifact this report describes.
        paths: Where each of the artifact's files lives on disk, in declaration order.
        downloaded_bytes: Bytes actually transferred; zero when everything was reused.
        reused: Whether every file was already present and verified, so nothing was
            fetched.
        warnings: Non-fatal notes — files with no recorded hash, or files that failed
            verification and were re-downloaded.
    """

    artifact_id: str
    paths: tuple[Path, ...]
    downloaded_bytes: int = 0
    reused: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def primary_path(self) -> Path:
        """The file to hand to llama-server (the first shard of a sharded artifact)."""
        return self.paths[0]


def default_model_dir() -> Path:
    """Where downloaded artifacts live by default."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "anyinfer" / "models"


def artifact_paths(artifact: GgufArtifact, model_dir: Path | None = None) -> tuple[Path, ...]:
    """Where an artifact's files would live on disk."""
    root = model_dir or default_model_dir()
    return tuple(root / file.filename for file in artifact.files)


def verify_file(path: Path, expected_sha256: str) -> bool:
    """Whether a file matches its expected hash.

    An artifact with no recorded hash cannot be verified; its mere existence is accepted,
    and the caller is warned.
    """
    if not expected_sha256:
        return path.exists()
    if not path.exists():
        return False
    return _read_and_hash(path, hashlib.sha256).lower() == expected_sha256.lower()


def _read_and_hash(path: Path, hasher_factory: Callable[[], hashlib._Hash]) -> str:
    """Chunk-read a file through a fresh hasher and return its hex digest.

    Reads in `_CHUNK_BYTES` blocks so hashing a large model file never holds it fully in
    memory. Shared by `verify_file` here, `acquire._sha256`/`_git_blob_sha1`, and
    `provenance._hash_file` — the read loop is the same regardless of which hash it feeds.
    """
    digest = hasher_factory()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


class FileLock:
    """A cooperative cross-process lock backed by an exclusively-created file.

    Deliberately dependency-free. A lock older than an hour is presumed abandoned
    by a crashed process and broken, because leaving a user permanently unable to download
    a model is worse than the rare double-download that reclaiming it might allow.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._acquired = False

    def __enter__(self) -> FileLock:
        """Acquire the lock, waiting for a live holder and reclaiming a stale one.

        Raises:
            LocalRuntimeError: If the lock is still held after five minutes.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + _LOCK_WAIT_S
        while not self._try_acquire():
            if time.monotonic() > deadline:
                raise self._timeout()
            time.sleep(_LOCK_POLL_S)
        return self

    async def __aenter__(self) -> FileLock:
        """Acquire the lock without blocking the event loop.

        The async engine runs several transfers on one loop, and a sibling task holding
        this lock can only release it by making progress. Sleeping the loop while waiting
        would therefore deadlock rather than wait, so the poll is `asyncio.sleep`.

        Raises:
            LocalRuntimeError: If the lock is still held after five minutes.
        """
        import asyncio

        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + _LOCK_WAIT_S
        while not self._try_acquire():
            if time.monotonic() > deadline:
                raise self._timeout()
            await asyncio.sleep(_LOCK_POLL_S)
        return self

    def _try_acquire(self) -> bool:
        """One non-blocking attempt, reclaiming a lock left by a crashed process."""
        try:
            descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if self._is_stale():
                with contextlib.suppress(OSError):
                    self._path.unlink()
            return False
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        self._acquired = True
        return True

    def _timeout(self) -> LocalRuntimeError:
        return LocalRuntimeError(
            f"timed out waiting for the download lock at {self._path}",
            hint="another process may be downloading; retry, or remove the lock",
        )

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self._path.stat().st_mtime
        except OSError:
            return True
        return age > _LOCK_STALE_S

    def _release(self) -> None:
        if self._acquired:
            self._acquired = False
            with contextlib.suppress(OSError):
                self._path.unlink()

    def __exit__(self, *exc: object) -> None:
        """Release the lock, if this instance was the one that took it."""
        self._release()

    async def __aexit__(self, *exc: object) -> None:
        """Release the lock, if this instance was the one that took it."""
        self._release()


def download_artifact(
    artifact: GgufArtifact,
    *,
    model_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    client: httpx2.Client | None = None,
    enforce_license: bool = False,
) -> DownloadReport:
    """Ensure every file of an artifact is present and verified.

    Args:
        artifact: The pinned catalog entry.
        model_dir: Destination directory; defaults to `default_model_dir()`.
        progress: Called as bytes arrive.
        client: An ``httpx2.Client`` to use, for tests or custom transports.
        enforce_license: Reject artifacts whose license is not in
            `ALLOWED_LICENSES`. Applied to application-supplied entries.

    Returns:
        A report naming the on-disk files.

    Raises:
        LocalRuntimeError: On a hash mismatch, a transfer failure, or a rejected license.
    """
    if enforce_license and not license_allowed(artifact.license):
        raise LocalRuntimeError(
            f"artifact {artifact.id!r} has license {artifact.license or 'unknown'!r}, "
            "which is not in the allowed set",
            hint=f"allowed licenses: {', '.join(sorted(ALLOWED_LICENSES))}",
        )

    root = model_dir or default_model_dir()
    root.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(artifact, root)
    warnings: list[str] = []
    downloaded = 0
    reused = True

    # Progress is reported for the artifact as a whole. A sharded artifact whose counter
    # restarts at zero on every shard is worse than no progress bar, because a caller
    # cannot tell a restart from a stall, so bytes already on disk are carried forward
    # and the total is the whole file set.
    artifact_total = artifact.total_size_bytes
    completed = 0

    owns_client = client is None
    http = client or httpx2.Client(follow_redirects=True, timeout=httpx2.Timeout(60.0))
    try:
        with FileLock(root / f"{artifact.id}.lock"):
            for file, path in zip(artifact.files, paths, strict=True):
                if not file.sha256:
                    warnings.append(
                        f"{file.filename} has no recorded sha256; it cannot be verified"
                    )
                if verify_file(path, file.sha256):
                    completed += file.size_bytes or path.stat().st_size
                    continue
                if path.exists():
                    warnings.append(f"{file.filename} failed verification; re-downloading")
                    with contextlib.suppress(OSError):
                        path.unlink()
                reused = False
                downloaded += _fetch(
                    http,
                    file,
                    path,
                    artifact.id,
                    _aggregating(progress, completed, artifact_total),
                )
                completed += file.size_bytes or path.stat().st_size
    finally:
        if owns_client:
            http.close()

    return DownloadReport(
        artifact_id=artifact.id,
        paths=paths,
        downloaded_bytes=downloaded,
        reused=reused,
        warnings=tuple(warnings),
    )


def _aggregating(
    progress: ProgressCallback | None, completed: int, artifact_total: int | None
) -> ProgressCallback | None:
    """Shift a per-file callback onto the artifact's own byte scale."""
    if progress is None:
        return None

    def report(artifact_id: str, written: int, file_total: int | None) -> None:
        total = artifact_total
        if total is None and file_total is not None:
            # Without pinned sizes the best available total is "what we have plus what
            # this file still owes"; it grows as shards complete, and says so by being
            # derived rather than declared.
            total = completed + file_total
        progress(artifact_id, completed + written, total)

    return report


def _fetch(
    client: httpx2.Client,
    file: GgufFile,
    destination: Path,
    artifact_id: str,
    progress: ProgressCallback | None,
) -> int:
    """Download one file to a ``.part`` sibling, verify it, then rename into place."""
    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0

    headers: dict[str, str] = {}
    if existing:
        headers["Range"] = f"bytes={existing}-"

    written = existing
    try:
        with client.stream("GET", file.url, headers=headers) as response:
            if existing and response.status_code == 200:
                # The server ignored the range request, so the partial file is not a
                # prefix of this body; start over rather than concatenating garbage.
                existing = 0
                written = 0
                with contextlib.suppress(OSError):
                    partial.unlink()
            elif response.status_code not in (200, 206):
                raise LocalRuntimeError(
                    f"download of {file.filename} failed with HTTP {response.status_code}",
                    hint="check the catalog URL, or your network connection",
                )

            total = _total_size(response, existing)
            mode = "ab" if existing else "wb"
            with partial.open(mode) as handle:
                for chunk in response.iter_bytes(_CHUNK_BYTES):
                    handle.write(chunk)
                    written += len(chunk)
                    if progress is not None:
                        progress(artifact_id, written, total)
    except httpx2.HTTPError as exc:
        raise LocalRuntimeError(
            f"download of {file.filename} failed: {exc}",
            hint="check your network connection and retry; partial progress is kept",
        ) from exc

    if file.sha256 and not verify_file(partial, file.sha256):
        with contextlib.suppress(OSError):
            partial.unlink()
        raise LocalRuntimeError(
            f"{file.filename} failed sha256 verification after download",
            hint="the file may be corrupt or the catalog hash may be stale; retry",
        )

    partial.replace(destination)
    return written - existing


def _total_size(response: httpx2.Response, already_have: int) -> int | None:
    """Total expected bytes, accounting for a resumed range."""
    length = response.headers.get("content-length")
    if length is None or not length.isdigit():
        return None
    return int(length) + already_have


def iter_missing(
    artifacts: Iterable[GgufArtifact], model_dir: Path | None = None
) -> list[GgufArtifact]:
    """Which artifacts are absent or fail verification."""
    missing: list[GgufArtifact] = []
    for artifact in artifacts:
        paths = artifact_paths(artifact, model_dir)
        if not all(
            verify_file(path, file.sha256)
            for file, path in zip(artifact.files, paths, strict=True)
        ):
            missing.append(artifact)
    return missing
