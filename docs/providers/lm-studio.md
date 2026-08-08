---
provider: lm-studio
icon: material/laptop
---

# LM Studio

LM Studio's local server, with **native model discovery**. Generation uses its
OpenAI-compatible endpoint — that dialect is shared and well understood — but discovery
uses the native API, because a local engine's model list is inventory, not a catalog.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery (context, quantization, residency)</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: health</span>
</div>

## Setup

```python
import anyinfer as ai

client = ai.Client([ai.ProviderSettings.of("lm-studio")])

result = client.generate(prompt, target="lm-studio:qwen3-8b")
```

Defaults to `http://127.0.0.1:1234/v1`, LM Studio's conventional address. A bare hostname
expands to that port, so a server on another machine needs only its name:

```python
ai.ProviderSettings.of("lm-studio", base_url="gpu-box")   # http://gpu-box:1234
```

An API token is only needed when you have enabled LM Studio's authentication.
`lmstudio:` is an accepted alias.

## Why the native API for discovery

The compatibility endpoint lists model ids. The native one lists what actually matters for
a local engine:

```python
for model in client.models("lm-studio"):
    caps = model.capabilities
    print(model.id, caps.context_window.value, caps.local.quantization)
    # qwen3-8b 32768 Q4_K_M
```

Context length, quantization, artifact size, tool-use and reasoning support — all with
`discovered` provenance, because the server reported them rather than a table guessing.
Embedding models are filtered out; they are not chat models.

Older LM Studio builds have no native API. A 404 there degrades to the OpenAI listing —
ids alone — rather than failing.

## Residency is visible

On a local engine the difference between a fast request and a thirty-second wait is
whether the model is already loaded. Health says so:

```python
health = client.health("lm-studio")
print(health.detail)   # "loaded: qwen3-8b"  or  "no model loaded; the first request will load one"
```

And the adapter exposes residency directly, the same way the [Ollama](ollama.md) one does:

```python
adapter = await client._pool.get("lm-studio")   # or use health() above
loaded = await adapter.loaded_models()          # {"qwen3-8b": 1}
```

## Reasoning

LM Studio names reasoning levels:

```python
result = client.generate(prompt, target="lm-studio:qwen3-8b", reasoning="medium")
```

`minimal` maps to the server's `low` rather than `off` — disabling reasoning changes the
answer more than reducing it does. Pass `provider_options={"lm-studio": {"reasoning":
"off"}}` to turn it off deliberately.

## Model management

This adapter *reads* inventory but does not manage it: loading, unloading, and downloading
stay in LM Studio's own UI and CLI (`lms load`, `lms unload`). Requests load a model on
demand as usual.

For an engine AnyInfer supervises end to end — downloading artifacts, tuning for your
hardware, and managing the server process — see [llama.cpp](llama-cpp.md).

## Other local engines

Running something else? [vLLM, SGLang, KoboldCpp, Jan, GPT4All, text-generation-webui, and
TabbyAPI](presets.md#local-engines) are all preconfigured presets, and any
OpenAI-compatible server works through [`openai-compat`](openai-compat.md).

## See also

<div class="anyinfer-see-also" markdown>

- [Contract snapshot](https://github.com/anthturner/AnyInfer/blob/main/contracts/lm-studio.md)
- [Ollama](ollama.md) — the other local engine with native discovery.
- [The local subsystem](../concepts/local.md) — hardware detection and supervision.

</div>
