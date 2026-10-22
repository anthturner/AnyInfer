"""Focused controls for provider-change CI routing and workflow coupling."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "provider_change_ci.py"
SPEC = importlib.util.spec_from_file_location("provider_change_ci", SCRIPT)
assert SPEC and SPEC.loader
CI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CI)


def test_selection_never_scans_synthetic_test_fixtures() -> None:
    assert CI.select({"tests/fixtures/provider-change/synthetic-wire-change.json"}) == {
        "schema_version": 1,
        "applicable": False,
        "reason": "no-applicable-record",
    }


@pytest.mark.parametrize(
    "path",
    ["contracts/openai.md", "specification/core-generation.md", "specification/fixtures/core-generation/example.json"],
)
def test_contract_or_normative_basis_change_without_a_production_record_is_refused(path: str) -> None:
    with pytest.raises(CI.ProviderChangeCIError, match="require a changed"):
        CI.select({path})


@pytest.mark.parametrize("path", ["src/python/anyinfer/cli.py", "src/csharp/AnyInfer/Providers/ProviderRegistry.cs"])
def test_source_only_change_remains_an_explicit_no_op(path: str) -> None:
    assert CI.select({path})["reason"] == "no-applicable-record"


def test_manual_dispatch_selects_only_a_candidate_production_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = tmp_path / "maintenance" / "changes"
    changes.mkdir(parents=True)
    record = json.loads(
        (ROOT / "tests" / "fixtures" / "provider-change" / "synthetic-wire-change.json").read_text()
    )
    record["shared_spec"] = {
        "impact": "candidate_draft",
        "rationale": "Synthetic candidate handoff.",
        "candidate": {"release_id": "core-generation-v-next", "paths": ["specification/next.md"]},
    }
    path = changes / "candidate-1.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    evidence = tmp_path / "maintenance" / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(CI, "ROOT", tmp_path)
    monkeypatch.setattr(CI, "CHANGES", changes)

    selected = CI.select_manual(
        "maintenance/changes/candidate-1.json",
        "evidence.json",
        "{}",
        "42",
        "candidate-evidence",
    )
    assert selected is not None
    assert selected["applicable"] is True
    assert selected["changed_paths"] is None


@pytest.mark.parametrize(
    ("input_path", "evidence", "facts", "run_id", "artifact", "message"),
    [
        ("maintenance/changes/candidate-1.json", "", "{}", "42", "candidate", "requires"),
        (
            "tests/fixtures/provider-change/synthetic-wire-change.json",
            "evidence.json",
            "{}",
            "42",
            "candidate",
            "canonical",
        ),
    ],
)
def test_manual_dispatch_refuses_partial_or_noncanonical_paths(
    input_path: str, evidence: str, facts: str, run_id: str, artifact: str, message: str
) -> None:
    with pytest.raises(CI.ProviderChangeCIError, match=message):
        CI.select_manual(input_path, evidence, facts, run_id, artifact)


def test_manual_dispatch_refuses_bundle_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = tmp_path / "maintenance" / "changes"
    changes.mkdir(parents=True)
    record = json.loads(
        (ROOT / "tests" / "fixtures" / "provider-change" / "synthetic-wire-change.json").read_text()
    )
    record["shared_spec"] = {
        "impact": "candidate_draft",
        "rationale": "Synthetic candidate handoff.",
        "candidate": {"release_id": "core-generation-v-next", "paths": ["specification/next.md"]},
    }
    (changes / "candidate-1.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(CI, "ROOT", tmp_path)
    monkeypatch.setattr(CI, "CHANGES", changes)

    with pytest.raises(CI.ProviderChangeCIError, match="safe path"):
        CI.select_manual(
            "maintenance/changes/candidate-1.json", "../evidence.json", "{}", "42", "candidate"
        )


def test_control_plane_change_is_an_explicit_no_op() -> None:
    assert CI.select({".github/workflows/ci.yml", "scripts/provider_change_ci.py"})["reason"] == "no-applicable-record"


def test_workflow_binds_each_registered_producer_and_aggregate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for artifact in (
        "provider-change-python-inventory",
        "provider-change-python-gates-verification",
        "provider-change-python-suite-verification",
        "provider-change-csharp-inventory",
        "provider-change-csharp-verification",
        "provider-change-run-report",
    ):
        assert artifact in workflow
    assert "provider-change:" in workflow
    assert "needs: [changes, gates, native-csharp, test]" in workflow
    assert "needs: [changes, gates, native-csharp, test, test-extra, test-macos, provider-change]" in workflow
    assert "provider_change" in workflow
    assert "pull_request.head.sha || github.sha" in workflow
    assert "--changed-paths-json" in workflow
    assert "provider_change_input_path" in workflow
    assert "candidate_evidence_path" in workflow
    assert "candidate_qualification_json" in workflow
    assert "candidate_evidence_artifact_run_id" in workflow
    assert "candidate_evidence_artifact_name" in workflow
    assert "provider-change-dispatch-receipt" in workflow


def test_workflow_dispatches_only_the_registered_required_gate_shards() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for gate in ("python-contracts", "python-fixtures", "python-conformance", "python-tests", "csharp-workspace"):
        assert f"--gate {gate}" in workflow
    assert "--inventory-only" in workflow
    assert workflow.count("run_provider_change_checks.py") == 5
    assert "candidate_args" in workflow
    assert "CANDIDATE_QUALIFICATION_JSON" in workflow
    assert "manual-candidate/${{ github.run_id }}" in workflow
    assert "run-id: ${{ inputs.candidate_evidence_artifact_run_id }}" in workflow
    assert "mkdir -p .tmp-provider-change" in workflow


def test_aggregate_rejects_a_synthetic_input_before_artifact_processing(tmp_path: Path) -> None:
    input_path = ROOT / "tests" / "fixtures" / "provider-change" / "synthetic-wire-change.json"
    with pytest.raises(CI.ProviderChangeCIError, match="production maintenance/changes"):
        CI.aggregate(input_path, ROOT / "maintenance" / "implementations.json", [], "a" * 40, "1", 1, tmp_path / "report.json")
