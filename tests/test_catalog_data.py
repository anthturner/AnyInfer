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


# ---- guided eviction through the CLI --------------------------------------------------


@pytest.fixture
def populated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A store with two entries whose bytes exist on disk, one fresh and one stale."""
    import time

    from anyinfer.local.store import MODEL_DIR_ENV, ModelStore, StoredFile, StoreEntry

    monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path))
    store = ModelStore(tmp_path)
    now = time.time()
    index: dict[str, StoreEntry] = {}
    for entry_id, size, days in (("fresh-entry", 4096, 1), ("stale-entry", 8192, 120)):
        directory = tmp_path / entry_id
        directory.mkdir()
        (directory / "weights.gguf").write_bytes(b"x" * size)
        index[entry_id] = StoreEntry(
            id=entry_id,
            model_id=f"catalog/{entry_id}",
            directory=entry_id,
            files=(
                StoredFile(path="weights.gguf", size_bytes=size, digest="d", verified=True),
            ),
            installed_at=now - days * 86400,
            last_used_at=now - days * 86400,
        )
    store._write_index(index)
    return tmp_path


def test_models_prune_dry_run_prints_the_plan_and_deletes_nothing(
    populated_store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["models", "prune", "--keep-bytes", "5000", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "stale-entry" in out
    assert "fresh-entry" not in out, "the recently-used entry must not be proposed"
    assert (populated_store / "stale-entry" / "weights.gguf").exists()


def test_models_prune_json_reports_the_plan_without_acting(
    populated_store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["models", "prune", "--keep-bytes", "5000", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [p["entry_id"] for p in payload["proposals"]] == ["stale-entry"]
    assert payload["total_bytes"] == 12288
    assert payload["remaining_bytes"] == 4096
    assert (populated_store / "stale-entry").exists()


def test_models_prune_with_yes_actually_deletes(
    populated_store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["models", "prune", "--keep-bytes", "5000", "--yes"]) == 0
    assert "freeing" in capsys.readouterr().out
    assert not (populated_store / "stale-entry").exists()
    assert (populated_store / "fresh-entry" / "weights.gguf").exists()


def test_models_prune_refuses_to_delete_without_a_terminal_or_yes(
    populated_store: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deliberately stricter than every other confirmation in this CLI.

    `_confirm` proceeds when stdin is not a tty, which is right for writing a config file
    and wrong for deleting tens of gigabytes a pipeline never meant to touch.
    """
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert main(["models", "prune", "--keep-bytes", "5000"]) == 1
    assert "nothing was deleted" in capsys.readouterr().err
    assert (populated_store / "stale-entry").exists()


def test_models_prune_needs_exactly_one_limit(populated_store: Path) -> None:
    """No default budget: an invented one would silently delete real gigabytes."""
    with pytest.raises(SystemExit):
        main(["models", "prune"])
    with pytest.raises(SystemExit):
        main(["models", "prune", "--keep-bytes", "1", "--older-than-days", "1"])


def test_models_prune_by_age_ignores_the_disk_total(
    populated_store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["models", "prune", "--older-than-days", "30", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [p["entry_id"] for p in payload["proposals"]] == ["stale-entry"]
    assert payload["keep_bytes"] is None


def test_a_store_that_already_fits_says_so_and_succeeds(
    populated_store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["models", "prune", "--keep-bytes", "1GB"]) == 0
    assert "nothing to prune" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500", 500),
        ("40GB", 40_000_000_000),
        ("40GiB", 42_949_672_960),
        ("1.5 tb", 1_500_000_000_000),
        ("500mib", 524_288_000),
    ],
)
def test_a_size_suffix_means_what_the_tool_that_printed_it_meant(
    text: str, expected: int
) -> None:
    """GB and GiB are both accepted and kept distinct: 7% of a disk budget is real space."""
    from anyinfer.cli import _byte_size

    assert _byte_size(text) == expected


@pytest.mark.parametrize("text", ["", "-5", "12PB", "lots"])
def test_an_unparseable_size_is_refused_by_the_parser(text: str) -> None:
    import argparse

    from anyinfer.cli import _byte_size

    with pytest.raises(argparse.ArgumentTypeError):
        _byte_size(text)
