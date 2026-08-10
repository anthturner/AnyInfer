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
