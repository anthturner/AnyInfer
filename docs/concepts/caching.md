# Prompt caching

Most providers can hold on to a prefix of your prompt and charge less the next time they
see it. What "hold on to it" means differs: some want to be told exactly where the
reusable part ends, others work it out themselves and want you not to disturb it.
AnyInfer treats that difference the way it treats [structured output](structured-output.md):
you state an intent — cache what is worth caching — and the core picks the strongest
mechanism the target offers, reporting when a weaker one is all that is available.

!!! warning "This is not a response cache"

    Prompt caching caches the prompt you send, on the provider's side, for the
    provider's retention window. It never skips a call, never reuses an answer, and
    never makes a repeated question free. AnyInfer stores nothing.

## It is off unless you ask

```python
result = client.generate(prompt, target="anthropic:claude-sonnet-4-5")  # no caching
result = client.generate(prompt, target="...", cache=ai.CachePolicy())  # caching
```

Caching changes what a provider bills you and how long it keeps a copy of your prompt,
and neither is a decision the library makes on your behalf. Set the policy once on the
client (`ai.Client(providers, cache=ai.CachePolicy())`) or in the
[shared configuration file](../reference/configuration.md), where the CLI and sidecar
pick it up too.

## The two mechanisms

**Explicit** — the provider accepts per-segment marks. AnyInfer decides which segments
are worth marking, largest first, bounded by the provider's own ceiling; the adapter
spells each mark in that provider's wire format.
[Anthropic](../providers/anthropic.md) works this way.

**Implicit** — the provider caches a stable prefix on its own. There is nothing to send,
so AnyInfer's job is to leave your prefix undisturbed and to tell you when your own
request is defeating it. [OpenAI](../providers/openai.md) and
[DeepSeek](../providers/deepseek.md) work this way.

When a target offers neither, the policy is reported as dropped via a
[`ParameterDropped` event](telemetry.md) rather than silently ignored.

## What gets marked

Three kinds of segment, in the order they sit on the wire:

| Segment | Why it is a good candidate |
|---|---|
| Tool declarations | Identical on every turn of a conversation, and often large |
| The system block | Stable by construction |
| The conversation prefix | Everything before the current turn; grows as the chat does |

Segments smaller than the provider's floor are skipped: below the floor a mark is billed
as a cache *write* that no later read ever pays back. You can narrow what is eligible:

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

`cache_mechanism` is what was asked for; the usage figures are what the provider
reported. [Cost](cost.md) is computed only from the reported numbers — an intention is
never billed as an outcome — and when a provider does not report cache accounting, the
figures stay `None` rather than becoming zero.

Subscribers see a `CachePlanned` [telemetry event](telemetry.md) carrying the mechanism,
the mark count, and the estimated cacheable size. Both events are content-free:
positions and counts, never text.

## Making caching actually work

An implicit-caching provider only helps if your prefix is byte-identical between turns.
The usual mistakes:

- a timestamp or request id in the system prompt
- tools serialized in a different order each time
- context blocks assembled from a set rather than a list

If your `cache_read_tokens` stays at zero while you expect hits, that is where to look.
[Context reduction](context-reduction.md) renders in path order by default for exactly
this reason.

!!! tip "Key takeaways"
    - Caching is opt-in, and a policy on a target that supports neither mechanism is
      reported as dropped, never silently ignored.
    - Intent and outcome are separate fields: `cache_mechanism` says what was planned,
      `usage.cache_read_tokens` says what the provider actually served.
    - Marks below the provider's minimum segment size cost money instead of saving it,
      so AnyInfer skips them.
    - Implicit caching lives or dies on a byte-identical prefix; look for timestamps and
      unstable serialization order when hits stay at zero.

## See also

<div class="anyinfer-see-also" markdown>

- [Cost and spending](cost.md): how cache reads show up in the bill.
- [Context reduction](context-reduction.md): stable rendering that keeps prefixes
  identical.
- [Telemetry](telemetry.md): `CachePlanned` and `ParameterDropped` events.

</div>
