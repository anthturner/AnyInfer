# Fit a corpus to a context budget

You have a pile of documents and a model with a finite window. This is the four-step
pattern: build documents, ask what fits, reduce, and place the result.

Reduction lives in `anyinfer.context`, an optional dependency-free subpackage. Your
application decides *what exists and what is safe to send*; the library decides *what
fits*. See [context reduction](../concepts/context-reduction.md) for why that line is
drawn there.

## 1. Build documents

```python
from anyinfer import context

documents = [
    context.ContextDocument.of("src/auth/credentials.py", credentials_source),
    context.ContextDocument.of("src/auth/tokens.py", tokens_source),
    context.ContextDocument.of("README.md", readme_text, pinned=True),
]
```

`of()` computes the digest, detects the language from the path, and derives a structural
extract — the signatures-and-imports view the `tiered` strategy falls back to. Pass
`extract=""` to skip extraction, or `language=` to override detection.

`pinned=True` means the user explicitly chose this file: it sorts ahead of everything and
is never chunked.

## 2. Ask what fits

Build the request you *would* send without the corpus, and ask what is left over:

```python
import anyinfer as ai

messages = [ai.user("How does credential resolution work?")]
budget = client.budget(messages, target="anthropic:claude-sonnet-4-5")

max_tokens = budget.remaining_tokens
if max_tokens is None:
    # The window is unknown; the library will not guess one for you.
    max_tokens = 8_000
```

That `if` is deliberate. When a target's context window is unknown, `remaining_tokens` is
`None` and the fallback is your explicit choice, made where you can see it.

## 3. Reduce

```python
reduction = context.select(
    documents,
    query="how does credential resolution work?",
    max_tokens=max_tokens,
)
```

The default `auto` strategy sends everything when it fits and falls back to `tiered` when
it does not. Name a strategy when you want a specific shape:

```python
context.select(documents, query, max_tokens=max_tokens, strategy="ranked")   # whole files
context.select(documents, query, max_tokens=max_tokens, strategy="tiered")   # full coverage
context.select(documents, query, max_tokens=max_tokens, strategy="packed")   # chunk-level
```

## 4. Place the result and check what happened

```python
messages.insert(0, ai.user(reduction.text))
result = client.generate(messages, target="anthropic:claude-sonnet-4-5")
```

The envelope goes in *your* message — the library never modifies the request. Then check
what it cost you:

```python
if not reduction.complete:
    log.info("context reduced: %s", reduction.summary())
    # ranked: 12 of 340 document(s); ~7900 of 8000 tokens; 328 omitted; limited by tokens
```

`summary()` is content-free: counts and ceilings, never paths or content. `metadata()`
gives the full machine-readable record for a debug pane.

## Observe reductions like any other event

```python
class ContextWatcher:
    def on_event(self, event):
        if isinstance(event, ai.ContextReduced):
            metrics.gauge("context.omitted", event.omitted_count)

reduction = context.select(documents, query, max_tokens=max_tokens,
                           observer=ContextWatcher())
```

## Reuse the ranking cache across turns

An interactive application ranks the same corpus on every turn. Build the statistics once:

```python
cache = context.build_rank_cache(documents)

for turn in conversation:
    reduction = context.select(documents, turn.text, max_tokens=budget_for(turn),
                               rank_cache=cache)
```

Invalidation is yours: key the cache on a corpus hash and rebuild when the corpus changes.
A stale cache produces undefined ranking, not an error.

## Keep the prompt prefix stable

Documents render in path order by default, whatever their rank. Two turns that select the
same documents produce byte-identical text, so provider prompt caches keep hitting. If you
would rather have strongest-first ordering:

```python
context.select(documents, query, max_tokens=max_tokens, render_order="rank")
```

That makes a *given* selection stable. To keep the selection itself stable across turns,
hand back the previous reduction's state:

```python
tuning = context.ContextTuning(carry_over_bonus=0.5)
first = context.select(documents, query, max_tokens=max_tokens, tuning=tuning)
...
second = context.select(
    documents, query, max_tokens=max_tokens, tuning=tuning, previous=first.state()
)
print(second.carried_over)
```

Unchanged documents get the bonus, so a corpus that barely moved produces the same
selection — and therefore the same prefix — rather than swapping one equally ranked file
for another.

## Choose a strategy from measurements

If you are unsure which strategy suits a corpus, cost all four. `plan()` runs each one,
measures the envelope it would render, and discards the text. It spends no inference:

```python
outcome = context.plan(documents, query, max_tokens=max_tokens)
for option in outcome.options:
    print(option.strategy, option.selected_count, option.estimated_tokens, option.complete)

best = outcome.best()
reduction = context.select(
    documents, query, max_tokens=max_tokens, strategy=best.strategy if best else "auto"
)
```

## Turn on the settings that suit your corpus

Every algorithmic choice is a field on `ContextTuning`, and the defaults reproduce the
plain behaviour exactly. For a source-code corpus, the shipped preset is a good starting
point:

```python
reduction = context.select(
    documents, query, max_tokens=max_tokens, tuning=context.ContextTuning.recommended()
)
```

That collapses duplicates, orders by relevance per token, penalizes near-identical
candidates, splits compound identifiers, expands the query, blends in import-graph
centrality, and shortens a file rather than dropping it. Each is [explained
here](../concepts/context-reduction.md#advanced-settings-in-one-place), and each can be set
in your [config file](../reference/configuration.md) instead.

## Compact the conversation, not just the corpus

Reduction is not only about material you collected. In an agentic loop the window fills
with tool results, and those compact well:

```python
compaction = context.compact_history(messages, max_tokens=max_tokens)
if not compaction.fits:
    ...  # the system prompt and recent turns alone exceed the budget; your call
result = client.generate(list(compaction.messages), target=target)
```

Tool-call pairing survives, system messages survive, and the recent window survives — the
three things naive truncation breaks.

Or hand the policy to the client and stop thinking about it. Every frontend built on that
client — including `anyinfer run` and the sidecar — then behaves the same way:

```python
client = ai.Client(providers, history=ai.HistoryPolicy())
```

By default that only acts once the route's larger-window targets are exhausted, so a bigger
model is always preferred to losing history. See
[the concept page](../concepts/context-reduction.md#or-let-the-client-do-it).

## When it will never fit

At some size no fidelity reduction is enough, and the answer is more requests rather than
fewer tokens. That is [`distill`](../examples/distill-a-corpus.md) — it reads everything
and writes something shorter, reporting exactly how many calls that took.

## See also

<div class="anyinfer-see-also" markdown>

- [Context reduction](../concepts/context-reduction.md) — the strategies and their tradeoffs.
- [Distill a corpus](../examples/distill-a-corpus.md) — the map/reduce cookbook.
- [Token estimation and context budgets](../concepts/budgeting.md) — where the budget comes from.

</div>
