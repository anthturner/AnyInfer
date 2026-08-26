"""Check that CHANGELOG.md obeys the rules in docs/contributing/changelog.md.

Three things are enforced here, and the third is the reason this file exists.

The first is shape: a fixed heading vocabulary, one bullet per entry, a length cap, and
an entry budget per release. Shape is what makes the file skimmable, and a changelog that
is not skimmable is one nobody reads in place of the commit log it was meant to replace.

The second is that the file always carries an ``## Unreleased`` section, even an empty
one. Entries accrue there as work merges, so the answer to "what is queued for the next
release?" is a section rather than a diff between two tags. Releasing promotes that
heading in place -- see ``--promote`` -- which is why an entry is written once, on its way
in, and never rewritten at release time.

The third is that released sections are immutable. The entries are drafted by a model,
and a model asked to "write the changelog" will cheerfully rewrite last year's entries
into its own voice -- silently, in a diff nobody is reading closely because the change
under review is a version bump. So history is not defended by asking nicely in a prompt:
the sections already on `main` must appear byte for byte as the tail of the file, and
anything else fails this check. New sections may only be added above them.

Also serves the release workflow: ``--emit-section VERSION`` prints one section's body,
which becomes the GitHub Release notes. The release notes and the changelog are then the
same bytes by construction rather than by discipline.

Run directly, or through ``python workspace.py check --only=changelog``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
PYPROJECT = ROOT / "pyproject.toml"

TITLE = "# Changelog"
"""The H1 the file must open with, so ``--emit-section`` can never mistake a different
document for this one."""

UNRELEASED = "Unreleased"
"""The heading in-flight entries accrue under. Always present, frequently empty, and the
only section whose contents may be edited freely."""

SECTION_RE = re.compile(
    r"^## (?P<version>\d+\.\d+\.\d+) — (?P<date>\d{4}-\d{2}-\d{2})$", re.MULTILINE
)
"""``## 0.2.0 - 2026-09-14``, with an em dash. One accepted spelling rather than several,
because ``--promote`` writes these and a human only ever edits the prose beneath them."""

HEADINGS: tuple[str, ...] = ("Breaking", "Added", "Changed", "Fixed")
"""The only subsection headings allowed, in the only order allowed. The fixed vocabulary
doubles as the relevance test: an entry that fits none of the four usually belongs in the
commit log instead."""

MAX_ENTRY_CHARS = 160
"""Length cap for an ordinary entry, measured on the entry's text with its Markdown line
wrapping collapsed -- so wrapping to the repository's line width costs nothing, and
writing three sentences costs what it should."""

MAX_FRONTIER_CHARS = 600
"""Length cap for the one long entry a release is allowed. Enough to introduce a new
capability class and link the page that explains it; not enough to explain it here."""

MAX_FRONTIER_ENTRIES = 1
"""How many long entries one release may carry. Two frontier items in a release almost
always means one of them is an increment wearing a frontier's clothes."""

MAX_ENTRIES = 15
"""Entry budget per released version. Past this the section must end with a link to the
full compare view, so a reader can see the list was curated rather than assume it was
complete. Not applied to ``Unreleased``, which is mid-accrual by definition; promotion is
where the budget bites."""

CURATION_LINK_RE = re.compile(r"/compare/")
"""What the optional trailing paragraph must contain to be accepted: the compare view for
the release. It is the only non-entry prose a section may carry."""


@dataclass
class Entry:
    """One changelog bullet, with any wrapped continuation lines folded in."""

    text: str
    line: int

    @property
    def is_frontier(self) -> bool:
        """Whether this entry claims the release's one long-form slot."""
        return len(self.text) > MAX_ENTRY_CHARS


@dataclass
class Section:
    """One section of the changelog: a released version, or ``Unreleased``."""

    version: str
    date: str
    line: int
    headings: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    body: list[str] = field(default_factory=list)
    curation_note: str | None = None

    @property
    def is_unreleased(self) -> bool:
        """Whether this is the in-flight section rather than a released version."""
        return self.version == UNRELEASED

    @property
    def key(self) -> tuple[int, ...]:
        """The version as a comparable tuple, for the descending-order check."""
        return tuple(int(part) for part in self.version.split("."))


def parse(text: str, problems: list[str]) -> list[Section]:
    """Split the changelog into sections, recording structural faults as it goes.

    Args:
        text: The whole file.
        problems: Accumulator; every fault found is appended as a human-readable line.

    Returns:
        Every section found, in file order. Sections are returned even when they carry
        faults, so one bad section cannot hide the ones after it.
    """
    lines = text.splitlines()
    if not lines or lines[0] != TITLE:
        problems.append(f"CHANGELOG.md must open with {TITLE!r}")

    sections: list[Section] = []
    current: Section | None = None
    pending: list[str] = []
    pending_line = 0

    def flush() -> None:
        """Fold the buffered bullet and its continuation lines into one entry."""
        nonlocal pending
        if not pending or current is None:
            pending = []
            return
        current.entries.append(Entry(" ".join(" ".join(pending).split()), pending_line))
        pending = []

    for number, raw in enumerate(lines, start=1):
        match = SECTION_RE.match(raw)
        if match is not None or raw == f"## {UNRELEASED}":
            flush()
            if match is None:
                current = Section(UNRELEASED, "", number)
            else:
                current = Section(match["version"], match["date"], number)
            sections.append(current)
            continue
        if raw.startswith("## "):
            flush()
            problems.append(f"line {number}: section heading does not parse: {raw!r}")
            current = None
            continue
        if current is None:
            continue

        current.body.append(raw)
        if raw.startswith("### "):
            flush()
            current.headings.append(raw.removeprefix("### ").strip())
        elif raw.startswith("- "):
            flush()
            pending = [raw.removeprefix("- ")]
            pending_line = number
        elif raw.startswith("  ") and raw.strip() and pending:
            pending.append(raw.strip())
        elif raw.strip():
            flush()
            if CURATION_LINK_RE.search(raw) and current.curation_note is None:
                current.curation_note = raw.strip()
            else:
                problems.append(
                    f"line {number}: only entries and one trailing compare link are "
                    f"allowed in a section: {raw.strip()[:60]!r}"
                )
        else:
            flush()
    flush()

    # The blank lines bracketing a section belong to the file, not to the section;
    # trimming here keeps `--emit-section` from padding a release body with them.
    for section in sections:
        while section.body and not section.body[0].strip():
            section.body.pop(0)
        while section.body and not section.body[-1].strip():
            section.body.pop()
    return sections


def check_section(section: Section, problems: list[str]) -> None:
    """Apply the per-section rules from docs/contributing/changelog.md.

    The heading vocabulary and the length caps apply everywhere, including to
    ``Unreleased``: an entry written badly on its way in is an entry that gets released
    badly. The entry budget does not, because a section still accruing has not finished
    being written -- promotion is where the budget is enforced.
    """
    where = f"{section.version} (line {section.line})"

    unknown = [name for name in section.headings if name not in HEADINGS]
    if unknown:
        problems.append(f"{where}: unknown heading(s) {unknown}; allowed: {list(HEADINGS)}")
    if len(set(section.headings)) != len(section.headings):
        problems.append(f"{where}: a heading is repeated")
    known = [name for name in section.headings if name in HEADINGS]
    if known != sorted(known, key=HEADINGS.index):
        problems.append(f"{where}: headings must appear in the order {list(HEADINGS)}")

    frontier = [entry for entry in section.entries if entry.is_frontier]
    if len(frontier) > MAX_FRONTIER_ENTRIES:
        lines = ", ".join(str(entry.line) for entry in frontier)
        problems.append(
            f"{where}: {len(frontier)} entries exceed {MAX_ENTRY_CHARS} characters "
            f"(lines {lines}); at most {MAX_FRONTIER_ENTRIES} may, and only to introduce "
            "a new capability class"
        )
    for entry in frontier:
        if len(entry.text) > MAX_FRONTIER_CHARS:
            problems.append(
                f"{where}: line {entry.line} is {len(entry.text)} characters, past the "
                f"{MAX_FRONTIER_CHARS} allowed even for a frontier entry; link the page "
                "that explains it instead of explaining it here"
            )

    if section.is_unreleased:
        # An empty Unreleased is the normal state immediately after a release, and a
        # curation link would point at a comparison that does not exist yet.
        if section.curation_note is not None:
            problems.append(f"{where}: a compare link belongs on a released section")
        return

    if not section.entries:
        problems.append(f"{where}: section has no entries")
    if len(section.entries) > MAX_ENTRIES:
        problems.append(
            f"{where}: {len(section.entries)} entries exceeds the budget of {MAX_ENTRIES}; "
            "cut to the entries a partner would act on"
        )
    if len(section.entries) >= MAX_ENTRIES and section.curation_note is None:
        problems.append(
            f"{where}: a section at the entry budget must end with a line linking the "
            "release's compare view, so a reader can tell the list was curated"
        )


def released_tail(text: str) -> str:
    """The part of a changelog that is frozen: the first released section onwards.

    ``Unreleased`` and the preamble sit above it and stay editable, which is what makes
    an accruing section possible at all.
    """
    match = SECTION_RE.search(text)
    return text[match.start() :] if match else ""


def baseline_tail(problems: list[str]) -> str | None:
    """The frozen region of CHANGELOG.md as it stands on ``main``.

    Returns:
        The text every future revision must keep as its tail, or ``None`` when there is
        no baseline to compare against -- an unreachable ``main`` (a shallow clone with
        no remote) or a ``main`` predating the file. Both are real states during
        bootstrap, and neither is a reason to fail a pull request.
    """
    for ref in ("origin/main", "main"):
        result = subprocess.run(
            ["git", "show", f"{ref}:CHANGELOG.md"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            tail = released_tail(result.stdout)
            if not tail:
                problems.append(f"{ref}:CHANGELOG.md has no released sections to protect")
                return None
            return tail
    return None


def check_history(text: str, problems: list[str]) -> None:
    """Fail if any section already released has been edited or removed."""
    baseline = baseline_tail(problems)
    if baseline is None:
        print("note: no released CHANGELOG.md on main; skipping the immutability check")
        return
    if released_tail(text).endswith(baseline):
        return

    published = [line for line in baseline.splitlines() if SECTION_RE.match(line)]
    first = published[0].removeprefix("## ") if published else "the first released section"
    problems.append(
        f"released sections were edited or removed. Everything from {first} down must "
        "match main byte for byte; a new version is promoted in above them, never "
        "written over them. Note the correction under Unreleased instead."
    )


def declared_version() -> str:
    """The version in pyproject.toml, which is the project's single source of truth."""
    with PYPROJECT.open("rb") as handle:
        version: str = tomllib.load(handle)["project"]["version"]
    return version


def emit_section(sections: list[Section], version: str) -> int:
    """Print one section's body, for use as a GitHub Release body.

    The version heading itself is dropped: the release is already titled with its
    version, and repeating it wastes the first line of the notes.
    """
    for section in sections:
        if section.version == version and not section.is_unreleased:
            print("\n".join(section.body))
            return 0
    print(f"CHANGELOG.md has no released section for {version}", file=sys.stderr)
    return 1


def promote(text: str, version: str, date: str) -> tuple[str, str | None]:
    """Pin the accrued ``Unreleased`` entries to a version, and open a fresh one.

    This is deliberately mechanical rather than a rewrite. The entries were drafted and
    reviewed when the work merged; promotion changes one heading and adds another, so
    releasing cannot quietly reword what was already agreed.

    Returns:
        The new text, and an error message if the promotion could not be made.
    """
    heading = f"## {UNRELEASED}"
    if f"\n{heading}\n" not in f"\n{text}":
        return text, f"CHANGELOG.md has no '{heading}' section to promote"
    if re.search(rf"^## {re.escape(version)} — ", text, re.MULTILINE):
        return text, f"CHANGELOG.md already has a section for {version}"

    lines = text.splitlines()
    index = lines.index(heading)
    # Stop at the next section: scanning to end of file would count every released
    # entry below and call an empty Unreleased full.
    body = lines[index + 1 :]
    for offset, line in enumerate(body):
        if line.startswith("## "):
            body = body[:offset]
            break
    if not any(line.startswith("- ") for line in body):
        return text, (
            f"{heading} is empty; a release needs at least one entry. Entries are drafted "
            "when work merges, so an empty section means nothing user-facing shipped."
        )

    lines[index : index + 1] = [heading, "", f"## {version} — {date}"]
    return "\n".join(lines) + "\n", None


def main(argv: list[str] | None = None) -> int:
    """Validate the changelog, emit one section of it, or promote the unreleased one."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--emit-section",
        metavar="VERSION",
        help="print this version's section body and exit; validates nothing",
    )
    parser.add_argument(
        "--promote",
        metavar="VERSION",
        help="pin the Unreleased section to this version and open a fresh one",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="release date for --promote",
    )
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="skip the immutability check (no git history available)",
    )
    args = parser.parse_args(argv)

    if not CHANGELOG.exists():
        print(f"missing {CHANGELOG.relative_to(ROOT)}", file=sys.stderr)
        return 1
    text = CHANGELOG.read_text(encoding="utf-8")

    if args.promote:
        if not args.date:
            print("--promote requires --date", file=sys.stderr)
            return 1
        text, error = promote(text, args.promote, args.date)
        if error is not None:
            print(error, file=sys.stderr)
            return 1
        CHANGELOG.write_text(text, encoding="utf-8")
        print(f"promoted {UNRELEASED} to {args.promote} — {args.date}")

    problems: list[str] = []
    sections = parse(text, problems)

    if args.emit_section:
        return emit_section(sections, args.emit_section)

    unreleased = [section for section in sections if section.is_unreleased]
    released = [section for section in sections if not section.is_unreleased]
    if len(unreleased) != 1:
        problems.append(
            f"CHANGELOG.md must carry exactly one '## {UNRELEASED}' section, even an "
            f"empty one; found {len(unreleased)}"
        )
    elif sections[0] is not unreleased[0]:
        problems.append(f"'## {UNRELEASED}' must be the first section")
    if not released:
        problems.append("CHANGELOG.md declares no released versions")
    for section in sections:
        check_section(section, problems)

    keys = [section.key for section in released]
    if keys != sorted(keys, reverse=True) or len(set(keys)) != len(keys):
        order = ", ".join(section.version for section in released)
        problems.append(f"released sections must run newest first with no repeats: {order}")

    if released:
        declared = declared_version()
        if released[0].version != declared:
            problems.append(
                f"pyproject declares {declared} but the newest released section is "
                f"{released[0].version}. A version bump promotes the Unreleased section "
                "-- the changelog workflow does that on the branch that bumps it."
            )

    if not args.skip_history:
        check_history(text, problems)

    if problems:
        print(f"CHANGELOG.md: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    counts = f"{len(released)} released version(s)"
    pending = len(unreleased[0].entries) if unreleased else 0
    print(f"CHANGELOG.md ok: {counts}, {pending} entry/entries awaiting release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
