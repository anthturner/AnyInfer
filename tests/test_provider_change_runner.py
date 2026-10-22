"""Focused controls for the registered provider-change command runner."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_provider_change_checks.py"
SPEC = importlib.util.spec_from_file_location("provider_change_runner", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


@pytest.fixture(autouse=True)
def _stable_source_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep runner controls independent of unrelated concurrent checkout edits."""
    monkeypatch.setattr(
        RUNNER,
        "_source_identity",
        lambda: {
            "commit": "b" * 40,
            "tree": "b" * 40,
            "dirty": True,
            "input_fingerprint": "c" * 64,
        },
    )


def _temporary(tmp_path: Path, name: str) -> Path:
    path = ROOT / ".tmp-tests" / "provider-change-runner" / tmp_path.name / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _run_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _paths(tmp_path: Path, gate_body: str = "print('gate output')") -> tuple[Path, Path, Path]:
    input_path = _temporary(tmp_path, "change.json")
    input_path.write_bytes(
        (ROOT / "tests" / "fixtures" / "provider-change" / "synthetic-wire-change.json").read_bytes()
    )
    gate_path = _temporary(tmp_path, "gate.py")
    gate_path.write_text(gate_body, encoding="utf-8")
    registry = json.loads((ROOT / "maintenance" / "implementations.json").read_text(encoding="utf-8"))
    python = next(item for item in registry["implementations"] if item["id"] == "anyinfer-python")
    python["gates"] = [
        {
            "id": "python-gate",
            "argv": ["{sys.executable}", gate_path.relative_to(ROOT).as_posix()],
        }
    ]
    registry["implementations"] = [python]
    registry_path = _temporary(tmp_path, "implementations.json")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return input_path, registry_path, ROOT / ".tmp-tests"


def test_inventory_only_writes_valid_dispatcher_context_and_no_verification(tmp_path: Path) -> None:
    input_path, registry_path, output_dir = _paths(tmp_path)

    run_directory = RUNNER._run_with_registry(
        input_path,
        registry_path,
        "anyinfer-python",
        output_dir,
        inventory_only=True,
        trusted_pr_head="a" * 40,
        run_id=_run_id("inventory"),
    )

    context = json.loads((run_directory / "context.json").read_text(encoding="utf-8"))
    inventory = json.loads((run_directory / "inventory.json").read_text(encoding="utf-8"))
    assert context["producer"] == {"id": "provider-change-dispatcher", "version": "1"}
    assert inventory["producer"] == {"id": "python-provider-bindings", "version": "1"}
    assert len(context["trusted_pr_head"]) == 40
    assert len(context["input_sha256"]) == 64
    assert len(context["evaluated_source"]["input_fingerprint"]) == 64
    assert not (run_directory / "verification.json").exists()


def test_registered_gate_runs_literal_argv_and_records_actual_nonzero(tmp_path: Path) -> None:
    input_path, registry_path, output_dir = _paths(tmp_path, "import sys\nprint('failed gate')\nsys.exit(7)\n")

    run_directory = RUNNER._run_with_registry(
        input_path,
        registry_path,
        "anyinfer-python",
        output_dir,
        trusted_pr_head="a" * 40,
        run_id=_run_id("failed"),
    )

    verification = json.loads((run_directory / "verification.json").read_text(encoding="utf-8"))
    gate = verification["gates"][0]
    assert (gate["id"], gate["status"], gate["exit_code"]) == ("python-gate", "failed", 7)
    assert gate["output_sha256"] == RUNNER._sha(
        (run_directory / "logs" / "python-gate.stdout").read_bytes()
    )
    assert gate["log_sha256"] == RUNNER._sha(
        (run_directory / "logs" / "python-gate.log").read_bytes()
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unknown-gate", "not registered"),
        ("root-traversal", "unsafe path"),
        ("shell-syntax", "shell syntax"),
    ],
)
def test_untrusted_gate_or_unsafe_registered_argv_is_refused_before_process(
    tmp_path: Path, mutation: str, message: str
) -> None:
    input_path, registry_path, output_dir = _paths(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if mutation == "root-traversal":
        registry["implementations"][0]["gates"][0]["argv"] = ["{sys.executable}", "../bad.py"]
    elif mutation == "shell-syntax":
        registry["implementations"][0]["gates"][0]["argv"] = ["python;bad"]
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(RUNNER.RunnerError, match=message):
        RUNNER._run_with_registry(
            input_path,
            registry_path,
            "anyinfer-python",
            output_dir,
            gate_ids=["not-registered"] if mutation == "unknown-gate" else None,
            trusted_pr_head="a" * 40,
            run_id=_run_id(f"refuse-{mutation}"),
        )


@pytest.mark.parametrize("target", ["input", "registry"])
def test_gate_mutation_of_immutable_inputs_invalidates_evidence(tmp_path: Path, target: str) -> None:
    input_path, registry_path, output_dir = _paths(tmp_path)
    target_path = input_path if target == "input" else registry_path
    gate_path = ROOT / ".tmp-tests" / "provider-change-runner" / tmp_path.name / "gate.py"
    gate_path.write_text(
        f"from pathlib import Path\nPath({str(target_path)!r}).write_text('{{}}', encoding='utf-8')\n",
        encoding="utf-8",
    )

    with pytest.raises(RUNNER.RunnerError, match="mutated immutable"):
        RUNNER._run_with_registry(
            input_path,
            registry_path,
            "anyinfer-python",
            output_dir,
            trusted_pr_head="a" * 40,
            run_id=_run_id(f"mutate-{target}"),
        )


def test_gate_mutation_of_a_controlled_untracked_source_invalidates_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path, registry_path, output_dir = _paths(tmp_path)
    source_path = ROOT / f"runner-source-{uuid.uuid4().hex}.txt"
    source_path.write_text("before", encoding="utf-8")
    gate_path = ROOT / ".tmp-tests" / "provider-change-runner" / tmp_path.name / "gate.py"
    gate_path.write_text(
        f"from pathlib import Path\nPath({str(source_path)!r}).write_text('after', encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        RUNNER,
        "_source_identity",
        lambda: {
            "commit": "b" * 40,
            "tree": "b" * 40,
            "dirty": True,
            "input_fingerprint": RUNNER._sha(source_path.read_bytes()),
        },
    )

    try:
        with pytest.raises(RUNNER.RunnerError, match="mutated controlled source"):
            RUNNER._run_with_registry(
                input_path,
                registry_path,
                "anyinfer-python",
                output_dir,
                trusted_pr_head="a" * 40,
                run_id=_run_id("mutate-source"),
            )
    finally:
        source_path.unlink(missing_ok=True)


def test_partial_gate_selection_emits_only_selected_registered_gate(tmp_path: Path) -> None:
    input_path, registry_path, output_dir = _paths(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["implementations"][0]["gates"].append(
        {"id": "python-suite", "argv": ["{sys.executable}", "-c", "print('suite')"]}
    )
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    run_directory = RUNNER._run_with_registry(
        input_path,
        registry_path,
        "anyinfer-python",
        output_dir,
        gate_ids=["python-suite"],
        trusted_pr_head="a" * 40,
        run_id=_run_id("partial"),
    )

    verification = json.loads((run_directory / "verification.json").read_text(encoding="utf-8"))
    assert [gate["id"] for gate in verification["gates"]] == ["python-suite"]


def test_cli_rejects_alternate_schema_valid_registry_before_dispatch(tmp_path: Path) -> None:
    input_path, registry_path, output_dir = _paths(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["implementations"][0]["exporter_argv"] = [
        "{sys.executable}", "-c", "print('injected')"
    ]
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_path),
            "--registry",
            str(registry_path),
            "--implementation",
            "anyinfer-python",
            "--output-dir",
            str(output_dir),
            "--inventory-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "must resolve exactly" in completed.stderr
    assert "injected" not in completed.stdout


def test_canonical_registry_is_accepted_by_the_production_cli_guard() -> None:
    assert RUNNER._canonical_registry(ROOT / "maintenance" / "implementations.json") == (
        ROOT / "maintenance" / "implementations.json"
    ).resolve()
