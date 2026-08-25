"""The Copilot adapter, driven against a fake SDK module.

The real ``github-copilot-sdk`` is an optional extra that drives a CLI subprocess, so these
tests install a fake ``copilot`` module in ``sys.modules`` and script the event shapes the
adapter reads: attribute-style and mapping-style deltas, ``assistant.usage`` events, and
both sync and async client surfaces.
"""

from __future__ import annotations

import inspect
import sys
import types
from collections.abc import Sequence
from typing import Any

import pytest

import anyinfer as ai
from anyinfer.errors import AuthError, ConfigError, RateLimitError
from anyinfer.providers.base import AdapterFinal, ProviderConfig, WireRequest
from anyinfer.providers.copilot import AUTO_MODEL, CopilotAdapter, _split_prompt, descriptor
from anyinfer.testing.conformance import (
    Capabilities,
    ConformanceHarness,
    run_conformance,
)
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
            self.stopped = 0
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

        async def stop(self) -> None:
            # Named as the real SDK names it: a fake that answers to `close` is how a
            # rename went unnoticed, because the fake was more forgiving than the thing
            # it stands in for.
            self.stopped += 1

    class _FakeStdioRuntimeConnection:
        def __init__(self, path: str | None = None, **rest: Any) -> None:
            self.path = path

    module = types.ModuleType("copilot")
    module.CopilotClient = _FakeCopilotClient  # type: ignore[attr-defined]
    module.StdioRuntimeConnection = _FakeStdioRuntimeConnection  # type: ignore[attr-defined]
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
    assert client.stopped == 1, "aclose must shut down the SDK client and its CLI process"


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


async def test_cli_path_reaches_the_sdk_as_a_runtime_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cli_path` is a declared setup field and a documented option; it must arrive.

    The SDK takes a runtime *connection*, not a flat path. `cli_path=` was an earlier
    spelling, and today's `CopilotClient` is keyword-only with no `**kwargs`, so the old
    call raised `TypeError` for anyone who set the documented option.
    """
    instances = _install_sdk(monkeypatch)
    adapter = CopilotAdapter(
        ProviderConfig(provider_id="copilot", options={"cli_path": "/opt/bin/copilot"})
    )
    try:
        await adapter.list_models()
    finally:
        await adapter.aclose()

    options = instances[0].options
    assert "cli_path" not in options, "the flat kwarg is not a parameter of the SDK"
    assert options["connection"].path == "/opt/bin/copilot"


async def test_the_cli_path_environment_variable_takes_the_same_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = _install_sdk(monkeypatch)
    monkeypatch.setenv("COPILOT_CLI_PATH", "/from/the/environment")
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        await adapter.list_models()
    finally:
        await adapter.aclose()

    assert instances[0].options["connection"].path == "/from/the/environment"


async def test_no_cli_path_leaves_discovery_to_the_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented default is the SDK's own discovery, which means sending nothing."""
    instances = _install_sdk(monkeypatch)
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    try:
        await adapter.list_models()
    finally:
        await adapter.aclose()

    assert instances[0].options == {}


def test_the_adapter_knows_a_shutdown_method_the_real_sdk_has() -> None:
    """The client owns a spawned CLI process, and a missed shutdown leaks it in silence.

    `aclose` probes for a shutdown method by name. When the SDK renamed `close` to `stop`,
    every probe missed, `aclose` did nothing, and no error was raised — the process simply
    stayed. This asserts at least one probed name still exists on the installed SDK.
    """
    copilot = pytest.importorskip("copilot")

    available = [
        name
        for name in CopilotAdapter._SHUTDOWN_METHODS
        if getattr(copilot.CopilotClient, name, None) is not None
    ]
    assert available, (
        "no name in CopilotAdapter._SHUTDOWN_METHODS exists on CopilotClient — the SDK "
        f"renamed its shutdown API again; it now has {[n for n in dir(copilot.CopilotClient) if 'stop' in n or 'close' in n]}"
    )


async def test_aclose_shuts_the_client_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whichever spelling the SDK uses, exactly one shutdown call must reach the client."""
    instances = _install_sdk(monkeypatch)
    adapter = CopilotAdapter(ProviderConfig(provider_id="copilot"))
    await adapter.list_models()
    await adapter.aclose()

    assert instances[0].stopped == 1


async def test_aclose_falls_back_to_async_context_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If every known name disappears, the context-manager contract is the last resort."""
    exited: list[bool] = []

    class _OnlyContextManager:
        async def __aexit__(self, *exc: object) -> None:
            exited.append(True)

    await CopilotAdapter._shutdown(_OnlyContextManager())
    assert exited == [True]


def test_the_construction_kwargs_bind_against_the_real_sdk() -> None:
    """Guards the rename class itself, not just today's instance of it.

    Every other test here runs against a fake that accepts `**options`, which is more
    permissive than the real constructor — that permissiveness is exactly why a removed
    `cli_path` parameter went unnoticed. This binds what the adapter builds against the
    installed SDK's real signature, so the next rename fails here instead of in a user's
    `ProviderError`.
    """
    copilot = pytest.importorskip("copilot")

    signature = inspect.signature(copilot.CopilotClient.__init__)
    connection = copilot.StdioRuntimeConnection(path="/opt/bin/copilot")
    signature.bind(object(), connection=connection)


async def test_an_option_the_sdk_rejects_is_an_actionable_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The options block is forwarded verbatim to a constructor that takes no `**kwargs`."""
    instances = _install_sdk(monkeypatch)
    del instances

    import copilot as fake_sdk

    def _strict(**options: Any) -> None:
        raise TypeError(
            "CopilotClient.__init__() got an unexpected keyword argument 'legacy_flag'"
        )

    monkeypatch.setattr(fake_sdk, "CopilotClient", _strict)
    adapter = CopilotAdapter(
        ProviderConfig(provider_id="copilot", options={"legacy_flag": True})
    )
    with pytest.raises(ConfigError) as excinfo:
        await adapter.list_models()

    assert excinfo.value.hint is not None
    assert "github-copilot-sdk" in excinfo.value.hint


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
    assert user_prompt == ("What is 2+2?\n\n[assistant] Let me check.\n\n[tool result] 4\n\nSo?")


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


# ---- conformance -----------------------------------------------------------------------
#
# The one row in the matrix whose evidence is a fake *SDK* rather than a fake server, and
# that is the honest analogue rather than a shortcut: this adapter's boundary genuinely is
# the SDK, not HTTP, so a transport-level fake would be testing a layer the adapter never
# touches. The fake module is installed by the harness itself rather than by a pytest
# fixture, because `workspace matrix` runs these harnesses outside pytest and a row that
# only exists under the test runner is a row the published matrix cannot honestly claim.


class _ConformanceSession:
    """A session whose scripted events, and failures, follow the scenario."""

    def __init__(self, events: Sequence[Any], error: Exception | None) -> None:
        self._events = list(events)
        self._error = error
        self.closed = False

    def send(self, prompt: str) -> list[Any]:
        if self._error is not None:
            raise self._error
        return list(self._events)

    def close(self) -> None:
        self.closed = True


def _conformance_sdk(scenario: str) -> types.ModuleType:
    """A fake ``copilot`` module scripted for one conformance scenario.

    Errors are raised as plain exceptions whose *message text* carries the signal, which
    is exactly how the adapter classifies them: the SDK exposes no status codes, so
    `_classify` matches on words like "unauthorized" and "rate limit". A fake that raised
    typed errors would be testing a mapping the adapter does not have.
    """
    from anyinfer.testing.fakes import scenario_responses

    responses = scenario_responses(scenario)
    state = {"call": 0}

    class _ConformanceClient:
        def __init__(self, **options: Any) -> None:
            self.options = options

        def create_session(self, **_session_options: Any) -> _ConformanceSession:
            index = min(state["call"], len(responses) - 1)
            response = responses[index]
            state["call"] += 1

            error: Exception | None = None
            if response.status == 401:
                error = RuntimeError("unauthorized: please run copilot login")
            elif response.status == 429:
                error = RuntimeError("rate limit exceeded, too many requests")
            events: list[Any] = [
                {"text": response.text},
                {"type": "assistant.usage", "input_tokens": 11, "output_tokens": 7},
            ]
            return _ConformanceSession(events, error)

        def list_models(self) -> list[Any]:
            return [{"id": "gpt-5"}]

        def close(self) -> None:
            return None

    module = types.ModuleType("copilot")
    module.CopilotClient = _ConformanceClient  # type: ignore[attr-defined]
    return module


async def _build_copilot_client(scenario: str) -> ai.AsyncClient:
    # Installed directly rather than through monkeypatch: the harness must behave the
    # same inside pytest and inside `workspace matrix`. Nothing else in this repository
    # imports `copilot`, and the one test that needs the import to fail forces it to
    # `None` explicitly, so it is unaffected by what is installed here.
    sys.modules["copilot"] = _conformance_sdk(scenario)
    return ai.AsyncClient(
        [ai.ProviderSettings.of("copilot")],
        route=ai.Route(
            targets=("copilot:gpt-5",), retry=ai.Retry(max_attempts=2, backoff_base_s=0.0)
        ),
    )


HARNESS = ConformanceHarness(
    provider_id="copilot",
    model="gpt-5",
    build_client=_build_copilot_client,
    # Every False is a documented property of the session API, not a gap in this fake.
    # It takes a prompt and options only, so caller tool specs have no wire form at all
    # (they are in `ignored_parameters`); there is no reasoning channel and no
    # response-format field, so a schema is prompt-injected and validated client-side.
    # Nothing counts response bytes, because the adapter is handed events, not a body.
    supports=Capabilities(
        tools=False,
        reasoning=False,
        byte_cap=False,
        cancellation=False,
    ),
)


async def test_copilot_conformance() -> None:
    results = await run_conformance(HARNESS)
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, f"conformance failures: {[(f.name, f.detail) for f in failures]}"
