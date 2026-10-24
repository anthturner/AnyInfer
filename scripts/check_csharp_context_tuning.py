"""Qualify independently observed context-tuning-v1 public evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

try:  # Direct-file invocation puts the sibling module on sys.path.
    from _csharp_observation import (
        ROOT,
        Case,
        ObservationError,
        ObserverRun,
        RunnerConfig,
        corpus_sha256,
        fail,
        fresh_run_directory,
        read_json_bytes,
        run_observers,
        source_identity,
        validate_handshake,
    )
except ModuleNotFoundError:  # Test imports use the repository-root package namespace.
    from scripts._csharp_observation import (
        ROOT,
        Case,
        ObservationError,
        ObserverRun,
        RunnerConfig,
        corpus_sha256,
        fail,
        fresh_run_directory,
        read_json_bytes,
        run_observers,
        source_identity,
        validate_handshake,
    )

PROFILE = "context-tuning-v1"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / PROFILE
DEFAULT_INPUT = FIXTURE_ROOT / "inputs.json"
DEFAULT_SCHEMA = FIXTURE_ROOT / "schema.json"
DEFAULT_OBSERVATION_SCHEMA = FIXTURE_ROOT / "observations.schema.json"
FROZEN_CORPUS_SHA256 = "122298b5b1631317db9aa93e428faa81a00ece6da9ba9694026a57cd050b30e6"
FROZEN_SCHEMA_SHA256 = "f8c79b38bff6f0acbed27c74e6112806a6fa927124d56890a7b253b566ec4884"
FROZEN_OBSERVATION_SCHEMA_SHA256 = (
    "9ee537e939ced40c3f81ba6e19d7988daff5dc3682ed64ccef4a572334182e86"
)
FROZEN_README_SHA256 = "484edc6784e2c7db87ed0e0a808d549f31910ffdde42ab2d2c6c0d7bdf43843c"

COUNT_FIELDS = {
    "shingle_size",
    "expansion_terms",
    "feedback_documents",
    "salience_iterations",
    "chunk_tokens",
}
BOOL_FIELDS = {"collapse_duplicates", "split_identifiers", "query_expansion", "compact_fallback"}
FLOAT_FIELDS = {
    "near_duplicate_threshold",
    "diversity",
    "expansion_weight",
    "salience_weight",
    "salience_damping",
    "rollup_share",
    "carry_over_bonus",
}
SETTING_FIELDS = BOOL_FIELDS | COUNT_FIELDS | FLOAT_FIELDS | {"selection_order"}
_CASE_KINDS = {"default", "recommended", "from_mapping", "merge"}
_CASE_IDENTIFIERS = {
    "default",
    "recommended",
    "field-collapse_duplicates",
    "field-near_duplicate_threshold",
    "field-shingle_size",
    "field-selection_order",
    "field-diversity",
    "field-split_identifiers",
    "field-query_expansion",
    "field-expansion_terms",
    "field-feedback_documents",
    "field-expansion_weight",
    "field-salience_weight",
    "field-salience_damping",
    "field-salience_iterations",
    "field-compact_fallback",
    "field-chunk_tokens",
    "field-rollup_share",
    "field-carry_over_bonus",
    "mapping-all-fields",
    "ranking-active-split",
    "ranking-active-query",
    "ranking-active-salience",
    "ranking-active-carry",
    "ranking-neutral-diversity",
    "unit-low",
    "unit-high",
    "unit-low-invalid",
    "unit-high-invalid",
    "rollup-low",
    "rollup-high",
    "rollup-mid",
    "weight-zero",
    "weight-negative",
    "count-zero",
    "count-negative",
    "positive-one",
    "positive-zero",
    "type-bool",
    "type-int",
    "type-number",
    "type-string",
    "type-null",
    "type-array",
    "type-object",
    "selection-order-invalid",
    "unknown",
    "unknown-null",
    "merge-empty",
    "merge-null-known",
    "merge-null-unknown",
    "merge-same",
    "merge-valid",
    "merge-invalid",
    "merge-invalid-base",
    "negative-zero",
    "int64-max",
    "native-overflow-shingle",
}
_NATIVE_OVERFLOW = 9_223_372_036_854_775_808


@dataclass(frozen=True)
class _Run(ObserverRun):
    """Observer run with domain information indexed from frozen input."""

    domains: dict[str, str]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_keys(value: dict[str, Any], keys: set[str], where: str) -> None:
    if set(value) != keys:
        fail(f"{where} keys must be exactly {sorted(keys)!r}")


def _integer(value: Any, where: str) -> None:
    if type(value) is not int:
        fail(f"{where} must be a decoded JSON integer")


def _boolean(value: Any, where: str) -> None:
    if type(value) is not bool:
        fail(f"{where} must be a decoded JSON boolean")


def _finite_number(value: Any, where: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        fail(f"{where} must be a finite JSON number")


def _validate_mapping(mapping: Any, where: str, *, native_range: bool) -> None:
    if not isinstance(mapping, dict):
        fail(f"{where} must be an object")
    _require_keys(mapping, SETTING_FIELDS, where)
    for field in BOOL_FIELDS:
        _boolean(mapping[field], f"{where}.{field}")
    for field in COUNT_FIELDS:
        _integer(mapping[field], f"{where}.{field}")
        if not native_range and not -(2**63) <= mapping[field] <= 2**63 - 1:
            fail(f"{where}.{field} is outside Int64 range")
    if type(mapping["selection_order"]) is not str:
        fail(f"{where}.selection_order must be a string")
    for field in FLOAT_FIELDS:
        _finite_number(mapping[field], f"{where}.{field}")


def validate_input(document: dict[str, Any]) -> tuple[Case, ...]:
    """Validate the closed input-only profile without consulting SDK outcomes."""
    if not isinstance(document, dict):
        fail("input document must be an object")
    _require_keys(document, {"profile", "format_version", "cases"}, "input document")
    if document["profile"] != PROFILE:
        fail(f"input profile must be {PROFILE!r}")
    _integer(document["format_version"], "input format_version")
    if document["format_version"] != 1:
        fail("input format_version must be 1")
    if not isinstance(document["cases"], list):
        fail("input cases must be an array")
    cases: list[Case] = []
    identifiers: set[str] = set()
    domains = {"shared": 0, "native_range": 0}
    for raw in document["cases"]:
        if not isinstance(raw, dict):
            fail("input case must be an object")
        identifier, kind, domain = raw.get("id"), raw.get("kind"), raw.get("domain")
        if type(identifier) is not str or not identifier or identifier in identifiers:
            fail("input case IDs must be nonempty and unique")
        if kind not in _CASE_KINDS or domain not in domains:
            fail(f"input case {identifier!r} has invalid kind or domain")
        required = {"id", "kind", "domain"}
        if kind in {"from_mapping", "merge"}:
            required.add("values")
        if kind == "merge":
            required.add("base")
        _require_keys(raw, required, f"input case {identifier!r}")
        if kind in {"from_mapping", "merge"} and not isinstance(raw["values"], dict):
            fail(f"input case {identifier!r}.values must be an object")
        if kind == "merge" and not isinstance(raw["base"], dict):
            fail(f"input case {identifier!r}.base must be an object")
        identifiers.add(identifier)
        domains[domain] += 1
        cases.append(Case(identifier, kind, raw))
    if (
        len(cases) != 58
        or identifiers != _CASE_IDENTIFIERS
        or domains != {"shared": 57, "native_range": 1}
    ):
        fail("input must contain exactly 58 cases: 57 shared and one native_range")
    boundary = next((case for case in cases if case.raw["domain"] == "native_range"), None)
    if boundary is None or boundary.identifier != "native-overflow-shingle":
        fail("native_range case must be native-overflow-shingle")
    return tuple(cases)


def load_profile(path: Path) -> tuple[dict[str, Any], tuple[Case, ...]]:
    """Load strict raw JSON and reject any non-frozen input path or bytes."""
    if path.resolve() != DEFAULT_INPUT.resolve():
        fail("only the byte-identical frozen input corpus is permitted")
    if _sha(path) != FROZEN_CORPUS_SHA256:
        fail("input corpus SHA-256 differs from the frozen asset")
    document = read_json_bytes(path)
    if not isinstance(document, dict):
        fail("input document must be an object")
    return document, validate_input(document)


def validate_observation(
    record: dict[str, Any], where: str = "record", *, native_range: bool = False
) -> None:
    """Validate one observed public representation, never an expected SDK outcome."""
    _require_keys(record, {"id", "kind", "public"}, where)
    if type(record["id"]) is not str or record["kind"] not in _CASE_KINDS:
        fail(f"{where} has invalid id or kind")
    public = record["public"]
    if not isinstance(public, dict):
        fail(f"{where}.public must be an object")
    if set(public) == {"error"}:
        error = public["error"]
        if not isinstance(error, dict):
            fail(f"{where}.public.error must be an object")
        _require_keys(error, {"type", "stage"}, f"{where}.public.error")
        if type(error["type"]) is not str or error["stage"] not in {"base", "operation"}:
            fail(f"{where}.public.error has invalid type or stage")
        if error["stage"] == "base" and record["id"] != "merge-invalid-base":
            fail(f"{where}.public.error base stage is only valid for merge-invalid-base")
        return
    keys = {
        "mapping",
        "round_trip",
        "ranking_is_default",
        "negative_zero_fields",
        "reused_instance",
        "base_after",
        "constants",
    }
    _require_keys(public, keys, f"{where}.public")
    _validate_mapping(public["mapping"], f"{where}.public.mapping", native_range=native_range)
    _validate_mapping(
        public["round_trip"], f"{where}.public.round_trip", native_range=native_range
    )
    _boolean(public["ranking_is_default"], f"{where}.public.ranking_is_default")
    zeros = public["negative_zero_fields"]
    if (
        not isinstance(zeros, list)
        or zeros != sorted(set(zeros))
        or any(item not in FLOAT_FIELDS for item in zeros)
    ):
        fail(f"{where}.public.negative_zero_fields must be an ordinal unique float-key list")
    negative_fields = [
        field
        for field in sorted(FLOAT_FIELDS)
        if type(public["mapping"][field]) is float
        and public["mapping"][field] == 0
        and math.copysign(1.0, public["mapping"][field]) < 0
    ]
    if zeros != negative_fields:
        fail(f"{where}.public.negative_zero_fields does not reflect mapping signed zeros")
    for field in FLOAT_FIELDS:
        mapped, round_tripped = public["mapping"][field], public["round_trip"][field]
        if (
            mapped == 0
            and round_tripped == 0
            and math.copysign(1.0, mapped) != math.copysign(1.0, round_tripped)
        ):
            fail(f"{where}.public.round_trip.{field} does not preserve the signed-zero bit")
    constants = public["constants"]
    if not isinstance(constants, dict):
        fail(f"{where}.public.constants must be an object")
    _require_keys(
        constants, {"default_chunk_tokens", "selection_orders"}, f"{where}.public.constants"
    )
    _integer(constants["default_chunk_tokens"], f"{where}.public.constants.default_chunk_tokens")
    if not isinstance(constants["selection_orders"], list) or any(
        type(item) is not str for item in constants["selection_orders"]
    ):
        fail(f"{where}.public.constants.selection_orders must be a string array")
    if record["kind"] == "merge":
        _boolean(public["reused_instance"], f"{where}.public.reused_instance")
        _validate_mapping(public["base_after"], f"{where}.public.base_after", native_range=False)
    elif public["reused_instance"] is not None or public["base_after"] is not None:
        fail(f"{where}.public non-merge records require null identity and base snapshots")


def read_run(
    path: Path, *, cases: Sequence[Case], expected_runtime: str, expected_corpus_sha256: str
) -> ObserverRun:
    """Read a complete observer run and validate its infrastructure and public values."""
    source = read_json_bytes(path)
    if not isinstance(source, dict):
        fail(f"{path} must contain an object")
    _require_keys(
        source,
        {"profile", "runtime", "source_revision", "source_dirty", "corpus_sha256", "observations"},
        str(path),
    )
    if source["profile"] != PROFILE or source["runtime"] != expected_runtime:
        fail(f"{path} has incorrect profile or runtime")
    if (
        type(source["source_revision"]) is not str
        or re.fullmatch(r"[0-9a-f]{40}", source["source_revision"]) is None
        or type(source["source_dirty"]) is not bool
        or source["corpus_sha256"] != expected_corpus_sha256
    ):
        fail(f"{path} has invalid provenance")
    expected = {case.identifier: case for case in cases}
    observed: dict[str, dict[str, Any]] = {}
    if not isinstance(source["observations"], list):
        fail(f"{path} observations must be an array")
    for record in source["observations"]:
        if not isinstance(record, dict):
            fail(f"{path} has non-object observation")
        identifier = record["id"]
        native_range = (
            identifier in expected and expected[identifier].raw["domain"] == "native_range"
        )
        validate_observation(record, str(path), native_range=native_range)
        if (
            identifier in observed
            or identifier not in expected
            or record["kind"] != expected[identifier].kind
        ):
            fail(f"{path} has duplicate, unknown, or wrong-kind observation")
        observed[identifier] = record
    if set(observed) != set(expected):
        fail(f"{path} does not cover the frozen case set")
    boundary = observed["native-overflow-shingle"]["public"]
    if expected_runtime == "python":
        if set(boundary) == {"error"}:
            fail(f"{path} Python native-range boundary must be a success")
        for field in ("mapping", "round_trip"):
            if boundary[field]["shingle_size"] != _NATIVE_OVERFLOW:
                fail(f"{path} Python native-range boundary must retain oversized shingle_size")
    elif set(boundary) != {"error"} or boundary["error"] != {
        "type": "ArgumentException",
        "stage": "operation",
    }:
        fail(f"{path} C# native-range boundary must be ArgumentException at operation")
    return ObserverRun(
        expected_runtime,
        source["source_revision"],
        source["source_dirty"],
        source["corpus_sha256"],
        observed,
    )


def _equal(left: Any, right: Any, path: tuple[str, ...] = ()) -> bool:
    if (
        path
        and path[-1] in FLOAT_FIELDS
        and type(left) in (int, float)
        and type(right) in (int, float)
    ):
        if not (math.isfinite(left) and math.isfinite(right) and left == right):
            return False
        return left != 0 or math.copysign(1.0, left) == math.copysign(1.0, right)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(_equal(left[k], right[k], (*path, k)) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _equal(a, b, path) for a, b in zip(left, right, strict=True)
        )
    return left == right


def compare_observations(
    python_run: ObserverRun, native_run: ObserverRun, cases: Sequence[Case]
) -> dict[str, Any]:
    """Compare only public observations; native-range evidence is reported separately."""
    validate_handshake(python_run, native_run)
    domains = {case.identifier: case.raw["domain"] for case in cases}
    matched: list[str] = []
    mismatches: list[dict[str, str]] = []
    native_only: list[dict[str, Any]] = []
    for case in cases:
        py, cs = python_run.observations[case.identifier], native_run.observations[case.identifier]
        if domains[case.identifier] == "native_range":
            native_only.append(
                {"id": case.identifier, "python": py["public"], "csharp": cs["public"]}
            )
            continue
        ppub, cpub = py["public"], cs["public"]
        if set(ppub) == {"error"} and set(cpub) == {"error"}:
            allowed = {"ArgumentException", "ArgumentOutOfRangeException"}
            ok = (
                ppub["error"]["type"] == "ValueError"
                and cpub["error"]["type"] in allowed
                and ppub["error"]["stage"] == cpub["error"]["stage"]
            )
        else:
            ok = _equal(ppub, cpub)
        if ok:
            matched.append(case.identifier)
        else:
            mismatches.append(
                {
                    "case": case.identifier,
                    "path": "public",
                    "reason": "observed public values differ",
                }
            )
    return {
        "profile": PROFILE,
        "status": "passed" if not mismatches else "failed",
        "matched": matched,
        "mismatches": mismatches,
        "native_only": native_only,
    }


def _frozen_assets() -> None:
    for path, digest in (
        (DEFAULT_INPUT, FROZEN_CORPUS_SHA256),
        (DEFAULT_SCHEMA, FROZEN_SCHEMA_SHA256),
        (DEFAULT_OBSERVATION_SCHEMA, FROZEN_OBSERVATION_SCHEMA_SHA256),
        (FIXTURE_ROOT / "README.md", FROZEN_README_SHA256),
    ):
        if _sha(path) != digest:
            fail(f"frozen asset hash differs: {path}")
    Draft202012Validator.check_schema(read_json_bytes(DEFAULT_SCHEMA))
    Draft202012Validator.check_schema(read_json_bytes(DEFAULT_OBSERVATION_SCHEMA))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the independently authored observers and qualify their raw evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=ROOT / ".tmp-tests" / "context-tuning")
    args = parser.parse_args(argv)
    try:
        _frozen_assets()
        document, cases = load_profile(args.input)
        Draft202012Validator(read_json_bytes(DEFAULT_SCHEMA)).validate(document)
        revision, dirty = source_identity()
        directory = fresh_run_directory(args.output_root)
        config = RunnerConfig(
            ROOT / "scripts" / "observe_python_context_tuning.py",
            "AnyInfer.ContextTuning",
            "AnyInfer.ContextTuning/AnyInfer.ContextTuning.csproj",
            "ContextTuningSourceDirty",
        )
        py_path, cs_path = run_observers(
            config,
            args.input,
            directory,
            source_revision=revision,
            source_dirty=dirty,
            run=lambda command, cwd: subprocess.run(command, cwd=cwd, check=True),
        )
        py_run = read_run(
            py_path,
            cases=cases,
            expected_runtime="python",
            expected_corpus_sha256=corpus_sha256(args.input),
        )
        cs_run = read_run(
            cs_path,
            cases=cases,
            expected_runtime="csharp",
            expected_corpus_sha256=corpus_sha256(args.input),
        )
        validate_handshake(py_run, cs_run, stamped_identity=(revision, dirty))
        result = compare_observations(py_run, cs_run, cases)
        (directory / "result.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        return 0 if result["status"] == "passed" else 1
    except ObservationError as error:
        print(f"context-tuning qualification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
