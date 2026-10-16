"""Produce a qualified Python report only from a verified frozen portable release."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import re
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

from .driver import _EXTENSIONS, observe_core
from .reference import (
    ReferencePreflightError,
    _clean_status,
    _distribution_lock,
    _git,
    _release_assets_module,
    _runtime_provenance,
    _safe_root,
    strict_reference_warnings,
)
from .reference_writer import _publish_new

__all__ = ["ReleaseReportError", "release_report_path", "write_release_report"]

_REPOSITORY_ROOT = Path(__file__).parents[3]
_DEFAULT_ROOT = _REPOSITORY_ROOT / "specification"
_DEFAULT_RELEASE = Path("releases/core-generation-v0.json")
_REVISION = re.compile(r"^[0-9a-f]{40}$")


class ReleaseReportError(ValueError):
    """The final portable report cannot be safely produced or qualified."""


def _fail(message: str) -> NoReturn:
    raise ReleaseReportError(message)


def _revision(repository: Path) -> str:
    value = _git(repository, "rev-parse", "HEAD").strip()
    if _REVISION.fullmatch(value) is None or value == "0" * 40:
        _fail("current executable source revision is not a nonzero Git revision")
    return value


def _is_link_or_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def release_report_path(repository_root: Path, revision: str) -> Path:
    """Return the only canonical A-side output path for a current qualified report."""
    if _REVISION.fullmatch(revision) is None or revision == "0" * 40:
        _fail("report revision is not a nonzero lowercase 40-hex value")
    return repository_root / "specification" / "reports" / f"python-{revision[:7]}.json"


def _output_path(repository: Path, revision: str) -> Path:
    target = release_report_path(repository, revision).absolute()
    specification = (repository / "specification").absolute()
    expected = (specification / "reports" / f"python-{revision[:7]}.json").absolute()
    if target != expected:
        _fail("qualified report output is not the exact canonical A-side filename")
    for ancestor in (*tuple(reversed(target.parents)), target):
        if _is_link_or_reparse(ancestor):
            _fail("qualified report output uses a link or reparse point")
    try:
        target.resolve(strict=False).relative_to(specification.resolve())
    except ValueError as error:
        raise ReleaseReportError("qualified report output escapes executable specification") from error
    if target.exists():
        _fail("qualified report output already exists")
    return target


def _prepare_output(repository: Path, output: Path, revision: str) -> None:
    """Create the one approved generated directory immediately before publication."""
    expected = release_report_path(repository, revision).absolute()
    if output.absolute() != expected:
        _fail("qualified report output changed after preflight")
    specification = repository / "specification"
    directory = specification / "reports"
    for path in (repository, specification):
        if _is_link_or_reparse(path) or not path.is_dir():
            _fail("qualified report executable root is unsafe")
    if directory.exists():
        if not directory.is_dir() or _is_link_or_reparse(directory):
            _fail("qualified report output directory is unsafe")
    else:
        directory.mkdir()
    if _is_link_or_reparse(directory) or output.exists() or _is_link_or_reparse(output):
        _fail("qualified report output changed before publication")
    try:
        directory.resolve().relative_to(specification.resolve())
    except ValueError as error:
        raise ReleaseReportError("qualified report output directory escapes executable root") from error


def _assets(root: Path, release: Path) -> tuple[ModuleType, Any]:
    helper = _release_assets_module()
    try:
        return helper, helper.load_release_assets(root, release)
    except helper.ReleaseBindingError as error:
        raise ReleaseReportError(f"frozen release is invalid: {error}") from error


def _preflight(
    root: Path,
    release: Path,
    repository_root: Path,
    observer: Callable[[Path], Awaitable[Mapping[str, Any]]] = observe_core,
) -> tuple[Path, Path, str, Any, ModuleType]:
    repository = _safe_root(repository_root, "repository root")
    selected = _safe_root(root, "selected release root")
    revision = _revision(repository)
    output = _output_path(repository, revision)
    try:
        _clean_status(repository, set())
        _runtime_provenance(repository, Path(__file__), observer)
    except ReferencePreflightError as error:
        raise ReleaseReportError(str(error)) from error
    helper, assets = _assets(selected, release)
    return repository, output, revision, assets, helper


def _same_release(before: Any, after: Any) -> bool:
    return (
        before.release_sha256 == after.release_sha256
        and dict(before.file_hashes) == dict(after.file_hashes)
        and dict(before.cases_by_id) == dict(after.cases_by_id)
    )


def _development_rows(observation: Mapping[str, Any], assets: Any, helper: ModuleType) -> list[dict[str, Any]]:
    if (
        observation.get("development_observation") != "UNRELEASED"
        or observation.get("report_v0_eligible") is not False
        or observation.get("unexecuted") != []
    ):
        _fail("native observer did not return a complete unreleased observation")
    rows = observation.get("cases")
    try:
        found = helper.validate_successful_cases(
            rows,
            assets.cases_by_id,
            declared_extensions=observation.get("extensions"),
            specification_root=assets.specification_root,
            require_python_extensions=True,
            development_observation=True,
        )
    except helper.ReleaseBindingError as error:
        raise ReleaseReportError(f"native observation cannot qualify: {error}") from error
    raw_counts = observation.get("counts")
    expected_counts = Counter(str(row["verdict"]) for row in found.values())
    expected_counts["unexecuted"] = 0
    if not isinstance(raw_counts, Mapping) or dict(raw_counts) != dict(sorted(expected_counts.items())):
        _fail("native observation counts are stale")
    result: list[dict[str, Any]] = []
    for case_id, inventory in assets.cases_by_id.items():
        row = found[case_id]
        verdict = row["verdict"]
        report_row: dict[str, Any] = {
            "id": case_id,
            "verdict": verdict,
            "detail": row.get("detail"),
        }
        if verdict == "extension" or inventory.get("kind") == "driver_assertion":
            report_row["evidence"] = row.get("evidence")
        else:
            report_row["evidence"] = None
        result.append(report_row)
    return result


def _implementation(repository: Path, revision: str) -> dict[str, Any]:
    try:
        lock = _distribution_lock()
    except ReferencePreflightError as error:
        raise ReleaseReportError(str(error)) from error
    anyinfer = lock.get("anyinfer")
    if not isinstance(anyinfer, Mapping) or not isinstance(anyinfer.get("version"), str):
        _fail("current environment has no AnyInfer package version")
    return {
        "name": "anyinfer-python",
        "version": anyinfer["version"],
        "source_revision": revision,
        "driver_revision": revision,
        "runtime": f"{sys.implementation.name} {sys.version}",
        "os": platform.platform(),
        "dependencies": {name: str(row["version"]) for name, row in lock.items()},
        "extensions": list(_EXTENSIONS),
    }


def _report(
    observation: Mapping[str, Any], assets: Any, helper: ModuleType, repository: Path, revision: str
) -> dict[str, Any]:
    cases = _development_rows(observation, assets, helper)
    counts = {verdict: sum(row["verdict"] == verdict for row in cases) for verdict in ("pass", "fail", "error", "extension")}
    report = {
        "report_version": "0",
        "release": assets.release["release"],
        "release_sha256": assets.release_sha256,
        "implementation": _implementation(repository, revision),
        "cases": cases,
        "counts": counts,
    }
    try:
        helper._qualify_report_mapping(report, assets)
    except helper.ReleaseBindingError as error:
        raise ReleaseReportError(f"generated report cannot qualify: {error}") from error
    return report


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


async def write_release_report(
    root: Path,
    *,
    release: Path = _DEFAULT_RELEASE,
    repository_root: Path = _REPOSITORY_ROOT,
    observe: Callable[[Path], Awaitable[Mapping[str, Any]]] = observe_core,
) -> Mapping[str, Any]:
    """Observe one verified release and atomically publish its qualified Python report."""
    repository, output, revision, before, helper = _preflight(root, release, repository_root, observe)
    with strict_reference_warnings():
        observation = await observe(before.specification_root)
    if not isinstance(observation, Mapping):
        _fail("native observer did not return an object")
    report = _report(observation, before, helper, repository, revision)
    after_repository, after_output, after_revision, after, after_helper = _preflight(
        root, release, repository_root, observe
    )
    if (
        after_repository != repository
        or after_output != output
        or after_revision != revision
        or not _same_release(before, after)
    ):
        _fail("source or frozen release changed during native observation")
    try:
        after_helper._qualify_report_mapping(report, after)
    except after_helper.ReleaseBindingError as error:
        raise ReleaseReportError(f"generated report cannot qualify after observation: {error}") from error
    _prepare_output(repository, output, revision)
    try:
        _publish_new(output, _json_bytes(report))
    except OSError as error:
        raise ReleaseReportError(f"cannot publish qualified report: {error}") from error
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_DEFAULT_ROOT)
    parser.add_argument("--release", type=Path, default=_DEFAULT_RELEASE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the private final portable-report producer."""
    args = _parser().parse_args(argv)
    try:
        asyncio.run(write_release_report(args.root, release=args.release))
    except ReleaseReportError as error:
        parser = _parser()
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
