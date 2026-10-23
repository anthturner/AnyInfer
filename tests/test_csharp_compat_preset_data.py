"""Controls for inert native compatibility-preset table generation."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_csharp_compat_presets.py"
INVENTORY = ROOT / "maintenance" / "provider-parity" / "python-builtins.json"
GENERATED = ROOT / "src" / "csharp" / "AnyInfer" / "Providers" / "CompatPresetTable.g.cs"


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("csharp_preset_generator", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_current_inventory_projects_only_sorted_compat_rows_and_deterministic_source(
    generator, tmp_path: Path
) -> None:
    document, digest = generator.load_inventory(INVENTORY)
    rows = generator.project(document)
    assert rows == sorted(rows, key=lambda row: row["id"])
    assert rows and all(row["family"] == "compat_preset" for row in rows)
    rendered = generator.render(document, digest)
    assert "CompatPresetTableSupport" not in rendered
    assert "new ProviderSetupSpec(" in rendered
    assert "new ModelCapabilities(" in rendered
    assert "internal const int GeneratorVersion = 2;" in rendered
    assert "ModelInventoryKind.Served" in rendered
    output = tmp_path / "CompatPresetTable.g.cs"
    output.write_bytes(rendered.encode("utf-8"))
    assert output.read_bytes() == generator.render(document, digest).encode("utf-8")


def test_checked_table_is_exact_fresh_rendering(generator) -> None:
    """The checked file is an output, never a test-created fixture."""
    if not GENERATED.exists():
        pytest.skip("coordinator has not emitted the root-owned generated table")
    document, digest = generator.load_inventory(INVENTORY)
    assert GENERATED.read_bytes() == generator.render(document, digest).encode("utf-8")


@pytest.mark.parametrize("mutated", [b"\xef\xbb\xbf", b"\r\n", b" "])
def test_byte_admission_refuses_noncanonical_input_without_rewriting(
    generator, tmp_path: Path, mutated: bytes
) -> None:
    path = tmp_path / "inventory.json"
    raw = INVENTORY.read_bytes()
    path.write_bytes(mutated + raw if mutated != b"\r\n" else raw.replace(b"\n", mutated))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        generator.load_inventory(path)
    assert path.read_bytes() == before


def test_check_refuses_stale_rendering_without_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "table.g.cs"
    path.write_text("stale\n", encoding="utf-8")
    before = path.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert path.read_bytes() == before


def test_load_rejects_valid_but_stale_inventory_without_rewriting(
    generator, tmp_path: Path
) -> None:
    document, _ = generator.load_inventory(INVENTORY)
    stale = copy.deepcopy(document)
    stale["providers"][0]["descriptor"]["display_name"] += " stale"
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(stale, separators=(",", ":")), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="stale or noncanonical"):
        generator.load_inventory(path)
    assert path.read_bytes() == before


def test_projection_rejects_closed_source_fact_and_factory_drift(generator) -> None:
    document, _ = generator.load_inventory(INVENTORY)
    row = next(row for row in document["providers"] if row["family"] == "compat_preset")

    unknown_field = copy.deepcopy(document)
    next(item for item in unknown_field["providers"] if item["id"] == row["id"])["descriptor"][
        "unknown"
    ] = None
    with pytest.raises(ValueError, match="unknown or missing"):
        generator.project(unknown_field)

    operations = copy.deepcopy(document)
    next(item for item in operations["providers"] if item["id"] == row["id"])["descriptor"][
        "operations"
    ] = ["embedding"]
    with pytest.raises(ValueError, match="source operations"):
        generator.project(operations)

    factory = copy.deepcopy(document)
    next(item for item in factory["providers"] if item["id"] == row["id"])["descriptor"][
        "factory"
    ]["keywords"]["preset"]["id"] = "foreign"
    with pytest.raises(ValueError, match="source factory"):
        generator.project(factory)

    inventory = copy.deepcopy(document)
    next(item for item in inventory["providers"] if item["id"] == row["id"])["descriptor"][
        "model_inventory"
    ] = "unknown"
    with pytest.raises(ValueError, match="model inventory"):
        generator.project(inventory)

    for non_served in ("available", "installed"):
        served_only = copy.deepcopy(document)
        next(item for item in served_only["providers"] if item["id"] == row["id"])["descriptor"][
            "model_inventory"
        ] = non_served
        with pytest.raises(ValueError, match="compat source inventory must remain served"):
            generator.project(served_only)


def test_render_rejects_unknown_reasoning_feature_provenance_and_non_neutral_capability(
    generator,
) -> None:
    document, digest = generator.load_inventory(INVENTORY)
    row = next(row for row in document["providers"] if row["family"] == "compat_preset")

    reasoning = copy.deepcopy(document)
    next(item for item in reasoning["providers"] if item["id"] == row["id"])["preset"][
        "reasoning"
    ] = "not-a-style"
    with pytest.raises(ValueError, match="reasoning"):
        generator.render(reasoning, digest)

    feature = copy.deepcopy(document)
    next(item for item in feature["providers"] if item["id"] == row["id"])["descriptor"][
        "default_capabilities"
    ]["features"]["value"] = ["NOT_A_FEATURE"]
    with pytest.raises(ValueError, match="feature"):
        generator.render(feature, digest)

    provenance = copy.deepcopy(document)
    next(item for item in provenance["providers"] if item["id"] == row["id"])["descriptor"][
        "default_capabilities"
    ]["features"]["provenance"] = "not-a-source"
    with pytest.raises(ValueError, match="provenance"):
        generator.render(provenance, digest)

    capability = copy.deepcopy(document)
    next(item for item in capability["providers"] if item["id"] == row["id"])["descriptor"][
        "default_capabilities"
    ]["pricing"] = {}
    with pytest.raises(ValueError, match="non-neutral"):
        generator.render(capability, digest)


def test_render_preserves_order_nulls_and_escapes_hostile_literals(generator) -> None:
    document, digest = generator.load_inventory(INVENTORY)
    changed = copy.deepcopy(document)
    row = next(row for row in changed["providers"] if row["family"] == "compat_preset")
    row["descriptor"]["aliases"] = ["zeta", "alpha"]
    row["descriptor"]["default_base_url"] = None
    row["descriptor"]["display_name"] = 'line\n"quote"\\slash\u0085\u2028\u2029\U0001f600'
    rendered = generator.render(changed, digest)
    assert 'new string[] { "zeta", "alpha" }' in rendered
    assert 'line\\n\\"quote\\"\\\\slash\\u0085\\u2028\\u2029\\ud83d\\ude00' in rendered
    assert ", null, " in rendered


def test_csharp_literal_encoder_uses_safe_ascii_escapes(generator) -> None:
    """C# regular literals must not receive raw Unicode line separators."""
    rendered = generator._cs("\u0085\u2028\u2029\U0001f600")
    assert rendered == '"\\u0085\\u2028\\u2029\\ud83d\\ude00"'
    assert all(character not in rendered for character in "\u0085\u2028\u2029\U0001f600")
