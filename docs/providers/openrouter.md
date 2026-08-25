---
provider: openrouter
icon: material/router-network
---

# OpenRouter

An [`openai-compat`](openai-compat.md) subclass. Its distinctive value is the model
listing: OpenRouter reports per-model context length and per-token pricing, so its
[costs](../concepts/cost.md) carry `discovered` provenance rather than cataloged
estimates.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: structured output (model-dependent)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: health</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery (pricing + context)</span>
</div>

## Setup

```python
client = ai.Client(
    [
        ai.ProviderSettings.of(
            "openrouter",
            api_key="env://OPENROUTER_API_KEY",
            options={"http_referer": "https://myapp.example", "x_title": "My App"},
        ),
    ]
)
result = client.generate(prompt, target="openrouter:anthropic/claude-sonnet-4.5")
```

Model ids are namespaced `vendor/model`. The attribution headers are optional.

## Discovery

The listing's prices are parsed with `Decimal` and arrive with
[`discovered` provenance](../concepts/capabilities.md#the-five-provenances), beating the
bundled table. Feature flags come from each model's `supported_parameters`, where absence
means unsupported: OpenRouter enumerates what a model accepts, so claiming more would
send requests the upstream provider silently drops.

## Notes

- Keep-alive comment lines (`: OPENROUTER PROCESSING`) are ignored by the SSE parser.
- A 402 (insufficient credits) is reported distinctly, hinting to add credits or pick a
  free-tier model.
- Upstream routing means the served model may differ from the one requested; the response
  echoes what actually served it.

## Wire Contract

For the exact request/response fields this adapter depends on, see
[contracts/openrouter.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/openrouter.md).

## See Also

<div class="anyinfer-see-also" markdown>

- [Routing and rate limits](../concepts/routing.md): AnyInfer's routing above OpenRouter's own.
- [Capabilities and provenance](../concepts/capabilities.md): where model facts come from here.

</div>
