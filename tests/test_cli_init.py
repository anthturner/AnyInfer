"""``anyinfer init`` — the first command a new user runs (IN.4, IN.5).

Discovery itself is covered in `test_local_discovery`; what is proved here is the command
built on top of it: which evidence becomes configuration, what the generated file may and
may not contain, and that an existing file is never replaced by accident.

Every test substitutes discovery, so nothing depends on what happens to be listening or
exported on the machine running the suite.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer import local as local_subsystem
from anyinfer._starter import (
    DEFAULT_STARTER_CONFIG,
    DEFAULT_STARTER_TARGET,
    STARTER_TEMPLATE,
    render_starter,
)
from anyinfer.cli import main
from anyinfer.config import load_config
from anyinfer.local.discovery import DiscoveredProvider

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _in_a_temporary_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`init` writes into the working directory, so give every test its own."""
    monkeypatch.chdir(tmp_path)


def _fake_discovery(
    monkeypatch: pytest.MonkeyPatch, found: Sequence[DiscoveredProvider]
) -> None:
    """Pin what discovery reports, and prove nothing is contacted."""

    async def discover(*_args: object, **_kwargs: object) -> tuple[DiscoveredProvider, ...]:
        return tuple(found)

    monkeypatch.setattr(local_subsystem, "discover", discover)
    monkeypatch.setattr(local_subsystem, "endpoint_candidates", lambda _registry: ())


def _running_engine() -> DiscoveredProvider:
    return DiscoveredProvider(
        provider_id="ollama",
        base_url="http://127.0.0.1:11434",
        evidence="endpoint",
        detail="2 models",
        models=("qwen3:8b", "llama3.1:8b"),
    )


def _environment_key() -> DiscoveredProvider:
    return DiscoveredProvider(
        provider_id="anthropic",
        base_url="https://api.anthropic.com",
        evidence="environment",
        detail="ANTHROPIC_API_KEY set",
        credential_key="api_key",
        credential_ref="env://ANTHROPIC_API_KEY",
    )


# ---- what gets written ---------------------------------------------------------------


def test_nothing_found_still_writes_a_valid_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A machine with nothing on it gets a file it can grow into, not an error."""
    _fake_discovery(monkeypatch, [])

    assert main(["init", "--yes", "--no-probe"]) == 0

    config = load_config("anyinfer.json")
    assert config.providers == ()
    assert config.route is None
    assert Path("starter.py").exists()
    assert "nothing to configure yet" in capsys.readouterr().out


def test_a_running_engine_becomes_a_configured_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_discovery(monkeypatch, [_running_engine()])

    assert main(["init", "--yes"]) == 0

    config = load_config("anyinfer.json")
    assert [s.instance_id for s in config.providers] == ["ollama"]
    assert config.providers[0].base_url == "http://127.0.0.1:11434"
    assert config.route is not None

    out = capsys.readouterr().out
    assert "found      ollama at http://127.0.0.1:11434 (2 models)" in out


def test_a_route_never_names_a_model_the_engine_does_not_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A catalog alias is kept only when it does not contradict what was observed.

    The alias maps to some model on this engine; discovery saw the engine's real list. If
    the alias's model is not in it, the alias is a configuration that fails on its first
    request, and a target that *was* observed is the honest answer instead.
    """
    engine = DiscoveredProvider(
        provider_id="ollama",
        base_url="http://127.0.0.1:11434",
        evidence="endpoint",
        detail="1 model",
        models=("some-model-no-alias-names",),
    )
    _fake_discovery(monkeypatch, [engine])

    assert main(["init", "--yes"]) == 0

    config = load_config("anyinfer.json")
    assert config.route is not None
    assert config.route.targets == ("ollama:some-model-no-alias-names",)


def test_a_credential_is_written_as_a_reference_never_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one unacceptable failure: a secret in a file that gets committed (R-IN1)."""
    from anyinfer.redaction import register_secret

    secret = "sk-ant-not-in-the-file"
    register_secret(secret)
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    _fake_discovery(monkeypatch, [_environment_key()])

    assert main(["init", "--yes", "--no-probe"]) == 0

    written = Path("anyinfer.json").read_text(encoding="utf-8")
    assert "env://ANTHROPIC_API_KEY" in written
    assert secret not in written
    assert secret not in Path("starter.py").read_text(encoding="utf-8")

    config = load_config("anyinfer.json")
    assert config.providers[0].api_key == "env://ANTHROPIC_API_KEY"


def test_a_credential_outside_the_well_known_fields_lands_in_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second credential is an ``options`` entry, which is where the format puts it."""
    _fake_discovery(
        monkeypatch,
        [
            DiscoveredProvider(
                provider_id="anthropic",
                base_url=None,
                evidence="environment",
                detail="ANTHROPIC_OAUTH_TOKEN set",
                credential_key="oauth_token",
                credential_ref="env://ANTHROPIC_OAUTH_TOKEN",
            )
        ],
    )

    assert main(["init", "--yes", "--no-probe"]) == 0
    config = load_config("anyinfer.json")
    assert config.providers[0].options["oauth_token"] == "env://ANTHROPIC_OAUTH_TOKEN"


def test_a_provider_needing_an_endpoint_becomes_a_note_not_a_broken_entry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Knowing a key exists says nothing about which tenant it belongs to."""
    _fake_discovery(
        monkeypatch,
        [
            DiscoveredProvider(
                provider_id="azure-foundry",
                base_url=None,
                evidence="environment",
                detail="AZURE_OPENAI_API_KEY set",
                credential_key="api_key",
                credential_ref="env://AZURE_OPENAI_API_KEY",
            )
        ],
    )

    assert main(["init", "--yes", "--no-probe"]) == 0

    assert load_config("anyinfer.json").providers == ()
    out = capsys.readouterr().out
    assert "azure-foundry" in out
    assert "base URL" in out


# ---- refusing to clobber ---------------------------------------------------------------


def test_an_existing_configuration_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_discovery(monkeypatch, [_running_engine()])
    Path("anyinfer.json").write_text('{"format_version": 1}', encoding="utf-8")

    assert main(["init", "--yes"]) == 1

    assert Path("anyinfer.json").read_text(encoding="utf-8") == '{"format_version": 1}'
    assert not Path("starter.py").exists(), "a refusal writes nothing at all"
    assert "--force" in capsys.readouterr().err


def test_force_replaces_both_files(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_discovery(monkeypatch, [_running_engine()])
    Path("anyinfer.json").write_text('{"format_version": 1}', encoding="utf-8")
    Path("starter.py").write_text("# stale\n", encoding="utf-8")

    assert main(["init", "--yes", "--force"]) == 0
    assert load_config("anyinfer.json").providers
    assert Path("starter.py").read_text(encoding="utf-8") != "# stale\n"


def test_output_writes_the_pair_somewhere_else(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_discovery(monkeypatch, [_running_engine()])
    (Path("conf")).mkdir()

    assert main(["init", "--yes", "--output", "conf/inference.json"]) == 0

    assert load_config("conf/inference.json").providers
    starter = Path("conf/starter.py").read_text(encoding="utf-8")
    assert 'CONFIG_PATH = "conf/inference.json"' in starter


# ---- probing restraint -----------------------------------------------------------------


def test_no_probe_contacts_nothing_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contacted: list[object] = []

    async def discover(*_args: object, **kwargs: object) -> tuple[DiscoveredProvider, ...]:
        contacted.append(kwargs.get("probe"))
        return ()

    monkeypatch.setattr(local_subsystem, "discover", discover)

    assert main(["init", "--yes", "--no-probe"]) == 0
    assert contacted == [False]
    assert "probed     nothing (--no-probe)" in capsys.readouterr().out


def test_the_summary_names_every_endpoint_it_contacted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R-IN2: touching loopback ports uninvited must not have to be taken on trust."""
    _fake_discovery(monkeypatch, [])
    monkeypatch.setattr(
        local_subsystem,
        "endpoint_candidates",
        lambda _registry: (("http://127.0.0.1:11434", "ollama"),),
    )

    assert main(["init", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:11434" in out


# ---- machine-readable output -------------------------------------------------------


def test_json_output_reports_the_same_decisions(monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    _fake_discovery(monkeypatch, [_running_engine(), _environment_key()])

    assert main(["init", "--yes", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [d["provider_id"] for d in payload["discovered"]] == ["ollama", "anthropic"]
    assert payload["config_path"] == "anyinfer.json"
    assert payload["route"] == [payload["target"]]
    assert Path("anyinfer.json").exists()


# ---- the generated starter -------------------------------------------------------------


def test_the_checked_in_example_is_the_template_verbatim() -> None:
    """One source for the starter, so the shipped and generated copies cannot diverge."""
    example = (REPO_ROOT / "docs" / "examples" / "starter.py").read_text(encoding="utf-8")
    assert example == STARTER_TEMPLATE
    assert (
        render_starter(target=DEFAULT_STARTER_TARGET, config_path=DEFAULT_STARTER_CONFIG)
        == example
    )


def test_generation_differs_from_the_example_only_in_two_lines() -> None:
    rendered = render_starter(target="ollama:qwen3:8b", config_path="conf/x.json")
    differences = [
        (a, b)
        for a, b in zip(STARTER_TEMPLATE.splitlines(), rendered.splitlines(), strict=True)
        if a != b
    ]
    assert differences == [
        ('CONFIG_PATH = "anyinfer.json"', 'CONFIG_PATH = "conf/x.json"'),
        ('TARGET = "medium"', 'TARGET = "ollama:qwen3:8b"'),
    ]


@pytest.mark.parametrize("bad", ['say "hi"', "line\nbreak", ""])
def test_generation_refuses_a_value_that_would_not_parse(bad: str) -> None:
    with pytest.raises(ValueError, match="quotes"):
        render_starter(target=bad, config_path="anyinfer.json")


def test_the_generated_starter_runs_against_a_scripted_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The example is executed, not merely parsed — its call path is exercised here.

    `run()` is the half of the starter that survives into a real application: it takes a
    client and a target and knows nothing about where either came from, which is exactly
    what lets it be proved offline.
    """
    _fake_discovery(monkeypatch, [_running_engine()])
    assert main(["init", "--yes"]) == 0

    import importlib.util

    spec = importlib.util.spec_from_file_location("generated_starter", "starter.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from anyinfer.registry import ProviderRegistry
    from anyinfer.testing import ScriptedModel, ScriptedProvider

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    provider = ScriptedProvider("acme", [ScriptedModel("m", text="Hello there.")])
    provider.register(registry)
    with ai.Client(
        [provider.settings()], registry=registry, use_default_catalog=False
    ) as client:
        assert module.run(client, provider.target("m")) == "Hello there."


def test_the_generated_starter_explains_an_empty_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-provider path is the one a first-run user is most likely to hit."""
    _fake_discovery(monkeypatch, [])
    assert main(["init", "--yes", "--no-probe"]) == 0

    finished = subprocess.run(
        [sys.executable, "starter.py"], capture_output=True, text=True, check=False
    )
    assert finished.returncode == 1
    assert "configures no providers yet" in finished.stderr
    assert not finished.stdout
