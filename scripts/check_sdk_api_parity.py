"""Validate the C# SDK evidence ledger without importing the Python SDK."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from re import compile as re_compile

BASELINE_REVISION = "199c3f833e568334b629edd7d89f41a3b76efe2a"
BASELINE_COUNT = 235
BASELINE_FINGERPRINT = "bd7aa30216f5586f8399e1fee6e7d4dcb7cd3e3c5c4cca6b0abd8f005e301243"
PLAN_PATH = Path("plans/CSHARP_SDK_API_PARITY.md")
ALLOWED_STATUSES = frozenset({"implemented", "partial", "deferred", "different"})
LEGACY_HEADER = "| Done | Python export | Source module | Assigned C# milestone |"
LEDGER_HEADER = "## Per-export evidence ledger"
LEDGER_TABLE_HEADER = (
    "| Python export | Status | C# public symbols | Native source | Test evidence | "
    "Milestone | Scope and remaining gap |"
)
# Double-backtick spans keep generic CLR arity (for example ``Box`1``) literal.
INLINE_CODE = re_compile(r"(?P<ticks>`+)(?P<value>[^\n]*?)(?P=ticks)")
_TYPE_NAME = r"AnyInfer(?:[.+][A-Za-z_][A-Za-z0-9_]*(?:`[0-9]+)?)*"
PUBLIC_SYMBOL = re_compile(
    rf"^(?:T:{_TYPE_NAME}|M:{_TYPE_NAME}\.(?:[A-Za-z_][A-Za-z0-9_]*(?:`[0-9]+)?|<Clone>\$)|"
    rf"[PFE]:{_TYPE_NAME}\.[A-Za-z_][A-Za-z0-9_]*(?:`[0-9]+)?)$"
)
ROOT_EXPORT_SOURCE = "(inspect root import; implicit/indirect export)"
SDK_MILESTONE = re_compile(
    r"^SDK\.\d+[a-z]?(?:[\u2013-]\d+[a-z]?)?(?:/\d+[a-z]?(?:[\u2013-]\d+[a-z]?)?)*$"
)


@dataclass(frozen=True, slots=True)
class CompletionRow:
    """One preserved row from the historical completion table."""

    name: str
    module: str
    done: str
    milestone: str


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One per-export entry from the evidence ledger."""

    name: str
    status: str
    symbols: str
    native_source: str
    test_evidence: str
    milestone: str
    scope: str


def extract_public_exports(path: Path) -> dict[str, str]:
    """Extract literal root exports and their direct ``ImportFrom`` modules statically."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: dict[str, str] = {}
    names: list[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                imports.setdefault(alias.asname or alias.name, module)
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            if not isinstance(node.value, (ast.List, ast.Tuple)) or not all(
                isinstance(element, ast.Constant) and isinstance(element.value, str)
                for element in node.value.elts
            ):
                raise ValueError("__all__ must be a literal list or tuple of strings")
            names = [element.value for element in node.value.elts]
    if names is None:
        raise ValueError("literal __all__ was not found")
    if len(names) != len(set(names)):
        raise ValueError("__all__ contains duplicate exports")
    return {name: imports.get(name, "<root>") for name in names}


def inventory_fingerprint(exports: Mapping[str, str]) -> str:
    """Return the frozen inventory digest for a name/module mapping."""
    canonical = "".join(f"{name}\t{module}\n" for name, module in sorted(exports.items()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _table_rows(markdown: str, header: str) -> list[list[str]]:
    lines = markdown.splitlines()
    try:
        start = lines.index(header) + 2
    except ValueError:
        return []
    rows: list[list[str]] = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().split("|")[1:-1]]
        if cells:
            rows.append(cells)
    return rows


def parse_completion_table(markdown: str) -> list[CompletionRow]:
    """Parse the immutable completion rows from the plan."""
    rows = _table_rows(markdown, LEGACY_HEADER)
    parsed: list[CompletionRow] = []
    for cells in rows:
        if len(cells) != 4:
            continue
        name_codes = _codes(cells[1])
        module_codes = _codes(cells[2])
        if len(name_codes) == 1 and (len(module_codes) == 1 or cells[2] == ROOT_EXPORT_SOURCE):
            parsed.append(
                CompletionRow(
                    name_codes[0],
                    module_codes[0] if module_codes else cells[2],
                    cells[0],
                    cells[3],
                )
            )
    return parsed


def parse_evidence_ledger(markdown: str) -> list[LedgerRow]:
    """Parse valid seven-column evidence-ledger rows."""
    rows = _table_rows(markdown, LEDGER_TABLE_HEADER)
    parsed: list[LedgerRow] = []
    for cells in rows:
        if len(cells) != 7:
            continue
        names = _codes(cells[0])
        status_codes = _codes(cells[1])
        status = (
            status_codes[0]
            if len(status_codes) == 1 and cells[1] == f"`{status_codes[0]}`"
            else cells[1]
        )
        if len(names) == 1:
            parsed.append(LedgerRow(names[0], status, *cells[2:]))
    return parsed


def _codes(cell: str) -> list[str]:
    return [match.group("value") for match in INLINE_CODE.finditer(cell)]


def validate_inventory(root: Path) -> list[str]:
    """Check the present static inventory against the frozen baseline."""
    try:
        exports = extract_public_exports(root / "src/python/anyinfer/__init__.py")
    except (OSError, SyntaxError, ValueError) as error:
        return [f"could not statically extract Python exports: {error}"]
    errors: list[str] = []
    if len(exports) != BASELINE_COUNT:
        errors.append(
            f"Python inventory has {len(exports)} exports; expected baseline {BASELINE_COUNT}"
        )
    fingerprint = inventory_fingerprint(exports)
    if fingerprint != BASELINE_FINGERPRINT:
        errors.append("Python inventory differs from frozen baseline fingerprint")
    return errors


def validate_baseline_metadata(markdown: str) -> list[str]:
    """Require the plan to name exactly the revision frozen by this checker."""
    baseline_lines = [line for line in markdown.splitlines() if line.startswith("> Baseline:")]
    expected = f"> Baseline: `{BASELINE_REVISION}`. Source inventory is static; "
    expected += "no Python package imports."
    if baseline_lines != [expected]:
        return ["plan baseline metadata is missing, stale, or changed"]
    return []


def validate_completion_table(markdown: str, exports: Mapping[str, str]) -> list[str]:
    """Ensure the historical completion table remains exactly intact."""
    errors: list[str] = []
    if markdown.count(LEGACY_HEADER) != 1:
        return ["legacy completion table header must appear exactly once"]
    raw_rows = _table_rows(markdown, LEGACY_HEADER)
    rows = parse_completion_table(markdown)
    if len(raw_rows) != len(exports) or len(rows) != len(raw_rows):
        errors.append("legacy completion table has malformed, missing, or extra rows")
    expected = [
        (name, ROOT_EXPORT_SOURCE if module == "<root>" else module)
        for name, module in exports.items()
    ]
    actual = [(row.name, row.module) for row in rows]
    if actual != expected:
        errors.append("legacy completion table export names or source mappings changed")
    if any(row.done != "[ ]" for row in rows):
        errors.append("legacy completion table checkboxes must remain [ ] at this slice")
    return errors


def _safe_paths(root: Path, cell: str, description: str) -> tuple[list[str], list[str]]:
    values = _codes(cell)
    errors: list[str] = []
    for value in values:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            errors.append(f"{description} path is not a contained relative path: {value}")
            continue
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            errors.append(f"{description} path escapes repository root: {value}")
            continue
        if not resolved.is_file():
            errors.append(f"{description} path does not exist: {value}")
    return values, errors


def validate_evidence_ledger(
    root: Path, markdown: str, exports: Mapping[str, str], symbols: set[str]
) -> list[str]:
    """Validate ledger coverage, evidence paths, and reflected public IDs."""
    errors: list[str] = []
    if markdown.count(LEDGER_HEADER) != 1:
        return ["evidence ledger must have exactly one '## Per-export evidence ledger' heading"]
    if markdown.count(LEDGER_TABLE_HEADER) != 1:
        return ["evidence ledger table header must appear exactly once"]
    raw_rows = _table_rows(markdown, LEDGER_TABLE_HEADER)
    rows = parse_evidence_ledger(markdown)
    if len(raw_rows) != len(exports) or len(rows) != len(raw_rows):
        errors.append("evidence ledger has malformed, missing, or extra rows")
    names = [row.name for row in rows]
    if len(names) != len(set(names)):
        errors.append("evidence ledger has duplicate Python exports")
    if set(names) != set(exports):
        errors.append("evidence ledger does not cover exactly the frozen Python export inventory")
    for row in rows:
        prefix = f"ledger row {row.name}"
        if row.status not in ALLOWED_STATUSES:
            errors.append(f"{prefix} has invalid status {row.status!r}")
        if not SDK_MILESTONE.fullmatch(row.milestone):
            errors.append(f"{prefix} requires an SDK milestone identifier")
        if _is_placeholder(row.scope):
            errors.append(f"{prefix} requires a nonempty milestone and scope/gap explanation")
        symbol_values = _codes(row.symbols)
        native_paths, native_errors = _safe_paths(
            root, row.native_source, f"{prefix} native source"
        )
        test_paths, test_errors = _safe_paths(root, row.test_evidence, f"{prefix} test evidence")
        errors.extend(native_errors)
        errors.extend(test_errors)
        if row.status == "deferred":
            if row.symbols != "—" or row.native_source != "—":
                errors.append(f"{prefix} deferred status requires — symbols and native source")
            if not test_paths or not any(
                path.startswith(("src/python/", "tests/")) for path in test_paths
            ):
                errors.append(f"{prefix} deferred status requires Python source or test evidence")
            continue
        if not symbol_values:
            errors.append(f"{prefix} requires at least one public native symbol")
        elif any(symbol not in symbols for symbol in symbol_values):
            errors.append(f"{prefix} names a native symbol absent from reflection output")
        if not native_paths or any(
            not path.startswith("src/csharp/AnyInfer/") for path in native_paths
        ):
            errors.append(f"{prefix} requires a native source path under src/csharp/AnyInfer")
        if not test_paths or not any(_is_test_path(path) for path in test_paths):
            errors.append(f"{prefix} requires at least one real test path")
    return errors


def _is_test_path(path: str) -> bool:
    return path.startswith(
        ("tests/", "src/csharp/AnyInfer.Tests/", "src/csharp/AnyInfer.Conformance/")
    )


def _is_placeholder(value: str) -> bool:
    return value.strip().casefold() in {"", "—", "-", "n/a", "none", "tbd", "todo", "placeholder"}


def collect_native_symbols(root: Path) -> set[str]:
    """Build the maintenance projection and return its emitted symbol set."""
    project = root / "src/csharp/AnyInfer.Maintenance/AnyInfer.Maintenance.csproj"
    dll = root / "src/csharp/AnyInfer.Maintenance/bin/Debug/net8.0/AnyInfer.Maintenance.dll"
    if not project.is_file():
        raise RuntimeError(f"maintenance project is missing: {project}")
    try:
        build = subprocess.run(
            ["dotnet", "build", str(project), "--no-restore", "-m:1"],
            cwd=root / "src/csharp",
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise RuntimeError(f"could not run native symbol projection build: {error}") from error
    if build.returncode:
        raise RuntimeError("native symbol projection build failed: " + _bounded_output(build))
    with tempfile.TemporaryDirectory(prefix="anyinfer-sdk-api-") as temporary:
        output = Path(temporary) / "public-api.json"
        try:
            projection = subprocess.run(
                ["dotnet", str(dll), "--public-api", "--output", str(output)],
                cwd=root / "src/csharp",
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as error:
            raise RuntimeError(f"could not run native symbol projection: {error}") from error
        if projection.returncode:
            raise RuntimeError("native symbol projection failed: " + _bounded_output(projection))
        try:
            values = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"native symbol projection did not produce JSON: {error}"
            ) from error
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise RuntimeError("native symbol projection must be a JSON string array")
    if values != sorted(set(values)):
        raise RuntimeError("native symbol projection must be sorted and unique")
    if any(PUBLIC_SYMBOL.fullmatch(value) is None for value in values):
        raise RuntimeError("native symbol projection contains an invalid public symbol ID")
    return set(values)


def _bounded_output(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stdout + result.stderr).strip().replace("\n", " ")
    return output[:500] or f"exit code {result.returncode}"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone evidence validator."""
    parser = argparse.ArgumentParser(
        description="Validate C# SDK export evidence coverage (not semantic parity)."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    errors = validate_inventory(root)
    try:
        exports = extract_public_exports(root / "src/python/anyinfer/__init__.py")
        markdown = (root / PLAN_PATH).read_text(encoding="utf-8")
    except (OSError, SyntaxError, ValueError) as error:
        errors.append(f"could not read parity inventory inputs: {error}")
        exports, markdown = {}, ""
    errors.extend(validate_baseline_metadata(markdown))
    errors.extend(validate_completion_table(markdown, exports))
    try:
        symbols = collect_native_symbols(root)
    except RuntimeError as error:
        errors.append(str(error))
        symbols = set()
    errors.extend(validate_evidence_ledger(root, markdown, exports, symbols))
    if errors:
        print("sdk API parity evidence check failed:", file=sys.stderr)
        for error in errors[:30]:
            print(f"- {error}", file=sys.stderr)
        if len(errors) > 30:
            print(f"- {len(errors) - 30} additional errors omitted", file=sys.stderr)
        return 1
    counts = Counter(row.status for row in parse_evidence_ledger(markdown))
    summary = ", ".join(f"{status}={counts[status]}" for status in sorted(counts))
    print(f"sdk API evidence coverage validated ({summary}); this is not a semantic parity claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
