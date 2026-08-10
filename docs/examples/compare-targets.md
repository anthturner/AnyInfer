# Compare target portability without spending

This complete shape uses a scripted provider so it is deterministic and offline:

```python
from anyinfer.testing import ScriptedModel, ScriptedProvider
import anyinfer as ai

provider = ScriptedProvider("offline", [ScriptedModel("small"), ScriptedModel("large")])
registry = provider.register(ai.ProviderRegistry(load_builtins=False, load_entry_points=False))

with ai.Client([provider.settings()], registry=registry, use_default_catalog=False) as client:
    results = client.compare(
        "Return an object",
        targets=[provider.target("small"), provider.target("large")],
        schema={"type": "object"},
    )

assert [item.resolvable for item in results] == [True, True]
assert provider.requests == []
```
