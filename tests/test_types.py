"""Domain-type behavior: immutability, equality, and derived values."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

import anyinfer as ai
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced, conjunction

PUBLIC_DATACLASSES = [
    ai.Text,
    ai.ToolCall,
    ai.ToolResult,
    ai.Message,
    ai.Sampling,
    ai.SchemaSpec,
    ai.ToolSpec,
    ai.Repair,
    ai.GenerationRequest,
    ai.ResolvedTarget,
    ai.Retry,
    ai.Route,
    ai.Usage,
    ai.Timing,
    ai.ErrorInfo,
    ai.AttemptRecord,
    ai.Generation,
    ai.TextDelta,
    ai.ReasoningDelta,
    ai.ToolCallDelta,
    ai.UsageUpdate,
    ai.TimingMark,
    ai.AttemptFailed,
    ai.StreamEnded,
    ai.Sourced,
    ai.ModelCapabilities,
    ai.Pricing,
    ai.LocalModelInfo,
    ai.Health,
    ai.DiscoveredModel,
]


@pytest.mark.parametrize("cls", PUBLIC_DATACLASSES, ids=lambda c: c.__name__)
def test_public_dataclasses_are_frozen_and_slotted(cls: type) -> None:
    """Public types are frozen with slots (AGENTS.md coding conventions)."""
    assert dataclasses.is_dataclass(cls)
    params = cls.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen, f"{cls.__name__} must be frozen"
    assert getattr(cls, "__slots__", None) is not None, f"{cls.__name__} must use slots"


def test_messages_are_immutable() -> None:
    message = ai.user("hello")
    with pytest.raises(dataclasses.FrozenInstanceError):
        message.role = "system"  # type: ignore[misc]


def test_message_equality_is_structural() -> None:
    assert ai.user("hi") == ai.user("hi")
    assert ai.user("hi") != ai.user("bye")
    assert ai.user("hi") != ai.system("hi")


def test_convenience_constructors_set_roles() -> None:
    assert ai.user("a").role == "user"
    assert ai.system("a").role == "system"
    assert ai.assistant("a").role == "assistant"


def test_message_text_concatenates_text_parts() -> None:
    message = ai.Message(
        role="assistant",
        content=(
            ai.Text("Hello, "),
            ai.ToolCall(id="c", name="t", arguments={}),
            ai.Text("world"),
        ),
    )
    assert message.text == "Hello, world"


def test_usage_normalization_computes_a_missing_total() -> None:
    usage = ai.Usage(input_tokens=10, output_tokens=5).normalized()
    assert usage.total_tokens == 15


def test_usage_normalization_leaves_unknowns_alone() -> None:
    assert ai.Usage(input_tokens=10).normalized().total_tokens is None


def test_usage_merge_prefers_later_known_values() -> None:
    merged = ai.Usage(input_tokens=1, output_tokens=2).merge(ai.Usage(output_tokens=9))
    assert merged.input_tokens == 1, "None must not overwrite a known value"
    assert merged.output_tokens == 9


def test_cost_stays_none_when_unknown() -> None:
    """An unknown cost must never masquerade as zero."""
    assert ai.Usage(input_tokens=100).cost_usd is None
    assert ai.Usage(cost_usd=Decimal("0")).cost_usd == Decimal("0")


def test_resolved_target_renders_canonically() -> None:
    assert str(ai.ResolvedTarget("ollama", "qwen3:8b")) == "ollama:qwen3:8b"


def test_request_timeout_default() -> None:
    assert ai.GenerationRequest(messages=()).effective_timeout_s == 120.0
    assert ai.GenerationRequest(messages=(), timeout_s=5.0).effective_timeout_s == 5.0


def test_with_messages_preserves_every_other_field() -> None:
    request = ai.GenerationRequest(
        messages=(ai.user("a"),),
        tools=(ai.ToolSpec("t", "d", {}),),
        sampling=ai.Sampling(temperature=0.3),
        reasoning="high",
        metadata={"run": "1"},
    )
    updated = request.with_messages((ai.user("b"),))

    assert updated.messages == (ai.user("b"),)
    assert updated.tools == request.tools
    assert updated.sampling == request.sampling
    assert updated.reasoning == "high"
    assert updated.metadata == {"run": "1"}


# ---- capabilities --------------------------------------------------------------------


def test_stronger_provenance_wins_an_overlay() -> None:
    catalog = ModelCapabilities(context_window=Sourced(8192, "catalog"))
    discovered = ModelCapabilities(context_window=Sourced(32768, "discovered"))
    assert catalog.overlay(discovered).context_window == Sourced(32768, "discovered")


def test_weaker_provenance_does_not_displace_stronger() -> None:
    probed = ModelCapabilities(context_window=Sourced(4096, "probed"))
    default = ModelCapabilities(context_window=Sourced(99999, "default"))
    assert probed.overlay(default).context_window == Sourced(4096, "probed")


def test_conjunction_takes_the_tightest_bound() -> None:
    result = conjunction(
        [
            ModelCapabilities(
                context_window=Sourced(128000, "catalog"),
                features=Sourced(Feature.TOOLS | Feature.JSON_SCHEMA, "catalog"),
            ),
            ModelCapabilities(
                context_window=Sourced(8192, "catalog"),
                features=Sourced(Feature.TOOLS, "catalog"),
            ),
        ]
    )
    assert result.context_window is not None
    assert result.context_window.value == 8192
    assert result.features.value == Feature.TOOLS


def test_conjunction_is_unknown_when_any_candidate_is_unknown() -> None:
    """Promising a minimum requires knowing every candidate's value."""
    result = conjunction(
        [
            ModelCapabilities(context_window=Sourced(128000, "catalog")),
            ModelCapabilities(context_window=None),
        ]
    )
    assert result.context_window is None


def test_conjunction_of_nothing_is_unknown() -> None:
    assert conjunction([]).context_window is None


# ---- sampling defaults (CS.6, CS.7) --------------------------------------------------------


def test_stronger_provenance_wins_a_sampling_default_overlay() -> None:
    base = ModelCapabilities(default_temperature=Sourced(1.0, "default"))
    stronger = ModelCapabilities(default_temperature=Sourced(0.4, "catalog"))

    assert base.overlay(stronger).default_temperature == Sourced(0.4, "catalog")
    assert stronger.overlay(base).default_temperature == Sourced(0.4, "catalog")


def test_a_sampling_default_survives_an_overlay_that_does_not_mention_it() -> None:
    base = ModelCapabilities(default_top_p=Sourced(1.0, "catalog"))
    assert base.overlay(ModelCapabilities()).default_top_p == Sourced(1.0, "catalog")


def test_conjunction_omits_sampling_defaults_rather_than_reducing_them() -> None:
    """No numeric reduction across candidates is a fact about what the provider will do."""
    result = conjunction(
        [
            ModelCapabilities(
                context_window=Sourced(8_000, "catalog"),
                default_temperature=Sourced(0.4, "catalog"),
                default_top_p=Sourced(1.0, "catalog"),
            ),
            ModelCapabilities(
                context_window=Sourced(16_000, "catalog"),
                default_temperature=Sourced(1.0, "catalog"),
                default_top_p=Sourced(0.9, "catalog"),
            ),
        ]
    )
    assert result.context_window == Sourced(8_000, "catalog")
    assert result.default_temperature is None
    assert result.default_top_p is None


def test_a_documented_default_is_carried_at_catalog_provenance() -> None:
    """CS.7: the one preset whose own reference states its defaults, and cites them."""
    import anyinfer as ai

    capabilities = ai.default_registry.get("ai21").default_capabilities
    assert capabilities.default_temperature == Sourced(0.4, "catalog")
    assert capabilities.default_top_p == Sourced(1.0, "catalog")


def test_no_provider_invents_a_sampling_default() -> None:
    """Only documentation populates these, so nothing may carry ``default`` provenance."""
    import anyinfer as ai

    for descriptor in ai.default_registry:
        for field_name in ("default_temperature", "default_top_p"):
            value = getattr(descriptor.default_capabilities, field_name)
            assert value is None or value.provenance in {"catalog", "override"}, (
                f"{descriptor.id}.{field_name} is {value!r}; a sampling default is only "
                "ever a documented fact"
            )
