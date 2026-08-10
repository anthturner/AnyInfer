"""Routing policy: retries, fallback chains, and backoff.

`Route` is a policy *object* rather than a set of client method parameters, so richer
policies (load balancing, cost-aware selection) can be added later without changing any
client signature; richer policies can be added without changing the call surface.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..errors import AuthError, ContextLengthError, ProviderError
from ..types.requests import Target

__all__ = ["Retry", "Route", "backoff_delay", "never_retry_client_errors"]


def never_retry_client_errors(error: ProviderError) -> bool:
    """Retry predicate that refuses errors no amount of repetition will fix.

    Authentication failures and context overflows are deterministic: the identical request
    will fail identically. Retrying them burns the budget that a genuinely transient failure
    later in the route might have needed.

    A spending refusal never reaches this predicate: `SpendLimitError` is not a
    `ProviderError` — no provider was involved, so it leaves the router entirely rather
    than being retried or redirected to the next target. That is deliberate. A ceiling is
    client-wide, so a different target does not satisfy it, and choosing a cheaper one
    because of cost is the adaptive routing this project defers.
    """
    if isinstance(error, AuthError | ContextLengthError):
        return False
    return error.retryable


@dataclass(frozen=True, slots=True)
class Retry:
    """Per-target retry policy.

    Attributes:
        max_attempts: Total attempts per target, including the first.
        backoff_base_s: Base for exponential backoff.
        backoff_max_s: Ceiling for any single delay.
        retry_on: Overrides the default predicate. The default declines deterministic
            failures (auth, context length) and otherwise follows ``error.retryable``.
    """

    max_attempts: int = 2
    backoff_base_s: float = 0.5
    backoff_max_s: float = 30.0
    retry_on: Callable[[ProviderError], bool] | None = None

    def should_retry(self, error: ProviderError) -> bool:
        """Whether ``error`` is worth retrying under this policy."""
        if self.retry_on is not None:
            return self.retry_on(error)
        return never_retry_client_errors(error)


@dataclass(frozen=True, slots=True)
class Route:
    """An ordered fallback chain and the policy applied to it.

    Beyond the general chain, two failure classes get their own chains because the right
    next target differs by *why* the first one failed: a prompt that overflowed one model's
    context needs a larger model, not another same-sized one, and a content-policy refusal
    needs a differently-governed provider, not a retry.

    Attributes:
        targets: Targets to try in order.
        retry: Retry policy applied per target.
        health_gate: Skip targets whose health probe recently failed.
        health_ttl_s: How long a health failure suppresses a target.
        context_window_targets: Chain used after a
            `ContextLengthError`. Empty means "use ``targets``".
        content_policy_targets: Chain used after a content-filter refusal. Empty means "use
            ``targets``".
    """

    targets: tuple[Target, ...]
    retry: Retry = Retry()
    health_gate: bool = True
    health_ttl_s: float = 30.0
    context_window_targets: tuple[Target, ...] = ()
    content_policy_targets: tuple[Target, ...] = ()

    @classmethod
    def of(cls, *targets: Target, retry: Retry | None = None) -> Route:
        """Build a route from positional targets."""
        return cls(targets=tuple(targets), retry=retry or Retry())

    def specialized_chain_for(self, error: ProviderError) -> tuple[Target, ...]:
        """The fallback chain that fits this failure, or ``()`` for the general one."""
        if isinstance(error, ContextLengthError):
            return self.context_window_targets
        return ()

    @classmethod
    def coerce(cls, value: Route | Target | Sequence[Target]) -> Route:
        """Accept a route, a single target string, or a sequence of targets."""
        if isinstance(value, Route):
            return value
        if isinstance(value, str):
            return cls(targets=(value,))
        return cls(targets=tuple(value))


def backoff_delay(
    attempt_number: int,
    retry: Retry,
    *,
    retry_after_s: float | None = None,
) -> float:
    """Compute the delay before the next attempt.

    Exponential from `Retry.backoff_base_s`, raised to the server's ``Retry-After``
    when that is longer, and capped by `Retry.backoff_max_s`. Honoring a server's
    advice is the difference between backing off and being banned.

    Args:
        attempt_number: The attempt that just failed, 1-based.
        retry: The policy in force.
        retry_after_s: Server-advised delay, when supplied.

    Returns:
        Seconds to sleep, never negative.
    """
    exponential: float = retry.backoff_base_s * float(2 ** max(0, attempt_number - 1))
    delay: float = max(exponential, retry_after_s or 0.0)
    return max(0.0, min(delay, retry.backoff_max_s))
