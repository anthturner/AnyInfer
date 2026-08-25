# Regression-Test Fallback and Repair

This test asserts the part of inference that should be deterministic (which route ran and
which mechanism enforced the schema), and it runs offline: a scripted provider and stored
fixtures, no network, no spend. The pytest plugin stores the normalized
[run manifest](../concepts/run-manifests.md) in `manifests/fallback-and-repair.json`
beside the test.

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

Create or refresh goldens with `pytest --update-manifests`, and review the JSON diff like
a behavior change: a different target, extra attempt, weaker schema mechanism, or new
reduction should be intentional.

## What to Notice

- The golden file is a normalized run manifest, so the assertion covers route, attempts,
  and schema mechanism rather than model prose.
- The scripted 503 on `primary` puts a real fallback hop in the manifest; the
  `anyinfer_scripted` and `anyinfer_golden_manifest` fixtures come from the pytest plugin
  described in [testing your application offline](../guides/testing-your-app.md).
- A golden manifest asserts "did this run's behavior change"; `compare_diff` asserts "did
  this request's resolution change"; see
  [the portability diff](../guides/comparing-targets.md).

## See Also

<div class="anyinfer-see-also" markdown>

- [Run manifests](../concepts/run-manifests.md): what the golden file records.
- [Test your application offline](../guides/testing-your-app.md): the pytest plugin and
  fixtures.
- [Will my request survive a target change?](../guides/comparing-targets.md): the
  request-level diff beside this run-level golden.

</div>
