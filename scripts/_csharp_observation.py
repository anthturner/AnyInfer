"""Private mechanics for provenance-bound C# observation profiles.

Profile checkers retain their own value, error, ordering, and native-only semantics.
This module only validates raw envelopes and runs the two independent observers.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CSHARP_ROOT = ROOT / "src" / "csharp"
_REVISION = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ObservationError(RuntimeError):
    """Signals malformed observer evidence or an unqualified comparison."""


@dataclass(frozen=True)
class Case:
    """Indexes one input-only case while preserving its raw mapping."""

    identifier: str
    kind: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class ObserverRun:
    """Pairs validated observer provenance with its indexed raw observations."""

    runtime: str
    source_revision: str
    source_dirty: bool
    corpus_sha256: str
    observations: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class RunnerConfig:
    """Defines one profile's independently implemented observer commands."""

    python_observer: Path
    native_project: str
    native_csproj: str
    dirty_property: str


ObservationValidator = Callable[[dict[str, Any], str], None]
RunCommand = Callable[[list[str], Path], None]


def fail(message: str) -> NoReturn:
    """Raise the stable evidence-validation exception."""
    raise ObservationError(message)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _nonstandard_number(value: str) -> NoReturn:
    fail(f"nonstandard JSON numeric constant {value!r}")


def read_json_bytes(path: Path) -> Any:
    """Read strict UTF-8 JSON bytes without normalizing their representation."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        fail(f"cannot read JSON evidence {path}: {error}")
    if raw.startswith(b"\xef\xbb\xbf"):
        fail(f"JSON evidence {path} must not begin with a UTF-8 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        fail(f"JSON evidence {path} is not strict UTF-8: {error}")
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_nonstandard_number)
    except json.JSONDecodeError as error:
        fail(f"cannot read JSON evidence {path}: {error}")


def require_mapping(value: Any, where: str) -> dict[str, Any]:
    """Require one decoded JSON object."""
    if not isinstance(value, dict):
        fail(f"{where} must be a JSON object")
    return value


def require_string(value: Any, where: str) -> str:
    """Require one nonempty JSON string."""
    if not isinstance(value, str) or not value:
        fail(f"{where} must be a nonempty string")
    return value


def read_cases(path: Path, *, profile: str) -> tuple[dict[str, Any], tuple[Case, ...]]:
    """Read a strict profile envelope and index its unique input cases."""
    source = require_mapping(read_json_bytes(path), "input envelope")
    if source.get("profile") != profile:
        fail(f"input profile must be {profile!r}")
    raw_cases = source.get("cases")
    if not isinstance(raw_cases, list):
        fail("input cases must be an array")
    cases: list[Case] = []
    identifiers: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        case = require_mapping(raw_case, f"input case {index}")
        identifier = require_string(case.get("id"), f"input case {index}.id")
        kind = require_string(case.get("kind"), f"input case {identifier}.kind")
        if identifier in identifiers:
            fail(f"input contains duplicate case id {identifier!r}")
        identifiers.add(identifier)
        cases.append(Case(identifier, kind, case))
    return source, tuple(cases)


def read_observations(
    path: Path,
    *,
    profile: str,
    expected_cases: Iterable[Case],
    expected_runtime: str,
    expected_corpus_sha256: str,
    validate_observation: ObservationValidator,
) -> ObserverRun:
    """Read an observer envelope and delegate only record-body validation."""
    source = require_mapping(read_json_bytes(path), f"observation envelope {path}")
    if source.get("profile") != profile:
        fail(f"{path} does not identify {profile!r}")
    runtime = source.get("runtime")
    if runtime != expected_runtime:
        fail(f"{path} runtime must be {expected_runtime!r}")
    revision = source.get("source_revision")
    if not isinstance(revision, str) or _REVISION.fullmatch(revision) is None:
        fail(f"{path} source_revision must be a lowercase 40-character Git revision")
    dirty = source.get("source_dirty")
    if type(dirty) is not bool:
        fail(f"{path} source_dirty must be a boolean")
    corpus_sha256 = source.get("corpus_sha256")
    if not isinstance(corpus_sha256, str) or _SHA256.fullmatch(corpus_sha256) is None:
        fail(f"{path} corpus_sha256 must be a lowercase SHA-256 digest")
    if corpus_sha256 != expected_corpus_sha256:
        fail(f"{path} corpus_sha256 does not identify the supplied input bytes")
    raw_observations = source.get("observations")
    if not isinstance(raw_observations, list):
        fail(f"{path} observations must be an array")
    expected = {case.identifier: case.kind for case in expected_cases}
    observed: dict[str, dict[str, Any]] = {}
    for index, raw_observation in enumerate(raw_observations):
        observation = require_mapping(raw_observation, f"{path} observation {index}")
        identifier = require_string(observation.get("id"), f"{path} observation {index}.id")
        kind = require_string(observation.get("kind"), f"{path} observation {identifier}.kind")
        if identifier in observed:
            fail(f"{path} contains duplicate observation id {identifier!r}")
        if identifier not in expected:
            fail(f"{path} contains unexpected observation id {identifier!r}")
        if kind != expected[identifier]:
            fail(
                f"{path} observation {identifier!r} has kind {kind!r}, "
                f"expected {expected[identifier]!r}"
            )
        validate_observation(observation, f"{path} observation {identifier!r}")
        observed[identifier] = observation
    missing = set(expected).difference(observed)
    if missing:
        fail(f"{path} is missing observations: {', '.join(sorted(missing))}")
    return ObserverRun(runtime, revision, dirty, corpus_sha256, observed)


def source_identity() -> tuple[str, bool]:
    """Read the exact source identity used to stamp a default native build."""
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if _REVISION.fullmatch(revision) is None:
        fail("Git HEAD is not a lowercase 40-character revision")
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return revision, dirty


def run_observers(
    config: RunnerConfig,
    input_path: Path,
    directory: Path,
    *,
    source_revision: str,
    source_dirty: bool,
    run: RunCommand,
) -> tuple[Path, Path]:
    """Build a stamped native observer then run both observers into one directory."""
    python_output = directory / "python.json"
    native_output = directory / "native.json"
    run(
        [
            "dotnet",
            "build",
            config.native_csproj,
            "--no-restore",
            f"-p:SourceRevisionId={source_revision}",
            f"-p:{config.dirty_property}={str(source_dirty).lower()}",
        ],
        CSHARP_ROOT,
    )
    run(
        [
            sys.executable,
            str(config.python_observer),
            "--observe",
            str(input_path),
            str(python_output),
        ],
        ROOT,
    )
    run(
        [
            "dotnet",
            "run",
            "--no-build",
            "--no-restore",
            "--project",
            config.native_project,
            "--",
            str(input_path),
            str(native_output),
        ],
        CSHARP_ROOT,
    )
    return python_output, native_output


def fresh_run_directory(output_root: Path) -> Path:
    """Create one profile-local fresh evidence directory."""
    output_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run-", dir=output_root))


def copy_comparison_evidence(
    directory: Path, python_source: Path, native_source: Path
) -> tuple[Path, Path]:
    """Copy comparison evidence without parsing or rewriting its bytes."""
    python_path = directory / "python.json"
    native_path = directory / "native.json"
    shutil.copy2(python_source, python_path)
    shutil.copy2(native_source, native_path)
    return python_path, native_path


def validate_handshake(
    python_run: ObserverRun,
    native_run: ObserverRun,
    *,
    stamped_identity: tuple[str, bool] | None = None,
) -> None:
    """Reject observer evidence not tied to one source identity and corpus."""
    if python_run.source_revision != native_run.source_revision:
        fail("observer source revisions differ; native executable evidence is not comparable")
    if python_run.source_dirty != native_run.source_dirty:
        fail("observer dirty-state evidence differs; native executable evidence is not comparable")
    if python_run.corpus_sha256 != native_run.corpus_sha256:
        fail("observer corpus digests differ; native executable evidence is not comparable")
    if stamped_identity is not None and (
        python_run.source_revision != stamped_identity[0]
        or python_run.source_dirty != stamped_identity[1]
    ):
        fail("default observer evidence is not bound to the stamped current source identity")


def corpus_sha256(path: Path) -> str:
    """Hash the exact raw corpus bytes used by both observer invocations."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
