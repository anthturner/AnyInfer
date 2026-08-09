"""Decide where a provider's prompt cache should be engaged.

The core owns the decision; adapters only spell whatever mark the plan names. That split is
the same one structured output already uses — the caller states an intent, the core picks
the strongest mechanism the target actually offers, and losing a rung is an observable
event rather than a silent downgrade.

Two mechanisms, and the difference matters more than it looks:

``explicit``
    The provider takes per-segment marks. The planner decides which segments earn one,
    largest-first, bounded by the provider's own ceiling and floor.
``implicit``
    The provider caches stable prefixes by itself. There is nothing to mark, so a plan
    here carries no marks — its value is the *guard*: noticing when a caller's own request
    changes its prefix between turns and therefore never hits the cache it is paying for.

Nothing here performs I/O, and nothing here rewrites a caller's messages. A plan is a
recommendation the request path applies; it is never a mutation performed behind the
caller's back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..registry import ProviderDescriptor
from ..types.capabilities import Feature, ModelCapabilities
from ..types.requests import CacheMechanism, CachePolicy, GenerationRequest
from .estimate import TokenEstimator

__all__ = ["SYSTEM_SEGMENT", "TOOLS_SEGMENT", "CacheMark", "CachePlan", "plan_cache"]

SYSTEM_SEGMENT = -1
"""Segment index naming the system block, which is not a message index on every dialect."""

TOOLS_SEGMENT = -2
"""Segment index naming the tool declarations."""


@dataclass(frozen=True, slots=True)
class CacheMark:
    """One place the prompt cache should be engaged.

    Attributes:
        segment: `TOOLS_SEGMENT`, `SYSTEM_SEGMENT`, or a zero-based index into the
            request's messages. A message mark means "cache everything up to and including
            this message", which is what every explicit-mark dialect actually expresses.
        estimated_tokens: Planning-side size of the segment, used to decide whether the
            mark was worth placing at all.
    """

    segment: int
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class CachePlan:
    """What the core decided to do about caching for one request.

    A plan with no mechanism is the ordinary case: no policy, or a target that offers
    nothing. It is never an error.

    Attributes:
        mechanism: The mechanism chosen, or ``None`` when caching will not be engaged.
        marks: Where to mark, in wire order. Always empty for ``implicit``.
        estimated_cacheable_tokens: Planning-side total of the marked segments, or of the
            stable prefix under ``implicit``. An estimate of intent — never a saving.
        reasons: Why the plan came out this way, for the degradation event and for humans
            reading a dry run. Content-free.
    """

    mechanism: CacheMechanism | None = None
    marks: tuple[CacheMark, ...] = ()
    estimated_cacheable_tokens: int = 0
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def active(self) -> bool:
        """Whether this plan engages the cache at all."""
        return self.mechanism is not None

    def prefix_signature(self, request: GenerationRequest) -> str:
        """A stable identifier for the part of the request the cache depends on.

        Two requests whose signatures differ cannot share a cached prefix, whatever the
        mechanism. Used by the implicit-mode guard to notice a caller who is defeating
        their own cache — a timestamp in the system prompt, a re-ordered tool list.
        """
        system = "\n".join(m.text for m in request.messages if m.role == "system")
        tools = json.dumps(
            [[t.name, t.description, t.parameters] for t in request.tools],
            sort_keys=True,
            default=str,
        )
        return f"{len(system)}:{hash(system) & 0xFFFFFFFF:08x}:{hash(tools) & 0xFFFFFFFF:08x}"


def plan_cache(
    request: GenerationRequest,
    policy: CachePolicy | None,
    capabilities: ModelCapabilities,
    descriptor: ProviderDescriptor,
    estimator: TokenEstimator,
) -> CachePlan:
    """Decide how, and where, to engage the target's prompt cache.

    Args:
        request: The request about to be dispatched.
        policy: The policy in force, or ``None`` for no placement.
        capabilities: Assembled capabilities for the resolved target.
        descriptor: The serving provider's descriptor, which declares its mechanism.
        estimator: Token counting, used only for the planning figure — a mark is an
            optimization, and optimizing against the conservative number is the safe
            direction.

    Returns:
        The plan. A plan that engages nothing carries a reason saying why.
    """
    if policy is None or not policy.active:
        return CachePlan()

    mechanism = descriptor.cache_mechanism
    if mechanism is None:
        return CachePlan(reasons=("the target declares no prompt-cache mechanism",))

    if mechanism == "explicit" and not _supports_placement(capabilities):
        return CachePlan(
            reasons=("the target's capabilities do not include cache placement",)
        )

    if mechanism == "implicit":
        # Nothing to send. The plan exists so the request path can watch prefix stability
        # and so the result can report which mechanism was in play.
        prefix_tokens = _estimate_prefix(request, estimator, policy)
        return CachePlan(
            mechanism="implicit",
            estimated_cacheable_tokens=prefix_tokens,
            reasons=("the target caches stable prefixes without being asked",),
        )

    return _plan_explicit(request, policy, descriptor, estimator)


def _plan_explicit(
    request: GenerationRequest,
    policy: CachePolicy,
    descriptor: ProviderDescriptor,
    estimator: TokenEstimator,
) -> CachePlan:
    """Choose which segments earn one of a bounded number of marks."""
    floor = max(policy.min_segment_tokens, descriptor.cache_min_tokens)
    budget = min(policy.max_marks, descriptor.cache_max_marks or policy.max_marks)
    reasons: list[str] = []

    candidates: list[CacheMark] = []
    if policy.include_tools and request.tools:
        candidates.append(CacheMark(TOOLS_SEGMENT, _tools_tokens(request, estimator)))
    if policy.include_system:
        system_tokens = _system_tokens(request, estimator)
        if system_tokens:
            candidates.append(CacheMark(SYSTEM_SEGMENT, system_tokens))

    # The longest stable message prefix is everything before the final user turn: the last
    # turn is what changed, and marking it would cache something no later request reuses.
    last_stable = _last_stable_message(request)
    if last_stable is not None:
        prefix_tokens = sum(
            estimator.estimate(message.text).tokens
            for message in request.messages[: last_stable + 1]
            if message.role != "system"
        )
        if prefix_tokens:
            candidates.append(CacheMark(last_stable, prefix_tokens))

    worthwhile = [c for c in candidates if c.estimated_tokens >= floor]
    if len(worthwhile) < len(candidates):
        reasons.append(f"segments under {floor} tokens are not worth a mark")

    if not worthwhile:
        return CachePlan(reasons=tuple(reasons or ("nothing large enough to cache",)))

    # Largest first, so a scarce mark budget buys the most.
    chosen = sorted(worthwhile, key=lambda mark: mark.estimated_tokens, reverse=True)
    if len(chosen) > budget:
        reasons.append(f"the target accepts at most {budget} marks")
        chosen = chosen[:budget]

    ordered = tuple(sorted(chosen, key=lambda mark: mark.segment))
    return CachePlan(
        mechanism="explicit",
        marks=ordered,
        estimated_cacheable_tokens=sum(m.estimated_tokens for m in ordered),
        reasons=tuple(reasons),
    )


def _supports_placement(capabilities: ModelCapabilities) -> bool:
    return bool(capabilities.features.value & Feature.CACHE_PLACEMENT)


def _system_tokens(request: GenerationRequest, estimator: TokenEstimator) -> int:
    text = "\n".join(m.text for m in request.messages if m.role == "system")
    return estimator.estimate(text).tokens if text else 0


def _tools_tokens(request: GenerationRequest, estimator: TokenEstimator) -> int:
    if not request.tools:
        return 0
    serialized = json.dumps(
        [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in request.tools
        ],
        default=str,
    )
    return estimator.estimate(serialized).tokens


def _estimate_prefix(
    request: GenerationRequest, estimator: TokenEstimator, policy: CachePolicy
) -> int:
    """How much of this request is stable enough for an implicit cache to hold."""
    total = 0
    if policy.include_system:
        total += _system_tokens(request, estimator)
    if policy.include_tools:
        total += _tools_tokens(request, estimator)
    last_stable = _last_stable_message(request)
    if last_stable is not None:
        total += sum(
            estimator.estimate(message.text).tokens
            for message in request.messages[: last_stable + 1]
            if message.role != "system"
        )
    return total


def _last_stable_message(request: GenerationRequest) -> int | None:
    """Index of the last message that is not part of the current turn.

    Returns ``None`` when every message is the current turn, which is the single-message
    case where there is no reusable history to cache.
    """
    non_system = [
        index for index, message in enumerate(request.messages) if message.role != "system"
    ]
    if len(non_system) < 2:
        return None
    return non_system[-2]
