"""Where the prompt cache gets engaged, and — more often — why it does not."""

from __future__ import annotations

from anyinfer.capabilities.cache import (
    SYSTEM_SEGMENT,
    TOOLS_SEGMENT,
    plan_cache,
)
from anyinfer.capabilities.estimate import HeuristicTokenEstimator
from anyinfer.registry import ProviderDescriptor
from anyinfer.testing import ScriptedProvider
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
from anyinfer.types.messages import Message, Text, assistant, system, user
from anyinfer.types.requests import CachePolicy, GenerationRequest, ToolSpec

ESTIMATOR = HeuristicTokenEstimator()

PLACEMENT_CAPABILITIES = ModelCapabilities(
    features=Sourced(Feature.STREAMING | Feature.CACHE_PLACEMENT, "catalog")
)


def _descriptor(**overrides: object) -> ProviderDescriptor:
    base = ScriptedProvider("acme").descriptor()
    return ProviderDescriptor(
        id=base.id,
        display_name=base.display_name,
        factory=base.factory,
        **overrides,  # type: ignore[arg-type]
    )


def _long(prefix: str, tokens: int = 2000) -> str:
    """Text comfortably above a 1024-token floor under the byte heuristic."""
    return f"{prefix} " + ("word " * (tokens * 3))


def _request(**overrides: object) -> GenerationRequest:
    fields: dict[str, object] = {
        "messages": (
            system(_long("system")),
            user(_long("first question")),
            assistant(_long("first answer")),
            user("and now a short follow-up"),
        )
    }
    fields.update(overrides)
    return GenerationRequest(**fields)  # type: ignore[arg-type]


# ---- nothing happens unless asked ----------------------------------------------------


def test_no_policy_means_no_plan() -> None:
    plan = plan_cache(
        _request(), None, PLACEMENT_CAPABILITIES, _descriptor(cache_mechanism="explicit"), ESTIMATOR
    )

    assert not plan.active
    assert plan.marks == ()


def test_mode_off_means_no_plan() -> None:
    plan = plan_cache(
        _request(),
        CachePolicy(mode="off"),
        PLACEMENT_CAPABILITIES,
        _descriptor(cache_mechanism="explicit"),
        ESTIMATOR,
    )

    assert not plan.active


def test_a_provider_with_no_mechanism_gets_no_plan_and_says_why() -> None:
    plan = plan_cache(
        _request(), CachePolicy(), PLACEMENT_CAPABILITIES, _descriptor(), ESTIMATOR
    )

    assert not plan.active
    assert plan.reasons
    assert "no prompt-cache mechanism" in plan.reasons[0]


def test_capabilities_without_placement_block_explicit_marks() -> None:
    """A descriptor may declare the mechanism while a given model lacks the feature."""
    plan = plan_cache(
        _request(),
        CachePolicy(),
        ModelCapabilities(features=Sourced(Feature.STREAMING, "catalog")),
        _descriptor(cache_mechanism="explicit", cache_max_marks=4),
        ESTIMATOR,
    )

    assert not plan.active
    assert "capabilities" in plan.reasons[0]


# ---- explicit marks ------------------------------------------------------------------


def test_large_segments_earn_marks_in_wire_order() -> None:
    request = _request(
        tools=(ToolSpec(name="search", description=_long("tool"), parameters={}),)
    )

    plan = plan_cache(
        request,
        CachePolicy(),
        PLACEMENT_CAPABILITIES,
        _descriptor(cache_mechanism="explicit", cache_max_marks=4),
        ESTIMATOR,
    )

    assert plan.mechanism == "explicit"
    segments = [mark.segment for mark in plan.marks]
    assert TOOLS_SEGMENT in segments
    assert SYSTEM_SEGMENT in segments
    assert segments == sorted(segments)
    assert plan.estimated_cacheable_tokens > 0


def test_segments_below_the_floor_are_not_marked() -> None:
    """Below a provider's floor a mark is billed as a write that never amortizes."""
    request = GenerationRequest(
        messages=(system("short"), user("also short"), assistant("brief"), user("hi"))
    )

    plan = plan_cache(
        request,
        CachePolicy(min_segment_tokens=1024),
        PLACEMENT_CAPABILITIES,
        _descriptor(cache_mechanism="explicit", cache_max_marks=4),
        ESTIMATOR,
    )

    assert not plan.active
    assert any("not worth a mark" in reason or "large enough" in reason for reason in plan.reasons)


def test_provider_floor_overrides_a_more_permissive_policy() -> None:
    request = _request()

    plan = plan_cache(
        request,
        CachePolicy(min_segment_tokens=0),
        PLACEMENT_CAPABILITIES,
        _descriptor(cache_mechanism="explicit", cache_max_marks=4, cache_min_tokens=10**6),
        ESTIMATOR,
    )

    assert not plan.active


def test_mark_budget_is_clamped_to_the_provider_ceiling() -> None:
    request = _request(
        tools=(ToolSpec(name="search", description=_long("tool"), parameters={}),)
    )

    plan = plan_cache(
        request,
        CachePolicy(max_marks=4),
        PLACEMENT_CAPABILITIES,
        _descriptor(cache_mechanism="explicit", cache_max_marks=1),
        ESTIMATOR,
    )

    assert len(plan.marks) == 1
    assert any("at most 1 marks" in reason for reason in plan.reasons)


def test_largest_segment_wins_a_scarce_budget() -> None:
    biggest = _long("system", tokens=8000)
    request = GenerationRequest(
        messages=(
            Message(role="system", content=(Text(biggest),)),
            user(_long("question", tokens=1200)),
            assistant(_long("answer", tokens=1200)),
            user("follow-up"),
        )
    )

    plan = plan_cache(
        request,
        CachePolicy(max_marks=1),
        PLACEMENT_CAPABILITIES,
        _descriptor(cache_mechanism="explicit", cache_max_marks=1),
        ESTIMATOR,
    )

    assert [mark.segment for mark in plan.marks] == [SYSTEM_SEGMENT]


def test_include_flags_are_respected() -> None:
    request = _request(
        tools=(ToolSpec(name="search", description=_long("tool"), parameters={}),)
    )

    plan = plan_cache(
        request,
        CachePolicy(include_tools=False, include_system=False),
        PLACEMENT_CAPABILITIES,
        _descriptor(cache_mechanism="explicit", cache_max_marks=4),
        ESTIMATOR,
    )

    segments = [mark.segment for mark in plan.marks]
    assert TOOLS_SEGMENT not in segments
    assert SYSTEM_SEGMENT not in segments


def test_a_single_turn_has_no_reusable_history_to_mark() -> None:
    request = GenerationRequest(messages=(user(_long("one long question")),))

    plan = plan_cache(
        request,
        CachePolicy(),
        PLACEMENT_CAPABILITIES,
        _descriptor(cache_mechanism="explicit", cache_max_marks=4),
        ESTIMATOR,
    )

    assert all(mark.segment < 0 for mark in plan.marks)


# ---- implicit ------------------------------------------------------------------------


def test_implicit_providers_get_a_plan_with_no_marks() -> None:
    plan = plan_cache(
        _request(),
        CachePolicy(),
        ModelCapabilities(features=Sourced(Feature.STREAMING, "catalog")),
        _descriptor(cache_mechanism="implicit"),
        ESTIMATOR,
    )

    assert plan.mechanism == "implicit"
    assert plan.marks == ()
    assert plan.estimated_cacheable_tokens > 0


def test_prefix_signature_changes_only_when_the_prefix_does() -> None:
    plan = plan_cache(
        _request(),
        CachePolicy(),
        PLACEMENT_CAPABILITIES,
        _descriptor(cache_mechanism="implicit"),
        ESTIMATOR,
    )

    same_prefix = _request(messages=(*_request().messages[:-1], user("a different tail")))
    changed_prefix = _request(
        messages=(system("a different system block"), *_request().messages[1:])
    )

    assert plan.prefix_signature(_request()) == plan.prefix_signature(same_prefix)
    assert plan.prefix_signature(_request()) != plan.prefix_signature(changed_prefix)
