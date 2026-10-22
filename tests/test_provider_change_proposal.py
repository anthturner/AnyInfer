from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_provider_change_proposal.py"
SPEC = importlib.util.spec_from_file_location("proposal_guard", SCRIPT)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


def _declaration_value(
    *, impact: str = "no_delta", disposition: str = "adopted"
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "id": "synthetic-proposal",
        "sources": [
            {
                "url": "https://example.test/provider",
                "fetched_at": "2026-10-22",
                "version_pin": "v1",
            }
        ],
        "disposition": disposition,
        "changes": [
            {
                "contract_id": "contracts/openai.md",
                "scope": "inference",
                "operations": ["generation"],
                "summary": "Synthetic test change.",
            }
        ],
        "shared_spec": {"impact": impact, "rationale": "Synthetic test rationale."},
        "implementations": [
            {
                "implementation_id": "anyinfer-python",
                "status": "updated",
                "rationale": "Synthetic test update.",
                "owned_paths": ["src/python/anyinfer/providers/openai.py"],
                "required_gate_ids": ["python-contracts"],
            }
        ],
    }
    if impact == "candidate_draft":
        value["shared_spec"] = {
            "impact": impact,
            "rationale": "Synthetic test rationale.",
            "candidate": {
                "release_id": "candidate-test",
                "paths": ["specification/candidates/new.md"],
            },
        }
    if disposition == "unverifiable":
        value["shared_spec"] = {"impact": "blocked", "rationale": "Synthetic blocker."}
    return value


def _declaration(path: Path, *, impact: str = "no_delta", disposition: str = "adopted") -> None:
    value = _declaration_value(impact=impact, disposition=disposition)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_no_change_does_not_request_a_pr() -> None:
    assert GUARD.check(set(), {"contracts/openai.md"}) == "no-change"


def test_complete_path_view_covers_untracked_and_staged_inputs() -> None:
    paths = GUARD.complete_paths(
        {"contracts/openai.md"},
        {"src/python/anyinfer/providers/openai.py"},
        {"maintenance/changes/new.json"},
    )
    assert paths == {
        "contracts/openai.md",
        "src/python/anyinfer/providers/openai.py",
        "maintenance/changes/new.json",
    }


@pytest.mark.parametrize("impact", ["no_delta", "candidate_draft"])
def test_declared_wire_or_new_candidate_draft_is_allowed(
    tmp_path: Path, impact: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    record = "maintenance/changes/synthetic.json"
    _declaration(tmp_path / record, impact=impact)
    changed = {record, "contracts/openai.md", "src/python/anyinfer/providers/openai.py"}
    if impact == "candidate_draft":
        changed.add("specification/candidates/new.md")
    assert GUARD.check(changed, {"contracts/openai.md"}) == "draft-prepared"


@pytest.mark.parametrize(
    "candidate_path",
    [
        "specification/candidates/new-normative.md",
        "specification/schemas/new-report.schema.json",
        "specification/inventories/new-inventory.json",
        "specification/fixtures/new-case.json",
    ],
)
def test_supported_new_candidate_asset_classes_are_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, candidate_path: str
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    record = "maintenance/changes/synthetic.json"
    _declaration(tmp_path / record, impact="candidate_draft")
    value = json.loads((tmp_path / record).read_text(encoding="utf-8"))
    value["shared_spec"]["candidate"]["paths"] = [candidate_path]
    (tmp_path / record).write_text(json.dumps(value), encoding="utf-8")
    assert (
        GUARD.check({record, "contracts/openai.md", candidate_path}, {"contracts/openai.md"})
        == "draft-prepared"
    )


@pytest.mark.parametrize("disposition", ["blocked", "unverifiable"])
def test_meaningful_blocked_or_unverifiable_draft_is_honest(
    tmp_path: Path, disposition: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    record = "maintenance/changes/synthetic.json"
    _declaration(tmp_path / record, disposition=disposition)
    assert (
        GUARD.check({record, "contracts/openai.md"}, {"contracts/openai.md"}) == "draft-prepared"
    )


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "maintenance/implementations.json",
        "scripts/run_provider_change_checks.py",
        "specification/core-generation.md",
    ],
)
def test_control_plane_and_sealed_asset_bypass_is_rejected(
    tmp_path: Path, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    record = "maintenance/changes/synthetic.json"
    _declaration(tmp_path / record)
    with pytest.raises(GUARD.ProposalError):
        GUARD.check({record, "contracts/openai.md", path}, {"contracts/openai.md"})


def test_declared_control_plane_path_is_still_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    record = "maintenance/changes/synthetic.json"
    _declaration(tmp_path / record)
    value = json.loads((tmp_path / record).read_text(encoding="utf-8"))
    value["implementations"][0]["owned_paths"] = ["scripts/check_provider_change.py"]
    (tmp_path / record).write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(GUARD.ProposalError, match="unsafe source path"):
        GUARD.check(
            {record, "contracts/openai.md", "scripts/check_provider_change.py"},
            {"contracts/openai.md"},
        )


def test_workflow_keeps_bounded_audit_and_places_guard_before_pr_mutation() -> None:
    workflow = (ROOT / ".github" / "workflows" / "contract-drift.yml").read_text(encoding="utf-8")
    assert 'default: "4"' in workflow
    assert 'default: "90"' in workflow
    assert "anthropics/claude-code-action@" in workflow
    assert "contract-drift-proposed-files" in workflow
    assert "--capture-bundle" in workflow
    assert "--restore-bundle" in workflow
    assert "git add -A" not in workflow
    publish = workflow.split("  publish:\n", maxsplit=1)[1]
    assert publish.index("validate and materialize a trusted proposal") < publish.index(
        "- name: create guarded draft pull request"
    )
    assert "gh pr create --base develop" in workflow
    assert "--draft" in workflow


def test_workflow_keeps_model_environment_out_of_fresh_publisher() -> None:
    workflow = (ROOT / ".github" / "workflows" / "contract-drift.yml").read_text(encoding="utf-8")
    propose, publish = workflow.split("  publish:\n", maxsplit=1)
    assert "contents: read" in propose
    assert "pull-requests: read" in propose
    assert "contents: write" not in propose
    assert "pull-requests: write" not in propose
    assert "contents: write" in publish
    assert "pull-requests: write" in publish
    assert "GITHUB_PATH" not in publish
    assert "GITHUB_ENV" not in publish
    assert "download the original selection report" in publish
    assert "needs.check.outputs.report_sha256" in publish


def _bundle(path: Path, files: dict[str, bytes], *, deleted: set[str] | None = None) -> None:
    rows = [
        {
            "path": name,
            "kind": "file",
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }
        for name, raw in files.items()
    ]
    rows.extend(
        {"path": name, "kind": "delete", "content_base64": ""} for name in sorted(deleted or set())
    )
    path.write_text(json.dumps({"schema_version": 1, "files": rows}), encoding="utf-8")


def test_control_plane_bundle_is_rejected_before_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    monkeypatch.setattr(GUARD, "MAINTENANCE", ROOT / "maintenance")
    bundle = tmp_path / "bundle.json"
    record = "maintenance/changes/synthetic.json"
    _bundle(
        bundle,
        {
            record: json.dumps(_declaration_value()).encode(),
            "scripts/check_provider_change_proposal.py": b"raise SystemExit(0)\n",
        },
    )
    monkeypatch.setattr(GUARD.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("ran git"))
    with pytest.raises(GUARD.ProposalError, match="control-plane"):
        GUARD.restore_bundle(bundle, {"contracts/openai.md"}, "HEAD")
    assert not (tmp_path / "scripts" / "check_provider_change_proposal.py").exists()


@pytest.mark.parametrize(
    ("path", "declaration_mutation", "message"),
    [
        (".git/config", None, "control-plane"),
        (".venv/bin/python", None, "control-plane"),
        ("docs/AGENTS.md", None, "control-plane"),
        ("README.md", None, "control-plane"),
        ("outside/candidate.md", "candidate", "candidate outside specification"),
    ],
)
def test_protected_or_outside_candidate_bundle_paths_are_rejected_prewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    declaration_mutation: str | None,
    message: str,
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    monkeypatch.setattr(GUARD, "MAINTENANCE", ROOT / "maintenance")
    record = "maintenance/changes/synthetic.json"
    declaration = _declaration_value()
    if declaration_mutation == "candidate":
        declaration["shared_spec"] = {
            "impact": "candidate_draft",
            "rationale": "Synthetic candidate.",
            "candidate": {"release_id": "candidate-test", "paths": [path]},
        }
    bundle = tmp_path / "bundle.json"
    _bundle(bundle, {record: json.dumps(declaration).encode(), path: b"malicious\n"})
    monkeypatch.setattr(GUARD.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("ran git"))
    with pytest.raises(GUARD.ProposalError, match=message):
        GUARD.restore_bundle(bundle, {"contracts/openai.md"}, "HEAD")
    assert not (tmp_path / path).exists()


@pytest.mark.parametrize(
    "path",
    [
        "specification/releases/draft-manifest.json",
        "specification/reference/reference-evidence.json",
        "specification/reference/expectations.json",
        "specification/qualification/candidate-evidence.json",
        "specification/reports/qualification-report.json",
        "specification/seals/candidate-seal.json",
    ],
)
def test_generated_candidate_output_namespaces_are_rejected_prewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    monkeypatch.setattr(GUARD, "MAINTENANCE", ROOT / "maintenance")
    record = "maintenance/changes/synthetic.json"
    declaration = _declaration_value(impact="candidate_draft")
    declaration["shared_spec"] = {
        "impact": "candidate_draft",
        "rationale": "Synthetic candidate.",
        "candidate": {"release_id": "candidate-test", "paths": [path]},
    }
    bundle = tmp_path / "bundle.json"
    _bundle(bundle, {record: json.dumps(declaration).encode(), path: b"generated\n"})
    monkeypatch.setattr(GUARD.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("ran git"))
    with pytest.raises(GUARD.ProposalError, match="unsupported candidate asset class"):
        GUARD.restore_bundle(bundle, {"contracts/openai.md"}, "HEAD")
    assert not (tmp_path / path).exists()


def test_bundle_restores_declared_untracked_or_staged_bytes_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    monkeypatch.setattr(GUARD, "MAINTENANCE", ROOT / "maintenance")
    bundle = tmp_path / "bundle.json"
    record = "maintenance/changes/synthetic.json"
    contract = "contracts/openai.md"
    source = "src/python/anyinfer/providers/openai.py"
    _bundle(
        bundle,
        {
            record: json.dumps(_declaration_value()).encode(),
            contract: b"contract draft\n",
            source: b"source draft\n",
        },
    )
    result, paths = GUARD.restore_bundle(bundle, {contract}, "HEAD")
    assert result == "draft-prepared"
    assert paths == {record, contract, source}
    assert (tmp_path / contract).read_bytes() == b"contract draft\n"


def test_existing_declaration_overwrite_is_rejected_before_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    monkeypatch.setattr(GUARD, "MAINTENANCE", ROOT / "maintenance")
    record = "maintenance/changes/tei-1-9-4.json"
    bundle = tmp_path / "bundle.json"
    _bundle(bundle, {record: json.dumps(_declaration_value()).encode()})
    monkeypatch.setattr(
        GUARD.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )
    with pytest.raises(GUARD.ProposalError, match="already exists"):
        GUARD.restore_bundle(bundle, {"contracts/openai.md"}, "trusted-base")
    assert not (tmp_path / record).exists()


def test_existing_declaration_deletion_is_rejected_before_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    monkeypatch.setattr(GUARD, "MAINTENANCE", ROOT / "maintenance")
    record = "maintenance/changes/tei-1-9-4.json"
    bundle = tmp_path / "bundle.json"
    _bundle(bundle, {}, deleted={record})
    monkeypatch.setattr(
        GUARD.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )
    with pytest.raises(GUARD.ProposalError, match="already exists"):
        GUARD.restore_bundle(bundle, {"contracts/openai.md"}, "trusted-base")
    assert not (tmp_path / record).exists()


def test_mutated_selection_report_or_baseline_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"selected": []}', encoding="utf-8")
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    monkeypatch.setattr(
        GUARD.subprocess, "check_output", lambda *_args, **_kwargs: "a" * 40 + "\n"
    )
    GUARD._verify_trusted_inputs(report, digest, "a" * 40)
    report.write_text('{"selected": ["changed"]}', encoding="utf-8")
    with pytest.raises(GUARD.ProposalError, match="selected drift report"):
        GUARD._verify_trusted_inputs(report, digest, "a" * 40)
    report.write_text('{"selected": []}', encoding="utf-8")
    with pytest.raises(GUARD.ProposalError, match="baseline"):
        GUARD._verify_trusted_inputs(report, digest, "b" * 40)
