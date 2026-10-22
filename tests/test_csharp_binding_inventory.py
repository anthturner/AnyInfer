"""Keep native C# exporter execution outside the ordinary Python test suite."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_csharp_binding_inventory.py"


def test_csharp_binding_inventory_controls_are_owned_by_the_native_workspace_gate() -> None:
    """The post-build checker, not pytest, executes all exporter contexts."""
    source = CHECKER.read_text(encoding="utf-8")

    assert '["dotnet", "build", "AnyInfer.sln", "--no-restore", "-m:1"]' in source
    assert '"--no-build"' in source
    assert '"--no-restore"' in source
    assert "_require_invalid_context_controls(context, directory)" in source
    for control in ("implementation-id", "bindings", "producer", "unexpected-field"):
        assert control in source
