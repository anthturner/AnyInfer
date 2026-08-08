---
provider: openai
icon: material/cloud-outline
---

# OpenAI

Uses the **Responses API**, not chat completions. It is OpenAI's current surface and exposes
reasoning effort and reasoning-token accounting the older shape does not.

Want the chat-completions dialect instead? Point [openai-compat](openai-compat.md) at
`https://api.openai.com/v1`.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: health</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery</span>
</div>

## Setup

```python
client = ai.Client([
    ai.ProviderSettings.of("openai", api_key="env://OPENAI_API_KEY"),
])
result = client.generate(prompt, target="openai:gpt-5")
```

No extra required — this is raw `httpx2`.

## Supported

| Behavior | Support |
|---|---|
| Streaming | Native, typed events |
| Structured output | `json_schema` via `text.format` |
| Tools | Native |
| Reasoning | `reasoning.effort`, plus reasoning-token counts |
| Usage | Input, output, cached, reasoning tokens |
| Cost | Catalogued pricing |

## Reasoning

```python
result = client.generate(prompt, target="openai:gpt-5", reasoning="high")
result.usage.reasoning_tokens
```

Effort levels pass straight through: `minimal`, `low`, `medium`, `high`.

## Notes

- System messages become the top-level `instructions` field.
- The output-token parameter is `max_output_tokens`.
- A response truncated by the token cap reports `finish_reason == "length"`.

## Provider options

```python
provider_options={"openai": {"store": False, "service_tier": "flex"}}
```

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/openai.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/openai.md).
