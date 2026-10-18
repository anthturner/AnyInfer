"""Compare independent Python and native observations for accounting-v1.

This is an orchestration and comparison tool only.  It intentionally contains no
pricing, estimation, ledger, or pacing logic: each runtime must produce its own
observations through its production public APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CSHARP_ROOT = ROOT / "src" / "csharp"
PYTHON_OBSERVER = ROOT / "tests" / "test_accounting_parity.py"
DEFAULT_INPUT = ROOT / "tests" / "fixtures" / "accounting-v1" / "inputs.json"
DEFAULT_OUTPUT_ROOT = ROOT / ".tmp-tests" / "accounting"
PROFILE = "accounting-v1"


class ObservationError(RuntimeError):
    """Signals malformed observer evidence or an unqualified comparison."""


@dataclass(frozen=True)
class Comparison:
    """Contains one complete accounting comparison without a semantic verdict table."""

    profile: str
    matched: tuple[str, ...]
    mismatches: tuple[dict[str, str], ...]
    native_only: tuple[dict[str, Any], ...]

    @property
    def status(self) -> str:
        """Gets pass, fail, or pending from actual evidence completeness."""
        if self.mismatches:
            return "fail"
        if any(item["qualification"] != "observed" for item in self.native_only):
            return "pending"
        return "pass"


@dataclass(frozen=True)
class ObserverRun:
    """Pairs a validated observer identity with its indexed raw observations."""

    runtime: str
    source_revision: str
    source_dirty: bool
    corpus_sha256: str
    observations: dict[str, dict[str, Any]]


# These are semantic exception families, not diagnostic-text fallbacks.  Observers
# must still expose an explicit structured error type for every error observation.
_ERROR_MAPPINGS: dict[str, frozenset[str]] = {
    "ValueError": frozenset(
        {"ArgumentException", "ArgumentOutOfRangeException", "FormatException"}
    ),
    "ArithmeticError": frozenset({"OverflowException", "DivideByZeroException"}),
    "OverflowError": frozenset({"OverflowException"}),
    "ZeroDivisionError": frozenset({"DivideByZeroException"}),
    "ContextLengthError": frozenset({"ContextLengthException"}),
    "SpendLimitError": frozenset({"SpendLimitException"}),
}
_DECIMAL_CAUSES: dict[str, str] = {
    "InvalidOperation": "invalid_operation",
    "Overflow": "overflow",
    "DivisionByZero": "division_by_zero",
}
_KNOWN_ERROR_TYPES = frozenset(
    {
        "ValueError",
        "ArithmeticError",
        "InvalidOperation",
        "Overflow",
        "DivisionByZero",
        "OverflowError",
        "ZeroDivisionError",
        "ArgumentException",
        "ArgumentOutOfRangeException",
        "FormatException",
        "ETrapException",
        "OverflowException",
        "DivideByZeroException",
        "ContextLengthError",
        "ContextLengthException",
        "SpendLimitError",
        "SpendLimitException",
    }
)
_ORDERED_MAP_NAMES = frozenset({"by_target", "by_label", "server_tool_uses"})
_REVISION = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _fail(message: str) -> NoReturn:
    raise ObservationError(message)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        _fail(f"cannot read JSON evidence {path}: {error}")


def _require_mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{where} must be a JSON object")
    return value


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{where} must be a nonempty string")
    return value


def read_cases(path: Path) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Read and strictly index the input-only fixture envelope."""
    source = _require_mapping(_read_json(path), "input envelope")
    if source.get("profile") != PROFILE:
        _fail(f"input profile must be {PROFILE!r}")
    raw_cases = source.get("cases")
    if not isinstance(raw_cases, list):
        _fail("input cases must be an array")
    cases: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        case = _require_mapping(raw_case, f"input case {index}")
        identifier = _require_string(case.get("id"), f"input case {index}.id")
        _require_string(case.get("kind"), f"input case {identifier}.kind")
        if identifier in ids:
            _fail(f"input contains duplicate case id {identifier!r}")
        ids.add(identifier)
        cases.append(case)
    return source, tuple(cases)


def read_observations(
    path: Path,
    *,
    expected_cases: Iterable[dict[str, Any]],
    expected_runtime: str,
    expected_corpus_sha256: str,
) -> ObserverRun:
    """Read one observer envelope and reject missing, duplicate, or malformed records."""
    source = _require_mapping(_read_json(path), f"observation envelope {path}")
    if source.get("profile") != PROFILE:
        _fail(f"{path} does not identify {PROFILE!r}")
    runtime = source.get("runtime")
    if runtime != expected_runtime:
        _fail(f"{path} runtime must be {expected_runtime!r}")
    revision = source.get("source_revision")
    if not isinstance(revision, str) or _REVISION.fullmatch(revision) is None:
        _fail(f"{path} source_revision must be a lowercase 40-character Git revision")
    dirty = source.get("source_dirty")
    if type(dirty) is not bool:
        _fail(f"{path} source_dirty must be a boolean")
    corpus_sha256 = source.get("corpus_sha256")
    if not isinstance(corpus_sha256, str) or _SHA256.fullmatch(corpus_sha256) is None:
        _fail(f"{path} corpus_sha256 must be a lowercase SHA-256 digest")
    if corpus_sha256 != expected_corpus_sha256:
        _fail(f"{path} corpus_sha256 does not identify the supplied input bytes")
    raw_observations = source.get("observations")
    if not isinstance(raw_observations, list):
        _fail(f"{path} observations must be an array")
    expected = {case["id"]: case["kind"] for case in expected_cases}
    observed: dict[str, dict[str, Any]] = {}
    for index, raw_observation in enumerate(raw_observations):
        observation = _require_mapping(raw_observation, f"{path} observation {index}")
        identifier = _require_string(observation.get("id"), f"{path} observation {index}.id")
        kind = _require_string(observation.get("kind"), f"{path} observation {identifier}.kind")
        if identifier in observed:
            _fail(f"{path} contains duplicate observation id {identifier!r}")
        if identifier not in expected:
            _fail(f"{path} contains unexpected observation id {identifier!r}")
        if kind != expected[identifier]:
            _fail(
                f"{path} observation {identifier!r} has kind {kind!r}, "
                f"expected {expected[identifier]!r}"
            )
        status = observation.get("status")
        if status == "ok":
            if "value" not in observation or "error_type" in observation:
                _fail(f"{path} successful observation {identifier!r} has malformed status fields")
        elif status == "error":
            _require_string(
                observation.get("error_type"),
                f"{path} error observation {identifier}.error_type",
            )
            if "value" in observation:
                _fail(f"{path} error observation {identifier!r} must not contain a value")
            for flag_name in ("error_flags", "structured_flags"):
                flags = observation.get(flag_name)
                if flags is not None and not isinstance(flags, dict):
                    _fail(f"{path} error observation {identifier!r}.{flag_name} must be an object")
            decimal_cause = observation.get("decimal_cause")
            if decimal_cause is not None:
                _require_string(
                    decimal_cause,
                    f"{path} error observation {identifier!r}.decimal_cause",
                )
        else:
            _fail(f"{path} observation {identifier!r} has unsupported status {status!r}")
        observed[identifier] = observation
    missing = set(expected).difference(observed)
    if missing:
        _fail(f"{path} is missing observations: {', '.join(sorted(missing))}")
    return ObserverRun(runtime, revision, dirty, corpus_sha256, observed)


def _value_difference(left: Any, right: Any, path: str = "$") -> str | None:
    """Return the first exact JSON-value difference, preserving numeric and list semantics."""
    if type(left) is not type(right):
        return f"{path}: type differs ({type(left).__name__} != {type(right).__name__})"
    if isinstance(left, dict):
        if set(left) != set(right):
            return f"{path}: keys differ ({list(left)} != {list(right)})"
        if path.rsplit(".", 1)[-1] in _ORDERED_MAP_NAMES and list(left) != list(right):
            return f"{path}: ordinal map keys differ ({list(left)} != {list(right)})"
        for key in left:
            difference = _value_difference(left[key], right[key], f"{path}.{key}")
            if difference is not None:
                return difference
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: list length differs ({len(left)} != {len(right)})"
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            difference = _value_difference(left_item, right_item, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    if left != right:
        return f"{path}: value differs ({left!r} != {right!r})"
    return None


def _errors_match(python: dict[str, Any], native: dict[str, Any]) -> bool:
    python_type = python["error_type"]
    native_type = native["error_type"]
    expected_cause = _DECIMAL_CAUSES.get(python_type)
    if expected_cause is not None:
        return (
            python.get("decimal_cause") == expected_cause
            and native_type == "ETrapException"
            and native.get("decimal_cause") == expected_cause
        )
    if native_type == "ETrapException":
        # ETrapException.Error is a concrete public arithmetic flag.  A generic
        # ArithmeticError cannot establish which decimal trap occurred.
        return False
    if python_type == native_type and python_type in _KNOWN_ERROR_TYPES:
        return True
    return native_type in _ERROR_MAPPINGS.get(python_type, frozenset())


def _native_boundary_evidence(observation: dict[str, Any]) -> bool:
    """Require an observer-reported native boundary, never a fixture echo."""
    if observation.get("status") != "error":
        return False
    flags = observation.get("structured_flags")
    return isinstance(flags, dict) and flags.get("native_only") is True


def compare_observations(
    cases: Iterable[dict[str, Any]],
    python: dict[str, dict[str, Any]],
    native: dict[str, dict[str, Any]],
) -> Comparison:
    """Compare raw projections while keeping native-only controls outside shared matches."""
    matched: list[str] = []
    mismatches: list[dict[str, str]] = []
    native_only: list[dict[str, Any]] = []
    for case in cases:
        identifier = case["id"]
        kind = case["kind"]
        python_observation = python[identifier]
        native_observation = native[identifier]
        if kind.startswith("native_only_"):
            native_only.append(
                {
                    "id": identifier,
                    "kind": kind,
                    "qualification": (
                        "observed" if _native_boundary_evidence(native_observation) else "pending"
                    ),
                    "python_status": python_observation["status"],
                    "native_status": native_observation["status"],
                }
            )
            continue
        if python_observation["status"] != native_observation["status"]:
            mismatches.append({"id": identifier, "difference": "observer statuses differ"})
            continue
        if python_observation["status"] == "ok":
            difference = _value_difference(
                python_observation["value"], native_observation["value"]
            )
            if difference is None:
                matched.append(identifier)
            else:
                mismatches.append({"id": identifier, "difference": difference})
            continue
        if _errors_match(python_observation, native_observation):
            matched.append(identifier)
        else:
            mismatches.append(
                {
                    "id": identifier,
                    "difference": (
                        "unmapped structured errors "
                        f"({python_observation['error_type']} "
                        f"!= {native_observation['error_type']})"
                    ),
                }
            )
    return Comparison(PROFILE, tuple(matched), tuple(mismatches), tuple(native_only))


def _run(command: list[str], *, cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _source_identity() -> tuple[str, bool]:
    """Read the exact source identity used to stamp a default native build."""
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if _REVISION.fullmatch(revision) is None:
        _fail("Git HEAD is not a lowercase 40-character revision")
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    return revision, dirty


def run_observers(
    inputs: Path,
    directory: Path,
    *,
    source_revision: str,
    source_dirty: bool,
) -> tuple[Path, Path]:
    """Run both independently implemented observers into one fresh evidence directory."""
    python_output = directory / "python.json"
    native_output = directory / "native.json"
    _run(
        [
            "dotnet",
            "build",
            "AnyInfer.Accounting/AnyInfer.Accounting.csproj",
            "--no-restore",
            f"-p:SourceRevisionId={source_revision}",
            f"-p:AccountingSourceDirty={str(source_dirty).lower()}",
        ],
        cwd=CSHARP_ROOT,
    )
    _run(
        [sys.executable, str(PYTHON_OBSERVER), "--observe", str(inputs), str(python_output)],
        cwd=ROOT,
    )
    _run(
        [
            "dotnet",
            "run",
            "--no-build",
            "--no-restore",
            "--project",
            "AnyInfer.Accounting",
            "--",
            str(inputs),
            str(native_output),
        ],
        cwd=CSHARP_ROOT,
    )
    return python_output, native_output


def _report(
    comparison: Comparison,
    *,
    input_path: Path,
    python_path: Path,
    native_path: Path,
    python_run: ObserverRun,
    native_run: ObserverRun,
) -> dict[str, Any]:
    return {
        "profile": comparison.profile,
        "status": comparison.status,
        "corpus_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "observers": {
            "python": {
                "runtime": python_run.runtime,
                "source_revision": python_run.source_revision,
                "source_dirty": python_run.source_dirty,
                "corpus_sha256": python_run.corpus_sha256,
            },
            "native": {
                "runtime": native_run.runtime,
                "source_revision": native_run.source_revision,
                "source_dirty": native_run.source_dirty,
                "corpus_sha256": native_run.corpus_sha256,
            },
        },
        "python_observation": str(python_path),
        "native_observation": str(native_path),
        "shared": {"matched": list(comparison.matched), "mismatches": list(comparison.mismatches)},
        "native_only": list(comparison.native_only),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse either default observer orchestration or an evidence-only comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("PYTHON", "NATIVE"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Write a fresh report and return nonzero for failed or incomplete qualification."""
    options = parse_args(sys.argv[1:] if argv is None else argv)
    input_path = options.input.resolve()
    _, cases = read_cases(input_path)
    corpus_sha256 = hashlib.sha256(input_path.read_bytes()).hexdigest()
    output_root = options.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=output_root))
    if options.compare is None:
        source_revision, source_dirty = _source_identity()
        python_path, native_path = run_observers(
            input_path,
            directory,
            source_revision=source_revision,
            source_dirty=source_dirty,
        )
    else:
        python_source, native_source = (path.resolve() for path in options.compare)
        python_path = directory / "python.json"
        native_path = directory / "native.json"
        shutil.copy2(python_source, python_path)
        shutil.copy2(native_source, native_path)
    python_run = read_observations(
        python_path,
        expected_cases=cases,
        expected_runtime="python",
        expected_corpus_sha256=corpus_sha256,
    )
    native_run = read_observations(
        native_path,
        expected_cases=cases,
        expected_runtime="csharp",
        expected_corpus_sha256=corpus_sha256,
    )
    if python_run.source_revision != native_run.source_revision:
        _fail("observer source revisions differ; native executable evidence is not comparable")
    if python_run.source_dirty != native_run.source_dirty:
        _fail(
            "observer dirty-state evidence differs; native executable evidence is not comparable"
        )
    if options.compare is None and (
        python_run.source_revision != source_revision or python_run.source_dirty != source_dirty
    ):
        _fail("default observer evidence is not bound to the stamped current source identity")
    comparison = compare_observations(cases, python_run.observations, native_run.observations)
    report = _report(
        comparison,
        input_path=input_path,
        python_path=python_path,
        native_path=native_path,
        python_run=python_run,
        native_run=native_run,
    )
    report_path = directory / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{comparison.status}: {report_path}")
    return 0 if comparison.status == "pass" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ObservationError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
