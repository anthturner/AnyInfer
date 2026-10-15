"""Client-side pacing: bound this process's own requests to one provider.

The library already reacts to a rate limit correctly — `RateLimitError` is retryable,
``Retry-After`` is honoured, and backoff rises to the server's advice. What it never did is
*anticipate* one: an ``asyncio.gather`` over a hundred requests sends a hundred requests,
takes a wall of 429s, and only then backs off, having already spent the provider's patience.

This module is the avoidance half, and it is deliberately small in what it claims:

- It paces **this process**. There is no shared state, no coordination between workers, and
  no parameter that would accept any — adding one would be a visible design change rather
  than a config option, which is the point.
- It enforces no quota the provider did not state. Every window it waits on was read from
  that provider's own response headers.
- It never influences *which* target is chosen. A limiter that skipped a busy provider in
  favour of an idle one would be load balancing, which this library does not do.

With no limits configured, nothing here runs: the transport is not wrapped, no permit is
taken, and a request is dispatched exactly as it was before this module existed.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx2

from ..events.telemetry import RateLimitObserved, RateLimitWaited, TelemetryEvent
from ..types.capabilities import RateLimitHeaders
from ..types.requests import RateLimits
from ..types.results import ResolvedTarget

__all__ = [
    "MAX_HEADER_WAIT_S",
    "AttemptPacing",
    "GoverningTransport",
    "RateLimiter",
    "WaitReason",
    "governed_attempt",
    "parse_reset_seconds",
]

MAX_HEADER_WAIT_S = 60.0
"""Longest delay a provider's own headers may impose.

A window that claims to reset in an hour is either a different window than the one this
request needs or a header this client has misread; waiting an hour on either would look
exactly like a hang. Past the ceiling the request goes anyway and the existing
`RateLimitError` path handles the outcome, as it did before this module existed.
"""

WaitReason = Literal["concurrency", "interval", "provider-headers"]
"""Which limit held a request back — a configured in-flight bound, a configured rate or
gap, or a window the provider itself reported."""

_DURATION = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>ms|s|m|h)")
_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_reset_seconds(raw: str | None, *, now: datetime | None = None) -> float | None:
    """Read a rate-limit reset header as seconds from now.

    Three spellings, because providers use three: a bare number of seconds (``"30"``), the
    compound duration form (``"6m0s"``, ``"500ms"``), and an RFC 3339 instant
    (``"2026-08-09T12:00:00Z"``).

    The absolute form is read here even though `parse_retry_after` refuses the HTTP-date
    form of ``Retry-After``, and the difference is deliberate rather than an oversight.
    There, a misread date changes *backoff after a failure*, where being wrong risks a ban
    and the fallback — exponential backoff — is already correct. Here, a misread instant can
    only produce a pause, and every pause is clamped to `MAX_HEADER_WAIT_S` before it is
    taken. A bounded wrong wait is a far smaller cost than refusing to pace the providers
    that state their window this way at all.

    Args:
        raw: The header value.
        now: Present instant, injectable for tests. Defaults to the current UTC time.

    Returns:
        Seconds until the window resets, or ``None`` when the value is absent, negative, or
        in a form this function refuses to guess at.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        pass
    else:
        return seconds if seconds >= 0 else None

    matches = list(_DURATION.finditer(text))
    if matches and "".join(m.group(0) for m in matches) == text:
        return sum(float(m.group("value")) * _UNIT_SECONDS[m.group("unit")] for m in matches)

    return _parse_instant(text, now)


def _parse_instant(text: str, now: datetime | None) -> float | None:
    """Read an RFC 3339 instant as seconds from now, never as a negative."""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        # A naive instant says nothing about which clock it belongs to, and assuming
        # this machine's is how a timezone becomes a wait.
        return None
    reference = now or datetime.now(UTC)
    return max(0.0, float((moment - reference).total_seconds()))


def _read_int(headers: Mapping[str, str], name: str) -> int | None:
    """Read a header as a non-negative integer, or ``None`` when it is absent or unusable."""
    if not name:
        return None
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        value = int(float(raw.strip()))
    except ValueError:
        return None
    return value if value >= 0 else None


class AttemptPacing:
    """How long one attempt spent waiting on its own limiter.

    The limiter lives under the transport and has no idea which request it is delaying.
    Rather than thread a correlation id through every adapter, which would make adapters
    aware of routing, and they must not be — the client marks the context it dispatches in
    and the limiter reads it back.

    Detach is explicit and must be called, because the dispatch site is an async generator.
    An async generator does not get a context of its own, so a marker left set across a
    ``yield`` stays visible to whatever the consumer does next, including another request
    of its own, which would then be credited with this attempt's wait. Pacing happens before
    the first event arrives, so detaching there costs nothing and closes the window.

    Args:
        request_id: Correlation id of the attempt being paced.
        target: The resolved target, for event attribution.
    """

    def __init__(self, request_id: str, target: ResolvedTarget | None = None) -> None:
        self.request_id = request_id
        self.target = target
        self.waited_s = 0.0
        self.reasons: tuple[WaitReason, ...] = ()
        self._token: Token[AttemptPacing | None] | None = _PACING.set(self)

    @property
    def waited_ms(self) -> float:
        """The wait in milliseconds, for `Timing.phases`."""
        return self.waited_s * 1000.0

    @property
    def waited(self) -> bool:
        """Whether this attempt was held back at all."""
        return self.waited_s > 0

    def record(self, waited_s: float, reason: WaitReason) -> None:
        """Accumulate one wait."""
        self.waited_s += waited_s
        self.reasons = (*self.reasons, reason)

    def detach(self) -> None:
        """Stop attributing pacing to this attempt. Idempotent."""
        token, self._token = self._token, None
        if token is not None:
            _PACING.reset(token)


_PACING: ContextVar[AttemptPacing | None] = ContextVar("anyinfer_attempt_pacing", default=None)


@contextlib.contextmanager
def governed_attempt(
    request_id: str, target: ResolvedTarget | None = None
) -> Iterator[AttemptPacing]:
    """Attribute whatever pacing happens inside to one attempt.

    The scoped form, for callers that are not async generators.

    Yields:
        The accumulator, whose `waited_ms` is meaningful once the block exits.
    """
    pacing = AttemptPacing(request_id, target)
    try:
        yield pacing
    finally:
        pacing.detach()


@dataclass(slots=True)
class _Window:
    """One provider-reported allowance window: what is left, and when it refills."""

    remaining: int | None = None
    limit: int | None = None
    resets_at: float | None = None

    def floor(self, reserve_fraction: float) -> float:
        """How many units to leave untouched.

        Without a stated limit there is no fraction to take, so the floor is zero and
        pacing only engages when the provider says it has nothing left. Reserving a guessed
        share of an unknown allowance would throttle a caller against a number this client
        made up.
        """
        if not reserve_fraction or self.limit is None:
            return 0.0
        return self.limit * reserve_fraction

    def wait_s(self, now: float, reserve_fraction: float) -> float:
        """Seconds to wait before spending from this window, which is usually zero."""
        if self.remaining is None or self.resets_at is None:
            return 0.0
        if self.remaining > self.floor(reserve_fraction):
            return 0.0
        return max(0.0, min(self.resets_at - now, MAX_HEADER_WAIT_S))


class RateLimiter:
    """Paces requests to one provider instance and learns from its response headers.

    One limiter belongs to one configured provider instance, because a rate limit is a
    property of an account at a provider rather than of the application: two aliases
    pointing at two keys have two independent buckets, and two aliases sharing one key are
    the caller's own decision to make.

    Args:
        limits: What the caller asked for. Nothing here runs when it is inert.
        dialect: Which headers this provider reports its state in; empty when it reports
            none, in which case pacing honours the configured bounds only.
        provider_id: Instance id, for event attribution.
        events: Where to send `RateLimitWaited` and `RateLimitObserved`.
        sees_responses: Whether this provider's traffic passes through a transport the core
            built. False for adapters that talk through a vendor SDK, whose response headers
            are never ours to read — such a provider is paced by configured bounds only.
        clock: Monotonic clock, injectable so tests need no real time.
        sleep: How to wait, injectable for the same reason.
    """

    def __init__(
        self,
        limits: RateLimits,
        *,
        dialect: RateLimitHeaders = RateLimitHeaders(),
        provider_id: str = "",
        events: Callable[[TelemetryEvent], None] | None = None,
        sees_responses: bool = True,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Any] | None = None,
    ) -> None:
        self._limits = limits
        self._dialect = dialect
        self._provider_id = provider_id
        self._sees_responses = sees_responses
        self._events = events
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._semaphore = (
            asyncio.Semaphore(limits.max_concurrent) if limits.max_concurrent is not None else None
        )
        self._gate = asyncio.Lock()
        self._last_dispatch: float | None = None
        self._tokens = 0.0
        self._refilled_at = self._clock()
        self._requests = _Window()
        self._tokens_window = _Window()
        if limits.requests_per_minute is not None:
            self._capacity = max(1.0, limits.requests_per_minute / 60.0)
            self._refill_per_s = limits.requests_per_minute / 60.0
            self._tokens = self._capacity
        else:
            self._capacity = 0.0
            self._refill_per_s = 0.0

    @property
    def limits(self) -> RateLimits:
        """What this limiter was configured to pace against.

        Read-only, and needed by exactly one caller: `AdapterPool._govern` judges an
        injected limiter's inertness from its own configuration rather than from the
        settings it is being installed against.
        """
        return self._limits

    def observed_wait_s(self) -> float:
        """Seconds this provider's own reported windows say to wait; ``0.0`` when clear.

        The same number `_dispatch_gate` already computes before pacing, exposed so a
        caller can *report* it rather than only wait on it. This matters at a fronting
        layer that must answer a client now: a `Retry-After` derived from the provider's
        own headers is the provider's number, passed through — not an estimate, and not a
        figure this library invented.

        Read-only. Nothing here mutates the windows, spends a token, or takes the gate, so
        calling it never changes what the next request is paced by.
        """
        now = self._clock()
        return max(
            self._requests.wait_s(now, self._limits.reserve_fraction),
            self._tokens_window.wait_s(now, self._limits.reserve_fraction),
        )

    @property
    def reads_headers(self) -> bool:
        """Whether this limiter can act on the provider's reported state.

        Both halves are needed: a remaining count says the window is nearly spent, and a
        reset says how long that lasts. With only one of them the honest move is to pace by
        the caller's own bounds; never to invent the missing half.
        """
        if not self._limits.respect_headers or not self._sees_responses:
            return False
        return bool(
            (self._dialect.requests_remaining and self._dialect.requests_reset)
            or (self._dialect.tokens_remaining and self._dialect.tokens_reset)
        )

    @property
    def unsupported_headers_reason(self) -> str | None:
        """Why header-driven pacing cannot run here, or ``None`` when it can.

        The caller asked for something this provider cannot supply, and a policy that
        silently does nothing is the degradation this library refuses to perform quietly.
        """
        if not self._limits.respect_headers or self.reads_headers:
            return None
        if not self._sees_responses:
            return (
                "this provider builds its own transport, so its response headers are "
                "never seen; pacing here is by configured bounds only"
            )
        if not self._dialect.declared:
            return "this provider publishes no rate-limit headers"
        return "this provider reports a remaining count but no window reset"

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold a dispatch permit for the life of one request.

        The permit spans the whole exchange, streaming included: releasing it when the
        response headers arrive would let a hundred half-read streams count as idle, which
        is the concurrency the provider actually sees.
        """
        if self._semaphore is not None:
            await self._acquire_semaphore()
        try:
            await self._wait_for_turn()
            yield
        finally:
            if self._semaphore is not None:
                self._semaphore.release()

    async def _acquire_semaphore(self) -> None:
        semaphore = self._semaphore
        if semaphore is None:
            return
        if semaphore.locked():
            started = self._clock()
            await semaphore.acquire()
            self._report(self._clock() - started, "concurrency")
            return
        await semaphore.acquire()

    async def _wait_for_turn(self) -> None:
        """Apply the rate bucket, the minimum interval, and any provider-stated window."""
        # Cumulative, not per-sleep: a window that resets in two hours would otherwise be
        # waited out one clamped minute at a time, which is the hang the ceiling exists to
        # prevent. Once this request has given the provider's own window its full ceiling,
        # it goes, and the existing RateLimitError path handles whatever happens next.
        header_waited = 0.0
        while True:
            async with self._gate:
                now = self._clock()
                delay, reason = self._next_delay(
                    now, headers_spent=header_waited >= MAX_HEADER_WAIT_S
                )
                if delay <= 0:
                    self._consume(now)
                    return
            await self._sleep(delay)
            if reason == "provider-headers":
                header_waited += delay
            self._report(delay, reason)

    def _next_delay(
        self, now: float, *, headers_spent: bool = False
    ) -> tuple[float, WaitReason | None]:
        """The longest delay any active limit demands right now, and which one demanded it."""
        candidates: list[tuple[float, WaitReason]] = []

        if self._refill_per_s > 0:
            self._refill(now)
            if self._tokens < 1.0:
                candidates.append(((1.0 - self._tokens) / self._refill_per_s, "interval"))

        if self._limits.min_interval_s > 0 and self._last_dispatch is not None:
            elapsed = now - self._last_dispatch
            if elapsed < self._limits.min_interval_s:
                candidates.append((self._limits.min_interval_s - elapsed, "interval"))

        if self.reads_headers and not headers_spent:
            reserve = self._limits.reserve_fraction
            for window in (self._requests, self._tokens_window):
                wait = window.wait_s(now, reserve)
                if wait > 0:
                    candidates.append((wait, "provider-headers"))

        if not candidates:
            return 0.0, None
        return max(candidates)

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._refilled_at)
        self._refilled_at = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_s)

    def _consume(self, now: float) -> None:
        if self._refill_per_s > 0:
            self._tokens = max(0.0, self._tokens - 1.0)
        self._last_dispatch = now
        # A window this client just spent from is stale until the provider reports again.
        # Decrementing the local copy keeps a burst from all reading the same "1 left".
        for window in (self._requests, self._tokens_window):
            if window.remaining is not None:
                window.remaining = max(0, window.remaining - 1)

    def observe(self, headers: Mapping[str, str]) -> None:
        """Learn this provider's current window from one response.

        Called for every response, including error responses: a 429 carries the most
        informative headers of any exchange.
        """
        if not self._dialect.declared:
            return
        now = self._clock()
        requests_reset = parse_reset_seconds(headers.get(self._dialect.requests_reset))
        tokens_reset = parse_reset_seconds(headers.get(self._dialect.tokens_reset))
        requests_remaining = _read_int(headers, self._dialect.requests_remaining)
        tokens_remaining = _read_int(headers, self._dialect.tokens_remaining)

        self._apply(
            self._requests,
            remaining=requests_remaining,
            limit=_read_int(headers, self._dialect.limit_requests),
            reset_s=requests_reset,
            now=now,
        )
        self._apply(
            self._tokens_window,
            remaining=tokens_remaining,
            limit=_read_int(headers, self._dialect.limit_tokens),
            reset_s=tokens_reset,
            now=now,
        )

        if requests_remaining is None and tokens_remaining is None:
            return
        self._emit(
            RateLimitObserved(
                provider_id=self._provider_id,
                requests_remaining=requests_remaining,
                tokens_remaining=tokens_remaining,
                resets_in_s=requests_reset if requests_reset is not None else tokens_reset,
            )
        )

    def _apply(
        self,
        window: _Window,
        *,
        remaining: int | None,
        limit: int | None,
        reset_s: float | None,
        now: float,
    ) -> None:
        """Fold one response's report into a window, leaving unstated fields alone."""
        if remaining is not None:
            window.remaining = remaining
        if limit is not None:
            window.limit = limit
        if reset_s is not None:
            window.resets_at = now + reset_s

    def _report(self, waited_s: float, reason: WaitReason | None) -> None:
        """Make one wait visible, to the attempt that paid for it and to observers."""
        if waited_s <= 0 or reason is None:
            return
        pacing = _PACING.get()
        if pacing is not None:
            pacing.record(waited_s, reason)
        self._emit(
            RateLimitWaited(
                request_id=pacing.request_id if pacing is not None else "",
                provider_id=self._provider_id,
                waited_s=waited_s,
                reason=reason,
                target=pacing.target if pacing is not None else None,
            )
        )

    def _emit(self, event: TelemetryEvent) -> None:
        if self._events is None:
            return
        self._events(event)


class GoverningTransport(httpx2.AsyncBaseTransport):
    """Wraps a provider's transport to pace its requests and read its limit headers.

    Governance sits here rather than in adapter code for one reason: adapters translate and
    nothing more, and a limiter is policy. Wrapping the transport means every ``httpx2``
    adapter is governed without knowing it, and the fake and cassette transports compose
    underneath, so pacing is testable against a scripted provider with no network and no
    real clock.

    Args:
        inner: The transport that actually performs the exchange.
        limiter: The pacer for this provider instance.
    """

    def __init__(self, inner: httpx2.AsyncBaseTransport, limiter: RateLimiter) -> None:
        self._inner = inner
        self._limiter = limiter

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        """Wait for a permit, perform the exchange, and learn from the response."""
        release = await self._enter()
        try:
            response = await self._inner.handle_async_request(request)
        except BaseException:
            await release()
            raise
        self._limiter.observe(response.headers)
        stream = response.stream
        if isinstance(stream, httpx2.AsyncByteStream):
            response.stream = _ReleasingStream(stream, release)
        else:
            # A synchronous body cannot be closed from this path; the exchange is already
            # complete, so the permit is given back now rather than never.
            await release()
        return response

    async def _enter(self) -> Callable[[], Any]:
        """Take a permit, returning the callable that gives it back.

        The permit outlives this method — it is released when the response body is closed —
        so the context manager is driven by hand rather than with ``async with``.
        """
        slot = self._limiter.slot()
        await slot.__aenter__()

        async def release() -> None:
            await slot.__aexit__(None, None, None)

        return release

    async def aclose(self) -> None:
        """Close the wrapped transport."""
        await self._inner.aclose()


class _ReleasingStream(httpx2.AsyncByteStream):
    """A response body that gives the dispatch permit back when it is closed.

    A permit held across a stream nobody drains would starve every other caller, so release
    is driven by teardown — the same path the byte cap and the timeout already use — rather
    than by reaching the end of the body. `httpx2.Response.aclose` type-checks its stream,
    so this subclasses the real base rather than merely matching its shape.
    """

    def __init__(self, inner: httpx2.AsyncByteStream, release: Callable[[], Any]) -> None:
        self._inner = inner
        self._release = release
        self._released = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._inner:
            yield chunk

    async def aclose(self) -> None:
        """Close the wrapped body, then release the permit exactly once."""
        try:
            closer = getattr(self._inner, "aclose", None)
            if closer is not None:
                await closer()
        finally:
            if not self._released:
                self._released = True
                await self._release()
