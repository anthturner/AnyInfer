"""Private time seam coverage at the routed AsyncClient boundary."""

from __future__ import annotations

import asyncio

import pytest

import anyinfer as ai
import anyinfer._client.generation as generation
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_client


async def test_injected_sleep_observes_retry_backoff_and_advances_virtual_time() -> None:
    """The private sleeper receives the production backoff duration."""
    clock = [0.0]
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)
        clock[0] += delay

    server = FakeOpenAIServer(
        [FakeResponse(status=503, error_message="temporary"), FakeResponse(text="recovered")]
    )
    async with make_client(server, _clock=lambda: clock[0], _sleep=sleep) as client:
        result = await client.generate(
            "hi",
            route=ai.Route(
                targets=("openai-compat:m",),
                retry=ai.Retry(max_attempts=2, backoff_base_s=1.25),
            ),
        )

    assert result.text == "recovered"
    assert [attempt.outcome for attempt in result.attempts] == ["retried", "ok"]
    assert delays == [1.25]
    assert clock == [1.25]


async def test_injected_clock_controls_native_health_cache_expiry() -> None:
    """HealthCache keeps its public expiry behavior when the client supplies its clock."""
    clock = [0.0]
    server = FakeOpenAIServer(FakeResponse(text="unused"))
    async with make_client(server, _clock=lambda: clock[0]) as client:
        target = client.resolve("openai-compat:m")
        client._health.mark_failed(target, "test")
        clock[0] = 59.0
        assert client._health.recently_failed(target, 60.0)
        clock[0] = 60.0
        assert not client._health.recently_failed(target, 60.0)


async def test_default_and_explicit_none_keep_native_sleep_and_attempt_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default path and explicit ``None`` remain observationally equivalent."""
    original_sleep = asyncio.sleep
    delays: list[float] = []

    async def spy_sleep(delay: float, result: object = None) -> object:
        delays.append(delay)
        return await original_sleep(0, result)

    monkeypatch.setattr(generation.asyncio, "sleep", spy_sleep)

    async def generate(*, explicit_none: bool) -> ai.GenerationResult:
        server = FakeOpenAIServer(
            [FakeResponse(status=503, error_message="temporary"), FakeResponse(text="recovered")]
        )
        kwargs: dict[str, object] = {"_sleep": None} if explicit_none else {}
        async with make_client(server, **kwargs) as client:
            return await client.generate(
                "hi",
                route=ai.Route(
                    targets=("openai-compat:m",),
                    retry=ai.Retry(max_attempts=2, backoff_base_s=0.25),
                ),
            )

    default = await generate(explicit_none=False)
    explicit_none = await generate(explicit_none=True)

    assert default.text == explicit_none.text == "recovered"
    assert [attempt.outcome for attempt in default.attempts] == ["retried", "ok"]
    assert [attempt.outcome for attempt in explicit_none.attempts] == ["retried", "ok"]
    assert delays == [0.25, 0.25]
