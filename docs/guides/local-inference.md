# Run a local model end to end

From a bare machine to a generated answer without installing or operating a separate local
model daemon. AnyInfer fetches a pinned `llama-server` runtime after an explicit install
command, then acquires and supervises the model from the application process.

## 1. See what you have

```bash
anyinfer doctor
```

```
platform          win32 / AMD64
cpu               AMD Ryzen 7 7800X3D 8-Core Processor
cores             8 physical, 16 logical
memory            127.1 GiB
accelerator       cuda: NVIDIA GeForce RTX 4090 (24.0 GiB)

recommended tier  large
                  24 GiB of VRAM comfortably fits the large tier
```

Programmatically:

```python
import anyinfer as ai
from anyinfer import local

profile = local.detect()
recommendation = local.recommend_alias(profile, ai.load_default_catalog())
```

Detection never raises. Anything it could not determine stays `None` on the profile —
with the reason recorded in `profile.warnings` — because a guessed number would silently
mis-tune the server.

## 2. Install a runtime

```console
$ anyinfer runtime list
$ anyinfer runtime install
```

The default is the small CPU, Metal, or Vulkan variant appropriate for this machine. CUDA
is a separate, much larger opt-in download:

```console
$ anyinfer runtime install cuda
```

Archives are pinned and hash-verified. This step is explicit because runtime downloads can
be large; it does not install a background service.

## 3. Configure the provider

```python
client = ai.Client([
    ai.ProviderSettings.of(
        "llama-cpp",
        options={
            "catalog": ai.load_default_catalog(),
            "posture": "balanced",         # conservative | balanced | aggressive
            # "binary": "/custom/llama-server",  # optional override
            "idle_ttl_s": 900,             # unload after 15 idle minutes
        },
    ),
])
```

## 4. Generate

```python
result = client.generate(
    "Explain the CAP theorem.",
    target="llama-cpp:qwen2.5-7b-instruct-q4-k-m",
)
```

That single call resolves the artifact from the catalog, downloads and hash-verifies it,
detects the hardware, tunes a plan, starts llama-server on loopback, waits for readiness,
and answers. Later calls reuse the running server.

## Watch the download

```python
def progress(artifact_id, done, total):
    percent = f"{100 * done / total:.0f}%" if total else f"{done / 1e6:.0f} MB"
    print(f"\r{artifact_id}: {percent}", end="", flush=True)

options = {"catalog": ai.load_default_catalog(), "progress": progress}
```

## Use an alias instead

```python
result = client.generate(prompt, target=recommendation.alias)
```

Now the same code runs a right-sized model on a laptop and on a workstation.

## Postures

| Posture | Memory committed | Concurrency | KV cache |
|---|---|---|---|
| `conservative` | 50% | 1 slot | f16 |
| `balanced` | 65% | 1 slot | f16 |
| `aggressive` | 75% | 2 slots | q8_0 |

The plan explains itself:

```python
plan = local.plan_server(
    profile, local.TuningInputs(parameter_size="7B"), posture="aggressive"
)
print("\n".join(plan.rationale))
```

## Ollama instead

If you already run Ollama, it needs no supervision at all:

```python
client = ai.Client([ai.ProviderSettings.of("ollama")])
result = client.generate(prompt, target="ollama:qwen3:8b")
```

Ollama gives you grammar-enforced structured output and per-phase timings; llama-cpp gives
you control over tuning and the exact model file. Either way it is one target string.

## Troubleshooting

**`could not find llama-server on PATH`** — run `anyinfer runtime install`, install a
llama.cpp build on `PATH`, or pass `options={"binary": "/path/to/llama-server"}`.

**`needs about 40.0 GiB but only 8.0 GiB of VRAM is uncommitted`** — admission control
refused *before* spawning, so nothing crashed. Choose a smaller tier or a more conservative
posture.

**`llama-server exited with code 3 while loading`** — the error includes the server's own
log tail, which usually names the real cause (an incompatible quantization, a corrupt file,
or genuine memory exhaustion).

**A model unloads while you are still reading its output** — it should not: the idle timer
keys on active streams, not on when the last request *arrived*. If you see this, please
report it.

See [the local subsystem](../concepts/local.md) for how the pieces fit together.
