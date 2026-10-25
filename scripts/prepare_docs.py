"""Stage existing documentation for Docusaurus without modifying authored Markdown."""

from __future__ import annotations

import argparse
import builtins
import hashlib
import importlib
import json
import posixpath
import re
import shutil
from collections.abc import Callable
from html import escape as html_escape
from pathlib import Path

try:  # Package import for tests and build scripts run from the repository root.
    from .docs_common import Page, build_pages, load_navigation, read_versions, redirects_for
except ImportError:  # Direct ``python scripts/prepare_docs.py`` execution.
    from docs_common import Page, build_pages, load_navigation, read_versions, redirects_for

_API_MARKER = re.compile(r"^(?P<indent>\s*):::\s+(?P<symbol>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*$")
_SNIPPET_MARKER = re.compile(r'^(?P<indent>\s*)--8<--\s+["\'](?P<target>[^"\']+)["\']\s*$')
_LINK = re.compile(r"(?P<image>!?)\[([^\]]*)\]\(([^)\s]+)(\s+[^)]*)?\)")
_ADMONITION = re.compile(r'^(?P<indent>\s*)!!!\s+(?P<kind>\w+)(?:\s+"(?P<title>[^"]+)")?\s*$')
_TAB = re.compile(r'^(?P<indent>\s*)===\s+"(?P<title>[^"]+)"\s*$')
_DETAILS = re.compile(r'^(?P<indent>\s*)\?\?\?\+?\s+\w+(?:\s+"(?P<title>[^"]+)")?\s*$')
_MATERIAL_ICON = re.compile(
    r':material-(?P<name>[a-z0-9-]+):(?:\{\s*title="(?P<title>[^"]*)"\s*\})?'
)
_MDX_PROTECTED = re.compile(
    r"(`+.*?`+|</?(?:a|abbr|b|blockquote|br|code|details|div|em|figcaption|figure|"
    r"h[1-6]|hr|i|img|input|li|ol|p|pre|section|span|strong|summary|table|tbody|td|"
    r"tfoot|th|thead|tr|ul|Tabs|TabItem)(?:\s[^>]*)?/?>)",
    re.DOTALL,
)
_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.*?)\s*$")
_AUTHOR_ID = re.compile(r"\s*\{\s*#(?P<identifier>[\w.-]+)\s*\}\s*$")
_HEADING_ATTRIBUTES = re.compile(r"\s*\{\s*(?:[.#][\w.-]+\s*)+\}\s*$")
_API_ANCHOR = re.compile(r'<a\s+id="(?P<identifier>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)"\s*></a>')
_GENERATED_REFERENCE = re.compile(r"\[([^\]]+)\]\(#(?P<target>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\)")
_BUILTIN_REFERENCE = frozenset(name for name in vars(builtins) if not name.startswith("_")) | {
    "Any",
    "Callable",
    "Final",
    "Literal",
    "Never",
    "NoReturn",
    "Protocol",
    "Self",
    "TypeAlias",
}


def prepare(
    root: Path | None = None,
    output_dir: Path | None = None,
    renderer: Callable[..., str] | None = None,
    *,
    allow_outside_generated: bool = False,
    incremental: bool = False,
) -> dict[str, object]:
    """Prepare all current documentation and return the manifest written to disk."""
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    docs_dir = root / "docs"
    output_dir = output_dir or root / "website" / ".generated"
    _validate_output_dir(root, output_dir, allow_outside_generated)
    navigation = load_navigation(root / "website" / "navigation.json")
    pages = build_pages(docs_dir, navigation)
    page_map = {page.source: page for page in pages}
    if renderer is None:
        renderer = _cached_reference_renderer(root, _reference_renderer())

    prepared: list[tuple[Page, str]] = []
    hidden_tocs: set[str] = set()
    for page in pages:
        source_path = docs_dir / page.source
        source = source_path.read_text(encoding="utf-8")
        if _hides_table_of_contents(source):
            hidden_tocs.add(page.source)
        content = _strip_frontmatter(source)
        rendered = _prepare_markdown(content, page, page_map, root, renderer)
        prepared.append((page, rendered))

    symbol_urls = _symbol_urls(prepared)
    documents: list[tuple[Path, str]] = []
    for page, rendered in prepared:
        rendered = _rewrite_generated_references(rendered, symbol_urls)
        if page.source == "index.md":
            documents.append((output_dir / "home.mdx", rendered))
            continue
        suffix = ".mdx" if _needs_mdx(rendered) else ".md"
        destination = output_dir / page.sdk / Path(page.source).with_suffix(suffix)
        metadata = _frontmatter(page, hide_toc=page.source in hidden_tocs)
        documents.append((destination, metadata + rendered))

    manifest: dict[str, object] = {
        "pages": [page.manifest() for page in pages],
        "versions": read_versions(root),
        "redirects": redirects_for(pages),
        "navigation": navigation,
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if output_dir.exists() and not incremental:
        shutil.rmtree(output_dir)
    for sdk in ("shared", "python", "csharp", "static"):
        (output_dir / sdk).mkdir(parents=True, exist_ok=True)
    expected = {path.resolve() for path, _content in documents}
    for destination, content in documents:
        _write_text_if_changed(destination, content)
    expected.update(_copy_static(root, output_dir))
    manifest_path = output_dir / "manifest.json"
    _write_text_if_changed(manifest_path, manifest_text)
    expected.add(manifest_path.resolve())
    if incremental:
        _remove_stale_files(output_dir, expected)
    return manifest


def _validate_output_dir(root: Path, output_dir: Path, allow_outside_generated: bool) -> None:
    """Reject accidental recursive cleanup outside the generated website directory."""
    target = output_dir.resolve()
    generated = (root / "website" / ".generated").resolve()
    if target == generated or generated in target.parents:
        return
    if not allow_outside_generated:
        raise ValueError(
            f"refusing to clear {target}; pass allow_outside_generated=True only for "
            "an explicit test root"
        )


def _reference_renderer() -> Callable[..., str]:
    try:
        module = importlib.import_module("scripts.generate_python_reference")
    except ModuleNotFoundError:
        module = importlib.import_module("generate_python_reference")
    render = getattr(module, "render_symbol", None)
    if not callable(render):
        raise RuntimeError("scripts.generate_python_reference.render_symbol is required")
    return render


def _cached_reference_renderer(root: Path, render: Callable[..., str]) -> Callable[..., str]:
    """Cache successful default API renders behind a source-content fingerprint."""
    cache_dir = root / "website" / ".cache" / "python-reference" / _reference_fingerprint(root)

    def cached(qualified: str, options: dict[str, object] | None = None) -> str:
        payload = json.dumps({"qualified": qualified, "options": options}, sort_keys=True)
        destination = cache_dir / f"{hashlib.sha256(payload.encode('utf-8')).hexdigest()}.md"
        if destination.is_file():
            return destination.read_text(encoding="utf-8")
        rendered = render(qualified, options)
        if not isinstance(rendered, str):
            raise TypeError(f"API renderer returned {type(rendered).__name__}, not text")
        cache_dir.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        return rendered

    return cached


def _reference_fingerprint(root: Path) -> str:
    """Hash documented Python sources and renderer inputs, without relying on mtimes."""
    sources = root / "src" / "python"
    ignored = frozenset({".cache", "__pycache__", "build", "dist", ".venv", "venv"})
    files = [
        path
        for path in sources.rglob("*.py")
        if not any(part in ignored for part in path.relative_to(sources).parts)
    ]
    files.extend(
        (root / "scripts" / "generate_python_reference.py", root / "website" / "requirements.lock")
    )
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _frontmatter(page: Page, *, hide_toc: bool = False) -> str:
    layout = "hide_table_of_contents: true\n" if hide_toc else ""
    return f"---\nslug: {page.slug}\ntitle: {page.title}\n{layout}---\n\n"


def _hides_table_of_contents(source: str) -> bool:
    """Carry the existing Material TOC setting into Docusaurus layout metadata."""
    if not source.startswith("---\n"):
        return False
    closing = source.find("\n---\n", len("---\n"))
    if closing < 0:
        return False
    frontmatter = source[len("---\n") : closing]
    if re.search(r"(?m)^hide_table_of_contents:[ \t]*true[ \t]*$", frontmatter):
        return True
    legacy = re.search(r"(?m)^hide:[ \t]*\n((?:[ \t]+[^\n]*(?:\n|$))*)", frontmatter)
    return legacy is not None and bool(re.search(r"(?m)^[ \t]+-[ \t]+toc[ \t]*$", legacy[1]))


def _copy_static(root: Path, output_dir: Path) -> set[Path]:
    """Copy public documentation artwork, styles, and source examples once per build."""
    static = output_dir / "static"
    expected: set[Path] = set()
    for source in (root / "docs" / "assets", root / "docs" / "stylesheets"):
        if source.exists():
            expected.update(_copy_tree_if_changed(source, static / source.name))
    # Only public source examples named from docs are assets. Copying the repository's
    # examples tree also picks up local C# bin/obj output, which must never ship on Pages.
    for source in (root / "docs" / "examples" / "starter.py",):
        if source.is_file():
            destination = static / source.relative_to(root / "docs")
            _copy_file_if_changed(source, destination)
            expected.add(destination.resolve())
    for source in (root / "examples" / "csharp-sdk",):
        if source.is_dir():
            expected.update(_copy_public_sources(source, static / source.relative_to(root)))
    return expected


def _copy_public_sources(source: Path, destination: Path) -> set[Path]:
    """Copy readable source examples while excluding build products and caches."""
    ignored = frozenset({"bin", "obj", "node_modules", ".cache", "__pycache__"})
    copied: set[Path] = set()
    for path in source.rglob("*"):
        if not path.is_file() or any(part in ignored for part in path.relative_to(source).parts):
            continue
        target = destination / path.relative_to(source)
        _copy_file_if_changed(path, target)
        copied.add(target.resolve())
    return copied


def _copy_tree_if_changed(source: Path, destination: Path) -> set[Path]:
    """Mirror static source files without changing timestamps for identical bytes."""
    copied: set[Path] = set()
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        target = destination / path.relative_to(source)
        _copy_file_if_changed(path, target)
        copied.add(target.resolve())
    return copied


def _copy_file_if_changed(source: Path, destination: Path) -> None:
    """Copy only changed asset bytes so preview watchers do not reload every page."""
    source_bytes = source.read_bytes()
    if destination.is_file() and destination.read_bytes() == source_bytes:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source_bytes)


def _write_text_if_changed(destination: Path, content: str) -> None:
    """Atomically publish changed text while leaving unchanged watcher inputs alone."""
    if destination.is_file() and destination.read_text(encoding="utf-8") == content:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(destination)


def _remove_stale_files(output_dir: Path, expected: set[Path]) -> None:
    """Remove stale generated files without deleting watched directories."""
    for path in output_dir.rglob("*"):
        if path.is_file() and path.resolve() not in expected:
            path.unlink()


def _prepare_markdown(
    content: str,
    page: Page,
    page_map: dict[str, Page],
    root: Path,
    renderer: Callable[..., str],
) -> str:
    content = _inject_legacy_heading_anchors(content)
    content = content.replace("{{ extra.anyinfer_version }}", str(read_versions(root)["python"]))
    content = _expand_snippets(content, root)
    content = _expand_api_markers(content, renderer)
    content = _convert_admonitions(content)
    content = _convert_details(content)
    content, has_tabs = _convert_tabs(content)
    content = _rewrite_links(content, page, page_map, root)
    content = _convert_html_and_attributes(content)
    content = _convert_material_icons(content)
    content = _escape_mdx_syntax(content)
    if has_tabs:
        content = (
            "import Tabs from '@theme/Tabs';\n"
            "import TabItem from '@theme/TabItem';\n\n" + content
        )
    return content


def _strip_frontmatter(content: str) -> str:
    """Remove legacy Material front matter before importing the home into TSX."""
    if not content.startswith("---\n"):
        return content
    closing = content.find("\n---\n", len("---\n"))
    return content[closing + len("\n---\n") :] if closing >= 0 else content


def _needs_mdx(content: str) -> bool:
    """Use MDX only for pages whose prepared content contains JSX or component imports."""
    return "import Tabs " in content or bool(
        re.search(r"<[/]?(?:[A-Za-z][^>]*className=|details\b)", content)
    )


def _expand_snippets(content: str, root: Path) -> str:
    lines: list[str] = []
    fenced = False
    for line in content.splitlines(keepends=True):
        match = _SNIPPET_MARKER.match(line.rstrip("\r\n"))
        if match is None:
            lines.append(line)
            if line.lstrip().startswith("```"):
                fenced = not fenced
            continue
        target, region = _split_region(match.group("target"))
        path = (root / target).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError(f"snippet {target!r} does not exist below repository root")
        snippet = path.read_text(encoding="utf-8")
        if region is not None:
            snippet = _extract_region(snippet, target, region)
        indent = match.group("indent")
        language = {".py": "python", ".cs": "csharp", ".json": "json", ".toml": "toml"}.get(
            path.suffix, ""
        )
        if not fenced:
            lines.append(f"{indent}```{language}\n")
        lines.extend(f"{indent}{part}\n" for part in snippet.rstrip("\n").splitlines())
        if not fenced:
            lines.append(f"{indent}```\n")
    return "".join(lines)


def _split_region(target: str) -> tuple[str, str | None]:
    path, separator, region = target.rpartition(":")
    return (path, region) if separator and path else (target, None)


def _extract_region(text: str, target: str, region: str) -> str:
    start = re.compile(rf"--8<--\s*\[start:{re.escape(region)}\]")
    end = re.compile(rf"--8<--\s*\[end:{re.escape(region)}\]")
    kept: list[str] = []
    active = False
    for line in text.splitlines(keepends=True):
        if start.search(line):
            active = True
            continue
        if end.search(line):
            if not active:
                break
            return "".join(kept)
        if active:
            kept.append(line)
    raise ValueError(f"snippet region {region!r} was not found in {target!r}")


def _expand_api_markers(content: str, renderer: Callable[..., str]) -> str:
    lines: list[str] = []
    fenced = False
    for line in content.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        match = None if fenced else _API_MARKER.match(line.rstrip("\r\n"))
        if match is None:
            lines.append(line)
            continue
        rendered = renderer(match.group("symbol"))
        if not isinstance(rendered, str) or not rendered.strip():
            raise ValueError(f"API renderer returned no content for {match.group('symbol')!r}")
        if re.search(r"^\s*:::", rendered, re.MULTILINE):
            raise ValueError(f"API renderer left a directive for {match.group('symbol')!r}")
        indent = match.group("indent")
        lines.extend(f"{indent}{part}\n" for part in rendered.rstrip("\n").splitlines())
    return "".join(lines)


def _convert_admonitions(content: str) -> str:
    lines = content.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    while index < len(lines):
        match = _ADMONITION.match(lines[index].rstrip("\r\n"))
        if match is None:
            output.append(lines[index])
            index += 1
            continue
        indent = match.group("indent")
        kind = match.group("kind")
        title = f" {match.group('title')}" if match.group("title") else ""
        output.append(f"{indent}:::{kind}{title}\n")
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and not line.startswith(indent + "    "):
                break
            output.append(line[len(indent) + 4 :] if line.startswith(indent + "    ") else line)
            index += 1
        output.append(f"{indent}:::\n")
    return "".join(output)


def _convert_tabs(content: str) -> tuple[str, bool]:
    lines = content.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    converted = False
    group_number = 0
    while index < len(lines):
        match = _TAB.match(lines[index].rstrip("\r\n"))
        if match is None:
            output.append(lines[index])
            index += 1
            continue
        converted = True
        group_number += 1
        tab_number = 0
        indent = match.group("indent")
        output.append(f"{indent}<Tabs>\n")
        while True:
            title = match.group("title")
            value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "tab"
            tab_number += 1
            output.append(
                f'{indent}<TabItem value="{value}" label="{title}">\n'
                f'{indent}<a id="__tabbed_{group_number}_{tab_number}"></a>\n\n'
            )
            index += 1
            while index < len(lines):
                line = lines[index]
                if line.strip() and not line.startswith(indent + "    "):
                    break
                output.append(
                    line[len(indent) + 4 :] if line.startswith(indent + "    ") else line
                )
                index += 1
            output.append(f"{indent}</TabItem>\n")
            blanks: list[str] = []
            while index < len(lines) and not lines[index].strip():
                blanks.append(lines[index])
                index += 1
            if index < len(lines):
                next_match = _TAB.match(lines[index].rstrip("\r\n"))
                if next_match is not None and next_match.group("indent") == indent:
                    match = next_match
                    continue
            output.append(f"{indent}</Tabs>\n")
            output.extend(blanks)
            break
    return "".join(output), converted


def _convert_details(content: str) -> str:
    """Translate Material's collapsible admonitions into portable HTML details blocks."""
    lines = content.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    while index < len(lines):
        match = _DETAILS.match(lines[index].rstrip("\r\n"))
        if match is None:
            output.append(lines[index])
            index += 1
            continue
        indent = match.group("indent")
        title = match.group("title") or "Details"
        output.append(f"{indent}<details>\n{indent}<summary>{title}</summary>\n\n")
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and not line.startswith(indent + "    "):
                break
            output.append(line[len(indent) + 4 :] if line.startswith(indent + "    ") else line)
            index += 1
        output.append(f"{indent}</details>\n")
    return "".join(output)


def _convert_html_and_attributes(content: str) -> str:
    def convert(part: str) -> str:
        part = re.sub(r'\s+markdown(?:="[^"]*")?', "", part)
        part = re.sub(r'\bclass="', "className=\"", part)
        part = re.sub(r"<(br|hr|img|input)(\s[^>]*?)?(?<!/)>", r"<\1\2 />", part)
        part = re.sub(
            r"^(?P<hashes>#{1,6})\s+(?P<title>.*?)\s+\{\s*(?P<classes>(?:\.[\w-]+\s*)+)\}\s*$",
            _heading_with_classes,
            part,
            flags=re.MULTILINE,
        )
        part = re.sub(
            r"^(?P<link>\[[^\]]+\]\([^\n)]+\))\n"
            r"\{\s*(?P<classes>(?:\.[\w-]+\s*)+)\}\s*$",
            _styled_link,
            part,
            flags=re.MULTILINE,
        )
        return re.sub(r"^\s*\{:?\s*\.[^}]+\}\s*$\n?", "", part, flags=re.MULTILINE)

    return _outside_fences(content, convert)


def _heading_with_classes(match: re.Match[str]) -> str:
    """Render a Material heading attribute list as an MDX heading element."""
    level = len(match.group("hashes"))
    classes = " ".join(token[1:] for token in match.group("classes").split())
    return f'<h{level} className="{classes}">{match.group("title")}</h{level}>'


def _styled_link(match: re.Match[str]) -> str:
    """Turn a validated Material link attribute list into an MDX anchor after routing."""
    link = _LINK.fullmatch(match.group("link"))
    if link is None:
        return match.group(0)
    label, target = link.group(2), link.group(3)
    if not target.startswith(("/", "https://", "http://")):
        return match.group(0)
    classes = " ".join(token[1:] for token in match.group("classes").split())
    return (
        f'<a className="{classes}" href="{html_escape(target, quote=True)}">'
        f'{html_escape(label)}</a>'
    )


def _inject_legacy_heading_anchors(content: str) -> str:
    """Place MkDocs-compatible heading anchors beside their rendered source headings."""
    try:
        from markdown.extensions.toc import slugify
    except ImportError as error:  # pragma: no cover - docs toolchain always installs markdown
        raise RuntimeError("documentation preparation requires the markdown package") from error

    seen: dict[str, int] = {}

    def transform(part: str) -> str:
        lines: list[str] = []
        for line in part.splitlines(keepends=True):
            match = _HEADING.match(line.rstrip("\r\n"))
            if match is None:
                lines.append(line)
                continue
            title = match.group("title")
            explicit = _AUTHOR_ID.search(title)
            visible_title = _HEADING_ATTRIBUTES.sub("", title)
            slug_title = _MATERIAL_ICON.sub("", visible_title)
            identifier = explicit.group("identifier") if explicit else slugify(slug_title, "-")
            occurrence = seen.get(identifier, 0)
            seen[identifier] = occurrence + 1
            if occurrence:
                identifier = f"{identifier}_{occurrence}"
            lines.append(f'<a id="{identifier}"></a>\n\n{match.group("hashes")} {visible_title}\n')
        return "".join(lines)

    return _outside_fences(content, transform)


def _symbol_urls(prepared: list[tuple[Page, str]]) -> dict[str, str]:
    """Index explicit renderer anchors, with unambiguous export aliases as fallbacks."""
    exact: dict[str, str] = {}
    aliases: dict[str, set[str]] = {}
    for page, content in prepared:
        for match in _API_ANCHOR.finditer(content):
            identifier = match.group("identifier")
            exact.setdefault(identifier, f"{page.url}#{identifier}")
            aliases.setdefault(identifier.rsplit(".", 1)[-1], set()).add(identifier)
    for alias, identifiers in aliases.items():
        if len(identifiers) == 1:
            identifier = next(iter(identifiers))
            exact.setdefault(alias, exact[identifier])
    return exact


def _rewrite_generated_references(content: str, symbol_urls: dict[str, str]) -> str:
    """Point generated API references at documented anchors and drop false type links."""
    def replace(match: re.Match[str]) -> str:
        label, target = match.groups()
        destination = symbol_urls.get(target) or symbol_urls.get(target.rsplit(".", 1)[-1])
        if destination is not None:
            return f"[{label}]({destination})"
        if "." in target or target in _BUILTIN_REFERENCE:
            return label
        return match.group(0)

    return _outside_fences(content, lambda part: _GENERATED_REFERENCE.sub(replace, part))


def _convert_material_icons(content: str) -> str:
    """Replace Material icon shorthand with portable readable text before MDX parses it."""
    icons = {
        "check": "✓",
        "minus": "\u2212",
        "close": "✕",
        "alert": "⚠",
        "alert-circle": "⚠",
        "arrow-right": "→",
    }

    def replace(match: re.Match[str]) -> str:
        icon = icons.get(match.group("name"), "")
        title = match.group("title")
        return f"{icon} ({title})" if title else icon

    return _outside_fences(content, lambda part: _MATERIAL_ICON.sub(replace, part))


def _escape_mdx_syntax(content: str) -> str:
    """Escape prose braces and pseudo-tags while preserving Markdown code and known JSX."""
    def escape(part: str) -> str:
        tokens = _MDX_PROTECTED.split(part)
        for index in range(0, len(tokens), 2):
            tokens[index] = re.sub(
                r"<(https?://[^<>\s]+)>", r"[\1](\1)", tokens[index]
            )
            tokens[index] = re.sub(r"(?<!\\)([{}])", r"\\\1", tokens[index])
            tokens[index] = re.sub(r"<(?=[A-Za-z])", r"\\<", tokens[index])
        return "".join(tokens)

    return _outside_fences(content, escape)


def _rewrite_links(content: str, page: Page, page_map: dict[str, Page], root: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        image, label, target, suffix = (
            match.group("image"),
            match.group(2),
            match.group(3),
            match.group(4) or "",
        )
        if target.startswith(("#", "/", "http://", "https://", "mailto:")):
            return match.group(0)
        pathname, fragment = _split_fragment(target)
        candidate = posixpath.normpath((Path(page.source).parent / pathname).as_posix())
        if not candidate.endswith(".md"):
            candidate = f"{candidate}.md" if f"{candidate}.md" in page_map else candidate
        target_page = page_map.get(candidate)
        if target_page is not None:
            return f"{image}[{label}]({target_page.url}{fragment}{suffix})"
        resolved = (root / "docs" / Path(page.source).parent / pathname).resolve()
        docs_root = (root / "docs").resolve()
        if resolved.is_file() and docs_root in resolved.parents:
            return (
                f"{image}[{label}](/{resolved.relative_to(docs_root).as_posix()}"
                f"{fragment}{suffix})"
            )
        # Links to repository material (contracts, source, examples) retain an inspectable
        # upstream target when no staged documentation page owns the path.
        if root in resolved.parents and resolved.exists():
            return (
                f"{image}[{label}](https://github.com/anthturner/AnyInfer/blob/main/"
                f"{resolved.relative_to(root).as_posix()}{fragment}{suffix})"
            )
        return match.group(0)

    return _outside_fences(content, lambda part: _LINK.sub(replace, part))


def _split_fragment(target: str) -> tuple[str, str]:
    pathname, marker, fragment = target.partition("#")
    return pathname, f"#{fragment}" if marker else ""


def _outside_fences(content: str, transform: Callable[[str], str]) -> str:
    """Apply a Markdown transformation only to prose, leaving fenced examples literal."""
    parts = re.split(r"(^\s*```[^\n]*\n.*?^\s*```\s*$)", content, flags=re.MULTILINE | re.DOTALL)
    return "".join(part if part.lstrip().startswith("```") else transform(part) for part in parts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incremental", action="store_true", help="update a watched staging tree")
    arguments = parser.parse_args()
    prepare(incremental=arguments.incremental)
