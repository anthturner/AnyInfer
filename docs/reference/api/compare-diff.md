# Portability Diff Tool

`anyinfer.evaluate.compare_diff`: snapshot [`compare()`](client.md) output for a fixture set, and
diff two snapshots structurally. No ranking, scoring, or live provider calls; every
function here either calls `compare()` (itself no-dispatch) or works on plain JSON. See the
[portability guide](../../guides/comparing-targets.md) for the full walkthrough and the
fixture schema.

```python
from anyinfer import compare_diff
```

<div class="anyinfer-api-block" markdown>

::: anyinfer.evaluate.compare_diff.load_fixtures

::: anyinfer.evaluate.compare_diff.snapshot

::: anyinfer.evaluate.compare_diff.diff

::: anyinfer.evaluate.compare_diff.diff_targets

::: anyinfer.evaluate.compare_diff.render_text

::: anyinfer.evaluate.compare_diff.Fixture

::: anyinfer.evaluate.compare_diff.DiffReport

::: anyinfer.evaluate.compare_diff.DiffEntry

::: anyinfer.evaluate.compare_diff.FIXTURE_SCHEMA_VERSION

</div>
