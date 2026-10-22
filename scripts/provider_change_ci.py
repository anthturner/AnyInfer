"""Trusted CI routing and aggregation for provider-change maintenance evidence.

This module deliberately has two small jobs: select a committed production declaration from
changed paths, and aggregate artifacts produced by the registered dispatcher.  It neither
executes registered commands nor treats a declaration or downloaded artifact as a source of
Git truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MAINTENANCE = ROOT / "maintenance"
CHANGES = MAINTENANCE / "changes"


class ProviderChangeCIError(ValueError):
    """CI routing or aggregation inputs are not trustworthy enough to use."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, Any]:
    """Read a declaration for routing only; schema validation belongs to the runner."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProviderChangeCIError(f"invalid changed declaration {path}: {error}") from error
    if not isinstance(value, dict):
        raise ProviderChangeCIError("selected declaration must be a JSON object")
    return value


def _is_substantive(path: str) -> bool:
    """Return whether a changed path needs a provider-change declaration.

    Maintenance machinery itself is intentionally not substantive: this repository can
    manually change the guard without inventing a provider claim.  Only provider snapshot
    contracts and normative/shared candidate assets are substantive.  Ordinary source
    changes stay on normal CI; a record can still declare source paths for validator
    coverage, but source changes do not manufacture provider-change applicability.
    """
    if re.fullmatch(r"contracts/[a-z0-9-]+\.md", path):
        return True
    if path in {"specification/core-generation.md", "specification/accounting-v1.md"}:
        return True
    return path.startswith(
        (
            "specification/fixtures/",
            "specification/inventories/",
            "specification/reference/",
            "specification/releases/",
            "specification/schemas/",
        )
    )


def select(changed_paths: set[str]) -> dict[str, Any]:
    """Select the one changed production declaration, or an explicit honest no-op."""
    records = sorted(path for path in CHANGES.glob("*.json") if path.is_file())
    changed_records = [
        path for path in records if path.relative_to(ROOT).as_posix() in changed_paths
    ]
    substantive = sorted(path for path in changed_paths if _is_substantive(path))
    if len(changed_records) > 1:
        raise ProviderChangeCIError(
            "one CI run may select exactly one provider-change declaration"
        )
    if not changed_records:
        if substantive:
            raise ProviderChangeCIError(
                "provider snapshot or normative shared asset changes require a changed "
                "maintenance/changes declaration"
            )
        return {"schema_version": 1, "applicable": False, "reason": "no-applicable-record"}

    record = changed_records[0]
    value = _record(record)
    implementation_ids = [
        item.get("implementation_id") for item in value.get("implementations", [])
    ]
    if not implementation_ids or any(not isinstance(item, str) for item in implementation_ids):
        raise ProviderChangeCIError("selected declaration has no implementation declarations")
    return {
        "schema_version": 1,
        "applicable": True,
        "input": record.relative_to(ROOT).as_posix(),
        "input_sha256": _sha(record),
        "implementation_ids": sorted(implementation_ids),
        "changed_paths": sorted(changed_paths),
    }


def select_manual(
    input_path: str | None,
    candidate_evidence_path: str | None,
    candidate_qualification_json: str | None,
    candidate_artifact_run_id: str | None,
    candidate_artifact_name: str | None,
) -> dict[str, Any] | None:
    """Select one operator-supplied candidate declaration for manual CI only."""
    supplied = (
        input_path,
        candidate_evidence_path,
        candidate_qualification_json,
        candidate_artifact_run_id,
        candidate_artifact_name,
    )
    if not any(supplied):
        return None
    if not all(supplied):
        raise ProviderChangeCIError(
            "manual candidate qualification requires declaration, artifact, evidence, "
            "and expected facts together"
        )
    if not isinstance(input_path, str) or not re.fullmatch(
        r"maintenance/changes/[a-z0-9][a-z0-9-]{1,62}\.json", input_path
    ):
        raise ProviderChangeCIError("manual input must name a canonical production declaration")
    path = ROOT / input_path
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(CHANGES.resolve())
    ):
        raise ProviderChangeCIError(
            "manual input must be an existing non-link production declaration"
        )
    if (
        candidate_evidence_path is None
        or Path(candidate_evidence_path).is_absolute()
        or ".." in Path(candidate_evidence_path).parts
    ):
        raise ProviderChangeCIError(
            "manual candidate evidence must be a safe path inside the downloaded bundle"
        )
    if not isinstance(candidate_artifact_run_id, str) or not re.fullmatch(
        r"[1-9][0-9]*", candidate_artifact_run_id
    ):
        raise ProviderChangeCIError("manual candidate artifact run ID is invalid")
    if not isinstance(candidate_artifact_name, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", candidate_artifact_name
    ):
        raise ProviderChangeCIError("manual candidate artifact name is invalid")
    try:
        qualification = json.loads(candidate_qualification_json)
    except (TypeError, json.JSONDecodeError) as error:
        raise ProviderChangeCIError("manual expected facts must be JSON") from error
    if not isinstance(qualification, dict):
        raise ProviderChangeCIError("manual expected facts must be a JSON object")
    value = _record(path)
    if value.get("shared_spec", {}).get("impact") != "candidate_draft":
        raise ProviderChangeCIError("manual input must declare candidate_draft shared impact")
    return {
        "schema_version": 1,
        "applicable": True,
        "input": input_path,
        "input_sha256": _sha(path),
        "implementation_ids": sorted(
            item.get("implementation_id") for item in value.get("implementations", [])
        ),
        "changed_paths": None,
        "manual_candidate_qualification": True,
    }


def _artifact_files(directories: list[Path], name: str) -> list[Path]:
    return sorted(
        path for directory in directories for path in directory.rglob(name) if path.is_file()
    )


def aggregate(
    input_path: Path,
    registry_path: Path,
    artifact_dirs: list[Path],
    trusted_pr_head: str,
    workflow_run_id: str,
    workflow_run_attempt: int,
    output_path: Path,
    changed_paths: set[str] | None = None,
    event_name: str = "",
    actor: str = "",
    candidate_evidence: Path | None = None,
    candidate_qualification: Path | None = None,
    manual_bundle_root: Path | None = None,
    candidate_artifact_run_id: str | None = None,
    candidate_artifact_name: str | None = None,
) -> dict[str, Any]:
    """Validate same-run artifacts against Git facts captured in this checkout."""
    if len(trusted_pr_head) != 40 or any(
        char not in "0123456789abcdef" for char in trusted_pr_head
    ):
        raise ProviderChangeCIError("trusted PR head must be a 40-character lowercase Git commit")
    if workflow_run_attempt < 1:
        raise ProviderChangeCIError("workflow run attempt must be positive")
    if not input_path.resolve().is_relative_to(CHANGES.resolve()):
        raise ProviderChangeCIError("input must be a production maintenance/changes declaration")
    manual = any(
        item is not None
        for item in (
            candidate_evidence,
            candidate_qualification,
            manual_bundle_root,
            candidate_artifact_run_id,
            candidate_artifact_name,
        )
    )
    if manual and event_name != "workflow_dispatch":
        raise ProviderChangeCIError("candidate qualification inputs are workflow_dispatch-only")
    if manual and (
        candidate_evidence is None
        or candidate_qualification is None
        or manual_bundle_root is None
        or candidate_artifact_run_id is None
        or candidate_artifact_name is None
    ):
        raise ProviderChangeCIError(
            "candidate evidence and expected facts must be supplied together"
        )
    # These modules depend on jsonschema, which the cheap `changes` classifier need not
    # install.  Import them only in the fully provisioned aggregation job.
    sys.path.insert(0, str(Path(__file__).parent))
    from check_provider_change import ProviderChangeError, validate
    from run_provider_change_checks import _source_identity

    inventories = _artifact_files(artifact_dirs, "inventory.json")
    verifications = _artifact_files(artifact_dirs, "verification.json")
    if not inventories or not verifications:
        raise ProviderChangeCIError(
            "missing required dispatcher inventory or verification artifacts"
        )
    context: dict[str, Any] = {
        "producer": {"id": "provider-change-ci", "version": "1"},
        "workflow_run": {"id": workflow_run_id, "attempt": workflow_run_attempt},
        "trusted_pr_head": trusted_pr_head,
        "evaluated_source": _source_identity(),
    }
    receipt: dict[str, Any] | None = None
    if manual:
        if (
            candidate_evidence is None
            or candidate_qualification is None
            or manual_bundle_root is None
            or candidate_artifact_run_id is None
            or candidate_artifact_name is None
        ):
            raise ProviderChangeCIError("candidate qualification is incomplete")
        evidence = candidate_evidence.resolve(strict=True)
        bundle = manual_bundle_root.resolve(strict=True)
        if (
            candidate_evidence.is_symlink()
            or not evidence.is_file()
            or not evidence.is_relative_to(bundle)
        ):
            raise ProviderChangeCIError(
                "candidate evidence must be an existing regular file inside the downloaded bundle"
            )
        qualification = _record(candidate_qualification)
        context["candidate_qualification"] = qualification
        receipt = {
            "schema_version": 1,
            "event": event_name,
            "actor": actor,
            "workflow_run": context["workflow_run"],
            "trusted_pr_head": trusted_pr_head,
            "evaluated_source": context["evaluated_source"],
            "input": input_path.relative_to(ROOT).as_posix(),
            "input_sha256": _sha(input_path),
            "candidate_evidence_sha256": _sha(evidence),
            "candidate_qualification_sha256": _sha(candidate_qualification),
            "candidate_artifact": {
                "run_id": candidate_artifact_run_id,
                "name": candidate_artifact_name,
            },
        }
    context_path = output_path.parent / "provider-change-trusted-context.json"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(json.dumps(context, sort_keys=True) + "\n", encoding="utf-8")
    try:
        report = validate(
            input_path,
            registry_path,
            context_path,
            inventories,
            verifications,
            changed_paths,
            candidate_evidence.resolve() if candidate_evidence else None,
        )
    except ProviderChangeError as error:
        raise ProviderChangeCIError(str(error)) from error
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if receipt is not None:
        output_path.with_name("provider-change-dispatch-receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def main() -> int:
    """Run selection or aggregation without accepting facts from a change declaration."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    select_parser = commands.add_parser("select")
    select_parser.add_argument("--changed-paths", type=Path, required=True)
    select_parser.add_argument("--event-name", required=True)
    select_parser.add_argument("--manual-input-path")
    select_parser.add_argument("--candidate-evidence-path")
    select_parser.add_argument("--candidate-qualification-json")
    select_parser.add_argument("--candidate-artifact-run-id")
    select_parser.add_argument("--candidate-artifact-name")
    select_parser.add_argument("--output", type=Path, required=True)
    aggregate_parser = commands.add_parser("aggregate")
    aggregate_parser.add_argument("--input", type=Path, required=True)
    aggregate_parser.add_argument("--registry", type=Path, required=True)
    aggregate_parser.add_argument("--artifact-dir", type=Path, action="append", required=True)
    aggregate_parser.add_argument("--trusted-pr-head", required=True)
    aggregate_parser.add_argument("--workflow-run-id", required=True)
    aggregate_parser.add_argument("--workflow-run-attempt", type=int, required=True)
    aggregate_parser.add_argument("--changed-paths-json", default="[]")
    aggregate_parser.add_argument("--event-name", required=True)
    aggregate_parser.add_argument("--actor", default="")
    aggregate_parser.add_argument("--candidate-evidence", type=Path)
    aggregate_parser.add_argument("--candidate-qualification", type=Path)
    aggregate_parser.add_argument("--manual-bundle-root", type=Path)
    aggregate_parser.add_argument("--candidate-artifact-run-id")
    aggregate_parser.add_argument("--candidate-artifact-name")
    aggregate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "select":
            manual = select_manual(
                args.manual_input_path,
                args.candidate_evidence_path,
                args.candidate_qualification_json,
                args.candidate_artifact_run_id,
                args.candidate_artifact_name,
            )
            if manual is not None and args.event_name != "workflow_dispatch":
                raise ProviderChangeCIError(
                    "manual candidate qualification is workflow_dispatch-only"
                )
            changed = set(args.changed_paths.read_text(encoding="utf-8").splitlines())
            result = manual or select(changed)
            args.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        else:
            changed_value = json.loads(args.changed_paths_json)
            if changed_value is not None and (
                not isinstance(changed_value, list)
                or not all(isinstance(item, str) for item in changed_value)
            ):
                raise ProviderChangeCIError("changed paths must be a JSON string array or null")
            aggregate(
                args.input,
                args.registry,
                args.artifact_dir,
                args.trusted_pr_head,
                args.workflow_run_id,
                args.workflow_run_attempt,
                args.output,
                set(changed_value) if changed_value is not None else None,
                args.event_name,
                args.actor,
                args.candidate_evidence,
                args.candidate_qualification,
                args.manual_bundle_root,
                args.candidate_artifact_run_id,
                args.candidate_artifact_name,
            )
    except (OSError, ProviderChangeCIError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
