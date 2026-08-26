"""The normalized reasoning ladder, and how each descriptor spells its rungs.

`none` is the newest rung and the one that is not merely "less": it asks for reasoning to
be *disabled*, which is a different request from `minimal` ("as little as you can") and
from leaving the field unset ("whatever this model does by default"). Providers spell that
in genuinely different ways — a disabled thinking block, a zero budget, a literal `none`,
an `enabled: false` flag — and several publish enums with no off value at all. This module
pins each choice, because the failure mode for all of them is silent: a request that says
"do not think" and produces a thinking model's answer anyway looks exactly like success.
"""

from __future__ import annotations

import pytest

from anyinfer.registry import default_registry
from anyinfer.types.requests import ReasoningEffort

EFFORTS: tuple[ReasoningEffort, ...] = ("none", "minimal", "low", "medium", "high")


def test_every_registered_descriptor_translates_every_level() -> None:
    """A level the type permits must not be a `KeyError` in somebody's lookup table.

    Most translators index a per-provider mapping; adding a rung to the literal without
    adding it to those tables would raise on dispatch rather than at type-check time.
    """
    for provider_id in default_registry.known_ids():
        translator = default_registry.get(provider_id).reasoning_translator
        for effort in EFFORTS:
            result = translator(effort)
            assert isinstance(result, dict | type(translator(None)))


def test_none_is_never_translated_into_a_positive_effort_level() -> None:
    """Clamping "off" onto "low" would ask for the opposite of what was requested."""
    for provider_id in default_registry.known_ids():
        wire = default_registry.get(provider_id).reasoning_translator("none")
        flat = repr(wire)
        assert "'minimal'" not in flat, provider_id
        assert "'low'" not in flat or "min" in flat, provider_id


@pytest.mark.parametrize(
    ("provider_id", "expected"),
    [
        # Providers whose reasoning is a budget or a switch: disabling is expressible.
        ("anthropic", {"thinking": {"type": "disabled"}}),
        ("cohere", {"thinking": {"type": "disabled"}}),
        ("deepseek", {"thinking": {"type": "disabled"}}),
        ("ollama", {"think": False}),
        # Providers tracking OpenAI's vocabulary, which now includes the value itself.
        ("openai", {"reasoning": {"effort": "none"}}),
        ("azure-foundry", {"reasoning_effort": "none"}),
        ("nebius", {"reasoning_effort": "none"}),
        ("xai", {"reasoning_effort": "none"}),
        # Providers with a named off value that is not the word "none".
        ("lm-studio", {"reasoning": "off"}),
        # Gateways normalizing across upstream ladders: the disable flag, not a level.
        ("openrouter", {"reasoning": {"enabled": False}}),
        # Gemini's thinkingLevel enum has no off value; the budget field does.
        ("gemini", {"thinkingConfig": {"thinkingBudget": 0}}),
        ("vertex", {"thinkingConfig": {"thinkingBudget": 0}}),
    ],
)
def test_none_reaches_each_providers_own_off_switch(
    provider_id: str, expected: dict[str, object]
) -> None:
    translator = default_registry.get(provider_id).reasoning_translator
    assert dict(translator("none")) == expected


def test_minimal_and_none_stay_distinct_where_the_provider_can_tell_them_apart() -> None:
    """Collapsing them would lose the difference between "think less" and "do not think"."""
    for provider_id in ("openai", "azure-foundry", "nebius", "lm-studio", "gemini"):
        translator = default_registry.get(provider_id).reasoning_translator
        assert dict(translator("none")) != dict(translator("minimal")), provider_id


def test_unset_is_still_distinct_from_none_everywhere() -> None:
    """`None` sends nothing at all; `"none"` sends an explicit instruction."""
    for provider_id in ("anthropic", "openai", "gemini", "ollama", "openrouter"):
        translator = default_registry.get(provider_id).reasoning_translator
        assert dict(translator(None)) == {}
        assert dict(translator("none")) != {}
