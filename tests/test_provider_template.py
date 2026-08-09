"""The scaffolded provider package is real: it imports, registers, and resolves.

This is the only check that the documented extension path works end to end. Path handling
in a generated package is a Windows trap, so it runs everywhere CI runs.
"""

from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path

import pytest

from anyinfer.cli import main
from anyinfer.errors import ConfigError
from anyinfer.registry import ProviderDescriptor, ProviderRegistry
from anyinfer.testing.scaffold import scaffold_provider


def test_scaffold_writes_every_declared_file(tmp_path: Path) -> None:
    written = scaffold_provider("acme", tmp_path)

    names = {path.relative_to(tmp_path).as_posix() for path in written}
    assert names == {
        "acme_anyinfer/__init__.py",
        "acme_anyinfer/adapter.py",
        "tests/test_conformance.py",
        "contracts/acme.md",
        "pyproject.toml",
        "README.md",
    }


def test_scaffolded_package_imports_and_registers(tmp_path: Path) -> None:
    """The generated descriptor is registrable and its targets resolve."""
    scaffold_provider("acme", tmp_path)
    sys.path.insert(0, str(tmp_path))
    try:
        module = importlib.import_module("acme_anyinfer")
        descriptor = module.provider()

        assert isinstance(descriptor, ProviderDescriptor)
        registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
        registry.register(descriptor)

        assert registry.resolve_alias("acme") == "acme"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("acme_anyinfer", None)
        sys.modules.pop("acme_anyinfer.adapter", None)


def test_scaffolded_pyproject_declares_the_entry_point(tmp_path: Path) -> None:
    scaffold_provider("acme", tmp_path)

    document = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    entry_points = document["project"]["entry-points"]["anyinfer.providers"]

    assert entry_points == {"acme": "acme_anyinfer:provider"}


def test_scaffolded_contract_has_every_required_section(tmp_path: Path) -> None:
    """The generated snapshot passes the same structural check the repo's own do."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        from validate_contracts import REQUIRED_HEADINGS
    finally:
        sys.path.pop(0)

    scaffold_provider("acme", tmp_path)
    text = (tmp_path / "contracts" / "acme.md").read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        assert heading in text


def test_hyphenated_ids_become_valid_python_names(tmp_path: Path) -> None:
    scaffold_provider("acme-llm", tmp_path)

    source = (tmp_path / "acme_llm_anyinfer" / "__init__.py").read_text(encoding="utf-8")
    assert "AcmeLlmAdapter" in source
    assert 'id="acme-llm"' in source
    assert "ACME_LLM_API_KEY" in source


def test_existing_files_are_not_overwritten(tmp_path: Path) -> None:
    scaffold_provider("acme", tmp_path)

    with pytest.raises(ConfigError):
        scaffold_provider("acme", tmp_path)

    assert scaffold_provider("acme", tmp_path, force=True)


def test_unusable_provider_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        scaffold_provider("not a provider!", tmp_path)


def test_cli_scaffold_reports_what_it_wrote(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["conform", "acme", "--scaffold", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 0
    assert "wrote" in captured.out
    assert "anyinfer conform acme" in captured.out


def test_cli_requires_a_model_when_actually_running(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["conform", "openai-compat"])

    captured = capsys.readouterr()
    assert code != 0
    assert "--model" in captured.out + captured.err
