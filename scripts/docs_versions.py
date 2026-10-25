"""Archive one SDK's documentation as a fixed version, independently of the other SDK.

Each SDK has its own Docusaurus docs plugin (``python`` and ``csharp``) and so its own version
history: ``website/<sdk>_versions.json``, ``website/<sdk>_versioned_docs/version-<v>/`` and
``website/<sdk>_versioned_sidebars/``. Shared documentation is never versioned.

A snapshot archives what was actually published for the outgoing version: the fully prepared
pages, including the rendered C# API reference and the expanded Python reference, plus the
manifest and symbol map they were prepared from. Archived pages are never regenerated from
today's sources. Absolute links between pages of the same SDK are pointed at the archive, so
an archived page does not silently send readers to a later release.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:  # Package import for tests and build scripts run from the repository root.
    from .docs_common import read_versions
except ImportError:  # Direct execution through scripts/build_docs.py.
    from docs_common import read_versions

SDKS = ("python", "csharp")
ARCHIVE_MANIFEST = "manifest.json"
ARCHIVE_SYMBOLS = "symbols.json"
_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


class SnapshotError(ValueError):
    """The requested snapshot would archive the wrong thing or disturb existing history."""


def versions_file(website: Path, sdk: str) -> Path:
    """Return the Docusaurus version list for one SDK plugin."""
    return website / f"{sdk}_versions.json"


def archive_dir(website: Path, sdk: str, version: str) -> Path:
    """Return the archived docs directory for one SDK version."""
    return website / f"{sdk}_versioned_docs" / f"version-{version}"


def sidebar_file(website: Path, sdk: str, version: str) -> Path:
    """Return the archived sidebar file Docusaurus reads for one SDK version."""
    return website / f"{sdk}_versioned_sidebars" / f"version-{version}-sidebars.json"


def archived_versions(website: Path, sdk: str) -> list[str]:
    """Return one SDK's archived versions, newest first, as Docusaurus lists them."""
    path = versions_file(website, sdk)
    if not path.is_file():
        return []
    versions = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(versions, list) or not all(isinstance(item, str) for item in versions):
        raise SnapshotError(f"{path.name} must be a JSON list of version names")
    return versions


def archived_manifest(website: Path, sdk: str, version: str) -> dict[str, Any]:
    """Return the manifest an archived version was prepared from."""
    path = archive_dir(website, sdk, version) / ARCHIVE_MANIFEST
    if not path.is_file():
        raise SnapshotError(f"archived {sdk} {version} has no {ARCHIVE_MANIFEST}")
    return json.loads(path.read_text(encoding="utf-8"))


def archived_url(sdk: str, version: str, url: str) -> str:
    """Map a current SDK route such as ``/csharp/api/x/`` to its archived route."""
    prefix = f"/{sdk}/"
    if not url.startswith(prefix):
        raise SnapshotError(f"{url} is not a {sdk} route")
    return f"{prefix}{version}/{url[len(prefix) :]}"


def snapshot(
    root: Path,
    sdk: str,
    version: str,
    *,
    prepare: Callable[[Path], dict[str, Any]],
    docusaurus: Callable[[list[str], Path], None],
    symbols: Callable[[Path], dict[str, str]] | None = None,
) -> Path:
    """Archive the current documentation of ``sdk`` as ``version``.

    Args:
        root: Repository root.
        sdk: ``python`` or ``csharp``.
        version: The outgoing version; it must equal the SDK's current package metadata.
        prepare: Fully prepares the documentation and returns the manifest it wrote.
        docusaurus: Runs a Docusaurus CLI command in ``website/``.
        symbols: Returns the prepared symbol-to-URL map to archive beside the pages.

    Returns:
        The archived docs directory.

    Raises:
        SnapshotError: For an unknown SDK, a version that is not the outgoing one, a version
            that is already archived, or an archive Docusaurus did not produce.
    """
    if sdk not in SDKS:
        raise SnapshotError(f"unknown SDK {sdk!r}; choose one of {', '.join(SDKS)}")
    if not _VERSION.fullmatch(version):
        raise SnapshotError(f"{version!r} is not a release version")
    current = str(read_versions(root)[sdk])
    if version != current:
        raise SnapshotError(
            f"{sdk} documentation describes {current}; snapshot the outgoing version before "
            f"changing the package version, not {version}"
        )
    website = root / "website"
    if version in archived_versions(website, sdk):
        raise SnapshotError(f"{sdk} {version} is already archived")
    other = {name: _tree_state(website, name) for name in SDKS if name != sdk}

    manifest = prepare(root)
    pages = [page for page in manifest["pages"] if page["sdk"] == sdk]
    if not pages:
        raise SnapshotError(f"prepared documentation has no {sdk} pages")
    docusaurus([f"docs:version:{sdk}", version], website)

    archive = archive_dir(website, sdk, version)
    if version not in archived_versions(website, sdk) or not archive.is_dir():
        raise SnapshotError(f"Docusaurus did not archive {sdk} {version}")
    routes = {page["url"] for page in pages}
    for document in sorted([*archive.rglob("*.md"), *archive.rglob("*.mdx")]):
        text = document.read_text(encoding="utf-8")
        rewritten = _point_links_at_archive(text, sdk, version, routes)
        if rewritten != text:
            document.write_text(rewritten, encoding="utf-8")
    (archive / ARCHIVE_MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if symbols is not None:
        mapped = {
            key: archived_url(sdk, version, value) if value.startswith(f"/{sdk}/") else value
            for key, value in sorted(symbols(root).items())
        }
        (archive / ARCHIVE_SYMBOLS).write_text(
            json.dumps(mapped, indent=2) + "\n", encoding="utf-8"
        )
    for name, state in other.items():
        if _tree_state(website, name) != state:
            raise SnapshotError(f"snapshotting {sdk} changed the {name} version history")
    return archive


def remove_snapshot(root: Path, sdk: str, version: str) -> None:
    """Remove one archived version, restoring the SDK's history to its earlier state."""
    website = root / "website"
    versions = archived_versions(website, sdk)
    if version not in versions:
        raise SnapshotError(f"{sdk} {version} is not archived")
    shutil.rmtree(archive_dir(website, sdk, version))
    sidebar_file(website, sdk, version).unlink(missing_ok=True)
    remaining = [item for item in versions if item != version]
    path = versions_file(website, sdk)
    if remaining:
        path.write_text(json.dumps(remaining, indent=2) + "\n", encoding="utf-8")
    else:
        path.unlink()
        for directory in (
            website / f"{sdk}_versioned_docs",
            website / f"{sdk}_versioned_sidebars",
        ):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()


def _point_links_at_archive(text: str, sdk: str, version: str, routes: set[str]) -> str:
    """Point absolute links to this SDK's current pages at their archived copies."""

    def replace(match: re.Match[str]) -> str:
        target = match.group("target")
        path, _, fragment = target.partition("#")
        if path not in routes:
            return match.group(0)
        archived = archived_url(sdk, version, path) + (f"#{fragment}" if fragment else "")
        return match.group(0).replace(target, archived)

    pattern = rf"(?:\]\(|href=\")(?P<target>/{re.escape(sdk)}/[^)\"\s]*)"
    return re.sub(pattern, replace, text)


def _tree_state(website: Path, sdk: str) -> tuple[tuple[str, str], ...]:
    """Fingerprint one SDK's version history so a snapshot can prove it left it alone."""
    paths = [versions_file(website, sdk)]
    for directory in (website / f"{sdk}_versioned_docs", website / f"{sdk}_versioned_sidebars"):
        if directory.is_dir():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    return tuple(
        sorted(
            (path.relative_to(website).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
            for path in paths
            if path.is_file()
        )
    )


def run_docusaurus(command: list[str], website: Path) -> None:
    """Run a Docusaurus CLI command with the repository-local installation."""
    entry = website / "node_modules" / "@docusaurus" / "core" / "bin" / "docusaurus.mjs"
    if not entry.is_file():
        raise SnapshotError("documentation dependencies are missing; run npm --prefix website ci")
    node = shutil.which("node")
    if node is None:
        raise SnapshotError("Node.js is required to archive documentation")
    subprocess.run([node, str(entry), *command], cwd=website, check=True)
