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


def test_per_search_unit_parses_when_present_and_stays_none_when_absent() -> None:
    table = PricingTable.from_mapping(
        {
            "format_version": 1,
            "providers": {
                "cohere": [
                    {
                        "model": "rerank-v3.5",
                        "input_per_1m": "0",
                        "output_per_1m": "0",
                        "per_search_unit": "2.00",
                        "last_verified": "2026-08-07",
                        "source": "https://example.invalid/prices",
                    }
                ],
                "openai": [
                    {
                        "model": "text-embedding-3-small",
                        "input_per_1m": "0.02",
                        "output_per_1m": "0",
                        "last_verified": "2026-08-07",
                        "source": "https://example.invalid/prices",
                    }
                ],
            },
        }
    )
    reranked = table.lookup("cohere", "rerank-v3.5")
    assert reranked is not None
    assert reranked.value.per_search_unit == Decimal("2.00")

    embedded = table.lookup("openai", "text-embedding-3-small")
    assert embedded is not None
    assert embedded.value.per_search_unit is None


def test_per_search_unit_rejects_a_negative_rate() -> None:
    with pytest.raises(ConfigError):
        PricingTable.from_mapping(
            {
                "format_version": 1,
                "providers": {
                    "cohere": [
                        {
                            "model": "rerank-v3.5",
                            "input_per_1m": "0",
                            "output_per_1m": "0",
                            "per_search_unit": "-1",
                            "last_verified": "2026-08-07",
                            "source": "https://example.invalid/prices",
                        }
                    ]
                },
            }
        )


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
        "openai:gpt-5": ModelCapabilities(pricing=Sourced(Pricing(Decimal("100"), Decimal("100"))))
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
    document = (REPO_ROOT / "src" / "anyinfer" / "capabilities" / "pricing.json").read_text(
        "utf-8"
    )
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, text=document))
    table = fetch_pricing("https://fake.invalid/pricing.json", transport=transport)
    assert table.lookup("openai", "gpt-5") is not None


def test_fetch_pricing_rejects_a_malformed_document() -> None:
    transport = httpx2.MockTransport(
        lambda request: httpx2.Response(200, json={"format_version": 99})
    )
    with pytest.raises(ConfigError):
        fetch_pricing("https://fake.invalid/pricing.json", transport=transport)


# ---- per-invocation rates inherit the token-rate discipline ----------------------------------
#
# The block was added so provider-run tools could be priced. It would be worth little if a
# rate could arrive with a date nobody earned and a source nobody can open — that discipline
# is the reason the table is trustworthy at all.


def _with_server_tools(rate: dict[str, object]) -> list[str]:
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import validate_pricing

    data = json.loads(validate_pricing.PRICING_PATH.read_text(encoding="utf-8"))
    data["server_tools"] = {"anthropic": {"web_search": rate}}
    probe = Path(__file__).resolve().parent.parent / "build" / "pricing_probe.json"
    probe.parent.mkdir(exist_ok=True)
    probe.write_text(json.dumps(data), encoding="utf-8")
    try:
        return validate_pricing.validate(probe)
    finally:
        probe.unlink(missing_ok=True)


_GOOD = {"per_use": "0.01", "last_verified": "2026-08-20", "source": "https://example.test/p"}


def test_a_well_formed_rate_passes() -> None:
    assert _with_server_tools(dict(_GOOD)) == []


def test_a_date_nobody_earned_is_refused() -> None:
    problems = _with_server_tools({**_GOOD, "last_verified": "2099-01-01"})
    assert any("is in the future" in problem for problem in problems)


def test_a_source_nobody_can_open_is_refused() -> None:
    problems = _with_server_tools({**_GOOD, "source": "somebody-told-me"})
    assert any("must be an https URL" in problem for problem in problems)


def test_a_zero_rate_is_refused_because_free_is_spelled_by_billed_as() -> None:
    """A zero asserts a number nobody verified.

    The three honest answers are a rate, `billed_as: tokens` for a tool folded into the
    token bill, and absence for a tool nobody has priced — which reports the cost as
    unknown. A bare zero is none of them.
    """
    problems = _with_server_tools({**_GOOD, "per_use": "0"})
    assert any("must be positive" in problem for problem in problems)


def test_a_rate_that_varies_by_model_can_be_expressed() -> None:
    """Two of the four bound providers charge by model class rather than a flat fee."""
    assert (
        _with_server_tools(
            {
                "last_verified": "2026-08-20",
                "source": "https://example.test/p",
                "per_use_by_model": {"gpt-5": "0.01"},
            }
        )
        == []
    )


def test_a_tool_folded_into_the_token_bill_says_so_rather_than_going_missing() -> None:
    """Gemini bills code execution as tokens; absent would wrongly mean unpriced."""
    assert (
        _with_server_tools(
            {
                "last_verified": "2026-08-20",
                "source": "https://example.test/p",
                "billed_as": "tokens",
            }
        )
        == []
    )


def test_two_rate_shapes_at_once_are_refused() -> None:
    """Two answers to one question, and whichever is read first becomes the bill."""
    problems = _with_server_tools({**_GOOD, "billed_as": "tokens"})
    assert any("exactly one of" in problem for problem in problems)


# ---- the rates actually shipped --------------------------------------------------------------


def test_every_shipped_rate_cites_a_provider_owned_page() -> None:
    """A secondary aggregator may trigger review; only the provider authorizes a rate."""
    import json

    import validate_pricing

    block = json.loads(validate_pricing.PRICING_PATH.read_text(encoding="utf-8"))[
        "server_tools"
    ]
    hosts = {
        "anthropic": "platform.claude.com",
        "openai": "developers.openai.com",
        "gemini": "ai.google.dev",
        "xai": "docs.x.ai",
    }
    for provider, expected_host in hosts.items():
        for kind, entry in block[provider].items():
            if kind.startswith("_"):
                continue
            assert expected_host in entry["source"], f"{provider}:{kind}"


def test_a_search_is_priced_for_every_provider_that_can_run_one() -> None:
    from anyinfer.capabilities.pricing_table import load_default_pricing

    table = load_default_pricing()
    for provider, model in (
        ("anthropic", "claude-sonnet-4-5"),
        ("openai", "gpt-5"),
        ("gemini", "gemini-2.5-flash"),
    ):
        sourced = table.lookup(provider, model)
        assert sourced is not None, f"{provider}:{model} has no entry"
        assert "web_search" in sourced.value.per_server_tool_use, f"{provider}:{model}"


def test_a_model_outside_the_priced_class_stays_unpriced_rather_than_guessed() -> None:
    """OpenAI charges non-reasoning models 2.5x for the same search.

    Only the families the pricing page names are listed, so an unlisted model reports the
    generation's cost as unknown instead of being sorted into a class by guesswork.
    """
    from anyinfer.capabilities.pricing_table import load_default_pricing

    sourced = load_default_pricing().lookup("openai", "gpt-4.1")
    assert sourced is not None
    assert "web_search" not in sourced.value.per_server_tool_use


def test_a_tool_billed_by_container_time_is_absent_rather_than_wrong() -> None:
    """Anthropic and OpenAI bill code execution per container-hour and per session.

    AnyInfer counts invocations, not container-hours, so no correct per-invocation number
    exists — and cost reporting as unknown is the honest outcome.
    """
    from anyinfer.capabilities.pricing_table import load_default_pricing

    table = load_default_pricing()
    for provider, model in (("anthropic", "claude-sonnet-4-5"), ("openai", "gpt-5")):
        priced = table.lookup(provider, model).value.per_server_tool_use
        assert "code_execution" not in priced, f"{provider} cannot price container time"


def test_the_block_is_optional() -> None:
    """The shipped table carries no rates yet, and that is a valid table."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import validate_pricing

    assert validate_pricing.validate() == []
