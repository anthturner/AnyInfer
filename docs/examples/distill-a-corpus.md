# Distill a corpus

Some material will never fit at any fidelity. `distill` reads all of it and writes
something shorter: each chunk is summarized against your question, then the notes are
synthesized into one answer.

It is the only reduction strategy that **spends inference**, so it is a separate function
rather than a `select()` strategy, and it reports the call count and aggregate usage so
the multiplier is never a surprise.

## The basic shape

```python
import anyinfer as ai
from anyinfer import context

client = ai.AsyncClient([
    ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY"),
])

result = await context.distill(
    changelog_text,
    "What changed for end users in this release?",
    client=client,
    target="anthropic:claude-sonnet-4-5",
)

print(result.text)
print(f"{result.calls} calls, {result.usage.output_tokens} output tokens")
```

`source` may be raw text or `ContextDocument` values. Documents split per document,
because a document boundary is a natural chunk boundary.

## Know the cost before you commit

A distillation over 200 chunks is 201 requests. Size it first:

```python
documents = [context.ContextDocument.of(p, t) for p, t in collected]
chunks = sum(len(context.split_document(d)) for d in documents)

estimate = client.budget(
    [ai.user("...one representative chunk...")],
    target="anthropic:claude-sonnet-4-5",
).estimated_cost

print(f"about {chunks + 1} calls")
if estimate is not None:
    print(f"roughly ${estimate.low * chunks:.2f}–${estimate.high * chunks:.2f}")
```

Afterwards, `result.usage.cost_usd` is what it actually cost, wherever the provider
reports cost.

## Spend nothing on the reduce phase

If your notes merge structurally — a union of entries, a concatenation, a JSON merge —
supply a `reducer` and the reduce call disappears entirely:

```python
import json

def merge_findings(notes):
    findings = []
    for note in notes:
        try:
            findings.extend(json.loads(note)["findings"])
        except (ValueError, KeyError):
            continue
    return json.dumps({"findings": findings}, indent=2)

result = await context.distill(
    documents,
    "List every configuration key this code reads.",
    client=client,
    target="anthropic:claude-sonnet-4-5",
    map_instructions=(
        'Return JSON: {"findings": [{"key": "...", "file": "..."}]}. '
        "Use only what this part contains."
    ),
    reducer=merge_findings,
)

assert result.calls == result.chunk_count   # map phase only
```

The map phase is still N calls; the reduce is free and reproducible.

## Own the framing

The built-in prompts are mechanical scaffolding — "here is part 3 of 9, take notes" — not
application prose. Replace them when the framing matters:

```python
result = await context.distill(
    transcripts,
    "What did customers complain about?",
    client=client,
    target="anthropic:claude-sonnet-4-5",
    map_instructions=(
        "Read this support transcript excerpt. List each distinct complaint with the "
        "product area it concerns. Quote the customer's own words where possible."
    ),
    reduce_instructions=(
        "Group these complaints by product area, most frequent first. Preserve the "
        "customer quotes."
    ),
)
```

## Hierarchical reduce, when there are many notes

With enough chunks, the notes themselves exceed the window. `distill` handles that by
reducing in batches — sized by what actually fits, not by note count — and then reducing
those summaries:

```python
result = await context.distill(huge_corpus, question, client=client, target=target)
print(result.reduce_depth)   # 1 for a single pass, higher when it recursed
```

A naive single-pass merge would simply overflow here.

## Bound the fan-out

Concurrency defaults to 4. A fan-out is somebody's rate limit:

```python
result = await context.distill(
    documents, question, client=client, target=target, concurrency=2,
)
```

Failures propagate as normal provider errors, so retry and fallback stay where they
belong — on your [`Route`](../concepts/routing.md), not duplicated inside the reducer.

## From a synchronous application

```python
with ai.Client([ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]) as client:
    result = context.distill_sync(
        corpus, question, client=client, target="anthropic:claude-sonnet-4-5",
    )
```

Chunks process one at a time — concurrency is the async path's feature. Use
`distill()` with an `AsyncClient` if you want the parallel map phase.

## Generating module digests (the caching recipe)

The `tiered` strategy renders app-supplied module digests but never generates them —
spending inference to summarize is your decision, not a side effect of packing. Here is
the pattern, with caching:

```python
surfaces = context.module_surfaces(documents, depth=2)

digests = {}
for module, surface in surfaces.items():
    key = hashlib.sha256(surface.encode()).hexdigest()
    if (cached := digest_cache.get(key)) is not None:
        digests[module] = cached
        continue
    summary = await client.generate(
        f"Describe what this module does in two sentences:\n\n{surface}",
        target="anthropic:claude-haiku-4-5",
    )
    digests[module] = summary.text
    digest_cache[key] = summary.text

reduction = context.select(
    documents, query, max_tokens=max_tokens, strategy="tiered",
    module_digests=digests,
)
```

`module_surfaces()` is deterministic, so the digest cache key is stable across runs. The
cache itself stays app-side.

## See also

<div class="anyinfer-see-also" markdown>

- [Context reduction](../concepts/context-reduction.md) — when to distill instead of select.
- [Fitting a corpus to a budget](../guides/fitting-context.md) — the non-inference strategies.

</div>
