"""Observe the frozen context-tuning corpus through public Python settings APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

from _csharp_observation import read_json_bytes, require_mapping
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "python"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "context-tuning-v1"
PROFILE = "context-tuning-v1"

if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from anyinfer.context.settings import (  # noqa: E402
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_TUNING,
    SELECTION_ORDERS,
    ContextTuning,
)


def _read_schema() -> dict[str, Any]:
    """Read the frozen input schema through the strict shared JSON reader."""
    return require_mapping(read_json_bytes(FIXTURE_ROOT / "schema.json"), "input schema")


def _read_observation_schema() -> dict[str, Any]:
    """Read the frozen observation schema through the strict shared JSON reader."""
    return require_mapping(
        read_json_bytes(FIXTURE_ROOT / "observations.schema.json"), "observation schema"
    )


def _admit_corpus(input_path: Path) -> tuple[dict[str, Any], str]:
    """Admit strict frozen-profile infrastructure without interpreting setting values."""
    raw = input_path.read_bytes()
    corpus = require_mapping(read_json_bytes(input_path), "input envelope")
    schema = _read_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(corpus)
    if corpus.get("profile") != PROFILE:
        raise ValueError(f"unexpected profile; expected {PROFILE!r}")
    if type(corpus.get("format_version")) is not int or corpus["format_version"] != 1:
        raise ValueError("context-tuning format_version must be the integer 1")
    return corpus, hashlib.sha256(raw).hexdigest()


def _source_provenance(corpus_sha256: str) -> dict[str, Any]:
    """Stamp evidence with the exact checkout and imported public SDK source."""
    expected = SOURCE.resolve()
    module_path = Path(ContextTuning.__module__.replace(".", "/"))
    loaded = Path(sys.modules[ContextTuning.__module__].__file__ or "").resolve()
    if not loaded.is_relative_to(expected) or loaded.name != f"{module_path.name}.py":
        raise RuntimeError(f"ContextTuning import escaped selected checkout: {loaded}")
    top = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if Path(top).resolve() != ROOT:
        raise RuntimeError(f"Git selected a different checkout: {top}")
    revision = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise RuntimeError(f"unexpected Git HEAD revision: {revision!r}")
    dirty = bool(
        subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {
        "profile": PROFILE,
        "runtime": "python",
        "source_revision": revision,
        "source_dirty": dirty,
        "corpus_sha256": corpus_sha256,
    }


def _negative_zero_fields(mapping: dict[str, Any]) -> list[str]:
    """Report signs preserved by the actual public mapping, in ordinal field order."""
    return sorted(
        name
        for name, value in mapping.items()
        if isinstance(value, float) and value == 0.0 and math.copysign(1.0, value) < 0.0
    )


def _success(tuning: ContextTuning, *, base: ContextTuning | None) -> dict[str, Any]:
    """Project public state without recreating defaults or validation logic."""
    mapping = tuning.to_mapping()
    return {
        "mapping": mapping,
        "round_trip": ContextTuning.from_mapping(mapping).to_mapping(),
        "ranking_is_default": tuning.ranking_is_default,
        "negative_zero_fields": _negative_zero_fields(mapping),
        "reused_instance": tuning is base if base is not None else None,
        "base_after": base.to_mapping() if base is not None else None,
        "constants": {
            "default_chunk_tokens": DEFAULT_CHUNK_TOKENS,
            "selection_orders": list(SELECTION_ORDERS),
        },
    }


def _observe_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run one literal operand through the corresponding public settings call."""
    kind = case["kind"]
    try:
        if kind == "default":
            tuning = DEFAULT_TUNING
            base = None
        elif kind == "recommended":
            tuning = ContextTuning.recommended()
            base = None
        elif kind == "from_mapping":
            tuning = ContextTuning.from_mapping(case["values"])
            base = None
        elif kind == "merge":
            try:
                base = ContextTuning.from_mapping(case["base"])
            except (TypeError, ValueError) as error:
                return _error(case, error, stage="base")
            tuning = base.merged(**case["values"])
        else:
            raise RuntimeError(f"unsupported frozen operation kind: {kind!r}")
    except (TypeError, ValueError) as error:
        return _error(case, error, stage="operation")
    return {"id": case["id"], "kind": kind, "public": _success(tuning, base=base)}


def _error(case: dict[str, Any], error: Exception, *, stage: str) -> dict[str, Any]:
    """Record an unmodified public exception type and the operation boundary."""
    return {
        "id": case["id"],
        "kind": case["kind"],
        "public": {"error": {"type": type(error).__name__, "stage": stage}},
    }


def observe(input_path: Path, output_path: Path) -> dict[str, Any]:
    """Observe all frozen literal cases and write schema-valid public evidence."""
    corpus, digest = _admit_corpus(input_path)
    output = {
        **_source_provenance(digest),
        "observations": [_observe_case(case) for case in corpus["cases"]],
    }
    schema = _read_observation_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return output


def main() -> None:
    """Parse the released observer CLI contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observe", nargs=2, metavar=("INPUT", "OUTPUT"), required=True)
    input_name, output_name = parser.parse_args().observe
    observe(Path(input_name), Path(output_name))


if __name__ == "__main__":
    main()
