"""The pricing table, estimated cost, and override provenance."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest

import anyinfer as ai
from anyinfer.capabilities.assemble import capabilities_for
from anyinfer.capabilities.budget import build_context_budget
from anyinfer.capabilities.pricing import compute_cost, estimate_cost
from anyinfer.capabilities.pricing_table import PricingTable, fetch_pricing, load_default_pricing
from anyinfer.errors import ConfigError
from anyinfer.registry import ProviderDescriptor, ProviderRegistry, default_registry
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.capabilities import ModelCapabilities, Pricing, Sourced
from anyinfer.types.messages import user
from anyinfer.types.requests import GenerationRequest
from anyinfer.types.results import Usage

REPO_ROOT = Path(__file__).resolve().parent.parent


def _request(text: str = "hi") -> GenerationRequest:
    return GenerationRequest(messages=(user(text),))


def _table(provider: str, model: str, inp: str, out: str) -> PricingTable:
    return PricingTable.from_mapping(
        {
            "format_version": 1,
            "providers": {
                provider: [
                    {
                        "model": model,
                        "input_per_1m": inp,
                        "output_per_1m": out,
                        "last_verified": "2026-08-07",
                        "source": "https://example.invalid/prices",
                    }
                ]
            },
        }
    )


# ---- the bundled table ---------------------------------------------------------------


def test_bundled_table_is_valid_per_the_ci_gate() -> None:
    """The same validator the pricing-refresh workflow runs must pass in CI."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_pricing.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_bundled_table_covers_the_catalog_hosted_models() -> None:
    table = load_default_pricing()
    for provider, model in (
        ("openai", "gpt-5"),
        ("openai", "gpt-5-mini"),
        ("anthropic", "claude-haiku-4-5"),
        ("anthropic", "claude-sonnet-4-5"),
        ("anthropic", "claude-opus-4-1"),
    ):
        assert table.lookup(provider, model) is not None, f"{provider}:{model} unpriced"


# ---- lookup semantics ----------------------------------------------------------------


def test_lookup_is_keyed_by_provider_and_model() -> None:
    """The same model on a different engine never inherits a price."""
    table = load_default_pricing()
    assert table.lookup("openai", "gpt-5") is not None
    assert table.lookup("azure-foundry", "gpt-5") is None


def test_lookup_prefix_matching_is_boundary_aware() -> None:
    table = load_default_pricing()
    dated = table.lookup("openai", "gpt-5-2026-01-01")
    assert dated is not None and dated.value.input_per_1m == Decimal("1.25")
    # "gpt-5-mini" has its own entry; the shorter "gpt-5" prefix must not capture it.
    mini = table.lookup("openai", "gpt-5-mini")
    assert mini is not None and mini.value.input_per_1m == Decimal("0.25")
    assert table.lookup("openai", "gpt-99") is None
    assert table.lookup("openai", "gpt-50") is None, "prefix must stop at a boundary"


def test_lookup_provenance_is_catalog() -> None:
    priced = load_default_pricing().lookup("openai", "gpt-5")
    assert priced is not None and priced.provenance == "catalog"


# ---- table validation ----------------------------------------------------------------


def test_from_mapping_rejects_bad_documents() -> None:
    with pytest.raises(ConfigError):
        PricingTable.from_mapping({"format_version": 2, "providers": {}})
    with pytest.raises(ConfigError):
        PricingTable.from_mapping(
            {
                "format_version": 1,
                "providers": {
                    "openai": [
                        {
                            "model": "m",
                            "input_per_1m": 1.25,  # float, not string
                            "output_per_1m": "10",
                            "last_verified": "2026-08-07",
                            "source": "https://x.invalid",
                        }
                    ]
                },
            }
        )
    with pytest.raises(ConfigError):
        _table("openai", "m", "-1", "10")


# ---- estimated cost ------------------------------------------------------------------


def test_estimate_cost_math_and_tri_state() -> None:
    request = _request("x" * 3000)  # estimate: 1004 tokens (incl. overhead), floor 375
    budget = build_context_budget(
        request,
        ModelCapabilities(pricing=Sourced(Pricing(Decimal("2"), Decimal("10")))),
        output_reserve_tokens=1000,
    )
    # Sourced defaults to "default" provenance — untrusted, so no money is computed.
    assert budget.estimated_cost is None

    trusted = build_context_budget(
        request,
        ModelCapabilities(pricing=Sourced(Pricing(Decimal("2"), Decimal("10")), "catalog")),
        output_reserve_tokens=1000,
    )
    cost = trusted.estimated_cost
    assert cost is not None
    assert cost.low == (Decimal(trusted.estimate.floor) / 1_000_000) * 2
    expected_high = (Decimal(trusted.estimate.tokens) / 1_000_000) * 2 + (
        Decimal(1000) / 1_000_000
    ) * 10
    assert cost.high == expected_high
    assert cost.low < cost.high

    assert build_context_budget(_request(), None).estimated_cost is None


def test_estimate_cost_trusts_override_provenance() -> None:
    priced = Sourced(Pricing(Decimal("1"), Decimal("1")), "override")
    assert estimate_cost(build_context_budget(_request(), None).estimate, 0, priced) is not None


# ---- assembly layers -----------------------------------------------------------------


def test_assembly_prices_hosted_models_from_the_table() -> None:
    caps = capabilities_for(
        default_registry.get("openai"), "gpt-5", pricing=load_default_pricing()
    )
    assert caps.pricing is not None
    assert caps.pricing.provenance == "catalog"
    assert caps.pricing.value.input_per_1m == Decimal("1.25")


def test_assembly_gives_local_engines_a_genuine_zero() -> None:
    caps = capabilities_for(
        default_registry.get("ollama"), "qwen3:8b", pricing=load_default_pricing()
    )
    assert caps.pricing is not None
    assert caps.pricing.value.input_per_1m == 0
    cost = compute_cost(Usage(input_tokens=100, output_tokens=50), caps)
    assert cost == Decimal(0), "free local inference is a real zero, not None"


def test_override_beats_discovered() -> None:
    discovered = {
        "m": ModelCapabilities(pricing=Sourced(Pricing(Decimal("5"), Decimal("5")), "discovered"))
    }
    override = {"m": ModelCapabilities(pricing=Sourced(Pricing(Decimal("9"), Decimal("9"))))}
    caps = capabilities_for(
        default_registry.get("openai"), "m", discovered=discovered, overrides=override
    )
    assert caps.pricing is not None
    assert caps.pricing.provenance == "override"
    assert caps.pricing.value.input_per_1m == Decimal("9")


# ---- client integration --------------------------------------------------------------


async def test_client_budget_carries_catalog_pricing_and_cost() -> None:
    async with ai.AsyncClient([]) as client:
        budget = client.budget("x" * 3000, target="openai:gpt-5")
    assert budget.pricing is not None and budget.pricing.provenance == "catalog"
    cost = budget.estimated_cost
    assert cost is not None and cost.currency == "USD"
    assert Decimal(0) < cost.low < cost.high


async def test_client_capability_overrides_win_end_to_end() -> None:
    overrides = {
        "openai:gpt-5": ModelCapabilities(
            pricing=Sourced(Pricing(Decimal("100"), Decimal("100")))
        )
    }
    async with ai.AsyncClient([], capability_overrides=overrides) as client:
        budget = client.budget("hello", target="openai:gpt-5")
    assert budget.pricing is not None and budget.pricing.provenance == "override"
    cost = budget.estimated_cost
    assert cost is not None and cost.high > Decimal("0.4"), "reserve priced at 100/1M"


async def test_client_rejects_malformed_override_keys() -> None:
    with pytest.raises(ConfigError):
        ai.AsyncClient([], capability_overrides={"no-colon": ModelCapabilities()})


async def test_generate_computes_cost_from_the_table() -> None:
    """Provider-reported usage priced by the catalog layer, end to end."""
    registry = ProviderRegistry(load_builtins=False, load_entry_points=False)
    from anyinfer.providers.openai_compat import OpenAICompatAdapter

    registry.register(
        ProviderDescriptor(
            id="openai",  # the table keys by provider id; this fake stands in for it
            display_name="Fake OpenAI",
            factory=OpenAICompatAdapter,
            requires_base_url=True,
        )
    )
    server = FakeOpenAIServer(FakeResponse(text="ok"))
    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        registry=registry,
        use_default_catalog=False,
    ) as client:
        result = await client.generate("hi", target="openai:gpt-5")

    assert result.usage.input_tokens is not None and result.usage.output_tokens is not None
    expected = (Decimal(result.usage.input_tokens) / 1_000_000) * Decimal("1.25") + (
        Decimal(result.usage.output_tokens) / 1_000_000
    ) * 10
    assert result.usage.cost_usd == expected


# ---- fetching a maintained table -----------------------------------------------------


def test_fetch_pricing_parses_a_served_table() -> None:
    document = (
        REPO_ROOT / "src" / "anyinfer" / "capabilities" / "pricing.json"
    ).read_text("utf-8")
    transport = httpx2.MockTransport(
        lambda request: httpx2.Response(200, text=document)
    )
    table = fetch_pricing("https://fake.invalid/pricing.json", transport=transport)
    assert table.lookup("openai", "gpt-5") is not None


def test_fetch_pricing_rejects_a_malformed_document() -> None:
    transport = httpx2.MockTransport(
        lambda request: httpx2.Response(200, json={"format_version": 99})
    )
    with pytest.raises(ConfigError):
        fetch_pricing("https://fake.invalid/pricing.json", transport=transport)
