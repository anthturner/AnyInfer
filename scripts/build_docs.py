"""Build or preview the static Docusaurus documentation with local search."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_WATCH_INTERVAL_SECONDS = 1.0
_IGNORED_WATCH_PARTS = frozenset(
    {
        ".cache",
        ".docusaurus",
        ".generated",
        ".git",
        "__pycache__",
        "build",
        "bin",
        "dist",
        "node_modules",
        "obj",
        "site",
    }
)


def _docusaurus_cli(root: Path) -> Path:
    """Return the repository-local Docusaurus executable."""
    suffix = ".cmd" if sys.platform == "win32" else ""
    return root / "website" / "node_modules" / ".bin" / f"docusaurus{suffix}"


def _docusaurus_command(root: Path) -> list[str]:
    """Use Docusaurus's local Node entry point when it is available."""
    node = shutil.which("node.exe" if sys.platform == "win32" else "node")
    entry_point = (
        root
        / "website"
        / "node_modules"
        / "@docusaurus"
        / "core"
        / "bin"
        / "docusaurus.mjs"
    )
    if node and entry_point.is_file():
        return [node, str(entry_point)]
    return [str(_docusaurus_cli(root))]


def _source_snapshot(root: Path) -> tuple[tuple[str, int, int], ...]:
    """Return metadata for authored inputs that require restaging on change."""
    paths: list[Path] = []
    patterns = {
        root / "docs": ("*",),
        root / "src" / "python": ("*.py",),
        root / "examples" / "csharp-sdk": ("*",),
        # Native sources and comments feed the generated C# API reference.
        root / "src" / "csharp" / "AnyInfer": ("*.cs", "*.csproj"),
        root / "src" / "csharp" / "AnyInfer.Maintenance": ("*.cs", "*.csproj"),
    }
    for directory, globs in patterns.items():
        if directory.is_dir():
            paths.extend(
                path
                for pattern in globs
                for path in directory.rglob(pattern)
                if path.is_file()
                and not any(part in _IGNORED_WATCH_PARTS for part in path.relative_to(root).parts)
            )
    paths.extend(
        path
        for path in (
            root / "pyproject.toml",
            root / "website" / "navigation.json",
            root / "website" / "requirements.lock",
            root / "website" / "docfx.json",
            root / "src" / "csharp" / "Directory.Build.props",
            root / "src" / "csharp" / "global.json",
            root / ".config" / "dotnet-tools.json",
        )
        if path.is_file()
    )
    return tuple(
        sorted(
            (
                path.relative_to(root).as_posix(),
                path.stat().st_mtime_ns,
                path.stat().st_size,
            )
            for path in paths
        )
    )


def _stop_preview_child(child: object) -> None:
    """Stop only the development server started by this preview invocation."""
    if child.poll() is not None:  # type: ignore[union-attr]
        return
    child.terminate()  # type: ignore[union-attr]
    try:
        child.wait(timeout=5)  # type: ignore[union-attr]
    except subprocess.TimeoutExpired:
        child.kill()  # type: ignore[union-attr]
        child.wait()  # type: ignore[union-attr]


def _preview(
    root: Path,
    rest: list[str],
    *,
    popen: object = subprocess.Popen,
    run: object = subprocess.run,
    sleep: object = time.sleep,
) -> int:
    """Serve Docusaurus while restaging changed documentation source files."""
    command = [*_docusaurus_command(root), "start", "--host", "127.0.0.1", *rest]
    child = popen(command, cwd=root / "website")  # type: ignore[operator]
    snapshot = _source_snapshot(root)
    try:
        while child.poll() is None:  # type: ignore[union-attr]
            sleep(_WATCH_INTERVAL_SECONDS)  # type: ignore[operator]
            updated = _source_snapshot(root)
            if updated != snapshot:
                snapshot = updated
                try:
                    run(  # type: ignore[operator]
                        [
                            sys.executable,
                            str(root / "scripts" / "prepare_docs.py"),
                            "--incremental",
                        ],
                        cwd=root,
                        check=True,
                    )
                except subprocess.CalledProcessError as error:
                    print(f"docs preview restaging failed: {error}", file=sys.stderr)
        return child.returncode or 0  # type: ignore[union-attr]
    except KeyboardInterrupt:
        _stop_preview_child(child)
        return child.returncode or 130  # type: ignore[union-attr]
    except BaseException:
        _stop_preview_child(child)
        raise


def main() -> int:
    """Prepare source content and run the requested documentation pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "prepare", "preview"))
    args, rest = parser.parse_known_args()
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if args.command != "prepare" and not npm:
        parser.error(
            "Node.js/npm is required; install Node 24 LTS and run npm --prefix website ci"
        )
    if args.command != "prepare" and not _docusaurus_cli(ROOT).exists():
        parser.error("documentation dependencies are missing; run npm --prefix website ci")
    if not all(
        path.exists()
        for path in (
            ROOT / "docs",
            ROOT / "src/csharp/Directory.Build.props",
            ROOT / "src/python/anyinfer-store/src",
            ROOT / "src/python/anyinfer-shared/src",
            ROOT / "src/python/anyinfer-confidential/src",
        )
    ):
        parser.error("the documentation site requires a complete repository checkout")
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/prepare_docs.py")], cwd=ROOT, check=True
        )
        if args.command == "prepare":
            return 0
        if args.command == "preview":
            if any(argument == "--host" or argument.startswith("--host=") for argument in rest):
                parser.error("preview host is fixed to 127.0.0.1")
            return _preview(ROOT, rest)
        if rest:
            parser.error("unexpected arguments for production build")
        subprocess.run([str(npm), "run", "site:build"], cwd=ROOT / "website", check=True)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/export_docs.py")], cwd=ROOT, check=True
        )
        subprocess.run([str(npm), "run", "search:index"], cwd=ROOT / "website", check=True)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_docs_site.py"), "--site", "site"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        return error.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
