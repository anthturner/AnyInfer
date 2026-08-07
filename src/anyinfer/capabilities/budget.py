"""The context budget calculator.

Answers the question apps otherwise hand-roll: *given this model's context window, how many
input tokens may this request spend, and how many remain?* The arithmetic — input allowance
= context window - output reserve - clamped safety headroom — has two deliberate
properties:

- **Unknown stays unknown.** An unknown context window yields ``None`` allowance and a
  ``None`` verdict, never a guess
  presented as a bound. Tri-state, exactly like cost.
- **The output reserve is derived, not flat.** A request that sets
  ``max_output_tokens`` reserves exactly that; otherwise the default reserve is capped by
  the model's known maximum output — reserving 4,096 tokens for a model that can only emit
  1,024 would waste allowance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..types.capabilities import ModelCapabilities, Pricing, Sourced
from ..types.requests import GenerationRequest
from .estimate import RequestEstimate, TokenEstimator, estimate_request
from .pricing import CostEstimate, estimate_cost

__all__ = [
    "DEFAULT_OUTPUT_RESERVE_TOKENS",
    "HEADROOM_FRACTION",
    "MAXIMUM_HEADROOM_TOKENS",
    "MINIMUM_HEADROOM_TOKENS",
    "ContextBudget",
    "build_context_budget",
    "headroom_for",
]

DEFAULT_OUTPUT_RESERVE_TOKENS = 4_096
"""Output tokens reserved when the request does not set ``max_output_tokens``."""

HEADROOM_FRACTION = 0.05
"""Fraction of the context window held back against estimation error."""

MINIMUM_HEADROOM_TOKENS = 256
"""Headroom floor, so tiny windows still keep a real safety margin."""

MAXIMUM_HEADROOM_TOKENS = 8_192
"""Headroom ceiling, so huge windows do not strand five figures of allowance."""


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """A request's estimated size held against a model's known capacity.

    The verdict is tri-state: `fits` is ``True``/``False`` when the context window
    is known, and ``None`` when it is not — an unknown capacity is reported as unknown,
    never guessed.

    Attributes:
        context_window: The model's context window with its provenance, or ``None`` when
            nothing trustworthy is known.
        estimate: The per-component input-token estimate.
        output_reserve_tokens: Tokens reserved for the response.
        headroom_tokens: Safety margin against estimation error.
        pricing: The model's per-token rates with their provenance, when known.
    """

    context_window: Sourced[int] | None
    estimate: RequestEstimate
    output_reserve_tokens: int
    headroom_tokens: int
    pricing: Sourced[Pricing] | None = None

    @property
    def input_allowance_tokens(self) -> int | None:
        """Tokens the input may spend, or ``None`` when the window is unknown."""
        if self.context_window is None:
            return None
        return max(
            0, self.context_window.value - self.output_reserve_tokens - self.headroom_tokens
        )

    @property
    def remaining_tokens(self) -> int | None:
        """Allowance left after the estimated input; negative when over budget.

        This is the number an app packs context against: keep adding material while it
        stays positive.
        """
        allowance = self.input_allowance_tokens
        if allowance is None:
            return None
        return allowance - self.estimate.tokens

    @property
    def fits(self) -> bool | None:
        """Whether the estimated request fits the allowance; ``None`` when unknowable."""
        remaining = self.remaining_tokens
        if remaining is None:
            return None
        return remaining >= 0

    @property
    def estimated_cost(self) -> CostEstimate | None:
        """A preflight cost range, or ``None`` when no trustworthy pricing exists.

        Estimated money never mixes with reported money:
        `cost_usd` is only ever computed from
        provider-reported usage, and this range is only ever computed from the estimate.
        """
        return estimate_cost(self.estimate, self.output_reserve_tokens, self.pricing)


def headroom_for(context_window_tokens: int) -> int:
    """The default safety headroom for a window: 5%, clamped to [256, 8192]."""
    return max(
        MINIMUM_HEADROOM_TOKENS,
        min(
            MAXIMUM_HEADROOM_TOKENS,
            math.ceil(context_window_tokens * HEADROOM_FRACTION),
        ),
    )


def build_context_budget(
    request: GenerationRequest,
    capabilities: ModelCapabilities | None,
    *,
    estimator: TokenEstimator | None = None,
    output_reserve_tokens: int | None = None,
    headroom_tokens: int | None = None,
) -> ContextBudget:
    """Compute the context budget for one request against one model's capabilities.

    Args:
        request: The request to size.
        capabilities: Assembled capabilities supplying the context window and maximum
            output size. ``None`` means nothing is known — the budget stays tri-state.
        estimator: Token counting strategy; defaults to the byte heuristic.
        output_reserve_tokens: Overrides the derived output reserve.
        headroom_tokens: Overrides the default clamped headroom.

    Returns:
        The computed `ContextBudget`.

    Raises:
        ValueError: If an explicit reserve or headroom is negative.
    """
    window = capabilities.context_window if capabilities is not None else None
    reserve = _resolve_reserve(request, capabilities, output_reserve_tokens)

    if headroom_tokens is not None:
        if headroom_tokens < 0:
            raise ValueError("safety headroom must not be negative")
        headroom = headroom_tokens
    else:
        headroom = headroom_for(window.value) if window is not None else 0

    return ContextBudget(
        context_window=window,
        estimate=estimate_request(request, estimator=estimator),
        output_reserve_tokens=reserve,
        headroom_tokens=headroom,
        pricing=capabilities.pricing if capabilities is not None else None,
    )


def _resolve_reserve(
    request: GenerationRequest,
    capabilities: ModelCapabilities | None,
    explicit: int | None,
) -> int:
    """Pick the output reserve: explicit → the request's cap → default, bounded by the model."""
    if explicit is not None:
        if explicit < 0:
            raise ValueError("output reserve must not be negative")
        return explicit
    if request.sampling.max_output_tokens is not None:
        return request.sampling.max_output_tokens
    reserve = DEFAULT_OUTPUT_RESERVE_TOKENS
    if capabilities is not None and capabilities.max_output_tokens is not None:
        reserve = min(reserve, capabilities.max_output_tokens.value)
    return reserve
