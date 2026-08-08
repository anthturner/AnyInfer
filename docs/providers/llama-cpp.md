---
provider: llama-cpp
icon: material/desktop-tower
---

# llama.cpp

A supervised `llama-server` subprocess speaking the OpenAI-compatible dialect over loopback.
In-process `llama-cpp-python` is explicitly not supported: one wire protocol for
every engine, crash isolation, and no GPU-wheel build matrix in the dependency tree.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output (grammar)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: health</span>
<span class="anyinfer-badge anyinfer-badge-no">:material-close: discovery</span>
</div>

## Setup

```python
client = ai.Client([
    ai.ProviderSettings.of(
        "llama-cpp",
        options={
            "catalog": ai.load_default_catalog(),
            "posture": "balanced",
            "idle_ttl_s": 900,
        },
    ),
])

result = client.generate(prompt, target="llama-cpp:qwen2.5-7b-instruct-q4-k-m")
```

The model reference is a **catalog artifact id**, not a file path. That one call resolves
the artifact, downloads and verifies it, tunes a server for your hardware, starts it, and
answers.

Install a pinned runtime with `anyinfer runtime install`, or supply your own `llama-server`
through the `binary` option. AnyInfer fetches runtimes and weights on demand rather than
embedding them in the wheel, and verifies catalog-managed downloads before use.

Aliases: `llamacpp`, `llama`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `catalog` | — | Required. Resolves artifact ids to pinned downloads. |
| `binary` | `llama-server` | Optional executable override; otherwise the best installed AnyInfer runtime is selected. |
| `model_dir` | platform cache | Where GGUF files are stored. |
| `posture` | `balanced` | `conservative`, `balanced`, or `aggressive`. |
| `hardware` | detected | A pre-detected profile, to skip re-probing. |
| `idle_ttl_s` | 900 | Unload after this long with no active streams. |
| `max_resident` | 1 | Concurrent servers before eviction. |
| `auto_download` | `True` | Fetch a missing artifact rather than failing. |
| `allow_remote_exposure` | `False` | Bind a non-loopback address. |
| `progress` | — | Download progress callback. |

The typed form of this table, for programmatic construction:

::: anyinfer.providers.llama_cpp.LlamaCppOptions

## Supported

| Behavior | Support |
|---|---|
| Streaming | Native SSE |
| Structured output | **Grammar (GBNF)**, compiled from your schema |
| Tools | Native, via `--jinja` |
| Usage | Input and output tokens |
| Cost | Free — a genuine zero, not an unknown |

## Structured output

llama.cpp compiles `response_format.json_schema` into a real GBNF grammar. As with Ollama,
the schema is *also* injected into the prompt, because a grammar constrains form without
conveying meaning.

## Tool calling needs `--jinja`

The tuner always emits `--jinja`. Without it, llama-server cannot apply a model's chat
template and tool calling silently does not work at all.

## Supervision

- Servers bind `127.0.0.1`. A non-loopback bind requires `allow_remote_exposure=True`.
- Model swaps are serialized — two unloaded models never race for the same VRAM.
- Requests block until the server is ready rather than receiving a 503 mid-load.
- VRAM admission is checked before spawning, so an oversized model is refused with a clear
  message instead of crashing the child process.
- The idle timer keys on active streams, so a long generation is never mistaken for idle.

See [the local subsystem](../concepts/local.md).

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/llama-cpp.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/llama-cpp.md).
