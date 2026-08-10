# Cost and spending

Cost in AnyInfer is **tri-state**, and the three states are kept apart everywhere:

| State | Meaning | How it renders |
|---|---|---|
| A number | Computed from pricing we trust and usage the provider reported | `0.004125` |
| `None` | We do not know — no pricing, or pricing we do not trust | `unknown`, never `$0.00` |
| `Decimal(0)` | Genuinely free, as local inference is | `0.000000` |

An unknown cost rendered as `$0.00` is the most common accounting bug in comparable
gateways, and nothing here will do it. That discipline is why the totals below always carry
a count of what they *could not* price alongside what they could.

## What one call cost

```python
result = client.generate(prompt, target="anthropic:claude-sonnet-4-5")

result.usage.cost_usd          # Decimal, or None
result.usage.input_tokens
result.usage.cache_read_tokens # served from the provider's prompt cache
```

Cost is computed centrally from the pricing the capability layer assembled, so every
provider reports it identically — and only from pricing whose provenance is trusted. A
descriptor-level fallback price is a placeholder, not a price, and never produces money.

## What this client has spent

```python
ledger = ai.SpendLedger()
client = ai.Client(providers, ledger=ledger)

...

totals = client.spend()
print(totals.cost, totals.requests, totals.unknown_requests)
```

`unknown_requests` is not optional detail. A total that silently omits the calls it could
not price understates spend while looking authoritative, so read the two together:

```python
if not totals.complete:
    print(f"{totals.unknown_requests} of {totals.requests} calls could not be priced")
```

Break it down by target, or by your own labels:

```python
client.generate(prompt, target=..., metadata={"tenant": "acme", "feature": "summarize"})

ledger.by_target()          # {"anthropic:claude-sonnet-4-5": SpendTotals(...)}
ledger.by_label("tenant")   # {"acme": SpendTotals(...), "globex": SpendTotals(...)}
```

The library never interprets those labels — tenant, feature, job id are your vocabulary,
carried through untouched.

## How bundled prices are checked

The repository's weekly drift check is a detector, not a price updater. It compares exact
provider-and-model keys against three public machine-readable sources: the provider-owned
Chutes and Avian catalogs are direct evidence, while OpenRouter is a secondary tripwire for
the ten explicitly mapped OpenAI and Anthropic entries. Every other priced provider has an
explicit manual, authenticated, unrepresentable, or deferred posture.

A clean run means those sources were reachable and the covered values matched. It does not
make an old price newly verified. A contributor still opens the provider's own current
pricing documentation, checks currency, units, tier, region, and token side, and submits a
human-reviewed change. Source outages make the check incomplete instead of producing a
false green result.

From a source checkout:

```console
python scripts/check_pricing_drift.py
python scripts/check_pricing_drift.py --format json
python scripts/check_pricing_drift.py --report pricing-drift-report.json
python scripts/check_pricing_drift.py --live-source chutes-models
```

Exit status `0` means a complete run with no drift, `1` means a complete run found a changed
or missing exact mapping, and `2` means validation or a required source failed. Ordinary
tests use minimized fixtures under `tests/fixtures/pricing/`; refreshing a fixture records a
source capture, not a new `last_verified` date for bundled rates.

!!! note "One ledger per client, by composition"

    There is no process-wide ledger. Two clients that should share a total are given the
    same `SpendLedger` object. A global would make your totals depend on import order, and
    would silently merge the accounting of two libraries that happen to share a process.

## Stopping before you spend too much

```python
client = ai.Client(
    providers,
    spend=ai.SpendPolicy(max_total_usd=Decimal("25"), max_request_usd=Decimal("0.50")),
)
```

A ceiling is checked **before dispatch**, beside the context gate, so a refusal costs
nothing — no request is sent. Crossing it raises `SpendLimitError`, carrying the ceiling,
what you had already spent, and the estimate that tripped it, so the arithmetic is visible
rather than just the verdict.

The estimate is the high end of the preflight cost range. That is deliberately the
pessimistic number: a guard built on the optimistic one would let requests through that it
was meant to stop.

### When the cost cannot be known

```python
ai.SpendPolicy(max_total_usd=Decimal("25"), on_unknown="refuse")
```

`allow` is the default and preserves the behaviour that shipped before ceilings existed: a
target with no trusted pricing is sent. `refuse` is for callers who would rather fail than
spend blind. There is deliberately no third option that treats unknown as zero — a guard
that does that enforces nothing while appearing to.

A refusal is not a routing signal. It leaves the router entirely rather than falling back
to a cheaper target: a ceiling is client-wide, so a different target does not satisfy it,
and picking a model *because* it is cheaper is adaptive routing, which this library defers.

## Keeping a total across restarts

The library writes nothing on its own. If you want durability, own the file:

```python
store = ai.SpendStore("~/.myapp/spend.json")
store.accumulate(ledger)              # atomic; folds today's ledger into the stored total
store.load()["total"].cost
```

Reads are total: a missing, truncated, or foreign file yields nothing rather than raising,
because a cache that can break your program is worse than no cache.

## What this is not

This is accounting for one client in one process. It shares no state with other processes,
authorizes nothing, and cannot see other consumers of the same API key. Organization-wide
quotas, virtual keys, and spend controls across a fleet belong to a deployment around
AnyInfer — they are deliberately not in the library.
