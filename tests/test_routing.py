"""Router behavior: retries, fallback chains, health gating, and the attempt trail."""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.errors import ContextLengthError, ProviderError
from anyinfer.registry import ProviderDescriptor, ProviderRegistry
from anyinfer.routing.policy import backoff_delay, never_retry_client_errors
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_client, make_multi_client


def _alias_registry() -> ProviderRegistry:
    """A registry exposing the openai-compat adapter under two ids, for fallback tests."""
    from anyinfer.providers.openai_compat import OpenAICompatAdapter
    from anyinfer.providers.openai_compat import descriptor as base

    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    for provider_id in ("primary", "secondary", "tertiary"):
        registry.register(
            ProviderDescriptor(
                id=provider_id,
                display_name=f"Fake {provider_id}",
                factory=OpenAICompatAdapter,
                requires_base_url=True,
                default_capabilities=base.default_capabilities,
            )
        )
    return registry


async def test_retry_then_success_records_full_trail() -> None:
    server = FakeOpenAIServer(
        [
            FakeResponse(status=503, error_message="temporarily down"),
            FakeResponse(text="recovered"),
        ]
    )
    async with make_client(server) as client:
        result = await client.generate(
            "hi",
            route=ai.Route(
                targets=("openai-compat:m",),
                retry=ai.Retry(max_attempts=2, backoff_base_s=0.0),
            ),
        )

    assert result.text == "recovered"
    assert [a.outcome for a in result.attempts] == ["retried", "ok"]
    assert result.attempts[0].error is not None
    assert result.attempts[0].error.retryable is True


async def test_non_retryable_error_does_not_retry() -> None:
    server = FakeOpenAIServer(
        [
            FakeResponse(status=401, error_message="bad key"),
            FakeResponse(text="never reached"),
        ]
    )
    async with make_client(server) as client:
        with pytest.raises(ai.AllTargetsFailedError):
            await client.generate(
                "hi",
                route=ai.Route(
                    targets=("openai-compat:m",),
                    retry=ai.Retry(max_attempts=3, backoff_base_s=0.0),
                ),
            )

    assert server.call_count == 1, "auth failures must not be retried"


async def test_fallback_advances_to_the_next_target() -> None:
    failing = FakeOpenAIServer(FakeResponse(status=500, error_message="boom"))
    healthy = FakeOpenAIServer(FakeResponse(text="from the backup"))

    client = make_multi_client(
        [("primary", failing), ("secondary", healthy)], registry=_alias_registry()
    )
    async with client:
        result = await client.generate(
            "hi",
            route=ai.Route(
                targets=("primary:m", "secondary:m"),
                retry=ai.Retry(max_attempts=1),
            ),
        )

    assert result.text == "from the backup"
    assert result.target.provider_id == "secondary"
    assert [a.outcome for a in result.attempts] == ["failed", "ok"]


async def test_all_targets_failed_carries_the_trail() -> None:
    failing = FakeOpenAIServer(FakeResponse(status=500, error_message="boom"))
    also_failing = FakeOpenAIServer(FakeResponse(status=500, error_message="boom too"))

    client = make_multi_client(
        [("primary", failing), ("secondary", also_failing)], registry=_alias_registry()
    )
    async with client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate(
                "hi",
                route=ai.Route(
                    targets=("primary:m", "secondary:m"), retry=ai.Retry(max_attempts=1)
                ),
            )

    error = excinfo.value
    assert len(error.attempts) == 2
    assert {a.target.provider_id for a in error.attempts} == {"primary", "secondary"}
    assert error.hint is not None


async def test_health_gate_skips_a_recently_failed_target() -> None:
    down = FakeOpenAIServer(FakeResponse(status=503, error_message="down"))
    healthy = FakeOpenAIServer(FakeResponse(text="ok"))

    client = make_multi_client(
        [("primary", down), ("secondary", healthy)], registry=_alias_registry()
    )
    route = ai.Route(
        targets=("primary:m", "secondary:m"),
        retry=ai.Retry(max_attempts=1),
        health_ttl_s=300.0,
    )
    async with client:
        first = await client.generate("hi", route=route)
        calls_after_first = down.call_count
        second = await client.generate("hi again", route=route)

    assert first.text == "ok"
    assert second.text == "ok"
    assert down.call_count == calls_after_first, "unhealthy target should be skipped"
    assert second.attempts[0].outcome == "skipped_unhealthy"


async def test_health_gate_can_be_disabled() -> None:
    down = FakeOpenAIServer(FakeResponse(status=503, error_message="down"))
    healthy = FakeOpenAIServer(FakeResponse(text="ok"))

    client = make_multi_client(
        [("primary", down), ("secondary", healthy)], registry=_alias_registry()
    )
    route = ai.Route(
        targets=("primary:m", "secondary:m"),
        retry=ai.Retry(max_attempts=1),
        health_gate=False,
    )
    async with client:
        await client.generate("hi", route=route)
        before = down.call_count
        await client.generate("hi again", route=route)

    assert down.call_count > before, "gate disabled: the failing target is retried"


async def test_retry_after_header_is_honored() -> None:
    server = FakeOpenAIServer(
        [
            FakeResponse(status=429, error_message="slow down", headers={"retry-after": "0"}),
            FakeResponse(text="ok"),
        ]
    )
    async with make_client(server) as client:
        result = await client.generate(
            "hi",
            route=ai.Route(
                targets=("openai-compat:m",), retry=ai.Retry(max_attempts=2, backoff_base_s=0.0)
            ),
        )

    assert result.text == "ok"
    assert result.attempts[0].error is not None
    assert result.attempts[0].error.type_name == "RateLimitError"


def test_backoff_is_exponential_and_capped() -> None:
    retry = ai.Retry(backoff_base_s=1.0, backoff_max_s=4.0)
    assert backoff_delay(1, retry) == 1.0
    assert backoff_delay(2, retry) == 2.0
    assert backoff_delay(3, retry) == 4.0
    assert backoff_delay(9, retry) == 4.0, "capped"


def test_backoff_honors_a_longer_retry_after() -> None:
    retry = ai.Retry(backoff_base_s=0.5, backoff_max_s=30.0)
    assert backoff_delay(1, retry, retry_after_s=7.0) == 7.0


def test_default_retry_predicate_declines_deterministic_failures() -> None:
    assert never_retry_client_errors(ai.AuthError("nope", retryable=True)) is False
    assert never_retry_client_errors(ContextLengthError("too big", retryable=True)) is False
    assert never_retry_client_errors(ProviderError("blip", retryable=True)) is True


async def test_context_window_fallback_chain_is_used_on_overflow() -> None:
    overflowing = FakeOpenAIServer(
        FakeResponse(status=422, error_message="maximum context length exceeded")
    )
    roomy = FakeOpenAIServer(FakeResponse(text="fits here"))

    client = make_multi_client(
        [("primary", overflowing), ("secondary", roomy), ("tertiary", roomy)],
        registry=_alias_registry(),
    )
    async with client:
        result = await client.generate(
            "a very long prompt",
            route=ai.Route(
                targets=("primary:m",),
                retry=ai.Retry(max_attempts=1),
                context_window_targets=("tertiary:big-model",),
            ),
        )

    assert result.text == "fits here"
    assert result.target.provider_id == "tertiary"


# ---- content-policy redirect ---------------------------------------------------------


def _three_provider_client(
    primary: FakeOpenAIServer,
    secondary: FakeOpenAIServer,
    tertiary: FakeOpenAIServer | None = None,
) -> ai.AsyncClient:
    registry = _alias_registry()
    tertiary = tertiary or FakeOpenAIServer(FakeResponse(text="unused"))
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "primary", base_url="https://a.invalid/v1", transport=primary.transport()
            ),
            ai.ProviderSettings.of(
                "secondary", base_url="https://b.invalid/v1", transport=secondary.transport()
            ),
            ai.ProviderSettings.of(
                "tertiary", base_url="https://c.invalid/v1", transport=tertiary.transport()
            ),
        ],
        registry=registry,
    )


async def test_content_filter_redirects_to_the_content_policy_chain() -> None:
    refusing = FakeOpenAIServer(
        FakeResponse(text="I cannot help with that.", finish_reason="content_filter")
    )
    permissive = FakeOpenAIServer(FakeResponse(text="an answer"))

    async with _three_provider_client(refusing, permissive) as client:
        result = await client.generate(
            "hi",
            route=ai.Route(
                targets=("primary:m",),
                retry=ai.Retry(max_attempts=1),
                content_policy_targets=("secondary:m",),
            ),
        )

    assert result.text == "an answer"
    assert result.target.provider_id == "secondary"
    assert [a.outcome for a in result.attempts] == ["redirected", "ok"]


async def test_content_filter_without_a_chain_surfaces_the_refusal() -> None:
    refusing = FakeOpenAIServer(
        FakeResponse(text="I cannot help with that.", finish_reason="content_filter")
    )
    async with make_client(refusing) as client:
        result = await client.generate("hi", target="openai-compat:m")

    assert result.finish_reason == "content_filter"
    assert result.text == "I cannot help with that."


async def test_content_filter_redirects_at_most_once() -> None:
    refusing_a = FakeOpenAIServer(FakeResponse(text="no.", finish_reason="content_filter"))
    refusing_b = FakeOpenAIServer(FakeResponse(text="also no.", finish_reason="content_filter"))

    async with _three_provider_client(refusing_a, refusing_b) as client:
        result = await client.generate(
            "hi",
            route=ai.Route(
                targets=("primary:m",),
                retry=ai.Retry(max_attempts=1),
                content_policy_targets=("secondary:m",),
            ),
        )

    # The chain's own refusal surfaces rather than looping.
    assert result.finish_reason == "content_filter"
    assert result.target.provider_id == "secondary"


# ---- flexible route spellings --------------------------------------------------------


async def test_route_accepts_a_bare_target_string() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hello"))
    async with make_client(server) as client:
        result = await client.generate("hi", route="openai-compat:m")
    assert result.text == "hello"


async def test_route_accepts_a_sequence_of_targets_as_a_fallback_chain() -> None:
    failing = FakeOpenAIServer(FakeResponse(status=500, error_message="down"))
    healthy = FakeOpenAIServer(FakeResponse(text="from the backup"))

    async with _three_provider_client(failing, healthy) as client:
        result = await client.generate("hi", route=["primary:m", "secondary:m"])

    assert result.text == "from the backup"
    assert result.target.provider_id == "secondary"


# ---- policy inheritance across the route spellings -----------------------------------
#
# Naming a target says *where* a call goes, not *how* it is governed. These four pin that
# down, because the alternative -- a target-shaped override silently reverting to stock
# `Retry()` -- is invisible at the call site and was live long enough to make the
# conformance suite sleep through backoff it had explicitly configured away.


async def test_a_bare_target_inherits_the_clients_retry_policy() -> None:
    """`target=` redirects the call; it does not opt the caller out of their own policy."""
    server = FakeOpenAIServer(
        [
            FakeResponse(status=503, error_message="down"),
            FakeResponse(status=503, error_message="still down"),
            FakeResponse(text="third time lucky"),
        ]
    )
    # Stock `Retry()` allows two attempts, so this only survives if max_attempts=3 carries.
    async with make_client(
        server,
        route=ai.Route(
            targets=("openai-compat:m",),
            retry=ai.Retry(max_attempts=3, backoff_base_s=0.0),
        ),
    ) as client:
        result = await client.generate("hi", target="openai-compat:m")

    assert result.text == "third time lucky"
    assert [a.outcome for a in result.attempts] == ["retried", "retried", "ok"]


async def test_a_target_shaped_route_string_inherits_the_clients_retry_policy() -> None:
    """The string spelling of ``route`` names targets only, so it inherits policy too."""
    server = FakeOpenAIServer(
        [
            FakeResponse(status=503, error_message="down"),
            FakeResponse(status=503, error_message="still down"),
            FakeResponse(text="recovered"),
        ]
    )
    async with make_client(
        server,
        route=ai.Route(
            targets=("openai-compat:m",),
            retry=ai.Retry(max_attempts=3, backoff_base_s=0.0),
        ),
    ) as client:
        result = await client.generate("hi", route="openai-compat:m")

    assert result.text == "recovered"


async def test_an_explicit_route_object_overrides_the_clients_policy_exactly() -> None:
    """A constructed `Route` is a complete statement of policy, not a partial one."""
    server = FakeOpenAIServer(
        [
            FakeResponse(status=503, error_message="down"),
            FakeResponse(text="never reached"),
        ]
    )
    async with make_client(
        server,
        route=ai.Route(
            targets=("openai-compat:m",),
            retry=ai.Retry(max_attempts=3, backoff_base_s=0.0),
        ),
    ) as client:
        with pytest.raises(ai.errors.AllTargetsFailedError):
            await client.generate(
                "hi",
                route=ai.Route(targets=("openai-compat:m",), retry=ai.Retry(max_attempts=1)),
            )


async def test_a_bare_target_does_not_inherit_the_specialized_chains() -> None:
    """Policy knobs carry; other people's targets do not.

    Inheriting ``context_window_targets`` would send the call to a provider the caller
    did not name -- the same surprise this inheritance exists to remove, pointing the
    other way.
    """
    overflowing = FakeOpenAIServer(
        FakeResponse(status=422, error_message="maximum context length exceeded")
    )
    roomy = FakeOpenAIServer(FakeResponse(text="fits here"))

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "primary", base_url="https://a.invalid/v1", transport=overflowing.transport()
            ),
            ai.ProviderSettings.of(
                "tertiary", base_url="https://c.invalid/v1", transport=roomy.transport()
            ),
        ],
        registry=_alias_registry(),
        route=ai.Route(
            targets=("primary:m",),
            retry=ai.Retry(max_attempts=1),
            context_window_targets=("tertiary:big-model",),
        ),
    )
    async with client:
        with pytest.raises(ai.errors.AllTargetsFailedError) as failure:
            await client.generate("a very long prompt", target="primary:m")

    # The overflow surfaced instead of being redirected, and nothing tried `tertiary`.
    attempts = failure.value.attempts
    assert [a.target.provider_id for a in attempts] == ["primary"]
    assert attempts[0].error is not None
    assert attempts[0].error.type_name == "ContextLengthError"


# ---- attempt timeout -----------------------------------------------------------------


async def test_attempt_timeout_is_a_typed_retryable_transport_error() -> None:
    import asyncio as _asyncio

    import httpx2 as _httpx2

    async def stall(request: _httpx2.Request) -> _httpx2.Response:
        await _asyncio.sleep(30.0)
        raise AssertionError("unreachable")

    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=_httpx2.MockTransport(stall),
            )
        ]
    )
    async with client:
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate(
                "hi",
                route=ai.Route(targets=("openai-compat:m",), retry=ai.Retry(max_attempts=1)),
                timeout_s=0.05,
            )

    error = excinfo.value.attempts[-1].error
    assert error is not None
    assert error.type_name == "TransportError", "a timeout must not escape as TimeoutError"
    assert error.retryable is True
