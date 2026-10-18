"""Controls for the generated C# run-manifest schema resource."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_csharp_manifest_schema.py"
SPEC = importlib.util.spec_from_file_location("generate_csharp_manifest_schema", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def test_embedded_manifest_schema_matches_the_public_python_helper() -> None:
    assert GENERATOR.OUTPUT.read_bytes() == GENERATOR.generated_bytes()
    assert GENERATOR.is_current()


def test_schema_drift_is_detected(tmp_path: Path) -> None:
    drifted = tmp_path / "manifest.schema.json"
    drifted.write_bytes(b"{}\n")

    assert not GENERATOR.is_current(drifted)
