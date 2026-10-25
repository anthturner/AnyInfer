# Distill a Corpus

`distill` reads material that will never fit at any fidelity and writes something
shorter: each chunk is summarized against your question, then the notes are synthesized
into one answer. A successful one-pass corpus of N chunks makes N map calls plus one synthesis
call; hierarchical reduction, retry, and repair can add calls. It is a separate function rather
than a `select()` strategy, and this example needs a
live provider: as written, [Anthropic](../providers/anthropic.md) with
`ANTHROPIC_API_KEY` set. `distill` is part of the Python SDK's `anyinfer.context`; the native
C# SDK has no context reduction.

## The Basic Shape

```python
import asyncio

import anyinfer as ai
from anyinfer import context


async def main() -> None:
    changelog_text = "The release adds embeddings, reranking, and a sidecar."
    async with ai.AsyncClient(
        [ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]
    ) as client:
        result = await context.distill(
            changelog_text,
            "What changed for end users in this release?",
            client=client,
            target="anthropic:claude-sonnet-4-5",
        )

        print(result.text)
        print(f"{result.calls} calls, {result.usage.output_tokens} output tokens")


asyncio.run(main())
```

`result.calls` and `result.usage` report the fan-out and aggregate spend, so the
multiplier is never a surprise. Each later async fence is an independent complete program;
`source` may be raw text or `ContextDocument` values; documents split per document, because a
document boundary is a natural chunk boundary.

## Know the Cost Before You Commit

A distillation over 200 chunks is 201 requests. Size it first:

```python
import asyncio

import anyinfer as ai
from anyinfer import context


async def main() -> None:
    documents = [context.ContextDocument.of("release-notes.md", "Release notes go here.")]
    chunks = sum(len(context.split_document(document)) for document in documents)
    async with ai.AsyncClient(
        [ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]
    ) as client:
        estimate = client.budget(
            [ai.user("...one representative chunk...")],
            target="anthropic:claude-sonnet-4-5",
        ).estimated_cost

    print(f"{chunks} map calls plus at least one synthesis call")
    if estimate is not None:
        print(f"map-pass estimate: ${estimate.low * chunks:.2f}–${estimate.high * chunks:.2f}")


asyncio.run(main())
```

The representative chunk estimates only the map pass. Synthesis, hierarchical reductions, and
any retry or repair add calls; afterwards, `result.usage.cost_usd` is the actual total wherever
the provider reports cost, and is `None` when it cannot be known.

## Hierarchical Reduce, When There Are Many Notes

With enough chunks, the notes themselves exceed the window. `distill` handles that by
reducing in batches (sized by what fits, not by note count) and then reducing those
summaries:

```python
import asyncio

import anyinfer as ai
from anyinfer import context


async def main() -> None:
    huge_corpus = "one observation per line\n" * 10_000
    question = "Which changes matter to users?"
    target = "anthropic:claude-sonnet-4-5"
    async with ai.AsyncClient(
        [ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]
    ) as client:
        result = await context.distill(huge_corpus, question, client=client, target=target)
        print(result.reduce_depth)  # 1 for a single pass, higher when it recursed


asyncio.run(main())
```

A single-pass merge would overflow here.

## Variations

If your notes merge structurally (a union of entries, a concatenation, a JSON merge),
supply a `reducer` and the reduce call disappears; the map phase is still N calls, the
reduce is free and reproducible:

```python
import asyncio
import json

import anyinfer as ai
from anyinfer import context


def merge_findings(notes):
    findings = []
    for note in notes:
        try:
            findings.extend(json.loads(note)["findings"])
        except (ValueError, KeyError):
            continue
    return json.dumps({"findings": findings}, indent=2)


async def main() -> None:
    documents = [context.ContextDocument.of("settings.py", "API_URL = read_env()")]
    async with ai.AsyncClient(
        [ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]
    ) as client:
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

    assert result.calls == result.chunk_count  # map phase only


asyncio.run(main())
```

The built-in prompts are mechanical scaffolding ("here is part 3 of 9, take notes"), not
application prose. Replace them when the framing matters:

```python
import asyncio

import anyinfer as ai
from anyinfer import context


async def main() -> None:
    transcripts = "Customer: Search returns old results after I edit a record."
    async with ai.AsyncClient(
        [ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]
    ) as client:
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
    print(result.text)


asyncio.run(main())
```

Concurrency defaults to 4, and a fan-out is somebody's rate limit. Failures propagate as
normal provider errors, so retry and fallback stay on your
[`Route`](../concepts/routing.md), not duplicated inside the reducer:

```python
import asyncio

import anyinfer as ai
from anyinfer import context


async def main() -> None:
    documents = [context.ContextDocument.of("notes.md", "One observation per line.")]
    question = "Which changes matter to users?"
    async with ai.AsyncClient(
        [ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]
    ) as client:
        result = await context.distill(
            documents,
            question,
            client=client,
            target="anthropic:claude-sonnet-4-5",
            concurrency=2,
        )
    print(result.text)


asyncio.run(main())
```

From a synchronous application, use `distill_sync`; chunks process one at a time, since
concurrency is the async path's feature:

```python
import anyinfer as ai
from anyinfer import context

corpus = "The release adds embeddings, reranking, and a sidecar."
question = "What changed for end users?"
with ai.Client([ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]) as client:
    result = context.distill_sync(
        corpus,
        question,
        client=client,
        target="anthropic:claude-sonnet-4-5",
    )
```

## See Also

<div class="anyinfer-see-also" markdown>

- [Context reduction](../concepts/context-reduction.md): when to distill instead of select.
- [Fitting a corpus to a budget](../guides/fitting-context.md): the non-inference strategies.

</div>
