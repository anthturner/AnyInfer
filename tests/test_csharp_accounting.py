"""Synthetic negative controls for the accounting observer verifier."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _checker() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "check_csharp_accounting.py"
    spec = importlib.util.spec_from_file_location("check_csharp_accounting", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = _checker()


def _cases() -> tuple[dict[str, object], ...]:
    return (
        {"id": "money", "kind": "generation_cost"},
        {"id": "ordered", "kind": "ledger"},
        {"id": "native-range", "kind": "native_only_range"},
    )


def _ok(identifier: str, kind: str, value: object) -> dict[str, object]:
    return {"id": identifier, "kind": kind, "status": "ok", "value": value}


def _write(path: Path, observations: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "profile": "accounting-v1",
                "runtime": "python",
                "source_revision": "a" * 40,
                "source_dirty": True,
                "corpus_sha256": "b" * 64,
                "observations": observations,
            }
        ),
        encoding="utf-8",
    )


def _envelope(
    runtime: str,
    observations: list[dict[str, object]],
    *,
    revision: str,
    dirty: bool,
    digest: str,
) -> dict[str, object]:
    return {
        "profile": "accounting-v1",
        "runtime": runtime,
        "source_revision": revision,
        "source_dirty": dirty,
        "corpus_sha256": digest,
        "observations": observations,
    }


def _complete_observations(runtime: str) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = [
        _ok("money", "generation_cost", "0.1"),
        _ok("ordered", "ledger", {"by_target": {"a": 1}}),
    ]
    if runtime == "csharp":
        observations.append(
            {
                "id": "native-range",
                "kind": "native_only_range",
                "status": "error",
                "error_type": "OverflowException",
                "structured_flags": {"native_only": True},
            }
        )
    else:
        observations.append(_ok("native-range", "native_only_range", "9223372036854775808"))
    return observations


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ([], "missing observations"),
        (
            [_ok("money", "generation_cost", "1"), _ok("money", "generation_cost", "1")],
            "duplicate",
        ),
        (
            [_ok("money", "generation_cost", "1"), _ok("extra", "generation_cost", "1")],
            "unexpected",
        ),
        ([{"id": "money", "kind": "generation_cost", "status": "wat"}], "unsupported status"),
    ],
)
def test_observation_shape_rejects_missing_duplicate_extra_and_status(
    tmp_path: Path, replacement: list[dict[str, object]], message: str
) -> None:
    path = tmp_path / "observations.json"
    _write(path, replacement)
    with pytest.raises(CHECKER.ObservationError, match=message):
        CHECKER.read_observations(
            path,
            expected_cases=_cases(),
            expected_runtime="python",
            expected_corpus_sha256="b" * 64,
        )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("0.10", "0.1"),
        (None, 0),
        (True, 1),
        ('{\\n  \\"a\\": 1\\n}', '{\\n  \\"a\\":1\\n}'),
    ],
)
def test_exact_projection_comparison_does_not_normalize_money_null_bool_or_bytes(
    left: object, right: object
) -> None:
    cases = _cases()[:1]
    python = {"money": _ok("money", "generation_cost", left)}
    native = {"money": _ok("money", "generation_cost", right)}
    comparison = CHECKER.compare_observations(cases, python, native)
    assert comparison.status == "fail"
    assert comparison.mismatches[0]["id"] == "money"


def test_ledger_ordinal_maps_remain_order_sensitive() -> None:
    cases = _cases()[1:2]
    python = {"ordered": _ok("ordered", "ledger", {"by_target": {"a": 1, "b": 2}})}
    native = {"ordered": _ok("ordered", "ledger", {"by_target": {"b": 2, "a": 1}})}
    comparison = CHECKER.compare_observations(cases, python, native)
    assert comparison.status == "fail"
    assert "ordinal map" in comparison.mismatches[0]["difference"]


def test_server_tool_use_order_remains_financially_sensitive() -> None:
    cases = _cases()[:1]
    python = {"money": _ok("money", "generation_cost", {"server_tool_uses": {"a": 1, "b": 2}})}
    native = {"money": _ok("money", "generation_cost", {"server_tool_uses": {"b": 2, "a": 1}})}
    comparison = CHECKER.compare_observations(cases, python, native)
    assert comparison.status == "fail"
    assert "ordinal map" in comparison.mismatches[0]["difference"]


def test_unmapped_error_cannot_pass() -> None:
    cases = _cases()[:1]
    python = {
        "money": {
            "id": "money",
            "kind": "generation_cost",
            "status": "error",
            "error_type": "Unexpected",
        }
    }
    native = {
        "money": {
            "id": "money",
            "kind": "generation_cost",
            "status": "error",
            "error_type": "NativeUnexpected",
        }
    }
    comparison = CHECKER.compare_observations(cases, python, native)
    assert comparison.status == "fail"
    assert "unmapped" in comparison.mismatches[0]["difference"]


@pytest.mark.parametrize(
    ("python_type", "python_cause", "native_cause"),
    [
        ("InvalidOperation", "invalid_operation", "overflow"),
        ("Overflow", "overflow", None),
        ("DivisionByZero", "division_by_zero", "rounded"),
    ],
)
def test_decimal_traps_require_the_matching_public_cause(
    python_type: str, python_cause: str, native_cause: str | None
) -> None:
    cases = _cases()[:1]
    python = {
        "money": {
            "id": "money",
            "kind": "generation_cost",
            "status": "error",
            "error_type": python_type,
            "decimal_cause": python_cause,
        }
    }
    native_error: dict[str, object] = {
        "id": "money",
        "kind": "generation_cost",
        "status": "error",
        "error_type": "ETrapException",
    }
    if native_cause is not None:
        native_error["decimal_cause"] = native_cause
    comparison = CHECKER.compare_observations(cases, python, {"money": native_error})
    assert comparison.status == "fail"
    assert "unmapped" in comparison.mismatches[0]["difference"]


def test_generic_arithmetic_error_does_not_blindly_match_a_decimal_trap() -> None:
    cases = _cases()[:1]
    python = {
        "money": {
            "id": "money",
            "kind": "generation_cost",
            "status": "error",
            "error_type": "ArithmeticError",
        }
    }
    native = {
        "money": {
            "id": "money",
            "kind": "generation_cost",
            "status": "error",
            "error_type": "ETrapException",
            "decimal_cause": "invalid_operation",
        }
    }
    comparison = CHECKER.compare_observations(cases, python, native)
    assert comparison.status == "fail"


def test_native_only_fixture_echo_is_pending_not_a_match() -> None:
    cases = _cases()[2:]
    python = {"native-range": _ok("native-range", "native_only_range", "9223372036854775808")}
    native = {"native-range": _ok("native-range", "native_only_range", "9223372036854775808")}
    comparison = CHECKER.compare_observations(cases, python, native)
    assert comparison.status == "pending"
    assert comparison.native_only[0]["qualification"] == "pending"


def test_native_only_structured_boundary_is_reported_not_counted_as_shared_match() -> None:
    cases = _cases()[2:]
    python = {"native-range": _ok("native-range", "native_only_range", "9223372036854775808")}
    native = {
        "native-range": {
            "id": "native-range",
            "kind": "native_only_range",
            "status": "error",
            "error_type": "OverflowException",
            "structured_flags": {"native_only": True},
        }
    }
    comparison = CHECKER.compare_observations(cases, python, native)
    assert comparison.status == "pass"
    assert comparison.matched == ()
    assert comparison.native_only[0]["qualification"] == "observed"


def test_run_observers_uses_pinned_python_and_csharp_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        calls.append((command, cwd))

    monkeypatch.setattr(CHECKER, "_run", fake_run)
    python_path, native_path = CHECKER.run_observers(
        tmp_path / "inputs.json",
        tmp_path,
        source_revision="a" * 40,
        source_dirty=True,
    )
    assert python_path == tmp_path / "python.json"
    assert native_path == tmp_path / "native.json"
    assert calls[0][0][:4] == [
        "dotnet",
        "build",
        "AnyInfer.Accounting/AnyInfer.Accounting.csproj",
        "--no-restore",
    ]
    assert "--project" not in calls[0][0]
    assert calls[0][0][-2:] == ["-p:SourceRevisionId=" + "a" * 40, "-p:AccountingSourceDirty=true"]
    assert calls[1][0][1].endswith("test_accounting_parity.py")
    assert calls[1][0][2] == "--observe"
    assert calls[2][0][:6] == [
        "dotnet",
        "run",
        "--no-build",
        "--no-restore",
        "--project",
        "AnyInfer.Accounting",
    ]
    assert calls[2][1] == CHECKER.CSHARP_ROOT


def test_observer_identity_requires_runtime_revision_and_dirty_flag(tmp_path: Path) -> None:
    path = tmp_path / "observations.json"
    path.write_text(json.dumps({"profile": "accounting-v1", "observations": []}), encoding="utf-8")
    with pytest.raises(CHECKER.ObservationError, match="runtime"):
        CHECKER.read_observations(
            path,
            expected_cases=(),
            expected_runtime="python",
            expected_corpus_sha256="b" * 64,
        )


def test_observer_identity_rejects_a_stale_input_digest(tmp_path: Path) -> None:
    path = tmp_path / "observations.json"
    _write(path, [])
    with pytest.raises(CHECKER.ObservationError, match="input bytes"):
        CHECKER.read_observations(
            path,
            expected_cases=(),
            expected_runtime="python",
            expected_corpus_sha256="c" * 64,
        )


@pytest.mark.parametrize(
    ("native_revision", "native_dirty", "native_digest", "message"),
    [
        ("c" * 40, True, None, "source revisions differ"),
        (None, False, None, "dirty-state evidence differs"),
        (None, True, "0" * 64, "does not identify the supplied input bytes"),
    ],
)
def test_main_compare_rejects_revision_dirty_and_corpus_handshake_mismatches(
    tmp_path: Path,
    native_revision: str | None,
    native_dirty: bool,
    native_digest: str | None,
    message: str,
) -> None:
    inputs = tmp_path / "inputs.json"
    inputs.write_text(
        json.dumps({"profile": "accounting-v1", "cases": list(_cases())}), encoding="utf-8"
    )
    digest = hashlib.sha256(inputs.read_bytes()).hexdigest()
    revision = "a" * 40
    python_path = tmp_path / "python.json"
    native_path = tmp_path / "native.json"
    python_path.write_text(
        json.dumps(
            _envelope(
                "python",
                _complete_observations("python"),
                revision=revision,
                dirty=True,
                digest=digest,
            )
        ),
        encoding="utf-8",
    )
    native_path.write_text(
        json.dumps(
            _envelope(
                "csharp",
                _complete_observations("csharp"),
                revision=native_revision or revision,
                dirty=native_dirty,
                digest=native_digest or digest,
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(CHECKER.ObservationError, match=message):
        CHECKER.main(
            [
                "--input",
                str(inputs),
                "--output-root",
                str(tmp_path / "runs"),
                "--compare",
                str(python_path),
                str(native_path),
            ]
        )
