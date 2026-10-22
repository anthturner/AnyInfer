"""Reject unsafe automated contract-drift proposal output before a draft PR exists."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
MAINTENANCE = ROOT / "maintenance"
_PROTECTED_PREFIXES = (
    ".git/",
    ".github/",
    ".venv/",
    "env/",
    "venv/",
    "maintenance/",
    "scripts/",
    "workspace.py",
)
_PROTECTED_FILES = {"pyproject.toml", "uv.lock"}
_SHARED_SOURCE_PREFIXES = ("tests/", "docs/", "examples/")
_CANDIDATE_OUTPUT_PREFIXES = (
    "specification/releases/",
    "specification/reference/",
    "specification/reports/",
    "specification/qualification/",
    "specification/qualifications/",
    "specification/seal/",
    "specification/seals/",
)
_BUNDLE_VERSION = 1
_MAX_BUNDLE_FILES = 256
_MAX_BUNDLE_BYTES = 8 * 1024 * 1024


class ProposalError(ValueError):
    """Automated proposal output would escape the trusted draft boundary."""


def _read_json(path: Path) -> dict[str, Any]:
    return _read_json_bytes(path.read_bytes(), str(path))


def _read_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ProposalError(f"{label}: expected a JSON object")
    return value


def _validate_against_schema(value: dict[str, Any], schema_name: str) -> None:
    schema = _read_json(MAINTENANCE / schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=str)
    if errors:
        raise ProposalError(f"{schema_name}: {errors[0].message}")


def _validate_declaration_value(value: dict[str, Any], label: str) -> dict[str, Any]:
    _validate_against_schema(value, "change.schema.json")
    if value["disposition"] not in {"adopted", "blocked", "unverifiable"}:
        raise ProposalError(f"{label}: proposal declaration is not meaningful")
    return value


def _validate_declaration(path: Path) -> dict[str, Any]:
    declaration = _read_json(path)
    return _validate_declaration_value(declaration, str(path))


def _validate_baseline_controls() -> None:
    """Validate publisher-owned registry and schema inputs from the clean checkout."""
    _validate_against_schema(
        _read_json(MAINTENANCE / "implementations.json"),
        "implementations.schema.json",
    )


def _registered_roots() -> dict[str, str]:
    registry = _read_json(MAINTENANCE / "implementations.json")
    return {item["id"]: item["root"].rstrip("/") + "/" for item in registry["implementations"]}


def _is_control_plane_path(path: str) -> bool:
    filename = path.rsplit("/", maxsplit=1)[-1]
    return (
        "/" not in path
        or path in _PROTECTED_FILES
        or filename in {"AGENTS.md", "CLAUDE.md"}
        or path.startswith(_PROTECTED_PREFIXES)
    )


def _allowed_owned_path(path: str, implementation_root: str) -> bool:
    return path.startswith(implementation_root) or path.startswith(_SHARED_SOURCE_PREFIXES)


def _is_candidate_asset(path: str) -> bool:
    """Return whether a new specification path is a draft input, never generated evidence."""
    if path.startswith(_CANDIDATE_OUTPUT_PREFIXES):
        return False
    return (
        path.endswith(".md")
        or (path.startswith("specification/schemas/") and path.endswith(".json"))
        or (path.startswith("specification/inventories/") and path.endswith(".json"))
        or (path.startswith("specification/fixtures/") and path.endswith(".json"))
    )


def check(
    changed_paths: set[str],
    selected_contracts: set[str],
    declarations_by_path: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Validate a model's uncommitted diff against its immutable declarations."""
    if not changed_paths:
        return "no-change"
    declarations = {
        path
        for path in changed_paths
        if path.startswith("maintenance/changes/") and path.endswith(".json")
    }
    if not declarations:
        raise ProposalError(
            "proposal changes require an immutable maintenance/changes declaration"
        )
    allowed = set(selected_contracts) | declarations
    candidate_paths: set[str] = set()
    roots = _registered_roots()
    for declaration_path in declarations:
        declaration = (
            declarations_by_path[declaration_path]
            if declarations_by_path is not None
            else _validate_declaration(ROOT / declaration_path)
        )
        for implementation in declaration["implementations"]:
            root = roots.get(implementation["implementation_id"])
            if root is None:
                raise ProposalError("proposal declaration names an unknown implementation")
            for path in implementation["owned_paths"]:
                if not _allowed_owned_path(path, root):
                    raise ProposalError(f"proposal declaration owns an unsafe source path: {path}")
                allowed.add(path)
        candidate = declaration["shared_spec"].get("candidate")
        if candidate:
            for path in candidate["paths"]:
                if not path.startswith("specification/"):
                    raise ProposalError(
                        f"proposal declaration owns a candidate outside specification: {path}"
                    )
                if not _is_candidate_asset(path):
                    raise ProposalError(
                        f"proposal declaration owns an unsupported candidate asset class: {path}"
                    )
                candidate_paths.add(path)
                allowed.add(path)
    for path in changed_paths:
        if path in declarations:
            continue
        if _is_control_plane_path(path):
            raise ProposalError(f"automated proposal may not change control-plane path: {path}")
        if path.startswith("specification/") and path not in candidate_paths:
            raise ProposalError(
                f"automated proposal may not alter sealed specification asset: {path}"
            )
        if path in allowed:
            continue
        raise ProposalError(f"automated proposal path is not declared: {path}")
    return "draft-prepared"


def _reject_existing_candidate_assets(changed_paths: set[str], baseline: str = "HEAD") -> None:
    """Candidate assets prepared by automation must be new, never sealed rewrites."""
    for path in changed_paths:
        if not path.startswith("specification/"):
            continue
        exists = (
            subprocess.run(
                ["git", "cat-file", "-e", f"{baseline}:{path}"],
                cwd=ROOT,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        if exists:
            raise ProposalError(f"candidate asset already exists in the trusted base: {path}")


def complete_paths(*groups: set[str]) -> set[str]:
    """Union normalized unstaged, staged, and non-ignored-untracked path views."""
    return {path.replace("\\", "/") for group in groups for path in group}


def _read_nul_paths(path: Path) -> set[str]:
    return {item.decode("utf-8") for item in path.read_bytes().split(b"\0") if item}


def _closed_path_name(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise ProposalError("bundle path is not a closed relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ProposalError("bundle path is not a closed relative path")
    return value


def _safe_worktree_file(path: str) -> Path:
    destination = ROOT / path
    if destination.is_symlink() or not destination.is_file():
        raise ProposalError(f"bundle source is not a regular file: {path}")
    resolved = destination.resolve()
    root = ROOT.resolve()
    if root not in (resolved, *resolved.parents):
        raise ProposalError(f"bundle source escapes the repository: {path}")
    return resolved


def _git_paths(baseline: str) -> set[str]:
    commands = (
        ["git", "diff", "--no-renames", "--name-only", "-z", baseline],
        ["git", "diff", "--cached", "--no-renames", "--name-only", "-z", baseline],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    )
    paths: set[str] = set()
    for command in commands:
        raw = subprocess.check_output(command, cwd=ROOT)
        paths.update(item.decode("utf-8") for item in raw.split(b"\0") if item)
    return complete_paths(paths)


def create_bundle(baseline: str) -> dict[str, Any]:
    """Serialize the untrusted working-tree view without granting it authority."""
    files: list[dict[str, str]] = []
    total = 0
    for path in sorted(_git_paths(baseline)):
        name = _closed_path_name(path)
        source = ROOT / name
        if not source.exists():
            files.append({"path": name, "kind": "delete", "content_base64": ""})
            continue
        raw = _safe_worktree_file(name).read_bytes()
        total += len(raw)
        if total > _MAX_BUNDLE_BYTES:
            raise ProposalError("proposal bundle exceeds its byte limit")
        files.append(
            {
                "path": name,
                "kind": "file",
                "content_base64": base64.b64encode(raw).decode("ascii"),
            }
        )
    if len(files) > _MAX_BUNDLE_FILES:
        raise ProposalError("proposal bundle exceeds its file limit")
    return {"schema_version": _BUNDLE_VERSION, "files": files}


def write_bundle(path: Path, baseline: str) -> None:
    """Write a deterministic, untrusted serialization of the current proposal files."""
    bundle = create_bundle(baseline)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_bundle(path: Path) -> dict[str, tuple[str, bytes]]:
    bundle = _read_json(path)
    if set(bundle) != {"schema_version", "files"} or bundle["schema_version"] != _BUNDLE_VERSION:
        raise ProposalError("proposal bundle has an invalid envelope")
    rows = bundle["files"]
    if not isinstance(rows, list) or len(rows) > _MAX_BUNDLE_FILES:
        raise ProposalError("proposal bundle has an invalid file list")
    files: dict[str, tuple[str, bytes]] = {}
    total = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "kind", "content_base64"}:
            raise ProposalError("proposal bundle file entry is invalid")
        name = _closed_path_name(row["path"])
        if (
            row["kind"] not in {"file", "delete"}
            or name in files
            or not isinstance(row["content_base64"], str)
        ):
            raise ProposalError("proposal bundle file entry is invalid")
        try:
            raw = base64.b64decode(row["content_base64"], validate=True)
        except (ValueError, TypeError) as error:
            raise ProposalError("proposal bundle content is not base64") from error
        total += len(raw)
        if total > _MAX_BUNDLE_BYTES:
            raise ProposalError("proposal bundle exceeds its byte limit")
        if row["kind"] == "delete" and raw:
            raise ProposalError("proposal deletion entry must not carry content")
        files[name] = (row["kind"], raw)
    return files


def _bundle_declarations(files: dict[str, tuple[str, bytes]]) -> dict[str, dict[str, Any]]:
    declarations: dict[str, dict[str, Any]] = {}
    for path, (kind, raw) in files.items():
        if kind == "file" and path.startswith("maintenance/changes/") and path.endswith(".json"):
            declarations[path] = _validate_declaration_value(_read_json_bytes(raw, path), path)
    return declarations


def _reject_existing_declarations(paths: set[str], baseline: str) -> None:
    """Declarations are immutable production records and must be new at the trusted base."""
    for path in paths:
        exists = (
            subprocess.run(
                ["git", "cat-file", "-e", f"{baseline}:{path}"],
                cwd=ROOT,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        if exists:
            raise ProposalError(f"proposal declaration already exists in the trusted base: {path}")


def _safe_bundle_destination(path: str) -> Path:
    destination = ROOT / path
    root = ROOT.resolve()
    for parent in (root, *destination.relative_to(ROOT).parents):
        candidate = parent if parent.is_absolute() else root / parent
        if candidate.exists() and candidate.is_symlink():
            raise ProposalError(f"bundle destination contains a symlink: {path}")
    resolved_parent = destination.parent.resolve()
    if root not in (resolved_parent, *resolved_parent.parents):
        raise ProposalError(f"bundle destination escapes the repository: {path}")
    return destination


def restore_bundle(
    bundle_path: Path, selected_contracts: set[str], baseline: str
) -> tuple[str, set[str]]:
    """Validate every untrusted entry in memory, then materialize only approved bytes."""
    _validate_baseline_controls()
    entries = _read_bundle(bundle_path)
    changed = set(entries)
    declaration_paths = {
        path
        for path in changed
        if path.startswith("maintenance/changes/") and path.endswith(".json")
    }
    deleted_declarations = {path for path in declaration_paths if entries[path][0] == "delete"}
    if deleted_declarations:
        _reject_existing_declarations(deleted_declarations, baseline)
        raise ProposalError("proposal bundle may not delete files")
    files = {path: raw for path, (kind, raw) in entries.items() if kind == "file"}
    if len(files) != len(entries):
        raise ProposalError("proposal bundle may not delete files")
    declarations = _bundle_declarations(entries)
    result = check(changed, selected_contracts, declarations)
    _reject_existing_declarations(declaration_paths, baseline)
    _reject_existing_candidate_assets(changed, baseline)
    for path in sorted(files):
        destination = _safe_bundle_destination(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(files[path])
    return result, changed


def _write_nul_paths(path: Path, paths: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(item.encode("utf-8") + b"\0" for item in sorted(paths)))


def _verify_trusted_inputs(selection_report: Path, expected_sha: str, baseline: str) -> None:
    """Bind proposal authority to the pre-model checkout and selection report bytes."""
    actual_sha = hashlib.sha256(selection_report.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ProposalError("selected drift report changed after trusted selection")
    actual_base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if actual_base != baseline:
        raise ProposalError("trusted proposal baseline changed before publishing")


def main() -> int:
    """Check the current uncommitted proposal diff using selected-snapshot evidence."""
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--changed-paths", type=Path)
    mode.add_argument("--capture-bundle", type=Path)
    mode.add_argument("--restore-bundle", type=Path)
    parser.add_argument("--selection-report", type=Path)
    parser.add_argument("--selection-sha256")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--approved-paths", type=Path)
    args = parser.parse_args()
    try:
        if args.capture_bundle:
            write_bundle(args.capture_bundle, args.baseline)
            return 0
        if not args.selection_report or not args.selection_sha256:
            raise ProposalError("selection report and its trusted SHA-256 are required")
        report = _read_json(args.selection_report)
        selected = {item["path"] for item in report.get("selected", [])}
        _verify_trusted_inputs(args.selection_report, args.selection_sha256, args.baseline)
        if args.restore_bundle:
            result, changed = restore_bundle(args.restore_bundle, selected, args.baseline)
            if args.approved_paths:
                _write_nul_paths(args.approved_paths, changed)
        else:
            changed = complete_paths(_read_nul_paths(args.changed_paths))
            result = check(changed, selected)
            _reject_existing_candidate_assets(changed, args.baseline)
        print(result)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
