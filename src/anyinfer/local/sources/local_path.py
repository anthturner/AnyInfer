"""The local-path resolver: adopt weights that are already on this disk.

No transfer at all. A user who downloaded a GGUF by hand, or an operator who mounted a
shared model volume, should not have to re-fetch forty gigabytes to make AnyInfer aware of
them — so a path is validated, listed, and handed to the store as an already-satisfied file
set.

Files resolved this way carry no digest from any authority, so they are recorded unverified
unless the caller pinned digests themselves. That distinction is preserved all the way out
to `ResolvedModel.verified`, because "AnyInfer checked these bytes" and "AnyInfer found
these bytes" are different claims.
"""

from __future__ import annotations

from pathlib import Path

from ...errors import LocalRuntimeError
from . import RemoteFile, ResolvedArtifact, SourceRef, register_resolver, safe_relative_path

__all__ = ["LocalPathResolver"]


class LocalPathResolver:
    """Registers existing on-disk files without copying or fetching them."""

    scheme = "local"

    async def resolve(
        self,
        ref: SourceRef,
        *,
        token: str | None = None,
        client: object | None = None,
    ) -> ResolvedArtifact:
        """List an existing file or directory as a resolved artifact.

        Args:
            ref: The reference; ``path`` is required and may be a file or a directory.
                ``files`` optionally selects specific entries from a directory.
            token: Ignored; a local path needs no credential.
            client: Ignored; nothing is fetched.

        Returns:
            The file list, with ``file://`` URLs that acquisition recognizes as
            already-present rather than fetchable.

        Raises:
            LocalRuntimeError: If the path is missing, or names nothing usable.
        """
        if not ref.path:
            raise LocalRuntimeError(
                "a local source reference needs a 'path'",
                hint="pass SourceRef(resolver='local', path='/models/my.gguf')",
            )
        root = Path(ref.path).expanduser()
        if not root.exists():
            raise LocalRuntimeError(
                f"no model file or directory at {root}",
                hint="check the path; nothing is fetched for a local source",
            )

        if root.is_file():
            members = [(safe_relative_path(root.name), root)]
        else:
            selected = (
                [root / safe_relative_path(name) for name in ref.files]
                if ref.files
                else sorted(p for p in root.rglob("*") if p.is_file())
            )
            members = []
            for path in selected:
                if not path.is_file():
                    raise LocalRuntimeError(
                        f"{path} is not a readable file",
                        hint="check the file list against the directory's contents",
                    )
                members.append((path.relative_to(root).as_posix(), path))

        if not members:
            raise LocalRuntimeError(
                f"{root} contains no files to register",
                hint="point the reference at the directory that holds the weights",
            )

        files = tuple(
            RemoteFile(
                path=relative,
                url=path.resolve().as_uri(),
                size_bytes=path.stat().st_size,
                digest=ref.digests.get(relative, "").lower(),
                digest_kind="sha256" if ref.digests.get(relative) else "none",
            )
            for relative, path in members
        )
        unverified = [f.path for f in files if f.digest_kind == "none"]
        warnings = (
            (f"{len(unverified)} local file(s) were registered without verification",)
            if unverified
            else ()
        )
        return ResolvedArtifact(
            resolver=self.scheme, files=files, revision=ref.revision, warnings=warnings
        )


register_resolver(LocalPathResolver())
