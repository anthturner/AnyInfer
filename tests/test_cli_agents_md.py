"""``anyinfer agents-md`` — instructions that ship outward (AL.2).

The fragment is read in somebody else's repository, where nothing here can correct it. So
what is asserted is not "it renders" but the three ways it could be wrong there: naming a
provider or an extra that does not exist, leaking an internal identifier, and describing an
API version other than the one that generated it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer._agents_md import AGENTS_MD_FORMATS, installed_extras, render_agents_md
from anyinfer.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent


def _declared_extras() -> set[str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    return set(project.get("optional-dependencies", {}))


def _backticked(text: str) -> set[str]:
    return set(re.findall(r"`([^`]+)`", text))


# ---- what it may claim -------------------------------------------------------------


def test_it_names_only_registered_providers() -> None:
    """A provider id that does not resolve sends an agent to write a broken target."""
    fragment = render_agents_md()
    known = set(ai.default_registry.known_ids())
    # Anything shaped like a target — `provider:model` in backticks — must name a real one.
    for token in _backticked(fragment):
        match = re.fullmatch(r'target="([a-z0-9-]+):([^"]+)"', token)
        if match is None:
            continue
        assert match.group(1) in known, f"{token} names an unregistered provider"


def test_it_names_only_extras_that_exist() -> None:
    """`pip install anyinfer[anthropic]` is the exact mistake this fragment corrects."""
    declared = _declared_extras()
    assert installed_extras(), "the installed distribution declares no extras to check"
    for name in installed_extras():
        assert name in declared, f"{name!r} is advertised but is not a declared extra"

    fragment = render_agents_md()
    for match in re.finditer(r"anyinfer\[([a-z0-9,-]+)\]", fragment):
        for name in match.group(1).split(","):
            assert name in declared or "no such extra" in fragment, (
                f"the fragment suggests the non-existent extra {name!r}"
            )


def test_it_stamps_the_version_it_describes() -> None:
    """A reader has to be able to notice that a copied fragment has gone stale."""
    assert f"AnyInfer {ai.__version__}" in render_agents_md()
    assert "Regenerate it after upgrading" in render_agents_md()


def test_it_carries_no_internal_identifier() -> None:
    """This is the likeliest place for internal shorthand to reach a stranger's repo."""
    for style in AGENTS_MD_FORMATS:
        assert not re.search(r"\bADR-\d", render_agents_md(style=style))


def test_it_stays_short_enough_to_paste() -> None:
    """An instruction file nobody reads corrects nothing."""
    assert len(render_agents_md().splitlines()) < 90


@pytest.mark.parametrize("style", AGENTS_MD_FORMATS)
def test_every_format_carries_the_same_claims(style: str) -> None:
    """One description of one API; only the wrapper differs between the three tools."""
    fragment = render_agents_md(style=style)  # type: ignore[arg-type]
    for claim in (
        "### The shape of a call",
        "### What not to guess",
        "### Do not hand-roll these",
        'target="anthropic:claude-sonnet-4-5"',
    ):
        assert claim in fragment


# ---- tailored to a repository ---------------------------------------------------------


def test_config_output_names_the_configured_targets() -> None:
    config = ai.loads_config(
        '{"providers": [{"id": "work-azure", "adapter": "azure-foundry", '
        '"base_url": "https://work.invalid/v1"}, {"id": "ollama"}], '
        '"default_route": ["work-azure:gpt-4o", "ollama:qwen3:8b"]}'
    )
    fragment = render_agents_md(config=config)

    assert "`work-azure`" in fragment
    assert "the `azure-foundry` adapter" in fragment
    assert "`work-azure:gpt-4o`" in fragment
    assert "`ollama:qwen3:8b`" in fragment


def test_config_output_says_so_when_nothing_is_configured() -> None:
    fragment = render_agents_md(config=ai.AnyInferConfig())
    assert "anyinfer init" in fragment


# ---- the command -----------------------------------------------------------------------


def test_the_command_prints_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Installing instructions into somebody's repository uninvited is not this tool's job."""
    monkeypatch.chdir(tmp_path)

    assert main(["agents-md"]) == 0

    assert capsys.readouterr().out.startswith("## Using AnyInfer")
    assert list(tmp_path.iterdir()) == []


def test_the_command_accepts_a_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "anyinfer.json"
    config.write_text('{"providers": [{"id": "ollama"}]}', encoding="utf-8")

    assert main(["agents-md", "--config", str(config)]) == 0
    assert "This repository's configuration" in capsys.readouterr().out


def test_an_unknown_format_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["agents-md", "--format", "emacs"])
