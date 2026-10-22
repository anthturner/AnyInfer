"""Focused controls for the Python provider-binding inventory exporter."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_python_provider_bindings.py"
SCHEMA = ROOT / "maintenance" / "binding-inventory.schema.json"
SHA = "a" * 64
COMMIT = "b" * 40


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("provider_binding_exporter", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _context() -> dict[str, object]:
    return {
        "schema_version": 1,
        "implementation_id": "anyinfer-python",
        "producer": {"id": "provider-change-dispatcher", "version": "1"},
        "workflow_run": {"id": "local-test", "attempt": 1},
        "trusted_pr_head": COMMIT,
        "evaluated_source": {
            "commit": COMMIT,
            "tree": COMMIT,
            "dirty": True,
            "input_fingerprint": SHA,
        },
        "registry_sha256": SHA,
        "input_sha256": SHA,
        "bindings": [],
    }


def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )


def test_inventory_uses_actual_builtins_and_preserves_context() -> None:
    exporter = _module()
    context = _context()
    raw = copy.deepcopy(context)

    inventory = exporter.build_inventory(context)

    _validator().validate(inventory)
    assert context == raw
    assert inventory["producer"] == {"id": "python-provider-bindings", "version": "1"}
    assert inventory["evaluated_source"]["dirty"] is True
    assert len(inventory["bindings"]) == 129
    preset = next(
        item
        for item in inventory["bindings"]
        if item["provider_id"] == "groq" and item["operation"] == "batch"
    )
    assert preset["contract_dependencies"] == [
        "contracts/openai-compat-presets.md",
        "contracts/openai-compat-presets.md#groq",
        "contracts/openai-compat.md",
    ]
    assert (
        next(
            item
            for item in inventory["bindings"]
            if item["provider_id"] == "lm-studio" and item["operation"] == "embedding"
        )["contract_dependencies"]
        == ["contracts/lm-studio.md", "contracts/openai-compat.md"]
    )
    inherited = {
        item["provider_id"]
        for item in inventory["bindings"]
        if "contracts/openai-compat.md" in item["contract_dependencies"]
    }
    assert inherited == {
        "azure-foundry",
        "deepseek",
        "llama-cpp",
        "lm-studio",
        "nebius",
        "openai-compat",
        "openrouter",
        "xai",
    } | {preset.id for preset in exporter.COMPAT_PRESETS}


def test_inventory_is_deterministic_and_has_no_plugin_or_factory_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = _module()

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("external plugin loading must not occur")

    monkeypatch.setattr("importlib.metadata.entry_points", fail)
    first = exporter.build_inventory(_context())
    second = exporter.build_inventory(_context())

    assert first == second
    assert first["bindings"] == sorted(
        first["bindings"], key=lambda item: (item["provider_id"], item["operation"])
    )


def test_missing_contract_mapping_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = _module()
    monkeypatch.delitem(exporter._DEDICATED_CONTRACTS, "openai")

    with pytest.raises(ValueError, match="registration does not match the checked contract mapping"):
        exporter.build_inventory(_context())


def test_cli_writes_deterministic_lf_json_without_stdout(tmp_path: Path) -> None:
    context = tmp_path / "context.json"
    output = tmp_path / "inventory.json"
    context.write_text(json.dumps(_context()), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--context", str(context), "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    content = output.read_bytes()
    assert completed.stdout == ""
    assert b"\r\n" not in content
    _validator().validate(json.loads(content))
