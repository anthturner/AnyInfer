"""Controls for pre-sealing candidate qualification evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "provider_change", ROOT / "scripts" / "check_provider_change.py"
)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)
SHA = "a" * 64
COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


@pytest.fixture(autouse=True)
def _candidate_repository_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(CHECKER, "ROOT", tmp_path)


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base(tmp_path: Path) -> tuple[Path, Path, Path, list[Path], list[Path]]:
    registry = json.loads((ROOT / "maintenance" / "implementations.json").read_text())
    change = json.loads(
        (
            ROOT / "tests" / "fixtures" / "provider-change" / "synthetic-wire-change.json"
        ).read_text()
    )
    change["shared_spec"] = {
        "impact": "candidate_draft",
        "rationale": "synthetic",
        "candidate": {"release_id": "synthetic-r1", "paths": ["candidate/manifest.json"]},
    }
    change["implementations"][0]["owned_paths"] = ["changed.py"]
    change["implementations"][1]["owned_paths"] = ["changed.cs"]
    input_path = _write(tmp_path / "change.json", change)
    registry_path = _write(tmp_path / "registry.json", registry)
    input_sha, registry_sha = _digest(input_path), _digest(registry_path)
    context = {
        "producer": {"id": "ci", "version": "1"},
        "workflow_run": {"id": "run", "attempt": 1},
        "trusted_pr_head": COMMIT_B,
        "evaluated_source": {
            "commit": COMMIT_B,
            "tree": COMMIT_B,
            "dirty": False,
            "input_fingerprint": SHA,
        },
    }
    context_path = _write(tmp_path / "context.json", context)
    inventories, verifications = [], []
    for item in registry["implementations"]:
        base = context | {
            "schema_version": 1,
            "implementation_id": item["id"],
            "registry_sha256": registry_sha,
            "input_sha256": input_sha,
        }
        inventories.append(
            _write(
                tmp_path / f"{item['id']}.inventory.json",
                base
                | {
                    "bindings": [
                        {
                            "provider_id": "synthetic",
                            "operation": "generation",
                            "contract_dependencies": ["contracts/openai-compat.md"],
                        }
                    ]
                },
            )
        )
        gates = [
            {
                "id": gate["id"],
                "status": "passed",
                "exit_code": 0,
                "output_sha256": SHA,
                "log_sha256": SHA,
            }
            for gate in item["gates"]
        ]
        verifications.append(
            _write(tmp_path / f"{item['id']}.verification.json", base | {"gates": gates})
        )
    return input_path, registry_path, context_path, inventories, verifications


def _candidate(
    tmp_path: Path,
    input_path: Path,
    registry_path: Path,
    context_path: Path,
    *,
    extension: bool = False,
) -> Path:
    root = tmp_path
    ref_source = ROOT / "specification" / "reference" / "python-fc53787.json"
    env_source = ROOT / "specification" / "reference" / "python-fc53787.environment.json"
    schema_source = ROOT / "specification" / "schemas" / "report-v0.schema.json"
    for source, name in (
        (ref_source, "specification/reference/python-fc53787.json"),
        (env_source, "specification/reference/python-fc53787.environment.json"),
        (schema_source, "specification/schemas/report-v0.schema.json"),
    ):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    reference_revision = json.loads(ref_source.read_text())["reference_run_revision"]
    for name in (
        "specification/normative/README.md",
        "specification/normative/MAINTENANCE.md",
        "specification/normative/profile.md",
    ):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic normative input\n", encoding="utf-8")
    fixture = root / "specification/fixtures/case.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("{}\n", encoding="utf-8")
    inventory = _write(
        root / "specification/inventory.json",
        {
            "cases": [
                {
                    "id": "case/one",
                    "kind": "fixture",
                    "path": "specification/fixtures/case.json",
                    "family": "synthetic",
                    "extension": "targets.alias" if extension else None,
                }
            ]
        },
    )
    report = _write(
        root / "python.report.json",
        {
            "report_version": "0",
            "release": "synthetic-r1",
            "release_sha256": "0" * 64,
            "implementation": {
                "name": "anyinfer-python",
                "version": "test",
                "source_revision": COMMIT_B,
                "driver_revision": COMMIT_B,
                "runtime": "test",
                "os": "test",
                "dependencies": {},
                "extensions": ["targets.alias"] if extension else [],
            },
            "cases": [
                {
                    "id": "case/one",
                    "verdict": "extension" if extension else "pass",
                    "detail": "eligible extension: targets.alias" if extension else None,
                    "evidence": {"native_outcome": {"none": True}, "adapter_entries": []}
                    if extension
                    else None,
                }
            ],
            "counts": {
                "pass": 0 if extension else 1,
                "fail": 0,
                "error": 0,
                "extension": 1 if extension else 0,
            },
        },
    )
    assets = [
        "specification/inventory.json",
        "specification/reference/python-fc53787.json",
        "specification/reference/python-fc53787.environment.json",
        "specification/schemas/report-v0.schema.json",
        "specification/normative/README.md",
        "specification/normative/MAINTENANCE.md",
        "specification/normative/profile.md",
        "specification/fixtures/case.json",
    ]
    manifest = _write(
        root / "specification/releases/manifest.json",
        {
            "release": "synthetic-r1",
            "profile": "synthetic-profile",
            "profile_revision": "v9",
            "reference_manifest": "specification/reference/python-fc53787.json",
            "files": {name: _digest(root / name) for name in sorted(assets)},
            "case_inventory": json.loads(inventory.read_text())["cases"],
        },
    )
    payload = {
        "schema_version": 1,
        "input_sha256": _digest(input_path),
        "registry_sha256": _digest(registry_path),
        "release_id": "synthetic-r1",
        "profile": "synthetic-profile",
        "profile_revision": "v9",
        "input_revision_a": reference_revision,
        "candidate_commit_b": COMMIT_B,
        "candidate_tree_b": COMMIT_B,
        "candidate_manifest": {
            "path": "specification/releases/manifest.json",
            "sha256": _digest(manifest),
        },
        "reference": {
            "path": "specification/reference/python-fc53787.json",
            "sha256": _digest(root / "specification/reference/python-fc53787.json"),
            "environment_path": "specification/reference/python-fc53787.environment.json",
            "environment_sha256": _digest(
                root / "specification/reference/python-fc53787.environment.json"
            ),
        },
        "normative": {
            "readme": {
                "path": "specification/normative/README.md",
                "sha256": _digest(root / "specification/normative/README.md"),
            },
            "maintenance": {
                "path": "specification/normative/MAINTENANCE.md",
                "sha256": _digest(root / "specification/normative/MAINTENANCE.md"),
            },
            "profile": {
                "path": "specification/normative/profile.md",
                "sha256": _digest(root / "specification/normative/profile.md"),
            },
        },
        "inventory": {"path": "specification/inventory.json", "sha256": _digest(inventory)},
        "schemas": ["specification/schemas/report-v0.schema.json"],
        "case_inputs": [
            {
                "id": "case/one",
                "path": "specification/fixtures/case.json",
                "sha256": _digest(fixture),
            }
        ],
        "assets": [{"path": name, "sha256": _digest(root / name)} for name in assets],
        "support_claimset": ["anyinfer-python"],
        "reports": [
            {
                "implementation_id": "anyinfer-python",
                "path": "python.report.json",
                "sha256": _digest(report),
                "run_identity": {"source_revision": COMMIT_B, "driver_revision": COMMIT_B},
            }
        ],
        "review": {"identity": "cold-review-1", "disposition": "approved"},
    }
    _write(root / "candidate.json", payload)
    report_value = json.loads(report.read_text())
    report_value["release_sha256"] = _digest(manifest)
    _write(report, report_value)
    payload["reports"][0]["sha256"] = _digest(report)
    _write(root / "candidate.json", payload)
    context = json.loads(context_path.read_text())
    context["candidate_qualification"] = {
        "input_revision_a": reference_revision,
        "candidate_commit_b": COMMIT_B,
        "candidate_tree_b": COMMIT_B,
        "support_claimset": ["anyinfer-python"],
        "reference_run_clean": True,
        "reference_ancestry_verified": True,
        "expected_artifact_digests": {"anyinfer-python": _digest(report)},
        "report_runs": {
            "anyinfer-python": {"source_revision": COMMIT_B, "driver_revision": COMMIT_B}
        },
        "review_identity": "cold-review-1",
        "review_disposition": "approved",
        "reviewed_candidate_commit_b": COMMIT_B,
    }
    _write(context_path, context)
    return root / "candidate.json"


def _refresh_report_binding(candidate: Path, context_path: Path) -> None:
    evidence = json.loads(candidate.read_text())
    report = candidate.parent / evidence["reports"][0]["path"]
    digest = _digest(report)
    evidence["reports"][0]["sha256"] = digest
    _write(candidate, evidence)
    context = json.loads(context_path.read_text())
    context["candidate_qualification"]["expected_artifact_digests"]["anyinfer-python"] = digest
    _write(context_path, context)


def _refresh_manifest_binding(candidate: Path, context_path: Path) -> Path:
    evidence = json.loads(candidate.read_text())
    manifest = candidate.parent / evidence["candidate_manifest"]["path"]
    evidence["candidate_manifest"]["sha256"] = _digest(manifest)
    report = candidate.parent / evidence["reports"][0]["path"]
    report_value = json.loads(report.read_text())
    report_value["release_sha256"] = _digest(manifest)
    _write(report, report_value)
    evidence["reports"][0]["sha256"] = _digest(report)
    _write(candidate, evidence)
    context = json.loads(context_path.read_text())
    context["candidate_qualification"]["expected_artifact_digests"]["anyinfer-python"] = _digest(
        report
    )
    _write(context_path, context)
    return manifest


def test_generic_non_v0_candidate_qualifies_only_with_independent_context(tmp_path: Path) -> None:
    paths = _base(tmp_path)
    candidate = _candidate(tmp_path, paths[0], paths[1], paths[2])
    report = CHECKER.validate(*paths, candidate_evidence=candidate)
    assert report["candidate_qualification"]["release_id"] == "synthetic-r1"


def test_candidate_cli_writes_a_schema_valid_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _base(tmp_path)
    candidate = _candidate(tmp_path, paths[0], paths[1], paths[2])
    output = tmp_path / "aggregate.json"
    arguments = [
        "check_provider_change.py",
        "--input",
        str(paths[0]),
        "--registry",
        str(paths[1]),
        "--context",
        str(paths[2]),
    ]
    for path in paths[3]:
        arguments.extend(["--inventory", str(path)])
    for path in paths[4]:
        arguments.extend(["--verification", str(path)])
    arguments.extend(["--candidate-evidence", str(candidate), "--output", str(output)])
    monkeypatch.setattr(sys, "argv", arguments)
    assert CHECKER.main() == 0
    result, _ = CHECKER.read_json(output)
    CHECKER._validate(result, "run-report.schema.json")
    assert result["candidate_qualification"]["report_count"] == 1


def test_candidate_accepts_an_inventory_eligible_extension_with_evidence(tmp_path: Path) -> None:
    paths = _base(tmp_path)
    candidate = _candidate(tmp_path, paths[0], paths[1], paths[2], extension=True)
    assert (
        CHECKER.validate(*paths, candidate_evidence=candidate)["candidate_qualification"][
            "report_count"
        ]
        == 1
    )


def test_external_wrapper_resolves_only_reports_from_its_bundle(tmp_path: Path) -> None:
    paths = _base(tmp_path)
    candidate = _candidate(tmp_path, paths[0], paths[1], paths[2])
    bundle = tmp_path / "downloaded" / "run-9"
    bundle.mkdir(parents=True)
    report = tmp_path / "python.report.json"
    moved_report = bundle / report.name
    report.rename(moved_report)
    moved_candidate = bundle / candidate.name
    candidate.rename(moved_candidate)
    assert (
        CHECKER.validate(*paths, candidate_evidence=moved_candidate)["candidate_qualification"][
            "report_count"
        ]
        == 1
    )


def test_external_report_symlink_is_rejected(tmp_path: Path) -> None:
    paths = _base(tmp_path)
    candidate = _candidate(tmp_path, paths[0], paths[1], paths[2])
    linked = candidate.parent / "linked-report.json"
    try:
        linked.symlink_to(candidate.parent / "python.report.json")
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")
    evidence = json.loads(candidate.read_text())
    evidence["reports"][0]["path"] = linked.name
    _write(candidate, evidence)
    with pytest.raises(CHECKER.ProviderChangeError, match="escapes evidence root"):
        CHECKER.validate(*paths, candidate_evidence=candidate)


@pytest.mark.parametrize(
    "mutation, match",
    [
        ("missing-context", "trusted context"),
        ("dirty", "clean reference"),
        ("review", "review"),
        ("hash", "hash mismatch"),
    ],
)
def test_candidate_controls_fail_closed(tmp_path: Path, mutation: str, match: str) -> None:
    paths = _base(tmp_path)
    candidate = _candidate(tmp_path, paths[0], paths[1], paths[2])
    if mutation == "missing-context":
        context = json.loads(paths[2].read_text())
        context.pop("candidate_qualification")
        _write(paths[2], context)
    elif mutation == "dirty":
        context = json.loads(paths[2].read_text())
        context["candidate_qualification"]["reference_run_clean"] = False
        _write(paths[2], context)
    elif mutation == "review":
        evidence = json.loads(candidate.read_text())
        evidence["review"]["disposition"] = "rejected"
        _write(candidate, evidence)
    else:
        (candidate.parent / "specification/inventory.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CHECKER.ProviderChangeError, match=match):
        CHECKER.validate(*paths, candidate_evidence=candidate)


@pytest.mark.parametrize(
    "mutation, match",
    [
        ("duplicate", "duplicate"),
        ("stale-count", "counts"),
        ("pending", "pending"),
        ("provenance", "provenance"),
        ("incomplete", "grammar"),
    ],
)
def test_candidate_report_content_controls_fail_after_digest_rebinding(
    tmp_path: Path, mutation: str, match: str
) -> None:
    paths = _base(tmp_path)
    candidate = _candidate(tmp_path, paths[0], paths[1], paths[2])
    report_path = candidate.parent / "python.report.json"
    report = json.loads(report_path.read_text())
    if mutation == "duplicate":
        report["cases"].append(report["cases"][0])
    elif mutation == "stale-count":
        report["counts"]["pass"] = 2
    elif mutation == "pending":
        report["cases"][0]["detail"] = "pending"
    elif mutation == "provenance":
        report["implementation"]["driver_revision"] = COMMIT_A
    else:
        report["cases"] = []
    _write(report_path, report)
    _refresh_report_binding(candidate, paths[2])
    with pytest.raises(CHECKER.ProviderChangeError, match=match):
        CHECKER.validate(*paths, candidate_evidence=candidate)


def test_candidate_b_must_bind_outer_checkout_after_all_nested_facts_agree(tmp_path: Path) -> None:
    paths = _base(tmp_path)
    candidate = _candidate(tmp_path, paths[0], paths[1], paths[2])
    context = json.loads(paths[2].read_text())
    context["evaluated_source"]["tree"] = COMMIT_A
    with pytest.raises(CHECKER.ProviderChangeError, match="checkout"):
        CHECKER._candidate_qualification(
            candidate,
            paths[0].read_bytes(),
            paths[1].read_bytes(),
            context,
            {"anyinfer-python": {"profile_claims": []}},
        )


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "kind", "path", "family", "extension"],
)
def test_manifest_case_inventory_must_exactly_bind_canonical_case_records(
    tmp_path: Path, mutation: str
) -> None:
    paths = _base(tmp_path)
    candidate = _candidate(tmp_path, paths[0], paths[1], paths[2])
    evidence = json.loads(candidate.read_text())
    manifest_path = candidate.parent / evidence["candidate_manifest"]["path"]
    manifest = json.loads(manifest_path.read_text())
    if mutation == "duplicate":
        manifest["case_inventory"].append(dict(manifest["case_inventory"][0]))
    else:
        row = manifest["case_inventory"][0]
        row[mutation] = "altered" if mutation != "path" else "specification/fixtures/other.json"
    _write(manifest_path, manifest)
    _refresh_manifest_binding(candidate, paths[2])
    with pytest.raises(CHECKER.ProviderChangeError, match=r"exactly bind inventory|duplicate"):
        CHECKER.validate(*paths, candidate_evidence=candidate)
