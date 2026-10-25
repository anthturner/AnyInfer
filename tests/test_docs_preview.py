"""Focused tests for Docusaurus preview source staging."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).parents[1] / "scripts" / "build_docs.py"
_SPEC = importlib.util.spec_from_file_location("build_docs", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "python" / "anyinfer").mkdir(parents=True)
    (tmp_path / "website").mkdir()
    (tmp_path / "src" / "csharp").mkdir(parents=True)
    (tmp_path / "examples" / "csharp-sdk").mkdir(parents=True)
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "src" / "python" / "anyinfer" / "client.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "website" / "navigation.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "website" / "requirements.lock").write_text("# lock\n", encoding="utf-8")
    (tmp_path / "src" / "csharp" / "Directory.Build.props").write_text("<Project/>\n", encoding="utf-8")
    (tmp_path / "examples" / "csharp-sdk" / "Sample.cs").write_text("var value = 1;\n", encoding="utf-8")
    return tmp_path


def test_source_snapshot_ignores_generated_directories_and_watches_csharp_sources(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ignored = root / "docs" / "build"
    ignored.mkdir()
    (ignored / "stale.md").write_text("old\n", encoding="utf-8")
    before = _MODULE._source_snapshot(root)

    (ignored / "stale.md").write_text("changed\n", encoding="utf-8")
    assert _MODULE._source_snapshot(root) == before

    (root / "docs" / "guide.md").write_text("# Changed\n", encoding="utf-8")
    assert _MODULE._source_snapshot(root) != before

    before = _MODULE._source_snapshot(root)
    csharp_source = root / "examples" / "csharp-sdk" / "Sample.cs"
    csharp_source.write_text("var value = 2;\n", encoding="utf-8")
    assert _MODULE._source_snapshot(root) != before

    before = _MODULE._source_snapshot(root)
    generated = root / "examples" / "csharp-sdk" / "bin"
    generated.mkdir()
    (generated / "Sample.dll").write_bytes(b"generated")
    assert _MODULE._source_snapshot(root) == before


def test_preview_restages_a_changed_source_and_preserves_child_exit_code(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / "docs" / "guide.md"
    commands: list[tuple[list[str], Path, bool]] = []

    class Child:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

    child = Child()

    def popen(command: list[str], *, cwd: Path) -> Child:
        assert command[-5:] == ["start", "--host", "127.0.0.1", "--port", "3001"]
        assert cwd == root / "website"
        return child

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        commands.append((command, cwd, check))

    calls = 0

    def sleep(_: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            source.write_text("# Updated\n", encoding="utf-8")
        else:
            child.returncode = 7

    assert _MODULE._preview(root, ["--port", "3001"], popen=popen, run=run, sleep=sleep) == 7
    assert commands == [
        ([
            _MODULE.sys.executable,
            str(root / "scripts" / "prepare_docs.py"),
            "--incremental",
        ], root, True)
    ]


def test_preview_retries_after_a_failed_restage_and_preserves_child_exit_code(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / "docs" / "guide.md"
    commands: list[list[str]] = []

    class Child:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

    child = Child()

    def popen(_: list[str], *, cwd: Path) -> Child:
        assert cwd == root / "website"
        return child

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == root and check
        commands.append(command)
        if len(commands) == 1:
            raise subprocess.CalledProcessError(1, command)

    calls = 0

    def sleep(_: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            source.write_text("# First edit\n", encoding="utf-8")
        elif calls == 2:
            source.write_text("# Second edit\n", encoding="utf-8")
        else:
            child.returncode = 9

    assert _MODULE._preview(root, [], popen=popen, run=run, sleep=sleep) == 9
    assert commands == [
        [
            _MODULE.sys.executable,
            str(root / "scripts" / "prepare_docs.py"),
            "--incremental",
        ],
        [
            _MODULE.sys.executable,
            str(root / "scripts" / "prepare_docs.py"),
            "--incremental",
        ],
    ]


def test_preview_stops_its_child_after_an_unexpected_restage_exception(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / "docs" / "guide.md"

    class Child:
        returncode: int | None = None
        terminated = False

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = 1

        def wait(self, *, timeout: int | None = None) -> int:
            assert timeout == 5
            return 1

    child = Child()

    def popen(_: list[str], *, cwd: Path) -> Child:
        assert cwd == root / "website"
        return child

    def run(_: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == root and check
        raise RuntimeError("unexpected preparation failure")

    def sleep(_: float) -> None:
        source.write_text("# Updated\n", encoding="utf-8")

    try:
        _MODULE._preview(root, [], popen=popen, run=run, sleep=sleep)
    except RuntimeError:
        pass
    else:  # pragma: no cover - keeps the assertion below meaningful.
        raise AssertionError("expected restaging failure")

    assert child.terminated
