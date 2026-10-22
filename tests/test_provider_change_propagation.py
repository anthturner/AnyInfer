"""Focused controls for the pure provider-change checker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_provider_change.py"
SPEC = importlib.util.spec_from_file_location("check_provider_change", SCRIPT)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)
SHA = "a" * 64
COMMIT = "b" * 40


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _context(dirty: bool = False) -> dict[str, object]:
    return {
        "producer": {"id": "ci", "version": "1"},
        "workflow_run": {"id": "run", "attempt": 1},
        "trusted_pr_head": COMMIT,
        "evaluated_source": {
            "commit": COMMIT,
            "tree": COMMIT,
            "dirty": dirty,
            "input_fingerprint": SHA,
        },
    }


def _case(tmp_path: Path) -> tuple[Path, Path, Path, list[Path], list[Path]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    registry = json.loads((ROOT / "maintenance" / "implementations.json").read_text())
    change = json.loads(
        (
            ROOT / "tests" / "fixtures" / "provider-change" / "synthetic-wire-change.json"
        ).read_text()
    )
    change["implementations"][0]["owned_paths"] = ["changed.py"]
    change["implementations"][1]["owned_paths"] = ["changed.cs"]
    input_path, registry_path, context_path = (
        _write(tmp_path / "change.json", change),
        _write(tmp_path / "registry.json", registry),
        _write(tmp_path / "context.json", _context()),
    )
    input_sha, registry_sha = (
        hashlib.sha256(input_path.read_bytes()).hexdigest(),
        hashlib.sha256(registry_path.read_bytes()).hexdigest(),
    )
    inventories, verifications = [], []
    for item in registry["implementations"]:
        impl = item["id"]
        bindings = (
            [
                {
                    "provider_id": "openai-compat",
                    "operation": "generation",
                    "contract_dependencies": ["contracts/openai-compat.md"],
                }
            ]
            if impl == "anyinfer-csharp"
            else [
                {
                    "provider_id": "python-openai",
                    "operation": "generation",
                    "contract_dependencies": ["contracts/openai-compat.md"],
                }
            ]
        )
        base = _context() | {
            "schema_version": 1,
            "implementation_id": impl,
            "registry_sha256": registry_sha,
            "input_sha256": input_sha,
        }
        inventories.append(
            _write(tmp_path / f"{impl}-inventory.json", base | {"bindings": bindings})
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
            _write(tmp_path / f"{impl}-verification.json", base | {"gates": gates})
        )
    return input_path, registry_path, context_path, inventories, verifications


def _rebind(paths: tuple[Path, Path, Path, list[Path], list[Path]]) -> None:
    input_sha = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    registry_sha = hashlib.sha256(paths[1].read_bytes()).hexdigest()
    for path in [*paths[3], *paths[4]]:
        value = json.loads(path.read_text())
        value["input_sha256"] = input_sha
        value["registry_sha256"] = registry_sha
        _write(path, value)


def test_valid_wire_only_change_emits_one_way_report(tmp_path: Path) -> None:
    paths = _case(tmp_path)
    report = CHECKER.validate(*paths, changed_paths={"changed.py", "changed.cs"})
    assert report["input_sha256"] == hashlib.sha256(paths[0].read_bytes()).hexdigest()
    assert len(report["inventory_artifacts"]) == 2


def test_existing_csharp_binding_cannot_be_declared_unsupported(tmp_path: Path) -> None:
    paths = _case(tmp_path)
    change = json.loads(paths[0].read_text())
    change["implementations"][1]["status"] = "unsupported"
    _write(paths[0], change)
    input_sha = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    for path in [*paths[3], *paths[4]]:
        value = json.loads(path.read_text())
        value["input_sha256"] = input_sha
        _write(path, value)
    with pytest.raises(CHECKER.ProviderChangeError, match="unsupported"):
        CHECKER.validate(*paths)


def test_stale_context_and_dirty_evidence_are_rejected(tmp_path: Path) -> None:
    paths = _case(tmp_path)
    stale = json.loads(paths[2].read_text())
    stale["trusted_pr_head"] = "c" * 40
    _write(paths[2], stale)
    with pytest.raises(CHECKER.ProviderChangeError, match="trusted context"):
        CHECKER.validate(*paths)

    paths = _case(tmp_path / "dirty")
    _write(paths[2], _context(dirty=True))
    for path in [*paths[3], *paths[4]]:
        value = json.loads(path.read_text())
        value["evaluated_source"]["dirty"] = True
        _write(path, value)
    with pytest.raises(CHECKER.ProviderChangeError, match="dirty"):
        CHECKER.validate(*paths)


def test_strict_json_rejects_duplicate_and_nonfinite_values(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a": 1, "a": 2}', encoding="utf-8")
    with pytest.raises(CHECKER.ProviderChangeError, match="duplicate"):
        CHECKER.read_json(duplicate)
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"a": NaN}', encoding="utf-8")
    with pytest.raises(CHECKER.ProviderChangeError, match="non-finite"):
        CHECKER.read_json(nonfinite)


@pytest.mark.parametrize("contract", ["contracts/mcp.md", "contracts/huggingface.md"])
def test_non_inference_requires_registry_classification_and_no_binding(
    tmp_path: Path, contract: str
) -> None:
    paths = _case(tmp_path)
    change = json.loads(paths[0].read_text())
    change["changes"][0].update(
        {"contract_id": contract, "scope": "non_inference", "operations": []}
    )
    change["disposition"] = "informational"
    _write(paths[0], change)
    _rebind(paths)
    assert (
        CHECKER.validate(*paths)["input_sha256"]
        == hashlib.sha256(paths[0].read_bytes()).hexdigest()
    )
    inventory = json.loads(paths[3][0].read_text())
    inventory["bindings"][0]["contract_dependencies"].append(contract)
    _write(paths[3][0], inventory)
    with pytest.raises(CHECKER.ProviderChangeError, match="actual binding"):
        CHECKER.validate(*paths)


def test_missing_duplicate_and_weakened_registered_gates_fail(tmp_path: Path) -> None:
    paths = _case(tmp_path)
    python_verification = paths[4][0]
    evidence = json.loads(python_verification.read_text())
    evidence["gates"].pop()
    _write(python_verification, evidence)
    with pytest.raises(CHECKER.ProviderChangeError, match="missing required"):
        CHECKER.validate(*paths)

    paths = _case(tmp_path / "duplicate")
    evidence = json.loads(paths[4][0].read_text())
    evidence["gates"].append(evidence["gates"][0])
    _write(paths[4][0], evidence)
    with pytest.raises(CHECKER.ProviderChangeError, match="duplicate gate"):
        CHECKER.validate(*paths)

    paths = _case(tmp_path / "weakened")
    change = json.loads(paths[0].read_text())
    change["implementations"][0]["required_gate_ids"] = ["python-contracts"]
    _write(paths[0], change)
    input_sha = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    for path in [*paths[3], *paths[4]]:
        value = json.loads(path.read_text())
        value["input_sha256"] = input_sha
        _write(path, value)
    evidence = json.loads(paths[4][0].read_text())
    evidence["gates"] = evidence["gates"][:1]
    _write(paths[4][0], evidence)
    with pytest.raises(CHECKER.ProviderChangeError, match="missing required"):
        CHECKER.validate(*paths)


def test_owned_changed_path_and_candidate_draft_remain_fail_closed(tmp_path: Path) -> None:
    paths = _case(tmp_path)
    with pytest.raises(CHECKER.ProviderChangeError, match="owned changed path"):
        CHECKER.validate(*paths, changed_paths={"unowned.py"})

    paths = _case(tmp_path / "candidate")
    change = json.loads(paths[0].read_text())
    change["shared_spec"] = {
        "impact": "candidate_draft",
        "rationale": "Synthetic draft only.",
        "candidate": {"release_id": "candidate", "paths": ["specification/new.md"]},
    }
    _write(paths[0], change)
    input_sha = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    for path in [*paths[3], *paths[4]]:
        value = json.loads(path.read_text())
        value["input_sha256"] = input_sha
        _write(path, value)
    with pytest.raises(CHECKER.ProviderChangeError, match="candidate draft"):
        CHECKER.validate(*paths)


def test_registered_third_language_is_planned_without_language_branches(tmp_path: Path) -> None:
    paths = _case(tmp_path)
    registry = json.loads(paths[1].read_text())
    registry["implementations"] = [
        {
            "id": "third-language",
            "language": "Other",
            "root": "third",
            "exporter_argv": ["third-export"],
            "gates": [{"id": "third-gate", "argv": ["third-check"]}],
            "profile_claims": [],
        }
    ]
    change = json.loads(paths[0].read_text())
    change["implementations"] = [
        {
            "implementation_id": "third-language",
            "status": "updated",
            "rationale": "Synthetic registered implementation.",
            "owned_paths": ["third/adapter"],
            "required_gate_ids": ["third-gate"],
        }
    ]
    inventory = json.loads(paths[3][0].read_text())
    inventory["implementation_id"] = "third-language"
    verification = json.loads(paths[4][0].read_text())
    verification["implementation_id"] = "third-language"
    verification["gates"] = [
        {
            "id": "third-gate",
            "status": "passed",
            "exit_code": 0,
            "output_sha256": SHA,
            "log_sha256": SHA,
        }
    ]
    paths[3][0].unlink()
    paths[4][0].unlink()
    inventories = [_write(tmp_path / "third.inventory.json", inventory)]
    verifications = [_write(tmp_path / "third.verification.json", verification)]
    paths = (paths[0], paths[1], paths[2], inventories, verifications)
    _write(paths[0], change)
    _write(paths[1], registry)
    _rebind(paths)
    assert (
        CHECKER.validate(*paths, changed_paths={"third/adapter"})["inventory_artifacts"][0][
            "implementation_id"
        ]
        == "third-language"
    )


def test_shared_base_dependency_closure_rejects_unaffected_or_omitted_consumer(
    tmp_path: Path,
) -> None:
    paths = _case(tmp_path)
    assert CHECKER.validate(*paths)["input_sha256"]
    change = json.loads(paths[0].read_text())
    change["implementations"][0]["status"] = "unaffected"
    _write(paths[0], change)
    _rebind(paths)
    with pytest.raises(CHECKER.ProviderChangeError, match="unaffected"):
        CHECKER.validate(*paths)
    change["implementations"].pop()
    _write(paths[0], change)
    _rebind(paths)
    with pytest.raises(CHECKER.ProviderChangeError, match="account for every"):
        CHECKER.validate(*paths)


@pytest.mark.parametrize("unaffected_consumer", [0, 1])
def test_preset_fragment_and_inherited_compat_dependencies_expand_planner_closure(
    tmp_path: Path, unaffected_consumer: int
) -> None:
    paths = _case(tmp_path)
    preset_inventory = json.loads(paths[3][0].read_text())
    preset_inventory["bindings"] = [
        {
            "provider_id": "synthetic-preset",
            "operation": "generation",
            "contract_dependencies": ["contracts/openai-compat-presets.md#synthetic-preset"],
        }
    ]
    inherited_inventory = json.loads(paths[3][1].read_text())
    inherited_inventory["bindings"] = [
        {
            "provider_id": "synthetic-adapter",
            "operation": "generation",
            "contract_dependencies": ["contracts/openai-compat.md"],
        }
    ]
    _write(paths[3][0], preset_inventory)
    _write(paths[3][1], inherited_inventory)
    change = json.loads(paths[0].read_text())
    change["changes"] = [
        {
            "contract_id": "contracts/openai-compat-presets.md#synthetic-preset",
            "scope": "inference",
            "operations": ["generation"],
            "summary": "Synthetic preset snapshot update.",
        },
        {
            "contract_id": "contracts/openai-compat.md",
            "scope": "inference",
            "operations": ["generation"],
            "summary": "Synthetic inherited adapter base update.",
        },
    ]
    _write(paths[0], change)
    _rebind(paths)
    assert CHECKER.validate(*paths)["input_sha256"]
    change["implementations"][unaffected_consumer]["status"] = "unaffected"
    _write(paths[0], change)
    _rebind(paths)
    with pytest.raises(CHECKER.ProviderChangeError, match="unaffected"):
        CHECKER.validate(*paths)


def test_absent_binding_can_be_unsupported_but_candidate_shared_core_needs_gates(
    tmp_path: Path,
) -> None:
    paths = _case(tmp_path)
    inventory = json.loads(paths[3][1].read_text())
    inventory["bindings"] = []
    _write(paths[3][1], inventory)
    change = json.loads(paths[0].read_text())
    change["implementations"][1]["status"] = "unsupported"
    _write(paths[0], change)
    _rebind(paths)
    assert CHECKER.validate(*paths)["input_sha256"]
    change["shared_spec"] = {
        "impact": "candidate_draft",
        "rationale": "synthetic shared core",
        "candidate": {"release_id": "candidate", "paths": ["specification/new.md"]},
    }
    _write(paths[0], change)
    evidence = json.loads(paths[4][1].read_text())
    evidence["gates"] = [
        {
            "id": "unrelated-gate",
            "status": "passed",
            "exit_code": 0,
            "output_sha256": SHA,
            "log_sha256": SHA,
        }
    ]
    _write(paths[4][1], evidence)
    _rebind(paths)
    with pytest.raises(CHECKER.ProviderChangeError, match="missing required"):
        CHECKER.validate(*paths)
