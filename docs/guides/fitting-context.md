# Fit a Corpus to a Context Budget

You have a pile of documents and a model with a finite window. This is the four-step
pattern: build documents, ask what fits, reduce, and place the result.

Reduction lives in `anyinfer.context`, an optional dependency-free subpackage. Your
application decides *what exists and what is safe to send*; the library decides *what
fits*. See [context reduction](../concepts/context-reduction.md) for why that line is
drawn there.

## 1. Build Documents

```python
from anyinfer import context

documents = [
    context.ContextDocument.of("src/auth/credentials.py", credentials_source),
    context.ContextDocument.of("src/auth/tokens.py", tokens_source),
    context.ContextDocument.of("README.md", readme_text, pinned=True),
]
```

`of()` computes the digest, detects the language from the path, and derives a structural
extract (the signatures-and-imports view the `tiered` strategy falls back to). Pass
`extract=""` to skip extraction, or `language=` to override detection.

`pinned=True` means the user explicitly chose this file: it sorts ahead of everything and
is never chunked.

## 2. Ask What Fits

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

When a target's context window is unknown, `remaining_tokens` is `None`; the fallback is
your explicit choice, made where you can see it. See
[token estimation and context budgets](../concepts/budgeting.md) for where the number
comes from.

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
context.select(documents, query, max_tokens=max_tokens, strategy="ranked")  # whole files
context.select(documents, query, max_tokens=max_tokens, strategy="tiered")  # full coverage
context.select(documents, query, max_tokens=max_tokens, strategy="packed")  # chunk-level
```

The [five strategies](../concepts/context-reduction.md#the-five-strategies) and their
tradeoffs are documented on the concept page.

## 4. Place the Result and Check What Happened

```python
messages.insert(0, ai.user(reduction.text))
result = client.generate(messages, target="anthropic:claude-sonnet-4-5")
```

The envelope goes in *your* message; the library never modifies the request. Then check
what it cost you:

```python
if not reduction.complete:
    log.info("context reduced: %s", reduction.summary())
    # ranked: 12 of 340 document(s); ~7900 of 8000 tokens; 328 omitted; limited by tokens
```

`summary()` is content-free: counts and ceilings, never paths or content. `metadata()`
gives the full machine-readable record for a debug pane.

## Observe Reductions like Any Other Event

```python
class ContextWatcher:
    def on_event(self, event):
        if isinstance(event, ai.ContextReduced):
            metrics.gauge("context.omitted", event.omitted_count)


reduction = context.select(documents, query, max_tokens=max_tokens, observer=ContextWatcher())
```

The `ContextReduced` event carries counts and ceilings only, like every
[telemetry event](../concepts/telemetry.md).

## Generating Module Digests

The `tiered` strategy renders module digests you supply, but never generates them:
summarizing spends inference, and that is your decision rather than a side effect of
packing. Generate them once and cache them:

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
    documents,
    query,
    max_tokens=max_tokens,
    strategy="tiered",
    module_digests=digests,
)
```

`module_surfaces()` is deterministic, so the digest cache key is stable across runs. The
cache itself stays app-side.

## Going Further

Each refinement is one section of the [concept page](../concepts/context-reduction.md):

- `plan()` prices every deterministic strategy for free before you commit; see
  [plan before you commit](../concepts/context-reduction.md#plan-before-you-commit).
- Duplicates collapse losslessly, and a file that just misses the budget can be shortened
  instead of dropped; see
  [losing less than you drop](../concepts/context-reduction.md#losing-less-than-you-drop).
- Carrying over the previous turn's selection keeps the prompt prefix stable, so provider
  caches keep hitting; see
  [turn two: send the same thing](../concepts/context-reduction.md#turn-two-send-the-same-thing).
- Every algorithmic choice is a `ContextTuning` field, and `recommended()` is the set
  worth having for source code; see
  [tuning](../concepts/context-reduction.md#tuning).
- `compact_history()` and `HistoryPolicy` apply the same discipline to the conversation
  itself; see
  [conversations are context too](../concepts/context-reduction.md#conversations-are-context-too).
- When no fidelity reduction is enough, the answer is more requests rather than fewer
  tokens; see [distill a corpus](../examples/distill-a-corpus.md).

!!! tip "Key Takeaways"
    - Ask `client.budget()` what is left over before reducing; an unknown window comes
      back as `None`, and the fallback number is yours to choose in the open.
    - The default `auto` strategy sends everything when it fits and degrades to `tiered`
      only when it must, so small corpora pay nothing.
    - The envelope lands in your own message; the library never edits
      `GenerationRequest.messages`.
    - `reduction.complete` and `summary()` report exactly what the budget cost, in
      content-free form that is safe to log.
    - Module digests for `tiered` are generated by your code, keyed on the deterministic
      `module_surfaces()` output, so a cache survives across runs.

## See Also

<div class="anyinfer-see-also" markdown>

- [Context reduction](../concepts/context-reduction.md): the strategies and their tradeoffs.
- [Distill a corpus](../examples/distill-a-corpus.md): the map/reduce cookbook.
- [Token estimation and context budgets](../concepts/budgeting.md): where the budget comes from.

</div>
