---
provider: nebius
icon: material/cloud-search-outline
---

# Nebius Token Factory

Nebius uses the OpenAI chat-completions dialect but exposes a richer model listing. AnyInfer
uses that listing to discover current context windows, quantization, feature support, and
prices instead of shipping a catalog that will age.

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

## Discovered capabilities

```python
for model in client.models("nebius"):
    caps = model.capabilities
    if caps and caps.pricing:
        print(
            model.id,
            caps.context_window.value if caps.context_window else "unknown context",
            caps.pricing.value.input_per_1m,
            caps.pricing.value.output_per_1m,
        )
```

The adapter asks for the verbose model list. Its context, pricing, quantization, and feature
values carry `discovered` provenance. If an endpoint does not support the verbose query, the
adapter falls back to the ordinary listing and returns model ids without inventing metadata.

## Reasoning

Normalized reasoning levels are sent as `reasoning_effort`. Reasoning fragments are surfaced
as `ReasoningDelta` events and remain separate from `Generation.text`:

```python
with client.stream(
    "Solve this carefully.",
    target="nebius:deepseek-ai/DeepSeek-V3",
    reasoning="high",
) as stream:
    for event in stream:
        if isinstance(event, ai.ReasoningDelta):
            inspect_reasoning(event.text)
        elif isinstance(event, ai.TextDelta):
            render_answer(event.text)
```

The upstream API also accepts reasoning levels outside AnyInfer's normalized four-level
scale. Send those explicitly through `provider_options` when you need them.

## Wire contract

For the exact fields this adapter sends and reads, see
[contracts/nebius.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/nebius.md).
