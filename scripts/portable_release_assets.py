"""Fail-closed binding and comparison of portable release assets.

The loader reads JSON and bytes only from a selected specification tree. The only
code it imports is this checkout's sibling validator source; it never changes the
module search path or imports code from that selected tree.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType, ModuleType
from typing import Any, NoReturn, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

__all__ = [
    "ReleaseAssets",
    "ReleaseBindingError",
    "load_release_assets",
    "require_comparable_reports",
    "validate_qualified_report",
    "validate_reference_evidence",
    "validate_successful_cases",
]

_HEX = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_DIST = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EXTENSIONS = frozenset(
    {
        "schema.ref",
        "schema.combinators",
        "schema.other_dialects",
        "schema.boolean_subschema",
        "schema.unknown_keywords_ignored",
        "messages.tool_role",
        "targets.alias",
        "messages.non_text_parts",
    }
)
_SCHEMAS = (
    "fixture-v0.schema.json",
    "transport-v0.schema.json",
    "inventory-v0.schema.json",
    "report-v0.schema.json",
)
_PACKAGE_NAMES = frozenset(
    {
        "anyinfer",
        "httpx2",
        "jsonschema",
        "jsonschema-specifications",
        "referencing",
        "attrs",
        "rpds-py",
    }
)
_FATAL_NATIVE_TYPES = frozenset(
    {"CancelledError", "KeyboardInterrupt", "SystemExit", "GeneratorExit"}
)
_RESULT_FIELDS = frozenset(
    {
        "text",
        "structured",
        "target",
        "finish_reason",
        "usage",
        "timing",
        "structured_mechanism",
        "repair_attempts",
        "attempts",
        "warnings",
    }
)
_FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "content_filter", "other"})
_MECHANISMS = frozenset({"grammar", "json_schema", "json_mode", "prompt"})
_USAGE_FIELDS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
    }
)
_ATTEMPT_OUTCOMES = frozenset({"ok", "retried", "failed", "skipped_unhealthy"})
SPECIFICATION = Path(__file__).resolve().parent.parent / "specification"


class ReleaseBindingError(ValueError):
    """Raised when a selected release cannot establish a qualified binding."""


@dataclass(frozen=True, slots=True)
class ReleaseAssets:
    """Recursively frozen facts bound to one selected sealed release."""

    specification_root: Path
    release_path: Path
    release_sha256: str
    release: Mapping[str, Any]
    inventory: Mapping[str, Any]
    cases_by_id: Mapping[str, Mapping[str, Any]]
    file_hashes: Mapping[str, str]
    reference_manifest: Mapping[str, Any]
    environment: Mapping[str, Any]


def _error(message: str) -> NoReturn:
    raise ReleaseBindingError(message)


def _validator_module() -> ModuleType:
    path = Path(__file__).with_name("validate_fixtures.py")
    spec = importlib.util.spec_from_file_location("_portable_release_validator", path)
    if spec is None or spec.loader is None:
        _error("trusted fixture validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        _error(f"{field} must be an object with string keys")
    return cast(Mapping[str, Any], value)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _selected_root(value: Path) -> Path:
    if _is_link(value) or not value.is_dir():
        _error("selected specification root is missing or uses a link/reparse point")
    root = value.resolve()
    if _is_link(root) or not root.is_dir():
        _error("selected specification root is unsafe")
    return root


def _parts(value: str, *, expected_prefix: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or "//" in value:
        _error(f"non-canonical release path: {value!r}")
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        _error(f"non-canonical release path: {value!r}")
    parts = PurePosixPath(value).parts
    if not parts or parts[0] != expected_prefix or any(part in {".", ".."} for part in parts):
        _error(f"unsafe release path: {value!r}")
    return parts


def _within(root: Path, candidate: Path, raw: str) -> Path:
    current = root
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        _error(f"release path escapes selected root: {raw!r}")
    for part in relative.parts:
        current /= part
        if _is_link(current):
            _error(f"release path uses link/reparse point: {raw!r}")
    if not candidate.is_file():
        _error(f"release asset is missing: {raw!r}")
    try:
        candidate.resolve().relative_to(root)
    except ValueError:
        _error(f"release path resolves outside selected root: {raw!r}")
    return candidate


def _asset_path(root: Path, raw: str) -> Path:
    parts = _parts(raw, expected_prefix="specification")
    if len(parts) == 1:
        _error(f"release asset names the selected root: {raw!r}")
    return _within(root, root.joinpath(*parts[1:]), raw)


def _release_path(root: Path, value: Path) -> Path:
    if value.is_absolute():
        candidate = value
        try:
            relative = candidate.relative_to(root / "releases")
        except ValueError:
            _error("absolute release file must be under selected releases/")
        if not relative.parts or any(part in {".", ".."} for part in relative.parts):
            _error("release file path is not canonical")
    else:
        parts = _parts(value.as_posix(), expected_prefix="releases")
        if len(parts) == 1:
            _error("release file must name a JSON file")
        candidate = root.joinpath(*parts)
    if candidate.suffix != ".json":
        _error("release file must be JSON")
    return _within(root, candidate, value.as_posix())


def _timestamp(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        _error(f"{field} must be a nonempty ISO timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _error(f"{field} is not an ISO timestamp")


def _revision(value: object, field: str) -> str:
    if not isinstance(value, str) or not _REVISION.fullmatch(value) or value == "0" * 40:
        _error(f"{field} is not a nonzero identified commit")
    return value


def _ordinary_json(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return -(2**63) <= value <= 2**63
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_ordinary_json(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _ordinary_json(key) and _ordinary_json(item)
            for key, item in value.items()
        )
    return False


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _pending(document: Mapping[str, Any]) -> bool:
    expected = document.get("expected")
    return isinstance(expected, Mapping) and expected.get("status") == "to_be_observed"


def _hash_field(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        _error(f"{field} must be a SHA-256 hex digest")


def _bound_requirement_refs(inventory: Mapping[str, Any], hashes: Mapping[str, Any]) -> None:
    requirements = inventory.get("requirements")
    if not isinstance(requirements, list):
        _error("inventory requirements are invalid")
    for requirement in requirements:
        item = _mapping(requirement, "inventory requirement")
        ref = item.get("spec_ref")
        if not isinstance(ref, str):
            _error("inventory requirement spec_ref is invalid")
        path, separator, fragment = ref.partition("#")
        if not separator or not fragment or not path.endswith(".md"):
            _error("inventory requirement spec_ref is not a Markdown target")
        _parts(path, expected_prefix="specification")
        if path not in hashes:
            _error("inventory requirement spec_ref target is not release-bound")


def _environment(
    environment: Mapping[str, Any], reference: Mapping[str, Any], revision: str
) -> None:
    if (
        environment.get("environment_version") != "0"
        or environment.get("reference_run_revision") != revision
    ):
        _error("environment version or reference revision is invalid")
    if not _mapping(environment.get("interpreter"), "environment interpreter"):
        _error("environment interpreter identity is missing")
    lock = _mapping(environment.get("dependency_lock"), "environment dependency_lock")
    if not _PACKAGE_NAMES.issubset(lock):
        _error("environment dependency lock omits required packages")
    package_versions: dict[str, str] = {}
    for name, row in lock.items():
        if not _DIST.fullmatch(name):
            _error(f"dependency lock name is not canonical: {name!r}")
        item = _mapping(row, f"dependency lock {name}")
        if set(item) != {
            "version",
            "requires",
            "metadata_sha256",
            "record_sha256",
            "direct_url_sha256",
        }:
            _error(f"dependency lock entry {name!r} has unexpected fields")
        version, requires = item.get("version"), item.get("requires")
        if (
            not isinstance(version, str)
            or not version
            or not isinstance(requires, list)
            or not all(isinstance(req, str) for req in requires)
        ):
            _error(f"dependency lock entry {name!r} is incomplete")
        _hash_field(item.get("metadata_sha256"), f"dependency lock {name!r} metadata_sha256")
        _hash_field(
            item.get("record_sha256"), f"dependency lock {name!r} record_sha256", nullable=True
        )
        _hash_field(
            item.get("direct_url_sha256"),
            f"dependency lock {name!r} direct_url_sha256",
            nullable=True,
        )
        package_versions[name] = version
    if dict(_mapping(reference.get("packages"), "reference packages")) != package_versions:
        _error("reference packages do not exactly project environment lock")
    imports = _mapping(environment.get("imports"), "environment imports")
    if set(imports) != {"anyinfer", "driver"}:
        _error("environment imports must bind anyinfer and driver")
    modules = _mapping(environment.get("loaded_modules"), "environment loaded_modules")
    if not modules:
        _error("environment loaded_modules is empty")
    for group in (imports, modules):
        for row in group.values():
            item = _mapping(row, "environment hash row")
            if (
                set(item) != {"path", "sha256"}
                or not isinstance(item.get("path"), str)
                or not item["path"]
            ):
                _error("environment hash row is incomplete")
            _hash_field(item.get("sha256"), "environment hash row sha256")
    validator = _mapping(environment.get("validator"), "environment validator")
    if set(validator) != {"selected", "defaults", "resource_identities"}:
        _error("environment validator has invalid fields")
    selected, defaults = validator.get("selected"), validator.get("defaults")
    if not isinstance(selected, str) or not selected:
        _error("environment validator selected identity is invalid")
    if not isinstance(defaults, str) and not isinstance(defaults, Mapping):
        _error("environment validator defaults are invalid")
    if (isinstance(defaults, str) and not defaults) or (
        isinstance(defaults, Mapping) and (not defaults or not _ordinary_json(dict(defaults)))
    ):
        _error("environment validator defaults are empty or non-JSON")
    if dict(validator) != dict(_mapping(reference.get("validator"), "reference validator")):
        _error("environment validator does not equal reference manifest")
    resources = validator.get("resource_identities")
    if not isinstance(resources, list) or not resources:
        _error("validator resource identities are invalid")
    identities: list[tuple[str, str]] = []
    for row in resources:
        item = _mapping(row, "validator resource identity")
        if (
            set(item) != {"uri", "sha256"}
            or not isinstance(item.get("uri"), str)
            or not item["uri"]
        ):
            _error("validator resource identity is incomplete")
        digest = item.get("sha256")
        _hash_field(digest, "validator resource identity sha256")
        identities.append((item["uri"], cast(str, digest)))
    if identities != sorted(identities) or len({uri for uri, _ in identities}) != len(identities):
        _error("validator resource identities are not sorted and unique")
    if environment.get("warning_policy") != {
        "mode": "error",
        "filters": [
            {
                "action": "error",
                "message": None,
                "category": "builtins.Warning",
                "module": None,
                "lineno": 0,
            }
        ],
    }:
        _error("environment warning policy is invalid")


def validate_reference_evidence(
    reference: Mapping[str, Any], environment: Mapping[str, Any], *, environment_sha256: str
) -> None:
    """Validate private reference metadata without attesting native execution."""
    if not _ordinary_json(dict(reference)) or not _ordinary_json(dict(environment)):
        _error("reference metadata must be bounded ordinary JSON")
    revision = _revision(reference.get("reference_run_revision"), "reference revision")
    driver = _mapping(reference.get("driver"), "reference driver")
    environment_row = _mapping(reference.get("environment"), "reference environment")
    if (
        reference.get("implementation") != "anyinfer-python"
        or reference.get("source_tree") != {"clean": True}
        or driver.get("path") != "tests/testing/portable/"
        or _revision(driver.get("git_revision"), "reference driver revision") != revision
        or not isinstance(reference.get("interpreter"), str)
        or not reference["interpreter"]
        or reference.get("warning_policy") != "error"
    ):
        _error("reference manifest identity is invalid")
    _timestamp(reference.get("produced_at"), "reference produced_at")
    env_name, env_hash = environment_row.get("path"), environment_row.get("sha256")
    expected_name = f"specification/reference/python-{revision[:7]}.environment.json"
    if env_name != expected_name:
        _error("reference environment path does not bind reference revision")
    _hash_field(env_hash, "reference environment sha256")
    if env_hash != environment_sha256:
        _error("reference environment hash does not bind raw environment bytes")
    _environment(environment, reference, revision)


def load_release_assets(specification_root: Path, release_path: Path) -> ReleaseAssets:
    """Load a closed selected release without globbing future files."""
    root = _selected_root(specification_root)
    validator = _validator_module()
    release_file = _release_path(root, release_path)
    try:
        release = _mapping(validator.read_json(release_file), "release")
    except (OSError, ValueError) as exc:
        raise ReleaseBindingError(f"invalid release JSON: {exc}") from exc
    required = {
        "release",
        "profile",
        "profile_revision",
        "created_at",
        "reference_manifest",
        "files",
        "case_inventory",
    }
    if (
        set(release) != required
        or release.get("profile") != "core-generation"
        or release.get("profile_revision") != "v0"
    ):
        _error("release fields or profile identity are invalid")
    release_id = release.get("release")
    if not isinstance(release_id, str) or not release_id or release_file.stem != release_id:
        _error("release filename does not match release identity")
    _timestamp(release.get("created_at"), "release created_at")
    hashes = _mapping(release.get("files"), "release files")
    if list(hashes) != sorted(hashes):
        _error("release files are not code-point sorted")
    for name, digest in hashes.items():
        if (
            not isinstance(digest, str)
            or not _HEX.fullmatch(digest)
            or name.startswith("specification/releases/")
            or "/reports/" in name
        ):
            _error("release file hashes are invalid")
        if _hash(_asset_path(root, name)) != digest:
            _error(f"release asset hash mismatch: {name}")
    inventory_name = "specification/inventories/core-generation-v0.json"
    inventory = _mapping(validator.read_json(_asset_path(root, inventory_name)), "inventory")
    _bound_requirement_refs(inventory, hashes)
    cases = inventory.get("cases")
    if not isinstance(cases, list):
        _error("inventory cases are invalid")
    case_records: dict[str, Mapping[str, Any]] = {}
    fixtures: list[Path] = []
    required_paths = {
        "specification/README.md",
        "specification/core-generation.md",
        "specification/MAINTENANCE.md",
        inventory_name,
        *(f"specification/schemas/{name}" for name in _SCHEMAS),
    }
    for value in cases:
        item = _mapping(value, "inventory case")
        case_id = item.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in case_records:
            _error("inventory case IDs are not unique")
        case_records[case_id] = item
        if item.get("kind") == "fixture":
            path = item.get("path")
            if not isinstance(path, str):
                _error("fixture case path is missing")
            required_paths.add(path)
            fixtures.append(_asset_path(root, path))
        elif (
            item.get("kind") != "driver_assertion"
            or item.get("path") is not None
            or not isinstance(item.get("recipe_ref"), str)
        ):
            _error("driver assertion inventory record is invalid")
    released = release.get("case_inventory")
    if not isinstance(released, list):
        _error("release case inventory is invalid")
    released_records: dict[str, Mapping[str, Any]] = {}
    for value in released:
        item = _mapping(value, "release case inventory record")
        case_id = item.get("id")
        if not isinstance(case_id, str) or case_id in released_records:
            _error("release case inventory has duplicate or invalid IDs")
        released_records[case_id] = item
    if set(released_records) != set(case_records) or any(
        dict(released_records[key]) != dict(case_records[key]) for key in case_records
    ):
        _error("release case inventory does not exactly bind inventory records")
    for fixture in fixtures:
        if _pending(_mapping(validator.read_json(fixture), "fixture")):
            _error("release fixture has pending expectation")
    ref_name = release.get("reference_manifest")
    if not isinstance(ref_name, str) or not re.fullmatch(
        r"specification/reference/python-[0-9a-f]{7}\.json", ref_name
    ):
        _error("reference manifest path is invalid")
    required_paths.add(ref_name)
    reference = _mapping(validator.read_json(_asset_path(root, ref_name)), "reference manifest")
    revision = _revision(reference.get("reference_run_revision"), "reference revision")
    if ref_name != f"specification/reference/python-{revision[:7]}.json":
        _error("reference manifest path does not bind reference revision")
    driver = _mapping(reference.get("driver"), "reference driver")
    environment_row = _mapping(reference.get("environment"), "reference environment")
    if (
        reference.get("implementation") != "anyinfer-python"
        or reference.get("source_tree") != {"clean": True}
        or driver.get("path") != "tests/testing/portable/"
        or _revision(driver.get("git_revision"), "reference driver revision") != revision
        or not isinstance(reference.get("interpreter"), str)
        or not reference["interpreter"]
        or reference.get("warning_policy") != "error"
    ):
        _error("reference manifest identity is invalid")
    _timestamp(reference.get("produced_at"), "reference produced_at")
    env_name, env_hash = environment_row.get("path"), environment_row.get("sha256")
    if not isinstance(env_name, str) or not re.fullmatch(
        r"specification/reference/python-[0-9a-f]{7}\.environment\.json", env_name
    ):
        _error("reference environment path is invalid")
    if env_name != f"specification/reference/python-{revision[:7]}.environment.json":
        _error("reference environment path does not bind reference revision")
    _hash_field(env_hash, "reference environment sha256")
    required_paths.add(env_name)
    environment_file = _asset_path(root, env_name)
    if _hash(environment_file) != env_hash:
        _error("reference environment hash mismatch")
    environment = _mapping(validator.read_json(environment_file), "reference environment")
    validate_reference_evidence(reference, environment, environment_sha256=_hash(environment_file))
    if set(hashes) != required_paths:
        _error("release file set is not the exact closed release input set")
    problems = validator.validate(
        root / "fixtures", coverage=True, specification_root=root, fixture_paths=fixtures
    )
    if problems:
        _error("selected release fixture validation failed: " + "; ".join(problems))
    return ReleaseAssets(
        root,
        release_file,
        _hash(release_file),
        _freeze(release),
        _freeze(inventory),
        _freeze(case_records),
        _freeze(hashes),
        _freeze(reference),
        _freeze(environment),
    )


def _normalized_result(value: object) -> None:
    result = _mapping(value, "extension native result")
    if set(result) != _RESULT_FIELDS:
        _error("extension native result omits normalized fields")
    if not isinstance(result.get("text"), str) or not _ordinary_json(result["structured"]):
        _error("extension native result has invalid text or structured value")
    if not isinstance(result.get("target"), Mapping):
        _error("extension native result has invalid text or target")
    target = _mapping(result["target"], "extension native target")
    if (
        not isinstance(target.get("provider_id"), str)
        or not target["provider_id"]
        or not isinstance(target.get("model"), str)
        or not target["model"]
    ):
        _error("extension native target is incomplete")
    if (
        not isinstance(result.get("finish_reason"), str)
        or result["finish_reason"] not in _FINISH_REASONS
    ):
        _error("extension native result has invalid finish reason")
    usage = _mapping(result.get("usage"), "extension native usage")
    if not _USAGE_FIELDS.issubset(usage) or any(
        isinstance(usage[name], bool)
        or (usage[name] is not None and not isinstance(usage[name], int))
        for name in _USAGE_FIELDS
    ):
        _error("extension native result has invalid usage")
    timing = _mapping(result.get("timing"), "extension native timing")
    if "first_token_ms" not in timing or "total_ms" not in timing:
        _error("extension native result has incomplete timing")
    first, total = timing["first_token_ms"], timing["total_ms"]
    valid_first = (
        (isinstance(first, str) and first in {"null", "non_null"})
        or first is None
        or (
            isinstance(first, (int, float))
            and not isinstance(first, bool)
            and math.isfinite(first)
        )
    )
    valid_total = (isinstance(total, str) and total == "present") or (
        isinstance(total, (int, float)) and not isinstance(total, bool) and math.isfinite(total)
    )
    if not valid_first or not valid_total:
        _error("extension native result has invalid timing")
    mechanism = result.get("structured_mechanism")
    if mechanism is not None and (not isinstance(mechanism, str) or mechanism not in _MECHANISMS):
        _error("extension native result has invalid structured mechanism")
    if (
        not isinstance(result.get("repair_attempts"), int)
        or isinstance(result.get("repair_attempts"), bool)
        or result["repair_attempts"] < 0
    ):
        _error("extension native result has invalid repair count")
    attempts = result.get("attempts")
    if not isinstance(attempts, list):
        _error("extension native result has invalid attempts")
    for attempt in attempts:
        item = _mapping(attempt, "extension native attempt")
        outcome = item.get("outcome")
        if (
            not isinstance(item.get("target"), str)
            or not item["target"]
            or not isinstance(outcome, str)
            or outcome not in _ATTEMPT_OUTCOMES
        ):
            _error("extension native attempt is incomplete")
        error = item.get("error")
        if outcome in {"retried", "failed"}:
            if not isinstance(error, Mapping) or not isinstance(error.get("category"), str):
                _error("extension native attempt omits failure category")
        elif error is not None:
            _error("extension native attempt has unexpected error")
    if not isinstance(result.get("warnings"), list) or not all(
        isinstance(item, str) for item in result["warnings"]
    ):
        _error("extension native result has invalid normalized subfields")


def _extension_evidence(value: object, case_id: str) -> None:
    evidence = _mapping(value, f"{case_id} extension evidence")
    if set(evidence) != {"native_outcome", "adapter_entries"}:
        _error(f"{case_id}: extension evidence is incomplete")
    outcome = _mapping(evidence.get("native_outcome"), f"{case_id} native outcome")
    if set(outcome) == {"result"}:
        _normalized_result(outcome["result"])
    elif outcome == {"none": True}:
        pass
    elif set(outcome) == {"error"}:
        error = _mapping(outcome["error"], f"{case_id} native error")
        if set(error) != {"category", "native_type", "message"}:
            _error(f"{case_id}: extension native error is incomplete")
        category, native_type = error.get("category"), error.get("native_type")
        if (
            category is not None and not isinstance(category, str)
        ) or not isinstance(native_type, str) or not native_type:
            _error(f"{case_id}: extension native error is invalid")
        final_type = native_type.rsplit(".", 1)[-1]
        if category == "cancelled" or final_type in _FATAL_NATIVE_TYPES:
            _error(f"{case_id}: extension evidence manufactures cancellation/fatal outcome")
    else:
        _error(f"{case_id}: extension native outcome is incomplete")
    entries = evidence.get("adapter_entries")
    if not isinstance(entries, list):
        _error(f"{case_id}: extension adapter entries are invalid")
    for ordinal, value in enumerate(entries):
        entry = _mapping(value, f"{case_id} adapter entry")
        if (
            set(entry) != {"entry_ordinal", "model", "role", "timeout_s", "max_response_bytes"}
            or entry.get("entry_ordinal") != ordinal
            or not isinstance(entry.get("model"), str)
            or not entry["model"]
            or entry.get("role") not in {"original", "correction"}
            or isinstance(entry.get("timeout_s"), bool)
            or not isinstance(entry.get("timeout_s"), (int, float))
            or not math.isfinite(entry["timeout_s"])
            or entry["timeout_s"] < 0
            or isinstance(entry.get("max_response_bytes"), bool)
            or not isinstance(entry.get("max_response_bytes"), int)
            or entry["max_response_bytes"] < 0
        ):
            _error(f"{case_id}: extension adapter entries are invalid")


def _case_validator(specification_root: Path | None) -> Draft202012Validator:
    """Build one selected-root validator for report case records."""
    root = SPECIFICATION if specification_root is None else specification_root
    validator_module = _validator_module()
    try:
        raw = validator_module.read_json(root / "schemas" / "report-v0.schema.json")
    except (OSError, ValueError) as error:
        _error(f"report case schema is unavailable: {error}")
    schema = _mapping(raw, "report schema")
    definitions = schema.get("$defs")
    if not isinstance(definitions, Mapping) or "case" not in definitions:
        _error("report schema has no case definition")
    view = {"$defs": definitions, "$ref": "#/$defs/case"}
    try:
        return validator_module.build_schema_validator(view)
    except SchemaError as error:
        _error(f"report case schema is invalid: {error}")


def validate_successful_cases(
    cases: object,
    inventory_cases: Mapping[str, Mapping[str, Any]],
    *,
    declared_extensions: object,
    specification_root: Path | None = None,
    require_python_extensions: bool = False,
    development_observation: bool = False,
) -> Mapping[str, Mapping[str, Any]]:
    """Validate complete successful report cases against selected v0 report definitions."""
    if (
        not isinstance(declared_extensions, list)
        or any(not isinstance(item, str) for item in declared_extensions)
        or len(set(declared_extensions)) != len(declared_extensions)
        or not set(declared_extensions).issubset(_EXTENSIONS)
        or (require_python_extensions and set(declared_extensions) != _EXTENSIONS)
    ):
        _error("report extensions are invalid")
    if not isinstance(cases, list):
        _error("report cases are invalid")
    if not _ordinary_json(cases):
        _error("report cases must be bounded ordinary JSON")
    validator = _case_validator(specification_root)
    validator_module = _validator_module()
    report_cases: dict[str, Mapping[str, Any]] = {}
    for value in cases:
        row = _mapping(value, "report case")
        case_id = row.get("id")
        if not isinstance(case_id, str) or case_id in report_cases:
            _error("report case IDs are duplicate or invalid")
        report_cases[case_id] = row
    if set(report_cases) != set(inventory_cases):
        _error("report case IDs are incomplete or extra")
    for case_id, row in report_cases.items():
        inventory = inventory_cases[case_id]
        verdict, evidence = row.get("verdict"), row.get("evidence")
        view: object = row
        if development_observation:
            view = dict(row)
            if inventory.get("kind") == "fixture":
                if set(row) != {"id", "verdict", "detail", "observations", "evidence"}:
                    _error("development fixture observation has invalid fields")
                if not _ordinary_json(row["observations"]):
                    _error("development fixture observation is not ordinary JSON")
                if verdict == "pass":
                    view["evidence"] = None
                view.pop("observations")
            elif inventory.get("kind") == "driver_assertion":
                if set(row) != {"id", "verdict", "detail", "evidence"}:
                    _error("development driver observation has invalid fields")
            else:
                _error("inventory case kind is invalid")
        try:
            errors = validator_module.schema_errors(validator, view)
        except validator_module.SchemaEvaluationError as error:
            raise ReleaseBindingError(f"report case schema evaluation failed: {error}") from error
        if errors:
            _error(f"report case schema validation failed: {errors[0].message}")
        if verdict not in {"pass", "extension"}:
            _error("report contains fail/error or invalid verdict")
        if verdict == "extension":
            feature = inventory.get("extension")
            if not isinstance(feature, str) or feature not in declared_extensions:
                _error(f"{case_id}: extension is not eligible and declared")
            _extension_evidence(evidence, case_id)
        elif inventory.get("kind") == "driver_assertion":
            evidence_map = _mapping(evidence, f"{case_id} driver evidence")
            observations = evidence_map.get("observations")
            if (
                evidence_map.get("recipe_ref") != inventory.get("recipe_ref")
                or not isinstance(observations, Mapping)
                or not observations
            ):
                _error(f"{case_id}: driver evidence is missing or mismatched")
    return report_cases


def _qualify_report_mapping(report: Mapping[str, Any], assets: ReleaseAssets) -> Mapping[str, Any]:
    if not _ordinary_json(report):
        _error("report must be ordinary JSON data")
    validator = _validator_module()
    problems = validator.validate_report(report, specification_root=assets.specification_root)
    if problems:
        _error("report schema validation failed: " + "; ".join(problems))
    if (
        report.get("release") != assets.release.get("release")
        or report.get("release_sha256") != assets.release_sha256
    ):
        _error("report release identity is untrusted")
    implementation = _mapping(report.get("implementation"), "report implementation")
    _revision(implementation.get("source_revision"), "report source revision")
    _revision(implementation.get("driver_revision"), "report driver revision")
    cases = report.get("cases")
    if not isinstance(cases, list):
        _error("report cases are invalid")
    validate_successful_cases(
        cases,
        assets.cases_by_id,
        declared_extensions=implementation.get("extensions"),
        specification_root=assets.specification_root,
        require_python_extensions=implementation.get("name") == "anyinfer-python",
    )
    counts = {
        verdict: sum(row.get("verdict") == verdict for row in cases)
        for verdict in ("pass", "fail", "error", "extension")
    }
    if report.get("counts") != counts or counts["fail"] != 0 or counts["error"] != 0:
        _error("report counts are stale or report contains fail/error")
    return report


def validate_qualified_report(report_path: Path, assets: ReleaseAssets) -> Mapping[str, Any]:
    """Load and fully qualify an ordinary JSON report against frozen assets."""
    validator = _validator_module()
    try:
        report = _mapping(validator.read_json(report_path), "report")
    except (OSError, ValueError) as exc:
        raise ReleaseBindingError(f"invalid report JSON: {exc}") from exc
    return _qualify_report_mapping(report, assets)


def require_comparable_reports(
    left: Mapping[str, Any], right: Mapping[str, Any], assets: ReleaseAssets
) -> None:
    """Qualify both reports and permit only v0's reference-extension asymmetry."""
    qualified = (_qualify_report_mapping(left, assets), _qualify_report_mapping(right, assets))
    rows: list[dict[str, Mapping[str, Any]]] = []
    names: list[object] = []
    for report in qualified:
        report_rows: dict[str, Mapping[str, Any]] = {}
        for value in cast(list[Any], report["cases"]):
            row = _mapping(value, "qualified report case")
            report_rows[cast(str, row["id"])] = row
        rows.append(report_rows)
        names.append(_mapping(report["implementation"], "qualified implementation").get("name"))
    for case_id, inventory in assets.cases_by_id.items():
        first, second = rows[0][case_id].get("verdict"), rows[1][case_id].get("verdict")
        if first == second and first in {"pass", "extension"}:
            continue
        if isinstance(inventory.get("extension"), str) and {first, second} == {
            "pass",
            "extension",
        }:
            extension_index = 0 if first == "extension" else 1
            if (
                names[extension_index] == "anyinfer-python"
                and names[1 - extension_index] != "anyinfer-python"
            ):
                continue
        _error(f"incomparable verdicts for {case_id}: {first!r} vs {second!r}")
