"""Run registered provider-change exporters and gates under controlled provenance.

Only ``maintenance/implementations.json`` supplies executable argv.  Change declarations
are immutable evidence inputs, never a command source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
MAINTENANCE = ROOT / "maintenance"
CANONICAL_REGISTRY = MAINTENANCE / "implementations.json"
_TIMEOUT_SECONDS = 600
_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_EXCLUDED_UNTRACKED = ("uv.lock", "v/")


class RunnerError(ValueError):
    """The controlled runner cannot safely produce qualifying evidence."""


def _reject_constant(value: str) -> None:
    raise RunnerError(f"non-finite JSON constant {value!r} is forbidden")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RunnerError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunnerError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise RunnerError(f"{path}: expected a JSON object")
    return value, raw


def _schema(name: str) -> Draft202012Validator:
    schema, _ = _read_json(MAINTENANCE / name)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate(value: dict[str, Any], schema_name: str) -> None:
    errors = sorted(_schema(schema_name).iter_errors(value), key=str)
    if errors:
        raise RunnerError(f"{schema_name}: {errors[0].message}")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _under_root(path: Path, label: str) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(ROOT)
    except ValueError as error:
        raise RunnerError(f"{label} must resolve under the repository root") from error
    return resolved


def _under_temporary_output(path: Path) -> Path:
    """Require runner artifacts to remain in the repository's ignored output root."""
    resolved = _under_root(path, "output directory")
    try:
        resolved.relative_to((ROOT / ".tmp-tests").resolve())
    except ValueError as error:
        raise RunnerError(
            "output directory must resolve under the ignored .tmp-tests directory"
        ) from error
    return resolved


def _canonical_registry(path: Path) -> Path:
    """Accept only the checked-in, non-link registry as CLI command authority."""
    canonical = CANONICAL_REGISTRY.resolve(strict=True)
    if CANONICAL_REGISTRY.is_symlink() or not canonical.is_file():
        raise RunnerError("canonical implementation registry must be a regular file")
    resolved = path.resolve(strict=False)
    if resolved != canonical:
        raise RunnerError("--registry must resolve exactly to maintenance/implementations.json")
    return canonical


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise RunnerError(f"unable to read Git source identity: {error}") from error


def _source_files() -> tuple[Path, ...]:
    """Return tracked plus non-ignored untracked files, excluding local user artifacts.

    The controlled set is Git's tracked files and ``--exclude-standard`` untracked files,
    sorted by repository-relative POSIX path.  ``uv.lock`` and ``v/`` are explicitly
    excluded local user artifacts; ignored output/build/cache paths are excluded by Git.
    """
    listed = _git("ls-files", "-z").split("\0")
    untracked = _git("ls-files", "--others", "--exclude-standard", "-z").split("\0")
    paths: set[str] = set()
    for relative in [*listed, *untracked]:
        if not relative or relative == "uv.lock" or relative.startswith(_EXCLUDED_UNTRACKED[1]):
            continue
        path = _under_root(ROOT / relative, "source path")
        if path.is_file():
            paths.add(relative.replace("\\", "/"))
    return tuple(ROOT / relative for relative in sorted(paths))


def _source_identity() -> dict[str, Any]:
    """Capture actual checkout identity and the controlled source-file fingerprint."""
    digest = hashlib.sha256()
    for path in _source_files():
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "commit": _git("rev-parse", "HEAD"),
        "tree": _git("rev-parse", "HEAD^{tree}"),
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=all")),
        "input_fingerprint": digest.hexdigest(),
    }


def _expand_argv(argv: list[str]) -> list[str]:
    expanded: list[str] = []
    controlled_executables: set[str] = set()
    for item in argv:
        if item == "{sys.executable}":
            expanded.append(sys.executable)
            controlled_executables.add(sys.executable)
        else:
            expanded.append(item)
    if not expanded or any(not item for item in expanded):
        raise RunnerError("registered argv must contain non-empty literal arguments")
    for item in expanded:
        if item in controlled_executables:
            continue
        if any(character in item for character in ";|&$"):
            raise RunnerError(f"registered argv contains shell syntax: {item!r}")
        if item.startswith("-") or ("/" not in item and "\\" not in item):
            continue
        candidate = Path(item)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RunnerError(f"registered argv contains an unsafe path: {item!r}")
        _under_root(ROOT / candidate, "registered argv path")
    return expanded


def _registered_implementation(registry: dict[str, Any], implementation_id: str) -> dict[str, Any]:
    matches = [item for item in registry["implementations"] if item["id"] == implementation_id]
    if len(matches) != 1:
        raise RunnerError(f"implementation is not registered exactly once: {implementation_id!r}")
    implementation = matches[0]
    root = _under_root(ROOT / implementation["root"], "registered implementation root")
    if not root.is_dir():
        raise RunnerError(
            f"registered implementation root does not exist: {implementation['root']}"
        )
    _expand_argv(implementation["exporter_argv"])
    for gate in implementation["gates"]:
        _expand_argv(gate["argv"])
    return implementation


def _run_command(argv: list[str], run_directory: Path, label: str) -> tuple[int, bytes, bytes]:
    """Run a registered argv without a shell and retain bounded local diagnostics."""
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            shell=False,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = error.stdout or b""
        diagnostic = output + (error.stderr or b"")
        (run_directory / "logs" / f"{label}.timeout.log").write_bytes(diagnostic)
        raise RunnerError(f"registered command timed out: {label}") from error
    except OSError as error:
        (run_directory / "logs" / f"{label}.spawn-error.log").write_text(
            str(error), encoding="utf-8", newline="\n"
        )
        raise RunnerError(f"registered command could not start: {label}") from error
    if completed.returncode < 0:
        (run_directory / "logs" / f"{label}.signal.log").write_bytes(
            completed.stdout + completed.stderr
        )
        raise RunnerError(f"registered command ended without a representable exit code: {label}")
    return completed.returncode, completed.stdout, completed.stderr


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _run_with_registry(
    input_path: Path,
    registry_path: Path,
    implementation_id: str,
    output_dir: Path,
    gate_ids: list[str] | None = None,
    inventory_only: bool = False,
    trusted_pr_head: str | None = None,
    run_id: str | None = None,
    run_attempt: int = 1,
) -> Path:
    """Execute supplied registry data; retained as an internal dependency-injection seam."""
    input_path = _under_root(input_path, "input path")
    registry_path = _under_root(registry_path, "registry path")
    output_dir = _under_temporary_output(output_dir)
    change, input_raw = _read_json(input_path)
    registry, registry_raw = _read_json(registry_path)
    _validate(change, "change.schema.json")
    _validate(registry, "implementations.schema.json")
    implementation = _registered_implementation(registry, implementation_id)
    selected = list(implementation["gates"])
    known_gates = {gate["id"]: gate for gate in selected}
    if inventory_only and gate_ids:
        raise RunnerError("--inventory-only cannot be combined with --gate")
    if gate_ids:
        if len(gate_ids) != len(set(gate_ids)):
            raise RunnerError("each selected gate id must be supplied at most once")
        unknown = sorted(set(gate_ids) - set(known_gates))
        if unknown:
            raise RunnerError(f"gate is not registered for {implementation_id}: {unknown!r}")
        selected = [known_gates[gate_id] for gate_id in gate_ids]
    if run_attempt < 1:
        raise RunnerError("run attempt must be positive")
    run_id = run_id or uuid.uuid4().hex
    if not _RUN_ID.fullmatch(run_id):
        raise RunnerError("run id must contain only letters, digits, '.', '_' or '-'")
    initial_source = _source_identity()
    trusted_pr_head = trusted_pr_head or initial_source["commit"]
    if not re.fullmatch(r"[a-f0-9]{40}", trusted_pr_head):
        raise RunnerError("trusted PR head must be a 40-character lowercase Git commit")

    run_directory = output_dir / "provider-change" / change["id"] / run_id
    _under_root(run_directory, "run output path")
    run_directory.mkdir(parents=True, exist_ok=False)
    (run_directory / "logs").mkdir()
    context = {
        "schema_version": 1,
        "implementation_id": implementation_id,
        "producer": {"id": "provider-change-dispatcher", "version": "1"},
        "workflow_run": {"id": run_id, "attempt": run_attempt},
        "trusted_pr_head": trusted_pr_head,
        "evaluated_source": initial_source,
        "registry_sha256": _sha(registry_raw),
        "input_sha256": _sha(input_raw),
        "bindings": [],
    }
    _validate(context, "binding-inventory.schema.json")
    context_path = run_directory / "context.json"
    inventory_path = run_directory / "inventory.json"
    _write_json(context_path, context)

    exporter_argv = _expand_argv(implementation["exporter_argv"])
    exporter_argv.extend(["--context", str(context_path), "--output", str(inventory_path)])
    exporter_code, exporter_stdout, exporter_stderr = _run_command(
        exporter_argv, run_directory, "exporter"
    )
    (run_directory / "logs" / "exporter.stdout").write_bytes(exporter_stdout)
    (run_directory / "logs" / "exporter.log").write_bytes(exporter_stdout + exporter_stderr)
    if exporter_code != 0:
        raise RunnerError(f"registered exporter failed with exit code {exporter_code}")
    inventory, _ = _read_json(inventory_path)
    _validate(inventory, "binding-inventory.schema.json")
    if inventory["producer"] == context["producer"]:
        raise RunnerError("exporter did not replace the dispatcher producer identity")
    for key in (
        "schema_version",
        "implementation_id",
        "workflow_run",
        "trusted_pr_head",
        "evaluated_source",
        "registry_sha256",
        "input_sha256",
    ):
        if inventory.get(key) != context[key]:
            raise RunnerError(f"exporter changed controlled context field: {key}")
    input_unchanged = _sha(input_path.read_bytes()) == context["input_sha256"]
    registry_unchanged = _sha(registry_path.read_bytes()) == context["registry_sha256"]
    if not input_unchanged or not registry_unchanged:
        raise RunnerError("exporter mutated immutable input or registry")
    if _source_identity() != initial_source:
        raise RunnerError("exporter mutated controlled source inputs")
    if inventory_only:
        return run_directory

    evidence: list[dict[str, Any]] = []
    for gate in selected:
        gate_id = gate["id"]
        code, stdout, stderr = _run_command(_expand_argv(gate["argv"]), run_directory, gate_id)
        output_path = run_directory / "logs" / f"{gate_id}.stdout"
        log_path = run_directory / "logs" / f"{gate_id}.log"
        output_path.write_bytes(stdout)
        log_path.write_bytes(stdout + stderr)
        evidence.append(
            {
                "id": gate_id,
                "status": "passed" if code == 0 else "failed",
                "exit_code": code,
                "output_sha256": _sha(stdout),
                "log_sha256": _sha(stdout + stderr),
            }
        )
    input_unchanged = _sha(input_path.read_bytes()) == context["input_sha256"]
    registry_unchanged = _sha(registry_path.read_bytes()) == context["registry_sha256"]
    if not input_unchanged or not registry_unchanged:
        raise RunnerError("gate mutated immutable input or registry")
    if _source_identity() != initial_source:
        raise RunnerError("gate mutated controlled source inputs")
    verification = {key: value for key, value in context.items() if key != "bindings"} | {
        "gates": evidence
    }
    _validate(verification, "verification.schema.json")
    _write_json(run_directory / "verification.json", verification)
    return run_directory


def main() -> int:
    """Parse the fixed runner CLI and dispatch only registered commands."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--implementation", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gate", action="append")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--trusted-pr-head")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt", type=int, default=1)
    args = parser.parse_args()
    try:
        registry_path = _canonical_registry(args.registry)
        _run_with_registry(
            args.input,
            registry_path,
            args.implementation,
            args.output_dir,
            args.gate,
            args.inventory_only,
            args.trusted_pr_head,
            args.run_id,
            args.run_attempt,
        )
    except RunnerError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
