"""Compare two qualified portable conformance reports for one sealed release."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from portable_release_assets import (
    ReleaseAssets,
    ReleaseBindingError,
    load_release_assets,
    require_comparable_reports,
    validate_qualified_report,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPECIFICATION = ROOT / "specification"
DEFAULT_RELEASE = Path("releases/core-generation-v0.json")


def _allowed_extension_ids(
    left: Mapping[str, Any], right: Mapping[str, Any], assets: ReleaseAssets
) -> list[str]:
    """Return sorted eligible Python-extension versus other-pass case identifiers."""
    reports = (left, right)
    rows: list[dict[str, Mapping[str, Any]]] = []
    names: list[object] = []
    for report in reports:
        report_rows: dict[str, Mapping[str, Any]] = {}
        for value in report["cases"]:
            if isinstance(value, Mapping) and isinstance(value.get("id"), str):
                report_rows[value["id"]] = value
        rows.append(report_rows)
        implementation = report.get("implementation")
        names.append(implementation.get("name") if isinstance(implementation, Mapping) else None)
    allowed: list[str] = []
    for case_id, inventory in assets.cases_by_id.items():
        first, second = rows[0][case_id].get("verdict"), rows[1][case_id].get("verdict")
        if (
            isinstance(inventory.get("extension"), str)
            and {first, second} == {"extension", "pass"}
            and names[0 if first == "extension" else 1] == "anyinfer-python"
        ):
            allowed.append(case_id)
    return sorted(allowed)


def compare_reports(
    left_path: Path,
    right_path: Path,
    *,
    specification_root: Path = DEFAULT_SPECIFICATION,
    release_path: Path = DEFAULT_RELEASE,
) -> tuple[ReleaseAssets, Mapping[str, Any], Mapping[str, Any], list[str]]:
    """Load one release, qualify both reports, and verify their allowed comparison."""
    assets = load_release_assets(specification_root, release_path)
    left = validate_qualified_report(left_path, assets)
    right = validate_qualified_report(right_path, assets)
    require_comparable_reports(left, right, assets)
    return assets, left, right, _allowed_extension_ids(left, right, assets)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path, help="first qualified report JSON")
    parser.add_argument("right", type=Path, help="second qualified report JSON")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_SPECIFICATION,
        help="selected specification directory (default: checkout specification/)",
    )
    parser.add_argument(
        "--release",
        type=Path,
        default=DEFAULT_RELEASE,
        help="release path under --root/releases (default: releases/core-generation-v0.json)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the read-only report comparison CLI."""
    args = _parser().parse_args(argv)
    try:
        assets, _left, _right, extension_ids = compare_reports(
            args.left,
            args.right,
            specification_root=args.root,
            release_path=args.release,
        )
    except ReleaseBindingError as error:
        print(f"compare_reports: {error}", file=sys.stderr)
        return 1
    print(
        "qualified comparable reports: "
        f"release={assets.release['release']} sha256={assets.release_sha256} "
        f"cases={len(assets.cases_by_id)}"
    )
    print(
        "allowed reference-extension-to-other-pass IDs: "
        + (", ".join(extension_ids) if extension_ids else "none")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
