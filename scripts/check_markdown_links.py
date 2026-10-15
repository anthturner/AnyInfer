#!/usr/bin/env python3
"""Check local Markdown links and heading fragments using only the standard library."""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]*>|(?:\\.|[^)])*)\)")
REF_DEF = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(?:<([^>]+)>|(\S+))")
REF_USE = re.compile(r"!?\[[^\]]*\]\[([^\]]*)\]")
HTML_ID = re.compile(r"\bid\s*=\s*[\"']([^\"']+)[\"']|\bname\s*=\s*[\"']([^\"']+)[\"']", re.I)


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text.strip())


def markdown_lines(path: Path) -> list[tuple[int, str]]:
    kept: list[tuple[int, str]] = []
    fence_char = ""
    fence_len = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = FENCE.match(line)
        if match:
            mark = match.group(1)
            if not fence_char:
                fence_char, fence_len = mark[0], len(mark)
            elif mark[0] == fence_char and len(mark) >= fence_len:
                fence_char, fence_len = "", 0
            continue
        if not fence_char:
            kept.append((number, line))
    return kept


def anchors(path: Path) -> set[str]:
    result: set[str] = set()
    used: dict[str, int] = {}
    for _, line in markdown_lines(path):
        for match in HTML_ID.finditer(line):
            result.add(match.group(1) or match.group(2))
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            title = re.sub(r"\s+#+\s*$", "", heading.group(1)).strip()
            title = re.sub(r"`([^`]*)`", r"\1", title)
            base = slug(title)
            n = used.get(base, 0)
            used[base] = n + 1
            result.add(base if n == 0 else f"{base}-{n}")
    return result


def clean_inline(line: str) -> str:
    return re.sub(r"(`+)(.*?)\1", lambda m: " " * len(m.group(0)), line)


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    lines = markdown_lines(path)
    refs: dict[str, str] = {}
    for _, line in lines:
        match = REF_DEF.match(line)
        if match:
            refs[match.group(1).strip().casefold()] = match.group(2) or match.group(3)

    links: list[tuple[int, str]] = []
    for number, line in lines:
        line = clean_inline(line)
        if REF_DEF.match(line):
            continue
        for match in LINK.finditer(line):
            dest = match.group(1).strip()
            if dest.startswith("<") and dest.endswith(">"):
                dest = dest[1:-1]
            else:
                dest = re.sub(r"\\([()\\])", r"\1", dest)
                dest = dest.split(None, 1)[0] if dest else ""
            links.append((number, dest))
        for match in REF_USE.finditer(line):
            label = (match.group(1) or match.group(0)[1:match.group(0).find("]")]).strip().casefold()
            if label not in refs:
                errors.append(f"{path}:{number}: undefined reference label [{label}]")
            else:
                links.append((number, refs[label]))

    for number, dest in links:
        if not dest or dest.startswith("#"):
            if dest.startswith("#") and unquote(dest[1:]) not in anchors(path):
                errors.append(f"{path}:{number}: missing fragment #{unquote(dest[1:])}")
            continue
        parsed = urlsplit(dest)
        if parsed.scheme or parsed.netloc:
            continue
        target_text = unquote(parsed.path)
        target = (path.parent / target_text).resolve() if target_text else path.resolve()
        if not target.exists():
            errors.append(f"{path}:{number}: missing relative target {parsed.path}")
            continue
        if parsed.fragment:
            fragment = unquote(parsed.fragment)
            anchor_file = target / "index.md" if target.is_dir() and (target / "index.md").exists() else target
            if not anchor_file.is_file() or anchor_file.suffix.lower() != ".md" or fragment not in anchors(anchor_file):
                errors.append(f"{path}:{number}: missing fragment #{fragment} in {parsed.path or '.'}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Markdown files or directories to check")
    args = parser.parse_args()
    files: set[Path] = set()
    for item in args.paths:
        if not item.exists():
            print(f"missing input path: {item}", file=sys.stderr)
            return 2
        if item.is_dir():
            files.update(p for p in item.rglob("*.md") if p.is_file())
        elif item.suffix.lower() == ".md":
            files.add(item)
    errors = [error for path in sorted(files) for error in check_file(path)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"{len(errors)} broken Markdown link(s) across {len(files)} file(s)", file=sys.stderr)
        return 1
    print(f"Markdown links OK ({len(files)} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
