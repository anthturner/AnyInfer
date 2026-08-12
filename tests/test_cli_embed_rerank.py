"""The `anyinfer embed` and `anyinfer rerank` CLI commands end to end.

Drives `main()` exactly as a shell would — argv in, exit code out, stdout/stderr captured —
against an in-process fake provider registered on the process-wide registry, the same way
`config["providers"][].adapter` resolves in real use.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from anyinfer.cli import main
from anyinfer.registry import default_registry
from anyinfer.testing import FakeEmbeddingRerankProvider


@pytest.fixture
def fake_provider() -> Iterator[FakeEmbeddingRerankProvider]:
    """Register a fake embedding/rerank provider on the default registry for one test."""
    fake = FakeEmbeddingRerankProvider(
        "cli-fake",
        embedding_dimensions={"embed-model": 4},
        rerank_models=["rerank-model"],
    )
    fake.register(default_registry)
    yield fake
    default_registry.unregister("cli-fake")


@pytest.fixture
def config(tmp_path: Path) -> Path:
    """A config file pointing at the fake provider."""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"providers": [{"id": "cli-fake", "adapter": "cli-fake"}]}),
        encoding="utf-8",
    )
    return path


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str | None) -> None:
    import io

    class _Stdin(io.StringIO):
        def __init__(self, value: str, tty: bool) -> None:
            super().__init__(value)
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    monkeypatch.setattr("sys.stdin", _Stdin(text or "", tty=text is None))


# ---- embed -----------------------------------------------------------------------------


def test_embed_text_argument_json_output(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)
    code = main(
        ["embed", "hello world", "--config", str(config), "--target", "cli-fake:embed-model", "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["vectors"]) == 1
    assert len(payload["vectors"][0]) == 4
    assert payload["space"]["provider_id"] == "cli-fake"


def test_embed_plain_output_reports_summary_to_stderr(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)
    code = main(["embed", "hello", "--config", str(config), "--target", "cli-fake:embed-model"])
    assert code == 0
    captured = capsys.readouterr()
    assert "1 vector(s)" in captured.err


def test_embed_oversized_request_batches_transparently(
    config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Core-owned batching is reachable from the CLI with zero frontend code."""
    from anyinfer import EmbeddingCapabilities

    fake = FakeEmbeddingRerankProvider(
        "cli-fake",
        embedding_dimensions={"embed-model": 4},
        embedding_capabilities={"embed-model": EmbeddingCapabilities(max_batch_inputs=2)},
    )
    fake.register(default_registry)
    try:
        _stdin(monkeypatch, None)
        inputs_file = tmp_path / "inputs.txt"
        inputs_file.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
        code = main(
            [
                "embed",
                "--file",
                str(inputs_file),
                "--config",
                str(config),
                "--target",
                "cli-fake:embed-model",
                "--json",
            ]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["vectors"]) == 5
        assert [len(req.inputs) for req in fake.embed_requests] == [2, 2, 1]
    finally:
        default_registry.unregister("cli-fake")


def test_embed_reads_newline_delimited_file(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _stdin(monkeypatch, None)
    inputs_file = tmp_path / "inputs.txt"
    inputs_file.write_text("one\ntwo\nthree\n", encoding="utf-8")
    code = main(
        [
            "embed",
            "--file",
            str(inputs_file),
            "--config",
            str(config),
            "--target",
            "cli-fake:embed-model",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["vectors"]) == 3


def test_embed_reads_jsonl(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _stdin(monkeypatch, None)
    jsonl_file = tmp_path / "inputs.jsonl"
    jsonl_file.write_text(
        '{"text": "alpha"}\n{"text": "beta"}\n', encoding="utf-8"
    )
    code = main(
        [
            "embed",
            "--jsonl",
            str(jsonl_file),
            "--config",
            str(config),
            "--target",
            "cli-fake:embed-model",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["vectors"]) == 2


def test_embed_writes_to_out_file(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _stdin(monkeypatch, None)
    out_file = tmp_path / "out.json"
    code = main(
        [
            "embed",
            "hello",
            "--config",
            str(config),
            "--target",
            "cli-fake:embed-model",
            "--out",
            str(out_file),
        ]
    )
    assert code == 0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(payload["vectors"]) == 1


def test_embed_nothing_to_embed_exits_2(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)
    code = main(["embed", "--config", str(config), "--target", "cli-fake:embed-model"])
    assert code == 2
    assert "nothing to embed" in capsys.readouterr().err


def test_embed_conflicting_sources_exits_2(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _stdin(monkeypatch, None)
    inputs_file = tmp_path / "inputs.txt"
    inputs_file.write_text("one\n", encoding="utf-8")
    code = main(
        [
            "embed",
            "hello",
            "--file",
            str(inputs_file),
            "--config",
            str(config),
            "--target",
            "cli-fake:embed-model",
        ]
    )
    assert code == 2
    assert "at most one" in capsys.readouterr().err


# ---- rerank ------------------------------------------------------------------------------


def test_rerank_document_flags_json_output(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)
    code = main(
        [
            "rerank",
            "capital of France",
            "--document",
            "Paris is the capital of France.",
            "--document",
            "Berlin is in Germany.",
            "--config",
            str(config),
            "--target",
            "cli-fake:rerank-model",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["items"]) == 2
    assert payload["items"][0]["score"] >= payload["items"][1]["score"]


def test_rerank_plain_output_lists_ranked_items(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)
    code = main(
        [
            "rerank",
            "France",
            "--document",
            "Paris France",
            "--config",
            str(config),
            "--target",
            "cli-fake:rerank-model",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "1. [0]" in out


def test_rerank_top_n(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)
    code = main(
        [
            "rerank",
            "France",
            "--document",
            "Paris France",
            "--document",
            "Berlin Germany",
            "--config",
            str(config),
            "--target",
            "cli-fake:rerank-model",
            "--top-n",
            "1",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["items"]) == 1


def test_rerank_nothing_to_rank_exits_2(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)
    code = main(["rerank", "query", "--config", str(config), "--target", "cli-fake:rerank-model"])
    assert code == 2
    assert "nothing to rank" in capsys.readouterr().err


def test_rerank_reads_jsonl_with_ids(
    config: Path,
    fake_provider: FakeEmbeddingRerankProvider,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _stdin(monkeypatch, None)
    jsonl_file = tmp_path / "docs.jsonl"
    jsonl_file.write_text(
        '{"id": "doc-a", "text": "Paris France"}\n{"id": "doc-b", "text": "Berlin Germany"}\n',
        encoding="utf-8",
    )
    code = main(
        [
            "rerank",
            "France",
            "--jsonl",
            str(jsonl_file),
            "--config",
            str(config),
            "--target",
            "cli-fake:rerank-model",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    ids = {item["document_id"] for item in payload["items"]}
    assert ids == {"doc-a", "doc-b"}
