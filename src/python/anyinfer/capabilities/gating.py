"""Pre-dispatch context-window gating.

Fail fast, or let the router fall back, when a request provably cannot fit the target's
context window, instead of paying a round trip to learn the same thing. Two rules keep the
gate honest:

- **Only known bounds gate.** A window whose provenance is ``default`` is a placeholder,
  not a fact; it never blocks a request (the same trust rule pricing follows).
- **Only the floor gates.** The gate compares the estimate's *lower bound* against the
  *whole* window — no reserve, no headroom. A heuristic planning estimate may overshoot,
  and wrongly refusing a servable request is worse than one wasted round trip; the floor
  makes the gate's claim as close to "provable" as a heuristic allows.

A gated target raises `ContextLengthError`, the same class a
provider would have returned, so ``Route.context_window_targets`` redirects the route
identically either way — just without the latency.
"""

from __future__ import annotations

from ..errors import ContextLengthError
from ..types.capabilities import ModelCapabilities, TokenCalibration
from ..types.requests import GenerationRequest
from .budget import ContextBudget, build_context_budget
from .estimate import TokenEstimator
from .pricing import TRUSTED_PROVENANCE

__all__ = ["check_context_fit", "context_gate_error"]


def context_gate_error(
    budget: ContextBudget,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ContextLengthError | None:
    """Decide whether a budget provably overflows its window.

    Args:
        budget: The computed budget for the request/target pair.
        provider: Provider id, for the error's structured fields.
        model: Model id, for the error message.

    Returns:
        The error to raise before dispatch, or ``None`` when the request may proceed —
        including whenever the window is unknown or untrusted.
    """
    if budget.estimate.unpriced_parts:
        return None
    window = budget.context_window
    if window is None or window.provenance not in TRUSTED_PROVENANCE:
        return None
    if budget.estimate.floor <= window.value:
        return None
    name = model or "the model"
    return ContextLengthError(
        f"request needs at least {budget.estimate.floor} input tokens (preflight estimate), "
        f"exceeding {name}'s {window.value}-token context window ({window.provenance})",
        provider=provider,
        hint=(
            "shorten the prompt, or set Route.context_window_targets so overflow falls "
            "back to a larger-context model"
        ),
    )


def check_context_fit(
    request: GenerationRequest,
    capabilities: ModelCapabilities | None,
    *,
    estimator: TokenEstimator | None = None,
    calibration: TokenCalibration | None = None,
    output_reserve_tokens: int | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> ContextBudget:
    """Build the budget for a request and raise if it provably cannot fit.

    Args:
        request: The `GenerationRequest` to size.
        capabilities: The target's assembled capabilities.
        estimator: Token counting strategy; defaults to the byte heuristic.
        calibration: The target provider's declared envelope correction. It never affects
            the gate's decision — the gate reads the floor, which no calibration moves —
            but it keeps the returned budget consistent with the one `budget()` reports.
        output_reserve_tokens: Overrides the derived output reserve.
        provider: Provider id, for the error's structured fields.
        model: Model id, for the error message.

    Returns:
        The computed `ContextBudget` when the
        request may proceed.

    Raises:
        ContextLengthError: When the estimate's floor exceeds a trusted-provenance
            context window.
    """
    budget = build_context_budget(
        request,
        capabilities,
        estimator=estimator,
        calibration=calibration,
        output_reserve_tokens=output_reserve_tokens,
    )
    error = context_gate_error(budget, provider=provider, model=model)
    if error is not None:
        raise error
    return budget
