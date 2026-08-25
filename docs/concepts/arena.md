# Arena runs

An arena sends the same request to a fixed set of targets and selects one answer, keeping
every candidate as evidence. A three-target arena costs up to three ordinary generations
before selection, and the `judge` or `synthesize` strategies add one more. It is an
on-demand comparison tool, not a router that learns from winners — results are not
stored, ranked across runs, or fed back into future target selection. To compare targets
*without* spending anything, use the
[portability diff](../guides/comparing-targets.md) instead.

The strongest mode is structured consensus: candidates must satisfy the same
[schema](structured-output.md), their canonical JSON values are grouped without regard to
object key order, and the largest exact group wins.

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

The other strategies: without a schema, `consensus` announces a degradation to
`first_valid`, since free-form text has no exact equality rule. `cheapest` never treats
an [unknown cost](cost.md) as zero, and `fastest` uses measured completion timing.
`judge` asks one named target to choose a candidate through a forced schema;
`synthesize` asks it to produce an additional answer while retaining all original
candidates, marked separately.

Candidate envelopes are anonymized by default — set `reveal_targets=True` only when the
selector genuinely needs provider identity.

## The same policy on every surface

The [CLI](../guides/cli.md) (`anyinfer run --arena ... --arena-strategy consensus`) and
the [OpenAI-compatible sidecar](../serve/README.md) (an `anyinfer_arena` request
extension) reach the same client-layer policy as the Python call above. The sidecar's
response remains a valid single-choice OpenAI completion, with content-free candidate
evidence added under `anyinfer_arena`; streaming buffers candidates and emits only the
selected answer, so branches never interleave on the wire.

## Tool loops and spend ceilings

[`run_tools(..., arena=policy, max_rounds=R)`](../guides/tool-loop.md) runs one isolated
conversation per candidate, with a provider-call ceiling of one round-trip per candidate
per round plus the optional judge or synthesis call. No candidate sees another
candidate's tool results.

Arena spend is estimated and reserved for the whole run before any branch dispatches, so
a [spend-ceiling](cost.md) refusal produces zero provider calls. If a failed candidate's
paid usage cannot be recovered faithfully, the aggregate is marked incomplete rather
than presenting an understated total. Use `anyinfer run --dry-run --arena ...` to
inspect the call ceiling and summed cost range without sending anything.

!!! tip "Key takeaways"
    - An arena multiplies cost by its target count; use it to answer a question, not as
      standing routing. The free alternative for capability comparisons is
      `compare()`.
    - Structured consensus is the mode with a real equality rule; text-only requests
      degrade to `first_valid` and say so.
    - Every candidate is returned, so the selected answer never erases the evidence
      behind it.
    - Spend is reserved up front: a ceiling refusal costs zero provider calls.

## See also

<div class="anyinfer-see-also" markdown>

- [Compare targets without spending](../guides/comparing-targets.md): the zero-cost
  alternative for capability questions.
- [Structured output](structured-output.md): the schema contract consensus depends on.
- [Cost and spending](cost.md): ceilings and unknown-cost handling.

</div>
