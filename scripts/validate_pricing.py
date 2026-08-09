"""Validate the bundled pricing table.

Gate for the pricing-refresh workflow and for CI: the file must parse through the same
code path the library uses, and every entry must satisfy the sanity rules that keep a
bad merge from silently corrupting cost reporting.

Exit codes: 0 valid, 1 invalid (reasons on stderr).
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICING_PATH = REPO_ROOT / "src" / "anyinfer" / "capabilities" / "pricing.json"

sys.path.insert(0, str(REPO_ROOT / "src"))

from anyinfer.capabilities.pricing_table import PricingTable  # noqa: E402


def validate(path: Path = PRICING_PATH) -> list[str]:
    """Return every problem found; an empty list means the file is valid."""
    problems: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))

    try:
        table = PricingTable.from_mapping(data)
    except Exception as error:  # noqa: BLE001 — report, don't crash the validator
        return [f"table does not parse: {error}"]

    today = _dt.date.today()
    for provider in table.providers:
        for entry in table.entries_for(provider):
            where = f"{provider}:{entry.model}"
            try:
                verified = _dt.date.fromisoformat(entry.last_verified)
            except ValueError:
                problems.append(f"{where}: last_verified {entry.last_verified!r} is not ISO")
                continue
            if verified > today:
                problems.append(f"{where}: last_verified {verified} is in the future")
            if not entry.source.startswith("https://"):
                problems.append(f"{where}: source must be an https URL")
            if entry.pricing.input_per_1m == 0 and entry.pricing.output_per_1m == 0:
                problems.append(
                    f"{where}: zero prices belong to local engines, not table entries"
                )
    return problems


def main() -> int:
    """CLI entry point."""
    problems = validate()
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}", file=sys.stderr)
        return 1
    print(f"{PRICING_PATH.name}: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
