"""Deterministic pricing drift check against OpenRouter's public model listing (D27).

The cheap, machine-readable half of the weekly pricing refresh: every bundled entry that
declares an ``openrouter_id`` is compared against OpenRouter's current per-token rates.
OpenRouter passes through first-party list prices for the majors, so a mismatch is a
strong (not infallible) signal that the provider moved its prices — the LLM verification
pass in the workflow confirms against the provider's own page before anything changes.

Stdlib only, so the check runs before any dependency is installed.

Exit codes: 0 no drift, 1 drift detected, 2 check could not run.
Writes ``drift=true|false`` to ``$GITHUB_OUTPUT`` when running in Actions.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICING_PATH = REPO_ROOT / "src" / "anyinfer" / "capabilities" / "pricing.json"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def fetch_openrouter_rates() -> dict[str, tuple[Decimal, Decimal]]:
    """Fetch OpenRouter's listing as ``id -> (input_per_1m, output_per_1m)``."""
    request = urllib.request.Request(
        OPENROUTER_MODELS_URL, headers={"User-Agent": "anyinfer-pricing-drift-check"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        listing = json.load(response)
    rates: dict[str, tuple[Decimal, Decimal]] = {}
    for model in listing.get("data", []):
        pricing = model.get("pricing") or {}
        try:
            rates[model["id"]] = (
                Decimal(pricing["prompt"]) * 1_000_000,
                Decimal(pricing["completion"]) * 1_000_000,
            )
        except (KeyError, ArithmeticError):
            continue
    return rates


def find_drift() -> list[str]:
    """Compare every cross-checkable bundled entry; return human-readable mismatches."""
    bundled = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    rates = fetch_openrouter_rates()

    drift: list[str] = []
    for provider, entries in bundled["providers"].items():
        for entry in entries:
            openrouter_id = entry.get("openrouter_id")
            if not openrouter_id:
                continue
            if openrouter_id not in rates:
                drift.append(f"{provider}:{entry['model']}: {openrouter_id} vanished upstream")
                continue
            live_input, live_output = rates[openrouter_id]
            ours_input = Decimal(entry["input_per_1m"])
            ours_output = Decimal(entry["output_per_1m"])
            if live_input != ours_input or live_output != ours_output:
                drift.append(
                    f"{provider}:{entry['model']}: bundled {ours_input}/{ours_output} "
                    f"vs live {live_input.normalize()}/{live_output.normalize()} per 1M"
                )
    return drift


def _write_github_output(drifted: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:  # noqa: PTH123
            handle.write(f"drift={'true' if drifted else 'false'}\n")


def main() -> int:
    """CLI entry point."""
    try:
        drift = find_drift()
    except Exception as error:  # noqa: BLE001 — an unreachable API is a report, not a crash
        print(f"CHECK FAILED: {error}", file=sys.stderr)
        _write_github_output(False)
        return 2
    _write_github_output(bool(drift))
    if drift:
        print("Pricing drift detected:")
        for line in drift:
            print(f"  {line}")
        return 1
    print("No pricing drift against OpenRouter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
