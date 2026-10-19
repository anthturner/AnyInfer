"""Pure regression controls for shared C# observation mechanics."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _helper() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "_csharp_observation.py"
    spec = importlib.util.spec_from_file_location("csharp_observation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HELPER = _helper()


def _case(identifier: str = "one", kind: str = "kind") -> dict[str, object]:
    return {"id": identifier, "kind": kind}


def _envelope(
    *, runtime: str = "python", observations: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "profile": "profile-v1",
        "runtime": runtime,
        "source_revision": "a" * 40,
        "source_dirty": True,
        "corpus_sha256": "b" * 64,
        "observations": observations if observations is not None else [_case() | {"status": "ok"}],
    }


@pytest.mark.parametrize(
    "payload",
    [b"\xef\xbb\xbf{}", b"\xff", b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'],
)
def test_strict_json_rejects_bom_invalid_utf8_duplicate_keys_and_nonfinite_constants(
    tmp_path: Path, payload: bytes
) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(payload)
    with pytest.raises(HELPER.ObservationError):
        HELPER.read_json_bytes(path)


def test_raw_corpus_hash_preserves_crlf_bytes(tmp_path: Path) -> None:
    path = tmp_path / "inputs.json"
    raw = b'{"profile":"profile-v1"}\r\n'
    path.write_bytes(raw)
    assert (
        HELPER.corpus_sha256(path)
        != HELPER.hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    )


def test_read_cases_rejects_duplicate_and_read_observations_rejects_identity_drift(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps({"profile": "profile-v1", "cases": [_case(), _case()]}), encoding="utf-8"
    )
    with pytest.raises(HELPER.ObservationError, match="duplicate"):
        HELPER.read_cases(cases_path, profile="profile-v1")

    observation_path = tmp_path / "observation.json"
    observation_path.write_text(json.dumps(_envelope()), encoding="utf-8")
    cases = (HELPER.Case("one", "kind", _case()),)
    with pytest.raises(HELPER.ObservationError, match="input bytes"):
        HELPER.read_observations(
            observation_path,
            profile="profile-v1",
            expected_cases=cases,
            expected_runtime="python",
            expected_corpus_sha256="c" * 64,
            validate_observation=lambda _record, _where: None,
        )


def test_compare_copy_is_fresh_and_preserves_raw_bytes(tmp_path: Path) -> None:
    source_python = tmp_path / "source-python.json"
    source_native = tmp_path / "source-native.json"
    source_python.write_bytes(b'{\r\n  "python": true\r\n}\r\n')
    source_native.write_bytes(b'{"native":true}\n')
    directory = HELPER.fresh_run_directory(tmp_path / "runs")
    python_path, native_path = HELPER.copy_comparison_evidence(
        directory, source_python, source_native
    )
    assert directory.parent == tmp_path / "runs"
    assert python_path.read_bytes() == source_python.read_bytes()
    assert native_path.read_bytes() == source_native.read_bytes()


def test_runner_builds_stamped_commands_and_preserves_callback(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path]] = []
    config = HELPER.RunnerConfig(
        Path("python-observer.py"),
        "Native.Project",
        "Native.Project/Native.Project.csproj",
        "Dirty",
    )
    HELPER.run_observers(
        config,
        tmp_path / "input.json",
        tmp_path,
        source_revision="a" * 40,
        source_dirty=True,
        run=lambda command, cwd: calls.append((command, cwd)),
    )
    assert calls[0][0][:4] == [
        "dotnet",
        "build",
        "Native.Project/Native.Project.csproj",
        "--no-restore",
    ]
    assert calls[0][0][-2:] == ["-p:SourceRevisionId=" + "a" * 40, "-p:Dirty=true"]
    assert calls[1][0][1:] == [
        "python-observer.py",
        "--observe",
        str(tmp_path / "input.json"),
        str(tmp_path / "python.json"),
    ]
    assert calls[2][0][:6] == [
        "dotnet",
        "run",
        "--no-build",
        "--no-restore",
        "--project",
        "Native.Project",
    ]
