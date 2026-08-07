"""Where model weights come from, as data.

A *source reference* is declarative — "this repo at this revision, these files" — and a
*resolver* turns it into a concrete, ordered file list with URLs, sizes, and digests. That
split is what keeps acquisition source-agnostic: adding an internal mirror is a new
resolver, not a new downloader.

This module is deliberately a leaf. It holds only the types, the protocol, the registry,
and the filename-safety rule; the resolvers that speak HTTP live in sibling modules and
register themselves on import, so importing a reference never drags in a network client.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol, runtime_checkable

from ...errors import ConfigError

__all__ = [
    "DigestKind",
    "RemoteFile",
    "ResolvedArtifact",
    "ResolverId",
    "SourceRef",
    "SourceResolver",
    "get_resolver",
    "register_resolver",
    "resolver_ids",
    "safe_relative_path",
]

ResolverId = Literal["huggingface", "url", "local"]
"""Resolvers shipped with AnyInfer. Applications may register more."""

DigestKind = Literal["sha256", "git-sha1", "none"]
"""How a file's recorded digest should be computed and compared."""


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A declarative pointer at a set of remote (or already-local) files.

    Attributes:
        resolver: Which resolver understands this reference.
        repo: Repository id, for repository-shaped resolvers (``"Qwen/Qwen2.5-7B-Instruct"``).
        revision: Branch, tag, or — preferably — an immutable commit sha.
        files: Explicit file list. Empty means "whatever the include globs match".
        digests: Per-file expected sha256, when the catalog pinned them.
        sizes: Per-file expected byte counts, when the catalog pinned them.
        urls: Direct download URLs, for the ``url`` resolver.
        include: Glob patterns selecting files from a repository listing.
        exclude: Glob patterns removing files the include list matched.
        path: An existing on-disk location, for the ``local`` resolver.
    """

    resolver: str = "huggingface"
    repo: str | None = None
    revision: str | None = None
    files: tuple[str, ...] = ()
    digests: Mapping[str, str] = field(default_factory=dict)
    sizes: Mapping[str, int] = field(default_factory=dict)
    urls: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    path: str | None = None

    def to_json(self) -> dict[str, object]:
        """Serialize for the store index."""
        data: dict[str, object] = {"resolver": self.resolver}
        if self.repo:
            data["repo"] = self.repo
        if self.revision:
            data["revision"] = self.revision
        if self.files:
            data["files"] = list(self.files)
        if self.urls:
            data["urls"] = list(self.urls)
        if self.path:
            data["path"] = self.path
        return data


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """One file a resolver decided belongs to an artifact.

    Attributes:
        path: Destination path *relative to the entry directory*, POSIX-separated.
        url: Where to fetch it.
        size_bytes: Expected size, or ``None`` when genuinely unknown.
        digest: Expected digest, lowercase hex.
        digest_kind: How to compute `digest`. ``"none"`` means unverifiable.
    """

    path: str
    url: str
    size_bytes: int | None = None
    digest: str = ""
    digest_kind: DigestKind = "none"

    @property
    def filename(self) -> str:
        """The final path component."""
        return PurePosixPath(self.path).name


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    """A concrete, ordered file list ready for acquisition.

    Attributes:
        resolver: Which resolver produced this.
        files: Every file to fetch, in acquisition order.
        repo: The repository this came from, when applicable.
        revision: The *immutable* revision this resolved to, when the resolver could
            determine one. A branch name is always resolved to a commit before use.
        warnings: Anything the caller should know — unverifiable files, skipped
            pickle weights, and so on.
    """

    resolver: str
    files: tuple[RemoteFile, ...] = ()
    repo: str | None = None
    revision: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def total_bytes(self) -> int | None:
        """Sum of every file size, or ``None`` when any one is unknown."""
        if any(f.size_bytes is None for f in self.files):
            return None
        return sum(f.size_bytes or 0 for f in self.files)


@runtime_checkable
class SourceResolver(Protocol):
    """Turns a `SourceRef` into a `ResolvedArtifact`."""

    scheme: str
    """The `SourceRef.resolver` value this implementation answers to."""

    async def resolve(
        self,
        ref: SourceRef,
        *,
        token: str | None = None,
        client: Any | None = None,
    ) -> ResolvedArtifact:
        """Expand a reference into a concrete file list.

        ``client`` is an optional ``httpx2.AsyncClient`` the caller already owns. Passing
        it keeps resolution and the subsequent transfer on one connection pool — and is
        what makes a resolver testable against a mock transport.
        """
        ...


_RESOLVERS: dict[str, SourceResolver] = {}


def register_resolver(resolver: SourceResolver) -> None:
    """Register a resolver under its `SourceResolver.scheme`.

    Registering the same scheme twice replaces the earlier entry, so an application can
    substitute an internal mirror for the bundled Hugging Face resolver.
    """
    _RESOLVERS[resolver.scheme] = resolver


def resolver_ids() -> tuple[str, ...]:
    """Every registered resolver scheme, sorted."""
    _load_builtin_resolvers()
    return tuple(sorted(_RESOLVERS))


def get_resolver(scheme: str) -> SourceResolver:
    """Look up a resolver.

    Raises:
        ConfigError: If no resolver is registered for ``scheme``.
    """
    _load_builtin_resolvers()
    resolver = _RESOLVERS.get(scheme)
    if resolver is None:
        known = ", ".join(sorted(_RESOLVERS)) or "(none)"
        raise ConfigError(
            f"no source resolver registered for {scheme!r}",
            hint=f"known resolvers: {known}",
        )
    return resolver


_BUILTINS_LOADED = False


def _load_builtin_resolvers() -> None:
    """Import the bundled resolvers on first use.

    Deferred so that merely reading a `SourceRef` — which the catalog does at import time —
    never pulls in an HTTP client.

    Guarded by an explicit flag rather than by "is the registry empty?": something else
    importing one resolver module directly would fill the registry and make an emptiness
    check skip the other two.
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    import importlib

    for name in ("huggingface", "direct_url", "local_path"):
        # Imported for the registration side effect; naming them here rather than at module
        # scope keeps a bare SourceRef free of any HTTP dependency.
        importlib.import_module(f"{__name__}.{name}")


# ---- filename safety -------------------------------------------------------------------

_RESERVED_WINDOWS_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")


def safe_relative_path(name: str) -> str:
    """Validate a remote-supplied path and return it in normalized POSIX form.

    File names come from a third-party API, so they are attacker-influenced input. This
    rejects everything that could escape the entry directory or land on a path the host OS
    treats specially, *before* any file is opened.

    Raises:
        ConfigError: If the name is absolute, escapes upward, names a Windows device, or
            contains a NUL byte.
    """
    raw = name.strip()
    if not raw:
        raise ConfigError("a source listed a file with an empty name")
    if "\x00" in raw:
        raise ConfigError(f"source file name {name!r} contains a NUL byte")

    unified = raw.replace("\\", "/")
    if unified.startswith("/") or _DRIVE_LETTER.match(unified):
        raise ConfigError(
            f"source file name {name!r} is an absolute path",
            hint="model files must land inside the store, never at an absolute location",
        )

    parts: list[str] = []
    for part in unified.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ConfigError(
                f"source file name {name!r} escapes its directory",
                hint="'..' segments are never accepted from a remote file listing",
            )
        if part.split(".", 1)[0].lower() in _RESERVED_WINDOWS_NAMES:
            raise ConfigError(
                f"source file name {name!r} uses a reserved device name",
                hint="this name cannot be written on Windows",
            )
        parts.append(part)

    if not parts:
        raise ConfigError(f"source file name {name!r} names no file")
    return "/".join(parts)
