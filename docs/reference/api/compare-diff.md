# Portability Diff Tool

`anyinfer.compare_diff`: snapshot [`compare()`](client.md) output for a fixture set, and
diff two snapshots structurally. No ranking, scoring, or live provider calls; every
function here either calls `compare()` (itself no-dispatch) or works on plain JSON. See the
[portability guide](../../guides/comparing-targets.md) for the full walkthrough and the
fixture schema.

```python
from anyinfer import compare_diff
```

<div class="anyinfer-api-block" markdown>

::: anyinfer.compare_diff.load_fixtures

::: anyinfer.compare_diff.snapshot

::: anyinfer.compare_diff.diff

::: anyinfer.compare_diff.diff_targets

::: anyinfer.compare_diff.render_text

::: anyinfer.compare_diff.Fixture

::: anyinfer.compare_diff.DiffReport

::: anyinfer.compare_diff.DiffEntry

::: anyinfer.compare_diff.FIXTURE_SCHEMA_VERSION

</div>
