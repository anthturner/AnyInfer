"""Create or verify one immutable core-generation release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from portable_release_assets import (
    ReleaseAssets,
    ReleaseBindingError,
    _asset_path,
    _is_link,
    _selected_root,
    _validator_module,
    load_release_assets,
)

_INVENTORY = "specification/inventories/core-generation-v0.json"
_NORMATIVE = (
    "specification/README.md",
    "specification/core-generation.md",
    "specification/MAINTENANCE.md",
)
_SCHEMAS = (
    "fixture-v0.schema.json",
    "transport-v0.schema.json",
    "inventory-v0.schema.json",
    "report-v0.schema.json",
)
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class _OwnedFile:
    device: int
    inode: int


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Mapping[str, Any]:
    value = _validator_module().read_json(path)
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ReleaseBindingError(f"release input is not a JSON object: {path.as_posix()}")
    return cast(Mapping[str, Any], value)


def _reference_name(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or path.parts[:1] != ("reference",)
        or any(part in {".", ".."} for part in path.parts)
        or path.suffix != ".json"
    ):
        raise ReleaseBindingError("reference must be a safe reference/<name>.json path")
    return value


def _release_output(root: Path, release_id: str) -> Path:
    if not _RELEASE_ID.fullmatch(release_id):
        raise ReleaseBindingError("release identity is not a safe filename")
    releases = root / "releases"
    if releases.exists():
        if _is_link(releases) or not releases.is_dir() or releases.resolve().parent != root:
            raise ReleaseBindingError("release directory is unsafe")
    else:
        releases.mkdir()
    return releases / f"{release_id}.json"


def _input_paths(
    root: Path, reference_name: str
) -> tuple[dict[str, str], list[Mapping[str, Any]]]:
    reference_path = _asset_path(root, f"specification/{reference_name}")
    reference = _read_json(reference_path)
    environment = reference.get("environment")
    if not isinstance(environment, Mapping) or not isinstance(environment.get("path"), str):
        raise ReleaseBindingError("reference manifest has no environment path")
    environment_name = cast(str, environment["path"])
    _asset_path(root, environment_name)

    inventory_path = _asset_path(root, _INVENTORY)
    inventory = _read_json(inventory_path)
    cases = inventory.get("cases")
    if not isinstance(cases, list):
        raise ReleaseBindingError("selected inventory has no case list")
    case_records: list[Mapping[str, Any]] = []
    case_ids: set[str] = set()
    fixture_paths: set[str] = set()
    for value in cases:
        if not isinstance(value, Mapping) or not isinstance(value.get("id"), str):
            raise ReleaseBindingError("selected inventory has an invalid case record")
        case_id = cast(str, value["id"])
        if not case_id or case_id in case_ids:
            raise ReleaseBindingError("selected inventory case IDs are not unique")
        case_ids.add(case_id)
        if value.get("kind") == "fixture":
            path = value.get("path")
            if not isinstance(path, str) or path in fixture_paths:
                raise ReleaseBindingError("selected inventory fixture paths are invalid")
            _asset_path(root, path)
            fixture_paths.add(path)
        elif value.get("kind") != "driver_assertion" or value.get("path") is not None:
            raise ReleaseBindingError("selected inventory driver record is invalid")
        case_records.append(value)

    names = {
        *_NORMATIVE,
        _INVENTORY,
        *(f"specification/schemas/{name}" for name in _SCHEMAS),
        *fixture_paths,
        f"specification/{reference_name}",
        environment_name,
    }
    has_generated_file = any(
        name.startswith("specification/releases/") or "/reports/" in name for name in names
    )
    if has_generated_file:
        raise ReleaseBindingError("release input set is not the closed core-generation-v0 set")
    hashes = {name: _hash(_asset_path(root, name)) for name in sorted(names)}
    return hashes, case_records


def _payload(
    release_id: str,
    reference_name: str,
    hashes: Mapping[str, str],
    cases: Sequence[Mapping[str, Any]],
) -> bytes:
    document: dict[str, Any] = {
        "release": release_id,
        "profile": "core-generation",
        "profile_revision": "v0",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reference_manifest": f"specification/{reference_name}",
        "files": dict(hashes),
        "case_inventory": list(cases),
    }
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_payload(descriptor: int, payload: bytes) -> None:
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def _remove_owned(path: Path, owned: _OwnedFile) -> None:
    try:
        current = path.lstat()
        if (
            stat.S_ISREG(current.st_mode)
            and current.st_dev == owned.device
            and current.st_ino == owned.inode
        ):
            path.unlink()
    except OSError:
        pass


def freeze_release(root: Path, reference_name: str, release_id: str) -> ReleaseAssets:
    """Write and qualify a new closed release without replacing an existing file."""
    selected = _selected_root(root)
    reference = _reference_name(reference_name)
    output = _release_output(selected, release_id)
    if output.exists() or _is_link(output):
        raise FileExistsError(f"release already exists: {output}")
    hashes, cases = _input_paths(selected, reference)
    payload = _payload(release_id, reference, hashes, cases)
    descriptor = os.open(
        output,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
    )
    details = os.fstat(descriptor)
    owned = _OwnedFile(details.st_dev, details.st_ino)
    try:
        _write_payload(descriptor, payload)
        return load_release_assets(selected, output)
    except BaseException:
        _remove_owned(output, owned)
        raise


def verify_release(root: Path, release_id: str) -> ReleaseAssets:
    """Load and verify one existing selected release."""
    selected = _selected_root(root)
    if not _RELEASE_ID.fullmatch(release_id):
        raise ReleaseBindingError("release identity is not a safe filename")
    return load_release_assets(selected, Path("releases") / f"{release_id}.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("specification"))
    parser.add_argument("--reference")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("release")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the release writer or verifier command-line interface."""
    args = _parser().parse_args(argv)
    if args.verify:
        if args.reference is not None:
            _parser().error("--reference is only valid when creating a release")
        assets = verify_release(args.root, args.release)
    else:
        if args.reference is None:
            _parser().error("--reference is required when creating a release")
        assets = freeze_release(args.root, args.reference, args.release)
    print(f"{assets.release['release']} {assets.release_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
