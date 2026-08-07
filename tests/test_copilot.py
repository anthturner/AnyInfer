"""The Copilot adapter, driven against a fake SDK module.

The real ``github-copilot-sdk`` is an optional extra that drives a CLI subprocess, so these
tests install a fake ``copilot`` module in ``sys.modules`` and script the event shapes the
adapter reads: attribute-style and mapping-style deltas, ``assistant.usage`` events, and
both sync and async client surfaces.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Sequence
from typing import Any

import pytest

import anyinfer as ai
from anyinfer.errors import AuthError, ConfigError, RateLimitError
from anyinfer.providers.base import AdapterFinal, ProviderConfig, WireRequest
from anyinfer.providers.copilot import AUTO_MODEL, CopilotAdapter, _split_prompt, descriptor
from anyinfer.types.messages import Message, ToolResult


def _request(**overrides: Any) -> WireRequest:
    defaults: dict[str, Any] = {"model": AUTO_MODEL, "messages": (ai.user("hi"),)}
    defaults.update(overrides)
    return WireRequest(**defaults)


class _FakeSession:
    """Scripted session whose ``send`` returns a plain iterable of events."""

    def __init__(self, events: Sequence[Any]) -> None:
        self._events = list(events)
        self.prompts: list[str] = []
        self.closed = False

    def send(self, prompt: str) -> list[Any]:
        self.prompts.append(prompt)
        return list(self._events)

    def close(self) -> None:
        self.closed = True


def _install_sdk(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: Sequence[Any] = (),
    models: Sequence[Any] = (),
    create_session_error: Exception | None = None,
    list_models_error: Exception | None = None,
) -> list[Any]:
    """Install a fake ``copilot`` module, returning the client instances it creates."""
    instances: list[Any] = []

    class _FakeCopilotClient:
        def __init__(self, **options: Any) -> None:
            self.options = options
            self.session_options: dict[str, Any] = {}
            self.sessions: list[_FakeSession] = []
            self.closed = False
            instances.append(self)

        def create_session(self, **session_options: Any) -> _FakeSession:
            if create_session_error is not None:
                raise create_session_error
            self.session_options = session_options
            session = _FakeSession(events)
            self.sessions.append(session)
            return session

        def list_models(self) -> list[Any]:
            if list_models_error is not None:
                raise list_models_error
            return list(models)

        def close(self) -> None:
            self.closed = True

    module = types.ModuleType("copilot")
    module.CopilotClient = _FakeCopilotClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "copilot", module)
    # The adapter consults this variable when building the client; a developer machine
    # that happens to export it must not leak into the fake's options.
    monkeypatch.delenv("COPILOT_CLI_PATH", raising=False)
    return instances


# ---- generation ----------------------------------------------------------------------


async def test_generate_yields_text_deltas_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deltas may be attributes or mapping keys; usage rides an assistant.usage event."""
    instances = _install_sdk(
        monkeypatch,
        events=[
            types.SimpleNamespace(delta="Hel"),
            {"text": "lo"},
            {"type": "assistant.usage", "input_tokens": 3, "output_tokens": 5},
        ],
    )
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        received = [event async for event in adapter.generate(_request())]
    finally:
        await adapter.aclose()

    deltas = [e for e in received if isinstance(e, ai.TextDelta)]
    assert "".join(d.text for d in deltas) == "Hello"

    final = received[-1]
    assert isinstance(final, AdapterFinal)
    assert final.finish_reason == "stop"
    assert final.usage is not None
    assert final.usage.input_tokens == 3
    assert final.usage.output_tokens == 5
    assert final.usage.total_tokens == 8, "usage must arrive normalized"

    client = instances[0]
    assert client.sessions[0].prompts == ["hi"]
    assert client.sessions[0].closed is True, "the session is torn down after the turn"
    assert client.closed is True, "aclose must shut down the SDK client"


async def test_async_sdk_surfaces_are_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Newer SDK versions are async end to end; the adapter must accept both shapes."""

    class _AsyncSession:
        def __init__(self) -> None:
            self.closed = False

        async def send(self, prompt: str) -> Any:
            async def _events() -> Any:
                yield {"delta": "as"}
                yield {"delta": "ync"}

            return _events()

        async def aclose(self) -> None:
            self.closed = True

    sessions: list[_AsyncSession] = []

    class _AsyncClient:
        def __init__(self, **options: Any) -> None:
            self.options = options

        async def create_session(self, **session_options: Any) -> _AsyncSession:
            session = _AsyncSession()
            sessions.append(session)
            return session

        async def aclose(self) -> None:
            return None

    module = types.ModuleType("copilot")
    module.CopilotClient = _AsyncClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "copilot", module)
    monkeypatch.delenv("COPILOT_CLI_PATH", raising=False)

    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        received = [event async for event in adapter.generate(_request())]
    finally:
        await adapter.aclose()

    text = "".join(e.text for e in received if isinstance(e, ai.TextDelta))
    assert text == "async"
    assert sessions[0].closed is True


async def test_reasoning_wire_lands_in_session_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = _install_sdk(monkeypatch, events=[{"text": "ok"}])
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        request = _request(reasoning_wire={"reasoning_effort": "high"})
        async for _ in adapter.generate(request):
            pass
    finally:
        await adapter.aclose()

    options = instances[0].session_options
    assert options["model"] == AUTO_MODEL
    assert options["reasoning_effort"] == "high"


def test_reasoning_translator_produces_the_wire_field() -> None:
    assert descriptor.reasoning_translator is not None
    assert descriptor.reasoning_translator("high") == {"reasoning_effort": "high"}
    assert descriptor.reasoning_translator(None) == {}


# ---- SDK import and error mapping ----------------------------------------------------


async def test_missing_sdk_is_a_config_error_with_an_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "copilot", raising=False)
    monkeypatch.setitem(sys.modules, "copilot", None)  # makes ``import copilot`` fail

    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    with pytest.raises(ConfigError) as excinfo:
        await adapter.list_models()

    assert excinfo.value.hint is not None
    assert "anyinfer[copilot]" in excinfo.value.hint


async def test_unauthorized_failures_map_to_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_sdk(
        monkeypatch,
        create_session_error=RuntimeError("401 unauthorized: token expired"),
    )
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        with pytest.raises(AuthError) as excinfo:
            async for _ in adapter.generate(_request()):
                pass
    finally:
        await adapter.aclose()

    assert excinfo.value.hint is not None
    assert "copilot login" in excinfo.value.hint


async def test_rate_limits_map_to_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_sdk(monkeypatch, list_models_error=RuntimeError("rate limit exceeded"))
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        with pytest.raises(RateLimitError):
            await adapter.list_models()
    finally:
        await adapter.aclose()


# ---- prompt folding ------------------------------------------------------------------


def test_split_prompt_folds_history_and_lifts_system_messages() -> None:
    """The session API takes one turn, so prior turns fold in rather than being dropped."""
    request = _request(
        messages=(
            ai.system("Be terse."),
            ai.user("What is 2+2?"),
            ai.assistant("Let me check."),
            Message(role="tool", content=(ToolResult(call_id="c1", content="4"),)),
            ai.user("So?"),
        )
    )

    system_prompt, user_prompt = _split_prompt(request)

    assert system_prompt == "Be terse."
    assert user_prompt == (
        "What is 2+2?\n\n[assistant] Let me check.\n\n[tool result] 4\n\nSo?"
    )


# ---- discovery -----------------------------------------------------------------------


async def test_list_models_inserts_the_auto_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_sdk(monkeypatch, models=["model-a", {"id": "model-b"}])
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    assert [m.id for m in models] == [AUTO_MODEL, "model-a", "model-b"]
    sentinel = models[0]
    assert sentinel.capabilities is not None
    assert sentinel.capabilities.features.provenance == "default", (
        "auto's capabilities are a conjunction claim, never presented as discovered"
    )


async def test_list_models_does_not_duplicate_an_existing_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_sdk(monkeypatch, models=["auto", "model-a"])
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        models = await adapter.list_models()
    finally:
        await adapter.aclose()

    assert [m.id for m in models].count(AUTO_MODEL) == 1


# ---- descriptor ----------------------------------------------------------------------


def test_descriptor_declares_the_parameters_it_ignores() -> None:
    """Silently-ignored parameters are the worst failure mode; these are declared."""
    assert descriptor.ignored_parameters == (
        "temperature",
        "top_p",
        "max_output_tokens",
        "stop",
        "tools",
    )


def test_descriptor_features_exclude_tools() -> None:
    """Tool specs have no wire form here, so TOOLS must never be claimed."""
    capabilities = descriptor.default_capabilities
    assert capabilities is not None
    features = capabilities.features.value
    assert ai.Feature.TOOLS not in features
    assert ai.Feature.STREAMING in features
    assert ai.Feature.SYSTEM_PROMPT in features
