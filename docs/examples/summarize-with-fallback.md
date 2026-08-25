# Structured Summaries with a Fallback Chain

A command-line tool that turns arbitrary text into a schema-validated summary, staying up
when a provider is not: it tries Anthropic first, falls back to OpenAI, and finally to a
local Ollama model. As written it needs `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and a
running Ollama; the shape itself is exercised in CI against in-process fakes.

```python
"""summarize.py — `python summarize.py < release-notes.txt`"""

import json
import sys

import anyinfer as ai

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "topics"],
}

client = ai.Client(
    [
        ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY"),
        ai.ProviderSettings.of("openai", api_key="env://OPENAI_API_KEY"),
        ai.ProviderSettings.of("ollama"),
    ]
)

result = client.generate(
    "Summarize this text:\n" + sys.stdin.read(),
    route=ai.Route(
        targets=(
            "anthropic:claude-sonnet-4-5",
            "openai:gpt-5.2",
            "ollama:qwen3:8b",
        ),
        retry=ai.Retry(max_attempts=2),
    ),
    schema=SUMMARY_SCHEMA,
    repair=ai.Repair(max_attempts=1),
)

print(json.dumps(result.structured, indent=2))
print(f"via {result.target} using {result.structured_mechanism}", file=sys.stderr)
for attempt in result.attempts:
    print(f"  {attempt.target}: {attempt.outcome}", file=sys.stderr)
```

## What to Notice

- `result.structured` is always valid against `SUMMARY_SCHEMA`: validation happens
  client-side regardless of which provider answered, and `result.structured_mechanism`
  tells you how it was enforced (`grammar`, `json_schema`, `json_mode`, or
  `prompt`). See [structured output](../concepts/structured-output.md).
- The fallback chain is data, not code. `Route.targets` is an ordered tuple; retry
  policy applies per target. No `try/except` pyramid, and the
  [attempt trail](../concepts/routing.md) (`result.attempts`) records every hop for your
  logs.
- Credentials never appear in source. `env://ANTHROPIC_API_KEY` is a
  [credential reference](../concepts/credentials.md); the resolved secret is registered
  for redaction, so it cannot leak through errors or telemetry.
- The local fallback needs no key at all. If both hosted providers are down, the same
  call lands on Ollama, and if everything fails, you get one `AllTargetsFailedError`
  carrying the per-target causes, not the last exception to happen to escape.

## See Also

<div class="anyinfer-see-also" markdown>

- [Add a fallback chain](../guides/fallback.md): retry policy and route design.
- [Enforce a JSON schema](../guides/structured-output.md): mechanisms and repair.

</div>
