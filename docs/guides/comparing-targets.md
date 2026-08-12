# Will my request survive a target change?

Use `compare()` before spending a generation. It resolves the exact messages, schema,
tools, sampling controls, and cache policy against every target and reports what will fit
or degrade.

```python
comparisons = await client.compare(
    messages,
    targets=["anthropic:claude-sonnet-4-5", "ollama:qwen3:8b"],
    schema=answer_schema,
)
for item in comparisons:
    print(item.requested, item.fits, item.structured_mechanism)
```

No provider call is made by default. Unknown windows produce `fits=None`, unknown prices
produce `cost=None`, and every consumed capability retains its provenance. An unknown or
unconfigured target is a `resolvable=False` record rather than an exception, so one bad
candidate does not erase the comparison.

`refresh=True` is the explicit exception: it may contact providers to refresh their model
listings. It still generates no text.

AnyInfer preserves target order and does not rank or choose. If an application wants a
cost-first or local-first policy, make that selection visibly in application code and pass
the resulting order to `Route`. `compare()` cannot predict undocumented provider refusals;
use `verify()` when you need one bounded real request as proof.

The command-line equivalent accepts repeatable targets:

```bash
anyinfer compare "Summarize this" --target medium --target ollama:qwen3:8b --json
```

The sidecar exposes the same records at `POST /v1/anyinfer/compare`, with an OpenAI-shaped
request plus a `targets` array.

## Turning comparisons into a regression test, or a portability report

`compare()` answers "what does this request become on this target, right now." The
portability diff tool (`anyinfer.compare_diff`) answers two follow-on questions: "did that
answer just change?" (regression detection) and "here's exactly what changes if I move from
A to B" (a portability report). Both reuse `compare()`'s own no-dispatch guarantee — this
tool never calls a provider either, and never ranks or recommends a target.

**Regression detection.** Define a fixture set — the requests you actually care about
staying stable — as a small JSON file:

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

Check `current` against a baseline you've committed to your repo, and fail CI when they
differ:

```python
import json

baseline = json.load(open("baseline.snapshot.json"))
report = compare_diff.diff(baseline, current)
if not report.is_empty:
    print(compare_diff.render_text(report))
    raise SystemExit(1)
```

That catches the case a code change (an adapter update, a dependency bump, a provider
preset change) silently alters what a fixed request becomes on a fixed target — something
that was previously only checkable by re-reading `compare()` output by eye.

**The portability report** needs no baseline file at all — it's the "should I move from A
to B" answer for one request, live:

```python
report = compare_diff.diff_targets(
    fixtures[0], "anthropic:claude-sonnet-4-5", "openai:gpt-5", client=client
)
print(compare_diff.render_text(report))
```

The fixture format is public and versioned (`compare_diff.FIXTURE_SCHEMA_VERSION`) — define
your own against your own real request shapes; your regression risk is your own requests,
not a set of illustrative examples. See the [API
reference](../reference/api/compare-diff.md) for every function's full signature.

This is deliberately a different tool from
[`contracts/DRIFT-CHECK.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md):
that procedure audits whether AnyInfer's claims about a provider's wire protocol still
match that provider's current public docs. This tool audits whether AnyInfer's own
decisions for a fixed request are stable — no network calls to a provider's documentation
are ever made here.
