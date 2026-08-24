"""Offline tests for the contract-snapshot drift selection tooling.

The script itself never reads provider documentation; it decides *which* snapshots the
expensive reasoning pass should read. These tests pin that decision, because a selector
that quietly drops snapshots produces a rotation nobody notices is incomplete.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_contract_drift as cli  # noqa: E402
import validate_contracts  # noqa: E402

TODAY = dt.date(2026, 8, 24)


class TestParsing:
    """Reading a snapshot's own claims about when and against what it was verified."""

    def test_qualified_dates_are_read_and_the_earliest_wins(self) -> None:
        """A snapshot is only as fresh as its stalest section."""
        text = "Last verified: chat 2026-08-07; embeddings and rerank 2026-08-12\n"
        assert cli.last_verified(text) == dt.date(2026, 8, 7)

    def test_a_snapshot_without_a_date_reads_as_none(self) -> None:
        assert cli.last_verified("# provider — Protocol Contract\n") is None

    def test_only_the_upstream_sources_section_counts(self) -> None:
        """Inline citations elsewhere are context for a reader, not verification sources."""
        text = (
            "## Upstream sources\n"
            "- https://example.test/api/reference\n"
            "- https://example.test/api/changelog\n"
            "\n"
            "## Wire contract\n"
            "See https://example.test/not-a-source for background.\n"
        )
        assert cli.upstream_sources(text) == [
            "https://example.test/api/reference",
            "https://example.test/api/changelog",
        ]

    def test_a_url_cited_twice_appears_once(self) -> None:
        text = (
            "## Upstream sources\n"
            "- https://example.test/a (generation)\n"
            "- https://example.test/a (embeddings, verified 2026-08-12)\n"
        )
        assert cli.upstream_sources(text) == ["https://example.test/a"]

    def test_trailing_punctuation_is_not_part_of_the_url(self) -> None:
        text = "## Upstream sources\n- https://example.test/a) and `https://example.test/b`\n"
        assert cli.upstream_sources(text) == ["https://example.test/a", "https://example.test/b"]


class TestSelection:
    """Which snapshots a run picks up, and which it says out loud that it deferred."""

    def test_never_live_verified_outranks_a_merely_old_snapshot(self) -> None:
        """A code-survey snapshot was never compared to upstream at all.

        Sorting purely by date would send the audit to snapshots that have at least been
        checked once, and leave the never-checked ones waiting for months.
        """
        report, code = cli.build_report(today=TODAY, budget=4, check_urls=False)
        assert code == 1
        selected = report["selected"]
        assert selected, "the repository's own snapshots should select at least one"
        assert all(e["never_live_verified"] for e in selected), (
            "ten snapshots say they were never live-verified; those come first"
        )

    def test_the_budget_bounds_the_run_and_names_what_it_deferred(self) -> None:
        """A check that silently audits three of twenty-two reads as 'we checked'."""
        report, _ = cli.build_report(today=TODAY, budget=2, check_urls=False)
        assert report["totals"]["selected"] == 2
        assert report["totals"]["deferred"] == report["totals"]["due"] - 2
        assert len(report["deferred"]) == report["totals"]["deferred"]
        assert not set(report["deferred"]) & {e["provider"] for e in report["selected"]}

    def test_every_snapshot_is_accounted_for_exactly_once(self) -> None:
        """Selected, deferred, and fresh must partition the snapshot set."""
        report, _ = cli.build_report(today=TODAY, budget=3, check_urls=False)
        seen = (
            [e["provider"] for e in report["selected"]] + report["deferred"] + report["fresh"]
        )
        assert len(seen) == report["totals"]["snapshots"]
        assert len(set(seen)) == len(seen), "a snapshot appeared in two buckets"

    def test_nothing_due_exits_zero(self) -> None:
        """No work is a clean run, not a failure."""
        report, code = cli.build_report(
            today=dt.date(2026, 8, 24), budget=0, max_age_days=10_000, check_urls=False
        )
        assert code == 0
        assert report["selected"] == []

    def test_procedure_documents_are_not_audited_as_snapshots(self) -> None:
        """NEW-PROVIDER.md and its siblings describe process, not a provider's wire."""
        names = {p.name for p in validate_contracts.snapshots()}
        assert not names & {
            "README.md",
            "TEMPLATE.md",
            "DRIFT-CHECK.md",
            "NEW-PROVIDER.md",
            "openai-compat-presets.md",
        }


class TestUrlChecks:
    """What a status code is allowed to prove."""

    def test_a_404_is_a_finding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import urllib.error

        def fail(*_args: object, **_kwargs: object) -> object:
            raise urllib.error.HTTPError("https://example.test/gone", 404, "Not Found", {}, None)  # type: ignore[arg-type]

        monkeypatch.setattr(cli.urllib.request, "urlopen", fail)
        assert cli.check_url("https://example.test/gone")["reachable"] is False

    def test_a_transport_failure_is_not_a_finding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Treating a flaky network as drift sends the expensive pass chasing nothing."""
        import urllib.error

        def fail(*_args: object, **_kwargs: object) -> object:
            raise urllib.error.URLError("connection reset")

        monkeypatch.setattr(cli.urllib.request, "urlopen", fail)
        result = cli.check_url("https://example.test/flaky")
        assert result["reachable"] is True
        assert "unverifiable" in result

    def test_a_200_reports_reachability_and_claims_nothing_about_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The checker deliberately proves reachability only.

        Documentation pages are client-rendered and change on every deploy, so a content
        diff would be noise. Judging content is the reasoning pass's job, and a report
        field implying otherwise would invite the audit to trust a page it never read.
        """

        class _Response:
            status = 200

            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        monkeypatch.setattr(cli.urllib.request, "urlopen", lambda *a, **k: _Response())
        result = cli.check_url("https://example.test/ok")
        assert result == {"url": "https://example.test/ok", "status": 200, "reachable": True}


class TestReportShape:
    """The report is the reasoning pass's only input, so its contract is load-bearing."""

    def test_the_report_carries_its_policy_and_a_format_version(self) -> None:
        report, _ = cli.build_report(today=TODAY, budget=1, check_urls=False)
        assert report["format_version"] == 1
        assert report["policy"] == {"max_age_days": 90, "budget": 1}
        assert report["checked_at"] == TODAY.isoformat()

    def test_each_selected_entry_carries_a_path_and_a_stated_reason(self) -> None:
        report, _ = cli.build_report(today=TODAY, budget=2, check_urls=False)
        for entry in report["selected"]:
            assert (ROOT / entry["path"]).is_file()
            assert entry["reason"]
            assert entry["sources"], "an auditable snapshot cites what it was verified against"

    def test_text_rendering_names_the_deferred_providers(self) -> None:
        report, _ = cli.build_report(today=TODAY, budget=1, check_urls=False)
        rendered = cli.render_text(report)
        assert "Deferred to a later run" in rendered
        for provider in report["deferred"]:
            assert provider in rendered
