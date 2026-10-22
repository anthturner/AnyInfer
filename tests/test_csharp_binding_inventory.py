"""External controls for the public C# provider-binding inventory exporter."""

from __future__ import annotations

import copy
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "src" / "csharp" / "AnyInfer.Maintenance" / "AnyInfer.Maintenance.csproj"
SCHEMA = ROOT / "maintenance" / "binding-inventory.schema.json"
SHA = "a" * 64
COMMIT = "b" * 40


def _context() -> dict[str, object]:
    return {
        "schema_version": 1,
        "implementation_id": "anyinfer-csharp",
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


def _run(context: dict[str, object], directory: Path) -> subprocess.CompletedProcess[str]:
    directory.mkdir(exist_ok=True)
    context_path = directory / "context.json"
    output_path = directory / "inventory.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    return subprocess.run(
        [
            "dotnet",
            "run",
            "--no-build",
            "--project",
            str(PROJECT),
            "--",
            "--context",
            str(context_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )


def test_csharp_exporter_is_schema_valid_deterministic_and_reads_actual_public_descriptors(
    tmp_path: Path,
) -> None:
    context = _context()
    original = copy.deepcopy(context)
    first = _run(context, tmp_path / "first")
    second = _run(context, tmp_path / "second")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout == ""
    assert context == original
    first_bytes = (tmp_path / "first" / "inventory.json").read_bytes()
    second_bytes = (tmp_path / "second" / "inventory.json").read_bytes()
    assert first_bytes == second_bytes
    assert b"\r\n" not in first_bytes
    inventory = json.loads(first_bytes)
    _validator().validate(inventory)
    assert inventory["producer"] == {"id": "csharp-provider-bindings", "version": "1"}
    assert inventory["trusted_pr_head"] == COMMIT
    assert inventory["bindings"] == [
        {
            "provider_id": "openai-compat",
            "operation": "generation",
            "contract_dependencies": ["contracts/openai-compat.md"],
        },
        {
            "provider_id": "tei",
            "operation": "embedding",
            "contract_dependencies": ["contracts/tei.md"],
        },
        {
            "provider_id": "tei",
            "operation": "rerank",
            "contract_dependencies": ["contracts/tei.md"],
        },
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.__setitem__("implementation_id", "wrong"),
        lambda value: value.__setitem__("bindings", [{"invented": True}]),
        lambda value: value["producer"].__setitem__("id", "wrong"),  # type: ignore[index]
        lambda value: value.__setitem__("unexpected", True),
    ],
)
def test_csharp_exporter_rejects_invalid_dispatcher_context(
    tmp_path: Path, mutate: Callable[[dict[str, object]], None]
) -> None:
    context = _context()
    mutate(context)

    completed = _run(context, tmp_path)

    assert completed.returncode != 0
    assert not (tmp_path / "inventory.json").exists()
