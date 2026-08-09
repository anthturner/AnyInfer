"""Tool-specific coding-agent files remain thin shims over canonical instructions."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_agents_file_owns_every_workstream() -> None:
    canonical = _read("AGENTS.md")
    for phrase in (
        "Core SDK / inference engine",
        "Demo application",
        "One-shot CLI and operator commands",
        "OpenAI-compatible sidecar",
        "Shared configuration",
    ):
        assert phrase in canonical
    assert "DESIGN.md" in canonical


def test_tool_bootstraps_defer_to_agents_without_copying_policy() -> None:
    for relative in ("CLAUDE.md", ".github/copilot-instructions.md"):
        shim = _read(relative)
        assert "AGENTS.md" in shim
        assert "only authoritative" in shim
        assert len(shim.split()) < 100


def test_drift_entry_points_defer_to_one_procedure() -> None:
    canonical = _read("contracts/DRIFT-CHECK.md")
    assert "## Procedure" in canonical
    for classification in (
        "`OK`",
        "`DRIFT`",
        "`DEPRECATION`",
        "`NEW-CAPABILITY`",
        "`UNVERIFIABLE`",
    ):
        assert classification in canonical

    for relative in (
        ".agents/skills/check-provider-drift/SKILL.md",
        ".claude/skills/check-provider-drift/SKILL.md",
        ".github/prompts/check-provider-drift.prompt.md",
    ):
        shim = _read(relative)
        assert "contracts/DRIFT-CHECK.md" in shim
        assert re.search(r"only\s+authoritative", shim)
        assert len(shim.split()) < 130
