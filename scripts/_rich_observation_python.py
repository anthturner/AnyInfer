"""Shared fact-only helpers for the Python rich-generation observer.

The helpers deliberately retain paths and leaf digests from an actual serializer.  They
never redact a value before proving whether a planted privacy marker leaked.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ObservationPrivacyError(RuntimeError):
    """An actual default serialization contained a forbidden payload marker."""


def require_python_source(root: Path) -> Path:
    """Return the selected checkout's Python source, refusing an installed package path."""
    source = (root / "src" / "python").resolve()
    if not (source / "anyinfer" / "__init__.py").is_file():
        raise RuntimeError(f"missing selected-checkout Python source at {source}")
    return source


def canonical_data(value: Any) -> dict[str, str]:
    """Capture a recursive JSON value in stable text plus its exact UTF-8 digest."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return {"canonical_json": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}


def serialization_evidence(
    value: Any, *, scope: str, event_type: str | None = None
) -> dict[str, Any]:
    """Inspect actual parsed serialization and return every field path and string leaf.

    Privacy checks happen on strings *before* they become one-way digest evidence, so a
    prefix/suffix variant cannot hide a marker merely because its whole-leaf hash differs.
    """
    forbidden = ("answer-marker", "reasoning-marker", "raw-marker", "metadata-marker")
    paths: list[str] = []
    leaves: list[dict[str, Any]] = []

    def walk(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                child_path = f"{path}/{escaped}"
                paths.append(child_path)
                walk(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                child_path = f"{path}/{index}"
                paths.append(child_path)
                walk(child, child_path)
        elif isinstance(item, str):
            allowed_metadata = (
                scope == "telemetry"
                and event_type == "RequestStarted"
                and path == "/metadata/fixture"
            )
            leaks = [marker for marker in forbidden if marker in item]
            if leaks and not (allowed_metadata and leaks == ["metadata-marker"]):
                raise ObservationPrivacyError(f"{scope} serialized {leaks[0]!r} at {path}")
            raw = item.encode("utf-8")
            leaves.append(
                {"path": path, "utf8_length": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            )

    walk(value, "")
    return {
        "field_paths": sorted(paths),
        "string_leaves": sorted(leaves, key=lambda leaf: leaf["path"]),
    }
