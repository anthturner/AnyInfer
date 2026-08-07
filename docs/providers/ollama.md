---
provider: ollama
icon: material/desktop-tower
---

# Ollama

Uses Ollama's **native** `/api/chat` API, not its `/v1` OpenAI-compatibility layer.

That choice is deliberate. The native API carries grammar-enforced structured output,
per-phase nanosecond timings, `keep_alive` session retention, and reasoning via `think` —
and the `/v1` layer *silently discards* parameters it does not implement, which is exactly
the failure mode AnyInfer exists to eliminate.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output (grammar)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: health</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery</span>
</div>

## Setup

```python
client = ai.Client([ai.ProviderSettings.of("ollama")])
result = client.generate(prompt, target="ollama:qwen3:8b")
```

Defaults to `http://127.0.0.1:11434`. A bare hostname expands automatically, so
`base_url="myserver"` becomes `http://myserver:11434`.

## Supported

| Behavior | Support |
|---|---|
| Streaming | Native NDJSON |
| Structured output | **Grammar-enforced** via `format` |
| Tools | Native |
| Reasoning | `think`, with effort levels |
| Usage | Input and output tokens |
| Phase timings | Model load, prefill, decode |
| Sessions | `keep_alive` |

## Model names contain colons

`"ollama:qwen3:8b"` is the provider `ollama` and the model `qwen3:8b` — targets split on the
first colon only.

## Structured output

Ollama compiles your schema to a decoding grammar. Two consequences AnyInfer handles:

- Grammar-hostile keywords (`minLength`, `maxLength`, huge `minItems`/`maxItems`) are
  stripped **for the wire only**; your original schema still validates the response.
- The schema is *also* injected into the prompt. A grammar guarantees well-formed JSON, not
  meaningful JSON — a model never shown the schema emits schema-shaped nonsense.

## Phase timings

```python
result.timing.phases
# {"model_load_ms": 300.0, "prefill_ms": 200.0,
#  "decode_ms": 1000.0, "provider_total_ms": 1500.0}
```

A large `model_load_ms` on a first request is the model being read from disk.

## Provider options

```python
provider_options={"ollama": {"keep_alive": "10m", "num_ctx": 8192, "num_gpu": 99}}
```

## Notes

- A missing model produces `ModelNotFoundError` hinting `ollama pull <model>`.
- Usage arrives only on the terminal object; the core synthesizes a `UsageUpdate` event so
  streaming consumers see it exactly as they would from any other provider.
- `/api/ps` exposes VRAM residency, which is how GPU spill is detected.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/ollama.md](https://github.com/anthturner/anyinfer/blob/main/contracts/ollama.md).
