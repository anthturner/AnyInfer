"""The bundled catalog and runtime tables as *data*, plus the CLI that surfaces them.

The validator is run as a test as well as in the refresh workflow, so a bad merge fails CI
rather than shipping. Everything here is offline: the tables are files, and the CLI paths
exercised are the ones that read them.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from anyinfer.catalog import load_default_catalog
from anyinfer.cli import main
from anyinfer.local.store import ModelStore

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_catalog import validate_models, validate_runtimes  # noqa: E402

# ---- the data ---------------------------------------------------------------------------


def test_the_bundled_model_table_is_valid() -> None:
    assert validate_models() == []


def test_the_bundled_runtime_table_is_valid() -> None:
    assert validate_runtimes() == []


def test_the_validator_script_exits_zero() -> None:
    """The workflow and CI gate run it as a process, so run it that way here too."""
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_catalog.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_the_validator_catches_an_unpinned_entry(tmp_path: Path) -> None:
    """The gate has to actually reject something, or it is decoration."""
    document = json.loads(
        (REPO_ROOT / "src" / "anyinfer" / "catalog" / "models.json").read_text(encoding="utf-8")
    )
    entry = document["models"][0]
    entry["variants"][0]["source"]["revision"] = "main"
    entry["variants"][0]["source"]["sha256"] = {}
    broken = tmp_path / "models.json"
    broken.write_text(json.dumps(document), encoding="utf-8")

    problems = validate_models(broken)
    assert any("not a 40-character commit sha" in p for p in problems)
    assert any("has no sha256" in p for p in problems)


def test_the_validator_catches_a_license_outside_the_allowlist(tmp_path: Path) -> None:
    document = json.loads(
        (REPO_ROOT / "src" / "anyinfer" / "catalog" / "models.json").read_text(encoding="utf-8")
    )
    document["models"][0]["license"] = "cc-by-nc-4.0"
    broken = tmp_path / "models.json"
    broken.write_text(json.dumps(document), encoding="utf-8")

    assert any("not in the allowlist" in p for p in validate_models(broken))


def test_the_validator_catches_a_fabricated_future_date(tmp_path: Path) -> None:
    document = json.loads(
        (REPO_ROOT / "src" / "anyinfer" / "catalog" / "models.json").read_text(encoding="utf-8")
    )
    document["models"][0]["last_verified"] = "2099-01-01"
    broken = tmp_path / "models.json"
    broken.write_text(json.dumps(document), encoding="utf-8")

    assert any("in the future" in p for p in validate_models(broken))


def test_estimates_are_monotonic_within_a_quantization_ladder() -> None:
    """A higher-quality rung must never claim to need less memory than a lower one."""
    for entry in load_default_catalog().models.values():
        gguf = [v for v in entry.variants if v.kind == "gguf" and v.est_file_bytes]
        ordered = sorted(gguf, key=lambda v: v.quality_rank)
        sizes = [v.est_file_bytes or 0 for v in ordered]
        assert sizes == sorted(sizes), f"{entry.id} ladder sizes are not monotonic"


def test_every_model_offers_a_quantization_the_default_ladder_permits() -> None:
    from anyinfer.local.variants import LLAMA_CPP_LADDER

    for entry in load_default_catalog().models.values():
        quants = {v.quantization.upper() for v in entry.variants}
        assert quants & set(LLAMA_CPP_LADDER), f"{entry.id} has only off-ladder quantizations"


# ---- the CLI ------------------------------------------------------------------------------


def test_models_list_prints_a_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["models", "list"]) == 0
    out = capsys.readouterr().out
    assert "MODEL" in out
    assert "FIT" in out


def test_models_list_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["models", "list", "--all", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hardware_source"] in ("detected", "provided", "unavailable")
    assert len(payload["models"]) >= 35
    assert all("fit" in entry and "reasons" in entry for entry in payload["models"])


def test_models_list_filters_by_category(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["models", "list", "--all", "--best-at", "coding", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["models"]
    assert all("coding" in entry["best_at"] for entry in payload["models"])


def test_models_installed_on_an_empty_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANYINFER_MODEL_DIR", str(tmp_path))
    assert main(["models", "installed"]) == 0
    assert "no models downloaded yet" in capsys.readouterr().out


def test_models_where_reports_a_missing_model_as_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANYINFER_MODEL_DIR", str(tmp_path))
    assert main(["models", "where", "qwen2.5-7b-instruct"]) == 1
    assert "not downloaded" in capsys.readouterr().err


def test_models_rm_reports_an_unknown_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANYINFER_MODEL_DIR", str(tmp_path))
    assert main(["models", "rm", "nope"]) == 1
    assert "no store entry" in capsys.readouterr().err


def test_the_model_dir_environment_variable_moves_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANYINFER_MODEL_DIR", str(tmp_path / "elsewhere"))
    assert ModelStore().root == tmp_path / "elsewhere"


def test_runtime_list_reports_the_pinned_build(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["runtime", "list"]) == 0
    out = capsys.readouterr().out
    assert "pinned build" in out
    assert "BACKEND" in out


def test_runtime_rm_reports_that_nothing_was_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANYINFER_RUNTIME_DIR", str(tmp_path))
    assert main(["runtime", "rm", "cuda"]) == 1
    assert "no cuda runtime is installed" in capsys.readouterr().err
