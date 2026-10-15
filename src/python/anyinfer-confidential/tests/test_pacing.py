"""Pacing state that survives a per-call client, and the bounds around it.

Core's `RateLimiter` was structurally inert behind the Relay: `_forward` builds a client
per call and closes it in a `finally`, and the token bucket, header-observed windows, and
in-flight accounting all live inside that client. Every forward call therefore paced
against an empty bucket and discarded what the provider had just reported.

The fix is to pool the *limiter* — not the client, which must keep dying with the BYOK
credential it carries. So the tests that matter here are about identity (does the same key
reach the same limiter?), about what is and is not held (timing, never secrets), and about
the bounds that stop a hostile caller growing either.
"""

from __future__ import annotations

import asyncio
import threading

import anyinfer as ai
import pytest
from anyinfer.types.capabilities import RateLimitHeaders
from anyinfer.types.requests import RateLimits

from anyinfer_confidential.pacing import DEFAULT_RESERVE_FRACTION, PacingKey, PacingPool

LIMITS = RateLimits(requests_per_minute=60)
DIALECT = RateLimitHeaders(requests_remaining="x-remaining", requests_reset="x-reset")


def _settings(api_key: str | None = "sk-live-abc", alias: str | None = None) -> ai.ProviderSettings:
    return ai.ProviderSettings.of(
        "openai", api_key=api_key, alias=alias, base_url="https://fake.invalid/v1"
    )


# ---- identity ----------------------------------------------------------------------------


async def test_the_same_key_and_provider_reach_the_same_limiter() -> None:
    """The whole point: pacing state has to outlive the client that used it."""
    pool = PacingPool()
    first = pool.limiter_for(pool.key_for(_settings()), LIMITS, DIALECT)
    second = pool.limiter_for(pool.key_for(_settings()), LIMITS, DIALECT)
    assert first is second


async def test_two_keys_at_one_provider_get_independent_limiters() -> None:
    """A rate limit belongs to an account, so two accounts must not pace each other."""
    pool = PacingPool()
    a = pool.limiter_for(pool.key_for(_settings("sk-one")), LIMITS, DIALECT)
    b = pool.limiter_for(pool.key_for(_settings("sk-two")), LIMITS, DIALECT)
    assert a is not b


async def test_one_key_at_two_provider_instances_gets_independent_limiters() -> None:
    pool = PacingPool()
    a = pool.limiter_for(pool.key_for(_settings(alias="work")), LIMITS, DIALECT)
    b = pool.limiter_for(pool.key_for(_settings(alias="personal")), LIMITS, DIALECT)
    assert a is not b


async def test_settings_with_no_key_still_pool_per_instance() -> None:
    """Without a key to distinguish by, per-instance is the honest granularity."""
    pool = PacingPool()
    a = pool.limiter_for(pool.key_for(_settings(None)), LIMITS, DIALECT)
    b = pool.limiter_for(pool.key_for(_settings(None)), LIMITS, DIALECT)
    assert a is b


async def test_changed_limits_reuse_the_limiter_rather_than_discarding_its_state() -> None:
    """Rebuilding would throw away the very state this pool exists to keep."""
    pool = PacingPool()
    key = pool.key_for(_settings())
    first = pool.limiter_for(key, LIMITS, DIALECT)
    second = pool.limiter_for(key, RateLimits(requests_per_minute=6000), DIALECT)
    assert first is second


# ---- what is held, and what is not --------------------------------------------------------


def test_the_digest_is_neither_the_key_nor_derivable_from_it_without_the_salt() -> None:
    pool = PacingPool()
    secret = "sk-live-super-secret-value"
    digest = pool.key_for(_settings(secret)).credential_digest

    assert secret not in digest
    assert digest != secret

    import hashlib

    assert digest != hashlib.sha256(secret.encode()).hexdigest(), "an unsalted digest is a lookup"


def test_two_pools_digest_the_same_key_differently() -> None:
    """Per-pool salt: a digest that escaped one process means nothing in another."""
    settings = _settings()
    assert PacingPool().key_for(settings) != PacingPool().key_for(settings)


def test_a_pacing_key_carries_no_credential_in_its_repr() -> None:
    """Keys end up in tracebacks and debugger frames; neither may show a secret."""
    key = PacingPool().key_for(_settings("sk-live-abc"))
    assert "sk-live-abc" not in repr(key)


async def test_the_pool_holds_neither_the_settings_nor_the_credential() -> None:
    """A settings object carries the credential, so keeping one would keep the credential.

    Asserted by walking the pool's own reachable state rather than by weak reference:
    `ProviderSettings` is slotted and cannot be weakly referenced, and this checks the
    stronger property anyway — that the secret appears nowhere in what the pool retains.
    """
    pool = PacingPool()
    secret = "sk-live-super-secret-value"
    pool.limiter_for(pool.key_for(_settings(secret)), LIMITS, DIALECT)

    seen: set[int] = set()

    def _walk(value: object, depth: int = 0) -> list[str]:
        if depth > 6 or id(value) in seen:
            return []
        seen.add(id(value))
        found: list[str] = []
        if isinstance(value, str):
            return [value] if secret in value else []
        if isinstance(value, ai.ProviderSettings):
            found.append("<ProviderSettings retained>")
        for child in _children(value):
            found.extend(_walk(child, depth + 1))
        return found

    def _children(value: object) -> list[object]:
        if isinstance(value, dict):
            return [*value.keys(), *value.values()]
        if isinstance(value, list | tuple | set | frozenset):
            return list(value)
        slots = getattr(type(value), "__slots__", ())
        by_slot = [getattr(value, name) for name in slots if hasattr(value, name)]
        return [*by_slot, *vars(value).values()] if hasattr(value, "__dict__") else by_slot

    leaks = _walk(pool)
    assert not leaks, f"the pool retained credential-bearing state: {leaks}"


# ---- bounds --------------------------------------------------------------------------------


async def test_the_limiter_pool_evicts_least_recently_used_past_its_bound() -> None:
    """A caller cycling keys must not be able to grow this without limit."""
    pool = PacingPool(max_keys=3)
    limiters = [
        pool.limiter_for(pool.key_for(_settings(f"sk-{i}")), LIMITS, DIALECT) for i in range(3)
    ]
    pool.limiter_for(pool.key_for(_settings("sk-0")), LIMITS, DIALECT)  # touch the oldest
    pool.limiter_for(pool.key_for(_settings("sk-new")), LIMITS, DIALECT)  # evicts sk-1

    assert pool.limiter_for(pool.key_for(_settings("sk-0")), LIMITS, DIALECT) is limiters[0]
    assert pool.limiter_for(pool.key_for(_settings("sk-1")), LIMITS, DIALECT) is not limiters[1]


@pytest.mark.parametrize("kwargs", [{"max_keys": 0}, {"latency_samples": 0}])
def test_a_pool_with_a_non_positive_bound_is_refused(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        PacingPool(**kwargs)


async def test_a_pool_refuses_a_second_event_loop_loudly() -> None:
    """A pooled limiter's asyncio primitives bind to one loop; the alternative is a deadlock."""
    pool = PacingPool()
    pool.limiter_for(pool.key_for(_settings()), LIMITS, DIALECT)

    failure: list[BaseException] = []

    def _other_loop() -> None:
        try:
            asyncio.run(_use())
        except BaseException as exc:
            failure.append(exc)

    async def _use() -> None:
        pool.limiter_for(pool.key_for(_settings()), LIMITS, DIALECT)

    thread = threading.Thread(target=_other_loop)
    thread.start()
    thread.join()

    assert failure and isinstance(failure[0], RuntimeError)
    assert "event loop" in str(failure[0])


# ---- service-time samples --------------------------------------------------------------------


def test_a_quantile_reads_high_rather_than_averaging() -> None:
    """LLM latency is heavy-tailed; a mean gets dragged around by the tail."""
    pool = PacingPool()
    for value in (0.1, 0.1, 0.1, 0.1, 10.0):
        pool.record_latency("acme", "openai:gpt-5", value)

    quantile = pool.service_quantile("acme", "openai:gpt-5")
    assert quantile is not None
    mean = (0.1 * 4 + 10.0) / 5
    assert quantile < mean, "p75 must not be dragged by one slow outlier the way a mean is"
    assert quantile >= 0.1


def test_no_samples_reports_absence_rather_than_zero() -> None:
    """Zero would tell a client to retry immediately, which is the opposite of the truth."""
    assert PacingPool().service_quantile("acme", "openai:gpt-5") is None


def test_one_tenants_samples_never_move_another_tenants_estimate() -> None:
    """The estimator is the last place the tenant side channel could reopen."""
    pool = PacingPool()
    for _ in range(20):
        pool.record_latency("noisy", "openai:gpt-5", 30.0)
    pool.record_latency("quiet", "openai:gpt-5", 0.2)

    assert pool.service_quantile("quiet", "openai:gpt-5") == pytest.approx(0.2)
    assert pool.service_quantile("quiet") == pytest.approx(0.2)


def test_a_tenant_wide_quantile_spans_that_tenants_targets_only() -> None:
    """Admission refuses before a route resolves, so the target is not yet known."""
    pool = PacingPool()
    pool.record_latency("acme", "openai:gpt-5", 1.0)
    pool.record_latency("acme", "anthropic:claude", 9.0)
    pool.record_latency("other", "openai:gpt-5", 99.0)

    assert pool.service_quantile("acme") == pytest.approx(9.0)


def test_a_bad_clock_reading_is_ignored_rather_than_failing_a_finished_call() -> None:
    pool = PacingPool()
    pool.record_latency("acme", "t", float("inf"))
    pool.record_latency("acme", "t", float("nan"))
    pool.record_latency("acme", "t", -1.0)
    assert pool.service_quantile("acme", "t") is None


def test_samples_are_bounded_per_pair() -> None:
    pool = PacingPool(latency_samples=4)
    for value in range(100):
        pool.record_latency("acme", "t", float(value))
    # Only the last four survive, so the quantile reflects recent traffic, not all of it.
    assert pool.service_quantile("acme", "t", quantile=0.0) == pytest.approx(96.0)


def test_the_reserve_default_leaves_room_for_the_customers_own_traffic() -> None:
    """A Relay forwarding with a customer's BYOK key is not that key's only consumer."""
    assert 0 < DEFAULT_RESERVE_FRACTION < 1
    assert RateLimits(reserve_fraction=DEFAULT_RESERVE_FRACTION).reserve_fraction > 0


def test_a_pacing_key_is_hashable_and_compares_by_value() -> None:
    a = PacingKey(credential_digest="d", provider_id="openai")
    b = PacingKey(credential_digest="d", provider_id="openai")
    assert a == b and hash(a) == hash(b)
    assert len({a, b}) == 1
