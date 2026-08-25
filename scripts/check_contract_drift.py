"""Deterministic staleness and reachability check over the contract snapshots.

This is the cheap half of the provider drift check. It never reads a provider's
documentation and never judges whether a snapshot is *correct* — verifying content is
what `contracts/DRIFT-CHECK.md` is for, and it takes a reasoning model with web access.
What this does is decide, deterministically and without credentials, *which* snapshots
that expensive pass should look at this week.

Two signals, both credential-free:

- **Age.** Every snapshot records a real `Last verified` date. A snapshot nobody has
  re-checked in months is not evidence about a live API; it is a claim about one.
- **Reachability.** Every snapshot lists the upstream pages it was verified against. A
  URL that has become a 404 is the strongest cheap signal that a provider reorganized
  its API documentation, which is exactly when wire details move.

Selection is oldest-first and bounded, so a weekly run costs a predictable amount and
every snapshot comes up for audit on a guaranteed rotation rather than whenever someone
remembers. Reporting the rotation is part of the output: a check that silently audits
three of twenty-five reads as "we checked" when it did not.

Exit codes: 0 nothing to audit, 1 snapshots selected for audit, 2 the check itself could
not complete.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from validate_contracts import LAST_VERIFIED, snapshots

ROOT = Path(__file__).resolve().parent.parent

SOURCE_URL = re.compile(r"https?://[^\s<>)\]|`\"']+")
"""URLs as they appear in a snapshot's bullet list of upstream sources."""

DEFAULT_MAX_AGE_DAYS = 90
"""Age past which a snapshot is a claim about an API rather than evidence about one."""

UNVERIFIED = re.compile(
    r"not yet live-verified|not yet verified against live|code survey", re.IGNORECASE
)
"""A snapshot that says, in its own words, that it was never checked against upstream.

This outranks age. A snapshot derived from a code survey last week is *less* trustworthy
than one verified against live documentation three months ago, because nobody has ever
compared it to what the provider actually publishes. Sorting purely by date would send
the expensive pass to the wrong snapshots for months."""

DEFAULT_BUDGET = 4
"""Snapshots audited per run. Bounds the cost of the reasoning pass that follows."""

USER_AGENT = "AnyInfer-contract-drift-check (+https://github.com/anthturner/AnyInfer)"


def upstream_sources(text: str) -> list[str]:
    """Every URL under a snapshot's ``## Upstream sources`` heading.

    Only that section counts. Snapshots cite URLs inline throughout — in rationale
    sections, in watchlist entries — and those are context for a reader, not the pages
    the snapshot was verified against.
    """
    lines = text.splitlines()
    try:
        start = next(
            i for i, line in enumerate(lines) if line.strip().startswith("## Upstream sources")
        )
    except StopIteration:
        return []
    urls: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        urls.extend(SOURCE_URL.findall(line))
    # Preserve document order; a snapshot may cite the same page twice with different
    # verification notes.
    return list(dict.fromkeys(urls))


def last_verified(text: str) -> dt.date | None:
    """The snapshot's own ``Last verified`` date, or ``None`` if it carries none.

    A snapshot may record several dates when its sections were verified separately. The
    earliest is the honest one: the snapshot is only as fresh as its stalest section.
    """
    found = [dt.date.fromisoformat(m) for m in LAST_VERIFIED.findall(text)]
    inline = re.findall(r"verified (\d{4}-\d{2}-\d{2})", text)
    found.extend(dt.date.fromisoformat(value) for value in inline)
    return min(found) if found else None


def check_url(url: str, *, timeout: float = 15.0) -> dict[str, Any]:
    """Fetch one documentation URL, reporting only what a status code can prove.

    A non-404 answer is not evidence the page still documents what the snapshot claims —
    only that something is served there. That distinction is the whole reason this
    script does not try to diff content: documentation pages are rendered by client-side
    frameworks and change on every deploy for reasons that have nothing to do with the
    API. A 404, by contrast, is unambiguous and worth a human's attention.
    """
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"url": url, "status": response.status, "reachable": True}
    except urllib.error.HTTPError as error:
        # An HTTPError *is* a response object -- it subclasses the same wrapper `urlopen`
        # returns -- so it holds the connection until it is closed. Every version leaked
        # it here; 3.14 is the first to say so, warning from the finalizer.
        error.close()
        return {"url": url, "status": error.code, "reachable": error.code != 404}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        # A transport failure is not a finding. Treating a flaky network as drift would
        # send the expensive pass chasing nothing, so it is recorded and ignored.
        return {"url": url, "status": None, "reachable": True, "unverifiable": str(error)[:200]}


def build_report(
    *,
    today: dt.date,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    budget: int = DEFAULT_BUDGET,
    check_urls: bool = True,
) -> tuple[dict[str, Any], int]:
    """Survey every snapshot and select the ones this run should audit."""
    entries: list[dict[str, Any]] = []
    for path in snapshots():
        text = path.read_text(encoding="utf-8")
        verified = last_verified(text)
        if verified is None:
            # validate_contracts.py is the gate for this; here it is a loud finding
            # rather than a crash, so one malformed snapshot cannot stop the rotation.
            entries.append(
                {
                    "provider": path.stem,
                    "path": str(path.relative_to(ROOT)),
                    "last_verified": None,
                    "age_days": None,
                    "reason": "no parseable 'Last verified' date",
                    "sources": [],
                }
            )
            continue
        never_live = bool(UNVERIFIED.search(text))
        entries.append(
            {
                "provider": path.stem,
                "path": str(path.relative_to(ROOT)),
                "last_verified": verified.isoformat(),
                "age_days": (today - verified).days,
                "never_live_verified": never_live,
                "reason": (
                    "never verified against live documentation"
                    if never_live
                    else f"{(today - verified).days} days since last verification"
                ),
                "sources": upstream_sources(text),
            }
        )

    # Priority order: no date at all, then never-live-verified, then oldest first.
    entries.sort(key=lambda e: e["age_days"] or 0, reverse=True)
    entries.sort(key=lambda e: bool(e.get("never_live_verified")), reverse=True)
    entries.sort(key=lambda e: e["age_days"] is None, reverse=True)

    due = [
        e
        for e in entries
        if e["age_days"] is None
        or e.get("never_live_verified")
        or e["age_days"] >= max_age_days
    ]
    selected = due[:budget]

    dead_links: list[dict[str, Any]] = []
    if check_urls:
        for entry in selected:
            results = [check_url(url) for url in entry["sources"]]
            entry["source_checks"] = results
            dead_links.extend(r for r in results if not r["reachable"])

    report = {
        "format_version": 1,
        "checked_at": today.isoformat(),
        "policy": {"max_age_days": max_age_days, "budget": budget},
        "totals": {
            "snapshots": len(entries),
            "due": len(due),
            "selected": len(selected),
            "deferred": max(0, len(due) - len(selected)),
            "dead_links": len(dead_links),
        },
        "selected": selected,
        # Named, not just counted: "12 deferred" reads as coverage until you see which.
        "deferred": [e["provider"] for e in due[budget:]],
        "fresh": [e["provider"] for e in entries if e not in due],
    }
    return report, (1 if selected else 0)


def render_text(report: dict[str, Any]) -> str:
    """A human-readable summary for the workflow log."""
    totals = report["totals"]
    lines = [
        f"{totals['snapshots']} contract snapshots; {totals['due']} due "
        f"(never live-verified, or past {report['policy']['max_age_days']} days).",
    ]
    if not report["selected"]:
        lines.append("Nothing to audit this run.")
        return "\n".join(lines)

    lines.append(f"\nSelected for audit ({totals['selected']}):")
    for entry in report["selected"]:
        lines.append(f"  {entry['provider']:20} {entry.get('reason', 'no date')}")
        for check in entry.get("source_checks", []):
            if not check["reachable"]:
                lines.append(f"      DEAD {check['status']} {check['url']}")
            elif check.get("unverifiable"):
                lines.append(f"      UNVERIFIABLE {check['url']}")
    if report["deferred"]:
        lines.append(
            f"\nDeferred to a later run ({totals['deferred']}): "
            + ", ".join(report["deferred"])
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the check and write its report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write the JSON report here.")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument(
        "--no-url-check", action="store_true", help="Skip fetching upstream source URLs."
    )
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = parser.parse_args(argv)

    try:
        report, code = build_report(
            today=args.today,
            max_age_days=args.max_age_days,
            budget=args.budget,
            check_urls=not args.no_url_check,
        )
    except (OSError, ValueError) as error:
        print(f"contract drift check could not complete: {error}", file=sys.stderr)
        return 2

    print(render_text(report))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
