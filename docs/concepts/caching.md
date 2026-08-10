# Prompt caching

Most providers can hold on to a prefix of your prompt and charge less the next time they
see it. What "hold on to it" means differs: some want to be told exactly where the reusable
part ends, others work it out themselves and want you not to disturb it.

AnyInfer treats that difference the way it treats structured output. You state an intent —
*cache what is worth caching*, and the core picks the strongest mechanism the target
actually offers, reporting it when a weaker one is all that is available.

!!! warning "This is not a response cache"

    Prompt caching caches the prompt **you send**, on the **provider's** side, for the
    **provider's** retention window. It never skips a call, never reuses an answer, and
    never makes a repeated question free. AnyInfer stores nothing.

## It is off unless you ask

```python
result = client.generate(prompt, target="anthropic:claude-sonnet-4-5")  # no caching
result = client.generate(prompt, target="...", cache=ai.CachePolicy())  # caching
```

Caching changes what a provider bills you and how long it keeps a copy of your prompt.
Neither is a decision the library makes on your behalf, so a request that carries no policy
behaves exactly as it did before this feature existed.

Set it once for a client if every request should use it:

```python
client = ai.Client(providers, cache=ai.CachePolicy())
```

or in shared configuration, where the CLI and the sidecar pick it up too:

```json
{
  "format_version": 1,
  "providers": [{"id": "anthropic"}],
  "cache": {"mode": "auto", "max_marks": 4}
}
```

## The two mechanisms

**Explicit** — the provider accepts per-segment marks. AnyInfer decides which segments are
worth marking, largest first, bounded by the provider's own ceiling; the adapter spells each
mark in that provider's wire format. Anthropic works this way.

**Implicit** — the provider caches a stable prefix on its own. There is nothing to send, so
AnyInfer's job is to leave your prefix undisturbed and to tell you when your own request is
defeating it. OpenAI and DeepSeek work this way.

When a target offers neither, the policy is reported as dropped rather than silently
ignored — you asked for caching and did not get it, and a cost expectation that is now wrong
should not be discovered from a bill.

## What gets marked

Three kinds of segment, in the order they sit on the wire:

| Segment | Why it is a good candidate |
|---|---|
| Tool declarations | Identical on every turn of a conversation, and often large |
| The system block | Stable by construction |
| The conversation prefix | Everything before the current turn; grows as the chat does |

Segments smaller than the provider's floor are skipped. Below that floor a mark is billed as
a cache *write* that no later read ever pays back, so a small mark costs money rather than
saving it.

You can narrow what is eligible:

```python
ai.CachePolicy(include_tools=True, include_system=False, min_segment_tokens=2048, max_marks=2)
```

## Seeing what happened

The result reports which mechanism was engaged:

```python
result.cache_mechanism  # "explicit", "implicit", or None
result.usage.cache_read_tokens  # what the provider says it served from cache
result.usage.cache_write_tokens  # what it says it stored
```

Those two are different kinds of fact and are kept apart on purpose. `cache_mechanism` is
what was *asked for*; the usage figures are what the provider *reported*. Cost is computed
only from the reported numbers — an intention is never billed as an outcome, and when a
provider does not report cache accounting, the figures stay `None` rather than becoming
zero.

Subscribers see a `CachePlanned` event carrying the mechanism, the mark count, and the
estimated cacheable size, and a `ParameterDropped` event when a policy could not be honored.
Both are content-free: positions and counts, never text.

## Making caching actually work

An implicit-caching provider only helps if your prefix is byte-identical between turns. The
usual mistakes:

- a timestamp or request id in the system prompt
- tools serialized in a different order each time
- context blocks assembled from a set rather than a list

If your `cache_read_tokens` stays at zero while you expect hits, that is where to look.
