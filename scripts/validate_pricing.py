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
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICING_PATH = REPO_ROOT / "src" / "anyinfer" / "capabilities" / "pricing.json"

sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from pricing_check import load_bundled, validate_policies  # noqa: E402

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
    generated_raw = data.get("generated")
    try:
        generated = _dt.date.fromisoformat(generated_raw)
    except (TypeError, ValueError):
        problems.append(f"generated {generated_raw!r} is not an ISO date")
    else:
        if generated > today:
            problems.append(f"generated {generated} is in the future")
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
                problems.append(f"{where}: zero prices belong to local engines, not table entries")
    problems.extend(_server_tool_problems(data, today))

    try:
        problems.extend(validate_policies(load_bundled(data)))
    except (KeyError, TypeError, ValueError) as error:
        problems.append(f"coverage policy validation failed: {error}")
    return problems


def _server_tool_problems(data: dict, today: _dt.date) -> list[str]:
    """Apply the token-rate discipline to per-invocation rates.

    Read from the raw document rather than through the table, because the loader keeps
    only the rate itself — the date and source exist to be audited here, and dropping
    them into the loader's return type would put audit metadata on every priced call.

    Without this, a search rate could land with a date in the future and a source that is
    not a URL and still pass the gate, which is precisely the discipline the block was
    added to inherit rather than to sit beside.
    """
    block = data.get("server_tools")
    if block is None:
        return []
    if not isinstance(block, dict):
        return ["server_tools must be a mapping of provider id to rates"]

    problems: list[str] = []
    for provider, rates in block.items():
        if not isinstance(rates, dict):
            problems.append(f"server_tools:{provider}: must be an object")
            continue
        for kind, entry in rates.items():
            if kind.startswith("_"):
                continue
            where = f"server_tools:{provider}:{kind}"
            if not isinstance(entry, dict):
                problems.append(f"{where}: must be an object")
                continue

            verified_raw = entry.get("last_verified")
            try:
                verified = _dt.date.fromisoformat(str(verified_raw))
            except ValueError:
                problems.append(f"{where}: last_verified {verified_raw!r} is not ISO")
            else:
                if verified > today:
                    problems.append(f"{where}: last_verified {verified} is in the future")

            source = entry.get("source")
            if not isinstance(source, str) or not source.startswith("https://"):
                problems.append(f"{where}: source must be an https URL")

            # Zero is not a rate a provider charges; it is a rate nobody filled in. An
            # entry that means "free" should be absent, which prices the call as unknown
            # rather than asserting a number.
            raw_rate = entry.get("per_use")
            try:
                if Decimal(str(raw_rate)) <= 0:
                    problems.append(f"{where}: per_use must be positive, not {raw_rate!r}")
            except (ArithmeticError, InvalidOperation):
                problems.append(f"{where}: per_use {raw_rate!r} is not a decimal string")
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
