"""Generate the native C# API reference pages from DocFX managed-reference metadata.

The pipeline is build-only: the DocFX version pinned in ``.config/dotnet-tools.json`` extracts
``src/csharp/AnyInfer/AnyInfer.csproj`` as configured by ``website/docfx.json``; this module
renders that metadata into Markdown for the C# docs plugin at ``/csharp/api/``; and the
maintenance tool's ``--documentation-api`` inventory is compared with the rendered symbol map,
so a declaration the renderer drops fails the build instead of quietly disappearing.

The extracted metadata and inventory are cached under ``website/.cache/csharp-reference/``
behind a fingerprint of every input that can change them: the native sources and comments,
project and props files, the SDK and tool pins, the DocFX configuration, and this renderer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

try:  # Package import for tests and build scripts run from the repository root.
    from .check_csharp_docs import load_inventory, reference_findings
except ImportError:  # Direct ``python scripts/generate_csharp_reference.py`` execution.
    from check_csharp_docs import load_inventory, reference_findings

ROOT = Path(__file__).resolve().parents[1]
API_ROUTE = "/api/"
PLUGIN_BASE = "/csharp"
SECTION = "C# API Reference"
SOURCE_BASE = "https://github.com/anthturner/AnyInfer/blob/main/"
FRAMEWORK_API = "https://learn.microsoft.com/dotnet/api/"
_KEYWORD_LINK = "https://learn.microsoft.com/dotnet/csharp/language-reference/keywords/"
_TYPE_KINDS = {
    "Class": "class",
    "Struct": "struct",
    "Interface": "interface",
    "Enum": "enum",
    "Delegate": "delegate",
}
_MEMBER_SECTIONS = (
    ("Constructor", "Constructors"),
    ("Field", "Fields"),
    ("Property", "Properties"),
    ("Method", "Methods"),
    ("Event", "Events"),
    ("Operator", "Operators"),
)
_DOCUMENTED = re.compile(r"^[TMPFE]:")
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>{}|#])")
_FINGERPRINT_IGNORED = frozenset({"bin", "obj", "TestResults", ".vs"})
# Record members the compiler synthesizes are not rendered (the documentation inventory
# excludes them for the same reason), so a relationship to one is shown as plain text.
_SYNTHESIZED_RECORD_MEMBERS = frozenset(
    {
        "Equals",
        "GetHashCode",
        "ToString",
        "PrintMembers",
        "Deconstruct",
        "op_Equality",
        "op_Inequality",
    }
)


class ReferenceError(ValueError):
    """The metadata cannot be rendered into a complete, link-consistent reference."""


@dataclass(frozen=True, slots=True)
class GeneratedPage:
    """One generated C# API page, staged into the ``csharp`` docs plugin."""

    uid: str
    path: str
    slug: str
    url: str
    title: str
    label: str
    namespace: str
    kind: str
    origin: str | None
    content: str

    def manifest(self, order: int) -> dict[str, object]:
        """Return the page's entry in the documentation manifest."""
        return {
            "source": f"generated:csharp-api/{self.uid}",
            "sdk": "csharp",
            "id": self.path.removesuffix(".md"),
            "slug": self.slug,
            "url": self.url,
            "title": self.title,
            "section": SECTION,
            "order": order,
            "generated": True,
            "origin": self.origin,
        }


@dataclass(frozen=True, slots=True)
class Reference:
    """The rendered reference: its pages and the authoritative symbol-to-URL map."""

    pages: tuple[GeneratedPage, ...]
    symbols: Mapping[str, str]
    namespaces: tuple[tuple[str, tuple[GeneratedPage, ...]], ...] = field(default=())

    def sidebar(self) -> dict[str, object]:
        """Return the manifest's sidebar description for the generated section."""
        index = next(page for page in self.pages if page.kind == "index")
        return {
            "label": SECTION,
            "index": index.path.removesuffix(".md"),
            "namespaces": [
                {
                    "label": namespace,
                    "items": [
                        {"id": page.path.removesuffix(".md"), "label": page.label}
                        for page in pages
                    ],
                }
                for namespace, pages in self.namespaces
            ],
        }


def type_slug(uid: str) -> str:
    """Return the readable route segment for a type UID.

    ``AnyInfer.Capabilities.ContextBudget`` becomes ``anyinfer.capabilities.contextbudget``;
    generic arity is explicit (``Box`1`` becomes ``box-1``, which no C# identifier can be),
    and a nested type keeps its containing type (``Box`1.Nested`` becomes ``box-1.nested``).
    """
    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*(?:`\d+)?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:`\d+)?)*", uid
    ):
        raise ReferenceError(f"{uid!r} is not a type UID")
    return re.sub(r"`(\d+)", r"-\1", uid).lower()


def member_anchor(comment_id: str) -> str:
    """Return the stable fragment for one member, derived from its documentation ID."""
    return "member-" + hashlib.sha256(comment_id.encode("utf-8")).hexdigest()[:16]


def load_metadata(directory: Path) -> list[dict[str, object]]:
    """Read every DocFX managed-reference document in ``directory``."""
    import yaml

    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    documents: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("### YamlMime:ManagedReference"):
            continue
        document = yaml.load(text, Loader=loader)
        if not isinstance(document, dict) or not isinstance(document.get("items"), list):
            raise ReferenceError(f"{path.name} is not a managed-reference document")
        documents.append(document)
    if not documents:
        raise ReferenceError(f"no DocFX managed-reference metadata in {directory}")
    return documents


def render(
    documents: Sequence[Mapping[str, object]],
    *,
    version: str,
    assembly: str = "AnyInfer",
    docfx_root: PurePosixPath = PurePosixPath("website"),
) -> Reference:
    """Render DocFX metadata into reference pages.

    Args:
        documents: Parsed managed-reference documents.
        version: The C# SDK version the pages describe.
        assembly: The only assembly whose declarations may be rendered.
        docfx_root: Repository-relative directory DocFX source paths are relative to.

    Raises:
        ReferenceError: On slug or anchor collisions, foreign assemblies, unresolved
            references into the documented assembly, or markup the renderer does not know.
    """
    items: dict[str, dict[str, object]] = {}
    references: dict[str, dict[str, object]] = {}
    for document in documents:
        for item in document["items"]:  # type: ignore[union-attr]
            uid = str(item["uid"])
            if item.get("type") != "Namespace" and assembly not in item.get("assemblies", []):
                raise ReferenceError(f"{uid} belongs to {item.get('assemblies')}, not {assembly}")
            items[uid] = item
        for reference in document.get("references", []) or []:  # type: ignore[union-attr]
            references.setdefault(str(reference["uid"]), reference)

    types = sorted(
        (item for item in items.values() if item.get("type") in _TYPE_KINDS),
        key=lambda item: str(item["uid"]),
    )
    pages_by_type: dict[str, tuple[str, str]] = {}
    slugs: dict[str, str] = {}
    symbols: dict[str, str] = {}
    targets: dict[str, str] = {}
    for item in types:
        uid = str(item["uid"])
        slug = type_slug(uid)
        if slug in slugs:
            raise ReferenceError(f"types {slugs[slug]} and {uid} share the route segment {slug!r}")
        slugs[slug] = uid
        url = f"{PLUGIN_BASE}{API_ROUTE}{slug}/"
        pages_by_type[uid] = (slug, url)
        _register(symbols, targets, item, url)
        anchors: dict[str, str] = {}
        for child in item.get("children", []) or []:
            member = items.get(str(child))
            if member is None:
                raise ReferenceError(f"{uid} lists child {child} with no metadata")
            anchor = member_anchor(str(member["commentId"]))
            if anchor in anchors:
                raise ReferenceError(f"{anchors[anchor]} and {member['commentId']} share {anchor}")
            anchors[anchor] = str(member["commentId"])
            _register(symbols, targets, member, f"{url}#{anchor}")
            overload = member.get("overload")
            if isinstance(overload, str):
                targets.setdefault(overload, f"{url}#{anchor}")

    context = _Context(items, references, targets, assembly)
    pages: list[GeneratedPage] = []
    for item in types:
        slug, url = pages_by_type[str(item["uid"])]
        pages.append(_type_page(item, slug, url, context, docfx_root))

    namespaces: dict[str, list[GeneratedPage]] = {}
    for page in pages:
        namespaces.setdefault(page.namespace, []).append(page)
    grouped = tuple(
        (namespace, tuple(sorted(entries, key=lambda page: page.label.lower())))
        for namespace, entries in sorted(namespaces.items())
    )
    index = _index_page(grouped, version, assembly, context)
    return Reference((index, *pages), symbols, grouped)


def _register(
    symbols: dict[str, str], targets: dict[str, str], item: Mapping[str, object], url: str
) -> None:
    comment_id = str(item["commentId"])
    if comment_id in symbols:
        raise ReferenceError(f"{comment_id} is rendered twice")
    symbols[comment_id] = url
    targets[str(item["uid"])] = url


@dataclass
class _Context:
    items: Mapping[str, Mapping[str, object]]
    references: Mapping[str, Mapping[str, object]]
    targets: Mapping[str, str]
    assembly: str

    def owned(self, uid: str) -> bool:
        """Whether a UID names a declaration in the documented assembly's namespaces."""
        return uid == self.assembly or uid.startswith(self.assembly + ".")

    def link(self, uid: str, text: str | None = None, *, code: bool = False) -> str:
        """Render a link to a UID, failing on an unresolved documented-assembly target."""
        reference = self.references.get(uid, {})
        label = text if text is not None else str(reference.get("name") or _short_name(uid))
        shown = _code(label) if code else escape(label)
        target = self.targets.get(uid)
        definition = reference.get("definition")
        if target is None:
            # A constructed generic type or member links to its generic definition's page.
            target = self.targets.get(
                definition if isinstance(definition, str) else _generic_definition(uid)
            )
        if target is not None:
            return f"[{shown}]({target})"
        if uid.startswith("{") or uid.startswith("`"):
            return shown
        if self.owned(uid):
            if _short_name(uid) in _SYNTHESIZED_RECORD_MEMBERS and self._in_record(uid):
                return _code(label)
            raise ReferenceError(f"unresolved reference to {uid}")
        href = reference.get("href")
        if isinstance(href, str) and href.startswith("https://"):
            return f"[{shown}]({href})"
        if uid.startswith("System.") or uid == "System":
            return f"[{shown}]({FRAMEWORK_API}{_framework_slug(uid)})"
        return shown

    def _in_record(self, uid: str) -> bool:
        parent = self.references.get(uid, {}).get("parent")
        declaration = self.items.get(str(parent), {}).get("syntax") or {}
        return bool(re.search(r"\brecord\b", str(declaration.get("content", ""))))  # type: ignore[union-attr]

    def type_reference(self, uid: str) -> str:
        """Render a possibly constructed type with a link for each named part."""
        reference = self.references.get(uid)
        if reference is None:
            if self.owned(uid) and uid not in self.targets:
                raise ReferenceError(f"unresolved type reference {uid}")
            return self.link(uid)
        parts = reference.get("spec.csharp")
        if not isinstance(parts, list):
            return self.link(uid)
        rendered: list[str] = []
        for part in parts:
            name = str(part.get("name", ""))
            part_uid = part.get("uid")
            rendered.append(self.link(str(part_uid), name) if part_uid else escape(name))
        return "".join(rendered)


def _type_page(
    item: Mapping[str, object],
    slug: str,
    url: str,
    context: _Context,
    docfx_root: PurePosixPath,
) -> GeneratedPage:
    kind = _TYPE_KINDS[str(item["type"])]
    syntax = item.get("syntax") or {}
    declaration = str(syntax.get("content", ""))  # type: ignore[union-attr]
    if kind == "class" and re.search(r"\brecord\b", declaration):
        kind = "record"
    elif kind == "struct" and re.search(r"\brecord\b", declaration):
        kind = "record struct"
    name = str(item["name"])
    namespace = str(item.get("namespace", ""))
    origin, line = _source(item, docfx_root)
    title = f"{name} {kind}"
    summary = _markdown(item.get("summary"), context)
    lines = [f"# {escape(title)}", ""]
    namespace_url = f"{PLUGIN_BASE}{API_ROUTE}#{_namespace_anchor(namespace)}"
    facts = [
        f"**Namespace:** [{escape(namespace)}]({namespace_url})",
        f"**Assembly:** {escape(context.assembly)}",
    ]
    if origin is not None:
        facts.append(
            f"**Source:** [{escape(PurePosixPath(origin).name)}]({_source_url(origin, line)})"
        )
    lines.extend([" · ".join(facts), ""])
    lines.extend(_obsolete(item, context))
    if summary:
        lines.extend([summary, ""])
    lines.extend(_code_block(declaration))
    lines.extend(_type_parameters(syntax, context))
    if kind == "delegate":
        lines.extend(_parameters(syntax, context))
        lines.extend(_returns(syntax, context))
    lines.extend(_relationships(item, context))
    if kind.startswith("record"):
        lines.extend(
            [
                ":::note Record type",
                "",
                "The compiler supplies this record's value equality (`Equals`, `GetHashCode`, "
                "`==` and `!=`), its `ToString` formatting, nondestructive `with` copies, and a "
                "`Deconstruct` method for any positional parameters. Members the type declares "
                "itself are listed below.",
                "",
                ":::",
                "",
            ]
        )
    lines.extend(_prose_section("Remarks", item.get("remarks"), context, level=2))
    lines.extend(_examples(item.get("example"), context, level=2))

    members = [context.items[str(child)] for child in item.get("children", []) or []]  # type: ignore[union-attr]
    if kind == "enum":
        lines.extend(_enum_values(members, context))
    else:
        for member_kind, heading in _MEMBER_SECTIONS:
            selected = [member for member in members if member.get("type") == member_kind]
            if selected:
                lines.extend(_member_section(heading, selected, context, docfx_root))

    description = _plain(item.get("summary")) or f"{name} {kind} in the AnyInfer C# SDK."
    frontmatter = (
        "---\n"
        f"slug: {API_ROUTE}{slug}/\n"
        f"title: {json.dumps(title)}\n"
        f"sidebar_label: {json.dumps(name)}\n"
        f"description: {json.dumps(_first_sentence(description))}\n"
        "custom_edit_url: null\n"
        "toc_max_heading_level: 2\n"
        "---\n\n"
    )
    return GeneratedPage(
        uid=str(item["commentId"]),
        path=f"api/{slug}.md",
        slug=f"{API_ROUTE}{slug}/",
        url=url,
        title=title,
        label=name,
        namespace=namespace,
        kind=kind,
        origin=origin,
        content=frontmatter + "\n".join(lines).rstrip() + "\n",
    )


def _index_page(
    namespaces: tuple[tuple[str, tuple[GeneratedPage, ...]], ...],
    version: str,
    assembly: str,
    context: _Context,
) -> GeneratedPage:
    total = sum(len(pages) for _namespace, pages in namespaces)
    lines = [
        "# C# API reference",
        "",
        f"Every public type of the `{assembly}` assembly in the C# SDK {escape(version)} "
        f"prerelease, generated from its source documentation comments: {total} types in "
        f"{len(namespaces)} namespaces. For what the native SDK does and does not support, its "
        "limits, and how it differs from the Python SDK, start with the "
        "[C# SDK guide](/csharp/) and the [C# SDK reference](/csharp/reference/).",
        "",
    ]
    for namespace, pages in namespaces:
        lines.extend(
            [
                f'<a id="{_namespace_anchor(namespace)}"></a>',
                "",
                f"## {escape(namespace)}",
                "",
                "| Type | Kind | Summary |",
                "|---|---|---|",
            ]
        )
        for page in pages:
            item = context.items[page.uid[2:]]
            lines.append(
                f"| [{escape(page.label)}]({page.url}) | {page.kind} | "
                f"{_cell(_markdown(item.get('summary'), context))} |"
            )
        lines.append("")
    frontmatter = (
        "---\n"
        f"slug: {API_ROUTE}\n"
        'title: "C# API reference"\n'
        'sidebar_label: "Overview"\n'
        "description: "
        + json.dumps(
            f"Generated reference for every public type in the AnyInfer C# SDK {version}."
        )
        + "\n"
        "custom_edit_url: null\n"
        "---\n\n"
    )
    return GeneratedPage(
        uid="index",
        path="api/index.md",
        slug=API_ROUTE,
        url=f"{PLUGIN_BASE}{API_ROUTE}",
        title="C# API reference",
        label="Overview",
        namespace="",
        kind="index",
        origin=None,
        content=frontmatter + "\n".join(lines).rstrip() + "\n",
    )


def _member_section(
    heading: str,
    members: list[Mapping[str, object]],
    context: _Context,
    docfx_root: PurePosixPath,
) -> list[str]:
    lines = [f"## {heading}", "", "| Member | Summary |", "|---|---|"]
    for member in members:
        anchor = member_anchor(str(member["commentId"]))
        lines.append(
            f"| [{escape(str(member['name']))}](#{anchor}) | "
            f"{_cell(_markdown(member.get('summary'), context))} |"
        )
    lines.append("")
    for member in members:
        lines.extend(_member(member, context, docfx_root))
    return lines


def _member(
    member: Mapping[str, object], context: _Context, docfx_root: PurePosixPath
) -> list[str]:
    syntax = member.get("syntax") or {}
    anchor = member_anchor(str(member["commentId"]))
    lines = [f'<a id="{anchor}"></a>', "", f"### {escape(str(member['name']))}", ""]
    lines.extend(_obsolete(member, context))
    summary = _markdown(member.get("summary"), context)
    if summary:
        lines.extend([summary, ""])
    lines.extend(_code_block(str(syntax.get("content", ""))))  # type: ignore[union-attr]
    lines.extend(_type_parameters(syntax, context))
    lines.extend(_parameters(syntax, context))
    lines.extend(
        _returns(syntax, context, property_like=member.get("type") in {"Property", "Field"})
    )
    exceptions = member.get("exceptions") or []
    if exceptions:
        lines.extend(["**Exceptions**", ""])
        for exception in exceptions:  # type: ignore[union-attr]
            description = _markdown(exception.get("description"), context)
            lines.append(
                f"- {context.type_reference(str(exception['type']))}"
                + (f" — {_inline(description)}" if description else "")
            )
        lines.append("")
    overridden = member.get("overridden")
    if isinstance(overridden, str):
        lines.extend([f"**Overrides:** {context.link(overridden)}", ""])
    implements = member.get("implements") or []
    if implements:
        links = ", ".join(context.link(str(uid)) for uid in implements)  # type: ignore[union-attr]
        lines.extend([f"**Implements:** {links}", ""])
    lines.extend(_prose_section("Remarks", member.get("remarks"), context, level=4))
    lines.extend(_examples(member.get("example"), context, level=4))
    origin, line = _source(member, docfx_root)
    if origin is not None:
        lines.extend([f"[View source]({_source_url(origin, line)})", ""])
    return lines


def _enum_values(members: list[Mapping[str, object]], context: _Context) -> list[str]:
    lines = ["## Values", "", "| Name | Value | Description |", "|---|---|---|"]
    for member in members:
        anchor = member_anchor(str(member["commentId"]))
        content = str((member.get("syntax") or {}).get("content", ""))  # type: ignore[union-attr]
        value = content.split("=", 1)[1].strip() if "=" in content else ""
        lines.append(
            f'| <a id="{anchor}"></a>`{member["name"]}` | `{value}` | '
            f"{_cell(_markdown(member.get('summary'), context))} |"
        )
    lines.append("")
    return lines


def _type_parameters(syntax: object, context: _Context) -> list[str]:
    parameters = syntax.get("typeParameters") if isinstance(syntax, dict) else None
    if not parameters:
        return []
    lines = ["**Type parameters**", ""]
    for parameter in parameters:
        description = _markdown(parameter.get("description"), context)
        lines.append(
            f"- `{parameter['id']}`" + (f" — {_inline(description)}" if description else "")
        )
    return [*lines, ""]


def _parameters(syntax: object, context: _Context) -> list[str]:
    parameters = syntax.get("parameters") if isinstance(syntax, dict) else None
    if not parameters:
        return []
    lines = ["**Parameters**", ""]
    for parameter in parameters:
        description = _markdown(parameter.get("description"), context)
        lines.append(
            f"- `{parameter['id']}` {context.type_reference(str(parameter['type']))}"
            + (f" — {_inline(description)}" if description else "")
        )
    return [*lines, ""]


def _returns(syntax: object, context: _Context, *, property_like: bool = False) -> list[str]:
    returned = syntax.get("return") if isinstance(syntax, dict) else None
    if not returned:
        return []
    description = _markdown(returned.get("description"), context)
    label = "Value" if property_like else "Returns"
    return [
        f"**{label}:** {context.type_reference(str(returned['type']))}"
        + (f" — {_inline(description)}" if description else ""),
        "",
    ]


def _relationships(item: Mapping[str, object], context: _Context) -> list[str]:
    lines: list[str] = []
    inheritance = [str(uid) for uid in item.get("inheritance", []) or []]  # type: ignore[union-attr]
    if inheritance:
        chain = [context.type_reference(uid) for uid in inheritance]
        chain.append(escape(str(item["name"])))
        lines.append("**Inheritance:** " + " → ".join(chain))
    implements = [str(uid) for uid in item.get("implements", []) or []]  # type: ignore[union-attr]
    if implements:
        lines.append(
            "**Implements:** " + ", ".join(context.type_reference(uid) for uid in implements)
        )
    derived = [str(uid) for uid in item.get("derivedClasses", []) or []]  # type: ignore[union-attr]
    if derived:
        lines.append("**Derived types:** " + ", ".join(context.link(uid) for uid in derived))
    inherited = [
        str(uid)
        for uid in item.get("inheritedMembers", []) or []  # type: ignore[union-attr]
        if context.owned(str(uid))
    ]
    if inherited:
        lines.append(
            "**Inherited members:** "
            + ", ".join(
                context.link(uid, str(context.references.get(uid, {}).get("nameWithType") or uid))
                for uid in inherited
            )
        )
    if not lines:
        return []
    return [*(line + "  " for line in lines[:-1]), lines[-1], ""]


def _obsolete(item: Mapping[str, object], context: _Context) -> list[str]:
    for attribute in item.get("attributes", []) or []:  # type: ignore[union-attr]
        if attribute.get("type") != "System.ObsoleteAttribute":
            continue
        arguments = attribute.get("arguments") or []
        message = next(
            (str(argument.get("value")) for argument in arguments if argument.get("value")), ""
        )
        body = escape(message) if message else "This member is obsolete."
        return [":::caution Obsolete", "", body, "", ":::", ""]
    return []


def _prose_section(title: str, value: object, context: _Context, *, level: int) -> list[str]:
    text = _markdown(value, context)
    if not text:
        return []
    return [f"{'#' * level} {title}" if level == 2 else f"**{title}**", "", text, ""]


def _examples(value: object, context: _Context, *, level: int) -> list[str]:
    examples = [entry for entry in value or [] if entry] if isinstance(value, list) else []
    if not examples:
        return []
    lines = ["## Examples" if level == 2 else "**Examples**", ""]
    for entry in examples:
        lines.extend([_markdown(entry, context), ""])
    return lines


def _code_block(content: str) -> list[str]:
    if not content:
        return []
    return ["```csharp", _wrap_signature(content), "```", ""]


def _wrap_signature(content: str, width: int = 100) -> str:
    """Break a long declaration after each top-level parameter, keeping it complete."""
    # The parameter list opens right after a name, generic argument list or operator token;
    # a tuple return type such as "(int, string)" follows whitespace instead.
    opening = next(
        (
            index
            for index, character in enumerate(content)
            if character == "(" and index > 0 and not content[index - 1].isspace()
        ),
        -1,
    )
    if len(content) <= width or opening < 0:
        return content
    depth = 0
    pieces: list[str] = []
    start = opening + 1
    closing = -1
    for index in range(opening, len(content)):
        character = content[index]
        if character in "(<[{":
            depth += 1
        elif character in ")>]}":
            depth -= 1
            if depth == 0 and character == ")":
                closing = index
                break
        elif character == "," and depth == 1:
            pieces.append(content[start:index].strip())
            start = index + 1
    if closing < 0:
        return content
    pieces.append(content[start:closing].strip())
    parameters = ",\n".join(f"    {piece}" for piece in pieces if piece)
    return f"{content[: opening + 1]}\n{parameters}){content[closing + 1 :]}"


def _source(
    item: Mapping[str, object], docfx_root: PurePosixPath
) -> tuple[str | None, int | None]:
    source = item.get("source")
    if not isinstance(source, dict) or not source.get("path"):
        return None, None
    path = PurePosixPath(os.path.normpath(str(docfx_root / str(source["path"])))).as_posix()
    if path.startswith("../") or path.startswith("/"):
        raise ReferenceError(f"{item['uid']} has a source path outside the repository: {path}")
    line = source.get("startLine")
    return path, int(line) + 1 if isinstance(line, int) else None


def _generic_definition(uid: str) -> str:
    """Map a constructed type UID such as ``N.Box{System.Int32}.Nested`` to ``N.Box`1.Nested``."""
    output: list[str] = []
    index = 0
    while index < len(uid):
        character = uid[index]
        if character != "{":
            output.append(character)
            index += 1
            continue
        depth, arguments, index = 1, 1, index + 1
        while index < len(uid) and depth:
            if uid[index] == "{":
                depth += 1
            elif uid[index] == "}":
                depth -= 1
            elif uid[index] == "," and depth == 1:
                arguments += 1
            index += 1
        output.append(f"`{arguments}")
    return "".join(output)


def _source_url(path: str, line: int | None) -> str:
    return f"{SOURCE_BASE}{path}" + (f"#L{line}" if line else "")


def _namespace_anchor(namespace: str) -> str:
    return "namespace-" + namespace.lower().replace(".", "-")


def _short_name(uid: str) -> str:
    return uid.split("(", 1)[0].rsplit(".", 1)[-1].split("`", 1)[0]


def _framework_slug(uid: str) -> str:
    return re.sub(r"`(\d+)", r"-\1", uid.split("(", 1)[0]).lower()


def escape(text: str) -> str:
    """Escape prose so Markdown and MDX treat it literally."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _code(text: str) -> str:
    fence = "``" if "`" in text else "`"
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def _cell(markdown: str) -> str:
    first = markdown.split("\n\n", 1)[0]
    return " ".join(first.split()).replace("|", "\\|") or " "


def _inline(markdown: str) -> str:
    return " ".join(markdown.split()) if "\n```" not in markdown else markdown


def _first_sentence(text: str) -> str:
    match = re.match(r"(.+?[.!?])(?:\s|$)", text)
    return (match.group(1) if match else text)[:240]


def _plain(value: object) -> str:
    """Return a fragment's visible text without markup, for metadata descriptions."""
    if not value:
        return ""
    collector = _TextCollector()
    collector.feed(str(value))
    return " ".join("".join(collector.parts).split())


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "xref":
            href = dict(attrs).get("href") or ""
            self.parts.append(_short_name(unquote(href.split("?", 1)[0])))

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _markdown(value: object, context: _Context) -> str:
    """Convert a DocFX HTML fragment to Markdown, resolving every cross-reference."""
    if value is None or value == "":
        return ""
    if isinstance(value, list):
        return "\n\n".join(_markdown(entry, context) for entry in value if entry)
    converter = _FragmentConverter(context)
    converter.feed(str(value))
    converter.close()
    return converter.result()


class _FragmentConverter(HTMLParser):
    """Translate the small HTML vocabulary DocFX emits for XML comments into Markdown."""

    _BLOCK_BREAK = "\n\n"

    def __init__(self, context: _Context) -> None:
        super().__init__(convert_charrefs=True)
        self.context = context
        self.output: list[str] = []
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.capture: list[str] | None = None
        self.lists: list[str] = []
        self.pre: list[str] | None = None
        self.pre_language = ""
        self.table: list[list[str]] | None = None
        self.cell: list[str] | None = None

    def _emit(self, text: str) -> None:
        if self.cell is not None:
            self.cell.append(text)
        elif self.capture is not None:
            self.capture.append(text)
        else:
            self.output.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if self.pre is not None and tag != "code":
            raise ReferenceError(f"unsupported <{tag}> inside a code block")
        if tag == "pre":
            self.pre = []
            return
        if tag == "code" and self.pre is not None:
            language = values.get("class", "")
            self.pre_language = (
                language.removeprefix("lang-") if language.startswith("lang-") else ""
            )
            return
        self.stack.append((tag, values))
        if tag in {"code", "xref", "a", "b", "strong", "i", "em"}:
            if self.capture is not None:
                raise ReferenceError(f"nested inline <{tag}> is not supported")
            self.capture = []
        elif tag == "p":
            self._emit(self._BLOCK_BREAK)
        elif tag == "br":
            self.stack.pop()
            self._emit("  \n")
        elif tag in {"ul", "ol"}:
            self.lists.append(tag)
            self._emit("\n")
        elif tag == "li":
            marker = "1." if self.lists and self.lists[-1] == "ol" else "-"
            self._emit("\n" + "  " * (len(self.lists) - 1) + marker + " ")
        elif tag == "table":
            self.table = []
        elif tag == "tr":
            if self.table is None:
                raise ReferenceError("<tr> outside a table")
            self.table.append([])
        elif tag in {"td", "th"}:
            self.cell = []
        elif tag in {"thead", "tbody", "div", "span", "summary", "remarks"}:
            pass
        else:
            raise ReferenceError(f"unsupported documentation markup <{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in {"br"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre" and self.pre is not None:
            code = "".join(self.pre).strip("\n")
            self.pre = None
            self._emit(f"\n\n```{self.pre_language}\n{code}\n```\n\n")
            return
        if tag == "code" and self.pre is not None:
            return
        if not self.stack or self.stack[-1][0] != tag:
            if tag in {"br"}:
                return
            raise ReferenceError(f"unbalanced </{tag}> in documentation markup")
        _tag, values = self.stack.pop()
        if tag in {"code", "xref", "a", "b", "strong", "i", "em"}:
            text = "".join(self.capture or [])
            self.capture = None
            self._emit(self._inline(tag, values, text))
        elif tag == "p":
            self._emit(self._BLOCK_BREAK)
        elif tag in {"ul", "ol"}:
            self.lists.pop()
            self._emit("\n\n")
        elif tag in {"td", "th"} and self.table is not None and self.cell is not None:
            self.table[-1].append(" ".join("".join(self.cell).split()).replace("|", "\\|"))
            self.cell = None
        elif tag == "table" and self.table is not None:
            rows, self.table = self.table, None
            if rows:
                width = max(len(row) for row in rows)
                padded = [row + [""] * (width - len(row)) for row in rows]
                lines = ["| " + " | ".join(padded[0]) + " |", "|" + "---|" * width]
                lines.extend("| " + " | ".join(row) + " |" for row in padded[1:])
                self._emit("\n\n" + "\n".join(lines) + "\n\n")

    def _inline(self, tag: str, values: dict[str, str], text: str) -> str:
        if tag == "code":
            return _code(text)
        if tag in {"b", "strong"}:
            return f"**{escape(text)}**"
        if tag in {"i", "em"}:
            return f"*{escape(text)}*"
        if tag == "xref":
            target = unquote(values.get("href", "").split("?", 1)[0])
            if not target:
                raise ReferenceError("cross-reference without a target")
            reference = self.context.references.get(target, {})
            label = text or str(
                reference.get("nameWithType")
                if self.context.items.get(target, {}).get("type") not in _TYPE_KINDS
                and reference.get("nameWithType")
                else reference.get("name") or _short_name(target)
            )
            return self.context.link(target, label, code=not text)
        href = values.get("href", "")
        if href.startswith(_KEYWORD_LINK):
            return _code(text)
        if not href:
            return escape(text)
        return f"[{escape(text)}]({href})"

    def handle_data(self, data: str) -> None:
        if self.pre is not None:
            self.pre.append(data)
        elif self.capture is not None:
            self.capture.append(data)
        else:
            self._emit(escape(data))

    def result(self) -> str:
        if self.stack or self.pre is not None:
            raise ReferenceError("unterminated documentation markup")
        text = "".join(self.output)
        text = re.sub(r"[ \t]*\n[ \t]*\n\s*", "\n\n", text)
        return text.strip()


# --- extraction ---------------------------------------------------------------------------


def fingerprint(root: Path) -> str:
    """Hash every input that can change the extracted metadata or the rendered pages."""
    csharp = root / "src" / "csharp"
    inputs: list[Path] = []
    for project in ("AnyInfer", "AnyInfer.Maintenance"):
        directory = csharp / project
        inputs.extend(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix in {".cs", ".csproj", ".json", ".props", ".targets"}
            and not any(part in _FINGERPRINT_IGNORED for part in path.relative_to(directory).parts)
        )
    inputs.extend(
        path
        for path in (
            csharp / "Directory.Build.props",
            csharp / "global.json",
            root / ".config" / "dotnet-tools.json",
            root / "website" / "docfx.json",
            root / "scripts" / "generate_csharp_reference.py",
            root / "scripts" / "check_csharp_docs.py",
        )
        if path.is_file()
    )
    digest = hashlib.sha256()
    for path in sorted(set(inputs), key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def _dotnet(root: Path, *arguments: str, runner: Callable[..., object]) -> None:
    if shutil.which("dotnet") is None:
        raise ReferenceError(
            "the C# API reference needs the .NET SDK selected by src/csharp/global.json; "
            "install it, then run `dotnet tool restore` from src/csharp"
        )
    try:
        runner(["dotnet", *arguments], cwd=root / "src" / "csharp", check=True)
    except subprocess.CalledProcessError as error:
        hint = (
            " (run `dotnet tool restore` from src/csharp to install the pinned DocFX)"
            if arguments[:2] == ("tool", "run")
            else ""
        )
        raise ReferenceError(f"`dotnet {' '.join(arguments)}` failed{hint}") from error


def run_inventory(
    root: Path, output: Path, *, runner: Callable[..., object] = subprocess.run
) -> Path:
    """Build the maintenance tool and write the assembly's documentation inventory."""
    _dotnet(
        root,
        "run",
        "--project",
        "AnyInfer.Maintenance/AnyInfer.Maintenance.csproj",
        "--configuration",
        "Release",
        "--",
        "--documentation-api",
        "--output",
        str(output),
        runner=runner,
    )
    return output


def extract(root: Path, *, runner: Callable[..., object] = subprocess.run) -> Path:
    """Return a cache directory holding current metadata and inventory, extracting if stale."""
    cache = root / "website" / ".cache" / "csharp-reference"
    key = fingerprint(root)
    destination = cache / key
    if (destination / "complete").is_file():
        return destination
    config = json.loads((root / "website" / "docfx.json").read_text(encoding="utf-8"))
    output = (root / "website" / config["metadata"][0]["dest"]).resolve()
    if cache.resolve() not in output.parents:
        raise ReferenceError("website/docfx.json must write below website/.cache/csharp-reference")
    shutil.rmtree(output, ignore_errors=True)
    _dotnet(
        root, "tool", "run", "docfx", "--", "metadata", "../../website/docfx.json", runner=runner
    )
    staging = cache / f"{key}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copytree(output, staging / "metadata")
    run_inventory(root, staging / "inventory.json", runner=runner)
    (staging / "complete").write_text(key + "\n", encoding="utf-8")
    for stale in cache.iterdir():
        if (
            stale.is_dir()
            and stale.name not in {staging.name, output.name}
            and len(stale.name) == 64
        ):
            shutil.rmtree(stale, ignore_errors=True)
    staging.rename(destination)
    return destination


def build(root: Path | None = None, *, version: str | None = None) -> Reference:
    """Extract (or reuse) metadata, render the reference, and prove inventory coverage."""
    root = (root or ROOT).resolve()
    if version is None:
        try:
            from .docs_common import read_versions
        except ImportError:
            from docs_common import read_versions
        version = str(read_versions(root)["csharp"])
    cache = extract(root)
    reference = render(load_metadata(cache / "metadata"), version=version)
    findings = reference_findings(load_inventory(cache / "inventory.json"), reference.symbols)
    if findings:
        raise ReferenceError(
            "generated C# reference does not match the documentation inventory:\n  "
            + "\n  ".join(findings[:50])
        )
    return reference


FIXTURE = Path("tests") / "fixtures" / "csharp-reference"


def refresh_fixture(
    root: Path, destination: Path, *, runner: Callable[..., object] = subprocess.run
) -> None:
    """Rebuild the representative extraction fixture's committed artifacts.

    The fixture project exercises declaration shapes the real assembly may not expose
    (generic and nested types, by-reference parameters, async streams, operators, records,
    ``inheritdoc`` and deliberate documentation gaps). Its compiler XML, inventory and DocFX
    metadata are committed so the renderer and checker tests run without the .NET SDK; the
    branch-dependent ``source.remote`` block DocFX records is removed for reproducibility.
    """
    import yaml

    fixture = root / FIXTURE
    project = fixture / "ReferenceFixture" / "ReferenceFixture.csproj"
    relative = Path("..") / ".." / project.relative_to(root)
    _dotnet(root, "build", str(relative), "--configuration", "Release", runner=runner)
    config = json.loads((fixture / "docfx.json").read_text(encoding="utf-8"))
    output = (fixture / config["metadata"][0]["dest"]).resolve()
    shutil.rmtree(output, ignore_errors=True)
    docfx_config = Path("..") / ".." / FIXTURE / "docfx.json"
    _dotnet(root, "tool", "run", "docfx", "--", "metadata", str(docfx_config), runner=runner)
    shutil.rmtree(destination, ignore_errors=True)
    (destination / "metadata").mkdir(parents=True)
    for path in sorted(output.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        header, _, body = text.partition("\n")
        document = yaml.safe_load(body)
        for item in document.get("items", []):
            if isinstance(item.get("source"), dict):
                item["source"].pop("remote", None)
        normalized = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=1000)
        (destination / "metadata" / path.name).write_text(
            f"{header}\n{normalized}", encoding="utf-8"
        )
    assembly = fixture / "ReferenceFixture" / "bin" / "Release" / "net8.0"
    shutil.copyfile(assembly / "ReferenceFixture.xml", destination / "ReferenceFixture.xml")
    _dotnet(
        root,
        "run",
        "--project",
        "AnyInfer.Maintenance/AnyInfer.Maintenance.csproj",
        "--configuration",
        "Release",
        "--",
        "--documentation-api",
        "--output",
        str((destination / "inventory.json").resolve()),
        "--assembly",
        str((assembly / "ReferenceFixture.dll").resolve()),
        runner=runner,
    )


def main(argv: Iterable[str] | None = None) -> int:
    """Render the reference into a directory for inspection, or refresh the test fixture."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path, help="directory for generated pages")
    action.add_argument(
        "--refresh-fixture",
        type=Path,
        nargs="?",
        const=ROOT / FIXTURE / "expected",
        help="rebuild the committed extraction fixture (default: its expected/ directory)",
    )
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    if arguments.refresh_fixture is not None:
        refresh_fixture(ROOT, arguments.refresh_fixture)
        return 0
    reference = build()
    for page in reference.pages:
        destination = arguments.output / page.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(page.content, encoding="utf-8")
    (arguments.output / "symbols.json").write_text(
        json.dumps(dict(sorted(reference.symbols.items())), indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {len(reference.pages)} pages and {len(reference.symbols)} symbols", file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
