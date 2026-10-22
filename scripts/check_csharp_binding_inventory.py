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


def _run(context: dict[str, Any], output: Path, directory: Path) -> None:
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
    if completed.returncode != 0:
        _fail(f"C# binding inventory exporter failed: {completed.stderr.strip()}")
    if completed.stdout:
        _fail("C# binding inventory exporter wrote unexpected standard output")


def _validate(value: Any) -> None:
    try:
        Draft202012Validator(
            json.loads(SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker()
        ).validate(value)
    except (SchemaError, ValidationError, json.JSONDecodeError) as error:
        _fail(f"binding inventory output is not schema-valid: {error}")
    if value.get("producer") != {"id": "csharp-provider-bindings", "version": "1"}:
        _fail("binding inventory producer is not the stable C# exporter identity")
    if value.get("bindings") != EXPECTED_BINDINGS:
        _fail("binding inventory does not match the declared public provider operations")


def main() -> int:
    """Run the local deterministic exporter shape check."""
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
        _validate(json.loads(first_bytes))
    state = "dirty" if context["evaluated_source"]["dirty"] else "clean"
    print(f"pass: nonqualifying C# binding inventory shape witness ({state} source)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
