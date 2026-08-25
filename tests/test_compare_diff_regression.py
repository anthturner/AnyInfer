"""CI regression guard: this repo's own illustrative fixtures must not silently drift.

Exercises the portability diff tool end to end against real provider descriptors (no
credentials are ever used — `compare()` never dispatches) and fails the moment a code
change alters what a fixed request becomes on a fixed target, unnoticed.
"""

from __future__ import annotations

import json
from pathlib import Path

from anyinfer import Client, ProviderSettings
from anyinfer.evaluate import compare_diff

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "compare-diff"


def _client() -> Client:
    return Client(
        [
            ProviderSettings.of("openai", api_key="sk-illustrative-only-not-a-real-key"),
            ProviderSettings.of("anthropic", api_key="sk-illustrative-only-not-a-real-key"),
            ProviderSettings.of("ollama"),
        ]
    )


def test_illustrative_fixtures_match_the_checked_in_baseline() -> None:
    fixtures = compare_diff.load_fixtures(FIXTURES_DIR / "fixtures.json")
    baseline = json.loads((FIXTURES_DIR / "baseline.snapshot.json").read_text(encoding="utf-8"))

    client = _client()
    try:
        current = compare_diff.snapshot(fixtures, client=client)
    finally:
        client.close()

    report = compare_diff.diff(baseline, current)
    assert report.is_empty, (
        "compare() output drifted for the checked-in illustrative fixtures — this is "
        "either a real regression or an intentional change that needs a regenerated "
        "baseline (see fixtures/compare-diff/README.md):\n" + compare_diff.render_text(report)
    )


def test_illustrative_fixtures_all_resolve() -> None:
    """The baseline itself should show every target resolvable — an unresolvable one
    would mean this fixture set stopped being illustrative (a typo'd target id, a
    provider rename) without anyone noticing.
    """  # noqa: D205
    fixtures = compare_diff.load_fixtures(FIXTURES_DIR / "fixtures.json")
    client = _client()
    try:
        result = compare_diff.snapshot(fixtures, client=client)
    finally:
        client.close()

    unresolvable = [
        f"{fixture_id}/{target}"
        for fixture_id, targets in result["fixtures"].items()
        for target, comparison in targets.items()
        if not comparison["resolvable"]
    ]
    assert not unresolvable, f"unexpectedly unresolvable: {unresolvable}"
