"""Pacing state that outlives one `Relay` call.

**Why this exists.** `Relay._forward` builds a fresh `AsyncClient` per call and closes it
in a `finally`. That is right for credentials — a BYOK key arrives with the request and
must die with it — and wrong for pacing, because a `RateLimiter`'s token bucket,
header-observed windows, and in-flight accounting all live inside the client. Every
forward call therefore paced against an empty bucket and threw away the windows the
provider had just reported. Core's limiter was structurally inert behind the Relay.

**What is held here, exhaustively.** Timing metadata: token-bucket levels, window resets,
in-flight counts, and service-latency samples as bare floats. No request body, no response
body, no slot value, no assembled prompt, and no credential. The relay module's claim that
nothing in Tier 2 opens a file or a database connection holds here too — this is process
memory that dies with the process, and nothing in it is written anywhere.

**How a credential is keyed without being kept.** A `PacingKey` carries a salted SHA-256
digest of the key identity, never the key. The salt is generated once per `PacingPool` and
never leaves memory, so a digest is not comparable across processes or across restarts and
is worthless if it ever escaped. It is never logged, never emitted on an event, and never
returned to a caller.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anyinfer import ProviderSettings
    from anyinfer.routing.limits import RateLimiter
    from anyinfer.types.capabilities import RateLimitHeaders
    from anyinfer.types.requests import RateLimits

__all__ = ["DEFAULT_RESERVE_FRACTION", "PacingKey", "PacingPool"]

DEFAULT_POOL_SIZE = 256
"""How many distinct credential/provider pairs a pool paces before evicting.

Bounded so a caller cycling keys cannot grow the pool without limit. Eviction forgets
pacing history for the least recently used pair, which costs one under-paced request
against that provider — never correctness.
"""

DEFAULT_LATENCY_SAMPLES = 64
"""Service-time samples retained per (tenant, target).

Enough for a stable upper quantile, small enough that sorting one to compute a quantile is
free. A ring rather than a growing list, so a busy tenant's memory does not grow with its
traffic.
"""

DEFAULT_RESERVE_FRACTION = 0.1
"""Share of a provider window left untouched for a pooled limiter.

Not zero, unlike the core default, because the situation is different: a Relay forwarding
with a customer's own BYOK key is almost certainly *not* the only consumer of that key —
the customer's own application is the other one. Reserving a tenth is the case
`RateLimits.reserve_fraction` documents verbatim.
"""


@dataclass(frozen=True, slots=True)
class PacingKey:
    """What a pooled limiter is keyed by: an account at a provider.

    Deliberately the same unit core's limiter documentation names, so a pooled limiter and
    a constructed one mean the same thing.

    Attributes:
        credential_digest: Salted SHA-256 of the credential, or of the instance id alone
            when the settings carry no key. Never the credential itself.
        provider_id: The provider instance id, which is also what `AdapterPool` keys its
            own limiters by — so an injected mapping and the pool agree without either
            translating.
    """

    credential_digest: str
    provider_id: str


class PacingPool:
    """Holds `RateLimiter` instances and latency samples across `Relay` calls.

    Timing metadata only — never a credential, prompt, slot value, or response. See the
    module docstring for the exhaustive list.

    **One event loop.** A `RateLimiter` holds an `asyncio.Semaphore` and an
    `asyncio.Lock`, which bind to the running loop at first await. A pooled limiter used
    from a second loop deadlocks silently, so the pool records the loop it was first used
    on and raises on a mismatch instead. A single-loop ASGI process — uvicorn's default,
    and what a Relay deployment is — never sees this.

    Args:
        max_keys: Distinct credential/provider pairs to pace before evicting the least
            recently used.
        latency_samples: Service-time samples retained per (tenant, target).
    """

    __slots__ = ("_latency", "_limiters", "_loop_id", "_max_keys", "_salt", "_samples")

    def __init__(
        self,
        *,
        max_keys: int = DEFAULT_POOL_SIZE,
        latency_samples: int = DEFAULT_LATENCY_SAMPLES,
    ) -> None:
        if max_keys < 1 or latency_samples < 1:
            raise ValueError("pool bounds must be positive")
        self._salt = secrets.token_bytes(16)
        self._max_keys = max_keys
        self._samples = latency_samples
        self._limiters: OrderedDict[PacingKey, RateLimiter] = OrderedDict()
        self._latency: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._loop_id: int | None = None

    def key_for(self, provider_settings: ProviderSettings) -> PacingKey:
        """Derive the pacing key for one call's provider settings.

        The digest covers the credential when there is one. Settings with no key digest
        the instance id alone, which still pools per instance — just without per-key
        granularity, which is the honest answer when there is no key to distinguish by.

        Args:
            provider_settings: The short-lived settings this call carries.

        Returns:
            The key its pacing state belongs under.
        """
        instance_id = provider_settings.instance_id
        api_key = getattr(provider_settings, "api_key", None)
        material = api_key if isinstance(api_key, str) and api_key else instance_id
        digest = hashlib.sha256(self._salt + material.encode("utf-8")).hexdigest()
        return PacingKey(credential_digest=digest, provider_id=instance_id)

    def limiter_for(
        self, key: PacingKey, limits: RateLimits, dialect: RateLimitHeaders
    ) -> RateLimiter:
        """The limiter this key's pacing state lives in, building one on first use.

        Args:
            key: From `key_for`.
            limits: Bounds to pace against, used only when a limiter is built. A later
                call with different limits reuses the existing limiter rather than
                rebuilding it — rebuilding would discard the very state this pool exists
                to keep, and a caller changing an account's limits mid-process is
                reconfiguring, not describing a new account.
            dialect: Which headers this provider reports its state in.

        Returns:
            The pooled limiter, marked most-recently-used.

        Raises:
            RuntimeError: This pool was already used from a different event loop.
        """
        self._check_loop()
        existing = self._limiters.get(key)
        if existing is not None:
            self._limiters.move_to_end(key)
            return existing

        from anyinfer.routing.limits import RateLimiter

        limiter = RateLimiter(limits, dialect=dialect, provider_id=key.provider_id)
        self._limiters[key] = limiter
        while len(self._limiters) > self._max_keys:
            self._limiters.popitem(last=False)
        return limiter

    def record_latency(self, tenant_id: str, target: str, service_s: float) -> None:
        """Record how long one *successful, unthrottled* call took to serve.

        The qualifier is the point. Feeding throttled or failed calls back in makes the
        estimator self-reinforcing: a busy period produces slow samples, slow samples
        produce longer advertised waits, longer waits produce a deeper queue. Only calls
        that actually completed are evidence about service time.

        Args:
            tenant_id: The tenant the call belonged to.
            target: The target it went to.
            service_s: Wall-clock seconds the call took. Non-finite or negative values are
                ignored rather than raising — a bad clock reading must not fail a request
                that already succeeded.
        """
        if not (service_s >= 0) or service_s == float("inf"):
            return
        key = (tenant_id, target)
        samples = self._latency.get(key)
        if samples is None:
            samples = deque(maxlen=self._samples)
            self._latency[key] = samples
            while len(self._latency) > self._max_keys:
                # Bounded for the same reason the limiters are: a caller cycling targets
                # must not grow this without limit. Eviction forgets timing history, which
                # costs one cold-start estimate.
                self._latency.popitem(last=False)
        self._latency.move_to_end(key)
        samples.append(float(service_s))

    def service_quantile(
        self, tenant_id: str, target: str | None = None, quantile: float = 0.75
    ) -> float | None:
        """An upper quantile of recent service time, or ``None`` with no samples yet.

        A quantile rather than a mean: LLM latency is heavy-tailed and dominated by output
        length, and a mean gets dragged around by the tail. p75 by default, biased high on
        purpose — advertising a wait that is too short costs a rejected round trip and a
        re-queue, while one that is slightly too long costs a little idle capacity.

        Samples are **never pooled across tenants**, whichever form is asked for: an
        estimate computed from another tenant's traffic is that tenant's load, readable off
        a number this one is handed. That is the metadata side channel `RelayRegistry`'s
        uniform error message exists to close, reopened at the estimator.

        Args:
            tenant_id: Whose samples to read.
            target: One target's samples, or ``None`` for this tenant's across all of its
                targets. The tenant-wide form is what admission control needs: a request
                is refused *before* its route resolves, so its target is not yet known —
                and resolving a route the caller will not be allowed to use, purely to
                sharpen a backoff hint, is work done for a rejected request.
            quantile: Where in the sorted samples to read, in ``(0, 1]``.

        Returns:
            The quantile in seconds, or ``None`` when there are no samples to read.
        """
        if target is not None:
            samples: list[float] = list(self._latency.get((tenant_id, target), ()))
        else:
            samples = [
                value
                for (owner, _), ring in self._latency.items()
                if owner == tenant_id
                for value in ring
            ]
        if not samples:
            return None
        samples.sort()
        index = min(len(samples) - 1, max(0, round(quantile * (len(samples) - 1))))
        return samples[index]

    def _check_loop(self) -> None:
        """Bind this pool to one event loop, or refuse.

        Raises:
            RuntimeError: The pool is being used from a loop other than the one it was
                first used on. Loud rather than silent: the alternative is a limiter whose
                semaphore belongs to a dead loop, which deadlocks the first request that
                waits on it with nothing in a log to say why.
        """
        loop_id = id(asyncio.get_running_loop())
        if self._loop_id is None:
            self._loop_id = loop_id
        elif self._loop_id != loop_id:
            raise RuntimeError(
                "a PacingPool is bound to the event loop it was first used on: its "
                "limiters hold asyncio primitives that cannot cross loops. Use one pool "
                "per loop, or run the relay in a single-loop process."
            )
