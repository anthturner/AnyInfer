"""`anyinfer conform` certifies an adapter and reports what it supports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anyinfer.cli import main
from anyinfer.errors import ConfigError
from anyinfer.testing.certify import case_names, load_declared_capabilities


def _config_file(tmp_path: Path, provider_id: str, base_url: str) -> Path:
    path = tmp_path / "anyinfer.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "providers": [{"id": provider_id, "base_url": base_url}],
            }
        ),
        encoding="utf-8",
    )
    return path


# ---- declarations --------------------------------------------------------------------


def test_missing_project_file_declares_full_support(tmp_path: Path) -> None:
    capabilities = load_declared_capabilities(tmp_path)
    assert capabilities.reasoning is True
    assert capabilities.retry_after is True


def test_declared_capabilities_are_read(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.anyinfer.conformance]\nreasoning = false\nretry_after = false\n",
        encoding="utf-8",
    )

    capabilities = load_declared_capabilities(tmp_path)

    assert capabilities.reasoning is False
    assert capabilities.retry_after is False
    assert capabilities.streaming is True


def test_unknown_capability_is_rejected(tmp_path: Path) -> None:
    """A typo must not read as "unsupported" — that would certify by omission."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.anyinfer.conformance]\nreasonning = false\n", encoding="utf-8"
    )

    with pytest.raises(ConfigError) as caught:
        load_declared_capabilities(tmp_path)

    assert "reasonning" in str(caught.value)


def test_non_boolean_capability_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.anyinfer.conformance]\nreasoning = "no"\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError):
        load_declared_capabilities(tmp_path)


def test_project_without_the_table_declares_full_support(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "acme"\nversion = "0.1.0"\n', encoding="utf-8"
    )

    assert load_declared_capabilities(tmp_path).tools is True


# ---- the command ---------------------------------------------------------------------


def test_presets_are_refused_with_a_pointer_to_their_own_process(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["conform", "groq", "--model", "whatever"])

    captured = capsys.readouterr()
    assert code != 0
    assert "preset" in captured.out.lower() or "preset" in captured.err.lower()


def test_unknown_case_name_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _config_file(tmp_path, "openai-compat", "http://acme.invalid/v1")

    code = main(
        [
            "conform",
            "openai-compat",
            "--model",
            "m",
            "--config",
            str(config),
            "--only",
            "not_a_case",
            "--project",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert code != 0
    assert "not_a_case" in captured.out + captured.err


def test_failing_run_exits_non_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An adapter pointed at nothing fails its cases, and the exit code says so.

    ``health`` deliberately is not the case used here: an adapter that reports
    ``Health(ok=False)`` against a dead endpoint has behaved correctly, and the suite says
    so. Generation is what cannot succeed without a server.
    """
    config = _config_file(tmp_path, "openai-compat", "http://127.0.0.1:9/v1")

    code = main(
        [
            "conform",
            "openai-compat",
            "--model",
            "m",
            "--config",
            str(config),
            "--project",
            str(tmp_path),
            "--only",
            "non_streaming",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "non_streaming" in captured.out


def test_declared_unsupported_cases_are_skipped_not_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config_file(tmp_path, "openai-compat", "http://127.0.0.1:9/v1")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.anyinfer.conformance]\nhealth = false\n", encoding="utf-8"
    )

    code = main(
        [
            "conform",
            "openai-compat",
            "--model",
            "m",
            "--config",
            str(config),
            "--project",
            str(tmp_path),
            "--only",
            "health",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "1 declared unsupported" in captured.out


def test_markdown_row_matches_the_matrix_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config_file(tmp_path, "openai-compat", "http://127.0.0.1:9/v1")

    main(
        [
            "conform",
            "openai-compat",
            "--model",
            "m",
            "--config",
            str(config),
            "--project",
            str(tmp_path),
            "--only",
            "health",
            "--markdown-row",
        ]
    )

    line = capsys.readouterr().out.strip()
    assert line.startswith("| openai-compat |")
    assert line.endswith("|")


def test_case_names_are_stable_and_non_empty() -> None:
    names = case_names()
    assert "health" in names
    assert "structured_output" in names
    assert len(set(names)) == len(names)
