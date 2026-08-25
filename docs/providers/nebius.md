---
provider: nebius
icon: material/cloud-search-outline
---

# Nebius Token Factory

Nebius uses the [OpenAI chat-completions dialect](openai-compat.md) but exposes a richer
model listing. AnyInfer uses that listing to discover current context windows,
quantization, feature support, and prices instead of shipping a catalog that will age.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: structured output (model-dependent)</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: tool calls (model-dependent)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reasoning channel</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery (pricing + context)</span>
</div>

## Setup

```python
import anyinfer as ai

client = ai.Client(
    [
        ai.ProviderSettings.of(
            "nebius",
            api_key="env://NEBIUS_API_KEY",
        ),
    ]
)

result = client.generate(
    "Explain why the sky appears blue.",
    target="nebius:deepseek-ai/DeepSeek-V3",
    reasoning="medium",
)
```

Model ids use the provider's namespaced catalog. A suffix such as `-fast` is part of the
model id and selects a separately priced flavor; AnyInfer does not rewrite it.

## Discovery

The adapter asks for the verbose model list, so `client.models("nebius")` reports each
model's context window, pricing, quantization, and feature flags with
[`discovered` provenance](../concepts/capabilities.md#the-five-provenances). If an
endpoint does not support the verbose query, the adapter falls back to the ordinary
listing and returns model ids without inventing metadata.

## Reasoning

Normalized reasoning levels are sent as `reasoning_effort`. Reasoning fragments are
surfaced as `ReasoningDelta` events on the [event stream](../concepts/events.md) and
remain separate from `Generation.text`. The upstream API also accepts reasoning levels
outside AnyInfer's normalized four-level scale; send those explicitly through
`provider_options` when needed.

## Wire Contract

For the exact fields this adapter sends and reads, see
[contracts/nebius.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/nebius.md).
