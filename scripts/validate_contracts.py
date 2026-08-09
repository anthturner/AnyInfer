"""Check that every contract snapshot carries the sections the drift check reads.

A snapshot missing its Auth section is not a smaller snapshot — it is a snapshot the drift
procedure cannot audit, and the gap is invisible until someone runs the check and finds
nothing to compare. Structure is cheap to enforce, so it is enforced here rather than in
review.

Content is not judged: this says a section exists, never that it is right. Verifying the
facts is what DRIFT-CHECK.md is for.

Run directly, or through ``python workspace.py check``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"

REQUIRED_HEADINGS: tuple[str, ...] = (
    "## Upstream sources",
    "## Wire contract",
    "### Endpoints",
    "### Auth",
    "### Version pins",
    "### Request fields",
    "### Response fields",
    "### Streaming",
    "### Errors",
    "## Watchlist",
)
"""Sections every provider snapshot must carry, in the order the template declares them."""

NOT_SNAPSHOTS = frozenset(
    {
        "README.md",
        "DRIFT-CHECK.md",
        "TEMPLATE.md",
        # Not a provider snapshot: the presets record verifies eighty-six endpoints against
        # one shared dialect, so it is organized per preset rather than per wire section.
        "openai-compat-presets.md",
    }
)
"""Files under contracts/ that document a process or a fleet rather than one provider."""

LAST_VERIFIED = re.compile(r"^Last verified:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
"""Every snapshot states when it was last checked, as a real ISO date."""


def snapshots() -> list[Path]:
    """Every provider snapshot under ``contracts/``."""
    return sorted(p for p in CONTRACTS.glob("*.md") if p.name not in NOT_SNAPSHOTS)


def problems(path: Path) -> list[str]:
    """Structural problems with one snapshot."""
    text = path.read_text(encoding="utf-8")
    found: list[str] = []

    # Prefix matching, not equality: a snapshot may qualify a heading ("### Response
    # fields read (native discovery)") without having omitted the section.
    headings = {line.rstrip() for line in text.splitlines() if line.startswith("#")}
    for heading in REQUIRED_HEADINGS:
        if not any(found_heading.startswith(heading) for found_heading in headings):
            found.append(f"missing section {heading!r}")

    if not LAST_VERIFIED.search(text):
        found.append("missing a 'Last verified: YYYY-MM-DD' line")

    return found


def main() -> int:
    """Validate every snapshot, reporting each problem with its file."""
    failures = 0
    for path in snapshots():
        for problem in problems(path):
            print(f"{path.relative_to(ROOT)}: {problem}")
            failures += 1

    if failures:
        print(f"\n{failures} contract snapshot problem(s); see contracts/TEMPLATE.md")
        return 1

    print(f"{len(snapshots())} contract snapshots have every required section")
    return 0


if __name__ == "__main__":
    sys.exit(main())
