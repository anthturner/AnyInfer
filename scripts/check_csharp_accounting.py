"""Compare independent Python and native observations for accounting-v1.

This is an orchestration and comparison tool only.  It intentionally contains no
pricing, estimation, ledger, or pacing logic: each runtime must produce its own
observations through its production public APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import _csharp_observation as observation

ROOT = Path(__file__).resolve().parents[1]
CSHARP_ROOT = ROOT / "src" / "csharp"
PYTHON_OBSERVER = ROOT / "tests" / "test_accounting_parity.py"
DEFAULT_INPUT = ROOT / "tests" / "fixtures" / "accounting-v1" / "inputs.json"
DEFAULT_OUTPUT_ROOT = ROOT / ".tmp-tests" / "accounting"
PROFILE = "accounting-v1"


class ObservationError(observation.ObservationError):
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


def _fail(message: str) -> NoReturn:
    raise ObservationError(message)


def _read_json(path: Path) -> Any:
    try:
        return observation.read_json_bytes(path)
    except observation.ObservationError as error:
        _fail(str(error))


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
    try:
        source, cases = observation.read_cases(path, profile=PROFILE)
    except observation.ObservationError as error:
        _fail(str(error))
    return source, tuple(case.raw for case in cases)


def read_observations(
    path: Path,
    *,
    expected_cases: Iterable[dict[str, Any]],
    expected_runtime: str,
    expected_corpus_sha256: str,
) -> ObserverRun:
    """Read one observer envelope and reject missing, duplicate, or malformed records."""

    def validate(record: dict[str, Any], where: str) -> None:
        status = record.get("status")
        if status == "ok":
            if "value" not in record or "error_type" in record:
                _fail(f"{where} has malformed status fields")
        elif status == "error":
            _require_string(record.get("error_type"), f"{where}.error_type")
            if "value" in record:
                _fail(f"{where} must not contain a value")
            for flag_name in ("error_flags", "structured_flags"):
                flags = record.get(flag_name)
                if flags is not None and not isinstance(flags, dict):
                    _fail(f"{where}.{flag_name} must be an object")
            decimal_cause = record.get("decimal_cause")
            if decimal_cause is not None:
                _require_string(decimal_cause, f"{where}.decimal_cause")
        else:
            _fail(f"{where} has unsupported status {status!r}")

    cases = tuple(observation.Case(case["id"], case["kind"], case) for case in expected_cases)
    try:
        run = observation.read_observations(
            path,
            profile=PROFILE,
            expected_cases=cases,
            expected_runtime=expected_runtime,
            expected_corpus_sha256=expected_corpus_sha256,
            validate_observation=validate,
        )
    except observation.ObservationError as error:
        _fail(str(error))
    return ObserverRun(
        run.runtime,
        run.source_revision,
        run.source_dirty,
        run.corpus_sha256,
        run.observations,
    )


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
    try:
        return observation.source_identity()
    except observation.ObservationError as error:
        _fail(str(error))


def run_observers(
    inputs: Path,
    directory: Path,
    *,
    source_revision: str,
    source_dirty: bool,
) -> tuple[Path, Path]:
    """Run both independently implemented observers into one fresh evidence directory."""
    config = observation.RunnerConfig(
        PYTHON_OBSERVER,
        "AnyInfer.Accounting",
        "AnyInfer.Accounting/AnyInfer.Accounting.csproj",
        "AccountingSourceDirty",
    )
    return observation.run_observers(
        config,
        inputs,
        directory,
        source_revision=source_revision,
        source_dirty=source_dirty,
        run=lambda command, cwd: _run(command, cwd=cwd),
    )


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
    corpus_sha256 = observation.corpus_sha256(input_path)
    directory = observation.fresh_run_directory(options.output_root.resolve())
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
        python_path, native_path = observation.copy_comparison_evidence(
            directory, python_source, native_source
        )
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
    try:
        observation.validate_handshake(
            observation.ObserverRun(
                python_run.runtime,
                python_run.source_revision,
                python_run.source_dirty,
                python_run.corpus_sha256,
                python_run.observations,
            ),
            observation.ObserverRun(
                native_run.runtime,
                native_run.source_revision,
                native_run.source_dirty,
                native_run.corpus_sha256,
                native_run.observations,
            ),
            stamped_identity=(source_revision, source_dirty) if options.compare is None else None,
        )
    except observation.ObservationError as error:
        _fail(str(error))
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
