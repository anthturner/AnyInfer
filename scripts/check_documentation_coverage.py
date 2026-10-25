"""Check the documentation review ledger against the pages the site actually publishes.

``maintenance/documentation/page-coverage.json`` records, for every authored published page,
which SDK its content describes, the executable evidence behind it, its review status, and
any journey it teaches that the native C# SDK does not implement. It is a review ledger, not
a router: routes, SDK plugins and versions are still derived from ``scripts/docs_common.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

try:  # Package import for tests run from the repository root.
    from .docs_common import build_pages, load_navigation
except ImportError:  # Direct ``python scripts/check_documentation_coverage.py`` execution.
    from docs_common import build_pages, load_navigation

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "maintenance" / "documentation" / "page-coverage.json"
SCOPES = frozenset({"shared", "python", "csharp", "mixed"})
REVIEW_STATES = frozenset({"pending", "reviewed"})
_SNIPPET = re.compile(r'^\s*--8<--\s+["\'](?P<target>[^"\']+)["\']\s*$', re.MULTILINE)


def published_sources(root: Path) -> list[str]:
    """Return every authored source the documentation site publishes, in navigation order."""
    pages = build_pages(root / "docs", load_navigation(root / "website" / "navigation.json"))
    return [page.source for page in pages]


def ledger_problems(
    ledger: dict[str, object],
    sources: Iterable[str],
    root: Path,
    *,
    require_reviewed: bool | None = None,
) -> list[str]:
    """Return every way the ledger disagrees with the published source set.

    Args:
        ledger: The parsed ledger document.
        sources: The authored sources the site publishes.
        root: Repository root used to resolve sources and cited evidence.
        require_reviewed: Override the ledger's own ``require_reviewed`` flag.
    """
    problems: list[str] = []
    if ledger.get("schema_version") != 1:
        problems.append("ledger schema_version must be 1")
    required = (
        bool(ledger.get("require_reviewed")) if require_reviewed is None else require_reviewed
    )
    rows = ledger.get("pages")
    if not isinstance(rows, list):
        return [*problems, "ledger pages must be a list"]

    counts = Counter(str(row.get("source")) for row in rows if isinstance(row, dict))
    problems.extend(
        f"{source}: listed {count} times" for source, count in counts.items() if count > 1
    )
    published = list(sources)
    problems.extend(
        f"{source}: published but missing from the ledger"
        for source in published
        if source not in counts
    )
    problems.extend(
        f"{source}: stale row for a source the site does not publish"
        for source in counts
        if source not in published
    )
    for row in rows:
        if not isinstance(row, dict):
            problems.append(f"malformed ledger row {row!r}")
            continue
        problems.extend(_row_problems(row, root, required))
    problems.extend(_repository_problems(ledger, root, required, set(published)))
    return problems


def _row_problems(row: dict[str, object], root: Path, required: bool) -> Iterable[str]:
    source = str(row.get("source"))
    if row.get("scope") not in SCOPES:
        yield f"{source}: scope must be one of {sorted(SCOPES)}"
    review = row.get("review")
    if review not in REVIEW_STATES:
        yield f"{source}: review must be one of {sorted(REVIEW_STATES)}"
    elif required and review != "reviewed":
        yield f"{source}: not reviewed"
    for key in ("evidence", "unsupported_native"):
        if not isinstance(row.get(key), list) or not all(
            isinstance(item, str) and item
            for item in row.get(key, [])  # type: ignore[union-attr]
        ):
            yield f"{source}: {key} must be a list of non-empty strings"
    if not isinstance(row.get("notes"), str):
        yield f"{source}: notes must be text"
    evidence = [str(item) for item in row.get("evidence", []) if isinstance(item, str)]  # type: ignore[union-attr]
    for path in evidence:
        if not (root / path).exists():
            yield f"{source}: cited evidence {path} does not exist"
    page = root / "docs" / source
    if page.is_file():
        for target in _SNIPPET.findall(page.read_text(encoding="utf-8")):
            path = target.rpartition(":")[0] if ":" in target else target
            if path not in evidence:
                yield f"{source}: includes {path} but does not cite it as evidence"


def _repository_problems(
    ledger: dict[str, object], root: Path, required: bool, published: set[str]
) -> Iterable[str]:
    entries = ledger.get("repository_only", [])
    exclusions = ledger.get("exclusions", [])
    if not isinstance(entries, list) or not isinstance(exclusions, list):
        yield "repository_only and exclusions must be lists"
        return
    seen: set[str] = set()
    for entry in entries:
        path = str(entry.get("path"))
        if path in seen:
            yield f"{path}: repository entrypoint listed twice"
        seen.add(path)
        if not (root / path).is_file():
            yield f"{path}: repository entrypoint does not exist"
        if path.startswith("docs/") and path.removeprefix("docs/") in published:
            yield f"{path}: published page listed as repository-only"
        if entry.get("scope") not in SCOPES:
            yield f"{path}: scope must be one of {sorted(SCOPES)}"
        review = entry.get("review")
        if review not in REVIEW_STATES:
            yield f"{path}: review must be one of {sorted(REVIEW_STATES)}"
        elif required and review != "reviewed":
            yield f"{path}: not reviewed"
        for mirror in entry.get("mirrors", []):
            if not (root / mirror).is_file():
                yield f"{path}: mirrored page {mirror} does not exist"
    for exclusion in exclusions:
        path = str(exclusion.get("path"))
        if not (root / path).exists():
            yield f"{path}: excluded path does not exist"
        if not str(exclusion.get("reason", "")).strip():
            yield f"{path}: exclusion needs a reason"
        if path in seen:
            yield f"{path}: both excluded and listed as a repository entrypoint"


def main(argv: list[str] | None = None) -> int:
    """Validate the committed ledger and print every problem."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--require-reviewed",
        action="store_true",
        help="fail on any row still pending review (final acceptance)",
    )
    arguments = parser.parse_args(argv)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    problems = ledger_problems(
        ledger,
        published_sources(ROOT),
        ROOT,
        require_reviewed=True if arguments.require_reviewed else None,
    )
    for problem in problems:
        print(problem)
    pending = sum(1 for row in ledger["pages"] if row.get("review") != "reviewed")
    print(
        f"documentation coverage: {len(ledger['pages'])} pages, {pending} pending review",
        file=sys.stderr,
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
