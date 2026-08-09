"""Provider runtime diagnostics: declaration, collection, and failure tolerance (D36)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

import anyinfer as ai
from anyinfer.providers.openai_compat import OpenAICompatAdapter
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.results import Diagnostic
from support import make_multi_client

SPILL = Diagnostic(code="fake.spill", severity="warning", message="the model spilled")


class _Recorder:
    """Collects telemetry events for assertions."""

    def __init__(self) -> None:
        self.events: list[ai.TelemetryEvent] = []

    def on_event(self, event: ai.TelemetryEvent) -> None:
        self.events.append(event)


def _adapter_reporting(reported: object) -> type:
    """An openai-compat adapter whose ``diagnostics()`` returns or raises ``reported``."""

    class Reporting(OpenAICompatAdapter):
        async def diagnostics(self) -> Sequence[Diagnostic]:
            if isinstance(reported, BaseException):
                raise reported
            return reported  # type: ignore[return-value]

    return Reporting


def _registry(
    *, declares: bool, reported: object = (SPILL,), implement: bool = True
) -> ai.ProviderRegistry:
    """One registration, varying what it declares and what it actually implements."""
    registry = ai.ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ai.ProviderDescriptor(
            id="noisy",
            display_name="Fake noisy",
            factory=_adapter_reporting(reported) if implement else OpenAICompatAdapter,
            requires_base_url=True,
            reports_diagnostics=declares,
        )
    )
    return registry


# ---- the type ------------------------------------------------------------------------


def test_diagnostic_is_content_free_by_construction() -> None:
    assert set(Diagnostic.__dataclass_fields__) == {"code", "severity", "message"}


# ---- collection during a request -----------------------------------------------------


async def test_diagnostics_land_on_the_result_warnings() -> None:
    server = FakeOpenAIServer(FakeResponse(text="fine"))
    async with make_multi_client([("noisy", server)], registry=_registry(declares=True)) as c:
        result = await c.generate("hi", target="noisy:m")

    assert result.text == "fine", "a diagnostic annotates a success, it does not replace it"
    assert "the model spilled" in result.warnings


async def test_diagnostics_are_emitted_as_telemetry_correlated_to_the_request() -> None:
    recorder = _Recorder()
    server = FakeOpenAIServer(FakeResponse(text="fine"))
    async with make_multi_client(
        [("noisy", server)], registry=_registry(declares=True), observers=[recorder]
    ) as client:
        await client.generate("hi", target="noisy:m")

    emitted = [e for e in recorder.events if isinstance(e, ai.ProviderDiagnostic)]
    assert len(emitted) == 1
    assert emitted[0].diagnostic == SPILL
    assert emitted[0].request_id is not None, "collected in a request, so it correlates"
    assert emitted[0].target is not None and emitted[0].target.provider_id == "noisy"


async def test_a_provider_that_does_not_declare_is_never_asked() -> None:
    server = FakeOpenAIServer(FakeResponse(text="fine"))
    async with make_multi_client([("noisy", server)], registry=_registry(declares=False)) as c:
        result = await c.generate("hi", target="noisy:m")

    assert result.warnings == (), "the flag is the switch, not the presence of the method"


# ---- failure tolerance ---------------------------------------------------------------


@pytest.mark.parametrize(
    "reported",
    [
        RuntimeError("the probe blew up"),
        None,  # not a sequence at all
        ("a bare string, not a Diagnostic",),
    ],
    ids=["raises", "wrong-type", "wrong-element-type"],
)
async def test_a_broken_diagnostic_never_fails_the_request(reported: object) -> None:
    server = FakeOpenAIServer(FakeResponse(text="fine"))
    async with make_multi_client(
        [("noisy", server)], registry=_registry(declares=True, reported=reported)
    ) as client:
        result = await client.generate("hi", target="noisy:m")

    assert result.text == "fine"
    assert result.warnings == ()


async def test_declaring_without_implementing_is_tolerated() -> None:
    server = FakeOpenAIServer(FakeResponse(text="fine"))
    async with make_multi_client(
        [("noisy", server)], registry=_registry(declares=True, implement=False)
    ) as client:
        result = await client.generate("hi", target="noisy:m")

    assert result.text == "fine"


# ---- the direct accessor -------------------------------------------------------------


async def test_client_diagnostics_asks_without_generating() -> None:
    recorder = _Recorder()
    server = FakeOpenAIServer()
    async with make_multi_client(
        [("noisy", server)], registry=_registry(declares=True), observers=[recorder]
    ) as client:
        reported = await client.diagnostics("noisy")

    assert list(reported) == [SPILL]
    assert server.call_count == 0
    standalone = [e for e in recorder.events if isinstance(e, ai.ProviderDiagnostic)]
    assert standalone and standalone[0].request_id is None
    assert standalone[0].target is None


async def test_client_diagnostics_is_empty_for_a_quiet_provider() -> None:
    server = FakeOpenAIServer()
    async with make_multi_client([("noisy", server)], registry=_registry(declares=False)) as c:
        assert list(await c.diagnostics("noisy")) == []


def test_sync_client_diagnostics() -> None:
    server = FakeOpenAIServer()
    client = ai.Client(
        [
            ai.ProviderSettings.of(
                "noisy", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        registry=_registry(declares=True),
    )
    try:
        assert list(client.diagnostics("noisy")) == [SPILL]
    finally:
        client.close()


# ---- capability-driven parameter dropping --------------------------------------------


def _reasoning_registry(features: object, provenance: str) -> ai.ProviderRegistry:
    """A registration whose model capabilities claim (or deny) reasoning support."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.types.capabilities import ModelCapabilities, Sourced

    registry = ai.ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ai.ProviderDescriptor(
            id="thinker",
            display_name="Fake thinker",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            reasoning_translator=lambda e: {} if e is None else {"reasoning_effort": e},
            static_capabilities={
                "m": ModelCapabilities(features=Sourced(features, provenance))  # type: ignore[arg-type]
            },
        )
    )
    return registry


async def test_reasoning_is_withheld_from_a_model_known_not_to_have_it() -> None:
    """Sending it anyway is the silently-ignored case the library exists to eliminate."""
    from anyinfer.types.capabilities import Feature

    recorder = _Recorder()
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_multi_client(
        [("thinker", server)],
        registry=_reasoning_registry(Feature.STREAMING, "discovered"),
        observers=[recorder],
    ) as client:
        await client.generate("hi", target="thinker:m", reasoning="high")

    assert "reasoning_effort" not in server.requests[0]
    dropped = [
        e for e in recorder.events
        if isinstance(e, ai.ParameterDropped) and e.parameter == "reasoning"
    ]
    assert len(dropped) == 1


async def test_reasoning_reaches_a_model_that_has_it() -> None:
    from anyinfer.types.capabilities import Feature

    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_multi_client(
        [("thinker", server)],
        registry=_reasoning_registry(Feature.STREAMING | Feature.REASONING, "discovered"),
    ) as client:
        await client.generate("hi", target="thinker:m", reasoning="high")

    assert server.requests[0]["reasoning_effort"] == "high"


async def test_a_guessed_absence_never_withholds_the_parameter() -> None:
    """Dropping a caller's parameter on a descriptor-level guess is worse than sending it."""
    from anyinfer.types.capabilities import Feature

    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_multi_client(
        [("thinker", server)],
        registry=_reasoning_registry(Feature.STREAMING, "default"),
    ) as client:
        await client.generate("hi", target="thinker:m", reasoning="high")

    assert server.requests[0]["reasoning_effort"] == "high"
