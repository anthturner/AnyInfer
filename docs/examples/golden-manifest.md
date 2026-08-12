# Regression-test fallback and repair

This test spends nothing and asserts the part of inference that should be deterministic:
which route ran and which mechanism enforced the schema. The pytest plugin stores the
normalized file in `manifests/fallback-and-repair.json` beside the test.

```python
import anyinfer as ai
from anyinfer.testing import ScriptedFailure, ScriptedModel


def test_fallback_contract(anyinfer_client, anyinfer_scripted, anyinfer_golden_manifest):
    provider = anyinfer_scripted(
        [
            ScriptedModel(
                "primary",
                failures=(ScriptedFailure(status=503, retry_after_s=0.0),),
            ),
            ScriptedModel("fallback", structured={"answer": "stable"}),
        ]
    )
    client = anyinfer_client(provider)
    result = client.generate(
        "answer",
        route=ai.Route(
            targets=(provider.target("primary"), provider.target("fallback")),
            retry=ai.Retry(max_attempts=1, backoff_base_s=0.0),
        ),
        schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    )

    anyinfer_golden_manifest(result.manifest, "fallback-and-repair")
```

Create or deliberately refresh goldens with `pytest --update-manifests`. Review the JSON
diff like a behavior change: a different target, extra attempt, weaker schema mechanism, or
new reduction should be intentional.
