#!/usr/bin/env python
"""Developer task runner for AnyInfer — one entry point for every routine command.

Run ``python workspace.py`` with no arguments to list the verbs.

Three properties are deliberate:

1. **Third-party gates shell out to the same command CI runs.** No verb reimplements
   ruff's or pytest's behaviour through a Python API, so a green `check` run means
   the same thing a green CI run does. The command is echoed before it runs, which keeps
   the runner discoverable — you can always copy the line and run it yourself.
2. **First-party maintenance code lives here, not in a scripts directory.** The docstring
   coverage gate, the doc-link check, the conformance-matrix generator, and the demo
   bundle build are functions in this module: one file to search, one ``--help`` that
   lists everything, and CI reaches them through the same verbs contributors run.
3. **It works in a fresh clone.** At import time this module needs nothing from
   ``anyinfer`` and nothing outside the standard library, so ``python workspace.py
   setup`` bootstraps an environment that does not exist yet. Verbs that do need the
   installed project import it lazily and fail with the actionable message instead of a
   traceback.

Verbs are registered by decorating a function with :func:`verb`; the parser, the help
listing, and the dispatch table are all derived from that registry.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import inspect
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import sysconfig
import textwrap
import time
import tomllib
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.request import urlopen

if TYPE_CHECKING:
    from anyinfer.testing.conformance import CaseResult


def _use_utf8_output() -> None:
    """Make stdout/stderr tolerate non-ASCII regardless of the console code page.

    A default Windows console is cp1252, which cannot encode the box-drawing and arrow
    characters used in the summaries — printing one raises ``UnicodeEncodeError`` and takes
    the whole run down. Reconfiguring to UTF-8 with ``errors="replace"`` means a legacy
    console degrades to a substituted glyph instead of a crash.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # A redirected or already-detached stream cannot be reconfigured; the runner
            # must still work, so this is best-effort.
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")


_use_utf8_output()

ArgumentAdder = Callable[[argparse.ArgumentParser], object]
"""Adds a verb's flags to its parser. The return value is discarded — argparse's
``add_argument`` returns an ``Action``, which callers have no use for."""

REPO_MARKERS = ("pyproject.toml", "src", "tests")
"""Files and directories that together identify an AnyInfer checkout."""


def _find_repository_root() -> Path | None:
    """Locate the checkout this runner should operate on.

    ``Path(__file__).parent`` is wrong for the installed console script: packaging copies
    this module into ``site-packages``, and running the gates from there would lint an
    empty directory and report a screenful of spurious failures. The working directory is
    authoritative, so the search starts there and walks up; the module's own directory is
    the fallback for ``python workspace.py`` invoked from elsewhere.

    Returns:
        The checkout root, or ``None`` when the runner was invoked outside one.
    """
    candidates = [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parent]
    for candidate in candidates:
        if all((candidate / marker).exists() for marker in REPO_MARKERS):
            return candidate
    return None


_ROOT = _find_repository_root()
ROOT = _ROOT if _ROOT is not None else Path.cwd()
"""The checkout the verbs operate on. Verbs refuse to run when none was found."""


def _warn_if_shadowed() -> str | None:
    """Detect a stale installed copy of this module shadowing the repository's.

    Older releases shipped ``workspace.py`` in the wheel, so an environment installed
    from one may still hold a copy in ``site-packages`` that wins on ``sys.path`` —
    making edits to the repository's runner appear to do nothing. Silent staleness is
    the worst version of this, so it is reported.

    Returns:
        A warning message, or ``None`` when the loaded module is the repository's.
    """
    loaded = Path(__file__).resolve()
    checkout = (ROOT / "workspace.py").resolve()
    if loaded == checkout or not checkout.exists():
        return None
    try:
        if loaded.read_bytes() == checkout.read_bytes():
            return None
    except OSError:
        return None
    return (
        f"running an installed copy of workspace.py that differs from {checkout}.\n"
        f"  loaded: {loaded}\n"
        f"  Re-run `pip install -e .` to pick up your edits, or use "
        f"`python workspace.py` directly."
    )


# Paths every quality gate operates on, matching .github/workflows/ci.yml.
LINT_PATHS = ("src", "tests", "workspace.py")

# Build outputs and tool caches. Directories are removed wholesale; the glob patterns are
# swept recursively. Nothing here is ever a source file.
BUILD_DIRS = ("build", "dist", "site", "htmlcov")
CACHE_DIRS = (".mypy_cache", ".ruff_cache", ".pytest_cache")
CACHE_GLOBS = ("**/__pycache__", "**/*.egg-info")
CACHE_FILES = (".coverage",)

__all__ = ["StepError", "Verb", "main", "verb"]


# ---------------------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Verb:
    """One registered subcommand."""

    name: str
    summary: str
    handler: Callable[[argparse.Namespace], int]
    group: str = "General"
    add_arguments: ArgumentAdder | None = None
    passthrough: bool = False
    """Whether trailing arguments are forwarded verbatim to the underlying tool."""


REGISTRY: dict[str, Verb] = {}
GROUP_ORDER: list[str] = []


def verb(
    name: str,
    summary: str,
    *,
    group: str = "General",
    arguments: ArgumentAdder | None = None,
    passthrough: bool = False,
) -> Callable[[Callable[[argparse.Namespace], int]], Callable[[argparse.Namespace], int]]:
    """Register a function as a ``workspace`` verb.

    Args:
        name: The verb as typed on the command line.
        summary: One-line description shown in ``workspace --help``.
        group: Heading the verb is listed under.
        arguments: Callback that adds this verb's flags to its parser.
        passthrough: Collect trailing arguments and forward them to the tool.

    Returns:
        The handler, unchanged, so decorated functions stay directly callable.
    """

    def decorator(
        handler: Callable[[argparse.Namespace], int],
    ) -> Callable[[argparse.Namespace], int]:
        if group not in GROUP_ORDER:
            GROUP_ORDER.append(group)
        REGISTRY[name] = Verb(
            name=name,
            summary=summary,
            handler=handler,
            group=group,
            add_arguments=arguments,
            passthrough=passthrough,
        )
        return handler

    return decorator


# ---------------------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------------------


class StepError(Exception):
    """A step failed. Carries the exit code the runner should return."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _c(code: str, text: str) -> str:
    """Colorize for a terminal, and not otherwise."""
    if os.environ.get("NO_COLOR"):
        return text
    if not os.environ.get("FORCE_COLOR") and not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    """Render text bold."""
    return _c("1", text)


def dim(text: str) -> str:
    """Render text dimmed."""
    return _c("2", text)


def green(text: str) -> str:
    """Render text green."""
    return _c("32", text)


def red(text: str) -> str:
    """Render text red."""
    return _c("31", text)


def yellow(text: str) -> str:
    """Render text yellow."""
    return _c("33", text)


def cyan(text: str) -> str:
    """Render text cyan."""
    return _c("36", text)


def run(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    quiet: bool = False,
) -> int:
    """Run a command from the repository root, echoing it first.

    Args:
        command: argv of the command to run.
        env: Extra environment variables overlaid on the current environment.
        check: Raise :class:`StepError` on a non-zero exit.
        quiet: Suppress the echoed command line.

    Returns:
        The command's exit code.

    Raises:
        StepError: If the command exits non-zero and ``check`` is set, or is not installed.
    """
    if not quiet:
        print(dim(f"$ {' '.join(command)}"), flush=True)

    # Child processes inherit the console code page too, and pytest's own output contains
    # non-ASCII (the conformance matrix symbols, em-dashes in test ids).
    merged = {"PYTHONIOENCODING": "utf-8", **os.environ, **(env or {})}
    try:
        completed = subprocess.run(command, cwd=ROOT, env=merged, check=False)
    except FileNotFoundError as error:
        raise StepError(
            f"{command[0]!r} is not installed — run `workspace setup` to install the "
            f"development dependencies"
        ) from error

    if check and completed.returncode != 0:
        raise StepError(f"{command[0]} failed", completed.returncode)
    return completed.returncode


def python(*args: str, **kwargs: object) -> int:
    """Run a module or script with the *current* interpreter.

    Using ``sys.executable`` rather than a bare ``python`` is what keeps the runner honest
    inside a virtualenv that has not been activated.
    """
    return run([sys.executable, *args], **kwargs)  # type: ignore[arg-type]


def _tool_path(name: str) -> Path | None:
    """Resolve a console-script tool to this interpreter's own copy, if it has one.

    The interpreter's scripts directory is checked first; outside a virtualenv, the user
    scheme's scripts directory is checked too. The second matters on a system interpreter
    whose site-packages is not writable: pip silently falls back to a user install there,
    which puts ``mkdocs.exe`` and friends in a directory that is routinely absent from
    PATH — ``setup`` then succeeds while every tool looks "not installed".

    Returns:
        The tool's path, or ``None`` when neither directory has a copy.
    """
    executable = f"{name}.exe" if os.name == "nt" else name
    directories = [Path(sysconfig.get_path("scripts"))]
    if sys.prefix == sys.base_prefix:  # pip never user-installs inside a virtualenv
        with contextlib.suppress(KeyError):
            directories.append(Path(sysconfig.get_path("scripts", f"{os.name}_user")))
    for directory in directories:
        candidate = directory / executable
        if candidate.exists():
            return candidate
    return None


def tool(name: str, *args: str, **kwargs: object) -> int:
    """Run a console-script tool, preferring the one installed for this interpreter.

    A globally-installed ``ruff`` on PATH may not be the one pinned for this project, so
    the interpreter's own copy (see :func:`_tool_path`) wins when it has one.
    """
    resolved = _tool_path(name)
    executable = str(resolved) if resolved is not None else name
    return run([executable, *args], **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------
# Step sequencing
# ---------------------------------------------------------------------------------------


@dataclass
class Report:
    """Outcome of a multi-step verb, so one failure does not hide the others."""

    results: list[tuple[str, bool, float]] = field(default_factory=list)

    def record(self, name: str, ok: bool, seconds: float) -> None:
        """Record one step's outcome."""
        self.results.append((name, ok, seconds))

    @property
    def failed(self) -> list[str]:
        """Names of the steps that failed."""
        return [name for name, ok, _ in self.results if not ok]

    def render(self) -> None:
        """Print the summary table."""
        print()
        print(bold("Summary"))
        width = max((len(name) for name, _, _ in self.results), default=0) + 2
        for name, ok, seconds in self.results:
            mark = green("PASS") if ok else red("FAIL")
            print(f"  {mark}  {name:<{width}} {dim(f'{seconds:.1f}s')}")

        if self.failed:
            print()
            print(
                red(f"{len(self.failed)} of {len(self.results)} steps failed: ")
                + ", ".join(self.failed)
            )
        else:
            print()
            print(green(f"All {len(self.results)} steps passed."))


@dataclass(frozen=True)
class Phase:
    """One named phase of a multi-step verb.

    A phase groups the steps that prove one thing (``docs-check`` is three commands but
    one verdict), and is the unit ``check --skip``/``--only`` selects by.
    """

    name: str
    what: str
    """One-line description, shown in the phase heading."""
    steps: tuple[tuple[str, Callable[[], int]], ...]


def run_phases(phases: Sequence[Phase], *, fail_fast: bool) -> int:
    """Run phases in order, reporting every outcome.

    Each phase is announced with a colored heading before its steps run, so a long log
    always says which phase it is in. Steps within a failed phase still run (a broken
    doc link should not hide a missing docstring), as do later phases unless
    ``fail_fast`` is set.

    Returns:
        ``0`` if every step of every phase passed, else ``1``.
    """
    report = Report()
    for phase in phases:
        print()
        print(cyan(bold(f"━━ phase: {phase.name} ")) + cyan(f"· {phase.what}"))
        failed_here = False
        for label, step in phase.steps:
            if len(phase.steps) > 1:
                print(bold(f"── {label} "))
            started = time.monotonic()
            try:
                code = step()
            except StepError as error:
                print(red(str(error)))
                code = error.code
            elapsed = time.monotonic() - started
            record_as = phase.name if len(phase.steps) == 1 else f"{phase.name}: {label}"
            report.record(record_as, code == 0, elapsed)
            failed_here = failed_here or code != 0
        if failed_here and fail_fast:
            break

    report.render()
    return 1 if report.failed else 0


# ---------------------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------------------


@verb(
    "setup",
    "Install the project and all development dependencies (editable).",
    group="Environment",
    arguments=lambda p: p.add_argument(
        "--extras",
        default="all,dev",
        help="extras to install (default: all,dev)",
    ),
)
def cmd_setup(args: argparse.Namespace) -> int:
    """Install the project in editable mode with its development extras."""
    python("-m", "pip", "install", "--upgrade", "pip")
    python("-m", "pip", "install", "-e", f".[{args.extras}]")
    print()
    print(green("Environment ready.") + " Try `workspace check` or `workspace demo`.")
    return 0


@verb("info", "Show interpreter, versions, and tool availability.", group="Environment")
def cmd_info(args: argparse.Namespace) -> int:
    """Report what this environment actually has, for debugging a broken setup."""
    print(bold("Interpreter"))
    print(f"  {sys.executable}")
    print(f"  Python {sys.version.split()[0]} on {sys.platform}")
    print(f"  repository: {ROOT}")

    print()
    print(bold("Packages"))
    # Versions come from the installed distribution metadata rather than a `__version__`
    # attribute: several projects (jsonschema among them) now deprecate that attribute.
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as distribution_version

    for package in ("anyinfer", "httpx2", "jsonschema", "PySide6", "markdown"):
        try:
            print(f"  {green('found')}    {package:<12} {distribution_version(package)}")
        except PackageNotFoundError:
            print(f"  {yellow('missing')}  {package}")

    print()
    print(bold("Tools"))
    for name in ("ruff", "mypy", "pytest", "lint-imports", "mkdocs"):
        found = _tool_path(name) is not None or shutil.which(name) is not None
        status = green("found") if found else yellow("missing")
        print(f"  {status}{'    ' if found else '  '}{name}")
    return 0


# ---------------------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------------------


GATE_ORDER = (
    "lint",
    "format",
    "types",
    "contracts",
    "test",
    "conformance",
    "docs-check",
    "docs-build",
)
"""Every phase ``check`` knows, in execution order: fastest feedback first (static
analysis, then the type checker, then the architecture contracts), the suite after the
cheap gates, and the documentation gates last because they partly re-run suite tests.

The set is exhaustive by design: every gate CI enforces is one of these phases, so a green
``check`` and a green CI run mean the same thing. Adding a gate to the pipeline means
adding a phase here, not a bare command to the workflow."""

DEFAULT_GATES = tuple(name for name in GATE_ORDER if name != "format")
"""What a bare ``check`` runs. ``format`` is opt-in (``--only=format``): the formatter is
deliberately not a gate — it reflows argv-style flag/value pairs one per line, which makes
the llama-server tuner and the provider payload builders materially harder to read."""


_DOCSTRING_INHERITED_EXEMPT = frozenset(
    {
        # dataclass and Exception machinery we do not author
        "__init__",
        "__eq__",
        "__repr__",
        "__hash__",
        "__setattr__",
        "__delattr__",
        "count",
        "index",
        "with_traceback",
        "add_note",
        "args",
    }
)
"""Members every exported class inherits; requiring docstrings for these is noise."""

_PUBLIC_SURFACES = (
    "anyinfer",
    "anyinfer.context",
    "anyinfer.local",
    "anyinfer.serve",
    "anyinfer.otel",
    "anyinfer.providers",
    "anyinfer.testing",
    "anyinfer.testing.conformance",
)
"""Namespaces that integrator or contributor documentation teaches directly."""

_PUBLIC_EXTRA_SYMBOLS = ("anyinfer.providers.llama_cpp.LlamaCppOptions",)
"""Documented public one-offs outside the surface modules."""


def _is_documented(obj: Any) -> bool:
    """Whether an object carries its own docstring."""
    doc = getattr(obj, "__doc__", None)
    return bool(doc and doc.strip())


def _check_class_member(owner: str, name: str, member: Any, failures: list[str]) -> None:
    """Check one attribute of an exported class."""
    if name.startswith("_") or name in _DOCSTRING_INHERITED_EXEMPT:
        return
    if not (
        inspect.isfunction(member)
        or inspect.ismethod(member)
        or isinstance(member, (property, classmethod, staticmethod))
    ):
        return
    target = member.fget if isinstance(member, property) else member
    if isinstance(member, (classmethod, staticmethod)):
        target = member.__func__
    if target is None:
        return
    if not _is_documented(target):
        failures.append(f"{owner}.{name}")


def _module_bindings(path: Path) -> tuple[list[str] | None, dict[str, bool]]:
    """Parse a module's exports and PEP 224 constant documentation."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    exported: list[str] | None = None
    documented: dict[str, bool] = {}
    for index, node in enumerate(tree.body):
        names: list[str] = []
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id == "__all__":
                        exported = list(ast.literal_eval(node.value))
                    else:
                        names.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            documented.setdefault(node.name, True)
            continue
        next_node = tree.body[index + 1] if index + 1 < len(tree.body) else None
        has_doc = (
            isinstance(next_node, ast.Expr)
            and isinstance(next_node.value, ast.Constant)
            and isinstance(next_node.value.value, str)
        )
        for name in names:
            documented[name] = documented.get(name, False) or has_doc
    return exported, documented


def _scan_public_boundaries() -> tuple[list[str], dict[str, bool]]:
    """Find undeclared public names and constant documentation states."""
    leaks: list[str] = []
    constant_docs: dict[str, bool] = {}
    for path in sorted((ROOT / "src" / "anyinfer").rglob("*.py")):
        if path.name == "__main__.py" or "__pycache__" in path.parts:
            continue
        exported, documented = _module_bindings(path)
        for name, has_doc in documented.items():
            constant_docs[name] = constant_docs.get(name, False) or has_doc
        if "_client" in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if exported is None:
            leaks.append(f"{relative}: no __all__")
            continue
        for name in documented:
            if not name.startswith("_") and name not in exported:
                leaks.append(f"{relative}: public name {name!r} not in __all__")
    return leaks, constant_docs


def _reference_directives() -> set[str]:
    """Return every mkdocstrings directive in the documentation."""
    directives: set[str] = set()
    for page in (ROOT / "docs").rglob("*.md"):
        text = page.read_text(encoding="utf-8")
        directives.update(re.findall(r"^::: +(\S+)", text, re.MULTILINE))
    return directives


def _referenced_object_ids(directives: set[str]) -> set[int]:
    """Resolve documented aliases so re-exports need not be rendered twice."""
    referenced: set[int] = set()
    for qualified in directives:
        parts = qualified.split(".")
        for boundary in range(len(parts), 0, -1):
            try:
                obj: Any = __import__(".".join(parts[:boundary]), fromlist=["*"])
            except ImportError:
                continue
            try:
                for part in parts[boundary:]:
                    obj = getattr(obj, part)
            except AttributeError:
                break
            referenced.add(id(obj))
            break
    return referenced


def _check_public_text(failures: list[str]) -> None:
    """Keep internal decision shorthand out of published prose and docstrings."""
    decision = re.compile(r"\bADR-\d{3}\b")
    for path in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
        if decision.search(path.read_text(encoding="utf-8")):
            failures.append(f"{path.relative_to(ROOT)} (contains internal decision shorthand)")


def _check_docstrings() -> int:
    """Check the public boundary, documentation, and API-reference coverage."""
    try:
        modules = [__import__(name, fromlist=["*"]) for name in _PUBLIC_SURFACES]
    except ImportError as error:
        raise StepError("anyinfer is not installed — run `workspace setup` first") from error

    failures, constant_docs = _scan_public_boundaries()
    directives = _reference_directives()
    referenced_ids = _referenced_object_ids(directives)
    _check_public_text(failures)
    checked = 0

    for module in modules:
        for name in getattr(module, "__all__", []):
            if name.startswith("_") or name == "__version__":
                continue
            checked += 1
            qualified = f"{module.__name__}.{name}"
            obj = getattr(module, name, None)
            if obj is None:
                failures.append(f"{qualified} (exported but not importable)")
                continue
            if qualified not in directives and id(obj) not in referenced_ids:
                failures.append(f"{qualified} (no ::: directive in docs/)")
            if inspect.isclass(obj):
                if not _is_documented(obj):
                    failures.append(qualified)
                for member_name, member in vars(obj).items():
                    _check_class_member(qualified, member_name, member, failures)
            elif inspect.isfunction(obj):
                if not _is_documented(obj):
                    failures.append(qualified)
            elif inspect.ismodule(obj):
                continue
            elif not constant_docs.get(name, False):
                failures.append(f"{qualified} (constant without a PEP 224 docstring)")

            doc = getattr(obj, "__doc__", "") or ""
            if re.search(r"\bADR-\d{3}\b", doc):
                failures.append(f"{qualified} (docstring contains internal decision shorthand)")

    for qualified in _PUBLIC_EXTRA_SYMBOLS:
        module_name, _, name = qualified.rpartition(".")
        module = __import__(module_name, fromlist=[name])
        obj = getattr(module, name)
        checked += 1
        if not _is_documented(obj):
            failures.append(qualified)
        if qualified not in directives:
            failures.append(f"{qualified} (no ::: directive in docs/)")

    if failures:
        print(f"{len(set(failures))} public-surface problem(s):\n", file=sys.stderr)
        for failure in sorted(set(failures)):
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"all {checked} exported symbols are documented and referenced; no leaks")
    return 0


_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

_MD_SKIP_DIRS = {
    ".git",
    ".tmp-tests",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "site",
    "build",
    "plans",
}
"""Directories whose Markdown is generated, third-party, or internal working notes whose
illustrative links are not meant to resolve — not ours to gate."""


def _markdown_files() -> list[Path]:
    """Every Markdown file worth checking."""
    return sorted(
        markdown
        for markdown in ROOT.rglob("*.md")
        if not any(part in _MD_SKIP_DIRS for part in markdown.relative_to(ROOT).parts)
    )


def _check_doc_links() -> int:
    """Fail on a broken relative link in the documentation.

    Documentation that points at files which do not exist is worse than missing
    documentation: it costs a reader their time and their trust. This checks every
    relative Markdown link in the repository's docs and top-level guides.
    """
    failures: list[str] = []

    for markdown in _markdown_files():
        text = markdown.read_text(encoding="utf-8", errors="replace")
        for match in _MD_LINK.finditer(text):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")) or not target:
                continue

            # Strip an anchor; the file is what we can verify.
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue

            resolved = (markdown.parent / path_part).resolve()
            if not resolved.exists():
                relative = markdown.relative_to(ROOT)
                failures.append(f"{relative}: {target}")

    if failures:
        print(f"{len(failures)} broken documentation link(s):\n", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"all relative links resolve across {len(_markdown_files())} markdown files")
    return 0


def _build_docs_site() -> int:
    """Build the published site with the strict build the Pages deploy runs.

    One function behind both entry points — the ``docs-build`` gate phase and
    ``workspace build docs`` — because a gate that runs a *different* build from the one
    that publishes is a gate that can pass while the deploy breaks.
    """
    return tool("mkdocs", "build", "--strict")


def _gate_phases(*, fix: bool) -> dict[str, Phase]:
    """The gate phases, keyed by the names ``--skip``/``--only`` accept.

    Args:
        fix: Let ruff rewrite files (lint applies fixes; format formats in place).
    """
    phases = [
        Phase(
            "lint",
            "ruff static analysis",
            (
                (
                    "ruff check",
                    lambda: tool("ruff", "check", *(["--fix"] if fix else []), *LINT_PATHS),
                ),
            ),
        ),
        Phase(
            "format",
            "ruff formatting (opt-in, never a default gate)",
            (
                (
                    "ruff format",
                    lambda: tool("ruff", "format", *([] if fix else ["--check"]), *LINT_PATHS),
                ),
            ),
        ),
        Phase("types", "mypy --strict over src and the runner", (("mypy", lambda: tool("mypy")),)),
        Phase(
            "contracts",
            "architecture contracts (import-linter, the ADRs)",
            (("lint-imports", lambda: tool("lint-imports")),),
        ),
        Phase(
            "test",
            "the full pytest suite, headless",
            (("pytest", lambda: tool("pytest", "-q", env=_headless_env())),),
        ),
        Phase(
            "conformance",
            "provider conformance and the serve invariants",
            (
                (
                    "conformance suite",
                    lambda: tool(
                        "pytest",
                        "tests/test_conformance.py",
                        "tests/test_ollama.py",
                        "-q",
                        env=_headless_env(),
                    ),
                ),
                (
                    "serve invariants (ADR-009)",
                    lambda: tool(
                        "pytest",
                        "tests/test_openai_roundtrip.py",
                        "tests/test_serve_app.py",
                        "-q",
                        env=_headless_env(),
                    ),
                ),
            ),
        ),
        Phase(
            "docs-check",
            "docstring coverage, doc links, runnable doc examples",
            (
                # The two checkers are functions in this module (property 2 in the module
                # docstring), called through their module-global names so tests can patch.
                ("docstring coverage", lambda: _check_docstrings()),
                ("doc links", lambda: _check_doc_links()),
                (
                    "doc examples",
                    lambda: tool(
                        "pytest", "tests/test_docs_examples.py", "-q", env=_headless_env()
                    ),
                ),
            ),
        ),
        Phase(
            "docs-build",
            "the strict site build the Pages deploy publishes",
            (("mkdocs build --strict", _build_docs_site),),
        ),
    ]
    return {phase.name: phase for phase in phases}


def _parse_gate_names(raw: str, option: str) -> tuple[str, ...]:
    """Split a ``--skip``/``--only`` value and reject names ``check`` does not have."""
    names = tuple(name.strip() for name in raw.split(",") if name.strip())
    unknown = [name for name in names if name not in GATE_ORDER]
    if unknown:
        raise StepError(
            f"{option} got unknown phase(s): {', '.join(unknown)}. "
            f"Valid phases, in run order: {', '.join(GATE_ORDER)}"
        )
    return names


def _check_arguments(p: argparse.ArgumentParser) -> object:
    """Flags for ``check``: phase selection (one of --skip/--only), --fix, --fail-fast."""
    selection = p.add_mutually_exclusive_group()
    selection.add_argument(
        "--skip",
        metavar="PHASES",
        help=f"comma-separated phases to leave out ({'|'.join(GATE_ORDER)})",
    )
    selection.add_argument(
        "--only",
        metavar="PHASES",
        help="comma-separated phases to run by themselves (same names as --skip)",
    )
    p.add_argument(
        "--fix",
        action="store_true",
        help="let the lint and format phases rewrite files instead of only checking",
    )
    return p.add_argument(
        "--fail-fast", action="store_true", help="stop at the first failing phase"
    )


@verb(
    "check",
    "Run every CI gate: lint, types, contracts, test, conformance, docs-check, docs-build.",
    group="Quality",
    arguments=_check_arguments,
)
def cmd_check(args: argparse.Namespace) -> int:
    """Run the quality gates, the same set CI enforces, as ordered phases.

    The phase list is the whole of CI: every step of every `ci.yml` job is one of these
    phases, so a green run here is a green run there (modulo the interpreter and OS
    matrix, which only the runners can cover).

    Phases, in run order — fastest feedback first, and the suite before the doc gates
    that partly re-run it:

      lint         ruff static analysis (--fix applies fixes)
      format       ruff formatting — OPT-IN via --only=format, never a default gate
      types        mypy --strict
      contracts    the architecture contracts (import-linter)
      test         the full pytest suite, headless
      conformance  provider conformance + the serve invariants (ADR-009)
      docs-check   docstring coverage, doc links, runnable doc examples
      docs-build   the strict site build the Pages deploy publishes

    Select phases with --skip=a,b or --only=a,b (mutually exclusive). Every selected
    phase runs even after one fails, so a single invocation tells you everything that is
    broken rather than only the first thing.
    """
    if args.only:
        wanted = set(_parse_gate_names(args.only, "--only"))
    elif args.skip:
        wanted = set(DEFAULT_GATES) - set(_parse_gate_names(args.skip, "--skip"))
    else:
        wanted = set(DEFAULT_GATES)

    phases = _gate_phases(fix=args.fix)
    selected = [phases[name] for name in GATE_ORDER if name in wanted]
    if not selected:
        print(yellow("No phases selected — nothing to do."))
        return 0
    return run_phases(selected, fail_fast=args.fail_fast)


_CONTRACTS_URL = "https://github.com/anthturner/AnyInfer/blob/main/contracts/README.md"
"""Absolute because the matrix page cannot link outside the mkdocs docs/ tree."""

_MATRIX_HEADER = """# Conformance matrix

**Generated from a real conformance run — do not edit by hand.**
Regenerate with `python workspace.py matrix`.

Legend: ✅ verified · ➖ declared unsupported · ❌ failing

Each cell is one parametrized test case executed against that adapter in fake-server mode.
A ➖ is an honest, declared limitation; it is not a pass.

"""

_MATRIX_FOOTER = f"""
## What the cases check

| Case | Verifies |
|---|---|
| `list_models` | Discovery returns models with non-empty ids. |
| `health` | The readiness probe answers with a boolean. |
| `non_streaming` | A buffered generation produces text and a valid finish reason. |
| `streaming` | Deltas arrive and concatenate to the final text (ordering guarantee 4). |
| `event_ordering` | All four ordering guarantees hold. |
| `ttft` | First-token timing is measured and consistent with total duration. |
| `usage` | Token counts are reported and internally consistent. |
| `usage_survives_streaming` | A trailing usage chunk reaches the result and the event stream. |
| `tool_calls` | Tool calls carry an id, a name, and parsed arguments. |
| `streaming_tool_calls` | Argument fragments reassemble by index. |
| `reasoning` | Reasoning streams as its own channel, excluded from the answer text. |
| `structured_output` | A schema request yields a validated value and records its mechanism. |
| `schema_repair` | The repair loop recovers an initially-invalid response. |
| `error_mapping` | Failures are typed, carry an attempt trail, and mark retryability. |
| `retry_after` | A rate-limited attempt is retried and recorded. |
| `byte_cap` | An oversized response is rejected rather than silently truncated. |
| `unknown_finish_reason` | An unrecognized finish reason normalizes instead of crashing. |

## Modes

- **fake-server** — in-process transports asserting we handle each protocol *shape*. Runs on
  every commit.
- **cassette** — recorded real traffic, asserting we handle what providers *actually send*.
- **live** — opt-in, requires credentials. `m365-copilot` is exempt: its authentication is
  interactive-only and cannot run headless.

## See also

- [Provider pages](../providers/README.md) for the human-readable version.
- [Contract snapshots]({_CONTRACTS_URL}) for the wire details each adapter depends on.
"""


async def _matrix_collect() -> dict[str, list[CaseResult]]:
    """Run every conformance harness the test suite defines."""
    try:
        from anyinfer.testing.conformance import run_conformance
    except ImportError as error:
        raise StepError("anyinfer is not installed — run `workspace setup` first") from error

    # The harnesses are defined by the test modules, which is the point: the published
    # matrix and the suite cannot disagree, because they run the same objects.
    sys.path.insert(0, str(ROOT / "tests"))
    import test_cohere_lmstudio
    import test_conformance
    import test_gemini
    import test_nebius
    import test_ollama
    import test_presets

    harnesses = {
        "openai-compat": test_conformance.HARNESS,
        "ollama": test_ollama.HARNESS,
        "gemini": test_gemini.HARNESS,
        "cohere": test_cohere_lmstudio.HARNESS,
        "lm-studio": test_cohere_lmstudio.LM_STUDIO_HARNESS,
        "nebius": test_nebius.HARNESS,
    }
    # Presets share one adapter, so one representative per quirk axis stands for all of
    # them rather than one row per preset: plain bearer auth, the renamed
    # output-token field, x-api-key auth, and the max_completion_tokens dialect.
    for preset_id in ("groq", "moonshot", "reka", "venice"):
        harnesses[preset_id] = test_presets._harness(
            test_presets.PRESETS_BY_ID[preset_id], "fake-model-small"
        )
    return {name: await run_conformance(h) for name, h in harnesses.items()}


def _matrix_render(results: dict[str, list[CaseResult]]) -> str:
    """Render the matrix as Markdown."""
    from datetime import date

    from anyinfer.testing.conformance import CONFORMANCE_CASES

    case_names = [case.name for case in CONFORMANCE_CASES]

    lines = [_MATRIX_HEADER]
    lines.append(f"Last generated: {date.today().isoformat()}.\n")
    lines.append("| Provider | " + " | ".join(case_names) + " |")
    lines.append("|---" * (len(case_names) + 1) + "|")

    for provider, provider_results in sorted(results.items()):
        by_name = {r.name: r for r in provider_results}
        cells = [by_name[name].symbol if name in by_name else "?" for name in case_names]
        lines.append(f"| {provider} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append(
        "Adapters without a harness yet (`openai`, `anthropic`, `azure-foundry`, "
        "`openrouter`, `copilot`, `m365-copilot`, `llama-cpp`, `deepseek`, `xai`, "
        "`bedrock`, `vertex`) are covered by their own dialect tests; "
        "the public matrix reports only shared-harness results. Expanding cassette-backed "
        "coverage is tracked as release follow-up work. "
        "The `groq`, `moonshot`, `reka` and `venice` rows exercise the shared adapter's "
        "quirk axes — bearer auth, the renamed output-token field, `x-api-key` auth, and "
        "the `max_completion_tokens` dialect. Every entry in the "
        "[preset registry](../providers/presets.md) is separately instantiated and checked "
        "for registry invariants; these rows do not claim a live upstream verification."
    )
    lines.append(_MATRIX_FOOTER)
    return "\n".join(lines)


@verb("matrix", "Regenerate the conformance matrix from an actual suite run.", group="Quality")
def cmd_matrix(args: argparse.Namespace) -> int:
    """Rewrite docs/reference/conformance-matrix.md from real results.

    The published matrix must never be hand-maintained: a hand-written table drifts from
    reality and then actively misleads. This runs the conformance suite against every
    adapter that has a harness and writes what the tests actually found.
    """
    results = asyncio.run(_matrix_collect())

    failures = [
        (provider, r.name, r.detail)
        for provider, rs in results.items()
        for r in rs
        if not r.passed and not r.skipped
    ]

    output = ROOT / "docs" / "reference" / "conformance-matrix.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_matrix_render(results), encoding="utf-8")
    print(f"wrote {output.relative_to(ROOT)}")

    if failures:
        print(f"\n{len(failures)} conformance failure(s):", file=sys.stderr)
        for provider, case, detail in failures:
            print(f"  {provider}/{case}: {detail}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------------------
# Running things
# ---------------------------------------------------------------------------------------


@verb(
    "demo",
    "Launch the PySide6 pack-in demo application.",
    group="Run",
    passthrough=True,
)
def cmd_demo(args: argparse.Namespace) -> int:
    """Run the demo app, forwarding any extra arguments to it."""
    from importlib.util import find_spec

    if find_spec("PySide6") is None:
        raise StepError(
            'PySide6 is not installed — run `workspace setup`, or `pip install -e ".[demo]"`'
        )
    return python("-m", "demo_app", *args.rest)


@verb(
    "serve",
    "Run the OpenAI-compatible loopback frontend.",
    group="Run",
    passthrough=True,
)
def cmd_serve(args: argparse.Namespace) -> int:
    """Start the serve frontend, forwarding any extra arguments."""
    return python("-m", "anyinfer.serve", *(args.rest or ["serve"]))


@verb(
    "web",
    "Build the site exactly as GitHub Pages will, and serve it for a look.",
    group="Run",
    arguments=lambda p: p.add_argument(
        "--port", type=int, default=8123, help="port to serve on (default: 8123)"
    ),
)
def cmd_web(args: argparse.Namespace) -> int:
    """Preview the exact artifact the Pages deploy publishes.

    ``workspace docs`` serves a live-reload development build; this verb instead runs the
    same strict build the deploy workflow runs and hosts the resulting ``site/`` directory
    on a loopback stdlib server — what you see is byte-for-byte what lands on GitHub
    Pages. Stop it with Ctrl+C.
    """
    _build_docs_site()
    print()
    print(
        green(f"Site built. Browse it at http://127.0.0.1:{args.port}/")
        + dim("  (Ctrl+C to stop)")
    )
    # Loopback only, like every other local server in this project.
    return python(
        "-m", "http.server", str(args.port), "--directory", "site", "--bind", "127.0.0.1"
    )


@verb("doctor", "Report detected hardware and the recommended local tier.", group="Run")
def cmd_doctor(args: argparse.Namespace) -> int:
    """Run the library's own environment diagnostic."""
    return python("-m", "anyinfer.serve", "doctor")


@verb("providers", "List every registered provider and what it needs.", group="Run")
def cmd_providers(args: argparse.Namespace) -> int:
    """List registered providers, including any installed third-party adapters."""
    return python("-m", "anyinfer.serve", "providers")


@verb(
    "docs",
    "Serve the documentation site locally with live reload.",
    group="Run",
    passthrough=True,
)
def cmd_docs(args: argparse.Namespace) -> int:
    """Serve the docs with mkdocs."""
    return tool("mkdocs", "serve", *args.rest)


# ---------------------------------------------------------------------------------------
# Build and clean
# ---------------------------------------------------------------------------------------


BUILD_TARGETS = ("wheel", "demo", "serve", "docs", "all")
"""What ``workspace build`` can produce. ``all`` expands to every artifact."""

BUILD_PLATFORMS = ("windows", "macos", "linux", "all")
"""Platforms ``workspace build`` accepts. ``all`` expands to the other three."""


def _host_platform() -> str:
    """The build-platform tag for the machine running this command."""
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def _build_wheel() -> int:
    """Build the wheel and sdist into ``dist/``.

    ``python -m build`` is preferred when available because it builds in an isolated
    environment, which is what catches a missing build dependency. Hatchling is the
    fallback so a plain dev environment can still produce a wheel.
    """
    from importlib.util import find_spec

    if find_spec("build") is not None:
        return python("-m", "build", "--outdir", "dist")

    if find_spec("hatchling") is None:
        raise StepError(
            "neither `build` nor `hatchling` is installed — "
            "run `pip install build` to build distributions"
        )
    print(dim("`build` is not installed; falling back to hatchling (no isolation)."))
    return python("-m", "hatchling", "build")


_DEMO_ENTRY_STUB = """\
'''PyInstaller entry point for the demo app.

Generated by `workspace build demo`. The real ``demo_app.__main__`` cannot be the entry
script directly: PyInstaller executes the entry file as a top-level script, where
``demo_app``'s relative imports have no parent package.
'''
import sys

from demo_app.app import main

sys.exit(main())
"""

_SERVE_ENTRY_STUB = """\
'''PyInstaller entry point for the AnyInfer sidecar.'''
import sys

from anyinfer.cli import main

sys.exit(main(["serve", *sys.argv[1:]]))
"""


def _bundle_platform_tag() -> str:
    """A short ``<os>-<arch>`` tag for the archive name, e.g. ``windows-x64``."""
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
        "i386": "x86",
        "i686": "x86",
    }.get(machine, machine)
    if arch == "x64" and sys.maxsize <= 2**32:
        # A 32-bit interpreter on a 64-bit OS produces a 32-bit executable, and the tag
        # names what the bundle *is*, not what the host could have built.
        arch = "x86"
    return f"{system}-{arch}"


def _project_version() -> str:
    """The version being bundled, read from pyproject.toml."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def _bundle_windows_icon(work_dir: Path) -> Path | None:
    """Convert the PNG icon to the .ico PyInstaller needs on Windows.

    Pillow is an optional build-time dependency; without it the executable simply keeps
    the default icon rather than failing the whole build.

    The guard tests ``os.name`` rather than ``sys.platform`` on purpose. mypy narrows
    ``sys.platform`` to the host it runs on, so under ``warn_unreachable`` the whole body
    below reads as dead code whenever the type check runs off Windows — which it does in
    CI. ``os.name`` is the same test at runtime and carries no such narrowing.
    """
    if os.name != "nt":
        return None
    try:
        from PIL import Image
    except ImportError:
        print("pillow is not installed - the executable will use the default icon")
        return None

    icon = work_dir / "anyinfer.ico"
    with Image.open(ROOT / "docs" / "assets" / "anyinfer-icon-512.png") as image:
        image.save(icon, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return icon


def _run_pyinstaller(
    entry: Path,
    work_dir: Path,
    *,
    name: str,
    windowed: bool,
    icon: Path | None,
    extra_args: Sequence[str] = (),
) -> Path:
    """Run PyInstaller and return the built application directory."""
    command = [
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        name,
        "--paths",
        str(ROOT / "src"),
        "--distpath",
        str(work_dir / "dist"),
        "--workpath",
        str(work_dir / "build"),
        "--specpath",
        str(work_dir),
    ]
    if windowed:
        command.append("--windowed")
    command.extend(extra_args)
    if icon is not None:
        command += ["--icon", str(icon)]
    command.append(str(entry))

    python(*command)
    return work_dir / "dist" / name


def _write_bundle_info(
    app_dir: Path,
    version: str,
    *,
    product: str,
    instructions: str,
) -> None:
    """Drop a provenance file beside a standalone executable."""
    (app_dir / "BUNDLE-INFO.txt").write_text(
        f"{product} {version} ({_bundle_platform_tag()})\n"
        f"https://github.com/anthturner/AnyInfer\n"
        f"\n{instructions.rstrip()}\n",
        encoding="utf-8",
    )
    shutil.copy2(ROOT / "LICENSE", app_dir / "LICENSE.txt")


def _zip_directory(app_dir: Path, archive: Path, *, root_name: str) -> None:
    """Zip the application directory, keeping a top-level folder inside the archive."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(app_dir.rglob("*")):
            bundle.write(path, Path(root_name) / path.relative_to(app_dir))


def _build_demo_bundle() -> int:
    """Build the standalone demo bundle the release workflow ships.

    Produces ``dist/bundle/anyinfer-demo-<platform>.zip``: a self-contained PyInstaller
    build of the pack-in PySide6 demo app that runs without a host Python. The archive
    name carries the platform but *not* the version, so the docs site can link to the
    newest build through GitHub's stable ``releases/latest/download/<asset>`` URLs; the
    version is recorded in the bundled ``BUNDLE-INFO.txt`` instead.

    Per AGENTS.md, the bundle never contains llama-server binaries, GGUF files, or model
    weights — the local subsystem fetches those at runtime by design.

    Requires ``pyinstaller`` (and optionally ``pillow`` for the Windows icon) on top of
    the ``demo`` extra; neither is a dev dependency because only release builds need them.
    """
    from importlib.util import find_spec

    if find_spec("PyInstaller") is None:
        raise StepError(
            "PyInstaller is not installed — run `pip install pyinstaller` "
            "(plus `pillow` for the Windows icon) to build the demo bundle"
        )

    version = _project_version()
    work_dir = ROOT / "build" / "demo-bundle"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    entry = work_dir / "demo_entry.py"
    entry.write_text(_DEMO_ENTRY_STUB, encoding="utf-8")

    app_dir = _run_pyinstaller(
        entry,
        work_dir,
        name="anyinfer-demo",
        windowed=True,
        icon=_bundle_windows_icon(work_dir),
        extra_args=(
            # Markdown resolves extensions through package metadata, and demo assets are
            # read via importlib.resources; neither is visible to static analysis.
            "--copy-metadata",
            "markdown",
            "--add-data",
            f"{ROOT / 'src' / 'demo_app' / 'assets'}{os.pathsep}demo_app/assets",
        ),
    )
    _write_bundle_info(
        app_dir,
        version,
        product="AnyInfer demo app",
        instructions=(
            "Run the anyinfer-demo executable in this directory. The app works fully\n"
            "offline against in-process fake providers; no credentials are required."
        ),
    )

    archive = ROOT / "dist" / "bundle" / f"anyinfer-demo-{_bundle_platform_tag()}.zip"
    _zip_directory(app_dir, archive, root_name="anyinfer-demo")
    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"built {archive.relative_to(ROOT)} ({size_mb:.1f} MiB) for version {version}")
    return 0


def _build_serve_bundle() -> int:
    """Build the standalone OpenAI-compatible sidecar bundle.

    Produces ``dist/bundle/anyinfer-serve-<platform>.zip``. It contains AnyInfer, the
    HTTP frontend, and every built-in pure-Python provider adapter, but no model weights,
    local runtime binaries, or optional cloud SDKs.
    """
    from importlib.util import find_spec

    if find_spec("PyInstaller") is None:
        raise StepError(
            "PyInstaller is not installed — run `pip install pyinstaller` to build "
            "the sidecar bundle"
        )
    if find_spec("uvicorn") is None:
        raise StepError("the serve extra is not installed — run `pip install '.[serve]'` first")

    version = _project_version()
    work_dir = ROOT / "build" / "serve-bundle"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    entry = work_dir / "serve_entry.py"
    entry.write_text(_SERVE_ENTRY_STUB, encoding="utf-8")
    app_dir = _run_pyinstaller(
        entry,
        work_dir,
        name="anyinfer-serve",
        windowed=False,
        icon=_bundle_windows_icon(work_dir),
        extra_args=(
            "--collect-submodules",
            "anyinfer.providers",
            "--collect-submodules",
            "uvicorn",
            "--collect-data",
            "anyinfer",
        ),
    )
    _write_bundle_info(
        app_dir,
        version,
        product="AnyInfer sidecar",
        instructions=(
            "Run `anyinfer-serve --config anyinfer.json`. The server binds to\n"
            "127.0.0.1 by default; use --help for exposure and authentication options."
        ),
    )
    executable = app_dir / ("anyinfer-serve.exe" if os.name == "nt" else "anyinfer-serve")
    run([str(executable), "--help"])
    _smoke_serve_executable(executable)

    archive = ROOT / "dist" / "bundle" / f"anyinfer-serve-{_bundle_platform_tag()}.zip"
    _zip_directory(app_dir, archive, root_name="anyinfer-serve")
    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"built {archive.relative_to(ROOT)} ({size_mb:.1f} MiB) for version {version}")
    return 0


def _smoke_serve_executable(executable: Path) -> None:
    """Start a frozen sidecar and verify its unauthenticated read-only endpoints."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(executable), "--port", str(port)],
        cwd=executable.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise StepError(
                    f"the frozen sidecar exited during its smoke test ({process.returncode})"
                )
            try:
                with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                    health = response.read()
                with urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=0.5) as response:
                    models = response.read()
                if b'"status":"ok"' in health and b'"data"' in models:
                    print("standalone sidecar health and model-list smoke test passed")
                    return
            except OSError:
                time.sleep(0.1)
        raise StepError("the frozen sidecar did not become healthy within 15 seconds")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@verb(
    "build",
    "Build packages, standalone applications, or the docs site.",
    group="Build",
    arguments=lambda p: (
        p.add_argument(
            "target",
            nargs="?",
            choices=BUILD_TARGETS,
            default="wheel",
            help="what to build (default: wheel)",
        ),
        p.add_argument(
            "platform",
            nargs="?",
            choices=BUILD_PLATFORMS,
            default=None,
            help="platform for native bundles (default: this machine's)",
        ),
    ),
)
def cmd_build(args: argparse.Namespace) -> int:
    """Build artifacts: ``workspace build [wheel|demo|serve|docs|all] [platform]``.

    The wheel is pure Python (``py3-none-any``) and serves every platform and
    architecture, so it is built once regardless of the platform argument. The demo and
    sidecar bundles are native PyInstaller builds: each can only be produced on the
    platform and architecture it targets, so this machine builds its own and the workflow's
    native runners build the rest — Windows x86_64, macOS arm64/x86_64, and Linux
    x86_64/arm64 (see ``.github/workflows/release.yml``). Windows x86 (32-bit) gets no
    demo bundle because PySide6 ships no 32-bit Qt wheels; the wheel covers it.

    ``docs`` builds the site into ``site/`` with the same strict build the Pages deploy
    runs; ``workspace web`` serves that artifact for a look.
    """
    host = _host_platform()
    targets = ("wheel", "demo", "serve", "docs") if args.target == "all" else (args.target,)
    requested = args.platform or host
    platforms = ("windows", "macos", "linux") if requested == "all" else (requested,)

    phases: list[Phase] = []
    if "wheel" in targets:
        phases.append(
            Phase(
                "wheel",
                "sdist + wheel into dist/ (serves every platform)",
                (("wheel + sdist", _build_wheel),),
            )
        )
    if "demo" in targets:
        for target_platform in platforms:
            if target_platform == host:
                # The same tag the bundle stamps into the archive name, so the phase
                # heading matches the artifact it produces.
                tag = _bundle_platform_tag()
                phases.append(
                    Phase(
                        "demo",
                        f"standalone PyInstaller bundle ({tag})",
                        (("demo bundle", _build_demo_bundle),),
                    )
                )
            elif requested == "all":
                print(
                    dim(
                        f"skipping the {target_platform} demo bundle — PyInstaller cannot "
                        f"cross-compile from {host}; the release workflow builds it on a "
                        "native runner."
                    )
                )
            else:
                raise StepError(
                    f"the {target_platform} demo bundle cannot be built on {host} — "
                    "PyInstaller only builds for the machine it runs on. The release "
                    "workflow (.github/workflows/release.yml) builds every platform on "
                    "native runners."
                )
    if "serve" in targets:
        for target_platform in platforms:
            if target_platform == host:
                tag = _bundle_platform_tag()
                phases.append(
                    Phase(
                        "serve",
                        f"standalone sidecar bundle ({tag})",
                        (("sidecar bundle", _build_serve_bundle),),
                    )
                )
            elif requested == "all":
                print(
                    dim(
                        f"skipping the {target_platform} sidecar bundle — PyInstaller cannot "
                        f"cross-compile from {host}; the release workflow builds it on a "
                        "native runner."
                    )
                )
            else:
                raise StepError(
                    f"the {target_platform} sidecar bundle cannot be built on {host} — "
                    "PyInstaller only builds for the machine it runs on. The release "
                    "workflow (.github/workflows/release.yml) builds every platform on "
                    "native runners."
                )
    if "docs" in targets:
        phases.append(
            Phase(
                "docs",
                "the documentation site, strict (the Pages artifact)",
                (("mkdocs build --strict", _build_docs_site),),
            )
        )
    if not phases:
        print(yellow("Nothing to build on this machine for that target/platform."))
        return 0
    return run_phases(phases, fail_fast=True)


@verb(
    "clean",
    "Remove build outputs and tool caches.",
    group="Build",
    arguments=lambda p: (
        p.add_argument(
            "--all",
            action="store_true",
            dest="everything",
            help="also remove caches, not just build outputs",
        ),
        p.add_argument("--dry-run", action="store_true", help="list what would be removed"),
    ),
)
def cmd_clean(args: argparse.Namespace) -> int:
    """Delete build artifacts, and optionally every tool cache.

    Only ever removes generated paths: build outputs, tool caches, ``__pycache__``, and
    egg-info. Source is never a candidate, and ``--dry-run`` shows the list first.
    """
    targets: list[Path] = [ROOT / name for name in BUILD_DIRS]

    if args.everything:
        targets += [ROOT / name for name in CACHE_DIRS]
        targets += [ROOT / name for name in CACHE_FILES]
        for pattern in CACHE_GLOBS:
            targets += [
                path
                for path in ROOT.glob(pattern)
                # A virtualenv inside the repo is not ours to sweep.
                if not any(part in {".venv", "venv", ".git"} for part in path.parts)
            ]

    existing = [path for path in targets if path.exists()]
    if not existing:
        print("Nothing to clean.")
        return 0

    for path in existing:
        display = path.relative_to(ROOT)
        if args.dry_run:
            print(f"  would remove {display}")
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        print(f"  removed {display}")

    if args.dry_run:
        print()
        print(dim(f"{len(existing)} path(s) would be removed. Re-run without --dry-run."))
    else:
        print()
        print(green(f"Removed {len(existing)} path(s)."))
        if not args.everything:
            print(dim("Caches were kept. Use `workspace clean --all` to remove them too."))
    return 0


# ---------------------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------------------


def _headless_env() -> dict[str, str]:
    """Environment for test runs.

    The Qt tests must never require a display, and hardware probes must never read a cached
    profile — a stale profile silently changes what the tuning assertions see.
    """
    return {
        "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
        "ANYINFER_HARDWARE_CACHE_BYPASS": "1",
    }


class _Formatter(argparse.RawDescriptionHelpFormatter):
    """Help formatter that leaves the hand-built verb listing alone."""


def _describe(handler: Callable[[argparse.Namespace], int]) -> str:
    """Render a handler's docstring as terminal help text.

    Docstrings here are written for readers of the source, so they carry indentation and
    a little RST. Both look like noise on a terminal, so they are stripped.
    """
    doc = handler.__doc__ or ""
    summary, _, body = doc.partition("\n")
    cleaned = f"{summary.strip()}\n{textwrap.dedent(body).rstrip()}"
    return cleaned.replace("``", "`")


GROUP_ICONS = {
    "Environment": "🛠️ ",
    "Quality": "🧪",
    "Run": "🚀",
    "Build": "📦",
}
"""One emoji per verb group, shown in the help listing.

Icons degrade to replacement glyphs (not crashes) on legacy consoles because stdout is
reconfigured to UTF-8 with ``errors="replace"`` at import.
"""


def _epilog() -> str:
    """The verb listing, grouped and colorized, for ``workspace --help``."""
    lines = [bold("verbs:")]
    width = max(len(name) for name in REGISTRY) + 2
    for group in GROUP_ORDER:
        lines.append("")
        lines.append(f"  {GROUP_ICONS.get(group, '▪️')} {bold(cyan(group))}")
        for name, entry in REGISTRY.items():
            if entry.group == group:
                lines.append(f"    {green(f'{name:<{width}}')} {entry.summary}")
    lines.append("")
    lines.append(dim("Run `workspace <verb> --help` for a verb's own options."))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser from the verb registry."""
    parser = argparse.ArgumentParser(
        prog="workspace",
        usage="workspace <verb> [options]",
        description=f"⚡ {bold(cyan('AnyInfer'))} — developer task runner.",
        epilog=_epilog(),
        formatter_class=_Formatter,
    )
    # The verb list is rendered by hand in the epilog, grouped by category. Suppressing
    # argparse's own flat listing avoids printing every verb twice.
    subparsers = parser.add_subparsers(dest="verb", metavar="<verb>", help=argparse.SUPPRESS)

    for entry in REGISTRY.values():
        sub = subparsers.add_parser(
            entry.name,
            prog=f"workspace {entry.name}",
            help=argparse.SUPPRESS,
            description=_describe(entry.handler),
            formatter_class=_Formatter,
        )
        if entry.add_arguments is not None:
            entry.add_arguments(sub)
        if entry.passthrough:
            # Documentation only. Passthrough arguments are split off in `main` before
            # argparse sees them, because argparse cannot be made to forward arbitrary
            # flags — `--help` and any unknown option would be claimed by this parser
            # rather than reaching the wrapped tool.
            sub.usage = f"workspace {entry.name} [options] [-- ...forwarded]"
        sub.set_defaults(_handler=entry.handler, rest=[])

    return parser


def _split_passthrough(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split ``argv`` into arguments for this parser and arguments to forward.

    For a verb declared ``passthrough``, everything after the verb is forwarded verbatim,
    so ``workspace demo --reset`` and ``workspace serve --port 9`` behave as if the
    wrapped tool had been invoked directly. An explicit ``--`` also ends this runner's
    arguments, which is how you forward a flag whose name the runner itself uses
    (``workspace serve -- --help``).
    """
    for index, argument in enumerate(argv):
        if argument.startswith("-"):
            continue
        entry = REGISTRY.get(argument)
        if entry is None:
            break
        if not entry.passthrough:
            break
        rest = argv[index + 1 :]
        if rest and rest[0] == "--":
            rest = rest[1:]
        return argv[: index + 1], rest
    return argv, []


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to a verb.

    Args:
        argv: Arguments to parse; defaults to :data:`sys.argv`.

    Returns:
        A process exit code.
    """
    parser = build_parser()
    own, forwarded = _split_passthrough(list(sys.argv[1:] if argv is None else argv))
    args = parser.parse_args(own)
    args.rest = forwarded

    if getattr(args, "_handler", None) is None:
        parser.print_help()
        return 0

    if _ROOT is None:
        # Running the gates against site-packages would produce a screenful of failures
        # that say nothing about the actual problem, so refuse with the real reason.
        print(
            red(
                "error: no AnyInfer checkout found here.\n"
                f"  `workspace` operates on a checkout (looked for "
                f"{', '.join(REPO_MARKERS)} in {Path.cwd()} and its parents).\n"
                "  cd into the repository and try again."
            )
        )
        return 2

    shadowed = _warn_if_shadowed()
    if shadowed is not None:
        print(yellow(f"warning: {shadowed}"))

    started = time.monotonic()
    try:
        code = int(args._handler(args))
    except StepError as error:
        print(red(f"error: {error}"))
        return error.code
    except KeyboardInterrupt:
        print()
        print(yellow("Interrupted."))
        return 130

    if code == 0:
        print(dim(f"\n{args.verb} finished in {time.monotonic() - started:.1f}s"))
    return code


if __name__ == "__main__":
    sys.exit(main())
