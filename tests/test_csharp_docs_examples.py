"""Authored C# documentation only shows source the offline example runner executes.

C# code reaches a page in exactly one way: a ``--8<--`` include of a file under
``examples/csharp-sdk/``. Every example class an include shows must be invoked by the runner
(``Program.cs`` or a case under ``Cases/``), so a published recipe cannot quietly stop running.
Generated API signatures under ``/csharp/api/`` are rendered from source and are not authored
examples; they are checked by the C# reference controls instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EXAMPLES = ROOT / "examples" / "csharp-sdk"
_FENCE = re.compile(r"^(?P<indent>\s*)```(?P<info>[^\n`]*)$")
_CSHARP = frozenset({"csharp", "cs", "c#"})
_INCLUDE = re.compile(r'^\s*--8<--\s+["\'](?P<target>[^"\']+)["\']\s*$')
_EXAMPLE_CLASS = re.compile(r"\b(?:public|internal)\s+static\s+class\s+(?P<name>\w+)")
_CASE = re.compile(r"\[ExampleCase\(\"(?P<name>[^\"]+)\"\)\]")


def _pages() -> list[Path]:
    return sorted(DOCS.rglob("*.md"))


def _csharp_blocks(path: Path) -> list[tuple[int, list[str]]]:
    """Return each C# fenced block in a page with its body lines."""
    blocks: list[tuple[int, list[str]]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        match = _FENCE.match(lines[index])
        if match is None:
            index += 1
            continue
        start = index
        info = match.group("info").strip().split(" ", 1)[0].lower()
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].strip().startswith("```"):
            body.append(lines[index])
            index += 1
        index += 1
        if info in _CSHARP:
            blocks.append((start + 1, body))
    return blocks


def _includes() -> dict[str, list[str]]:
    """Map each included example file to the pages that include it."""
    included: dict[str, list[str]] = {}
    for page in _pages():
        for line in page.read_text(encoding="utf-8").splitlines():
            match = _INCLUDE.match(line)
            if match is None:
                continue
            target = match.group("target")
            path = target.rpartition(":")[0] if target.count(":") == 1 else target
            if path.startswith("examples/csharp-sdk/"):
                included.setdefault(path, []).append(page.relative_to(DOCS).as_posix())
    return included


def _runner_sources(excluding: Path) -> str:
    sources = [EXAMPLES / "Program.cs", *sorted((EXAMPLES / "Cases").glob("*.cs"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in sources if path != excluding)


def test_pages_never_hand_write_csharp() -> None:
    handwritten = []
    for page in _pages():
        for line, body in _csharp_blocks(page):
            code = [text for text in body if text.strip()]
            if len(code) != 1 or _INCLUDE.match(code[0]) is None:
                handwritten.append(f"{page.relative_to(DOCS)}:{line}")
    assert handwritten == [], (
        "C# in documentation must be an include of an executed file under examples/csharp-sdk/"
    )


def test_every_included_example_exists_and_is_executed_by_the_runner() -> None:
    included = _includes()
    assert included, "the C# documentation includes no example source"
    unexecuted = []
    for relative, pages in sorted(included.items()):
        path = ROOT / relative
        assert path.is_file(), f"{relative} included by {pages} does not exist"
        if path.parent.name == "Cases" or path.name == "Program.cs":
            continue
        classes = _EXAMPLE_CLASS.findall(path.read_text(encoding="utf-8"))
        assert classes, f"{relative} declares no example class"
        runner = _runner_sources(excluding=path)
        if not any(re.search(rf"\b{re.escape(name)}\.", runner) for name in classes):
            unexecuted.append(f"{relative} (included by {', '.join(pages)})")
    assert unexecuted == [], "included examples the offline runner never executes"


def test_example_cases_are_named_uniquely() -> None:
    names: list[str] = []
    for path in sorted((EXAMPLES / "Cases").glob("*.cs")):
        names.extend(_CASE.findall(path.read_text(encoding="utf-8")))
    assert len(names) == len(set(names)), "duplicate example case names"


@pytest.mark.parametrize(
    ("body", "allowed"),
    [
        (['--8<-- "examples/csharp-sdk/GenerationExample.cs"'], True),
        (["", '--8<-- "examples/csharp-sdk/GenerationExample.cs:region"', ""], True),
        (["var client = new AsyncClient();"], False),
        (['--8<-- "examples/csharp-sdk/A.cs"', "Console.WriteLine();"], False),
    ],
)
def test_the_handwritten_code_control_distinguishes_includes_from_code(
    tmp_path: Path, body: list[str], allowed: bool
) -> None:
    page = tmp_path / "page.md"
    page.write_text("# Page\n\n```csharp\n" + "\n".join(body) + "\n```\n", encoding="utf-8")
    [(_line, block)] = _csharp_blocks(page)
    code = [text for text in block if text.strip()]
    assert (len(code) == 1 and _INCLUDE.match(code[0]) is not None) is allowed
