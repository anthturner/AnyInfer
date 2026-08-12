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
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: embeddings</span>
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

## GPU spill is reported, not left to guesswork

The slowest failure Ollama has is not a failure. A model that no longer fits in VRAM
alongside whatever else the GPU is holding is loaded anyway, with the overflow served from
system memory — the request succeeds, the answer is correct, and it takes an order of
magnitude longer than the same model took yesterday. The wire says nothing about it.

`/api/ps` reports how much of each resident model is actually in VRAM, so the adapter reads
it and says so:

```python
for note in client.diagnostics("ollama"):
    print(note.code, note.message)
# ollama.gpu-spill  qwen3:8b is only 45% resident in VRAM; the rest runs on the CPU,
#                   which is far slower. Free GPU memory, or choose a smaller model
#                   or quantization.
```

The same text lands on `result.warnings` for any request that hit it, and as a
`ProviderDiagnostic` event. Costs nothing: `/api/ps` is a local read, never a generation.
A model within 5% of full residency is not reported — Ollama's own sizes wobble by a few
megabytes, and a warning on every healthy load is one nobody reads.

## Embeddings

Ollama's native `POST /api/embed` is a batch-capable embedding endpoint, distinct from the
older deprecated `POST /api/embeddings` (singular-input) route this adapter does not speak.

```python
result = client.embed(["Why is the sky blue?", "Why is the grass green?"], target="ollama:nomic-embed-text")
print(result.space.dimensions, len(result.vectors))
```

Batch input is native — every text in one call is sent as one array, not simulated with
repeated requests. Requested `dimensions` are forwarded when the model supports native
dimensionality reduction. There is no reranking support for this provider; Ollama documents
no native rerank endpoint.

## Provider options

```python
provider_options = {"ollama": {"keep_alive": "10m", "num_ctx": 8192, "num_gpu": 99}}
```

## Notes

- A missing model produces `ModelNotFoundError` hinting `ollama pull <model>`.
- Usage arrives only on the terminal object; the core synthesizes a `UsageUpdate` event so
  streaming consumers see it exactly as they would from any other provider.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/ollama.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/ollama.md).

## Multimodal inputs

Vision-capable models receive inline images through the native message `images` field.
Remote image URLs, documents, and audio are refused rather than silently dropped.
