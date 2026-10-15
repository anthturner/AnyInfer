"""End-to-end development observations for every core-generation fixture."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from .comparison import compare_fixture
from .runner import run_fixture

ROOT = Path(__file__).parents[3]
FIXTURES = tuple(sorted((ROOT / "specification/fixtures/core-generation").rglob("*.json")))
EXTENSIONS = (
    "schema.ref",
    "schema.combinators",
    "schema.other_dialects",
    "schema.boolean_subschema",
    "schema.unknown_keywords_ignored",
    "messages.tool_role",
    "targets.alias",
    "messages.non_text_parts",
)

assert FIXTURES, "the canonical core-generation fixture discovery must not be empty"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.relative_to(ROOT).as_posix())
async def test_native_execution_retains_pending_or_extension_observations(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    run = await run_fixture(fixture)

    assert run.error_stage != "harness", fixture["id"]
    if run.requests:
        assert len(run.operations) == 1, fixture["id"]
        assert run.operations[0].evidence_available, fixture["id"]
    else:
        assert all(operation.evidence_available for operation in run.operations), fixture["id"]

    observed = compare_fixture(fixture, run, extensions=EXTENSIONS)
    extension = fixture.get("extension")
    if extension is not None:
        assert extension in EXTENSIONS, fixture["id"]
        assert observed["verdict"] == "extension", observed
        _assert_extension_evidence(observed["evidence"])
        return

    expected = fixture["expected"]
    assert expected["status"] == "to_be_observed", fixture["id"]
    assert observed["verdict"] is None, observed


def _assert_extension_evidence(evidence: Any) -> None:
    assert isinstance(evidence, Mapping)
    assert set(evidence) == {"native_outcome", "adapter_entries"}
    outcome = evidence["native_outcome"]
    entries = evidence["adapter_entries"]
    assert isinstance(outcome, Mapping) and len(outcome) == 1
    assert isinstance(entries, list)
    if set(outcome) == {"error"}:
        assert isinstance(outcome["error"], Mapping)
        assert set(outcome["error"]) == {"category", "native_type", "message"}
    elif set(outcome) == {"result"}:
        assert isinstance(outcome["result"], Mapping)
    else:
        assert outcome == {"none": True}
    for ordinal, entry in enumerate(entries):
        assert isinstance(entry, Mapping)
        assert set(entry) == {
            "entry_ordinal",
            "model",
            "role",
            "timeout_s",
            "max_response_bytes",
        }
        assert entry["entry_ordinal"] == ordinal
