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
    for procedure in (
        "contracts/NEW-PROVIDER.md",
        "contracts/DRIFT-CHECK.md",
        "docs/agents/INTEGRATION.md",
    ):
        assert procedure in canonical, f"AGENTS.md never names {procedure}"


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


def test_new_provider_entry_points_defer_to_one_procedure() -> None:
    """Adding a provider is one procedure with three shims, like the drift check."""
    canonical = _read("contracts/NEW-PROVIDER.md")
    for step in (
        "## Step 0",
        "## Step 1",
        "## Step 2",
        "## Step 3",
        "## Step 4",
        "## Step 5",
        "## Step 6",
        "## Step 7",
    ):
        assert step in canonical
    assert "What \"done\" means" in canonical

    for relative in (
        ".agents/skills/add-provider/SKILL.md",
        ".claude/skills/add-provider/SKILL.md",
        ".github/prompts/add-provider.prompt.md",
    ):
        shim = _read(relative)
        assert "contracts/NEW-PROVIDER.md" in shim
        assert re.search(r"only\s+authoritative", shim)
        assert len(shim.split()) < 130


def test_the_new_provider_procedure_covers_every_registration_gate() -> None:
    """Each gate below fails a build when missed, so the procedure must name all of them.

    An agent that follows the procedure and still trips one of these has been handed an
    incomplete recipe -- which is exactly the failure this file exists to prevent.
    """
    canonical = _read("contracts/NEW-PROVIDER.md")
    for gate in (
        "_BUILTIN_MODULES",
        "scripts/generate_provider_index.py",
        "ADAPTER_PAGES",
        "ADAPTER_SUMMARIES",
        "mkdocs.yml",
        "lint-imports",
        "workspace.py",
        "python scripts/generate_provider_index.py",
        "python workspace.py matrix",
    ):
        assert gate in canonical, f"the procedure never mentions {gate}"


def test_every_canonical_procedure_links_only_to_files_that_exist() -> None:
    """A procedure that points at a moved file sends the agent to invent the step."""
    for relative in (
        "contracts/NEW-PROVIDER.md",
        "contracts/DRIFT-CHECK.md",
        "docs/agents/INTEGRATION.md",
    ):
        source = ROOT / relative
        for link in re.findall(r"\]\((?!https?:)([^)#]+)", _read(relative)):
            assert (source.parent / link).resolve().is_file(), (
                f"{relative} links to {link}, which does not exist"
            )


def test_agents_file_governs_outward_facing_instructions() -> None:
    """Instruction text this project emits is under the same authority as its own."""
    canonical = _read("AGENTS.md")
    assert "docs/agents/INTEGRATION.md" in canonical
    assert "anyinfer agents-md" in canonical
    assert "llms.txt" in canonical


def test_integration_entry_points_defer_to_one_procedure() -> None:
    """The same shape as the drift-check trio: one procedure, three thin shims."""
    canonical = _read("docs/agents/INTEGRATION.md")
    for step in (
        "## Step 0",
        "## Step 1",
        "## Step 2",
        "## Step 3",
        "## Step 4",
        "## Step 5",
        "## Step 6",
    ):
        assert step in canonical

    for relative in (
        ".agents/skills/anyinfer-integration/SKILL.md",
        ".claude/skills/anyinfer-integration/SKILL.md",
        ".github/prompts/anyinfer-integration.prompt.md",
    ):
        shim = _read(relative)
        assert "docs/agents/INTEGRATION.md" in shim
        assert re.search(r"only\s+authoritative", shim)
        assert len(shim.split()) < 130


def test_a_skill_shim_points_at_a_file_that_exists() -> None:
    """A relative link into a moved file turns a skill into a silent no-op."""
    for relative in (
        ".agents/skills/anyinfer-integration/SKILL.md",
        ".claude/skills/anyinfer-integration/SKILL.md",
        ".agents/skills/check-provider-drift/SKILL.md",
        ".claude/skills/check-provider-drift/SKILL.md",
        ".agents/skills/add-provider/SKILL.md",
        ".claude/skills/add-provider/SKILL.md",
    ):
        shim_path = ROOT / relative
        for link in re.findall(r"\]\((\.\./[^)]+)\)", _read(relative)):
            assert (shim_path.parent / link).resolve().is_file(), (
                f"{relative} links to {link}, which does not exist"
            )


def test_no_user_facing_text_carries_an_adr_identifier() -> None:
    """`ADR-NNN` is internal shorthand; outside this repo it explains nothing.

    One sweep over every outward surface — the published docs, the README, the emitted
    instruction fragment, and the skill shims, because the rule is stated in AGENTS.md
    and was, until now, enforced by nobody.
    """
    from anyinfer._agents_md import AGENTS_MD_FORMATS, render_agents_md

    offenders: list[str] = []
    for path in sorted((ROOT / "docs").rglob("*.md")):
        if re.search(r"\bADR-\d", path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    for relative in (
        "README.md",
        ".agents/skills/anyinfer-integration/SKILL.md",
        ".claude/skills/anyinfer-integration/SKILL.md",
        ".github/prompts/anyinfer-integration.prompt.md",
        ".agents/skills/add-provider/SKILL.md",
        ".claude/skills/add-provider/SKILL.md",
        ".github/prompts/add-provider.prompt.md",
    ):
        if re.search(r"\bADR-\d", _read(relative)):
            offenders.append(relative)
    for style in AGENTS_MD_FORMATS:
        if re.search(r"\bADR-\d", render_agents_md(style=style)):
            offenders.append(f"anyinfer agents-md --format {style}")

    assert offenders == [], (
        "state the rule in plain words instead; ADR numbers belong to DESIGN.md, "
        "AGENTS.md, and non-rendering code comments"
    )


def test_public_docstrings_carry_no_adr_identifier() -> None:
    """Rendered onto the published site by mkdocstrings, so these are user-facing too."""
    import ast

    offenders: list[str] = []
    for path in sorted((ROOT / "src" / "anyinfer").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                continue
            doc = ast.get_docstring(node)
            if doc and re.search(r"\bADR-\d", doc):
                name = getattr(node, "name", "<module>")
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    assert offenders == []
