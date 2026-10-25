"""Controls for the documentation review ledger at maintenance/documentation/page-coverage.json."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_documentation_coverage import LEDGER, ledger_problems, published_sources

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ledger() -> dict[str, object]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sources() -> list[str]:
    return published_sources(ROOT)


def test_committed_ledger_matches_the_published_source_set(
    ledger: dict[str, object], sources: list[str]
) -> None:
    assert ledger_problems(ledger, sources, ROOT) == []
    rows = ledger["pages"]
    assert isinstance(rows, list)
    assert sorted(row["source"] for row in rows) == sorted(sources)


def test_a_published_page_without_a_row_fails(
    ledger: dict[str, object], sources: list[str]
) -> None:
    mutated = copy.deepcopy(ledger)
    mutated["pages"] = [row for row in mutated["pages"] if row["source"] != "guides/streaming.md"]
    assert "guides/streaming.md: published but missing from the ledger" in ledger_problems(
        mutated, sources, ROOT
    )


def test_duplicate_and_stale_rows_fail(ledger: dict[str, object], sources: list[str]) -> None:
    mutated = copy.deepcopy(ledger)
    row = next(row for row in mutated["pages"] if row["source"] == "guides/fallback.md")
    mutated["pages"].append(copy.deepcopy(row))
    mutated["pages"].append({**copy.deepcopy(row), "source": "guides/retired-page.md"})
    problems = ledger_problems(mutated, sources, ROOT)
    assert "guides/fallback.md: listed 2 times" in problems
    assert "guides/retired-page.md: stale row for a source the site does not publish" in problems


def test_unreviewed_rows_fail_once_review_is_required(
    ledger: dict[str, object], sources: list[str]
) -> None:
    mutated = copy.deepcopy(ledger)
    for row in mutated["pages"]:
        row["review"] = "reviewed"
    for entry in mutated["repository_only"]:
        entry["review"] = "reviewed"
    assert ledger_problems(mutated, sources, ROOT, require_reviewed=True) == []
    mutated["pages"][0]["review"] = "pending"
    assert ledger_problems(mutated, sources, ROOT, require_reviewed=True) == [
        f"{mutated['pages'][0]['source']}: not reviewed"
    ]


def test_missing_or_uncited_evidence_fails(ledger: dict[str, object], sources: list[str]) -> None:
    mutated = copy.deepcopy(ledger)
    row = next(row for row in mutated["pages"] if row["source"] == "guides/streaming.md")
    row["evidence"] = [
        path for path in row["evidence"] if path != "examples/csharp-sdk/StreamingExample.cs"
    ]
    row["evidence"].append("examples/csharp-sdk/NoSuchExample.cs")
    problems = ledger_problems(mutated, sources, ROOT)
    assert (
        "guides/streaming.md: cited evidence examples/csharp-sdk/NoSuchExample.cs does not exist"
        in problems
    )
    assert (
        "guides/streaming.md: includes examples/csharp-sdk/StreamingExample.cs "
        "but does not cite it as evidence"
    ) in problems


def test_invalid_scope_and_repository_entries_fail(
    ledger: dict[str, object], sources: list[str]
) -> None:
    mutated = copy.deepcopy(ledger)
    mutated["pages"][0]["scope"] = "go"
    mutated["repository_only"].append(
        {"path": "docs/guides/streaming.md", "scope": "mixed", "review": "pending", "mirrors": []}
    )
    mutated["exclusions"].append({"path": "NO_SUCH_FILE.md", "reason": ""})
    problems = ledger_problems(mutated, sources, ROOT)
    assert any(
        problem.endswith("scope must be one of ['csharp', 'mixed', 'python', 'shared']")
        for problem in problems
    )
    assert "docs/guides/streaming.md: published page listed as repository-only" in problems
    assert "NO_SUCH_FILE.md: excluded path does not exist" in problems
    assert "NO_SUCH_FILE.md: exclusion needs a reason" in problems
