# Compare target portability without spending

`compare()` resolves a fixed request against every target and reports what it would
become — fit, dispatch order preserved, no provider ever contacted. This complete shape
uses a scripted provider with two deliberately different capability profiles, so it is
deterministic, offline, and actually shows a degradation rather than two identical
records:

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

## What to notice

- **Fit is per target, not per request.** The identical prompt fits `full`'s 32,768-token
  window and does not fit `narrow`'s 64-token one — `item.budget.fits` reports each
  independently, in the order the targets were given.
- **Mechanism degrades honestly instead of failing.** `full` enforces the schema natively
  (`json_schema`); `narrow` has no schema mechanism at all, so `compare()` reports it would
  fall back to prompt injection (`prompt`) rather than pretending both targets would behave
  the same way.
- **Nothing was dispatched.** `provider.requests == []` after the call — `compare()` never
  constructs an adapter or sends a request, no matter how many targets it evaluates.
- **`resolvable` stays `True` for both**, because these targets exist and are configured;
  an unknown or unconfigured target would instead be a `resolvable=False` record explaining
  why, never an exception. See [comparing targets](../guides/comparing-targets.md) for that
  case and the CLI/sidecar equivalents.
