"""What a client spent, what it could not price, and what it refused to spend."""

from __future__ import annotations

import threading
from decimal import Decimal
from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer.capabilities.ledger import SpendLedger, SpendStore, SpendTotals
from anyinfer.errors import SpendLimitError
from anyinfer.registry import ProviderDescriptor, ProviderRegistry
from anyinfer.testing import ScriptedModel, ScriptedProvider
from anyinfer.types.capabilities import (
    Feature,
    ModelCapabilities,
    Pricing,
    Sourced,
)
from anyinfer.types.requests import ResolvedTarget
from anyinfer.types.results import Usage

TARGET = ResolvedTarget("acme", "m")
PRICED = ModelCapabilities(
    context_window=Sourced(100_000, "catalog"),
    features=Sourced(Feature.STREAMING | Feature.SYSTEM_PROMPT, "catalog"),
    pricing=Sourced(Pricing(Decimal("3"), Decimal("15")), "catalog"),
)
UNPRICED = ModelCapabilities(
    context_window=Sourced(100_000, "catalog"),
    features=Sourced(Feature.STREAMING | Feature.SYSTEM_PROMPT, "catalog"),
)


# ---- totals --------------------------------------------------------------------------


def test_known_and_unknown_costs_stay_distinguishable() -> None:
    """A total that silently omits unpriced calls reads as authoritative and is not."""
    ledger = SpendLedger()

    ledger.record(TARGET, Usage(input_tokens=100, output_tokens=50, cost_usd=Decimal("0.25")))
    ledger.record(TARGET, Usage(input_tokens=100, output_tokens=50))

    totals = ledger.totals()
    assert totals.cost == Decimal("0.25")
    assert totals.requests == 2
    assert totals.unknown_requests == 1
    assert not totals.complete


def test_a_genuine_zero_is_not_an_unknown() -> None:
    """Local inference is free; that is a price, not a missing one."""
    ledger = SpendLedger()

    ledger.record(TARGET, Usage(input_tokens=10, output_tokens=5, cost_usd=Decimal(0)))

    totals = ledger.totals()
    assert totals.cost == Decimal(0)
    assert totals.requests == 1
    assert totals.unknown_requests == 0
    assert totals.complete


def test_token_counts_accumulate() -> None:
    ledger = SpendLedger()

    ledger.record(TARGET, Usage(input_tokens=100, output_tokens=50, cache_read_tokens=80))
    ledger.record(TARGET, Usage(input_tokens=200, output_tokens=10, cache_read_tokens=20))

    totals = ledger.totals()
    assert totals.input_tokens == 300
    assert totals.output_tokens == 60
    assert totals.cache_read_tokens == 100


def test_totals_split_by_target() -> None:
    ledger = SpendLedger()
    other = ResolvedTarget("acme", "large")

    ledger.record(TARGET, Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("1")))
    ledger.record(other, Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("2")))

    by_target = ledger.by_target()
    assert by_target["acme:m"].cost == Decimal("1")
    assert by_target["acme:large"].cost == Decimal("2")


def test_concurrent_recording_totals_correctly() -> None:
    ledger = SpendLedger()

    def record_many() -> None:
        for _ in range(200):
            ledger.record(TARGET, Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("0.01")))

    threads = [threading.Thread(target=record_many) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    totals = ledger.totals()
    assert totals.requests == 800
    assert totals.cost == Decimal("8.00")


def test_reset_forgets_everything() -> None:
    ledger = SpendLedger()
    ledger.record(TARGET, Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("1")))

    ledger.reset()

    assert ledger.totals().requests == 0
    assert ledger.by_target() == {}


# ---- as an observer, through a real client -------------------------------------------


def _client(capabilities: ModelCapabilities, **kwargs: object) -> tuple[ai.Client, ScriptedProvider]:
    provider = ScriptedProvider("acme", [ScriptedModel("m", text="ok")])
    base = provider.descriptor()
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    registry.register(
        ProviderDescriptor(
            id=base.id,
            display_name=base.display_name,
            factory=base.factory,
            locality="hosted",
            default_base_url=base.default_base_url,
            setup=base.setup,
            default_capabilities=capabilities,
        ),
        replace=True,
    )
    client = ai.Client(
        [provider.settings()],
        registry=registry,
        use_default_catalog=False,
        **kwargs,  # type: ignore[arg-type]
    )
    return client, provider


def test_a_ledger_observes_a_real_client() -> None:
    ledger = SpendLedger()
    client, provider = _client(PRICED, ledger=ledger)
    with client:
        client.generate("hi", target=provider.target("m"))
        client.generate("hi again", target=provider.target("m"))

    totals = ledger.totals()
    assert totals.requests == 2
    assert totals.cost > 0
    assert totals.complete


def test_an_unpriced_target_counts_as_unknown() -> None:
    ledger = SpendLedger()
    client, provider = _client(UNPRICED, ledger=ledger)
    with client:
        client.generate("hi", target=provider.target("m"))

    totals = ledger.totals()
    assert totals.requests == 1
    assert totals.unknown_requests == 1
    assert totals.cost == Decimal(0)
    assert not totals.complete


def test_metadata_labels_attribute_spend() -> None:
    ledger = SpendLedger()
    client, provider = _client(PRICED, ledger=ledger)
    with client:
        client.generate("hi", target=provider.target("m"), metadata={"tenant": "acme"})
        client.generate("hi", target=provider.target("m"), metadata={"tenant": "globex"})
        client.generate("hi", target=provider.target("m"), metadata={"tenant": "acme"})

    by_tenant = ledger.by_label("tenant")
    assert by_tenant["acme"].requests == 2
    assert by_tenant["globex"].requests == 1


def test_client_spend_reports_zeros_without_a_ledger() -> None:
    """A caller reading spend() should never have to branch on whether it was enabled."""
    client, provider = _client(PRICED)
    with client:
        client.generate("hi", target=provider.target("m"))
        totals = client.spend()

    assert totals == SpendTotals()
    assert totals.requests == 0


def test_client_spend_reports_the_ledger_when_one_is_attached() -> None:
    client, provider = _client(PRICED, ledger=SpendLedger())
    with client:
        client.generate("hi", target=provider.target("m"))
        totals = client.spend()

    assert totals.requests == 1


# ---- the ceiling ---------------------------------------------------------------------


def test_a_per_request_ceiling_refuses_before_dispatch() -> None:
    """Nothing is sent: the provider must record zero calls."""
    client, provider = _client(
        PRICED, spend=ai.SpendPolicy(max_request_usd=Decimal("0.0000001"))
    )
    with client, pytest.raises(SpendLimitError) as caught:
        client.generate("hi", target=provider.target("m"))

    assert provider.call_count("m") == 0
    assert caught.value.limit_usd == Decimal("0.0000001")
    assert caught.value.estimated_usd is not None
    assert "ceiling" in str(caught.value)


def test_a_cumulative_ceiling_refuses_once_it_is_reached() -> None:
    ledger = SpendLedger()
    client, provider = _client(
        PRICED, ledger=ledger, spend=ai.SpendPolicy(max_total_usd=Decimal("1000"))
    )
    with client:
        client.generate("hi", target=provider.target("m"))
        # Pretend the client has already spent the budget.
        ledger.record(
            ResolvedTarget("acme", "m"),
            Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("1000")),
        )
        with pytest.raises(SpendLimitError) as caught:
            client.generate("again", target=provider.target("m"))

    assert caught.value.spent_usd is not None
    assert caught.value.spent_usd >= Decimal("1000")


def test_a_generous_ceiling_does_not_interfere() -> None:
    client, provider = _client(PRICED, spend=ai.SpendPolicy(max_total_usd=Decimal("1000000")))
    with client:
        result = client.generate("hi", target=provider.target("m"))

    assert result.text == "ok"


def test_unknown_cost_is_allowed_by_default() -> None:
    """The default preserves the behaviour that shipped before ceilings existed."""
    client, provider = _client(UNPRICED, spend=ai.SpendPolicy(max_total_usd=Decimal("1")))
    with client:
        result = client.generate("hi", target=provider.target("m"))

    assert result.text == "ok"


def test_unknown_cost_can_be_refused() -> None:
    client, provider = _client(
        UNPRICED,
        spend=ai.SpendPolicy(max_total_usd=Decimal("1"), on_unknown="refuse"),
    )
    with client, pytest.raises(SpendLimitError) as caught:
        client.generate("hi", target=provider.target("m"))

    assert provider.call_count("m") == 0
    assert "cannot be estimated" in str(caught.value)


def test_an_inert_policy_never_refuses() -> None:
    client, provider = _client(PRICED, spend=ai.SpendPolicy())
    with client:
        assert client.generate("hi", target=provider.target("m")).text == "ok"


def test_a_negative_ceiling_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        ai.SpendPolicy(max_total_usd=Decimal("-1"))
    with pytest.raises(ValueError):
        ai.SpendPolicy(on_unknown="pretend-zero")  # type: ignore[arg-type]


# ---- the store -----------------------------------------------------------------------


def test_store_round_trips(tmp_path: Path) -> None:
    ledger = SpendLedger()
    ledger.record(TARGET, Usage(input_tokens=10, output_tokens=5, cost_usd=Decimal("0.5")))

    store = SpendStore(tmp_path / "spend.json")
    store.accumulate(ledger)

    loaded = store.load()
    assert loaded["total"].cost == Decimal("0.5")
    assert loaded["total"].requests == 1


def test_store_accumulates_across_runs(tmp_path: Path) -> None:
    store = SpendStore(tmp_path / "spend.json")

    for _ in range(3):
        ledger = SpendLedger()
        ledger.record(TARGET, Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("2")))
        store.accumulate(ledger)

    assert store.load()["total"].cost == Decimal("6")
    assert store.load()["total"].requests == 3


def test_store_buckets_are_independent(tmp_path: Path) -> None:
    store = SpendStore(tmp_path / "spend.json")
    ledger = SpendLedger()
    ledger.record(TARGET, Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("1")))

    store.accumulate(ledger, bucket="nightly")
    store.accumulate(ledger, bucket="adhoc")

    loaded = store.load()
    assert set(loaded) == {"nightly", "adhoc"}


def test_an_unreadable_store_yields_nothing_rather_than_raising(tmp_path: Path) -> None:
    path = tmp_path / "spend.json"
    path.write_text("{ this is not json", encoding="utf-8")

    assert SpendStore(path).load() == {}


def test_a_foreign_format_version_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "spend.json"
    path.write_text('{"format_version": 99, "buckets": {}}', encoding="utf-8")

    assert SpendStore(path).load() == {}


def test_mixing_currencies_is_refused_rather_than_converted(tmp_path: Path) -> None:
    """A converted figure would have no provenance, and we have no rate source."""
    store = SpendStore(tmp_path / "spend.json")
    usd = SpendLedger(currency="USD")
    usd.record(TARGET, Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("1")))
    store.accumulate(usd)

    eur = SpendLedger(currency="EUR")
    eur.record(TARGET, Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("1")))

    with pytest.raises(ValueError):
        store.accumulate(eur)
