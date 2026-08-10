"""Golden-file assertions for run manifests.

A model's prose is untestable — it changes with a temperature, a weight update, or a
provider's silent model swap, so an application that asserts on it either pins nothing or
fails constantly. Its *inference behaviour* is a different thing entirely: which target
answered, which structured-output mechanism the ladder chose, how many repairs were spent,
what got reduced, which parameters the target refused. All of that is deterministic, all of
it is in the manifest, and all of it is exactly what breaks when a config change goes wrong.

So a manifest makes a good golden file, provided the volatile parts come out first — a
golden that fails on every run because a duration moved by a millisecond gets deleted by
the second week. `normalize()` is what removes them, and it is part of the contract rather
than an afterthought.

```python
def test_falls_back_to_the_cheap_model(anyinfer_client, anyinfer_golden_manifest):
    result = build_app(anyinfer_client).answer("hi")
    anyinfer_golden_manifest(result.manifest, "fallback")
```

Run the suite with ``--update-manifests`` to rewrite the goldens after a deliberate change.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..manifest import RunManifest

__all__ = ["VOLATILE_FIELDS", "assert_manifest_matches", "normalize"]

VOLATILE_FIELDS: Mapping[str, tuple[str, ...]] = {
    "": ("request_id", "anyinfer_version"),
    "attempts": (
        "first_token_ms",
        "total_ms",
        "queued_ms",
        "retry_delay_s",
        "paced_s",
    ),
    "timing": ("first_token_ms", "total_ms", "output_tokens_per_s", "phases"),
}
"""Which fields `normalize()` drops, keyed by the facet they live on.

Everything here is a wall-clock or a per-process identifier: true of the run, and false of
the next identical one. Nothing about a *decision* is in this list, because a decision that
changed is precisely what a golden manifest exists to catch.
"""


def normalize(manifest: RunManifest | Mapping[str, Any]) -> dict[str, Any]:
    """Strip the fields that differ between two identical runs.

    Args:
        manifest: A `RunManifest` or its `RunManifest.to_dict` form.

    Returns:
        JSON-safe data with every volatile field removed, ready to compare or write.
    """
    data = dict(manifest.to_dict() if isinstance(manifest, RunManifest) else manifest)

    for name in VOLATILE_FIELDS[""]:
        data.pop(name, None)

    attempts = data.get("attempts")
    if isinstance(attempts, list):
        data["attempts"] = [
            {k: v for k, v in attempt.items() if k not in VOLATILE_FIELDS["attempts"]}
            for attempt in attempts
            if isinstance(attempt, Mapping)
        ]

    timing = data.get("timing")
    if isinstance(timing, Mapping):
        data["timing"] = {
            k: v for k, v in timing.items() if k not in VOLATILE_FIELDS["timing"]
        }
    return data


def assert_manifest_matches(
    manifest: RunManifest | Mapping[str, Any],
    path: Path | str,
    *,
    update: bool = False,
) -> None:
    """Assert a manifest matches its golden file, normalizing volatility away first.

    A missing golden is written rather than failed: the first run of a new test records
    what the behaviour *is*, and the diff in review is where it gets agreed to. A golden
    that exists and disagrees is a failure, reported as a field-by-field difference rather
    than two walls of JSON.

    Args:
        manifest: The manifest the run produced.
        path: Where the golden lives. Parent directories are created as needed.
        update: Rewrite the golden instead of comparing. Wired to the pytest plugin's
            ``--update-manifests`` flag.

    Raises:
        AssertionError: If the golden exists and the run no longer matches it.
    """
    target = Path(path)
    actual = normalize(manifest)

    if update or not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", "utf-8")
        return

    expected = json.loads(target.read_text("utf-8"))
    if expected == actual:
        return
    differences = "\n".join(_differences(expected, actual))
    raise AssertionError(
        f"the run manifest no longer matches {target}:\n{differences}\n"
        "re-run with --update-manifests if this change was intended"
    )


def _differences(expected: Any, actual: Any, prefix: str = "") -> list[str]:
    """Describe how two normalized manifests differ, one line per field."""
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        lines: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            where = f"{prefix}.{key}" if prefix else key
            if key not in expected:
                lines.append(f"  + {where} = {json.dumps(actual[key])}")
            elif key not in actual:
                lines.append(f"  - {where} = {json.dumps(expected[key])}")
            else:
                lines.extend(_differences(expected[key], actual[key], where))
        return lines
    if isinstance(expected, list) and isinstance(actual, list):
        lines = []
        for index in range(max(len(expected), len(actual))):
            where = f"{prefix}[{index}]"
            if index >= len(expected):
                lines.append(f"  + {where} = {json.dumps(actual[index])}")
            elif index >= len(actual):
                lines.append(f"  - {where} = {json.dumps(expected[index])}")
            else:
                lines.extend(_differences(expected[index], actual[index], where))
        return lines
    if expected != actual:
        return [f"  ~ {prefix}: {json.dumps(expected)} -> {json.dumps(actual)}"]
    return []
