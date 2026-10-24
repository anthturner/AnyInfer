"""Pure contract controls for the development-only context-tuning-v1 corpus."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "context-tuning-v1"
_INPUTS_PATH = _FIXTURE_ROOT / "inputs.json"
_INPUT_SCHEMA_PATH = _FIXTURE_ROOT / "schema.json"
_OBSERVATION_SCHEMA_PATH = _FIXTURE_ROOT / "observations.schema.json"
_FIELDS = (
    "collapse_duplicates",
    "near_duplicate_threshold",
    "shingle_size",
    "selection_order",
    "diversity",
    "split_identifiers",
    "query_expansion",
    "expansion_terms",
    "feedback_documents",
    "expansion_weight",
    "salience_weight",
    "salience_damping",
    "salience_iterations",
    "compact_fallback",
    "chunk_tokens",
    "rollup_share",
    "carry_over_bonus",
)
_CASES = (
    ("default", "default", "shared"),
    ("recommended", "recommended", "shared"),
    ("field-collapse_duplicates", "from_mapping", "shared"),
    ("field-near_duplicate_threshold", "from_mapping", "shared"),
    ("field-shingle_size", "from_mapping", "shared"),
    ("field-selection_order", "from_mapping", "shared"),
    ("field-diversity", "from_mapping", "shared"),
    ("field-split_identifiers", "from_mapping", "shared"),
    ("field-query_expansion", "from_mapping", "shared"),
    ("field-expansion_terms", "from_mapping", "shared"),
    ("field-feedback_documents", "from_mapping", "shared"),
    ("field-expansion_weight", "from_mapping", "shared"),
    ("field-salience_weight", "from_mapping", "shared"),
    ("field-salience_damping", "from_mapping", "shared"),
    ("field-salience_iterations", "from_mapping", "shared"),
    ("field-compact_fallback", "from_mapping", "shared"),
    ("field-chunk_tokens", "from_mapping", "shared"),
    ("field-rollup_share", "from_mapping", "shared"),
    ("field-carry_over_bonus", "from_mapping", "shared"),
    ("mapping-all-fields", "from_mapping", "shared"),
    ("ranking-active-split", "from_mapping", "shared"),
    ("ranking-active-query", "from_mapping", "shared"),
    ("ranking-active-salience", "from_mapping", "shared"),
    ("ranking-active-carry", "from_mapping", "shared"),
    ("ranking-neutral-diversity", "from_mapping", "shared"),
    ("unit-low", "from_mapping", "shared"),
    ("unit-high", "from_mapping", "shared"),
    ("unit-low-invalid", "from_mapping", "shared"),
    ("unit-high-invalid", "from_mapping", "shared"),
    ("rollup-low", "from_mapping", "shared"),
    ("rollup-high", "from_mapping", "shared"),
    ("rollup-mid", "from_mapping", "shared"),
    ("weight-zero", "from_mapping", "shared"),
    ("weight-negative", "from_mapping", "shared"),
    ("count-zero", "from_mapping", "shared"),
    ("count-negative", "from_mapping", "shared"),
    ("positive-one", "from_mapping", "shared"),
    ("positive-zero", "from_mapping", "shared"),
    ("type-bool", "from_mapping", "shared"),
    ("type-int", "from_mapping", "shared"),
    ("type-number", "from_mapping", "shared"),
    ("type-string", "from_mapping", "shared"),
    ("type-null", "from_mapping", "shared"),
    ("type-array", "from_mapping", "shared"),
    ("type-object", "from_mapping", "shared"),
    ("selection-order-invalid", "from_mapping", "shared"),
    ("unknown", "from_mapping", "shared"),
    ("unknown-null", "from_mapping", "shared"),
    ("merge-empty", "merge", "shared"),
    ("merge-null-known", "merge", "shared"),
    ("merge-null-unknown", "merge", "shared"),
    ("merge-same", "merge", "shared"),
    ("merge-valid", "merge", "shared"),
    ("merge-invalid", "merge", "shared"),
    ("merge-invalid-base", "merge", "shared"),
    ("negative-zero", "from_mapping", "shared"),
    ("int64-max", "from_mapping", "shared"),
    ("native-overflow-shingle", "from_mapping", "native_range"),
)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def inputs() -> dict[str, Any]:
    return _read(_INPUTS_PATH)


@pytest.fixture
def input_schema() -> dict[str, Any]:
    return _read(_INPUT_SCHEMA_PATH)


@pytest.fixture
def observation_schema() -> dict[str, Any]:
    return _read(_OBSERVATION_SCHEMA_PATH)


def _mapping() -> dict[str, Any]:
    return {
        "collapse_duplicates": False,
        "near_duplicate_threshold": 0.1,
        "shingle_size": 2,
        "selection_order": "density",
        "diversity": 0.2,
        "split_identifiers": True,
        "query_expansion": True,
        "expansion_terms": 3,
        "feedback_documents": 4,
        "expansion_weight": 0.5,
        "salience_weight": 0.6,
        "salience_damping": 0.7,
        "salience_iterations": 8,
        "compact_fallback": True,
        "chunk_tokens": 9,
        "rollup_share": 0.8,
        "carry_over_bonus": 0.9,
    }


def _success(*, merge: bool) -> dict[str, Any]:
    mapping = _mapping()
    return {
        "mapping": mapping,
        "round_trip": mapping.copy(),
        "ranking_is_default": False,
        "negative_zero_fields": [],
        "reused_instance": False if merge else None,
        "base_after": mapping.copy() if merge else None,
        "constants": {"default_chunk_tokens": 512, "selection_orders": ["rank", "density"]},
    }


def _envelope(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": "context-tuning-v1",
        "runtime": "python",
        "source_revision": "a" * 40,
        "source_dirty": False,
        "corpus_sha256": "b" * 64,
        "observations": [record],
    }


def test_input_corpus_is_the_exact_closed_58_case_book(inputs: dict[str, Any]) -> None:
    """The input-only fixture preserves ordinal IDs, kinds, domains, and all fields."""
    assert tuple((case["id"], case["kind"], case["domain"]) for case in inputs["cases"]) == _CASES
    assert len(_CASES) == 58
    assert sum(domain == "shared" for _, _, domain in _CASES) == 57
    assert _CASES[-1] == ("native-overflow-shingle", "from_mapping", "native_range")
    all_fields = next(case for case in inputs["cases"] if case["id"] == "mapping-all-fields")
    assert tuple(all_fields["values"]) == _FIELDS
    assert set(all_fields["values"]) == set(_FIELDS)


def test_input_schema_is_valid_and_accepts_the_literal_input_corpus(
    inputs: dict[str, Any], input_schema: dict[str, Any]
) -> None:
    """The corpus is structurally valid without importing or exercising either SDK."""
    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator(input_schema).validate(inputs)


def test_inputs_are_operands_only_not_hidden_sdk_outcomes(inputs: dict[str, Any]) -> None:
    """No case embeds output, exception, default-map, or verdict oracle data."""
    assert set(inputs) == {"profile", "format_version", "cases"}
    for case in inputs["cases"]:
        assert set(case).issubset({"id", "kind", "domain", "values", "base"})
        assert not ({"expected", "error", "output", "result", "defaults"} & set(case))


def test_literal_raw_json_edge_cases_are_retained_and_schema_limited(
    inputs: dict[str, Any], input_schema: dict[str, Any]
) -> None:
    """The profile keeps 1.0 and negative-zero inputs; decoded-type rejection is CTUNE.3 work."""
    cases = {case["id"]: case for case in inputs["cases"]}
    assert type(cases["type-int"]["values"]["chunk_tokens"]) is float
    assert cases["type-int"]["values"]["chunk_tokens"] == 1.0
    assert math.copysign(1.0, cases["negative-zero"]["values"]["diversity"]) == -1.0
    Draft202012Validator(input_schema).validate(inputs)


def test_observation_schema_accepts_success_merge_nonmerge_and_error_witnesses(
    observation_schema: dict[str, Any],
) -> None:
    """Synthetic records exercise schema branches only; they are not SDK qualifications."""
    Draft202012Validator.check_schema(observation_schema)
    validator = Draft202012Validator(observation_schema)
    validator.validate(
        _envelope({"id": "default", "kind": "default", "public": _success(merge=False)})
    )
    validator.validate(
        _envelope({"id": "merge-valid", "kind": "merge", "public": _success(merge=True)})
    )
    validator.validate(
        _envelope(
            {
                "id": "merge-invalid",
                "kind": "merge",
                "public": {"error": {"type": "ValueError", "stage": "operation"}},
            }
        )
    )
    validator.validate(
        _envelope(
            {
                "id": "merge-invalid-base",
                "kind": "merge",
                "public": {"error": {"type": "ValueError", "stage": "base"}},
            }
        )
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda record: record.update(extra=True),
        lambda record: record.pop("kind"),
        lambda record: record.update(kind="other"),
        lambda record: record["public"].update(extra=True),
        lambda record: record["public"]["error"].update(stage="other"),
    ),
)
def test_observation_schema_closes_root_record_success_and_error_shapes(
    observation_schema: dict[str, Any], mutate: Any
) -> None:
    """Closed envelopes reject extra/missing keys and unknown error stages."""
    record = {
        "id": "merge-invalid",
        "kind": "merge",
        "public": {"error": {"type": "ValueError", "stage": "operation"}},
    }
    mutate(record)
    assert list(Draft202012Validator(observation_schema).iter_errors(_envelope(record)))


def test_observation_schema_closes_the_root_and_success_identity_base_shapes(
    observation_schema: dict[str, Any],
) -> None:
    """Root closure and success branches preserve merge-only identity/base fields."""
    validator = Draft202012Validator(observation_schema)
    root = _envelope({"id": "default", "kind": "default", "public": _success(merge=False)})
    root["extra"] = True
    assert list(validator.iter_errors(root))

    nonmerge = _success(merge=False)
    nonmerge["reused_instance"] = True
    assert list(
        validator.iter_errors(_envelope({"id": "default", "kind": "default", "public": nonmerge}))
    )
    merge = _success(merge=True)
    merge["base_after"] = None
    assert list(
        validator.iter_errors(_envelope({"id": "merge-valid", "kind": "merge", "public": merge}))
    )


def test_input_schema_allows_the_documented_python_oversized_integer(
    inputs: dict[str, Any], input_schema: dict[str, Any]
) -> None:
    """The native range boundary is valid corpus input, not schema-level rejection."""
    overflow = next(case for case in inputs["cases"] if case["id"] == "native-overflow-shingle")
    assert overflow["values"]["shingle_size"] == 9_223_372_036_854_775_808
    Draft202012Validator(input_schema).validate(
        {"profile": "context-tuning-v1", "format_version": 1, "cases": [overflow]}
    )
