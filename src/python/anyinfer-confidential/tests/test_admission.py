"""Per-tenant admission control: bounded, isolated, and inert until configured.

What waits here is a *caller*, never a stored request — a durable queue would have to
persist slot-fills and assembled prompts, which is a different product with a weaker
guarantee than Tier 2's structural zero-retention.

The subtle part is slot accounting, and it is what most of these tests are about: a slot
is *transferred* from a releasing holder to the next waiter rather than released and
re-taken, so no arriving request can steal the slot a waiter was just promised. Every path
out — success, timeout, cancellation — has to leave the counter balanced, and a leaked
count would silently shrink a tenant's capacity for the life of the process.
"""

from __future__ import annotations

import asyncio

import pytest

from anyinfer_confidential.admission import (
    AdmissionController,
    RelayThrottledError,
    TenantLimits,
    ThrottleInfo,
)

# ---- the limits type ----------------------------------------------------------------------


def test_all_defaults_are_inert() -> None:
    """Mirrors `RateLimits`: an unconfigured relay behaves exactly as it did before."""
    assert not TenantLimits().active
    assert TenantLimits(max_in_flight=1).active


@pytest.mark.parametrize(
    "kwargs",
    [{"max_in_flight": 0}, {"max_waiting": 0}, {"max_wait_s": 0}, {"max_wait_s": -1}],
)
def test_a_bound_that_could_not_be_honored_is_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        TenantLimits(**kwargs)  # type: ignore[arg-type]


async def test_the_inert_path_takes_no_slot_and_counts_nothing() -> None:
    controller = AdmissionController()
    async with controller.admit("unconfigured", estimate=1.0):
        assert controller.in_flight("unconfigured") == 0
    assert controller.remaining("unconfigured") is None


# ---- the cap -------------------------------------------------------------------------------


async def test_the_cap_bounds_concurrency() -> None:
    controller = AdmissionController()
    controller.set_limits("acme", TenantLimits(max_in_flight=2, max_waiting=8))
    peak = 0
    live = 0

    async def work() -> None:
        nonlocal peak, live
        async with controller.admit("acme", estimate=1.0):
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1

    await asyncio.gather(*(work() for _ in range(8)))
    assert peak == 2
    assert controller.in_flight("acme") == 0, "every slot was returned"


async def test_a_waiter_is_admitted_when_a_slot_is_released() -> None:
    controller = AdmissionController()
    controller.set_limits("acme", TenantLimits(max_in_flight=1, max_waiting=4))
    order: list[str] = []

    async def work(name: str) -> None:
        async with controller.admit("acme", estimate=1.0):
            order.append(name)
            await asyncio.sleep(0.01)

    await asyncio.gather(work("first"), work("second"))
    assert order == ["first", "second"]


async def test_a_full_queue_refuses_fast_rather_than_growing() -> None:
    """Backpressure over buffering: the refusal is the feature."""
    controller = AdmissionController()
    controller.set_limits("acme", TenantLimits(max_in_flight=1, max_waiting=1, max_wait_s=5))

    async def hold() -> None:
        async with controller.admit("acme", estimate=1.0):
            await asyncio.sleep(0.2)

    running = [asyncio.create_task(hold()) for _ in range(2)]  # one in flight, one queued
    await asyncio.sleep(0.02)

    with pytest.raises(RelayThrottledError) as caught:
        async with controller.admit("acme", estimate=2.0):
            pass

    assert caught.value.info.reason == "tenant-queue-full"
    assert caught.value.info.retry_after_s == 2.0
    await asyncio.gather(*running)
    assert controller.in_flight("acme") == 0


async def test_a_waiter_that_waits_too_long_is_refused_and_leaks_no_slot() -> None:
    controller = AdmissionController()
    controller.set_limits("acme", TenantLimits(max_in_flight=1, max_waiting=4, max_wait_s=0.03))

    async def hold() -> None:
        async with controller.admit("acme", estimate=1.0):
            await asyncio.sleep(0.2)

    holder = asyncio.create_task(hold())
    await asyncio.sleep(0.01)

    with pytest.raises(RelayThrottledError) as caught:
        async with controller.admit("acme", estimate=1.0):
            pass
    assert caught.value.info.reason == "tenant-in-flight"

    await holder
    assert controller.in_flight("acme") == 0
    assert controller.waiting("acme") == 0


async def test_a_cancelled_waiter_frees_its_place_in_the_queue() -> None:
    """A client disconnect and a timeout are the same cleanup — the work evaporates."""
    controller = AdmissionController()
    controller.set_limits("acme", TenantLimits(max_in_flight=1, max_waiting=4, max_wait_s=5))

    async def hold() -> None:
        async with controller.admit("acme", estimate=1.0):
            await asyncio.sleep(0.2)

    async def queue_up() -> None:
        async with controller.admit("acme", estimate=1.0):
            pass

    holder = asyncio.create_task(hold())
    await asyncio.sleep(0.01)
    abandoned = asyncio.create_task(queue_up())
    await asyncio.sleep(0.01)
    assert controller.waiting("acme") == 1

    abandoned.cancel()
    with pytest.raises((asyncio.CancelledError, RelayThrottledError)):
        await abandoned

    await holder
    assert controller.waiting("acme") == 0
    assert controller.in_flight("acme") == 0


async def test_a_slot_is_returned_even_when_the_held_work_raises() -> None:
    controller = AdmissionController()
    controller.set_limits("acme", TenantLimits(max_in_flight=1))

    with pytest.raises(RuntimeError):
        async with controller.admit("acme", estimate=1.0):
            raise RuntimeError("the work failed")

    assert controller.in_flight("acme") == 0
    async with controller.admit("acme", estimate=1.0):
        pass  # the cap is not permanently consumed


# ---- isolation -------------------------------------------------------------------------------


async def test_one_tenant_at_its_cap_does_not_delay_another() -> None:
    """The noisy-neighbour property, and the reason isolation is per-tenant by construction."""
    controller = AdmissionController()
    for tenant in ("noisy", "quiet"):
        controller.set_limits(tenant, TenantLimits(max_in_flight=1, max_waiting=32, max_wait_s=5))

    served: list[str] = []

    async def work(tenant: str, name: str) -> None:
        async with controller.admit(tenant, estimate=1.0):
            served.append(name)
            await asyncio.sleep(0.02)

    tasks = [asyncio.create_task(work("noisy", f"noisy-{i}")) for i in range(8)]
    await asyncio.sleep(0.005)
    tasks.append(asyncio.create_task(work("quiet", "quiet-0")))
    await asyncio.gather(*tasks)

    assert served.index("quiet-0") <= 2, (
        "the quiet tenant waited behind the noisy one's backlog: "
        f"served order was {served}"
    )


async def test_one_tenants_budget_is_reported_from_its_own_state_only() -> None:
    controller = AdmissionController()
    controller.set_limits("acme", TenantLimits(max_in_flight=4))
    controller.set_limits("other", TenantLimits(max_in_flight=4))

    async def hold(tenant: str) -> None:
        async with controller.admit(tenant, estimate=1.0):
            await asyncio.sleep(0.05)

    busy = [asyncio.create_task(hold("other")) for _ in range(4)]
    await asyncio.sleep(0.01)

    assert controller.remaining("acme") == 4, "another tenant's saturation is not visible here"
    await asyncio.gather(*busy)


def test_only_configured_tenants_are_reported_as_configured() -> None:
    controller = AdmissionController()
    controller.set_limits("bounded", TenantLimits(max_in_flight=1))
    controller.set_limits("unbounded", TenantLimits())
    assert controller.configured_tenants == ("bounded",)


def test_a_throttle_carries_a_reason_a_client_can_branch_on() -> None:
    info = ThrottleInfo("provider-window", 3.5, remaining=0)
    assert "provider-window" in str(RelayThrottledError(info))
    assert RelayThrottledError(info).info is info
