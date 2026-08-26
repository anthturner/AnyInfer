"""Client-side pacing, proved with a fake clock and no network.

Every test here drives `RateLimiter` with an injected clock and sleep, so a "one request per
second" cap is asserted against arithmetic rather than against wall time. A test that slept
for real would be slow and flaky in the same change.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest

import anyinfer as ai
from anyinfer.routing.limits import (
    MAX_HEADER_WAIT_S,
    AttemptPacing,
    GoverningTransport,
    RateLimiter,
    governed_attempt,
    parse_reset_seconds,
)
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.capabilities import RateLimitHeaders

OPENAI_DIALECT = RateLimitHeaders(
    requests_remaining="x-ratelimit-remaining-requests",
    requests_reset="x-ratelimit-reset-requests",
    tokens_remaining="x-ratelimit-remaining-tokens",
    tokens_reset="x-ratelimit-reset-tokens",
    limit_requests="x-ratelimit-limit-requests",
    limit_tokens="x-ratelimit-limit-tokens",
)


class FakeClock:
    """A monotonic clock that only moves when something sleeps on it."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        # Yield so other tasks make progress, as a real sleep would.
        await asyncio.sleep(0)

    @property
    def total_slept(self) -> float:
        return sum(self.slept)


def _limiter(limits: ai.RateLimits, **kwargs: Any) -> tuple[RateLimiter, FakeClock, list[Any]]:
    clock = FakeClock()
    events: list[Any] = []
    limiter = RateLimiter(
        limits,
        provider_id=kwargs.pop("provider_id", "openai"),
        events=events.append,
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )
    return limiter, clock, events


# ---- the inert default ----------------------------------------------------------------


def test_default_limits_are_inert() -> None:
    """The load-bearing acceptance criterion: unconfigured means unchanged."""
    assert ai.RateLimits(respect_headers=False).active is False


def test_a_bare_policy_means_pace_by_what_the_provider_reports() -> None:
    assert ai.RateLimits().active is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_concurrent": 0},
        {"max_concurrent": -1},
        {"requests_per_minute": 0},
        {"requests_per_minute": -5.0},
        {"min_interval_s": -0.1},
        {"reserve_fraction": -0.1},
        {"reserve_fraction": 1.0},
        {"reserve_fraction": 2.0},
    ],
)
def test_unenforceable_limits_are_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ai.RateLimits(**kwargs)


# ---- concurrency ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrency_never_exceeds_the_bound() -> None:
    limiter, _, _ = _limiter(ai.RateLimits(max_concurrent=3, respect_headers=False))
    in_flight = 0
    peak = 0
    release = asyncio.Event()

    async def one() -> None:
        nonlocal in_flight, peak
        async with limiter.slot():
            in_flight += 1
            peak = max(peak, in_flight)
            await release.wait()
            in_flight -= 1

    tasks = [asyncio.create_task(one()) for _ in range(12)]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert peak == 3

    release.set()
    await asyncio.gather(*tasks)
    assert peak == 3


# ---- rate and interval ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_requests_per_minute_cap_paces_to_the_expected_wall_time() -> None:
    """60/min is one per second: four requests cost three seconds of waiting."""
    limiter, clock, _ = _limiter(ai.RateLimits(requests_per_minute=60.0, respect_headers=False))

    for _ in range(4):
        async with limiter.slot():
            pass

    assert clock.total_slept == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_min_interval_spaces_dispatches() -> None:
    limiter, clock, _ = _limiter(ai.RateLimits(min_interval_s=0.25, respect_headers=False))

    for _ in range(3):
        async with limiter.slot():
            pass

    assert clock.slept == [pytest.approx(0.25), pytest.approx(0.25)]


# ---- provider-reported windows --------------------------------------------------------


@pytest.mark.asyncio
async def test_an_exhausted_window_delays_by_the_stated_reset() -> None:
    limiter, clock, _ = _limiter(ai.RateLimits(), dialect=OPENAI_DIALECT)
    limiter.observe(
        {
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-reset-requests": "12s",
        }
    )

    async with limiter.slot():
        pass

    assert clock.total_slept == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_a_healthy_window_delays_nothing() -> None:
    limiter, clock, _ = _limiter(ai.RateLimits(), dialect=OPENAI_DIALECT)
    limiter.observe(
        {
            "x-ratelimit-remaining-requests": "500",
            "x-ratelimit-reset-requests": "12s",
        }
    )

    async with limiter.slot():
        pass

    assert clock.slept == []


@pytest.mark.asyncio
async def test_respect_headers_false_ignores_the_same_headers() -> None:
    limiter, clock, _ = _limiter(ai.RateLimits(respect_headers=False), dialect=OPENAI_DIALECT)
    limiter.observe(
        {
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-reset-requests": "12s",
        }
    )

    async with limiter.slot():
        pass

    assert clock.slept == []


@pytest.mark.asyncio
async def test_reserve_fraction_stops_early_leaving_headroom() -> None:
    """10% of a 1000-request window means stopping with 100 left, not with none."""
    limiter, clock, _ = _limiter(ai.RateLimits(reserve_fraction=0.1), dialect=OPENAI_DIALECT)
    limiter.observe(
        {
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": "100",
            "x-ratelimit-reset-requests": "30s",
        }
    )

    async with limiter.slot():
        pass

    assert clock.total_slept == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_a_reserve_without_a_stated_limit_takes_no_fraction() -> None:
    """Reserving a share of an unknown allowance would throttle against a made-up number."""
    limiter, clock, _ = _limiter(ai.RateLimits(reserve_fraction=0.5), dialect=OPENAI_DIALECT)
    limiter.observe(
        {
            "x-ratelimit-remaining-requests": "5",
            "x-ratelimit-reset-requests": "30s",
        }
    )

    async with limiter.slot():
        pass

    assert clock.slept == []


@pytest.mark.asyncio
async def test_a_long_window_is_clamped_rather_than_waited_out() -> None:
    limiter, clock, _ = _limiter(ai.RateLimits(), dialect=OPENAI_DIALECT)
    limiter.observe(
        {
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-reset-requests": "2h",
        }
    )

    async with limiter.slot():
        pass

    assert clock.total_slept == pytest.approx(MAX_HEADER_WAIT_S)


@pytest.mark.asyncio
async def test_an_undeclared_dialect_reads_nothing() -> None:
    limiter, clock, events = _limiter(ai.RateLimits())
    limiter.observe({"x-ratelimit-remaining-requests": "0"})

    async with limiter.slot():
        pass

    assert clock.slept == []
    assert not [e for e in events if isinstance(e, ai.RateLimitObserved)]


# ---- degradation is reported ----------------------------------------------------------


def test_a_provider_with_no_dialect_reports_why_headers_cannot_be_honoured() -> None:
    limiter, _, _ = _limiter(ai.RateLimits())
    assert limiter.unsupported_headers_reason == "this provider publishes no rate-limit headers"


def test_a_half_declared_dialect_is_refused_rather_than_half_used() -> None:
    limiter, _, _ = _limiter(
        ai.RateLimits(),
        dialect=RateLimitHeaders(requests_remaining="x-remaining"),
    )
    assert limiter.reads_headers is False
    assert "no window reset" in (limiter.unsupported_headers_reason or "")


def test_an_sdk_provider_says_its_responses_are_never_seen() -> None:
    limiter, _, _ = _limiter(ai.RateLimits(), dialect=OPENAI_DIALECT, sees_responses=False)
    assert limiter.reads_headers is False
    assert "builds its own transport" in (limiter.unsupported_headers_reason or "")


def test_not_asking_for_header_pacing_is_not_a_degradation() -> None:
    limiter, _, _ = _limiter(ai.RateLimits(respect_headers=False))
    assert limiter.unsupported_headers_reason is None


# ---- events and attribution -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_wait_is_attributed_to_the_request_that_paid_for_it() -> None:
    limiter, _, events = _limiter(ai.RateLimits(requests_per_minute=60.0, respect_headers=False))

    async with limiter.slot():
        pass  # spends the one available token

    with governed_attempt("req-42") as pacing:
        async with limiter.slot():
            pass

    assert pacing.waited_s == pytest.approx(1.0)
    assert pacing.reasons == ("interval",)
    waited = [e for e in events if isinstance(e, ai.RateLimitWaited)]
    assert [(e.request_id, e.reason) for e in waited] == [("req-42", "interval")]


@pytest.mark.asyncio
async def test_a_wait_outside_a_request_still_reports_itself() -> None:
    limiter, _, events = _limiter(ai.RateLimits(requests_per_minute=60.0, respect_headers=False))

    for _ in range(2):
        async with limiter.slot():
            pass

    waited = [e for e in events if isinstance(e, ai.RateLimitWaited)]
    assert [e.request_id for e in waited] == [""]


def test_pacing_detach_is_idempotent() -> None:
    pacing = AttemptPacing("req-1")
    pacing.detach()
    pacing.detach()


def test_observing_reports_what_the_provider_said() -> None:
    limiter, _, events = _limiter(ai.RateLimits(), dialect=OPENAI_DIALECT)
    limiter.observe(
        {
            "x-ratelimit-remaining-requests": "7",
            "x-ratelimit-remaining-tokens": "1200",
            "x-ratelimit-reset-requests": "6m0s",
        }
    )

    observed = [e for e in events if isinstance(e, ai.RateLimitObserved)]
    assert len(observed) == 1
    assert observed[0].requests_remaining == 7
    assert observed[0].tokens_remaining == 1200
    assert observed[0].resets_in_s == pytest.approx(360.0)


# ---- reset parsing --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30", 30.0),
        ("1.5", 1.5),
        ("0", 0.0),
        ("1s", 1.0),
        ("6m0s", 360.0),
        ("500ms", 0.5),
        ("1h30m", 5400.0),
        ("", None),
        (None, None),
        ("-5", None),
        ("soon", None),
        ("2026-13-45T99:00:00Z", None),
    ],
)
def test_reset_header_forms(raw: str | None, expected: float | None) -> None:
    assert parse_reset_seconds(raw) == expected


def test_an_rfc_3339_instant_is_read_as_a_delta() -> None:
    now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
    later = (now + timedelta(seconds=45)).isoformat().replace("+00:00", "Z")
    assert parse_reset_seconds(later, now=now) == pytest.approx(45.0)


def test_a_past_instant_is_no_wait_rather_than_a_negative_one() -> None:
    now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
    earlier = (now - timedelta(seconds=45)).isoformat().replace("+00:00", "Z")
    assert parse_reset_seconds(earlier, now=now) == 0.0


def test_a_naive_instant_is_refused() -> None:
    """No timezone means no clock, and assuming this machine's is how skew becomes a wait."""
    assert parse_reset_seconds("2026-08-09T12:00:00") is None


# ---- the governing transport ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_transport_paces_and_learns_without_changing_the_response() -> None:
    limiter, clock, _ = _limiter(ai.RateLimits(), dialect=OPENAI_DIALECT)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"ok": True},
            headers={
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-reset-requests": "5s",
            },
        )

    transport = GoverningTransport(httpx2.MockTransport(handler), limiter)
    async with httpx2.AsyncClient(transport=transport, base_url="https://example.test") as c:
        first = await c.get("/one")
        assert first.json() == {"ok": True}
        assert clock.slept == []

        await c.get("/two")

    assert clock.total_slept == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_an_abandoned_stream_gives_its_permit_back() -> None:
    """R-RG4: a permit held across a body nobody drains would starve every other caller."""
    limiter, _, _ = _limiter(ai.RateLimits(max_concurrent=1, respect_headers=False))

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="chunk" * 10)

    transport = GoverningTransport(httpx2.MockTransport(handler), limiter)
    async with httpx2.AsyncClient(transport=transport, base_url="https://example.test") as c:
        async with c.stream("GET", "/one"):
            pass  # never read the body

        # Would hang here if the permit were still held.
        await asyncio.wait_for(c.get("/two"), timeout=5.0)


@pytest.mark.asyncio
async def test_a_failed_exchange_gives_its_permit_back() -> None:
    limiter, _, _ = _limiter(ai.RateLimits(max_concurrent=1, respect_headers=False))

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    transport = GoverningTransport(httpx2.MockTransport(handler), limiter)
    async with httpx2.AsyncClient(transport=transport, base_url="https://example.test") as c:
        with pytest.raises(httpx2.ConnectError):
            await c.get("/one")
        with pytest.raises(httpx2.ConnectError):
            await asyncio.wait_for(c.get("/two"), timeout=5.0)


@pytest.mark.asyncio
async def test_an_error_response_is_still_learned_from() -> None:
    """A 429 carries the most informative headers of any exchange."""
    limiter, clock, _ = _limiter(ai.RateLimits(), dialect=OPENAI_DIALECT)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            json={"error": "slow down"},
            headers={
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-reset-requests": "8s",
            },
        )

    transport = GoverningTransport(httpx2.MockTransport(handler), limiter)
    async with httpx2.AsyncClient(transport=transport, base_url="https://example.test") as c:
        await c.get("/one")
        await c.get("/two")

    assert clock.total_slept == pytest.approx(8.0)


# ---- wired into a real client ---------------------------------------------------------


class Collector:
    """Keeps every event a client emits, in order."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def on_event(self, event: Any) -> None:
        self.events.append(event)


def _scripted_client(**limit_kwargs: Any) -> tuple[ai.Client, Collector]:
    """A client over a scripted provider, governed by whatever limits were asked for."""
    from anyinfer.registry import ProviderRegistry
    from anyinfer.testing import ScriptedModel, ScriptedProvider

    provider = ScriptedProvider("acme", [ScriptedModel("m", text="ok")])
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(provider.descriptor(), replace=True)
    limits = ai.RateLimits(**limit_kwargs) if limit_kwargs else None
    collector = Collector()
    client = ai.Client(
        [provider.settings(limits=limits)],
        registry=registry,
        use_default_catalog=False,
    )
    client.subscribe(collector)
    return client, collector


def test_a_paced_request_reports_its_queue_time_in_the_result() -> None:
    """R-RG2: a paced request must never read as provider latency."""
    client, collector = _scripted_client(min_interval_s=0.2, respect_headers=False)
    with client:
        first = client.generate("hello", target="acme:m")
        second = client.generate("hello", target="acme:m")

    assert "queued_ms" not in first.timing.phases
    assert second.timing.phases["queued_ms"] >= 150.0
    waited = [e for e in collector.events if isinstance(e, ai.RateLimitWaited)]
    assert [e.reason for e in waited] == ["interval"]
    assert waited[0].target is not None
    assert waited[0].request_id


def test_asking_for_header_pacing_a_provider_cannot_do_is_reported() -> None:
    client, collector = _scripted_client(max_concurrent=2)
    with client:
        client.generate("hello", target="acme:m")

    dropped = [
        e
        for e in collector.events
        if isinstance(e, ai.ParameterDropped) and e.parameter == "limits.respect_headers"
    ]
    assert len(dropped) == 1
    assert "no rate-limit headers" in dropped[0].reason


def test_an_ungoverned_client_takes_no_permit_and_reports_no_wait() -> None:
    """The plan's whole acceptance test: unconfigured behaves exactly as before."""
    client, collector = _scripted_client()

    with client:
        result = client.generate("hello", target="acme:m")

    assert result.text == "ok"
    assert "queued_ms" not in result.timing.phases
    assert not [e for e in collector.events if isinstance(e, ai.RateLimitWaited)]
    assert not [
        e
        for e in collector.events
        if isinstance(e, ai.ParameterDropped) and e.parameter.startswith("limits.")
    ]


# ---- the injection seam ------------------------------------------------------------------
#
# `AdapterPool._govern` is the single site a `RateLimiter` is constructed, which is what
# makes injection a seam rather than a refactor. It exists for one situation the
# constructed path cannot serve: a caller that builds a short-lived client per request
# around a long-lived credential, where a per-client limiter paces every call against an
# empty bucket and discards the windows the provider just reported.


async def test_an_injected_limiter_survives_the_client_that_used_it() -> None:
    """The property the seam exists for: pacing state outliving a per-request client.

    Asserted on the token bucket rather than on wall time. Three requests through three
    separate clients draw the bucket down; without injection each client would build a
    fresh limiter and the third request would find a full one — which is exactly the
    inertness this seam exists to fix.
    """
    # `FakeClock`, not a frozen one: this module's clock advances when something sleeps
    # on it, which is what `_dispatch_gate`'s wait loop needs to make progress. A clock
    # that never moves paired with a sleep that never waits spins that loop forever.
    clock = FakeClock()
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    shared = RateLimiter(
        ai.RateLimits(requests_per_minute=60),
        provider_id="openai-compat",
        clock=clock,
        sleep=clock.sleep,
    )

    for _ in range(3):
        client = ai.AsyncClient(
            [
                ai.ProviderSettings.of(
                    "openai-compat",
                    base_url="https://fake.invalid/v1",
                    transport=server.transport(),
                )
            ],
            limiters={"openai-compat": shared},
            use_default_catalog=False,
        )
        try:
            await client.generate("hi", target="openai-compat:m")
        finally:
            await client.aclose()
        assert client._pool.limiter_for("openai-compat") is shared

    assert len(server.requests) == 3
    # A 60/minute bucket holds one request, so calls two and three each had to wait for a
    # refill: the shared limiter paced across three separate clients. Three per-client
    # limiters would each have started full and nothing would ever have slept.
    assert clock.total_slept > 0, "the pooled bucket paced nothing; state did not carry"


async def test_an_injected_limiter_wins_over_one_built_from_settings() -> None:
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    shared = RateLimiter(ai.RateLimits(requests_per_minute=600), provider_id="openai-compat")
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
                limits=ai.RateLimits(requests_per_minute=1),
            )
        ],
        limiters={"openai-compat": shared},
        use_default_catalog=False,
    )
    try:
        await client.generate("hi", target="openai-compat:m")
        assert client._pool.limiter_for("openai-compat") is shared
    finally:
        await client.aclose()


async def test_an_inert_injected_limiter_installs_no_governor() -> None:
    """Inertness is judged from the injected limiter's own configuration, not the settings'.

    The one honestly-inert policy, per `RateLimits.active`: a bare `RateLimits()` still
    means "pace me by what the provider reports", so opting out is spelled by switching
    header-following off with no bounds set.
    """
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    inert = RateLimiter(ai.RateLimits(respect_headers=False), provider_id="openai-compat")
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        limiters={"openai-compat": inert},
        use_default_catalog=False,
    )
    try:
        await client.generate("hi", target="openai-compat:m")
        assert client._pool.limiter_for("openai-compat") is None
    finally:
        await client.aclose()


async def test_no_injection_changes_nothing() -> None:
    """The seam is inert by omission, which is what makes it safe to add to core."""
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
                limits=ai.RateLimits(requests_per_minute=60),
            )
        ],
        use_default_catalog=False,
    )
    try:
        await client.generate("hi", target="openai-compat:m")
        limiter = client._pool.limiter_for("openai-compat")
        assert limiter is not None
        assert limiter.limits.requests_per_minute == 60
    finally:
        await client.aclose()


# ---- reporting an observed window ----------------------------------------------------------


def test_observed_wait_reports_the_providers_own_number_without_spending_anything() -> None:
    """A fronting layer must be able to *report* the wait, not only sleep through it."""
    clock = [1000.0]
    limiter = RateLimiter(
        ai.RateLimits(requests_per_minute=60, respect_headers=True),
        dialect=ai.RateLimitHeaders(
            requests_remaining="x-remaining", requests_reset="x-reset", limit_requests="x-limit"
        ),
        provider_id="p",
        clock=lambda: clock[0],
    )

    assert limiter.observed_wait_s() == 0.0, "nothing observed yet is not a wait"

    limiter.observe({"x-remaining": "0", "x-reset": "30", "x-limit": "100"})
    first = limiter.observed_wait_s()
    assert first == pytest.approx(30.0, abs=1.0)

    # Read-only: asking twice must not consume a token, take the gate, or move the window.
    assert limiter.observed_wait_s() == pytest.approx(first)


def test_observed_wait_is_clear_when_the_window_has_room() -> None:
    limiter = RateLimiter(
        ai.RateLimits(requests_per_minute=60, respect_headers=True),
        dialect=ai.RateLimitHeaders(requests_remaining="x-remaining", requests_reset="x-reset"),
        provider_id="p",
    )
    limiter.observe({"x-remaining": "50", "x-reset": "30"})
    assert limiter.observed_wait_s() == 0.0
