"""Check the C# provider-binding exporter as a nonqualifying shape witness.

This local workspace gate only proves the deterministic public descriptor projection.
It is not provider-change evidence: a dirty checkout is recorded as dirty and the
schema fingerprint is deliberately not a trusted change declaration.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "src" / "csharp" / "AnyInfer.Maintenance" / "AnyInfer.Maintenance.csproj"
SCHEMA = ROOT / "maintenance" / "binding-inventory.schema.json"
IMPLEMENTATIONS = ROOT / "maintenance" / "implementations.json"
EXPECTED_BINDINGS = [
    {
        "provider_id": "jina",
        "operation": "embedding",
        "contract_dependencies": ["contracts/jina.md"],
    },
    {
        "provider_id": "jina",
        "operation": "rerank",
        "contract_dependencies": ["contracts/jina.md"],
    },
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
    {
        "provider_id": "voyage",
        "operation": "embedding",
        "contract_dependencies": ["contracts/voyage.md"],
    },
    {
        "provider_id": "voyage",
        "operation": "rerank",
        "contract_dependencies": ["contracts/voyage.md"],
    },
]


def _fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        _fail(f"could not read source metadata: git {' '.join(args)}")
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_solution() -> None:
    completed = subprocess.run(
        ["dotnet", "build", "AnyInfer.sln", "--no-restore", "-m:1"],
        cwd=ROOT / "src" / "csharp",
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        _fail(
            "C# proof solution build failed:\n"
            f"stdout:\n{completed.stdout.strip()}\n"
            f"stderr:\n{completed.stderr.strip()}"
        )


def _context() -> dict[str, Any]:
    commit = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    dirty = bool(_git("status", "--porcelain"))
    schema_sha256 = _sha256(SCHEMA)
    return {
        "schema_version": 1,
        "implementation_id": "anyinfer-csharp",
        "producer": {"id": "provider-change-dispatcher", "version": "1"},
        "workflow_run": {"id": "local-csharp-binding-shape", "attempt": 1},
        "trusted_pr_head": commit,
        "evaluated_source": {
            "commit": commit,
            "tree": tree,
            "dirty": dirty,
            "input_fingerprint": schema_sha256,
        },
        "registry_sha256": _sha256(IMPLEMENTATIONS),
        "input_sha256": schema_sha256,
        "bindings": [],
    }


def _invoke(
    context: dict[str, Any], output: Path, directory: Path
) -> subprocess.CompletedProcess[str]:
    context_path = directory / f"{output.stem}.context.json"
    context_path.write_text(
        json.dumps(context, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8"
    )
    completed = subprocess.run(
        [
            "dotnet",
            "run",
            "--no-build",
            "--no-restore",
            "--project",
            str(PROJECT),
            "--",
            "--context",
            str(context_path),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed


def _run(context: dict[str, Any], output: Path, directory: Path) -> None:
    completed = _invoke(context, output, directory)
    if completed.returncode != 0:
        _fail(f"C# binding inventory exporter failed: {completed.stderr.strip()}")
    if completed.stdout:
        _fail("C# binding inventory exporter wrote unexpected standard output")


def _validate(value: Any, context: dict[str, Any]) -> None:
    try:
        Draft202012Validator(
            json.loads(SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker()
        ).validate(value)
    except (SchemaError, ValidationError, json.JSONDecodeError) as error:
        _fail(f"binding inventory output is not schema-valid: {error}")
    if value.get("producer") != {"id": "csharp-provider-bindings", "version": "1"}:
        _fail("binding inventory producer is not the stable C# exporter identity")
    for field in (
        "schema_version",
        "implementation_id",
        "workflow_run",
        "trusted_pr_head",
        "evaluated_source",
        "registry_sha256",
        "input_sha256",
    ):
        if value.get(field) != context[field]:
            _fail(f"binding inventory did not preserve dispatcher provenance field {field}")
    if value.get("bindings") != EXPECTED_BINDINGS:
        _fail("binding inventory does not match the declared public provider operations")


def _require_invalid_context_controls(context: dict[str, Any], directory: Path) -> None:
    controls = (
        (
            "implementation-id",
            lambda value: value.__setitem__("implementation_id", "wrong"),
        ),
        ("bindings", lambda value: value.__setitem__("bindings", [{"invented": True}])),
        ("producer", lambda value: value["producer"].__setitem__("id", "wrong")),
        ("unexpected-field", lambda value: value.__setitem__("unexpected", True)),
    )
    for name, mutate in controls:
        invalid = json.loads(json.dumps(context))
        mutate(invalid)
        output = directory / f"invalid-{name}.json"
        completed = _invoke(invalid, output, directory)
        if completed.returncode == 0:
            _fail(f"C# binding inventory exporter accepted invalid {name} context")
        if output.exists():
            _fail(f"C# binding inventory exporter wrote output for invalid {name} context")


def main() -> int:
    """Run the local deterministic exporter shape check."""
    _build_solution()
    context = _context()
    temporary_root = ROOT / ".tmp-tests"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="csharp-binding-inventory-", dir=temporary_root
    ) as raw:
        directory = Path(raw)
        first = directory / "first.json"
        second = directory / "second.json"
        _run(context, first, directory)
        _run(context, second, directory)
        first_bytes = first.read_bytes()
        second_bytes = second.read_bytes()
        if first_bytes != second_bytes:
            _fail("binding inventory exporter output is not deterministic")
        if b"\r\n" in first_bytes or not first_bytes.endswith(b"\n"):
            _fail("binding inventory exporter output is not LF-terminated UTF-8 JSON")
        _validate(json.loads(first_bytes), context)
        _require_invalid_context_controls(context, directory)
    state = "dirty" if context["evaluated_source"]["dirty"] else "clean"
    print(f"pass: nonqualifying C# binding inventory shape witness ({state} source)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
