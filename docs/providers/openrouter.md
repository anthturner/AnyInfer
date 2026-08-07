---
provider: openrouter
icon: material/router-network
---

# OpenRouter

An `openai-compat` subclass. Its distinctive value is the model listing: OpenRouter reports
per-model context length **and** per-token pricing, so its costs carry `discovered`
provenance rather than catalogued estimates.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: structured output (model-dependent)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: health</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery (pricing + context)</span>
</div>

## Setup

```python
client = ai.Client([
    ai.ProviderSettings.of(
        "openrouter",
        api_key="env://OPENROUTER_API_KEY",
        options={"http_referer": "https://myapp.example", "x_title": "My App"},
    ),
])
result = client.generate(prompt, target="openrouter:anthropic/claude-sonnet-4.5")
```

Model ids are namespaced `vendor/model`. The attribution headers are optional.

## Discovered capabilities

```python
for model in client.models("openrouter"):
    caps = model.capabilities
    if caps and caps.pricing:
        print(model.id, caps.pricing.value.input_per_1m, caps.pricing.provenance)
```

Prices are parsed with `Decimal`: per-token prices are fractions of a cent, and float error
accumulates quickly across a long run.

Feature flags come from each model's `supported_parameters`. Absence is treated as
unsupported rather than unknown — OpenRouter enumerates what a model accepts, so a missing
entry is meaningful, and claiming more would send requests the upstream provider silently
drops.

## Notes

- Keep-alive comment lines (`: OPENROUTER PROCESSING`) are ignored by the SSE parser.
- A 402 (insufficient credits) is reported distinctly, hinting to add credits or pick a
  free-tier model.
- Upstream routing means the served model may differ from the one requested; the response
  echoes what actually served it.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/openrouter.md](https://github.com/anthturner/anyinfer/blob/main/contracts/openrouter.md).
