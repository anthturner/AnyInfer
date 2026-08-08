---
provider: openai-compat
icon: material/swap-horizontal
---

# OpenAI-compatible

The base dialect for any endpoint speaking `POST /chat/completions`: vLLM, LM Studio, an
externally-run llama-server, a corporate gateway, or OpenAI itself.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: structured output (server-dependent)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: health</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: discovery</span>
</div>

## Setup

```python
client = ai.Client([
    ai.ProviderSettings.of(
        "openai-compat",
        base_url="http://localhost:8000/v1",
        api_key="env://MY_API_KEY",        # optional for keyless local servers
    ),
])
result = client.generate(prompt, target="openai-compat:my-model")
```

`base_url` is required — there is no sensible default for "any server".

Aliases: `openai-compatible`, `oai-compat`.

## Supported

| Behavior | Support |
|---|---|
| Streaming | SSE |
| Structured output | `json_schema` or `json_object`, where the server implements it |
| Tools | Native |
| Usage | When the server reports it |

## Capabilities are unknown by default

AnyInfer cannot know what an arbitrary server supports, so features default to a
conservative set and structured output falls back to prompt injection unless told otherwise.
Client-side validation means you still get a validated result either way.

To declare what your server actually does, register a descriptor with richer
`default_capabilities` — see [writing an adapter](../contributing/writing-an-adapter.md).

## Servers that ignore `stream`

Some endpoints accept `stream: true` and answer with a buffered body anyway. The adapter
detects that and consumes the body rather than paying for a second request, so your consumer
code is unaffected.

## Known divergences

- `max_tokens` vs `max_completion_tokens` — subclasses override this; the base sends
  `max_tokens`.
- `stream_options.include_usage` is not universally implemented. Usage is simply absent when
  a server omits it, never fabricated.
- `response_format` support varies widely between implementations, which is one of the
  reasons validation is always client-side.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/openai-compat.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/openai-compat.md).
