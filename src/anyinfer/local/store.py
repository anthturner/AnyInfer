"""Where acquired model weights live, and how to find them again.

Deterministic placement plus an index, so "where is qwen3-8b at Q5_K_M?" is answered from a
small JSON file rather than a filesystem crawl over directories that may hold forty
gigabytes each.

Layout::

    <root>/
      store.json                        index
      gguf/<publisher>/<repo>/<sha12>/  the shard set
      hf/<publisher>/<repo>/<sha12>/    a repository snapshot
      .locks/<entry_id>.lock
      .staging/<entry_id>/              .part files, removed on success

Revision-scoped directories mean two revisions of one repository coexist, deletion is a
single tree removal, and two repositories shipping ``model-00001-of-00004.safetensors``
cannot collide.

**The index is a cache, not the truth.** A user will eventually delete a directory by hand,
so every read tolerates a missing or corrupt index and `ModelStore.rebuild_index` recovers
by rescanning. Writes are atomic and lock-guarded, the same discipline downloads use.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..errors import ConfigError, LocalRuntimeError
from .downloads import FileLock, default_model_dir, verify_file
from .sources import SourceRef, safe_relative_path

__all__ = [
    "INDEX_NAME",
    "MODEL_DIR_ENV",
    "STORE_FORMAT_VERSION",
    "ModelStore",
    "RemovalReport",
    "ResolvedModel",
    "StoreEntry",
    "StoredFile",
    "default_store_root",
    "entry_id_for",
    "iter_entry_dirs",
    "placement_for",
]

INDEX_NAME = "store.json"
"""The index file at the root of a store."""

STORE_FORMAT_VERSION = 1
"""Schema version of the index document."""

MODEL_DIR_ENV = "ANYINFER_MODEL_DIR"
"""Overrides the store root."""

_STAGING = ".staging"
_LOCKS = ".locks"


@dataclass(frozen=True, slots=True)
class StoredFile:
    """One file of a stored entry.

    Attributes:
        path: Path relative to the entry directory, POSIX-separated.
        size_bytes: Size at install time.
        digest: Expected digest, lowercase hex, or empty when there was none.
        digest_kind: How `digest` was computed.
        verified: Whether the bytes were checked against `digest` at install time.
        mtime: Modification time at install time, used for the cheap re-check.
    """

    path: str
    size_bytes: int = 0
    digest: str = ""
    digest_kind: str = "none"
    verified: bool = False
    mtime: float = 0.0

    def to_json(self) -> dict[str, Any]:
        """Serialize for the index."""
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "digest": self.digest,
            "digest_kind": self.digest_kind,
            "verified": self.verified,
            "mtime": self.mtime,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> StoredFile:
        """Parse one index file record."""
        return cls(
            path=str(data.get("path", "")),
            size_bytes=int(data.get("size_bytes", 0) or 0),
            digest=str(data.get("digest", "")),
            digest_kind=str(data.get("digest_kind", "none")),
            verified=bool(data.get("verified")),
            mtime=float(data.get("mtime", 0.0) or 0.0),
        )


@dataclass(frozen=True, slots=True)
class StoreEntry:
    """One acquired model in the store.

    Attributes:
        id: Stable entry id, also the lock and staging name.
        kind: ``"gguf"`` (a file set) or ``"hf_repo"`` (a directory snapshot).
        model_id: The catalog model this realizes, when it came from the catalog.
        variant_id: The catalog variant, when it came from the catalog.
        quantization: The quantization on disk.
        engine: Which engine this variant is for.
        source: How it was acquired, including the resolved immutable revision.
        directory: Where the files live, relative to the store root.
        handle: The path an engine is pointed at, relative to the store root — the first
            shard for GGUF, the directory for a snapshot.
        files: Every file, with digests.
        license: License id recorded at acquisition.
        installed_at: Unix timestamp of successful registration.
        last_used_at: Unix timestamp of the most recent `ModelStore.locate`.
        external: True when the bytes are owned by something else (an adopted Hugging Face
            cache). Removal only unregisters an external entry; it never deletes.
        warnings: Anything the user should know — unverified files, most importantly.
    """

    id: str
    kind: str = "gguf"
    model_id: str = ""
    variant_id: str = ""
    quantization: str = ""
    engine: str = "llama.cpp"
    source: Mapping[str, Any] = field(default_factory=dict)
    directory: str = ""
    handle: str = ""
    files: tuple[StoredFile, ...] = ()
    license: str = ""
    installed_at: float = 0.0
    last_used_at: float = 0.0
    external: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def total_bytes(self) -> int:
        """Bytes this entry occupies."""
        return sum(f.size_bytes for f in self.files)

    @property
    def verified(self) -> bool:
        """Whether every file was verified against a digest at install time."""
        return bool(self.files) and all(f.verified for f in self.files)

    def to_json(self) -> dict[str, Any]:
        """Serialize for the index."""
        return {
            "id": self.id,
            "kind": self.kind,
            "model_id": self.model_id,
            "variant_id": self.variant_id,
            "quantization": self.quantization,
            "engine": self.engine,
            "source": dict(self.source),
            "directory": self.directory,
            "handle": self.handle,
            "files": [f.to_json() for f in self.files],
            "license": self.license,
            "installed_at": self.installed_at,
            "last_used_at": self.last_used_at,
            "external": self.external,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> StoreEntry:
        """Parse one index entry."""
        return cls(
            id=str(data["id"]),
            kind=str(data.get("kind", "gguf")),
            model_id=str(data.get("model_id", "")),
            variant_id=str(data.get("variant_id", "")),
            quantization=str(data.get("quantization", "")),
            engine=str(data.get("engine", "llama.cpp")),
            source=dict(data.get("source", {})),
            directory=str(data.get("directory", "")),
            handle=str(data.get("handle", "")),
            files=tuple(
                StoredFile.from_json(f) for f in data.get("files", []) if isinstance(f, Mapping)
            ),
            license=str(data.get("license", "")),
            installed_at=float(data.get("installed_at", 0.0) or 0.0),
            last_used_at=float(data.get("last_used_at", 0.0) or 0.0),
            external=bool(data.get("external")),
            warnings=tuple(str(w) for w in data.get("warnings", [])),
        )


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    """A located model, ready to launch an engine against.

    Attributes:
        entry_id: The store entry.
        kind: ``"gguf"`` or ``"hf_repo"``.
        path: The engine handle — a file for GGUF, a directory for a snapshot.
        quantization: What is actually on disk.
        engine: Which engine this variant is for.
        verified: Whether every file was verified.
        warnings: Notes carried from the entry.
        launch_hints: Engine-shaped arguments a caller can turn into a command line.
            **Advisory data, not process control**: this module locates weights, it does not
            start servers.
    """

    entry_id: str
    kind: str
    path: Path
    quantization: str | None = None
    engine: str = "llama.cpp"
    verified: bool = False
    warnings: tuple[str, ...] = ()
    launch_hints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RemovalReport:
    """The outcome of removing an entry.

    Attributes:
        entry_id: What was removed.
        removed: Whether an entry was found and unregistered.
        freed_bytes: Bytes reclaimed; zero for an external entry, which is only
            unregistered.
        external: Whether the files were left alone because something else owns them.
    """

    entry_id: str
    removed: bool = False
    freed_bytes: int = 0
    external: bool = False


def default_store_root() -> Path:
    """Where the store lives by default."""
    override = os.environ.get(MODEL_DIR_ENV)
    return Path(override) if override else default_model_dir()


def entry_id_for(
    kind: str, *, repo: str | None, revision: str | None, variant_id: str, filename: str = ""
) -> str:
    """Build a stable entry id from what identifies an artifact."""
    if repo:
        publisher, _, name = repo.partition("/")
        stem = f"{publisher}--{name or publisher}"
    else:
        stem = variant_id or Path(filename).stem or "artifact"
    short = (revision or "")[:12]
    parts = [kind, stem]
    if variant_id and variant_id not in stem:
        parts.append(variant_id)
    if short:
        parts.append(short)
    return "-".join(_slug(p) for p in parts if p)


class ModelStore:
    """A directory of acquired models, with an index over it.

    Not thread-safe by construction; correctness across processes comes from the same
    cooperative file lock downloads use, taken around every index mutation.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else default_store_root()

    @property
    def root(self) -> Path:
        """The store root."""
        return self._root

    @property
    def index_path(self) -> Path:
        """Where the index document lives."""
        return self._root / INDEX_NAME

    def staging_dir(self, entry_id: str) -> Path:
        """Where an in-progress acquisition writes its ``.part`` files."""
        return self._root / _STAGING / _slug(entry_id)

    def lock_path(self, entry_id: str) -> Path:
        """The cross-process lock guarding one entry."""
        return self._root / _LOCKS / f"{_slug(entry_id)}.lock"

    def entry_dir(self, entry: StoreEntry) -> Path:
        """Absolute path to an entry's directory."""
        return self._root / entry.directory

    def resolve_within(self, entry: StoreEntry, relative: str) -> Path:
        """Resolve a path inside an entry, refusing anything that escapes it.

        Called for every file before it is opened. Names come from a remote API, so this is
        the containment gate, applied *after* resolution so a symlink cannot step outside.

        Raises:
            ConfigError: If the path is unsafe or resolves outside the entry directory.
        """
        base = self.entry_dir(entry)
        candidate = (base / safe_relative_path(relative)).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError:
            raise ConfigError(
                f"file {relative!r} resolves outside the store entry directory",
                hint="the source listing cannot be trusted; nothing was written",
            ) from None
        return candidate

    # ---- index -----------------------------------------------------------------------

    def load_index(self) -> dict[str, StoreEntry]:
        """Read the index, tolerating absence and corruption.

        A store whose index cannot be parsed reports as empty rather than raising: the
        files are still there, `rebuild_index` can recover them, and refusing to work at
        all because a cache file got truncated would be the wrong trade.
        """
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        if int(data.get("format_version", 0) or 0) > STORE_FORMAT_VERSION:
            return {}
        entries: dict[str, StoreEntry] = {}
        for raw in data.get("entries", []):
            if not isinstance(raw, Mapping) or "id" not in raw:
                continue
            with contextlib.suppress(TypeError, ValueError, KeyError):
                entry = StoreEntry.from_json(raw)
                entries[entry.id] = entry
        return entries

    def _write_index(self, entries: Mapping[str, StoreEntry]) -> None:
        """Write the index atomically."""
        document = {
            "format_version": STORE_FORMAT_VERSION,
            "entries": [entries[key].to_json() for key in sorted(entries)],
        }
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
        temporary.replace(self.index_path)

    def register(self, entry: StoreEntry) -> StoreEntry:
        """Add or replace an index entry.

        Called only after every file has been verified: a half-complete multi-file set is
        never registered, which is what makes `locate` trustworthy.
        """
        stamped = replace(entry, installed_at=entry.installed_at or time.time())
        with FileLock(self.lock_path("index")):
            entries = self.load_index()
            entries[stamped.id] = stamped
            self._write_index(entries)
        return stamped

    def unregister(self, entry_id: str) -> StoreEntry | None:
        """Drop an index entry without touching files."""
        with FileLock(self.lock_path("index")):
            entries = self.load_index()
            removed = entries.pop(entry_id, None)
            if removed is not None:
                self._write_index(entries)
        return removed

    def rebuild_index(self) -> list[StoreEntry]:
        """Drop entries whose files are gone, and re-stat the rest.

        The recovery path for a user who deleted a directory by hand. It does not invent
        entries for unknown directories — an unrecognized tree could be anything, and
        registering it would be a claim about bytes nobody checked.
        """
        with FileLock(self.lock_path("index")):
            entries = self.load_index()
            surviving: dict[str, StoreEntry] = {}
            for entry_id, entry in entries.items():
                directory = self.entry_dir(entry)
                if not directory.exists():
                    continue
                files: list[StoredFile] = []
                intact = True
                for stored in entry.files:
                    path = directory / stored.path
                    try:
                        stat = path.stat()
                    except OSError:
                        intact = False
                        break
                    files.append(replace(stored, size_bytes=stat.st_size, mtime=stat.st_mtime))
                if intact and files:
                    surviving[entry_id] = replace(entry, files=tuple(files))
            self._write_index(surviving)
            return [surviving[key] for key in sorted(surviving)]

    # ---- queries ---------------------------------------------------------------------

    def list_installed(self) -> list[StoreEntry]:
        """Every registered entry, id-ordered."""
        entries = self.load_index()
        return [entries[key] for key in sorted(entries)]

    def get(self, entry_id: str) -> StoreEntry | None:
        """One entry by id."""
        return self.load_index().get(entry_id)

    def find(
        self,
        model_id: str,
        *,
        variant_id: str | None = None,
        quantization: str | None = None,
        engine: str | None = None,
    ) -> StoreEntry | None:
        """The best registered entry matching a model and optional constraints.

        "Best" is the most recently installed match, so re-acquiring at a different
        quantization changes what a bare model id resolves to — which is what a user who
        just downloaded something expects.
        """
        candidates = [
            entry
            for entry in self.load_index().values()
            if entry.model_id == model_id
            and (variant_id is None or entry.variant_id == variant_id)
            and (quantization is None or entry.quantization.upper() == quantization.upper())
            and (engine is None or entry.engine == engine)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: (e.installed_at, e.id))

    def locate(
        self,
        model_id: str,
        *,
        variant_id: str | None = None,
        quantization: str | None = None,
        engine: str | None = None,
        verify: bool = False,
        launch_hints: Mapping[str, Any] | None = None,
    ) -> ResolvedModel | None:
        """Find a stored model and return a path an engine can be launched against.

        No network I/O, ever. Verification is the deliberate exception to "always check":
        hashing forty gigabytes on every request would be absurd, so the rule is *verify on
        install and on adoption*, then on lookup compare size and mtime against the index
        and re-hash only on a mismatch. ``verify=True`` forces a full re-hash.

        Returns:
            The located model, or ``None`` when it is absent or fails its check.
        """
        entry = self.find(
            model_id, variant_id=variant_id, quantization=quantization, engine=engine
        )
        if entry is None:
            return None

        problems = self.check(entry, deep=verify)
        if problems:
            return None

        self._touch(entry.id)
        return ResolvedModel(
            entry_id=entry.id,
            kind=entry.kind,
            path=self._root / entry.handle,
            quantization=entry.quantization or None,
            engine=entry.engine,
            verified=entry.verified,
            warnings=entry.warnings,
            launch_hints=dict(launch_hints or {}),
        )

    def check(self, entry: StoreEntry, *, deep: bool = False) -> tuple[str, ...]:
        """Report what is wrong with a stored entry, cheaply by default.

        The shallow check compares size and mtime against the index; the deep check
        re-hashes. Either way an empty result means "as installed".
        """
        problems: list[str] = []
        directory = self.entry_dir(entry)
        for stored in entry.files:
            path = directory / stored.path
            try:
                stat = path.stat()
            except OSError:
                problems.append(f"{stored.path} is missing")
                continue
            if stat.st_size != stored.size_bytes:
                problems.append(
                    f"{stored.path} is {stat.st_size} bytes; the index recorded "
                    f"{stored.size_bytes}"
                )
                continue
            if not deep and stored.mtime and abs(stat.st_mtime - stored.mtime) > 1.0:
                problems.append(f"{stored.path} was modified after installation")
                continue
            if deep and stored.digest_kind == "sha256" and not verify_file(path, stored.digest):
                problems.append(f"{stored.path} failed sha256 verification")
        return tuple(problems)

    def disk_usage(self) -> int:
        """Total bytes the registered entries occupy, excluding external ones."""
        return sum(e.total_bytes for e in self.load_index().values() if not e.external)

    def _touch(self, entry_id: str) -> None:
        """Record a use. Best-effort — a read-only store must not break lookup."""
        with contextlib.suppress(LocalRuntimeError, OSError), FileLock(self.lock_path("index")):
            entries = self.load_index()
            entry = entries.get(entry_id)
            if entry is None:
                return
            entries[entry_id] = replace(entry, last_used_at=time.time())
            self._write_index(entries)

    # ---- mutation ---------------------------------------------------------------------

    def remove(self, entry_id: str) -> RemovalReport:
        """Delete an entry's files and unregister it.

        An **external** entry — one adopted from somebody else's cache — is only
        unregistered. Deleting files this store never wrote would be overstepping.
        """
        entry = self.get(entry_id)
        if entry is None:
            return RemovalReport(entry_id=entry_id, removed=False)
        if entry.external:
            self.unregister(entry_id)
            return RemovalReport(entry_id=entry_id, removed=True, external=True)

        freed = entry.total_bytes
        directory = self.entry_dir(entry)
        with FileLock(self.lock_path(entry_id)):
            if directory.is_dir():
                shutil.rmtree(directory, ignore_errors=True)
            _prune_empty(directory.parent, self._root)
        self.unregister(entry_id)
        return RemovalReport(entry_id=entry_id, removed=True, freed_bytes=freed)

    def clear_staging(self, entry_id: str) -> None:
        """Remove an entry's staging directory and its partial transfers."""
        staging = self.staging_dir(entry_id)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    # ---- adoption ----------------------------------------------------------------------

    def adopt_legacy_flat(self, artifacts: Sequence[Any]) -> list[StoreEntry]:
        """Register pre-existing flat-layout GGUF files without moving or re-fetching them.

        Earlier builds wrote ``<root>/<filename>.gguf`` with no revision in the path. Those
        files are perfectly good bytes a user paid bandwidth for, so the store adopts them
        where they lie — but only after verifying each one against its catalog hash, so
        adoption is never a lie about what is on disk.

        Args:
            artifacts: Pinned catalog artifacts to look for, each with ``id`` and ``files``.

        Returns:
            Newly registered entries.
        """
        existing = self.load_index()
        adopted: list[StoreEntry] = []
        for artifact in artifacts:
            entry_id = f"legacy-{_slug(str(artifact.id))}"
            if entry_id in existing:
                continue
            files: list[StoredFile] = []
            complete = True
            for spec in artifact.files:
                path = self._root / spec.filename
                if not spec.sha256 or not verify_file(path, spec.sha256):
                    complete = False
                    break
                stat = path.stat()
                files.append(
                    StoredFile(
                        path=spec.filename,
                        size_bytes=stat.st_size,
                        digest=spec.sha256,
                        digest_kind="sha256",
                        verified=True,
                        mtime=stat.st_mtime,
                    )
                )
            if not complete or not files:
                continue
            adopted.append(
                self.register(
                    StoreEntry(
                        id=entry_id,
                        kind="gguf",
                        model_id=str(artifact.id),
                        variant_id=str(artifact.id),
                        quantization=str(getattr(artifact, "quantization", "") or ""),
                        engine="llama.cpp",
                        source={"resolver": "legacy-flat"},
                        directory=".",
                        handle=files[0].path,
                        files=tuple(files),
                        license=str(getattr(artifact, "license", "") or ""),
                        warnings=(
                            "adopted from the pre-store flat layout; it was verified but "
                            "lives outside the revision-scoped tree",
                        ),
                    )
                )
            )
        return adopted

    def adopt_external(
        self,
        directory: Path,
        *,
        entry_id: str,
        model_id: str,
        variant_id: str,
        kind: str = "hf_repo",
        engine: str = "vllm",
        quantization: str = "",
        source: Mapping[str, Any] | None = None,
        expected: Mapping[str, str] | None = None,
    ) -> StoreEntry | None:
        """Register a directory this store does not own, if every file checks out.

        The Hugging Face cache case. We do not adopt another library's *layout* for our own
        writes — it is their private implementation detail — but re-downloading forty
        gigabytes the user already has is user-hostile. Adopted entries are marked
        `StoreEntry.external`, are never written to, and are never deleted by `remove`.

        Args:
            directory: The existing snapshot directory.
            entry_id: Id to register it under.
            model_id: Catalog model this realizes.
            variant_id: Catalog variant this realizes.
            kind: Artifact kind.
            engine: Engine the variant targets.
            quantization: What is on disk.
            source: Provenance to record.
            expected: Per-relative-path sha256 that every file must match. Adoption is
                refused outright when this is empty — an unverified adoption is a guess.

        Returns:
            The registered entry, or ``None`` when verification failed.
        """
        if not directory.is_dir() or not expected:
            return None
        files: list[StoredFile] = []
        for relative, digest in sorted(expected.items()):
            path = directory / relative
            if not verify_file(path, digest):
                return None
            stat = path.stat()
            files.append(
                StoredFile(
                    path=relative,
                    size_bytes=stat.st_size,
                    digest=digest,
                    digest_kind="sha256",
                    verified=True,
                    mtime=stat.st_mtime,
                )
            )
        if not files:
            return None

        try:
            relative_dir = directory.resolve().relative_to(self._root.resolve()).as_posix()
        except ValueError:
            relative_dir = directory.resolve().as_posix()
        handle = relative_dir if kind == "hf_repo" else f"{relative_dir}/{files[0].path}"
        return self.register(
            StoreEntry(
                id=entry_id,
                kind=kind,
                model_id=model_id,
                variant_id=variant_id,
                quantization=quantization,
                engine=engine,
                source=dict(source or {"resolver": "external"}),
                directory=relative_dir,
                handle=handle,
                files=tuple(files),
                external=True,
                warnings=("adopted from an existing cache; AnyInfer will never modify it",),
            )
        )


# ---- placement ------------------------------------------------------------------------


def placement_for(
    kind: str, ref: SourceRef, *, revision: str | None, variant_id: str
) -> str:
    """The store-relative directory a variant's files belong in.

    Revision-scoped, publisher-scoped, and kind-scoped, so nothing can collide and a single
    tree removal is a complete uninstall.
    """
    top = "gguf" if kind == "gguf" else "hf"
    if ref.repo:
        publisher, _, name = ref.repo.partition("/")
        publisher = _slug(publisher)
        name = _slug(name or publisher)
    else:
        publisher, name = "direct", _slug(variant_id or "artifact")
    short = _slug((revision or ref.revision or "unpinned")[:12])
    return f"{top}/{publisher}/{name}/{short}"


def _prune_empty(directory: Path, stop: Path) -> None:
    """Remove now-empty parent directories up to (but not including) the store root."""
    current = directory.resolve()
    root = stop.resolve()
    while current != root and root in current.parents:
        try:
            next(current.iterdir())
            return
        except StopIteration:
            with contextlib.suppress(OSError):
                current.rmdir()
            current = current.parent
        except OSError:
            return


def _slug(value: str) -> str:
    """Reduce a string to a filesystem-safe token."""
    safe = [c if c.isalnum() or c in "-._" else "-" for c in value.strip().lower()]
    return "".join(safe).strip("-.") or "x"


def iter_entry_dirs(root: Path) -> Iterator[Path]:
    """Every entry-shaped directory under a store root, ignoring the reserved ones."""
    for top in ("gguf", "hf"):
        base = root / top
        if not base.is_dir():
            continue
        for publisher in sorted(p for p in base.iterdir() if p.is_dir()):
            for name in sorted(p for p in publisher.iterdir() if p.is_dir()):
                yield from sorted(p for p in name.iterdir() if p.is_dir())
