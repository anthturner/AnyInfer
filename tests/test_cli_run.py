"""The one-off `anyinfer run` command end to end (§22).

These drive `main()` exactly as a shell would — argv in, exit code out, stdout/stderr
captured — against a fake transport, so the assertions cover the real client path
(routing, streaming, structured output, tool declarations) without a network call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from anyinfer.cli import main
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse


@pytest.fixture
def config(tmp_path: Path) -> Path:
    """A serve/run config file pointing at one openai-compat provider."""
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
    """Route every provider construction through a fake OpenAI server.

    The config file cannot carry a live transport object, so the fake is injected by
    patching `ProviderSettings.of` to add it — the same seam the serve tests use, reached
    from the other side.
    """
    import anyinfer

    server = FakeOpenAIServer(FakeResponse(text="Hello from the CLI."))
    original = anyinfer.ProviderSettings.of

    def _with_transport(provider_id: str, **kwargs: Any) -> Any:
        kwargs.setdefault("transport", server.transport())
        return original(provider_id, **kwargs)

    monkeypatch.setattr(anyinfer.ProviderSettings, "of", staticmethod(_with_transport))
    return server


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str | None) -> None:
    """Present stdin as either a TTY (no pipe) or a pipe carrying `text`."""
    import io

    class _Stdin(io.StringIO):
        def __init__(self, value: str, tty: bool) -> None:
            super().__init__(value)
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    monkeypatch.setattr("sys.stdin", _Stdin(text or "", tty=text is None))


# ---- the basic path ------------------------------------------------------------------


def test_prompt_argument_streams_to_stdout(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)

    code = main(["run", "say hi", "--config", str(config), "--target", "fake:m"])

    assert code == 0
    out = capsys.readouterr().out
    assert "Hello from the CLI." in out
    # Streaming must not swallow the trailing newline a shell prompt needs.
    assert out.endswith("\n")


def test_prompt_can_be_piped_on_stdin(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, "summarize this text")

    code = main(["run", "--config", str(config), "--target", "fake:m"])

    assert code == 0
    assert "Hello from the CLI." in capsys.readouterr().out


def test_argument_and_stdin_combine(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cat file | anyinfer run 'Summarize:'` must send both halves."""
    _stdin(monkeypatch, "the piped body")

    code = main(["run", "Summarize:", "--config", str(config), "--target", "fake:m"])

    assert code == 0
    sent = json.dumps(transport.requests[-1]["messages"])
    assert "Summarize:" in sent and "the piped body" in sent


def test_no_prompt_anywhere_is_a_usage_error(
    config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)

    code = main(["run", "--config", str(config)])

    assert code == 2
    assert "nothing to do" in capsys.readouterr().err


def test_missing_providers_explains_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")

    code = main(["run", "hi", "--config", str(empty)])

    assert code == 2
    assert "no providers configured" in capsys.readouterr().err


def test_bad_config_is_reported_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stdin(monkeypatch, None)
    broken = tmp_path / "broken.json"
    broken.write_text('{"providers": [{"id": "openai", "api_key_env": "KEY"}]}')

    code = main(["run", "hi", "--config", str(broken)])

    captured = capsys.readouterr()
    assert code == 1
    assert "unknown key" in captured.err
    assert "Traceback" not in captured.err


# ---- output modes -------------------------------------------------------------------


def test_json_mode_emits_one_parseable_object(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)

    code = main(["run", "hi", "--config", str(config), "--target", "fake:m", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["text"] == "Hello from the CLI."
    assert payload["usage"]["output_tokens"] is not None
    assert payload["timing"]["total_ms"] is not None
    assert payload["finish_reason"] == "stop"


def test_no_stream_still_prints_the_text(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)

    code = main([
        "run", "hi", "--config", str(config), "--target", "fake:m", "--no-stream",
    ])

    assert code == 0
    assert "Hello from the CLI." in capsys.readouterr().out


def test_stats_go_to_stderr_leaving_stdout_clean(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stdout stays pipeable; the figures a human wants go to stderr."""
    _stdin(monkeypatch, None)

    code = main([
        "run", "hi", "--config", str(config), "--target", "fake:m", "--stats",
    ])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "Hello from the CLI."
    assert "tokens" in captured.err


# ---- structured output ---------------------------------------------------------------


def test_schema_prints_validated_json(
    tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import anyinfer

    server = FakeOpenAIServer(FakeResponse(text='{"city": "Boston"}'))
    original = anyinfer.ProviderSettings.of

    def _with_transport(provider_id: str, **kwargs: Any) -> Any:
        kwargs.setdefault("transport", server.transport())
        return original(provider_id, **kwargs)

    monkeypatch.setattr(anyinfer.ProviderSettings, "of", staticmethod(_with_transport))
    _stdin(monkeypatch, None)

    schema = tmp_path / "city.json"
    schema.write_text(
        json.dumps({
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        }),
        encoding="utf-8",
    )

    code = main([
        "run", "where?", "--config", str(config), "--target", "fake:m",
        "--schema", str(schema),
    ])

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"city": "Boston"}


def test_bad_schema_file_is_reported_not_traced(
    tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stdin(monkeypatch, None)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main([
            "run", "hi", "--config", str(config), "--target", "fake:m",
            "--schema", str(broken),
        ])

    assert "not valid JSON" in str(excinfo.value)


# ---- tools ---------------------------------------------------------------------------


def test_tool_choice_without_a_tool_is_rejected(
    config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)

    code = main([
        "run", "hi", "--config", str(config), "--target", "fake:m",
        "--tool-choice", "required",
    ])

    assert code == 2
    assert "--tool-choice needs at least one --tool" in capsys.readouterr().err


def test_requested_tool_calls_are_reported(
    tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI does not execute tools; it must surface what the model asked for."""
    import anyinfer

    server = FakeOpenAIServer(
        FakeResponse(
            text="",
            tool_calls=(("c1", "get_weather", '{"city": "NY"}'),),
            finish_reason="tool_calls",
        )
    )
    original = anyinfer.ProviderSettings.of

    def _with_transport(provider_id: str, **kwargs: Any) -> Any:
        kwargs.setdefault("transport", server.transport())
        return original(provider_id, **kwargs)

    monkeypatch.setattr(anyinfer.ProviderSettings, "of", staticmethod(_with_transport))
    _stdin(monkeypatch, None)

    tool = tmp_path / "weather.json"
    tool.write_text(
        json.dumps({
            "name": "get_weather",
            "description": "look up weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        }),
        encoding="utf-8",
    )

    code = main([
        "run", "weather in NY?", "--config", str(config), "--target", "fake:m",
        "--tool", str(tool), "--no-stream",
    ])

    assert code == 0
    assert "get_weather" in capsys.readouterr().err


# ---- sampling and routing wiring -----------------------------------------------------


def test_sampling_flags_reach_the_request(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stdin(monkeypatch, None)

    code = main([
        "run", "hi", "--config", str(config), "--target", "fake:m",
        "--temperature", "0.25", "--max-tokens", "64", "--stop", "END",
    ])

    assert code == 0
    body = transport.requests[-1]
    assert body["temperature"] == 0.25
    assert body["max_tokens"] == 64
    assert body["stop"] == ["END"]


def test_route_overrides_target(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeated --route names an ordered fallback list and wins over --target."""
    _stdin(monkeypatch, None)

    code = main([
        "run", "hi", "--config", str(config),
        "--target", "fake:ignored", "--route", "fake:first", "--route", "fake:second",
    ])

    assert code == 0
    # The first route entry is what actually got dispatched, not --target.
    assert transport.requests[-1]["model"] == "first"


# ---- verify --------------------------------------------------------------------------


@pytest.fixture
def ok_transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A fake server that answers the verification probe correctly."""
    import anyinfer

    server = FakeOpenAIServer(FakeResponse(text=json.dumps({"reply": "OK"})))
    original = anyinfer.ProviderSettings.of

    def _with_transport(provider_id: str, **kwargs: Any) -> Any:
        kwargs.setdefault("transport", server.transport())
        return original(provider_id, **kwargs)

    monkeypatch.setattr(anyinfer.ProviderSettings, "of", staticmethod(_with_transport))
    return server


def test_verify_reports_a_working_target(
    config: Path, ok_transport: Any, capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["verify", "fake:m", "--config", str(config)])

    assert code == 0
    assert "ok" in capsys.readouterr().out
    assert ok_transport.call_count == 1


def test_verify_exits_nonzero_for_a_broken_target(
    config: Path, transport: Any, capsys: pytest.CaptureFixture[str],
) -> None:
    """Usable as a setup gate: a failed probe is a failed command."""
    code = main(["verify", "fake:m", "--config", str(config)])

    assert code == 1, "the fake answers prose, not the probe's schema"
    out = capsys.readouterr().out
    assert "answered" in out, "reached, but could not hold the shape"
    assert "not in the requested shape" in out


def test_verify_json_is_machine_readable(
    config: Path, ok_transport: Any, capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["verify", "fake:m", "--config", str(config), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["ok"] is True
    assert payload[0]["target"] == "fake:m"
    assert payload[0]["reached"] is True


def test_verify_without_a_target_needs_a_route(
    config: Path, ok_transport: Any, capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["verify", "--config", str(config)])

    assert code == 2
    assert "nothing to verify" in capsys.readouterr().err


# ---- dry run -------------------------------------------------------------------------


def test_dry_run_reports_without_sending(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)

    code = main(["run", "summarize this", "--config", str(config), "--target", "fake:m",
                 "--dry-run"])

    assert code == 0
    assert transport.call_count == 0, "a preflight never sends the request"
    out = capsys.readouterr().out
    assert "input estimate" in out
    assert "fake:m" in out


def test_dry_run_says_unknown_rather_than_guessing(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """openai-compat has no catalogued window, and a guess would look authoritative."""
    _stdin(monkeypatch, None)

    main(["run", "hi", "--config", str(config), "--target", "fake:m", "--dry-run"])

    out = capsys.readouterr().out
    assert "unknown" in out
    assert "fits              unknown" in out


def test_dry_run_json_is_machine_readable(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)

    code = main(["run", "hi", "--config", str(config), "--target", "fake:m",
                 "--dry-run", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["target"] == "fake:m"
    assert payload["estimate"]["total"] > 0
    assert payload["fits"] is None


def test_dry_run_needs_a_target(
    config: Path, transport: Any, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stdin(monkeypatch, None)

    code = main(["run", "hi", "--config", str(config), "--dry-run"])

    assert code == 2
    assert "needs a target" in capsys.readouterr().err
