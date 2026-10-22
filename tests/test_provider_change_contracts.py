"""Structural controls for immutable provider-change maintenance artifacts."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = ROOT / "maintenance"
FIXTURES = ROOT / "tests" / "fixtures" / "provider-change"
SCHEMAS = (
    "change.schema.json",
    "implementations.schema.json",
    "binding-inventory.schema.json",
    "verification.schema.json",
    "run-report.schema.json",
    "candidate-evidence.schema.json",
)
SHA = "a" * 64


def _git_revision(revision: str) -> str:
    return subprocess.check_output(["git", "rev-parse", revision], cwd=ROOT, text=True).strip()


GIT_COMMIT = _git_revision("HEAD")
GIT_TREE = _git_revision("HEAD^{tree}")


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((MAINTENANCE / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _provenance() -> dict[str, object]:
    return {
        "producer": {"id": "synthetic-producer", "version": "1"},
        "workflow_run": {"id": "local-synthetic", "attempt": 1},
        "trusted_pr_head": GIT_COMMIT,
        "evaluated_source": {
            "commit": GIT_COMMIT,
            "tree": GIT_TREE,
            "dirty": True,
            "input_fingerprint": SHA,
        },
        "registry_sha256": SHA,
        "input_sha256": SHA,
    }


def _inventory() -> dict[str, object]:
    return _provenance() | {
        "schema_version": 1,
        "implementation_id": "third-language",
        "bindings": [
            {
                "provider_id": "synthetic-provider",
                "operation": "generation",
                "contract_dependencies": ["contracts/openai-compat.md"],
            }
        ],
    }


def _verification() -> dict[str, object]:
    return _provenance() | {
        "schema_version": 1,
        "implementation_id": "third-language",
        "gates": [
            {
                "id": "third-language-contracts",
                "status": "passed",
                "exit_code": 0,
                "output_sha256": SHA,
                "log_sha256": SHA,
            }
        ],
    }


def _report() -> dict[str, object]:
    return _provenance() | {
        "schema_version": 1,
        "inventory_artifacts": [{"implementation_id": "third-language", "sha256": SHA}],
        "verification_artifacts": [{"implementation_id": "third-language", "sha256": SHA}],
    }


def test_all_contracts_are_draft_2020_12_schemas() -> None:
    for name in SCHEMAS:
        _validator(name)


def test_committed_registry_and_synthetic_declaration_are_valid_inputs() -> None:
    _validator("implementations.schema.json").validate(
        json.loads((MAINTENANCE / "implementations.json").read_text(encoding="utf-8"))
    )
    _validator("change.schema.json").validate(
        json.loads((FIXTURES / "synthetic-wire-change.json").read_text(encoding="utf-8"))
    )


def test_non_inference_scope_requires_no_inference_operations() -> None:
    declaration = json.loads((FIXTURES / "synthetic-wire-change.json").read_text())
    change = declaration["changes"][0]
    change["contract_id"] = "contracts/mcp.md"
    change["scope"] = "non_inference"
    change["operations"] = []
    declaration["disposition"] = "informational"
    declaration["implementations"] = [
        {
            "implementation_id": "anyinfer-python",
            "status": "unaffected",
            "rationale": "Synthetic out-of-binding-scope audit.",
            "owned_paths": [],
            "required_gate_ids": ["python-contracts"],
        },
        {
            "implementation_id": "anyinfer-csharp",
            "status": "unaffected",
            "rationale": "Synthetic out-of-binding-scope audit.",
            "owned_paths": [],
            "required_gate_ids": ["csharp-workspace"],
        },
    ]
    _validator("change.schema.json").validate(declaration)
    change["operations"] = ["generation"]
    with pytest.raises(ValidationError):
        _validator("change.schema.json").validate(declaration)

    change["scope"] = "inference"
    change["operations"] = []
    with pytest.raises(ValidationError):
        _validator("change.schema.json").validate(declaration)


def test_python_registration_lists_the_baseline_workspace_gates() -> None:
    registry = json.loads((MAINTENANCE / "implementations.json").read_text(encoding="utf-8"))
    python = next(item for item in registry["implementations"] if item["id"] == "anyinfer-python")
    assert python["gates"] == [
        {
            "id": "python-contracts",
            "argv": ["{sys.executable}", "workspace.py", "check", "--only=contracts"],
        },
        {
            "id": "python-fixtures",
            "argv": ["{sys.executable}", "workspace.py", "check", "--only=fixtures"],
        },
        {
            "id": "python-conformance",
            "argv": ["{sys.executable}", "workspace.py", "check", "--only=conformance"],
        },
        {
            "id": "python-tests",
            "argv": ["{sys.executable}", "workspace.py", "check", "--only=test"],
        },
    ]
    assert registry["non_inference_contracts"] == ["contracts/mcp.md", "contracts/huggingface.md"]


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        ("binding-inventory.schema.json", _inventory()),
        ("verification.schema.json", _verification()),
        ("run-report.schema.json", _report()),
    ],
)
def test_generated_artifact_envelopes_accept_a_generic_third_language(
    schema: str, payload: dict[str, object]
) -> None:
    _validator(schema).validate(payload)


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        ("binding-inventory.schema.json", _inventory()),
        ("verification.schema.json", _verification()),
        ("run-report.schema.json", _report()),
    ],
)
def test_provenance_accepts_current_git_commit_and_tree_ids(
    schema: str, payload: dict[str, object]
) -> None:
    _validator(schema).validate(payload)


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        ("binding-inventory.schema.json", _inventory()),
        ("verification.schema.json", _verification()),
        ("run-report.schema.json", _report()),
    ],
)
def test_provenance_rejects_content_hashes_in_git_identity_fields(
    schema: str, payload: dict[str, object]
) -> None:
    invalid = copy.deepcopy(payload)
    invalid["trusted_pr_head"] = SHA
    with pytest.raises(ValidationError):
        _validator(schema).validate(invalid)

    invalid = copy.deepcopy(payload)
    invalid["evaluated_source"]["tree"] = SHA  # type: ignore[index]
    with pytest.raises(ValidationError):
        _validator(schema).validate(invalid)


@pytest.mark.parametrize(
    ("schema", "payload", "mutation"),
    [
        (
            "change.schema.json",
            json.loads((FIXTURES / "synthetic-wire-change.json").read_text()),
            "remove-source",
        ),
        (
            "implementations.schema.json",
            json.loads((MAINTENANCE / "implementations.json").read_text()),
            "unknown-field",
        ),
        ("binding-inventory.schema.json", _inventory(), "empty-dependencies"),
        ("verification.schema.json", _verification(), "unknown-field"),
        ("run-report.schema.json", _report(), "unknown-field"),
    ],
)
def test_contracts_reject_missing_or_unknown_or_incomplete_shapes(
    schema: str, payload: dict[str, object], mutation: str
) -> None:
    invalid = copy.deepcopy(payload)
    if mutation == "remove-source":
        invalid.pop("sources")
    elif mutation == "empty-dependencies":
        invalid["bindings"][0]["contract_dependencies"] = []  # type: ignore[index]
    else:
        invalid["invented"] = True
    with pytest.raises(ValidationError):
        _validator(schema).validate(invalid)


def test_candidate_reference_is_required_only_for_candidate_draft() -> None:
    declaration = json.loads((FIXTURES / "synthetic-wire-change.json").read_text())
    declaration["shared_spec"]["impact"] = "candidate_draft"
    with pytest.raises(ValidationError):
        _validator("change.schema.json").validate(declaration)

    declaration["shared_spec"]["candidate"] = {
        "release_id": "core-generation-v-next",
        "paths": ["specification/core-generation-next.md"],
    }
    _validator("change.schema.json").validate(declaration)
    declaration["shared_spec"]["impact"] = "no_delta"
    with pytest.raises(ValidationError):
        _validator("change.schema.json").validate(declaration)


def test_updated_status_requires_an_owned_path() -> None:
    declaration = json.loads((FIXTURES / "synthetic-wire-change.json").read_text())
    declaration["implementations"][0]["owned_paths"] = []
    with pytest.raises(ValidationError):
        _validator("change.schema.json").validate(declaration)


def test_declaration_cannot_embed_generated_outcome_evidence() -> None:
    declaration = json.loads((FIXTURES / "synthetic-wire-change.json").read_text())
    declaration["verification_sha256"] = SHA
    with pytest.raises(ValidationError):
        _validator("change.schema.json").validate(declaration)


def test_unverifiable_declaration_is_blocked_without_claiming_completion() -> None:
    declaration = json.loads((FIXTURES / "synthetic-wire-change.json").read_text())
    declaration["disposition"] = "unverifiable"
    declaration["shared_spec"]["impact"] = "blocked"
    _validator("change.schema.json").validate(declaration)

    declaration["disposition"] = "fictional"
    with pytest.raises(ValidationError):
        _validator("change.schema.json").validate(declaration)


@pytest.mark.parametrize(("field", "value"), [("url", "not a URI"), ("fetched_at", "2026-02-30")])
def test_source_urls_and_dates_use_json_schema_format_validation(field: str, value: str) -> None:
    declaration = json.loads((FIXTURES / "synthetic-wire-change.json").read_text())
    declaration["sources"][0][field] = value
    with pytest.raises(ValidationError):
        _validator("change.schema.json").validate(declaration)
