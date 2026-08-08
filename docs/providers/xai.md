---
provider: xai
icon: material/alpha-x-box-outline
---

# xAI (Grok)

An OpenAI-compatible dialect whose distinctive value is **honest cost**: xAI reports the
exact amount billed on every response, and its model listing carries real prices and
context windows.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reasoning</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery (pricing + context)</span>
</div>

## Setup

```python
import anyinfer as ai

client = ai.Client([
    ai.ProviderSettings.of("xai", api_key="env://XAI_API_KEY"),
])

result = client.generate(prompt, target="xai:grok-4.5")
```

`grok:` is accepted as an alias.

## Cost you can trust

Most providers give you token counts and leave the arithmetic to a price table. xAI
returns `cost_in_usd_ticks` — the amount actually billed, including server-side tool
fees and tiered pricing — and AnyInfer adopts it directly:

```python
result = client.generate(prompt, target="xai:grok-4.5")
print(result.usage.cost_usd)   # what you were charged, not an estimate
```

That matters here because several of xAI's billing rules can't be reproduced from
per-token rates: prompts of 200k tokens or more bill **every** token at the higher tier,
web search costs $5 per 1,000 calls, and code execution costs $5 per 1,000 invocations.

## Discovered capabilities

The `language-models` listing reports context windows and per-token prices, so
capabilities arrive with `discovered` provenance rather than catalogued estimates:

```python
for model in client.models("xai"):
    caps = model.capabilities
    if caps and caps.pricing:
        print(model.id, caps.pricing.value.input_per_1m, caps.pricing.provenance)
```

If that endpoint is unavailable, discovery degrades to the plain model listing — ids
only — rather than failing.

## Reasoning

```python
result = client.generate(prompt, target="xai:grok-4.5", reasoning="medium")
```

`minimal` clamps to `low`: only some Grok models accept `none`, and silently disabling
reasoning on a reasoning model would change the answer more than you asked for. Pass
`provider_options={"xai": {"reasoning_effort": "none"}}` to disable it deliberately on a
model that supports it. The `grok-4.20` generation ships as separate `-reasoning` and
`-non-reasoning` model ids instead of taking the parameter.

## A note on the API surface

xAI documents chat completions as **legacy** — new features land on their Responses API
first, and server-side tools (web search, X search, code execution, file search, MCP)
are only available there. This adapter speaks chat completions, which remains fully
supported; the contract snapshot tracks that migration as the primary drift signal.

## The Anthropic-compatible endpoint

xAI also exposes a Messages endpoint:

```python
ai.ProviderSettings.of(
    "anthropic", base_url="https://api.x.ai", api_key="env://XAI_API_KEY"
)
```

Use the native `xai:` provider unless you need Messages-dialect behavior — the reported
cost and discovered pricing above are only wired there.

## See also

<div class="anyinfer-see-also" markdown>

- [Contract snapshot](https://github.com/anthturner/AnyInfer/blob/main/contracts/xai.md)
- [Capabilities and provenance](../concepts/capabilities.md) — why discovered pricing
  outranks the bundled table.

</div>
