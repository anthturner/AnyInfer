---
provider: xai
icon: material/alpha-x-box-outline
---

# xAI (Grok)

An [OpenAI-compatible](openai-compat.md) dialect whose distinctive value is reported
cost: xAI reports the exact amount billed on every response, and its model listing
carries real prices and context windows.

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

client = ai.Client(
    [
        ai.ProviderSettings.of("xai", api_key="env://XAI_API_KEY"),
    ]
)

result = client.generate(prompt, target="xai:grok-4.5")
```

`grok:` is accepted as an alias.

## Exact Cost

Most providers report token counts and leave the arithmetic to a price table. xAI
returns `cost_in_usd_ticks`: the amount actually billed, including server-side tool
fees and tiered pricing, and AnyInfer adopts it directly for
[cost accounting](../concepts/cost.md):

```python
result = client.generate(prompt, target="xai:grok-4.5")
print(result.usage.cost_usd)  # what you were charged, not an estimate
```

That matters here because several of xAI's billing rules can't be reproduced from
per-token rates: prompts of 200k tokens or more bill **every** token at the higher tier,
web search costs $5 per 1,000 calls, and code execution costs $5 per 1,000 invocations.

## Discovery

The `language-models` listing reports context windows and per-token prices, so
capabilities arrive with
[`discovered` provenance](../concepts/capabilities.md#the-five-provenances) rather than
cataloged estimates:

```python
for model in client.models("xai"):
    caps = model.capabilities
    if caps and caps.pricing:
        print(model.id, caps.pricing.value.input_per_1m, caps.pricing.provenance)
```

If that endpoint is unavailable, discovery degrades to the plain model listing (ids
only) rather than failing.

## Reasoning

```python
result = client.generate(prompt, target="xai:grok-4.5", reasoning="medium")
```

`minimal` clamps to `low`: only some Grok models accept `none`, and silently disabling
reasoning on a reasoning model would change the answer more than was asked for. Pass
`provider_options={"xai": {"reasoning_effort": "none"}}` to disable it deliberately on a
model that supports it. The `grok-4.20` generation ships as separate `-reasoning` and
`-non-reasoning` model ids instead of taking the parameter.

## The Anthropic-Compatible Endpoint

xAI also exposes a Messages endpoint at `https://api.x.ai`, which the Anthropic adapter
serves through a base-URL override; see
[pointing that adapter elsewhere](anthropic.md#pointing-this-adapter-elsewhere). Use the
native `xai:` provider unless Messages-dialect behavior is needed; the reported cost and
discovered pricing above are only wired there.

## Wire Contract

For the exact request/response fields this adapter depends on, see
[contracts/xai.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/xai.md).

## See Also

<div class="anyinfer-see-also" markdown>

- [Capabilities and provenance](../concepts/capabilities.md): why discovered pricing
  outranks the bundled table.

</div>
