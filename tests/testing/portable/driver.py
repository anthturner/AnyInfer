"""Write an explicitly UNRELEASED observation of the selected portable corpus.

This private driver is intentionally not a report-v0 producer.  It observes native Python
behaviour against a selected specification tree and records enough input and environment
identity to make a development result auditable without claiming release qualification.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import warnings
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .comparison import compare_fixture
from .runner import run_fixture
from .values import MissingEvidenceError, ensure_value_domain

_REPOSITORY_ROOT = Path(__file__).parents[3]
_DEFAULT_ROOT = _REPOSITORY_ROOT / "specification"
_INVENTORY = Path("inventories/core-generation-v0.json")
_CORE_PREFIX = "specification/fixtures/core-generation/"
_TRANSPORT_PREFIX = "specification/fixtures/transport/"
_EXTENSIONS = (
    "schema.ref",
    "schema.combinators",
    "schema.other_dialects",
    "schema.boolean_subschema",
    "schema.unknown_keywords_ignored",
    "messages.tool_role",
    "targets.alias",
    "messages.non_text_parts",
)
_NORMATIVE_INPUTS = (
    Path("README.md"),
    Path("core-generation.md"),
    Path("MAINTENANCE.md"),
    Path("schemas/fixture-v0.schema.json"),
    Path("schemas/transport-v0.schema.json"),
    Path("schemas/inventory-v0.schema.json"),
    Path("schemas/report-v0.schema.json"),
    _INVENTORY,
)


class DriverInputError(ValueError):
    """The selected specification tree cannot safely be observed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve())
    except ValueError as error:
        raise DriverInputError(f"path escapes selected specification root: {path}") from error


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DriverInputError(f"cannot read JSON input {path}: {error}") from error
    if not isinstance(document, dict):
        raise DriverInputError(f"JSON input must be an object: {path}")
    return document


def _selected_fixture(root: Path, path_value: object) -> Path:
    if not isinstance(path_value, str) or "\\" in path_value:
        raise DriverInputError("inventory fixture path must be a canonical slash-delimited string")
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise DriverInputError(f"unsafe inventory fixture path: {path_value!r}")
    try:
        under_fixtures = relative.relative_to("specification/fixtures")
    except ValueError as error:
        raise DriverInputError(
            f"inventory fixture path is outside specification fixtures: {path_value!r}"
        ) from error
    candidate = root / "fixtures" / under_fixtures
    _inside(root, candidate)
    if not candidate.is_file():
        raise DriverInputError(f"inventory fixture is missing from selected root: {path_value}")
    return candidate


def _validate_fixture_identity(root: Path, record: Mapping[str, Any], path: Path) -> None:
    fixture = _load_json(path)
    for field in ("id", "family", "extension"):
        if fixture.get(field) != record.get(field):
            raise DriverInputError(
                f"selected fixture {path} {field} does not match inventory {record.get('id')!r}"
            )


def _inventory(root: Path) -> list[dict[str, Any]]:
    inventory_path = root / _INVENTORY
    _inside(root, inventory_path)
    inventory = _load_json(inventory_path)
    if inventory.get("profile") != "core-generation" or inventory.get("profile_revision") != "v0":
        raise DriverInputError("selected inventory is not core-generation v0")
    cases = inventory.get("cases")
    if not isinstance(cases, list):
        raise DriverInputError("selected inventory cases must be an array")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in cases:
        if not isinstance(record, dict):
            raise DriverInputError("selected inventory contains a non-object case")
        case_id, kind = record.get("id"), record.get("kind")
        if not isinstance(case_id, str) or not isinstance(kind, str):
            raise DriverInputError("selected inventory case lacks id or kind")
        if case_id in seen:
            raise DriverInputError(f"duplicate selected inventory case id: {case_id}")
        seen.add(case_id)
        if kind == "fixture":
            path_value = record.get("path")
            if not isinstance(path_value, str):
                raise DriverInputError(f"fixture case {case_id} lacks a path")
            if path_value.startswith(_CORE_PREFIX):
                _validate_fixture_identity(root, record, _selected_fixture(root, path_value))
            elif path_value.startswith(_TRANSPORT_PREFIX):
                candidate = (
                    root / "fixtures" / Path(path_value).relative_to("specification/fixtures")
                )
                _inside(root, candidate)
                if candidate.is_file():
                    _validate_fixture_identity(root, record, _selected_fixture(root, path_value))
            else:
                raise DriverInputError(f"fixture case {case_id} has an unknown fixture domain")
        elif kind == "driver_assertion":
            if record.get("path") is not None or not isinstance(record.get("recipe_ref"), str):
                raise DriverInputError(f"driver assertion {case_id} has an invalid recipe record")
        else:
            raise DriverInputError(f"unknown inventory case kind {kind!r}")
        records.append(record)
    return records


def _asset_problems(root: Path) -> list[str]:
    """Validate selected core inputs with schemas from that same selected root."""
    problems: list[str] = []
    schemas: dict[str, Draft202012Validator] = {}
    for name in (
        "fixture-v0.schema.json",
        "transport-v0.schema.json",
        "inventory-v0.schema.json",
    ):
        path = root / "schemas" / name
        try:
            schemas[name] = Draft202012Validator(_load_json(path))
        except Exception as error:  # jsonschema reports the selected schema failure below.
            problems.append(f"selected schema {name} is invalid: {error}")
    if problems:
        return problems
    inventory_path = root / _INVENTORY
    try:
        inventory = _load_json(inventory_path)
    except DriverInputError as error:
        return [str(error)]
    problems.extend(
        f"{_INVENTORY.as_posix()}: {error.message}"
        for error in schemas["inventory-v0.schema.json"].iter_errors(inventory)
    )
    cases = inventory.get("cases")
    if not isinstance(cases, list):
        return problems
    for record in cases:
        if not isinstance(record, dict) or record.get("kind") != "fixture":
            continue
        path_value = record.get("path")
        if not isinstance(path_value, str):
            continue
        schema_name = (
            "fixture-v0.schema.json"
            if path_value.startswith(_CORE_PREFIX)
            else "transport-v0.schema.json"
        )
        if path_value.startswith(_TRANSPORT_PREFIX):
            candidate = root / "fixtures" / Path(path_value).relative_to("specification/fixtures")
            _inside(root, candidate)
            if not candidate.is_file():
                continue
        elif not path_value.startswith(_CORE_PREFIX):
            continue
        try:
            path = _selected_fixture(root, path_value)
            fixture = _load_json(path)
        except DriverInputError as error:
            problems.append(str(error))
            continue
        problems.extend(
            f"{path.relative_to(root).as_posix()}: {error.message}"
            for error in schemas[schema_name].iter_errors(fixture)
        )
    return problems


def _hashes(root: Path, records: Iterable[Mapping[str, Any]]) -> list[dict[str, str | None]]:
    paths = list(_NORMATIVE_INPUTS)
    paths.extend(
        Path(str(record["path"])).relative_to("specification")
        for record in records
        if record.get("kind") == "fixture"
    )
    result: list[dict[str, str | None]] = []
    seen: set[Path] = set()
    for relative in paths:
        if relative in seen:
            continue
        seen.add(relative)
        path = root / relative
        _inside(root, path)
        if not path.is_file() and relative.as_posix().startswith("fixtures/transport/"):
            result.append({"path": relative.as_posix(), "sha256": None})
            continue
        if not path.is_file():
            raise DriverInputError(f"required selected input is missing: {relative.as_posix()}")
        result.append({"path": relative.as_posix(), "sha256": _sha256(path)})
    return result


def _git(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *command],
            cwd=_REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def _warning_policy() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for action, message, category, module, lineno in warnings.filters:
        category_name = (
            f"{category.__module__}.{category.__qualname__}"
            if isinstance(category, type)
            else repr(category)
        )
        result.append(
            {
                "action": action,
                "message": getattr(message, "pattern", message),
                "category": category_name,
                "module": getattr(module, "pattern", module),
                "lineno": lineno,
            }
        )
    return result


def _implementation() -> dict[str, Any]:
    import anyinfer

    dependencies: dict[str, str | None] = {}
    for name in ("anyinfer", "httpx2", "jsonschema", "pytest"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    return {
        "source": {
            "head": _git(["rev-parse", "HEAD"]),
            "dirty": bool(_git(["status", "--porcelain"])),
        },
        "imports": {
            "anyinfer": str(Path(anyinfer.__file__).resolve()),
            "driver": str(Path(__file__).resolve()),
        },
        "runtime": {
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "dependencies": dependencies,
        "warning_policy": _warning_policy(),
    }


def _check_recipe(record: object, case_id: str, recipe_ref: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise DriverInputError(f"driver recipe {case_id} returned a non-object record")
    if record.get("id") != case_id:
        raise DriverInputError(f"driver recipe {case_id} returned the wrong identity")
    if record.get("verdict") not in {"pass", "fail", "error"}:
        raise DriverInputError(f"driver recipe {case_id} returned an invalid verdict")
    evidence = record.get("evidence")
    if record["verdict"] == "pass":
        if (
            not isinstance(evidence, dict)
            or evidence.get("recipe_ref") != recipe_ref
            or not evidence.get("observations")
        ):
            raise MissingEvidenceError(f"passing driver recipe {case_id} lacks observations")
        ensure_value_domain(evidence)
    return record


async def observe_core(root: Path) -> dict[str, Any]:
    """Observe the selected core-generation root sequentially and return development JSON."""
    root = root.resolve()
    if not root.is_dir():
        raise DriverInputError(f"selected specification root does not exist: {root}")
    problems = _asset_problems(root)
    if problems:
        raise DriverInputError("selected fixture assets are invalid: " + "; ".join(problems))
    records = _inventory(root)
    cases: list[dict[str, Any]] = []
    unexecuted: list[dict[str, Any]] = []
    for record in records:
        case_id = str(record["id"])
        if record["kind"] == "fixture":
            path = str(record["path"])
            if path.startswith(_TRANSPORT_PREFIX):
                candidate = root / "fixtures" / Path(path).relative_to("specification/fixtures")
                fixture_path = _selected_fixture(root, path) if candidate.is_file() else None
                unexecuted.append(
                    {
                        "id": case_id,
                        "path": path,
                        "family": str(record["family"]),
                        "extension": record.get("extension"),
                        "status": "present" if fixture_path is not None else "missing",
                        "sha256": _sha256(fixture_path) if fixture_path is not None else None,
                        "reason": "transport driver is not implemented",
                    }
                )
                continue
            fixture = _load_json(_selected_fixture(root, path))
            if fixture.get("id") != case_id or fixture.get("family") != record.get("family"):
                raise DriverInputError(
                    f"selected fixture identity does not match inventory: {case_id}"
                )
            cases.append(
                compare_fixture(fixture, await run_fixture(fixture), extensions=_EXTENSIONS)
            )
            continue
        recipe_ref = str(record["recipe_ref"])
        if recipe_ref == "driver/http-correction-byte-budget-reset":
            unexecuted.append(
                {
                    "id": case_id,
                    "path": None,
                    "family": str(record["family"]),
                    "extension": record.get("extension"),
                    "status": "unavailable",
                    "sha256": None,
                    "reason": "HTTP driver recipe is not implemented",
                }
            )
            continue
        try:
            from .proofs import CORE_DRIVER_RECIPE_IDS, run_core_driver_assertion
        except ImportError as error:
            cases.append(
                {
                    "id": case_id,
                    "verdict": "error",
                    "detail": f"core proof driver unavailable: {error}",
                    "evidence": None,
                }
            )
            continue
        if recipe_ref not in CORE_DRIVER_RECIPE_IDS:
            raise DriverInputError(
                f"inventory recipe is not an available core recipe: {recipe_ref}"
            )
        cases.append(
            _check_recipe(await run_core_driver_assertion(recipe_ref), case_id, recipe_ref)
        )
    identities = [case.get("id") for case in cases] + [case["id"] for case in unexecuted]
    if len(identities) != len(records) or len(set(identities)) != len(records):
        raise DriverInputError("driver did not produce exact selected inventory coverage")
    counts = Counter(str(case.get("verdict")) for case in cases)
    counts["unexecuted"] = len(unexecuted)
    return {
        "development_observation": "UNRELEASED",
        "report_v0_eligible": False,
        "report_v0_reason": "development observations do not carry release or reference qualification",
        "profile": {"name": "core-generation", "revision": "v0"},
        "selected_root": str(root),
        "inputs": _hashes(root, records),
        "implementation": _implementation(),
        "extensions": list(_EXTENSIONS),
        "cases": cases,
        "unexecuted": unexecuted,
        "counts": dict(sorted(counts.items())),
    }


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    """Atomically write UTF-8 LF JSON without changing structured member order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    """Run the UNRELEASED development observer as a command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_DEFAULT_ROOT)
    parser.add_argument("--portable-report", type=Path, required=True)
    parser.add_argument("--write-reference", type=Path)
    args = parser.parse_args(argv)
    if args.write_reference is not None:
        parser.error(
            "--write-reference is unavailable until M1.5c/M1.7 reference preflight exists"
        )
    try:
        write_json(args.portable_report, asyncio.run(observe_core(args.root)))
    except DriverInputError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
