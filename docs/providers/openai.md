---
provider: openai
icon: material/cloud-outline
---

# OpenAI

Uses the Responses API, OpenAI's current surface, which exposes reasoning effort and
reasoning-token accounting the older chat-completions shape does not. For the
chat-completions dialect, point [openai-compat](openai-compat.md) at
`https://api.openai.com/v1` instead.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: health</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery</span>
</div>

## Setup

```python
client = ai.Client(
    [
        ai.ProviderSettings.of("openai", api_key="env://OPENAI_API_KEY"),
    ]
)
result = client.generate(prompt, target="openai:gpt-5")
```

## Supported

| Behavior | Support |
|---|---|
| Streaming | Native, typed events |
| Structured output | `json_schema` via `text.format` |
| Tools | Native |
| Reasoning | `reasoning.effort`, plus reasoning-token counts |
| Usage | Input, output, cached, reasoning tokens |
| Cost | Cataloged pricing |

## Reasoning

```python
result = client.generate(prompt, target="openai:gpt-5", reasoning="high")
result.usage.reasoning_tokens
```

Effort levels pass straight through: `minimal`, `low`, `medium`, `high`.

## Embeddings

The dedicated adapter serves `POST /v1/embeddings` through the shared OpenAI-compatible
dialect:

```python
result = client.embed(
    ["first text", "second text"],
    target="openai:text-embedding-3-small",
)
```

Requests larger than the API's 2,048-input ceiling are
[split by the core](../concepts/embeddings.md#batching) and re-assembled in input order.
Requested `dimensions` are forwarded (text-embedding-3 and later). OpenAI's request
schema has no input-intent concept, so passing `input_type` adds a warning to the result
rather than silently doing nothing. There is no reranking endpoint on this API.

## Multimodal inputs

Images and files are projected to Responses API `input_image` and `input_file` content
items. Inline bytes become data URLs; remote URLs stay remote. Audio input is model-specific,
so [capability data](../concepts/capabilities.md) must not be read as a promise that every
OpenAI model accepts it.

## Notes

- System messages become the top-level `instructions` field.
- The output-token parameter is `max_output_tokens`.
- A response truncated by the token cap reports `finish_reason == "length"`.
- Request-level extras such as `store` and `service_tier` pass through the
  [escape hatch](README.md#reaching-provider-specific-parameters):
  `provider_options = {"openai": {"store": False, "service_tier": "flex"}}`.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/openai.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/openai.md).
