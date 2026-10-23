"""Strictly compare independent public tool-loop-v1 observations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

import _csharp_observation as observation
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

PROFILE = "tool-loop-v1"
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / PROFILE
DEFAULT_INPUT = FIXTURES / "inputs.json"
DEFAULT_OUTPUT_ROOT = ROOT / ".tmp-tests" / "tool-loop"
INPUT_SCHEMA = FIXTURES / "schema.json"
OBSERVATION_SCHEMA = FIXTURES / "observations.schema.json"
FROZEN_CORPUS_SHA256 = "4693fca5c88e2c3ca129b7197b819c5c55bfbe11d2621135184bb7bfcfbad5a9"
FROZEN_SCHEMA_SHA256 = "7c445c33b494b2a5a0a4ca3204129fbd8630e776c5e50545f9a7bb11c7f80f7c"
FROZEN_OBSERVATION_SCHEMA_SHA256 = (
    "0eab305617e3563affe3dea43ad8360cf3a1b93cca29bd4b7bb48ccb994fa772"
)
FROZEN_README_SHA256 = "4467ff276cdb8d1d1c24b16d1cd0a3470343a6effc92d5469f46804585ffa1f1"
RUNNER = observation.RunnerConfig(
    python_observer=ROOT / "scripts" / "observe_python_tool_loop.py",
    native_project="AnyInfer.ToolLoop",
    native_csproj="AnyInfer.ToolLoop/AnyInfer.ToolLoop.csproj",
    dirty_property="ToolLoopSourceDirty",
)
_ERROR_TYPES = {"ToolLoopError": "ToolLoopException"}


def _fail(message: str) -> NoReturn:
    raise observation.ObservationError(message)


def _validate_schema(path: Path, value: Any, *, label: str) -> None:
    try:
        Draft202012Validator(observation.read_json_bytes(path)).validate(value)
    except (SchemaError, ValidationError) as error:
        _fail(f"{label} does not satisfy its frozen schema: {error.message}")


def _verify_frozen_assets() -> None:
    for path, digest in (
        (DEFAULT_INPUT, FROZEN_CORPUS_SHA256),
        (INPUT_SCHEMA, FROZEN_SCHEMA_SHA256),
        (OBSERVATION_SCHEMA, FROZEN_OBSERVATION_SCHEMA_SHA256),
        (FIXTURES / "README.md", FROZEN_README_SHA256),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            _fail(f"frozen asset digest differs: {path.name}")


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _fail("observation contains a nonfinite JSON number")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def read_cases(path: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Read the no-kind closed input grammar without using the kind-bearing helper."""
    raw = observation.read_json_bytes(path)
    _validate_schema(INPUT_SCHEMA, raw, label="tool-loop input")
    if raw["profile"] != PROFILE:
        _fail("input profile is not tool-loop-v1")
    identifiers = tuple(item["id"] for item in raw["cases"])
    if len(identifiers) != 10 or len(set(identifiers)) != len(identifiers):
        _fail("tool-loop input must contain ten unique case identifiers")
    return raw, identifiers


def _validate_envelope(
    path: Path, *, runtime: str, identifiers: Sequence[str], digest: str
) -> dict[str, Any]:
    raw = observation.read_json_bytes(path)
    _finite(raw)
    _validate_schema(OBSERVATION_SCHEMA, raw, label=f"{runtime} observation")
    if raw["profile"] != PROFILE or raw["runtime"] != runtime:
        _fail("observation profile or runtime is invalid")
    if raw["corpus_sha256"] != digest:
        _fail("observation corpus digest does not identify supplied input bytes")
    observed = [item["id"] for item in raw["observations"]]
    if observed != list(identifiers):
        _fail("observations must contain exactly the input case IDs once and in input order")
    return raw


def _comparison_value(record: Mapping[str, Any]) -> dict[str, Any]:
    """Retain runtime diagnostics while excluding only their declared free-text role."""
    value = json.loads(json.dumps(record))
    error = value["public"]["error"]
    if error is not None:
        if error["type"] in set(_ERROR_TYPES) | set(_ERROR_TYPES.values()):
            error["type"] = "<tool-loop-error>"
        for name in ("message", "detail", "hint"):
            if name in error:
                error[name] = "<free-diagnostic>"
    return value


def _equal(left: Any, right: Any, path: str = "value") -> str | None:
    if type(left) is not type(right):
        return f"{path}: {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return f"{path}: object keys differ"
        for key in left:
            difference = _equal(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
    elif isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: array length differs"
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            difference = _equal(a, b, f"{path}[{index}]")
            if difference:
                return difference
    elif left != right:
        return f"{path}: {left!r} != {right!r}"
    return None


def compare_case(
    identifier: str, python: Mapping[str, Any], native: Mapping[str, Any]
) -> dict[str, str] | None:
    """Compare one actual capture without deriving an expected SDK result."""
    python_error = python["public"]["error"]
    native_error = native["public"]["error"]
    if python_error is not None and python_error["type"] != "ToolLoopError":
        _fail("Python tool-loop error type must be ToolLoopError")
    if native_error is not None and native_error["type"] != "ToolLoopException":
        _fail("C# tool-loop error type must be ToolLoopException")
    difference = _equal(_comparison_value(python), _comparison_value(native))
    return None if difference is None else {"id": identifier, "difference": difference}


def validate_handshake(
    python: Mapping[str, Any], native: Mapping[str, Any], *, identity: tuple[str, bool] | None
) -> None:
    """Require both recordings to identify one source tree and optional current stamp."""
    python_identity = python["source_revision"], python["source_dirty"]
    native_identity = native["source_revision"], native["source_dirty"]
    if python_identity != native_identity:
        _fail("observer source revision or dirty state differs")
    if identity and python_identity != identity:
        _fail("default observation evidence is not stamped with current source identity")


def _run(command: list[str], cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main(argv: list[str] | None = None) -> int:
    """Run independent observers or compare two existing observation envelopes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("PYTHON", "NATIVE"))
    options = parser.parse_args(sys.argv[1:] if argv is None else argv)
    _verify_frozen_assets()
    input_path = options.input.resolve()
    _, identifiers = read_cases(input_path)
    digest = observation.corpus_sha256(input_path)
    if digest != FROZEN_CORPUS_SHA256:
        _fail("tool-loop input bytes do not match the frozen corpus SHA-256")
    directory = observation.fresh_run_directory(options.output_root.resolve())
    identity: tuple[str, bool] | None = None
    if options.compare:
        python_path, native_path = observation.copy_comparison_evidence(
            directory, *(item.resolve() for item in options.compare)
        )
    else:
        identity = observation.source_identity()
        python_path, native_path = observation.run_observers(
            RUNNER,
            input_path,
            directory,
            source_revision=identity[0],
            source_dirty=identity[1],
            run=_run,
        )
    python = _validate_envelope(
        python_path, runtime="python", identifiers=identifiers, digest=digest
    )
    native = _validate_envelope(
        native_path, runtime="csharp", identifiers=identifiers, digest=digest
    )
    validate_handshake(python, native, identity=identity)
    mismatches = [
        result
        for identifier, left, right in zip(
            identifiers, python["observations"], native["observations"], strict=True
        )
        if (result := compare_case(identifier, left, right)) is not None
    ]
    mismatched_ids = {entry["id"] for entry in mismatches}
    report = {
        "profile": PROFILE,
        "status": "pass" if not mismatches else "fail",
        "corpus_sha256": digest,
        "shared": {
            "matched": [item for item in identifiers if item not in mismatched_ids],
            "mismatches": mismatches,
        },
        "runtime_specific": [],
        "native_only": [],
    }
    report_path = directory / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']}: {report_path}")
    return int(bool(mismatches))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except observation.ObservationError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from None
