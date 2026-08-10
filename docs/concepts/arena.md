# Arena runs

An arena sends the same request to a fixed set of targets, so a three-target arena costs
up to three ordinary generations before selection—and `judge` or `synthesize` adds one more.
It is an on-demand comparison tool, not a router that learns from winners. Every candidate
is returned so the selected answer never erases the evidence behind it.

The most defensible mode is structured consensus: candidates must satisfy the same schema,
their canonical JSON values are grouped without regard to object key order, and the largest
exact group wins.

```python
import anyinfer as ai

policy = ai.ArenaPolicy(
    targets=("openai:gpt-5-mini", "anthropic:claude-haiku-4-5", "ollama:qwen3:8b"),
    strategy="consensus",
    min_candidates=2,
)

result = client.generate(
    "Classify this ticket.",
    schema={
        "type": "object",
        "properties": {"label": {"type": "string"}},
        "required": ["label"],
        "additionalProperties": False,
    },
    arena=policy,
)

print(result.structured)
print(result.arena.agreement)
for candidate in result.arena.candidates:
    print(candidate.generation, candidate.error)
```

Without a schema, `consensus` announces a degradation to `first_valid`; free-form text has
no honest equality rule. `cheapest` never treats unknown cost as zero, and `fastest` uses
measured completion timing. `judge` asks one named target to choose a candidate through a
forced schema. `synthesize` asks it to produce an additional answer, while retaining all
original candidates and marking the synthesized result separately.

Candidate envelopes are anonymized by default. Set `reveal_targets=True` only when the
selector genuinely needs provider identity. Arena results are not stored, ranked across
runs, or fed back into future target selection.

## The same policy on every surface

Python, the CLI, and the OpenAI-compatible sidecar reach the same client-layer policy:

=== "Python"

    ```python
    result = client.generate("Classify this", schema=schema, arena=policy)
    ```

=== "CLI"

    ```console
    anyinfer run "Classify this" --schema schema.json \
      --arena openai:gpt-5-mini,anthropic:claude-haiku-4-5,ollama:qwen3:8b \
      --arena-strategy consensus --arena-min-candidates 2 --stats
    ```

=== "Sidecar"

    ```json
    {
      "model": "ignored-when-arena-is-present",
      "messages": [{"role": "user", "content": "Classify this"}],
      "anyinfer_arena": {
        "targets": ["openai:gpt-5-mini", "anthropic:claude-haiku-4-5", "ollama:qwen3:8b"],
        "strategy": "consensus",
        "min_candidates": 2
      }
    }
    ```

The response remains a valid single-choice OpenAI completion and adds
`anyinfer_arena` with content-free candidate evidence. Streaming buffers candidates and
emits only the selected answer, so branches never interleave on the wire.

## Tool loops and spend ceilings

`run_tools(..., arena=policy, max_rounds=R)` runs one isolated conversation per candidate.
Its provider-call ceiling is `N × R`, plus one optional judge or synthesis call. No
candidate sees another candidate's tool results. Run-scoped single-flight memoization may
share successful, byte-identical tool calls when policy and tool annotations permit it;
failed calls are never cached.

Arena spend is estimated and reserved for the whole run before any branch dispatches. A
ceiling refusal therefore produces zero provider calls. If a failed candidate's paid usage
cannot be recovered faithfully, the aggregate is marked incomplete rather than presenting
an understated total as authoritative.

Use `anyinfer run --dry-run --arena ...` to inspect the call ceiling and summed cost range
without sending a request.
