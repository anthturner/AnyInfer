"""Bounded, fair, per-tenant admission control for the Relay.

**Backpressure, not buffering.** What waits here is a *caller* — a coroutine already
holding its own request — never a stored request. A durable job queue would have to persist
slot-fills and assembled prompts, which is a different product with a weaker guarantee than
Tier 2's: the relay module's zero-retention claim is structural, and a queue that survives
a restart would end it. So a tenant over its cap waits briefly and is then refused, and a
caller that disconnects takes its work with it.

**Isolation is structural, not scheduled.** Each tenant has its own counter, its own cap,
and its own queue, so one tenant's burst of a hundred waiters cannot delay another tenant's
single request — there is no shared queue for it to sit behind. That is stronger than the
round-robin scheduling this was first designed with, and it is why none is here: with no
cross-tenant contention to arbitrate, a fairness policy would be machinery with no
consumer.

The design that *would* need one is a process-wide concurrency cap on top of the per-tenant
ones, which is deliberately absent. Bounding the process means tenants compete for one
resource, which means scheduling them fairly, which is the complexity this shape avoids. A
deployment that needs a hard process ceiling sets it where it belongs — at the ASGI server's
own concurrency limit — rather than having this class reimplement one.

**Inert by default.** A `TenantLimits` with every field unset takes no lock, awaits
nothing, and counts nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["AdmissionController", "RelayThrottledError", "TenantLimits", "ThrottleInfo"]


@dataclass(frozen=True, slots=True)
class TenantLimits:
    """How much of one process one tenant may occupy.

    All-defaults is inert, mirroring `RateLimits`' contract: a Relay whose registry sets no
    limits dispatches exactly as it did before admission control existed.

    Attributes:
        max_in_flight: Requests this tenant may have executing at once. ``None`` means
            unbounded, which is the pre-existing behaviour.
        max_waiting: Callers that may queue for a slot once the cap is reached. ``None``
            means unbounded queueing, which is rarely what anyone wants — a bound here is
            what turns overload into a fast refusal rather than a growing backlog.
        max_wait_s: How long a queued caller waits before being refused. A refusal a client
            can retry beats a request that eventually completes long after the caller
            stopped caring.
    """

    max_in_flight: int | None = None
    max_waiting: int | None = None
    max_wait_s: float = 10.0

    def __post_init__(self) -> None:
        """Reject bounds that could not be honored.

        Raises:
            ValueError: A cap is not positive, or the wait budget is not positive.
        """
        for name in ("max_in_flight", "max_waiting"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be at least 1 when set")
        if self.max_wait_s <= 0:
            raise ValueError("max_wait_s must be positive")

    @property
    def active(self) -> bool:
        """Whether these limits constrain anything at all."""
        return self.max_in_flight is not None


@dataclass(frozen=True, slots=True)
class ThrottleInfo:
    """Why a request was refused, and what a client should do about it.

    Every number here derives from the *requesting* tenant's own state. A `retry_after_s`
    computed from process-wide load would reopen the enumeration hole `RelayRegistry`
    closes deliberately: a tenant polling in a loop could read another tenant's traffic
    volume off its own backoff hint.

    Attributes:
        reason: Which bound was hit.
        retry_after_s: Seconds to wait, jittered and clamped. Provider-exact when the
            provider stated it; a queueing estimate otherwise.
        remaining: This tenant's own remaining admission budget when it is known.
    """

    reason: Literal["tenant-in-flight", "tenant-queue-full", "provider-window"]
    retry_after_s: float
    remaining: int | None = None


class RelayThrottledError(Exception):
    """The relay refused a request to protect its own bounds.

    Not a `RelayError`: those describe a request the relay cannot serve at all, while this
    one describes a request it could serve later. The HTTP layer maps them to 404/400 and
    429 respectively, and conflating them would tell a client to fix its routing key when
    the answer is to wait a second.

    Attributes:
        info: The typed refusal, for a caller that is not speaking HTTP.
    """

    def __init__(self, info: ThrottleInfo) -> None:
        super().__init__(f"refused: {info.reason}; retry in {info.retry_after_s:.1f}s")
        self.info = info


class AdmissionController:
    """Bounds and fairly interleaves concurrent work per tenant."""

    __slots__ = ("_in_flight", "_limits", "_waiters")

    def __init__(self) -> None:
        self._limits: dict[str, TenantLimits] = {}
        self._in_flight: dict[str, int] = {}
        # One queue per tenant, never a shared one: a tenant's waiters are only ever woken
        # by that same tenant releasing a slot, which is what makes isolation structural.
        self._waiters: dict[str, deque[asyncio.Future[None]]] = {}

    def set_limits(self, tenant_id: str, limits: TenantLimits) -> None:
        """Provision one tenant's bounds."""
        self._limits[tenant_id] = limits

    def limits_for(self, tenant_id: str) -> TenantLimits:
        """This tenant's bounds, defaulting to inert."""
        return self._limits.get(tenant_id, TenantLimits())

    @property
    def configured_tenants(self) -> tuple[str, ...]:
        """Tenants with active limits, for a deployment-time warning."""
        return tuple(t for t, limits in self._limits.items() if limits.active)

    def in_flight(self, tenant_id: str) -> int:
        """How many of this tenant's requests are executing right now."""
        return self._in_flight.get(tenant_id, 0)

    def remaining(self, tenant_id: str) -> int | None:
        """This tenant's own remaining admission budget, or ``None`` when unbounded."""
        cap = self.limits_for(tenant_id).max_in_flight
        if cap is None:
            return None
        return max(0, cap - self.in_flight(tenant_id))

    @asynccontextmanager
    async def admit(
        self, tenant_id: str, *, estimate: float
    ) -> AsyncIterator[None]:
        """Hold one admission slot for the duration of the block.

        Args:
            tenant_id: Whose budget to spend.
            estimate: Seconds to advertise if this call is refused, already jittered and
                clamped by the caller — the estimator needs service-time samples this
                class does not hold, so the number is computed above and passed down.

        Raises:
            RelayThrottledError: The tenant is at its cap and its queue is full or its wait
                budget expired.
        """
        limits = self.limits_for(tenant_id)
        if not limits.active:
            # The inert path: no counter, no lock, no await beyond the caller's own.
            yield
            return

        await self._acquire(tenant_id, limits, estimate)
        try:
            yield
        finally:
            self._release(tenant_id)

    async def _acquire(self, tenant_id: str, limits: TenantLimits, estimate: float) -> None:
        """Take a slot, waiting fairly and briefly, or refuse.

        Raises:
            RelayThrottledError: The queue is full, or the wait budget expired.
        """
        cap = limits.max_in_flight
        assert cap is not None  # noqa: S101 — narrowed by `limits.active`
        if self._in_flight.get(tenant_id, 0) < cap:
            self._in_flight[tenant_id] = self._in_flight.get(tenant_id, 0) + 1
            return

        queue = self._waiters.setdefault(tenant_id, deque())
        if limits.max_waiting is not None and len(queue) >= limits.max_waiting:
            raise RelayThrottledError(
                ThrottleInfo("tenant-queue-full", estimate, remaining=0)
            )

        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        queue.append(waiter)
        try:
            await asyncio.wait_for(waiter, timeout=limits.max_wait_s)
        except (TimeoutError, asyncio.CancelledError):
            # A timeout and a client disconnect are the same cleanup: drop the waiter and
            # let the work evaporate, which is the zero-retention behaviour anyway. The
            # slot this waiter would have taken has not been handed over yet, so nothing
            # leaks — but a release that raced us may already have granted it, in which
            # case it must be passed on rather than dropped.
            if waiter.done() and not waiter.cancelled() and waiter.exception() is None:
                self._release(tenant_id)
            else:
                self._drop(tenant_id, waiter)
            raise RelayThrottledError(
                ThrottleInfo("tenant-in-flight", estimate, remaining=0)
            ) from None
        # The releasing side transferred its slot to us rather than decrementing, so the
        # in-flight count is already correct and must not be incremented again.

    def _release(self, tenant_id: str) -> None:
        """Hand this tenant's slot to its next waiter, or give it back to the pool.

        The slot is *transferred* rather than released and re-taken: decrementing here and
        letting the woken waiter increment would open a window in which a newly-arriving
        request could take the slot the waiter was just promised, which is how a queue
        starves its own front under load.
        """
        queue = self._waiters.get(tenant_id)
        while queue:
            waiter = queue.popleft()
            if not waiter.done():
                waiter.set_result(None)  # slot transferred; count stays as it is
                return
        if queue is not None and not queue:
            del self._waiters[tenant_id]
        current = self._in_flight.get(tenant_id, 0)
        if current <= 1:
            self._in_flight.pop(tenant_id, None)
        else:
            self._in_flight[tenant_id] = current - 1

    def _drop(self, tenant_id: str, waiter: asyncio.Future[None]) -> None:
        """Remove one abandoned waiter from its tenant's queue."""
        queue = self._waiters.get(tenant_id)
        if queue is None:
            return
        with contextlib.suppress(ValueError):
            queue.remove(waiter)
        if not queue:
            del self._waiters[tenant_id]

    def waiting(self, tenant_id: str) -> int:
        """How many callers are queued for this tenant right now."""
        queue = self._waiters.get(tenant_id)
        return len(queue) if queue else 0
