"""The `anyinfer context` command end to end.

Driven through `main()` exactly as a shell would — argv in, exit code out, stdout and
stderr captured. No provider is contacted: reduction is deterministic and local, which is
the whole point of the subsystem.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anyinfer.cli import main


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A small source tree, with the working directory moved into it."""
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "node_modules").mkdir()

    (root / "README.md").write_text("# Project\n\nIt resolves credentials.\n", encoding="utf-8")
    (root / "src" / "credentials.py").write_text(
        "\n".join(f"def resolve_credential_{i}():\n    return {i}" for i in range(30)),
        encoding="utf-8",
    )
    (root / "src" / "unrelated.py").write_text(
        "\n".join(f"def paint_{i}():\n    return 'red'" for i in range(30)), encoding="utf-8"
    )
    (root / "src" / "copy.py").write_text(
        "\n".join(f"def resolve_credential_{i}():\n    return {i}" for i in range(30)),
        encoding="utf-8",
    )
    (root / "node_modules" / "vendored.js").write_text("module.exports = 1;\n", encoding="utf-8")
    (root / "image.bin").write_bytes(b"\x00\x01\x02binary")

    monkeypatch.chdir(root)
    return root


def test_it_prints_an_envelope_on_stdout_and_the_account_on_stderr(corpus, capsys):
    assert main(["context", ".", "--query", "credentials", "--max-tokens", "4000"]) == 0
    captured = capsys.readouterr()
    assert "<context" in captured.out
    assert 'format="1"' in captured.out
    assert "document(s)" in captured.err
    assert "<context" not in captured.err


def test_collection_skips_vendored_and_binary_files(corpus, capsys):
    main(["context", ".", "--query", "credentials", "--max-tokens", "8000"])
    out = capsys.readouterr().out
    assert "vendored.js" not in out
    assert "image.bin" not in out
    assert "credentials.py" in out


def test_generated_paths_can_be_asked_for(corpus, capsys):
    main(
        [
            "context",
            ".",
            "--query",
            "module",
            "--max-tokens",
            "8000",
            "--include-generated",
        ]
    )
    assert "vendored.js" in capsys.readouterr().out


def test_duplicates_collapse_by_default(corpus, capsys):
    main(["context", ".", "--query", "credentials", "--max-tokens", "8000"])
    out = capsys.readouterr().out
    assert "<duplicate" in out
    assert 'identical="true"' in out


def test_a_pinned_path_is_always_included(corpus, capsys):
    main(
        [
            "context",
            ".",
            "--query",
            "credentials",
            "--max-tokens",
            "600",
            "--pin",
            "src/unrelated.py",
        ]
    )
    assert "unrelated.py" in capsys.readouterr().out


def test_the_plan_costs_every_strategy(corpus, capsys):
    assert main(["context", ".", "--query", "credentials", "--max-tokens", "700", "--plan"]) == 0
    out = capsys.readouterr().out
    for strategy in ("whole", "ranked", "tiered", "packed"):
        assert strategy in out
    assert "distill" in out
    assert "generation call(s)" in out


def test_the_plan_is_available_as_json(corpus, capsys):
    main(["context", ".", "--query", "credentials", "--max-tokens", "700", "--plan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_count"] >= 3
    assert {option["strategy"] for option in payload["options"]} == {
        "whole",
        "ranked",
        "tiered",
        "packed",
    }
    assert payload["best"] in {"whole", "ranked", "tiered", "packed"}


def test_the_reduction_record_is_available_as_json(corpus, capsys):
    main(["context", ".", "--query", "credentials", "--max-tokens", "700", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["max_tokens"] == 700
    assert payload["estimated_tokens"] <= 700
    assert "collapsed_exact" in payload


def test_a_missing_budget_is_refused_rather_than_guessed(corpus, capsys):
    assert main(["context", ".", "--query", "credentials"]) == 2
    assert "--max-tokens" in capsys.readouterr().err


def test_an_unknown_context_window_is_refused_rather_than_guessed(corpus, capsys):
    code = main(["context", ".", "--query", "credentials", "--target", "openai-compat:mystery"])
    assert code == 2
    assert "unknown" in capsys.readouterr().err


def test_a_preset_overrides_the_config_file(tmp_path, corpus, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"context": {"collapse_duplicates": False}}), encoding="utf-8")
    argv = [
        "context",
        ".",
        "--query",
        "credentials",
        "--max-tokens",
        "8000",
        "--config",
        str(config),
    ]

    main(argv)
    assert "<duplicate" not in capsys.readouterr().out

    main([*argv, "--preset", "recommended"])
    assert "<duplicate" in capsys.readouterr().out


def test_a_flag_overrides_a_preset(corpus, capsys):
    # The recommended preset collapses both exactly and by similarity, so turning
    # collapse off means turning both off.
    main(
        [
            "context",
            ".",
            "--query",
            "credentials",
            "--max-tokens",
            "8000",
            "--preset",
            "recommended",
            "--no-context-collapse-duplicates",
            "--context-near-duplicate-threshold",
            "0",
        ]
    )
    assert "<duplicate" not in capsys.readouterr().out


def test_a_tuning_flag_overrides_the_config_file(tmp_path, corpus, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"context": {"collapse_duplicates": True}}), encoding="utf-8")

    main(
        [
            "context",
            ".",
            "--query",
            "credentials",
            "--max-tokens",
            "8000",
            "--config",
            str(config),
            "--no-context-collapse-duplicates",
        ]
    )
    assert "<duplicate" not in capsys.readouterr().out


def test_a_config_file_setting_applies_without_a_flag(tmp_path, corpus, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"context": {"collapse_duplicates": False}}), encoding="utf-8")

    main(
        [
            "context",
            ".",
            "--query",
            "credentials",
            "--max-tokens",
            "8000",
            "--config",
            str(config),
        ]
    )
    assert "<duplicate" not in capsys.readouterr().out


def test_every_setting_is_reachable_from_the_command_line():
    # One vocabulary across the config file, the CLI, and the keyword argument: a setting
    # that exists in only two of the three is the drift this generation exists to prevent.
    import dataclasses

    from anyinfer.cli import build_parser
    from anyinfer.context import ContextTuning

    parser = build_parser()
    for field in dataclasses.fields(ContextTuning):
        flag = f"--context-{field.name.replace('_', '-')}"
        annotation = str(field.type)
        if "bool" in annotation:
            value: list[str] = []
        elif "SelectionOrder" in annotation:
            value = ["density"]
        elif "int" in annotation:
            value = ["3"]
        else:
            value = ["0.5"]

        parsed = parser.parse_args(["context", ".", "--max-tokens", "100", flag, *value])
        assert getattr(parsed, f"context_{field.name}") is not None, field.name


def test_unset_flags_stay_unset():
    from anyinfer.cli import build_parser

    parsed = build_parser().parse_args(["context", ".", "--max-tokens", "100"])
    assert parsed.context_diversity is None
    assert parsed.context_query_expansion is None


def test_an_empty_corpus_is_reported_rather_than_rendered(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert main(["context", ".", "--query", "anything", "--max-tokens", "1000"]) == 2
    assert "no readable text files" in capsys.readouterr().err
