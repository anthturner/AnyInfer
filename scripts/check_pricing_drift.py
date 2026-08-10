"""Deterministic multi-source pricing drift check.

The checker detects possible drift and never edits pricing data. Direct provider catalogs
are stronger evidence than OpenRouter's secondary signal, but a contributor still verifies
the provider's current human-readable pricing documentation before changing a rate or date.

Exit codes: 0 complete/no drift, 1 complete/drift, 2 incomplete or invalid.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pricing_check import (
    SOURCES,
    DriftFinding,
    SourceResult,
    build_report,
    compare_rates,
    failed_findings,
    load_bundled,
    render_json,
    render_text,
    selected_rates,
    validate_policies,
)
from pricing_fetch import fetch_json

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICING_PATH = REPO_ROOT / "src" / "anyinfer" / "capabilities" / "pricing.json"


def _checked_at() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_check(
    *,
    source_names: Sequence[str],
    fetcher: Callable[[str], Mapping[str, Any]] = fetch_json,
    checked_at: str | None = None,
    pricing_path: Path = PRICING_PATH,
) -> tuple[dict[str, Any], int]:
    """Run enabled sources and return the report plus the documented exit code."""
    data = json.loads(pricing_path.read_text(encoding="utf-8"), parse_float=str)
    rates = load_bundled(data)
    policy_problems = validate_policies(rates)
    if policy_problems:
        raise ValueError("; ".join(policy_problems))

    findings: list[DriftFinding] = []
    results: list[SourceResult] = []
    for source_name in source_names:
        source = SOURCES[source_name]
        selected = selected_rates(rates, source_name)
        try:
            observations = source.parser(fetcher(source.url))
            if selected and not observations:
                raise ValueError("source schema yielded no comparable observations")
        except Exception as error:  # noqa: BLE001 - every source failure is report data
            reason = f"{type(error).__name__}: {error}"
            results.append(
                SourceResult(
                    source_name, source.authority, source.url, len(selected), 0, False, reason
                )
            )
            findings.extend(failed_findings(selected, checker=source_name, reason=reason))
            continue
        results.append(
            SourceResult(
                source_name,
                source.authority,
                source.url,
                len(selected),
                len(observations),
                True,
            )
        )
        findings.extend(compare_rates(selected, observations, checker=source_name))

    report = build_report(
        checked_at=checked_at or _checked_at(),
        all_rates=rates,
        findings=findings,
        source_results=results,
    )
    if report["summary"]["source_failures"]:
        return report, 2
    if report["summary"]["drift"]:
        return report, 1
    return report, 0


def _write_github_output(drifted: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:  # noqa: PTH123
            handle.write(f"drift={'true' if drifted else 'false'}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="write the versioned JSON report here")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--live-source",
        action="append",
        choices=tuple(SOURCES),
        dest="sources",
        help="run only this source (repeatable); default runs every public source",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = _parser().parse_args(argv)
    source_names = args.sources or list(SOURCES)
    try:
        report, exit_code = run_check(source_names=source_names)
        report_text = render_json(report)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(report_text, encoding="utf-8")
        sys.stdout.write(report_text if args.format == "json" else render_text(report))
    except Exception as error:  # noqa: BLE001 - validation/report failures are exit 2
        print(f"CHECK FAILED: {error}", file=sys.stderr)
        _write_github_output(False)
        return 2
    _write_github_output(exit_code == 1)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
