"""Check native C# documentation against the assembly's complete documentable surface.

Three independent sources meet here. The maintenance tool's ``--documentation-api`` inventory
reflects over the built assembly and lists every documentable declaration by its canonical
XML documentation ID. The compiler's XML documentation file says what was actually written.
The generated reference map says which IDs the published C# API pages render. A declaration
missing from either of the last two, or documented only by a placeholder, is a finding.

This checker is deliberately independent of the Python-equivalence evidence ledger: native
documentation completeness is not API parity, and neither implies the other.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

_PLACEHOLDER = re.compile(
    r"^(?:todo|tbd|fixme|xxx|placeholder|summary|description|\.\.\.)\b", re.I
)
_PLACEHOLDER_ANYWHERE = re.compile(r"\b(?:TODO|FIXME|TBD|XXX)\b")
_INTERNAL_IDENTIFIER = re.compile(r"\bADR-\d+\b")
_DOCUMENTED_KINDS = frozenset("TMPFE")


@dataclass(frozen=True, slots=True)
class Symbol:
    """One inventory entry produced by ``AnyInfer.Maintenance --documentation-api``."""

    id: str
    kind: str
    signature: str
    parameters: tuple[str, ...]
    type_parameters: tuple[str, ...]
    returns: bool
    inherits: bool


def load_inventory(path: Path) -> dict[str, Symbol]:
    """Read an inventory file, rejecting duplicate or malformed entries."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("symbols"), list):
        raise ValueError(f"{path} is not a version 1 documentation inventory")
    symbols: dict[str, Symbol] = {}
    for entry in document["symbols"]:
        symbol = Symbol(
            id=str(entry["id"]),
            kind=str(entry["kind"]),
            signature=str(entry["signature"]),
            parameters=tuple(str(name) for name in entry["parameters"]),
            type_parameters=tuple(str(name) for name in entry["type_parameters"]),
            returns=bool(entry["returns"]),
            inherits=bool(entry["inherits"]),
        )
        if symbol.id[:2] not in {f"{kind}:" for kind in _DOCUMENTED_KINDS}:
            raise ValueError(f"inventory entry {symbol.id!r} is not a documentation ID")
        if symbol.id in symbols:
            raise ValueError(f"inventory lists {symbol.id!r} twice")
        symbols[symbol.id] = symbol
    return symbols


def load_comments(path: Path) -> dict[str, ET.Element]:
    """Index a compiler XML documentation file by member ID.

    The compiler repeats a positional record's comment on its primary constructor, and can
    emit the same constructor twice; identical repeats are folded, conflicting ones rejected.
    """
    members: dict[str, ET.Element] = {}
    for member in ET.parse(path).getroot().iter("member"):
        name = member.get("name")
        if not name:
            raise ValueError(f"{path} has a member without a name")
        previous = members.get(name)
        if previous is not None and ET.tostring(previous) != ET.tostring(member):
            raise ValueError(f"{path} documents {name!r} twice with different content")
        members[name] = member
    return members


def comment_findings(
    inventory: Mapping[str, Symbol], comments: Mapping[str, ET.Element]
) -> list[str]:
    """Return every missing or inadequate source comment in the inventory."""
    findings: list[str] = []
    for symbol in sorted(inventory.values(), key=lambda item: item.id):
        member = comments.get(symbol.id)
        if member is None:
            findings.append(f"{symbol.id}: no XML documentation")
            continue
        findings.extend(
            f"{symbol.id}: {problem}" for problem in _member_problems(symbol, member, comments)
        )
    return findings


def effective_comment(member: ET.Element, comments: Mapping[str, ET.Element]) -> ET.Element | None:
    """Expand ``<inheritdoc cref="..."/>`` the way the reference renderer presents it.

    The member's own top-level elements win; anything it omits is taken from the cited
    declaration, recursively. A bare ``<inheritdoc/>`` (no ``cref``) names no declaration in
    this assembly, so ``None`` is returned and the caller decides whether it is allowed.
    """
    seen: set[str] = set()
    current = member
    merged = ET.Element("member", member.attrib)
    while True:
        inherit = current.find("inheritdoc")
        own = [child for child in current if child.tag != "inheritdoc"]
        for child in own:
            if not any(_same_slot(child, existing) for existing in merged):
                merged.append(child)
        if inherit is None:
            return merged
        cref = inherit.get("cref")
        if cref is None:
            return None
        if cref in seen or cref not in comments:
            raise ValueError(f"{member.get('name')}: inheritdoc cites unknown or cyclic {cref!r}")
        seen.add(cref)
        current = comments[cref]


def _same_slot(left: ET.Element, right: ET.Element) -> bool:
    return left.tag == right.tag and left.get("name") == right.get("name")


def _member_problems(
    symbol: Symbol, member: ET.Element, comments: Mapping[str, ET.Element]
) -> Iterable[str]:
    text = _text(member)
    if _INTERNAL_IDENTIFIER.search(text):
        yield "documentation contains an internal decision identifier"
    if _PLACEHOLDER_ANYWHERE.search(text):
        yield "documentation contains a placeholder marker"
    for reference in member.iter():
        cref = reference.get("cref")
        if cref is not None and cref.startswith("!:"):
            yield f"unresolved cref {cref!r}"
    try:
        expanded = effective_comment(member, comments)
    except ValueError as error:
        yield str(error).split(": ", 1)[1]
        return
    if expanded is None:
        if not symbol.inherits:
            yield "inheritdoc on a declaration that neither overrides nor implements a member"
        return
    member = expanded
    summary = member.find("summary")
    summary_text = _text(summary) if summary is not None else ""
    if not summary_text:
        yield "empty or missing summary"
    elif _PLACEHOLDER.match(summary_text) or summary_text.rstrip(".") == _bare_name(symbol):
        yield f"placeholder summary {summary_text!r}"
    yield from _named_problems(member, "param", symbol.parameters)
    yield from _named_problems(member, "typeparam", symbol.type_parameters)
    if symbol.returns:
        returns = member.find("returns")
        if returns is None or not _text(returns):
            yield "missing returns documentation"


def _named_problems(member: ET.Element, tag: str, names: tuple[str, ...]) -> Iterable[str]:
    documented = {element.get("name"): _text(element) for element in member.findall(tag)}
    for name in names:
        if not documented.get(name):
            yield f"missing {tag} documentation for {name!r}"


def _bare_name(symbol: Symbol) -> str:
    name = symbol.id[2:].split("(", 1)[0].rsplit(".", 1)[-1]
    return name.split("`", 1)[0]


def _text(element: ET.Element | None) -> str:
    """Return an element's normalized prose, counting references as their target names."""
    if element is None:
        return ""
    parts: list[str] = []
    for node in element.iter():
        for attribute in ("cref", "name", "langword", "href"):
            if node is not element and node.get(attribute):
                parts.append(str(node.get(attribute)))
        if node.text:
            parts.append(node.text)
        if node is not element and node.tail:
            parts.append(node.tail)
    return " ".join(" ".join(parts).split())


def reference_findings(inventory: Mapping[str, Symbol], rendered: Mapping[str, str]) -> list[str]:
    """Return inventory IDs missing from the generated reference, and unexplained extras.

    Args:
        inventory: The assembly's documentable declarations.
        rendered: Generated reference map from documentation ID to published URL.
    """
    findings = [
        f"{identifier}: not rendered in the generated C# reference"
        for identifier in sorted(set(inventory) - set(rendered))
    ]
    findings.extend(
        f"{identifier}: rendered but absent from the documentation inventory"
        for identifier in sorted(set(rendered) - set(inventory))
        if identifier[:2] in {f"{kind}:" for kind in _DOCUMENTED_KINDS}
    )
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the requested checks and print every finding."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--comments", type=Path, help="compiler XML documentation file")
    parser.add_argument("--reference-map", type=Path, help="generated ID-to-URL map (JSON)")
    arguments = parser.parse_args(argv)
    if arguments.comments is None and arguments.reference_map is None:
        parser.error("pass --comments, --reference-map, or both")
    inventory = load_inventory(arguments.inventory)
    findings: list[str] = []
    if arguments.comments is not None:
        findings.extend(comment_findings(inventory, load_comments(arguments.comments)))
    if arguments.reference_map is not None:
        rendered = json.loads(arguments.reference_map.read_text(encoding="utf-8"))
        findings.extend(reference_findings(inventory, rendered))
    for finding in findings:
        print(finding)
    print(
        f"C# documentation: {len(inventory)} declarations, {len(findings)} finding(s)",
        file=sys.stderr,
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
