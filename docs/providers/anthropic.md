---
provider: anthropic
icon: material/cloud-outline
---

# Anthropic

The Messages API over raw `httpx2`. Registered as `anthropic`, with the alias `claude`.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output (emulated)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: health</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery</span>
</div>

## Setup

```python
client = ai.Client(
    [
        ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY"),
    ]
)
result = client.generate(prompt, target="anthropic:claude-sonnet-4-5")
```

No extra required.

## Supported

| Behavior | Support |
|---|---|
| Streaming | Native, typed SSE events |
| Structured output | Emulated as a forced tool call |
| Tools | Native |
| Reasoning | Extended thinking, budgeted in tokens |
| Usage | Input, output, plus cache read/write |
| Cost | Catalogued pricing |

## Thinking

Reasoning effort maps to a thinking **budget**, because Anthropic budgets in tokens rather
than naming levels:

| Effort | Wire form |
|---|---|
| `minimal` | `{"type": "disabled"}` |
| `low` | 1024 tokens |
| `medium` | 4096 tokens |
| `high` | 16384 tokens |

Thinking arrives as `ReasoningDelta` events. It **starts the first-token clock** — the model
is working and the user sees activity, but is excluded from the answer text.

## Structured output

Anthropic has no `response_format` field, so a schema becomes a single forced tool call,
which the API does constrain. You still get a normal validated `result.structured`; the
emulation is invisible except in `structured_mechanism`.

## Notes

- System messages become the top-level `system` field.
- `max_tokens` is **required** by the API; AnyInfer sends 4096 when you set none rather than
  letting the request fail with a 400.
- Tool results ride on a *user* turn in this dialect, not a `tool` role.
- Model listing is cursor-paginated, and pagination is followed automatically.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/anthropic.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/anthropic.md).

## Multimodal inputs

Images and PDF documents accept inline bytes or provider-fetchable URLs. The adapter emits
native image/document content blocks. Audio input is not part of this Messages projection
and fails explicitly.
