"""The portability diff tool: fixture loading, snapshotting, and structural diffing."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer import compare_diff
from anyinfer.errors import ConfigError
from anyinfer.providers.openai_compat import OpenAICompatAdapter
from anyinfer.registry import ProviderDescriptor, ProviderRegistry


def _registry() -> ProviderRegistry:
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="json-only",
            display_name="JSON only",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            static_capabilities={
                "m": ai.ModelCapabilities(
                    context_window=ai.Sourced(8_192, "catalog"),
                    features=ai.Sourced(ai.Feature.JSON_MODE, "catalog"),
                    pricing=ai.Sourced(ai.Pricing(Decimal("1"), Decimal("2")), "catalog"),
                )
            },
        )
    )
    registry.register(
        ProviderDescriptor(
            id="generation-only",
            display_name="Generation only",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
        )
    )
    return registry


def _client() -> ai.Client:
    return ai.Client(
        [ai.ProviderSettings.of("json-only", base_url="https://unused.invalid/v1")],
        registry=_registry(),
        use_default_catalog=False,
    )


_FIXTURE_DOC = {
    "schema_version": 1,
    "fixtures": [
        {
            "id": "simple",
            "request": {"messages": [{"role": "user", "text": "hello"}]},
            "targets": ["json-only:m", "generation-only:m"],
        }
    ],
}


def _write_fixture_file(tmp_path: Path, doc: object = _FIXTURE_DOC) -> Path:
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ---- load_fixtures ----------------------------------------------------------------------


def test_load_fixtures_parses_a_valid_file(tmp_path: Path) -> None:
    fixtures = compare_diff.load_fixtures(_write_fixture_file(tmp_path))
    assert len(fixtures) == 1
    assert fixtures[0].id == "simple"
    assert fixtures[0].targets == ("json-only:m", "generation-only:m")
    assert fixtures[0].request.messages[0].text == "hello"


def test_load_fixtures_rejects_wrong_schema_version(tmp_path: Path) -> None:
    doc = {**_FIXTURE_DOC, "schema_version": 999}
    with pytest.raises(ConfigError):
        compare_diff.load_fixtures(_write_fixture_file(tmp_path, doc))


def test_load_fixtures_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        compare_diff.load_fixtures(path)


def test_load_fixtures_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        compare_diff.load_fixtures(tmp_path / "nonexistent.json")


def test_load_fixtures_rejects_a_fixture_with_no_targets(tmp_path: Path) -> None:
    doc = {
        "schema_version": 1,
        "fixtures": [
            {
                "id": "bad",
                "request": {"messages": [{"role": "user", "text": "hi"}]},
                "targets": [],
            }
        ],
    }
    with pytest.raises(ConfigError):
        compare_diff.load_fixtures(_write_fixture_file(tmp_path, doc))


def test_load_fixtures_rejects_an_unsupported_message_role(tmp_path: Path) -> None:
    doc = {
        "schema_version": 1,
        "fixtures": [
            {
                "id": "bad",
                "request": {"messages": [{"role": "tool", "text": "hi"}]},
                "targets": ["json-only:m"],
            }
        ],
    }
    with pytest.raises(ConfigError):
        compare_diff.load_fixtures(_write_fixture_file(tmp_path, doc))


# ---- snapshot -----------------------------------------------------------------------------


def test_snapshot_never_dispatches_and_reports_both_targets(tmp_path: Path) -> None:
    fixtures = compare_diff.load_fixtures(_write_fixture_file(tmp_path))
    client = _client()
    try:
        result = compare_diff.snapshot(fixtures, client=client)
    finally:
        client.close()

    assert result["schema_version"] == 1
    assert set(result["fixtures"]["simple"]) == {"json-only:m", "generation-only:m"}
    assert result["fixtures"]["simple"]["json-only:m"]["resolvable"] is True


# ---- diff -----------------------------------------------------------------------------


def test_diff_of_identical_snapshots_is_empty(tmp_path: Path) -> None:
    fixtures = compare_diff.load_fixtures(_write_fixture_file(tmp_path))
    client = _client()
    try:
        snap = compare_diff.snapshot(fixtures, client=client)
    finally:
        client.close()

    report = compare_diff.diff(snap, snap)
    assert report.is_empty
    assert compare_diff.render_text(report) == "no differences"


def test_diff_detects_a_changed_field() -> None:
    baseline = {
        "schema_version": 1,
        "fixtures": {"f": {"t": {"structured_mechanism": "json_mode", "fits": True}}},
    }
    current = {
        "schema_version": 1,
        "fixtures": {"f": {"t": {"structured_mechanism": "json_schema", "fits": True}}},
    }
    report = compare_diff.diff(baseline, current)
    assert not report.is_empty
    assert len(report.entries) == 1
    entry = report.entries[0]
    assert entry.kind == "changed"
    assert entry.field == "structured_mechanism"
    assert entry.before == "json_mode"
    assert entry.after == "json_schema"
    assert "structured_mechanism" in entry.summary


def test_diff_detects_a_target_added_or_removed() -> None:
    baseline = {"schema_version": 1, "fixtures": {"f": {"t1": {"fits": True}}}}
    current = {
        "schema_version": 1,
        "fixtures": {"f": {"t1": {"fits": True}, "t2": {"fits": False}}},
    }
    report = compare_diff.diff(baseline, current)
    assert len(report.entries) == 1
    assert report.entries[0].kind == "added"
    assert report.entries[0].target == "t2"

    reverse = compare_diff.diff(current, baseline)
    assert reverse.entries[0].kind == "removed"
    assert reverse.entries[0].target == "t2"


def test_diff_recurses_into_nested_lists_by_position() -> None:
    baseline = {
        "schema_version": 1,
        "fixtures": {"f": {"t": {"dropped": [{"name": "top_p", "reason": "unsupported"}]}}},
    }
    current = {
        "schema_version": 1,
        "fixtures": {"f": {"t": {"dropped": [{"name": "top_p", "reason": "silently ignored"}]}}},
    }
    report = compare_diff.diff(baseline, current)
    assert len(report.entries) == 1
    assert report.entries[0].field == "dropped.0.reason"


def test_diff_rejects_a_document_with_no_schema_version() -> None:
    with pytest.raises(ConfigError):
        compare_diff.diff({}, {"schema_version": 1, "fixtures": {}})


# ---- diff_targets (ad hoc customer-facing mode) ------------------------------------------


def test_diff_targets_compares_two_targets_live_with_no_baseline_file(tmp_path: Path) -> None:
    fixtures = compare_diff.load_fixtures(_write_fixture_file(tmp_path))
    client = _client()
    try:
        report = compare_diff.diff_targets(
            fixtures[0], "json-only:m", "generation-only:m", client=client
        )
    finally:
        client.close()

    assert not report.is_empty
    fields = {entry.field for entry in report.entries}
    # json-only has priced, capable static capabilities; generation-only has none of that.
    assert "cost" in fields
