---
provider: llama-cpp
icon: material/desktop-tower
---

# llama.cpp

A supervised `llama-server` subprocess speaking the OpenAI-compatible dialect over loopback.
In-process `llama-cpp-python` is not supported: one wire protocol for every engine, crash
isolation, and no GPU-wheel build matrix in the dependency tree.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output (grammar)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: vision with projector</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: health</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: catalog discovery</span>
</div>

## Setup

```python
client = ai.Client(
    [
        ai.ProviderSettings.of(
            "llama-cpp",
            options={
                "posture": "balanced",
                "idle_ttl_s": 900,
            },
        ),
    ]
)

result = client.generate(prompt, target="llama-cpp:qwen2.5-7b-instruct-q4-k-m")
```

The model reference is a **catalog artifact id**, not a file path. That one call resolves
the artifact, downloads and verifies it, tunes a server for your hardware, starts it, and
answers.

Install a pinned runtime with `anyinfer runtime install`, or supply your own `llama-server`
through the `binary` option. With multiple installed runtimes, set `runtime` to `cuda`,
`vulkan`, `metal`, `rocm`, or `cpu`; the default `auto` selects the highest-ranked installed
backend the detected hardware can drive.

Aliases: `llamacpp`, `llama`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `catalog` | client's active catalog | Optional direct-adapter override for artifact resolution. |
| `runtime` | `auto` | Installed backend family to use; `auto` selects the best usable one. |
| `binary` | — | Optional executable override; takes precedence over `runtime`. |
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
| Images | OpenAI-compatible image content when the artifact pins a projector |
| Embeddings | `--embeddings`-started server, genuinely OpenAI-shaped `/v1/embeddings` |

## Vision models and projector companions

A vision artifact is two verified files: the model GGUF and its multimodal projector.
AnyInfer counts both for fit and download admission, fetches both through the normal model
store, starts `llama-server` with `--mmproj`, and advertises `VISION` with catalog
provenance. The bundled Qwen2.5-VL entry includes its pinned projector.

An image request against an artifact without a projector fails before generation instead
of starting a text-only server that would ignore the image. Documents and audio are not
projected through the llama.cpp adapter.

## Structured output

llama.cpp compiles `response_format.json_schema` into a real GBNF grammar. As with
[Ollama](ollama.md), the schema is *also*
[injected into the prompt](../concepts/structured-output.md), because a grammar
constrains form without conveying meaning.

## Tool calling

The tuner always emits `--jinja`. Without it, llama-server cannot apply a model's chat
template and tool calling silently does not work at all.

## Embeddings

`--embeddings` can only be set when llama-server starts — live-verified: an
already-running chat server answers every `/v1/embeddings` call with a 501 asking you to
restart it with the flag, and there is no way to toggle it afterward. So `embed()` never
reuses a chat server's resident process, even for the same GGUF: it starts (or reuses) a
second one, keyed separately, specifically for embedding calls.

```python
result = client.embed(
    ["first text", "second text"],
    target="llama-cpp:nomic-embed-text-v1.5",
)
```

Once started with `--embeddings`, the endpoint is genuinely OpenAI-shaped, and the same
code path every hosted OpenAI-compatible provider uses handles it with no
llama.cpp-specific parsing.

## Supervision

- Servers bind `127.0.0.1`. A non-loopback bind requires `allow_remote_exposure=True`.
- VRAM admission is checked before spawning, so an oversized model is refused with a clear
  message instead of crashing the child process.

Serialized model swaps, readiness blocking, and the idle timer are covered in
[the local subsystem](../concepts/local.md#supervision).

## CPU fallback

VRAM admission control refuses a model that cannot fit, but it also does something quieter:
on a machine where the weights plus KV cache leave no room, the plan offloads **no** layers
and the model is served entirely on the CPU. That is the right call — a slow answer beats no
answer, and it is invisible from the result. So the adapter reports it as a
[runtime diagnostic](../concepts/capabilities.md#runtime-diagnostics):

```python
for note in client.diagnostics("llama-cpp"):
    print(note.code, note.message)
# llama-cpp.cpu-only  qwen3-8b is being served with no layers offloaded, so it runs on
#                     the CPU despite this machine having a cuda accelerator. ...
```

Reported only when an accelerator was actually detected — on a CPU-only machine this is the
plan working, not the plan degrading, and read from the supervisor's own state, so it costs
nothing and never triggers hardware detection on its own.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/llama-cpp.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/llama-cpp.md).
