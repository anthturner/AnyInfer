# Illustrative `compare_diff` fixtures

`fixtures.json` is a small, non-exhaustive example of the [portability diff
tool](https://anyinfer.dev/guides/comparing-targets/#turning-comparisons-into-a-regression-test-or-a-portability-report)'s
public fixture schema — copy it as a starting point for your own fixture set, built
against your own real request shapes and targets. `baseline.snapshot.json` is a checked-in
snapshot this repository's own test suite (`tests/test_compare_diff_regression.py`) diffs
against on every run, catching the case a code change silently alters what one of these
fixed requests becomes on a fixed target.

Regenerate the baseline after an intentional change to `compare()`'s output shape:

```bash
anyinfer compare --snapshot --fixtures fixtures/compare-diff/fixtures.json \
    --out fixtures/compare-diff/baseline.snapshot.json --config <any config with these providers>
```

or, from Python:

```python
from anyinfer import Client, ProviderSettings, compare_diff
import json

client = Client([
    ProviderSettings.of("openai", api_key="sk-illustrative-only-not-a-real-key"),
    ProviderSettings.of("anthropic", api_key="sk-illustrative-only-not-a-real-key"),
    ProviderSettings.of("ollama"),
])
fixtures = compare_diff.load_fixtures("fixtures/compare-diff/fixtures.json")
snap = compare_diff.snapshot(fixtures, client=client)
client.close()
json.dump(snap, open("fixtures/compare-diff/baseline.snapshot.json", "w"), indent=2, sort_keys=True)
```

The API keys above are deliberately fake strings, never used to authenticate anything —
`compare()` never dispatches a real request, so only credential *presence* matters, not
validity.
