"""Pure validator for provider-change declarations and produced evidence.

This module never invokes registered commands.  The runner supplies inventories and gate
artifacts; this checker only validates their immutable bytes and trusted CI context.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_ROOT = ROOT
MAINTENANCE = ROOT / "maintenance"


class ProviderChangeError(ValueError):
    """A declaration or supplied evidence does not meet the closed contract."""


def _reject_constant(value: str) -> None:
    raise ProviderChangeError(f"non-finite JSON constant {value!r} is forbidden")


def read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    """Read one strict JSON object and retain its exact bytes for provenance."""
    raw = path.read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderChangeError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ProviderChangeError(f"{path}: expected a JSON object")
    return value, raw


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProviderChangeError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _validate(value: dict[str, Any], schema_name: str) -> None:
    schema, _ = read_json(MAINTENANCE / schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=str)
    if errors:
        raise ProviderChangeError(f"{schema_name}: {errors[0].message}")


def _same_context(artifact: dict[str, Any], context: dict[str, Any], label: str) -> None:
    for key in ("workflow_run", "trusted_pr_head", "evaluated_source"):
        if artifact.get(key) != context.get(key):
            raise ProviderChangeError(f"{label}: {key} does not match trusted context")


def _closed_path(root: Path, name: object, label: str) -> Path:
    """Resolve a relative evidence path without permitting escapes or symlinks."""
    if not isinstance(name, str) or not name or Path(name).is_absolute() or "\\" in name:
        raise ProviderChangeError(f"{label}: path is not a closed relative path")
    path = root / name
    try:
        resolved = path.resolve(strict=True)
        base = root.resolve(strict=True)
    except OSError as error:
        raise ProviderChangeError(f"{label}: referenced path is unavailable") from error
    if base not in (resolved, *resolved.parents) or path.is_symlink():
        raise ProviderChangeError(f"{label}: referenced path escapes evidence root")
    return resolved


def _hash_file(root: Path, name: object, expected: object, label: str) -> tuple[Path, bytes]:
    if not isinstance(expected, str) or len(expected) != 64:
        raise ProviderChangeError(f"{label}: hash is invalid")
    path = _closed_path(root, name, label)
    raw = path.read_bytes()
    if _sha(raw) != expected:
        raise ProviderChangeError(f"{label}: raw-byte hash mismatch")
    return path, raw


def _no_pending(value: object) -> bool:
    if value == "pending":
        return False
    if isinstance(value, dict):
        return all(_no_pending(key) and _no_pending(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_no_pending(item) for item in value)
    return True


def _candidate_qualification(
    evidence_path: Path,
    change_raw: bytes,
    registry_raw: bytes,
    context: dict[str, Any],
    implementations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Validate candidate files against *independent* trusted qualification facts.

    This deliberately reads generic candidate assets rather than the v0 release loader;
    loading the latter would silently impose the sealed core-generation/v0 identity.
    """
    evidence, _ = read_json(evidence_path)
    _validate(evidence, "candidate-evidence.schema.json")
    trusted = context.get("candidate_qualification")
    if not isinstance(trusted, dict):
        raise ProviderChangeError("candidate qualification lacks independent trusted context")
    evidence_root = evidence_path.parent
    canonical_root = ROOT
    if evidence["input_sha256"] != _sha(change_raw) or evidence["registry_sha256"] != _sha(
        registry_raw
    ):
        raise ProviderChangeError("candidate evidence does not bind raw declaration and registry")
    # These facts are intentionally not inferred from the wrapper or declaration.
    for key in ("input_revision_a", "candidate_commit_b", "candidate_tree_b", "support_claimset"):
        if trusted.get(key) != evidence.get(key):
            raise ProviderChangeError(f"candidate evidence does not match trusted {key}")
    if not trusted.get("reference_run_clean") or not trusted.get("reference_ancestry_verified"):
        raise ProviderChangeError("candidate qualification lacks clean reference provenance")
    canonical_paths = [
        evidence["candidate_manifest"]["path"],
        evidence["reference"]["path"],
        evidence["reference"]["environment_path"],
        evidence["inventory"]["path"],
        *evidence["schemas"],
        *(item["path"] for item in evidence["normative"].values()),
        *(item["path"] for item in evidence["case_inputs"]),
    ]
    if any(not name.startswith("specification/") for name in canonical_paths):
        raise ProviderChangeError(
            "candidate canonical assets must be repository specification paths"
        )
    outer_source = context["evaluated_source"]
    if (
        outer_source.get("commit") != evidence["candidate_commit_b"]
        or outer_source.get("tree") != evidence["candidate_tree_b"]
        or outer_source.get("dirty")
    ):
        raise ProviderChangeError("candidate B does not bind the trusted evaluated checkout")
    manifest_row = evidence["candidate_manifest"]
    manifest_path, manifest_raw = _hash_file(
        canonical_root, manifest_row["path"], manifest_row["sha256"], "candidate manifest"
    )
    manifest, _ = read_json(manifest_path)
    required_manifest = {
        "release",
        "profile",
        "profile_revision",
        "reference_manifest",
        "files",
        "case_inventory",
    }
    if not required_manifest <= set(manifest) or manifest.get("release") != evidence["release_id"]:
        raise ProviderChangeError("candidate manifest identity is invalid")
    if (
        manifest.get("profile") != evidence["profile"]
        or manifest.get("profile_revision") != evidence["profile_revision"]
    ):
        raise ProviderChangeError("candidate manifest profile does not match evidence")
    files = manifest.get("files")
    if not isinstance(files, dict) or list(files) != sorted(files) or not files:
        raise ProviderChangeError("candidate manifest file set is not closed and sorted")
    assets = evidence["assets"]
    asset_names = {item["path"] for item in assets}
    normative_files = {item["path"] for item in evidence["normative"].values()}
    if len(normative_files) != 3:
        raise ProviderChangeError("candidate normative asset roles overlap")
    for item in assets:
        _, raw = _hash_file(canonical_root, item["path"], item["sha256"], "candidate asset")
        if files[item["path"]] != item["sha256"]:
            raise ProviderChangeError("candidate asset does not match manifest hash")
        if item["path"] == evidence["inventory"]["path"] or item["path"] in evidence["schemas"]:
            try:
                parsed = json.loads(
                    raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ProviderChangeError(
                    "candidate inventory or schema is invalid JSON"
                ) from error
            if not _no_pending(parsed):
                raise ProviderChangeError("candidate assets contain pending expectations")
    inventory_path, inventory_raw = _hash_file(
        canonical_root,
        evidence["inventory"]["path"],
        evidence["inventory"]["sha256"],
        "candidate inventory",
    )
    if (
        evidence["inventory"]["path"] not in files
        or _sha(inventory_raw) != files[evidence["inventory"]["path"]]
    ):
        raise ProviderChangeError("candidate inventory is not a manifest asset")
    inventory, _ = read_json(inventory_path)
    cases = inventory.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ProviderChangeError("candidate inventory has no cases")
    case_ids = [item.get("id") for item in cases if isinstance(item, dict)]
    if (
        len(case_ids) != len(cases)
        or len(set(case_ids)) != len(case_ids)
        or any(not isinstance(item, str) for item in case_ids)
    ):
        raise ProviderChangeError("candidate inventory case IDs are invalid")
    embedded_cases = manifest["case_inventory"]
    if not isinstance(embedded_cases, list):
        raise ProviderChangeError("candidate manifest case inventory is invalid")
    record_fields = ("id", "kind", "path", "family", "extension")
    embedded_by_id: dict[str, tuple[object, ...]] = {}
    for row in embedded_cases:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or row["id"] in embedded_by_id
        ):
            raise ProviderChangeError(
                "candidate manifest case inventory has duplicate or invalid IDs"
            )
        embedded_by_id[row["id"]] = tuple(row.get(field) for field in record_fields)
    inventory_by_id = {
        item["id"]: tuple(item.get(field) for field in record_fields)
        for item in cases
        if isinstance(item, dict)
    }
    if embedded_by_id != inventory_by_id:
        raise ProviderChangeError("candidate manifest does not exactly bind inventory")
    fixture_paths = {
        item["id"]: item.get("path")
        for item in cases
        if isinstance(item, dict) and item.get("kind") == "fixture"
    }
    case_inputs = {item["id"]: item for item in evidence["case_inputs"]}
    if set(case_inputs) != set(fixture_paths) or len(case_inputs) != len(evidence["case_inputs"]):
        raise ProviderChangeError("candidate case inputs do not exactly cover fixture cases")
    for case_id, expected_path in fixture_paths.items():
        row = case_inputs[case_id]
        if row["path"] != expected_path:
            raise ProviderChangeError("candidate case input does not match inventory path")
        _hash_file(canonical_root, row["path"], row["sha256"], f"candidate case input {case_id}")
    ref_path, _ref_raw = _hash_file(
        canonical_root,
        evidence["reference"]["path"],
        evidence["reference"]["sha256"],
        "reference manifest",
    )
    environment_path, environment_raw = _hash_file(
        canonical_root,
        evidence["reference"]["environment_path"],
        evidence["reference"]["environment_sha256"],
        "reference environment",
    )
    reference, _ = read_json(ref_path)
    environment, _ = read_json(environment_path)
    try:
        helper_spec = importlib.util.spec_from_file_location(
            "portable_release_assets", SCRIPT_ROOT / "scripts" / "portable_release_assets.py"
        )
        if helper_spec is None or helper_spec.loader is None:
            raise ImportError("portable reference validator is unavailable")
        helper = importlib.util.module_from_spec(helper_spec)
        sys.modules[helper_spec.name] = helper
        helper_spec.loader.exec_module(helper)
        helper.validate_reference_evidence(
            reference, environment, environment_sha256=_sha(environment_raw)
        )
    except (ImportError, ValueError) as error:
        raise ProviderChangeError(f"candidate reference evidence is invalid: {error}") from error
    if (
        manifest.get("reference_manifest") != evidence["reference"]["path"]
        or reference.get("reference_run_revision") != evidence["input_revision_a"]
        or reference.get("driver", {}).get("git_revision") != evidence["input_revision_a"]
    ):
        raise ProviderChangeError("candidate reference evidence does not bind revision A")
    required_assets = (
        normative_files
        | {
            evidence["inventory"]["path"],
            evidence["reference"]["path"],
            evidence["reference"]["environment_path"],
        }
        | set(evidence["schemas"])
        | {row["path"] for row in evidence["case_inputs"]}
    )
    if (
        set(files) != required_assets
        or asset_names != required_assets
        or len(asset_names) != len(assets)
    ):
        raise ProviderChangeError("candidate assets do not exactly equal the classified corpus")
    required_claimants = {"anyinfer-python"} | {
        ident
        for ident, item in implementations.items()
        if evidence["profile"] in item["profile_claims"]
    }
    if (
        set(evidence["support_claimset"]) != required_claimants
        or set(trusted["support_claimset"]) != required_claimants
    ):
        raise ProviderChangeError("candidate support claimset is incomplete")
    reports = {item["implementation_id"]: item for item in evidence["reports"]}
    if set(reports) != required_claimants or len(reports) != len(evidence["reports"]):
        raise ProviderChangeError("candidate reports do not cover every claimant exactly once")
    expected_digests = trusted.get("expected_artifact_digests")
    expected_runs = trusted.get("report_runs")
    if not isinstance(expected_digests, dict) or not isinstance(expected_runs, dict):
        raise ProviderChangeError("candidate qualification lacks trusted report facts")
    for ident, row in reports.items():
        report_path, report_raw = _hash_file(
            evidence_root, row["path"], row["sha256"], f"{ident} candidate report"
        )
        if (
            expected_digests.get(ident) != _sha(report_raw)
            or expected_runs.get(ident) != row["run_identity"]
        ):
            raise ProviderChangeError(f"{ident}: report does not match trusted run facts")
        report, _ = read_json(report_path)
        if report.get("report_version") != "0":
            raise ProviderChangeError("candidate report grammar is unregistered")
        schema_path = next(
            (name for name in evidence["schemas"] if name.endswith("report-v0.schema.json")), None
        )
        if schema_path is None:
            raise ProviderChangeError("candidate report schema asset is missing")
        schema_file, _ = _hash_file(
            canonical_root, schema_path, files[schema_path], "candidate report schema"
        )
        schema, _ = read_json(schema_file)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report),
            key=str,
        )
        if errors:
            raise ProviderChangeError(
                f"{ident}: candidate report violates report grammar: {errors[0].message}"
            )
        if report.get("release") != evidence["release_id"] or report.get("release_sha256") != _sha(
            manifest_raw
        ):
            raise ProviderChangeError(f"{ident}: report release identity mismatch")
        implementation = report.get("implementation")
        expected_run = row["run_identity"]
        if (
            not isinstance(implementation, dict)
            or implementation.get("name") != ident
            or not isinstance(expected_run, dict)
            or implementation.get("source_revision") != expected_run.get("source_revision")
            or implementation.get("driver_revision") != expected_run.get("driver_revision")
            or any(
                not isinstance(expected_run.get(key), str)
                or len(expected_run[key]) != 40
                or any(character not in "0123456789abcdef" for character in expected_run[key])
                for key in ("source_revision", "driver_revision")
            )
        ):
            raise ProviderChangeError(f"{ident}: report implementation provenance is untrusted")
        results = report.get("cases")
        try:
            helper.validate_successful_cases(
                results,
                {item["id"]: item for item in cases if isinstance(item, dict)},
                declared_extensions=implementation.get("extensions"),
                specification_root=SCRIPT_ROOT / "specification",
            )
            fixture_spec = importlib.util.spec_from_file_location(
                "candidate_validate_fixtures", SCRIPT_ROOT / "scripts" / "validate_fixtures.py"
            )
            if fixture_spec is None or fixture_spec.loader is None:
                raise ImportError("trusted fixture validator is unavailable")
            fixture_validator = importlib.util.module_from_spec(fixture_spec)
            sys.modules[fixture_spec.name] = fixture_validator
            fixture_spec.loader.exec_module(fixture_validator)
            problems = fixture_validator.validate_report(
                report, specification_root=SCRIPT_ROOT / "specification"
            )
        except (ImportError, ValueError) as error:
            raise ProviderChangeError(
                f"{ident}: candidate report validation failed: {error}"
            ) from error
        if problems:
            raise ProviderChangeError(
                f"{ident}: candidate report validation failed: {problems[0]}"
            )
        if not isinstance(results, list) or not _no_pending(report):
            raise ProviderChangeError(f"{ident}: candidate report has pending or invalid results")
        counts = {
            verdict: sum(
                item.get("verdict") == verdict for item in results if isinstance(item, dict)
            )
            for verdict in ("pass", "fail", "error", "extension")
        }
        if report.get("counts") != counts or counts["fail"] or counts["error"]:
            raise ProviderChangeError(
                f"{ident}: candidate report counts are stale or unsuccessful"
            )
    review = evidence["review"]
    if (
        trusted.get("review_identity") != review["identity"]
        or trusted.get("review_disposition") != review["disposition"]
        or trusted.get("reviewed_candidate_commit_b") != evidence["candidate_commit_b"]
    ):
        raise ProviderChangeError("candidate review does not match independent trusted facts")
    if review["disposition"] != "approved":
        raise ProviderChangeError("candidate review is not approved")
    return {
        "release_id": evidence["release_id"],
        "manifest_sha256": _sha(manifest_raw),
        "report_count": len(reports),
    }


def validate(
    input_path: Path,
    registry_path: Path,
    context_path: Path,
    inventory_paths: list[Path],
    verification_paths: list[Path],
    changed_paths: set[str] | None = None,
    candidate_evidence: Path | None = None,
) -> dict[str, Any]:
    """Validate evidence and return a report; this function has no side effects."""
    change, change_raw = read_json(input_path)
    registry, registry_raw = read_json(registry_path)
    context, _ = read_json(context_path)
    _validate(change, "change.schema.json")
    _validate(registry, "implementations.schema.json")
    input_sha, registry_sha = _sha(change_raw), _sha(registry_raw)
    implementations = {item["id"]: item for item in registry["implementations"]}
    if len(implementations) != len(registry["implementations"]):
        raise ProviderChangeError("registry has duplicate implementation IDs")
    declared = {item["implementation_id"]: item for item in change["implementations"]}
    if set(declared) != set(implementations) or len(declared) != len(change["implementations"]):
        raise ProviderChangeError(
            "declaration must account for every registered implementation exactly once"
        )

    inventories: dict[str, tuple[dict[str, Any], bytes]] = {}
    for path in inventory_paths:
        value, raw = read_json(path)
        _validate(value, "binding-inventory.schema.json")
        impl = value["implementation_id"]
        if impl in inventories or impl not in implementations:
            raise ProviderChangeError("inventory implementation membership is invalid")
        _same_context(value, context, str(path))
        if value["input_sha256"] != input_sha or value["registry_sha256"] != registry_sha:
            raise ProviderChangeError(f"{path}: immutable input or registry hash mismatch")
        inventories[impl] = (value, raw)
    if set(inventories) != set(implementations):
        raise ProviderChangeError("exactly one current inventory is required per implementation")

    non_inference = set(registry["non_inference_contracts"])
    affected: dict[str, set[tuple[str, str]]] = {key: set() for key in implementations}
    for item in change["changes"]:
        contract, scope = item["contract_id"], item["scope"]
        if scope == "non_inference":
            if contract not in non_inference:
                raise ProviderChangeError("non-inference contract is not registered")
            has_dependency = any(
                contract in binding["contract_dependencies"]
                for inventory, _ in inventories.values()
                for binding in inventory["bindings"]
            )
            if has_dependency:
                raise ProviderChangeError(
                    "non-inference contract has an actual binding dependency"
                )
            continue
        if contract in non_inference:
            raise ProviderChangeError("registered non-inference contract cannot bypass closure")
        for impl, (inventory, _) in inventories.items():
            for binding in inventory["bindings"]:
                if (
                    contract in binding["contract_dependencies"]
                    and binding["operation"] in item["operations"]
                ):
                    affected[impl].add((binding["provider_id"], binding["operation"]))

    verification: dict[str, list[tuple[dict[str, Any], bytes]]] = {
        key: [] for key in implementations
    }
    for path in verification_paths:
        value, raw = read_json(path)
        _validate(value, "verification.schema.json")
        impl = value["implementation_id"]
        if impl not in verification:
            raise ProviderChangeError("verification implementation is not registered")
        _same_context(value, context, str(path))
        if value["input_sha256"] != input_sha or value["registry_sha256"] != registry_sha:
            raise ProviderChangeError(f"{path}: immutable input or registry hash mismatch")
        verification[impl].append((value, raw))

    for impl, registration in implementations.items():
        declaration = declared[impl]
        baseline = {gate["id"] for gate in registration["gates"]}
        required = baseline | set(declaration["required_gate_ids"])
        bound = affected[impl]
        if declaration["status"] == "unsupported" and bound:
            raise ProviderChangeError(f"{impl}: unsupported contradicts an affected binding")
        if declaration["status"] == "unaffected" and bound:
            raise ProviderChangeError(f"{impl}: unaffected contradicts an affected binding")
        if (
            declaration["status"] == "updated"
            and changed_paths is not None
            and not (set(declaration["owned_paths"]) & changed_paths)
        ):
            raise ProviderChangeError(f"{impl}: updated has no owned changed path")
        requires_evidence = bound or change["shared_spec"]["impact"] == "candidate_draft"
        if declaration["status"] != "blocked" and requires_evidence:
            seen: set[str] = set()
            for evidence, _ in verification[impl]:
                for gate in evidence["gates"]:
                    if gate["id"] in seen:
                        raise ProviderChangeError(f"{impl}: duplicate gate evidence")
                    seen.add(gate["id"])
                    if gate["status"] != "passed" or gate["exit_code"] != 0:
                        raise ProviderChangeError(f"{impl}: gate did not pass")
            if not required <= seen:
                raise ProviderChangeError(f"{impl}: missing required gate evidence")
    candidate_report: dict[str, Any] | None = None
    if change["shared_spec"]["impact"] == "candidate_draft":
        if candidate_evidence is None:
            raise ProviderChangeError(
                "candidate draft is unqualified without separate maintenance evidence"
            )
        candidate_report = _candidate_qualification(
            candidate_evidence, change_raw, registry_raw, context, implementations
        )
    if context["evaluated_source"]["dirty"]:
        raise ProviderChangeError("dirty evidence cannot qualify a complete provider change")

    report = {
        "schema_version": 1,
        "producer": context["producer"],
        "workflow_run": context["workflow_run"],
        "trusted_pr_head": context["trusted_pr_head"],
        "evaluated_source": context["evaluated_source"],
        "registry_sha256": registry_sha,
        "input_sha256": input_sha,
        "inventory_artifacts": [
            {"implementation_id": key, "sha256": _sha(raw)}
            for key, (_, raw) in inventories.items()
        ],
        "verification_artifacts": [
            {"implementation_id": key, "sha256": _sha(raw)}
            for key, items in verification.items()
            for _, raw in items
        ],
    }
    if candidate_report is not None:
        report["candidate_qualification"] = candidate_report
    return report


def main() -> int:
    """Run the pure validator and write a report only after successful validation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, action="append", required=True)
    parser.add_argument("--verification", type=Path, action="append", required=True)
    parser.add_argument("--changed-paths", type=Path)
    parser.add_argument("--candidate-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    changed = (
        set(args.changed_paths.read_text(encoding="utf-8").splitlines())
        if args.changed_paths
        else None
    )
    try:
        report = validate(
            args.input,
            args.registry,
            args.context,
            args.inventory,
            args.verification,
            changed,
            args.candidate_evidence,
        )
        _validate(report, "run-report.schema.json")
    except ProviderChangeError as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
