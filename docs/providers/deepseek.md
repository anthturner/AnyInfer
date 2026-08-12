---
provider: deepseek
icon: material/atom-variant
---

# DeepSeek

An OpenAI-compatible dialect with three deltas that would otherwise cost you silently:
reasoning arrives on its own channel, thinking is on by default, and cache accounting is
automatic and split.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: structured output (JSON mode)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reasoning</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: cache accounting</span>
</div>

## Setup

```python
import anyinfer as ai

client = ai.Client(
    [
        ai.ProviderSettings.of("deepseek", api_key="env://DEEPSEEK_API_KEY"),
    ]
)

result = client.generate(prompt, target="deepseek:deepseek-v4-pro")
```

Two models are served: `deepseek-v4-flash` and `deepseek-v4-pro`. The old
`deepseek-chat` / `deepseek-reasoner` aliases were discontinued in July 2026.

## Reasoning

Thinking is **on by default**. Chain-of-thought streams as `ReasoningDelta` events,
separate from the answer:

```python
with client.stream(prompt, target="deepseek:deepseek-v4-pro") as stream:
    for event in stream:
        if isinstance(event, ai.ReasoningDelta):
            print("[thinking]", event.text, end="")
        elif isinstance(event, ai.TextDelta):
            print(event.text, end="")
```

Requesting an effort level enables thinking explicitly and sets the level. Because
DeepSeek accepts `low`/`high`/`max`, AnyInfer maps `minimal` and `low` to `low`, and
`medium` and `high` to `high`, rather than sending a value the API would rewrite:

```python
result = client.generate(prompt, target="deepseek:deepseek-v4-pro", reasoning="low")
```

To turn thinking **off** — a deliberate behavior change, not an effort setting:

```python
client.generate(
    prompt,
    target="deepseek:deepseek-v4-pro",
    provider_options={"deepseek": {"thinking": {"type": "disabled"}}},
)
```

!!! warning "Sampling is ignored while thinking"

    DeepSeek silently discards `temperature` and `top_p` in thinking mode, which is the
    default. AnyInfer declares both as ignored, so setting one raises a
    `ParameterDropped` telemetry event instead of quietly doing nothing.

## Cache accounting

Context caching is automatic: no opt-in, no cache-control parameters. DeepSeek reports
the split, and cache hits bill at a much lower rate:

```python
result = client.generate(long_prompt, target="deepseek:deepseek-v4-flash")
print(result.usage.input_tokens)  # hits + misses
print(result.usage.cache_read_tokens)  # the part that was cheap
```

!!! note "Cost is a ceiling here"

    The bundled pricing table records the standard (cache-miss) rate, so
    `usage.cost_usd` overstates spend on cache-heavy workloads. Supply
    `capability_overrides` if you need the blended rate.

## The Anthropic-compatible endpoint

DeepSeek also exposes a Messages endpoint. Point the Anthropic adapter at it — the
dialect is the same, so nothing else is needed:

```python
ai.ProviderSettings.of(
    "anthropic",
    base_url="https://api.deepseek.com/anthropic",
    api_key="env://DEEPSEEK_API_KEY",
)
```

Use the native `deepseek:` provider unless you specifically need Messages-dialect
behavior — the reasoning channel and cache accounting above are only wired there.

## See also

<div class="anyinfer-see-also" markdown>

- [Contract snapshot](https://github.com/anthturner/AnyInfer/blob/main/contracts/deepseek.md)
- [Presets](presets.md): other OpenAI-compatible providers serving DeepSeek models.

</div>
