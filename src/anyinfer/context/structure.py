"""Language detection and structural extraction.

An *extract* is what a file looks like with its bodies removed: imports, declarations,
signatures, and headings. It is what the ``tiered`` strategy sends when a whole file will
not fit — a signature tells a model far more per token than an arbitrary truncation does.

Extraction is regex-based rather than parser-based, deliberately. A parser exists for
exactly one language; this table covers twelve with a few lines each, degrades to
"no extract" instead of raising on malformed input, and adds no dependencies. Adding a
language is one suffix entry plus one pattern list.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath

__all__ = [
    "MAX_EXTRACT_CHARS",
    "MAX_SECTION_CHARS",
    "SMALL_FILE_VERBATIM_BYTES",
    "TRUNCATION_MARKER",
    "detect_language",
    "is_generated_path",
    "structural_extract",
]

MAX_EXTRACT_CHARS = 12_000
"""Ceiling on one extract. Beyond this the extract stops being a summary."""

MAX_SECTION_CHARS = 2_000
"""Ceiling on one contiguous run of kept lines, so a header-only file cannot dominate."""

SMALL_FILE_VERBATIM_BYTES = 512
"""Files this small are their own best extract — summarizing them saves nothing."""

TRUNCATION_MARKER = "[truncated structural extract]"
"""Appended when an extract hits `MAX_EXTRACT_CHARS`, so truncation is never silent."""

_SUFFIX_LANGUAGES: Mapping[str, str] = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".cxx": "cpp",
    ".dart": "dart",
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".md": "markdown",
    ".mjs": "javascript",
    ".ps1": "powershell",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "shell",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}
"""Suffix to language name.

``.h`` is deliberately absent: it may be C or C++, and guessing wrong produces a worse
extract than none. ``.txt`` likewise has no structure to extract.
"""

_DECLARATION_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "c": (
        r"^\s*[\w*]+\s+\**\w+\s*\([^;]*\)\s*\{?\s*$",
        r"^\s*#(include|define)\b",
        r"^\s*(typedef|struct|enum|union)\b",
    ),
    "cpp": (
        r"^\s*(class|struct|namespace|template|enum|using)\b",
        r"^\s*[\w:<>*&\s]+\s+\**[\w:]+\s*\([^;]*\)\s*(const)?\s*\{?\s*$",
        r"^\s*#(include|define)\b",
    ),
    "csharp": (
        r"^\s*(using|namespace)\b",
        r"^\s*\[[\w.]+.*\]\s*$",
        r"^\s*(public|private|protected|internal|static|abstract|sealed|partial|"
        r"override|virtual|async)[\w\s<>,\[\]]*\s[\w<>]+\s*\(?",
    ),
    "dart": (
        r"^\s*(import|export|part)\b",
        r"^\s*(class|mixin|extension|enum|typedef)\b",
        r"^\s*@\w+",
        r"^\s*[\w<>?,\s]+\s+\w+\s*\([^;]*\)\s*(async)?\s*\{?\s*$",
    ),
    "go": (r"^\s*(package|import)\b", r"^\s*(func|type|const|var)\b"),
    "java": (
        r"^\s*(package|import)\b",
        r"^\s*@\w+",
        r"^\s*(public|private|protected|static|final|abstract|class|interface|enum|"
        r"record)\b",
    ),
    "javascript": (
        r"^\s*(import|export|require)\b",
        r"^\s*(async\s+)?function\b",
        r"^\s*(class|const|let|var)\s+\w+\s*=",
        r"^\s*class\b",
    ),
    "kotlin": (
        r"^\s*(package|import)\b",
        r"^\s*(class|object|interface|enum|fun|val|var|data class)\b",
    ),
    "markdown": (r"^#{1,6}\s+\S", r"^\s*[-*]\s+\*\*"),
    "powershell": (r"^\s*(using|Import-Module)\b", r"^\s*(function|filter|class|enum|param)\b"),
    "python": (r"^\s*(import|from)\b", r"^\s*(class|def|async def)\b", r"^\s*@\w+"),
    "ruby": (r"^\s*(require|require_relative|include)\b", r"^\s*(class|module|def|attr_\w+)\b"),
    "rust": (
        r"^\s*(use|mod|pub mod|extern crate)\b",
        r"^\s*(pub\s+)?(fn|struct|enum|trait|impl|type|const|static)\b",
        r"^\s*#\[\w+",
    ),
    "shell": (r"^\s*(function\s+)?\w+\s*\(\)\s*\{", r"^\s*(source|\.)\s+\S"),
    "typescript": (
        r"^\s*(import|export)\b",
        r"^\s*(async\s+)?function\b",
        r"^\s*(export\s+)?(class|interface|type|enum|const|abstract class)\b",
        r"^\s*@\w+",
    ),
    "xml": (r"^\s*<[\w:]+", r"^\s*<\?xml"),
    "yaml": (r"^\S+:", r"^\s*-\s+\w+:"),
}
"""Per-language line patterns worth keeping. Everything else is a body, and is dropped."""

_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    language: tuple(re.compile(pattern) for pattern in patterns)
    for language, patterns in _DECLARATION_PATTERNS.items()
}

_GENERATED_SEGMENTS = frozenset(
    {
        "vendor",
        "third_party",
        "thirdparty",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        "generated",
        ".venv",
        "venv",
    }
)
_GENERATED_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".g.dart",
    ".freezed.dart",
    ".g.cs",
    ".designer.cs",
    ".pb.go",
    "_pb2.py",
    ".generated.ts",
    ".lock",
)
_GENERATED_PREFIXES = ("moc_", "ui_", "qrc_")


def detect_language(path: str) -> str | None:
    """Infer a language from a path's suffix, or ``None`` when it is ambiguous."""
    return _SUFFIX_LANGUAGES.get(PurePosixPath(path.lower()).suffix)


def is_generated_path(path: str) -> bool:
    """Whether a path looks machine-generated or vendored.

    Offered as a public helper because the decision belongs at *collection* time — the
    library never walks a filesystem, but an app deciding what to collect needs the same
    heuristic AnyInfer would have applied.
    """
    lowered = path.lower()
    parts = PurePosixPath(lowered).parts
    if any(segment in _GENERATED_SEGMENTS for segment in parts):
        return True
    name = PurePosixPath(lowered).name
    if any(name.endswith(suffix) for suffix in _GENERATED_SUFFIXES):
        return True
    return any(name.startswith(prefix) for prefix in _GENERATED_PREFIXES)


def structural_extract(content: str, *, language: str | None) -> str:
    """Reduce a document to its declarations, imports, and headings.

    Args:
        content: The document text.
        language: The detected language. ``None`` yields no extract — guessing patterns
            for an unknown language produces noise, not a summary.

    Returns:
        The extract, or ``""`` when none could be produced. Files under
        `SMALL_FILE_VERBATIM_BYTES` are returned whole: they are already their own
        summary.
    """
    if not content:
        return ""
    if len(content.encode("utf-8")) <= SMALL_FILE_VERBATIM_BYTES:
        return content
    patterns = _COMPILED.get(language or "")
    if not patterns:
        return ""

    kept: list[str] = []
    section_chars = 0
    previous_kept = False

    for line in content.splitlines():
        try:
            matched = any(pattern.match(line) for pattern in patterns)
        except (re.error, ValueError):
            # A pathological line is not a reason to fail the whole reduction.
            matched = False

        if not matched:
            previous_kept = False
            section_chars = 0
            continue

        if previous_kept and section_chars >= MAX_SECTION_CHARS:
            continue

        stripped = line.rstrip()
        kept.append(stripped)
        section_chars = section_chars + len(stripped) if previous_kept else len(stripped)
        previous_kept = True

    if not kept:
        return ""

    extract = "\n".join(kept)
    if len(extract) > MAX_EXTRACT_CHARS:
        extract = extract[:MAX_EXTRACT_CHARS].rstrip() + "\n" + TRUNCATION_MARKER
    return extract
