# Compare targets without spending

`compare()` resolves a concrete request (the exact messages, schema, tools, sampling
controls, and cache policy) against every target you name and reports what it would
become on each: whether it fits, which structured-output mechanism would enforce the
schema, what would be dropped, and what it would cost. No provider is contacted, target
order is preserved, and nothing is ranked. If an application wants a cost-first or
local-first policy, make that selection visibly in application code and pass the
resulting order to [`Route`](../concepts/routing.md).

## A deterministic, offline example

This complete shape uses a scripted provider with two different capability profiles, so
it is deterministic, offline, and shows a degradation rather than two identical records:

```python
from anyinfer.testing import ScriptedModel, ScriptedProvider
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
import anyinfer as ai

provider = ScriptedProvider(
    "offline",
    [
        # Full-featured: a wide window and native JSON Schema support.
        ScriptedModel(
            "full",
            capabilities=ModelCapabilities(
                context_window=Sourced(32_768, "default"),
                features=Sourced(Feature.STREAMING | Feature.JSON_SCHEMA | Feature.SYSTEM_PROMPT, "default"),
            ),
        ),
        # Narrow: a small window and no schema mechanism beyond prompt injection.
        ScriptedModel(
            "narrow",
            capabilities=ModelCapabilities(
                context_window=Sourced(64, "default"),
                features=Sourced(Feature.STREAMING | Feature.SYSTEM_PROMPT, "default"),
            ),
        ),
    ],
)
registry = provider.register(ai.ProviderRegistry(load_builtins=False, load_entry_points=False))

with ai.Client([provider.settings()], registry=registry, use_default_catalog=False) as client:
    results = client.compare(
        "Return an object describing this sentence in detail, with several fields. " * 5,
        targets=[provider.target("full"), provider.target("narrow")],
        schema={"type": "object"},
    )

for item in results:
    print(item.requested, item.budget.fits if item.budget else None, item.structured_mechanism)
# offline:full   True  json_schema
# offline:narrow False prompt

assert [item.resolvable for item in results] == [True, True]
assert provider.requests == []
```

The identical prompt fits `full`'s 32,768-token window and does not fit `narrow`'s
64-token one; `item.budget.fits` reports each target independently, in the order the
targets were given. The schema degrades rather than failing: `full` would enforce it
natively (`json_schema`), while `narrow` has no schema mechanism, so its record reports
the prompt-injection fallback (`prompt`). And `provider.requests` is still empty
afterward, because `compare()` never constructs an adapter or sends a request, no matter
how many targets it evaluates.

Unknowns stay unknown: an unknown or untrusted context window produces a `None` fit and
an unpriced target produces `cost=None`, never a plausible number. A target that does
not exist or is not configured comes back as a `resolvable=False` record explaining why,
rather than an exception, so one bad candidate does not erase the comparison.
`refresh=True` may contact providers to refresh their model listings — the one exception
to the no-contact rule — but still generates no text. Since `compare()` cannot predict
undocumented provider refusals, use
[`verify()`](../concepts/capabilities.md#proving-a-target-works) when you need one
bounded real request as proof.

The command-line equivalent accepts repeatable targets:

```bash
anyinfer compare "Summarize this" --target medium --target ollama:qwen3:8b --json
```

The sidecar exposes the same records at `POST /v1/anyinfer/compare`, with an
OpenAI-shaped request plus a `targets` array.

## From one comparison to a diff

`compare()` answers "what does this request become on this target, right now." The
portability diff tool (`anyinfer.compare_diff`) answers two follow-on questions: did
that answer just change (regression detection), and what exactly changes in a move from
A to B (a portability report). It reuses `compare()`'s no-dispatch guarantee: no
provider is called, and no target is ranked or recommended.

For regression detection, define a fixture set — the requests you care about staying
stable — as a small JSON file:

```json
{
  "schema_version": 1,
  "fixtures": [
    {
      "id": "structured-summary",
      "request": {"messages": [{"role": "user", "text": "Summarize this document."}]},
      "targets": ["anthropic:claude-sonnet-4-5", "openai:gpt-5"]
    }
  ]
}
```

```python
from anyinfer import Client, compare_diff

client = Client(providers)
fixtures = compare_diff.load_fixtures("fixtures.json")
current = compare_diff.snapshot(fixtures, client=client)
client.close()
```

Check `current` against a baseline committed to your repository, and fail CI when they
differ:

```python
import json

baseline = json.load(open("baseline.snapshot.json"))
report = compare_diff.diff(baseline, current)
if not report.is_empty:
    print(compare_diff.render_text(report))
    raise SystemExit(1)
```

That catches the case where a code change (an adapter update, a dependency bump, a
provider preset change) silently alters what a fixed request becomes on a fixed target.

The portability report needs no baseline file; it is the "should I move from A to B"
answer for one request, live:

```python
report = compare_diff.diff_targets(
    fixtures[0], "anthropic:claude-sonnet-4-5", "openai:gpt-5", client=client
)
print(compare_diff.render_text(report))
```

The fixture format is public and versioned (`compare_diff.FIXTURE_SCHEMA_VERSION`).
Define fixtures against your own request shapes, since your regression risk is your own
requests; the [API reference](../reference/api/compare-diff.md) has every signature.

## When resolution is not the question

When the question is answer quality rather than request resolution, and you are willing
to spend real generations, run an [arena](../concepts/arena.md). A
[golden manifest](../examples/golden-manifest.md) answers "did this run's behavior
change", while `compare_diff` answers "did this request's resolution change".

!!! tip "Key takeaways"
    - `compare()` resolves a request against every named target without dispatching,
      ranking, or choosing; order is preserved and unknowns stay `None`.
    - Read the fit verdict from `item.budget.fits`; an unresolvable target is a
      `resolvable=False` record, never an exception.
    - `compare_diff.diff()` turns snapshots into a CI regression gate, and
      `diff_targets()` produces a live A-to-B portability report, both without a
      provider call.
    - Spending real generations to judge answers is an arena's job, not `compare()`'s.

## See also

<div class="anyinfer-see-also" markdown>

- [Arena runs](../concepts/arena.md): judging answers by spending.
- [Regression-test fallback and repair](../examples/golden-manifest.md): pinning a run's
  behavior with a golden manifest.
- [Capabilities and provenance](../concepts/capabilities.md): the data comparison reads.
- [compare_diff API](../reference/api/compare-diff.md): full signatures and the fixture
  schema.

</div>
