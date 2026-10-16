"""Private atomic writer for an unreleased portable Python reference observation."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import secrets
import sys
import tempfile
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from .reference import (
    ReferencePreflightError,
    capture_reference_environment,
    preflight_reference,
    strict_reference_warnings,
)


def _assets_module() -> ModuleType:
    path = Path(__file__).parents[3] / "scripts" / "portable_release_assets.py"
    spec = importlib.util.spec_from_file_location("_portable_reference_assets", path)
    if spec is None or spec.loader is None:
        raise ReferencePreflightError("trusted release-asset helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
        raise
    return module


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def _inventory(root: Path) -> dict[str, Mapping[str, Any]]:
    validator = _assets_module()._validator_module()
    raw = validator.read_json(root / "inventories" / "core-generation-v0.json")
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ReferencePreflightError("selected inventory is invalid")
    result: dict[str, Mapping[str, Any]] = {}
    for item in raw["cases"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or item["id"] in result
        ):
            raise ReferencePreflightError("selected inventory has invalid or duplicate IDs")
        result[item["id"]] = item
    return result


def _validate_observation(
    observation: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
    *,
    specification_root: Path,
) -> None:
    rows = observation.get("cases")
    if not isinstance(rows, list):
        raise ReferencePreflightError("native observation has no case list")
    if (
        observation.get("development_observation") != "UNRELEASED"
        or observation.get("report_v0_eligible") is not False
    ):
        raise ReferencePreflightError("native observation is not explicitly unreleased")
    if observation.get("unexecuted") != []:
        raise ReferencePreflightError("native observation has unexecuted obligations")
    helper = _assets_module()
    try:
        found = helper.validate_successful_cases(
            rows,
            cases,
            declared_extensions=observation.get("extensions"),
            specification_root=specification_root,
            require_python_extensions=True,
            development_observation=True,
        )
    except helper.ReleaseBindingError as error:
        raise ReferencePreflightError(f"native observation is invalid: {error}") from error
    raw_counts = observation.get("counts")
    if not isinstance(raw_counts, Mapping) or set(raw_counts) - {
        "pass",
        "fail",
        "error",
        "extension",
        "unexecuted",
    }:
        raise ReferencePreflightError("native observation counts are invalid")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in raw_counts.values()
    ):
        raise ReferencePreflightError("native observation counts are not nonnegative integers")
    counts = Counter(str(row["verdict"]) for row in found.values())
    expected_counts = dict(sorted(counts.items()))
    expected_counts["unexecuted"] = 0
    if raw_counts != expected_counts:
        raise ReferencePreflightError("native observation counts are stale")


def _is_link_or_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _prepare_reference_directory(preflight: Any) -> None:
    """Create only executable A's preflight-approved reference directory safely."""
    repository = preflight.repository_root.absolute()
    specification = repository / "specification"
    directory = specification / "reference"
    expected_environment = directory / f"python-{preflight.revision[:7]}.environment.json"
    expected_manifest = directory / f"python-{preflight.revision[:7]}.json"
    if (
        preflight.environment_path.absolute() != expected_environment
        or preflight.manifest_path.absolute() != expected_manifest
    ):
        raise ReferencePreflightError("reference output paths changed after preflight")

    for path in (repository, specification):
        if _is_link_or_reparse(path) or not path.is_dir():
            raise ReferencePreflightError("reference output directory is unsafe")
    if directory.exists():
        if not directory.is_dir() or _is_link_or_reparse(directory):
            raise ReferencePreflightError("reference output directory is unsafe")
    else:
        directory.mkdir()
    if _is_link_or_reparse(directory):
        raise ReferencePreflightError("reference output directory is unsafe")
    try:
        directory.resolve().relative_to(specification.resolve())
    except ValueError as error:
        raise ReferencePreflightError("reference output directory escapes executable root") from error
    if (
        preflight.environment_path.is_symlink()
        or preflight.manifest_path.is_symlink()
        or _is_link_or_reparse(preflight.environment_path)
        or _is_link_or_reparse(preflight.manifest_path)
        or preflight.environment_path.exists()
        or preflight.manifest_path.exists()
    ):
        raise ReferencePreflightError("reference output paths changed after preflight")


def _manifest(
    preflight: Any, environment: Mapping[str, Any], environment_sha256: str
) -> dict[str, Any]:
    revision = preflight.revision
    validator = environment.get("validator")
    if not isinstance(validator, Mapping):
        raise ReferencePreflightError("captured environment has no validator identity")
    lock = environment.get("dependency_lock")
    if not isinstance(lock, Mapping):
        raise ReferencePreflightError("captured environment has no dependency lock")
    packages: dict[str, str] = {}
    for name, value in lock.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, Mapping)
            or not isinstance(value.get("version"), str)
        ):
            raise ReferencePreflightError("captured dependency lock is invalid")
        packages[name] = value["version"]
    return {
        "implementation": "anyinfer-python",
        "reference_run_revision": revision,
        "source_tree": {"clean": True},
        "driver": {"path": "tests/testing/portable/", "git_revision": revision},
        "interpreter": f"{sys.implementation.name} {sys.version}",
        "environment": {
            "path": f"specification/reference/python-{revision[:7]}.environment.json",
            "sha256": environment_sha256,
        },
        "packages": packages,
        "validator": dict(validator),
        "warning_policy": "error",
        "produced_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _publish_new(path: Path, payload: bytes) -> Callable[[], None]:
    """Publish once and return a rollback that owns only this exact new file."""
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=f".{secrets.token_hex(8)}.tmp", dir=path.parent
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            owned = os.fstat(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    identity = (owned.st_dev, owned.st_ino)

    def rollback() -> None:
        try:
            current = path.lstat()
        except FileNotFoundError:
            return
        if (current.st_dev, current.st_ino) == identity:
            path.unlink()

    return rollback


def _rollback_publications(
    rollbacks: list[Callable[[], None]], observation_rollback: Callable[[], None] | None
) -> None:
    """Attempt every owned rollback while preserving the original publication failure."""
    try:
        for rollback in reversed(rollbacks):
            with contextlib.suppress(BaseException):
                rollback()
    finally:
        if observation_rollback is not None:
            with contextlib.suppress(BaseException):
                observation_rollback()


async def write_reference(
    root: Path,
    *,
    expected_revision: str,
    output_manifest: Path,
    output_environment: Path,
    repository_root: Path,
    observe: Callable[[Path], Awaitable[Mapping[str, Any]]],
    publish_observation: Callable[[Mapping[str, Any]], Callable[[], None]] | None = None,
) -> Mapping[str, Any]:
    """Observe and atomically publish an unreleased clean-source reference."""
    before = preflight_reference(
        root,
        expected_revision=expected_revision,
        output_manifest=output_manifest,
        output_environment=output_environment,
        repository_root=repository_root,
    )
    with strict_reference_warnings():
        observation = await observe(before.specification_root)
        environment = capture_reference_environment(before)
    if not isinstance(observation, Mapping):
        raise ReferencePreflightError("native observer did not return an object")
    _validate_observation(
        observation,
        _inventory(before.specification_root),
        specification_root=before.specification_root,
    )
    after = preflight_reference(
        root,
        expected_revision=expected_revision,
        output_manifest=output_manifest,
        output_environment=output_environment,
        repository_root=repository_root,
    )
    if after.revision != before.revision or dict(after.input_hashes) != dict(before.input_hashes):
        raise ReferencePreflightError("source or selected corpus changed during observation")
    environment_bytes = _json_bytes(dict(environment))
    manifest = _manifest(after, environment, hashlib.sha256(environment_bytes).hexdigest())
    helper = _assets_module()
    try:
        helper.validate_reference_evidence(
            manifest, environment, environment_sha256=hashlib.sha256(environment_bytes).hexdigest()
        )
    except helper.ReleaseBindingError as error:
        raise ReferencePreflightError(f"reference metadata is invalid: {error}") from error
    manifest_bytes = _json_bytes(manifest)
    _prepare_reference_directory(after)
    rollback_observation = publish_observation(observation) if publish_observation is not None else None
    rollbacks: list[Callable[[], None]] = []
    try:
        rollbacks.append(_publish_new(after.environment_path, environment_bytes))
        rollbacks.append(_publish_new(after.manifest_path, manifest_bytes))
    except BaseException:
        _rollback_publications(rollbacks, rollback_observation)
        raise
    return observation
