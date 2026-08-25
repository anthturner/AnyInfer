# Cost and spending

AnyInfer computes what each call cost, keeps a per-client spend ledger, and can refuse a
request before it crosses a ceiling. One rule underlies all three: an unknown cost is
reported as unknown, never rendered as zero.

## Cost is tri-state

| State | Meaning | How it renders |
|---|---|---|
| A number | Computed from trusted pricing and provider-reported usage | `0.004125` |
| `None` | Unknown — no pricing, or pricing that is not trusted | `unknown`, never `$0.00` |
| `Decimal(0)` | Genuinely free, as local inference is | `0.000000` |

Rendering an unknown cost as `$0.00` turns a reporting gap into a silent accounting error.
Since AnyInfer will not do that, every total below carries a count of the calls it could
not price alongside the ones it could.

Cost is computed centrally, from pricing whose
[provenance](capabilities.md#the-five-provenances) is trusted (`catalog`, `discovered`,
`probed`, or `override`), so every provider reports it identically. A descriptor-level
fallback price is a placeholder and never produces money.

## Where prices come from

A bundled pricing table supplies the `catalog` layer for hosted models. Each entry records
when it was last verified and against what source; a weekly repository check watches for
drift, and `fetch_pricing()` pulls the maintained file for numbers newer than your
installed release. Prices are keyed by provider *and* model, because the same model served
by a different engine may cost differently. On top of the table:

- [OpenRouter](../providers/openrouter.md) reports real per-token pricing in its model
  listing, so its costs carry `discovered` provenance and beat the table.
- Local engines ([Ollama](../providers/ollama.md),
  [llama.cpp](../providers/llama-cpp.md)) get a genuine `Pricing(0, 0)`: free inference
  is a real zero, not an unknown.
- [Azure AI Foundry](../providers/azure-foundry.md) and the Copilots ship no table
  entries: Foundry pricing is region- and deployment-specific, and Copilot bills by
  subscription rather than per token. Their costs stay `None` unless you
  [override](capabilities.md#overriding-capabilities).

How the bundled table is checked for drift is a contributor concern; see
[the scheduled repository checks](../contributing/automation.md#scheduled-repository-checks).

## What one call cost

```python
result = client.generate(prompt, target="anthropic:claude-sonnet-4-5")

result.usage.cost_usd  # Decimal, or None
result.usage.input_tokens
result.usage.cache_read_tokens  # served from the provider's prompt cache
```

Check `cost_usd` for `None` before formatting it. The `cache_read_tokens` field is how
[prompt caching](caching.md) shows up in the bill.

## What this client has spent

```python
ledger = ai.SpendLedger()
client = ai.Client(providers, ledger=ledger)

...

totals = client.spend()
print(totals.cost, totals.requests, totals.unknown_requests)
```

Read `cost` together with `unknown_requests`: a total that omits the calls it could not
price understates spend while looking authoritative.

```python
if not totals.complete:
    print(f"{totals.unknown_requests} of {totals.requests} calls could not be priced")
```

Break spending down by target, or by your own labels:

```python
client.generate(prompt, target=..., metadata={"tenant": "acme", "feature": "summarize"})

ledger.by_target()  # {"anthropic:claude-sonnet-4-5": SpendTotals(...)}
ledger.by_label("tenant")  # {"acme": SpendTotals(...), "globex": SpendTotals(...)}
```

The library never interprets the labels. Tenant, feature, job id — that vocabulary is
yours, carried through untouched.

There is no process-wide ledger. Two clients that should share a total are given the same
`SpendLedger` object; a global would make totals depend on import order and would merge
the accounting of unrelated libraries sharing a process.

## Stopping before you spend too much

```python
client = ai.Client(
    providers,
    spend=ai.SpendPolicy(max_total_usd=Decimal("25"), max_request_usd=Decimal("0.50")),
)
```

A ceiling is checked before dispatch, beside the [context gate](budgeting.md), so a
refusal costs nothing. Crossing it raises
[`SpendLimitError`](../reference/errors.md), which carries the ceiling, what you had
already spent, and the estimate that tripped it, so you can see the arithmetic and not
just the verdict.

The estimate is the high end of the
[preflight cost range](budgeting.md#estimated-cost) — the pessimistic number, since a
guard built on the optimistic one would admit requests it was meant to stop.

### When the cost cannot be known

```python
ai.SpendPolicy(max_total_usd=Decimal("25"), on_unknown="refuse")
```

`allow` is the default: a target with no trusted pricing is sent, which preserves the
behavior that existed before ceilings did. `refuse` is for callers who would rather fail
than spend blind. There is no option that treats unknown as zero, because a guard that
does that enforces nothing while appearing to.

A refusal is not a [routing](routing.md) signal. It leaves the router entirely rather
than falling back to a cheaper target: a ceiling is client-wide, so a different target
does not satisfy it.

## Keeping a total across restarts

The library writes nothing on its own. For durability, own the file:

```python
store = ai.SpendStore("~/.myapp/spend.json")
store.accumulate(ledger)  # atomic; folds today's ledger into the stored total
store.load()["total"].cost
```

Reads are total: a missing, truncated, or foreign file yields nothing rather than
raising.

## Scope

This is accounting for one client in one process. It cannot see other processes or other
consumers of the same API key. Organization-wide quotas and fleet-level spend controls
belong to a deployment around AnyInfer, not inside it.

!!! tip "Key takeaways"
    - Cost is tri-state: a number from trusted pricing, a genuine `Decimal(0)` for local
      inference, or `None` for unknown. `None` is never rendered as `$0.00`.
    - Read `SpendTotals.cost` together with `unknown_requests`; a total is only honest
      with both.
    - A `SpendPolicy` ceiling refuses before dispatch, using the high end of the
      preflight estimate. Unknown-cost targets pass by default; set
      `on_unknown="refuse"` to fail instead.
    - Durable totals are opt-in via `SpendStore`; the library writes nothing on its own.

## See also

<div class="anyinfer-see-also" markdown>

- [Capabilities and provenance](capabilities.md): where pricing trust comes from.
- [Token estimation and context budgets](budgeting.md): the preflight estimate a ceiling
  checks against.
- [Arena runs](arena.md): comparing targets when you are willing to spend; the
  [portability diff](../guides/comparing-targets.md) compares without spending.

</div>
