"""`anyinfer compare --snapshot`/`--diff`/`--diff-request` end to end."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from anyinfer.cli import main
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "fake",
                        "adapter": "openai-compat",
                        "base_url": "https://fake.invalid/v1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    import anyinfer

    server = FakeOpenAIServer(FakeResponse(text="unused — compare never dispatches"))
    original = anyinfer.ProviderSettings.of

    def _with_transport(provider_id: str, **kwargs: Any) -> Any:
        kwargs.setdefault("transport", server.transport())
        return original(provider_id, **kwargs)

    monkeypatch.setattr(anyinfer.ProviderSettings, "of", staticmethod(_with_transport))
    return server


@pytest.fixture
def fixtures(tmp_path: Path) -> Path:
    path = tmp_path / "fixtures.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixtures": [
                    {
                        "id": "hello",
                        "request": {"messages": [{"role": "user", "text": "hi"}]},
                        "targets": ["fake:m"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_snapshot_writes_a_file(
    config: Path, transport: Any, fixtures: Path, tmp_path: Path
) -> None:
    out = tmp_path / "snap.json"
    code = main(
        ["compare", "--snapshot", "--fixtures", str(fixtures), "--out", str(out), "--config", str(config)]
    )
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert "fake:m" in payload["fixtures"]["hello"]
    assert transport.requests == []


def test_diff_of_identical_snapshots_exits_zero(
    config: Path, transport: Any, fixtures: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "snap.json"
    main(["compare", "--snapshot", "--fixtures", str(fixtures), "--out", str(out), "--config", str(config)])

    code = main(["compare", "--diff", str(out), str(out)])
    assert code == 0
    assert "no differences" in capsys.readouterr().out


def test_diff_of_different_snapshots_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    baseline.write_text(
        json.dumps({"schema_version": 1, "fixtures": {"f": {"t": {"fits": True}}}})
    )
    current.write_text(
        json.dumps({"schema_version": 1, "fixtures": {"f": {"t": {"fits": False}}}})
    )

    code = main(["compare", "--diff", str(baseline), str(current)])
    assert code == 1
    assert "fits" in capsys.readouterr().out


def test_diff_request_reports_live_without_a_snapshot_file(
    config: Path, transport: Any, fixtures: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "compare",
            "--diff-request",
            "hello",
            "--diff-target-a",
            "fake:m",
            "--diff-target-b",
            "fake:m",
            "--fixtures",
            str(fixtures),
            "--config",
            str(config),
        ]
    )
    assert code == 0
    assert "no differences" in capsys.readouterr().out
    assert transport.requests == []


def test_snapshot_without_fixtures_is_a_usage_error(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["compare", "--snapshot", "--config", str(config)])
    assert code == 2
    assert "--fixtures" in capsys.readouterr().err
