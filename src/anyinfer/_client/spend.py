"""Spend governance — the pre-dispatch checks that stop a request costing more than allowed.

The four methods that consult `SpendPolicy` and `SpendLedger` before a call goes out:
the generation and per-operation ceilings, the arena ceiling, and the cost estimate they
all rest on.

A.1.3 proposed these move beside `capabilities/ledger.py`. They stay in `_client/`
instead: they are client methods that read client state and call `resolve()`, and
`capabilities/` is the lower layer that must not know about the client. Moving them there
would have inverted a dependency the import-linter contracts exist to protect. `ledger.py`
keeps owning what a ledger *is*; this owns when the client consults one.

Mixed into `AsyncClient`, not usable alone — see `generation.py`'s docstring.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

from ..capabilities.budget import build_context_budget
from ..capabilities.estimate import TokenEstimator
from ..capabilities.ledger import SpendLedger
from ..capabilities.pricing import (
    compute_operation_cost,
)
from ..errors import (
    AnyInferError,
    SpendLimitError,
)
from ..routing.policy import Route
from ..types.capabilities import (
    ModelCapabilities,
    TokenCalibration,
)
from ..types.operations import (
    InferenceOperation,
)
from ..types.requests import (
    GenerationRequest,
    ResolvedTarget,
    SpendPolicy,
    Target,
)
from ..types.results import (
    Usage,
)
from .messages import _spend_prechecked


class SpendGovernanceMixin:
    """Pre-dispatch spend checks. Mixed into `AsyncClient`; not usable alone."""

    if TYPE_CHECKING:
        # Declared, never defined — `AsyncClient` supplies these. See `generation.py`.
        _estimator: TokenEstimator
        _ledger: SpendLedger | None
        _spend_policy: SpendPolicy | None

        def resolve(self, target: Target) -> ResolvedTarget: ...

        def _operation_capabilities(
            self, resolved: ResolvedTarget
        ) -> ModelCapabilities | None: ...

    def _enforce_spend_ceiling(
        self,
        estimate: Decimal | None,
        *,
        policy: SpendPolicy,
        request_id: str,
        unknown: bool,
        unknown_message: str,
        unknown_hint: str | None = None,
        over_request_message: str,
        over_request_hint: str | None = None,
        over_total_message: Callable[[Decimal, Decimal], str],
        over_total_hint: str | None = None,
    ) -> None:
        """Shared tail of every spend check: unknown-cost policy, then the two ceilings.

        Every call site (single-request, operation, and summed-arena) has already produced
        its own high-end ``estimate`` — or established that it could not, signaled by
        ``unknown`` — because what is being estimated differs by call site. What repeats
        everywhere is: refuse (or not) when the cost is unknown, refuse when the per-request
        ceiling is crossed, and otherwise reserve against the cumulative ceiling through the
        ledger. Message text is supplied by the caller so each site keeps its exact wording.

        Raises:
            SpendLimitError: When a ceiling would be crossed, or the cost is unknown and the
                policy says not to spend blind.
            RuntimeError: When a cumulative ceiling is configured but no ledger was supplied.
        """
        spent = self._ledger.totals().cost if self._ledger is not None else Decimal(0)
        if unknown and policy.on_unknown == "refuse":
            raise SpendLimitError(
                unknown_message,
                limit_usd=policy.max_request_usd or policy.max_total_usd,
                spent_usd=spent,
                hint=unknown_hint,
            )
        if estimate is None:
            return

        if policy.max_request_usd is not None and estimate > policy.max_request_usd:
            raise SpendLimitError(
                over_request_message,
                limit_usd=policy.max_request_usd,
                spent_usd=spent,
                estimated_usd=estimate,
                hint=over_request_hint,
            )

        if policy.max_total_usd is not None:
            ledger = self._ledger
            if ledger is None:
                raise RuntimeError("a cumulative spend policy requires a spend ledger")
            accepted, spent, reserved = ledger.reserve(request_id, estimate, policy.max_total_usd)
            if not accepted:
                raise SpendLimitError(
                    over_total_message(spent, reserved),
                    limit_usd=policy.max_total_usd,
                    spent_usd=spent,
                    estimated_usd=estimate,
                    hint=over_total_hint,
                )

    def _check_operation_spend(
        self,
        *,
        operation: InferenceOperation,
        route: Route,
        texts: Sequence[str] | None,
        request_id: str,
    ) -> None:
        """Refuse an embed/rerank call that would cross this client's spending ceiling.

        Embedding costs are estimated from the caller's texts at the first target's
        trusted input rate. Rerank costs are never estimated — search-unit billing has no
        verified request-shape formula, and a guessed estimate would enforce nothing
        while appearing to — so ``on_unknown`` governs rerank calls.

        Raises:
            SpendLimitError: When a ceiling would be crossed, or when the cost cannot be
                known and the policy says not to spend blind.
        """
        policy = self._spend_policy
        if policy is None or not policy.active:
            return

        estimate: Decimal | None = None
        if operation == "embedding" and texts is not None and route.targets:
            try:
                resolved = self.resolve(route.targets[0])
                capabilities = self._operation_capabilities(resolved)
            except (AnyInferError, ValueError):
                capabilities = None
            if capabilities is not None:
                tokens = sum(self._estimator.estimate(t).tokens for t in texts)
                estimate = compute_operation_cost(
                    Usage(input_tokens=tokens), capabilities, "embedding"
                )

        self._enforce_spend_ceiling(
            estimate,
            policy=policy,
            request_id=request_id,
            unknown=estimate is None,
            unknown_message=f"the cost of this {operation} request cannot be estimated",
            unknown_hint=(
                "this target has no trusted pricing (rerank costs are never "
                "estimated); set on_unknown='allow' to send it anyway, or supply "
                "pricing as a capability override"
            ),
            over_request_message=(
                f"this {operation} request could cost {estimate}, above the per-request "
                f"ceiling of {policy.max_request_usd}"
            ),
            over_total_message=lambda spent, reserved: (
                f"this client has spent {spent}, reserved {reserved}, and this "
                f"{operation} request could cost {estimate}, above the total "
                f"ceiling {policy.max_total_usd}"
            ),
        )

    def _check_spend(
        self,
        request: GenerationRequest,
        resolved: ResolvedTarget,
        capabilities: ModelCapabilities | None,
        *,
        request_id: str,
    ) -> None:
        """Refuse a request that would cross this client's spending ceiling.

        Runs before dispatch, so a refusal costs nothing. The estimate is the *high* end of
        the preflight range and is reported in the error, so a caller can see the arithmetic
        rather than being told only that they were declined.

        Raises:
            SpendLimitError: When a ceiling would be crossed, or when the cost cannot be
                known and the policy says not to spend blind.
        """
        if _spend_prechecked.get():
            return
        policy = self._spend_policy
        if policy is None or not policy.active:
            return

        estimate = self._estimate_request_cost(request, capabilities)

        self._enforce_spend_ceiling(
            estimate,
            policy=policy,
            request_id=request_id,
            unknown=estimate is None,
            unknown_message=f"the cost of a request to {resolved} cannot be estimated",
            unknown_hint=(
                "this target has no trusted pricing; set on_unknown='allow' to "
                "send it anyway, or supply pricing as a capability override"
            ),
            over_request_message=(
                f"a request to {resolved} could cost {estimate}, above the per-request "
                f"ceiling of {policy.max_request_usd}"
            ),
            over_request_hint=(
                "shorten the prompt, cap max_output_tokens, or raise max_request_usd"
            ),
            over_total_message=lambda spent, reserved: (
                f"this client has spent {spent}, reserved {reserved}, and the next "
                f"request could cost {estimate}, above the ceiling of "
                f"{policy.max_total_usd}"
            ),
            over_total_hint="raise max_total_usd, or reset the ledger to start a new budget",
        )

    def _estimate_request_cost(
        self, request: GenerationRequest, capabilities: ModelCapabilities | None
    ) -> Decimal | None:
        """The high end of a request's preflight cost range, or ``None`` when unknowable."""
        if capabilities is None or capabilities.pricing is None:
            return None
        budget = build_context_budget(
            request,
            capabilities,
            estimator=self._estimator,
            calibration=TokenCalibration(),
        )
        estimated = budget.estimated_cost
        return estimated.high if estimated is not None else None
