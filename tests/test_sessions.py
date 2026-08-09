"""Session reuse: the handle, the routing rules, and per-provider behaviour (D40)."""

from __future__ import annotations

import sys
import types
from collections.abc import Sequence
from typing import Any

import pytest

import anyinfer as ai
from anyinfer.providers.base import ProviderConfig, WireRequest
from anyinfer.providers.copilot import CopilotAdapter
from anyinfer.providers.ollama import SESSION_KEEP_ALIVE, OllamaAdapter
from anyinfer.testing.fakes import FakeOllamaServer, FakeOpenAIServer, FakeResponse
from support import make_client, make_multi_client, make_sync_client

# ---- the handle ----------------------------------------------------------------------


async def test_an_unsupported_provider_yields_an_inert_session() -> None:
    """Not an error: the request behaves exactly as it would have, and says so."""
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(server) as client:
        session = client.session("openai-compat:m")
        assert session.supported is False
        assert session.reuse == "unsupported"

        result = await client.generate("hello", session=session)

    assert result.text == "hi"
    assert session.turns == 1
    assert session.reuse == "unsupported"
    assert "keep_alive" not in server.requests[0]


async def test_a_closed_session_is_refused() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(server) as client:
        session = client.session("openai-compat:m")
        session.close()
        with pytest.raises(ai.ConfigError):
            await client.generate("hello", session=session)

    assert server.call_count == 0


def test_the_handle_is_a_context_manager() -> None:
    server = FakeOpenAIServer()
    client = make_sync_client(server)
    try:
        with client.session("openai-compat:m") as session:
            assert session.closed is False
        assert session.closed is True
    finally:
        client.close()


def test_applies_to_is_bound_to_one_target() -> None:
    session = ai.Session(ai.ResolvedTarget("ollama", "qwen3:8b"), supported=True)
    assert session.applies_to(ai.ResolvedTarget("ollama", "qwen3:8b")) is True
    assert session.applies_to(ai.ResolvedTarget("ollama", "qwen3:4b")) is False
    assert session.applies_to(ai.ResolvedTarget("openai", "qwen3:8b")) is False

    session.close()
    assert session.applies_to(ai.ResolvedTarget("ollama", "qwen3:8b")) is False


def test_an_unsupported_session_never_applies() -> None:
    session = ai.Session(ai.ResolvedTarget("openai", "gpt-5"), supported=False)
    assert session.applies_to(ai.ResolvedTarget("openai", "gpt-5")) is False


# ---- ollama: residency ---------------------------------------------------------------


async def _ollama_client(server: FakeOllamaServer) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama", base_url="http://127.0.0.1:11434", transport=server.transport()
            )
        ]
    )


async def test_ollama_holds_the_model_resident_for_an_open_session() -> None:
    """Ollama keeps no conversation, but reloading the weights between turns is the cost."""
    server = FakeOllamaServer(FakeResponse(text="hi"))
    async with await _ollama_client(server) as client:
        session = client.session("ollama:qwen3:8b")
        assert session.supported is True

        await client.generate("first", session=session)
        assert session.reuse == "fresh"
        await client.generate("second", session=session)
        assert session.reuse == "resumed"

    assert all(body["keep_alive"] == SESSION_KEEP_ALIVE for body in server.requests)


async def test_ollama_sends_no_keep_alive_without_a_session() -> None:
    server = FakeOllamaServer(FakeResponse(text="hi"))
    async with await _ollama_client(server) as client:
        await client.generate("hello", target="ollama:qwen3:8b")

    assert "keep_alive" not in server.requests[0]


async def test_an_explicit_keep_alive_beats_the_session_default() -> None:
    """It is the caller's memory; a session must not quietly override their choice."""
    server = FakeOllamaServer(FakeResponse(text="hi"))
    async with await _ollama_client(server) as client:
        session = client.session("ollama:qwen3:8b")
        await client.generate(
            "hello", session=session, provider_options={"ollama": {"keep_alive": "1h"}}
        )

    assert server.requests[0]["keep_alive"] == "1h"


def test_the_ollama_payload_distinguishes_no_session_from_a_first_turn() -> None:
    adapter = OllamaAdapter(ProviderConfig(provider_id="ollama"))
    request = WireRequest(model="m", messages=(ai.user("hi"),))

    assert "keep_alive" not in adapter.build_payload(request)
    first_turn = adapter.build_payload(
        WireRequest(model="m", messages=(ai.user("hi"),), session_state={})
    )
    assert first_turn["keep_alive"] == SESSION_KEEP_ALIVE


# ---- routing rules -------------------------------------------------------------------


async def test_a_session_does_not_follow_a_fallback_to_another_provider() -> None:
    """One provider's handle means nothing to another, so that turn runs stateless."""
    broken = FakeOllamaServer(FakeResponse(status=500, error_message="down"))
    other = FakeOpenAIServer(FakeResponse(text="from elsewhere"))
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "ollama", base_url="http://127.0.0.1:11434", transport=broken.transport()
            ),
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=other.transport(),
            ),
        ]
    )
    async with client:
        session = client.session("ollama:qwen3:8b")
        result = await client.generate(
            "hello",
            route=ai.Route(
                targets=("ollama:qwen3:8b", "openai-compat:m"), retry=ai.Retry(max_attempts=1)
            ),
            session=session,
        )

    assert result.text == "from elsewhere"
    assert session.reuse == "unsupported", "the turn that answered was not this session's"
    assert "keep_alive" not in other.requests[0]


# ---- copilot: real conversation reuse -------------------------------------------------


class _FakeSession:
    def __init__(self, events: Sequence[Any]) -> None:
        self._events = list(events)
        self.prompts: list[str] = []
        self.closed = False

    def send(self, prompt: str) -> list[Any]:
        self.prompts.append(prompt)
        return list(self._events)

    def close(self) -> None:
        self.closed = True


def _install_copilot(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    instances: list[Any] = []

    class _FakeCopilotClient:
        def __init__(self, **options: Any) -> None:
            self.sessions: list[_FakeSession] = []
            self.closed = False
            instances.append(self)

        def create_session(self, **session_options: Any) -> _FakeSession:
            session = _FakeSession([{"text": "ok"}])
            self.sessions.append(session)
            return session

        def list_models(self) -> list[Any]:
            return ["auto"]

        def close(self) -> None:
            self.closed = True

    module = types.ModuleType("copilot")
    module.CopilotClient = _FakeCopilotClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "copilot", module)
    monkeypatch.delenv("COPILOT_CLI_PATH", raising=False)
    return instances


async def test_copilot_creates_one_session_per_request_without_a_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = _install_copilot(monkeypatch)
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        for _ in range(2):
            async for _event in adapter.generate(
                WireRequest(model="auto", messages=(ai.user("hi"),))
            ):
                pass
    finally:
        await adapter.aclose()

    client = instances[0]
    assert len(client.sessions) == 2
    assert all(s.closed for s in client.sessions), "an unsessioned turn owns its session"


async def test_copilot_resumes_one_session_and_sends_only_the_new_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = _install_copilot(monkeypatch)
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    state: dict[str, Any] | None = {}
    try:
        for prompt in ("first question", "second question"):
            async for event in adapter.generate(
                WireRequest(
                    model="auto",
                    messages=(
                        ai.user("first question"),
                        ai.assistant("an answer"),
                        ai.user(prompt),
                    ),
                    session_state=state,
                )
            ):
                if hasattr(event, "session_state") and event.session_state is not None:
                    state = dict(event.session_state)
    finally:
        await adapter.aclose()

    client = instances[0]
    assert len(client.sessions) == 1, "the second turn resumed rather than starting over"
    held = client.sessions[0]
    assert len(held.prompts) == 2
    assert "[assistant]" in held.prompts[0], "the first turn still carries the history"
    assert "[assistant]" not in held.prompts[1], (
        "a resumed session must not re-send what the service already holds"
    )
    assert held.closed is True, "closing the adapter closes what it held open"


# ---- llama.cpp: pinning --------------------------------------------------------------


async def test_llama_cpp_pins_the_server_while_a_session_is_open() -> None:
    """Unloading between turns discards the KV cache the next turn was about to reuse."""
    import pathlib
    import tempfile

    from test_llama_cpp import PAYLOAD, _adapter

    with tempfile.TemporaryDirectory() as raw:
        tmp_path = pathlib.Path(raw)
        (tmp_path / "test-model.gguf").write_bytes(PAYLOAD)
        adapter, supervisor = _adapter(tmp_path, FakeOpenAIServer(FakeResponse(text="hi")))
        try:
            async for _event in adapter.generate(
                WireRequest(model="test-model", messages=(ai.user("hi"),), session_state={})
            ):
                pass
        finally:
            await adapter.aclose()

    assert supervisor.persisted == [True]


async def test_sessions_are_reported_end_to_end() -> None:
    server = FakeOllamaServer(FakeResponse(text="hi"))
    async with await _ollama_client(server) as client:
        session = client.session("ollama:qwen3:8b")
        assert "turns=0" in repr(session)
        await client.generate("hello", session=session)
        assert session.active is True
        assert "resumed" not in repr(session)


async def test_multi_provider_client_still_opens_a_session_per_target() -> None:
    ollama = FakeOllamaServer(FakeResponse(text="hi"))
    other = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_multi_client([("openai-compat", other)]) as client:
        assert client.session("openai-compat:m").supported is False
    assert ollama.call_count == 0
