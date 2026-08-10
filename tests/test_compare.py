"""No-dispatch target comparison and portability reporting."""

from __future__ import annotations

from decimal import Decimal

import pytest

import anyinfer as ai
from anyinfer.providers.openai_compat import OpenAICompatAdapter
from anyinfer.registry import ProviderDescriptor, ProviderRegistry
from anyinfer.testing import ScriptedModel, ScriptedProvider


def _registry() -> ProviderRegistry:
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id="json-only",
            display_name="JSON only",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
            static_capabilities={
                "m": ai.ModelCapabilities(
                    context_window=ai.Sourced(8_192, "catalog"),
                    features=ai.Sourced(ai.Feature.JSON_MODE, "catalog"),
                    pricing=ai.Sourced(ai.Pricing(Decimal("1"), Decimal("2")), "catalog"),
                )
            },
        )
    )
    return registry


@pytest.mark.asyncio
async def test_compare_reports_ladder_fit_cost_and_does_not_dispatch() -> None:
    registry = _registry()
    provider = ScriptedProvider("scripted", [ScriptedModel("unused")])
    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "json-only", base_url="https://unused.invalid/v1", transport=provider.transport()
            )
        ],
        registry=registry,
        use_default_catalog=False,
    ) as client:
        compared = await client.compare(
            "a short request",
            targets=["json-only:m"],
            schema={"type": "object"},
            sampling=ai.Sampling(max_output_tokens=8),
        )

    item = compared[0]
    assert item.resolvable is True
    assert item.structured_mechanism == "json_mode"
    rejected = {r.mechanism: r.reason for r in item.mechanism_rungs if not r.available}
    assert "json_schema" in rejected and "json_schema" in rejected["json_schema"]
    assert item.fits is True
    assert item.cost is not None
    assert provider.requests == []
    assert ai.TargetComparison.from_dict(item.to_dict()) == item


@pytest.mark.asyncio
async def test_unresolvable_targets_are_data_and_order_is_preserved() -> None:
    registry = _registry()
    async with ai.AsyncClient(
        [ai.ProviderSettings.of("json-only", base_url="https://unused.invalid/v1")],
        registry=registry,
        use_default_catalog=False,
    ) as client:
        compared = await client.compare(
            "hi",
            targets=["missing:m", "json-only:m", "also-missing:m", "json-only:other"],
        )

    assert [item.requested for item in compared] == [
        "missing:m", "json-only:m", "also-missing:m", "json-only:other"
    ]
    assert [item.resolvable for item in compared] == [False, True, False, True]


@pytest.mark.asyncio
async def test_default_window_never_becomes_a_fit_verdict() -> None:
    provider = ScriptedProvider("scripted", [ScriptedModel("m")])
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    provider.register(registry)
    async with ai.AsyncClient(
        [provider.settings()], registry=registry, use_default_catalog=False
    ) as client:
        item = (await client.compare("hi", targets=[provider.target("m")]))[0]
    assert item.budget is not None
    assert item.budget.context_window is not None
    assert item.budget.context_window.provenance == "default"
    assert item.fits is None


@pytest.mark.asyncio
async def test_comparison_and_dispatch_gate_share_the_same_budget() -> None:
    registry = _registry()
    async with ai.AsyncClient(
        [ai.ProviderSettings.of("json-only", base_url="https://unused.invalid/v1")],
        registry=registry,
        use_default_catalog=False,
    ) as client:
        item = (await client.compare("x" * 100_000, targets=["json-only:m"]))[0]
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.generate("x" * 100_000, target="json-only:m")

    assert item.fits is False
    assert "context" in str(excinfo.value).lower()
