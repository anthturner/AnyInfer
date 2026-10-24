"""Independent fail-closed controls for the SDK API evidence checker."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPOSITORY = Path(__file__).parents[1]
_CHECKER_PATH = _REPOSITORY / "scripts" / "check_sdk_api_parity.py"


def _checker() -> ModuleType:
    """Load the maintenance checker by path without importing the SDK package."""
    spec = importlib.util.spec_from_file_location("sdk_api_parity_checker", _CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _root(tmp_path: Path, exports: str = '"Alpha",') -> Path:
    """Construct the smallest source tree accepted by static inventory controls."""
    init = tmp_path / "src" / "python" / "anyinfer" / "__init__.py"
    init.parent.mkdir(parents=True)
    init.write_text(
        "from .sample import Alpha\n\n__all__ = [\n" + exports + "\n]\n", encoding="utf-8"
    )
    native = tmp_path / "src" / "csharp" / "AnyInfer" / "Sample.cs"
    native.parent.mkdir(parents=True)
    native.write_text("public sealed class Sample {}\n", encoding="utf-8")
    test = tmp_path / "src" / "csharp" / "AnyInfer.Tests" / "SampleTests.cs"
    test.parent.mkdir(parents=True)
    test.write_text("public sealed class SampleTests {}\n", encoding="utf-8")
    return tmp_path


def _completion(names: tuple[str, ...] = ("Alpha",), mark: str = " ") -> str:
    """Render a root completion table with literal import-source mapping."""
    rows = "\n".join(
        f"| [{mark}] | `{name}` | `.sample` | SDK.1 generation |" for name in names
    )
    return "\n".join(
        (
            "## Root exports (235)",
            "",
            "| Done | Python export | Source module | Assigned C# milestone |",
            "|---|---|---|---|",
            rows,
        )
    )


def _ledger(
    name: str = "Alpha",
    *,
    status: str = "implemented",
    symbol: str = "T:AnyInfer.Sample",
    source: str = "src/csharp/AnyInfer/Sample.cs",
    evidence: str = "src/csharp/AnyInfer.Tests/SampleTests.cs",
    milestone: str = "SDK.1",
    gap: str = "Complete native mapping.",
) -> str:
    """Render one ledger row in the exact checked table shape."""
    return "\n".join(
        (
            "## Per-export evidence ledger",
            "",
            "| Python export | Status | C# public symbols | Native source | Test evidence | Milestone | Scope and remaining gap |",
            "|---|---|---|---|---|---|---|",
            f"| `{name}` | {status} | `{symbol}` | `{source}` | `{evidence}` | {milestone} | {gap} |",
        )
    )


def test_inventory_is_static_ast_and_preserves_import_source_mapping(tmp_path: Path) -> None:
    """A toxic module body must not execute while collecting literal root exports."""
    checker = _checker()
    init = tmp_path / "__init__.py"
    init.write_text(
        "from .one import Alpha as PublicAlpha\n"
        "from .two import Beta\n"
        "raise RuntimeError('an inventory parser imported the SDK')\n"
        "__all__ = ['PublicAlpha', 'Beta']\n",
        encoding="utf-8",
    )

    assert checker.extract_public_exports(init) == {
        "Beta": ".two",
        "PublicAlpha": ".one",
    }


def test_real_repository_static_inventory_matches_the_pinned_baseline() -> None:
    """The checked repository's static export inventory matches the frozen fingerprint."""
    checker = _checker()

    assert checker.validate_inventory(_REPOSITORY) == []


def test_baseline_plan_metadata_rejects_a_stale_revision() -> None:
    """The plan declares the same source revision that the checker pins."""
    checker = _checker()
    plan = (_REPOSITORY / "plans/CSHARP_SDK_API_PARITY.md").read_text(encoding="utf-8")

    assert checker.validate_baseline_metadata(plan) == []
    stale = plan.replace(checker.BASELINE_REVISION, "0" * 40, 1)
    assert "plan baseline metadata is missing, stale, or changed" in (
        checker.validate_baseline_metadata(stale)
    )


@pytest.mark.parametrize(
    ("exports", "expected"),
    (
        ('"Alpha", "Alpha",', "duplicate"),
        ('"Alpha",', "baseline"),
    ),
)
def test_inventory_rejects_duplicate_and_pinned_baseline_drift(
    tmp_path: Path, exports: str, expected: str
) -> None:
    """The checked inventory is both unique and pinned, rather than self-derived."""
    checker = _checker()
    root = _root(tmp_path, exports)

    errors = checker.validate_inventory(root)

    assert errors
    assert any(expected in error.lower() for error in errors)


@pytest.mark.parametrize(
    "rows",
    (
        ("Alpha", "Alpha"),
        ("Alpha", "Extra"),
        ("Extra",),
    ),
)
def test_completion_table_rejects_extra_missing_and_duplicate_rows(
    tmp_path: Path, rows: tuple[str, ...]
) -> None:
    """Final-completion boxes cannot silently drift from the static root API surface."""
    checker = _checker()
    exports = checker.extract_public_exports(_root(tmp_path) / "src/python/anyinfer/__init__.py")
    malformed = _completion(rows)

    errors = checker.validate_completion_table(malformed, exports)

    assert "legacy completion table export names or source mappings changed" in errors


def test_completion_table_rejects_changed_final_completion_mark(tmp_path: Path) -> None:
    """Root export rows are immutable work markers, not reconciliation status fields."""
    checker = _checker()
    exports = checker.extract_public_exports(_root(tmp_path) / "src/python/anyinfer/__init__.py")

    assert "legacy completion table checkboxes must remain [ ] at this slice" in (
        checker.validate_completion_table(_completion(("Alpha",), "x"), exports)
    )


def test_completion_table_rejects_import_source_drift(tmp_path: Path) -> None:
    """A completion row must retain the literal ``ImportFrom`` module source."""
    checker = _checker()
    exports = checker.extract_public_exports(_root(tmp_path) / "src/python/anyinfer/__init__.py")
    markdown = _completion().replace("`.sample`", "`.renamed`")

    assert "legacy completion table export names or source mappings changed" in (
        checker.validate_completion_table(markdown, exports)
    )


def test_valid_one_export_completion_and_evidence_rows_pass_pure_validators(tmp_path: Path) -> None:
    """Pure table validators accept a complete small fixture before mutation controls run."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")
    python_test = root / "tests/test_sample.py"
    python_test.parent.mkdir()
    python_test.write_text("def test_sample() -> None:\n    pass\n", encoding="utf-8")

    assert checker.validate_completion_table(_completion(), exports) == []
    assert checker.validate_evidence_ledger(
        root,
        _ledger(evidence="tests/test_sample.py"),
        exports,
        {"T:AnyInfer.Sample"},
    ) == []


def test_ordinary_csharp_test_evidence_path_is_accepted_and_non_test_path_is_rejected(
    tmp_path: Path,
) -> None:
    """Ordinary C# test evidence is valid, while a source file cannot masquerade as one."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")

    assert checker.validate_evidence_ledger(
        root, _ledger(), exports, {"T:AnyInfer.Sample"}
    ) == []
    errors = checker.validate_evidence_ledger(
        root,
        _ledger(evidence="src/csharp/AnyInfer/Sample.cs"),
        exports,
        {"T:AnyInfer.Sample"},
    )
    assert "ledger row Alpha requires at least one real test path" in errors


def test_ledger_rejects_an_extra_malformed_raw_row(tmp_path: Path) -> None:
    """A malformed raw row cannot be silently skipped while parsed rows still look valid."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")
    python_test = root / "tests/test_sample.py"
    python_test.parent.mkdir()
    python_test.write_text("def test_sample() -> None:\n    pass\n", encoding="utf-8")
    malformed = _ledger(evidence="tests/test_sample.py") + "\n| malformed | raw | row | with | too | many | cells | here |"

    assert "evidence ledger has malformed, missing, or extra rows" in (
        checker.validate_evidence_ledger(root, malformed, exports, {"T:AnyInfer.Sample"})
    )


def test_evidence_ledger_rejects_a_second_table_header_under_one_heading(tmp_path: Path) -> None:
    """A second table cannot hide rows after the single evidence-ledger heading."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")
    second_table = "\n".join(
        (
            checker.LEDGER_TABLE_HEADER,
            "|---|---|---|---|---|---|---|",
            "| `Alpha` | deferred | — | — | `src/python/anyinfer/__init__.py` | SDK.1 | Later. |",
        )
    )

    errors = checker.validate_evidence_ledger(
        root, _ledger() + "\n\n" + second_table, exports, {"T:AnyInfer.Sample"}
    )

    assert "evidence ledger table header must appear exactly once" in errors


def test_completion_table_rejects_a_second_legacy_table_header(tmp_path: Path) -> None:
    """The immutable completion table cannot be duplicated beneath the plan heading."""
    checker = _checker()
    exports = checker.extract_public_exports(_root(tmp_path) / "src/python/anyinfer/__init__.py")
    second_table = "\n".join(
        (
            checker.LEGACY_HEADER,
            "|---|---|---|---|",
            "| [ ] | `Alpha` | `.sample` | SDK.1 |",
        )
    )

    errors = checker.validate_completion_table(_completion() + "\n\n" + second_table, exports)

    assert "legacy completion table header must appear exactly once" in errors


@pytest.mark.parametrize(
    ("status", "gap"),
    (
        ("", "Complete native mapping."),
        ("placeholder", "Complete native mapping."),
        ("partial", ""),
        ("different", ""),
        ("deferred", ""),
    ),
)
def test_ledger_rejects_empty_unknown_and_unexplained_statuses(
    tmp_path: Path, status: str, gap: str
) -> None:
    """Every non-complete mapping carries an explicit classification and remaining scope."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")

    errors = checker.validate_evidence_ledger(
        root, _ledger(status=status, gap=gap), exports, {"T:AnyInfer.Sample"}
    )

    if status in {"", "placeholder"}:
        assert any("invalid status" in error for error in errors)
    else:
        assert any("scope/gap explanation" in error for error in errors)


@pytest.mark.parametrize(
    ("milestone", "gap", "diagnostic"),
    (
        ("not-a-milestone", "Complete native mapping.", "SDK milestone identifier"),
        ("SDK.1", "TBD", "scope/gap explanation"),
    ),
)
def test_ledger_rejects_invalid_milestone_and_placeholder_scope_with_specific_diagnostic(
    tmp_path: Path, milestone: str, gap: str, diagnostic: str
) -> None:
    """Milestones and scope must be assigned rather than placeholder prose."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")

    errors = checker.validate_evidence_ledger(
        root, _ledger(milestone=milestone, gap=gap), exports, {"T:AnyInfer.Sample"}
    )

    assert any(diagnostic in error for error in errors)


def test_ledger_rejects_broken_inline_status_delimiters_with_status_diagnostic(tmp_path: Path) -> None:
    """Only an exact one-backtick status code span is normalized."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")

    errors = checker.validate_evidence_ledger(
        root, _ledger(status="``implemented`"), exports, {"T:AnyInfer.Sample"}
    )

    assert "ledger row Alpha has invalid status '``implemented`'" in errors


@pytest.mark.parametrize(
    "path",
    (
        "",
        "src/csharp/AnyInfer/Missing.cs",
        "../outside.cs",
        "C:/absolute.cs",
        "src/python/anyinfer/__init__.py",
    ),
)
def test_ledger_rejects_missing_escaping_and_wrong_area_paths(tmp_path: Path, path: str) -> None:
    """Evidence paths are contained, existing, and restricted to native source/test roots."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")
    markdown = _ledger(source=path)

    errors = checker.validate_evidence_ledger(
        root, markdown, exports, {"T:AnyInfer.Sample"}
    )
    assert any("native source" in error for error in errors)


def test_ledger_rejects_symlink_which_escapes_native_source_root(tmp_path: Path) -> None:
    """A contained spelling is insufficient when its resolved target escapes the checkout."""
    checker = _checker()
    root = _root(tmp_path)
    outside = tmp_path.parent / "outside.cs"
    outside.write_text("public sealed class Outside {}\n", encoding="utf-8")
    link = root / "src/csharp/AnyInfer/Escapes.cs"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")

    errors = checker.validate_evidence_ledger(
        root,
        _ledger(source="src/csharp/AnyInfer/Escapes.cs"),
        exports,
        {"T:AnyInfer.Sample"},
    )
    assert any("escapes" in error for error in errors)


def test_ledger_requires_actual_public_reflection_witness_not_source_tokens(tmp_path: Path) -> None:
    """Comments and source text cannot substitute for the maintenance reflection output."""
    checker = _checker()
    root = _root(tmp_path)
    source = root / "src/csharp/AnyInfer/Sample.cs"
    source.write_text("// T:AnyInfer.Sample\ninternal sealed class Sample {}\n", encoding="utf-8")
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")

    assert "ledger row Alpha names a native symbol absent from reflection output" in (
        checker.validate_evidence_ledger(root, _ledger(), exports, set())
    )


def test_ledger_accepts_generic_reflection_id_and_rejects_stale_member(
    tmp_path: Path,
) -> None:
    """Reflection IDs retain generic backtick arity and reject a stale public member witness."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")
    generic = "M:AnyInfer.Box`1.Get"
    valid = _ledger(
        symbol=f"``{generic}``",
        evidence="src/csharp/AnyInfer.Tests/Conformance/SampleTests.cs",
    )
    conformance = root / "src/csharp/AnyInfer.Tests/Conformance/SampleTests.cs"
    conformance.parent.mkdir(parents=True)
    conformance.write_text("public sealed class SampleTests {}\n", encoding="utf-8")
    assert not checker.validate_evidence_ledger(root, valid, exports, {generic})
    assert checker.validate_evidence_ledger(root, valid, exports, {"T:AnyInfer.Box`1"})


def test_ledger_normalizes_status_written_as_inline_code(tmp_path: Path) -> None:
    """Ledger authors may quote a status without changing its checked meaning."""
    checker = _checker()
    root = _root(tmp_path)
    exports = checker.extract_public_exports(root / "src/python/anyinfer/__init__.py")
    python_test = root / "tests/test_sample.py"
    python_test.parent.mkdir()
    python_test.write_text("def test_sample() -> None:\n    pass\n", encoding="utf-8")
    markdown = _ledger(status="`implemented`", evidence="tests/test_sample.py")

    assert not checker.validate_evidence_ledger(
        root, markdown, exports, {"T:AnyInfer.Sample"}
    )


def test_ledger_parser_fails_closed_for_missing_heading_and_malformed_table() -> None:
    """The evidence table must be an exact, parseable seven-column contract."""
    checker = _checker()

    assert checker.parse_evidence_ledger("| Python export | Status |\n|---|---|\n| `Alpha` | implemented |") == []
    assert checker.parse_completion_table("## Root exports\nnot a table") == []


def test_ledger_rejects_multiple_heading_instances_with_specific_diagnostic() -> None:
    """A second ledger heading cannot introduce unchecked evidence rows."""
    checker = _checker()

    assert checker.validate_evidence_ledger(Path(), _ledger() + "\n## Per-export evidence ledger", {}, set()) == [
        "evidence ledger must have exactly one '## Per-export evidence ledger' heading"
    ]


def test_collect_native_symbols_uses_maintenance_cli_and_rejects_bad_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The runtime projection is a strict JSON CLI boundary, with no source-token fallback."""
    checker = _checker()
    root = _root(tmp_path)
    project = root / "src/csharp/AnyInfer.Maintenance/AnyInfer.Maintenance.csproj"
    project.parent.mkdir(parents=True)
    project.write_text("<Project />", encoding="utf-8")
    dll = root / "src/csharp/AnyInfer.Maintenance/bin/Debug/net8.0/AnyInfer.Maintenance.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"")

    class Result:
        returncode = 0
        stdout = '["M:AnyInfer.Box`1.Get", "T:AnyInfer.Box`1"]'
        stderr = ""

    calls: list[object] = []

    def run(*args: object, **kwargs: object) -> Result:
        calls.append((args, kwargs))
        command = args[0]
        assert isinstance(command, list)
        if "--output" in command:
            output = Path(command[command.index("--output") + 1])
            output.write_text(Result.stdout, encoding="utf-8")
        return Result()

    monkeypatch.setattr(checker.subprocess, "run", run)
    assert checker.collect_native_symbols(root) == {
        "M:AnyInfer.Box`1.Get",
        "T:AnyInfer.Box`1",
    }
    assert calls

    class BadResult:
        returncode = 0
        stdout = '["not-a-public-id"]'
        stderr = ""

    def bad_run(*args: object, **kwargs: object) -> BadResult:
        command = args[0]
        assert isinstance(command, list)
        if "--output" in command:
            output = Path(command[command.index("--output") + 1])
            output.write_text(BadResult.stdout, encoding="utf-8")
        return BadResult()

    monkeypatch.setattr(checker.subprocess, "run", bad_run)
    with pytest.raises((RuntimeError, ValueError)):
        checker.collect_native_symbols(root)


@pytest.mark.parametrize(
    "invalid_id",
    (
        "M:AnyInfer.Message.<Clone>",
        "M:AnyInfer.Message.Clone$",
        "P:AnyInfer.Message.<Clone>$",
        "F:AnyInfer.Message.<Clone>$",
        "E:AnyInfer.Message.<Clone>$",
    ),
)
def test_native_projection_accepts_only_method_clone_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invalid_id: str
) -> None:
    """Record clone IDs are admitted only in their real method-projection spelling."""
    checker = _checker()
    root = _root(tmp_path)
    project = root / "src/csharp/AnyInfer.Maintenance/AnyInfer.Maintenance.csproj"
    project.parent.mkdir(parents=True)
    project.write_text("<Project />", encoding="utf-8")
    dll = root / "src/csharp/AnyInfer.Maintenance/bin/Debug/net8.0/AnyInfer.Maintenance.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"")
    payload = ["M:AnyInfer.Message.<Clone>$"]

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(*args: object, **kwargs: object) -> Result:
        command = args[0]
        assert isinstance(command, list)
        if "--output" in command:
            output = Path(command[command.index("--output") + 1])
            output.write_text(json.dumps(payload), encoding="utf-8")
        return Result()

    monkeypatch.setattr(checker.subprocess, "run", run)
    assert checker.collect_native_symbols(root) == {"M:AnyInfer.Message.<Clone>$"}

    payload[:] = [invalid_id]
    with pytest.raises(RuntimeError, match="invalid public symbol ID"):
        checker.collect_native_symbols(root)
